from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN, RobovacDPs
from .mixins import CoordinatorTuyaDeviceUniqueIDMixin


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    discovered_devices = hass.data[DOMAIN][config_entry.entry_id][CONF_DISCOVERED_DEVICES]

    devices = []

    for device_id, props in discovered_devices.items():
        coordinator = props[CONF_COORDINATOR]
        
        # Only add auto-return switch if the DPS is available
        if coordinator.data and RobovacDPs.ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156 in coordinator.data:
            devices.append(AutoReturnCleaningSwitch(coordinator=coordinator))

    if devices:
        return async_add_devices(devices)


class AutoReturnCleaningSwitch(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, SwitchEntity):

    _attr_name = "Auto-return cleaning"
    _attr_icon = "mdi:autorenew"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and RobovacDPs.ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156 in self.coordinator.data

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data:
            value = self.coordinator.data.get(RobovacDPs.ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156)
            
            if isinstance(value, bool):
                return value
            elif value is not None:
                # Try to convert string values
                if str(value).lower() in ['true', '1', 'on']:
                    return True
                elif str(value).lower() in ['false', '0', 'off']:
                    return False
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.tuya_client.async_set({RobovacDPs.ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156: True})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.tuya_client.async_set({RobovacDPs.ROBOVAC_AUTO_RETURN_CLEAN_DPS_ID_156: False})
