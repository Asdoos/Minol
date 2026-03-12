"""The Minol Energy integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import MinolApiClient
from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN
from .coordinator import MinolDataCoordinator, _get_update_interval

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]

type MinolConfigEntry = ConfigEntry[MinolDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Set up Minol Energy from a config entry."""

    def _on_tokens_refreshed(access_token: str, refresh_token: str | None) -> None:
        """Persist refreshed tokens back to the config entry.

        Uses async_update_entry(data=…) which fires add_update_listener callbacks.
        The listener below guards against that by comparing entry.options.
        """
        _LOGGER.debug("Persisting refreshed tokens to config entry")
        new_data = {**entry.data, CONF_ACCESS_TOKEN: access_token, "token_expires_in": 3600}
        if refresh_token:
            new_data[CONF_REFRESH_TOKEN] = refresh_token
        hass.config_entries.async_update_entry(entry, data=new_data)

    client = MinolApiClient(
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        on_tokens_refreshed=_on_tokens_refreshed,
    )
    if expires_in := entry.data.get("token_expires_in"):
        client.set_token_expiry(int(expires_in))

    coordinator = MinolDataCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Snapshot of options at setup time so the listener below can detect real
    # options changes vs. token-refresh data updates (which also fire the listener).
    _known_options: dict = dict(entry.options)

    async def _async_options_updated(
        hass: HomeAssistant, entry: MinolConfigEntry
    ) -> None:
        """Handle options update — adjust polling interval; reload only if needed."""
        nonlocal _known_options
        coordinator_inner: MinolDataCoordinator = entry.runtime_data
        coordinator_inner.update_interval = _get_update_interval(entry)
        if entry.options != _known_options:
            # Real options change (scan interval or prices) — reload to recreate sensors.
            _known_options = dict(entry.options)
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Minol Energy set up: %s (polling every %s)",
        entry.title,
        _get_update_interval(entry),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MinolConfigEntry) -> bool:
    """Unload a Minol Energy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: MinolDataCoordinator = entry.runtime_data
        await coordinator.client.close()

    return unload_ok
