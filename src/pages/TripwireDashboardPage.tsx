import { useState } from 'react';
import { AlertFeed } from '../components/AlertFeed';
import { useAlerts } from '../hooks/useAlerts';
import type { TripwireAlert, WebSocketReadyState } from '../types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default WebSocket URL — can be overridden via the VITE_WS_URL env var. */
const DEFAULT_WS_URL =
  (import.meta.env['VITE_WS_URL'] as string | undefined) ?? 'ws://localhost:8080/ws/alerts';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Dot indicator reflecting the current WebSocket connection state. */
function ConnectionBadge({ state }: { state: WebSocketReadyState }) {
  const styles: Record<WebSocketReadyState, { dot: string; label: string }> = {
    OPEN: { dot: 'bg-green-500', label: 'Connected' },
    CONNECTING: { dot: 'bg-yellow-400 animate-pulse', label: 'Connecting…' },
    CLOSING: { dot: 'bg-yellow-400', label: 'Closing…' },
    CLOSED: { dot: 'bg-red-500', label: 'Disconnected' },
  };
  const { dot, label } = styles[state];

  return (
    <span className="flex items-center gap-1.5 text-sm text-gray-600">
      <span className={`inline-block w-2 h-2 rounded-full ${dot}`} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

/** Modal-style detail panel for a selected alert. */
function AlertDetail({
  alert,
  onClose,
}: {
  alert: TripwireAlert;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label={`Alert detail: ${alert.rule_name}`}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg bg-white rounded-lg shadow-xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="absolute top-3 right-4 text-gray-400 hover:text-gray-700 text-xl font-bold"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          ×
        </button>

        <h2 className="text-lg font-semibold text-gray-900 mb-4">{alert.rule_name}</h2>

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="font-medium text-gray-500">Alert ID</dt>
          <dd className="font-mono text-gray-800 break-all">{alert.alert_id}</dd>

          <dt className="font-medium text-gray-500">Host</dt>
          <dd className="text-gray-800">{alert.hostname}</dd>

          <dt className="font-medium text-gray-500">Severity</dt>
          <dd className="text-gray-800">{alert.severity}</dd>

          <dt className="font-medium text-gray-500">Type</dt>
          <dd className="text-gray-800">{alert.tripwire_type}</dd>

          <dt className="font-medium text-gray-500">Timestamp</dt>
          <dd className="text-gray-800">{new Date(alert.timestamp).toLocaleString()}</dd>
        </dl>

        {alert.event_detail && (
          <>
            <h3 className="mt-4 mb-2 text-sm font-semibold text-gray-700">Event Detail</h3>
            <pre className="bg-gray-100 rounded p-3 text-xs overflow-auto max-h-48 text-gray-800">
              {JSON.stringify(alert.event_detail, null, 2)}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TripwireDashboardPage
// ---------------------------------------------------------------------------

/**
 * Top-level TripWire Security Dashboard page.
 *
 * Renders a live alert feed sourced from the WebSocket broadcaster at
 * `VITE_WS_URL` (defaults to `ws://localhost:8080/ws/alerts`).  Clicking any
 * alert row opens an inline detail panel with the full event payload.
 *
 * Add a `?token=<jwt>` query parameter to the WS URL via the `token` prop
 * (or set `VITE_WS_URL` to a pre-tokenised URL) for authenticated deployments.
 */
export function TripwireDashboardPage() {
  const [selectedAlert, setSelectedAlert] = useState<TripwireAlert | null>(null);

  const { alerts, wsState, clearAlerts } = useAlerts({ wsUrl: DEFAULT_WS_URL });

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="bg-gray-900 text-white px-6 py-4 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <span className="text-2xl" aria-hidden="true">
            🛡️
          </span>
          <h1 className="text-xl font-bold tracking-tight">TripWire Dashboard</h1>
        </div>
        <ConnectionBadge state={wsState} />
      </header>

      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-200">
        <p className="text-sm text-gray-600">
          {alerts.length === 0
            ? 'No alerts'
            : `${alerts.length.toLocaleString()} alert${alerts.length !== 1 ? 's' : ''}`}
        </p>
        <button
          className="text-sm text-gray-500 hover:text-red-600 transition-colors disabled:opacity-40"
          onClick={clearAlerts}
          disabled={alerts.length === 0}
          aria-label="Clear all alerts"
        >
          Clear
        </button>
      </div>

      {/* ── Alert Feed ── */}
      <main className="px-6 py-4">
        <AlertFeed
          alerts={alerts}
          height={Math.max(400, window.innerHeight - 180)}
          onSelectAlert={setSelectedAlert}
        />
      </main>

      {/* ── Detail panel ── */}
      {selectedAlert && (
        <AlertDetail alert={selectedAlert} onClose={() => setSelectedAlert(null)} />
      )}
    </div>
  );
}
