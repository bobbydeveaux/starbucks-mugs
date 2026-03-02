import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useTemperatures } from './useTemperatures';
import type { Country } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockCountries: Country[] = [
  {
    country: 'Spain',
    code: 'ES',
    avgTemps: {
      jan: 10, feb: 11, mar: 13, apr: 15, may: 19, jun: 24,
      jul: 27, aug: 27, sep: 23, oct: 18, nov: 13, dec: 10,
    },
  },
  {
    country: 'Norway',
    code: 'NO',
    avgTemps: {
      jan: -4, feb: -4, mar: 0, apr: 5, may: 11, jun: 15,
      jul: 17, aug: 16, sep: 12, oct: 7, nov: 2, dec: -2,
    },
  },
  {
    country: 'Thailand',
    code: 'TH',
    avgTemps: {
      jan: 26, feb: 28, mar: 29, apr: 30, may: 29, jun: 29,
      jul: 28, aug: 28, sep: 27, oct: 27, nov: 27, dec: 26,
    },
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(data: unknown = mockCountries) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

function mockFetchNetworkError(message = 'Network error') {
  return vi.fn().mockRejectedValue(new Error(message));
}

function mockFetchHttpError(status: number) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve({}),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useTemperatures', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetchSuccess());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it('starts in loading state', () => {
    const { result } = renderHook(() => useTemperatures());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.countries).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Successful fetch
  // -------------------------------------------------------------------------

  it('returns parsed Country[] on successful fetch', async () => {
    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.countries).toHaveLength(mockCountries.length);
    expect(result.current.error).toBeNull();
  });

  it('populates countries with the correct data', async () => {
    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.countries[0]).toMatchObject({
      country: 'Spain',
      code: 'ES',
    });
    expect(result.current.countries[0].avgTemps.jan).toBe(10);
  });

  it('fetches /temperatures.json exactly once on mount', async () => {
    const fetchMock = mockFetchSuccess();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      '/temperatures.json',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('does not re-fetch on re-render', async () => {
    const fetchMock = mockFetchSuccess();
    vi.stubGlobal('fetch', fetchMock);

    const { result, rerender } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender();
    rerender();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error and clears loading when fetch fails with network error', async () => {
    vi.stubGlobal('fetch', mockFetchNetworkError('Network error'));

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.error).toContain('Network error');
    expect(result.current.countries).toHaveLength(0);
  });

  it('sets error when temperatures.json returns a non-ok HTTP response', async () => {
    vi.stubGlobal('fetch', mockFetchHttpError(404));

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/temperatures\.json/);
    expect(result.current.countries).toHaveLength(0);
  });

  it('sets error when temperatures.json returns a 500 response', async () => {
    vi.stubGlobal('fetch', mockFetchHttpError(500));

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/500/);
    expect(result.current.countries).toHaveLength(0);
  });

  it('does not throw — error is returned in state, not propagated', async () => {
    vi.stubGlobal('fetch', mockFetchNetworkError('Network error'));

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Hook is in a stable error state — no exception escapes
    expect(result.current.error).not.toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.countries).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Empty data
  // -------------------------------------------------------------------------

  it('handles an empty countries array from the server', async () => {
    vi.stubGlobal('fetch', mockFetchSuccess([]));

    const { result } = renderHook(() => useTemperatures());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.countries).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });
});
