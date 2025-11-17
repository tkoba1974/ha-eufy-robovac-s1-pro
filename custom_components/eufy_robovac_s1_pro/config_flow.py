import logging

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import DOMAIN
from .eufy_local_id_grabber.clients import EufyHomeSession

logger = logging.getLogger(__name__)

EUFY_LOGIN_SCHEMA = vol.Schema({vol.Required("username"): str, vol.Required("password"): str})


class EufyVacuumConfigFlow(ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input: dict[str, str] | None = None) -> data_entry_flow.FlowResult:
        errors = {}

        if user_input is not None:
            username = user_input["username"]
            password = user_input["password"]

            await self.async_set_unique_id(username)
            self._abort_if_unique_id_configured()

            client = EufyHomeSession(username, password)

            try:
                await self.hass.async_add_executor_job(client.get_user_info)
            except Exception:
                logger.exception("Error when logging in with %s", username)

                # TODO: proper exception handling
                errors["username"] = errors["password"] = "Username or password is incorrect"
            else:
                return self.async_create_entry(
                    title=username,
                    data={CONF_EMAIL: username, CONF_PASSWORD: password},
                )

        return self.async_show_form(step_id="user", data_schema=EUFY_LOGIN_SCHEMA)
