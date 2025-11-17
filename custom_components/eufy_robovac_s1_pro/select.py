"""Select platform for Eufy Robovac."""
import logging
from typing import Any
import asyncio

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN

logger = logging.getLogger(__name__)

# S1 Pro Cleaning Mode definitions
CLEANING_MODES = {
    "vacuum": {
        "name": "Vacuum Only",
        "dps154": "FAoKCgASABoAIgIIAhIGCAEQASAB",
        "dps10": None
    },
    "mop_low": {
        "name": "Vacuum and Mop (Water Level: Low)",
        "dps154": "FAoKCgIIAhIAGgAiABIGCAEQASAB",
        "dps10": "low"
    },
    "mop_middle": {
        "name": "Vacuum and Mop (Water Level: Medium)",
        "dps154": "FgoMCgIIAhIAGgAiAggBEgYIARABIAE=",
        "dps10": "middle"
    },
    "mop_high": {
        "name": "Vacuum and Mop (Water Level: High)",
        "dps154": "FgoMCgIIAhIAGgAiAggCEgYIARABIAE=",
        "dps10": "high"
    }
}

# Map DPS values to mode names
DPS_TO_MODE_MAP = {
    ("FAoKCgASABoAIgIIAhIGCAEQASAB", None): "vacuum",
    ("FAoKCgIIAhIAGgAiABIGCAEQASAB", "low"): "mop_low",
    ("FgoMCgIIAhIAGgAiAggBEgYIARABIAE=", "middle"): "mop_middle",
    ("FgoMCgIIAhIAGgAiAggCEgYIARABIAE=", "high"): "mop_high",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    discovered_devices = hass.data[DOMAIN][config_entry.entry_id][CONF_DISCOVERED_DEVICES]

    logger.debug("Setting up select entities for discovered devices: %s", discovered_devices)

    entities = []
    for device_id, props in discovered_devices.items():
        entities.append(CleaningModeSelect(coordinator=props[CONF_COORDINATOR]))
    
    async_add_entities(entities)


class CleaningModeSelect(CoordinatorEntity, SelectEntity):
    """Select entity for cleaning mode."""

    _attr_name = "Cleaning Mode"
    _attr_icon = "mdi:broom"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.tuya_client.device_id}_cleaning_mode"
        
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.tuya_client.device_id)},
            manufacturer="Eufy",
            name="Eufy Robovac S1 Pro",
            model="S1 Pro (T2080)",
        )

    @property
    def options(self) -> list[str]:
        """Return available options."""
        return [CLEANING_MODES[mode]["name"] for mode in CLEANING_MODES.keys()]

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        if not self.coordinator.data:
            return None
        
        dps154 = self.coordinator.data.get("154", "")
        dps10 = self.coordinator.data.get("10", None)
        
        # Check if DPS 10 is a string (water level)
        if isinstance(dps10, str) and dps10 in ["low", "middle", "high"]:
            water_level = dps10
        else:
            water_level = None
        
        # Try to find matching mode
        mode_key = (dps154, water_level)
        if mode_key in DPS_TO_MODE_MAP:
            mode = DPS_TO_MODE_MAP[mode_key]
            if mode in CLEANING_MODES:
                return CLEANING_MODES[mode]["name"]
        
        # Try without water level (vacuum mode)
        if dps154 == CLEANING_MODES["vacuum"]["dps154"]:
            return CLEANING_MODES["vacuum"]["name"]
        
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        # Find the mode by name
        selected_mode = None
        for mode_key, mode_config in CLEANING_MODES.items():
            if mode_config["name"] == option:
                selected_mode = mode_key
                break
        
        if not selected_mode:
            logger.error(f"Invalid cleaning mode selected: {option}")
            return
        
        mode_config = CLEANING_MODES[selected_mode]
        logger.info(f"Setting cleaning mode to: {mode_config['name']}")
        
        try:
            # Set DPS 154
            await self.coordinator.tuya_client.async_set({"154": mode_config["dps154"]})
            await asyncio.sleep(0.5)
            
            # Set DPS 10 if needed (for mopping modes)
            if mode_config["dps10"]:
                await self.coordinator.tuya_client.async_set({"10": mode_config["dps10"]})
            await asyncio.sleep(0.5)
            
            # Refresh state
            await self.coordinator.async_request_refresh()
            
            logger.info(f"Cleaning mode set to: {mode_config['name']}")
        except Exception as e:
            logger.error(f"Failed to set cleaning mode: {e}")
