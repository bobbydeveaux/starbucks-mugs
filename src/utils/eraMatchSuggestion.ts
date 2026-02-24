import type { CarModel } from '../types';

/**
 * Suggests the closest-era rival for a selected car using the pre-authored
 * `eraRivals` IDs baked into the JSON catalog.
 *
 * The function does NOT scan all years in the rival catalog; it restricts
 * candidates to the IDs listed in `selectedCar.eraRivals` and then picks
 * the candidate whose model year is closest to the selected car's year.
 *
 * @param selectedCar   - The car the user has selected.
 * @param rivalCatalog  - The full catalog of cars from the opposing brand.
 * @returns The best-matching rival CarModel, or `null` when no match exists
 *          (empty eraRivals, empty catalog, or no ID overlap).
 *
 * @example
 * const suggestion = eraMatchSuggestion(ferrariF40, lamborghiniCars);
 * // → CountachLP5000S or similar 1980s Lamborghini
 */
export function eraMatchSuggestion(
  selectedCar: CarModel,
  rivalCatalog: CarModel[],
): CarModel | null {
  const { eraRivals } = selectedCar;

  if (!eraRivals.length || !rivalCatalog.length) {
    return null;
  }

  // Only consider cars whose IDs appear in the eraRivals list.
  const candidates = rivalCatalog.filter((car) => eraRivals.includes(car.id));

  if (!candidates.length) {
    return null;
  }

  // Among the candidates, find the one closest in year to the selected car.
  let best = candidates[0];
  let bestDiff = Math.abs(candidates[0].year - selectedCar.year);

  for (const car of candidates.slice(1)) {
    const diff = Math.abs(car.year - selectedCar.year);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = car;
    }
  }

  return best;
}
