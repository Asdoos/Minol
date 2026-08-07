"""Long-term statistics import for the full consumption history.

The API keeps every monthly period since move-in (37 for the author's account),
while sensor states only start when Home Assistant first polls.  Importing the
history as *external* statistics gives the Energy Dashboard the complete series,
independent of when the integration was installed and of HA running at a period
boundary:

    minol_energy:heating_energy      kWh
    minol_energy:hot_water_energy    kWh
    minol_energy:cold_water_volume   m³

These are statistics only — no entity, no state.  Pick them directly as an
Energy Dashboard source; they can be removed again under
*Developer tools → Statistics*.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback

from .api import MinolApiClient
from .const import (
    DOMAIN,
    SERVICE_COLD_WATER,
    SERVICE_HEATING,
    SERVICE_HOT_WATER,
    STATUS_UVI_AVAILABLE,
)

_LOGGER = logging.getLogger(__name__)

# service code → (statistic_id suffix, display name, unit)
_SERIES: dict[str, tuple[str, str, str]] = {
    SERVICE_HEATING: (
        "heating_energy",
        "Minol Heating",
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SERVICE_HOT_WATER: (
        "hot_water_energy",
        "Minol Hot Water",
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SERVICE_COLD_WATER: (
        "cold_water_volume",
        "Minol Cold Water",
        UnitOfVolume.CUBIC_METERS,
    ),
}


def _metadata(statistic_id: str, name: str, unit: str) -> dict[str, Any]:
    """Build recorder metadata, tolerating the has_mean → mean_type rename."""
    meta: dict[str, Any] = {
        "has_mean": False,
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": unit,
    }
    try:
        from homeassistant.components.recorder.models import StatisticMeanType
    except ImportError:
        return meta  # HA < 2025.2 only knows has_mean
    meta["mean_type"] = StatisticMeanType.NONE
    return meta


def build_statistics(
    periods: list[dict[str, Any]], service_code: str
) -> list[StatisticData]:
    """Turn consumption periods into cumulative statistics rows, oldest first.

    ``sum`` has to be the running total since the series began — the dashboard
    derives each month's consumption from the difference between two rows — so
    the periods are sorted by start before accumulating rather than trusting the
    order the API happened to return them in.
    """
    rows: list[tuple[datetime, float]] = []
    for period in periods:
        if period.get("statusOverall") != STATUS_UVI_AVAILABLE:
            continue  # still preliminary — no final value to record yet
        start = MinolApiClient.get_period_start(period)
        value = MinolApiClient.get_service_value(period, service_code)
        if start is None or value is None:
            continue
        rows.append((start, value))

    rows.sort()
    stats: list[StatisticData] = []
    total = 0.0
    for start, value in rows:
        total += value
        stats.append(StatisticData(start=start, state=value, sum=total))
    return stats


@callback
def async_import_history(hass: HomeAssistant, periods: list[dict[str, Any]]) -> None:
    """Import every finalised consumption period into long-term statistics.

    The whole series is re-imported on every call.  Rows are keyed by start
    time, so an existing month is updated instead of duplicated, and a value the
    API revises later corrects itself together with every cumulative sum after
    it.
    ponytail: no change detection — ~40 upserts per poll is cheaper than
    tracking what moved.  Add it if a history ever gets long enough to notice.
    """
    if "recorder" not in hass.config.components:
        _LOGGER.debug("Recorder not enabled — skipping statistics import")
        return

    for service_code, (suffix, name, unit) in _SERIES.items():
        stats = build_statistics(periods, service_code)
        if not stats:
            continue
        statistic_id = f"{DOMAIN}:{suffix}"
        async_add_external_statistics(hass, _metadata(statistic_id, name, unit), stats)
        _LOGGER.debug(
            "Imported %d periods into %s (total %.3f %s)",
            len(stats),
            statistic_id,
            stats[-1]["sum"],
            unit,
        )
