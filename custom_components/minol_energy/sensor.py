"""Sensor platform for Minol Energy.

Sensors are derived from the eMonitoring dashboard JSON which contains
three blocks – one per consumption type (HEIZUNG, WARMWASSER, KALTWASSER).
Each block carries ``data1`` (yearly totals), ``data2_*`` (share of
building), and ``data3`` (per-m² values + DIN reference).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MinolConfigEntry
from .const import DOMAIN
from .coordinator import MinolDataCoordinator

_LOGGER = logging.getLogger(__name__)

# Map dashboard keyFigure to (icon, unit, device_class).
_TYPE_META: dict[str, tuple[str, str | None, SensorDeviceClass | None]] = {
    "HEIZUNG": ("mdi:radiator", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "WARMWASSER": ("mdi:water-boiler", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "KALTWASSER": ("mdi:water", UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER),
}


@dataclass(frozen=True, kw_only=True)
class _DashSensorDef:
    """Definition for a sensor extracted from the dashboard."""

    suffix: str  # e.g. "current_year", "previous_year"
    name_tpl: str  # e.g. "{type_text} Current Year"
    extractor: str  # Which data* array + index logic to use
    state_class: SensorStateClass | None = None


# We create these sensors for every consumption type in the dashboard.
_SENSOR_DEFS: list[_DashSensorDef] = [
    _DashSensorDef(
        suffix="current_year",
        name_tpl="{type_text} Current Year",
        extractor="data1_curr",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _DashSensorDef(
        suffix="previous_year",
        name_tpl="{type_text} Previous Year",
        extractor="data1_prev",
        state_class=SensorStateClass.TOTAL,
    ),
    _DashSensorDef(
        suffix="per_m2_current",
        name_tpl="{type_text} per m\u00b2 Current Year",
        extractor="data3_curr",
    ),
    _DashSensorDef(
        suffix="per_m2_previous",
        name_tpl="{type_text} per m\u00b2 Previous Year",
        extractor="data3_prev",
    ),
    _DashSensorDef(
        suffix="din_avg",
        name_tpl="{type_text} DIN Average",
        extractor="data3_ref",
    ),
    _DashSensorDef(
        suffix="building_share",
        name_tpl="{type_text} Building Share %",
        extractor="data2_pct",
    ),
]


def _extract(block: dict[str, Any], extractor: str) -> float | None:
    """Pull a value out of a dashboard block using the extractor key."""
    try:
        if extractor == "data1_curr":
            return _find_value(block["data1"], "CURR")
        if extractor == "data1_prev":
            return _find_value(block["data1"], "1PREV")
        if extractor == "data3_curr":
            return _find_value(block["data3"], "CURR", block["keyFigure"])
        if extractor == "data3_prev":
            return _find_value(block["data3"], "1PREV", block["keyFigure"])
        if extractor == "data3_ref":
            return _find_value(block["data3"], "CURR", "REF")
        if extractor == "data2_pct":
            # data2_2 current year: NE share label is like "12 %"
            for item in block.get("data2_2") or block.get("data2_1") or []:
                if item.get("categoryInt") == "NE":
                    label = item.get("label", "")
                    return float(label.replace("%", "").strip())
            return None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _find_value(
    items: list[dict[str, Any]],
    category_int: str,
    key_figure: str | None = None,
) -> float | None:
    """Find a value in a list of data points by categoryInt and optional keyFigure."""
    for item in items:
        if item.get("categoryInt") != category_int:
            continue
        if key_figure and item.get("keyFigure") != key_figure:
            continue
        val = item.get("value")
        return float(val) if val is not None else None
    return None


# ---------------------------------------------------------------------------
# Nice text labels for the German consumption types
# ---------------------------------------------------------------------------
_TYPE_TEXT = {
    "HEIZUNG": "Heating",
    "WARMWASSER": "Hot Water",
    "KALTWASSER": "Cold Water",
}


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: MinolConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Minol sensors from a config entry."""
    coordinator: MinolDataCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []

    # Tenant info sensor
    entities.append(MinolTenantInfoSensor(coordinator, entry))

    # Dashboard consumption sensors
    dashboard_blocks = (
        coordinator.data.get("dashboard", {}).get("dashboard") or []
    )
    for block in dashboard_blocks:
        kf = block.get("keyFigure", "UNKNOWN")
        type_text = _TYPE_TEXT.get(kf, kf.title())
        icon, unit, device_class = _TYPE_META.get(
            kf, ("mdi:gauge", None, None)
        )

        for sdef in _SENSOR_DEFS:
            # Per-m² and DIN sensors keep the same unit but suffix /m²
            is_per_m2 = "per_m2" in sdef.suffix or sdef.suffix == "din_avg"
            sensor_unit = f"{unit}/m\u00b2" if is_per_m2 and unit else unit
            sensor_icon = icon
            if sdef.suffix == "building_share":
                sensor_unit = "%"
                sensor_icon = "mdi:chart-pie"

            entities.append(
                MinolSensor(
                    coordinator=coordinator,
                    entry=entry,
                    key_figure=kf,
                    sensor_def=sdef,
                    type_text=type_text,
                    unit=sensor_unit,
                    icon_str=sensor_icon,
                    device_class=device_class if not is_per_m2 and sdef.suffix != "building_share" else None,
                )
            )

    # Per-room / per-meter sensors
    rooms = coordinator.data.get("rooms", {})
    for cons_type, meters in rooms.items():
        type_text = _TYPE_TEXT.get(cons_type, cons_type.title())
        icon, unit, device_class = _TYPE_META.get(
            cons_type, ("mdi:gauge", None, None)
        )
        for meter in meters:
            entities.append(
                MinolRoomSensor(
                    coordinator=coordinator,
                    entry=entry,
                    cons_type=cons_type,
                    meter=meter,
                    type_text=type_text,
                    unit=unit,
                    icon_str=icon,
                    device_class=device_class,
                )
            )

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Sensor entities
# ---------------------------------------------------------------------------

class MinolSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """A sensor derived from the eMonitoring dashboard."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        key_figure: str,
        sensor_def: _DashSensorDef,
        type_text: str,
        unit: str | None,
        icon_str: str,
        device_class: SensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._key_figure = key_figure
        self._sensor_def = sensor_def

        slug = f"{key_figure}_{sensor_def.suffix}".lower()
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_name = sensor_def.name_tpl.format(type_text=type_text)
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon_str
        self._attr_device_class = device_class
        self._attr_state_class = sensor_def.state_class
        self._attr_suggested_display_precision = 2
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Minol eMonitoring",
            "manufacturer": "Minol-ZENNER",
            "model": "eMonitoring",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> float | None:
        dashboard_blocks = (
            self.coordinator.data.get("dashboard", {}).get("dashboard") or []
        )
        for block in dashboard_blocks:
            if block.get("keyFigure") == self._key_figure:
                return _extract(block, self._sensor_def.extractor)
        return None


class MinolTenantInfoSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """Sensor showing the tenant address / property info."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tenant_info"
        self._attr_name = "Tenant Info"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Minol eMonitoring",
            "manufacturer": "Minol-ZENNER",
            "model": "eMonitoring",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.data.get("tenant_info", {})
        street = info.get("addrStreet", "")
        num = info.get("addrHouseNum", "")
        city = info.get("addrCity", "")
        postal = info.get("addrPostalCode", "")
        if street:
            return f"{street} {num}, {postal} {city}".strip()
        return info.get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.data.get("tenant_info", {})
        return {
            "name": info.get("name"),
            "email": info.get("email"),
            "property_number": info.get("lgnr", "").strip(),
            "unit_number": info.get("nenr"),
            "floor": info.get("geschossText"),
            "position": info.get("lageText"),
            "move_in_date": info.get("einzugMieter"),
            "user_number": info.get("userNumber"),
        }


class MinolRoomSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """A sensor for a single meter in a room (RAUM view)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        cons_type: str,
        meter: dict[str, Any],
        type_text: str,
        unit: str | None,
        icon_str: str,
        device_class: SensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._cons_type = cons_type
        self._ger_nr = meter.get("gerNr", "")
        self._internal_key = meter.get("internalKey", "")

        room_name = meter.get("raum", "Unknown")
        slug = f"{cons_type}_{self._ger_nr}".lower()
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_name = f"{type_text} {room_name} ({self._ger_nr[-4:]})"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon_str
        self._attr_device_class = device_class
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Minol eMonitoring",
            "manufacturer": "Minol-ZENNER",
            "model": "eMonitoring",
            "entry_type": "service",
        }

    def _find_meter(self) -> dict[str, Any] | None:
        """Find this meter in the current coordinator data."""
        meters = self.coordinator.data.get("rooms", {}).get(self._cons_type, [])
        for m in meters:
            if m.get("gerNr") == self._ger_nr:
                return m
        return None

    @property
    def native_value(self) -> float | None:
        meter = self._find_meter()
        if meter is None:
            return None
        val = meter.get("consumptionBew")
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        meter = self._find_meter()
        if meter is None:
            return {}
        return {
            "room": meter.get("raum"),
            "meter_serial": meter.get("gerNr"),
            "reading": meter.get("ablesung"),
            "initial_reading": meter.get("anfangsstand"),
            "raw_consumption": meter.get("consumption"),
            "weighting_factor": meter.get("bewertung"),
            "unit": meter.get("unit"),
        }
