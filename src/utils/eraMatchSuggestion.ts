import type { CarModel } from '../types';

/**
 * Maps a car model's year to its decade bucket (the nearest decade floor).
 *
 * @param year - The car's production year, e.g. 1984.
 * @returns The decade value, e.g. 1980 for any year from 1980–1989.
 *
 * @example
 * yearToDecade(1984); // → 1980
 * yearToDecade(1990); // → 1990
 * yearToDecade(2023); // → 2020
 */
export function yearToDecade(year: number): number {
  return Math.floor(year / 10) * 10;
}

/**
 * Suggests the best rival car from the opposing catalog for a given selected car.
 *
 * Strategy:
 * 1. If the selected car's `eraRivals` list contains IDs that appear in the
 *    opponent catalog, return the first matching rival (authors curated this list
 *    for meaningful pairings).
 * 2. Otherwise fall back to the opponent whose year is numerically closest to
 *    the selected car's year.
 * 3. If the opponent catalog is empty, return `null`.
 *
 * @param selectedCar - The car the user has chosen.
 * @param opponentCatalog - All models from the opposing brand.
 * @returns The suggested rival `CarModel`, or `null` if no rivals are available.
 *
 * @example
 * const rival = eraMatchSuggestion(selectedFerrari, allLambos);
 */
export function eraMatchSuggestion(
  selectedCar: CarModel,
  opponentCatalog: CarModel[],
): CarModel | null {
  if (opponentCatalog.length === 0) return null;

  // 1. Use the curated eraRivals list first.
  if (selectedCar.eraRivals.length > 0) {
    const opponentById = new Map(opponentCatalog.map((c) => [c.id, c]));
    for (const rivalId of selectedCar.eraRivals) {
      const match = opponentById.get(rivalId);
      if (match) return match;
    }
  }

  // 2. Fallback: nearest year in the opponent catalog.
  return opponentCatalog.reduce((closest, candidate) => {
    const candidateDelta = Math.abs(candidate.year - selectedCar.year);
    const closestDelta = Math.abs(closest.year - selectedCar.year);
    return candidateDelta < closestDelta ? candidate : closest;
  });
}
