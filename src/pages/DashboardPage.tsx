/**
 * DashboardPage — the real-time security monitoring dashboard for the
 * Tripwire cybersecurity tool.
 *
 * Wires together alert data fetching (REST + WebSocket patches) with the
 * TrendChart visualisation. Filter state is managed locally and passed down
 * to both the data layer and the chart.
 */

import { useState, useCallback } from 'react';
import { TrendChart } from '../components/TrendChart';
import { useAlerts } from '../hooks/useAlerts';
import type { AlertFilters, TimeRange, Severity, TripwireType } from '../types';

// ---------------------------------------------------------------------------
// Default filter values
// ---------------------------------------------------------------------------

const DEFAULT_FILTERS: AlertFilters = {
  hostIds: [],
  severity: 'ALL',
  tripwireType: 'ALL',
  timeRange: '24h',
};

// ---------------------------------------------------------------------------
// Severity and type selector controls
// ---------------------------------------------------------------------------

const SEVERITY_OPTIONS: Array<Severity | 'ALL'> = [
  'ALL',
  'INFO',
  'WARN',
  'CRITICAL',
];

const TYPE_OPTIONS: Array<TripwireType | 'ALL'> = [
  'ALL',
  'FILE',
  'NETWORK',
  'PROCESS',
];

interface SelectProps<T extends string> {
  label: string;
  value: T;
  options: T[];
  onChange: (v: T) => void;
}

function Select<T extends string>({
  label,
  value,
  options,
  onChange,
}: SelectProps<T>) {
  return (
    <label className="flex flex-col gap-1 text-xs text-gray-600">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-gray-800 shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Alert count badge
// ---------------------------------------------------------------------------

function AlertCountBadge({ count }: { count: number }) {
  return (
    <span
      aria-label={`${count} alert${count !== 1 ? 's' : ''} in current window`}
      className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700"
    >
      {count.toLocaleString()} alert{count !== 1 ? 's' : ''}
    </span>
  );
}

// ---------------------------------------------------------------------------
// DashboardPage component
// ---------------------------------------------------------------------------

export function DashboardPage() {
  const [filters, setFilters] = useState<AlertFilters>(DEFAULT_FILTERS);

  const handleTimeRangeChange = useCallback((range: TimeRange) => {
    setFilters((prev) => ({ ...prev, timeRange: range }));
  }, []);

  const handleSeverityChange = useCallback((severity: Severity | 'ALL') => {
    setFilters((prev) => ({ ...prev, severity }));
  }, []);

  const handleTypeChange = useCallback((tripwireType: TripwireType | 'ALL') => {
    setFilters((prev) => ({ ...prev, tripwireType }));
  }, []);

  const { alerts, loading, error, from, to } = useAlerts(filters);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Top nav bar */}
      <header className="border-b border-gray-200 bg-white px-6 py-3 shadow-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-gray-900">Tripwire</span>
            <span className="rounded bg-blue-600 px-2 py-0.5 text-xs font-semibold text-white">
              Dashboard
            </span>
          </div>
          <AlertCountBadge count={alerts.length} />
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-7xl px-6 py-6">
        {/* Filter bar */}
        <div className="mb-6 flex flex-wrap items-end gap-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-medium text-gray-700 w-full sm:w-auto">
            Filters
          </p>
          <Select<Severity | 'ALL'>
            label="Severity"
            value={filters.severity}
            options={SEVERITY_OPTIONS}
            onChange={handleSeverityChange}
          />
          <Select<TripwireType | 'ALL'>
            label="Type"
            value={filters.tripwireType}
            options={TYPE_OPTIONS}
            onChange={handleTypeChange}
          />
        </div>

        {/* Trend chart */}
        <TrendChart
          alerts={alerts}
          from={from}
          to={to}
          timeRange={filters.timeRange}
          onTimeRangeChange={handleTimeRangeChange}
          loading={loading}
          error={error}
          className="shadow-sm"
        />
      </main>
    </div>
  );
}
