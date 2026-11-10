"""Base entity: one Home Assistant device per station."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, SOCKET_TYPE_NAMES
from .coordinator import WallboxWebConfigEntry, WallboxWebCoordinator


def station_device_info(coordinator: WallboxWebCoordinator, station: dict[str, Any]) -> DeviceInfo:
    """Device registry entry of a station."""
    socket = SOCKET_TYPE_NAMES.get(str(station.get("socketType") or ""))
    product = station.get("productCode") or None
    info = DeviceInfo(
        identifiers={(DOMAIN, station["id"])},
        manufacturer=MANUFACTURER,
        model=product or socket or "Wallbox",
        name=station.get("name") or station["id"],
        serial_number=station.get("serial") or None,
        sw_version=station.get("firmware") or None,
        hw_version=station.get("hardware") or None,
    )
    if coordinator.server_device_id:
        info["via_device_id"] = coordinator.server_device_id
    url = station.get("appUrl")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        info["configuration_url"] = url
    return info


class WallboxWebEntity(CoordinatorEntity[WallboxWebCoordinator]):
    """Entity of one station."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WallboxWebCoordinator, station_id: str, description: EntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self.station_id = station_id
        self._attr_unique_id = f"{station_id}_{description.key}"
        station = coordinator.station(station_id) or {"id": station_id}
        self._attr_device_info = station_device_info(coordinator, station)

    @property
    def station_state(self) -> dict[str, Any]:
        """Latest StationState ({} when unknown)."""
        return self.coordinator.state(self.station_id) or {}

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.station(self.station_id) is None:
            return False
        return bool(self.station_state.get("online"))


def nested(state: dict[str, Any], *path: str) -> Any:
    """state["a"]["b"] or None."""
    cur: Any = state
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


@callback
def async_setup_station_entities(
    entry: WallboxWebConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[WallboxWebCoordinator, str], Iterable[Entity]],
) -> None:
    """Add the entities of every station now and of the stations that appear later (dynamic devices)."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        if coordinator.data is None:
            return
        new = [sid for sid in coordinator.data.stations if sid not in known]
        if not new:
            return
        known.update(new)
        entities: list[Entity] = []
        for sid in new:
            entities.extend(factory(coordinator, sid))
        async_add_entities(entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
