import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import type { CarModel, CarCatalogEnvelope, CatalogFilters } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** All Ferrari models from the JSON catalog (unfiltered) */
  ferrariCars: CarModel[];
  /** All Lamborghini models from the JSON catalog (unfiltered) */
  lamboCars: CarModel[];
  /** Ferrari models that pass the current era and search filters */
  filteredFerraris: CarModel[];
  /** Lamborghini models that pass the current era and search filters */
  filteredLambos: CarModel[];
  /** Currently active decade filter, or undefined for all decades */
  era: number | undefined;
  /** Currently active search query (the debounced value applied to filtering) */
  search: string;
  /** Set the decade filter; pass undefined to clear */
  setEra: (decade: number | undefined) => void;
  /** Set the search query; filtering is debounced by 300 ms */
  setSearch: (query: string) => void;
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
}

/**
 * Fetches both brand JSON files in parallel and exposes era-filtered,
 * debounced-search-filtered car lists for Ferrari and Lamborghini.
 *
 * @param initialFilters - Optional initial filter values for decade and search.
 * @returns Loading state, error state, raw car arrays, filtered car arrays,
 *          and filter setter functions.
 *
 * @example
 * const { filteredFerraris, filteredLambos, setEra, setSearch, loading } =
 *   useCarCatalog();
 */
export function useCarCatalog(initialFilters?: CatalogFilters): UseCarCatalogResult {
  const [allFerraris, setAllFerraris] = useState<CarModel[]>([]);
  const [allLambos, setAllLambos] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Era filter applied immediately (no debounce needed — decade selection is
  // a discrete UI action, not a keystroke-level event).
  const [era, setEra] = useState<number | undefined>(initialFilters?.decade);

  // Raw search query (what the user has typed) and debounced value (used in
  // the filter memo, updated 300 ms after the last keystroke).
  const [rawSearch, setRawSearch] = useState(initialFilters?.search ?? '');
  const [debouncedSearch, setDebouncedSearch] = useState(initialFilters?.search ?? '');
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setSearch = useCallback((query: string) => {
    setRawSearch(query);
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(() => {
      setDebouncedSearch(query);
      debounceTimerRef.current = null;
    }, 300);
  }, []);

  // Clear debounce timer on unmount.
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current !== null) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  // Fetch both catalogs once on mount.
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

        // Sort chronologically by year so consumers receive stable ordering.
        const sortByYear = (a: CarModel, b: CarModel) => a.year - b.year;
        setAllFerraris([...ferrariEnvelope.cars].sort(sortByYear));
        setAllLambos([...lamboEnvelope.cars].sort(sortByYear));
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Component unmounted — ignore stale response.
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

  /** Apply era and search filters to a car array. */
  function applyFilters(cars: CarModel[], decade: number | undefined, query: string): CarModel[] {
    let result = cars;

    if (decade !== undefined) {
      result = result.filter((car) => car.decade === decade);
    }

    const trimmed = query.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }

  const filteredFerraris = useMemo(
    () => applyFilters(allFerraris, era, debouncedSearch),
    [allFerraris, era, debouncedSearch],
  );

  const filteredLambos = useMemo(
    () => applyFilters(allLambos, era, debouncedSearch),
    [allLambos, era, debouncedSearch],
  );

  return {
    ferrariCars: allFerraris,
    lamboCars: allLambos,
    filteredFerraris,
    filteredLambos,
    era,
    search: rawSearch,
    setEra,
    setSearch,
    loading,
    error,
  };
}
