import { describe, it, expect } from 'vitest';
import { eraMatchSuggestion } from './eraMatchSuggestion';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(overrides: Partial<CarModel> & { id: string; year: number }): CarModel {
  return {
    brand: 'ferrari',
    model: overrides.id,
    decade: Math.floor(overrides.year / 10) * 10,
    imageUrl: '/images/placeholder.jpg',
    specs: {
      hp: 400,
      torqueLbFt: 300,
      zeroToSixtyMs: 4.5,
      topSpeedMph: 180,
      engineConfig: 'V12, 5.0L',
    },
    eraRivals: [],
    ...overrides,
  };
}

/** A small Lamborghini catalog used across most tests */
const lambo1963 = makeCar({ id: 'lamborghini-350-gt-1963', brand: 'lamborghini', year: 1963 });
const lambo1965 = makeCar({ id: 'lamborghini-400-gt-1965', brand: 'lamborghini', year: 1965 });
const lambo1970 = makeCar({ id: 'lamborghini-miura-sv-1970', brand: 'lamborghini', year: 1970 });
const lambo1984 = makeCar({ id: 'lamborghini-countach-lp500s-1984', brand: 'lamborghini', year: 1984 });
const lambo1990 = makeCar({ id: 'lamborghini-diablo-1990', brand: 'lamborghini', year: 1990 });

const lamboCatalog: CarModel[] = [lambo1963, lambo1965, lambo1970, lambo1984, lambo1990];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('eraMatchSuggestion', () => {
  // -------------------------------------------------------------------------
  // Edge case: empty catalog
  // -------------------------------------------------------------------------

  it('returns null when opponentCatalog is empty', () => {
    const ferrari = makeCar({ id: 'ferrari-250-gto-1962', year: 1962 });
    expect(eraMatchSuggestion(ferrari, [])).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Exact match via eraRivals
  // -------------------------------------------------------------------------

  it('returns the exact eraRival when the catalog contains the referenced ID', () => {
    const ferrari = makeCar({
      id: 'ferrari-250-gto-1962',
      year: 1962,
      eraRivals: ['lamborghini-350-gt-1963'],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    expect(result).toBe(lambo1963);
  });

  it('returns the single eraRival even if it is not the closest year in the full catalog', () => {
    // lambo1984 is the exact era rival; lambo1990 would be closer if we only sorted by year
    // from a different base, but here we want the curated eraRival to win.
    const ferrari = makeCar({
      id: 'ferrari-testarossa-1984',
      year: 1984,
      eraRivals: ['lamborghini-countach-lp500s-1984'],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    expect(result).toBe(lambo1984);
  });

  // -------------------------------------------------------------------------
  // Nearest match among multiple eraRivals
  // -------------------------------------------------------------------------

  it('returns the closest-year rival when multiple eraRivals are listed', () => {
    // Ferrari 1964 — era rivals are lambo1963 (diff=1) and lambo1970 (diff=6)
    const ferrari = makeCar({
      id: 'ferrari-275-gtb-1964',
      year: 1964,
      eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-miura-sv-1970'],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    // lambo1963 (year=1963) is 1 year away; lambo1970 is 6 years away → expect lambo1963
    expect(result).toBe(lambo1963);
  });

  it('returns the nearest rival when ties are broken by first found (stable)', () => {
    // Ferrari 1964 — two rivals equidistant (1963 and 1965, both 1 year away)
    const ferrari = makeCar({
      id: 'ferrari-275-gtb-1964',
      year: 1964,
      eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-400-gt-1965'],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    // Both are 1 year away — the reduce keeps the first equal candidate (lambo1963)
    expect(result).toBe(lambo1963);
  });

  // -------------------------------------------------------------------------
  // Fallback: no eraRivals → closest year in full catalog
  // -------------------------------------------------------------------------

  it('falls back to closest year in full catalog when eraRivals is empty', () => {
    // Ferrari 1987 has no eraRivals; lambo1984 (diff=3) is closer than lambo1990 (diff=3) — tie
    // but lambo1984 comes first in the array so it wins.
    const ferrari = makeCar({
      id: 'ferrari-f40-1987',
      year: 1987,
      eraRivals: [],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    // Distances: 1963→24, 1965→22, 1970→17, 1984→3, 1990→3 — first 3-year tie is lambo1984
    expect(result).toBe(lambo1984);
  });

  it('falls back to full catalog when no eraRivals IDs match catalog entries', () => {
    const ferrari = makeCar({
      id: 'ferrari-308-gts-1977',
      year: 1977,
      eraRivals: ['lamborghini-unknown-id-9999'],
    });

    const result = eraMatchSuggestion(ferrari, lamboCatalog);

    // Distances: 1963→14, 1965→12, 1970→7, 1984→7, 1990→13 — first 7-year tie is lambo1970
    expect(result).toBe(lambo1970);
  });

  // -------------------------------------------------------------------------
  // Single-entry catalog
  // -------------------------------------------------------------------------

  it('returns the only car when catalog has one entry', () => {
    const ferrari = makeCar({ id: 'ferrari-250-gto-1962', year: 1962, eraRivals: [] });
    const singleCatalog: CarModel[] = [lambo1990];

    const result = eraMatchSuggestion(ferrari, singleCatalog);

    expect(result).toBe(lambo1990);
  });
});
