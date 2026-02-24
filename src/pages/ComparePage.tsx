import { useState, useEffect, useMemo } from 'react';
import { ComparisonView } from '../components/ComparisonView';
import { useComparison } from '../hooks/useComparison';
import { eraMatchSuggestion } from '../utils/eraMatchSuggestion';
import type { CarModel, CarCatalogEnvelope } from '../types';

// ---------------------------------------------------------------------------
// Internal hook: load both car catalogs once
// ---------------------------------------------------------------------------

interface UseCarsResult {
  ferrariCars: CarModel[];
  lamboCars: CarModel[];
  loading: boolean;
  error: string | null;
}

function useCars(): UseCarsResult {
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
          throw new Error(`Failed to load Ferrari data (${ferrariRes.status})`);
        }
        if (!lamboRes.ok) {
          throw new Error(`Failed to load Lamborghini data (${lamboRes.status})`);
        }

        const [ferrariEnvelope, lamboEnvelope]: [CarCatalogEnvelope, CarCatalogEnvelope] =
          await Promise.all([ferrariRes.json(), lamboRes.json()]);

        setFerrariCars(ferrariEnvelope.cars);
        setLamboCars(lamboEnvelope.cars);
        setLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return; // unmounted — ignore
        }
        setError(err instanceof Error ? err.message : 'Failed to load car data');
        setLoading(false);
      }
    }

    fetchCars();
    return () => controller.abort();
  }, []);

  return { ferrariCars, lamboCars, loading, error };
}

// ---------------------------------------------------------------------------
// CarSelector — labelled <select> dropdown
// ---------------------------------------------------------------------------

interface CarSelectorProps {
  label: string;
  cars: CarModel[];
  selected: CarModel | null;
  onSelect: (car: CarModel | null) => void;
  accentClass: string;
}

function CarSelector({ label, cars, selected, onSelect, accentClass }: CarSelectorProps) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`select-${label}`} className={`text-xs font-semibold uppercase tracking-wide ${accentClass}`}>
        {label}
      </label>
      <select
        id={`select-${label}`}
        value={selected?.id ?? ''}
        onChange={(e) => {
          const car = cars.find((c) => c.id === e.target.value) ?? null;
          onSelect(car);
        }}
        className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-offset-1 bg-white"
        aria-label={`Select ${label}`}
      >
        <option value="">— Select a {label} —</option>
        {cars.map((car) => (
          <option key={car.id} value={car.id}>
            {car.year} {car.model}
          </option>
        ))}
      </select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ComparePage
// ---------------------------------------------------------------------------

export function ComparePage() {
  const { ferrariCars, lamboCars, loading, error } = useCars();
  const { selectedFerrari, selectedLambo, setSelectedFerrari, setSelectedLambo, winners } =
    useComparison();

  // Era-rival suggestions: shown below each selector once a car is picked.
  const ferrariRivalSuggestion = useMemo<CarModel | null>(
    () => (selectedFerrari ? eraMatchSuggestion(selectedFerrari, lamboCars) : null),
    [selectedFerrari, lamboCars],
  );

  const lamboRivalSuggestion = useMemo<CarModel | null>(
    () => (selectedLambo ? eraMatchSuggestion(selectedLambo, ferrariCars) : null),
    [selectedLambo, ferrariCars],
  );

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500 text-lg">Loading catalogs…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-red-600 text-lg" role="alert">
          {error}
        </p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">Ferrari vs Lamborghini</h1>
          <p className="mt-1 text-gray-500">
            Select one car from each brand for a head-to-head stat comparison.
          </p>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Car selectors */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {/* Ferrari selector */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
            <CarSelector
              label="Ferrari"
              cars={ferrariCars}
              selected={selectedFerrari}
              onSelect={setSelectedFerrari}
              accentClass="text-ferrari-red"
            />
            {/* Era-rival suggestion */}
            {selectedFerrari && ferrariRivalSuggestion && (
              <p className="mt-3 text-xs text-gray-500" aria-live="polite">
                Era rival suggestion:{' '}
                <button
                  type="button"
                  className="text-lambo-yellow underline hover:text-yellow-600 focus:outline-none"
                  onClick={() => setSelectedLambo(ferrariRivalSuggestion)}
                >
                  {ferrariRivalSuggestion.year} {ferrariRivalSuggestion.model}
                </button>
              </p>
            )}
            {selectedFerrari && !ferrariRivalSuggestion && (
              <p className="mt-3 text-xs text-gray-400" aria-live="polite">
                No era-rival suggestion available for this model.
              </p>
            )}
          </div>

          {/* Lamborghini selector */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
            <CarSelector
              label="Lamborghini"
              cars={lamboCars}
              selected={selectedLambo}
              onSelect={setSelectedLambo}
              accentClass="text-lambo-yellow"
            />
            {/* Era-rival suggestion */}
            {selectedLambo && lamboRivalSuggestion && (
              <p className="mt-3 text-xs text-gray-500" aria-live="polite">
                Era rival suggestion:{' '}
                <button
                  type="button"
                  className="text-ferrari-red underline hover:text-red-700 focus:outline-none"
                  onClick={() => setSelectedFerrari(lamboRivalSuggestion)}
                >
                  {lamboRivalSuggestion.year} {lamboRivalSuggestion.model}
                </button>
              </p>
            )}
            {selectedLambo && !lamboRivalSuggestion && (
              <p className="mt-3 text-xs text-gray-400" aria-live="polite">
                No era-rival suggestion available for this model.
              </p>
            )}
          </div>
        </div>

        {/* Comparison panel */}
        <ComparisonView
          ferrari={selectedFerrari}
          lamborghini={selectedLambo}
          stats={winners}
        />
      </main>
    </div>
  );
}
