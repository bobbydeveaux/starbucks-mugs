import { useState, useCallback } from 'react';
import type { CarBrand, CarModel } from '../types';
import { useCarCatalog } from '../hooks/useCarCatalog';
import { CarCard } from './CarCard';

interface CatalogPageProps {
  brand: CarBrand;
}

const BRAND_CONFIG: Record<
  CarBrand,
  {
    label: string;
    headerBg: string;
    headerText: string;
    subText: string;
    subtitle: string;
    activeDecade: string;
    inactiveDecade: string;
    focusRing: string;
  }
> = {
  ferrari: {
    label: 'Ferrari',
    headerBg: 'bg-ferrari-red',
    headerText: 'text-white',
    subText: 'text-red-100',
    subtitle: 'Every production Ferrari from 1947 to the present day.',
    activeDecade: 'bg-ferrari-red text-white border-ferrari-red',
    inactiveDecade:
      'bg-white text-gray-700 border-gray-300 hover:border-ferrari-red hover:text-ferrari-red',
    focusRing: 'focus:ring-ferrari-red',
  },
  lamborghini: {
    label: 'Lamborghini',
    headerBg: 'bg-lambo-yellow',
    headerText: 'text-gray-900',
    subText: 'text-yellow-800',
    subtitle: 'Every production Lamborghini from 1963 to the present day.',
    activeDecade: 'bg-lambo-yellow text-gray-900 border-lambo-yellow',
    inactiveDecade:
      'bg-white text-gray-700 border-gray-300 hover:border-lambo-yellow hover:text-yellow-700',
    focusRing: 'focus:ring-lambo-yellow',
  },
};

/**
 * Reusable catalog page for a single car brand.
 * Fetches the brand's JSON catalog, renders decade-filter buttons, a search input,
 * and a responsive grid of CarCard components.
 */
export function CatalogPage({ brand }: CatalogPageProps) {
  const [search, setSearch] = useState('');
  const [selectedDecade, setSelectedDecade] = useState<number | undefined>(undefined);
  const [selectedCarId, setSelectedCarId] = useState<string | null>(null);

  const { cars, loading, error, decades } = useCarCatalog(brand, {
    search,
    decade: selectedDecade,
  });

  const handleSelect = useCallback((car: CarModel) => {
    setSelectedCarId((prev) => (prev === car.id ? null : car.id));
  }, []);

  const handleDecadeClick = useCallback((decade: number) => {
    setSelectedDecade((prev) => (prev === decade ? undefined : decade));
  }, []);

  const config = BRAND_CONFIG[brand];

  return (
    <div className="min-h-screen bg-gray-50">
      <header className={`${config.headerBg} shadow-sm`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className={`text-3xl font-bold ${config.headerText}`}>{config.label} Catalog</h1>
          <p className={`mt-1 ${config.subText}`}>{config.subtitle}</p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Search */}
        <div className="mb-4">
          <input
            type="search"
            placeholder="Search models…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search car models"
            className="w-full sm:max-w-xs rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-gray-400"
          />
        </div>

        {/* Decade filter */}
        {decades.length > 0 && (
          <div
            className="flex flex-wrap gap-2 mb-8"
            role="group"
            aria-label="Filter by decade"
          >
            <button
              type="button"
              onClick={() => setSelectedDecade(undefined)}
              className={`px-3 py-1 rounded-full text-sm font-medium border transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 ${config.focusRing} ${
                selectedDecade === undefined ? config.activeDecade : config.inactiveDecade
              }`}
            >
              All
            </button>
            {decades.map((decade) => (
              <button
                key={decade}
                type="button"
                onClick={() => handleDecadeClick(decade)}
                className={`px-3 py-1 rounded-full text-sm font-medium border transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 ${config.focusRing} ${
                  selectedDecade === decade ? config.activeDecade : config.inactiveDecade
                }`}
              >
                {decade}s
              </button>
            ))}
          </div>
        )}

        {/* Loading spinner */}
        {loading && (
          <div
            className="flex items-center justify-center py-24"
            role="status"
            aria-label="Loading cars"
          >
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-gray-200 border-t-gray-600" />
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="rounded-md bg-red-50 p-6 text-center" role="alert">
            <p className="text-sm font-medium text-red-800">{error}</p>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && cars.length === 0 && (
          <p className="py-16 text-center text-sm text-gray-400">
            No cars match your filters.
          </p>
        )}

        {/* Car grid */}
        {!loading && !error && cars.length > 0 && (
          <ul
            className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
            role="list"
            aria-label={`${config.label} cars`}
          >
            {cars.map((car) => (
              <li key={car.id} role="listitem">
                <CarCard
                  car={car}
                  isSelected={car.id === selectedCarId}
                  onSelect={handleSelect}
                />
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

export default CatalogPage;
