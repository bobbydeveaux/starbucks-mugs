import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useDrinks } from './useDrinks';
import type { DrinkCatalogEnvelope, FilterState } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const starbucksEnvelope: DrinkCatalogEnvelope = {
  schema_version: '1.0',
  brand: 'starbucks',
  updated: '2026-02-24',
  drinks: [
    {
      id: 'sbux-flat-white',
      brand: 'starbucks',
      name: 'Flat White',
      category: 'hot',
      size_ml: 354,
      image: '/images/sbux-flat-white.webp',
      nutrition: { calories_kcal: 160, sugar_g: 14, fat_g: 6, protein_g: 9, caffeine_mg: 130 },
    },
    {
      id: 'sbux-cold-brew',
      brand: 'starbucks',
      name: 'Cold Brew Coffee',
      category: 'iced',
      size_ml: 473,
      image: '/images/sbux-cold-brew.webp',
      nutrition: { calories_kcal: 5, sugar_g: 0, fat_g: 0, protein_g: 1, caffeine_mg: 205 },
    },
    {
      id: 'sbux-frappuccino-caramel',
      brand: 'starbucks',
      name: 'Caramel Frappuccino',
      category: 'blended',
      size_ml: 473,
      image: '/images/sbux-frappuccino-caramel.webp',
      nutrition: { calories_kcal: 380, sugar_g: 55, fat_g: 13, protein_g: 5, caffeine_mg: 90 },
    },
    {
      id: 'sbux-chai-latte',
      brand: 'starbucks',
      name: 'Chai Tea Latte',
      category: 'tea',
      size_ml: 354,
      image: '/images/sbux-chai-latte.webp',
      nutrition: { calories_kcal: 240, sugar_g: 42, fat_g: 4, protein_g: 8, caffeine_mg: 95 },
    },
  ],
};

const costaEnvelope: DrinkCatalogEnvelope = {
  schema_version: '1.0',
  brand: 'costa',
  updated: '2026-02-24',
  drinks: [
    {
      id: 'costa-latte',
      brand: 'costa',
      name: 'Latte',
      category: 'hot',
      size_ml: 354,
      image: '/images/costa-latte.webp',
      nutrition: { calories_kcal: 170, sugar_g: 15, fat_g: 6, protein_g: 11, caffeine_mg: 185 },
    },
    {
      id: 'costa-cold-brew',
      brand: 'costa',
      name: 'Cold Brew',
      category: 'iced',
      size_ml: 325,
      image: '/images/costa-cold-brew.webp',
      nutrition: { calories_kcal: 10, sugar_g: 0, fat_g: 0, protein_g: 1, caffeine_mg: 200 },
    },
    {
      id: 'costa-frostino-caramel',
      brand: 'costa',
      name: 'Caramel Frostino',
      category: 'blended',
      size_ml: 473,
      image: '/images/costa-frostino-caramel.webp',
      nutrition: { calories_kcal: 420, sugar_g: 62, fat_g: 13, protein_g: 7, caffeine_mg: 90 },
    },
    {
      id: 'costa-chai-latte',
      brand: 'costa',
      name: 'Chai Latte',
      category: 'tea',
      size_ml: 354,
      image: '/images/costa-chai-latte.webp',
      nutrition: { calories_kcal: 220, sugar_g: 37, fat_g: 4, protein_g: 7, caffeine_mg: 80 },
    },
  ],
};

