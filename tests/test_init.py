"""Setup, devices, entities, push updates, commands, permissions, reauth, diagnostics, websocket."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.wallbox_web.const import CONF_TOKEN, DOMAIN

from .fake_server import TOKEN_READ, FakeWallboxWeb, make_station

STATION = "00012345"


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def wait_for(hass: HomeAssistant, predicate: Any, timeout: float = 5) -> None:
    """Let the SSE task run until `predicate()` holds."""
    for _ in range(int(timeout / 0.02)):
        await hass.async_block_till_done()
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


def entity_id(hass: HomeAssistant, platform: str, key: str, station: str = STATION) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{station}_{key}")
    assert eid is not None, f"{platform} {key} missing"
    return eid


async def test_setup_device_and_entities(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, STATION), entry.entry_id)
    assert device is not None
    assert device.manufacturer == "Scame"
    assert device.model == "205.W000-X"
    assert device.name == "Garage"
    assert device.serial_number == STATION
    assert device.sw_version == "V5.1.1.0 646"
    assert device.configuration_url == "https://wallbox.example.com/home"
    server = dr.async_get(hass).async_get(device.via_device_id)  # type: ignore[arg-type]
    assert server is not None
    assert server.entry_type is dr.DeviceEntryType.SERVICE

    assert hass.states.get(entity_id(hass, "sensor", "status")).state == "idle"
    power = hass.states.get(entity_id(hass, "sensor", "power"))
    assert power.state == "0.0"
    assert power.attributes["unit_of_measurement"] == "kW"
    lifetime = hass.states.get(entity_id(hass, "sensor", "lifetime_energy"))
    assert lifetime.state == "1234.567"
    assert lifetime.attributes["state_class"] == "total_increasing"
    assert lifetime.attributes["device_class"] == "energy"
    assert lifetime.attributes["unit_of_measurement"] == "kWh"
    assert lifetime.attributes["source"] == "meter"
    assert hass.states.get(entity_id(hass, "sensor", "last_charge_cost")).state == "4.43"
    assert hass.states.get(entity_id(hass, "sensor", "error")).state == "none"
    assert hass.states.get(entity_id(hass, "binary_sensor", "plugged")).state == STATE_OFF
    assert hass.states.get(entity_id(hass, "binary_sensor", "online")).state == STATE_ON
    assert hass.states.get(entity_id(hass, "number", "max_current")).state == "16.0"
    assert hass.states.get(entity_id(hass, "select", "behaviour_mode")).state == "personal"
    assert hass.states.get(entity_id(hass, "button", "start")).state != STATE_UNAVAILABLE
    assert hass.states.get(entity_id(hass, "button", "stop")).state == STATE_UNAVAILABLE
    # single-phase station: no L2/L3 entities; voltage disabled by default
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{STATION}_current_l2") is None
    voltage = er.async_get(hass).async_get(entity_id(hass, "sensor", "voltage"))
    assert voltage.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_push_updates(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    coordinator = entry.runtime_data
    await wait_for(hass, lambda: coordinator.sse_connected)
    polls = len([c for c in fake.calls if c[1] == "/stations"])

    fake.push_state(
        STATION,
        status="charging",
        plugged=True,
        power={"activeW": 7200},
        session={"active": True, "energyWh": 5120, "durationS": 2700, "chargeId": 8},
        errors=[{"code": "HGTP", "group": 2}],
    )
    status_id = entity_id(hass, "sensor", "status")
    await wait_for(hass, lambda: hass.states.get(status_id).state == "charging")
    assert hass.states.get(entity_id(hass, "sensor", "power")).state == "7.2"
    assert hass.states.get(entity_id(hass, "sensor", "power")).attributes["charge_id"] == 8
    assert hass.states.get(entity_id(hass, "sensor", "session_energy")).state == "5.12"
    assert hass.states.get(entity_id(hass, "sensor", "session_duration")).state == "45.0"
    assert hass.states.get(entity_id(hass, "binary_sensor", "charging")).state == STATE_ON
    assert hass.states.get(entity_id(hass, "binary_sensor", "problem")).state == STATE_ON
    assert hass.states.get(entity_id(hass, "sensor", "error")).state == "hgtp"
    # push, not polling
    assert len([c for c in fake.calls if c[1] == "/stations"]) == polls

    fake.push_state(STATION, online=False)
    await wait_for(hass, lambda: hass.states.get(status_id).state == STATE_UNAVAILABLE)
    assert hass.states.get(entity_id(hass, "binary_sensor", "online")).state == STATE_OFF


async def test_dynamic_station(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await wait_for(hass, lambda: entry.runtime_data.sse_connected)
    new = make_station("00099999", "Ospiti", phases=3, current={"l1A": 1.0, "l2A": 1.0, "l3A": 1.0})
    new["phases"] = 3
    fake.add(new)
    fake.push("station_added", new)
    await wait_for(
        hass, lambda: er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "00099999_status") is not None
    )
    assert dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "00099999"), entry.entry_id).name == "Ospiti"
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, "00099999_current_l3") is not None

    fake.stations.pop("00099999")
    fake.push("station_removed", {"id": "00099999"})
    status = entity_id(hass, "sensor", "status", "00099999")
    await wait_for(hass, lambda: hass.states.get(status).state == STATE_UNAVAILABLE)


async def test_commands(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await hass.services.async_call("button", "press", {"entity_id": entity_id(hass, "button", "start")}, blocking=True)
    assert ("POST", "/commands/start", None) in fake.calls
    assert hass.states.get(entity_id(hass, "sensor", "status")).state == "charging"
    assert hass.states.get(entity_id(hass, "button", "start")).state == STATE_UNAVAILABLE
    assert hass.states.get(entity_id(hass, "button", "pause")).state != STATE_UNAVAILABLE

    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id(hass, "number", "max_current"), "value": 10}, blocking=True
    )
    assert ("PUT", "/max-current", {"amps": 10}) in fake.calls
    assert hass.states.get(entity_id(hass, "number", "max_current")).state == "10.0"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id(hass, "select", "behaviour_mode"), "option": "free"},
        blocking=True,
    )
    assert hass.states.get(entity_id(hass, "select", "behaviour_mode")).state == "free"


async def test_command_errors(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    fake.fail_next["POST /api/v1/stations/00012345/commands/start"] = (
        422,
        {"ok": False, "code": "procedure_failed", "error": "Rejected", "detail": "occupied"},
    )
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id(hass, "button", "start")}, blocking=True
        )
    assert err.value.translation_key == "procedure_failed"
    assert err.value.translation_placeholders["detail"] == "occupied"

    fake.fail_next["PUT /api/v1/stations/00012345/max-current"] = (
        409,
        {"ok": False, "code": "busy", "error": "busy"},
    )
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id(hass, "number", "max_current"), "value": 12}, blocking=True
        )
    assert err.value.translation_key == "busy"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id(hass, "select", "behaviour_mode"), "option": "ocpp"},
            blocking=True,
        )


async def test_read_only_token(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN: TOKEN_READ})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "status")).state == "idle"
    for platform, key in (("button", "start"), ("number", "max_current"), ("select", "behaviour_mode")):
        assert hass.states.get(entity_id(hass, platform, key)).state == STATE_UNAVAILABLE


async def test_auth_failure_starts_reauth(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN: "wbx_revoked"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_server_without_v1_retries(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    fake.v1 = False
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_polling_fallback_without_sse(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    fake.sse_enabled = False
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert not coordinator.sse_connected
    fake.stations[STATION]["state"]["status"] = "connected"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", "status")).state == "connected"


async def test_unload(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    await wait_for(hass, lambda: fake.sse_clients == 1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_stale_device(hass: HomeAssistant, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    from custom_components.wallbox_web import async_remove_config_entry_device

    registry = dr.async_get(hass)
    live = registry.async_get_device_by_identifier((DOMAIN, STATION), entry.entry_id)
    assert not await async_remove_config_entry_device(hass, entry, live)
    stale = registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "gone")})
    assert await async_remove_config_entry_device(hass, entry, stale)


async def test_diagnostics(hass: HomeAssistant, hass_client: Any, fake: FakeWallboxWeb, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = str(diag)
    assert TOKEN_READ not in text
    assert "wbx_" not in text
    assert STATION not in text
    assert "192.0.2.10" not in text
    assert diag["stations"][0]["state"]["status"] == "idle"


async def test_websocket_charge_curve(
    hass: HomeAssistant, hass_ws_client: Any, fake: FakeWallboxWeb, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    fake.curve = {
        "charge": {"id": 8},
        "samples": [{"t": "2026-11-10T18:00:00Z", "powerW": 7000, "energyWh": 100, "status": "charging"}],
    }
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, STATION), entry.entry_id)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "wallbox_web/charge_curve", "device_id": device.id})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["samples"][0]["powerW"] == 7000
    await client.send_json_auto_id({"type": "wallbox_web/charge_curve", "device_id": "nope"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
