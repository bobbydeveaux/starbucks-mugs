/**
 * useAlerts — TanStack Query-powered hook for fetching dashboard alerts.
 *
 * Integrates with FilterContext to automatically re-fetch when filters change.
 * Also exposes a separate query for the host list used in the host-ID filter.
 */

import { useQuery } from '@tanstack/react-query';
import { fetchAlerts, fetchHosts } from '../api/alerts';
import type { AlertFilterState } from '../types/alert';
import type { AlertsResponse, HostsResponse } from '../types/alert';

// ---------------------------------------------------------------------------
// Query key factories — keeps keys consistent across the app
// ---------------------------------------------------------------------------

/** Returns a stable query key for an alerts list given the current filters */
export const alertsQueryKey = (filters: AlertFilterState) =>
  ['alerts', filters] as const;

/** Returns the query key for the hosts list */
export const hostsQueryKey = () => ['hosts'] as const;

// ---------------------------------------------------------------------------
// useAlerts
// ---------------------------------------------------------------------------

export interface UseAlertsOptions {
  /** Set to false to pause fetching (e.g. while editing a filter form) */
  enabled?: boolean;
  /** Polling interval in milliseconds; 0 disables polling (default) */
  refetchInterval?: number;
}

export interface UseAlertsResult {
  /** Paginated alerts data; undefined while loading */
  data: AlertsResponse | undefined;
  /** True on the initial load before data is available */
  isLoading: boolean;
  /** True when a background refetch is in flight */
  isFetching: boolean;
  /** Non-null when the query encountered an error */
  error: Error | null;
  /** Manually trigger a refetch */
  refetch: () => void;
}

/**
 * Fetches alerts from the REST API using the provided filter state.
 *
 * Uses TanStack Query for caching, background refetching, and automatic
 * re-fetching when `filters` change.
 *
 * @param filters - Active filter / pagination state.
 * @param options - Optional configuration overrides.
 * @returns Loading state, error state, and alert data.
 *
 * @example
 * const { data, isLoading, error } = useAlerts(filters);
 */
export function useAlerts(
  filters: AlertFilterState,
  options: UseAlertsOptions = {},
): UseAlertsResult {
  const { enabled = true, refetchInterval = 0 } = options;

  const { data, isLoading, isFetching, error, refetch } = useQuery<AlertsResponse, Error>({
    queryKey: alertsQueryKey(filters),
    queryFn: ({ signal }) =>
      fetchAlerts(
        {
          from: filters.from,
          to: filters.to,
          host_id: filters.host_id,
          severity: filters.severity,
          tripwire_type: filters.tripwire_type,
          limit: filters.limit,
          offset: filters.offset,
        },
        signal,
      ),
    enabled,
    refetchInterval: refetchInterval > 0 ? refetchInterval : false,
    staleTime: 10_000, // 10 seconds
  });

  return {
    data,
    isLoading,
    isFetching,
    error: error ?? null,
    refetch,
  };
}

// ---------------------------------------------------------------------------
// useHosts
// ---------------------------------------------------------------------------

export interface UseHostsResult {
  /** Host list data; undefined while loading */
  data: HostsResponse | undefined;
  /** True on the initial load */
  isLoading: boolean;
  /** Non-null when the query encountered an error */
  error: Error | null;
}

/**
 * Fetches the list of registered hosts from the REST API.
 *
 * The host list is used to populate the host-ID filter dropdown.
 * It is cached for 60 seconds since hosts change infrequently.
 *
 * @returns Loading state, error state, and host data.
 *
 * @example
 * const { data: hostsData } = useHosts();
 */
export function useHosts(): UseHostsResult {
  const { data, isLoading, error } = useQuery<HostsResponse, Error>({
    queryKey: hostsQueryKey(),
    queryFn: ({ signal }) => fetchHosts(signal),
    staleTime: 60_000, // 60 seconds — hosts change infrequently
  });

  return { data, isLoading, error: error ?? null };
}
