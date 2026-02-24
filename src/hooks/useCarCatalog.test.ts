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
      id: 'ferrari-testarossa-1984',
      brand: 'ferrari',
      model: 'Testarossa',
      year: 1984,
      decade: 1980,
      imageUrl: '/images/ferrari/testarossa.jpg',
      specs: { hp: 385, torqueLbFt: 361, zeroToSixtyMs: 5.8, topSpeedMph: 181, engineConfig: 'Flat-12, 4.9L' },
      eraRivals: ['lamborghini-countach-lp500s-1982'],
    },
    {
      id: 'ferrari-f40-1987',
      brand: 'ferrari',
      model: 'F40',
      year: 1987,
      decade: 1980,
      imageUrl: '/images/ferrari/f40.jpg',
      specs: { hp: 478, torqueLbFt: 424, zeroToSixtyMs: 3.8, topSpeedMph: 201, engineConfig: 'Twin-Turbo V8, 2.9L' },
      eraRivals: [],
    },
    {
      id: 'ferrari-308-gtb-1975',
      brand: 'ferrari',
      model: '308 GTB',
      year: 1975,
      decade: 1970,
      imageUrl: '/images/ferrari/308-gtb.jpg',
      specs: { hp: 255, torqueLbFt: 209, zeroToSixtyMs: 6.5, topSpeedMph: 155, engineConfig: 'V8, 3.0L' },
      eraRivals: [],
    },
  ],
};

