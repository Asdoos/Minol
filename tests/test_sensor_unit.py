"""Unit tests for the sensor platform.

Focus: the ``last_reset`` behaviour that makes period totals add up in Home
Assistant's long-term statistics.  Homeassistant itself is stubbed (conftest.py),
so these tests exercise the entities' own logic plus a replica of HA's
documented statistics arithmetic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorStateClass

from custom_components.minol_energy.const import (
    SERVICE_COLD_WATER,
    SERVICE_HEATING,
    SERVICE_HOT_WATER,
)
from custom_components.minol_energy.sensor import async_setup_entry

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCoordinator:
    def __init__(self, data: dict) -> None:
        self.data = data

    def async_add_listener(self, callback):
        self.listener = callback
        return lambda: None


class _FakeEntry:
    entry_id = "ENTRY1"

    def __init__(self, options: dict | None = None) -> None:
        self.options = options or {}

    def async_on_unload(self, callback) -> None:
        pass


class _FakeHass:
    class config:  # mirrors hass.config.language
        language = "de"


def _device(room: str, energy: float) -> dict:
    return {"deviceid": f"DEV{room}", "room": room, "energyValue": energy}


def _period(period: str, heating: float, devices: list[dict] | None = None) -> dict:
    """One consumption period with all three services."""
    return {
        "period": period,
        "statusOverall": "UVI_AVAILABLE",
        "consumptions": [
            {
                "service": SERVICE_HEATING,
                "energyValue": heating,
                "co2kg": 12.5,
                "devices": devices or [],
            },
            {"service": SERVICE_HOT_WATER, "energyValue": 90.0, "co2kg": 4.0},
            {"service": SERVICE_COLD_WATER, "energyValue": 3.4},
        ],
    }


async def _setup(data: dict, options: dict | None = None) -> dict[str, object]:
    """Run async_setup_entry and return the created entities by translation key."""
    entities: list = []
    coordinator = _FakeCoordinator(data)
    entry = _FakeEntry(options)
    entry.runtime_data = coordinator
    await async_setup_entry(_FakeHass, entry, lambda new: entities.extend(new))
    return {e.unique_id: e for e in entities}


# real /consumptions format: the month is labelled by its last day
_JAN = _period("2026-01-31T00:00:00Z", 300.0, devices=[_device("0000002", 120.0)])


# ---------------------------------------------------------------------------
# last_reset wiring
# ---------------------------------------------------------------------------


class TestLastReset:
    async def test_total_sensor_is_total_with_period_start(self):
        ents = await _setup({"latest_consumption": _JAN})
        total = ents["ENTRY1_100_energy_total"]
        assert total.state_class is SensorStateClass.TOTAL
        assert total.native_value == 300.0
        assert total.last_reset == datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def test_latest_month_sensor_also_resets_per_period(self):
        ents = await _setup({"latest_consumption": _JAN})
        latest = ents["ENTRY1_100_latest_month"]
        assert latest.state_class is SensorStateClass.TOTAL
        assert latest.last_reset == datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def test_co2_sensor_has_no_last_reset(self):
        """last_reset is only valid for total sensors — HA errors on measurement."""
        ents = await _setup({"latest_consumption": _JAN})
        co2 = ents["ENTRY1_100_co2_latest_month"]
        assert co2.state_class is SensorStateClass.MEASUREMENT
        assert co2.last_reset is None

    async def test_room_sensor_last_reset(self):
        ents = await _setup({"latest_consumption": _JAN})
        room = ents["ENTRY1_room_0000002_100"]
        assert room.native_value == 120.0
        assert room.last_reset == datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def test_unparseable_period_yields_no_reset(self):
        period = dict(_JAN, period="Januar 2026")
        ents = await _setup({"latest_consumption": period})
        assert ents["ENTRY1_100_energy_total"].last_reset is None


# ---------------------------------------------------------------------------
# Statistics arithmetic
# ---------------------------------------------------------------------------


def _ha_total_sum(samples: list[tuple[float, datetime | None]]) -> float:
    """Replica of HA's statistics engine for ``state_class: total``.

    Within one ``last_reset`` the sum grows by the state's delta; a changed
    ``last_reset`` means the counter restarted, so the state is added in full.
    """
    total = 0.0
    prev_state: float | None = None
    prev_reset: datetime | None = None
    for state, reset in samples:
        if prev_state is None or reset != prev_reset:
            total += state
        else:
            total += state - prev_state
        prev_state, prev_reset = state, reset
    return total


def _ha_total_increasing_sum(states: list[float]) -> float:
    """Replica of HA's engine for ``state_class: total_increasing`` (pre-0.7.2).

    The first state is only a baseline; a drop counts as a meter reset and the
    new state is added in full, otherwise only the increase is added.
    """
    total = 0.0
    prev: float | None = None
    for state in states:
        if prev is not None:
            total += state if state < prev else state - prev
        prev = state
    return total


_MONTHS = [
    ("2026-01-31T00:00:00Z", 300.0),
    ("2026-02-28T00:00:00Z", 250.0),
    ("2026-03-31T00:00:00Z", 280.0),
]


class TestStatisticsAccumulation:
    """Three consecutive periods must add up to their true sum."""

    async def _samples(self) -> list[tuple[float, datetime | None]]:
        coordinator = _FakeCoordinator({"latest_consumption": _period(*_MONTHS[0])})
        entry = _FakeEntry()
        entry.runtime_data = coordinator
        entities: list = []
        await async_setup_entry(_FakeHass, entry, lambda new: entities.extend(new))
        sensor = next(
            e for e in entities if e.unique_id == "ENTRY1_100_energy_total"
        )

        samples = []
        for period, value in _MONTHS:
            coordinator.data = {"latest_consumption": _period(period, value)}
            samples.append((sensor.native_value, sensor.last_reset))
        return samples

    async def test_sum_matches_real_consumption(self):
        samples = await self._samples()
        assert _ha_total_sum(samples) == 830.0  # 300 + 250 + 280

    async def test_old_total_increasing_undercounted(self):
        """Regression guard: this is the bug fixed in 0.7.2."""
        samples = await self._samples()
        assert _ha_total_increasing_sum([s for s, _ in samples]) == 280.0

    async def test_revised_value_within_same_period_adds_delta_only(self):
        """An estimate corrected upward must not be counted twice."""
        coordinator = _FakeCoordinator({"latest_consumption": _period("2026-01-31T00:00:00Z", 200.0)})
        entry = _FakeEntry()
        entry.runtime_data = coordinator
        entities: list = []
        await async_setup_entry(_FakeHass, entry, lambda new: entities.extend(new))
        sensor = next(e for e in entities if e.unique_id == "ENTRY1_100_energy_total")

        samples = []
        for value in (200.0, 240.0):
            coordinator.data = {"latest_consumption": _period("2026-01-31T00:00:00Z", value)}
            samples.append((sensor.native_value, sensor.last_reset))
        assert _ha_total_sum(samples) == 240.0
