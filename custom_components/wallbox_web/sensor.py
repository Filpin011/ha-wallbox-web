"""Sensors of a station."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ERROR_CODES, STATION_STATUSES
from .coordinator import WallboxWebConfigEntry, WallboxWebCoordinator
from .entity import WallboxWebEntity, async_setup_station_entities, nested

PARALLEL_UPDATES = 0


def _status(s: dict[str, Any]) -> str | None:
    v = s.get("status")
    if v is None:
        return None
    return v if v in STATION_STATUSES else "undefined"


def _error(s: dict[str, Any]) -> str | None:
    errors = s.get("errors")
    if not isinstance(errors, list):
        return None
    if not errors:
        return "none"
    first = errors[0]
    code = str(first.get("code", "")).lower() if isinstance(first, dict) else ""
    return code if code in ERROR_CODES else "unknown"


def _num(*path: str) -> Callable[[dict[str, Any]], Any]:
    def get(s: dict[str, Any]) -> Any:
        v = nested(s, *path)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    return get


def _three_phase(coordinator: WallboxWebCoordinator, station_id: str) -> bool:
    station = coordinator.station(station_id) or {}
    if station.get("phases") == 3:
        return True
    return nested(coordinator.state(station_id) or {}, "current", "l2A") is not None


@dataclass(frozen=True, kw_only=True)
class WallboxSensorDescription(SensorEntityDescription):
    """Sensor description with its value getter."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None
    exists_fn: Callable[[WallboxWebCoordinator, str], bool] = lambda _c, _s: True
    unit_fn: Callable[[dict[str, Any]], str | None] | None = None


SENSORS: tuple[WallboxSensorDescription, ...] = (
    WallboxSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATION_STATUSES,
        value_fn=_status,
    ),
    WallboxSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=_num("power", "activeW"),
        attrs_fn=lambda s: {"charge_id": nested(s, "session", "chargeId")},
    ),
    WallboxSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_num("session", "energyWh"),
    ),
    WallboxSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=_num("energy", "lifetimeWh"),
        attrs_fn=lambda s: {"source": nested(s, "energy", "lifetimeSource")},
    ),
    WallboxSensorDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_num("session", "durationS"),
    ),
    WallboxSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        value_fn=_num("current", "l1A"),
    ),
    WallboxSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_num("current", "l2A"),
        exists_fn=_three_phase,
    ),
    WallboxSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=_num("current", "l3A"),
        exists_fn=_three_phase,
    ),
    WallboxSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=_num("voltageV"),
    ),
    WallboxSensorDescription(
        key="max_available_power",
        translation_key="max_available_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_num("power", "maxAvailableW"),
    ),
    WallboxSensorDescription(
        key="power_limit",
        translation_key="power_limit",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=1,
        value_fn=_num("power", "limitW"),
    ),
    WallboxSensorDescription(
        key="external_power",
        translation_key="external_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=_num("power", "externalW"),
    ),
    WallboxSensorDescription(
        key="error",
        translation_key="error",
        device_class=SensorDeviceClass.ENUM,
        options=ERROR_CODES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_error,
        attrs_fn=lambda s: {
            "errors": [str(e.get("code", "")).lower() for e in s.get("errors") or [] if isinstance(e, dict)]
        },
    ),
    WallboxSensorDescription(
        key="active_schedules",
        translation_key="active_schedules",
        value_fn=_num("schedules", "activeCount"),
    ),
    WallboxSensorDescription(
        key="last_charge_energy",
        translation_key="last_charge_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_num("lastCharge", "energyWh"),
        attrs_fn=lambda s: {"start": nested(s, "lastCharge", "start"), "end": nested(s, "lastCharge", "end")}
        if isinstance(s.get("lastCharge"), dict)
        else None,
    ),
    WallboxSensorDescription(
        key="last_charge_cost",
        translation_key="last_charge_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=_num("lastCharge", "cost"),
        unit_fn=lambda s: nested(s, "lastCharge", "currency") or "EUR",
    ),
    WallboxSensorDescription(
        key="last_charge_saving",
        translation_key="last_charge_saving",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=_num("lastCharge", "saving"),
        unit_fn=lambda s: nested(s, "lastCharge", "currency") or "EUR",
    ),
    WallboxSensorDescription(
        key="charge_card",
        translation_key="charge_card",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: nested(s, "session", "card"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Sensors of every station."""
    async_setup_station_entities(
        entry,
        async_add_entities,
        lambda coordinator, sid: [WallboxSensor(coordinator, sid, d) for d in SENSORS if d.exists_fn(coordinator, sid)],
    )


class WallboxSensor(WallboxWebEntity, SensorEntity):
    """A numeric / enum value of the station state."""

    entity_description: WallboxSensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.station_state)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.unit_fn is not None:
            return self.entity_description.unit_fn(self.station_state)
        return super().native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.station_state)
