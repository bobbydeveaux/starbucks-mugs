import { describe, it, expect } from 'vitest';
import { filterCountries } from './filterCountries';
import type { Country } from '../types';

// Fixture — five countries with known January averages (Celsius)
const countries: Country[] = [
  {
    country: 'Iceland',
    code: 'IS',
    avgTemps: { jan: -1, feb: -1, mar: 1, apr: 4, may: 9, jun: 12, jul: 14, aug: 13, sep: 10, oct: 6, nov: 2, dec: 0 },
  },
  {
    country: 'Spain',
    code: 'ES',
    avgTemps: { jan: 10, feb: 11, mar: 13, apr: 15, may: 18, jun: 23, jul: 27, aug: 27, sep: 23, oct: 18, nov: 13, dec: 10 },
  },
  {
    country: 'Kenya',
    code: 'KE',
    avgTemps: { jan: 24, feb: 25, mar: 25, apr: 24, may: 22, jun: 21, jul: 20, aug: 21, sep: 22, oct: 23, nov: 23, dec: 23 },
  },
  {
    country: 'Brazil',
    code: 'BR',
    avgTemps: { jan: 27, feb: 27, mar: 26, apr: 25, may: 22, jun: 20, jul: 20, aug: 21, sep: 22, oct: 23, nov: 25, dec: 26 },
  },
  {
    country: 'Australia',
    code: 'AU',
    avgTemps: { jan: 28, feb: 28, mar: 26, apr: 23, may: 19, jun: 16, jul: 15, aug: 17, sep: 20, oct: 22, nov: 25, dec: 27 },
  },
];

describe('filterCountries', () => {
  it('returns countries within tolerance', () => {
    // Target 25°C ± 3 in January → Kenya (24), Brazil (27), Australia (28)
    const result = filterCountries(countries, 'jan', 25, 3);
    const names = result.map((c) => c.country);
    expect(names).toContain('Kenya');
    expect(names).toContain('Brazil');
    expect(names).toContain('Australia');
    expect(names).not.toContain('Spain');
    expect(names).not.toContain('Iceland');
  });

  it('excludes countries outside tolerance', () => {
    // Target 25°C ± 1 in January → only Kenya (24, diff=1) and Brazil (27, diff=2 excluded)
    const result = filterCountries(countries, 'jan', 25, 1);
    const names = result.map((c) => c.country);
    expect(names).toContain('Kenya');
    expect(names).not.toContain('Brazil');   // diff = 2
    expect(names).not.toContain('Australia'); // diff = 3
    expect(names).not.toContain('Spain');
    expect(names).not.toContain('Iceland');
  });

  it('returns exact match only when tolerance is 0', () => {
    // Target 27°C ± 0 in January → Brazil (27) only
    const result = filterCountries(countries, 'jan', 27, 0);
    expect(result).toHaveLength(1);
    expect(result[0].country).toBe('Brazil');
  });

  it('returns empty array when no countries match', () => {
    // Target 0°C ± 0 in January → nothing matches exactly
    const result = filterCountries(countries, 'jan', 0, 0);
    expect(result).toHaveLength(0);
  });

  it('returns all countries when tolerance is very large', () => {
    const result = filterCountries(countries, 'jan', 15, 100);
    expect(result).toHaveLength(countries.length);
  });

  it('returns empty array for empty input', () => {
    const result = filterCountries([], 'jan', 25, 3);
    expect(result).toHaveLength(0);
  });

  it('returns empty array when targetTempCelsius is NaN', () => {
    const result = filterCountries(countries, 'jan', NaN, 3);
    expect(result).toHaveLength(0);
  });

  it('sorts results ascending by absolute temperature difference', () => {
    // Target 25°C ± 3 in January:
    //   Kenya=24 (diff=1), Brazil=27 (diff=2), Australia=28 (diff=3)
    const result = filterCountries(countries, 'jan', 25, 3);
    const diffs = result.map((c) => Math.abs(c.avgTemps.jan - 25));
    for (let i = 1; i < diffs.length; i++) {
      expect(diffs[i]).toBeGreaterThanOrEqual(diffs[i - 1]);
    }
  });

  it('works correctly for months other than January', () => {
    // Target 20°C ± 2 in July → Kenya (20, diff=0), Brazil (20, diff=0)
    const result = filterCountries(countries, 'jul', 20, 2);
    const names = result.map((c) => c.country);
    expect(names).toContain('Kenya');
    expect(names).toContain('Brazil');
    expect(names).not.toContain('Iceland'); // jul=14, diff=6
    expect(names).not.toContain('Australia'); // jul=15, diff=5
  });

  it('does not mutate the input array', () => {
    const input: Country[] = [
      {
        country: 'Spain',
        code: 'ES',
        avgTemps: { jan: 10, feb: 11, mar: 13, apr: 15, may: 18, jun: 23, jul: 27, aug: 27, sep: 23, oct: 18, nov: 13, dec: 10 },
      },
      {
        country: 'Kenya',
        code: 'KE',
        avgTemps: { jan: 24, feb: 25, mar: 25, apr: 24, may: 22, jun: 21, jul: 20, aug: 21, sep: 22, oct: 23, nov: 23, dec: 23 },
      },
    ];
    const copy = [...input];
    filterCountries(input, 'jan', 15, 5);
    expect(input).toEqual(copy);
  });
});
