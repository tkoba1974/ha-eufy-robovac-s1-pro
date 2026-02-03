import logging
from typing import Any
import asyncio
import base64
import json
import time
from enum import Enum

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
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

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
    "Max": "Max",
    "middle": "Standard",  # Fallback
}

# S1 Pro Command definitions for DPS 152 (from actual app logs)
S1_PRO_COMMANDS = {
    "start": "AA==",        # 掃除開始
    "cleaning": "AggO",     # 掃除中
    "pause": "AggN",        # 一時停止
    "return": "AggG",       # ステーション帰還
}


class RobovacState(Enum):
    """ロボット掃除機の状態定義"""
    CLEANING = "cleaning"
    PAUSED = "paused"
    RETURNING = "returning"
    DOCKED = "docked"
    ERROR = "error"
    UNKNOWN = "unknown"


def decode_dps153_to_state(dps153_value: str) -> tuple[RobovacState, str]:
    """
    dps153の値からロボット掃除機の状態とサブステータスを判定
    
    この関数は環境や設定の違いに対応できるよう、バイトパターンの
    普遍的な特徴に基づいて判定を行います。
    
    判定ロジック:
    1. Cleaning: Byte[1]=0x0a, Byte[2]=0x00, Byte[3]=0x10, Byte[4]=0x05, length=7
    2. Paused: Byte[1]=0x0a, Byte[2]=0x00, Byte[3]=0x10, Byte[4]=0x05, length>=9, Byte[6]=0x02
    3. Returning: Byte[1]=0x10, Byte[2]=0x07, Byte[3]=0x42
    4. Docked: 上記以外の場合
    
    Args:
        dps153_value: Base64エンコードされたdps153の値、またはバイト列
        
    Returns:
        (RobovacState, substatus_str): 判定された状態とサブステータス文字列のタプル
    """
    try:
        # Base64文字列の場合はデコード
        if isinstance(dps153_value, str):
            decoded = base64.b64decode(dps153_value)
        else:
            decoded = dps153_value
        
        # 最低限の長さチェック
        if len(decoded) < 3:
            logger.warning(f"dps153 data too short: {len(decoded)} bytes")
            return RobovacState.UNKNOWN, "unknown"
        
        byte1 = decoded[1]
        byte2 = decoded[2]
        
        # デバッグログ
        hex_str = ' '.join([f"{b:02x}" for b in decoded])
        logger.debug(f"dps153 decoded: {hex_str}")
        
        # ========== 主要な状態判定 ==========
        
        # Byte[1]=0x0a, Byte[2]=0x00 のパターン
        # (Cleaning, Paused, モップ関連Docked)
        if byte1 == 0x0a and byte2 == 0x00:
            if len(decoded) >= 5:
                byte3 = decoded[3]
                byte4 = decoded[4]
                
                # Cleaning/Pausedのパターン
                if byte3 == 0x10 and byte4 == 0x05:
                    # Pausedの判定
                    if len(decoded) >= 7 and decoded[6] == 0x02:
                        return RobovacState.PAUSED, "paused"
                    else:
                        return RobovacState.CLEANING, "cleaning"
                
                # モップ関連Dockedのパターン
                elif byte3 == 0x10 and byte4 == 0x09:
                    substatus = _get_docked_substatus(decoded)
                    return RobovacState.DOCKED, substatus
        
        # Returning の判定
        if byte1 == 0x10 and byte2 == 0x07:
            if len(decoded) >= 4 and decoded[3] == 0x42:
                return RobovacState.RETURNING, "returning"
        
        # Docked (その他) の判定
        if byte1 == 0x10:
            substatus = _get_docked_substatus(decoded)
            return RobovacState.DOCKED, substatus
        
        # デフォルトはDocked (未知のパターンでも安全側に倒す)
        logger.warning(f"Unknown dps153 pattern, defaulting to DOCKED: {hex_str}")
        return RobovacState.DOCKED, "idle"
        
    except Exception as e:
        logger.error(f"Error decoding dps153: {e}", exc_info=True)
        return RobovacState.UNKNOWN, "error"


def _get_docked_substatus(decoded: bytes) -> str:
    """
    Docked状態の詳細なサブステータスを取得
    
    Args:
        decoded: デコードされたdps153のバイト列
        
    Returns:
        サブステータス文字列
    """
    if len(decoded) < 3:
        return "unknown"
    
    byte1 = decoded[1]
    byte2 = decoded[2]
    
    # Byte[1]=0x10 の場合
    if byte1 == 0x10:
        if byte2 == 0x03:
            # 充電関連
            if len(decoded) >= 5:
                if decoded[4] == 0x00:
                    return "charging"
                elif decoded[4] == 0x02:
                    return "fully_charged"
            return "charging"
        
        elif byte2 == 0x09:
            # モップ関連操作
            if len(decoded) >= 4:
                byte3 = decoded[3]
                
                if byte3 == 0xfa:
                    return "dust_collecting"
                elif byte3 == 0x1a:
                    return "mop_drying"
                elif byte3 == 0x3a:
                    return "mop_washing"
            
            return "mop_operations"
    
    # Byte[1]=0x0a の場合 (給水中、掃除前モップ洗浄中など)
    if byte1 == 0x0a and byte2 == 0x00:
        if len(decoded) >= 5 and decoded[3] == 0x10 and decoded[4] == 0x09:
            if len(decoded) >= 12 and decoded[11] == 0x3a:
                return "mop_washing_pre"
            return "water_refilling"
    
    return "idle"


