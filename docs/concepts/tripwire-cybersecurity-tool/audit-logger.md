# TripWire Agent — SHA-256 Chained Audit Logger

This document describes the append-only, tamper-evident audit logger
implemented in `internal/audit/audit_logger.go`.

---

## Overview

The audit logger provides a forensic, append-only log of security events
recorded by the TripWire agent. Each log entry is cryptographically linked
to its predecessor via a SHA-256 hash chain, making any modification,
insertion, or deletion detectable.

---

## Package: `internal/audit`

**File:** `internal/audit/audit_logger.go`

### Hash chain

Each entry's `event_hash` is computed as:

```
event_hash = SHA-256( JSON({seq, ts, payload, prev_hash}) )
```

Where:

- `seq` — monotonically increasing integer (starts at 1)
- `ts` — UTC timestamp of the entry
- `payload` — arbitrary JSON payload (the alert detail)
- `prev_hash` — the `event_hash` of the immediately preceding entry

The genesis entry (first entry ever written) uses a `prev_hash` of 64 ASCII
zero characters (`"000...0"`, exported as `audit.GenesisHash`).

This construction means that any modification to **any** field of any entry,
or any deletion or insertion of an entry, causes all subsequent `event_hash`
values to diverge from the values computed during verification.

### Wire format

Each entry is written as a single JSON line terminated by `\n`:

```json
{
  "seq": 1,
  "ts": "2026-02-25T19:30:00.123456789Z",
  "payload": {"tripwire_type": "FILE", "rule": "etc-passwd"},
  "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "event_hash": "a3f1..."
}
```

### File append semantics

The log file is opened with `os.O_APPEND | os.O_CREATE | os.O_WRONLY` and
mode `0600`. POSIX guarantees that `write(2)` with `O_APPEND` is atomic for
writes not exceeding `PIPE_BUF` bytes. JSON audit entries are kept small
enough to satisfy this in practice, so concurrent processes cannot interleave
partial writes.

---

## API

### `Open(path string) (*Logger, error)`

Opens (or creates) the log file at `path`. If the file already contains
entries, `Open` reads them all to:

1. Verify the integrity of the existing chain.
2. Restore the current sequence number and `prev_hash` so that subsequent
   `Append` calls continue the chain correctly.

Returns an error if the file cannot be opened, any entry is malformed, or
the chain is broken.

### `(*Logger).Append(payload json.RawMessage) (Entry, error)`

Writes a new tamper-evident entry. `payload` must be valid JSON; passing
`nil` records a JSON `null` payload.

Returns the populated `Entry` (including the assigned sequence number,
timestamp, `EventHash`, and `PrevHash`) so callers can persist chain
metadata without re-reading the file.

`Append` is **safe for concurrent use** — a mutex serialises all calls.

### `(*Logger).Close() error`

Syncs the underlying file and closes it.

### `Verify(path string) ([]Entry, error)`

Reads the entire log file at `path` and verifies the full hash chain from
genesis to the last entry. Returns the ordered slice of `Entry` values on
success, or the first chain error encountered (hash mismatch or `prev_hash`
linkage break). An empty file is valid and returns an empty slice.

```go
entries, err := audit.Verify("/var/log/tripwire/audit.log")
if err != nil {
    log.Printf("ALERT: audit log tampered: %v", err)
}
```

---

## Usage example

```go
import "github.com/tripwire/agent/internal/audit"

// Open (or resume) the audit log.
logger, err := audit.Open("/var/log/tripwire/audit.log")
if err != nil {
    log.Fatalf("audit: %v", err)
}
defer logger.Close()

// Append an event payload.
payload, _ := json.Marshal(map[string]any{
    "tripwire_type": "FILE",
    "rule":         "etc-passwd-watch",
    "path":         "/etc/passwd",
})
entry, err := logger.Append(payload)
if err != nil {
    log.Printf("audit append: %v", err)
}
log.Printf("audit seq=%d hash=%s", entry.Seq, entry.EventHash)
```

---

## Testing

Unit tests live in `internal/audit/audit_logger_test.go` and cover:

| Test | Description |
|---|---|
| `TestAppend_SingleEntry` | Seq=1, genesis prev_hash, 64-char event_hash |
| `TestAppend_MultipleEntries_Chain` | Correct chaining across three entries |
| `TestAppend_HashMatchesManualComputation` | SHA-256 of JSON content matches returned hash |
| `TestAppend_NilPayload` | nil payload becomes JSON `null` |
| `TestAppend_GenesisHash_IsAllZeros` | GenesisHash is exactly 64 zero chars |
| `TestOpen_ResumeExistingChain` | Re-opening a file continues the chain at the correct seq |
| `TestVerify_EmptyFile` | Empty file returns zero entries without error |
| `TestVerify_ValidChain` | Five entries verify cleanly |
| `TestVerify_DetectsModifiedPayload` | Flipped bool in payload triggers error |
| `TestVerify_DetectsDeletedEntry` | Removing first line triggers chain-break error |
| `TestVerify_DetectsModifiedEventHash` | Forged event_hash triggers mismatch error |
| `TestOpen_RejectsCorruptedLog` | Corrupted existing file prevents opening |
| `TestAppend_ConcurrentSafe` | 10 goroutines × 20 appends produce a valid chain |

Run with:

```bash
go test ./internal/audit/...
```

---

## Security considerations

- The log file is created with mode `0600` (owner read/write only).
- The log is **never automatically truncated**. Operators must rotate the
  file and begin a new chain in the rotated copy. After rotation, re-open
  the logger to start a new chain in the new file.
- Hash-chaining detects tampering but does not prevent it. For stronger
  guarantees, store the `event_hash` of the last-known-good entry in a
  separate, write-protected location (e.g. a hardware TPM or a remote
  attestation service).
- The genesis hash (`audit.GenesisHash`) is a public constant. An attacker
  who can rewrite the entire log from scratch can forge a valid chain.
  Out-of-band verification (e.g. comparing the `event_hash` of a specific
  entry against a securely stored reference) is required to detect this.
