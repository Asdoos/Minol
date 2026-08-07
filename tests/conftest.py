"""Stub out homeassistant modules so the integration can be imported without HA.

Most of homeassistant is faked with MagicMock, but anything the integration uses
as a *base class* or compares by identity has to be a real object: two MagicMock
bases make ``class X(CoordinatorEntity[T], SensorEntity)`` fail with a metaclass
conflict, and ``state_class is SensorStateClass.TOTAL`` needs a real enum.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from unittest.mock import MagicMock

# Register stubs for every homeassistant namespace touched by the package
# __init__.py and its siblings.  Must happen before any test module is imported.
_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.diagnostics",
    "homeassistant.components.sensor",
    "homeassistant.components.recorder",
    "homeassistant.components.recorder.models",
    "homeassistant.components.recorder.statistics",
    "voluptuous",
]
for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())


class _Subscriptable:
    """Base that tolerates ``Base[T]`` the way HA's generic entity classes do."""

    def __class_getitem__(cls, _item):
        return cls


class SensorStateClass(StrEnum):
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class SensorDeviceClass(StrEnum):
    ENERGY = "energy"
    WATER = "water"
    WEIGHT = "weight"
    MONETARY = "monetary"


class UnitOfEnergy(StrEnum):
    KILO_WATT_HOUR = "kWh"


class UnitOfVolume(StrEnum):
    CUBIC_METERS = "m³"


class UnitOfMass(StrEnum):
    KILOGRAMS = "kg"


class SensorEntity:
    """Minimal stand-in for HA's SensorEntity (``_attr_*`` → read-only property)."""

    _attr_state_class: SensorStateClass | None = None
    _attr_device_class: SensorDeviceClass | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_translation_key: str | None = None
    _attr_unique_id: str | None = None
    _attr_name: str | None = None
    _attr_icon: str | None = None
    _attr_device_info: dict | None = None

    @property
    def state_class(self) -> SensorStateClass | None:
        return self._attr_state_class

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._attr_device_class

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._attr_native_unit_of_measurement

    @property
    def unique_id(self) -> str | None:
        return self._attr_unique_id

    @property
    def translation_key(self) -> str | None:
        return self._attr_translation_key


class CoordinatorEntity(_Subscriptable):
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator


class DataUpdateCoordinator(_Subscriptable):
    def __init__(self, *args, **kwargs) -> None:
        pass


_sensor = sys.modules["homeassistant.components.sensor"]
_sensor.SensorEntity = SensorEntity
_sensor.SensorStateClass = SensorStateClass
_sensor.SensorDeviceClass = SensorDeviceClass

_const = sys.modules["homeassistant.const"]
_const.UnitOfEnergy = UnitOfEnergy
_const.UnitOfVolume = UnitOfVolume
_const.UnitOfMass = UnitOfMass

_coord = sys.modules["homeassistant.helpers.update_coordinator"]
_coord.CoordinatorEntity = CoordinatorEntity
_coord.DataUpdateCoordinator = DataUpdateCoordinator

sys.modules["homeassistant.config_entries"].ConfigEntry = _Subscriptable

# statistics.py: StatisticData/StatisticMetaData are TypedDicts (plain dicts at
# runtime), @callback is a no-op marker, and every import is captured so tests
# can inspect what would have gone to the recorder.
class StatisticMeanType(StrEnum):
    NONE = "none"


IMPORTED_STATISTICS: list[tuple[dict, list[dict]]] = []

_models = sys.modules["homeassistant.components.recorder.models"]
_models.StatisticData = dict
_models.StatisticMetaData = dict
_models.StatisticMeanType = StatisticMeanType

sys.modules["homeassistant.components.recorder.statistics"].async_add_external_statistics = (
    lambda hass, metadata, statistics: IMPORTED_STATISTICS.append((metadata, statistics))
)

sys.modules["homeassistant.core"].callback = lambda func: func
