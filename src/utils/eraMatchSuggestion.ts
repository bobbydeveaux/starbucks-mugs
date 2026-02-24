import type { CarModel } from '../types';

/**
 * Returns the rival car from `opponentCatalog` that is the closest contemporary
 * to `selectedCar`, using the pre-authored `eraRivals` IDs as the primary lookup.
 *
 * Algorithm:
 * 1. If `opponentCatalog` is empty, return `null`.
 * 2. Resolve `eraRivals` IDs to `CarModel` objects from `opponentCatalog`.
 * 3. If any rivals are found, return the one with the smallest `|year − selectedCar.year|`.
 * 4. Fallback: if no `eraRivals` match, return the opponent closest in year from the full catalog.
 *
 * @param selectedCar    - The car for which a rival suggestion is needed.
 * @param opponentCatalog - All cars from the opposing brand.
 * @returns The suggested rival `CarModel`, or `null` when the catalog is empty.
 *
 * @example
 * const suggestion = eraMatchSuggestion(ferrariTestarossa, lamboCatalog);
 * // Returns the Lamborghini whose year is closest to 1984
 */
export function eraMatchSuggestion(
  selectedCar: CarModel,
  opponentCatalog: CarModel[],
): CarModel | null {
  if (opponentCatalog.length === 0) return null;

  // Resolve eraRivals IDs to actual CarModel objects from the opponent catalog.
  const rivals = selectedCar.eraRivals
    .map((id) => opponentCatalog.find((car) => car.id === id))
    .filter((car): car is CarModel => car !== undefined);

  // Use the curated rivals if available; otherwise fall back to the full catalog.
  const pool = rivals.length > 0 ? rivals : opponentCatalog;

  return pool.reduce((best, current) => {
    const bestDiff = Math.abs(best.year - selectedCar.year);
    const currentDiff = Math.abs(current.year - selectedCar.year);
    return currentDiff < bestDiff ? current : best;
  });
}
