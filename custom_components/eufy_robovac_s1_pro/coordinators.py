import hashlib
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .tuya import Message, TuyaDevice

logger = logging.getLogger(__name__)

_DPS_VALUE_PREVIEW_LEN = 64


def _summarize_dps_value(value):
    """Truncate long base64/string DPS values to keep diff logs readable.

    Long opaque DPS values (e.g. DPS 153/167/178 are base64 protobuf blobs that
    can be hundreds of bytes) are summarised as ``<head>...<sha1[:8]> (len=N)``
    so the log line stays useful for spotting changes without dumping the
    entire payload into the log file.
    """
    if isinstance(value, str) and len(value) > _DPS_VALUE_PREVIEW_LEN:
        digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:8]
        return f"{value[:_DPS_VALUE_PREVIEW_LEN]}...{digest} (len={len(value)})"
    return value


class EufyTuyaDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, *args, host: str, device_id: str, local_key: str, **kwargs):
        super().__init__(*args, **kwargs)

        self.tuya_client = TuyaDevice(device_id=device_id, local_key=local_key, host=host)

        extra_handler_list = [self.handle_tuya_message]

        for message_type in [Message.GET_COMMAND, Message.GRATUITOUS_UPDATE]:
            if message_type not in self.tuya_client._handlers:
                self.tuya_client._handlers[message_type] = extra_handler_list
            else:
                self.tuya_client._handlers[message_type] += extra_handler_list

    def handle_new_dps(self, new_dps: dict, async_set_updated_data_upon_change: bool = False):
        existing_dps = (self.data or {}).copy()

        changed = new_dps != existing_dps

        if changed:
            if logger.isEnabledFor(logging.DEBUG):
                _SENTINEL = object()
                diff = {
                    k: (existing_dps.get(k, _SENTINEL), v)
                    for k, v in new_dps.items()
                    if existing_dps.get(k, _SENTINEL) != v
                }
                if diff:
                    formatted = {
                        k: f"{'<new>' if old is _SENTINEL else _summarize_dps_value(old)!r}"
                        f" -> {_summarize_dps_value(new)!r}"
                        for k, (old, new) in diff.items()
                    }
                    logger.debug("DPS changed: %s", formatted)

            existing_dps.update(new_dps)

            if async_set_updated_data_upon_change:
                # only do this if there were changes as to not spam the state machine
                self.async_set_updated_data(existing_dps)

        return existing_dps

    async def handle_tuya_message(self, message, _):
        self.handle_new_dps(dict(message.payload["dps"]), async_set_updated_data_upon_change=True)

    async def _async_update_data(self):
        # note: this will call the tuya message handler above
        # which will in turn call handle_tuya_message and may cause an extra update to the state machine
        # TODO: this all needs to be cleaned up
        dps = dict((await self.tuya_client.async_get()) or {})

        return self.handle_new_dps(
            dps,
        )
