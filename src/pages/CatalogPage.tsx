import { useState } from 'react';
import { useCarCatalog } from '../hooks/useCarCatalog';
import { CarCard } from '../components/CarCard';
import type { CarModel, CarBrand } from '../types';

// ---------------------------------------------------------------------------
// Brand section component
// ---------------------------------------------------------------------------

const BRAND_CONFIG: Record<CarBrand, {
  label: string;
  headingClass: string;
  dividerClass: string;
  emptyText: string;
}> = {
  ferrari: {
    label: 'Ferrari',
    headingClass: 'text-ferrari-red',
    dividerClass: 'border-ferrari-red',
    emptyText: 'No Ferrari models match your filters.',
  },
  lamborghini: {
    label: 'Lamborghini',
    headingClass: 'text-yellow-600',
    dividerClass: 'border-lambo-yellow',
    emptyText: 'No Lamborghini models match your filters.',
  },
};

function BrandSection({
  brand,
  cars,
  selectedId,
  onSelect,
}: {
  brand: CarBrand;
  cars: CarModel[];
  selectedId: string | null;
  onSelect: (car: CarModel) => void;
}) {
  const config = BRAND_CONFIG[brand];

  return (
    <section aria-label={`${config.label} cars`}>
      <div className="mb-4 flex items-center gap-3">
        <h2 className={`text-xl font-bold ${config.headingClass}`}>
          {config.label}
        </h2>
        <span className="text-sm text-gray-500">({cars.length} models)</span>
        <div className={`flex-1 border-t ${config.dividerClass}`} />
      </div>

      {cars.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">{config.emptyText}</p>
      ) : (
        <ul
          className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
          role="list"
          aria-label={`${config.label} car cards`}
        >
          {cars.map((car) => (
            <li key={car.id} role="listitem">
              <CarCard
                car={car}
                isSelected={car.id === selectedId}
                onSelect={onSelect}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// CatalogPage
// ---------------------------------------------------------------------------

export function CatalogPage() {
  const { ferrariCars, lamboCars, loading, error } = useCarCatalog();
  const [selectedFerrariId, setSelectedFerrariId] = useState<string | null>(null);
  const [selectedLamboId, setSelectedLamboId] = useState<string | null>(null);

  function handleSelect(car: CarModel) {
    if (car.brand === 'ferrari') {
      setSelectedFerrariId((prev) => (prev === car.id ? null : car.id));
    } else {
      setSelectedLamboId((prev) => (prev === car.id ? null : car.id));
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">Car Catalog</h1>
          <p className="mt-1 text-gray-500">
            Browse Ferrari and Lamborghini models from every era.
          </p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {loading && (
          <div className="flex items-center justify-center py-20" role="status" aria-label="Loading cars">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-300 border-t-ferrari-red" />
            <span className="ml-3 text-gray-500">Loading catalog…</span>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          >
            <strong>Failed to load cars:</strong> {error}
          </div>
        )}

        {!loading && !error && (
          <div className="flex flex-col gap-12">
            <BrandSection
              brand="ferrari"
              cars={ferrariCars}
              selectedId={selectedFerrariId}
              onSelect={handleSelect}
            />
            <BrandSection
              brand="lamborghini"
              cars={lamboCars}
              selectedId={selectedLamboId}
              onSelect={handleSelect}
            />
          </div>
        )}
      </main>
    </div>
  );
}

export default CatalogPage;
