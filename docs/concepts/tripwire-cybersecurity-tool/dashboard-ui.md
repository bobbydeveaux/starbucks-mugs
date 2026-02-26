# TripWire Dashboard UI — Multi-Host Selector & Host Status Overview

This document describes the React frontend components and hooks that implement
the **multi-host selector** and **host status overview** panels of the TripWire
cybersecurity dashboard.

---

## Route

The dashboard is served at `/dashboard` (registered in `src/App.tsx`).
Navigate to `http://<host>:5173/dashboard` during development.

---

## Components

### `HostStatusBadge`

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

### `HostSelector`

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

### `HostStatusOverview`

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

## Page

### `TripWireDashboardPage`

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

## Hook

### `useHosts`

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

## TypeScript Types

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

## Backend Integration

The dashboard components consume one REST endpoint:

| Method | Path            | Description                                           |
|--------|-----------------|-------------------------------------------------------|
| `GET`  | `/api/v1/hosts` | Returns a JSON array of all `Host` objects, ordered by hostname. |

See [`rest-api.md`](rest-api.md) for full request/response documentation.

---

## Test Coverage

| File                                              | Tests | Coverage                                         |
|---------------------------------------------------|-------|--------------------------------------------------|
| `src/hooks/useHosts.test.ts`                      | 7     | Loading, success, HTTP error, network error, refetch, URL, error-clear |
| `src/components/HostStatusBadge.test.tsx`         | 10    | All three status labels, ARIA role/label, colour classes |
| `src/components/HostSelector.test.tsx`            | 17    | Render, checkbox state, toggle, select-all, clear, disabled states, empty state, summary |
| `src/components/HostStatusOverview.test.tsx`      | 14    | Summary cards, table rows, filtering, empty states, badge rendering |

Run with:

```bash
npm test
# or to target only the dashboard files:
./node_modules/.bin/vitest run src/hooks/useHosts.test.ts \
  src/components/HostStatusBadge.test.tsx \
  src/components/HostSelector.test.tsx \
  src/components/HostStatusOverview.test.tsx
```
