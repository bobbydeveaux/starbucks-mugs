import type { Host, HostStatus } from '../types';
import { HostStatusBadge } from './HostStatusBadge';

interface HostStatusOverviewProps {
  /** Full list of registered hosts */
  hosts: Host[];
  /**
   * Optional set of host IDs to display.  When provided only the matching
   * hosts are rendered; an empty array means "show all".
   */
  selectedHostIds?: string[];
}

/** Format an ISO-8601 last_seen timestamp as a locale-aware relative string */
function formatLastSeen(lastSeen: string | undefined): string {
  if (!lastSeen) return 'Never';

  const date = new Date(lastSeen);
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return date.toLocaleDateString();
}

/** Count hosts by status for the summary row */
function countByStatus(hosts: Host[]): Record<HostStatus, number> {
  return hosts.reduce(
    (acc, h) => {
      acc[h.status] = (acc[h.status] ?? 0) + 1;
      return acc;
    },
    { ONLINE: 0, OFFLINE: 0, DEGRADED: 0 } as Record<HostStatus, number>,
  );
}

/**
 * HostStatusOverview renders a summary card strip followed by a table of every
 * registered host with its current status, IP, platform, agent version and
 * last-seen timestamp.
 *
 * When `selectedHostIds` is a non-empty array only the matching hosts are
 * shown in the table; the summary counters always reflect the full list so
 * operators have fleet-wide context while filtering.
 */
export function HostStatusOverview({ hosts, selectedHostIds }: HostStatusOverviewProps) {
  const visibleHosts =
    selectedHostIds && selectedHostIds.length > 0
      ? hosts.filter((h) => selectedHostIds.includes(h.host_id))
      : hosts;

  const counts = countByStatus(hosts);

  return (
    <section aria-label="Host status overview" className="flex flex-col gap-4">
      {/* Summary cards */}
      <div role="group" className="grid grid-cols-3 gap-3" aria-label="Host status summary">
        <div
          role="img"
          className="flex flex-col items-center rounded-lg border border-green-200 bg-green-50 px-4 py-3"
          aria-label={`${counts.ONLINE} online hosts`}
        >
          <span className="text-2xl font-bold text-green-700">{counts.ONLINE}</span>
          <span className="text-xs font-medium text-green-600">Online</span>
        </div>
        <div
          role="img"
          className="flex flex-col items-center rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-3"
          aria-label={`${counts.DEGRADED} degraded hosts`}
        >
          <span className="text-2xl font-bold text-yellow-700">{counts.DEGRADED}</span>
          <span className="text-xs font-medium text-yellow-600">Degraded</span>
        </div>
        <div
          role="img"
          className="flex flex-col items-center rounded-lg border border-red-200 bg-red-50 px-4 py-3"
          aria-label={`${counts.OFFLINE} offline hosts`}
        >
          <span className="text-2xl font-bold text-red-700">{counts.OFFLINE}</span>
          <span className="text-xs font-medium text-red-600">Offline</span>
        </div>
      </div>

      {/* Host table */}
      {visibleHosts.length === 0 ? (
        <p className="text-sm text-gray-500 italic py-4 text-center">
          {hosts.length === 0 ? 'No hosts registered yet.' : 'No hosts match the current selection.'}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm" aria-label="Host list">
            <thead className="bg-gray-50">
              <tr>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Hostname
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Status
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  IP Address
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Platform
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Agent Version
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  Last Seen
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {visibleHosts.map((host) => (
                <tr key={host.host_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">
                    {host.hostname}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <HostStatusBadge status={host.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {host.ip_address || '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {host.platform || '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap font-mono text-xs">
                    {host.agent_version || '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {formatLastSeen(host.last_seen)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default HostStatusOverview;
