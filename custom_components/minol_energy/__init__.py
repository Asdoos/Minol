"""The Minol Energy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import MinolApiClient
from .const import DOMAIN
from .coordinator import MinolDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type MinolConfigEntry = ConfigEntry[MinolDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Set up Minol Energy from a config entry."""
    client = MinolApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    await client.authenticate()

    coordinator = MinolDataCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Unload a Minol Energy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: MinolDataCoordinator = entry.runtime_data
        await coordinator.client.close()

    return unload_ok
