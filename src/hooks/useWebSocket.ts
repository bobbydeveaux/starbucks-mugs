/**
 * useWebSocket — manages a WebSocket connection with automatic exponential-
 * backoff reconnection.
 *
 * The hook connects on mount, reconnects after any close or error, and cleans
 * up the socket and any pending reconnect timer on unmount.
 */

import { useEffect, useRef, useCallback } from 'react';

export interface WebSocketMessage<T = unknown> {
  type: string;
  payload: T;
}

export interface UseWebSocketOptions<T = unknown> {
  /** Full WebSocket URL, e.g. "ws://localhost:8080/ws/alerts" */
  url: string;
  /** Optional bearer token appended as ?token=<value> */
  token?: string;
  /** Called for every successfully parsed JSON message */
  onMessage: (msg: WebSocketMessage<T>) => void;
  /** Set to false to skip connecting (useful when a prerequisite is missing) */
  enabled?: boolean;
}

const MAX_RETRY_DELAY_MS = 30_000;

/**
 * Compute exponential-backoff delay for the n-th retry attempt (0-indexed).
 * Caps at MAX_RETRY_DELAY_MS.
 */
function backoffDelay(attempt: number): number {
  return Math.min(1_000 * 2 ** attempt, MAX_RETRY_DELAY_MS);
}

export function useWebSocket<T = unknown>({
  url,
  token,
  onMessage,
  enabled = true,
}: UseWebSocketOptions<T>): void {
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);

  // Keep onMessage in a ref so changing the callback never triggers reconnect
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  const connect = useCallback(() => {
    if (!enabled) return;

    const fullUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url;

    let ws: WebSocket;
    try {
      ws = new WebSocket(fullUrl);
    } catch {
      // If the URL is invalid, schedule a retry anyway
      timerRef.current = setTimeout(connect, backoffDelay(attemptRef.current++));
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WebSocketMessage<T>;
        onMessageRef.current(msg);
      } catch {
        // Ignore non-JSON frames
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; let onclose handle retry
      ws.close();
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (!enabled) return;
      const delay = backoffDelay(attemptRef.current++);
      timerRef.current = setTimeout(connect, delay);
    };
  }, [url, token, enabled]);

  useEffect(() => {
    connect();

    return () => {
      // Prevent the close handler from scheduling a reconnect after unmount
      const ws = wsRef.current;
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
        wsRef.current = null;
      }
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [connect]);
}
