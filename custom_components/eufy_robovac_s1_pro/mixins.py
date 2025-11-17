from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


class CoordinatorTuyaDeviceUniqueIDMixin:
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.tuya_client.device_id)},
            manufacturer="Eufy",
            # points to parent Eufy Vacuum device
            via_device=(DOMAIN, self.coordinator.tuya_client.device_id),
        )

    @property
    def unique_id(self) -> str:
        slug = self.name.lower().replace(" ", "_")

        return self.coordinator.tuya_client.device_id + "-" + slug
