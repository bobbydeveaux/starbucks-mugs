import { useState, useEffect, useMemo } from 'react';
import type { CarModel, CarCatalogEnvelope, CatalogFilters } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** Filtered Ferrari models sorted chronologically by year */
  ferrariCars: CarModel[];
  /** Filtered Lamborghini models sorted chronologically by year */
  lamboCars: CarModel[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
}

/**
 * Fetches both car catalog JSON files in parallel and exposes filtered,
 * chronologically sorted car arrays based on the given CatalogFilters.
 *
 * @param filters - Active decade filter and model name search query.
 * @returns Loading state, error state, and filtered car arrays for each brand.
 *
 * @example
 * const { ferrariCars, lamboCars, loading, error } = useCarCatalog({ decade: 1980, search: 'Testarossa' });
 */
export function useCarCatalog(filters: CatalogFilters = {}): UseCarCatalogResult {
  const [allFerraris, setAllFerraris] = useState<CarModel[]>([]);
  const [allLambos, setAllLambos] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchCars() {
      try {
        const [ferrariRes, lamboRes] = await Promise.all([
          fetch('/data/ferrari.json', { signal }),
          fetch('/data/lamborghini.json', { signal }),
        ]);

        if (!ferrariRes.ok) {
          throw new Error(`Failed to fetch ferrari.json: ${ferrariRes.status}`);
        }
        if (!lamboRes.ok) {
          throw new Error(`Failed to fetch lamborghini.json: ${lamboRes.status}`);
        }

        const [ferrariEnvelope, lamboEnvelope]: [CarCatalogEnvelope, CarCatalogEnvelope] =
          await Promise.all([ferrariRes.json(), lamboRes.json()]);

        // Sort chronologically by year
        const sortByYear = (a: CarModel, b: CarModel) => a.year - b.year;

        setAllFerraris([...ferrariEnvelope.cars].sort(sortByYear));
        setAllLambos([...lamboEnvelope.cars].sort(sortByYear));
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
  }, []);

  const ferrariCars = useMemo(() => {
    let result = allFerraris;

    if (filters.decade !== undefined) {
      result = result.filter((car) => car.decade === filters.decade);
    }

    const trimmed = filters.search?.trim().toLowerCase() ?? '';
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allFerraris, filters.decade, filters.search]);

  const lamboCars = useMemo(() => {
    let result = allLambos;

    if (filters.decade !== undefined) {
      result = result.filter((car) => car.decade === filters.decade);
    }

    const trimmed = filters.search?.trim().toLowerCase() ?? '';
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allLambos, filters.decade, filters.search]);

  return { ferrariCars, lamboCars, loading, error };
}
