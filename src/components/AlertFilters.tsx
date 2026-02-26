/**
 * AlertFilters — dashboard filter controls for the TripWire alert feed.
 *
 * Renders a row of drop-down selects for severity, tripwire type, and host,
 * plus a "Reset" button. State is managed entirely through FilterContext;
 * this component is purely presentational with respect to data fetching.
 */

import type { Host, Severity, TripwireType } from '../types/alert';
import { useFilterContext } from '../contexts/FilterContext';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SEVERITY_OPTIONS: Array<{ label: string; value: Severity }> = [
  { label: 'Critical', value: 'CRITICAL' },
  { label: 'Warning', value: 'WARN' },
  { label: 'Info', value: 'INFO' },
];

const TYPE_OPTIONS: Array<{ label: string; value: TripwireType }> = [
  { label: 'File', value: 'FILE' },
  { label: 'Network', value: 'NETWORK' },
  { label: 'Process', value: 'PROCESS' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AlertFiltersProps {
  /** List of registered hosts used to populate the host filter drop-down */
  hosts?: Host[];
  /** Whether the host list is still loading */
  hostsLoading?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * AlertFilters renders a toolbar of filter controls for the alert dashboard.
 *
 * It reads and updates state via `useFilterContext()`, so it must be rendered
 * inside a `FilterProvider`.
 *
 * @example
 * <FilterProvider>
 *   <AlertFilters hosts={hostsData?.hosts} />
 * </FilterProvider>
 */
export function AlertFilters({ hosts = [], hostsLoading = false }: AlertFiltersProps) {
  const {
    filters,
    setSeverity,
    setTripwireType,
    setHostId,
    resetFilters,
  } = useFilterContext();

  const hasActiveFilters =
    filters.severity !== undefined ||
    filters.tripwire_type !== undefined ||
    filters.host_id !== undefined;

  return (
    <div
      role="group"
      aria-label="Alert filters"
      className="flex flex-wrap items-center gap-3 p-4 bg-white border border-gray-200 rounded-lg shadow-sm"
    >
      {/* Severity filter */}
      <div className="flex flex-col gap-1 min-w-[140px]">
        <label
          htmlFor="severity-filter"
          className="text-xs font-semibold text-gray-500 uppercase tracking-wide"
        >
          Severity
        </label>
        <select
          id="severity-filter"
          value={filters.severity ?? ''}
          onChange={(e) =>
            setSeverity(e.target.value === '' ? undefined : (e.target.value as Severity))
          }
          className="border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-red-500"
          aria-label="Filter by severity"
        >
          <option value="">All severities</option>
          {SEVERITY_OPTIONS.map(({ label, value }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {/* Tripwire type filter */}
      <div className="flex flex-col gap-1 min-w-[140px]">
        <label
          htmlFor="type-filter"
          className="text-xs font-semibold text-gray-500 uppercase tracking-wide"
        >
          Type
        </label>
        <select
          id="type-filter"
          value={filters.tripwire_type ?? ''}
          onChange={(e) =>
            setTripwireType(
              e.target.value === '' ? undefined : (e.target.value as TripwireType),
            )
          }
          className="border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-red-500"
          aria-label="Filter by type"
        >
          <option value="">All types</option>
          {TYPE_OPTIONS.map(({ label, value }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {/* Host filter */}
      <div className="flex flex-col gap-1 min-w-[180px]">
        <label
          htmlFor="host-filter"
          className="text-xs font-semibold text-gray-500 uppercase tracking-wide"
        >
          Host
        </label>
        <select
          id="host-filter"
          value={filters.host_id ?? ''}
          onChange={(e) =>
            setHostId(e.target.value === '' ? undefined : e.target.value)
          }
          disabled={hostsLoading}
          className="border border-gray-300 rounded px-2 py-1.5 text-sm text-gray-700 bg-white focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50"
          aria-label="Filter by host"
        >
          <option value="">All hosts</option>
          {hosts.map((host) => (
            <option key={host.host_id} value={host.host_id}>
              {host.hostname}
            </option>
          ))}
        </select>
      </div>

      {/* Reset button */}
      {hasActiveFilters && (
        <button
          type="button"
          onClick={resetFilters}
          className="mt-5 px-3 py-1.5 text-sm font-medium text-gray-600 border border-gray-300 rounded hover:border-red-500 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 transition-colors"
          aria-label="Reset all filters"
        >
          Reset filters
        </button>
      )}
    </div>
  );
}

export default AlertFilters;
