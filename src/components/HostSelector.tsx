import type { Host } from '../types';
import { HostStatusBadge } from './HostStatusBadge';

interface HostSelectorProps {
  /** Full list of available hosts to display in the selector */
  hosts: Host[];
  /** IDs of currently selected hosts */
  selectedHostIds: string[];
  /** Called whenever the selection changes */
  onChange: (selectedHostIds: string[]) => void;
}

/**
 * HostSelector renders a scrollable, accessible checklist that lets operators
 * select one or more monitored hosts.  It exposes "Select All" and "Clear"
 * shortcuts and surfaces each host's current status badge so operators can
 * quickly identify degraded or offline machines.
 *
 * Selection state is entirely controlled: the parent owns `selectedHostIds`
 * and receives updates via `onChange`.
 */
export function HostSelector({ hosts, selectedHostIds, onChange }: HostSelectorProps) {
  const allSelected = hosts.length > 0 && selectedHostIds.length === hosts.length;
  const noneSelected = selectedHostIds.length === 0;

  function toggleHost(hostId: string) {
    if (selectedHostIds.includes(hostId)) {
      onChange(selectedHostIds.filter((id) => id !== hostId));
    } else {
      onChange([...selectedHostIds, hostId]);
    }
  }

  function selectAll() {
    onChange(hosts.map((h) => h.host_id));
  }

  function clearAll() {
    onChange([]);
  }

  return (
    <div className="flex flex-col gap-2" aria-label="Host selector">
      {/* Bulk-action toolbar */}
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium text-gray-700">
          {hosts.length} host{hosts.length !== 1 ? 's' : ''}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={selectAll}
            disabled={allSelected}
            aria-label="Select all hosts"
            className="px-2 py-1 rounded text-xs font-medium border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Select all
          </button>
          <button
            type="button"
            onClick={clearAll}
            disabled={noneSelected}
            aria-label="Clear host selection"
            className="px-2 py-1 rounded text-xs font-medium border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Scrollable host checklist */}
      <ul
        role="listbox"
        aria-multiselectable="true"
        aria-label="Available hosts"
        className="max-h-64 overflow-y-auto rounded-md border border-gray-200 divide-y divide-gray-100"
      >
        {hosts.length === 0 && (
          <li className="px-3 py-3 text-sm text-gray-500 italic">No hosts registered</li>
        )}
        {hosts.map((host) => {
          const isSelected = selectedHostIds.includes(host.host_id);
          return (
            <li
              key={host.host_id}
              role="option"
              aria-selected={isSelected}
              className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
              onClick={() => toggleHost(host.host_id)}
            >
              <input
                type="checkbox"
                id={`host-${host.host_id}`}
                checked={isSelected}
                onChange={() => toggleHost(host.host_id)}
                onClick={(e) => e.stopPropagation()}
                aria-label={`Select ${host.hostname}`}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
              />
              <label
                htmlFor={`host-${host.host_id}`}
                className="flex flex-1 items-center justify-between gap-2 cursor-pointer text-sm"
                onClick={(e) => e.preventDefault()}
              >
                <span className="font-medium text-gray-800 truncate">{host.hostname}</span>
                <HostStatusBadge status={host.status} />
              </label>
            </li>
          );
        })}
      </ul>

      {/* Selection summary */}
      {hosts.length > 0 && (
        <p className="text-xs text-gray-500" aria-live="polite">
          {selectedHostIds.length === 0
            ? 'No hosts selected — showing all'
            : `${selectedHostIds.length} of ${hosts.length} selected`}
        </p>
      )}
    </div>
  );
}

export default HostSelector;
