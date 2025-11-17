from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import base64
import logging

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN
from .coordinators import EufyTuyaDataUpdateCoordinator
from .mixins import CoordinatorTuyaDeviceUniqueIDMixin

_LOGGER = logging.getLogger(__name__)


def decode_varint(data: bytes, start_pos: int) -> tuple[int, int]:
    """Decode Protocol Buffer varint format.
    
    Returns:
        tuple: (decoded_value, next_position)
    """
    value = 0
    shift = 0
    pos = start_pos
    
    while pos < len(data):
        byte = data[pos]
        value |= (byte & 0x7F) << shift
        pos += 1
        if not (byte & 0x80):  # MSB is 0, so this is the last byte
            break
        shift += 7
    
    return value, pos


def parse_dps167_statistics(dps167_value: str) -> dict[str, int | None]:
    """Parse statistics from DPS 167.
    
    Based on detailed analysis of S1 Pro data:
    - Total count: Last field (varint, can be 1 or 2 bytes)
    - Total area: 2-byte varint at fixed position 14-15
    - Total time: Not yet identified in DPS 167
    
    Args:
        dps167_value: Base64-encoded DPS 167 value
        
    Returns:
        dict with keys: total_count, total_area, total_time_mins
    """
    stats = {
        "total_count": None,
        "total_area": None,
        "total_time_mins": None,
    }
    
    try:
        # Decode base64
        data = base64.b64decode(dps167_value)
        
        if len(data) == 0:
            return stats
        
        # 1. Total count is in the last field as varint
        # The last field has tag 0x18 (field #3, wire_type=0)
        # It can be 1 byte (0-127) or 2+ bytes (128+)
        
        # Find the last field by looking for tag 0x18 from the end
        if len(data) >= 2 and data[-2] == 0x18:
            # Tag found, next byte is the value (1-byte varint)
            stats["total_count"] = data[-1]
        elif len(data) >= 3 and data[-3] == 0x18:
            # Tag found, next 2 bytes are the value (2-byte varint)
            byte1 = data[-2]
            byte2 = data[-1]
            if byte1 & 0x80:  # MSB set = multi-byte varint
                stats["total_count"] = (byte1 & 0x7F) + (byte2 << 7)
            else:
                # Single byte value
                stats["total_count"] = byte1
        elif len(data) >= 4 and data[-4] == 0x18:
            # Tag found, next 3 bytes are the value (3-byte varint, for 16384+)
            byte1 = data[-3]
            byte2 = data[-2]
            byte3 = data[-1]
            if (byte1 & 0x80) and (byte2 & 0x80):
                stats["total_count"] = (byte1 & 0x7F) + ((byte2 & 0x7F) << 7) + (byte3 << 14)
            elif byte1 & 0x80:
                # 2-byte varint
                stats["total_count"] = (byte1 & 0x7F) + (byte2 << 7)
            else:
                # Single byte
                stats["total_count"] = byte1
        
        # 2. Total area is at fixed position 14-15 as 2-byte varint
        # Confirmed positions for data length 18-19 bytes
        if len(data) >= 16:
            byte1 = data[14]
            byte2 = data[15]
            
            # Decode 2-byte varint
            if byte1 & 0x80:  # MSB set = multi-byte varint
                area = (byte1 & 0x7F) + (byte2 << 7)
                stats["total_area"] = area
            else:
                # Single byte value (unlikely for area, but handle it)
                stats["total_area"] = byte1
        
        # 3. Total time: not yet reliably identified
                
    except Exception as e:
        _LOGGER.debug(f"Error parsing DPS 167: {e}")
    
    return stats


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    discovered_devices = hass.data[DOMAIN][config_entry.entry_id][CONF_DISCOVERED_DEVICES]

    devices = []

    for device_id, props in discovered_devices.items():
        coordinator = props[CONF_COORDINATOR]
        
        # Always add battery sensor (S1 Pro uses DPS 8)
        devices.append(BatteryPercentageSensor(coordinator=coordinator))
        
        # Add running status sensor (DPS 153 with DPS 2 fallback)
        devices.append(
            RunningStatusSensor(
                coordinator=coordinator,
            )
        )
        
        # Add statistics sensors (from DPS 167)
        devices.append(TotalCleaningCountSensor(coordinator=coordinator))
        devices.append(TotalCleaningAreaSensor(coordinator=coordinator))
        # TODO: Uncomment when time data position is identified
        # devices.append(TotalCleaningTimeSensor(coordinator=coordinator))

    if devices:
        return async_add_devices(devices)


