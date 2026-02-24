import { describe, it, expect } from 'vitest';
import { yearToDecade, eraMatchSuggestion } from './eraMatchSuggestion';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(overrides: Partial<CarModel> & { id: string; year: number }): CarModel {
  return {
    id: overrides.id,
    brand: overrides.brand ?? 'ferrari',
    model: overrides.model ?? overrides.id,
    year: overrides.year,
    decade: Math.floor(overrides.year / 10) * 10,
    imageUrl: '/images/placeholder.jpg',
    specs: {
      hp: 400,
      torqueLbFt: 300,
      zeroToSixtyMs: 4.5,
      topSpeedMph: 180,
      engineConfig: 'V12, 5.0L',
    },
    eraRivals: overrides.eraRivals ?? [],
    ...overrides,
  };
}

const ferrariTestarossa = makeCar({ id: 'ferrari-testarossa-1984', brand: 'ferrari', year: 1984, model: 'Testarossa' });
const ferrariF40 = makeCar({ id: 'ferrari-f40-1987', brand: 'ferrari', year: 1987, model: 'F40' });
const ferrari308 = makeCar({ id: 'ferrari-308-1975', brand: 'ferrari', year: 1975, model: '308 GTB' });

const lamboCountach = makeCar({ id: 'lamborghini-countach-1974', brand: 'lamborghini', year: 1974, model: 'Countach' });
const lamboJalpa = makeCar({ id: 'lamborghini-jalpa-1981', brand: 'lamborghini', year: 1981, model: 'Jalpa' });
const lamboDialablo = makeCar({ id: 'lamborghini-diablo-1990', brand: 'lamborghini', year: 1990, model: 'Diablo' });

// ---------------------------------------------------------------------------
// yearToDecade tests
// ---------------------------------------------------------------------------

describe('yearToDecade', () => {
  it('maps the first year of a decade to that decade', () => {
    expect(yearToDecade(1980)).toBe(1980);
    expect(yearToDecade(1990)).toBe(1990);
    expect(yearToDecade(2000)).toBe(2000);
  });

  it('maps mid-decade years to the correct decade floor', () => {
    expect(yearToDecade(1984)).toBe(1980);
    expect(yearToDecade(1987)).toBe(1980);
    expect(yearToDecade(1995)).toBe(1990);
    expect(yearToDecade(2023)).toBe(2020);
  });

  it('maps the last year of a decade correctly', () => {
    expect(yearToDecade(1989)).toBe(1980);
    expect(yearToDecade(1999)).toBe(1990);
    expect(yearToDecade(2009)).toBe(2000);
  });

  it('handles year 1950', () => {
    expect(yearToDecade(1950)).toBe(1950);
    expect(yearToDecade(1957)).toBe(1950);
  });
});

// ---------------------------------------------------------------------------
// eraMatchSuggestion tests
// ---------------------------------------------------------------------------

describe('eraMatchSuggestion', () => {
  // -------------------------------------------------------------------------
  // Empty catalog
  // -------------------------------------------------------------------------

  it('returns null when the opponent catalog is empty', () => {
    expect(eraMatchSuggestion(ferrariTestarossa, [])).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Curated eraRivals takes precedence
  // -------------------------------------------------------------------------

  it('returns the first eraRival whose ID is in the opponent catalog', () => {
    const ferrari = makeCar({
      id: 'ferrari-testarossa-1984',
      year: 1984,
      eraRivals: ['lamborghini-countach-1974', 'lamborghini-jalpa-1981'],
    });

    const result = eraMatchSuggestion(ferrari, [lamboCountach, lamboJalpa, lamboDialablo]);
    expect(result?.id).toBe('lamborghini-countach-1974');
  });

  it('skips eraRivals IDs that do not appear in the opponent catalog', () => {
    const ferrari = makeCar({
      id: 'ferrari-testarossa-1984',
      year: 1984,
      eraRivals: ['lamborghini-missing-model', 'lamborghini-jalpa-1981'],
    });

    const result = eraMatchSuggestion(ferrari, [lamboJalpa, lamboDialablo]);
    expect(result?.id).toBe('lamborghini-jalpa-1981');
  });

  it('falls back to nearest-year when no eraRival IDs match the catalog', () => {
    const ferrari = makeCar({
      id: 'ferrari-testarossa-1984',
      year: 1984,
      eraRivals: ['lamborghini-missing-1', 'lamborghini-missing-2'],
    });

    // lamboJalpa (1981) is 3 years away; lamboDialablo (1990) is 6 years away.
    const result = eraMatchSuggestion(ferrari, [lamboJalpa, lamboDialablo]);
    expect(result?.id).toBe('lamborghini-jalpa-1981');
  });

  // -------------------------------------------------------------------------
  // Nearest-year fallback
  // -------------------------------------------------------------------------

  it('returns the closest opponent by year when eraRivals is empty', () => {
    // ferrariTestarossa year=1984; countach=1974 (delta 10), jalpa=1981 (delta 3)
    const result = eraMatchSuggestion(ferrariTestarossa, [lamboCountach, lamboJalpa]);
    expect(result?.id).toBe('lamborghini-jalpa-1981');
  });

  it('returns the only opponent in a single-element catalog', () => {
    const result = eraMatchSuggestion(ferrariTestarossa, [lamboCountach]);
    expect(result?.id).toBe('lamborghini-countach-1974');
  });

  it('returns the earlier opponent on an exact tie in year distance', () => {
    // ferrari year=1980; candidate A year=1975 (delta 5), candidate B year=1985 (delta 5)
    // reduce keeps the first minimum, so it returns whichever comes first in the array
    const ferrari = makeCar({ id: 'ferrari-1980', year: 1980 });
    const earlier = makeCar({ id: 'lambo-1975', brand: 'lamborghini', year: 1975 });
    const later = makeCar({ id: 'lambo-1985', brand: 'lamborghini', year: 1985 });

    const result = eraMatchSuggestion(ferrari, [earlier, later]);
    // On tie the reduce keeps the first element (earlier)
    expect(result?.id).toBe('lambo-1975');
  });

  it('handles a car with a year earlier than all opponents', () => {
    // ferrari308 year=1975; all lambos are after
    const result = eraMatchSuggestion(ferrari308, [lamboJalpa, lamboDialablo]);
    // jalpa=1981 delta 6, diablo=1990 delta 15 → jalpa wins
    expect(result?.id).toBe('lamborghini-jalpa-1981');
  });

  it('handles a car with a year later than all opponents', () => {
    // ferrariF40 year=1987; countach=1974 delta 13, jalpa=1981 delta 6
    const result = eraMatchSuggestion(ferrariF40, [lamboCountach, lamboJalpa]);
    expect(result?.id).toBe('lamborghini-jalpa-1981');
  });

  // -------------------------------------------------------------------------
  // Exact-year match
  // -------------------------------------------------------------------------

  it('returns the opponent with the exact same year when available', () => {
    const ferrari = makeCar({ id: 'ferrari-1981', year: 1981 });
    const exactMatch = makeCar({ id: 'lambo-exact-1981', brand: 'lamborghini', year: 1981 });

    const result = eraMatchSuggestion(ferrari, [lamboCountach, exactMatch, lamboDialablo]);
    expect(result?.id).toBe('lambo-exact-1981');
  });
});
