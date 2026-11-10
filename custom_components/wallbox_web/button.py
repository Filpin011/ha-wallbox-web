"""Charge commands: Start, Pause, Resume, Stop (enabled only when the station allows the action)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import COMMANDS
from .coordinator import WallboxWebConfigEntry
from .entity import WallboxWebEntity, async_setup_station_entities, nested

# Commands wait for the station procedure: one at a time per platform.
PARALLEL_UPDATES = 1

BUTTONS: tuple[ButtonEntityDescription, ...] = tuple(
    ButtonEntityDescription(key=cmd, translation_key=cmd) for cmd in COMMANDS
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Command buttons of every station."""
    async_setup_station_entities(
        entry,
        async_add_entities,
        lambda coordinator, sid: [WallboxCommandButton(coordinator, sid, d) for d in BUTTONS],
    )


class WallboxCommandButton(WallboxWebEntity, ButtonEntity):
    """Runs one charge procedure; available only when the app would enable the same button."""

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.can_control
            and nested(self.station_state, "commands", self.entity_description.key) is True
        )

    async def async_press(self) -> None:
        await self.coordinator.async_control(self.station_id, self.entity_description.key)
