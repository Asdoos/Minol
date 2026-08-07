"""Sensor platform for Minol Energy.

Sensors are derived from the mobile app's Mulesoft Experience API.
The API returns monthly consumption periods; each period contains
one entry per service type (100=Heating, 200=Hot Water, 300=Cold Water).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfMass, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MinolConfigEntry
from .api import MinolApiClient
from .const import (
    CONF_COLD_WATER_PRICE,
    CONF_HEATING_PRICE,
    CONF_HOT_WATER_PRICE,
    DOMAIN,
    ROOM_TYPE_NAMES,
    ROOM_TYPE_NAMES_DE,
    SERVICE_COLD_WATER,
    SERVICE_HEATING,
    SERVICE_HOT_WATER,
)
from .coordinator import MinolDataCoordinator
from .statistics import build_statistics

_LOGGER = logging.getLogger(__name__)

_DEVICE_INFO_BASE = {
    "manufacturer": "Minol-ZENNER",
    "model": "eMonitoring",
    "entry_type": "service",
}


def _build_device_info(entry_id: str) -> dict:
    """Return the shared device-info dict for all Minol sensors."""
    return {
        **_DEVICE_INFO_BASE,
        "identifiers": {(DOMAIN, entry_id)},
        "name": "Minol Energy",
    }


@dataclass(frozen=True)
class _ServiceMeta:
    service_code: str
    type_text: str      # English service name (room sensor _attr_name)
    type_text_de: str   # German service name (room sensor _attr_name)
    icon: str
    energy_unit: str
    service_unit: str  # raw meter unit shown in attributes
    device_class: SensorDeviceClass | None
    translation_key: str       # main consumption sensor
    total_translation_key: str  # energy-dashboard-compatible total_increasing sensor
    co2_translation_key: str   # CO₂ sensor ("" for cold water)
    cost_translation_key: str  # cost sensor


_SERVICES: list[_ServiceMeta] = [
    _ServiceMeta(
        service_code=SERVICE_HEATING,
        type_text="Heating",
        type_text_de="Heizung",
        icon="mdi:radiator",
        energy_unit=UnitOfEnergy.KILO_WATT_HOUR,
        service_unit="EH",
        device_class=SensorDeviceClass.ENERGY,
        translation_key="heating_latest_month",
        total_translation_key="heating_energy_total",
        co2_translation_key="heating_co2_latest_month",
        cost_translation_key="heating_cost",
    ),
    _ServiceMeta(
        service_code=SERVICE_HOT_WATER,
        type_text="Hot Water",
        type_text_de="Warmwasser",
        icon="mdi:water-boiler",
        energy_unit=UnitOfEnergy.KILO_WATT_HOUR,
        service_unit="m³",
        device_class=SensorDeviceClass.ENERGY,
        translation_key="hot_water_latest_month",
        total_translation_key="hot_water_energy_total",
        co2_translation_key="hot_water_co2_latest_month",
        cost_translation_key="hot_water_cost",
    ),
    _ServiceMeta(
        service_code=SERVICE_COLD_WATER,
        type_text="Cold Water",
        type_text_de="Kaltwasser",
        icon="mdi:water",
        energy_unit=UnitOfVolume.CUBIC_METERS,
        service_unit="m³",
        device_class=SensorDeviceClass.WATER,
        translation_key="cold_water_latest_month",
        total_translation_key="cold_water_energy_total",
        co2_translation_key="",
        cost_translation_key="cold_water_cost",
    ),
]

_PRICE_CONF_KEY: dict[str, str] = {
    SERVICE_HEATING: CONF_HEATING_PRICE,
    SERVICE_HOT_WATER: CONF_HOT_WATER_PRICE,
    SERVICE_COLD_WATER: CONF_COLD_WATER_PRICE,
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

    lang = hass.config.language
    use_de = lang.startswith("de")
    room_names = ROOM_TYPE_NAMES_DE if use_de else ROOM_TYPE_NAMES

    entities: list[SensorEntity] = [
        MinolTenantInfoSensor(coordinator, entry),
    ]

    latest = coordinator.data.get("latest_consumption", {})
    active_services = {
        c.get("service") for c in latest.get("consumptions", [])
    }

    for svc in _SERVICES:
        if svc.service_code not in active_services:
            continue
        # Latest month energy / volume
        entities.append(
            MinolConsumptionSensor(
                coordinator=coordinator,
                entry=entry,
                service=svc,
                field="energyValue",
                suffix="latest_month",
                translation_key=svc.translation_key,
                unit=svc.energy_unit,
                state_class=SensorStateClass.TOTAL,
                device_class=svc.device_class,
                icon=svc.icon,
            )
        )
        # Lifetime total over every finalised period — the same running sum the
        # external statistics import uses, so entity and Energy Dashboard agree.
        entities.append(
            MinolTotalSensor(
                coordinator=coordinator,
                entry=entry,
                service=svc,
                field="energyValue",
                suffix="energy_total",
                translation_key=svc.total_translation_key,
                unit=svc.energy_unit,
                state_class=SensorStateClass.TOTAL,
                device_class=svc.device_class,
                icon=svc.icon,
            )
        )
        # CO2 sensor (cold water has no CO₂ equivalent)
        if svc.co2_translation_key:
            entities.append(
                MinolConsumptionSensor(
                    coordinator=coordinator,
                    entry=entry,
                    service=svc,
                    field="co2kg",
                    suffix="co2_latest_month",
                    translation_key=svc.co2_translation_key,
                    unit=UnitOfMass.KILOGRAMS,
                    state_class=SensorStateClass.MEASUREMENT,
                    device_class=SensorDeviceClass.WEIGHT,
                    icon="mdi:molecule-co2",
                )
            )
        # Cost sensor (only when price configured)
        price = entry.options.get(_PRICE_CONF_KEY.get(svc.service_code, ""), 0.0)
        if price:
            entities.append(
                MinolCostSensor(
                    coordinator=coordinator,
                    entry=entry,
                    service=svc,
                    price=float(price),
                )
            )

    async_add_entities(entities)

    # Room-level sensors are added dynamically so they appear even when the
    # first coordinator refresh returns a period without device-level data
    # (e.g. the current month is still preliminary).  The listener re-runs
    # after every coordinator update and adds any new (room_id, service_code)
    # pairs it finds.
    rooms_added: set[tuple[str, str]] = set()

    def _add_room_sensors() -> None:
        if not coordinator.data:
            _LOGGER.debug("_add_room_sensors: coordinator.data is None, skipping")
            return
        device_period = coordinator.data.get("latest_consumption", {})
        if not device_period:
            _LOGGER.debug("_add_room_sensors: no consumption period available yet")
            return

        total_devices = sum(
            len(cons.get("devices", []))
            for cons in device_period.get("consumptions", [])
        )
        _LOGGER.debug(
            "_add_room_sensors: scanning period=%s status=%s total_devices=%d rooms_known=%d",
            device_period.get("period"),
            device_period.get("statusOverall"),
            total_devices,
            len(rooms_added),
        )

        new_entities: list[SensorEntity] = []
        for svc in _SERVICES:
            for cons in device_period.get("consumptions", []):
                if cons.get("service") != svc.service_code:
                    continue
                for device in cons.get("devices", []):
                    room_id = device.get("room")
                    if not room_id:
                        continue
                    key = (room_id, svc.service_code)
                    if key not in rooms_added:
                        rooms_added.add(key)
                        new_entities.append(
                            MinolRoomSensor(
                                coordinator=coordinator,
                                entry=entry,
                                service=svc,
                                room_id=room_id,
                                room_names=room_names,
                                use_de=use_de,
                            )
                        )
        if new_entities:
            _LOGGER.debug(
                "Adding %d new room sensor(s)",
                len(new_entities),
            )
            async_add_entities(new_entities)
        elif total_devices == 0:
            _LOGGER.debug(
                "_add_room_sensors: period %s has no devices — "
                "room sensors cannot be created. "
                "Run: uv run pytest tests/test_api_live.py::test_devices_in_get_all_data -v -s",
                device_period.get("period"),
            )

    # Run once immediately with the data already in the coordinator, then
    # re-run after every successful coordinator refresh.
    _add_room_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_room_sensors))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_consumption_entry(
    data: dict[str, Any], service_code: str
) -> dict[str, Any]:
    """Return the consumption dict for a specific service in the latest period."""
    latest = data.get("latest_consumption", {})
    for cons in latest.get("consumptions", []):
        if cons.get("service") == service_code:
            return cons
    return {}


# ---------------------------------------------------------------------------
# Sensor entities
# ---------------------------------------------------------------------------


class MinolConsumptionSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """A sensor showing a single field for one service type in the latest period."""

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        service: _ServiceMeta,
        field: str,
        suffix: str,
        translation_key: str,
        unit: str | None,
        state_class: SensorStateClass | None,
        device_class: SensorDeviceClass | None,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._service = service
        self._field = field

        slug = f"{service.service_code}_{suffix}".lower()
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_translation_key = translation_key
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_device_info = _build_device_info(entry.entry_id)

    @property
    def native_value(self) -> float | None:
        cons = _get_consumption_entry(
            self.coordinator.data, self._service.service_code
        )
        val = cons.get(self._field)
        return float(val) if val is not None else None

    @property
    def last_reset(self) -> datetime | None:
        """Start of the billing period the current value accumulates from.

        The API reports consumption *per period*, so the value drops back at
        every period boundary.  Without last_reset, HA's statistics engine only
        adds the *increase* over the previous period's value — a month of
        250 kWh following one of 300 kWh would contribute 0 to the total.
        A changed last_reset tells HA the counter restarted, so the whole new
        period value is added to the long-term sum.
        """
        if self.state_class is not SensorStateClass.TOTAL:
            return None  # CO₂ sensor is a measurement — last_reset is invalid there
        return MinolApiClient.get_period_start(
            self.coordinator.data.get("latest_consumption", {})
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        latest = self.coordinator.data.get("latest_consumption", {})
        cons = _get_consumption_entry(
            self.coordinator.data, self._service.service_code
        )
        attrs: dict[str, Any] = {
            "period": latest.get("period"),
            "status": latest.get("statusOverall"),
            "estimated": cons.get("estimated"),
            "service_value": cons.get("serviceValue"),
            "service_unit": cons.get("serviceUnit") or self._service.service_unit,
            "energy_unit": cons.get("energyUnit"),
        }
        return {k: v for k, v in attrs.items() if v is not None}


class MinolTotalSensor(MinolConsumptionSensor):
    """Running total of every finalised period since move-in.

    "Gesamt" has to mean *gesamt*: the plain per-period value used to sit here,
    so the total read identical to the latest month.  build_statistics() already
    produces the cumulative series for the external statistics — its last row is
    that lifetime sum, and reusing it keeps entity and dashboard in step.
    """

    @property
    def native_value(self) -> float | None:
        stats = build_statistics(
            self.coordinator.data.get("consumptions", []), self._service.service_code
        )
        return round(stats[-1]["sum"], 3) if stats else None

    @property
    def last_reset(self) -> datetime | None:
        return None  # cumulative — the counter never restarts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        stats = build_statistics(
            self.coordinator.data.get("consumptions", []), self._service.service_code
        )
        return {"periods": len(stats)}


class MinolTenantInfoSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """Sensor showing property / tenant info from the user profile."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"
    _attr_translation_key = "tenant_info"

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tenant_info"
        self._attr_device_info = _build_device_info(entry.entry_id)

    @property
    def native_value(self) -> str | None:
        profile = self.coordinator.data.get("profile", {})
        addr = profile.get("billingUnitAddress", {})
        street = addr.get("street", "")
        num = addr.get("houseNumber", "")
        city = addr.get("city", "")
        postal = addr.get("zip", "")
        if street:
            return f"{street} {num}, {postal} {city}".strip(", ")
        return profile.get("billingUnit")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profile = self.coordinator.data.get("profile", {})
        ref = profile.get("residentialUnitReference", {})
        addr = profile.get("billingUnitAddress", {})
        return {
            "user_id": profile.get("userID"),
            "email": profile.get("eMail"),
            "first_name": profile.get("firstName"),
            "last_name": profile.get("lastName"),
            "billing_unit": profile.get("billingUnit"),
            "residential_unit_id": ref.get("residentialUnitID"),
            "floor": ref.get("floor"),
            "position": ref.get("position"),
            "move_in_date": profile.get("moveInDate"),
            "city": addr.get("city"),
            "country": addr.get("country"),
        }


class MinolCostSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """Estimated cost: latest month consumption × configured price per unit."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "\u20ac"
    _attr_icon = "mdi:currency-eur"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        service: _ServiceMeta,
        price: float,
    ) -> None:
        super().__init__(coordinator)
        self._service = service
        self._price = price

        slug = f"{service.service_code}_cost".lower()
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_translation_key = service.cost_translation_key
        self._attr_device_info = _build_device_info(entry.entry_id)

    @property
    def native_value(self) -> float | None:
        cons = _get_consumption_entry(
            self.coordinator.data, self._service.service_code
        )
        energy = cons.get("energyValue")
        if energy is None:
            return None
        return round(float(energy) * self._price, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"price_per_unit": self._price}


class MinolRoomSensor(CoordinatorEntity[MinolDataCoordinator], SensorEntity):
    """Aggregated energy/volume sensor for one room and service type.

    Sums all device readings (e.g. multiple HKV heat cost allocators) for the
    same room ID and service within the latest consumption period.
    """

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: MinolDataCoordinator,
        entry: MinolConfigEntry,
        service: _ServiceMeta,
        room_id: str,
        room_names: dict[str, str],
        use_de: bool,
    ) -> None:
        super().__init__(coordinator)
        self._service = service
        self._room_id = room_id

        room_name = room_names.get(room_id) or f"Room {room_id.lstrip('0') or room_id}"
        type_text = service.type_text_de if use_de else service.type_text
        slug = f"room_{room_id}_{service.service_code}"
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_name = f"{room_name} {type_text}"
        self._attr_native_unit_of_measurement = service.energy_unit
        self._attr_device_class = service.device_class
        self._attr_icon = service.icon
        self._attr_device_info = _build_device_info(entry.entry_id)

    def _device_period(self) -> dict[str, Any]:
        """Return the latest consumption period (contains device-level data)."""
        return (self.coordinator.data or {}).get("latest_consumption", {})

    def _get_devices(self) -> list[dict[str, Any]]:
        """Return all devices for this room + service in the device period."""
        for cons in self._device_period().get("consumptions", []):
            if cons.get("service") == self._service.service_code:
                return [
                    d for d in cons.get("devices", [])
                    if d.get("room") == self._room_id
                ]
        return []

    @property
    def native_value(self) -> float | None:
        devices = self._get_devices()
        if not devices:
            return None
        return sum(float(d.get("energyValue") or 0) for d in devices)

    @property
    def last_reset(self) -> datetime | None:
        """Start of the billing period — see MinolConsumptionSensor.last_reset."""
        return MinolApiClient.get_period_start(self._device_period())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        latest = self._device_period()
        devices = self._get_devices()
        attrs: dict[str, Any] = {
            "period": latest.get("period"),
            "room_id": self._room_id,
            "room_name": ROOM_TYPE_NAMES.get(self._room_id),
            "device_count": len(devices),
        }
        if len(devices) == 1:
            d = devices[0]
            attrs["device_id"] = d.get("deviceid")
            attrs["device_value"] = d.get("deviceValue")
            attrs["device_unit"] = d.get("deviceUnit")
            attrs["estimated"] = d.get("estimated")
            attrs["is_data_missing"] = d.get("isDataMissing")
        elif len(devices) > 1:
            attrs["devices"] = [
                {
                    "device_id": d.get("deviceid"),
                    "energy_value": d.get("energyValue"),
                    "device_value": d.get("deviceValue"),
                    "estimated": d.get("estimated"),
                }
                for d in devices
            ]
        return {k: v for k, v in attrs.items() if v is not None}
