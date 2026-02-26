/**
 * TypeScript type definitions for the TripWire cybersecurity dashboard.
 * Matches the data model defined in internal/server/storage/models.go and
 * the REST API documented in docs/concepts/tripwire-cybersecurity-tool/rest-api.md.
 */

// ---------------------------------------------------------------------------
// Enums / discriminated union types
// ---------------------------------------------------------------------------

/** Tripwire event type — matches the TripwireType enum in the backend */
export type TripwireType = 'FILE' | 'NETWORK' | 'PROCESS';

/** Alert severity level */
export type Severity = 'INFO' | 'WARN' | 'CRITICAL';

/** Host connectivity status */
export type HostStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED';

// ---------------------------------------------------------------------------
// Core data models
// ---------------------------------------------------------------------------

/** A single alert event received from an agent */
export interface Alert {
  /** Client-generated UUID */
  alert_id: string;
  /** Host identifier */
  host_id: string;
  /** ISO 8601 timestamp when the event occurred on the host */
  timestamp: string;
  /** Type of tripwire that fired */
  tripwire_type: TripwireType;
  /** Name of the rule that fired */
  rule_name: string;
  /** JSON payload with type-specific metadata */
  event_detail: Record<string, unknown>;
  /** Severity level */
  severity: Severity;
  /** ISO 8601 timestamp when the server received the alert */
  received_at: string;
}

/** A registered monitoring host */
export interface Host {
  /** Unique host identifier */
  host_id: string;
  /** Hostname of the machine */
  hostname: string;
  /** Primary IP address of the host */
  ip_address: string;
  /** Operating system platform, e.g. "linux" */
  platform: string;
  /** Installed agent version string */
  agent_version: string;
  /** ISO 8601 timestamp of last agent heartbeat */
  last_seen: string | null;
  /** Current connectivity status */
  status: HostStatus;
}

// ---------------------------------------------------------------------------
// API request / response types
// ---------------------------------------------------------------------------

/** Query parameters accepted by GET /api/v1/alerts */
export interface AlertQueryParams {
  /** ISO 8601 start time for the time window */
  from?: string;
  /** ISO 8601 end time for the time window */
  to?: string;
  /** Filter to a single host by ID */
  host_id?: string;
  /** Filter to a single severity level */
  severity?: Severity;
  /** Filter to a single tripwire type */
  tripwire_type?: TripwireType;
  /** Maximum number of results to return (default: 50) */
  limit?: number;
  /** Number of results to skip for pagination */
  offset?: number;
}

/** Paginated response from GET /api/v1/alerts */
export interface AlertsResponse {
  alerts: Alert[];
  total: number;
  limit: number;
  offset: number;
}

/** Response from GET /api/v1/hosts */
export interface HostsResponse {
  hosts: Host[];
}

// ---------------------------------------------------------------------------
// Filter state for the dashboard UI
// ---------------------------------------------------------------------------

/** Active filter state used by the dashboard UI */
export interface AlertFilterState {
  /** Filter by severity; undefined means show all */
  severity: Severity | undefined;
  /** Filter by tripwire type; undefined means show all */
  tripwire_type: TripwireType | undefined;
  /** Filter by host ID; undefined means show all hosts */
  host_id: string | undefined;
  /** ISO 8601 start of the time window; undefined means no lower bound */
  from: string | undefined;
  /** ISO 8601 end of the time window; undefined means no upper bound */
  to: string | undefined;
  /** Maximum alerts per page */
  limit: number;
  /** Pagination offset */
  offset: number;
}

/** Default filter state — shows all alerts, first page */
export const DEFAULT_ALERT_FILTERS: AlertFilterState = {
  severity: undefined,
  tripwire_type: undefined,
  host_id: undefined,
  from: undefined,
  to: undefined,
  limit: 50,
  offset: 0,
};
