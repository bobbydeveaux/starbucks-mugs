import type { ComparisonState } from '../types';
import { getNutritionRows } from '../utils/getNutritionRows';

interface ComparisonPanelProps {
  comparison: ComparisonState;
  onClear: () => void;
}

/**
 * Side-by-side nutritional comparison panel for one Costa and one Starbucks drink.
 *
 * Renders nothing when fewer than two drinks are selected.
 * Shows a guard message when both selected drinks are from the same brand.
 * Renders a full nutrition table and a clear/reset button when valid.
 */
export function ComparisonPanel({ comparison, onClear }: ComparisonPanelProps) {
  const { starbucks, costa } = comparison;

  // Render nothing until at least one drink is selected
  if (!starbucks && !costa) {
    return null;
  }

  // Guard: both slots filled but same brand — can't happen with the current
  // state model (each brand has its own slot) but guard defensively.
  const bothSameBrand =
    starbucks !== null &&
    costa !== null &&
    starbucks.brand === costa.brand;

  const hasFullComparison = starbucks !== null && costa !== null;

  return (
    <section
      aria-label="Drink comparison panel"
      className="mt-10 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-xl font-bold text-gray-900">Comparison</h2>
        <button
          type="button"
          onClick={onClear}
          className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-gray-400 rounded"
          aria-label="Clear comparison and deselect both drinks"
        >
          Clear
        </button>
      </div>

      {/* Drink headers */}
      <div className="grid grid-cols-3 gap-0 border-b border-gray-100">
        <div className="px-6 py-4 bg-gray-50">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Nutrient</p>
        </div>
        <div className="px-6 py-4 bg-costa-light text-center border-l border-gray-100">
          <p className="text-xs font-semibold uppercase tracking-wide text-costa">Costa Coffee</p>
          {costa ? (
            <p className="mt-1 text-sm font-medium text-gray-900 truncate" title={costa.name}>
              {costa.name}
            </p>
          ) : (
            <p className="mt-1 text-sm text-gray-400">No drink selected</p>
          )}
        </div>
        <div className="px-6 py-4 bg-starbucks-light text-center border-l border-gray-100">
          <p className="text-xs font-semibold uppercase tracking-wide text-starbucks">Starbucks</p>
          {starbucks ? (
            <p className="mt-1 text-sm font-medium text-gray-900 truncate" title={starbucks.name}>
              {starbucks.name}
            </p>
          ) : (
            <p className="mt-1 text-sm text-gray-400">No drink selected</p>
          )}
        </div>
      </div>

      {/* Same-brand guard */}
      {bothSameBrand && (
        <div
          role="alert"
          className="px-6 py-5 text-center text-sm text-amber-700 bg-amber-50"
        >
          Both selected drinks are from the same brand. Please select one Costa and one
          Starbucks drink to compare them.
        </div>
      )}

      {/* Prompt when only one drink is selected */}
      {!hasFullComparison && !bothSameBrand && (
        <div className="px-6 py-5 text-center text-sm text-gray-500">
          Select one drink from each brand to see a full nutrition comparison.
        </div>
      )}

      {/* Nutrition rows */}
      {hasFullComparison && !bothSameBrand && (() => {
        const rows = getNutritionRows(costa!, starbucks!);
        return (
          <dl>
            {rows.map((row, index) => {
              const costaWins = row.costaValue < row.starbucksValue;
              const starbucksWins = row.starbucksValue < row.costaValue;

              return (
                <div
                  key={row.label}
                  className={[
                    'grid grid-cols-3 gap-0',
                    index % 2 === 0 ? 'bg-white' : 'bg-gray-50',
                  ].join(' ')}
                >
                  {/* Nutrient label */}
                  <dt className="px-6 py-3 text-sm font-medium text-gray-700 flex items-center">
                    {row.label}
                  </dt>

                  {/* Costa value */}
                  <dd
                    className={[
                      'px-6 py-3 text-sm text-center border-l border-gray-100 flex items-center justify-center gap-1',
                      costaWins ? 'font-bold text-costa' : 'text-gray-700',
                    ].join(' ')}
                    aria-label={`Costa: ${row.costaValue} ${row.unit}`}
                  >
                    <span>{row.costaValue}</span>
                    <span className="text-xs text-gray-400">{row.unit}</span>
                    {costaWins && (
                      <span className="ml-1 text-xs font-normal text-costa" aria-label="lower value">
                        ↓
                      </span>
                    )}
                  </dd>

                  {/* Starbucks value */}
                  <dd
                    className={[
                      'px-6 py-3 text-sm text-center border-l border-gray-100 flex items-center justify-center gap-1',
                      starbucksWins ? 'font-bold text-starbucks' : 'text-gray-700',
                    ].join(' ')}
                    aria-label={`Starbucks: ${row.starbucksValue} ${row.unit}`}
                  >
                    <span>{row.starbucksValue}</span>
                    <span className="text-xs text-gray-400">{row.unit}</span>
                    {starbucksWins && (
                      <span className="ml-1 text-xs font-normal text-starbucks" aria-label="lower value">
                        ↓
                      </span>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        );
      })()}
    </section>
  );
}

export default ComparisonPanel;
