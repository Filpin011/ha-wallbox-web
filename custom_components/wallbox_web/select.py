"""Behaviour mode: Free / Personal."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import BEHAVIOUR_MODES, BEHAVIOUR_MODES_WRITABLE, DOMAIN
from .coordinator import WallboxWebConfigEntry
from .entity import WallboxWebEntity, async_setup_station_entities

PARALLEL_UPDATES = 1

BEHAVIOUR_MODE = SelectEntityDescription(
    key="behaviour_mode",
    translation_key="behaviour_mode",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Behaviour mode of every station."""
    async_setup_station_entities(
        entry, async_add_entities, lambda coordinator, sid: [WallboxBehaviourMode(coordinator, sid, BEHAVIOUR_MODE)]
    )


class WallboxBehaviourMode(WallboxWebEntity, SelectEntity):
    """Free (no card needed) or Personal (start from app / card). Net and Ocpp are read-only."""

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.can_control

    @property
    def options(self) -> list[str]:
        current = self.current_option
        if current is not None and current not in BEHAVIOUR_MODES_WRITABLE:
            return [*BEHAVIOUR_MODES_WRITABLE, current]
        return list(BEHAVIOUR_MODES_WRITABLE)

    @property
    def current_option(self) -> str | None:
        v = self.station_state.get("behaviourMode")
        return v if v in BEHAVIOUR_MODES else None

    async def async_select_option(self, option: str) -> None:
        if option not in BEHAVIOUR_MODES_WRITABLE:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_not_writable",
                translation_placeholders={"mode": option},
            )
        await self.coordinator.async_control(self.station_id, "behaviour_mode", option)
