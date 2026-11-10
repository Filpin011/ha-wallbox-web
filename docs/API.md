# Wallbox WEB API v1 – contract used by this integration

> Independent, unofficial project – see [DISCLAIMER.md](../DISCLAIMER.md).

This is the HTTP contract between the integration and a Wallbox WEB server (self-hosted or the Home Assistant
add-on). The integration's tests run against an in-process fake of it (`tests/fake_server.py`).

Authentication: `Authorization: Bearer <API token>` (`wbx_…`), with the token permissions `read` (every `GET`, the
event stream) and `control` (commands and settings). A read-only token makes the buttons, number and select
unavailable. `401` starts the Home Assistant re-authentication flow.

## 1. HTTP API contract v1

Base path `/api/v1`, JSON (`application/json; charset=utf-8`), `cache-control: no-store`. Times are ISO-8601 UTC
strings (`2026-11-10T18:04:05.123Z`); energies in **Wh**, powers in **W**, currents in **A** (decimals allowed),
durations in **s** – integers unless stated. Additive changes (new fields, new enum values, new events) do not bump
the version; clients ignore unknown fields and map unknown enum values to `undefined`/`unknown`. Breaking changes
go to `/api/v2`.

### 1.1 Endpoints

| Method & path | Perm. | Body | 200 response |
|---|---|---|---|
| `GET /api/v1` | read | – | `ServerInfo` |
| `GET /api/v1/stations` | read | – (`?include=state` adds `state` to each station) | `{ stations: Station[] }` |
| `GET /api/v1/stations/{id}` | read | – | `Station` (with `state`) |
| `GET /api/v1/stations/{id}/state` | read | – | `StationState` |
| `POST /api/v1/stations/{id}/commands/{command}` | control | `{}` | `CommandResult` – `command` ∈ `start`, `stop`, `pause`, `resume` |
| `PUT /api/v1/stations/{id}/max-current` | control | `{ "amps": 16 }` | `{ ok:true, maxCurrent: MaxCurrent, state: StationState }` |
| `PUT /api/v1/stations/{id}/behaviour-mode` | control | `{ "mode": "free" \| "personal" }` | `{ ok:true, behaviourMode, state: StationState }` |
| `GET /api/v1/stations/{id}/charges?limit=20&before=<iso>` | read | – | `{ charges: Charge[], nextBefore: string \| null }` (newest first, `limit` 1…100, default 20) |
| `GET /api/v1/stations/{id}/charges/current/curve` | read | – | `{ charge: Charge \| null, samples: Sample[] }` (empty when no charge in progress) |
| `GET /api/v1/stations/{id}/charges/{chargeId}/curve` | read | – | `{ charge: Charge, samples: Sample[] }` |
| `GET /api/v1/events` | read | – (`?stations=id1,id2` filter, optional) | `text/event-stream` (§1.5) |

`{id}` = station id (`[A-Za-z0-9_.-]{1,64}`, the board serial number).

### 1.2 Types