# サブステータスの人間が読める説明文
SUBSTATUS_DESCRIPTIONS = {
    "charging": "Charging",
    "fully_charged": "Fully Charged",
    "dust_collecting": "Collecting Dust",
    "water_refilling": "Refilling Water",
    "mop_washing_pre": "Pre-washing Mop",
    "mop_washing": "Washing Mop",
    "mop_drying": "Drying Mop",
    "mop_operations": "Mop Operations",
    "cleaning": "Cleaning",
    "paused": "Paused",
    "returning": "Returning to Dock",
    "idle": "Idle",
    "unknown": "Unknown",
    "error": "Error",
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
        | VacuumEntityFeature.SEND_COMMAND
    )

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._last_command = None
        self._last_command_time = 0
        self._was_paused = False  # 一時停止状態を記憶
        self._substatus = None  # サブステータスを保持
        self._detected_state = None  # 判定された状態を保持

    async def async_added_to_hass(self):
        """Register services."""
        await super().async_added_to_hass()

        async def handle_clean_room(call):
            """Handle the clean_room service call."""
            room_ids = call.data.get("room_ids", [])
            count = call.data.get("count", 1)
            
            await self.async_send_command(
                "clean_room", {"roomIds": room_ids, "count": count}
            )

        self.hass.services.async_register(
            DOMAIN,
            "clean_room",
            handle_clean_room,
            schema=vol.Schema(
                {
                    vol.Required("entity_id"): cv.entity_id,
                    vol.Required("room_ids"): vol.All(cv.ensure_list, [cv.positive_int]),
                    vol.Optional("count", default=1): cv.positive_int,
                }
            ),
        )

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
        dps6 = self.coordinator.data.get("6", 0)      # Status indicator 1
        dps153 = self.coordinator.data.get("153", "")  # Actual status indicator (most reliable)
        
        logger.debug(f"Activity check - DPS 6: {dps6}, DPS 153: {dps153}")
        
        # Error detection
        if isinstance(dps6, int) and dps6 >= 100:
            self._detected_state = RobovacState.ERROR
            self._substatus = "error"
            return VacuumActivity.ERROR
        
        # Check DPS 153 status using improved pattern-based detection
        if dps153:
            detected_state, substatus = decode_dps153_to_state(dps153)
            
            # 判定結果を保持
            self._detected_state = detected_state
            self._substatus = substatus
            
            logger.debug(f"Detected state: {detected_state.value}, substatus: {substatus}")
            
            # 状態に応じたフラグ更新と値の返却
            if detected_state == RobovacState.CLEANING:
                self._was_paused = False
                return VacuumActivity.CLEANING
            elif detected_state == RobovacState.PAUSED:
                self._was_paused = True
                return VacuumActivity.PAUSED
            elif detected_state == RobovacState.RETURNING:
                self._was_paused = False
                return VacuumActivity.RETURNING
            elif detected_state == RobovacState.DOCKED:
                self._was_paused = False
                return VacuumActivity.DOCKED
            elif detected_state == RobovacState.ERROR:
                return VacuumActivity.ERROR
            else:  # UNKNOWN
                # 未知の状態はIDLEとして扱う
                return VacuumActivity.IDLE
        
        # DPS 153が利用できない場合のフォールバック
        # (互換性のために旧ロジックを一部残す)
        dps152 = self.coordinator.data.get("152", "")
        dps6 = self.coordinator.data.get("6", 0)
        dps7 = self.coordinator.data.get("7", 0)
        
        logger.debug(f"Fallback to DPS 152/6/7 - DPS 152: {dps152}, DPS 6: {dps6}, DPS 7: {dps7}")
        
        if dps152 == S1_PRO_COMMANDS["cleaning"] or dps152 == "AggO":
            self._was_paused = False
            return VacuumActivity.CLEANING
        elif dps152 == S1_PRO_COMMANDS["pause"] or dps152 == "AggN":
            self._was_paused = True
            return VacuumActivity.PAUSED
        elif dps152 == S1_PRO_COMMANDS["return"] or dps152 == "AggG":
            self._was_paused = False
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
        
        # デフォルト
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
            
            # Check DPS 153 first (most reliable)
            if dps153:
                detected_state, _ = decode_dps153_to_state(dps153)
                return detected_state == RobovacState.CLEANING
            
            # Fallback to DPS 152 if DPS 153 is not available
            dps152 = self.coordinator.data.get("152", "")
            if dps152 == S1_PRO_COMMANDS["cleaning"] or dps152 == "AggO":
                return True
            
            # Final fallback to DPS 6/7
            dps6 = self.coordinator.data.get("6", 0)
            dps7 = self.coordinator.data.get("7", 0)
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
        
        # dps153の判定を新しいロジックで行う
        is_paused_by_dps153 = False
        if current_dps153:
            detected_state, _ = decode_dps153_to_state(current_dps153)
            is_paused_by_dps153 = (detected_state == RobovacState.PAUSED)
        
        # 一時停止状態からの再開か確認
        if (activity == VacuumActivity.PAUSED or 
            self._was_paused or 
            is_paused_by_dps153 or
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
