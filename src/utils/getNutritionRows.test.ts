import { describe, it, expect } from 'vitest';
import { getNutritionRows } from './getNutritionRows';
import type { Drink } from '../types';

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

describe('getNutritionRows', () => {
  it('returns exactly 5 rows', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    expect(rows).toHaveLength(5);
  });

  it('returns rows with labels Calories, Sugar, Fat, Protein, Caffeine in order', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    expect(rows.map(r => r.label)).toEqual(['Calories', 'Sugar', 'Fat', 'Protein', 'Caffeine']);
  });

  it('maps calories_kcal correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    const calories = rows.find(r => r.label === 'Calories')!;
    expect(calories.costaValue).toBe(144);
    expect(calories.starbucksValue).toBe(160);
    expect(calories.unit).toBe('kcal');
  });

  it('maps sugar_g correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    const sugar = rows.find(r => r.label === 'Sugar')!;
    expect(sugar.costaValue).toBe(12);
    expect(sugar.starbucksValue).toBe(14);
    expect(sugar.unit).toBe('g');
  });

  it('maps fat_g correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    const fat = rows.find(r => r.label === 'Fat')!;
    expect(fat.costaValue).toBe(8);
    expect(fat.starbucksValue).toBe(6);
    expect(fat.unit).toBe('g');
  });

  it('maps protein_g correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    const protein = rows.find(r => r.label === 'Protein')!;
    expect(protein.costaValue).toBe(8);
    expect(protein.starbucksValue).toBe(9);
    expect(protein.unit).toBe('g');
  });

  it('maps caffeine_mg correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    const caffeine = rows.find(r => r.label === 'Caffeine')!;
    expect(caffeine.costaValue).toBe(185);
    expect(caffeine.starbucksValue).toBe(130);
    expect(caffeine.unit).toBe('mg');
  });

  it('each row has costaValue, starbucksValue, label, and unit', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink);
    for (const row of rows) {
      expect(row).toHaveProperty('label');
      expect(row).toHaveProperty('costaValue');
      expect(row).toHaveProperty('starbucksValue');
      expect(row).toHaveProperty('unit');
    }
  });
});
