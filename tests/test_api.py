"""HTTP client and SSE parser against the fake server."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.wallbox_web.api import (
    WallboxWebApiError,
    WallboxWebAuthError,
    WallboxWebClient,
    WallboxWebConnectionError,
    WallboxWebNotSupportedError,
    normalize_url,
    parse_sse,
)

from .fake_server import INSTANCE_ID, TOKEN_FULL, TOKEN_READ, FakeWallboxWeb


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def client(session, fake: FakeWallboxWeb, token: str = TOKEN_FULL) -> WallboxWebClient:
    return WallboxWebClient(session, fake.url + "/", token)  # type: ignore[attr-defined]


def test_normalize_url() -> None:
    assert normalize_url(" https://wallbox.example.com/// ") == "https://wallbox.example.com"
    assert normalize_url("https://example.com/wallbox/") == "https://example.com/wallbox"


async def test_server_info_and_stations(session, fake: FakeWallboxWeb) -> None:
    c = client(session, fake)
    info = await c.server_info()
    assert info["instanceId"] == INSTANCE_ID
    assert info["permissions"] == ["read", "control"]
    stations = await c.stations()
    assert stations[0]["id"] == "00012345"
    assert stations[0]["state"]["status"] == "idle"
    no_state = await c.stations(include_state=False)
    assert "state" not in no_state[0]


async def test_auth_error(session, fake: FakeWallboxWeb) -> None:
    with pytest.raises(WallboxWebAuthError):
        await client(session, fake, "wbx_wrong").server_info()


async def test_not_supported_404(session, fake: FakeWallboxWeb) -> None:
    fake.v1 = False
    with pytest.raises(WallboxWebNotSupportedError):
        await client(session, fake).server_info()


async def test_not_supported_html(session, fake: FakeWallboxWeb) -> None:
    c = WallboxWebClient(session, fake.url + "/html", TOKEN_FULL)  # type: ignore[attr-defined]
    with pytest.raises(WallboxWebNotSupportedError):
        await c.server_info()


async def test_connection_error(session, monkeypatch) -> None:
    c = WallboxWebClient(session, "http://127.0.0.1:9", TOKEN_FULL)

    def refuse(*_args, **_kwargs):
        raise aiohttp.ClientConnectionError("connection refused")

    # no real socket in tests (pytest-homeassistant blocks them): simulate a refused connection
    monkeypatch.setattr(session, "request", refuse)
    monkeypatch.setattr(session, "get", refuse)
    with pytest.raises(WallboxWebConnectionError):
        await c.server_info()


async def test_command_and_errors(session, fake: FakeWallboxWeb) -> None:
    c = client(session, fake)
    result = await c.command("00012345", "start")
    assert result["state"]["status"] == "charging"
    with pytest.raises(WallboxWebApiError) as err:
        await c.command("00012345", "start")
    assert err.value.status == 409
    assert err.value.code == "not_allowed_in_state"
    with pytest.raises(WallboxWebApiError) as err:
        await c.command("nope", "stop")
    assert err.value.code == "station_not_found"
    fake.fail_next["POST /api/v1/stations/00012345/commands/pause"] = (
        422,
        {"ok": False, "code": "procedure_failed", "error": "Rejected", "detail": "occupied"},
    )
    with pytest.raises(WallboxWebApiError) as err:
        await c.command("00012345", "pause")
    assert err.value.detail == "occupied"


async def test_rate_limited(session, fake: FakeWallboxWeb) -> None:
    fake.fail_next["GET /api/v1/stations"] = (429, {"ok": False, "code": "rate_limited", "error": "slow down"})
    with pytest.raises(WallboxWebApiError) as err:
        await client(session, fake).stations()
    assert err.value.code == "rate_limited"
    assert err.value.retry_after == 7


async def test_read_only_token(session, fake: FakeWallboxWeb) -> None:
    c = client(session, fake, TOKEN_READ)
    assert (await c.server_info())["permissions"] == ["read"]
    with pytest.raises(WallboxWebApiError) as err:
        await c.set_max_current("00012345", 10)
    assert err.value.status == 403
    assert err.value.code == "insufficient_permission"


async def test_settings(session, fake: FakeWallboxWeb) -> None:
    c = client(session, fake)
    r = await c.set_max_current("00012345", 10)
    assert r["maxCurrent"]["valueA"] == 10
    with pytest.raises(WallboxWebApiError) as err:
        await c.set_max_current("00012345", 99)
    assert err.value.code == "invalid_request"
    r = await c.set_behaviour_mode("00012345", "free")
    assert r["state"]["behaviourMode"] == "free"


async def test_event_stream(session, fake: FakeWallboxWeb) -> None:
    c = client(session, fake)
    received = []

    async def consume() -> None:
        async for ev in c.events():
            received.append(ev)
            if len(received) == 3:
                return

    task = asyncio.create_task(consume())
    for _ in range(100):
        if fake.sse_clients:
            break
        await asyncio.sleep(0.01)
    fake.push_state("00012345", status="charging")
    await asyncio.wait_for(task, 5)
    assert [e.event for e in received] == ["hello", "state", "state"]
    assert received[2].data["status"] == "charging"


class _Chunks:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def readany(self) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


async def test_parse_sse_edge_cases() -> None:
    stream = _Chunks(
        [
            b"retry: 5000\r\n: hi\r\n\r\nevent: st",
            b'ate\r\ndata: {"a":\r\ndata: 1}\r\nid: 9\r\n\r\n',
            b"data: plain text\n\nevent: empty\n\n",
            b"event: ping\ndata: {}\n\n",
        ]
    )
    events = [e async for e in parse_sse(stream)]
    assert events[0].event == "state"
    assert events[0].data == {"a": 1}
    assert events[0].id == "9"
    assert events[1].event == "message"
    assert events[1].data == "plain text"
    assert events[2].event == "ping"
    assert len(events) == 3
