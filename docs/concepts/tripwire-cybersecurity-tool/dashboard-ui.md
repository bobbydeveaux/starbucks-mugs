# TripWire Dashboard UI

**Created:** 2026-02-26
**Status:** In Progress (Sprint 5)

---

## Overview

The TripWire Dashboard UI is a React 18 single-page application built with TypeScript and Vite. It connects to the dashboard server's WebSocket endpoint (`/ws/alerts`) to stream security alerts in real time and exposes a virtualized alert feed that remains performant under high event volumes. It also provides a multi-host selector and fleet-wide host status overview.

---

## Route

The dashboard is served at `/dashboard` (registered in `src/App.tsx`).
Navigate to `http://<host>:5173/dashboard` during development.

---

## WebSocket Integration (Sprint 5, Task 2)

This section covers the WebSocket integration layer:

- `src/hooks/useWebSocket.ts` — connection lifecycle management
- `src/hooks/useAlerts.ts` — live alert accumulation
- `src/components/AlertFeed.tsx` — virtualized alert list
- `src/pages/TripwireDashboardPage.tsx` — top-level dashboard route (alert feed)

### Architecture

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

### WebSocket URL and Authentication

The server's WebSocket handler (`/internal/server/websocket/handler.go`) delegates authentication to a TLS-terminating reverse proxy or a JWT-validation middleware in the chi router chain. **The handler itself does not validate tokens.**

Browser `WebSocket` connections cannot carry custom HTTP headers during the upgrade handshake (RFC 6455). The `useWebSocket` hook therefore appends the bearer token as a URL query parameter:

```
ws://dashboard/ws/alerts?token=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

The query parameter name is `token`. The reverse proxy (Nginx/Caddy) or the router middleware validates this parameter and rejects requests with missing or invalid tokens before the WebSocket handler receives them.

Configure the WebSocket URL via the `VITE_WS_URL` environment variable (defaults to `ws://localhost:8080/ws/alerts` for local development).

### `useWebSocket` Hook

**File:** `src/hooks/useWebSocket.ts`

Manages a single WebSocket connection with automatic exponential-backoff reconnection.

#### Signature

```typescript
function useWebSocket(url: string, options?: UseWebSocketOptions): UseWebSocketReturn
```

#### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `onMessage` | `(event: MessageEvent) => void` | — | Called for each incoming frame |
| `reconnectAttempts` | `number` | `Infinity` | Max reconnect attempts before giving up |
| `reconnectIntervalMs` | `number` | `1000` | Base reconnect delay in ms (doubles each attempt, max 30 s) |
| `token` | `string` | — | Bearer token appended as `?token=<value>` |
| `shouldReconnect` | `boolean` | `true` | Set to `false` to disable auto-reconnect |

#### Return value

| Field | Type | Description |
|---|---|---|
| `readyState` | `WebSocketReadyState` | `'CONNECTING' \| 'OPEN' \| 'CLOSING' \| 'CLOSED'` |
| `sendMessage` | `(data: string) => void` | Sends a text frame (no-op if not OPEN) |
| `disconnect` | `() => void` | Closes the socket and cancels pending reconnects |

#### Reconnect behaviour

- Delay after attempt *n*: `clamp(reconnectIntervalMs × 2^(n−1), reconnectIntervalMs, 30 000)`
- The attempt counter resets to 0 on every successful open, so a briefly-interrupted connection that reconnects successfully starts fresh.
- Calling `disconnect()` cancels any scheduled reconnect timer and sets `intentionalClose = true` so that the subsequent `onclose` event does not trigger another reconnect.

#### Example

```typescript
const { readyState } = useWebSocket('ws://localhost:8080/ws/alerts', {
  token: bearerToken,
  onMessage: (e) => console.log(JSON.parse(e.data)),
  reconnectIntervalMs: 2000,
});
```

### `useAlerts` Hook

**File:** `src/hooks/useAlerts.ts`

Maintains a live, capped in-memory list of `TripwireAlert` objects sourced from the WebSocket stream.

#### Signature

```typescript
function useAlerts(options: UseAlertsOptions): UseAlertsReturn
```

#### Options

| Option | Type | Default | Description |
|---|---|---|---|
| `wsUrl` | `string` | — | WebSocket URL (required) |
| `token` | `string` | — | Bearer token forwarded to `useWebSocket` |
| `maxAlerts` | `number` | `1000` | Maximum alerts to retain (oldest dropped) |

#### Return value

| Field | Type | Description |
|---|---|---|
| `alerts` | `TripwireAlert[]` | Ordered newest-first |
| `wsState` | `WebSocketReadyState` | Current connection state |
| `clearAlerts` | `() => void` | Empties the in-memory list |

