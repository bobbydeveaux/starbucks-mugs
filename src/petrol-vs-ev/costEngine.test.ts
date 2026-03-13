import { describe, it, expect } from 'vitest';
import {
  iceCostPerMile,
  evCostPerMile,
  annualCost,
  evCo2PerMile,
  breakevenYears,
  GRID_CO2_G_PER_KWH,
} from './costEngine';

// ---------------------------------------------------------------------------
// iceCostPerMile
// ---------------------------------------------------------------------------

describe('iceCostPerMile', () => {
  it('calculates correctly for a typical petrol car (145 ppl, 40 MPG)', () => {
    // (145 × 4.546) / 40 = 659.17 / 40 = 16.479...
    const result = iceCostPerMile(145, 40);
    expect(result).toBeCloseTo(16.479, 2);
  });

  it('calculates correctly for a diesel car (151 ppl, 55 MPG)', () => {
    // (151 × 4.546) / 55 = 686.446 / 55 = 12.480...
    const result = iceCostPerMile(151, 55);
    expect(result).toBeCloseTo(12.480, 2);
  });

  it('uses 4.546 litres per gallon conversion factor', () => {
    // With mpg=4.546, result equals pricePpl
    const result = iceCostPerMile(100, 4.546);
    expect(result).toBeCloseTo(100, 5);
  });

  it('scales linearly with price (doubling price doubles cost)', () => {
    const base = iceCostPerMile(100, 40);
    const doubled = iceCostPerMile(200, 40);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });

  it('scales inversely with MPG (halving MPG doubles cost)', () => {
    const base = iceCostPerMile(145, 40);
    const halfMpg = iceCostPerMile(145, 20);
    expect(halfMpg).toBeCloseTo(base * 2, 10);
  });

  it('returns a very large number for very low MPG (near-zero)', () => {
    const result = iceCostPerMile(145, 0.001);
    expect(result).toBeGreaterThan(100000);
  });
});

// ---------------------------------------------------------------------------
// evCostPerMile
// ---------------------------------------------------------------------------

describe('evCostPerMile', () => {
  it('calculates correctly for a typical EV (24.5 ppkwh, 3.9 mi/kWh)', () => {
    // 24.5 / 3.9 = 6.282...
    const result = evCostPerMile(24.5, 3.9);
    expect(result).toBeCloseTo(6.282, 2);
  });

  it('calculates correctly for an economy-7 tariff (13 ppkwh, 4.2 mi/kWh)', () => {
    // 13 / 4.2 = 3.095...
    const result = evCostPerMile(13, 4.2);
    expect(result).toBeCloseTo(3.095, 2);
  });

  it('scales linearly with tariff (doubling tariff doubles cost)', () => {
    const base = evCostPerMile(24.5, 3.9);
    const doubled = evCostPerMile(49, 3.9);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });

  it('scales inversely with efficiency (halving efficiency doubles cost)', () => {
    const base = evCostPerMile(24.5, 4);
    const halfEfficiency = evCostPerMile(24.5, 2);
    expect(halfEfficiency).toBeCloseTo(base * 2, 10);
  });

  it('returns efficiency value when tariff equals efficiency (result = 1 p/mile)', () => {
    const result = evCostPerMile(4, 4);
    expect(result).toBeCloseTo(1, 10);
  });

  it('returns a very large number for very low efficiency (near-zero)', () => {
    const result = evCostPerMile(24.5, 0.001);
    expect(result).toBeGreaterThan(10000);
  });
});

// ---------------------------------------------------------------------------
// annualCost
// ---------------------------------------------------------------------------

