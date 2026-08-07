"""Unit tests for the long-term statistics import."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from custom_components.minol_energy.const import (
    SERVICE_COLD_WATER,
    SERVICE_HEATING,
    SERVICE_HOT_WATER,
)
from custom_components.minol_energy.statistics import (
    async_import_history,
    build_statistics,
)
from tests import conftest


def _period(period: str, heating: float, status: str = "UVI_AVAILABLE") -> dict:
    return {
        "period": period,
        "statusOverall": status,
        "consumptions": [
            {"service": SERVICE_HEATING, "energyValue": heating},
            {"service": SERVICE_HOT_WATER, "energyValue": 10.0},
            {"service": SERVICE_COLD_WATER, "energyValue": 1.0},
        ],
    }


_PERIODS = [
    _period("2026-01-31T00:00:00Z", 300.0),
    _period("2026-02-28T00:00:00Z", 250.0),
    _period("2026-03-31T00:00:00Z", 280.0),
]


class _FakeHass:
    class config:
        components = frozenset({"recorder", "sensor"})


class TestBuildStatistics:
    def test_sums_are_cumulative(self):
        stats = build_statistics(_PERIODS, SERVICE_HEATING)
        assert [s["state"] for s in stats] == [300.0, 250.0, 280.0]
        assert [s["sum"] for s in stats] == [300.0, 550.0, 830.0]

    def test_starts_are_month_firsts(self):
        stats = build_statistics(_PERIODS, SERVICE_HEATING)
        assert [s["start"] for s in stats] == [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
        ]

    def test_unordered_input_still_accumulates_chronologically(self):
        """A wrong order would silently corrupt every sum after it."""
        shuffled = [_PERIODS[2], _PERIODS[0], _PERIODS[1]]
        assert build_statistics(shuffled, SERVICE_HEATING) == build_statistics(
            _PERIODS, SERVICE_HEATING
        )

    def test_preliminary_period_skipped(self):
        periods = [*_PERIODS, _period("2026-04-30T00:00:00Z", 99.0, status="PENDING")]
        stats = build_statistics(periods, SERVICE_HEATING)
        assert len(stats) == 3
        assert stats[-1]["sum"] == 830.0

    def test_missing_service_skipped(self):
        periods = [
            *_PERIODS,
            {
                "period": "2026-04-30T00:00:00Z",
                "statusOverall": "UVI_AVAILABLE",
                "consumptions": [{"service": SERVICE_COLD_WATER, "energyValue": 2.0}],
            },
        ]
        assert len(build_statistics(periods, SERVICE_HEATING)) == 3

    def test_unparseable_period_skipped(self):
        periods = [*_PERIODS, _period("Januar 2026", 99.0)]
        assert len(build_statistics(periods, SERVICE_HEATING)) == 3

    def test_no_periods(self):
        assert build_statistics([], SERVICE_HEATING) == []


class TestAsyncImportHistory:
    def setup_method(self):
        conftest.IMPORTED_STATISTICS.clear()

    def test_imports_one_series_per_service(self):
        async_import_history(_FakeHass, _PERIODS)
        by_id = {
            meta["statistic_id"]: (meta, stats)
            for meta, stats in conftest.IMPORTED_STATISTICS
        }
        assert set(by_id) == {
            "minol_energy:heating_energy",
            "minol_energy:hot_water_energy",
            "minol_energy:cold_water_volume",
        }

        meta, stats = by_id["minol_energy:heating_energy"]
        assert meta["source"] == "minol_energy"  # must match the statistic_id prefix
        assert meta["has_sum"] is True
        assert meta["unit_of_measurement"] == "kWh"
        assert stats[-1]["sum"] == 830.0

        assert by_id["minol_energy:cold_water_volume"][0][
            "unit_of_measurement"
        ] == "m³"

    def test_repeated_import_is_stable(self):
        """Rows are keyed by start time — re-importing must not shift the sums."""
        async_import_history(_FakeHass, _PERIODS)
        first = list(conftest.IMPORTED_STATISTICS)
        conftest.IMPORTED_STATISTICS.clear()
        async_import_history(_FakeHass, _PERIODS)
        assert conftest.IMPORTED_STATISTICS == first

    def test_skipped_without_recorder(self):
        class _NoRecorder:
            class config:
                components = frozenset({"sensor"})

        async_import_history(_NoRecorder, _PERIODS)
        assert conftest.IMPORTED_STATISTICS == []

    def test_metadata_on_ha_without_mean_type(self, monkeypatch):
        """HA < 2025.2 has no StatisticMeanType — has_mean must carry it alone."""
        models = sys.modules["homeassistant.components.recorder.models"]
        monkeypatch.delattr(models, "StatisticMeanType")

        async_import_history(_FakeHass, _PERIODS)
        meta, _ = conftest.IMPORTED_STATISTICS[0]
        assert "mean_type" not in meta
        assert meta["has_mean"] is False
        assert meta["has_sum"] is True
