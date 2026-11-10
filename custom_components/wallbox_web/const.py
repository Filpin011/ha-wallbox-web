"""Constants of the Wallbox WEB integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "wallbox_web"
LOGGER = logging.getLogger(__package__)

CONF_URL: Final = "url"
CONF_TOKEN: Final = "token"  # noqa: S105 - config key, not a secret
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SOURCE_ADDON: Final = "addon"

API_VERSION: Final = 1
POLL_INTERVAL: Final = timedelta(seconds=30)
REQUEST_TIMEOUT: Final = 15
COMMAND_TIMEOUT: Final = 90
SSE_BACKOFF_MIN: Final = 5
SSE_BACKOFF_MAX: Final = 300
# A stream that sends nothing (not even the 15 s ping) for this long is considered dead.
SSE_READ_TIMEOUT: Final = 60

PERMISSION_READ: Final = "read"
PERMISSION_CONTROL: Final = "control"

MANUFACTURER: Final = "Scame"

STATION_STATUSES: Final = [
    "idle",
    "preparing",
    "connected",
    "charging",
    "suspended_ev",
    "suspended_evse",
    "end_charge",
    "faulted",
    "not_available",
    "reserved",
    "bootloader",
    "shutdown",
    "rebooting",
    "suspended_no_power",
    "unreachable",
    "undefined",
]

ERROR_CODES: Final = [
    "none",
    "rcdm",
    "lide",
    "vent",
    "blck",
    "blef",
    "wifi",
    "mirr",
    "rcbo",
    "cpse",
    "ppse",
    "cpls",
    "ppls",
    "vbus",
    "mfre",
    "emtr",
    "ovce",
    "rcte",
    "emex",
    "chn2",
    "penf",
    "hgtp",
    "unknown",
]

SOCKET_TYPE_NAMES: Final = {
    "type2": "Type 2",
    "type2_tethered": "Type 2 (cable)",
    "type1_tethered": "Type 1 (cable)",
    "type3a": "Type 3A",
    "schuko": "Schuko",
    "ccs2": "CCS2",
    "chademo": "CHAdeMO",
}

BEHAVIOUR_MODES_WRITABLE: Final = ["free", "personal"]
BEHAVIOUR_MODES: Final = ["free", "personal", "net", "ocpp"]

COMMANDS: Final = ["start", "pause", "resume", "stop"]
