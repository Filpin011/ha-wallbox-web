"""Binary sensors of a station."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WallboxWebConfigEntry
from .entity import WallboxWebEntity, async_setup_station_entities, nested

PARALLEL_UPDATES = 0


def _bool(*path: str) -> Callable[[dict[str, Any]], bool | None]:
    def get(s: dict[str, Any]) -> bool | None:
        v = nested(s, *path)
        return v if isinstance(v, bool) else None

    return get


def _problem(s: dict[str, Any]) -> bool | None:
    if "status" not in s and "errors" not in s:
        return None
    return bool(s.get("errors")) or s.get("status") == "faulted"


@dataclass(frozen=True, kw_only=True)
class WallboxBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor description with its value getter."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    always_available: bool = False


BINARY_SENSORS: tuple[WallboxBinaryDescription, ...] = (
    WallboxBinaryDescription(
        key="plugged",
        translation_key="plugged",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=_bool("plugged"),
    ),
    WallboxBinaryDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda s: s.get("status") == "charging" if "status" in s else None,
    ),
    WallboxBinaryDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_problem,
    ),
    WallboxBinaryDescription(
        key="schedule_active",
        translation_key="schedule_active",
        value_fn=_bool("schedules", "anyActive"),
    ),
    WallboxBinaryDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: bool(s.get("online")),
        always_available=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Binary sensors of every station."""
    async_setup_station_entities(
        entry,
        async_add_entities,
        lambda coordinator, sid: [WallboxBinarySensor(coordinator, sid, d) for d in BINARY_SENSORS],
    )


class WallboxBinarySensor(WallboxWebEntity, BinarySensorEntity):
    """A boolean of the station state."""

    entity_description: WallboxBinaryDescription

    @property
    def available(self) -> bool:
        if self.entity_description.always_available:
            return self.coordinator.last_update_success and self.coordinator.station(self.station_id) is not None
        return super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.station_state)
