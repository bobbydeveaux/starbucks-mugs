import { useState, useCallback, useMemo } from 'react';
import { DrinkCatalog } from '../components/DrinkCatalog';
import { FilterBar } from '../components/FilterBar';
import { SearchBox } from '../components/SearchBox';
import { ComparisonPanel } from '../components/ComparisonPanel';
import { useDrinks } from '../hooks/useDrinks';
import type { Drink, ComparisonState, FilterState } from '../types';

export function CostaVsStarbucksPage() {
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
   * Clicking the same drink again deselects it (toggle behaviour).
   */
  const handleSelect = useCallback((drink: Drink) => {
    setComparison(prev => ({
      ...prev,
      [drink.brand]: prev[drink.brand]?.id === drink.id ? null : drink,
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
        {/* Filter controls — FilterBar + SearchBox applied together via useDrinks */}
        <div className="mb-6 flex flex-wrap gap-3 items-center">
          <FilterBar
            category={filter.category}
            onCategoryChange={(category) => setFilter(f => ({ ...f, category }))}
          />
          <SearchBox
            query={filter.query}
            onQueryChange={(query) => setFilter(f => ({ ...f, query }))}
          />
        </div>

        {/* Drink catalog — two brand sections with selection wiring */}
        <DrinkCatalog drinks={drinks} selectedIds={selectedIds} onSelect={handleSelect} />

        {/* Comparison panel — shown once at least one drink is selected */}
        <ComparisonPanel
          starbucksDrink={comparison.starbucks}
          costaDrink={comparison.costa}
          onClear={handleClearComparison}
        />
      </main>
    </div>
  );
}
