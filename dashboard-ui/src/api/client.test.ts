import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import {
  setToken,
  getToken,
  clearToken,
  isAuthenticated,
  getAlerts,
  getHosts,
  getAudit,
  getHealth,
  ApiResponseError,
} from './client';

// ---------------------------------------------------------------------------
// Token storage tests
// ---------------------------------------------------------------------------

describe('token storage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('setToken stores token in localStorage', () => {
    setToken('test-token-123');
    expect(localStorage.getItem('tripwire_access_token')).toBe('test-token-123');
  });

  it('getToken retrieves stored token', () => {
    localStorage.setItem('tripwire_access_token', 'my-token');
    expect(getToken()).toBe('my-token');
  });

  it('getToken returns null when no token stored', () => {
    expect(getToken()).toBeNull();
  });

  it('clearToken removes token from localStorage', () => {
    localStorage.setItem('tripwire_access_token', 'my-token');
    clearToken();
    expect(localStorage.getItem('tripwire_access_token')).toBeNull();
  });

  it('isAuthenticated returns true when token exists', () => {
    setToken('token');
    expect(isAuthenticated()).toBe(true);
  });

  it('isAuthenticated returns false when no token', () => {
    expect(isAuthenticated()).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// API fetch helpers tests
// ---------------------------------------------------------------------------

describe('API client fetch helpers', () => {
  const mockFetch = vi.fn();

  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', mockFetch);
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockSuccess(body: unknown, status = 200) {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status,
      text: () => Promise.resolve(JSON.stringify(body)),
    });
  }

  function mockError(status: number, body = '{"error":"bad request"}') {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status,
      text: () => Promise.resolve(body),
    });
  }

  it('getHealth fetches /healthz without auth header', async () => {
    mockSuccess({ status: 'ok' });
    const result = await getHealth();
    expect(result).toEqual({ status: 'ok' });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/healthz');
    expect((init.headers as Record<string, string>)['Authorization']).toBeUndefined();
  });

  it('getAlerts attaches Authorization header when token is set', async () => {
    setToken('bearer-abc');
    mockSuccess([]);
    await getAlerts({ from: '2026-01-01T00:00:00Z', to: '2026-02-01T00:00:00Z' });
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer bearer-abc');
  });

  it('getAlerts encodes query params correctly', async () => {
    mockSuccess([]);
    await getAlerts({
      from: '2026-01-01T00:00:00Z',
      to: '2026-02-01T00:00:00Z',
      severity: 'CRITICAL',
      limit: 50,
      offset: 0,
    });
    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/alerts?');
    expect(url).toContain('severity=CRITICAL');
    expect(url).toContain('limit=50');
    expect(url).toContain('from=2026-01-01T00%3A00%3A00Z');
  });

  it('getAlerts omits undefined params', async () => {
    mockSuccess([]);
    await getAlerts({ from: '2026-01-01T00:00:00Z', to: '2026-02-01T00:00:00Z' });
    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain('host_id');
    expect(url).not.toContain('severity');
  });

  it('getHosts fetches /api/v1/hosts', async () => {
    const hosts = [{ host_id: 'h1', hostname: 'web-01' }];
    mockSuccess(hosts);
    const result = await getHosts();
    expect(result).toEqual(hosts);
    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/hosts');
  });

  it('getAudit encodes query params', async () => {
    mockSuccess([]);
    await getAudit({
      host_id: 'host-uuid',
      from: '2026-01-01T00:00:00Z',
      to: '2026-02-01T00:00:00Z',
    });
    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/audit?');
    expect(url).toContain('host_id=host-uuid');
  });

  it('throws ApiResponseError on non-ok response', async () => {
    mockError(401, '{"error":"unauthorized"}');
    await expect(getHosts()).rejects.toBeInstanceOf(ApiResponseError);
  });

  it('ApiResponseError carries status and body', async () => {
    mockError(403, '{"error":"forbidden"}');
    try {
      await getHosts();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiResponseError);
      expect((e as ApiResponseError).status).toBe(403);
      expect((e as ApiResponseError).body).toBe('{"error":"forbidden"}');
    }
  });

  it('does not send Authorization header when no token', async () => {
    mockSuccess({ status: 'ok' });
    await getHealth();
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)['Authorization']).toBeUndefined();
  });
});
