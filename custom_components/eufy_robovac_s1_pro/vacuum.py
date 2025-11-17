import logging
from typing import Any
import asyncio

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
    VacuumActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN

logger = logging.getLogger(__name__)


# S1 Pro actual fan speed mappings (from app testing)
HA_TO_EUFY_FAN_SPEED_MAP = {
    "Quiet": ("gentle", "Quiet"),      # DPS 9: gentle, DPS 158: Quiet
    "Standard": ("normal", "Standard"), # DPS 9: normal, DPS 158: Standard  
    "Turbo": ("strong", "Turbo"),      # DPS 9: strong, DPS 158: Turbo
    "Maximum": ("max", "Max")           # DPS 9: max, DPS 158: Max
}

# Reverse mapping for display
EUFY_TO_HA_FAN_SPEED_MAP = {
    "gentle": "Quiet",
    "normal": "Standard",
    "strong": "Turbo",
    "max": "Maximum",
    "Quiet": "Quiet",
    "Standard": "Standard",
    "Turbo": "Turbo",
    "Max": "Maximum",
    "middle": "Standard",  # Fallback
}

# S1 Pro Command definitions for DPS 152 (from actual app logs)
S1_PRO_COMMANDS = {
    "start": "AA==",        # 掃除開始
    "cleaning": "AggO",     # 掃除中
    "pause": "AggN",        # 一時停止
    "return": "AggG",       # ステーション帰還
}

