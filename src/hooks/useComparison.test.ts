import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useComparison } from './useComparison';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(
  overrides: Partial<CarModel> & {
    id: string;
    brand: CarModel['brand'];
    hp: number;
    torque: number;
    zeroToSixty: number;
    topSpeed: number;
  },
): CarModel {
  return {
    model: 'Test Model',
    year: 2000,
    decade: 2000,
    image: '/images/test.jpg',
    eraRivals: [],
    specs: {
      hp: overrides.hp,
      torqueLbFt: overrides.torque,
      zeroToSixtyMs: overrides.zeroToSixty,
      topSpeedMph: overrides.topSpeed,
      engineConfig: 'V12',
    },
    ...overrides,
  };
}

const ferrari = makeCar({
  id: 'ferrari-test',
  brand: 'ferrari',
  hp: 500,
  torque: 350,
  zeroToSixty: 3.5,
  topSpeed: 200,
});

const lambo = makeCar({
  id: 'lambo-test',
  brand: 'lamborghini',
  hp: 480,
  torque: 380,
  zeroToSixty: 4.0,
  topSpeed: 195,
});

const equalLambo = makeCar({
  id: 'lambo-equal',
  brand: 'lamborghini',
  hp: 500,    // tie with ferrari
  torque: 350, // tie
  zeroToSixty: 3.5, // tie
  topSpeed: 200, // tie
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useComparison', () => {
  it('starts with null selections and empty winners array', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.selectedLambo).toBeNull();
    expect(result.current.winners).toEqual([]);
  });

  it('winners is empty when only a Ferrari is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedFerrari(ferrari));
    expect(result.current.winners).toEqual([]);
  });

  it('winners is empty when only a Lamborghini is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => result.current.setSelectedLambo(lambo));
    expect(result.current.winners).toEqual([]);
  });

  it('computes winners for all four stats when both cars are selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    expect(result.current.winners).toHaveLength(4);
  });

  it('correctly identifies the higher-HP car as winner', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari); // hp: 500
      result.current.setSelectedLambo(lambo);     // hp: 480
    });
    const hpStat = result.current.winners.find((w) => w.label === 'Horsepower');
    expect(hpStat?.winner).toBe('ferrari');
    expect(hpStat?.ferrariValue).toBe(500);
    expect(hpStat?.lamboValue).toBe(480);
  });

  it('correctly identifies the higher-torque car as winner', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari); // torque: 350
      result.current.setSelectedLambo(lambo);     // torque: 380
    });
    const stat = result.current.winners.find((w) => w.label === 'Torque (lb-ft)');
    expect(stat?.winner).toBe('lamborghini');
  });

  it('correctly identifies the lower 0-60 time as winner (lower is faster)', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari); // 0-60: 3.5s (faster)
      result.current.setSelectedLambo(lambo);     // 0-60: 4.0s
    });
    const stat = result.current.winners.find((w) => w.label === '0–60 mph (s)');
    expect(stat?.winner).toBe('ferrari');
  });

  it('correctly identifies the higher top-speed car as winner', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari); // topSpeed: 200
      result.current.setSelectedLambo(lambo);     // topSpeed: 195
    });
    const stat = result.current.winners.find((w) => w.label === 'Top Speed (mph)');
    expect(stat?.winner).toBe('ferrari');
  });

  it('returns "tie" when both cars have the same stat value', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(equalLambo);
    });
    result.current.winners.forEach((stat) => {
      expect(stat.winner).toBe('tie');
    });
  });

  it('updates winners reactively when a different car is selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    const hpBefore = result.current.winners.find((w) => w.label === 'Horsepower')?.winner;

    const strongerLambo = makeCar({
      id: 'lambo-strong',
      brand: 'lamborghini',
      hp: 600, // beats ferrari (500)
      torque: 400,
      zeroToSixty: 3.0,
      topSpeed: 210,
    });
    act(() => result.current.setSelectedLambo(strongerLambo));
    const hpAfter = result.current.winners.find((w) => w.label === 'Horsepower')?.winner;

    expect(hpBefore).toBe('ferrari');
    expect(hpAfter).toBe('lamborghini');
  });

  it('resets to empty winners when a car is deselected (set to null)', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    expect(result.current.winners).toHaveLength(4);

    act(() => result.current.setSelectedFerrari(null));
    expect(result.current.winners).toEqual([]);
  });
});