#### Message handling

Each incoming WebSocket frame is parsed as `WsAlertMessage`:

```typescript
interface WsAlertMessage {
  type: 'alert';
  data: TripwireAlert;
}
```

Frames that fail JSON parsing, have a non-`"alert"` type, or lack an `alert_id` are silently dropped. This matches the server's message format defined in `internal/server/websocket/broadcaster.go`.

#### Example

```typescript
const { alerts, wsState, clearAlerts } = useAlerts({
  wsUrl: import.meta.env['VITE_WS_URL'] ?? 'ws://localhost:8080/ws/alerts',
  token: bearerToken,
  maxAlerts: 500,
});
```

### `AlertFeed` Component

**File:** `src/components/AlertFeed.tsx`

Renders a virtualized list of `TripwireAlert` objects using `react-window`'s `FixedSizeList`. The DOM node count stays constant regardless of how many alerts accumulate — only the visible rows plus `overscanCount=5` off-screen rows are mounted at any time.

#### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `alerts` | `TripwireAlert[]` | — | Ordered alert list (newest-first) |
| `height` | `number` | `600` | Visible height in pixels passed to `FixedSizeList` |
| `onSelectAlert` | `(alert: TripwireAlert) => void` | — | Called when a row is clicked or activated |

#### Row layout (64 px each)

```
[ sensor icon ] [ SEVERITY badge ] [ rule_name / hostname ] [ HH:MM:SS ]
```

Severity colour coding:
- `CRITICAL` — red left border, red background
- `WARN` — yellow left border, yellow background
- `INFO` — blue left border, blue background

#### Accessibility

- Each row has `role="button"` with a descriptive `aria-label` (`"<severity> alert: <rule_name> on <hostname>"`).
- Rows are keyboard-navigable (`tabIndex=0`) and respond to `Enter` and `Space`.
- The empty-state container has `role="status"` and `aria-live="polite"`.

#### Example

```tsx
const { alerts, wsState } = useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' });

<AlertFeed
  alerts={alerts}
  height={600}
  onSelectAlert={(a) => setSelected(a)}
/>
```

---

## Multi-Host Selector & Host Status Overview

This section describes the components and hooks that implement the multi-host
selector and host status overview panels.

### Components

#### `HostStatusBadge`

**File:** `src/components/HostStatusBadge.tsx`

A small, colour-coded pill badge that surfaces the liveness state of a
monitored host.

| Status     | Colour | Label     |
|------------|--------|-----------|
| `ONLINE`   | Green  | Online    |
| `DEGRADED` | Yellow | Degraded  |
| `OFFLINE`  | Red    | Offline   |

**Props:**

| Prop     | Type         | Description                  |
|----------|--------------|------------------------------|
| `status` | `HostStatus` | Current liveness state of the host |

**Accessibility:** renders with `role="status"` and an `aria-label` of
`Host status: <label>` so screen readers announce the current state.

---

#### `HostSelector`

**File:** `src/components/HostSelector.tsx`

A scrollable, accessible checklist that lets operators select one or more
monitored hosts.  Selection state is **fully controlled** — the parent owns
`selectedHostIds` and receives updates via `onChange`.

Features:
- **Select All** / **Clear** shortcut buttons in the toolbar
- Per-host status badge so operators can spot unhealthy machines instantly
- Live selection summary (`"2 of 5 selected"` / `"No hosts selected — showing all"`)
- Empty-state message when no hosts are registered

**Props:**

| Prop              | Type                         | Description                                 |
|-------------------|------------------------------|---------------------------------------------|
| `hosts`           | `Host[]`                     | Full list of available hosts to display     |
| `selectedHostIds` | `string[]`                   | IDs of currently selected hosts             |
| `onChange`        | `(ids: string[]) => void`    | Called when the selection changes           |

**Accessibility:** The checklist is rendered as a `listbox` with
`aria-multiselectable="true"`.  Each item has `role="option"` and
`aria-selected`.  Bulk-action buttons carry descriptive `aria-label`
attributes.

---

#### `HostStatusOverview`

**File:** `src/components/HostStatusOverview.tsx`

Fleet-wide status panel with two sections:

1. **Summary cards** — three count tiles showing the total number of
   `ONLINE`, `DEGRADED`, and `OFFLINE` hosts.  The counters always reflect the
   **full** host list regardless of the current filter so operators retain
   fleet-wide context while drilling into a subset.

2. **Host table** — a responsive table listing every visible host with:
   - Hostname
   - Status badge (`HostStatusBadge`)
   - IP address
   - Platform (e.g. `linux`, `darwin`)
   - Agent version
   - Last-seen timestamp (formatted as a relative string, e.g. `"42s ago"`)

