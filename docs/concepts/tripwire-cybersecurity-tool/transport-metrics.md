# Transport Layer – Prometheus Metrics

**Status:** Implemented (Sprint 4)

This document describes the Prometheus-compatible metrics exported by the TripWire
agent's gRPC transport layer and explains how to wire them into an HTTP endpoint
that a Prometheus server can scrape.

---

## Overview

The transport package exposes operational counters and a connection gauge through a
zero-dependency, pure-Go implementation that produces output in the standard
[Prometheus text exposition format (v0.0.4)][prom-text-format].  No external
libraries are required — the metrics are serialised using `fmt` and `sync/atomic`.

The `Metrics` type is decoupled from the `Client` via the `WithMetrics` functional
option.  Callers that do not pass `WithMetrics` incur zero overhead (all helper
calls reduce to a single nil-pointer check).

---

## Metric Reference

All metric names are prefixed with `transport_`.

| Metric name | Type | Description |
|---|---|---|
| `transport_connection_attempts_total` | counter | Total gRPC connection attempts |
| `transport_connection_errors_total` | counter | Connection attempts that failed |
| `transport_reconnect_attempts_total` | counter | Reconnect cycles after a transient error |
| `transport_agent_registrations_total` | counter | `RegisterAgent` RPCs attempted |
| `transport_registration_errors_total` | counter | `RegisterAgent` RPCs that returned an error |
| `transport_alerts_sent_total` | counter | `AgentEvent` messages delivered to the dashboard |
| `transport_stream_send_errors_total` | counter | `stream.Send` calls that returned an error |
| `transport_stream_recv_errors_total` | counter | `stream.Recv` calls that returned a non-EOF error |
| `transport_connected` | gauge | `1` while a bidirectional alert stream is active, `0` otherwise |

---

## Wiring the Metrics Endpoint

### 1. Create the metrics object

```go
m := transport.NewMetrics()
```

### 2. Pass it to the transport client

```go
client := transport.New(cfg, logger, transport.WithMetrics(m))
```

### 3. Serve the `/metrics` HTTP endpoint

The `Metrics.Handler()` method returns a standard `http.Handler` that writes all
metrics in Prometheus text format on every request:

```go
mux := http.NewServeMux()
mux.Handle("/metrics", m.Handler())
mux.Handle("/healthz", healthHandler)

srv := &http.Server{Addr: cfg.Health.Address, Handler: mux}
go srv.ListenAndServe()
```

The default health endpoint address is `127.0.0.1:9090` (see `health.address` in
`config.example.yaml`).  By default the metrics endpoint is only reachable from
the loopback interface — change `health.address` if you need off-host access.

### 4. Example scrape output

```
# HELP transport_connection_attempts_total Total number of gRPC connection attempts made by the transport client.
# TYPE transport_connection_attempts_total counter
transport_connection_attempts_total 1
# HELP transport_connection_errors_total Total number of gRPC connection attempts that returned an error.
# TYPE transport_connection_errors_total counter
transport_connection_errors_total 0
# HELP transport_reconnect_attempts_total Total number of reconnection cycles initiated after a transient error.
# TYPE transport_reconnect_attempts_total counter
transport_reconnect_attempts_total 0
# HELP transport_agent_registrations_total Total number of RegisterAgent RPCs attempted.
# TYPE transport_agent_registrations_total counter
transport_agent_registrations_total 1
# HELP transport_registration_errors_total Total number of RegisterAgent RPCs that returned an error.
# TYPE transport_registration_errors_total counter
transport_registration_errors_total 0
# HELP transport_alerts_sent_total Total number of AgentEvent messages successfully delivered to the dashboard.
# TYPE transport_alerts_sent_total counter
transport_alerts_sent_total 42
# HELP transport_stream_send_errors_total Total number of stream.Send calls that returned an error.
# TYPE transport_stream_send_errors_total counter
transport_stream_send_errors_total 0
# HELP transport_stream_recv_errors_total Total number of stream.Recv calls that returned a non-EOF error.
# TYPE transport_stream_recv_errors_total counter
transport_stream_recv_errors_total 0
# HELP transport_connected 1 when a bidirectional alert stream is currently active, 0 otherwise.
# TYPE transport_connected gauge
transport_connected 1
```

---

## Prometheus Configuration

Add the agent's health address to your `prometheus.yml` scrape config:

```yaml
scrape_configs:
  - job_name: tripwire-agent
    static_configs:
      - targets:
          - "10.0.1.42:9090"   # agent health.address
    metrics_path: /metrics
    scrape_interval: 15s
```

---

## Key Alerting Rules

The following PromQL expressions are useful starting points for alerting:

```yaml
groups:
  - name: tripwire-transport
    rules:
      # Agent has been disconnected for more than 60 seconds.
      - alert: TripwireAgentDisconnected
        expr: transport_connected == 0
        for: 60s
        labels:
          severity: warning
        annotations:
          summary: "TripWire agent is not connected to the dashboard"

      # More than 5 registration errors in the last 5 minutes.
      - alert: TripwireRegistrationErrors
        expr: increase(transport_registration_errors_total[5m]) > 5
        labels:
          severity: warning
        annotations:
          summary: "TripWire agent is repeatedly failing to register"

      # More than 10 reconnect attempts in the last 5 minutes.
      - alert: TripwireHighReconnectRate
        expr: increase(transport_reconnect_attempts_total[5m]) > 10
        labels:
          severity: warning
        annotations:
          summary: "TripWire agent is reconnecting frequently"
```

---

## Design Notes

### No external dependencies

The metrics implementation uses only the Go standard library (`sync/atomic`,
`fmt`, `net/http`).  This keeps the agent binary small and avoids pulling in the
full `github.com/prometheus/client_golang` dependency tree.

### Thread safety

All counter and gauge fields use `sync/atomic.Int64` (`Add`, `Store`, `Load`).
The HTTP handler captures a consistent snapshot of all values before writing,
meaning a scrape never observes a partial update.

### No-op when disabled

When `WithMetrics` is not passed to `New`, all metric helper calls inside the
client reduce to a single `if c.metrics != nil` check and are eliminated by the
Go compiler as a no-op branch.  There is no measurable overhead on the hot path.

---

[prom-text-format]: https://prometheus.io/docs/instrumenting/exposition_formats/
