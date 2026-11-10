"""Config flow: self-hosted server (URL + API token) or the add-on (Supervisor discovery)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
import voluptuous as vol

from .api import (
    WallboxWebAuthError,
    WallboxWebClient,
    WallboxWebConnectionError,
    WallboxWebError,
    WallboxWebNotSupportedError,
    normalize_url,
)
from .const import CONF_SOURCE_ADDON, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN, LOGGER

URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): URL_SELECTOR,
        vol.Required(CONF_TOKEN): TOKEN_SELECTOR,
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR})
RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): URL_SELECTOR,
        vol.Required(CONF_VERIFY_SSL, default=True): bool,
    }
)


def _title(url: str, addon: bool = False) -> str:
    if addon:
        return "Wallbox WEB (add-on)"
    host = urlparse(url).hostname or url
    return f"Wallbox WEB ({host})"


class WallboxWebConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wallbox WEB."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def _validate(self, url: str, token: str, verify_ssl: bool) -> tuple[dict[str, Any] | None, str | None]:
        """GET /api/v1 then /api/v1/stations. Returns (server info, None) or (None, error key)."""
        client = WallboxWebClient(
            async_get_clientsession(self.hass, verify_ssl=verify_ssl), url, token, verify_ssl=verify_ssl
        )
        try:
            info = await client.server_info()
            await client.stations(include_state=False)
        except WallboxWebAuthError:
            return None, "invalid_auth"
        except WallboxWebNotSupportedError:
            return None, "api_not_supported"
        except WallboxWebConnectionError:
            return None, "cannot_connect"
        except WallboxWebError:
            LOGGER.exception("Unexpected answer validating %s", url)
            return None, "unknown"
        return info, None

    # ---- self-hosted -------------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """URL + API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            if not url.startswith(("http://", "https://")):
                errors[CONF_URL] = "invalid_url"
            else:
                info, error = await self._validate(url, user_input[CONF_TOKEN], user_input[CONF_VERIFY_SSL])
                if error:
                    errors["base"] = error
                else:
                    assert info is not None
                    await self.async_set_unique_id(str(info["instanceId"]))
                    self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN]})
                    return self.async_create_entry(
                        title=_title(url),
                        data={
                            CONF_URL: url,
                            CONF_TOKEN: user_input[CONF_TOKEN],
                            CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or {}),
            errors=errors,
            description_placeholders={"token_page": "/admin/tokens", "example_url": "https://wallbox.example.com"},
        )

    # ---- reauth ------------------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token was revoked / is invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, error = await self._validate(
                entry.data[CONF_URL], user_input[CONF_TOKEN], entry.data.get(CONF_VERIFY_SSL, True)
            )
            if error:
                errors["base"] = error
            else:
                assert info is not None
                await self.async_set_unique_id(str(info["instanceId"]))
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"url": entry.data[CONF_URL]},
        )

    # ---- reconfigure -------------------------------------------------------------------------

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change URL / certificate check of an existing server."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = normalize_url(user_input[CONF_URL])
            if not url.startswith(("http://", "https://")):
                errors[CONF_URL] = "invalid_url"
            else:
                info, error = await self._validate(url, entry.data[CONF_TOKEN], user_input[CONF_VERIFY_SSL])
                if error:
                    errors["base"] = error
                else:
                    assert info is not None
                    await self.async_set_unique_id(str(info["instanceId"]))
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        entry,
                        title=_title(url, entry.data.get(CONF_SOURCE_ADDON, False)),
                        data_updates={CONF_URL: url, CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL]},
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(RECONFIGURE_SCHEMA, user_input or dict(entry.data)),
            errors=errors,
        )

    # ---- add-on (Supervisor discovery, docs/API.md §2) --------------------------------

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The Wallbox WEB add-on announced itself."""
        cfg = discovery_info.config
        host, port, token = cfg.get("host"), cfg.get("port"), cfg.get("api_token")
        if not host or not port or not token:
            return self.async_abort(reason="invalid_discovery_info")
        scheme = "https" if cfg.get("ssl") else "http"
        url = f"{scheme}://{host}:{port}"
        info, error = await self._validate(url, str(token), True)
        if error:
            return self.async_abort(reason=error)
        assert info is not None
        await self.async_set_unique_id(str(info["instanceId"]))
        self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_TOKEN: str(token)})
        self._discovered = {
            CONF_URL: url,
            CONF_TOKEN: str(token),
            CONF_VERIFY_SSL: True,
            CONF_SOURCE_ADDON: True,
        }
        self.context["title_placeholders"] = {"name": discovery_info.name or "Wallbox WEB"}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The user confirms the add-on."""
        if user_input is not None:
            return self.async_create_entry(title=_title("", addon=True), data=self._discovered)
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": self.context.get("title_placeholders", {}).get("name", "Wallbox WEB")},
        )
