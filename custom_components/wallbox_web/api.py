"""Async client of the Wallbox WEB HTTP API v1 (docs/API.md).

No Home Assistant imports: the client only needs an aiohttp session, so it can be tested (and later
published as a library) on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_VERSION, COMMAND_TIMEOUT, REQUEST_TIMEOUT, SSE_READ_TIMEOUT


class WallboxWebError(Exception):
    """Base error of the client."""


class WallboxWebConnectionError(WallboxWebError):
    """The server could not be reached (DNS, TCP, TLS, timeout, 5xx without JSON)."""


class WallboxWebAuthError(WallboxWebError):
    """401: missing, invalid or revoked token."""


class WallboxWebNotSupportedError(WallboxWebError):
    """The server answers but has no /api/v1 (older Wallbox WEB) or is not Wallbox WEB at all."""


class WallboxWebApiError(WallboxWebError):
    """A JSON error answer of the API: HTTP status + `code` (+ optional detail)."""

    def __init__(self, status: int, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.data = data or {}

    @property
    def detail(self) -> str | None:
        """`detail` of a 422 procedure_failed."""
        d = self.data.get("detail")
        return d if isinstance(d, str) else None

    @property
    def retry_after(self) -> float | None:
        """Seconds from a 429 answer."""
        v = self.data.get("retry_after")
        return float(v) if isinstance(v, (int, float)) else None


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One Server-Sent Event."""

    event: str
    data: Any
    id: str | None = None


def normalize_url(url: str) -> str:
    """`https://host/` → `https://host` (keeps a path prefix, e.g. behind a reverse proxy)."""
    url = url.strip()
    while url.endswith("/"):
        url = url[:-1]
    return url


