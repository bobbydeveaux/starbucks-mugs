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
      eraRivals: [],
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
        topSpeedMph: 180,
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
        zeroToSixtyMs: 4.1,
        topSpeedMph: 201,
        engineConfig: 'V8 Twin-Turbo, 2.9L',
      },
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
      eraRivals: [],
    },
    {
      id: 'lamborghini-countach-1974',
      brand: 'lamborghini',
      model: 'Countach',
      year: 1974,
      decade: 1970,
      imageUrl: '/images/lamborghini/countach.jpg',
      specs: {
        hp: 375,
        torqueLbFt: 268,
        zeroToSixtyMs: 5.6,
        topSpeedMph: 179,
        engineConfig: 'V12, 3.9L',
      },
      eraRivals: [],
    },
  ],
};

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

function mockFetch(
  ferrariData: CarCatalogEnvelope = ferrariEnvelope,
  lamboData: CarCatalogEnvelope = lamboEnvelope,
) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: unknown) => {
      const urlStr = String(url);
      const data = urlStr.includes('ferrari') ? ferrariData : lamboData;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(data),
      } as Response);
    }),
  );
}

beforeEach(() => {
  mockFetch();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Data loading tests (real timers — waitFor works correctly)
// ---------------------------------------------------------------------------

describe('useCarCatalog — data loading', () => {
  it('starts in loading state', () => {
    const { result } = renderHook(() => useCarCatalog());
    expect(result.current.loading).toBe(true);
  });

  it('resolves loading and populates car arrays', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.filteredFerraris).toHaveLength(3);
    expect(result.current.filteredLambos).toHaveLength(2);
  });

  it('sorts Ferraris chronologically by year', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const years = result.current.filteredFerraris.map((c) => c.year);
    expect(years).toEqual([...years].sort((a, b) => a - b));
  });

  it('sets error on fetch failure', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('Network error'))));
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.error).toMatch(/network error/i));
    expect(result.current.loading).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Era filter tests (real timers)
// ---------------------------------------------------------------------------

describe('useCarCatalog — era filter', () => {
  it('filters Ferraris by decade when era is set', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1980);
    });

    expect(result.current.filteredFerraris).toHaveLength(2);
    expect(result.current.filteredFerraris.every((c) => c.decade === 1980)).toBe(true);
  });

  it('clears era filter when setEra(undefined) is called', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(1980);
    });
    expect(result.current.filteredFerraris).toHaveLength(2);

    act(() => {
      result.current.setEra(undefined);
    });
    expect(result.current.filteredFerraris).toHaveLength(3);
  });

  it('returns empty array for a decade with no matching cars', async () => {
    const { result } = renderHook(() => useCarCatalog());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.setEra(2020);
    });

    expect(result.current.filteredFerraris).toHaveLength(0);
    expect(result.current.filteredLambos).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Debounced search tests (fake timers)
// ---------------------------------------------------------------------------

describe('useCarCatalog — debounced search', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Render the hook and let the initial fetch resolve.
   * vi.runAllTimersAsync() flushes both pending timers and microtasks,
   * allowing fetch Promises to settle while fake timers are active.
   */
  async function renderAndLoad() {
    const hookResult = renderHook(() => useCarCatalog());
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    return hookResult;
  }

  it('does not filter before 300 ms have elapsed', async () => {
    const { result } = await renderAndLoad();
    expect(result.current.loading).toBe(false);
    expect(result.current.filteredFerraris).toHaveLength(3);

    act(() => {
      result.current.setSearch('Testarossa');
    });

    // Advance only 200 ms — debounce has not fired yet
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(result.current.filteredFerraris).toHaveLength(3);
  });

  it('filters after 300 ms have elapsed', async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setSearch('Testarossa');
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('Testarossa');
  });

  it('is case-insensitive', async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setSearch('testarossa');
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current.filteredFerraris).toHaveLength(1);
  });

  it('updates searchValue immediately (before debounce fires)', async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setSearch('F40');
    });

    expect(result.current.searchValue).toBe('F40');
    // Filter hasn't applied yet
    expect(result.current.filteredFerraris).toHaveLength(3);
  });

  it('debounce resets when setSearch is called again before 300 ms', async () => {
    const { result } = await renderAndLoad();

    // Type 'F', wait 200 ms, then type 'F40'
    act(() => {
      result.current.setSearch('F');
    });

    act(() => {
      vi.advanceTimersByTime(200);
    });

    act(() => {
      result.current.setSearch('F40');
    });

    // 200 ms further — only 200 ms since 'F40' was typed
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // Debounce for 'F40' hasn't fired yet — all ferraris still visible
    expect(result.current.filteredFerraris).toHaveLength(3);

    // Advance the remaining 100 ms to cross the 300 ms threshold
    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('F40');
  });

  it('combines era and search filters', async () => {
    const { result } = await renderAndLoad();

    act(() => {
      result.current.setEra(1980);
      result.current.setSearch('Testarossa');
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current.filteredFerraris).toHaveLength(1);
    expect(result.current.filteredFerraris[0].model).toBe('Testarossa');
    expect(result.current.filteredLambos).toHaveLength(0);
  });
});
