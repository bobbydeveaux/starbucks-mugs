import { useState, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';
import type { TripwireAlert, WsAlertMessage, WebSocketReadyState } from '../types';

export interface UseAlertsOptions {
  /**
   * WebSocket URL for the live alert stream.
   * Example: `ws://localhost:8080/ws/alerts`
   */
  wsUrl: string;
  /**
   * Bearer token forwarded to {@link useWebSocket} as a query parameter.
   * Required by the server's auth middleware when running without a TLS-
   * terminating reverse proxy.
   */
  token?: string;
  /**
   * Maximum number of alerts to retain in memory.  When the list exceeds
   * this limit the oldest entries (tail of the array) are dropped.
   * Defaults to `1000`.
   */
  maxAlerts?: number;
}

export interface UseAlertsReturn {
  /**
   * Live alert list ordered newest-first.  Prepended on every incoming
   * WebSocket message without triggering a full list re-render (consumers
   * should use a virtualized list component such as AlertFeed).
   */
  alerts: TripwireAlert[];
  /** Current WebSocket connection state */
  wsState: WebSocketReadyState;
  /** Discard all alerts from the in-memory list */
  clearAlerts: () => void;
}

/**
 * Maintains a live, capped in-memory list of TripWire security alerts sourced
 * from the WebSocket stream at `wsUrl`.
 *
 * Alerts are prepended (newest-first) on each incoming WebSocket message.
 * Non-alert frames and malformed JSON are silently ignored.  The list is
 * capped at `maxAlerts` entries to prevent unbounded memory growth during
 * long-running sessions.
 *
 * The hook delegates connection management to {@link useWebSocket}, which
 * handles automatic exponential-backoff reconnection and bearer-token auth.
 *
 * @example
 * const { alerts, wsState } = useAlerts({
 *   wsUrl: 'ws://localhost:8080/ws/alerts',
 *   token: bearerToken,
 * });
 */
export function useAlerts({
  wsUrl,
  token,
  maxAlerts = 1_000,
}: UseAlertsOptions): UseAlertsReturn {
  const [alerts, setAlerts] = useState<TripwireAlert[]>([]);

  // Hold maxAlerts in a ref so the callback closure always sees the current
  // value without needing to be re-created on every render.
  const maxAlertsRef = useRef(maxAlerts);
  maxAlertsRef.current = maxAlerts;

  const handleMessage = useCallback((event: MessageEvent) => {
    let parsed: WsAlertMessage;
    try {
      parsed = JSON.parse(event.data as string) as WsAlertMessage;
    } catch {
      // Ignore non-JSON frames (e.g. ping/pong text frames).
      return;
    }

    // Only process well-formed alert messages.
    if (parsed.type !== 'alert' || !parsed.data?.alert_id) return;

    const incoming = parsed.data;

    setAlerts((prev) => {
      const next = [incoming, ...prev];
      // Cap the list to prevent unbounded memory growth.
      return next.length > maxAlertsRef.current
        ? next.slice(0, maxAlertsRef.current)
        : next;
    });
  }, []);

  const { readyState } = useWebSocket(wsUrl, {
    onMessage: handleMessage,
    token,
  });

  const clearAlerts = useCallback(() => setAlerts([]), []);

  return { alerts, wsState: readyState, clearAlerts };
}
