"""Config flow for Minol Energy integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import MinolApiClient, MinolAuthError, MinolConnectionError
from .const import (
    CONF_COLD_WATER_PRICE,
    CONF_HEATING_PRICE,
    CONF_HOT_WATER_PRICE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

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

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return MinolOptionsFlow(config_entry)

    async def _validate_credentials(
        self, username: str, password: str
    ) -> dict[str, str]:
        """Validate credentials and return errors dict (empty on success)."""
        errors: dict[str, str] = {}
        client = MinolApiClient(username=username, password=password)
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
        return errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step – username / password entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await self._validate_credentials(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )

            if not errors:
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

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication when credentials expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to re-enter credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            username = reauth_entry.data[CONF_USERNAME]

            errors = await self._validate_credentials(
                username, user_input[CONF_PASSWORD]
            )

            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class MinolOptionsFlow(OptionsFlow):
    """Handle options for Minol Energy."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL // 60),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
                    vol.Optional(
                        CONF_HEATING_PRICE,
                        default=options.get(CONF_HEATING_PRICE, 0.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                    vol.Optional(
                        CONF_HOT_WATER_PRICE,
                        default=options.get(CONF_HOT_WATER_PRICE, 0.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                    vol.Optional(
                        CONF_COLD_WATER_PRICE,
                        default=options.get(CONF_COLD_WATER_PRICE, 0.0),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
                }
            ),
        )
