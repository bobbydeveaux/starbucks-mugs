import type { Drink, FilterState } from '../types';

/**
 * Pure utility function that filters a drinks array by category and search query.
 *
 * @param drinks - Full list of drinks to filter.
 * @param filter - Active category and free-text search query.
 * @returns Drinks that match both the category filter and the search query.
 *
 * @example
 * // Filter to hot drinks only
 * filterDrinks(allDrinks, { category: 'hot', query: '' });
 *
 * @example
 * // Filter by name search across all categories
 * filterDrinks(allDrinks, { category: 'all', query: 'latte' });
 */
export function filterDrinks(drinks: Drink[], filter: FilterState): Drink[] {
  let result = drinks;

  if (filter.category !== 'all') {
    result = result.filter((d) => d.category === filter.category);
  }

  const trimmed = filter.query.trim().toLowerCase();
  if (trimmed) {
    result = result.filter((d) => d.name.toLowerCase().includes(trimmed));
  }

  return result;
}
