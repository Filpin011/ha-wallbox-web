"""Wallbox WEB integration: Scame-compatible wallboxes through a Wallbox WEB server (API v1).

Independent, unofficial project – not affiliated with SCAME PARRE S.p.A. (see DISCLAIMER.md).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .api import WallboxWebClient, WallboxWebError
from .const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from .coordinator import WallboxWebConfigEntry, WallboxWebCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket command used by the Wallbox WEB card (once, not per entry)."""
    websocket_api.async_register_command(hass, ws_charge_curve)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WallboxWebConfigEntry) -> bool:
    """Set up one Wallbox WEB server."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    client = WallboxWebClient(
        async_get_clientsession(hass, verify_ssl=verify_ssl),
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
        verify_ssl=verify_ssl,
    )
    coordinator = WallboxWebCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # The server itself: parent ("via") device of the stations.
    server = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"server_{coordinator.instance_id}")},
        manufacturer="Wallbox WEB",
        name=entry.title,
        model="Wallbox WEB server",
        sw_version=str(coordinator.info.get("appVersion") or "") or None,
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=client.url,
    )
    coordinator.server_device_id = server.id

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_push()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WallboxWebConfigEntry) -> bool:
    """Unload a config entry (the event stream task is cancelled with the entry)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: WallboxWebConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting a station device the server no longer reports (stale devices)."""
    coordinator = entry.runtime_data
    for domain, ident in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        if ident.startswith("server_"):
            return False
        if coordinator.data and ident in coordinator.data.stations:
            return False
    return True


def _station_for_device(hass: HomeAssistant, device_id: str) -> tuple[WallboxWebCoordinator, str] | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    station_id = next(
        (i for d, i in device.identifiers if d == DOMAIN and not i.startswith("server_")),
        None,
    )
    if station_id is None:
        return None
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data, station_id


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/charge_curve", vol.Required("device_id"): str})
@websocket_api.async_response
async def ws_charge_curve(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Power curve of the charge in progress (recorder data) for the card: {charge, samples}."""
    found = _station_for_device(hass, msg["device_id"])
    if found is None:
        connection.send_error(msg["id"], "not_found", "Unknown Wallbox WEB station device")
        return
    coordinator, station_id = found
    try:
        curve = await coordinator.client.current_curve(station_id)
    except WallboxWebError as err:
        connection.send_error(msg["id"], "unavailable", str(err))
        return
    samples = curve.get("samples") if isinstance(curve, dict) else None
    connection.send_result(
        msg["id"],
        {
            "charge": curve.get("charge") if isinstance(curve, dict) else None,
            "samples": samples if isinstance(samples, list) else [],
        },
    )
