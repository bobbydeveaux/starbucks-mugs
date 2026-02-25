# TripWire Agent — Core & Configuration

This document describes the Go packages that form the core of the TripWire
agent binary: configuration loading, the agent orchestrator, and the `/healthz`
liveness endpoint.

---

## Overview

The TripWire agent is a statically-compiled Go binary (`cmd/agent/main.go`)
that:

1. Loads a YAML configuration file (`internal/config`).
2. Instantiates and starts the agent orchestrator (`internal/agent`).
3. Creates one `FileWatcher` per `FILE`-type rule (`internal/watcher`) and
   registers them with the orchestrator via `agent.WithWatchers`.
4. Wires watcher, queue, and transport components together via the agent's
   goroutine lifecycle.
5. Serves a `/healthz` HTTP endpoint on a loopback address so health-check
   tooling can probe the agent without opening external inbound ports.
6. Handles `SIGTERM`/`SIGINT` for graceful shutdown.

For file watcher details see [`file-watcher.md`](file-watcher.md).

---

## Package: `internal/config`

**File:** `internal/config/config.go`

### Config struct

```go
type Config struct {
    DashboardAddr string        // Required. gRPC endpoint of the dashboard.
    TLS           TLSConfig     // Required. mTLS certificate paths.
    Rules         []TripwireRule
    LogLevel      string        // "debug" | "info" | "warn" | "error". Default: "info".
    HealthAddr    string        // Listen address for /healthz. Default: "127.0.0.1:9000".
    AgentVersion  string        // Sent to dashboard on registration.
}

type TLSConfig struct {
    CertPath string // Required. PEM agent client certificate.
    KeyPath  string // Required. PEM agent private key.
    CAPath   string // Required. PEM CA certificate for dashboard verification.
}

type TripwireRule struct {
    Name     string // Required. Human-readable rule identifier.
    Type     string // Required. FILE | NETWORK | PROCESS.
    Target   string // Required. Path glob, port number, or process name.
    Severity string // Required. INFO | WARN | CRITICAL.
}
```

### LoadConfig

```go
func LoadConfig(path string) (*Config, error)
```

Reads the YAML file at `path`, unmarshals it into `Config`, applies defaults
(`log_level: "info"`, `health_addr: "127.0.0.1:9000"`), and validates all
required fields. Returns a descriptive error for any missing required field or
invalid enumerated value.

**Required fields:** `dashboard_addr`, `tls.cert_path`, `tls.key_path`,
`tls.ca_path`.

---

## Package: `internal/agent`

**File:** `internal/agent/agent.go`

### Interfaces

```go
type Watcher interface {
    Start(ctx context.Context) error
    Stop()
    Events() <-chan AlertEvent
}

type Queue interface {
    Enqueue(ctx context.Context, evt AlertEvent) error
    Depth() int
    Close() error
}

type Transport interface {
    Start(ctx context.Context) error
    Send(ctx context.Context, evt AlertEvent) error
    Stop()
}
```

These interfaces are the contracts implemented by the file, network, and
process watcher packages, the SQLite alert queue, and the gRPC transport
client respectively.

### AlertEvent

```go
type AlertEvent struct {
    TripwireType string         // "FILE" | "NETWORK" | "PROCESS"
    RuleName     string
    Severity     string         // "INFO" | "WARN" | "CRITICAL"
    Timestamp    time.Time
    Detail       map[string]any // type-specific metadata
}
```

### Agent

```go
func New(cfg *config.Config, logger *slog.Logger, opts ...Option) *Agent
func (a *Agent) Start(ctx context.Context) error
func (a *Agent) Stop()
func (a *Agent) Health() HealthStatus
func (a *Agent) HealthzHandler(w http.ResponseWriter, r *http.Request)
```

#### Functional options

| Option | Description |
|--------|-------------|
| `WithWatchers(ws ...Watcher)` | Register one or more watcher components |
| `WithQueue(q Queue)` | Register the local alert queue |
| `WithTransport(t Transport)` | Register the gRPC transport client |

#### Start / Stop lifecycle

`Start` initialises all registered components in order:

1. Transport is started first so watchers can deliver events immediately.
2. Each watcher is started; a per-watcher goroutine reads from its `Events()`
   channel and calls `handleEvent`.
3. Returns a non-nil error if any component fails to initialise; the agent
   rolls back to a clean state.

`Stop` cancels the shared context, stops all watchers, waits for the
event-processing goroutines (`sync.WaitGroup`), stops the transport, and
closes the queue. It is safe to call `Stop` multiple times.

#### Event processing

Each alert event is:
1. Recorded in the local queue (`Queue.Enqueue`) for at-least-once delivery.
2. Forwarded to the transport (`Transport.Send`) for immediate streaming to
   the dashboard.
3. Timestamped as `lastAlertAt` for the `/healthz` response.

Errors from the queue or transport are logged as warnings but do not halt the
agent.

### HealthStatus

```go
type HealthStatus struct {
    Status      string  `json:"status"`       // always "ok"
    UptimeS     float64 `json:"uptime_s"`     // seconds since agent start
    QueueDepth  int     `json:"queue_depth"`  // pending events in local queue
    LastAlertAt string  `json:"last_alert_at,omitempty"` // RFC3339 or omitted
}
```

---

## Package: `internal/agent` — NetworkWatcher

**File:** `internal/agent/network_watcher.go`

`NetworkWatcher` implements the `Watcher` interface for NETWORK-type tripwire
rules.  It polls `/proc/net/tcp` and `/proc/net/tcp6` on a configurable
interval, compares each snapshot against the previous one, and emits an
`AlertEvent` whenever a new TCP ESTABLISHED connection is detected on a
monitored local port.

