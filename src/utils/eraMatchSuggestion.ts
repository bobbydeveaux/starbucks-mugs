import type { CarModel } from '../types';

/**
 * Suggests the best era-match rival for a selected car using the car's
 * pre-authored `eraRivals` id list. Among the ids listed, it returns the
 * rival whose year is closest to the selected car's year.
 *
 * The function intentionally relies on `eraRivals` ids (pre-curated in the
 * JSON catalog) rather than brute-force scanning all years in the rival
 * catalog, keeping the matching logic deterministic and data-driven.
 *
 * @param selected - The currently selected car whose rival we want to suggest.
 * @param rivalCatalog - All available cars from the opposing brand.
 * @returns The closest-year rival from the eraRivals list, or `null` if no
 *          match can be found (empty catalog, empty eraRivals, or no eraRivals
 *          ids are present in the provided catalog).
 *
 * @example
 * const suggestion = eraMatchSuggestion(ferrariTestarossa, allLambos);
 * // Returns the Lamborghini whose id appears in ferrariTestarossa.eraRivals
 * // and whose year is nearest to 1984.
 */
export function eraMatchSuggestion(
  selected: CarModel,
  rivalCatalog: CarModel[],
): CarModel | null {
  if (!selected.eraRivals.length || !rivalCatalog.length) {
    return null;
  }

  // Build an id → car lookup for O(1) access
  const rivalById = new Map<string, CarModel>(rivalCatalog.map((c) => [c.id, c]));

  // Collect only the pre-listed rivals that are present in the catalog
  const candidates = selected.eraRivals
    .map((id) => rivalById.get(id))
    .filter((c): c is CarModel => c !== undefined);

  if (!candidates.length) {
    return null;
  }

  // Pick the candidate whose year is closest to the selected car's year;
  // ties are broken in favour of the first candidate in the eraRivals list.
  return candidates.reduce((best, current) => {
    const bestDiff = Math.abs(best.year - selected.year);
    const currentDiff = Math.abs(current.year - selected.year);
    return currentDiff < bestDiff ? current : best;
  });
}
