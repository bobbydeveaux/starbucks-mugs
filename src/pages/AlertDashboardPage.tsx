/**
 * AlertDashboardPage — the main TripWire security alert dashboard.
 *
 * Composes AlertFilters + AlertTable with real-time polling every 30 seconds.
 * The QueryClient is configured at the App level; this page just consumes data.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FilterProvider, useFilterContext } from '../contexts/FilterContext';
import { useAlerts, useHosts } from '../hooks/useAlerts';
import { AlertFilters } from '../components/AlertFilters';
import { AlertTable } from '../components/AlertTable';

// ---------------------------------------------------------------------------
// Inner component that consumes filter context
// ---------------------------------------------------------------------------

function DashboardContent() {
  const { filters } = useFilterContext();

  const { data, isLoading, isFetching, error } = useAlerts(filters, {
    refetchInterval: 30_000, // poll every 30 seconds
  });

  const { data: hostsData, isLoading: hostsLoading } = useHosts();

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-gray-900 text-white px-6 py-4 shadow-lg">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">TripWire Dashboard</h1>
            <p className="text-gray-400 text-sm mt-0.5">
              Real-time security alert monitoring
            </p>
          </div>
          {data && (
            <span className="text-sm text-gray-300">
              {data.total.toLocaleString()} alert{data.total !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-6 py-6 space-y-4">
        <AlertFilters
          hosts={hostsData?.hosts}
          hostsLoading={hostsLoading}
        />
        <AlertTable
          data={data}
          isLoading={isLoading}
          isFetching={isFetching}
          error={error}
        />
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// QueryClient singleton for the dashboard
// ---------------------------------------------------------------------------

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

/**
 * AlertDashboardPage is the top-level component for the /dashboard route.
 *
 * It provides both the TanStack QueryClient and the FilterProvider so that
 * child components can use hooks without further wrapping.
 *
 * @example
 * <Route path="/dashboard" element={<AlertDashboardPage />} />
 */
export function AlertDashboardPage() {
  return (
    <QueryClientProvider client={queryClient}>
      <FilterProvider>
        <DashboardContent />
      </FilterProvider>
    </QueryClientProvider>
  );
}

export default AlertDashboardPage;
