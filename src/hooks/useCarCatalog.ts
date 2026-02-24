import { useState, useEffect, useMemo } from 'react';
import type { CarModel, CarBrand, CarSpecs, CatalogFilters } from '../types';

/** Return shape of the useCarCatalog hook */
export interface UseCarCatalogResult {
  /** All Ferrari models matching the current filters, sorted chronologically */
  ferrariCars: CarModel[];
  /** All Lamborghini models matching the current filters, sorted chronologically */
  lamboCars: CarModel[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails; contains an error message */
  error: string | null;
}

/** Raw car entry shape as stored in the JSON data files */
interface RawCarEntry {
  id: string;
  brand: CarBrand;
  model: string;
  year: number;
  decade: number;
  /** JSON uses 'image'; mapped to 'imageUrl' in the CarModel type */
  image: string;
  price?: number;
  specs: CarSpecs;
  eraRivals: string[];
}

interface RawCarCatalogEnvelope {
  schema_version: string;
  brand: CarBrand;
  updated: string;
  cars: RawCarEntry[];
}

function mapRawCar(raw: RawCarEntry): CarModel {
  return {
    id: raw.id,
    brand: raw.brand,
    model: raw.model,
    year: raw.year,
    decade: raw.decade,
    imageUrl: raw.image,
    price: raw.price,
    specs: raw.specs,
    eraRivals: raw.eraRivals,
  };
}

/**
 * Fetches both brand JSON files in parallel and exposes filtered, chronologically
 * sorted car arrays based on the given CatalogFilters.
 *
 * @param filters - Optional decade filter and search query.
 * @returns Loading state, error state, and filtered car arrays for each brand.
 *
 * @example
 * const { ferrariCars, lamboCars, loading, error } = useCarCatalog({ decade: 1980, search: 'countach' });
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

        const [ferrariEnvelope, lamboEnvelope]: [RawCarCatalogEnvelope, RawCarCatalogEnvelope] =
          await Promise.all([ferrariRes.json(), lamboRes.json()]);

        const ferraris = ferrariEnvelope.cars
          .map(mapRawCar)
          .sort((a, b) => a.year - b.year);
        const lambos = lamboEnvelope.cars
          .map(mapRawCar)
          .sort((a, b) => a.year - b.year);

        setAllFerraris(ferraris);
        setAllLambos(lambos);
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

  const { decade, search } = filters;

  const ferrariCars = useMemo(() => {
    let result = allFerraris;
    if (decade !== undefined) {
      result = result.filter((c) => c.decade === decade);
    }
    const trimmed = (search ?? '').trim().toLowerCase();
    if (trimmed) {
      result = result.filter((c) => c.model.toLowerCase().includes(trimmed));
    }
    return result;
  }, [allFerraris, decade, search]);

  const lamboCars = useMemo(() => {
    let result = allLambos;
    if (decade !== undefined) {
      result = result.filter((c) => c.decade === decade);
    }
    const trimmed = (search ?? '').trim().toLowerCase();
    if (trimmed) {
      result = result.filter((c) => c.model.toLowerCase().includes(trimmed));
    }
    return result;
  }, [allLambos, decade, search]);

  return { ferrariCars, lamboCars, loading, error };
}
