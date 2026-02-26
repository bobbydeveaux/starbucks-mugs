// API types matching the TripWire dashboard REST API

export type TripwireType = 'FILE' | 'NETWORK' | 'PROCESS';
export type Severity = 'INFO' | 'WARN' | 'CRITICAL';
export type HostStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED';

export interface Alert {
  alert_id: string;
  host_id: string;
  timestamp: string;
  tripwire_type: TripwireType;
  rule_name: string;
  event_detail: Record<string, unknown>;
  severity: Severity;
  received_at: string;
}

export interface Host {
  host_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  agent_version: string;
  last_seen: string;
  status: HostStatus;
}

export interface AuditEntry {
  entry_id: string;
  host_id: string;
  sequence_num: number;
  event_hash: string;
  prev_hash: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AlertsQueryParams {
  from: string;
  to: string;
  host_id?: string;
  severity?: Severity;
  limit?: number;
  offset?: number;
}

export interface AuditQueryParams {
  host_id: string;
  from: string;
  to: string;
}

export interface ApiError {
  error: string;
}

export interface HealthResponse {
  status: 'ok';
}
