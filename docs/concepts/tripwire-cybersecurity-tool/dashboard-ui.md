# TripWire Dashboard UI

**Created:** 2026-02-26
**Status:** In Progress (Sprint 5)

---

## Overview

The TripWire Dashboard UI is a React 18 single-page application built with TypeScript and Vite. It connects to the dashboard server's WebSocket endpoint (`/ws/alerts`) to stream security alerts in real time and exposes a virtualized alert feed that remains performant under high event volumes.

This document covers the WebSocket integration layer implemented in **Sprint 5, task 2**:

- `src/hooks/useWebSocket.ts` — connection lifecycle management
- `src/hooks/useAlerts.ts` — live alert accumulation
- `src/components/AlertFeed.tsx` — virtualized alert list
- `src/pages/TripwireDashboardPage.tsx` — top-level dashboard route

---

## Architecture

```
TripwireDashboardPage
  └── useAlerts({ wsUrl, token, maxAlerts })
        └── useWebSocket(url, { onMessage, token, reconnectIntervalMs })
                │
                │  ws://dashboard/ws/alerts?token=<jwt>
                │
        Dashboard Server (Go)
        /internal/server/websocket/handler.go
```

The page mounts `useAlerts`, which internally delegates all connection management to `useWebSocket`. Incoming WebSocket messages are parsed as `WsAlertMessage` JSON envelopes and prepended to the in-memory alert list. The `AlertFeed` component renders the list via `react-window`'s `FixedSizeList` so that DOM node count stays constant regardless of how many alerts arrive.

---

## WebSocket URL and Authentication

The server's WebSocket handler (`/internal/server/websocket/handler.go`) delegates authentication to a TLS-terminating reverse proxy or a JWT-validation middleware in the chi router chain. **The handler itself does not validate tokens.**

Browser `WebSocket` connections cannot carry custom HTTP headers during the upgrade handshake (RFC 6455). The `useWebSocket` hook therefore appends the bearer token as a URL query parameter:

```
ws://dashboard/ws/alerts?token=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

The query parameter name is `token`. The reverse proxy (Nginx/Caddy) or the router middleware validates this parameter and rejects requests with missing or invalid tokens before the WebSocket handler receives them.

Configure the WebSocket URL via the `VITE_WS_URL` environment variable (defaults to `ws://localhost:8080/ws/alerts` for local development).

---

## `useWebSocket` Hook

**File:** `src/hooks/useWebSocket.ts`

Manages a single WebSocket connection with automatic exponential-backoff reconnection.

### Signature

```typescript
function useWebSocket(url: string, options?: UseWebSocketOptions): UseWebSocketReturn
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `onMessage` | `(event: MessageEvent) => void` | — | Called for each incoming frame |
| `reconnectAttempts` | `number` | `Infinity` | Max reconnect attempts before giving up |
| `reconnectIntervalMs` | `number` | `1000` | Base reconnect delay in ms (doubles each attempt, max 30 s) |
| `token` | `string` | — | Bearer token appended as `?token=<value>` |
| `shouldReconnect` | `boolean` | `true` | Set to `false` to disable auto-reconnect |

### Return value

| Field | Type | Description |
|---|---|---|
| `readyState` | `WebSocketReadyState` | `'CONNECTING' \| 'OPEN' \| 'CLOSING' \| 'CLOSED'` |
| `sendMessage` | `(data: string) => void` | Sends a text frame (no-op if not OPEN) |
| `disconnect` | `() => void` | Closes the socket and cancels pending reconnects |

### Reconnect behaviour

- Delay after attempt *n*: `clamp(reconnectIntervalMs × 2^(n−1), reconnectIntervalMs, 30 000)`
- The attempt counter resets to 0 on every successful open, so a briefly-interrupted connection that reconnects successfully starts fresh.
- Calling `disconnect()` cancels any scheduled reconnect timer and sets `intentionalClose = true` so that the subsequent `onclose` event does not trigger another reconnect.

### Example

```typescript
const { readyState } = useWebSocket('ws://localhost:8080/ws/alerts', {
  token: bearerToken,
  onMessage: (e) => console.log(JSON.parse(e.data)),
  reconnectIntervalMs: 2000,
});
```

---

## `useAlerts` Hook

**File:** `src/hooks/useAlerts.ts`

Maintains a live, capped in-memory list of `TripwireAlert` objects sourced from the WebSocket stream.

### Signature

```typescript
function useAlerts(options: UseAlertsOptions): UseAlertsReturn
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `wsUrl` | `string` | — | WebSocket URL (required) |
| `token` | `string` | — | Bearer token forwarded to `useWebSocket` |
| `maxAlerts` | `number` | `1000` | Maximum alerts to retain (oldest dropped) |

