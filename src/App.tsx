import { useState, useCallback, useMemo } from 'react';
import { DrinkCatalog } from './components/DrinkCatalog';
import { useDrinks } from './hooks/useDrinks';
import type { Drink, ComparisonState, FilterState } from './types';

function App() {
  // --- comparison state: at most one drink per brand ---
  const [comparison, setComparison] = useState<ComparisonState>({
    starbucks: null,
    costa: null,
  });

  // --- filter state: category + free-text search ---
  const [filter, setFilter] = useState<FilterState>({
    category: 'all',
    query: '',
  });

  // --- data layer ---
  const { drinks, loading, error } = useDrinks(filter);

  /**
   * handleSelect — called when the user clicks "Select to Compare" on a DrinkCard.
   *
   * Selecting a drink from brand X replaces any previous selection for that brand.
   * It is impossible to select two drinks from the same brand simultaneously — the
   * second click simply updates the same brand slot (duplicate-brand guard).
   */
  const handleSelect = useCallback((drink: Drink) => {
    setComparison(prev => ({
      ...prev,
      [drink.brand]: drink,
    }));
  }, []);

  /**
   * handleClearComparison — resets both selection slots to null.
   */
  const handleClearComparison = useCallback(() => {
    setComparison({ starbucks: null, costa: null });
  }, []);

  // selectedIds passed to DrinkCatalog so cards can show their highlight state
  const selectedIds = useMemo(() => ({
    starbucks: comparison.starbucks?.id ?? null,
    costa: comparison.costa?.id ?? null,
  }), [comparison.starbucks?.id, comparison.costa?.id]);

  const hasSelection = comparison.starbucks !== null || comparison.costa !== null;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500 text-lg">Loading drinks…</p>
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
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">Costa vs Starbucks</h1>
          <p className="mt-1 text-gray-500">
            Select one drink from each brand and compare them side by side.
          </p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Filter controls (placeholder — wired in feat-filter-search tasks) */}
        <div className="mb-4 flex gap-2 items-center">
          <label htmlFor="search" className="sr-only">
            Search drinks
          </label>
          <input
            id="search"
            type="search"
            placeholder="Search drinks…"
            value={filter.query}
            onChange={e => setFilter(f => ({ ...f, query: e.target.value }))}
            className="border rounded px-3 py-1.5 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-starbucks"
          />
        </div>

        {/* Drink catalog — two brand sections with selection wiring */}
        <DrinkCatalog drinks={drinks} selectedIds={selectedIds} onSelect={handleSelect} />

        {/* Comparison summary — shown once at least one drink is selected */}
        {hasSelection && (
          <section
            aria-label="Current selection"
            className="mt-10 p-6 bg-white rounded-lg shadow-sm border border-gray-200"
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900">Your selection</h2>
              <button
                type="button"
                onClick={handleClearComparison}
                className="text-sm text-gray-500 hover:text-gray-700 underline"
              >
                Clear
              </button>
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-starbucks mb-1">
                  Starbucks
                </p>
                {comparison.starbucks ? (
                  <p className="font-medium text-gray-900">{comparison.starbucks.name}</p>
                ) : (
                  <p className="text-gray-400 text-sm">No drink selected</p>
                )}
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-costa mb-1">
                  Costa
                </p>
                {comparison.costa ? (
                  <p className="font-medium text-gray-900">{comparison.costa.name}</p>
                ) : (
                  <p className="text-gray-400 text-sm">No drink selected</p>
                )}
              </div>
            </div>

            {comparison.starbucks && comparison.costa && (
              <p className="mt-4 text-sm text-gray-500">
                Full nutrition comparison panel coming in the next sprint.
              </p>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
