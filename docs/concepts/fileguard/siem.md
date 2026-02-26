# FileGuard SIEM Forwarding Service Reference

Documentation for the async SIEM event forwarding service used by the FileGuard scan pipeline.

---

## Overview

`SIEMService` provides fire-and-forget delivery of `ScanEvent` records to external SIEM
platforms — Splunk HEC and RiverSafe WatchTower — fully decoupled from the scan critical path.

**Design goals:**

| Goal | Implementation |
|---|---|
| Non-blocking | `forward_event()` schedules an `asyncio.Task` and returns immediately; delivery never delays scan responses |
| Reliability | Exponential back-off retry for transient network and HTTP 5xx failures |
| Fail-safe | SIEM delivery failures are logged and suppressed; they never propagate to callers or affect scan outcomes |
| Observability | Prometheus counter `siem_delivery_errors_total` incremented on every failed delivery attempt |

---

## File

**`fileguard/services/siem.py`**

---

## Classes

### `SIEMService`

```python
class SIEMService:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None: ...
    def forward_event(self, event: ScanEvent, config: SIEMConfig) -> asyncio.Task[None]: ...
```

#### Constructor

| Argument | Type | Default | Description |
|---|---|---|---|
| `http_client` | `httpx.AsyncClient \| None` | `None` | Optional shared HTTP client for connection pooling. When `None`, a transient client is created per delivery attempt. |

#### `forward_event(event, config)`

Schedules asynchronous delivery of `event` to the SIEM destination described by `config`.

**This method is non-blocking.** It creates an `asyncio.Task` via `asyncio.create_task()`
and returns immediately. Callers on the scan critical path must use this method — not
`await` the coroutine directly — to preserve response latency.

**Returns:** `asyncio.Task[None]` — callers can discard this in production or `await` it in tests.

**Never raises:** All delivery errors are caught internally and logged at WARNING level.

---

### `SIEMConfig`

```python
@dataclass
class SIEMConfig:
    type: str
    endpoint: str
    token: str | None = None
    max_retries: int = 3
    retry_base_delay: float = 1.0
```

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | `str` | — | Destination type: `"splunk"` or `"watchtower"` |
| `endpoint` | `str` | — | Full URL of the SIEM ingest endpoint |
| `token` | `str \| None` | `None` | Auth token (Splunk HEC token or WatchTower Bearer token) |
| `max_retries` | `int` | `3` | Additional retry attempts after initial failure |
| `retry_base_delay` | `float` | `1.0` | Base delay (seconds) for exponential back-off |

---

## Retry policy

On a transient failure (network error or retryable HTTP status code), the service retries
up to `max_retries` additional times using exponential back-off with jitter:

```
delay = retry_base_delay × 2^attempt + uniform(0, 0.5)
```

**Retryable HTTP status codes:** `408`, `429`, `500`, `502`, `503`, `504`

**Non-retryable HTTP status codes:** All other codes (e.g. `400`, `401`, `403`) cause
immediate abort after a single attempt.

Each failed attempt (including retries) increments `siem_delivery_errors_total`.

---

## Prometheus metrics

### `siem_delivery_errors_total`

```
# HELP siem_delivery_errors_total Total number of failed SIEM event delivery attempts
# TYPE siem_delivery_errors_total counter
siem_delivery_errors_total{destination="splunk",error_type="http_error"} 0
siem_delivery_errors_total{destination="splunk",error_type="network_error"} 0
siem_delivery_errors_total{destination="watchtower",error_type="http_error"} 0
siem_delivery_errors_total{destination="watchtower",error_type="network_error"} 0
```

| Label | Values | Description |
|---|---|---|
| `destination` | `"splunk"`, `"watchtower"` | The SIEM type from `SIEMConfig.type` |
| `error_type` | `"http_error"`, `"network_error"`, `"unknown"` | Category of failure |

**Alerting:** A companion Prometheus alert rule `SIEMHighDeliveryErrorRate` fires when
the delivery error rate exceeds 0.5% over a 5-minute window
(defined in `deploy/prometheus/alerts/siem.yaml`).

---

## Destination payload formats

### Splunk HEC

Payload is wrapped in the standard HEC event envelope:

```json
{
  "event": {
    "scan_id": "11111111-2222-3333-4444-555555555555",
    "tenant_id": "aaaa-...",
    "file_hash": "e3b0c44298fc1c...",
    "file_name": "report.pdf",
    "file_size_bytes": 204800,
    "mime_type": "application/pdf",
    "status": "clean",
    "action_taken": "pass",
    "findings": [],
    "scan_duration_ms": 312,
    "created_at": "2026-01-15T12:00:00+00:00",
    "hmac_signature": "deadbeef..."
  },
  "sourcetype": "fileguard:scan"
}
```

**Auth header:** `Authorization: Splunk <token>`

### RiverSafe WatchTower

Payload is the event object sent directly (no envelope):

```json
{
  "scan_id": "11111111-2222-3333-4444-555555555555",
  "tenant_id": "aaaa-...",
  "file_hash": "e3b0c44298fc1c...",
  "file_name": "report.pdf",
  "file_size_bytes": 204800,
  "mime_type": "application/pdf",
  "status": "clean",
  "action_taken": "pass",
  "findings": [],
  "scan_duration_ms": 312,
  "created_at": "2026-01-15T12:00:00+00:00",
  "hmac_signature": "deadbeef..."
}
```

**Auth header:** `Authorization: Bearer <token>`

---

## Usage

### Fire-and-forget from the scan pipeline

```python
from fileguard.services.siem import SIEMService, SIEMConfig

siem = SIEMService()

# Construct config from tenant settings (e.g. loaded from DB at request time)
config = SIEMConfig(
    type="splunk",
    endpoint="https://splunk.example.com:8088/services/collector/event",
    token="your-hec-token",
)

# Non-blocking — returns immediately, delivery happens in the background
siem.forward_event(scan_event, config)
```

### Shared HTTP client (recommended for production)

```python
import httpx
from fileguard.services.siem import SIEMService

# Create a shared client at application startup (e.g. in lifespan event)
http_client = httpx.AsyncClient(timeout=10.0)
siem = SIEMService(http_client=http_client)

# Use siem throughout the application lifetime
# Close the client at shutdown
await http_client.aclose()
```

### Awaiting delivery in tests

```python
task = siem.forward_event(event, config)
await task  # wait for delivery to complete in test context
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest fileguard/tests/test_siem.py -v
```

Tests are fully offline (no Splunk or WatchTower connection required). Coverage includes:

- Successful delivery to Splunk HEC (correct HEC envelope and `Authorization: Splunk` header)
- Successful delivery to WatchTower (flat payload and `Authorization: Bearer` header)
- Network failure triggers retry and increments `siem_delivery_errors_total`
- HTTP 5xx triggers retry; counter incremented per attempt
- HTTP 4xx (non-retryable) aborts immediately with single counter increment
- Error counter labels verified for both `splunk` and `watchtower` destinations
- `forward_event` returns `asyncio.Task` without blocking
- Transient client creation when no shared `http_client` is injected
