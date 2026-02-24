import { useMemo } from 'react';
import { ComparisonView } from '../components/ComparisonView';
import { useCarCatalog } from '../hooks/useCarCatalog';
import { useComparison } from '../hooks/useComparison';
import { eraMatchSuggestion } from '../utils/eraMatchSuggestion';
import type { CarModel } from '../types';

function CarSelector({
  label,
  cars,
  selectedId,
  onSelect,
  colorClass,
}: {
  label: string;
  cars: CarModel[];
  selectedId: string | null;
  onSelect: (car: CarModel | null) => void;
  colorClass: string;
}) {
  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const value = e.target.value;
    if (!value) {
      onSelect(null);
      return;
    }
    const car = cars.find((c) => c.id === value) ?? null;
    onSelect(car);
  }

  return (
    <div className="flex-1 min-w-0">
      <label htmlFor={`select-${label}`} className={`block text-sm font-semibold mb-1 ${colorClass}`}>
        {label}
      </label>
      <select
        id={`select-${label}`}
        value={selectedId ?? ''}
        onChange={handleChange}
        className="w-full border border-gray-300 rounded px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-gray-400"
        aria-label={`Select a ${label}`}
      >
        <option value="">— Choose a model —</option>
        {cars.map((car) => (
          <option key={car.id} value={car.id}>
            {car.year} {car.model}
          </option>
        ))}
      </select>
    </div>
  );
}

export function ComparePage() {
  const { ferrariCars, lamboCars, loading, error } = useCarCatalog();
  const { selectedFerrari, selectedLambo, setSelectedFerrari, setSelectedLambo, winners } =
    useComparison();

  // Era-rival suggestion: surface the opponent rival closest in year to the
  // most recently selected car. When both are selected, bias toward Ferrari
  // so we suggest a contemporary Lamborghini.
  const eraRivalSuggestion = useMemo(() => {
    if (selectedFerrari && !selectedLambo) {
      return eraMatchSuggestion(selectedFerrari, lamboCars);
    }
    if (selectedLambo && !selectedFerrari) {
      return eraMatchSuggestion(selectedLambo, ferrariCars);
    }
    if (selectedFerrari && selectedLambo) {
      return eraMatchSuggestion(selectedFerrari, lamboCars);
    }
    return null;
  }, [selectedFerrari, selectedLambo, ferrariCars, lamboCars]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500 text-lg">Loading cars…</p>
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
        <div className="flex flex-col sm:flex-row gap-4">
          <CarSelector
            label="Ferrari"
            cars={ferrariCars}
            selectedId={selectedFerrari?.id ?? null}
            onSelect={setSelectedFerrari}
            colorClass="text-ferrari-red"
          />

          {/* Era-rival hint when only Ferrari selected */}
          {selectedFerrari && !selectedLambo && eraRivalSuggestion && (
            <div className="sm:hidden text-xs text-gray-500 -mt-2">
              Suggested rival:{' '}
              <span className="font-medium text-lambo-yellow">
                {eraRivalSuggestion.year} {eraRivalSuggestion.model}
              </span>
            </div>
          )}

          <div className="hidden sm:flex items-end pb-2 px-2">
            <span className="text-xl font-bold text-gray-300">vs</span>
          </div>

          <CarSelector
            label="Lamborghini"
            cars={lamboCars}
            selectedId={selectedLambo?.id ?? null}
            onSelect={setSelectedLambo}
            colorClass="text-lambo-yellow"
          />

          {/* Era-rival hint when only Lambo selected */}
          {selectedLambo && !selectedFerrari && eraRivalSuggestion && (
            <div className="sm:hidden text-xs text-gray-500 -mt-2">
              Suggested rival:{' '}
              <span className="font-medium text-ferrari-red">
                {eraRivalSuggestion.year} {eraRivalSuggestion.model}
              </span>
            </div>
          )}
        </div>

        {/* Era-rival suggestion row (desktop) */}
        {eraRivalSuggestion && (selectedFerrari || selectedLambo) && (
          <p className="hidden sm:block mt-2 text-xs text-gray-500">
            Era-rival suggestion:{' '}
            <span
              className={`font-medium ${
                selectedFerrari && !selectedLambo ? 'text-lambo-yellow' : 'text-ferrari-red'
              }`}
            >
              {eraRivalSuggestion.year} {eraRivalSuggestion.model}
            </span>{' '}
            is a close contemporary from the opposing brand.
          </p>
        )}

        {/* Comparison panel */}
        <ComparisonView
          ferrari={selectedFerrari}
          lambo={selectedLambo}
          winners={winners}
          eraRivalSuggestion={eraRivalSuggestion}
        />
      </main>
    </div>
  );
}
