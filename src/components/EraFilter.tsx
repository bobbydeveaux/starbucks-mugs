interface EraFilterProps {
  /** Currently selected decade, or null for "All Eras" */
  era: number | null;
  /** Sorted list of available decades derived from the catalog data */
  availableDecades: number[];
  /** Called when the user selects or clears a decade */
  onChange: (era: number | null) => void;
}

/**
 * Renders a row of decade-selector buttons that filter the car catalog by era.
 *
 * The active decade is highlighted in ferrari-red. "All Eras" deselects any
 * active era filter.
 *
 * @example
 * <EraFilter era={selectedEra} availableDecades={[1960, 1970, 1980]} onChange={setEra} />
 */
export function EraFilter({ era, availableDecades, onChange }: EraFilterProps) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
        Era
      </label>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by era">
        <button
          type="button"
          onClick={() => onChange(null)}
          className={[
            'px-3 py-1.5 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-ferrari-red',
            era === null
              ? 'bg-ferrari-red text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200',
          ].join(' ')}
          aria-pressed={era === null}
        >
          All Eras
        </button>

        {availableDecades.map((decade) => (
          <button
            key={decade}
            type="button"
            onClick={() => onChange(decade === era ? null : decade)}
            className={[
              'px-3 py-1.5 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-ferrari-red',
              era === decade
                ? 'bg-ferrari-red text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200',
            ].join(' ')}
            aria-pressed={era === decade}
          >
            {decade}s
          </button>
        ))}
      </div>
    </div>
  );
}

export default EraFilter;