class WallboxWebClient:
    """Client of one Wallbox WEB server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str,
        *,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self.url = normalize_url(url)
        self._token = token
        self._ssl: bool | None = None if verify_ssl else False

    # ---- plumbing ----------------------------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def _api(self, path: str) -> str:
        return f"{self.url}/api/v{API_VERSION}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                self._api(path),
                headers=self._headers,
                json=json_body,
                params=params,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                return await self._decode(resp, path)
        except WallboxWebError:
            raise
        except TimeoutError as err:
            raise WallboxWebConnectionError(f"Timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise WallboxWebConnectionError(f"Cannot reach {self.url}: {err}") from err

    @staticmethod
    async def _decode(resp: aiohttp.ClientResponse, path: str) -> Any:
        body: Any = None
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            try:
                body = await resp.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                body = None
        if resp.status < 300:
            if body is None:
                # A 200 HTML page: some other web app (or a login page of a proxy) answers on this URL.
                raise WallboxWebNotSupportedError(f"{path}: not a JSON answer")
            return body
        data = body if isinstance(body, dict) else {}
        code = str(data.get("code") or "")
        message = str(data.get("error") or resp.reason or "")
        if resp.status == 401:
            raise WallboxWebAuthError(message or "unauthorized")
        if resp.status == 404 and code in ("", "not_found"):
            raise WallboxWebNotSupportedError(f"{path}: 404")
        if resp.status >= 500 and not code:
            raise WallboxWebConnectionError(f"{path}: HTTP {resp.status}")
        if resp.status == 429:
            ra = resp.headers.get("retry-after")
            if ra and ra.isdigit():
                data = {**data, "retry_after": int(ra)}
        raise WallboxWebApiError(resp.status, code or f"http_{resp.status}", message, data)

    @staticmethod
    def _sid(station_id: str) -> str:
        return quote(station_id, safe="")

    # ---- endpoints ---------------------------------------------------------------------------

    async def server_info(self) -> dict[str, Any]:
        """GET /api/v1 → ServerInfo. Raises WallboxWebNotSupportedError if it is not v1."""
        info = await self._request("GET", "")
        if not isinstance(info, dict) or info.get("apiVersion") != API_VERSION or not info.get("instanceId"):
            raise WallboxWebNotSupportedError("unexpected /api/v1 answer")
        return info

    async def stations(self, *, include_state: bool = True) -> list[dict[str, Any]]:
        """GET /api/v1/stations (with each station's state)."""
        body = await self._request("GET", "/stations", params={"include": "state"} if include_state else None)
        stations = body.get("stations") if isinstance(body, dict) else None
        if not isinstance(stations, list):
            raise WallboxWebNotSupportedError("unexpected /stations answer")
        return [s for s in stations if isinstance(s, dict) and isinstance(s.get("id"), str)]

    async def station_state(self, station_id: str) -> dict[str, Any]:
        """GET /api/v1/stations/{id}/state."""
        return await self._request("GET", f"/stations/{self._sid(station_id)}/state")

    async def command(self, station_id: str, command: str) -> dict[str, Any]:
        """POST /api/v1/stations/{id}/commands/{command} – waits for the procedure (≤ 90 s)."""
        return await self._request(
            "POST",
            f"/stations/{self._sid(station_id)}/commands/{command}",
            json_body={},
            timeout=COMMAND_TIMEOUT,
        )

    async def set_max_current(self, station_id: str, amps: int) -> dict[str, Any]:
        """PUT /api/v1/stations/{id}/max-current."""
        return await self._request(
            "PUT", f"/stations/{self._sid(station_id)}/max-current", json_body={"amps": amps}, timeout=COMMAND_TIMEOUT
        )

    async def set_behaviour_mode(self, station_id: str, mode: str) -> dict[str, Any]:
        """PUT /api/v1/stations/{id}/behaviour-mode."""
        return await self._request(
            "PUT",
            f"/stations/{self._sid(station_id)}/behaviour-mode",
            json_body={"mode": mode},
            timeout=COMMAND_TIMEOUT,
        )

    async def charges(self, station_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """GET /api/v1/stations/{id}/charges?limit=."""
        body = await self._request("GET", f"/stations/{self._sid(station_id)}/charges", params={"limit": str(limit)})
        charges = body.get("charges") if isinstance(body, dict) else None
        return charges if isinstance(charges, list) else []

    async def current_curve(self, station_id: str) -> dict[str, Any]:
        """GET /api/v1/stations/{id}/charges/current/curve → {charge, samples}."""
        return await self._request("GET", f"/stations/{self._sid(station_id)}/charges/current/curve")

    # ---- Server-Sent Events ------------------------------------------------------------------

    async def events(self) -> AsyncIterator[SseEvent]:
        """GET /api/v1/events: yields events until the stream ends (then returns) or fails (raises)."""
        try:
            async with self._session.get(
                self._api("/events"),
                headers={**self._headers, "Accept": "text/event-stream"},
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=None, connect=REQUEST_TIMEOUT, sock_read=SSE_READ_TIMEOUT),
            ) as resp:
                if resp.status != 200 or "text/event-stream" not in resp.headers.get("content-type", ""):
                    await self._decode(resp, "/events")
                    raise WallboxWebNotSupportedError("/events: not an event stream")
                async for ev in parse_sse(resp.content):
                    yield ev
        except WallboxWebError:
            raise
        except TimeoutError as err:
            raise WallboxWebConnectionError("event stream timed out") from err
        except aiohttp.ClientError as err:
            raise WallboxWebConnectionError(f"event stream failed: {err}") from err


async def parse_sse(stream: aiohttp.StreamReader | Any) -> AsyncIterator[SseEvent]:
    """Minimal SSE parser (WHATWG): `event:`, `data:` (multi-line), `id:`, comments, blank line = dispatch.

    `data` is decoded as JSON when possible, else kept as a string. Events without data are skipped.
    """
    event = "message"
    data_lines: list[str] = []
    last_id: str | None = None
    buffer = b""
    while True:
        chunk = await stream.readany() if hasattr(stream, "readany") else await stream.read(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            nl = buffer.find(b"\n")
            if nl < 0:
                break
            raw, buffer = buffer[:nl], buffer[nl + 1 :]
            line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
            if line == "":
                if data_lines:
                    text = "\n".join(data_lines)
                    try:
                        payload: Any = json.loads(text)
                    except ValueError:
                        payload = text
                    yield SseEvent(event, payload, last_id)
                event, data_lines = "message", []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event = value or "message"
            elif field == "data":
                data_lines.append(value)
            elif field == "id":
                last_id = value
        await asyncio.sleep(0)
