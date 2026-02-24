import { useState, useEffect, useMemo, useCallback } from 'react';
import type { CarModel, CarCatalogEnvelope } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** All raw Ferrari cars (unfiltered) */
  ferraris: CarModel[];
  /** All raw Lamborghini cars (unfiltered) */
  lambos: CarModel[];
  /** Ferrari cars matching the current era and search filters */
  filteredFerraris: CarModel[];
  /** Lamborghini cars matching the current era and search filters */
  filteredLambos: CarModel[];
  /** Available decade values derived from the loaded catalog data */
  availableDecades: number[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
  /** Currently selected decade filter, or null for all eras */
  era: number | null;
  /** Update the era (decade) filter */
  setEra: (era: number | null) => void;
  /** Current raw search query (not debounced — for controlled input binding) */
  search: string;
  /** Update the search query; filtering is debounced by 300 ms */
  setSearch: (search: string) => void;
}

/**
 * Fetches both car catalog JSON files in parallel and exposes filtered,
 * era-bucketed car arrays based on the current era and search state.
 *
 * Search is debounced by 300 ms to avoid filtering on every keystroke.
 *
 * @returns Loading state, error state, filtered car arrays, and filter setters.
 *
 * @example
 * const { filteredFerraris, filteredLambos, era, setEra, search, setSearch } = useCarCatalog();
 */
export function useCarCatalog(): UseCarCatalogResult {
  const [ferraris, setFerraris] = useState<CarModel[]>([]);
  const [lambos, setLambos] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Era filter — a decade value like 1980, or null for all eras
  const [era, setEraState] = useState<number | null>(null);

  // Raw search query (bound to the input element)
  const [search, setSearchState] = useState('');
  // Debounced version used for actual filtering
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Stable setters
  const setEra = useCallback((value: number | null) => {
    setEraState(value);
  }, []);

  const setSearch = useCallback((value: string) => {
    setSearchState(value);
  }, []);

  // Fetch both catalogs once on mount
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchCatalogs() {
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
        const sortedFerraris = [...ferrariEnvelope.cars].sort((a, b) => a.year - b.year);
        const sortedLambos = [...lamboEnvelope.cars].sort((a, b) => a.year - b.year);

        setFerraris(sortedFerraris);
        setLambos(sortedLambos);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load car catalog');
        setLoading(false);
      }
    }

    fetchCatalogs();

    return () => {
      controller.abort();
    };
  }, []);

  // Debounce the search input by 300 ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [search]);

  // Derive sorted, unique decades from the loaded data
  const availableDecades = useMemo(() => {
    const decadeSet = new Set<number>();
    for (const car of ferraris) decadeSet.add(car.decade);
    for (const car of lambos) decadeSet.add(car.decade);
    return Array.from(decadeSet).sort((a, b) => a - b);
  }, [ferraris, lambos]);

  // Apply era and debounced search filters
  const filteredFerraris = useMemo(() => {
    let result = ferraris;

    if (era !== null) {
      result = result.filter((car) => car.decade === era);
    }

    const trimmed = debouncedSearch.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [ferraris, era, debouncedSearch]);

  const filteredLambos = useMemo(() => {
    let result = lambos;

    if (era !== null) {
      result = result.filter((car) => car.decade === era);
    }

    const trimmed = debouncedSearch.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [lambos, era, debouncedSearch]);

  return {
    ferraris,
    lambos,
    filteredFerraris,
    filteredLambos,
    availableDecades,
    loading,
    error,
    era,
    setEra,
    search,
    setSearch,
  };
}
