import { describe, it, expect } from 'vitest';
import { eraMatchSuggestion } from './eraMatchSuggestion';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(overrides: Partial<CarModel> & { id: string; year: number }): CarModel {
  return {
    brand: 'ferrari',
    model: 'Test Model',
    decade: Math.floor(overrides.year / 10) * 10,
    image: '/images/test.jpg',
    eraRivals: [],
    specs: {
      hp: 300,
      torqueLbFt: 220,
      zeroToSixtyMs: 5.5,
      topSpeedMph: 160,
      engineConfig: 'V12, 3.0L',
    },
    ...overrides,
  };
}

const lambo1963 = makeCar({ id: 'lamborghini-350-gt-1963', brand: 'lamborghini', year: 1963 });
const lambo1965 = makeCar({ id: 'lamborghini-400-gt-1965', brand: 'lamborghini', year: 1965 });
const lambo1969 = makeCar({ id: 'lamborghini-islero-1969', brand: 'lamborghini', year: 1969 });

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('eraMatchSuggestion', () => {
  it('returns the single rival listed in eraRivals when it is in the catalog', () => {
    const ferrari = makeCar({
      id: 'ferrari-250-gto-1962',
      year: 1962,
      eraRivals: ['lamborghini-350-gt-1963'],
    });

    const result = eraMatchSuggestion(ferrari, [lambo1963, lambo1965]);
    expect(result).toBe(lambo1963);
  });

  it('picks the nearest-year rival when multiple eraRivals are listed', () => {
    // Ferrari 1964 — rivals include 1963 and 1965; delta from 1964: 1963→1, 1965→1 (tie → first wins)
    const ferrari = makeCar({
      id: 'ferrari-275-gtb-1964',
      year: 1964,
      eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-400-gt-1965'],
    });

    // delta to 1963 == delta to 1965 == 1; reduce keeps the first (1963)
    const result = eraMatchSuggestion(ferrari, [lambo1963, lambo1965]);
    expect(result?.id).toBe('lamborghini-350-gt-1963');
  });

  it('picks the rival with the strictly smaller year delta', () => {
    // Ferrari 1967 — rivals 1963 and 1965; delta: 1963→4, 1965→2 → pick 1965
    const ferrari = makeCar({
      id: 'ferrari-330-1967',
      year: 1967,
      eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-400-gt-1965'],
    });

    const result = eraMatchSuggestion(ferrari, [lambo1963, lambo1965, lambo1969]);
    expect(result?.id).toBe('lamborghini-400-gt-1965');
  });

  it('returns null when the opponent catalog is empty', () => {
    const ferrari = makeCar({
      id: 'ferrari-250-gto-1962',
      year: 1962,
      eraRivals: ['lamborghini-350-gt-1963'],
    });

    expect(eraMatchSuggestion(ferrari, [])).toBeNull();
  });

  it('returns null when eraRivals is empty', () => {
    const ferrari = makeCar({
      id: 'ferrari-250-testa-rossa-1957',
      year: 1957,
      eraRivals: [],
    });

    expect(eraMatchSuggestion(ferrari, [lambo1963, lambo1965])).toBeNull();
  });

  it('returns null when none of the rival ids exist in the opponent catalog', () => {
    const ferrari = makeCar({
      id: 'ferrari-test',
      year: 1970,
      eraRivals: ['lamborghini-nonexistent-id'],
    });

    expect(eraMatchSuggestion(ferrari, [lambo1963, lambo1965])).toBeNull();
  });

  it('ignores catalog cars that are not listed in eraRivals', () => {
    // Only lambo1963 is in eraRivals — lambo1969 should never be returned
    const ferrari = makeCar({
      id: 'ferrari-250-gto-1962',
      year: 1962,
      eraRivals: ['lamborghini-350-gt-1963'],
    });

    const result = eraMatchSuggestion(ferrari, [lambo1963, lambo1965, lambo1969]);
    expect(result?.id).toBe('lamborghini-350-gt-1963');
  });
});
