"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wallbox_web.const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN

from .fake_server import INSTANCE_ID, TOKEN_FULL, FakeWallboxWeb, make_station


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Load custom_components/ in every test."""
    return


@pytest.fixture
async def fake(socket_enabled: Any) -> AsyncGenerator[FakeWallboxWeb]:
    """A running fake Wallbox WEB server with one station (a real localhost socket: `socket_enabled`)."""
    server = FakeWallboxWeb()
    server.add(make_station())
    server.url = await server.start()  # type: ignore[attr-defined]
    yield server
    await server.close()


@pytest.fixture
def entry(fake: FakeWallboxWeb) -> MockConfigEntry:
    """A config entry pointing at the fake server (not yet added to hass)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Wallbox WEB (127.0.0.1)",
        unique_id=INSTANCE_ID,
        data={CONF_URL: fake.url, CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True},  # type: ignore[attr-defined]
    )
