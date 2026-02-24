import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useComparison } from './useComparison';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrariTestarossa: CarModel = {
  id: 'ferrari-testarossa-1984',
  brand: 'ferrari',
  model: 'Testarossa',
  year: 1984,
  decade: 1980,
  imageUrl: '/images/ferrari/testarossa.jpg',
  price: 87000,
  specs: {
    hp: 390,
    torqueLbFt: 361,
    zeroToSixtyMs: 5.8,
    topSpeedMph: 181,
    engineConfig: 'Flat-12, 4.9L',
  },
  eraRivals: ['lamborghini-countach-lp500s-1982'],
};

const lamboCountach: CarModel = {
  id: 'lamborghini-countach-lp500s-1982',
  brand: 'lamborghini',
  model: 'Countach LP500S',
  year: 1982,
  decade: 1980,
  imageUrl: '/images/lamborghini/countach.jpg',
  price: 100000,
  specs: {
    hp: 375,
    torqueLbFt: 268,
    zeroToSixtyMs: 5.0,
    topSpeedMph: 183,
    engineConfig: 'V12, 4.7L',
  },
  eraRivals: ['ferrari-testarossa-1984'],
};

// A Lamborghini that beats Ferrari on every stat
const fastLambo: CarModel = {
  id: 'lamborghini-huracán-2015',
  brand: 'lamborghini',
  model: 'Huracán LP610-4',
  year: 2015,
  decade: 2010,
  imageUrl: '/images/lamborghini/huracan.jpg',
  specs: {
    hp: 610,
    torqueLbFt: 413,
    zeroToSixtyMs: 2.5,
    topSpeedMph: 202,
    engineConfig: 'V10, 5.2L',
  },
  eraRivals: [],
};

// A Ferrari that wins on every numeric stat vs a weaker car
const fastFerrari: CarModel = {
  id: 'ferrari-f40-1992',
  brand: 'ferrari',
  model: 'F40',
  year: 1992,
  decade: 1990,
  imageUrl: '/images/ferrari/f40.jpg',
  specs: {
    hp: 478,
    torqueLbFt: 424,
    zeroToSixtyMs: 4.2,
    topSpeedMph: 201,
    engineConfig: 'Twin-Turbo V8, 2.9L',
  },
  eraRivals: [],
};

const slowLambo: CarModel = {
  id: 'lamborghini-urraco-1972',
  brand: 'lamborghini',
  model: 'Urraco',
  year: 1972,
  decade: 1970,
  imageUrl: '/images/lamborghini/urraco.jpg',
  specs: {
    hp: 220,
    torqueLbFt: 180,
    zeroToSixtyMs: 7.5,
    topSpeedMph: 150,
    engineConfig: 'V8, 2.5L',
  },
  eraRivals: [],
};

// Cars with identical stats for tie testing
const tiedFerrari: CarModel = {
  ...ferrariTestarossa,
  id: 'ferrari-tied',
  brand: 'ferrari',
  specs: { hp: 400, torqueLbFt: 350, zeroToSixtyMs: 5.0, topSpeedMph: 180, engineConfig: 'V12' },
};

