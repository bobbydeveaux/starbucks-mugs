import { useState, useEffect, useRef, useCallback } from 'react';
import type { WebSocketReadyState } from '../types';

/** Clamp value between min and max */
function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export interface UseWebSocketOptions {
  /** Called for each incoming MessageEvent */
  onMessage?: (event: MessageEvent) => void;
  /**
   * Maximum number of reconnect attempts before giving up.
   * Defaults to `Infinity` (reconnect indefinitely).
   */
  reconnectAttempts?: number;
  /**
   * Base reconnect delay in milliseconds.  Each retry doubles the interval
   * (exponential back-off), capped at 30 000 ms.  Defaults to 1 000 ms.
   */
  reconnectIntervalMs?: number;
  /**
   * Bearer token to authenticate the WebSocket connection.
   *
   * Browser WebSocket connections cannot carry custom HTTP headers, so the
   * token is appended to the URL as the `token` query parameter
   * (`ws://host/ws/alerts?token=<value>`).  The server's auth middleware or
   * reverse proxy is expected to validate this parameter.
   */
  token?: string;
  /**
   * When `false` the hook will not attempt to reconnect after a disconnect.
   * Defaults to `true`.
   */
  shouldReconnect?: boolean;
}

export interface UseWebSocketReturn {
  /** Current WebSocket ready state */
  readyState: WebSocketReadyState;
  /** Send a UTF-8 text message over the open connection (no-op if not OPEN) */
  sendMessage: (data: string) => void;
  /** Manually close the connection and cancel any pending reconnect timer */
  disconnect: () => void;
}

/**
 * Manages a WebSocket connection with automatic exponential-backoff
 * reconnection.
 *
 * The hook dials `url` on mount and re-dials whenever it drops.  Each
 * successive reconnect attempt waits `reconnectIntervalMs * 2^(attempt-1)`
 * milliseconds (capped at 30 s).  If `token` is provided it is appended to
 * the URL as `?token=<value>` because the browser WebSocket API does not
 * support sending custom HTTP headers during the upgrade handshake.
 *
 * @param url  - WebSocket URL, e.g. `ws://localhost:8080/ws/alerts`
 * @param options - Connection and reconnect options
 *
 * @example
 * const { readyState } = useWebSocket('ws://localhost:8080/ws/alerts', {
 *   token: bearerToken,
 *   onMessage: (e) => console.log(e.data),
 * });
 */
export function useWebSocket(
  url: string,
  options: UseWebSocketOptions = {},
): UseWebSocketReturn {
  const {
    onMessage,
    reconnectAttempts = Infinity,
    reconnectIntervalMs = 1_000,
    token,
    shouldReconnect = true,
  } = options;

  const [readyState, setReadyState] = useState<WebSocketReadyState>('CLOSED');

  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);

  // Keep the latest callbacks in refs to avoid stale closures without
  // re-triggering the connection effect.
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  // connectRef holds the latest connect function so the onclose handler can
  // schedule the next attempt without a circular useCallback dependency.
  const connectRef = useRef<() => void>(() => undefined);

  /** Build the full URL, appending the token as a query parameter if provided. */
  const buildUrl = useCallback((): string => {
    if (!token) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}token=${encodeURIComponent(token)}`;
  }, [url, token]);

  const connect = useCallback((): void => {
    // Tear down any existing socket before opening a new one.
    const prev = wsRef.current;
    if (prev) {
      prev.onopen = null;
      prev.onclose = null;
      prev.onerror = null;
      prev.onmessage = null;
      prev.close();
    }

    const ws = new WebSocket(buildUrl());
    wsRef.current = ws;
    setReadyState('CONNECTING');

    ws.onopen = () => {
      attemptRef.current = 0;
      setReadyState('OPEN');
    };

    ws.onmessage = (event: MessageEvent) => {
      onMessageRef.current?.(event);
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; let onclose drive reconnect.
      setReadyState('CLOSED');
    };

    ws.onclose = () => {
      setReadyState('CLOSED');

      if (intentionalCloseRef.current) return;
      if (!shouldReconnect) return;
      if (attemptRef.current >= reconnectAttempts) return;

      attemptRef.current++;
      const delay = clamp(
        reconnectIntervalMs * 2 ** (attemptRef.current - 1),
        reconnectIntervalMs,
        30_000,
      );
      timerRef.current = setTimeout(() => connectRef.current(), delay);
    };
  }, [buildUrl, reconnectAttempts, reconnectIntervalMs, shouldReconnect]);

  // Sync connectRef to the latest connect function.
  connectRef.current = connect;

  useEffect(() => {
    intentionalCloseRef.current = false;
    connect();

    return () => {
      intentionalCloseRef.current = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendMessage = useCallback((data: string): void => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  const disconnect = useCallback((): void => {
    intentionalCloseRef.current = true;
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const ws = wsRef.current;
    if (ws) {
      ws.close();
    }
    setReadyState('CLOSED');
  }, []);

  return { readyState, sendMessage, disconnect };
}
