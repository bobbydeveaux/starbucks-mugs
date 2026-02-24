interface EraFilterProps {
  /** Currently selected decade, or undefined for "All" */
  value: number | undefined;
  /** Called when the user selects or clears a decade */
  onChange: (decade: number | undefined) => void;
  /** Ordered list of decade values to display as buttons */
  decades?: number[];
}

const DEFAULT_DECADES = [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020];

/**
 * Decade-selector filter for the car catalog.
 *
 * Renders an "All" button plus one button per decade. The active decade is
 * highlighted using the ferrari-red / lambo-yellow brand tokens alternately,
 * defaulting to ferrari-red. Clicking the active decade deselects it (restores
 * "All").
 */
export function EraFilter({
  value,
  onChange,
  decades = DEFAULT_DECADES,
}: EraFilterProps) {
  const handleClick = (decade: number) => {
    // Toggle off if already selected
    onChange(value === decade ? undefined : decade);
  };

  return (
    <fieldset>
      <legend className="text-sm font-medium text-gray-700 mb-2">Filter by Era</legend>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Era filter">
        <button
          type="button"
          onClick={() => onChange(undefined)}
          aria-pressed={value === undefined}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-ferrari-red ${
            value === undefined
              ? 'bg-ferrari-red text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          All
        </button>
        {decades.map((decade) => (
          <button
            key={decade}
            type="button"
            onClick={() => handleClick(decade)}
            aria-pressed={value === decade}
            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-ferrari-red ${
              value === decade
                ? 'bg-ferrari-red text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {decade}s
          </button>
        ))}
      </div>
    </fieldset>
  );
}
