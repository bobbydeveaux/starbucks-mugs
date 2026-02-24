import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useCarCatalog } from './useCarCatalog';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FERRARI_CARS = [
  {
    id: 'ferrari-testarossa-1984',
    brand: 'ferrari',
    model: 'Testarossa',
    year: 1984,
    decade: 1980,
    image: '/images/ferrari/testarossa.jpg',
    specs: { hp: 390, torqueLbFt: 362, zeroToSixtyMs: 5.2, topSpeedMph: 181, engineConfig: 'Flat-12, 4.9L' },
    eraRivals: ['lamborghini-countach-lp500s-1982'],
  },
  {
    id: 'ferrari-250-gto-1962',
    brand: 'ferrari',
    model: '250 GTO',
    year: 1962,
    decade: 1960,
    image: '/images/ferrari/250-gto.jpg',
    specs: { hp: 296, torqueLbFt: 210, zeroToSixtyMs: 6.1, topSpeedMph: 174, engineConfig: 'V12, 3.0L' },
    eraRivals: ['lamborghini-350-gt-1963'],
  },
];

const LAMBO_CARS = [
  {
    id: 'lamborghini-countach-lp500s-1982',
    brand: 'lamborghini',
    model: 'Countach LP500S',
    year: 1982,
    decade: 1980,
    image: '/images/lamborghini/countach-lp500s.jpg',
    specs: { hp: 375, torqueLbFt: 268, zeroToSixtyMs: 4.9, topSpeedMph: 183, engineConfig: 'V12, 4.8L' },
    eraRivals: ['ferrari-testarossa-1984'],
  },
  {
    id: 'lamborghini-350-gt-1963',
    brand: 'lamborghini',
    model: '350 GT',
    year: 1963,
    decade: 1960,
    image: '/images/lamborghini/350-gt.jpg',
    specs: { hp: 270, torqueLbFt: 221, zeroToSixtyMs: 6.7, topSpeedMph: 152, engineConfig: 'V12, 3.5L' },
    eraRivals: ['ferrari-250-gto-1962'],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(ferrariCars = FERRARI_CARS, lamboCars = LAMBO_CARS) {
  return vi.fn().mockImplementation((url: string) => {
    if (url.includes('ferrari')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ schema_version: '1.0', brand: 'ferrari', updated: '2026-01-01', cars: ferrariCars }),
      });
    }
    if (url.includes('lamborghini')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ schema_version: '1.0', brand: 'lamborghini', updated: '2026-01-01', cars: lamboCars }),
      });
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
  });

  it('starts with empty car arrays', () => {
    const { result } = renderHook(() => useCarCatalog());
    expect(result.current.ferrariCars).toEqual([]);
    expect(result.current.lamboCars).toEqual([]);
  });

  it('starts with null error', () => {
    const { result } = renderHook(() => useCarCatalog());
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Successful fetch
  // -------------------------------------------------------------------------

  it('sets loading to false after fetch completes', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it('populates ferrariCars after fetch', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars).toHaveLength(2);
  });

  it('populates lamboCars after fetch', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.lamboCars).toHaveLength(2);
  });

  it('maps JSON image field to imageUrl on CarModel', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars[0].imageUrl).toBe(FERRARI_CARS[1].image); // sorted by year, 250 GTO (1962) first
  });

  it('sorts ferrariCars chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const years = result.current.ferrariCars.map((c) => c.year);
    expect(years).toEqual([...years].sort((a, b) => a - b));
  });

  it('sorts lamboCars chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const years = result.current.lamboCars.map((c) => c.year);
    expect(years).toEqual([...years].sort((a, b) => a - b));
  });

  // -------------------------------------------------------------------------
  // Filtering by decade
  // -------------------------------------------------------------------------

  it('filters ferrariCars by decade when provided', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1980 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars).toHaveLength(1);
    expect(result.current.ferrariCars[0].model).toBe('Testarossa');
  });

  it('filters lamboCars by decade when provided', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 1960 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.lamboCars).toHaveLength(1);
    expect(result.current.lamboCars[0].model).toBe('350 GT');
  });

  it('returns empty arrays when no cars match the decade filter', async () => {
    const { result } = renderHook(() => useCarCatalog({ decade: 2020 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars).toHaveLength(0);
    expect(result.current.lamboCars).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // Filtering by search
  // -------------------------------------------------------------------------

  it('filters ferrariCars by search query (case-insensitive)', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: 'testa' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars).toHaveLength(1);
    expect(result.current.ferrariCars[0].model).toBe('Testarossa');
  });

  it('filters lamboCars by search query', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: 'countach' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.lamboCars).toHaveLength(1);
    expect(result.current.lamboCars[0].model).toBe('Countach LP500S');
  });

  it('returns all cars when search is an empty string', async () => {
    const { result } = renderHook(() => useCarCatalog({ search: '' }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.ferrariCars).toHaveLength(2);
    expect(result.current.lamboCars).toHaveLength(2);
  });

  // -------------------------------------------------------------------------
  // Error state
  // -------------------------------------------------------------------------

  it('sets error when ferrari fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.includes('ferrari')) {
        return Promise.resolve({ ok: false, status: 500 });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ schema_version: '1.0', brand: 'lamborghini', updated: '2026-01-01', cars: LAMBO_CARS }),
      });
    }));
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBeNull();
  });

  it('sets error when lamborghini fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url.includes('lamborghini')) {
        return Promise.resolve({ ok: false, status: 404 });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ schema_version: '1.0', brand: 'ferrari', updated: '2026-01-01', cars: FERRARI_CARS }),
      });
    }));
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBeNull();
  });
});
