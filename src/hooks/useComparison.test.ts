import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useComparison } from './useComparison';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrari: CarModel = {
  id: 'ferrari-testarossa-1984',
  brand: 'ferrari',
  model: 'Testarossa',
  year: 1984,
  decade: 1980,
  image: '/images/ferrari/testarossa.jpg',
  price: 87000,
  specs: {
    hp: 390,
    torqueLbFt: 362,
    zeroToSixtyMs: 5.2,
    topSpeedMph: 181,
    engineConfig: 'Flat-12, 4.9L',
  },
  eraRivals: ['lambo-countach-lp500s-1982'],
};

const lambo: CarModel = {
  id: 'lambo-countach-lp500s-1982',
  brand: 'lamborghini',
  model: 'Countach LP500S',
  year: 1982,
  decade: 1980,
  image: '/images/lambo/countach-lp500s.jpg',
  price: 100000,
  specs: {
    hp: 375,
    torqueLbFt: 268,
    zeroToSixtyMs: 4.9,
    topSpeedMph: 183,
    engineConfig: 'V12, 4.8L',
  },
  eraRivals: ['ferrari-testarossa-1984'],
};

/** Car identical to ferrari for tie-test purposes */
const ferrariTwin: CarModel = {
  ...ferrari,
  id: 'ferrari-testarossa-twin',
  specs: { ...ferrari.specs },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useComparison', () => {
  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  it('starts with both selections as null', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.selectedLambo).toBeNull();
  });

  it('starts with an empty winners array', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.winners).toEqual([]);
  });

  it('exposes setSelectedFerrari and setSelectedLambo setters', () => {
    const { result } = renderHook(() => useComparison());
    expect(typeof result.current.setSelectedFerrari).toBe('function');
    expect(typeof result.current.setSelectedLambo).toBe('function');
  });

  // -------------------------------------------------------------------------
  // Selecting cars
  // -------------------------------------------------------------------------

  it('updates selectedFerrari when setSelectedFerrari is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedFerrari(ferrari));
    expect(result.current.selectedFerrari).toBe(ferrari);
  });

  it('updates selectedLambo when setSelectedLambo is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedLambo(lambo));
    expect(result.current.selectedLambo).toBe(lambo);
  });

  it('allows deselecting a Ferrari by setting null', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedFerrari(ferrari));
    act(() => result.current.setSelectedFerrari(null));
    expect(result.current.selectedFerrari).toBeNull();
  });

  it('allows deselecting a Lamborghini by setting null', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedLambo(lambo));
    act(() => result.current.setSelectedLambo(null));
    expect(result.current.selectedLambo).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Winners — empty when one or both cars are missing
  // -------------------------------------------------------------------------

  it('returns empty winners when only ferrari is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedFerrari(ferrari));
    expect(result.current.winners).toEqual([]);
  });

  it('returns empty winners when only lambo is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedLambo(lambo));
    expect(result.current.winners).toEqual([]);
  });

  it('returns empty winners after deselecting a car', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    act(() => result.current.setSelectedFerrari(null));
    expect(result.current.winners).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // Winners — correct shape when both cars are selected
  // -------------------------------------------------------------------------

  it('returns four winners when both cars are selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    expect(result.current.winners).toHaveLength(4);
  });

  it('each stat has label, ferrariValue, lamboValue, and winner fields', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
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

  it('includes Horsepower, Torque, 0-60, and Top Speed stats', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const labels = result.current.winners.map((s) => s.label);
    expect(labels).toContain('Horsepower');
    expect(labels).toContain('Torque (lb-ft)');
    expect(labels).toContain('0–60 mph (s)');
    expect(labels).toContain('Top Speed (mph)');
  });

  // -------------------------------------------------------------------------
  // Winner logic — higher-is-better stats
  // -------------------------------------------------------------------------

  it('awards Horsepower winner to the car with more hp', () => {
    // ferrari.hp=390 > lambo.hp=375 → ferrari wins
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const hp = result.current.winners.find((s) => s.label === 'Horsepower')!;
    expect(hp.ferrariValue).toBe(390);
    expect(hp.lamboValue).toBe(375);
    expect(hp.winner).toBe('ferrari');
  });

  it('awards Torque winner to the car with more torque', () => {
    // ferrari.torqueLbFt=362 > lambo.torqueLbFt=268 → ferrari wins
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const torque = result.current.winners.find((s) => s.label === 'Torque (lb-ft)')!;
    expect(torque.winner).toBe('ferrari');
  });

  it('awards Top Speed winner to the car with higher topSpeedMph', () => {
    // lambo.topSpeedMph=183 > ferrari.topSpeedMph=181 → lambo wins
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const topSpeed = result.current.winners.find((s) => s.label === 'Top Speed (mph)')!;
    expect(topSpeed.winner).toBe('lamborghini');
  });

  // -------------------------------------------------------------------------
  // Winner logic — lower-is-better stats
  // -------------------------------------------------------------------------

  it('awards 0-60 winner to the car with the lower time', () => {
    // lambo.zeroToSixtyMs=4.9 < ferrari.zeroToSixtyMs=5.2 → lambo wins
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const zeroSixty = result.current.winners.find((s) => s.label === '0–60 mph (s)')!;
    expect(zeroSixty.winner).toBe('lamborghini');
  });

  // -------------------------------------------------------------------------
  // Winner logic — ties
  // -------------------------------------------------------------------------

  it('returns "tie" winner when both cars have equal stat values', () => {
    const { result } = renderHook(() => useComparison());
    // ferrariTwin has identical specs to ferrari
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(ferrariTwin as unknown as CarModel);
    });
    for (const stat of result.current.winners) {
      expect(stat.winner).toBe('tie');
    }
  });

  // -------------------------------------------------------------------------
  // Winners reflect correct raw values
  // -------------------------------------------------------------------------

  it('ferrariValue and lamboValue match the selected cars specs', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const hp = result.current.winners.find((s) => s.label === 'Horsepower')!;
    expect(hp.ferrariValue).toBe(ferrari.specs.hp);
    expect(hp.lamboValue).toBe(lambo.specs.hp);
  });

  // -------------------------------------------------------------------------
  // Reactivity — winners update when selection changes
  // -------------------------------------------------------------------------

  it('winners update when a new car is selected', () => {
    const betterLambo: CarModel = {
      ...lambo,
      specs: { ...lambo.specs, hp: 500 },
    };

    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });

    const hpBefore = result.current.winners.find((s) => s.label === 'Horsepower')!;
    expect(hpBefore.winner).toBe('ferrari');

    act(() => result.current.setSelectedLambo(betterLambo));

    const hpAfter = result.current.winners.find((s) => s.label === 'Horsepower')!;
    expect(hpAfter.lamboValue).toBe(500);
    expect(hpAfter.winner).toBe('lamborghini');
  });
});
