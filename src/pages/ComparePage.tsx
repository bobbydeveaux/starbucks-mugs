import { useCarCatalog } from '../hooks/useCarCatalog';
import { CatalogFilters } from '../components/CatalogFilters';

/** Head-to-head car comparison page with era and search filtering. */
export function ComparePage() {
  const {
    filteredFerraris,
    filteredLambos,
    loading,
    error,
    era,
    setEra,
    setSearch,
    searchValue,
  } = useCarCatalog();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">Ferrari vs Lamborghini</h1>
          <p className="mt-1 text-gray-500">
            Select one car from each brand for a head-to-head stat comparison.
          </p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <CatalogFilters
          era={era}
          onEraChange={setEra}
          searchValue={searchValue}
          onSearchChange={setSearch}
        />

        {loading && (
          <p className="text-gray-500 text-center py-8" aria-live="polite">
            Loading cars…
          </p>
        )}

        {error && (
          <div role="alert" className="bg-red-50 border border-red-200 rounded-md p-4">
            <p className="text-red-700">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Ferrari column */}
            <section aria-label="Ferrari catalog">
              <h2 className="text-xl font-bold text-ferrari-red mb-3">
                Ferrari{' '}
                <span className="text-sm font-normal text-gray-500">
                  ({filteredFerraris.length} models)
                </span>
              </h2>
              {filteredFerraris.length === 0 ? (
                <p className="text-gray-400 italic">No Ferrari models match your filters.</p>
              ) : (
                <ul className="space-y-2">
                  {filteredFerraris.map((car) => (
                    <li
                      key={car.id}
                      className="bg-white rounded-lg border border-gray-200 px-4 py-3 flex items-center justify-between"
                    >
                      <div>
                        <span className="font-medium text-gray-900">{car.model}</span>
                        <span className="ml-2 text-sm text-gray-500">{car.year}</span>
                      </div>
                      <span className="text-xs text-gray-400">{car.specs.hp} hp</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Lamborghini column */}
            <section aria-label="Lamborghini catalog">
              <h2 className="text-xl font-bold text-lambo-yellow mb-3">
                Lamborghini{' '}
                <span className="text-sm font-normal text-gray-500">
                  ({filteredLambos.length} models)
                </span>
              </h2>
              {filteredLambos.length === 0 ? (
                <p className="text-gray-400 italic">No Lamborghini models match your filters.</p>
              ) : (
                <ul className="space-y-2">
                  {filteredLambos.map((car) => (
                    <li
                      key={car.id}
                      className="bg-white rounded-lg border border-gray-200 px-4 py-3 flex items-center justify-between"
                    >
                      <div>
                        <span className="font-medium text-gray-900">{car.model}</span>
                        <span className="ml-2 text-sm text-gray-500">{car.year}</span>
                      </div>
                      <span className="text-xs text-gray-400">{car.specs.hp} hp</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
