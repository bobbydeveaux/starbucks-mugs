import { EraFilter } from './EraFilter';
import { SearchBar } from './SearchBar';

interface CatalogFiltersProps {
  /** Currently selected decade filter, or null for all eras */
  era: number | null;
  /** Sorted list of available decades */
  availableDecades: number[];
  /** Called when the era filter changes */
  onEraChange: (era: number | null) => void;
  /** Current raw search query */
  search: string;
  /** Called when the search query changes */
  onSearchChange: (search: string) => void;
}

/**
 * Wrapper that renders the EraFilter and SearchBar side by side, providing a
 * unified filter bar for the car catalog pages.
 *
 * @example
 * <CatalogFilters
 *   era={era}
 *   availableDecades={availableDecades}
 *   onEraChange={setEra}
 *   search={search}
 *   onSearchChange={setSearch}
 * />
 */
export function CatalogFilters({
  era,
  availableDecades,
  onEraChange,
  search,
  onSearchChange,
}: CatalogFiltersProps) {
  const hasActiveFilters = era !== null || search.trim() !== '';

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        {/* Era filter takes up most of the space */}
        <div className="flex-1">
          <EraFilter era={era} availableDecades={availableDecades} onChange={onEraChange} />
        </div>

        {/* Search bar on the right */}
        <div className="w-full sm:w-64">
          <SearchBar value={search} onChange={onSearchChange} />
        </div>
      </div>

      {/* Clear all filters link — only shown when a filter is active */}
      {hasActiveFilters && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={() => {
              onEraChange(null);
              onSearchChange('');
            }}
            className="text-xs text-gray-500 underline hover:text-ferrari-red focus:outline-none focus:text-ferrari-red transition-colors"
          >
            Clear all filters
          </button>
        </div>
      )}
    </div>
  );
}

export default CatalogFilters;
