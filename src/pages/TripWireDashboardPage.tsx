import { useState } from 'react';
import { useHosts } from '../hooks/useHosts';
import { HostSelector } from '../components/HostSelector';
import { HostStatusOverview } from '../components/HostStatusOverview';

/**
 * TripWireDashboardPage is the main monitoring dashboard for the TripWire
 * cybersecurity tool.
 *
 * It fetches the list of registered agent hosts from `GET /api/v1/hosts`,
 * renders a multi-host selector panel on the left, and a host status overview
 * (summary counters + detail table) on the right.  Operators can select a
 * subset of hosts to narrow the detail table while retaining fleet-wide
 * summary counts.
 */
export function TripWireDashboardPage() {
  const { hosts, loading, error, refetch } = useHosts();
  const [selectedHostIds, setSelectedHostIds] = useState<string[]>([]);

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Page header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">TripWire Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">Real-time host monitoring</p>
        </div>
        <button
          type="button"
          onClick={refetch}
          disabled={loading}
          aria-label="Refresh host list"
          className="flex items-center gap-2 px-3 py-2 rounded-md border border-gray-300 text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </header>

      {/* Error banner */}
      {error && (
        <div
          role="alert"
          className="mx-6 mt-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          <strong className="font-semibold">Error: </strong>
          {error}
        </div>
      )}

      {/* Main layout: sidebar + content */}
      <main className="flex gap-0 p-6">
        {/* Left sidebar — host selector */}
        <aside
          aria-label="Host selection panel"
          className="w-72 shrink-0 mr-6 rounded-lg border border-gray-200 bg-white p-4 self-start"
        >
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Filter by host</h2>
          {loading && hosts.length === 0 ? (
            <p className="text-sm text-gray-400 italic">Loading hosts…</p>
          ) : (
            <HostSelector
              hosts={hosts}
              selectedHostIds={selectedHostIds}
              onChange={setSelectedHostIds}
            />
          )}
        </aside>

        {/* Right content — status overview */}
        <div className="flex-1 min-w-0">
          <HostStatusOverview hosts={hosts} selectedHostIds={selectedHostIds} />
        </div>
      </main>
    </div>
  );
}

export default TripWireDashboardPage;
