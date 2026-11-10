"""In-process fake of the Wallbox WEB API v1 (docs/API.md) for the tests.

Implements the contract the integration codes against, so the tests exercise the real HTTP client, the
SSE parser and the coordinator end to end over 127.0.0.1.
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

TOKEN_FULL = "wbx_full_token_for_tests_000000000000000000000000000"
TOKEN_READ = "wbx_read_token_for_tests_000000000000000000000000000"
INSTANCE_ID = "4f1c2b8e-0000-4000-8000-000000000001"


def make_station(sid: str = "00012345", name: str = "Garage", **state: Any) -> dict[str, Any]:
    """A Station with its state (only fake data, no real serials)."""
    st: dict[str, Any] = {
        "id": sid,
        "online": True,
        "updatedAt": "2026-11-10T18:00:00.000Z",
        "status": "idle",
        "statusCode": 1,
        "plugged": False,
        "evConnected": False,
        "power": {"activeW": 0, "maxAvailableW": 7400, "limitW": 6900, "externalW": None},
        "current": {"l1A": 0.0, "l2A": None, "l3A": None},
        "voltageV": 231,
        "session": {
            "active": False,
            "energyWh": 0,
            "durationS": 0,
            "startedAt": None,
            "sessionId": None,
            "card": None,
            "chargeId": None,
        },
        "energy": {"lifetimeWh": 1234567, "lifetimeSource": "meter"},
        "maxCurrent": {"valueA": 16, "min": 6, "max": 32},
        "behaviourMode": "personal",
        "errors": [],
        "schedules": {"activeCount": 0, "anyActive": False},
        "lastCharge": {
            "id": 7,
            "start": "2026-11-09T20:00:00.000Z",
            "end": "2026-11-09T23:00:00.000Z",
            "energyWh": 18450,
            "durationS": 10800,
            "peakW": 7300,
            "card": None,
            "cost": 4.43,
            "saving": 12.1,
            "currency": "EUR",
            "curveUrl": f"/api/v1/stations/{sid}/charges/7/curve",
        },
        "commands": {"start": True, "stop": False, "pause": False, "resume": False},
    }
    for k, v in state.items():
        if isinstance(v, dict) and isinstance(st.get(k), dict):
            st[k] = {**st[k], **v}
        else:
            st[k] = v
    return {
        "id": sid,
        "name": name,
        "serial": sid,
        "productCode": "205.W000-X",
        "socketType": "type2",
        "phases": 1,
        "firmware": "V5.1.1.0 646",
        "hardware": "rev B",
        "address": "192.0.2.10",
        "appUrl": "https://wallbox.example.com/home",
        "state": st,
    }


class FakeWallboxWeb:
    """The fake server and its state."""

    def __init__(self) -> None:
        self.stations: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, list[str]] = {TOKEN_FULL: ["read", "control"], TOKEN_READ: ["read"]}
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_next: dict[str, tuple[int, dict[str, Any]]] = {}
        self.v1 = True
        self.sse_enabled = True
        self._sse_queues: list[asyncio.Queue[tuple[str, Any] | None]] = []
        self.server: TestServer | None = None
        self.curve: dict[str, Any] = {"charge": None, "samples": []}

    # ---- lifecycle -------------------------------------------------------------------------

    async def start(self) -> str:
        app = web.Application()
        r = app.router
        r.add_get("/api/v1", self._info)
        r.add_get("/api/v1/stations", self._stations)
        r.add_get("/api/v1/stations/{id}/state", self._state)
        r.add_post("/api/v1/stations/{id}/commands/{cmd}", self._command)
        r.add_put("/api/v1/stations/{id}/max-current", self._max_current)
        r.add_put("/api/v1/stations/{id}/behaviour-mode", self._behaviour)
        r.add_get("/api/v1/stations/{id}/charges/current/curve", self._curve)
        r.add_get("/api/v1/events", self._events)
        r.add_get("/html", self._html)
        self.server = TestServer(app, host="127.0.0.1")
        await self.server.start_server()
        return str(self.server.make_url("")).rstrip("/")

    async def close(self) -> None:
        for q in self._sse_queues:
            q.put_nowait(None)
        if self.server:
            await self.server.close()

    # ---- helpers for tests -----------------------------------------------------------------

    def add(self, station: dict[str, Any]) -> None:
        self.stations[station["id"]] = copy.deepcopy(station)

    def push(self, event: str, data: Any) -> None:
        for q in self._sse_queues:
            q.put_nowait((event, data))

    def push_state(self, sid: str, **changes: Any) -> dict[str, Any]:
        st = self.stations[sid]["state"]
        for k, v in changes.items():
            st[k] = {**st[k], **v} if isinstance(v, dict) and isinstance(st.get(k), dict) else v
        self.push("state", copy.deepcopy(st))
        return st

    @property
    def sse_clients(self) -> int:
        return len(self._sse_queues)

    # ---- handlers --------------------------------------------------------------------------

    def _auth(self, request: web.Request, need: str = "read") -> web.Response | None:
        h = request.headers.get("Authorization", "")
        token = h.removeprefix("Bearer ").strip()
        perms = self.tokens.get(token)
        if perms is None:
            return web.json_response(
                {"ok": False, "code": "unauthorized", "error": "Authentication required."}, status=401
            )
        if need not in perms:
            return web.json_response(
                {"ok": False, "code": "insufficient_permission", "error": "Missing permission", "required": need},
                status=403,
            )
        if not self.v1:
            return web.json_response({"ok": False, "code": "not_found", "error": "Not found"}, status=404)
        key = f"{request.method} {request.path}"
        if key in self.fail_next:
            status, body = self.fail_next.pop(key)
            headers = {"retry-after": "7"} if status == 429 else None
            return web.json_response(body, status=status, headers=headers)
        return None

    def _token_perms(self, request: web.Request) -> list[str]:
        return self.tokens.get(request.headers.get("Authorization", "").removeprefix("Bearer ").strip(), [])

    def _station(self, request: web.Request) -> dict[str, Any] | web.Response:
        s = self.stations.get(request.match_info["id"])
        if s is None:
            return web.json_response({"ok": False, "code": "station_not_found", "error": "Unknown station"}, status=404)
        return s

    async def _info(self, request: web.Request) -> web.Response:
        if (err := self._auth(request)) is not None:
            return err
        return web.json_response(
            {
                "apiVersion": 1,
                "instanceId": INSTANCE_ID,
                "name": "Wallbox WEB",
                "appVersion": "1.5.0",
                "appUrl": "https://wallbox.example.com",
                "permissions": self._token_perms(request),
                "timeZone": "Europe/Rome",
                "serverTime": "2026-11-10T18:00:00.000Z",
            }
        )

    async def _stations(self, request: web.Request) -> web.Response:
        if (err := self._auth(request)) is not None:
            return err
        self.calls.append(("GET", "/stations", None))
        include = request.query.get("include") == "state"
        out = []
        for s in self.stations.values():
            item = {k: v for k, v in s.items() if k != "state"}
            if include:
                item["state"] = s["state"]
            out.append(item)
        return web.json_response({"stations": out})

    async def _state(self, request: web.Request) -> web.Response:
        if (err := self._auth(request)) is not None:
            return err
        s = self._station(request)
        return s if isinstance(s, web.Response) else web.json_response(s["state"])

    async def _command(self, request: web.Request) -> web.Response:
        if (err := self._auth(request, "control")) is not None:
            return err
        s = self._station(request)
        if isinstance(s, web.Response):
            return s
        cmd = request.match_info["cmd"]
        self.calls.append(("POST", f"/commands/{cmd}", None))
        st = s["state"]
        if not st["commands"].get(cmd):
            return web.json_response(
                {"ok": False, "code": "not_allowed_in_state", "error": "Not allowed", "status": st["status"]},
                status=409,
            )
        if cmd in ("start", "resume"):
            st.update(status="charging", statusCode=4)
            st["commands"] = {"start": False, "stop": True, "pause": True, "resume": False}
        elif cmd == "pause":
            st.update(status="suspended_evse", statusCode=6)
            st["commands"] = {"start": False, "stop": True, "pause": False, "resume": True}
        elif cmd == "stop":
            st.update(status="idle", statusCode=1)
            st["commands"] = {"start": True, "stop": False, "pause": False, "resume": False}
        return web.json_response({"ok": True, "command": cmd, "state": st})

    async def _max_current(self, request: web.Request) -> web.Response:
        if (err := self._auth(request, "control")) is not None:
            return err
        s = self._station(request)
        if isinstance(s, web.Response):
            return s
        body = await request.json()
        self.calls.append(("PUT", "/max-current", body))
        amps = body.get("amps")
        mc = s["state"]["maxCurrent"]
        if not isinstance(amps, int) or not mc["min"] <= amps <= mc["max"]:
            return web.json_response({"ok": False, "code": "invalid_request", "error": "amps out of range"}, status=400)
        mc["valueA"] = amps
        return web.json_response({"ok": True, "maxCurrent": mc, "state": s["state"]})

    async def _behaviour(self, request: web.Request) -> web.Response:
        if (err := self._auth(request, "control")) is not None:
            return err
        s = self._station(request)
        if isinstance(s, web.Response):
            return s
        body = await request.json()
        self.calls.append(("PUT", "/behaviour-mode", body))
        s["state"]["behaviourMode"] = body["mode"]
        return web.json_response({"ok": True, "behaviourMode": body["mode"], "state": s["state"]})

    async def _curve(self, request: web.Request) -> web.Response:
        if (err := self._auth(request)) is not None:
            return err
        s = self._station(request)
        return s if isinstance(s, web.Response) else web.json_response(self.curve)

    async def _html(self, request: web.Request) -> web.Response:
        return web.Response(text="<html>login</html>", content_type="text/html")

    async def _events(self, request: web.Request) -> web.StreamResponse:
        if (err := self._auth(request)) is not None:
            return err
        if not self.sse_enabled:
            return web.json_response({"ok": False, "code": "not_found", "error": "Not found"}, status=404)
        resp = web.StreamResponse(headers={"content-type": "text/event-stream", "cache-control": "no-store"})
        await resp.prepare(request)
        q: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
        self._sse_queues.append(q)

        async def send(event: str, data: Any) -> None:
            await resp.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())

        try:
            await resp.write(b"retry: 5000\n: comment line\n\n")
            await send("hello", {"apiVersion": 1, "instanceId": INSTANCE_ID, "permissions": self._token_perms(request)})
            for s in self.stations.values():
                await send("state", s["state"])
            while True:
                item = await q.get()
                if item is None:
                    break
                await send(*item)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._sse_queues.remove(q)
        return resp
