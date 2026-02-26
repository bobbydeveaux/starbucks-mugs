# AV Engine Adapter

**Module:** `fileguard.engines`
**Status:** Implemented (Sprint 2)

---

## Overview

The AV engine adapter layer provides a uniform interface between the FileGuard
scan pipeline and any antivirus backend. All concrete engine integrations
implement the abstract `AVEngineAdapter` base class, enabling the pipeline to
remain agnostic of the underlying AV technology.

This design realises **ADR-04** from the HLD: ClamAV is the default, open-source
engine; commercial engines (Sophos, CrowdStrike) are drop-in replacements loaded
via configurable class path.

---

## Core Types

### `Finding`

Immutable record of a single detected issue. Shared across AV and PII detection
layers.

```python
from fileguard.engines import Finding, FindingType, FindingSeverity

Finding(
    type=FindingType.AV_THREAT,   # or FindingType.PII
    category="EICAR-Test-Signature",
    severity=FindingSeverity.CRITICAL,
    offset=0,                      # byte offset (0 for AV threats)
    match="EICAR-Test-Signature",  # virus name; "[REDACTED]" for PII
)
```

| Field      | Type             | Description |
|------------|------------------|-------------|
| `type`     | `FindingType`    | `"av_threat"` or `"pii"` |
| `category` | `str`            | Engine-specific label (e.g. `"EICAR"`, `"NHS_NUMBER"`) |
| `severity` | `FindingSeverity`| `"low"` / `"medium"` / `"high"` / `"critical"` |
| `offset`   | `int`            | Byte offset in extracted text; `0` for AV threats |
| `match`    | `str`            | Matched value; PII matches stored as `"[REDACTED]"` |

`Finding` is a frozen `dataclass`: instances are immutable and hashable.

### `AVEngineError`

Raised when the engine daemon is unreachable or returns an unexpected error.
Callers must treat this as a scan failure and apply fail-secure policy
(reject the file — see ADR-06).

```python
from fileguard.engines import AVEngineError

try:
    findings = adapter.scan(path)
except AVEngineError:
    # engine is unavailable — reject the file
    raise
```

---

## Abstract Interface

```python
from abc import ABC, abstractmethod
from pathlib import Path

class AVEngineAdapter(ABC):

    @abstractmethod
    def scan(self, file_path: Path) -> list[Finding]:
        """Scan file_path and return any detected findings.

        Returns an empty list when the file is clean.

        Raises:
            AVEngineError: engine unreachable or returned an error.
            FileNotFoundError: file_path does not exist.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Return True if the engine is reachable and ready.

        Must not raise; returns False on any error.
        """
```

Implementations **must** be thread-safe: the scan worker pool invokes `scan`
from multiple threads concurrently.

---

## ClamAV Adapter

`ClamAVAdapter` is the default implementation, connecting to a running
`clamd` daemon over a TCP socket.

### Configuration

| Parameter | Default    | Source |
|-----------|------------|--------|
| `host`    | `"clamav"` | `settings.CLAMAV_HOST` |
| `port`    | `3310`     | `settings.CLAMAV_PORT` |

The host default matches the Docker Compose service name; no change is needed
for standard deployments.

### Usage

```python
from pathlib import Path
from fileguard.engines import ClamAVAdapter

adapter = ClamAVAdapter(host="clamav", port=3310)

# Check engine health (e.g. on startup)
if not adapter.ping():
    raise RuntimeError("ClamAV daemon is not reachable")

# Scan a file
findings = adapter.scan(Path("/tmp/upload.pdf"))
for finding in findings:
    print(f"Threat: {finding.category} (severity={finding.severity})")
```

### Scan result mapping

| clamd status | Adapter result |
|---|---|
| `"OK"` | Empty `findings` list |
| `"FOUND"` | One `Finding` per detected threat, `severity=CRITICAL` |
| `ConnectionError` | `AVEngineError` raised |
| Any other exception | `AVEngineError` raised |

---

## Writing a Custom Adapter

To integrate a commercial engine, subclass `AVEngineAdapter`:

```python
from pathlib import Path
from fileguard.engines import AVEngineAdapter, AVEngineError, Finding, FindingSeverity, FindingType


class SophosAdapter(AVEngineAdapter):
    """Example stub for a Sophos engine integration."""

    def __init__(self, api_url: str, api_key: str) -> None:
        self._url = api_url
        self._key = api_key

    def scan(self, file_path: Path) -> list[Finding]:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        try:
            raw = _call_sophos_api(self._url, self._key, file_path)
        except Exception as exc:
            raise AVEngineError(f"Sophos scan failed: {exc}") from exc
        return _map_sophos_results(raw)

    def ping(self) -> bool:
        try:
            return _sophos_health_check(self._url, self._key)
        except Exception:
            return False
```

---

## File Location

```
fileguard/
└── engines/
    ├── __init__.py   # public re-exports
    ├── base.py       # AVEngineAdapter, Finding, AVEngineError
    └── clamav.py     # ClamAVAdapter
tests/
└── unit/
    └── test_av_engine.py
```