```ts
interface ServerInfo {
  apiVersion: 1;
  instanceId: string;          // random UUID generated once in DATA_DIR (config entry unique id)
  name: string;                // "Wallbox WEB"
  appVersion: string;          // package.json version
  appUrl: string;              // APP_URL
  permissions: ("read" | "control")[]; // of the calling token
  timeZone: string;            // COSTS_TIME_ZONE
  serverTime: string;
}

interface Station {
  id: string;                  // board serial number
  name: string;                // station name (ConnectorName), fallback advert name
  serial: string;              // board serial number (= id today)
  productCode: string | null;  // SocketInfo productCode, e.g. "205.W113-B"
  socketType: SocketType;      // "type2" | "type2_tethered" | "type1_tethered" | "type3a" | "schuko" | "ccs2" | "chademo" | "none" | "unknown"
  phases: 1 | 3 | null;        // SocketPowerMode
  firmware: string | null;     // e.g. "V5.1.1.0 646"
  hardware: string | null;     // hardwareRevision
  address: string;             // LAN host the server uses (diagnostics only)
  appUrl: string;              // deep link to the station in the app (configuration_url)
  state?: StationState;
}

type StationStatus =
  | "idle" | "preparing" | "connected" | "charging" | "suspended_ev" | "suspended_evse" | "end_charge"
  | "faulted" | "not_available" | "reserved" | "bootloader" | "shutdown" | "rebooting"
  | "suspended_no_power" | "unreachable" | "undefined";
// ConnectorStatus: -1 unreachable, 0 undefined, 1 idle, 2 preparing, 3 connected, 4 charging,
// 5 suspended_ev, 6 suspended_evse, 7 end_charge, 8 faulted, 9 not_available, 10 reserved, 11 bootloader,
// 12 shutdown, 13 rebooting, 14 suspended_no_power

interface StationState {
  id: string;
  online: boolean;             // false = no fresh reading (station unreachable / not seen for > 90 s)
  updatedAt: string;           // time of the reading this snapshot is built from
  status: StationStatus;
  statusCode: number;          // raw ConnectorStatus
  plugged: boolean;            // Status word0 bit1
  evConnected: boolean;        // Status word0 bit2
  power: {
    activeW: number;           // TransactionData currentPower
    maxAvailableW: number | null; // "Max disponibile": 230 V × rotary switch A (× 3 three-phase); null if unknown
    limitW: number | null;     // "Limite": MaxPower 33384 (0 → null)
    externalW: number | null;  // ExternalPower 33284 (signed)
  };
  current: { l1A: number; l2A: number | null; l3A: number | null }; // mA / 1000
  voltageV: number | null;
  session: {
    active: boolean;           // status in charging / suspended_* (ACTIVE_CHARGE_STATUSES)
    energyWh: number;          // TransactionData charge
    durationS: number;
    startedAt: string | null;  // recorder stationStartAt
    sessionId: number | null;
    card: string | null;       // RFID UID, "" = free mode
    chargeId: number | null;   // recorder charge id (curve)
  };
  energy: {
    lifetimeWh: number;        // never decreases (see "Lifetime energy")
    lifetimeSource: "meter" | "accumulated";
  };
  maxCurrent: MaxCurrent;
  behaviourMode: "free" | "personal" | "net" | "ocpp" | null;
  errors: { code: string; group: 1 | 2 }[];   // Errors01 / Errors02 codes, e.g. {code:"RCDM", group:1}
  schedules: { activeCount: number; anyActive: boolean };
  lastCharge: Charge | null;   // newest finished charge
  commands: { start: boolean; stop: boolean; pause: boolean; resume: boolean }; // enabled like the app buttons
}

interface MaxCurrent { valueA: number | null; min: number; max: number } // register 92; max = rotary switch (TransactionData w51), fallback 32

interface Charge {
  id: number;                  // recorder charge id, or negative synthetic id for history-only records
  start: string;
  end: string | null;          // null while in progress
  energyWh: number;
  durationS: number;
  peakW: number | null;
  card: string | null;
  cost: number | null;         // frozen cost (null = price not set)
  saving: number | null;       // petrol saving
  currency: "EUR";
  curveUrl: string | null;     // relative, e.g. "/api/v1/stations/X/charges/12/curve"
}

interface Sample { t: string; powerW: number; energyWh: number; status: StationStatus }

interface CommandResult {
  ok: true;
  command: "start" | "stop" | "pause" | "resume";
  state: StationState;         // fresh state read after the procedure
}
```

### 1.3 Commands

- `start` → procedure 9, `stop` → 12, `pause` → 10 (Suspend), `resume` → 11 (Release), parameter
  `TransactionAuthorizationUuid` ← the server's own 10-char UID (stable, `DATA_DIR`).
