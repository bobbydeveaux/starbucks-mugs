import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from './useWebSocket';

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

/**
 * A minimal WebSocket mock that exposes the event callbacks so tests can
 * simulate open / close / message / error events synchronously.
 */
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState: number = MockWebSocket.CONNECTING;
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;

  /** All instances created during the test (for assertions). */
  static instances: MockWebSocket[] = [];

  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({} as CloseEvent);
  });

  send = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  /** Simulate the server accepting the upgrade (readyState → OPEN). */
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({} as Event);
  }

  /** Simulate an incoming text message from the server. */
  simulateMessage(data: string) {
    this.onmessage?.({ data } as MessageEvent);
  }

  /** Simulate the connection dropping (readyState → CLOSED). */
  simulateClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({} as CloseEvent);
  }

  /** Simulate a socket error (followed immediately by close). */
  simulateError() {
    this.onerror?.({} as Event);
    this.simulateClose();
  }
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', MockWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  MockWebSocket.instances = [];
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function latestWs(): MockWebSocket {
  const instances = MockWebSocket.instances;
  const ws = instances[instances.length - 1];
  if (!ws) throw new Error('No MockWebSocket instance found');
  return ws;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useWebSocket', () => {
  // ── Initial state ──────────────────────────────────────────────────────────

  it('starts in CONNECTING state', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    expect(result.current.readyState).toBe('CONNECTING');
  });

  it('creates a WebSocket connection on mount', () => {
    renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(latestWs().url).toBe('ws://localhost:8080/ws/alerts');
  });

  // ── Token appended to URL ──────────────────────────────────────────────────

  it('appends token as query parameter when provided', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { token: 'my-secret-jwt' }),
    );
    expect(latestWs().url).toContain('token=my-secret-jwt');
  });

  it('URL-encodes the token value', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { token: 'Bearer abc+123/==' }),
    );
    expect(latestWs().url).not.toContain('Bearer abc+123/==');
    expect(latestWs().url).toContain('token=');
  });

  it('does not append token param when token is undefined', () => {
    renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    expect(latestWs().url).toBe('ws://localhost:8080/ws/alerts');
    expect(latestWs().url).not.toContain('token=');
  });

  it('uses & separator when URL already has query params', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts?foo=bar', { token: 'tok' }),
    );
    expect(latestWs().url).toBe('ws://localhost:8080/ws/alerts?foo=bar&token=tok');
  });

  // ── readyState transitions ─────────────────────────────────────────────────

  it('transitions to OPEN when connection is established', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    act(() => latestWs().simulateOpen());
    expect(result.current.readyState).toBe('OPEN');
  });

  it('transitions to CLOSED when connection drops', () => {
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { shouldReconnect: false }),
    );
    act(() => latestWs().simulateOpen());
    act(() => latestWs().simulateClose());
    expect(result.current.readyState).toBe('CLOSED');
  });

  // ── onMessage callback ─────────────────────────────────────────────────────

  it('calls onMessage for each incoming message', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts', { onMessage }));
    act(() => latestWs().simulateOpen());
    act(() => latestWs().simulateMessage('{"type":"alert"}'));
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ data: '{"type":"alert"}' }));
  });

  it('calls onMessage for multiple messages in sequence', () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts', { onMessage }));
    act(() => latestWs().simulateOpen());
    act(() => latestWs().simulateMessage('msg1'));
    act(() => latestWs().simulateMessage('msg2'));
    act(() => latestWs().simulateMessage('msg3'));
    expect(onMessage).toHaveBeenCalledTimes(3);
  });

  // ── Automatic reconnection ────────────────────────────────────────────────

  it('reconnects after disconnect with exponential back-off', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { reconnectIntervalMs: 100 }),
    );
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => {
      latestWs().simulateOpen();
      latestWs().simulateClose();
    });

    // First reconnect after 100 ms
    act(() => vi.advanceTimersByTime(100));
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('resets attempt counter after a successful connection', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { reconnectIntervalMs: 100 }),
    );

    // First disconnect → second connect
    act(() => {
      latestWs().simulateOpen();
      latestWs().simulateClose();
    });
    act(() => vi.advanceTimersByTime(100));

    // Second connect succeeds → reset counter
    act(() => latestWs().simulateOpen());

    // Third disconnect should use the base interval (100 ms), not a doubled one
    act(() => latestWs().simulateClose());
    act(() => vi.advanceTimersByTime(100));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('stops reconnecting when shouldReconnect is false', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { shouldReconnect: false }),
    );
    act(() => {
      latestWs().simulateOpen();
      latestWs().simulateClose();
    });
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('stops reconnecting after reaching reconnectAttempts limit', () => {
    renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', {
        reconnectAttempts: 2,
        reconnectIntervalMs: 100,
      }),
    );

    // First connection fails immediately (never opens — stays CONNECTING then closes)
    act(() => latestWs().simulateClose());
    act(() => vi.advanceTimersByTime(100));
    expect(MockWebSocket.instances).toHaveLength(2);

    // Second reconnect attempt also fails
    act(() => latestWs().simulateClose());
    act(() => vi.advanceTimersByTime(200));
    expect(MockWebSocket.instances).toHaveLength(3);

    // Limit reached — no more reconnects regardless of time elapsed
    act(() => latestWs().simulateClose());
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  // ── sendMessage ────────────────────────────────────────────────────────────

  it('sendMessage sends data when the connection is OPEN', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    act(() => latestWs().simulateOpen());
    act(() => result.current.sendMessage('hello'));
    expect(latestWs().send).toHaveBeenCalledWith('hello');
  });

  it('sendMessage is a no-op when the connection is not OPEN', () => {
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { shouldReconnect: false }),
    );
    // Still CONNECTING — do not send
    act(() => result.current.sendMessage('hello'));
    expect(latestWs().send).not.toHaveBeenCalled();
  });

  // ── disconnect ────────────────────────────────────────────────────────────

  it('disconnect closes the socket and stops reconnecting', () => {
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { reconnectIntervalMs: 100 }),
    );
    act(() => latestWs().simulateOpen());
    act(() => result.current.disconnect());
    act(() => vi.advanceTimersByTime(30_000));
    expect(result.current.readyState).toBe('CLOSED');
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  // ── Cleanup on unmount ────────────────────────────────────────────────────

  it('closes the WebSocket when the component unmounts', () => {
    const { unmount } = renderHook(() => useWebSocket('ws://localhost:8080/ws/alerts'));
    const ws = latestWs();
    unmount();
    expect(ws.close).toHaveBeenCalled();
  });

  it('cancels the reconnect timer on unmount', () => {
    const { unmount } = renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { reconnectIntervalMs: 100 }),
    );
    act(() => {
      latestWs().simulateOpen();
      latestWs().simulateClose();
    });
    unmount();
    // Advance past the reconnect window — no new socket should be created
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it('transitions to CLOSED on socket error', () => {
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8080/ws/alerts', { shouldReconnect: false }),
    );
    act(() => latestWs().simulateError());
    expect(result.current.readyState).toBe('CLOSED');
  });
});
