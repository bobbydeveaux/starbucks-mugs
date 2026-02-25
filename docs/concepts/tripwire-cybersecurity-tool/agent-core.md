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
3. Wires watcher, queue, and transport components together via the agent's
   goroutine lifecycle.
4. Serves a `/healthz` HTTP endpoint on a loopback address so health-check
   tooling can probe the agent without opening external inbound ports.
5. Handles `SIGTERM`/`SIGINT` for graceful shutdown.

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

## Binary: `cmd/agent/main.go`

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `-config` | `/etc/tripwire/config.yaml` | Path to the YAML configuration file |

### Logging

A structured JSON `slog.Logger` is initialised from `Config.LogLevel` and
set as the default logger. All agent packages use the default logger or accept
a `*slog.Logger` argument.

### Signal handling

`SIGTERM` and `SIGINT` trigger graceful shutdown:

1. `Agent.Stop()` is called — watchers, transport, and queue are closed.
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
