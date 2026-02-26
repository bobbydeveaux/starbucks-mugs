# FileGuard AV Engine Adapter Reference

Documentation for the antivirus engine plugin interface and ClamAV daemon adapter used by the FileGuard scan pipeline.

---

## Overview

The AV engine layer sits at the heart of the scan pipeline.  It abstracts all
AV engine communication behind a common interface (`AVEngineAdapter`), so the
pipeline code remains independent of whether ClamAV, Sophos, or any other
engine is in use.

**Design goals:**

| Goal | Implementation |
|---|---|
| Pluggable engines | Abstract `AVEngineAdapter` base class; concrete adapters hot-swapped via config |
| Fail-secure | `scan()` raises `AVEngineError` instead of returning clean when the daemon is unavailable or returns an error |
| Non-blocking async | All blocking socket I/O delegated to a thread-pool executor; event loop never blocked |
| Testability | Thin client-factory method (`_get_client`) makes the socket layer trivially mockable |

---

## Files

| File | Purpose |
|---|---|
| `fileguard/core/av_adapter.py` | Abstract interface, `ScanResult` dataclass, `AVEngineError` exception |
| `fileguard/core/adapters/clamav_adapter.py` | ClamAV daemon adapter (Unix socket + TCP) |

---

## Abstract Interface (`av_adapter.py`)

### `AVEngineAdapter`

```python
class AVEngineAdapter(ABC):
    async def scan(self, data: bytes) -> ScanResult: ...
    async def is_available(self) -> bool: ...
    def engine_name(self) -> str: ...
```

All concrete adapter implementations must subclass `AVEngineAdapter` and
implement these three methods.

#### `scan(data)`

Scan raw file bytes and return a structured verdict.

| Returns / Raises | Condition |
|---|---|
| `ScanResult(is_clean=True)` | Engine found no threats |
| `ScanResult(is_clean=False, threat_name=…)` | Engine found a threat |
| `AVEngineError` | Daemon unreachable, returned ERROR, or produced unrecognised response |

**Fail-secure contract:** `scan()` must *never* return `is_clean=True` when the
scan cannot be verified.  Any failure must raise `AVEngineError` so the pipeline
can apply its `rejected` / `block` disposition.

#### `is_available()`

Health-check whether the engine is reachable.

| Returns | Condition |
|---|---|
| `True` | Engine responds to health probe |
| `False` | Any error (connection refused, timeout, unexpected response, …) |

This method must **never** raise; it is safe to call from health-check endpoints
without a surrounding `try/except`.

#### `engine_name()`

Returns a short, lowercase engine identifier (e.g. `"clamav"`) used in
`ScanResult.engine_name` and log output.

---

### `ScanResult`

```python
@dataclass
class ScanResult:
    is_clean: bool
    threat_name: Optional[str] = None   # None when is_clean=True
    engine_name: str = ""
    raw_response: str = ""
```

| Field | Description |
|---|---|
| `is_clean` | `True` = no threats detected; `False` = threat found |
| `threat_name` | Threat identifier returned by the engine (e.g. `"Win.Test.EICAR_HDB-1"`) |
| `engine_name` | Short engine identifier from `AVEngineAdapter.engine_name()` |
| `raw_response` | Raw status string from the engine for audit/debug logging |

---

### `AVEngineError`

```python
class AVEngineError(Exception): ...
```

Raised by `scan()` on any unrecoverable condition.  Always chains the original
exception as `__cause__`.  Callers **must not** swallow this exception;
the pipeline must apply fail-secure disposition (`rejected` / `block`).

---

## ClamAV Adapter (`clamav_adapter.py`)

### `ClamAVAdapter`

```python
class ClamAVAdapter(AVEngineAdapter):
    def __init__(
        self,
        socket_path: Optional[str] = None,
        *,
        host: str = "clamav",
        port: int = 3310,
        timeout: int = 30,
    ) -> None: ...
```

#### Constructor arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `socket_path` | `str \| None` | `None` | Unix domain socket path (e.g. `"/var/run/clamav/clamd.ctl"`). When set, Unix socket is used and `host`/`port` are ignored. |
| `host` | `str` | `"clamav"` | TCP hostname for the clamd daemon. Used only when `socket_path` is `None`. |
| `port` | `int` | `3310` | TCP port for the clamd daemon. |
| `timeout` | `int` | `30` | Socket I/O timeout in seconds. |

#### Transport selection

```
socket_path provided  →  clamd.ClamdUnixSocket(socket_path)
socket_path is None   →  clamd.ClamdNetworkSocket(host, port)
```

