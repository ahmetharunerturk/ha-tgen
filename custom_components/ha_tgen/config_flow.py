"""Single-instance UI setup; detailed camera options live in the panel."""

from functools import partial

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from . import directory_roots
from .const import DEFAULT_OUTPUT_ROOT, DOMAIN
from .paths import validate_directory


class TimelapseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select and verify a private output location."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            try:
                _, outputs = directory_roots(self.hass)
                root = await self.hass.async_add_executor_job(
                    partial(
                        validate_directory,
                        user_input["output_root"],
                        outputs,
                        create=True,
                    )
                )
            except (ValueError, OSError):
                errors["output_root"] = "invalid_directory"
            else:
                return self.async_create_entry(
                    title="HA Timelapse Generator", data={"output_root": str(root)}
                )
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("output_root", default=DEFAULT_OUTPUT_ROOT): selector.TextSelector(),
                }
            ),
        )
