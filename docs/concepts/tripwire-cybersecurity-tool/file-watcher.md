# TripWire Agent — File Watcher

This document describes the `internal/watcher` package, specifically the
`FileWatcher` component that monitors filesystem paths for changes and emits
`AlertEvent`s through the agent pipeline.

---

## Overview

The `FileWatcher` is a polling-based filesystem monitor that satisfies the
[`watcher.Watcher`](#watcher-interface) interface. It scans configured
directory and file targets every **100 ms** (default), detects creates,
writes, and deletes, and forwards `AlertEvent`s to the agent orchestrator.

### Why polling?

Polling with a 100 ms interval guarantees detection within ≤ 200 ms worst
case — more than **25× margin** against the 5-second alert SLA stated in
[PRD Goal G-2 and User Story US-01](PRD.md). It requires no kernel-level
hooks, works uniformly across Linux, macOS, and Windows, and tolerates
watched paths that do not yet exist at agent startup.

---

## Package: `internal/watcher`

The `internal/watcher` package contains two files:

| File | Contents |
|------|----------|
| `internal/watcher/watcher.go` | `AlertEvent` type and `Watcher` interface |
| `internal/watcher/file.go`   | `FileWatcher` implementation |

---

## Watcher interface

**File:** `internal/watcher/watcher.go`

```go
// AlertEvent is emitted by a Watcher when a monitored resource changes.
type AlertEvent struct {
    TripwireType string         // "FILE" | "NETWORK" | "PROCESS"
    RuleName     string
    Severity     string         // "INFO" | "WARN" | "CRITICAL"
    Timestamp    time.Time
    Detail       map[string]any // type-specific metadata
}

// Watcher is the common interface for all watcher implementations.
type Watcher interface {
    Start(ctx context.Context) error
    Stop()
    Events() <-chan AlertEvent
}
```

All concrete watcher types (`FileWatcher`, `NetworkWatcher`, and the planned
`ProcessWatcher`) implement this interface. The agent orchestrator depends on
`watcher.Watcher` and `watcher.AlertEvent`; the `agent` package re-exports
both as type aliases for backward compatibility:

```go
// In internal/agent/agent.go:
type AlertEvent = watcher.AlertEvent
type Watcher    = watcher.Watcher
```

---

## FileWatcher

**File:** `internal/watcher/file.go`

```go
type FileWatcher struct { /* unexported */ }

func NewFileWatcher(rules []config.TripwireRule, logger *slog.Logger, interval time.Duration) *FileWatcher
func (fw *FileWatcher) Start(ctx context.Context) error
func (fw *FileWatcher) Stop()
func (fw *FileWatcher) Events() <-chan watcher.AlertEvent
func (fw *FileWatcher) Ready() <-chan struct{}
```

### `NewFileWatcher`

Constructs a `FileWatcher` from the slice of rules. Rules with a type other
than `"FILE"` are silently ignored so that the complete rule set can be passed
without pre-filtering.

| Parameter  | Description |
|------------|-------------|
| `rules`    | Slice of `TripwireRule`; only `Type == "FILE"` entries are used |
| `logger`   | Structured logger for diagnostic messages |
| `interval` | Poll frequency; `0` or negative uses `DefaultPollInterval` (100 ms) |

### `Start`

Launches the background polling goroutine. Returns immediately and always
returns `nil`. It is safe to call `Start` once per watcher instance.

### `Stop`

Signals the goroutine to exit and blocks until it has done so, then closes
the `Events` channel. Safe to call multiple times (idempotent).

### `Events`

Returns the read-only channel on which `AlertEvent`s are delivered. The
channel is closed when `Stop` returns.

### `Ready`

Returns a channel that is closed once the **initial filesystem snapshot** has
been taken. Waiting on `Ready()` before triggering filesystem operations in
tests eliminates race conditions where a pre-existing file would be missed.

---

## Event types

| Filesystem change | `Detail["operation"]` |
|-------------------|-----------------------|
| New file appears  | `"create"`            |
| File size or mtime changes | `"write"` |
| File removed      | `"delete"`            |

Sub-directory entries are **not** watched recursively. Only immediate children
of a directory target are tracked.

---

## AlertEvent payload

```json
{
  "tripwire_type": "FILE",
  "rule_name":     "etc-passwd-watch",
  "severity":      "CRITICAL",
  "timestamp":     "2026-02-25T19:30:00Z",
  "detail": {
    "path":      "/etc/passwd",
    "operation": "write"
  }
}
```

---

## Wiring into the agent

```go
fw := watcher.NewFileWatcher(cfg.Rules, logger, 0) // 0 → 100 ms default

ag := agent.New(cfg, logger,
    agent.WithWatchers(fw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)

if err := ag.Start(ctx); err != nil {
    log.Fatal(err)
}
```

---

## 5-second SLA validation

The end-to-end alert emission SLA is validated by integration tests in
`internal/watcher/file_test.go`. The key test is:

**`TestE2E_FileAlertEmission_WithinSLA`** — wires a real `FileWatcher` into
the `Agent` orchestrator with a fake transport, triggers a file creation, and
asserts the `AlertEvent` arrives at the transport **within 5 seconds**.

```
go test -v -run TestE2E ./internal/watcher/...
```

Typical observed latency: **< 200 ms** (limited by the 50 ms poll interval
used in tests).

---

## Configuration

The `FileWatcher` is driven by `FILE`-type rules in the agent configuration:

```yaml
rules:
  - name: etc-passwd-watch
    type: FILE
    target: /etc/passwd
    severity: CRITICAL

  - name: home-dir-watch
    type: FILE
    target: /home/operator
    severity: WARN
```

See [`agent-configuration.md`](agent-configuration.md) for the full
configuration reference.

---

## Test coverage

| Test | Description |
|------|-------------|
| `TestFileWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestFileWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestFileWatcher_IgnoresNonFileRules` | Non-FILE rules filtered silently |
| `TestFileWatcher_DetectsFileCreate` | CREATE event emitted for new files |
| `TestFileWatcher_DetectsFileWrite` | WRITE event emitted for modified files |
| `TestFileWatcher_DetectsFileDelete` | DELETE event emitted for removed files |
| `TestFileWatcher_WatchesSingleFile` | Single-file (not directory) target |
| `TestFileWatcher_ReadyChannelClosedAfterStart` | Ready() fires after Start |
| `TestE2E_FileAlertEmission_WithinSLA` | **5-second SLA acceptance test** |
| `TestE2E_FileAlertEmission_MultipleEvents` | Multiple events all within SLA |
| `TestE2E_FileAlertEmission_AgentStop` | Agent.Stop during active watch |