const tiedLambo: CarModel = {
  ...lamboCountach,
  id: 'lambo-tied',
  brand: 'lamborghini',
  specs: { hp: 400, torqueLbFt: 350, zeroToSixtyMs: 5.0, topSpeedMph: 180, engineConfig: 'V12' },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useComparison', () => {
  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  it('starts with both selections null', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.selectedLambo).toBeNull();
  });

  it('starts with an empty winners array', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.winners).toEqual([]);
  });

  it('exposes setSelectedFerrari and setSelectedLambo as functions', () => {
    const { result } = renderHook(() => useComparison());
    expect(typeof result.current.setSelectedFerrari).toBe('function');
    expect(typeof result.current.setSelectedLambo).toBe('function');
  });

  // -------------------------------------------------------------------------
  // Selection state management
  // -------------------------------------------------------------------------

  it('updates selectedFerrari when setSelectedFerrari is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
    });
    expect(result.current.selectedFerrari).toEqual(ferrariTestarossa);
  });

  it('updates selectedLambo when setSelectedLambo is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedLambo(lamboCountach);
    });
    expect(result.current.selectedLambo).toEqual(lamboCountach);
  });

  it('can clear selectedFerrari back to null', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
    });
    act(() => {
      result.current.setSelectedFerrari(null);
    });
    expect(result.current.selectedFerrari).toBeNull();
  });

  it('can clear selectedLambo back to null', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedLambo(lamboCountach);
    });
    act(() => {
      result.current.setSelectedLambo(null);
    });
    expect(result.current.selectedLambo).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Winners array — empty when selection is incomplete
  // -------------------------------------------------------------------------

  it('returns empty winners when only Ferrari is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
    });
    expect(result.current.winners).toEqual([]);
  });

  it('returns empty winners when only Lamborghini is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedLambo(lamboCountach);
    });
    expect(result.current.winners).toEqual([]);
  });

  it('returns empty winners after clearing a previously full selection', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    act(() => {
      result.current.setSelectedFerrari(null);
    });
    expect(result.current.winners).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Winners array — structure
  // -------------------------------------------------------------------------

  it('returns 4 comparison stats when both cars are selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    expect(result.current.winners).toHaveLength(4);
  });

  it('each stat entry has label, ferrariValue, lamboValue, and winner fields', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    for (const stat of result.current.winners) {
      expect(stat).toHaveProperty('label');
      expect(stat).toHaveProperty('ferrariValue');
      expect(stat).toHaveProperty('lamboValue');
      expect(stat).toHaveProperty('winner');
      expect(typeof stat.label).toBe('string');
      expect(typeof stat.ferrariValue).toBe('number');
      expect(typeof stat.lamboValue).toBe('number');
      expect(['ferrari', 'lamborghini', 'tie']).toContain(stat.winner);
    }
  });

  it('includes Horsepower, Torque, 0-60, and Top Speed stat labels', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    const labels = result.current.winners.map((s) => s.label);
    expect(labels).toContain('Horsepower');
    expect(labels).toContain('Torque (lb-ft)');
    expect(labels).toContain('0–60 mph (s)');
    expect(labels).toContain('Top Speed (mph)');
  });

  // -------------------------------------------------------------------------
  // Winner logic — higher-wins stats (HP, torque, top speed)
  // -------------------------------------------------------------------------

  it('awards Horsepower to Ferrari when Ferrari has higher HP', () => {
    // fastFerrari (478 HP) vs slowLambo (220 HP)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(fastFerrari);
      result.current.setSelectedLambo(slowLambo);
    });
    const hpStat = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hpStat?.winner).toBe('ferrari');
  });

  it('awards Horsepower to Lamborghini when Lamborghini has higher HP', () => {
    // fastLambo (610 HP) vs ferrariTestarossa (390 HP)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(fastLambo);
    });
    const hpStat = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hpStat?.winner).toBe('lamborghini');
  });

  it('awards Torque to Ferrari when Ferrari has higher torque', () => {
    // fastFerrari (424 lb-ft) vs slowLambo (180 lb-ft)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(fastFerrari);
      result.current.setSelectedLambo(slowLambo);
    });
    const torqueStat = result.current.winners.find((s) => s.label === 'Torque (lb-ft)');
    expect(torqueStat?.winner).toBe('ferrari');
  });

  it('awards Top Speed to Lamborghini when Lamborghini has higher top speed', () => {
    // lamboCountach (183 mph) vs ferrariTestarossa (181 mph)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    const topSpeedStat = result.current.winners.find((s) => s.label === 'Top Speed (mph)');
    expect(topSpeedStat?.winner).toBe('lamborghini');
  });

  // -------------------------------------------------------------------------
  // Winner logic — lower-wins stat (0-60 time)
  // -------------------------------------------------------------------------

  it('awards 0-60 to Lamborghini when Lamborghini has a lower (faster) 0-60 time', () => {
    // lamboCountach (5.0s) vs ferrariTestarossa (5.8s)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    const zeroSixty = result.current.winners.find((s) => s.label === '0–60 mph (s)');
    expect(zeroSixty?.winner).toBe('lamborghini');
  });

  it('awards 0-60 to Ferrari when Ferrari has a lower (faster) 0-60 time', () => {
    // fastFerrari (4.2s) vs slowLambo (7.5s)
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(fastFerrari);
      result.current.setSelectedLambo(slowLambo);
    });
    const zeroSixty = result.current.winners.find((s) => s.label === '0–60 mph (s)');
    expect(zeroSixty?.winner).toBe('ferrari');
  });

  // -------------------------------------------------------------------------
  // Winner logic — ties
  // -------------------------------------------------------------------------

  it('records "tie" when both cars have identical stats', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(tiedFerrari);
      result.current.setSelectedLambo(tiedLambo);
    });
    for (const stat of result.current.winners) {
      expect(stat.winner).toBe('tie');
    }
  });

  it('records correct stat values for a tied HP comparison', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(tiedFerrari);
      result.current.setSelectedLambo(tiedLambo);
    });
    const hpStat = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hpStat?.ferrariValue).toBe(400);
    expect(hpStat?.lamboValue).toBe(400);
  });

  // -------------------------------------------------------------------------
  // Stat values are populated correctly
  // -------------------------------------------------------------------------

  it('populates ferrariValue and lamboValue correctly from specs', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    const hpStat = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hpStat?.ferrariValue).toBe(ferrariTestarossa.specs.hp);
    expect(hpStat?.lamboValue).toBe(lamboCountach.specs.hp);
  });

  it('populates 0-60 values correctly from specs', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });
    const zeroSixty = result.current.winners.find((s) => s.label === '0–60 mph (s)');
    expect(zeroSixty?.ferrariValue).toBe(ferrariTestarossa.specs.zeroToSixtyMs);
    expect(zeroSixty?.lamboValue).toBe(lamboCountach.specs.zeroToSixtyMs);
  });

  // -------------------------------------------------------------------------
  // Replacing a selection
  // -------------------------------------------------------------------------

  it('updates winners when Ferrari selection is replaced', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });

    const firstHp = result.current.winners.find((s) => s.label === 'Horsepower')?.ferrariValue;

    act(() => {
      result.current.setSelectedFerrari(fastFerrari);
    });

    const updatedHp = result.current.winners.find((s) => s.label === 'Horsepower')?.ferrariValue;
    expect(updatedHp).not.toBe(firstHp);
    expect(updatedHp).toBe(fastFerrari.specs.hp);
  });

  it('updates winners when Lamborghini selection is replaced', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrariTestarossa);
      result.current.setSelectedLambo(lamboCountach);
    });

    const firstLamboHp = result.current.winners.find((s) => s.label === 'Horsepower')?.lamboValue;

    act(() => {
      result.current.setSelectedLambo(fastLambo);
    });

    const updatedLamboHp = result.current.winners.find((s) => s.label === 'Horsepower')?.lamboValue;
    expect(updatedLamboHp).not.toBe(firstLamboHp);
    expect(updatedLamboHp).toBe(fastLambo.specs.hp);
  });
});
