import type { Drink } from '../types';

/** A single comparison row for one nutritional field */
export interface NutritionRow {
  /** Human-readable field name, e.g. "Calories" */
  label: string;
  /** Unit string appended after each value, e.g. "kcal" */
  unit: string;
  starbucksValue: number;
  costaValue: number;
}

/**
 * Produces a comparison row for every nutritional field defined in DrinkNutrition.
 *
 * @param starbucksDrink - The selected Starbucks drink.
 * @param costaDrink     - The selected Costa drink.
 * @returns Array of labelled nutrition rows, one per field.
 *
 * @example
 * const rows = getNutritionRows(starbucksDrink, costaDrink);
 * // [{ label: 'Calories', unit: 'kcal', starbucksValue: 160, costaValue: 144 }, ...]
 */
export function getNutritionRows(starbucksDrink: Drink, costaDrink: Drink): NutritionRow[] {
  return [
    {
      label: 'Calories',
      unit: 'kcal',
      starbucksValue: starbucksDrink.nutrition.calories_kcal,
      costaValue: costaDrink.nutrition.calories_kcal,
    },
    {
      label: 'Sugar',
      unit: 'g',
      starbucksValue: starbucksDrink.nutrition.sugar_g,
      costaValue: costaDrink.nutrition.sugar_g,
    },
    {
      label: 'Fat',
      unit: 'g',
      starbucksValue: starbucksDrink.nutrition.fat_g,
      costaValue: costaDrink.nutrition.fat_g,
    },
    {
      label: 'Protein',
      unit: 'g',
      starbucksValue: starbucksDrink.nutrition.protein_g,
      costaValue: costaDrink.nutrition.protein_g,
    },
    {
      label: 'Caffeine',
      unit: 'mg',
      starbucksValue: starbucksDrink.nutrition.caffeine_mg,
      costaValue: costaDrink.nutrition.caffeine_mg,
    },
  ];
}
