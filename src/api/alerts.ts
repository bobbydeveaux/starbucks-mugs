/**
 * Type-safe REST API client for the TripWire dashboard server.
 * Communicates with the endpoints documented in
 * docs/concepts/tripwire-cybersecurity-tool/rest-api.md.
 */

import type {
  AlertQueryParams,
  AlertsResponse,
  HostsResponse,
} from '../types/alert';

/** Base URL for the dashboard API (relative so it works in any deployment) */
const API_BASE = '/api/v1';

/**
 * Constructs a query string from an object, omitting keys whose value is
 * undefined, null, or an empty string.
 */
function buildQueryString(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== '',
  );
  if (entries.length === 0) return '';
  const qs = entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&');
  return `?${qs}`;
}

/**
 * Performs a fetch request and parses the JSON response.
 * Throws a descriptive error when the server returns a non-2xx status.
 */
async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${response.statusText} (${path})`);
  }

  return response.json() as Promise<T>;
}

/**
 * Fetches a paginated, filtered list of alerts from GET /api/v1/alerts.
 *
 * @param params - Optional query parameters for filtering and pagination.
 * @param signal - Optional AbortSignal to cancel the request.
 * @returns Paginated alerts response.
 *
 * @example
 * const data = await fetchAlerts({ severity: 'CRITICAL', limit: 20 });
 */
export async function fetchAlerts(
  params: AlertQueryParams = {},
  signal?: AbortSignal,
): Promise<AlertsResponse> {
  const qs = buildQueryString(params as Record<string, string | number | undefined>);
  return apiFetch<AlertsResponse>(`/alerts${qs}`, signal);
}

/**
 * Fetches all registered hosts from GET /api/v1/hosts.
 *
 * @param signal - Optional AbortSignal to cancel the request.
 * @returns List of registered hosts.
 */
export async function fetchHosts(signal?: AbortSignal): Promise<HostsResponse> {
  return apiFetch<HostsResponse>('/hosts', signal);
}
