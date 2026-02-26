import type { HostStatus } from '../types';

interface HostStatusBadgeProps {
  /** Current liveness state of the host */
  status: HostStatus;
}

const STATUS_CONFIG: Record<HostStatus, { label: string; className: string }> = {
  ONLINE: {
    label: 'Online',
    className: 'bg-green-100 text-green-800 border-green-300',
  },
  OFFLINE: {
    label: 'Offline',
    className: 'bg-red-100 text-red-800 border-red-300',
  },
  DEGRADED: {
    label: 'Degraded',
    className: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  },
};

/**
 * HostStatusBadge renders a small pill-shaped badge indicating the current
 * liveness state of a monitored host.
 *
 * - **ONLINE** — green pill, "Online"
 * - **OFFLINE** — red pill, "Offline"
 * - **DEGRADED** — yellow pill, "Degraded"
 */
export function HostStatusBadge({ status }: HostStatusBadgeProps) {
  const config = STATUS_CONFIG[status];

  return (
    <span
      role="status"
      aria-label={`Host status: ${config.label}`}
      className={[
        'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border',
        config.className,
      ].join(' ')}
    >
      {config.label}
    </span>
  );
}

export default HostStatusBadge;
