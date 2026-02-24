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
  // No filter applied
  // -------------------------------------------------------------------------

  it('returns all drinks when category is "all" and query is empty', () => {
    const result = filterDrinks(drinks, { category: 'all', query: '' });
    expect(result).toHaveLength(drinks.length);
    expect(result).toEqual(drinks);
  });

  it('returns an empty array when given an empty drinks list', () => {
    const result = filterDrinks([], { category: 'all', query: '' });
    expect(result).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Category filtering
  // -------------------------------------------------------------------------

  it('filters by category "hot"', () => {
    const result = filterDrinks(drinks, { category: 'hot', query: '' });
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.category).toBe('hot'));
  });

  it('filters by category "iced"', () => {
    const result = filterDrinks(drinks, { category: 'iced', query: '' });
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.category).toBe('iced'));
  });

  it('filters by category "blended"', () => {
    const result = filterDrinks(drinks, { category: 'blended', query: '' });
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.category).toBe('blended'));
  });

  it('filters by category "tea"', () => {
    const result = filterDrinks(drinks, { category: 'tea', query: '' });
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.category).toBe('tea'));
  });

  it('returns empty array when no drinks match the category', () => {
    const result = filterDrinks(drinks, { category: 'other', query: '' });
    expect(result).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // Search query filtering
  // -------------------------------------------------------------------------

  it('filters by search query (case-insensitive substring match)', () => {
    const result = filterDrinks(drinks, { category: 'all', query: 'latte' });
    expect(result.length).toBeGreaterThan(0);
    result.forEach((d) => expect(d.name.toLowerCase()).toContain('latte'));
  });

  it('search is case-insensitive', () => {
    const lower = filterDrinks(drinks, { category: 'all', query: 'latte' });
    const upper = filterDrinks(drinks, { category: 'all', query: 'LATTE' });
    const mixed = filterDrinks(drinks, { category: 'all', query: 'LaTtE' });
    expect(lower.length).toBe(upper.length);
    expect(lower.length).toBe(mixed.length);
  });

  it('trims whitespace from the search query', () => {
    const padded = filterDrinks(drinks, { category: 'all', query: '  latte  ' });
    const clean = filterDrinks(drinks, { category: 'all', query: 'latte' });
    expect(padded).toEqual(clean);
  });

  it('returns empty array when query matches no drinks', () => {
    const result = filterDrinks(drinks, { category: 'all', query: 'zzznomatch999' });
    expect(result).toHaveLength(0);
  });

  it('returns all drinks when query is only whitespace', () => {
    const result = filterDrinks(drinks, { category: 'all', query: '   ' });
    expect(result).toHaveLength(drinks.length);
  });

  // -------------------------------------------------------------------------
  // Combined category + search filtering
  // -------------------------------------------------------------------------

  it('applies category and search simultaneously', () => {
    const result = filterDrinks(drinks, { category: 'hot', query: 'latte' });
    result.forEach((d) => {
      expect(d.category).toBe('hot');
      expect(d.name.toLowerCase()).toContain('latte');
    });
  });

  it('returns empty when category matches but query does not', () => {
    const result = filterDrinks(drinks, { category: 'hot', query: 'frappuccino' });
    expect(result).toHaveLength(0);
  });

  it('returns empty when query matches but category does not', () => {
    const result = filterDrinks(drinks, { category: 'iced', query: 'flat white' });
    expect(result).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // Does not mutate the original array
  // -------------------------------------------------------------------------

  it('does not mutate the original drinks array', () => {
    const original = [...drinks];
    filterDrinks(drinks, { category: 'hot', query: 'latte' });
    expect(drinks).toEqual(original);
  });
});
