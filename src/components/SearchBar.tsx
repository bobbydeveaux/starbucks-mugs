interface SearchBarProps {
  /** Current search value (controlled) */
  value: string;
  /** Called on every keystroke; filtering is debounced inside useCarCatalog */
  onChange: (value: string) => void;
  /** Optional placeholder text */
  placeholder?: string;
}

/**
 * Controlled text input for filtering car models by name.
 *
 * The input is a simple controlled component — debouncing happens in the
 * useCarCatalog hook so that `value` and `onChange` stay in sync with the
 * visible input while the actual filter update is throttled.
 *
 * @example
 * <SearchBar value={search} onChange={setSearch} placeholder="Search models…" />
 */
export function SearchBar({
  value,
  onChange,
  placeholder = 'Search models…',
}: SearchBarProps) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="car-search" className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
        Search
      </label>
      <div className="relative">
        {/* Search icon */}
        <span
          className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-gray-400"
          aria-hidden="true"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
            />
          </svg>
        </span>

        <input
          id="car-search"
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-10 text-sm text-gray-900 placeholder:text-gray-400 focus:border-ferrari-red focus:outline-none focus:ring-2 focus:ring-ferrari-red/30 transition-colors"
          aria-label="Search car models"
        />

        {/* Clear button — only shown when there is text */}
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="absolute inset-y-0 right-2 flex items-center px-1 text-gray-400 hover:text-gray-600 focus:outline-none"
            aria-label="Clear search"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

export default SearchBar;