class BaseDPSensorEntity(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
    
    def __init__(
        self,
        *args,
        name: str,
        icon: str | None,
        dps_id: str,
        coordinator: EufyTuyaDataUpdateCoordinator,
        **kwargs,
    ):
        self._attr_name = name
        self._attr_icon = icon
        self.dps_id = dps_id
        super().__init__(*args, coordinator=coordinator, **kwargs)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and self.dps_id in self.coordinator.data

    @property
    def native_value(self):
        if self.coordinator.data:
            value = self.coordinator.data.get(self.dps_id)
            if converter := getattr(self, "parse_value", None):
                try:
                    return converter(value)
                except Exception:
                    return value
            return value
        return None


class BatteryPercentageSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_name = "Battery"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and ("8" in self.coordinator.data or "163" in self.coordinator.data)

    @property
    def icon(self) -> str:
        # Check if charging based on DPS 5 (mode)
        mode = (self.coordinator.data or {}).get("5", "")
        charging = mode in ["charge", "docked", "Charging"]
        
        return icon_for_battery_level(self.native_value, charging=charging)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            # S1 Pro uses DPS 8 for battery
            value = self.coordinator.data.get("8")
            if value is not None:
                try:
                    battery = int(value)
                    if 0 <= battery <= 100:
                        return battery
                except (ValueError, TypeError):
                    pass
            
            # Fallback to DPS 163
            value = self.coordinator.data.get("163")
            if value is not None:
                try:
                    battery = int(value)
                    if 0 <= battery <= 100:
                        return battery
                except (ValueError, TypeError):
                    pass
        return None



class RunningStatusSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
    """Sensor that shows running status based on DPS 153 (S1 Pro actual state)."""
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Running Status"
    _attr_icon = "mdi:play-pause"
    
    # S1 Pro status definitions (same as vacuum.py)
    S1_PRO_STATUS = {
        "CLEANING": "BgoAEAUyAA==",     # 掃除中
        "PAUSED": "CAoAEAUyAggB",      # 一時停止
        "RETURNING": "BBAHQgA=",        # 帰還中
    }
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Check if we have coordinator data and either DPS 153 (preferred) or DPS 2 (fallback)
        return self.coordinator.data is not None and ("153" in self.coordinator.data or "2" in self.coordinator.data)
    
    @property
    def native_value(self) -> str:
        """Return the running status based on DPS 153."""
        if not self.coordinator.data:
            return "Unknown"
        
        # Check DPS 153 first (most reliable for S1 Pro)
        dps153 = self.coordinator.data.get("153", "")
        
        # If vacuum is cleaning, paused, or returning, it's "Running"
        if dps153 in self.S1_PRO_STATUS.values():
            return "Running"
        
        # If DPS 153 has any value other than the known states, it's docked/stopped
        if dps153:
            return "Stopped"
        
        # Fallback to DPS 2 if DPS 153 is not available
        dps2 = self.coordinator.data.get("2")
        if dps2 is True:
            return "Running"
        elif dps2 is False:
            return "Stopped"
        
        return "Unknown"


class TotalCleaningCountSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
    """Sensor for total number of cleaning sessions from DPS 167."""
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Total Cleaning Count"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and "167" in self.coordinator.data
    
    @property
    def native_value(self) -> int | None:
        """Return the total cleaning count."""
        if not self.coordinator.data:
            return None
        
        dps167 = self.coordinator.data.get("167", "")
        if not dps167:
            return None
        
        stats = parse_dps167_statistics(dps167)
        return stats.get("total_count")


class TotalCleaningAreaSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
    """Sensor for total cleaned area from DPS 167."""
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Total Cleaning Area"
    _attr_icon = "mdi:texture-box"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and "167" in self.coordinator.data
    
    @property
    def native_value(self) -> int | None:
        """Return the total cleaning area in square meters."""
        if not self.coordinator.data:
            return None
        
        dps167 = self.coordinator.data.get("167", "")
        if not dps167:
            return None
        
        stats = parse_dps167_statistics(dps167)
        return stats.get("total_area")


# TODO: Uncomment when time data position is identified in DPS 167 or DPS 168
# class TotalCleaningTimeSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SensorEntity):
#     """Sensor for total cleaning time from DPS 167.
#     
#     NOTE: The exact position of time data has not been reliably identified yet.
#     Current investigation shows:
#     - Not found as simple varint at any fixed position
#     - May be split into hours/minutes components
#     - May be stored in seconds (requires 3-byte varint)
#     - May be in DPS 168 instead of DPS 167
#     
#     TODO: Analyze logs with larger time differences to identify the pattern.
#     """
#     
#     _attr_entity_category = EntityCategory.DIAGNOSTIC
#     _attr_name = "Total Cleaning Time"
#     _attr_icon = "mdi:clock-outline"
#     _attr_device_class = SensorDeviceClass.DURATION
#     _attr_native_unit_of_measurement = UnitOfTime.MINUTES
#     _attr_state_class = SensorStateClass.TOTAL_INCREASING
#     
#     @property
#     def available(self) -> bool:
#         """Return if entity is available."""
#         return self.coordinator.data is not None and "167" in self.coordinator.data
#     
#     @property
#     def native_value(self) -> int | None:
#         """Return the total cleaning time in minutes."""
#         if not self.coordinator.data:
#             return None
#         
#         dps167 = self.coordinator.data.get("167", "")
#         if not dps167:
#             return None
#         
#         stats = parse_dps167_statistics(dps167)
#         return stats.get("total_time_mins")
