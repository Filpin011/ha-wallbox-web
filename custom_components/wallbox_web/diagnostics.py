"""Diagnostics (token, URL host, serials, addresses and card UIDs redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, CONF_URL
from .coordinator import WallboxWebConfigEntry

TO_REDACT = {
    CONF_TOKEN,
    CONF_URL,
    "api_token",
    "serial",
    "address",
    "card",
    "appUrl",
    "curveUrl",
    "instanceId",
    "id",
    "stationId",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: WallboxWebConfigEntry) -> dict[str, Any]:
    """Diagnostics of one server."""
    coordinator = entry.runtime_data
    data = coordinator.data
    # Stations keyed by position, not by serial, so nothing identifying leaks through the keys.
    stations = []
    if data is not None:
        for sid, station in data.stations.items():
            stations.append({"station": station, "state": data.states.get(sid)})
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "title": "**REDACTED**", "version": entry.version},
            "server": coordinator.info,
            "coordinator": {
                "last_update_success": coordinator.last_update_success,
                "update_interval": str(coordinator.update_interval),
                "sse_connected": coordinator.sse_connected,
                "sse_last_event": coordinator.sse_last_event,
                "sse_error": coordinator.sse_error,
                "can_control": coordinator.can_control,
            },
            "stations": stations,
        },
        TO_REDACT,
    )