# S1 Pro Status definitions for DPS 153 (from actual device analysis)
S1_PRO_STATUS = {
    "CLEANING": "BgoAEAUyAA==",     # 掃除中
    "PAUSED": "CAoAEAUyAggB",      # 一時停止
    "RETURNING": "BBAHQgA=",        # 帰還中
    # DOCKED states vary based on charging status, water refill, etc.
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    discovered_devices = hass.data[DOMAIN][config_entry.entry_id][CONF_DISCOVERED_DEVICES]

    logger.debug("Got discovered devices: %s", discovered_devices)

    return async_add_devices(
        [RobovacVacuum(coordinator=props[CONF_COORDINATOR]) for device_id, props in discovered_devices.items()]
    )


class RobovacVacuum(CoordinatorEntity, StateVacuumEntity):

    _attr_name = "Eufy Robovac S1 Pro"
    _attr_supported_features = (
        VacuumEntityFeature.BATTERY
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.START
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.FAN_SPEED
    )

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._last_command = None
        self._last_command_time = 0
        self._was_paused = False  # 一時停止状態を記憶

    @property
    def icon(self) -> str:
        if self.activity == VacuumActivity.ERROR:
            return "mdi:robot-vacuum-alert"
        return "mdi:robot-vacuum"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Eufy",
            name=self.name,
            model="S1 Pro (T2080)",
        )

    @property
    def unique_id(self) -> str:
        return self.coordinator.tuya_client.device_id

    @property
    def activity(self) -> VacuumActivity | None:
        """Return the current activity of the vacuum."""
        if not self.coordinator.data:
            return None
            
        # S1 Pro status detection based on actual DPS values
        dps2 = self.coordinator.data.get("2", False)  # Power status
        dps5 = self.coordinator.data.get("5", "")     # Mode
        dps6 = self.coordinator.data.get("6", 0)      # Status indicator 1
        dps7 = self.coordinator.data.get("7", 0)      # Status indicator 2
        dps152 = self.coordinator.data.get("152", "")  # Command status
        dps153 = self.coordinator.data.get("153", "")  # Actual status indicator (most reliable)
        
        logger.debug(f"Activity check - DPS 2: {dps2}, DPS 5: {dps5}, DPS 6: {dps6}, DPS 7: {dps7}, DPS 152: {dps152}, DPS 153: {dps153}")
        
        # Error detection
        if isinstance(dps6, int) and dps6 >= 100:
            return VacuumActivity.ERROR
        
        # Check DPS 153 status first (most reliable)
        if dps153 == S1_PRO_STATUS["CLEANING"]:
            self._was_paused = False  # クリア
            return VacuumActivity.CLEANING
        elif dps153 == S1_PRO_STATUS["PAUSED"]:
            self._was_paused = True  # 一時停止状態を記憶
            return VacuumActivity.PAUSED
        elif dps153 == S1_PRO_STATUS["RETURNING"]:
            self._was_paused = False  # クリア
            return VacuumActivity.RETURNING
        
        # If DPS 153 doesn't match known states, it's docked or charging
        # (DPS 153 varies for different docked states like charging, fully charged, water refill, etc.)
        if dps153 and dps153 not in S1_PRO_STATUS.values():
            self._was_paused = False  # クリア
            return VacuumActivity.DOCKED
        
        # Fallback to DPS 152 status if DPS 153 is not available
        if not dps153:
            if dps152 == S1_PRO_COMMANDS["cleaning"] or dps152 == "AggO":
                self._was_paused = False  # クリア
                return VacuumActivity.CLEANING
            elif dps152 == S1_PRO_COMMANDS["pause"] or dps152 == "AggN":
                self._was_paused = True  # 一時停止状態を記憶
                return VacuumActivity.PAUSED
            elif dps152 == S1_PRO_COMMANDS["return"] or dps152 == "AggG":
                self._was_paused = False  # クリア
                return VacuumActivity.RETURNING
            
            # Fallback to DPS 6/7 combination
            if dps6 == 2 and dps7 == 3:
                self._was_paused = False
                return VacuumActivity.CLEANING
            elif dps6 == 3 and dps7 == 4:
                self._was_paused = True
                return VacuumActivity.PAUSED
            elif dps6 == 1 and dps7 == 2:
                self._was_paused = False
                return VacuumActivity.RETURNING
            elif dps6 == 0 and dps7 == 0:
                battery = self.coordinator.data.get("8", 0)
                if battery >= 95:
                    return VacuumActivity.DOCKED
                else:
                    return VacuumActivity.IDLE
            else:
                # Default state based on power and battery
                if dps2:
                    return VacuumActivity.IDLE
                else:
                    battery = self.coordinator.data.get("8", 0)
                    if battery >= 95:
                        return VacuumActivity.DOCKED
                    else:
                        return VacuumActivity.IDLE
        
        # If we get here without a determined state, return IDLE
        return VacuumActivity.IDLE

    @property
    def battery_level(self) -> int | None:
        """Returns the battery level as a percentage"""
        if self.coordinator.data:
            # S1 Pro uses DPS 8 for battery level (confirmed from logs)
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

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the vacuum."""
        attrs = super().state_attributes or {}
        
        if self.coordinator.data:
            # Only include essential attributes for end users
            if error_code := self.error_code:
                attrs["error_code"] = error_code
            
        return attrs
    
    def _is_running(self) -> bool:
        """Check if vacuum is actually running based on multiple indicators."""
        if self.coordinator.data:
            dps153 = self.coordinator.data.get("153", "")
            dps152 = self.coordinator.data.get("152", "")
            dps6 = self.coordinator.data.get("6", 0)
            dps7 = self.coordinator.data.get("7", 0)
            
            # Check DPS 153 first (most reliable)
            if dps153 == S1_PRO_STATUS["CLEANING"]:
                return True
            
            # Fallback to DPS 152 if DPS 153 is not available
            if not dps153 and (dps152 == S1_PRO_COMMANDS["cleaning"] or dps152 == "AggO"):
                return True
            
            # Final fallback to DPS 6/7
            if not dps153 and not dps152:
                return (dps6 == 2 and dps7 == 3)
                
        return False

    @property
    def error_code(self) -> str | None:
        """Return error code if any."""
        if self.coordinator.data:
            # Check if DPS 6 has an error value (high numbers)
            error_code = self.coordinator.data.get("6")
            if isinstance(error_code, int) and error_code >= 100:
                return str(error_code)
        return None

    @property
    def fan_speed(self) -> str | None:
        """Return the current fan speed."""
        if self.coordinator.data:
            # Check DPS 9 first (primary)
            raw_speed = self.coordinator.data.get("9")
            if raw_speed and raw_speed in EUFY_TO_HA_FAN_SPEED_MAP:
                return EUFY_TO_HA_FAN_SPEED_MAP[raw_speed]
            
            # Check DPS 158 as fallback
            raw_speed = self.coordinator.data.get("158")
            if raw_speed and raw_speed in EUFY_TO_HA_FAN_SPEED_MAP:
                return EUFY_TO_HA_FAN_SPEED_MAP[raw_speed]
        return None

    @property
    def fan_speed_list(self) -> list[str]:
        """Get the list of available fan speeds."""
        return ["Quiet", "Standard", "Turbo", "Maximum"]

    async def _send_command(self, command: str) -> None:
        """Send command via DPS 152."""
        try:
            logger.info(f"Sending command via DPS 152: {command}")
            
            # Store last command for debugging
            self._last_command = command
            self._last_command_time = asyncio.get_event_loop().time()
            
            # Send command to DPS 152
            await self.coordinator.tuya_client.async_set({"152": command})
            
            # Wait for response
            await asyncio.sleep(0.5)
            
            # Also set appropriate mode for consistency
            if command == S1_PRO_COMMANDS["start"]:
                await self.coordinator.tuya_client.async_set({"5": "smart"})
            elif command == S1_PRO_COMMANDS["pause"]:
                await self.coordinator.tuya_client.async_set({"5": "pause"})
            elif command == S1_PRO_COMMANDS["return"]:
                await self.coordinator.tuya_client.async_set({"5": "charge"})
            
            # Wait and refresh state
            await asyncio.sleep(1.0)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            raise

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the vacuum on and start cleaning."""
        logger.info("Starting vacuum cleaning via DPS 152")
        
        try:
            # Clear pause state
            self._was_paused = False
            
            # Send start command
            await self._send_command(S1_PRO_COMMANDS["start"])
            
            # Wait for state to stabilize
            await asyncio.sleep(2.0)
            
            # Send cleaning command to confirm
            await self._send_command(S1_PRO_COMMANDS["cleaning"])
            
            # Final refresh
            await self.coordinator.async_request_refresh()
            
            if self._is_running():
                logger.info("Vacuum started successfully")
            else:
                logger.warning("Vacuum may not have started properly")
                
        except Exception as e:
            logger.error(f"Failed to start vacuum: {e}")
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the vacuum off."""
        logger.info("Stopping vacuum")
        await self.async_pause()  # For S1 Pro, stop = pause

    async def async_start(self) -> None:
        """Start or resume cleaning."""
        logger.debug("Starting/resuming cleaning")
        
        # Check current state
        activity = self.activity
        current_dps152 = self.coordinator.data.get("152", "")
        current_dps153 = self.coordinator.data.get("153", "")
        
        # 一時停止状態からの再開か確認
        if (activity == VacuumActivity.PAUSED or 
            self._was_paused or 
            current_dps153 == S1_PRO_STATUS["PAUSED"] or
            current_dps152 == S1_PRO_COMMANDS["pause"]):
            # 一時停止からの再開 - cleaningコマンドのみ送信
            logger.info("Resuming from pause - sending cleaning command only")
            
            # 掃除中コマンドを直接送信（「掃除を再開」のアナウンス）
            await self._send_command(S1_PRO_COMMANDS["cleaning"])
            
            # 一時停止フラグをクリア
            self._was_paused = False
            
        else:
            # 新規開始（「掃除を開始」のアナウンス）
            logger.info("Starting new cleaning session")
            await self.async_turn_on()

    async def async_pause(self) -> None:
        """Pause the vacuum."""
        logger.debug("Pausing vacuum via DPS 152")
        
        try:
            # 一時停止状態を記憶
            self._was_paused = True
            
            # Send pause command
            await self._send_command(S1_PRO_COMMANDS["pause"])
            
            logger.info("Vacuum paused")
        except Exception as e:
            logger.error(f"Failed to pause vacuum: {e}")
            self._was_paused = False  # エラー時はリセット

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum - S1 Pro doesn't have stop, using pause instead."""
        logger.debug("Stop requested - using pause for S1 Pro")
        await self.async_pause()

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return vacuum to base."""
        logger.debug("Returning to base via DPS 152")
        
        try:
            # Clear pause state
            self._was_paused = False
            
            # Send return command
            await self._send_command(S1_PRO_COMMANDS["return"])
            
            logger.info("Return to base command sent")
        except Exception as e:
            logger.error(f"Failed to return to base: {e}")

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean-up - Not supported on S1 Pro."""
        logger.info("Spot cleaning is not supported on S1 Pro - ignoring request")
        # Do nothing, but don't raise an error for compatibility

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum (make it beep) - Not supported on S1 Pro."""
        logger.info("Locate function is not supported on S1 Pro - ignoring request")
        # Do nothing, but don't raise an error for compatibility

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set the vacuum's fan speed."""
        if fan_speed not in HA_TO_EUFY_FAN_SPEED_MAP:
            logger.error(f"Invalid fan speed: {fan_speed}")
            return
            
        logger.debug(f"Setting fan speed to {fan_speed}")
        
        try:
            dps9_value, dps158_value = HA_TO_EUFY_FAN_SPEED_MAP[fan_speed]
            
            # Set both DPS values for S1 Pro
            await self.coordinator.tuya_client.async_set({
                "9": dps9_value,
                "158": dps158_value
            })
            
            logger.info(f"Fan speed set to {fan_speed}")
        except Exception as e:
            logger.error(f"Failed to set fan speed: {e}")
