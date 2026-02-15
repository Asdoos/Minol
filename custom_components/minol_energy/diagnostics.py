"""Diagnostics support for Minol Energy."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import MinolConfigEntry

REDACT_CONFIG = {CONF_USERNAME, CONF_PASSWORD}
REDACT_DATA = {
    "name",
    "email",
    "addrStreet",
    "addrHouseNum",
    "addrCity",
    "addrPostalCode",
    "userNumber",
    "lgnr",
    "nenr",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MinolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "config_entry": async_redact_data(entry.as_dict(), REDACT_CONFIG),
        "coordinator_data": async_redact_data(coordinator.data, REDACT_DATA),
    }
