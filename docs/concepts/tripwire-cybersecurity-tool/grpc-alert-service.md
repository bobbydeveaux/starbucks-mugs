# gRPC Alert Service & WebSocket Broadcaster

This document describes the gRPC alert ingestion service and the in-process
WebSocket broadcaster that together form the real-time alert pipeline of the
TripWire dashboard server.

---

## Overview

```
TripWire Agent                 Dashboard Server
┌────────────┐  gRPC stream   ┌──────────────────────────────────┐
│ AgentEvent │──────────────▶ │  AlertService.StreamAlerts        │
└────────────┘  ServerCommand │   1. Validate event               │
                ◀──────────── │   2. Persist to PostgreSQL        │
                              │   3. Publish to Broadcaster ──▶ chan│
                              └──────────────────────────────────┘
                                         │
                                         ▼ (non-blocking fan-out)
                              ┌──────────────────────────────────┐
                              │  InProcessBroadcaster            │
                              │  sync.Map: ch1, ch2, ch3 ...     │
                              └──────────────────────────────────┘
                                   │         │         │
                                   ▼         ▼         ▼
                              WS client1  WS client2  WS client3
```

---

## gRPC Service

### Package

```
internal/server/grpc/alert_service.go
```

### Proto definition

```protobuf
// proto/alert.proto
service AlertService {
  rpc StreamAlerts(stream AgentEvent) returns (stream ServerCommand);
  rpc RegisterAgent(RegisterRequest) returns (RegisterResponse);
}
```

Generate Go code with:
```sh
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       proto/alert.proto
```

Pre-generated stubs live in `proto/alert/`.

### Constructor

```go
svc := grpc.NewAlertService(
    store,       // storage.Store (Postgres)
    broadcaster, // websocket.Broadcaster
    logger,      // *slog.Logger
    300,         // maxEventAgeSecs (0 = default 300)
)
```

### RegisterAgent

Upserts a `Host` record in PostgreSQL.  The hostname is taken from the mTLS
client-certificate CN when available, falling back to the `hostname` field in
the `RegisterRequest`.  Returns the dashboard-assigned `host_id` and the server
clock for skew compensation.

### StreamAlerts

Reads `AgentEvent` messages from the bidirectional client stream and for each:

1. **Validates** the event (required fields, timestamp bounds ±5 min/+60s,
   `tripwire_type` ∈ {FILE, NETWORK, PROCESS}, `severity` ∈ {INFO, WARN, CRITICAL},
   JSON validity of `event_detail_json`).
2. **Persists** a valid alert to PostgreSQL via `store.BatchInsertAlerts` (batched,
   100 ms flush interval).
3. **Publishes** the persisted alert to the WebSocket broadcaster using a
   **non-blocking send** — slow or disconnected WebSocket clients cannot stall
   the gRPC goroutine.
4. Sends an `ACK` `ServerCommand` back to the agent.  Invalid events receive an
   `ERROR` `ServerCommand` and are not written to the database.

---

## WebSocket Broadcaster

### Package

```
internal/server/websocket/broadcaster.go
```

### Interface

```go
type Broadcaster interface {
    Subscribe(ctx context.Context) <-chan storage.Alert
    Unsubscribe(ch <-chan storage.Alert)
    Publish(a storage.Alert)
    Close()
}
```

### InProcessBroadcaster

The concrete implementation for single-instance deployments.

```go
b := websocket.NewBroadcaster(logger, 64 /* per-subscriber buffer */)
defer b.Close()

// WebSocket handler subscribes on connect:
ch := b.Subscribe(clientCtx)

// Alert service publishes on every persisted event (non-blocking):
b.Publish(alert)

// WebSocket handler reads and writes to the browser:
for a := range ch {
    conn.WriteJSON(a)
}
```

### Fan-out semantics

| Property | Detail |
|---|---|
| **Delivery** | Best-effort; drops for full buffers |
| **Back-pressure** | None — `Publish` is always O(1) and non-blocking |
| **Concurrency** | `sync.Map` for lock-free subscriber enumeration |
| **Cleanup** | Context cancellation automatically calls `Unsubscribe` |
| **Multi-instance** | Replace `InProcessBroadcaster` with a Redis pub/sub adapter |

### Non-blocking publish

```go
// Inside Publish:
select {
case ch <- a:
    // delivered
default:
    logger.Warn("subscriber buffer full, dropping alert", ...)
}
```

A full subscriber buffer (caused by a slow or disconnected browser client)
results in a warning log and a dropped alert for **that subscriber only**.
Other subscribers and the gRPC ingestion goroutine are unaffected.

---

## Acceptance Criteria

| # | Criterion | Covered by |
|---|---|---|
| 1 | Each persisted alert is published to the broadcaster without blocking StreamAlerts | `Publish` non-blocking select/default |
| 2 | A slow/disconnected WebSocket consumer does not cause back-pressure on the gRPC stream | Per-subscriber buffered channel; drop-on-full |
| 3 | Integration test confirms an ingested event appears on a subscribed WebSocket connection | `TestIntegration_IngestedEventAppearsOnWebSocketSubscription` |

---

## Tests

```sh
go test ./internal/server/grpc/...
go test ./internal/server/websocket/...
```

Key test cases:

| Test | What it checks |
|---|---|
| `TestStreamAlerts_PersistsAndBroadcasts` | Happy path: persist + broadcast + ACK |
| `TestStreamAlerts_SlowSubscriberDoesNotBlock` | Criterion §2: 10 events with a full buffer completes quickly |
| `TestIntegration_IngestedEventAppearsOnWebSocketSubscription` | Criterion §3: end-to-end event delivery |
| `TestBroadcaster_SlowConsumer_DropsNotBlocks` | Publish never blocks on a slow consumer |
| `TestBroadcaster_ContextCancelUnsubscribes` | Automatic cleanup on context cancel |
| `TestStreamAlerts_InvalidTripwireType` | Validation: error ACK, no persistence |
| `TestStreamAlerts_StaleTimestamp` | Validation: reject events >5 min old |
| `TestStreamAlerts_StoreError_SendsErrorACK` | DB failure: error ACK, no broadcast |
