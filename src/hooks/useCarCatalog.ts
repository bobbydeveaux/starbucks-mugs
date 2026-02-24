import { useState, useEffect } from 'react';
import type { CarModel, CarCatalogEnvelope } from '../types';

export interface UseCarCatalogResult {
  /** Ferrari models sorted chronologically by year */
  ferrariCars: CarModel[];
  /** Lamborghini models sorted chronologically by year */
  lamboCars: CarModel[];
  loading: boolean;
  error: string | null;
}

/**
 * Fetches both brand JSON files in parallel and exposes chronologically sorted
 * car arrays, mirroring the useDrinks pattern used for the drinks catalog.
 */
export function useCarCatalog(): UseCarCatalogResult {
  const [ferrariCars, setFerrariCars] = useState<CarModel[]>([]);
  const [lamboCars, setLamboCars] = useState<CarModel[]>([]);
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

        setFerrariCars([...ferrariEnvelope.cars].sort((a, b) => a.year - b.year));
        setLamboCars([...lamboEnvelope.cars].sort((a, b) => a.year - b.year));
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return;
        setError(err instanceof Error ? err.message : 'Failed to load car data');
        setLoading(false);
      }
    }

    fetchCars();
    return () => controller.abort();
  }, []);

  return { ferrariCars, lamboCars, loading, error };
}
