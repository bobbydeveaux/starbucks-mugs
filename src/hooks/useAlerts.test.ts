import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { useAlerts, useHosts, alertsQueryKey, hostsQueryKey } from './useAlerts';
import { DEFAULT_ALERT_FILTERS } from '../types/alert';
import type { AlertsResponse, HostsResponse } from '../types/alert';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockAlertsResponse: AlertsResponse = {
  alerts: [
    {
      alert_id: 'alert-001',
      host_id: 'host-abc',
      timestamp: '2026-02-01T12:00:00Z',
      tripwire_type: 'FILE',
      rule_name: 'etc-passwd-watch',
      event_detail: {},
      severity: 'CRITICAL',
      received_at: '2026-02-01T12:00:01Z',
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

const mockHostsResponse: HostsResponse = {
  hosts: [
    {
      host_id: 'host-abc',
      hostname: 'prod-server-01',
      ip_address: '10.0.0.1',
      platform: 'linux',
      agent_version: '1.2.0',
      last_seen: '2026-02-01T12:00:00Z',
      status: 'ONLINE',
    },
  ],
};

function makeFetchMock(data: unknown, ok = true) {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? 'OK' : 'Internal Server Error',
    json: () => Promise.resolve(data),
  });
}

// ---------------------------------------------------------------------------
// Wrapper that provides a fresh QueryClient for each test
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
}

// ---------------------------------------------------------------------------
// Query key factories
// ---------------------------------------------------------------------------

describe('alertsQueryKey', () => {
  it('includes the filters in the query key', () => {
    const key = alertsQueryKey(DEFAULT_ALERT_FILTERS);
    expect(key[0]).toBe('alerts');
    expect(key[1]).toBe(DEFAULT_ALERT_FILTERS);
  });
});

describe('hostsQueryKey', () => {
  it('returns the hosts key', () => {
    expect(hostsQueryKey()).toEqual(['hosts']);
  });
});

// ---------------------------------------------------------------------------
// useAlerts
// ---------------------------------------------------------------------------

describe('useAlerts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetchMock(mockAlertsResponse));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts in loading state', () => {
    const { result } = renderHook(() => useAlerts(DEFAULT_ALERT_FILTERS), {
      wrapper: createWrapper(),
    });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });

  it('returns alert data after successful fetch', async () => {
    const { result } = renderHook(() => useAlerts(DEFAULT_ALERT_FILTERS), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(mockAlertsResponse);
    expect(result.current.error).toBeNull();
  });

  it('returns error state when fetch fails', async () => {
    vi.stubGlobal('fetch', makeFetchMock({}, false));
    const { result } = renderHook(() => useAlerts(DEFAULT_ALERT_FILTERS), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).not.toBeNull();
    expect(result.current.data).toBeUndefined();
  });

  it('does not fetch when enabled is false', () => {
    const fetchMock = makeFetchMock(mockAlertsResponse);
    vi.stubGlobal('fetch', fetchMock);

    renderHook(() => useAlerts(DEFAULT_ALERT_FILTERS, { enabled: false }), {
      wrapper: createWrapper(),
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('passes severity filter to the API call', async () => {
    const fetchMock = makeFetchMock(mockAlertsResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(
      () => useAlerts({ ...DEFAULT_ALERT_FILTERS, severity: 'CRITICAL' }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('severity=CRITICAL');
  });
});

// ---------------------------------------------------------------------------
// useHosts
// ---------------------------------------------------------------------------

describe('useHosts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetchMock(mockHostsResponse));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns host data after successful fetch', async () => {
    const { result } = renderHook(() => useHosts(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(mockHostsResponse);
    expect(result.current.error).toBeNull();
  });

  it('returns error state when fetch fails', async () => {
    vi.stubGlobal('fetch', makeFetchMock({}, false));
    const { result } = renderHook(() => useHosts(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).not.toBeNull();
  });
});
