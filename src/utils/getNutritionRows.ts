import type { Drink, NutritionRow } from '../types'

/**
 * Transforms two drinks (one Costa, one Starbucks) into a list of labelled
 * comparison rows — one row per nutritional field defined in `DrinkNutrition`.
 *
 * The returned rows are ordered from most impactful / commonly referenced
 * (calories first) to least (caffeine last) to match typical nutrition-label
 * convention.
 */
export function getNutritionRows(costaDrink: Drink, starbucksDrink: Drink): NutritionRow[] {
  return [
    {
      label: 'Calories',
      costaValue: costaDrink.nutrition.calories_kcal,
      starbucksValue: starbucksDrink.nutrition.calories_kcal,
      unit: 'kcal',
    },
    {
      label: 'Sugar',
      costaValue: costaDrink.nutrition.sugar_g,
      starbucksValue: starbucksDrink.nutrition.sugar_g,
      unit: 'g',
    },
    {
      label: 'Fat',
      costaValue: costaDrink.nutrition.fat_g,
      starbucksValue: starbucksDrink.nutrition.fat_g,
      unit: 'g',
    },
    {
      label: 'Protein',
      costaValue: costaDrink.nutrition.protein_g,
      starbucksValue: starbucksDrink.nutrition.protein_g,
      unit: 'g',
    },
    {
      label: 'Caffeine',
      costaValue: costaDrink.nutrition.caffeine_mg,
      starbucksValue: starbucksDrink.nutrition.caffeine_mg,
      unit: 'mg',
    },
  ]
}
