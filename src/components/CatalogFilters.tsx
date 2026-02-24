import { EraFilter } from './EraFilter';
import { SearchBar } from './SearchBar';

interface CatalogFiltersProps {
  /** Currently active decade filter (undefined = all) */
  era: number | undefined;
  /** Called when the user selects or clears a decade */
  onEraChange: (decade: number | undefined) => void;
  /** Current (un-debounced) search input value */
  searchValue: string;
  /** Called on every search keystroke; debouncing is handled by useCarCatalog */
  onSearchChange: (query: string) => void;
}

/**
 * Composite filter bar combining the EraFilter decade-selector and the
 * SearchBar model-name input. Intended to be rendered above the car grids
 * on pages that consume `useCarCatalog`.
 */
export function CatalogFilters({
  era,
  onEraChange,
  searchValue,
  onSearchChange,
}: CatalogFiltersProps) {
  const isFiltered = era !== undefined || searchValue.trim() !== '';

  return (
    <section
      aria-label="Catalog filters"
      className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 space-y-4"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Filter Cars</h2>
        {isFiltered && (
          <button
            type="button"
            onClick={() => {
              onEraChange(undefined);
              onSearchChange('');
            }}
            className="text-sm text-ferrari-red hover:text-red-700 font-medium focus:outline-none focus:underline"
          >
            Clear all filters
          </button>
        )}
      </div>

      <SearchBar
        value={searchValue}
        onChange={onSearchChange}
        placeholder="Search model names…"
      />

      <EraFilter value={era} onChange={onEraChange} />
    </section>
  );
}
