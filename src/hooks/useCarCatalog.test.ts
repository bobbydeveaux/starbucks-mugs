import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useCarCatalog } from './useCarCatalog';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrariEnvelope = {
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
      image: '/images/ferrari/250-gto.jpg',
      specs: { hp: 296, torqueLbFt: 210, zeroToSixtyMs: 6.1, topSpeedMph: 174, engineConfig: 'V12, 3.0L' },
      eraRivals: ['lamborghini-350-gt-1963'],
    },
    {
      id: 'ferrari-testarossa-1984',
      brand: 'ferrari',
      model: 'Testarossa',
      year: 1984,
      decade: 1980,
      image: '/images/ferrari/testarossa.jpg',
      specs: { hp: 390, torqueLbFt: 361, zeroToSixtyMs: 5.2, topSpeedMph: 180, engineConfig: 'Flat-12, 4.9L' },
      eraRivals: ['lamborghini-countach-lp500s-1982'],
    },
    {
      id: 'ferrari-enzo-2002',
      brand: 'ferrari',
      model: 'Enzo Ferrari',
      year: 2002,
      decade: 2000,
      image: '/images/ferrari/enzo.jpg',
      specs: { hp: 651, torqueLbFt: 485, zeroToSixtyMs: 3.3, topSpeedMph: 217, engineConfig: 'V12, 6.0L' },
      eraRivals: ['lamborghini-murcielago-2001'],
    },
  ],
};