- Preconditions checked by the server first (same rules as the app's buttons): `start` needs `idle` and behaviour
  mode `personal` (in `free` mode → 409 `free_mode`), `pause` needs `charging`, `resume` needs `suspended_evse` and no
  `CHN2`/`EMEX`, `stop` needs an active session. Otherwise 409 `not_allowed_in_state`.
- The request waits for the procedure (≤ 70 s) and answers with the fresh state; clients use a 90 s
  timeout. A second command for the same station while one runs → 409 `busy`.
- Procedure outcome Error → 422 `procedure_failed` with `detail` ∈ `rejected`, `occupied`, `expired`, `invalid`,
  `internal`, `undefined`. The procedure ran but did not answer in time (or the station was busy with another
  procedure) → 504 `station_timeout`. `login_required` is reserved: the PIN of a station lives in the browser, so
  v1 reports a refusal of a PIN-protected station as `procedure_failed` / `rejected`.
- `max-current`: integer 6…`maxCurrent.max` → procedure 21 on register 92; 400 `invalid_request` outside the range.
- `behaviour-mode`: procedure 18; only when `idle` or `MFRE` present (409 `not_allowed_in_state`).

### 1.4 Lifetime energy

`energy.lifetimeWh` is guaranteed monotonic: the server keeps `max_seen` per station in `DATA_DIR`. Source `meter`
(TotalEnergy 1566) while it never decreases across sessions; on a decrease (> 1 Wh, not a glitch) the station is
switched permanently to `accumulated` = `baseline + Σ finished charges + current session energy`, where `baseline` =
the last `meter` value, so the HA statistic continues without a reset.

### 1.5 Server-Sent Events `GET /api/v1/events`

Standard SSE (`event:` + `data:` JSON + `id:`), `retry: 5000`. On connect the server sends `hello` and one `state`
per station (full snapshot), then:

| event | data | when |
|---|---|---|
| `hello` | `{ apiVersion:1, instanceId, permissions }` | first event |
| `state` | `StationState` (full) | on change, while charging at most every 10 s, heartbeat ≥ every 30 s |
| `station_added` | `Station` | a new station appears (advert, added by address) |
| `station_removed` | `{ id }` | station deleted from the app |
| `charge_started` | `{ stationId, charge: Charge }` | recorder `start` |
| `charge_sample` | `{ stationId, chargeId, sample: Sample }` | recorder sample (every 30 s) |
| `charge_finished` | `{ stationId, charge: Charge }` | recorder `end` (cost included when already frozen) |
| `ping` | `{}` | every 15 s |

`Last-Event-ID` is not replayed (state is a snapshot: the first `state` events after reconnect are the replay).
At most **2 concurrent streams per token** (the third closes the oldest).

### 1.6 Errors

Every error: HTTP status + `{ "ok": false, "code": "<code>", "error": "<english message>", ... }`.

| HTTP | code | meaning / extra fields |
|---|---|---|
| 400 | `invalid_request` | malformed body / query (`field`) |
| 401 | `unauthorized` | missing / invalid / revoked token (`www-authenticate: Bearer`) |
| 403 | `insufficient_permission` | token lacks `required` (`"control"`) |
| 403 | `forbidden` | sessions of users that must complete onboarding |
| 404 | `station_not_found` | unknown `{id}` |
| 404 | `charge_not_found` | unknown charge |
| 404 | `not_found` | unknown `/api/v1/...` route (lets clients detect a server without v1) |
| 409 | `not_allowed_in_state` | `status` (current) |
| 409 | `free_mode` | start refused in Free behaviour mode |
| 409 | `busy` | another command / procedure is running on that station |
| 422 | `procedure_failed` | `detail` (see §1.3) |
| 422 | `login_required` | station needs the PIN login and no PIN is saved |
| 429 | `rate_limited` | `retry-after` header (s) |
| 503 | `station_unreachable` | no connection to the station |
| 504 | `station_timeout` | procedure did not finish in time |
| 500 | `internal_error` | |

### 1.7 Rate limits

Per token (in-memory token bucket, reset on restart): reads **120/min**, commands and settings **10/min per station**,
SSE connects **10/min**. Over the limit → 429 `rate_limited` + `retry-after` (s) + `retryAfter` in the body.
`API_RATE_LIMIT=0` disables them (tests). Reads are served from the monitor cache, so they never translate into
station reads (the first call after a server start waits ≤ 8 s for one read of each station).

## 2. Supervisor discovery (add-on → integration)

The add-on declares in its `config.yaml`:

```yaml
discovery:
  - wallbox_web
hassio_api: true   # not needed only for discovery (/discovery is allowed to every add-on), harmless
```

On every start (after the server answers `/api/health`) it provisions a token with `wallbox: ["read","control"]`
named `Home Assistant (add-on)` (reusing it if it still exists – the token value is kept in the add-on's `/data`)
and sends:

```http
POST http://supervisor/discovery
Authorization: Bearer ${SUPERVISOR_TOKEN}
Content-Type: application/json

{
  "service": "wallbox_web",
  "config": {
    "host": "<add-on hostname, e.g. 1a2b3c4d-wallbox-web>",
    "port": 8423,
    "ssl": false,
    "api_token": "wbx_…",
    "version": "1.5.0",
    "instance_id": "<ServerInfo.instanceId>"
  }
}
```

(with bashio: `bashio::discovery "wallbox_web" "${config}"`). Fields: `host` (required, the add-on's internal DNS
name = add-on slug with `_` → `-`), `port` (required, the add-on's direct port – 8423 by default – not the ingress port), `api_token`
(required), `version` (required, add-on / app version), `ssl` (optional, default `false`), `instance_id` (optional;
the integration otherwise reads it from `GET /api/v1`). The add-on deletes the message on uninstall (automatic) and
re-sends it when the token changes.

Integration side (`config_flow.py`): `async_step_hassio(discovery_info: HassioServiceInfo)` reads `config`, builds
`http://{host}:{port}`, calls `GET /api/v1` with the token, sets `unique_id = instanceId` and
`_abort_if_unique_id_configured(updates={url, token})` (an existing entry follows a new token/port automatically), then
`async_step_hassio_confirm` shows "Vuoi configurare Wallbox WEB (add-on)?" and creates the entry. Errors → abort
`cannot_connect` / `api_not_supported`.
