"""Coordinator edge cases: poll errors, rate limit, event handling, stream failures."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wallbox_web.api import SseEvent, WallboxWebAuthError, WallboxWebConnectionError
from custom_components.wallbox_web.const import SSE_BACKOFF_MAX

from .fake_server import FakeWallboxWeb, make_station

STATION = "00012345"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_poll_errors(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    coordinator = await _setup(hass, entry)

    fake.fail_next["GET /api/v1/stations"] = (429, {"ok": False, "code": "rate_limited", "error": "slow"})
    await coordinator.async_refresh()
    assert not coordinator.last_update_success

    fake.v1 = False
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    fake.v1 = True

    with patch.object(coordinator.client, "stations", AsyncMock(side_effect=WallboxWebConnectionError("down"))):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success

    await coordinator.async_refresh()
    assert coordinator.last_update_success

    fake.tokens.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert any(f["context"]["source"] == SOURCE_REAUTH for f in hass.config_entries.flow.async_progress())


async def test_setup_connection_error(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with patch(
        "custom_components.wallbox_web.api.WallboxWebClient.server_info",
        AsyncMock(side_effect=WallboxWebConnectionError("down")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_poll_keeps_state_when_missing(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    coordinator = await _setup(hass, entry)
    original = coordinator.client.stations

    async def without_state(include_state: bool = True):
        return await original(include_state=False)

    with patch.object(coordinator.client, "stations", without_state):
        await coordinator.async_refresh()
    assert coordinator.state(STATION)["status"] == "idle"


async def test_events(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    coordinator = await _setup(hass, entry)
    coordinator.handle_event(SseEvent("hello", {"permissions": ["read"]}))
    assert not coordinator.can_control
    coordinator.handle_event(SseEvent("ping", "not a dict"))

    # state of an unknown station → refresh fetches it
    fake.add(make_station("00077777", "Nuova"))
    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh:
        coordinator.handle_event(SseEvent("state", {"id": "00077777", "status": "idle"}))
        coordinator.handle_event(SseEvent("charge_finished", {"stationId": STATION}))
        await hass.async_block_till_done()
    assert refresh.await_count == 2
    assert coordinator.station("00077777") is None


async def test_stream_failures(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    fake.sse_enabled = False
    coordinator = await _setup(hass, entry)
    coordinator._sse_task.cancel()

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) >= 3:
            raise RuntimeError("stop")

    async def boom():
        raise ValueError("unexpected")
        yield  # pragma: no cover

    with (
        patch("custom_components.wallbox_web.coordinator.asyncio.sleep", fake_sleep),
        patch.object(coordinator.client, "events", boom),
        pytest.raises(RuntimeError),
    ):
        await coordinator._sse_loop()
    assert sleeps == [5, 10, 20]
    assert "unexpected" in (coordinator.sse_error or "")

    sleeps.clear()
    with (
        patch("custom_components.wallbox_web.coordinator.asyncio.sleep", fake_sleep),
        pytest.raises(RuntimeError),
    ):
        await coordinator._sse_loop()
    assert sleeps[0] == SSE_BACKOFF_MAX

    async def unauthorized():
        raise WallboxWebAuthError("revoked")
        yield  # pragma: no cover

    with (
        patch.object(coordinator.client, "events", unauthorized),
        patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh,
    ):
        await coordinator._sse_loop()
    refresh.assert_awaited_once()
    assert coordinator.sse_error == "unauthorized"


async def test_control_errors(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    coordinator = await _setup(hass, entry)
    with (
        patch.object(coordinator.client, "command", AsyncMock(side_effect=WallboxWebConnectionError("down"))),
        pytest.raises(HomeAssistantError) as err,
    ):
        await coordinator.async_control(STATION, "start")
    assert err.value.translation_key == "cannot_connect"

    with (
        patch.object(coordinator.client, "command", AsyncMock(side_effect=WallboxWebAuthError("revoked"))),
        pytest.raises(HomeAssistantError) as err,
    ):
        await coordinator.async_control(STATION, "start")
    assert err.value.translation_key == "invalid_auth"

    fake.fail_next[f"POST /api/v1/stations/{STATION}/commands/start"] = (418, {"ok": False, "code": "teapot"})
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_control(STATION, "start")
    assert err.value.translation_key == "command_failed"

    # an answer without state → refresh
    with (
        patch.object(coordinator.client, "command", AsyncMock(return_value={"ok": True})),
        patch.object(coordinator, "async_request_refresh", AsyncMock()) as refresh,
    ):
        await coordinator.async_control(STATION, "start")
    refresh.assert_awaited_once()