**Props:**

| Prop              | Type         | Description                                                                |
|-------------------|--------------|----------------------------------------------------------------------------|
| `hosts`           | `Host[]`     | Full list of registered hosts                                              |
| `selectedHostIds` | `string[]?`  | If non-empty, only these hosts appear in the table. Omit to show all.     |

---

### Page

#### `TripWireDashboardPage`

**File:** `src/pages/TripWireDashboardPage.tsx`

The top-level dashboard page.  It:

1. Calls `useHosts()` to load the host list from `GET /api/v1/hosts`.
2. Maintains `selectedHostIds` state (empty = show all).
3. Renders a **two-column layout**:
   - **Left sidebar** — `HostSelector` for filtering.
   - **Right area** — `HostStatusOverview` showing the (filtered) fleet.
4. Provides a **Refresh** button that re-calls `useHosts().refetch()`.
5. Shows an inline error banner on fetch failure.

---

### Hook

#### `useHosts`

**File:** `src/hooks/useHosts.ts`

Fetches the list of monitored hosts from `GET /api/v1/hosts` and exposes
loading/error/data state.

```ts
const { hosts, loading, error, refetch } = useHosts();
```

| Return field | Type            | Description                                |
|--------------|-----------------|--------------------------------------------|
| `hosts`      | `Host[]`        | All registered hosts (empty while loading) |
| `loading`    | `boolean`       | True while a fetch is in flight            |
| `error`      | `string \| null`| Non-null when the last fetch failed        |
| `refetch`    | `() => void`    | Triggers a fresh fetch without remounting  |

The hook automatically cancels the in-flight request via `AbortController`
when the consuming component unmounts.

---

### TypeScript Types

The following types were added to `src/types.ts`:

```ts
/** Liveness state of a monitored host */
export type HostStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED';

/** Registered agent host as returned by GET /api/v1/hosts */
export interface Host {
  host_id: string;       // Stable UUID assigned on first registration
  hostname: string;      // mTLS certificate CN or agent-reported hostname
  ip_address?: string;   // Primary IP (may be absent)
  platform?: string;     // OS platform string (e.g. "linux", "darwin")
  agent_version?: string;
  last_seen?: string;    // ISO 8601 timestamp
  status: HostStatus;
}
```

These types mirror the Go `storage.Host` struct and the JSON serialisation
produced by `GET /api/v1/hosts`.

---

### Backend Integration

The dashboard components consume one REST endpoint:

| Method | Path            | Description                                           |
|--------|-----------------|-------------------------------------------------------|
| `GET`  | `/api/v1/hosts` | Returns a JSON array of all `Host` objects, ordered by hostname. |

See [`rest-api.md`](rest-api.md) for full request/response documentation.

---

## Testing

All core modules are covered by unit tests:

| File                                              | Tests | Description |
|---------------------------------------------------|-------|-------------|
| `src/hooks/useWebSocket.test.ts`                  | 20    | Connection lifecycle, reconnect, token URL-encoding, cleanup |
| `src/hooks/useAlerts.test.ts`                     | 13    | Alert prepend, maxAlerts cap, malformed message rejection, clearAlerts |
| `src/components/AlertFeed.test.tsx`               | 18    | Empty state, row rendering, severity badges, keyboard interaction, icons |
| `src/hooks/useHosts.test.ts`                      | 7     | Loading, success, HTTP error, network error, refetch, URL, error-clear |
| `src/components/HostStatusBadge.test.tsx`         | 10    | All three status labels, ARIA role/label, colour classes |
| `src/components/HostSelector.test.tsx`            | 17    | Render, checkbox state, toggle, select-all, clear, disabled states, empty state, summary |
| `src/components/HostStatusOverview.test.tsx`      | 14    | Summary cards, table rows, filtering, empty states, badge rendering |

WebSocket tests use a `MockWebSocket` class exposing `simulateOpen()`, `simulateMessage()`, `simulateClose()`, and `simulateError()` helpers.

Run with:

```bash
npm test
# or to target specific files:
npx vitest run src/hooks/useWebSocket.test.ts src/hooks/useAlerts.test.ts src/components/AlertFeed.test.tsx
./node_modules/.bin/vitest run src/hooks/useHosts.test.ts \
  src/components/HostStatusBadge.test.tsx \
  src/components/HostSelector.test.tsx \
  src/components/HostStatusOverview.test.tsx
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
- [rest-api.md](./rest-api.md) — REST endpoints consumed by dashboard tasks
