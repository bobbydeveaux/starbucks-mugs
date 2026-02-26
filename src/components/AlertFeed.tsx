import { memo, useCallback } from 'react';
import { FixedSizeList, type ListChildComponentProps } from 'react-window';
import type { TripwireAlert, Severity } from '../types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Fixed height of each virtualized alert row in pixels. */
const ITEM_HEIGHT = 64;

/** Tailwind class strings applied to the row container per severity level. */
const SEVERITY_ROW: Record<Severity, string> = {
  CRITICAL: 'border-red-500 bg-red-50 text-red-900',
  WARN: 'border-yellow-400 bg-yellow-50 text-yellow-900',
  INFO: 'border-blue-400 bg-blue-50 text-blue-900',
};

/** Tailwind class strings applied to the severity badge per level. */
const SEVERITY_BADGE: Record<Severity, string> = {
  CRITICAL: 'bg-red-600 text-white',
  WARN: 'bg-yellow-500 text-white',
  INFO: 'bg-blue-500 text-white',
};

/** Unicode icon representing each tripwire sensor type. */
const TYPE_ICON: Record<string, string> = {
  FILE: '📄',
  NETWORK: '🌐',
  PROCESS: '⚙️',
};

// ---------------------------------------------------------------------------
// AlertRow — a single virtualized row
// ---------------------------------------------------------------------------

interface AlertRowData {
  alerts: TripwireAlert[];
  onSelect: (alert: TripwireAlert) => void;
}

type AlertRowProps = ListChildComponentProps<AlertRowData>;

/**
 * A single row inside the FixedSizeList.  Memoized so that react-window does
 * not re-render off-screen rows when only the data array reference changes.
 */
const AlertRow = memo(({ index, style, data }: AlertRowProps) => {
  const alert = data.alerts[index];
  if (!alert) return null;

  const rowClass = SEVERITY_ROW[alert.severity] ?? 'border-gray-300 bg-gray-50 text-gray-900';
  const badgeClass = SEVERITY_BADGE[alert.severity] ?? 'bg-gray-500 text-white';
  const icon = TYPE_ICON[alert.tripwire_type] ?? '🔔';
  const timeLabel = new Date(alert.timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      data.onSelect(alert);
    }
  }

  return (
    <div
      style={style}
      className={`flex items-center gap-3 px-4 border-l-4 cursor-pointer transition-[filter] hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-500 ${rowClass}`}
      role="button"
      tabIndex={0}
      aria-label={`${alert.severity} alert: ${alert.rule_name} on ${alert.hostname}`}
      onClick={() => data.onSelect(alert)}
      onKeyDown={handleKeyDown}
    >
      {/* Sensor-type icon */}
      <span className="shrink-0 text-xl" aria-hidden="true">
        {icon}
      </span>

      {/* Severity badge */}
      <span
        className={`shrink-0 text-xs font-semibold px-1.5 py-0.5 rounded ${badgeClass}`}
        aria-hidden="true"
      >
        {alert.severity}
      </span>

      {/* Rule name + hostname */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate leading-tight">{alert.rule_name}</p>
        <p className="text-xs opacity-75 truncate leading-tight">{alert.hostname}</p>
      </div>

      {/* Timestamp */}
      <time
        className="shrink-0 text-xs opacity-60 tabular-nums"
        dateTime={alert.timestamp}
      >
        {timeLabel}
      </time>
    </div>
  );
});

AlertRow.displayName = 'AlertRow';

// ---------------------------------------------------------------------------
// AlertFeed — public component
// ---------------------------------------------------------------------------

export interface AlertFeedProps {
  /**
   * Ordered list of alerts to render, newest-first.
   * Typically sourced from {@link useAlerts}.
   */
  alerts: TripwireAlert[];
  /**
   * Visible height of the feed in pixels.
   * Passed directly to react-window `FixedSizeList`.
   * Defaults to `600`.
   */
  height?: number;
  /**
   * Called when the user clicks or activates a row.
   * Use this to show an alert detail panel.
   */
  onSelectAlert?: (alert: TripwireAlert) => void;
}

/**
 * `AlertFeed` renders a live, virtualized stream of TripWire security alerts.
 *
 * Virtualization via `react-window` `FixedSizeList` keeps the DOM node count
 * constant regardless of how many alerts accumulate, preventing layout
 * thrashing during high-frequency event streams.
 *
 * New alerts prepended to the `alerts` array appear at the top of the feed
 * within a single render cycle — there is no full list re-render.
 *
 * @example
 * const { alerts, wsState } = useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' });
 *
 * <AlertFeed
 *   alerts={alerts}
 *   height={500}
 *   onSelectAlert={(a) => setSelectedAlert(a)}
 * />
 */
export function AlertFeed({ alerts, height = 600, onSelectAlert }: AlertFeedProps) {
  const handleSelect = useCallback(
    (alert: TripwireAlert) => {
      onSelectAlert?.(alert);
    },
    [onSelectAlert],
  );

  if (alerts.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center gap-2 text-gray-400"
        style={{ height }}
        role="status"
        aria-live="polite"
        aria-label="Alert feed — no alerts"
      >
        <span className="text-4xl" aria-hidden="true">
          🛡️
        </span>
        <p className="text-sm">No alerts — watching for events…</p>
      </div>
    );
  }

  return (
    <FixedSizeList<AlertRowData>
      height={height}
      width="100%"
      itemCount={alerts.length}
      itemSize={ITEM_HEIGHT}
      itemData={{ alerts, onSelect: handleSelect }}
      overscanCount={5}
    >
      {AlertRow}
    </FixedSizeList>
  );
}
