# DispositionEngine

**Module:** `fileguard.core.disposition`
**Status:** Implemented (Sprint 4)

---

## Overview

The `DispositionEngine` evaluates AV and PII findings accumulated in a
`ScanContext` against per-tenant, per-file-type disposition rules and
produces a final `DispositionResult` of **block**, **quarantine**, or
**pass** (with optional flags).

**Design principles:**

| Principle | Implementation |
|---|---|
| Fail-secure | Any unhandled exception during evaluation always results in `block`; a file is never silently passed through on error |
| Configurable per-tenant | Rules stored as JSONB in `TenantConfig.disposition_rules`; evaluated at scan time without restart |
| Per-MIME-type overrides | `mime_type_overrides` map lets tenants configure different actions for specific file types |
| Quarantine delegation | Quarantine storage is delegated to an injectable `QuarantineService`; absent or failing service falls back to `block` |
| Stateless | The same `DispositionEngine` instance can be used concurrently from multiple asyncio tasks |

---

## Files

| File | Purpose |
|---|---|
| `fileguard/core/disposition.py` | `DispositionEngine`, `DispositionResult`, `QuarantineService` interface, `QuarantineError` |
| `fileguard/tests/test_disposition.py` | Full unit test suite covering all disposition outcomes and edge cases |

---

## Disposition Rule Schema

Rules are stored as JSONB in `TenantConfig.disposition_rules` and resolved at scan time.

```json
{
    "on_error":     "block",
    "on_av_threat": "block",
    "on_pii":       "pass",
    "mime_type_overrides": {
        "application/pdf": {
            "on_pii": "quarantine"
        }
    }
}
```

### Rule Keys

| Key | Description | Valid Values | Default |
|---|---|---|---|
| `on_error` | Action when `context.errors` is non-empty | `"block"`, `"quarantine"`, `"pass"` | `"block"` |
| `on_av_threat` | Action when AV-threat findings are present | `"block"`, `"quarantine"`, `"pass"` | `"block"` |
| `on_pii` | Action when PII findings are present | `"block"`, `"quarantine"`, `"pass"` | `"pass"` |
| `mime_type_overrides` | Per-MIME-type rule overrides (applied before top-level rules) | Object keyed by MIME type | `{}` |

All keys are optional. Built-in defaults apply whenever a key is absent or contains an invalid value.

### Rule Resolution Order

For each rule key (`on_error`, `on_av_threat`, `on_pii`), the engine resolves the action as follows:

1. **MIME-type override** — `rules["mime_type_overrides"][mime_type][rule_key]`
2. **Top-level rule** — `rules[rule_key]`
3. **Built-in default** — see table above

Invalid action values (anything other than `"block"`, `"quarantine"`, `"pass"`) are silently ignored and the next level is tried.

---

## Evaluation Priority

Within a scan context, conditions are evaluated in this priority order:

1. **Scan errors** (`context.errors` non-empty) — highest priority; applies `on_error` rule
2. **AV-threat findings** — applies `on_av_threat` rule
3. **PII findings** — applies `on_pii` rule
4. **No findings** — clean pass, `action="pass"`, `status="clean"`

---

## Disposition Actions and Status

| Action | Status | When |
|---|---|---|
| `"pass"` | `"clean"` | No findings, no errors |
| `"pass"` | `"flagged"` | Findings present but rule says `"pass"` (pass-with-flags) |
| `"block"` | `"rejected"` | Rule says `"block"`, or fail-secure triggered |
| `"quarantine"` | `"rejected"` | Rule says `"quarantine"` and `QuarantineService` succeeds |

---

## Classes

### `DispositionEngine`

```python
class DispositionEngine:
    def __init__(
        self,
        quarantine_service: QuarantineService | None = None,
    ) -> None: ...

    async def decide(
        self,
        context: ScanContext,
        rules: dict[str, Any] | None = None,
    ) -> DispositionResult: ...
```

