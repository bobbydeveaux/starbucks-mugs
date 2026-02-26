import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchAlerts, fetchHosts } from './alerts';
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
      event_detail: { path: '/etc/passwd', event: 'WRITE' },
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

function makeFetchMock(data: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: ok ? 'OK' : 'Not Found',
    json: () => Promise.resolve(data),
  });
}

// ---------------------------------------------------------------------------
// fetchAlerts
// ---------------------------------------------------------------------------

describe('fetchAlerts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetchMock(mockAlertsResponse));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls /api/v1/alerts without params when called with empty object', async () => {
    const result = await fetchAlerts({});
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe('/api/v1/alerts');
    expect(result).toEqual(mockAlertsResponse);
  });

  it('appends severity param to the URL', async () => {
    await fetchAlerts({ severity: 'CRITICAL' });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain('severity=CRITICAL');
  });

  it('appends tripwire_type param to the URL', async () => {
    await fetchAlerts({ tripwire_type: 'FILE' });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain('tripwire_type=FILE');
  });

  it('appends host_id param to the URL', async () => {
    await fetchAlerts({ host_id: 'host-abc' });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain('host_id=host-abc');
  });

  it('appends limit and offset params to the URL', async () => {
    await fetchAlerts({ limit: 20, offset: 40 });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain('limit=20');
    expect(url).toContain('offset=40');
  });

  it('omits undefined params from the URL', async () => {
    await fetchAlerts({ severity: undefined, host_id: undefined });
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).not.toContain('severity');
    expect(url).not.toContain('host_id');
  });

  it('throws an error when the server returns a non-ok status', async () => {
    vi.stubGlobal('fetch', makeFetchMock({}, false, 401));
    await expect(fetchAlerts()).rejects.toThrow('API error 401');
  });

  it('throws an error when fetch itself rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));
    await expect(fetchAlerts()).rejects.toThrow('Network error');
  });
});

// ---------------------------------------------------------------------------
// fetchHosts
// ---------------------------------------------------------------------------

describe('fetchHosts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetchMock(mockHostsResponse));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls /api/v1/hosts', async () => {
    const result = await fetchHosts();
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe('/api/v1/hosts');
    expect(result).toEqual(mockHostsResponse);
  });

  it('throws an error when the server returns a non-ok status', async () => {
    vi.stubGlobal('fetch', makeFetchMock({}, false, 500));
    await expect(fetchHosts()).rejects.toThrow('API error 500');
  });
});