const defaultFilter: FilterState = { category: 'all', query: '' };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch(
  starbucksData: unknown = starbucksEnvelope,
  costaData: unknown = costaEnvelope,
) {
  return vi.fn().mockImplementation((url: string) => {
    if (url.includes('starbucks')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(starbucksData) });
    }
    if (url.includes('costa')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(costaData) });
    }
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useDrinks', () => {
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
    const { result } = renderHook(() => useDrinks(defaultFilter));
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.drinks).toEqual([]);
  });

  it('clears loading state after data is fetched', async () => {
    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Parallel fetch and merge
  // -------------------------------------------------------------------------

  it('fetches both JSON files in parallel via Promise.all', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const urls = fetchMock.mock.calls.map((call: [string]) => call[0]);
    expect(urls).toContain('/data/starbucks.json');
    expect(urls).toContain('/data/costa.json');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('merges drinks from both brands into a combined list', async () => {
    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const total =
      starbucksEnvelope.drinks.length + costaEnvelope.drinks.length;
    expect(result.current.drinks).toHaveLength(total);
  });

  it('separates drinks by brand correctly', async () => {
    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.starbucksDrinks).toHaveLength(
      starbucksEnvelope.drinks.length,
    );
    expect(result.current.costaDrinks).toHaveLength(costaEnvelope.drinks.length);

    result.current.starbucksDrinks.forEach((d) =>
      expect(d.brand).toBe('starbucks'),
    );
    result.current.costaDrinks.forEach((d) => expect(d.brand).toBe('costa'));
  });

  // -------------------------------------------------------------------------
  // Filtering by category
  // -------------------------------------------------------------------------

  it('returns all drinks when category is "all"', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'all', query: '' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    const total =
      starbucksEnvelope.drinks.length + costaEnvelope.drinks.length;
    expect(result.current.drinks).toHaveLength(total);
  });

  it('filters drinks by category "hot"', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'hot', query: '' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.drinks.forEach((d) => expect(d.category).toBe('hot'));

    const expectedHot = [
      ...starbucksEnvelope.drinks,
      ...costaEnvelope.drinks,
    ].filter((d) => d.category === 'hot').length;
    expect(result.current.drinks).toHaveLength(expectedHot);
  });

  it('filters drinks by category "iced"', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'iced', query: '' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.drinks.forEach((d) => expect(d.category).toBe('iced'));
  });

  it('filters drinks by category "blended"', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'blended', query: '' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.drinks.forEach((d) => expect(d.category).toBe('blended'));
  });

  it('filters drinks by category "tea"', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'tea', query: '' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.drinks.forEach((d) => expect(d.category).toBe('tea'));
  });

  // -------------------------------------------------------------------------
  // Search query
  // -------------------------------------------------------------------------

  it('filters drinks by search query (case-insensitive)', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'all', query: 'flat white' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.drinks.length).toBeGreaterThan(0);
    result.current.drinks.forEach((d) =>
      expect(d.name.toLowerCase()).toContain('flat white'),
    );
  });

  it('search query is case-insensitive', async () => {
    const { result: lower } = renderHook(() =>
      useDrinks({ category: 'all', query: 'latte' }),
    );
    const { result: upper } = renderHook(() =>
      useDrinks({ category: 'all', query: 'LATTE' }),
    );
    await waitFor(() => expect(lower.current.loading).toBe(false));
    await waitFor(() => expect(upper.current.loading).toBe(false));

    expect(lower.current.drinks.length).toBe(upper.current.drinks.length);
  });

  it('returns empty list when query matches no drinks', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'all', query: 'zzznomatch999' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.drinks).toHaveLength(0);
    expect(result.current.starbucksDrinks).toHaveLength(0);
    expect(result.current.costaDrinks).toHaveLength(0);
  });

  it('applies category and query filters simultaneously', async () => {
    const { result } = renderHook(() =>
      useDrinks({ category: 'hot', query: 'flat' }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));

    result.current.drinks.forEach((d) => {
      expect(d.category).toBe('hot');
      expect(d.name.toLowerCase()).toContain('flat');
    });
  });

  it('trims whitespace from the search query', async () => {
    const { result: padded } = renderHook(() =>
      useDrinks({ category: 'all', query: '  latte  ' }),
    );
    const { result: clean } = renderHook(() =>
      useDrinks({ category: 'all', query: 'latte' }),
    );
    await waitFor(() => expect(padded.current.loading).toBe(false));
    await waitFor(() => expect(clean.current.loading).toBe(false));

    expect(padded.current.drinks.length).toBe(clean.current.drinks.length);
  });

  // -------------------------------------------------------------------------
  // Error handling
  // -------------------------------------------------------------------------

  it('sets error state and clears loading when fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    );

    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.drinks).toHaveLength(0);
  });

  it('sets error when starbucks.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('starbucks')) {
          return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(costaEnvelope),
        });
      }),
    );

    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/starbucks\.json/);
    expect(result.current.drinks).toHaveLength(0);
  });

  it('sets error when costa.json returns a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('costa')) {
          return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(starbucksEnvelope),
        });
      }),
    );

    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/costa\.json/);
    expect(result.current.drinks).toHaveLength(0);
  });

  it('does not crash the app on fetch failure (error returned, not thrown)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    );

    const { result } = renderHook(() => useDrinks(defaultFilter));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // The hook should be in a stable error state, not throw
    expect(result.current.error).not.toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.drinks).toEqual([]);
  });
});
