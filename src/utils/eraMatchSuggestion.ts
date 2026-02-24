/**
 * Maps a car model year to its decade bucket label.
 *
 * Used by the EraFilter component to display decade labels and to match
 * cars to their era bucket for filtering purposes.
 *
 * @param year - A four-digit model year, e.g. 1984.
 * @returns A decade label string, e.g. "1980s".
 *
 * @example
 * eraMatchSuggestion(1984) // → "1980s"
 * eraMatchSuggestion(1963) // → "1960s"
 * eraMatchSuggestion(2023) // → "2020s"
 */
export function eraMatchSuggestion(year: number): string {
  const decade = Math.floor(year / 10) * 10;
  return `${decade}s`;
}