### Return value

| Field | Type | Description |
|---|---|---|
| `alerts` | `TripwireAlert[]` | Ordered newest-first |
| `wsState` | `WebSocketReadyState` | Current connection state |
| `clearAlerts` | `() => void` | Empties the in-memory list |

### Message handling

Each incoming WebSocket frame is parsed as `WsAlertMessage`:

```typescript
interface WsAlertMessage {
  type: 'alert';
  data: TripwireAlert;
}
```

Frames that fail JSON parsing, have a non-`"alert"` type, or lack an `alert_id` are silently dropped. This matches the server's message format defined in `internal/server/websocket/broadcaster.go`.

### Example

```typescript
const { alerts, wsState, clearAlerts } = useAlerts({
  wsUrl: import.meta.env['VITE_WS_URL'] ?? 'ws://localhost:8080/ws/alerts',
  token: bearerToken,
  maxAlerts: 500,
});
```

---

## `AlertFeed` Component

**File:** `src/components/AlertFeed.tsx`

Renders a virtualized list of `TripwireAlert` objects using `react-window`'s `FixedSizeList`. The DOM node count stays constant regardless of how many alerts accumulate — only the visible rows plus `overscanCount=5` off-screen rows are mounted at any time.

### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `alerts` | `TripwireAlert[]` | — | Ordered alert list (newest-first) |
| `height` | `number` | `600` | Visible height in pixels passed to `FixedSizeList` |
| `onSelectAlert` | `(alert: TripwireAlert) => void` | — | Called when a row is clicked or activated |

### Row layout (64 px each)

```
[ sensor icon ] [ SEVERITY badge ] [ rule_name / hostname ] [ HH:MM:SS ]
```

Severity colour coding:
- `CRITICAL` — red left border, red background
- `WARN` — yellow left border, yellow background
- `INFO` — blue left border, blue background

### Accessibility

- Each row has `role="button"` with a descriptive `aria-label` (`"<severity> alert: <rule_name> on <hostname>"`).
- Rows are keyboard-navigable (`tabIndex=0`) and respond to `Enter` and `Space`.
- The empty-state container has `role="status"` and `aria-live="polite"`.

### Example

```tsx
const { alerts, wsState } = useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' });

<AlertFeed
  alerts={alerts}
  height={600}
  onSelectAlert={(a) => setSelected(a)}
/>
```

---

## `TripwireDashboardPage`

**File:** `src/pages/TripwireDashboardPage.tsx`
**Route:** `/dashboard`

Top-level page component that wires together `useAlerts` and `AlertFeed`. Provides:

- A header bar with the TripWire branding and a `ConnectionBadge` showing the current WebSocket state (animated pulse when `CONNECTING`, green when `OPEN`, red when `CLOSED`).
- A toolbar displaying the current alert count and a **Clear** button.
- An `AlertFeed` sized to fill the remaining viewport height.
- A modal-style `AlertDetail` panel that opens when a row is clicked, showing the full `event_detail` JSON payload.

### Environment variable

| Variable | Default | Description |
|---|---|---|
| `VITE_WS_URL` | `ws://localhost:8080/ws/alerts` | WebSocket URL (override in `.env.local`) |

---

## Testing

All three core modules are covered by unit tests:

| File | Tests | Description |
|---|---|---|
| `src/hooks/useWebSocket.test.ts` | 20 | Connection lifecycle, reconnect, token URL-encoding, cleanup |
| `src/hooks/useAlerts.test.ts` | 13 | Alert prepend, maxAlerts cap, malformed message rejection, clearAlerts |
| `src/components/AlertFeed.test.tsx` | 18 | Empty state, row rendering, severity badges, keyboard interaction, icons |

WebSocket is mocked via a `MockWebSocket` class that exposes `simulateOpen()`, `simulateMessage()`, `simulateClose()`, and `simulateError()` helpers. `useWebSocket` is mocked for `useAlerts` tests to isolate alert-list logic.

Run with:

```bash
npx vitest run src/hooks/useWebSocket.test.ts src/hooks/useAlerts.test.ts src/components/AlertFeed.test.tsx
```

---

## Dependencies Added

| Package | Version | Purpose |
|---|---|---|
| `react-window` | `^1.8.10` | Virtualized list (`FixedSizeList`) |
| `@types/react-window` | `^1.8.8` | TypeScript types for react-window |

---

## Related Docs

- [HLD.md](./HLD.md) — system architecture and WebSocket message format
- [grpc-alert-service.md](./grpc-alert-service.md) — alert ingestion pipeline
- [rest-api.md](./rest-api.md) — REST endpoints consumed by future dashboard tasks
