import type { Drink } from '../types';
import { getNutritionRows } from '../utils/getNutritionRows';

interface ComparisonPanelProps {
  starbucksDrink: Drink | null;
  costaDrink: Drink | null;
  onClear: () => void;
}

/**
 * Renders a side-by-side nutritional comparison of one Starbucks and one Costa drink.
 *
 * - Renders a prompt when fewer than two drinks are selected.
 * - Renders a full side-by-side table once both slots are filled.
 * - Exposes a "Clear" button that calls onClear to reset both selections.
 */
export function ComparisonPanel({ starbucksDrink, costaDrink, onClear }: ComparisonPanelProps) {
  const hasStarbucks = starbucksDrink !== null;
  const hasCosta = costaDrink !== null;
  const hasSelection = hasStarbucks || hasCosta;
  const hasFullComparison = hasStarbucks && hasCosta;

  if (!hasSelection) {
    return null;
  }

  return (
    <section
      aria-label="Drink comparison panel"
      className="mt-10 bg-white rounded-lg shadow-sm border border-gray-200"
    >
      {/* Panel header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <h2 className="text-xl font-bold text-gray-900">Side-by-Side Comparison</h2>
        <button
          type="button"
          onClick={onClear}
          className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-gray-400 rounded"
          aria-label="Clear comparison"
        >
          Clear
        </button>
      </div>

      {/* Drink name header row */}
      <div className="grid grid-cols-3 gap-0 border-b border-gray-100 px-6 py-4">
        <div className="col-start-2 text-center">
          <span className="text-xs font-semibold uppercase tracking-wide text-starbucks">
            Starbucks
          </span>
          {hasStarbucks ? (
            <p className="mt-1 font-semibold text-gray-900 text-sm">{starbucksDrink.name}</p>
          ) : (
            <p className="mt-1 text-sm text-gray-400 italic">Not selected</p>
          )}
        </div>
        <div className="text-center">
          <span className="text-xs font-semibold uppercase tracking-wide text-costa">
            Costa
          </span>
          {hasCosta ? (
            <p className="mt-1 font-semibold text-gray-900 text-sm">{costaDrink.name}</p>
          ) : (
            <p className="mt-1 text-sm text-gray-400 italic">Not selected</p>
          )}
        </div>
      </div>

      {/* Prompt when only one drink is selected */}
      {!hasFullComparison && (
        <p
          className="px-6 py-6 text-sm text-gray-500 text-center"
          role="status"
          aria-live="polite"
        >
          {!hasStarbucks
            ? 'Select a Starbucks drink above to complete the comparison.'
            : 'Select a Costa drink above to complete the comparison.'}
        </p>
      )}

      {/* Full side-by-side nutrition table */}
      {hasFullComparison && (
        <div className="px-6 py-4">
          <table className="w-full text-sm" aria-label="Nutrition comparison">
            <thead className="sr-only">
              <tr>
                <th scope="col">Nutrient</th>
                <th scope="col">Starbucks</th>
                <th scope="col">Costa</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {getNutritionRows(starbucksDrink, costaDrink).map((row) => {
                const sbuxWins = row.starbucksValue < row.costaValue;
                const costaWins = row.costaValue < row.starbucksValue;

                return (
                  <tr key={row.label} className="group">
                    <td className="py-3 text-gray-500 font-medium w-1/3">{row.label}</td>
                    <td
                      className={[
                        'py-3 text-center w-1/3 font-semibold',
                        sbuxWins ? 'text-starbucks' : 'text-gray-700',
                      ].join(' ')}
                    >
                      {row.starbucksValue}
                      <span className="text-xs font-normal text-gray-400 ml-1">{row.unit}</span>
                    </td>
                    <td
                      className={[
                        'py-3 text-center w-1/3 font-semibold',
                        costaWins ? 'text-costa' : 'text-gray-700',
                      ].join(' ')}
                    >
                      {row.costaValue}
                      <span className="text-xs font-normal text-gray-400 ml-1">{row.unit}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <p className="mt-4 text-xs text-gray-400 text-center">
            Lower value highlighted in brand colour where applicable.
          </p>
        </div>
      )}
    </section>
  );
}

export default ComparisonPanel;
