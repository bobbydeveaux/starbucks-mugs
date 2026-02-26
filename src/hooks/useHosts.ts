import { useState, useEffect, useCallback } from 'react';
import type { Host } from '../types';

/** Return shape of the useHosts hook */
export interface UseHostsResult {
  /** All hosts registered with the dashboard server */
  hosts: Host[];
  /** True while the initial or refetch request is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains a human-readable error message */
  error: string | null;
  /** Trigger a fresh fetch of the hosts list */
  refetch: () => void;
}

/**
 * Fetches the list of monitored hosts from `GET /api/v1/hosts`.
 *
 * The hook automatically cancels the in-flight request when the consuming
 * component unmounts.  Call the returned `refetch` function to force a reload
 * without remounting the component (e.g. after a manual refresh button click).
 *
 * @returns Loading state, error state, host array, and a refetch callback.
 *
 * @example
 * const { hosts, loading, error, refetch } = useHosts();
 */
export function useHosts(): UseHostsResult {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Incrementing this counter triggers a new fetch without changing component
  // identity (avoids remounting the consumer).
  const [fetchTick, setFetchTick] = useState(0);

  const refetch = useCallback(() => {
    setFetchTick((n) => n + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchHosts() {
      setLoading(true);
      setError(null);

      try {
        const res = await fetch('/api/v1/hosts', { signal });
        if (!res.ok) {
          throw new Error(`Failed to fetch hosts: HTTP ${res.status}`);
        }
        const data: Host[] = await res.json();
        setHosts(data);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Component unmounted — discard the result silently.
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load hosts');
      } finally {
        setLoading(false);
      }
    }

    fetchHosts();

    return () => {
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchTick]);

  return { hosts, loading, error, refetch };
}
