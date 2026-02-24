import { describe, it, expect } from 'vitest';
import { filterDrinks } from './filterDrinks';
import type { Drink } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const drinks: Drink[] = [
  {
    id: 'sbux-flat-white',
    brand: 'starbucks',
    name: 'Flat White',
    category: 'hot',
    size_ml: 354,
    nutrition: { calories_kcal: 160, sugar_g: 14, fat_g: 6, protein_g: 9, caffeine_mg: 130 },
  },
  {
    id: 'sbux-cold-brew',
    brand: 'starbucks',
    name: 'Cold Brew Coffee',
    category: 'iced',
    size_ml: 473,
    nutrition: { calories_kcal: 5, sugar_g: 0, fat_g: 0, protein_g: 1, caffeine_mg: 205 },
  },
  {
    id: 'sbux-frappuccino-caramel',
    brand: 'starbucks',
    name: 'Caramel Frappuccino',
    category: 'blended',
    size_ml: 473,
    nutrition: { calories_kcal: 380, sugar_g: 55, fat_g: 13, protein_g: 5, caffeine_mg: 90 },
  },
  {
    id: 'sbux-chai-latte',
    brand: 'starbucks',
    name: 'Chai Tea Latte',
    category: 'tea',
    size_ml: 354,
    nutrition: { calories_kcal: 240, sugar_g: 42, fat_g: 4, protein_g: 8, caffeine_mg: 95 },
  },
  {
    id: 'costa-latte',
    brand: 'costa',
    name: 'Latte',
    category: 'hot',
    size_ml: 354,
    nutrition: { calories_kcal: 170, sugar_g: 15, fat_g: 6, protein_g: 11, caffeine_mg: 185 },
  },
  {
    id: 'costa-cold-brew',
    brand: 'costa',
    name: 'Cold Brew',
    category: 'iced',
    size_ml: 325,
    nutrition: { calories_kcal: 10, sugar_g: 0, fat_g: 0, protein_g: 1, caffeine_mg: 200 },
  },
  {
    id: 'costa-frostino-caramel',
    brand: 'costa',
    name: 'Caramel Frostino',
    category: 'blended',
    size_ml: 473,
    nutrition: { calories_kcal: 420, sugar_g: 62, fat_g: 13, protein_g: 7, caffeine_mg: 90 },
  },
  {
    id: 'costa-chai-latte',
    brand: 'costa',
    name: 'Chai Latte',
    category: 'tea',
    size_ml: 354,
    nutrition: { calories_kcal: 220, sugar_g: 37, fat_g: 4, protein_g: 7, caffeine_mg: 80 },
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('filterDrinks', () => {
  // -------------------------------------------------------------------------
  // No filters
  // -------------------------------------------------------------------------

  it('returns all drinks when category is "all" and query is empty', () => {
    const result = filterDrinks(drinks, 'all', '');
    expect(result).toHaveLength(drinks.length);
    expect(result).toEqual(drinks);
  });

  it('returns empty array when input is empty', () => {
    const result = filterDrinks([], 'all', '');
    expect(result).toEqual([]);
  });

  it('returns empty array when input is empty with active filters', () => {
    const result = filterDrinks([], 'hot', 'latte');
    expect(result).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Category filtering
  // -------------------------------------------------------------------------

  it('filters by category "hot"', () => {
    const result = filterDrinks(drinks, 'hot', '');
    expect(result).toHaveLength(2);
    result.forEach((d) => expect(d.category).toBe('hot'));
  });

  it('filters by category "iced"', () => {
    const result = filterDrinks(drinks, 'iced', '');
    expect(result).toHaveLength(2);
    result.forEach((d) => expect(d.category).toBe('iced'));
  });

  it('filters by category "blended"', () => {
    const result = filterDrinks(drinks, 'blended', '');
    expect(result).toHaveLength(2);
    result.forEach((d) => expect(d.category).toBe('blended'));
  });

  it('filters by category "tea"', () => {
    const result = filterDrinks(drinks, 'tea', '');
    expect(result).toHaveLength(2);
    result.forEach((d) => expect(d.category).toBe('tea'));
  });

  it('returns empty array when no drinks match the category', () => {
    const result = filterDrinks(drinks, 'other', '');
    expect(result).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Search query filtering
  // -------------------------------------------------------------------------

  it('filters by search query (case-insensitive, lowercase query)', () => {
    const result = filterDrinks(drinks, 'all', 'latte');
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.name.toLowerCase()).toContain('latte'));
  });

  it('filters by search query (case-insensitive, uppercase query)', () => {
    const result = filterDrinks(drinks, 'all', 'LATTE');
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.name.toLowerCase()).toContain('latte'));
  });

  it('search is case-insensitive (lower and upper produce same results)', () => {
    const lower = filterDrinks(drinks, 'all', 'cold brew');
    const upper = filterDrinks(drinks, 'all', 'COLD BREW');
    expect(lower.length).toBe(upper.length);
    expect(lower.map((d) => d.id)).toEqual(upper.map((d) => d.id));
  });

  it('returns empty array when query matches no drink name', () => {
    const result = filterDrinks(drinks, 'all', 'zzznomatch999');
    expect(result).toEqual([]);
  });

  it('trims whitespace from the search query', () => {
    const padded = filterDrinks(drinks, 'all', '  latte  ');
    const clean = filterDrinks(drinks, 'all', 'latte');
    expect(padded.length).toBe(clean.length);
    expect(padded.map((d) => d.id)).toEqual(clean.map((d) => d.id));
  });

  it('returns all drinks when query is only whitespace', () => {
    const result = filterDrinks(drinks, 'all', '   ');
    expect(result).toHaveLength(drinks.length);
  });

  // -------------------------------------------------------------------------
  // Combined category + search filtering
  // -------------------------------------------------------------------------

  it('applies category and search filters simultaneously', () => {
    const result = filterDrinks(drinks, 'hot', 'flat');
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('sbux-flat-white');
    result.forEach((d) => {
      expect(d.category).toBe('hot');
      expect(d.name.toLowerCase()).toContain('flat');
    });
  });

  it('returns empty when category matches but query does not', () => {
    const result = filterDrinks(drinks, 'hot', 'zzznomatch999');
    expect(result).toEqual([]);
  });

  it('returns empty when query matches but category does not', () => {
    // "Latte" is a hot/tea drink; filtering by "iced" should exclude it
    const result = filterDrinks(drinks, 'iced', 'latte');
    expect(result).toEqual([]);
  });

  it('returns matching drinks when both filters are satisfied', () => {
    const result = filterDrinks(drinks, 'tea', 'chai');
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => {
      expect(d.category).toBe('tea');
      expect(d.name.toLowerCase()).toContain('chai');
    });
  });

  // -------------------------------------------------------------------------
  // Immutability / no side-effects
  // -------------------------------------------------------------------------

  it('does not mutate the input array', () => {
    const original = [...drinks];
    filterDrinks(drinks, 'hot', 'flat');
    expect(drinks).toEqual(original);
  });
});
