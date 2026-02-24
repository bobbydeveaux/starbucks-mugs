import { useState, useEffect, useMemo } from 'react';
import type { CarModel, CarCatalogEnvelope } from '../types';

// ---------------------------------------------------------------------------
// Raw JSON shape
// ---------------------------------------------------------------------------

/**
 * Raw car shape as it appears in the JSON file.
 * The JSON uses `image` instead of the `imageUrl` field on CarModel.
 */
type RawCar = Omit<CarModel, 'imageUrl'> & { image: string };

/** Raw catalog envelope shape from the JSON file */
type RawCarCatalogEnvelope = Omit<CarCatalogEnvelope, 'cars'> & { cars: RawCar[] };

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** Filtered Ferrari models sorted chronologically by year */
  filteredFerraris: CarModel[];
  /** Filtered Lamborghini models sorted chronologically by year */
  filteredLambos: CarModel[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
  /** Currently active decade filter, e.g. 1980. Undefined means all decades. */
  era: number | undefined;
  /** Set the active era decade (e.g. 1980) or pass undefined to clear the filter */
  setEra: (decade: number | undefined) => void;
  /** Raw (non-debounced) search string as typed by the user */
  search: string;
  /** Update the search string; filtering is applied after a 300 ms debounce */
  setSearch: (query: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEBOUNCE_MS = 300;

/** Normalise raw JSON car data to the CarModel shape */
function mapRawCar({ image, ...rest }: RawCar): CarModel {
  return { ...rest, imageUrl: image };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Fetches both brand car catalog JSON files in parallel and exposes filtered,
 * chronologically-sorted car arrays.
 *
 * Era filtering narrows results to a specific decade (e.g. 1980 → 1980–1989).
 * Search filtering is debounced by 300 ms and matches model names
 * case-insensitively.
 *
 * @returns Loading state, error state, filtered car arrays, and filter controls.
 *
 * @example
 * const { filteredFerraris, filteredLambos, setEra, setSearch } = useCarCatalog();
 */
export function useCarCatalog(): UseCarCatalogResult {
  const [allFerraris, setAllFerraris] = useState<CarModel[]>([]);
  const [allLambos, setAllLambos] = useState<CarModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [era, setEra] = useState<number | undefined>(undefined);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // -------------------------------------------------------------------------
  // Fetch both catalogs on mount
  // -------------------------------------------------------------------------

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

        const [ferrariEnvelope, lamboEnvelope]: [RawCarCatalogEnvelope, RawCarCatalogEnvelope] =
          await Promise.all([ferrariRes.json(), lamboRes.json()]);

        const sortedFerraris = ferrariEnvelope.cars
          .map(mapRawCar)
          .sort((a, b) => a.year - b.year);

        const sortedLambos = lamboEnvelope.cars
          .map(mapRawCar)
          .sort((a, b) => a.year - b.year);

        setAllFerraris(sortedFerraris);
        setAllLambos(sortedLambos);
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

  // -------------------------------------------------------------------------
  // Debounce search input
  // -------------------------------------------------------------------------

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
    };
  }, [search]);

  // -------------------------------------------------------------------------
  // Apply era + search filters
  // -------------------------------------------------------------------------

  const filteredFerraris = useMemo(() => {
    let result = allFerraris;

    if (era !== undefined) {
      result = result.filter((car) => car.decade === era);
    }

    const trimmed = debouncedSearch.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allFerraris, era, debouncedSearch]);

  const filteredLambos = useMemo(() => {
    let result = allLambos;

    if (era !== undefined) {
      result = result.filter((car) => car.decade === era);
    }

    const trimmed = debouncedSearch.trim().toLowerCase();
    if (trimmed) {
      result = result.filter((car) => car.model.toLowerCase().includes(trimmed));
    }

    return result;
  }, [allLambos, era, debouncedSearch]);

  return {
    filteredFerraris,
    filteredLambos,
    loading,
    error,
    era,
    setEra,
    search,
    setSearch,
  };
}
