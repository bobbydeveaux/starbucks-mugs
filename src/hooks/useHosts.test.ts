import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useHosts } from './useHosts';
import type { Host } from '../types';

const mockHosts: Host[] = [
  {
    host_id: 'host-1',
    hostname: 'server-alpha',
    ip_address: '10.0.0.1',
    platform: 'linux',
    agent_version: '1.2.3',
    last_seen: new Date().toISOString(),
    status: 'ONLINE',
  },
  {
    host_id: 'host-2',
    hostname: 'server-beta',
    ip_address: '10.0.0.2',
    platform: 'linux',
    agent_version: '1.2.3',
    last_seen: new Date(Date.now() - 300_000).toISOString(),
    status: 'DEGRADED',
  },
];

describe('useHosts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts in a loading state with an empty host list', () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => new Promise(() => {}), // never resolves
    } as Response);

    const { result } = renderHook(() => useHosts());

    expect(result.current.loading).toBe(true);
    expect(result.current.hosts).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('populates hosts on a successful fetch', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockHosts),
    } as Response);

    const { result } = renderHook(() => useHosts());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hosts).toEqual(mockHosts);
    expect(result.current.error).toBeNull();
  });

  it('sets error when the server returns a non-OK status', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 503,
    } as Response);

    const { result } = renderHook(() => useHosts());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/503/);
    expect(result.current.hosts).toEqual([]);
  });

  it('sets error when fetch throws a network error', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useHosts());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('Network error');
    expect(result.current.hosts).toEqual([]);
  });

  it('refetches when refetch() is called', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockHosts),
    } as Response);

    const { result } = renderHook(() => useHosts());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetch).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('calls fetch with /api/v1/hosts', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response);

    const { result } = renderHook(() => useHosts());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetch).toHaveBeenCalledWith('/api/v1/hosts', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it('clears a previous error on a successful refetch', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce({ ok: false, status: 500 } as Response)
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHosts) } as Response);

    const { result } = renderHook(() => useHosts());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBeNull();

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.hosts).toEqual(mockHosts);
  });
});
