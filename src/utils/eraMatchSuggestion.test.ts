import { describe, it, expect } from 'vitest';
import { eraMatchSuggestion } from './eraMatchSuggestion';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCar(overrides: Partial<CarModel> & Pick<CarModel, 'id' | 'brand' | 'model' | 'year'>): CarModel {
  return {
    decade: Math.floor(overrides.year / 10) * 10,
    imageUrl: `/images/${overrides.brand}/${overrides.id}.jpg`,
    specs: {
      hp: 400,
      torqueLbFt: 300,
      zeroToSixtyMs: 5.0,
      topSpeedMph: 180,
      engineConfig: 'V12, 4.0L',
    },
    eraRivals: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrariF40 = makeCar({
  id: 'ferrari-f40-1987',
  brand: 'ferrari',
  model: 'F40',
  year: 1987,
  eraRivals: ['lamborghini-countach-lp5000s-1982', 'lamborghini-diablo-1990'],
});

const countachLP5000 = makeCar({
  id: 'lamborghini-countach-lp5000s-1982',
  brand: 'lamborghini',
  model: 'Countach LP5000S',
  year: 1982,
});

const diablo = makeCar({
  id: 'lamborghini-diablo-1990',
  brand: 'lamborghini',
  model: 'Diablo',
  year: 1990,
});

const murcielago = makeCar({
  id: 'lamborghini-murcielago-2001',
  brand: 'lamborghini',
  model: 'Murciélago',
  year: 2001,
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('eraMatchSuggestion', () => {
  it('returns null for empty eraRivals', () => {
    const car = makeCar({ id: 'ferrari-250-gto-1962', brand: 'ferrari', model: '250 GTO', year: 1962, eraRivals: [] });
    const result = eraMatchSuggestion(car, [countachLP5000, diablo]);
    expect(result).toBeNull();
  });

  it('returns null for empty rival catalog', () => {
    const result = eraMatchSuggestion(ferrariF40, []);
    expect(result).toBeNull();
  });

  it('returns null when no eraRivals IDs match the rival catalog', () => {
    // ferrariF40.eraRivals lists countach and diablo; we only provide murciélago
    const result = eraMatchSuggestion(ferrariF40, [murcielago]);
    expect(result).toBeNull();
  });

  it('returns the only matching rival when there is exactly one', () => {
    const result = eraMatchSuggestion(ferrariF40, [countachLP5000, murcielago]);
    // murcielago ID is not in eraRivals, so countach is the only candidate
    expect(result).toBe(countachLP5000);
  });

  it('returns the closer rival when two candidates are listed', () => {
    // ferrariF40 year = 1987; countach = 1982 (diff 5), diablo = 1990 (diff 3)
    const result = eraMatchSuggestion(ferrariF40, [countachLP5000, diablo, murcielago]);
    expect(result).toBe(diablo); // diablo is 3 years away vs countach 5 years
  });

  it('handles exact year match', () => {
    const exactRival = makeCar({
      id: 'lamborghini-countach-lp5000s-1982',
      brand: 'lamborghini',
      model: 'Countach LP5000S',
      year: 1987, // same year as F40
    });
    const result = eraMatchSuggestion(ferrariF40, [exactRival, diablo]);
    expect(result).toBe(exactRival); // diff 0 wins
  });

  it('is deterministic: returns the first encountered car on equal distance', () => {
    // Both candidates are equidistant from the selected car's year (1987)
    // countach = 1982 (diff 5), hypothetical 1992 rival (diff 5)
    const rival1992 = makeCar({
      id: 'lamborghini-diablo-1990', // reuse id so it's in eraRivals
      brand: 'lamborghini',
      model: 'Diablo Hypothetical',
      year: 1992, // diff = 5 from 1987
    });
    // Pass countach first — it should be returned (first-encountered wins on tie)
    const result = eraMatchSuggestion(
      { ...ferrariF40, eraRivals: ['lamborghini-countach-lp5000s-1982', 'lamborghini-diablo-1990'] },
      [countachLP5000, rival1992],
    );
    // countach diff = 5, rival1992 diff = 5; first encountered (countach) is kept
    expect(result).toBe(countachLP5000);
  });
});
