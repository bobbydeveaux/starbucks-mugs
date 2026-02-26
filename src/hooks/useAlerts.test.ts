import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAlerts } from './useAlerts';
import type { TripwireAlert } from '../types';

// ---------------------------------------------------------------------------
// Mock useWebSocket
// ---------------------------------------------------------------------------

/**
 * We isolate useAlerts by mocking useWebSocket so that tests control exactly
 * which MessageEvents arrive, without needing a real WebSocket.
 */
let capturedOnMessage: ((event: MessageEvent) => void) | undefined;

vi.mock('./useWebSocket', () => ({
  useWebSocket: vi.fn(
    (_url: string, opts?: { onMessage?: (e: MessageEvent) => void }) => {
      capturedOnMessage = opts?.onMessage;
      return { readyState: 'OPEN', sendMessage: vi.fn(), disconnect: vi.fn() };
    },
  ),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeAlert(overrides: Partial<TripwireAlert> = {}): TripwireAlert {
  return {
    alert_id: crypto.randomUUID(),
    host_id: 'host-001',
    hostname: 'web-01',
    timestamp: new Date().toISOString(),
    tripwire_type: 'FILE',
    rule_name: 'etc-passwd-watch',
    severity: 'CRITICAL',
    ...overrides,
  };
}

function sendAlertMessage(alert: TripwireAlert) {
  act(() => {
    capturedOnMessage?.({
      data: JSON.stringify({ type: 'alert', data: alert }),
    } as MessageEvent);
  });
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  capturedOnMessage = undefined;
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useAlerts', () => {
  // ── Initial state ──────────────────────────────────────────────────────────

  it('starts with an empty alert list', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    expect(result.current.alerts).toEqual([]);
  });

  it('exposes the WebSocket ready state', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    expect(result.current.wsState).toBe('OPEN');
  });

  // ── Incoming alerts ────────────────────────────────────────────────────────

  it('prepends a new alert when a well-formed WS message arrives', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    const alert = makeAlert();
    sendAlertMessage(alert);
    expect(result.current.alerts).toHaveLength(1);
    expect(result.current.alerts[0].alert_id).toBe(alert.alert_id);
  });

  it('prepends (newest-first) — later alerts appear at index 0', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    const first = makeAlert({ rule_name: 'first' });
    const second = makeAlert({ rule_name: 'second' });
    sendAlertMessage(first);
    sendAlertMessage(second);
    expect(result.current.alerts[0].rule_name).toBe('second');
    expect(result.current.alerts[1].rule_name).toBe('first');
  });

  it('accumulates multiple alerts in order', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    const a1 = makeAlert({ rule_name: 'a1' });
    const a2 = makeAlert({ rule_name: 'a2' });
    const a3 = makeAlert({ rule_name: 'a3' });
    sendAlertMessage(a1);
    sendAlertMessage(a2);
    sendAlertMessage(a3);
    expect(result.current.alerts).toHaveLength(3);
    expect(result.current.alerts.map((a) => a.rule_name)).toEqual(['a3', 'a2', 'a1']);
  });

  // ── maxAlerts cap ──────────────────────────────────────────────────────────

  it('caps the alert list at maxAlerts (drops oldest)', () => {
    const maxAlerts = 5;
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts', maxAlerts }),
    );
    for (let i = 0; i < 8; i++) {
      sendAlertMessage(makeAlert({ rule_name: `alert-${i}` }));
    }
    expect(result.current.alerts).toHaveLength(maxAlerts);
    // The most recent 5 alerts should be kept (alerts 7..3)
    expect(result.current.alerts[0].rule_name).toBe('alert-7');
    expect(result.current.alerts[maxAlerts - 1].rule_name).toBe('alert-3');
  });

  it('defaults to a maxAlerts cap of 1000', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    // Batch all 1050 messages in a single act() to avoid per-message render overhead
    act(() => {
      for (let i = 0; i < 1050; i++) {
        capturedOnMessage?.({
          data: JSON.stringify({ type: 'alert', data: makeAlert() }),
        } as MessageEvent);
      }
    });
    expect(result.current.alerts).toHaveLength(1000);
  });

  // ── Malformed / irrelevant messages ───────────────────────────────────────

  it('ignores non-JSON WebSocket frames', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    act(() => {
      capturedOnMessage?.({ data: 'not json at all' } as MessageEvent);
    });
    expect(result.current.alerts).toHaveLength(0);
  });

  it('ignores messages with a non-alert type', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    act(() => {
      capturedOnMessage?.({
        data: JSON.stringify({ type: 'heartbeat', payload: {} }),
      } as MessageEvent);
    });
    expect(result.current.alerts).toHaveLength(0);
  });

  it('ignores alert messages missing alert_id', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    act(() => {
      capturedOnMessage?.({
        data: JSON.stringify({ type: 'alert', data: { host_id: 'x' } }),
      } as MessageEvent);
    });
    expect(result.current.alerts).toHaveLength(0);
  });

  // ── clearAlerts ────────────────────────────────────────────────────────────

  it('clearAlerts empties the alert list', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    sendAlertMessage(makeAlert());
    sendAlertMessage(makeAlert());
    expect(result.current.alerts).toHaveLength(2);

    act(() => result.current.clearAlerts());
    expect(result.current.alerts).toHaveLength(0);
  });

  it('clearAlerts does not error when the list is already empty', () => {
    const { result } = renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts' }),
    );
    expect(() => act(() => result.current.clearAlerts())).not.toThrow();
  });

  // ── Token forwarding ───────────────────────────────────────────────────────

  it('forwards the token option to useWebSocket', async () => {
    const { useWebSocket } = await import('./useWebSocket');
    renderHook(() =>
      useAlerts({ wsUrl: 'ws://localhost:8080/ws/alerts', token: 'secret-tok' }),
    );
    expect(useWebSocket).toHaveBeenCalledWith(
      'ws://localhost:8080/ws/alerts',
      expect.objectContaining({ token: 'secret-tok' }),
    );
  });
});
