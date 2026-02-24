import { useState, useEffect, useMemo } from 'react';
import type { Drink, DrinkCatalogEnvelope, FilterState } from '../types';

interface UseDrinksResult {
  drinks: Drink[];
  loading: boolean;
  error: string | null;
}

async function fetchBrand(url: string): Promise<Drink[]> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
  const envelope: DrinkCatalogEnvelope = await res.json() as DrinkCatalogEnvelope;
  if (!Array.isArray(envelope.drinks)) {
    throw new Error(`Malformed response from ${url}: missing drinks array`);
  }
  return envelope.drinks;
}

function filterDrinks(drinks: Drink[], filter: FilterState): Drink[] {
  const query = filter.query.trim().toLowerCase();
  return drinks.filter(drink => {
    const matchesCategory =
      filter.category === 'all' || drink.category === filter.category;
    const matchesQuery =
      query === '' || drink.name.toLowerCase().includes(query);
    return matchesCategory && matchesQuery;
  });
}

export function useDrinks(filter: FilterState): UseDrinksResult {
  const [allDrinks, setAllDrinks] = useState<Drink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);

    Promise.all([
      fetchBrand('/data/starbucks.json'),
      fetchBrand('/data/costa.json'),
    ])
      .then(([starbucks, costa]) => {
        if (!cancelled) {
          setAllDrinks([...starbucks, ...costa]);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unknown error loading drinks');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const drinks = useMemo(() => filterDrinks(allDrinks, filter), [allDrinks, filter]);

  return { drinks, loading, error };
}