The engine is constructed once and reused across scans. Inject a
`QuarantineService` to enable quarantine actions; omit it to fall back
to block on quarantine decisions.

#### `decide(context, rules)`

Primary pipeline entry point. Reads `context.findings` and `context.errors`,
resolves the applicable rules, and returns an immutable `DispositionResult`.

**Fail-secure:** any unhandled exception is caught, logged, and produces a
`block` outcome. The exception message is included in `result.reasons`.

### `DispositionResult`

Immutable frozen dataclass returned by `DispositionEngine.decide()`.

```python
@dataclass(frozen=True)
class DispositionResult:
    action: Literal["pass", "quarantine", "block"]
    status: Literal["clean", "flagged", "rejected"]
    quarantine_ref: str | None        # set when action == "quarantine"
    reasons: list[str]                # human-readable decision trail
```

### `QuarantineService`

Abstract base class that must be implemented by quarantine storage backends.

```python
class QuarantineService(ABC):
    @abstractmethod
    async def store(self, context: ScanContext) -> str: ...
```

`store()` must:
- Read `context.file_bytes` and `context.scan_id`
- Encrypt and persist the file
- Return an opaque quarantine reference string
- Raise `QuarantineError` on any storage failure

### `QuarantineError`

Raised by `QuarantineService.store()` when storage fails.  The
`DispositionEngine` catches this and falls back to `block`.

---

## Pipeline Integration

```python
from fileguard.core.disposition import DispositionEngine
from fileguard.core.scan_context import ScanContext

# Construct once (stateless; safe to share across coroutines)
engine = DispositionEngine(quarantine_service=my_quarantine_service)

# Per-scan usage
ctx = ScanContext(file_bytes=raw_bytes, mime_type="application/pdf")
# ... run AV scan, PII detection steps ...
result = await engine.decide(ctx, rules=tenant_config.disposition_rules)

match result.action:
    case "pass":
        return {"status": result.status, "action": "pass"}
    case "block":
        raise HTTPException(status_code=403, detail="File rejected")
    case "quarantine":
        return {"status": "rejected", "quarantine_ref": result.quarantine_ref}
```

---

## Fail-Secure Guarantees

1. **Exception safety:** The outer `decide()` method wraps `_evaluate()` in a
   broad `except Exception` catch. Any unexpected exception yields
   `action="block"` with a reason string describing the exception type and
   message.

2. **Scan errors:** When `context.errors` is non-empty (set by upstream
   pipeline steps on AV or PII backend failures), the engine applies
   `on_error` (default `"block"`) without inspecting findings.

3. **Quarantine fallback:** If no `QuarantineService` is configured, or if
   `QuarantineService.store()` raises any exception, the quarantine action
   falls back to `block` automatically.

4. **Invalid rules:** Unrecognised action values in the rules dict are silently
   ignored; the engine falls through to the next resolution level (top-level
   rule, then built-in default).

---

## Testing

All disposition outcomes and edge cases are covered by
`fileguard/tests/test_disposition.py`:

| Test class | Coverage |
|---|---|
| `TestCleanPass` | No findings → `pass`/`clean` |
| `TestAVThreatDisposition` | AV-threat rule resolution, MIME overrides, multi-threat reasons |
| `TestPIIDisposition` | PII pass-with-flags, block, quarantine, MIME overrides, AV priority |
| `TestScanErrorDisposition` | Error-triggered block, custom `on_error` rule, error priority |
| `TestQuarantineFallback` | No service → block; `QuarantineError` → block; unexpected exception → block |
| `TestFailSecureException` | Exception during evaluation → block, never pass |
| `TestRuleEdgeCases` | Empty rules, unknown MIME type, invalid action values |
| `TestResolveAction` | `_resolve_action` helper priority and defaults |
| `TestDeriveStatus` | `_derive_status` all action/findings combinations |
| `TestDispositionResult` | Immutability, field defaults |
| `TestQuarantineServiceInterface` | Abstract interface, `QuarantineError` type |