---

### clamd INSTREAM response mapping

| clamd response | `scan()` result |
|---|---|
| `{'stream': ('OK', None)}` | `ScanResult(is_clean=True)` |
| `{'stream': ('FOUND', '<name>')}` | `ScanResult(is_clean=False, threat_name='<name>')` |
| `{'stream': ('ERROR', '<msg>')}` | raises `AVEngineError("ClamAV daemon reported error: <msg>")` |
| Missing `stream` key | raises `AVEngineError("Unexpected ClamAV INSTREAM response: …")` |
| Unknown status token | raises `AVEngineError("Unrecognised ClamAV response status …")` |
| `ConnectionError` from clamd | raises `AVEngineError("ClamAV daemon unreachable …")` |

---

## Configuration

ClamAV connection parameters are read from `fileguard.config.settings`:

```python
# fileguard/config.py
CLAMAV_HOST: str = "clamav"   # hostname for TCP transport
CLAMAV_PORT: int = 3310       # port for TCP transport
```

For on-prem / Kubernetes DaemonSet deployments using a Unix socket, pass
`socket_path` directly to the constructor:

```python
from fileguard.core.adapters.clamav_adapter import ClamAVAdapter

# Kubernetes DaemonSet (Unix socket — recommended for same-node latency)
adapter = ClamAVAdapter(socket_path="/var/run/clamav/clamd.ctl")

# TCP (network-separated deployment)
from fileguard.config import settings
adapter = ClamAVAdapter(host=settings.CLAMAV_HOST, port=settings.CLAMAV_PORT)
```

---

## Usage examples

### Scan a file

```python
from fileguard.core.adapters.clamav_adapter import ClamAVAdapter
from fileguard.core.av_adapter import AVEngineError

adapter = ClamAVAdapter(socket_path="/var/run/clamav/clamd.ctl")

async def scan_upload(file_bytes: bytes) -> str:
    try:
        result = await adapter.scan(file_bytes)
    except AVEngineError as exc:
        # Fail-secure: treat scan failure as rejection
        raise RuntimeError(f"AV scan failed — file rejected: {exc}") from exc

    if result.is_clean:
        return "clean"
    return f"flagged:{result.threat_name}"
```

### Health-check

```python
async def health() -> dict:
    available = await adapter.is_available()
    return {"clamav": "ok" if available else "unavailable"}
```

---

## Fail-secure behaviour

`ClamAVAdapter` enforces fail-secure at every failure point:

| Failure scenario | `scan()` behaviour | `is_available()` behaviour |
|---|---|---|
| Unix socket not found / refused | raises `AVEngineError` | returns `False` |
| TCP connection refused / timeout | raises `AVEngineError` | returns `False` |
| clamd returns `ERROR` status | raises `AVEngineError` | N/A |
| Unexpected response structure | raises `AVEngineError` | N/A |
| Unrecognised status token | raises `AVEngineError` | N/A |

`scan()` **never** returns `is_clean=True` when any failure occurs.

---

## Adding a new engine adapter

1. Create `fileguard/core/adapters/<engine>_adapter.py`
2. Subclass `AVEngineAdapter` and implement `scan()`, `is_available()`, and `engine_name()`
3. Wire the adapter into the scan pipeline via the deployment configuration

```python
from fileguard.core.av_adapter import AVEngineAdapter, AVEngineError, ScanResult

class SophosAdapter(AVEngineAdapter):
    async def scan(self, data: bytes) -> ScanResult:
        ...  # call Sophos SDK; raise AVEngineError on any failure

    async def is_available(self) -> bool:
        try:
            ...  # SDK health probe
            return True
        except Exception:
            return False

    def engine_name(self) -> str:
        return "sophos"
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/unit/test_clamav_adapter.py -v
```

Tests are fully offline (no ClamAV daemon or network required).  Coverage includes:

- Clean scan (`OK` response) — `is_clean=True`, no `threat_name`
- Infected scan (`FOUND` response) — `is_clean=False`, `threat_name` set
- Error response (`ERROR` status) — `AVEngineError` raised with daemon message
- Daemon unreachable (`ConnectionError`) — `AVEngineError` raised with connection description
- Malformed responses (missing `stream` key, empty tuple, unknown token) — `AVEngineError`
- `is_available()` returns `True` on successful PING
- `is_available()` returns `False` for `ConnectionError`, `RuntimeError`, timeout — never raises
- Unix socket transport (`socket_path`) vs TCP (`host`/`port`) constructor paths
