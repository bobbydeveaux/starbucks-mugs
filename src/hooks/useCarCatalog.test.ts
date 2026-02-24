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
      price: 87000,
      specs: {
        hp: 390,
        torqueLbFt: 362,
        zeroToSixtyMs: 5.2,
        topSpeedMph: 181,
        engineConfig: 'Flat-12, 4.9L',
      },
      eraRivals: ['lambo-countach-lp500s-1982'],
    },
    {
      id: 'ferrari-f40-1987',
      brand: 'ferrari',
      model: 'F40',
      year: 1987,
      decade: 1980,
      imageUrl: '/images/ferrari/f40.jpg',
      price: 400000,
      specs: {
        hp: 478,
        torqueLbFt: 424,
        zeroToSixtyMs: 3.8,
        topSpeedMph: 201,
        engineConfig: 'V8 Twin-Turbo, 3.0L',
      },
      eraRivals: ['lambo-countach-25th-1988'],
    },
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
      price: 100000,
      specs: {
        hp: 375,
        torqueLbFt: 268,
        zeroToSixtyMs: 4.9,
        topSpeedMph: 183,
        engineConfig: 'V12, 4.8L',
      },
      eraRivals: ['ferrari-testarossa-1984'],
    },
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
      id: 'lamborghini-diablo-1990',
      brand: 'lamborghini',
      model: 'Diablo',
      year: 1990,
      decade: 1990,
      imageUrl: '/images/lamborghini/diablo.jpg',
      specs: {
        hp: 492,
        torqueLbFt: 428,
        zeroToSixtyMs: 4.1,
        topSpeedMph: 202,
        engineConfig: 'V12, 5.7L',
      },
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
    expect(result.current.ferrariCars).toEqual([]);
    expect(result.current.lamboCars).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Parallel fetch and data
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

  it('returns ferrari cars separately from lambo cars', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.lamboCars).toHaveLength(lamboEnvelope.cars.length);

    result.current.ferrariCars.forEach((car) => expect(car.brand).toBe('ferrari'));
    result.current.lamboCars.forEach((car) => expect(car.brand).toBe('lamborghini'));
  });

  // -------------------------------------------------------------------------
  // Chronological sorting
  // -------------------------------------------------------------------------

  it('sorts ferrari cars chronologically by year (ascending)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const years = result.current.ferrariCars.map((car) => car.year);
    const sorted = [...years].sort((a, b) => a - b);
    expect(years).toEqual(sorted);
  });

  it('sorts lambo cars chronologically by year (ascending)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const years = result.current.lamboCars.map((car) => car.year);
    const sorted = [...years].sort((a, b) => a - b);
    expect(years).toEqual(sorted);
  });

  // -------------------------------------------------------------------------
  // Decade filter
  // -------------------------------------------------------------------------

  it('returns all cars when no decade filter is set', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.lamboCars).toHaveLength(lamboEnvelope.cars.length);
  });

  it('filters ferrari cars by decade', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.ferrariCars.forEach((car) => expect(car.decade).toBe(1980));

    const expected1980s = ferrariEnvelope.cars.filter((c) => c.decade === 1980).length;
    expect(result.current.ferrariCars).toHaveLength(expected1980s);
  });

  it('filters lambo cars by decade', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.lamboCars.forEach((car) => expect(car.decade).toBe(1980));

    const expected1980s = lamboEnvelope.cars.filter((c) => c.decade === 1980).length;
    expect(result.current.lamboCars).toHaveLength(expected1980s);
  });

  it('returns empty arrays when no cars match the decade', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 2050 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(0);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // Search filter
  // -------------------------------------------------------------------------

  it('filters cars by model name search (case-insensitive)', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: 'testarossa' }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars.length).toBeGreaterThan(0);
    result.current.ferrariCars.forEach((car) =>
      expect(car.model.toLowerCase()).toContain('testarossa'),
    );
  });

  it('search is case-insensitive', async () => {
    const { result: lower } = renderHook(() => useCarCatalog({ search: 'testarossa' }));
    const { result: upper } = renderHook(() => useCarCatalog({ search: 'TESTAROSSA' }));

    await waitFor(() => expect(lower.current.loading).toBe(false));
    await waitFor(() => expect(upper.current.loading).toBe(false));

    expect(lower.current.ferrariCars.length).toBe(upper.current.ferrariCars.length);
  });

  it('returns empty list when search matches no cars', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: 'zzznomatch999' }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(0);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  it('trims whitespace from search query', async () => {
    const { result: padded } = renderHook(() => useCarCatalog({ search: '  F40  ' }));
    const { result: clean } = renderHook(() => useCarCatalog({ search: 'F40' }));

    await waitFor(() => expect(padded.current.loading).toBe(false));
    await waitFor(() => expect(clean.current.loading).toBe(false));

    expect(padded.current.ferrariCars.length).toBe(clean.current.ferrariCars.length);
  });

  // -------------------------------------------------------------------------
  // Combined decade + search filter
  // -------------------------------------------------------------------------

  it('applies decade and search filters simultaneously', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1980, search: 'Testarossa' }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.ferrariCars.forEach((car) => {
      expect(car.decade).toBe(1980);
      expect(car.model.toLowerCase()).toContain('testarossa');
    });
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error state and clears loading when fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.ferrariCars).toHaveLength(0);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  it('sets error when ferrari.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('ferrari')) {
          return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(lamboEnvelope),
        });
      }),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/ferrari\.json/);
    expect(result.current.ferrariCars).toHaveLength(0);
  });

  it('sets error when lamborghini.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('lamborghini')) {
          return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(ferrariEnvelope),
        });
      }),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/lamborghini\.json/);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  it('does not crash the app on fetch failure (error returned, not thrown)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    );

    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).not.toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.ferrariCars).toEqual([]);
    expect(result.current.lamboCars).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Default parameter
  // -------------------------------------------------------------------------

  it('works with no arguments (empty filters)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.ferrariCars).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.lamboCars).toHaveLength(lamboEnvelope.cars.length);
  });
});
