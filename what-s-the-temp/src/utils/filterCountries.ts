import type { Country, MonthKey } from '../types';

/**
 * Filters countries whose average temperature for the given month falls within
 * `toleranceCelsius` degrees of `targetTempCelsius`.
 *
 * The caller is responsible for converting any user-supplied temperature to
 * Celsius before calling this function, keeping the logic unit-agnostic.
 *
 * Results are sorted ascending by absolute difference from the target
 * temperature (closest match first).
 *
 * @returns Empty array when `targetTempCelsius` is NaN or the input array is empty.
 */
export function filterCountries(
  countries: Country[],
  month: MonthKey,
  targetTempCelsius: number,
  toleranceCelsius: number,
): Country[] {
  if (isNaN(targetTempCelsius)) return [];

  const filtered = countries.filter((c) => {
    const diff = Math.abs(c.avgTemps[month] - targetTempCelsius);
    return diff <= toleranceCelsius;
  });

  return filtered.sort(
    (a, b) =>
      Math.abs(a.avgTemps[month] - targetTempCelsius) -
      Math.abs(b.avgTemps[month] - targetTempCelsius),
  );
}