const lamboEnvelope: CarCatalogEnvelope = {
  schema_version: '1.0',
  brand: 'lamborghini',
  updated: '2026-02-24',
  cars: [
    {
      id: 'lamborghini-countach-lp500s-1982',
      brand: 'lamborghini',
      model: 'Countach LP500S',
      year: 1982,
      decade: 1980,
      imageUrl: '/images/lamborghini/countach-lp500s.jpg',
      specs: { hp: 375, torqueLbFt: 268, zeroToSixtyMs: 5.6, topSpeedMph: 182, engineConfig: 'V12, 4.8L' },
      eraRivals: [],
    },
    {
      id: 'lamborghini-jalpa-1981',
      brand: 'lamborghini',
      model: 'Jalpa',
      year: 1981,
      decade: 1980,
      imageUrl: '/images/lamborghini/jalpa.jpg',
      specs: { hp: 255, torqueLbFt: 225, zeroToSixtyMs: 6.8, topSpeedMph: 155, engineConfig: 'V8, 3.5L' },
      eraRivals: [],
    },
    {
      id: 'lamborghini-urraco-1970',
      brand: 'lamborghini',
      model: 'Urraco',
      year: 1970,
      decade: 1970,
      imageUrl: '/images/lamborghini/urraco.jpg',
      specs: { hp: 220, torqueLbFt: 181, zeroToSixtyMs: 7.5, topSpeedMph: 150, engineConfig: 'V8, 2.5L' },
      eraRivals: [],
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
// Tests
// ---------------------------------------------------------------------------

describe('useCarCatalog', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal('fetch', mockFetch());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it('starts in loading state with empty arrays', () => {
    const { result } = renderHook(() => useCarCatalog());
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.ferrariCars).toEqual([]);
    expect(result.current.lamboCars).toEqual([]);
    expect(result.current.filteredFerraris).toEqual([]);
    expect(result.current.filteredLambos).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Parallel fetch and data integrity
  // -------------------------------------------------------------------------

  it('fetches both JSON files in parallel via Promise.all', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const urls = fetchMock.mock.calls.map((call: [string]) => call[0]);
    expect(urls).toContain('/data/ferrari.json');
    expect(urls).toContain('/data/lamborghini.json');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('populates ferrariCars and lamboCars with unfiltered data', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.lamboCars).toHaveLength(lamboEnvelope.cars.length);
  });

  it('sorts cars chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const ferrariYears = result.current.ferrariCars.map((c) => c.year);
    const lamboYears = result.current.lamboCars.map((c) => c.year);

    expect(ferrariYears).toEqual([...ferrariYears].sort((a, b) => a - b));
    expect(lamboYears).toEqual([...lamboYears].sort((a, b) => a - b));
  });

  // -------------------------------------------------------------------------
  // Era (decade) filtering
  // -------------------------------------------------------------------------

  it('returns all cars when no era filter is set', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
  });

  it('filters to only the selected decade when setEra is called', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1980); });

    // ferrariEnvelope has 2 cars in decade=1980, lamboEnvelope has 2
    expect(result.current.filteredFerraris.every((c) => c.decade === 1980)).toBe(true);
    expect(result.current.filteredFerraris).toHaveLength(2);
    expect(result.current.filteredLambos.every((c) => c.decade === 1980)).toBe(true);
    expect(result.current.filteredLambos).toHaveLength(2);
  });

  it('filters to a different decade correctly', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1970); });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].id).toBe('ferrari-308-gtb-1975');
    expect(result.current.filteredLambos).toHaveLength(1);
    expect(result.current.filteredLambos[0].id).toBe('lamborghini-urraco-1970');
  });

  it('returns empty arrays when no cars match the selected decade', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(2000); });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('restores all cars when era is cleared (set to undefined)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1980); });
    expect(result.current.filteredFerraris).toHaveLength(2);

    act(() => { result.current.setEra(undefined); });
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
  });

  // -------------------------------------------------------------------------
  // Debounced search filtering
  // -------------------------------------------------------------------------

  it('exposes the raw search value immediately via search field', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('Testa'); });
    expect(result.current.search).toBe('Testa');
  });

  it('does NOT apply search filter immediately (debounce pending)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('Testarossa'); });

    // Filter should still show all cars before 300 ms elapses
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
  });

  it('applies search filter after 300 ms debounce', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('Testarossa'); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('Testarossa');
  });

  it('resets the 300 ms timer when user keeps typing', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('T'); });
    act(() => { vi.advanceTimersByTime(200); });
    act(() => { result.current.setSearch('Te'); });
    act(() => { vi.advanceTimersByTime(200); });

    // Only 200 ms have passed since the last keystroke — filter not applied yet.
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);

    act(() => { vi.advanceTimersByTime(100); });

    // Now 300 ms since last keystroke — filter applied.
    expect(result.current.filteredFerraris.every((c) =>
      c.model.toLowerCase().includes('te'),
    )).toBe(true);
  });

  it('search is case-insensitive', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('TESTAROSSA'); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('Testarossa');
  });

  it('trims whitespace from the search query', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('  F40  '); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('F40');
  });

  it('returns empty arrays when query matches no models', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('zzznomatch999'); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('clears search filter when query is set to empty string', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setSearch('F40'); });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current.filteredFerraris).toHaveLength(1);

    act(() => { result.current.setSearch(''); });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
  });

  // -------------------------------------------------------------------------
  // Combined era + search filtering
  // -------------------------------------------------------------------------

  it('applies era and search filters simultaneously', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1980); });
    act(() => { result.current.setSearch('F40'); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('F40');
    expect(result.current.filteredFerraris[0].decade).toBe(1980);
  });

  it('restores full era results when search is cleared', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => { result.current.setEra(1980); });
    act(() => { result.current.setSearch('F40'); });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current.filteredFerraris).toHaveLength(1);

    act(() => { result.current.setSearch(''); });
    act(() => { vi.advanceTimersByTime(300); });
    // Now era=1980 only, so 2 ferraris
    expect(result.current.filteredFerraris).toHaveLength(2);
  });

  // -------------------------------------------------------------------------
  // initialFilters support
  // -------------------------------------------------------------------------

  it('respects initial decade filter', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.era).toBe(1980);
    expect(result.current.filteredFerraris.every((c) => c.decade === 1980)).toBe(true);
  });

  it('respects initial search filter after debounce', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: 'Testarossa' }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Initial search is applied without waiting for a keystroke debounce
    act(() => { vi.advanceTimersByTime(0); });
    expect(result.current.search).toBe('Testarossa');
    expect(result.current.filteredFerraris.every((c) =>
      c.model.toLowerCase().includes('testarossa'),
    )).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error state and clears loading when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.ferrariCars).toHaveLength(0);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  it('sets error when ferrari.json returns a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.includes('ferrari')) {
        return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(lamboEnvelope) });
    }));

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/ferrari\.json/);
  });

  it('sets error when lamborghini.json returns a non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.includes('lamborghini')) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ferrariEnvelope) });
    }));

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/lamborghini\.json/);
  });

  it('does not crash on fetch failure (error returned, not thrown)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).not.toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.ferrariCars).toEqual([]);
  });
});
