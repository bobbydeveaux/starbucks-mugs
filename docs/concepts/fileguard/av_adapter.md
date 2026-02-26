# AV Engine Adapter Interface

FileGuard uses a plugin-based approach for anti-virus scanning so that the
default ClamAV engine can be swapped for commercial alternatives (e.g. Sophos,
CrowdStrike) without modifying the core scan pipeline.

## Module

```
fileguard/core/av_adapter.py
```

## Public API

### `AVEngineAdapter` (abstract base class)

All AV engine implementations must subclass `AVEngineAdapter` and implement
the three abstract methods below.

```python
from fileguard.core.av_adapter import AVEngineAdapter, ScanResult

class MyEngine(AVEngineAdapter):
    def scan(self, data: bytes) -> ScanResult: ...
    def is_available(self) -> bool: ...
    def engine_name(self) -> str: ...
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `scan` | `(data: bytes) -> ScanResult` | Inspect raw file bytes and return a scan verdict |
| `is_available` | `() -> bool` | Return `True` when the engine daemon is reachable |
| `engine_name` | `() -> str` | Return a stable, lowercase engine identifier (e.g. `"clamav"`) |

### `ScanResult`

Frozen dataclass returned by `AVEngineAdapter.scan()`.

| Field | Type | Description |
|-------|------|-------------|
| `is_clean` | `bool` | `True` when no threats were detected |
| `threats` | `tuple[AVThreat, ...]` | Detected threats; empty when `is_clean` is `True` |
| `engine_name` | `str` | Engine identifier (mirrors `AVEngineAdapter.engine_name()`) |
| `engine_version` | `str \| None` | AV engine / signature DB version string |
| `scan_duration_ms` | `int \| None` | Elapsed scan time in milliseconds |

`ScanResult` raises `ValueError` on construction if `is_clean=True` is combined
with a non-empty `threats` tuple.

### `AVThreat`

Frozen dataclass describing a single detected threat.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Threat / signature name (e.g. `"Win.Trojan.EICAR-1"`) |
| `severity` | `AVThreatSeverity` | `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` |
| `category` | `str \| None` | Optional engine-provided category (e.g. `"Trojan"`) |

### Exception Hierarchy

```
AVEngineError                 ← base; pipeline treats as fail-secure
├── AVEngineUnavailableError  ← daemon unreachable / timeout
└── AVEngineScanError         ← daemon reachable but returned an error
```

## Fail-Secure Contract

Adapters **must not** return `ScanResult(is_clean=True)` when an error or
ambiguous engine response occurs.  They must raise `AVEngineError` (or a
subclass) so the pipeline can apply the fail-secure policy and return a
`rejected` verdict.

`is_available()` must **not** raise; it must catch connectivity errors
internally and return `False`.

## Implementing a Custom Adapter

```python
from fileguard.core.av_adapter import (
    AVEngineAdapter,
    AVEngineUnavailableError,
    AVEngineScanError,
    AVThreat,
    AVThreatSeverity,
    ScanResult,
)

class SophosAdapter(AVEngineAdapter):
    def __init__(self, api_url: str, api_key: str) -> None:
        self._url = api_url
        self._key = api_key

    def engine_name(self) -> str:
        return "sophos-sav"

    def is_available(self) -> bool:
        try:
            # health-check call to Sophos API
            response = _ping(self._url, self._key)
            return response.ok
        except Exception:
            return False

    def scan(self, data: bytes) -> ScanResult:
        try:
            result = _submit(self._url, self._key, data)
        except TimeoutError as exc:
            raise AVEngineUnavailableError("Sophos API timed out") from exc
        except Exception as exc:
            raise AVEngineScanError(f"Sophos returned error: {exc}") from exc

        threats = tuple(
            AVThreat(name=t["name"], severity=AVThreatSeverity.HIGH)
            for t in result.get("detections", [])
        )
        return ScanResult(
            is_clean=len(threats) == 0,
            threats=threats,
            engine_name=self.engine_name(),
        )
```

## Loading a Custom Adapter

Set the `AV_ENGINE_CLASS_PATH` environment variable to the fully-qualified
class path of your adapter.  FileGuard will import and instantiate it at
startup:

```
AV_ENGINE_CLASS_PATH=mypackage.sophos.SophosAdapter
```

Constructor arguments are passed via additional `AV_ENGINE_*` environment
variables (adapter-specific).