describe('annualCost', () => {
  it('calculates correctly for typical ICE cost-per-mile and mileage', () => {
    // 16.479 p/mile × 10000 miles = 164,790p
    const result = annualCost(16.479, 10000);
    expect(result).toBeCloseTo(164790, 0);
  });

  it('calculates correctly for a typical EV', () => {
    // 6.282 p/mile × 10000 miles = 62,820p
    const result = annualCost(6.282, 10000);
    expect(result).toBeCloseTo(62820, 0);
  });

  it('returns zero when annual miles is zero', () => {
    expect(annualCost(16.479, 0)).toBe(0);
  });

  it('returns zero when cost per mile is zero', () => {
    expect(annualCost(0, 10000)).toBe(0);
  });

  it('scales linearly with mileage', () => {
    const base = annualCost(10, 10000);
    const doubled = annualCost(10, 20000);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });

  it('scales linearly with cost per mile', () => {
    const base = annualCost(10, 10000);
    const doubled = annualCost(20, 10000);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });
});

// ---------------------------------------------------------------------------
// evCo2PerMile
// ---------------------------------------------------------------------------

describe('evCo2PerMile', () => {
  it('uses the 233 g/kWh grid average constant', () => {
    expect(GRID_CO2_G_PER_KWH).toBe(233);
  });

  it('calculates correctly for a typical EV (3.9 mi/kWh)', () => {
    // 233 / 3.9 = 59.74...
    const result = evCo2PerMile(3.9);
    expect(result).toBeCloseTo(59.74, 1);
  });

  it('calculates correctly for a highly efficient EV (5.0 mi/kWh)', () => {
    // 233 / 5.0 = 46.6
    const result = evCo2PerMile(5.0);
    expect(result).toBeCloseTo(46.6, 1);
  });

  it('calculates correctly for a less efficient EV (3.0 mi/kWh)', () => {
    // 233 / 3.0 = 77.666...
    const result = evCo2PerMile(3.0);
    expect(result).toBeCloseTo(77.667, 2);
  });

  it('scales inversely with efficiency (halving efficiency doubles CO2)', () => {
    const base = evCo2PerMile(4);
    const halfEfficiency = evCo2PerMile(2);
    expect(halfEfficiency).toBeCloseTo(base * 2, 10);
  });

  it('returns 233 g/mile when efficiency is exactly 1 mi/kWh', () => {
    expect(evCo2PerMile(1)).toBeCloseTo(233, 10);
  });

  it('returns a very large number for near-zero efficiency', () => {
    expect(evCo2PerMile(0.001)).toBeGreaterThan(100000);
  });
});

// ---------------------------------------------------------------------------
// breakevenYears
// ---------------------------------------------------------------------------

describe('breakevenYears', () => {
  it('calculates correctly for a typical scenario (£5000 delta, £1000/yr savings)', () => {
    expect(breakevenYears(5000, 1000)).toBeCloseTo(5, 10);
  });

  it('calculates correctly for a longer breakeven (£10000 delta, £800/yr savings)', () => {
    expect(breakevenYears(10000, 800)).toBeCloseTo(12.5, 10);
  });

  it('calculates correctly for a short breakeven (£2000 delta, £2000/yr savings)', () => {
    expect(breakevenYears(2000, 2000)).toBeCloseTo(1, 10);
  });

  it('returns Infinity when annual savings is zero', () => {
    expect(breakevenYears(5000, 0)).toBe(Infinity);
  });

  it('returns Infinity when annual savings is negative (EV costs more to run)', () => {
    expect(breakevenYears(5000, -500)).toBe(Infinity);
  });

  it('returns Infinity when both priceDelta and savings are zero', () => {
    expect(breakevenYears(0, 0)).toBe(Infinity);
  });

  it('returns zero when priceDelta is zero and savings are positive', () => {
    expect(breakevenYears(0, 1000)).toBeCloseTo(0, 10);
  });

  it('scales linearly with price delta', () => {
    const base = breakevenYears(5000, 1000);
    const doubled = breakevenYears(10000, 1000);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });

  it('scales inversely with annual savings', () => {
    const base = breakevenYears(5000, 1000);
    const doubled = breakevenYears(5000, 500);
    expect(doubled).toBeCloseTo(base * 2, 10);
  });
});
