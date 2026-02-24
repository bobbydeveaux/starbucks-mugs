import { describe, it, expect } from 'vitest';
import { getNutritionRows } from './getNutritionRows';
import type { NutritionRow } from './getNutritionRows';
import type { Drink } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sbuxFlatWhite: Drink = {
  id: 'sbux-flat-white',
  brand: 'starbucks',
  name: 'Flat White',
  category: 'hot',
  size_ml: 354,
  image: '/images/sbux-flat-white.webp',
  nutrition: {
    calories_kcal: 160,
    sugar_g: 14,
    fat_g: 6,
    protein_g: 9,
    caffeine_mg: 130,
  },
};

const costaAmericano: Drink = {
  id: 'costa-americano',
  brand: 'costa',
  name: 'Americano',
  category: 'hot',
  size_ml: 354,
  image: '/images/costa-americano.webp',
  nutrition: {
    calories_kcal: 140,
    sugar_g: 10,
    fat_g: 4,
    protein_g: 7,
    caffeine_mg: 185,
  },
};

/** Drink with equal nutrition to sbuxFlatWhite for tie testing */
const costaIdentical: Drink = {
  id: 'costa-identical',
  brand: 'costa',
  name: 'Identical Drink',
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

/** Drink with zero nutrition values */
const costaZero: Drink = {
  id: 'costa-zero',
  brand: 'costa',
  name: 'Zero Drink',
  category: 'iced',
  size_ml: 200,
  nutrition: {
    calories_kcal: 0,
    sugar_g: 0,
    fat_g: 0,
    protein_g: 0,
    caffeine_mg: 0,
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('getNutritionRows', () => {
  // -------------------------------------------------------------------------
  // Row structure
  // -------------------------------------------------------------------------

  it('returns exactly 5 rows', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    expect(rows).toHaveLength(5);
  });

  it('returns rows in order: Calories, Sugar, Fat, Protein, Caffeine', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const labels = rows.map((r) => r.label);
    expect(labels).toEqual(['Calories', 'Sugar', 'Fat', 'Protein', 'Caffeine']);
  });

  it('returns rows with correct keys', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const keys = rows.map((r) => r.key);
    expect(keys).toEqual([
      'calories_kcal',
      'sugar_g',
      'fat_g',
      'protein_g',
      'caffeine_mg',
    ]);
  });

  it('returns rows with correct units', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const units = rows.map((r) => r.unit);
    expect(units).toEqual(['kcal', 'g', 'g', 'g', 'mg']);
  });

  // -------------------------------------------------------------------------
  // Numeric values
  // -------------------------------------------------------------------------

  it('extracts starbucksValue from the starbucks drink nutrition', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.starbucksValue).toBe(160);
  });

  it('extracts costaValue from the costa drink nutrition', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.costaValue).toBe(140);
  });

  it('extracts all starbucks nutrition values correctly', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    expect(rows[0].starbucksValue).toBe(160); // calories_kcal
    expect(rows[1].starbucksValue).toBe(14);  // sugar_g
    expect(rows[2].starbucksValue).toBe(6);   // fat_g
    expect(rows[3].starbucksValue).toBe(9);   // protein_g
    expect(rows[4].starbucksValue).toBe(130); // caffeine_mg
  });

  it('extracts all costa nutrition values correctly', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    expect(rows[0].costaValue).toBe(140); // calories_kcal
    expect(rows[1].costaValue).toBe(10);  // sugar_g
    expect(rows[2].costaValue).toBe(4);   // fat_g
    expect(rows[3].costaValue).toBe(7);   // protein_g
    expect(rows[4].costaValue).toBe(185); // caffeine_mg
  });

  // -------------------------------------------------------------------------
  // maxValue (bar scaling)
  // -------------------------------------------------------------------------

  it('sets maxValue to the higher of the two values', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    // sbux: 160, costa: 140 → max = 160
    expect(caloriesRow.maxValue).toBe(160);
  });

  it('sets maxValue to costaValue when costa is higher', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caffeineRow = rows.find((r) => r.key === 'caffeine_mg')!;
    // sbux: 130, costa: 185 → max = 185
    expect(caffeineRow.maxValue).toBe(185);
  });

  it('sets maxValue to the shared value when both values are equal', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaIdentical);
    rows.forEach((row: NutritionRow) => {
      expect(row.maxValue).toBe(Math.max(row.starbucksValue, row.costaValue));
      expect(row.maxValue).toBe(row.starbucksValue);
    });
  });

  it('sets maxValue to 0 when both drinks have zero nutrition', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaZero);
    // starbucks has non-zero values so max won't be 0 — check the zero scenario
    const sbuxZero: Drink = {
      ...sbuxFlatWhite,
      nutrition: { calories_kcal: 0, sugar_g: 0, fat_g: 0, protein_g: 0, caffeine_mg: 0 },
    };
    const zeroRows = getNutritionRows(sbuxZero, costaZero);
    zeroRows.forEach((row: NutritionRow) => {
      expect(row.maxValue).toBe(0);
    });
  });

  // -------------------------------------------------------------------------
  // Null starbucks drink
  // -------------------------------------------------------------------------

  it('defaults starbucksValue to 0 when starbucksDrink is null', () => {
    const rows = getNutritionRows(null, costaAmericano);
    rows.forEach((row: NutritionRow) => {
      expect(row.starbucksValue).toBe(0);
    });
  });

  it('uses costaValue as maxValue when starbucksDrink is null', () => {
    const rows = getNutritionRows(null, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.maxValue).toBe(140);
  });

  it('includes "not selected" in ariaLabel for the missing starbucks drink', () => {
    const rows = getNutritionRows(null, costaAmericano);
    rows.forEach((row: NutritionRow) => {
      expect(row.ariaLabel).toContain('not selected');
    });
  });

  // -------------------------------------------------------------------------
  // Null costa drink
  // -------------------------------------------------------------------------

  it('defaults costaValue to 0 when costaDrink is null', () => {
    const rows = getNutritionRows(sbuxFlatWhite, null);
    rows.forEach((row: NutritionRow) => {
      expect(row.costaValue).toBe(0);
    });
  });

  it('uses starbucksValue as maxValue when costaDrink is null', () => {
    const rows = getNutritionRows(sbuxFlatWhite, null);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.maxValue).toBe(160);
  });

  it('includes "not selected" in ariaLabel for the missing costa drink', () => {
    const rows = getNutritionRows(sbuxFlatWhite, null);
    rows.forEach((row: NutritionRow) => {
      expect(row.ariaLabel).toContain('not selected');
    });
  });

  // -------------------------------------------------------------------------
  // Both drinks null
  // -------------------------------------------------------------------------

  it('returns 5 rows with all-zero values when both drinks are null', () => {
    const rows = getNutritionRows(null, null);
    expect(rows).toHaveLength(5);
    rows.forEach((row: NutritionRow) => {
      expect(row.starbucksValue).toBe(0);
      expect(row.costaValue).toBe(0);
      expect(row.maxValue).toBe(0);
    });
  });

  it('includes "not selected" twice in ariaLabel when both drinks are null', () => {
    const rows = getNutritionRows(null, null);
    rows.forEach((row: NutritionRow) => {
      const matches = row.ariaLabel.match(/not selected/g);
      expect(matches).toHaveLength(2);
    });
  });

  // -------------------------------------------------------------------------
  // ariaLabel format (WCAG compliance)
  // -------------------------------------------------------------------------

  it('produces correct ariaLabel for calories row', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.ariaLabel).toBe(
      'Calories: 160 kcal for Flat White, 140 kcal for Americano',
    );
  });

  it('produces correct ariaLabel for caffeine row', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caffeineRow = rows.find((r) => r.key === 'caffeine_mg')!;
    expect(caffeineRow.ariaLabel).toBe(
      'Caffeine: 130 mg for Flat White, 185 mg for Americano',
    );
  });

  it('ariaLabel starts with the nutrient label', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const labelPrefixes = rows.map((r) => r.ariaLabel.startsWith(r.label));
    expect(labelPrefixes.every(Boolean)).toBe(true);
  });

  it('ariaLabel contains both drink names when both drinks are provided', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    rows.forEach((row: NutritionRow) => {
      expect(row.ariaLabel).toContain('Flat White');
      expect(row.ariaLabel).toContain('Americano');
    });
  });

  it('ariaLabel contains the unit for each nutrient', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    rows.forEach((row: NutritionRow) => {
      expect(row.ariaLabel).toContain(row.unit);
    });
  });

  it('ariaLabel contains numeric values', () => {
    const rows = getNutritionRows(sbuxFlatWhite, costaAmericano);
    const caloriesRow = rows.find((r) => r.key === 'calories_kcal')!;
    expect(caloriesRow.ariaLabel).toContain('160');
    expect(caloriesRow.ariaLabel).toContain('140');
  });
});
