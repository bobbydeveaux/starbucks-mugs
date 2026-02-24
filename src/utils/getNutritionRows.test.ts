import { describe, it, expect } from 'vitest';
import { getNutritionRows } from './getNutritionRows';
import type { Drink } from '../types';

const starbucksDrink: Drink = {
  id: 'sbux-flat-white',
  brand: 'starbucks',
  name: 'Flat White',
  category: 'hot',
  size_ml: 354,
  nutrition: {
    calories_kcal: 160,
    sugar_g: 14,
    fat_g: 6,
    protein_g: 9,
    caffeine_mg: 130,
  },
};

const costaDrink: Drink = {
  id: 'costa-flat-white',
  brand: 'costa',
  name: 'Flat White',
  category: 'hot',
  size_ml: 300,
  nutrition: {
    calories_kcal: 144,
    sugar_g: 12,
    fat_g: 8,
    protein_g: 8,
    caffeine_mg: 185,
  },
};

describe('getNutritionRows', () => {
  it('returns exactly 5 rows (one per nutritional field)', () => {
    const rows = getNutritionRows(starbucksDrink, costaDrink);
    expect(rows).toHaveLength(5);
  });

  it('returns rows with the correct labels in order', () => {
    const rows = getNutritionRows(starbucksDrink, costaDrink);
    expect(rows.map((r) => r.label)).toEqual([
      'Calories',
      'Sugar',
      'Fat',
      'Protein',
      'Caffeine',
    ]);
  });

  it('returns rows with the correct units', () => {
    const rows = getNutritionRows(starbucksDrink, costaDrink);
    expect(rows.map((r) => r.unit)).toEqual(['kcal', 'g', 'g', 'g', 'mg']);
  });

  it('maps starbucksValue correctly for each field', () => {
    const rows = getNutritionRows(starbucksDrink, costaDrink);
    expect(rows[0].starbucksValue).toBe(160); // calories
    expect(rows[1].starbucksValue).toBe(14);  // sugar
    expect(rows[2].starbucksValue).toBe(6);   // fat
    expect(rows[3].starbucksValue).toBe(9);   // protein
    expect(rows[4].starbucksValue).toBe(130); // caffeine
  });

  it('maps costaValue correctly for each field', () => {
    const rows = getNutritionRows(starbucksDrink, costaDrink);
    expect(rows[0].costaValue).toBe(144); // calories
    expect(rows[1].costaValue).toBe(12);  // sugar
    expect(rows[2].costaValue).toBe(8);   // fat
    expect(rows[3].costaValue).toBe(8);   // protein
    expect(rows[4].costaValue).toBe(185); // caffeine
  });

  it('handles drinks with zero values without error', () => {
    const zeroDrink: Drink = {
      id: 'sbux-water',
      brand: 'starbucks',
      name: 'Water',
      category: 'other',
      size_ml: 500,
      nutrition: { calories_kcal: 0, sugar_g: 0, fat_g: 0, protein_g: 0, caffeine_mg: 0 },
    };
    const rows = getNutritionRows(zeroDrink, costaDrink);
    expect(rows).toHaveLength(5);
    rows.forEach((r) => expect(r.starbucksValue).toBe(0));
  });
});
