"""Config flow for Minol Energy integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import MinolApiClient, MinolAuthError, MinolConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MinolEnergyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Minol Energy."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step – username / password entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = MinolApiClient(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )

            try:
                await client.authenticate()
            except MinolAuthError:
                errors["base"] = "invalid_auth"
            except MinolConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Minol login")
                errors["base"] = "unknown"
            finally:
                await client.close()

            if not errors:
                # Prevent duplicate entries for the same account.
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Minol ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
