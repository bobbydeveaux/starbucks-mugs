import { useState, useEffect, useMemo } from 'react';
import type { CarModel, CarCatalogEnvelope, CarBrand, CatalogFilters } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** Cars matching the current filters */
  cars: CarModel[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
  /** Sorted list of unique decades present in the full (unfiltered) catalog */
  decades: number[];
}

/**
 * Fetches a single brand's car catalog JSON and exposes a filtered list
 * based on the given CatalogFilters.
 *
 * @param brand   - Which brand's JSON to fetch ('ferrari' | 'lamborghini').
 * @param filters - Optional decade and search filters.
 * @returns Loading state, error state, filtered car array, and available decades.
 *
 * @example
 * const { cars, loading, error, decades } = useCarCatalog('ferrari', { decade: 1980 });
 */
export function useCarCatalog(
  brand: CarBrand,
  filters: CatalogFilters = {},
): UseCarCatalogResult {
  const [allCars, setAllCars] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchCars() {
      try {
        const res = await fetch(`/data/${brand}.json`, { signal });

        if (!res.ok) {
          throw new Error(`Failed to fetch ${brand}.json: ${res.status}`);
        }

        const envelope: CarCatalogEnvelope = await res.json();
        setAllCars(envelope.cars);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Component unmounted — ignore
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load car data');
        setLoading(false);
      }
    }

    fetchCars();

    return () => {
      controller.abort();
    };
  }, [brand]);

  const filtered = useMemo(() => {
    let result = allCars;

    if (filters.decade !== undefined) {
      result = result.filter((c) => c.decade === filters.decade);
    }

    const trimmed = (filters.search ?? '').trim().toLowerCase();
    if (trimmed) {
      result = result.filter((c) => c.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allCars, filters.decade, filters.search]);

  const decades = useMemo(() => {
    const set = new Set(allCars.map((c) => c.decade));
    return Array.from(set).sort((a, b) => a - b);
  }, [allCars]);

  return { cars: filtered, loading, error, decades };
}
