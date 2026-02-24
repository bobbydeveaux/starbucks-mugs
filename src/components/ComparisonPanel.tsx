import type { Drink } from '../types';
import { NutritionBar } from './NutritionBar';

interface ComparisonPanelProps {
  /** Selected Starbucks drink, or null if none selected */
  starbucks: Drink | null;
  /** Selected Costa drink, or null if none selected */
  costa: Drink | null;
  /** Callback to clear both selections */
  onClear: () => void;
}

interface NutritionRow {
  label: string;
  key: keyof Drink['nutrition'];
  unit: string;
}

const NUTRITION_ROWS: NutritionRow[] = [
  { label: 'Calories', key: 'calories_kcal', unit: 'kcal' },
  { label: 'Sugar', key: 'sugar_g', unit: 'g' },
  { label: 'Fat', key: 'fat_g', unit: 'g' },
  { label: 'Protein', key: 'protein_g', unit: 'g' },
  { label: 'Caffeine', key: 'caffeine_mg', unit: 'mg' },
];

/**
 * ComparisonPanel displays a side-by-side nutritional comparison of one Costa
 * drink and one Starbucks drink. Each nutritional field is visualised with a
 * NutritionBar so users can compare values at a glance.
 *
 * Renders nothing when both selections are null.
 */
export function ComparisonPanel({ starbucks, costa, onClear }: ComparisonPanelProps) {
  if (!starbucks && !costa) return null;

  const bothSelected = starbucks !== null && costa !== null;

  return (
    <section
      aria-label="Nutrition comparison"
      className="mt-10 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden"
    >
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">Nutrition comparison</h2>
        <button
          type="button"
          onClick={onClear}
          className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-gray-400 rounded"
        >
          Clear
        </button>
      </div>

      {/* Drink name headers */}
      <div className="grid grid-cols-[6rem_1fr] gap-0">
        <div className="px-6 py-3 bg-gray-50 border-b border-gray-100" />
        <div className="grid grid-cols-2 border-b border-gray-100">
          <div className="px-4 py-3 bg-costa-light border-r border-gray-100">
            <p className="text-xs font-semibold uppercase tracking-wide text-costa">Costa</p>
            {costa ? (
              <p className="text-sm font-medium text-gray-900 truncate">{costa.name}</p>
            ) : (
              <p className="text-sm text-gray-400 italic">Not selected</p>
            )}
          </div>
          <div className="px-4 py-3 bg-starbucks-light">
            <p className="text-xs font-semibold uppercase tracking-wide text-starbucks">Starbucks</p>
            {starbucks ? (
              <p className="text-sm font-medium text-gray-900 truncate">{starbucks.name}</p>
            ) : (
              <p className="text-sm text-gray-400 italic">Not selected</p>
            )}
          </div>
        </div>
      </div>

      {/* Prompt when only one brand is selected */}
      {!bothSelected && (
        <p className="px-6 py-4 text-sm text-gray-500 text-center">
          Select a drink from the other brand to see a full comparison.
        </p>
      )}

      {/* Nutrition rows — only shown when both drinks are selected */}
      {bothSelected && (
        <dl>
          {NUTRITION_ROWS.map(({ label, key, unit }, idx) => {
            const costaValue = costa!.nutrition[key];
            const starbucksValue = starbucks!.nutrition[key];
            const isEven = idx % 2 === 0;

            return (
              <div
                key={key}
                className={`grid grid-cols-[6rem_1fr] gap-0 border-b border-gray-100 last:border-b-0 ${
                  isEven ? 'bg-white' : 'bg-gray-50/50'
                }`}
              >
                {/* Nutrient label */}
                <div className="px-6 py-3 flex items-center">
                  <dt className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                    {label}
                  </dt>
                </div>

                {/* Bar chart + values */}
                <div className="px-4 py-2">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="w-14 text-right text-sm font-medium text-costa shrink-0">
                      {costaValue}
                      <span className="text-xs font-normal text-gray-400 ml-0.5">{unit}</span>
                    </span>
                    <div className="flex-1">
                      <NutritionBar
                        costaValue={costaValue}
                        starbucksValue={starbucksValue}
                        unit={unit}
                      />
                    </div>
                    <span className="w-14 text-left text-sm font-medium text-starbucks shrink-0">
                      {starbucksValue}
                      <span className="text-xs font-normal text-gray-400 ml-0.5">{unit}</span>
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

export default ComparisonPanel;
