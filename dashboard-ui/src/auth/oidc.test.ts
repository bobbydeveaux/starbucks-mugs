import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { handleCallback, logout } from './oidc';
import { getToken, setToken } from '@/api/client';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockCrypto() {
  const subtleMock = {
    digest: vi.fn().mockResolvedValue(new ArrayBuffer(32)),
  };
  vi.stubGlobal('crypto', {
    getRandomValues: (arr: Uint8Array) => {
      arr.fill(42);
      return arr;
    },
    subtle: subtleMock,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('OIDC handleCallback', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    mockCrypto();
    vi.stubGlobal('fetch', vi.fn());
    // Set OIDC env vars
    vi.stubEnv('VITE_OIDC_TOKEN_ENDPOINT', 'https://auth.example.com/token');
    vi.stubEnv('VITE_OIDC_CLIENT_ID', 'test-client');
    vi.stubEnv('VITE_OIDC_REDIRECT_URI', 'http://localhost:3000/auth/callback');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('returns false when state does not match', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'expected-state');
    sessionStorage.setItem('tripwire_oidc_verifier', 'verifier');
    const params = new URLSearchParams({ code: 'abc', state: 'wrong-state' });
    const result = await handleCallback(params);
    expect(result).toBe(false);
  });

  it('returns false when code is missing', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'state123');
    sessionStorage.setItem('tripwire_oidc_verifier', 'verifier');
    const params = new URLSearchParams({ state: 'state123' });
    const result = await handleCallback(params);
    expect(result).toBe(false);
  });

  it('returns false when no stored state exists', async () => {
    const params = new URLSearchParams({ code: 'abc', state: 'state123' });
    const result = await handleCallback(params);
    expect(result).toBe(false);
  });

  it('stores access token and returns true on successful exchange', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'state123');
    sessionStorage.setItem('tripwire_oidc_verifier', 'my-verifier');

    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ access_token: 'jwt-access-token', token_type: 'Bearer' }),
    });

    const params = new URLSearchParams({ code: 'auth-code', state: 'state123' });
    const result = await handleCallback(params);

    expect(result).toBe(true);
    expect(getToken()).toBe('jwt-access-token');
  });

  it('returns false when token endpoint returns non-ok', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'state123');
    sessionStorage.setItem('tripwire_oidc_verifier', 'my-verifier');

    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 400,
    });

    const params = new URLSearchParams({ code: 'auth-code', state: 'state123' });
    const result = await handleCallback(params);
    expect(result).toBe(false);
  });

  it('returns false when access_token is absent in response', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'state123');
    sessionStorage.setItem('tripwire_oidc_verifier', 'my-verifier');

    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token_type: 'Bearer' }),
    });

    const params = new URLSearchParams({ code: 'auth-code', state: 'state123' });
    const result = await handleCallback(params);
    expect(result).toBe(false);
  });

  it('cleans up sessionStorage after callback', async () => {
    sessionStorage.setItem('tripwire_oidc_state', 'state123');
    sessionStorage.setItem('tripwire_oidc_verifier', 'my-verifier');

    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ access_token: 'token' }),
    });

    await handleCallback(new URLSearchParams({ code: 'code', state: 'state123' }));

    expect(sessionStorage.getItem('tripwire_oidc_state')).toBeNull();
    expect(sessionStorage.getItem('tripwire_oidc_verifier')).toBeNull();
  });
});

describe('OIDC logout', () => {
  it('clears the stored token', () => {
    setToken('some-token');
    logout();
    expect(getToken()).toBeNull();
  });
});
