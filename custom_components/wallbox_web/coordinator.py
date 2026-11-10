"""Data coordinator: push (SSE /api/v1/events) with a 30 s polling fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SseEvent,
    WallboxWebApiError,
    WallboxWebAuthError,
    WallboxWebClient,
    WallboxWebConnectionError,
    WallboxWebError,
    WallboxWebNotSupportedError,
)
from .const import DOMAIN, LOGGER, PERMISSION_CONTROL, POLL_INTERVAL, SSE_BACKOFF_MAX, SSE_BACKOFF_MIN

type WallboxWebConfigEntry = ConfigEntry[WallboxWebCoordinator]


@dataclass(slots=True)
class WallboxData:
    """Snapshot of every station of the server. Compared with == (always_update=False)."""

    stations: dict[str, dict[str, Any]] = field(default_factory=dict)
    states: dict[str, dict[str, Any]] = field(default_factory=dict)


# API error codes that have a translated exception message in strings.json ("exceptions").
_TRANSLATED_CODES = {
    "not_allowed_in_state",
    "free_mode",
    "busy",
    "procedure_failed",
    "login_required",
    "insufficient_permission",
    "station_unreachable",
    "station_timeout",
    "rate_limited",
    "invalid_request",
    "station_not_found",
}


def _split_station(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    station = {k: v for k, v in raw.items() if k != "state"}
    state = raw.get("state")
    return station, state if isinstance(state, dict) else None


class WallboxWebCoordinator(DataUpdateCoordinator[WallboxData]):
    """One coordinator per Wallbox WEB server (config entry); data of all its stations."""

    config_entry: WallboxWebConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WallboxWebConfigEntry, client: WallboxWebClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.info: dict[str, Any] = {}
        self.sse_connected = False
        self.sse_last_event: str | None = None
        self.sse_error: str | None = None
        self._sse_task: asyncio.Task[None] | None = None
        # Registry id of the server ("service") device, parent of the stations (set by async_setup_entry).
        self.server_device_id: str | None = None

    # ---- properties --------------------------------------------------------------------------

    @property
    def instance_id(self) -> str:
        return str(self.info.get("instanceId", ""))

    @property
    def can_control(self) -> bool:
        """The token has the `control` permission (buttons, number, select)."""
        perms = self.info.get("permissions")
        return isinstance(perms, list) and PERMISSION_CONTROL in perms

    def station(self, station_id: str) -> dict[str, Any] | None:
        return self.data.stations.get(station_id) if self.data else None

    def state(self, station_id: str) -> dict[str, Any] | None:
        return self.data.states.get(station_id) if self.data else None

    # ---- polling -----------------------------------------------------------------------------

    async def _async_setup(self) -> None:
        try:
            self.info = await self.client.server_info()
        except WallboxWebAuthError as err:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_auth") from err
        except WallboxWebNotSupportedError as err:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="api_not_supported") from err
        except WallboxWebError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_update_data(self) -> WallboxData:
        try:
            raw = await self.client.stations(include_state=True)
        except WallboxWebAuthError as err:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_auth") from err
        except WallboxWebNotSupportedError as err:
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="api_not_supported") from err
        except WallboxWebApiError as err:
            retry = err.retry_after if err.status == 429 else None
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
                retry_after=retry,
            ) from err
        except WallboxWebError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        data = WallboxData()
        previous = self.data
        for item in raw:
            station, state = _split_station(item)
            sid = station["id"]
            data.stations[sid] = station
            if state is not None:
                data.states[sid] = state
            elif previous and sid in previous.states:
                data.states[sid] = previous.states[sid]
        return data

    # ---- push --------------------------------------------------------------------------------

    def start_push(self) -> None:
        """Start the SSE listener (cancelled automatically when the entry unloads)."""
        if self._sse_task is None:
            self._sse_task = self.config_entry.async_create_background_task(
                self.hass, self._sse_loop(), name=f"{DOMAIN} event stream"
            )

    async def _sse_loop(self) -> None:
        backoff = SSE_BACKOFF_MIN
        while True:
            try:
                async for ev in self.client.events():
                    if not self.sse_connected:
                        LOGGER.debug("Event stream connected")
                        self.sse_connected = True
                        self.sse_error = None
                        backoff = SSE_BACKOFF_MIN
                    self.sse_last_event = ev.event
                    self.handle_event(ev)
                self.sse_error = "stream closed"
            except asyncio.CancelledError:
                raise
            except WallboxWebAuthError:
                # The poll raises ConfigEntryAuthFailed and starts the reauth flow.
                self.sse_connected = False
                self.sse_error = "unauthorized"
                await self.async_request_refresh()
                return
            except WallboxWebNotSupportedError as err:
                self.sse_error = str(err)
                backoff = SSE_BACKOFF_MAX
            except WallboxWebError as err:
                self.sse_error = str(err)
            except Exception as err:  # noqa: BLE001 - never let the background task die silently
                LOGGER.exception("Unexpected error in the event stream")
                self.sse_error = repr(err)
            if self.sse_connected:
                LOGGER.debug("Event stream lost (%s), polling every %s", self.sse_error, POLL_INTERVAL)
            self.sse_connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, SSE_BACKOFF_MAX)

    def handle_event(self, ev: SseEvent) -> None:
        """Apply one SSE event to the coordinator data."""
        if self.data is None or not isinstance(ev.data, dict):
            return
        d = ev.data
        if ev.event == "hello":
            perms = d.get("permissions")
            if isinstance(perms, list):
                self.info = {**self.info, "permissions": perms}
            return
        if ev.event == "state" and isinstance(d.get("id"), str):
            sid = d["id"]
            if sid not in self.data.stations:
                # A state for a station we do not know yet: let the poll fetch its identity.
                self.hass.async_create_task(self.async_request_refresh())
                return
            self._publish(states={**self.data.states, sid: d})
        elif ev.event == "station_added" and isinstance(d.get("id"), str):
            station, state = _split_station(d)
            states = self.data.states if state is None else {**self.data.states, station["id"]: state}
            self._publish(stations={**self.data.stations, station["id"]: station}, states=states)
        elif ev.event == "station_removed" and isinstance(d.get("id"), str):
            sid = d["id"]
            self._publish(
                stations={k: v for k, v in self.data.stations.items() if k != sid},
                states={k: v for k, v in self.data.states.items() if k != sid},
            )
        elif ev.event == "charge_finished":
            # lastCharge (cost, saving) changed: the next state carries it, but fetch now.
            self.hass.async_create_task(self.async_request_refresh())

    def _publish(
        self, *, stations: dict[str, dict[str, Any]] | None = None, states: dict[str, dict[str, Any]] | None = None
    ) -> None:
        assert self.data is not None
        self.async_set_updated_data(
            WallboxData(
                stations=stations if stations is not None else self.data.stations,
                states=states if states is not None else self.data.states,
            )
        )

    # ---- control -----------------------------------------------------------------------------

    async def async_control(self, station_id: str, action: str, value: Any = None) -> None:
        """Run a command / setting and apply the returned state. Raises translated HomeAssistantError."""
        try:
            if action == "max_current":
                result = await self.client.set_max_current(station_id, int(value))
            elif action == "behaviour_mode":
                result = await self.client.set_behaviour_mode(station_id, str(value))
            else:
                result = await self.client.command(station_id, action)
        except WallboxWebAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="invalid_auth") from err
        except WallboxWebApiError as err:
            key = err.code if err.code in _TRANSLATED_CODES else "command_failed"
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={
                    "detail": err.detail or "",
                    "status": str(err.data.get("status", "")),
                    "error": err.message,
                },
            ) from err
        except (WallboxWebConnectionError, WallboxWebNotSupportedError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        state = result.get("state") if isinstance(result, dict) else None
        if isinstance(state, dict) and self.data is not None and station_id in self.data.stations:
            self._publish(states={**self.data.states, station_id: state})
        else:
            await self.async_request_refresh()
