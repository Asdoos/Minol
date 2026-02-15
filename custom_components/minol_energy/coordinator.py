"""DataUpdateCoordinator for Minol Energy."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import MinolApiClient, MinolAuthError, MinolConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MinolDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared data fetcher for the Minol eMonitoring portal."""

    def __init__(self, hass: HomeAssistant, client: MinolApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get_all_data()
        except MinolAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MinolConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err
