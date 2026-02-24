import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
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
      id: 'ferrari-250-gto-1962',
      brand: 'ferrari',
      model: '250 GTO',
      year: 1962,
      decade: 1960,
      imageUrl: '/images/ferrari/250-gto.jpg',
      specs: {
        hp: 296,
        torqueLbFt: 210,
        zeroToSixtyMs: 6.1,
        topSpeedMph: 174,
        engineConfig: 'V12, 3.0L',
      },
      eraRivals: ['lamborghini-350-gt-1963'],
    },
    {
      id: 'ferrari-testarossa-1984',
      brand: 'ferrari',
      model: 'Testarossa',
      year: 1984,
      decade: 1980,
      imageUrl: '/images/ferrari/testarossa.jpg',
      specs: {
        hp: 390,
        torqueLbFt: 361,
        zeroToSixtyMs: 5.8,
        topSpeedMph: 181,
        engineConfig: 'Flat-12, 4.9L',
      },
      eraRivals: ['lamborghini-countach-lp500-1982'],
    },
    {
      id: 'ferrari-enzo-2002',
      brand: 'ferrari',
      model: 'Enzo',
      year: 2002,
      decade: 2000,
      imageUrl: '/images/ferrari/enzo.jpg',
      specs: {
        hp: 651,
        torqueLbFt: 485,
        zeroToSixtyMs: 3.65,
        topSpeedMph: 217,
        engineConfig: 'V12, 6.0L',
      },
      eraRivals: ['lamborghini-murcielago-2001'],
    },
  ],
};

