from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import base64
import logging

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN
from .coordinators import EufyTuyaDataUpdateCoordinator
from .mixins import CoordinatorTuyaDeviceUniqueIDMixin
# vacuum.pyから状態判定関数と説明文をインポート
from .vacuum import decode_dps153_to_state, SUBSTATUS_DESCRIPTIONS, RobovacState

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
    """Parse cumulative cleaning statistics from DPS 167.

    DPS 167 is a length-prefixed protobuf with two top-level submessages:
        field 1 (sub): current/last session info (time_s, area)
        field 2 (sub): cumulative totals (time_s, area, count)

    Verified on FW 7.0.168 against the Eufy app's "掃除履歴" header
    (count / area / total time) — see ``feature/room-cleaning`` branch
    notes for the raw byte walkthrough.
    """
    stats: dict[str, int | None] = {
        "total_count": None,
        "total_area": None,
        "total_time_mins": None,
    }

    try:
        data = base64.b64decode(dps167_value)
        if len(data) < 2:
            return stats

        # Strip the 1-byte length prefix.
        body = data[1:]
        fields = _parse_protobuf_fields(body)

        cumulative = fields.get(2)
        if cumulative is None:
            return stats

        cumulative_fields = _parse_protobuf_fields(cumulative)
        total_time_s = cumulative_fields.get(1)
        if isinstance(total_time_s, int):
            stats["total_time_mins"] = total_time_s // 60
        if isinstance(cumulative_fields.get(2), int):
            stats["total_area"] = cumulative_fields[2]
        if isinstance(cumulative_fields.get(3), int):
            stats["total_count"] = cumulative_fields[3]
    except Exception as e:
        _LOGGER.debug("Error parsing DPS 167: %s", e)

    return stats


