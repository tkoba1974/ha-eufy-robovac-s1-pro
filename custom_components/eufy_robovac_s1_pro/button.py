from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN, MAINTENANCE_ITEMS, RobovacDPs
from .coordinators import EufyTuyaDataUpdateCoordinator
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
        
        # Only add maintenance reset buttons if the reset DPS is available
        if coordinator.data and RobovacDPs.ROBOVAC_REPLACE_DPS_ID_115 in coordinator.data:
            for maintenance_item in MAINTENANCE_ITEMS:
                # Also check if the status DPS for this maintenance item exists
                if maintenance_item.status_dp in coordinator.data:
                    devices.append(
                        MaintenanceResetButton(
                            name=maintenance_item.name,
                            icon=maintenance_item.icon,
                            dp_value_to_set=maintenance_item.reset_dp_value,
                            coordinator=coordinator,
                        )
                    )

    if devices:
        return async_add_devices(devices)


class MaintenanceResetButton(CoordinatorTuyaDeviceUniqueIDMixin, CoordinatorEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    maintenance_item_name: str
    dp_value_to_set: str

    def __init__(
        self,
        name: str,
        icon: str,
        dp_value_to_set,
        coordinator: EufyTuyaDataUpdateCoordinator,
    ) -> None:
        self.maintenance_item_name = name
        self._attr_icon = icon
        self.dp_value_to_set = dp_value_to_set

        super().__init__(coordinator=coordinator)

    @property
    def name(self) -> str:
        return f"{self.maintenance_item_name} reset"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data is not None and RobovacDPs.ROBOVAC_REPLACE_DPS_ID_115 in self.coordinator.data

    async def async_press(self) -> None:
        await self.coordinator.tuya_client.async_set({RobovacDPs.ROBOVAC_REPLACE_DPS_ID_115: self.dp_value_to_set})
