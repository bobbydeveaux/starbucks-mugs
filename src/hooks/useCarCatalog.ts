import { useState, useEffect, useMemo, useRef } from 'react';
import type { CarModel, CarCatalogEnvelope, CatalogFilters } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** Filtered Ferrari models matching current era/search filters, sorted chronologically */
  filteredFerraris: CarModel[];
  /** Filtered Lamborghini models matching current era/search filters, sorted chronologically */
  filteredLambos: CarModel[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
  /** Active decade filter (undefined = all decades) */
  era: number | undefined;
  /** Set the decade filter; pass undefined to clear */
  setEra: (decade: number | undefined) => void;
  /** Set the model-name search string; debounced internally to 300 ms */
  setSearch: (query: string) => void;
  /** Current raw (un-debounced) search input value for controlled input binding */
  searchValue: string;
}

const DEBOUNCE_MS = 300;

/**
 * Fetches both car catalog JSON files in parallel and exposes filtered,
 * chronologically-sorted arrays for each brand.
 *
 * Filtering supports two orthogonal axes:
 * - `era` — decimal decade value (e.g. 1980) narrows results to that decade
 * - `search` — case-insensitive substring match against `CarModel.model`,
 *   debounced to 300 ms so the filter only re-runs after the user pauses typing
 *
 * @returns Loading/error state, filtered car arrays, and filter setters.
 *
 * @example
 * const { filteredFerraris, filteredLambos, setEra, setSearch } = useCarCatalog();
 */
export function useCarCatalog(): UseCarCatalogResult {
  const [allCars, setAllCars] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [era, setEra] = useState<number | undefined>(undefined);
  const [searchValue, setSearchValue] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Debounce the search query
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setSearch = (query: string) => {
    setSearchValue(query);
    if (debounceTimer.current !== null) {
      clearTimeout(debounceTimer.current);
    }
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(query);
    }, DEBOUNCE_MS);
  };

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimer.current !== null) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, []);

  // Fetch both catalogs once on mount
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

        setAllCars([...ferrariEnvelope.cars, ...lamboEnvelope.cars]);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
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

  // Apply era and debounced search filters
  const filteredCars = useMemo(() => {
    let result = allCars;

    if (era !== undefined) {
      result = result.filter((car) => car.decade === era);
    }

    const trimmed = debouncedSearch.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allCars, era, debouncedSearch]);

  const filteredFerraris = useMemo(
    () =>
      filteredCars
        .filter((car) => car.brand === 'ferrari')
        .sort((a, b) => a.year - b.year),
    [filteredCars],
  );

  const filteredLambos = useMemo(
    () =>
      filteredCars
        .filter((car) => car.brand === 'lamborghini')
        .sort((a, b) => a.year - b.year),
    [filteredCars],
  );

  return {
    filteredFerraris,
    filteredLambos,
    loading,
    error,
    era,
    setEra,
    setSearch,
    searchValue,
  };
}
