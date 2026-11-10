"""Max charging current (6 A … the station maximum)."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WallboxWebConfigEntry
from .entity import WallboxWebEntity, async_setup_station_entities, nested

PARALLEL_UPDATES = 1

MAX_CURRENT = NumberEntityDescription(
    key="max_current",
    translation_key="max_current",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_step=1,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
)

DEFAULT_MIN = 6
DEFAULT_MAX = 32


async def async_setup_entry(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Max current of every station."""
    async_setup_station_entities(
        entry, async_add_entities, lambda coordinator, sid: [WallboxMaxCurrent(coordinator, sid, MAX_CURRENT)]
    )


class WallboxMaxCurrent(WallboxWebEntity, NumberEntity):
    """6 A … rotary switch maximum."""

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.can_control

    @property
    def native_value(self) -> float | None:
        v = nested(self.station_state, "maxCurrent", "valueA")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @property
    def native_min_value(self) -> float:
        v = nested(self.station_state, "maxCurrent", "min")
        return float(v) if isinstance(v, (int, float)) else DEFAULT_MIN

    @property
    def native_max_value(self) -> float:
        v = nested(self.station_state, "maxCurrent", "max")
        return float(v) if isinstance(v, (int, float)) else DEFAULT_MAX

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_control(self.station_id, "max_current", round(value))