const lamboEnvelope: CarCatalogEnvelope = {
  schema_version: '1.0',
  brand: 'lamborghini',
  updated: '2026-02-24',
  cars: [
    {
      id: 'lamborghini-350-gt-1963',
      brand: 'lamborghini',
      model: '350 GT',
      year: 1963,
      decade: 1960,
      imageUrl: '/images/lamborghini/350-gt.jpg',
      specs: {
        hp: 270,
        torqueLbFt: 221,
        zeroToSixtyMs: 6.7,
        topSpeedMph: 152,
        engineConfig: 'V12, 3.5L',
      },
      eraRivals: ['ferrari-250-gto-1962'],
    },
    {
      id: 'lamborghini-countach-lp500-1982',
      brand: 'lamborghini',
      model: 'Countach LP500',
      year: 1982,
      decade: 1980,
      imageUrl: '/images/lamborghini/countach.jpg',
      specs: {
        hp: 375,
        torqueLbFt: 268,
        zeroToSixtyMs: 5.6,
        topSpeedMph: 183,
        engineConfig: 'V12, 5.0L',
      },
      eraRivals: ['ferrari-testarossa-1984'],
    },
    {
      id: 'lamborghini-murcielago-2001',
      brand: 'lamborghini',
      model: 'Murciélago',
      year: 2001,
      decade: 2000,
      imageUrl: '/images/lamborghini/murcielago.jpg',
      specs: {
        hp: 572,
        torqueLbFt: 479,
        zeroToSixtyMs: 3.8,
        topSpeedMph: 205,
        engineConfig: 'V12, 6.5L',
      },
      eraRivals: ['ferrari-enzo-2002'],
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(
  ferrariData: unknown = ferrariEnvelope,
  lamboData: unknown = lamboEnvelope,
) {
  return vi.fn().mockImplementation((url: string) => {
    if (url.includes('ferrari')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ferrariData) });
    }
    if (url.includes('lamborghini')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(lamboData) });
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

// ---------------------------------------------------------------------------
// Tests — use real timers unless specifically testing debounce
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
    const { result } = renderHook(() => useCarCatalog());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.filteredFerraris).toEqual([]);
    expect(result.current.filteredLambos).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Parallel fetch
  // -------------------------------------------------------------------------

  it('fetches both JSON files in parallel', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const urls = fetchMock.mock.calls.map((call: [string]) => call[0]);
    expect(urls).toContain('/data/ferrari.json');
    expect(urls).toContain('/data/lamborghini.json');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // -------------------------------------------------------------------------
  // Data loading and sorting
  // -------------------------------------------------------------------------

  it('loads and exposes ferrari and lambo cars after fetch', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
  });

  it('sorts cars chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const ferrariYears = result.current.filteredFerraris.map((c) => c.year);
    expect(ferrariYears).toEqual([...ferrariYears].sort((a, b) => a - b));

    const lamboYears = result.current.filteredLambos.map((c) => c.year);
    expect(lamboYears).toEqual([...lamboYears].sort((a, b) => a - b));
  });

  it('derives availableDecades from both catalogs without duplicates', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.availableDecades).toEqual([1960, 1980, 2000]);
    const uniqueDecades = [...new Set(result.current.availableDecades)];
    expect(result.current.availableDecades).toEqual(uniqueDecades);
  });

  // -------------------------------------------------------------------------
  // Era (decade) filtering
  // -------------------------------------------------------------------------

  it('returns all cars when era is null', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.era).toBeNull();
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
  });

  it('filters both catalogs by the selected era decade', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1980);
    });

    expect(result.current.era).toBe(1980);
    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('Testarossa');
    expect(result.current.filteredLambos).toHaveLength(1);
    expect(result.current.filteredLambos[0].model).toBe('Countach LP500');
  });

  it('returns empty arrays when no cars match the selected era', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1940);
    });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('restores full catalog when era is cleared back to null', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1980); });
    expect(result.current.filteredFerraris).toHaveLength(1);

    act(() => { result.current.setEra(null); });
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
  });

  // -------------------------------------------------------------------------
  // Search filtering (real-timer tests — verify end state after full debounce)
  // -------------------------------------------------------------------------

  it('starts with an empty search query', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.search).toBe('');
  });

  it('applies search filter once debounce settles', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('Enzo'); });

    // waitFor polls until the debounced filter resolves (real timers: ≤ 300 ms)
    await waitFor(() => {
      expect(result.current.filteredFerraris).toHaveLength(1);
    });
    expect(result.current.filteredFerraris[0].model).toBe('Enzo');
  });

  it('search filtering is case-insensitive', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('ENZO'); });

    await waitFor(() => {
      expect(result.current.filteredFerraris).toHaveLength(1);
    });
  });

  it('returns empty arrays when search matches no cars', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('zzznomatch999'); });

    await waitFor(() => {
      expect(result.current.filteredFerraris).toHaveLength(0);
      expect(result.current.filteredLambos).toHaveLength(0);
    });
  });

  it('restores full catalog when search is cleared', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('Enzo'); });
    await waitFor(() => expect(result.current.filteredFerraris).toHaveLength(1));

    act(() => { result.current.setSearch(''); });
    await waitFor(() =>
      expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length),
    );
  });

  // -------------------------------------------------------------------------
  // Debounce timing — switch to fake timers after data is loaded
  // -------------------------------------------------------------------------

  it('does not filter before 300 ms debounce elapses', async () => {
    const { result } = renderHook(() => useCarCatalog());
    // Load data with real timers
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Switch to fake timers now that async loading is complete
    vi.useFakeTimers();
    try {
      act(() => { result.current.setSearch('Enzo'); });
      // Advance by less than 300 ms — filter should NOT have applied yet
      act(() => { vi.advanceTimersByTime(100); });
      expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    } finally {
      vi.useRealTimers();
    }
  });

  it('applies search filter exactly at 300 ms debounce boundary', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();
    try {
      act(() => { result.current.setSearch('Enzo'); });
      act(() => { vi.advanceTimersByTime(300); });
      expect(result.current.filteredFerraris).toHaveLength(1);
      expect(result.current.filteredFerraris[0].model).toBe('Enzo');
    } finally {
      vi.useRealTimers();
    }
  });

  // -------------------------------------------------------------------------
  // Combined era + search filtering
  // -------------------------------------------------------------------------

  it('applies era and search filters simultaneously', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1960); });
    act(() => { result.current.setSearch('250'); });

    // Wait for debounce to settle — era filter gives 1 Ferrari + 1 Lambo from the
    // 1960s immediately; after debounce, search "250" keeps only the 250 GTO and
    // eliminates the 350 GT (no "250" in its name).
    await waitFor(() => {
      expect(result.current.filteredLambos).toHaveLength(0);
    });
    // Only the 250 GTO (1962, decade 1960) should remain
    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('250 GTO');
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error state and clears loading when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('sets error when ferrari.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('ferrari')) {
          return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(lamboEnvelope) });
      }),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/ferrari\.json/);
  });

  it('sets error when lamborghini.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('lamborghini')) {
          return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ferrariEnvelope) });
      }),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/lamborghini\.json/);
  });
});
