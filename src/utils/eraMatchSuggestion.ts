import type { CarModel } from '../types';

/**
 * Given a selected car and a catalog of cars from the opposing brand, returns
 * the era-rival whose model year is closest to the selected car's year.
 *
 * Candidates are determined by the `eraRivals` id array embedded in the
 * selected car's data — the function does NOT brute-force the entire catalog.
 *
 * Returns `null` when:
 * - `opponentCatalog` is empty
 * - `selected.eraRivals` is empty (no rivals defined for this model)
 * - None of the rival ids are found in `opponentCatalog`
 */
export function eraMatchSuggestion(
  selected: CarModel,
  opponentCatalog: CarModel[],
): CarModel | null {
  if (opponentCatalog.length === 0 || selected.eraRivals.length === 0) {
    return null;
  }

  const rivalIdSet = new Set(selected.eraRivals);
  const candidates = opponentCatalog.filter((car) => rivalIdSet.has(car.id));

  if (candidates.length === 0) return null;

  // Pick the candidate whose year is closest to the selected car's year.
  return candidates.reduce((best, car) => {
    const delta = Math.abs(car.year - selected.year);
    const bestDelta = Math.abs(best.year - selected.year);
    return delta < bestDelta ? car : best;
  });
}
