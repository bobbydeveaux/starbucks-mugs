/**
 * useAlerts — fetches alerts from the REST API and patches in live alert
 * events delivered over the WebSocket connection.
 *
 * The hook re-fetches whenever the filters change. WebSocket events are
 * prepended to the front of the list without triggering an extra API call,
 * keeping the feed and trend chart up-to-date within one render cycle.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { Alert, AlertFilters } from '../types';
import { useWebSocket } from './useWebSocket';
import { timeRangeToDates } from '../utils/aggregateAlerts';

export interface UseAlertsResult {
  alerts: Alert[];
  loading: boolean;
  error: string | null;
  /** Computed window start; consumed by TrendChart for binning */
  from: Date;
  /** Computed window end; consumed by TrendChart for binning */
  to: Date;
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const WS_BASE = (import.meta.env.VITE_WS_BASE as string | undefined) ?? '';

function buildApiUrl(filters: AlertFilters, from: Date, to: Date): string {
  const params = new URLSearchParams();
  params.set('from', from.toISOString());
  params.set('to', to.toISOString());

  if (filters.hostIds.length > 0) {
    // REST API supports a single host_id filter; use the first selected host
    params.set('host_id', filters.hostIds[0]);
  }
  if (filters.severity !== 'ALL') {
    params.set('severity', filters.severity);
  }
  if (filters.tripwireType !== 'ALL') {
    params.set('type', filters.tripwireType);
  }
  params.set('limit', '1000');

  return `${API_BASE}/api/v1/alerts?${params.toString()}`;
}

export function useAlerts(filters: AlertFilters): UseAlertsResult {
  const { from, to } = timeRangeToDates(filters.timeRange);

  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const fetchAlerts = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(buildApiUrl(filters, from, to), {
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const data = (await res.json()) as Alert[];
      setAlerts(data);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      setError(err instanceof Error ? err.message : 'Failed to fetch alerts');
    } finally {
      setLoading(false);
    }
  }, [
    // Re-fetch whenever any filter value changes; stringify arrays to get
    // a stable reference comparison with useCallback's dependency check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    filters.timeRange,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    filters.severity,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    filters.tripwireType,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    filters.hostIds.join(','),
  ]);

  useEffect(() => {
    void fetchAlerts();
    return () => abortRef.current?.abort();
  }, [fetchAlerts]);

  // Patch in live alerts from the WebSocket without a full re-fetch
  const handleWsMessage = useCallback(
    (msg: { type: string; payload: unknown }) => {
      if (msg.type === 'alert') {
        const alert = msg.payload as Alert;
        setAlerts((prev) => [alert, ...prev]);
      }
    },
    [],
  );

  useWebSocket({
    url: `${WS_BASE}/ws/alerts`,
    onMessage: handleWsMessage,
    enabled: WS_BASE !== '' || API_BASE !== '',
  });

  return { alerts, loading, error, from, to };
}
