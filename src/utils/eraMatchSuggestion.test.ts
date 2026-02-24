import { describe, it, expect } from 'vitest';
import { eraMatchSuggestion } from './eraMatchSuggestion';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeCar(
  overrides: Pick<CarModel, 'id' | 'brand' | 'model' | 'year'> & Partial<CarModel>,
): CarModel {
  return {
    decade: Math.floor(overrides.year / 10) * 10,
    image: '/images/placeholder.jpg',
    specs: {
      hp: 300,
      torqueLbFt: 250,
      zeroToSixtyMs: 5.0,
      topSpeedMph: 180,
      engineConfig: 'V12, 4.0L',
    },
    eraRivals: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Fixture cars
// ---------------------------------------------------------------------------

const lambo1963 = makeCar({ id: 'lamborghini-350-gt-1963', brand: 'lamborghini', model: '350 GT', year: 1963 });
const lambo1966 = makeCar({ id: 'lamborghini-miura-p400-1966', brand: 'lamborghini', model: 'Miura P400', year: 1966 });
const lambo1971 = makeCar({ id: 'lamborghini-countach-lp500-1971', brand: 'lamborghini', model: 'Countach LP500', year: 1971 });
const lambo1985 = makeCar({ id: 'lamborghini-countach-5000-qv-1985', brand: 'lamborghini', model: 'Countach 5000 QV', year: 1985 });

const ferrari1962 = makeCar({
  id: 'ferrari-250-gto-1962',
  brand: 'ferrari',
  model: '250 GTO',
  year: 1962,
  eraRivals: ['lamborghini-350-gt-1963'],
});

const ferrari1984 = makeCar({
  id: 'ferrari-testarossa-1984',
  brand: 'ferrari',
  model: 'Testarossa',
  year: 1984,
  eraRivals: ['lamborghini-countach-lp500-1971', 'lamborghini-countach-5000-qv-1985'],
});

const ferrariNoRivals = makeCar({
  id: 'ferrari-250-testa-rossa-1957',
  brand: 'ferrari',
  model: '250 Testa Rossa',
  year: 1957,
  eraRivals: [],
});

const ferrariUnknownRivals = makeCar({
  id: 'ferrari-unknown-rivals',
  brand: 'ferrari',
  model: 'Unknown',
  year: 1990,
  eraRivals: ['lamborghini-does-not-exist-1990'],
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('eraMatchSuggestion', () => {
  describe('exact match', () => {
    it('returns the sole eraRival when only one is listed and present in catalog', () => {
      const result = eraMatchSuggestion(ferrari1962, [lambo1963]);
      expect(result).toBe(lambo1963);
    });

    it('returns the rival with the exact same year when available', () => {
      const lambo1984 = makeCar({ id: 'lamborghini-1984', brand: 'lamborghini', model: 'Test 1984', year: 1984 });
      const selected = makeCar({
        id: 'ferrari-1984',
        brand: 'ferrari',
        model: 'Test Ferrari',
        year: 1984,
        eraRivals: ['lamborghini-1984', 'lamborghini-countach-5000-qv-1985'],
      });
      const result = eraMatchSuggestion(selected, [lambo1984, lambo1985]);
      expect(result).toBe(lambo1984);
    });
  });

  describe('nearest-year match', () => {
    it('returns the eraRival whose year is closest when no exact match exists', () => {
      // ferrari1984 has eraRivals: [countach-1971, countach-5000-qv-1985]
      // |1984 - 1971| = 13, |1984 - 1985| = 1 → lambo1985 is closer
      const result = eraMatchSuggestion(ferrari1984, [lambo1971, lambo1985]);
      expect(result).toBe(lambo1985);
    });

    it('returns the closer of two rivals when years straddle the selected year', () => {
      // selected year 1964, rivals at 1963 (diff=1) and 1966 (diff=2)
      const selected = makeCar({
        id: 'ferrari-275-gtb-1964',
        brand: 'ferrari',
        model: '275 GTB',
        year: 1964,
        eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-miura-p400-1966'],
      });
      const result = eraMatchSuggestion(selected, [lambo1963, lambo1966]);
      expect(result).toBe(lambo1963); // diff 1 < diff 2
    });

    it('returns the first listed rival on a tie (equal year distance)', () => {
      // rivals equidistant: 1963 (diff=1) and 1965 (diff=1) from year 1964
      const lambo1965 = makeCar({ id: 'lamborghini-400-gt-1965', brand: 'lamborghini', model: '400 GT', year: 1965 });
      const selected = makeCar({
        id: 'ferrari-tie',
        brand: 'ferrari',
        model: 'Tie Ferrari',
        year: 1964,
        eraRivals: ['lamborghini-350-gt-1963', 'lamborghini-400-gt-1965'],
      });
      const result = eraMatchSuggestion(selected, [lambo1963, lambo1965]);
      // Both have diff=1; the first listed (lambo1963) should be returned
      expect(result).toBe(lambo1963);
    });
  });

  describe('edge cases — empty / missing data', () => {
    it('returns null when the rival catalog is empty', () => {
      const result = eraMatchSuggestion(ferrari1962, []);
      expect(result).toBeNull();
    });

    it('returns null when the selected car has no eraRivals', () => {
      const result = eraMatchSuggestion(ferrariNoRivals, [lambo1963, lambo1966]);
      expect(result).toBeNull();
    });

    it('returns null when eraRivals ids are not present in the rival catalog', () => {
      const result = eraMatchSuggestion(ferrariUnknownRivals, [lambo1963, lambo1966]);
      expect(result).toBeNull();
    });

    it('returns null when both selected car has no eraRivals and catalog is empty', () => {
      const result = eraMatchSuggestion(ferrariNoRivals, []);
      expect(result).toBeNull();
    });

    it('ignores catalog cars whose ids are not in eraRivals', () => {
      // ferrari1962 only lists lambo1963 as eraRival; lambo1966 is in catalog but should be ignored
      const result = eraMatchSuggestion(ferrari1962, [lambo1963, lambo1966]);
      expect(result).toBe(lambo1963);
    });

    it('returns null when only some eraRivals ids are in catalog but none match', () => {
      const selectedWithPartialRivals = makeCar({
        id: 'ferrari-partial',
        brand: 'ferrari',
        model: 'Partial',
        year: 1970,
        eraRivals: ['lamborghini-does-not-exist'],
      });
      const result = eraMatchSuggestion(selectedWithPartialRivals, [lambo1963, lambo1966]);
      expect(result).toBeNull();
    });
  });

  describe('catalog with a single rival', () => {
    it('returns the only eraRival regardless of year distance', () => {
      // ferrari1984 lists both lambo1971 and lambo1985; catalog only has lambo1971
      const result = eraMatchSuggestion(ferrari1984, [lambo1971]);
      expect(result).toBe(lambo1971);
    });
  });
});
