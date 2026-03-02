import { useState, useEffect } from 'react';
import type { Country } from '../types';

/** Return shape of the useTemperatures hook */
export interface UseTemperaturesResult {
  /** All countries loaded from /temperatures.json */
  countries: Country[];
  /** True while the initial JSON fetch is in flight */
  loading: boolean;
  /** Non-null when the fetch fails or JSON is malformed; contains an error message */
  error: string | null;
}

/**
 * Fetches `/temperatures.json` once on mount and exposes the parsed
 * country temperature data along with loading and error state.
 *
 * @returns Loading state, error state, and country array.
 *
 * @example
 * const { countries, loading, error } = useTemperatures();
 */
export function useTemperatures(): UseTemperaturesResult {
  const [countries, setCountries] = useState<Country[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;

    async function fetchTemperatures() {
      try {
        const res = await fetch('/temperatures.json', { signal });

        if (!res.ok) {
          throw new Error(`Failed to fetch temperatures.json: ${res.status}`);
        }

        const data: Country[] = await res.json();
        setCountries(data);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Component unmounted — ignore stale response.
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load temperature data');
        setLoading(false);
      }
    }

    fetchTemperatures();

    return () => {
      controller.abort();
    };
  }, []);

  return { countries, loading, error };
}
