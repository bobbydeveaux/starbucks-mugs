/**
 * AlertTable — displays a paginated list of TripWire alerts.
 *
 * Renders a table of alert rows with severity badges, tripwire type labels,
 * and pagination controls. Delegates data fetching to the parent via props.
 */

import type { Alert, AlertsResponse } from '../types/alert';
import { useFilterContext } from '../contexts/FilterContext';

// ---------------------------------------------------------------------------
// Severity badge colours
// ---------------------------------------------------------------------------

const SEVERITY_STYLES: Record<string, string> = {
  CRITICAL: 'bg-red-100 text-red-700 border border-red-300',
  WARN: 'bg-yellow-100 text-yellow-700 border border-yellow-300',
  INFO: 'bg-blue-100 text-blue-700 border border-blue-300',
};

const SEVERITY_LABELS: Record<string, string> = {
  CRITICAL: 'Critical',
  WARN: 'Warning',
  INFO: 'Info',
};

const TYPE_LABELS: Record<string, string> = {
  FILE: 'File',
  NETWORK: 'Network',
  PROCESS: 'Process',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${SEVERITY_STYLES[severity] ?? ''}`}
    >
      {SEVERITY_LABELS[severity] ?? severity}
    </span>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const ts = new Date(alert.timestamp).toLocaleString();
  return (
    <tr className="border-t border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3 text-sm text-gray-700 font-mono whitespace-nowrap">{ts}</td>
      <td className="px-4 py-3">
        <SeverityBadge severity={alert.severity} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-700">
        {TYPE_LABELS[alert.tripwire_type] ?? alert.tripwire_type}
      </td>
      <td className="px-4 py-3 text-sm text-gray-800 font-medium">{alert.rule_name}</td>
      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{alert.host_id}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AlertTableProps {
  /** Paginated alerts response from the server */
  data: AlertsResponse | undefined;
  /** True while the initial fetch is in flight */
  isLoading: boolean;
  /** True during background refetches */
  isFetching: boolean;
  /** Non-null when the query failed */
  error: Error | null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * AlertTable renders a sortable, paginated list of security alerts.
 *
 * Pagination state is managed via FilterContext. The component reads the
 * current `offset` / `limit` from context and calls `setOffset` to navigate.
 *
 * @example
 * <FilterProvider>
 *   <AlertTable data={data} isLoading={isLoading} isFetching={isFetching} error={error} />
 * </FilterProvider>
 */
export function AlertTable({ data, isLoading, isFetching, error }: AlertTableProps) {
  const { filters, setOffset } = useFilterContext();
  const { limit, offset } = filters;

  const total = data?.total ?? 0;
  const alerts: Alert[] = data?.alerts ?? [];
  const pageCount = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  // -------------------------------------------------------------------------
  // Loading skeleton
  // -------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div role="status" aria-label="Loading alerts" className="p-8 text-center text-gray-500">
        Loading alerts…
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Error state
  // -------------------------------------------------------------------------

  if (error) {
    return (
      <div role="alert" className="p-6 rounded-lg bg-red-50 border border-red-200 text-red-700">
        <strong>Failed to load alerts:</strong> {error.message}
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Empty state
  // -------------------------------------------------------------------------

  if (alerts.length === 0) {
    return (
      <div className="p-8 text-center text-gray-500">
        No alerts match the current filters.
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Table
  // -------------------------------------------------------------------------

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
      {isFetching && !isLoading && (
        <div
          role="status"
          aria-label="Refreshing alerts"
          className="h-1 bg-blue-500 animate-pulse"
        />
      )}
      <table className="w-full text-left">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Time
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Severity
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Type
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Rule
            </th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Host
            </th>
          </tr>
        </thead>
        <tbody className="bg-white">
          {alerts.map((alert) => (
            <AlertRow key={alert.alert_id} alert={alert} />
          ))}
        </tbody>
      </table>

      {/* Pagination */}
      {pageCount > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
          <p className="text-sm text-gray-600">
            Showing {offset + 1}–{Math.min(offset + limit, total)} of {total} alerts
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 text-sm rounded border border-gray-300 disabled:opacity-40 hover:border-red-400 transition-colors"
              aria-label="Previous page"
            >
              Previous
            </button>
            <span className="px-3 py-1 text-sm text-gray-600">
              Page {currentPage} of {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= total}
              className="px-3 py-1 text-sm rounded border border-gray-300 disabled:opacity-40 hover:border-red-400 transition-colors"
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default AlertTable;
