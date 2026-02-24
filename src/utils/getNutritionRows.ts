import type { Drink } from '../types';

/** A single row in the side-by-side nutrition comparison table */
export interface NutritionRow {
  label: string;
  costaValue: number;
  starbucksValue: number;
  unit: string;
}

/**
 * Builds an ordered list of nutrition comparison rows from two drinks.
 *
 * @param costa    - The selected Costa drink.
 * @param starbucks - The selected Starbucks drink.
 * @returns An array of {@link NutritionRow} objects covering all nutritional fields.
 *
 * @example
 * const rows = getNutritionRows(costaDrink, starbucksDrink);
 * // [{ label: 'Calories', costaValue: 144, starbucksValue: 160, unit: 'kcal' }, ...]
 */
export function getNutritionRows(costa: Drink, starbucks: Drink): NutritionRow[] {
  return [
    {
      label: 'Calories',
      costaValue: costa.nutrition.calories_kcal,
      starbucksValue: starbucks.nutrition.calories_kcal,
      unit: 'kcal',
    },
    {
      label: 'Sugar',
      costaValue: costa.nutrition.sugar_g,
      starbucksValue: starbucks.nutrition.sugar_g,
      unit: 'g',
    },
    {
      label: 'Fat',
      costaValue: costa.nutrition.fat_g,
      starbucksValue: starbucks.nutrition.fat_g,
      unit: 'g',
    },
    {
      label: 'Protein',
      costaValue: costa.nutrition.protein_g,
      starbucksValue: starbucks.nutrition.protein_g,
      unit: 'g',
    },
    {
      label: 'Caffeine',
      costaValue: costa.nutrition.caffeine_mg,
      starbucksValue: starbucks.nutrition.caffeine_mg,
      unit: 'mg',
    },
  ];
}