const lamboEnvelope = {
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
      image: '/images/lamborghini/350-gt.jpg',
      specs: { hp: 270, torqueLbFt: 221, zeroToSixtyMs: 6.7, topSpeedMph: 152, engineConfig: 'V12, 3.5L' },
      eraRivals: ['ferrari-250-gto-1962'],
    },
    {
      id: 'lamborghini-countach-lp400-1974',
      brand: 'lamborghini',
      model: 'Countach LP400',
      year: 1974,
      decade: 1970,
      image: '/images/lamborghini/countach-lp400.jpg',
      specs: { hp: 375, torqueLbFt: 268, zeroToSixtyMs: 5.6, topSpeedMph: 179, engineConfig: 'V12, 4.0L' },
      eraRivals: ['ferrari-308-gt4-dino-1973'],
    },
    {
      id: 'lamborghini-murcielago-2001',
      brand: 'lamborghini',
      model: 'Murciélago',
      year: 2001,
      decade: 2000,
      image: '/images/lamborghini/murcielago.jpg',
      specs: { hp: 571, torqueLbFt: 457, zeroToSixtyMs: 3.8, topSpeedMph: 205, engineConfig: 'V12, 6.5L' },
      eraRivals: ['ferrari-enzo-2002'],
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(ferrariData = ferrariEnvelope, lamboData = lamboEnvelope) {
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
    // Always restore real timers so fake timers from one test don't bleed into the next
    vi.useRealTimers();
  });

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it('starts in loading state with empty car arrays', () => {
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

  it('fetches ferrari.json and lamborghini.json in parallel', async () => {
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
  // Data population
  // -------------------------------------------------------------------------

  it('populates filteredFerraris and filteredLambos after fetch', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
  });

  it('maps the raw image field to imageUrl on returned CarModel objects', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.filteredFerraris.forEach((car) => {
      expect(car).toHaveProperty('imageUrl');
      expect(typeof car.imageUrl).toBe('string');
      expect(car.imageUrl.length).toBeGreaterThan(0);
    });
  });

  it('sorts cars chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const ferrariYears = result.current.filteredFerraris.map((c) => c.year);
    for (let i = 1; i < ferrariYears.length; i++) {
      expect(ferrariYears[i]).toBeGreaterThanOrEqual(ferrariYears[i - 1]);
    }

    const lamboYears = result.current.filteredLambos.map((c) => c.year);
    for (let i = 1; i < lamboYears.length; i++) {
      expect(lamboYears[i]).toBeGreaterThanOrEqual(lamboYears[i - 1]);
    }
  });

  // -------------------------------------------------------------------------
  // Era filter
  // -------------------------------------------------------------------------

  it('starts with no era filter (era is undefined)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.era).toBeUndefined();
  });

  it('filters to the selected decade when era is set', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1980);
    });

    result.current.filteredFerraris.forEach((car) => {
      expect(car.decade).toBe(1980);
    });
    result.current.filteredLambos.forEach((car) => {
      expect(car.decade).toBe(1980);
    });
  });

  it('filters both brands to the same era simultaneously', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1960);
    });

    expect(result.current.filteredFerraris.length).toBeGreaterThan(0);
    expect(result.current.filteredLambos.length).toBeGreaterThan(0);

    result.current.filteredFerraris.forEach((car) => expect(car.decade).toBe(1960));
    result.current.filteredLambos.forEach((car) => expect(car.decade).toBe(1960));
  });

  it('returns empty arrays when era matches no cars', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1930); // no cars in fixture from 1930s
    });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('restores full catalog when era is cleared (set to undefined)', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1980);
    });
    act(() => {
      result.current.setEra(undefined);
    });

    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
  });

  // -------------------------------------------------------------------------
  // Search filter (with debounce — uses fake timers)
  //
  // Pattern: load data with real timers first, then switch to fake timers to
  // control debounce behaviour precisely.
  // -------------------------------------------------------------------------

  it('starts with empty search string', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.search).toBe('');
  });

  it('updates the search string immediately when setSearch is called', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setSearch('Enzo');
    });

    expect(result.current.search).toBe('Enzo');
  });

  it('does not filter before the 300 ms debounce elapses', async () => {
    const { result } = renderHook(() => useCarCatalog());
    // Wait for initial data to load with real timers
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Switch to fake timers — subsequent setTimeout calls will be controlled
    vi.useFakeTimers();

    act(() => {
      result.current.setSearch('Enzo');
    });

    // Advance time by just under the debounce threshold
    act(() => {
      vi.advanceTimersByTime(299);
    });

    // Filtering should not have been applied yet — full catalog still visible
    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
  });

  it('applies search filter after 300 ms debounce elapses', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    act(() => {
      result.current.setSearch('Enzo');
    });

    // Advance past the debounce threshold
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current.filteredFerraris.length).toBeGreaterThan(0);
    result.current.filteredFerraris.forEach((car) =>
      expect(car.model.toLowerCase()).toContain('enzo'),
    );
  });

  it('search is case-insensitive', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    act(() => { result.current.setSearch('ENZO'); });
    act(() => { vi.advanceTimersByTime(300); });
    const upperCount = result.current.filteredFerraris.length;

    act(() => { result.current.setSearch('enzo'); });
    act(() => { vi.advanceTimersByTime(300); });
    const lowerCount = result.current.filteredFerraris.length;

    expect(upperCount).toBe(lowerCount);
    expect(upperCount).toBeGreaterThan(0);
  });

  it('returns empty arrays when search matches no model names', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    act(() => { result.current.setSearch('zzznomatch999'); });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });

  it('trims whitespace from search query before filtering', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    act(() => { result.current.setSearch('  Enzo  '); });
    act(() => { vi.advanceTimersByTime(300); });
    const paddedCount = result.current.filteredFerraris.length;

    act(() => { result.current.setSearch('Enzo'); });
    act(() => { vi.advanceTimersByTime(300); });
    const cleanCount = result.current.filteredFerraris.length;

    expect(paddedCount).toBe(cleanCount);
  });

  // -------------------------------------------------------------------------
  // Combined era + search filters
  // -------------------------------------------------------------------------

  it('applies era and search filters simultaneously', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    act(() => {
      result.current.setEra(1960);
      result.current.setSearch('GT');
    });
    act(() => { vi.advanceTimersByTime(300); });

    result.current.filteredFerraris.forEach((car) => {
      expect(car.decade).toBe(1960);
      expect(car.model.toLowerCase()).toContain('gt');
    });
  });

  it('restores full catalog when both filters are cleared', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.useFakeTimers();

    // Apply filters
    act(() => {
      result.current.setEra(1980);
      result.current.setSearch('Testarossa');
    });
    act(() => { vi.advanceTimersByTime(300); });

    // Clear filters
    act(() => {
      result.current.setEra(undefined);
      result.current.setSearch('');
    });
    act(() => { vi.advanceTimersByTime(300); });

    expect(result.current.filteredFerraris).toHaveLength(ferrariEnvelope.cars.length);
    expect(result.current.filteredLambos).toHaveLength(lamboEnvelope.cars.length);
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
