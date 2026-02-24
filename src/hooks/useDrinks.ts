import { useState, useEffect, useMemo } from 'react';
import type { Drink, DrinkCatalogEnvelope, FilterState } from '../types';
import { filterDrinks } from '../utils/filterDrinks';

/** Return shape of the useDrinks hook */
export interface UseDrinksResult {
  /** All drinks matching the current filter/search, across both brands */
  drinks: Drink[];
  /** Filtered Starbucks drinks */
  starbucksDrinks: Drink[];
  /** Filtered Costa drinks */
  costaDrinks: Drink[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
}

/**
 * Fetches both brand JSON files in parallel and exposes a filtered, searched
 * list of drinks based on the given FilterState.
 *
 * @param filter - Active category filter and search query.
 * @returns Loading state, error state, and filtered drink arrays.
 *
 * @example
 * const { drinks, loading, error } = useDrinks({ category: 'hot', query: '' });
 */
export function useDrinks(filter: FilterState): UseDrinksResult {
  const [allDrinks, setAllDrinks] = useState<Drink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchDrinks() {
      try {
        const [starbucksRes, costaRes] = await Promise.all([
          fetch('/data/starbucks.json', { signal }),
          fetch('/data/costa.json', { signal }),
        ]);

        if (!starbucksRes.ok) {
          throw new Error(`Failed to fetch starbucks.json: ${starbucksRes.status}`);
        }
        if (!costaRes.ok) {
          throw new Error(`Failed to fetch costa.json: ${costaRes.status}`);
        }

        const [starbucksEnvelope, costaEnvelope]: [DrinkCatalogEnvelope, DrinkCatalogEnvelope] =
          await Promise.all([starbucksRes.json(), costaRes.json()]);

        setAllDrinks([...starbucksEnvelope.drinks, ...costaEnvelope.drinks]);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Component unmounted — ignore
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load drink data');
        setLoading(false);
      }
    }

    fetchDrinks();

    return () => {
      controller.abort();
    };
  }, []);

  const filtered = useMemo(
    () => filterDrinks(allDrinks, filter.category, filter.query),
    [allDrinks, filter.category, filter.query],
  );

  const starbucksDrinks = useMemo(
    () => filtered.filter((d) => d.brand === 'starbucks'),
    [filtered],
  );

  const costaDrinks = useMemo(
    () => filtered.filter((d) => d.brand === 'costa'),
    [filtered],
  );

  return { drinks: filtered, starbucksDrinks, costaDrinks, loading, error };
}
