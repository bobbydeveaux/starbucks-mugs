import type { Drink } from '../types';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/**
 * A single row of nutrition comparison data consumed by the ComparisonPanel.
 *
 * Each row covers one nutritional field (calories, sugar, fat, protein, or
 * caffeine) and supplies all the data needed to render a labelled pair of
 * `NutritionBar` components side by side.
 */
export interface NutritionRow {
  /** Nutrition field key from DrinkNutrition, e.g. `'calories_kcal'` */
  key: string;
  /** Human-readable label displayed above the bars, e.g. `'Calories'` */
  label: string;
  /** Unit appended to numeric values, e.g. `'kcal'`, `'g'`, `'mg'` */
  unit: string;
  /** Numeric value for the selected Starbucks drink (0 when none selected) */
  starbucksValue: number;
  /** Numeric value for the selected Costa drink (0 when none selected) */
  costaValue: number;
  /**
   * The higher of `starbucksValue` and `costaValue`.
   *
   * Scale `NutritionBar` widths proportionally to this value so that both
   * bars are always comparable on the same scale. Zero when both values
   * are zero.
   */
  maxValue: number;
  /**
   * WCAG AA-compliant `aria-label` for the `NutritionBar` pair.
   *
   * Format: `"<Label>: <value> <unit> for <drink name>, <value> <unit> for <drink name>"`
   *
   * @example
   * "Calories: 160 kcal for Flat White, 140 kcal for Americano"
   */
  ariaLabel: string;
}

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

type NutritionKey = keyof Drink['nutrition'];

interface NutritionMetric {
  key: NutritionKey;
  label: string;
  unit: string;
}

const NUTRITION_METRICS: NutritionMetric[] = [
  { key: 'calories_kcal', label: 'Calories', unit: 'kcal' },
  { key: 'sugar_g', label: 'Sugar', unit: 'g' },
  { key: 'fat_g', label: 'Fat', unit: 'g' },
  { key: 'protein_g', label: 'Protein', unit: 'g' },
  { key: 'caffeine_mg', label: 'Caffeine', unit: 'mg' },
];

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Builds an array of {@link NutritionRow} objects from two selected drinks.
 *
 * Returns five rows — one per nutritional field — in display order:
 * Calories → Sugar → Fat → Protein → Caffeine.
 *
 * Either argument may be `null` when the user has only selected one drink so
 * far. Values for the absent drink default to `0`.
 *
 * @param starbucksDrink - The currently selected Starbucks drink, or `null`.
 * @param costaDrink - The currently selected Costa drink, or `null`.
 * @returns Array of 5 {@link NutritionRow} objects ready for rendering.
 *
 * @example
 * const rows = getNutritionRows(flatWhiteSbux, flatWhiteCosta);
 * rows[0].label;     // 'Calories'
 * rows[0].ariaLabel; // 'Calories: 160 kcal for Flat White, 140 kcal for Flat White'
 */
export function getNutritionRows(
  starbucksDrink: Drink | null,
  costaDrink: Drink | null,
): NutritionRow[] {
  return NUTRITION_METRICS.map(({ key, label, unit }) => {
    const starbucksValue = starbucksDrink?.nutrition[key] ?? 0;
    const costaValue = costaDrink?.nutrition[key] ?? 0;
    const maxValue = Math.max(starbucksValue, costaValue);

    const starbucksSegment = starbucksDrink
      ? `${starbucksValue} ${unit} for ${starbucksDrink.name}`
      : 'not selected';
    const costaSegment = costaDrink
      ? `${costaValue} ${unit} for ${costaDrink.name}`
      : 'not selected';

    return {
      key,
      label,
      unit,
      starbucksValue,
      costaValue,
      maxValue,
      ariaLabel: `${label}: ${starbucksSegment}, ${costaSegment}`,
    };
  });
}
