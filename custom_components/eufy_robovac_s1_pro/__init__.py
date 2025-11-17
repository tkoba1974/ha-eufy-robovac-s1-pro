"""
Quick and dirty module to support Eufy S1 Pro.
"""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import CONF_COORDINATOR, CONF_DISCOVERED_DEVICES, DOMAIN, PLATFORMS
from .coordinators import EufyTuyaDataUpdateCoordinator
from .discovery import discover
from .eufy_local_id_grabber.clients import EufyHomeSession, TuyaAPISession

logger = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Eufy Vacuum entities from a config entry.
    """

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(entry.entry_id, {})

    username = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    client = EufyHomeSession(username, password)

    try:
        user_info = await hass.async_add_executor_job(client.get_user_info)
        logger.debug("Eufy user info: %s", user_info)
        #
        # eufy_device_list = await hass.async_add_executor_job(client.get_devices)
        # logger.debug("Eufy device list: %s", eufy_device_list)

        tuya_session = TuyaAPISession(username=f'eh-{user_info["id"]}', country_code=user_info["phone_code"])

        homes = await hass.async_add_executor_job(tuya_session.list_homes)
        logger.debug("Tuya homes: %s", homes)

        hass.data[DOMAIN][entry.entry_id].setdefault(CONF_DISCOVERED_DEVICES, {})

        detected_devices = await discover()

        for home in homes:
            devices_for_home = await hass.async_add_executor_job(tuya_session.list_devices, home["groupId"])

            for device in devices_for_home:
                logger.debug("Got Tuya device in home group %s: %s", home["groupId"], device)

                device_id = device["devId"]
                local_key = device["localKey"]

                if discovered_device := detected_devices.pop(device_id):
                    device_ip = discovered_device["ip"]

                    logger.debug(
                        "Found matching discovered device at %s for device ID %s",
                        device_ip,
                        device_id,
                    )

                    hass_entity_id = f'{home["groupId"]}-{device["devId"]}'

                    coordinator = EufyTuyaDataUpdateCoordinator(
                        hass,
                        logger=logger,
                        name=DOMAIN,
                        update_interval=timedelta(seconds=30),
                        host=device_ip,
                        device_id=device_id,
                        local_key=local_key,
                    )

                    # Try to get initial data, but don't fail if it doesn't work
                    try:
                        await coordinator.async_config_entry_first_refresh()
                    except Exception as e:
                        logger.warning(
                            "Could not get initial data for device %s at %s: %s",
                            device_id,
                            device_ip,
                            e,
                        )
                        # Still add the device, it might come online later

                    hass.data[DOMAIN][entry.entry_id][CONF_DISCOVERED_DEVICES][hass_entity_id] = {
                        CONF_COORDINATOR: coordinator
                    }
                else:
                    logger.debug(
                        "Could not find device %s on the local network, skipping",
                        device_id,
                    )

    except Exception:
        # TODO: raise proper exception
        logger.exception("Exception when trying to get initial user info and devices")
        raise
    else:
        # Forward the setup to each platform - use the correct method
        # Try the newer API first, then fallback to older methods
        try:
            # For Home Assistant 2023.8+
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except AttributeError:
            # Fallback for single platform setup
            for platform in PLATFORMS:
                try:
                    hass.async_create_task(
                        hass.config_entries.async_forward_entry_setup(entry, platform)
                    )
                except Exception as e:
                    logger.error("Failed to setup platform %s: %s", platform, e)
                    # Continue with other platforms even if one fails

        return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Try multiple unload methods for compatibility
    try:
        # For newer Home Assistant versions
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except AttributeError:
        # Fallback for older versions
        try:
            unload_ok = all(
                await asyncio.gather(
                    *[
                        hass.config_entries.async_forward_entry_unload(entry, platform)
                        for platform in PLATFORMS
                    ]
                )
            )
        except Exception as e:
            logger.error("Error unloading platforms: %s", e)
            unload_ok = False
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    
    return unload_ok
