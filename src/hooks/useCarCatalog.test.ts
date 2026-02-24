import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useCarCatalog } from './useCarCatalog';
import type { CarCatalogEnvelope } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrariEnvelope: CarCatalogEnvelope = {
  schema_version: '1.0',
  brand: 'ferrari',
  updated: '2026-02-24',
  cars: [
    {
      id: 'ferrari-testarossa-1984',
      brand: 'ferrari',
      model: 'Testarossa',
      year: 1984,
      decade: 1980,
      imageUrl: '/images/ferrari/testarossa.jpg',
      specs: {
        hp: 390,
        torqueLbFt: 362,
        zeroToSixtyMs: 5.8,
        topSpeedMph: 181,
        engineConfig: 'Flat-12, 4.9L',
      },
      eraRivals: [],
    },
    {
      id: 'ferrari-f40-1987',
      brand: 'ferrari',
      model: 'F40',
      year: 1987,
      decade: 1980,
      imageUrl: '/images/ferrari/f40.jpg',
      specs: {
        hp: 478,
        torqueLbFt: 424,
        zeroToSixtyMs: 3.8,
        topSpeedMph: 201,
        engineConfig: 'V8, 2.9L Twin-Turbo',
      },
      eraRivals: [],
    },
    {
      id: 'ferrari-250-gto-1962',
      brand: 'ferrari',
      model: '250 GTO',
      year: 1962,
      decade: 1960,
      imageUrl: '/images/ferrari/250-gto.jpg',
      specs: {
        hp: 302,
        torqueLbFt: 217,
        zeroToSixtyMs: 6.1,
        topSpeedMph: 174,
        engineConfig: 'V12, 3.0L',
      },
      eraRivals: [],
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(data: unknown = ferrariEnvelope) {
  return vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(data) });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useCarCatalog', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it('starts in loading state', () => {
    const { result } = renderHook(() => useCarCatalog('ferrari'));
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.cars).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Fetch behavior
  // -------------------------------------------------------------------------

  it('fetches from the correct brand URL', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledWith('/data/ferrari.json', expect.any(Object));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('fetches lamborghini URL when brand is lamborghini', async () => {
    const lamboEnvelope = { ...ferrariEnvelope, brand: 'lamborghini', cars: [] };
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve(lamboEnvelope) });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useCarCatalog('lamborghini'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledWith('/data/lamborghini.json', expect.any(Object));
  });

  it('returns all cars when no filters are applied', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.cars).toHaveLength(ferrariEnvelope.cars.length);
  });

  // -------------------------------------------------------------------------
  // Decade filter
  // -------------------------------------------------------------------------

  it('filters cars by decade', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.cars.forEach((c) => expect(c.decade).toBe(1980));
    expect(result.current.cars).toHaveLength(2);
  });

  it('returns empty array when no cars match the decade', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { decade: 2050 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.cars).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // Search filter
  // -------------------------------------------------------------------------

  it('filters cars by search query (case-insensitive)', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { search: 'testarossa' }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.cars).toHaveLength(1);
    expect(result.current.cars[0].model).toBe('Testarossa');
  });

  it('search is case-insensitive', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { search: 'TESTAROSSA' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.cars).toHaveLength(1);
  });

  it('returns empty list when query matches no cars', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { search: 'zzznomatch999' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.cars).toHaveLength(0);
  });

  it('applies decade and search filters simultaneously', async () => {
    const { result } = renderHook(() =>
      useCarCatalog('ferrari', { decade: 1980, search: 'f40' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.cars.forEach((c) => {
      expect(c.decade).toBe(1980);
      expect(c.model.toLowerCase()).toContain('f40');
    });
  });

  it('trims whitespace from the search query', async () => {
    const { result: padded } = renderHook(() =>
      useCarCatalog('ferrari', { search: '  Testarossa  ' }),
    );
    const { result: clean } = renderHook(() =>
      useCarCatalog('ferrari', { search: 'Testarossa' }),
    );
    await waitFor(() => expect(padded.current.loading).toBe(false));
    await waitFor(() => expect(clean.current.loading).toBe(false));

    expect(padded.current.cars.length).toBe(clean.current.cars.length);
  });

  // -------------------------------------------------------------------------
  // Decades list
  // -------------------------------------------------------------------------

  it('returns sorted unique decades from the full catalog', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.decades).toEqual([1960, 1980]);
  });

  it('decades list is unaffected by active filters', async () => {
    const { result } = renderHook(() => useCarCatalog('ferrari', { decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Even with decade filter active, decades includes all decades from raw data
    expect(result.current.decades).toEqual([1960, 1980]);
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error state when fetch returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({}) }),
    );

    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/ferrari\.json/);
    expect(result.current.cars).toHaveLength(0);
  });

  it('sets error state when fetch rejects (network error)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.cars).toHaveLength(0);
  });

  it('does not throw — returns stable error state instead', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const { result } = renderHook(() => useCarCatalog('ferrari'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).not.toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.cars).toEqual([]);
  });
});
