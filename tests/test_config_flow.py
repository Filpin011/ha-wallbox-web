"""Config flow: user, errors, reauth, reconfigure, Supervisor discovery."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wallbox_web.const import CONF_SOURCE_ADDON, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN

from .fake_server import INSTANCE_ID, TOKEN_FULL, TOKEN_READ, FakeWallboxWeb

NO_SETUP = "custom_components.wallbox_web.async_setup_entry"


async def test_user_flow(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: fake.url + "/", CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True},  # type: ignore[attr-defined]
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wallbox WEB (127.0.0.1)"
    assert result["data"] == {CONF_URL: fake.url, CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True}  # type: ignore[attr-defined]
    assert result["result"].unique_id == INSTANCE_ID


async def test_user_flow_errors_then_recover(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    url = fake.url  # type: ignore[attr-defined]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "wallbox.example.com", CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_TOKEN: "wbx_bad", CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://127.0.0.1:9", CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    fake.v1 = False
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: url, CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {"base": "api_not_supported"}

    fake.v1 = True
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: url, CONF_TOKEN: TOKEN_FULL, CONF_VERIFY_SSL: False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VERIFY_SSL] is False


async def test_user_flow_already_configured(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: fake.url, CONF_TOKEN: TOKEN_READ, CONF_VERIFY_SSL: True},  # type: ignore[attr-defined]
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_TOKEN] == TOKEN_READ


async def test_reauth(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "wbx_bad"})
    assert result["errors"] == {"base": "invalid_auth"}
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN_READ})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == TOKEN_READ


async def test_reauth_other_server(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="another-instance",
        data={CONF_URL: fake.url, CONF_TOKEN: "x", CONF_VERIFY_SSL: True},  # type: ignore[attr-defined]
    )
    other.add_to_hass(hass)
    result = await other.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN_FULL})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_reconfigure(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "ftp://x", CONF_VERIFY_SSL: True}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: fake.url + "/", CONF_VERIFY_SSL: False},  # type: ignore[attr-defined]
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_VERIFY_SSL] is False


def _discovery(fake: FakeWallboxWeb, **config: object) -> HassioServiceInfo:
    port = int(fake.url.rsplit(":", 1)[1])  # type: ignore[attr-defined]
    cfg = {"host": "127.0.0.1", "port": port, "api_token": TOKEN_FULL, "version": "1.5.0", **config}
    return HassioServiceInfo(config=cfg, name="Wallbox WEB", slug="abcd1234_wallbox_web", uuid="1234")


async def test_hassio_discovery(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(fake))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wallbox WEB (add-on)"
    assert result["data"][CONF_SOURCE_ADDON] is True
    assert result["data"][CONF_URL].startswith("http://127.0.0.1:")


async def test_hassio_discovery_updates_existing(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    old = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INSTANCE_ID,
        data={CONF_URL: "http://old-host:3000", CONF_TOKEN: "wbx_old", CONF_VERIFY_SSL: True, CONF_SOURCE_ADDON: True},
    )
    old.add_to_hass(hass)
    with patch(NO_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(fake)
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert old.data[CONF_TOKEN] == TOKEN_FULL


async def test_hassio_discovery_invalid(hass: HomeAssistant, fake: FakeWallboxWeb) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(fake, api_token="")
    )
    assert result["reason"] == "invalid_discovery_info"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(fake, api_token="wbx_bad")
    )
    assert result["reason"] == "invalid_auth"