### Key types

```go
// ConnKey uniquely identifies an active network connection.
type ConnKey struct {
    LocalAddr  string // "ip:port"
    RemoteAddr string // "ip:port"
    Protocol   string // "tcp" or "tcp6"
}

// ProcReader returns the current set of established connections.
// The default implementation reads /proc/net/tcp*; inject a stub in tests.
type ProcReader func() (map[ConnKey]struct{}, error)

// ConnEntry is returned by ParseProcNetFile.
type ConnEntry struct {
    LocalAddr  string
    RemoteAddr string
    Protocol   string
}
```

### Constructors

```go
// NewNetworkWatcher uses the real /proc/net/tcp* reader.
func NewNetworkWatcher(
    rules        []config.TripwireRule,
    logger       *slog.Logger,
    pollInterval time.Duration,
) (*NetworkWatcher, error)

// NewNetworkWatcherWithReader accepts an injectable ProcReader for testing.
func NewNetworkWatcherWithReader(
    rules        []config.TripwireRule,
    logger       *slog.Logger,
    pollInterval time.Duration,
    reader       ProcReader,
) (*NetworkWatcher, error)
```

- Only `TripwireRule` entries with `Type == "NETWORK"` are compiled; other
  types are silently skipped.
- `Target` must be a valid port number in `[1, 65535]`; an error is returned
  if it is not.
- `pollInterval <= 0` defaults to 1 second.

### AlertEvent detail fields

| Key | Type | Description |
|-----|------|-------------|
| `local_addr` | `string` | Local "ip:port" of the connection |
| `remote_addr` | `string` | Remote "ip:port" of the connection |
| `protocol` | `string` | `"tcp"` or `"tcp6"` |

### Low-level helpers (exported for testing)

```go
// ParseProcNetFile parses a /proc/net/tcp or /proc/net/tcp6 file.
// Returns only ESTABLISHED connections (socket state 0x01).
func ParseProcNetFile(path, proto string) ([]ConnEntry, error)

// HexToAddr decodes a /proc/net hex address ("XXXXXXXX:PPPP" or
// "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:PPPP") into a "host:port" string.
func HexToAddr(hexAddr string) (string, error)
```

### How polling works

1. Every `pollInterval` the watcher calls `ProcReader` to obtain the current
   set of ESTABLISHED connections (`map[ConnKey]struct{}`).
2. Entries in the current set that were **absent** from the previous snapshot
   are classified as new connections.
3. Each new connection is checked against every compiled rule.  A match on
   local port fires an `AlertEvent` into the buffered events channel.
4. The previous snapshot is replaced by the current one, so persistent
   connections never re-fire.
5. If the reader returns an error the poll is skipped and the previous snapshot
   is retained; monitoring resumes on the next tick.

### Lifecycle

```
NewNetworkWatcher → Start(ctx) → polling goroutine begins
                 → Stop()      → goroutine exits, Events() channel closed
```

`Stop()` is idempotent and safe to call multiple times.  Monitoring also stops
when the context passed to `Start` is cancelled.

If no NETWORK rules are configured the goroutine exits immediately after
`Start`, closing the events channel with no polls performed.

---

## Binary: `cmd/agent/main.go`

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `-config` | `/etc/tripwire/config.yaml` | Path to the YAML configuration file |

### Logging

A structured JSON `slog.Logger` is initialised from `Config.LogLevel` and
set as the default logger. All agent packages use the default logger or accept
a `*slog.Logger` argument.

### Watcher registration

`cmd/agent/main.go` calls `buildFileWatchers(cfg, logger)` which iterates
over all configured rules and creates one `watcher.FileWatcher` per `FILE`-type
rule. The resulting slice is passed to `agent.WithWatchers(...)` so the
orchestrator manages their lifecycle.

```go
func buildFileWatchers(cfg *config.Config, logger *slog.Logger) []agent.Watcher
```

### Signal handling

`SIGTERM` and `SIGINT` trigger graceful shutdown:

1. `Agent.Stop()` is called — watchers (including all `FileWatcher` instances),
   transport, and queue are closed.
2. The `/healthz` HTTP server is shut down with a 10-second timeout.
3. The process exits 0.

### /healthz endpoint

`GET /healthz` is served on `Config.HealthAddr` (default `127.0.0.1:9000`).
The agent does **not** bind to external interfaces for this endpoint.

**Response:** `200 OK`, `Content-Type: application/json`

```json
{
  "status": "ok",
  "uptime_s": 42.3,
  "queue_depth": 7,
  "last_alert_at": "2026-02-25T19:30:00Z"
}
```

`last_alert_at` is omitted when no alert has been processed since agent start.

---

## Package: `internal/watcher`

The `FileWatcher` in `internal/watcher/file.go` implements the `Watcher`
interface by polling the filesystem every 100 ms (configurable). It detects
file creates, writes, and deletes on the paths defined by `FILE`-type
tripwire rules.

See [`file-watcher.md`](file-watcher.md) for the full FileWatcher reference
and end-to-end SLA test documentation.

---

## Configuration file

See [`deployments/config/config.example.yaml`](../../../deployments/config/config.example.yaml)
for a fully-annotated example configuration.

---

## Running the agent

```bash
# Build
go build -o tripwire-agent ./cmd/agent

# Run with config
./tripwire-agent -config /etc/tripwire/config.yaml

# Health probe
curl http://127.0.0.1:9000/healthz
```
