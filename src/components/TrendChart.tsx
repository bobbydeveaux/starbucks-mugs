/**
 * TrendChart — displays alert volume over a time window, with one stacked
 * area series per severity level (INFO / WARN / CRITICAL).
 *
 * The component is purely presentational: it receives a pre-fetched `alerts`
 * array and the [from, to] window for binning, then derives the recharts
 * dataset client-side. It re-renders automatically whenever `alerts` changes,
 * so WebSocket-pushed events update the chart within one render cycle without
 * triggering an extra API call.
 */

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { aggregateAlertsByTime } from '../utils/aggregateAlerts';
import type { Alert, TimeRange } from '../types';

// ---------------------------------------------------------------------------
// Severity colour palette
// ---------------------------------------------------------------------------

const SEVERITY_COLOURS = {
  INFO: '#3B82F6',      // blue-500
  WARN: '#F59E0B',      // amber-500
  CRITICAL: '#EF4444',  // red-500
} as const;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function LoadingOverlay() {
  return (
    <div className="flex h-full items-center justify-center text-gray-500">
      <span className="animate-pulse">Loading alerts…</span>
    </div>
  );
}

function ErrorOverlay({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex h-full items-center justify-center text-red-600 text-sm"
    >
      Failed to load alerts: {message}
    </div>
  );
}

function EmptyOverlay() {
  return (
    <div className="flex h-full items-center justify-center text-gray-400 text-sm">
      No alerts in this time window.
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TooltipPayload {
  name: string;
  value: number;
  color: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="rounded border border-gray-200 bg-white p-2 shadow text-xs">
      <p className="mb-1 font-medium text-gray-700">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }}>
          {entry.name}: {entry.value}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Time-range selector
// ---------------------------------------------------------------------------

const TIME_RANGE_LABELS: Record<TimeRange, string> = {
  '1h': 'Last 1 hour',
  '6h': 'Last 6 hours',
  '24h': 'Last 24 hours',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
};

interface TimeRangeSelectorProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
}

function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  return (
    <div
      role="group"
      aria-label="Select time range"
      className="flex flex-wrap gap-1"
    >
      {(Object.keys(TIME_RANGE_LABELS) as TimeRange[]).map((range) => (
        <button
          key={range}
          type="button"
          aria-pressed={value === range}
          onClick={() => onChange(range)}
          className={[
            'rounded px-2 py-1 text-xs font-medium transition-colors',
            value === range
              ? 'bg-blue-600 text-white'
              : 'border border-gray-300 bg-white text-gray-600 hover:bg-gray-50',
          ].join(' ')}
        >
          {range}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TrendChart props and component
// ---------------------------------------------------------------------------

export interface TrendChartProps {
  /** Raw alerts to bin and visualise */
  alerts: Alert[];
  /** Inclusive window start — used for bucket alignment */
  from: Date;
  /** Inclusive window end — used for bucket alignment */
  to: Date;
  /** Currently selected preset (controls the TimeRangeSelector UI only) */
  timeRange: TimeRange;
  /** Called when the user picks a different preset */
  onTimeRangeChange: (range: TimeRange) => void;
  /** True while the initial REST fetch is in flight */
  loading?: boolean;
  /** Non-null when the fetch failed */
  error?: string | null;
  /** CSS class applied to the outermost container */
  className?: string;
}

/**
 * TrendChart renders a stacked AreaChart with one series per severity level.
 *
 * Data is aggregated client-side via `aggregateAlertsByTime`, so the chart
 * stays in sync with any in-memory alerts list (REST fetch + WS patches)
 * without additional network round-trips.
 */
export function TrendChart({
  alerts,
  from,
  to,
  timeRange,
  onTimeRangeChange,
  loading = false,
  error = null,
  className = '',
}: TrendChartProps) {
  const data = aggregateAlertsByTime(alerts, from, to);
  const hasAlerts = alerts.length > 0;

  return (
    <section
      aria-label="Alert volume trend chart"
      className={`rounded-lg border border-gray-200 bg-white p-4 ${className}`}
    >
      {/* Header row */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-800">
          Alert Volume
        </h2>
        <TimeRangeSelector value={timeRange} onChange={onTimeRangeChange} />
      </div>

      {/* Chart body — fixed height so ResponsiveContainer has a measured parent */}
      <div style={{ height: 240 }}>
        {loading && <LoadingOverlay />}
        {!loading && error && <ErrorOverlay message={error} />}
        {!loading && !error && !hasAlerts && <EmptyOverlay />}
        {!loading && !error && hasAlerts && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={data}
              margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 11, fill: '#6B7280' }}
                tickLine={false}
                axisLine={{ stroke: '#E5E7EB' }}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: '#6B7280' }}
                tickLine={false}
                axisLine={false}
                width={32}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                iconType="circle"
                iconSize={8}
                wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
              />
              <Area
                type="monotone"
                dataKey="INFO"
                name="INFO"
                stackId="1"
                stroke={SEVERITY_COLOURS.INFO}
                fill={SEVERITY_COLOURS.INFO}
                fillOpacity={0.15}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
              <Area
                type="monotone"
                dataKey="WARN"
                name="WARN"
                stackId="1"
                stroke={SEVERITY_COLOURS.WARN}
                fill={SEVERITY_COLOURS.WARN}
                fillOpacity={0.15}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
              <Area
                type="monotone"
                dataKey="CRITICAL"
                name="CRITICAL"
                stackId="1"
                stroke={SEVERITY_COLOURS.CRITICAL}
                fill={SEVERITY_COLOURS.CRITICAL}
                fillOpacity={0.15}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