def _parse_protobuf_fields(data: bytes) -> dict[int, int | bytes]:
    """Walk a protobuf message and return {field_number: value}.

    Only varint (wire type 0) and length-delimited (wire type 2) fields are
    decoded — that's all DPS 167/168 use. Repeated fields keep the last
    value, which is sufficient for the singular fields we care about.
    """
    fields: dict[int, int | bytes] = {}
    pos = 0
    while pos < len(data):
        tag, pos = decode_varint(data, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
            value, pos = decode_varint(data, pos)
            fields[field_number] = value
        elif wire_type == 2:
            length, pos = decode_varint(data, pos)
            fields[field_number] = data[pos:pos + length]
            pos += length
        else:
            # Unknown wire type — bail out rather than risk misalignment.
            break
    return fields


# DPS 168 carries a ConsumableResponse protobuf (Eufy/Tuya cloud-side proto):
#     ConsumableResponse { ConsumableRuntime runtime = 1 }
#     ConsumableRuntime { Duration <component> = N; ... }
#     Duration { uint32 duration = 22 }   # observed unit on S1 Pro: minutes
#
# The standard cloud .proto numbers components 1-7, 10, 11. S1 Pro renumbers
# scrape (4 -> 41) and dirty_watertank (10 -> 43); everything else matches.
# Field-to-component mapping was verified empirically against the Eufy app's
# Maintenance screen: every value matches within rounding of the integer hours
# the app shows.
#
# Each entry: (field, attribute_key, display_name, max_lifetime_hours, icon).
# The S1 Pro app does not display dustbag (field 7 — empty in dumps), so we
# don't expose a sensor for it.
CONSUMABLE_ITEMS: list[tuple[int, str, str, int, str]] = [
    (1,  "side_brush",        "Side Brush Remaining",                180, "mdi:broom"),
    (2,  "rolling_brush",     "Rolling Brush Remaining",             180, "mdi:broom"),
    (3,  "filter_mesh",       "High-Performance Filter Remaining",    60, "mdi:air-filter"),
    (5,  "sensor",            "Sensors Remaining",                   360, "mdi:leak"),
    (6,  "mop",               "Rolling Mop Remaining",                60, "mdi:water-circle"),
    (11, "dirty_waterfilter", "Dirty Water Tank Filter Remaining",   360, "mdi:filter-variant"),
    (41, "scrape",            "Mop Cleaning Tray Remaining",          30, "mdi:tray"),
    (43, "dirty_watertank",   "Dirty Water Tank Remaining",           30, "mdi:water-pump"),
]


def parse_dps168_consumables(dps168_value: str) -> dict[str, int | None]:
    """Parse per-component cumulative usage (in minutes) from DPS 168.

    DPS 168 wraps ``ConsumableResponse`` (see ``proto/cloud/consumable.proto``
    in jeppesens/eufy-clean#126) — a length-prefixed protobuf where field 1 is
    the inner ``ConsumableRuntime`` submessage. Each consumable entry is a
    ``Duration`` submessage with a single varint at field 22 holding the
    component's cumulative usage. Returns ``{attribute_key: usage_minutes}``
    for every consumable we expose; missing fields map to ``None``.
    """
    usage: dict[str, int | None] = {key: None for _, key, *_ in CONSUMABLE_ITEMS}

    try:
        data = base64.b64decode(dps168_value)
        if len(data) < 2:
            return usage

        # Strip the 1-byte length prefix, then drill into runtime (field 1).
        outer = _parse_protobuf_fields(data[1:])
        runtime = outer.get(1)
        if not isinstance(runtime, (bytes, bytearray)):
            return usage

        runtime_fields = _parse_protobuf_fields(runtime)

        for field_num, key, *_ in CONSUMABLE_ITEMS:
            entry = runtime_fields.get(field_num)
            if not isinstance(entry, (bytes, bytearray)) or len(entry) == 0:
                continue
            entry_fields = _parse_protobuf_fields(entry)
            duration = entry_fields.get(22)
            if isinstance(duration, int):
                usage[key] = duration
    except Exception as e:
        _LOGGER.debug("Error parsing DPS 168: %s", e)

    return usage


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
        devices.append(TotalCleaningTimeSensor(coordinator=coordinator))

        # Add maintenance/consumable remaining-% sensors (from DPS 168)
        for field_num, key, name, max_hours, icon in CONSUMABLE_ITEMS:
            devices.append(
                ConsumableRemainingSensor(
                    coordinator=coordinator,
                    consumable_key=key,
                    name=name,
                    max_hours=max_hours,
                    icon=icon,
                )
            )

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



class RunningStatusSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor that shows detailed running status based on DPS 153.
    
    RestoreEntity を使用して再起動後もDPSが読めるまで最終値を保持します。
    """
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Running Status"
    _attr_icon = "mdi:robot-vacuum"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._restored_value = None
    
    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            self._restored_value = last_state.state
            _LOGGER.debug("Restored Running Status: %s", self._restored_value)
    
    @property
    def available(self) -> bool:
        """Available if we have live data or a restored value."""
        has_live = self.coordinator.data is not None and ("153" in self.coordinator.data or "2" in self.coordinator.data)
        return has_live or self._restored_value is not None
    
    @property
    def native_value(self) -> str:
        """Return the detailed running status based on DPS 153."""
        if not self.coordinator.data:
            return self._restored_value or "Unknown"
        
        # Check DPS 153 first (most reliable for S1 Pro)
        dps153 = self.coordinator.data.get("153", "")
        
        if dps153:
            # 新しいバイトパターン判定ロジックを使用
            detected_state, substatus = decode_dps153_to_state(dps153)
            
            # サブステータスの説明文を取得
            status_description = SUBSTATUS_DESCRIPTIONS.get(substatus, "Unknown")
            
            _LOGGER.debug(
                f"Running Status: state={detected_state.value}, "
                f"substatus={substatus}, description={status_description}"
            )
            
            return status_description
        
        # Fallback to DPS 2 if DPS 153 is not available
        dps2 = self.coordinator.data.get("2")
        if dps2 is True:
            return "Running"
        elif dps2 is False:
            return "Stopped"
        
        return "Unknown"
    
    @property
    def icon(self) -> str:
        """Return icon based on current state."""
        if not self.coordinator.data:
            return "mdi:robot-vacuum"
        
        dps153 = self.coordinator.data.get("153", "")
        
        if dps153:
            detected_state, substatus = decode_dps153_to_state(dps153)
            
            # 状態に応じたアイコンを返す
            if detected_state == RobovacState.CLEANING:
                return "mdi:robot-vacuum"
            elif detected_state == RobovacState.PAUSED:
                return "mdi:pause-circle"
            elif detected_state == RobovacState.RETURNING:
                return "mdi:home-import-outline"
            elif detected_state == RobovacState.DOCKED:
                # サブステータスに応じたアイコン
                if substatus in ["charging", "fully_charged"]:
                    return "mdi:battery-charging"
                elif substatus == "dust_collecting":
                    return "mdi:delete-empty"
                elif substatus in ["mop_washing", "mop_washing_pre"]:
                    return "mdi:spray-bottle"
                elif substatus == "mop_drying":
                    return "mdi:fan"
                elif substatus == "water_refilling":
                    return "mdi:water"
                else:
                    return "mdi:home"
            elif detected_state == RobovacState.ERROR:
                return "mdi:alert-circle"
        
        return "mdi:robot-vacuum"


class TotalCleaningCountSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for total number of cleaning sessions from DPS 167.
    
    累積値のため RestoreEntity を使用して再起動後も最終値を保持します。
    """
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Total Cleaning Count"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_valid_count = None
    
    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._last_valid_count = int(last_state.state)
                _LOGGER.debug(
                    "Restored Total Cleaning Count: %s", self._last_valid_count
                )
            except (ValueError, TypeError):
                pass
    
    @property
    def available(self) -> bool:
        """Available if we have live data or a restored value."""
        has_live = self.coordinator.data is not None and "167" in self.coordinator.data
        return has_live or self._last_valid_count is not None
    
    @property
    def native_value(self) -> int | None:
        """Return the total cleaning count."""
        if not self.coordinator.data:
            return self._last_valid_count
        
        dps167 = self.coordinator.data.get("167", "")
        if not dps167:
            return self._last_valid_count
        
        stats = parse_dps167_statistics(dps167)
        new_count = stats.get("total_count")
        
        if new_count is None:
            return self._last_valid_count
        
        if self._last_valid_count is None or new_count >= self._last_valid_count:
            self._last_valid_count = new_count
            return new_count
        else:
            return self._last_valid_count


class TotalCleaningAreaSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for total cleaned area from DPS 167.
    
    累積値のため RestoreEntity を使用して再起動後も最終値を保持します。
    """
    
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Total Cleaning Area"
    _attr_icon = "mdi:texture-box"
    _attr_native_unit_of_measurement = "m²"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_valid_area = None
    
    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._last_valid_area = int(last_state.state)
                _LOGGER.debug(
                    "Restored Total Cleaning Area: %s m²", self._last_valid_area
                )
            except (ValueError, TypeError):
                pass
    
    @property
    def available(self) -> bool:
        """Available if we have live data or a restored value."""
        has_live = self.coordinator.data is not None and "167" in self.coordinator.data
        return has_live or self._last_valid_area is not None
    
    @property
    def native_value(self) -> int | None:
        """Return the total cleaning area in square meters."""
        if not self.coordinator.data:
            return self._last_valid_area
        
        dps167 = self.coordinator.data.get("167", "")
        if not dps167:
            return self._last_valid_area
        
        stats = parse_dps167_statistics(dps167)
        new_area = stats.get("total_area")
        
        if new_area is None:
            return self._last_valid_area
        
        if self._last_valid_area is None or new_area >= self._last_valid_area:
            self._last_valid_area = new_area
            return new_area
        else:
            return self._last_valid_area


class TotalCleaningTimeSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, RestoreEntity, SensorEntity):
    """Sensor for total cleaning time from DPS 167.

    累積値のため RestoreEntity を使用して再起動後も最終値を保持します。
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Total Cleaning Time"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_valid_minutes = None

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._last_valid_minutes = int(last_state.state)
                _LOGGER.debug(
                    "Restored Total Cleaning Time: %s min", self._last_valid_minutes
                )
            except (ValueError, TypeError):
                pass

    @property
    def available(self) -> bool:
        """Available if we have live data or a restored value."""
        has_live = self.coordinator.data is not None and "167" in self.coordinator.data
        return has_live or self._last_valid_minutes is not None

    @property
    def native_value(self) -> int | None:
        """Return the total cleaning time in minutes."""
        if not self.coordinator.data:
            return self._last_valid_minutes

        dps167 = self.coordinator.data.get("167", "")
        if not dps167:
            return self._last_valid_minutes

        stats = parse_dps167_statistics(dps167)
        new_minutes = stats.get("total_time_mins")

        if new_minutes is None:
            return self._last_valid_minutes

        if self._last_valid_minutes is None or new_minutes >= self._last_valid_minutes:
            self._last_valid_minutes = new_minutes
            return new_minutes
        else:
            return self._last_valid_minutes


class ConsumableRemainingSensor(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, RestoreEntity, SensorEntity):
    """Per-component remaining-life % sensor backed by DPS 168.

    Mirrors the Eufy app's "Maintenance" screen: ``remaining = max - usage``
    converted to a percentage. DPS 168 publishes the cumulative usage in
    minutes; the per-component lifetime (in hours) is hard-coded from the
    app's display since it is not carried in the DPS payload.

    Uses ``RestoreEntity`` so the value survives restarts before the first
    DPS 168 publish (which does not happen until the device emits a fresh
    consumable update — typically after a cleaning session).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        *,
        coordinator: EufyTuyaDataUpdateCoordinator,
        consumable_key: str,
        name: str,
        max_hours: int,
        icon: str,
    ):
        super().__init__(coordinator=coordinator)
        self._consumable_key = consumable_key
        self._max_minutes = max_hours * 60
        self._attr_name = name
        self._attr_icon = icon
        self._last_valid_pct: int | None = None

    async def async_added_to_hass(self) -> None:
        """Restore last known value on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._last_valid_pct = int(last_state.state)
            except (ValueError, TypeError):
                pass

    @property
    def available(self) -> bool:
        has_live = self.coordinator.data is not None and "168" in self.coordinator.data
        return has_live or self._last_valid_pct is not None

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return self._last_valid_pct

        dps168 = self.coordinator.data.get("168", "")
        if not dps168:
            return self._last_valid_pct

        usage_min = parse_dps168_consumables(dps168).get(self._consumable_key)
        if usage_min is None:
            return self._last_valid_pct

        remaining_min = max(0, self._max_minutes - usage_min)
        pct = round(remaining_min / self._max_minutes * 100)
        self._last_valid_pct = pct
        return pct
