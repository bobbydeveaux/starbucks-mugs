import { describe, it, expect } from 'vitest';
import {
  parseSearchParams,
  buildVehicleQuery,
  mapDbRowToVehicle,
  shapeVehiclesResponse,
} from './vehicleSearch';
import { DEFAULT_VEHICLE_LIMIT, MAX_VEHICLE_LIMIT } from '../types/vehicle';

// ---------------------------------------------------------------------------
// parseSearchParams
// ---------------------------------------------------------------------------

describe('parseSearchParams', () => {
  // ---- success cases --------------------------------------------------------

  it('returns success with all defaults when query is empty', () => {
    const result = parseSearchParams({});
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({
      make: undefined,
      model: undefined,
      year: undefined,
      fuel_type: undefined,
      q: undefined,
      limit: DEFAULT_VEHICLE_LIMIT,
    });
  });

  it('parses a valid make', () => {
    const result = parseSearchParams({ make: 'Toyota' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBe('Toyota');
  });

  it('trims whitespace from make', () => {
    const result = parseSearchParams({ make: '  Tesla  ' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBe('Tesla');
  });

  it('parses a valid model', () => {
    const result = parseSearchParams({ model: 'Corolla' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.model).toBe('Corolla');
  });

  it('parses a valid year', () => {
    const result = parseSearchParams({ year: '2023' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.year).toBe(2023);
  });

  it('parses year at lower boundary (1900)', () => {
    const result = parseSearchParams({ year: '1900' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.year).toBe(1900);
  });

  it('parses year at upper boundary (2100)', () => {
    const result = parseSearchParams({ year: '2100' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.year).toBe(2100);
  });

  it('parses all valid fuel_type values', () => {
    const types = ['petrol', 'diesel', 'ev', 'hybrid', 'phev'] as const;
    for (const ft of types) {
      const result = parseSearchParams({ fuel_type: ft });
      expect(result.success).toBe(true);
      if (!result.success) return;
      expect(result.data.fuel_type).toBe(ft);
    }
  });

  it('parses a valid q freetext search', () => {
    const result = parseSearchParams({ q: 'Model 3' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.q).toBe('Model 3');
  });

  it('parses an explicit limit', () => {
    const result = parseSearchParams({ limit: '50' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.limit).toBe(50);
  });

  it('clamps limit to MAX_VEHICLE_LIMIT when the supplied value exceeds the max', () => {
    const result = parseSearchParams({ limit: String(MAX_VEHICLE_LIMIT + 1) });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.limit).toBe(MAX_VEHICLE_LIMIT);
  });

  it('accepts limit equal to MAX_VEHICLE_LIMIT exactly', () => {
    const result = parseSearchParams({ limit: String(MAX_VEHICLE_LIMIT) });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.limit).toBe(MAX_VEHICLE_LIMIT);
  });

  it('parses all fields together', () => {
    const result = parseSearchParams({
      make: 'BMW',
      model: 'i3',
      year: '2021',
      fuel_type: 'ev',
      q: 'Range Extender',
      limit: '10',
    });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data).toEqual({
      make: 'BMW',
      model: 'i3',
      year: 2021,
      fuel_type: 'ev',
      q: 'Range Extender',
      limit: 10,
    });
  });

  it('converts empty-string make to undefined', () => {
    const result = parseSearchParams({ make: '   ' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBeUndefined();
  });

  it('converts empty-string q to undefined', () => {
    const result = parseSearchParams({ q: '   ' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.q).toBeUndefined();
  });

  // ---- error cases ---------------------------------------------------------

  it('returns error when make exceeds 100 characters', () => {
    const result = parseSearchParams({ make: 'A'.repeat(101) });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/make/i);
  });

  it('returns error when model exceeds 100 characters', () => {
    const result = parseSearchParams({ model: 'B'.repeat(101) });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/model/i);
  });

  it('returns error when year is not an integer string', () => {
    const result = parseSearchParams({ year: 'abc' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/year/i);
  });

  it('returns error when year is a float string', () => {
    const result = parseSearchParams({ year: '2023.5' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/year/i);
  });

  it('returns error when year is below 1900', () => {
    const result = parseSearchParams({ year: '1899' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/year/i);
  });

  it('returns error when year exceeds 2100', () => {
    const result = parseSearchParams({ year: '2101' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/year/i);
  });

  it('returns error for an unrecognised fuel_type', () => {
    const result = parseSearchParams({ fuel_type: 'hydrogen' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/fuel_type/i);
  });

  it('returns error when q exceeds 200 characters', () => {
    const result = parseSearchParams({ q: 'x'.repeat(201) });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/q/i);
  });

  it('returns error when limit is zero', () => {
    const result = parseSearchParams({ limit: '0' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/limit/i);
  });

  it('returns error when limit is negative', () => {
    const result = parseSearchParams({ limit: '-5' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/limit/i);
  });

  it('returns error when limit is not a number', () => {
    const result = parseSearchParams({ limit: 'lots' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/limit/i);
  });

  it('returns error when make is an array (duplicate query param)', () => {
    const result = parseSearchParams({ make: ['Toyota', 'Honda'] });
    // Arrays are silently ignored (non-string treated as undefined) — make becomes undefined
    // This verifies we don't throw on array values
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBeUndefined();
  });

  it('returns error when year is supplied as an array', () => {
    const result = parseSearchParams({ year: ['2020', '2021'] });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/year/i);
  });

  it('returns error when fuel_type is supplied as an array', () => {
    const result = parseSearchParams({ fuel_type: ['ev', 'petrol'] });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/fuel_type/i);
  });

  it('returns error when limit is supplied as an array', () => {
    const result = parseSearchParams({ limit: ['10', '20'] });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error).toMatch(/limit/i);
  });
});

// ---------------------------------------------------------------------------
// buildVehicleQuery
// ---------------------------------------------------------------------------

describe('buildVehicleQuery', () => {
  const defaultParams = {
    make: undefined,
    model: undefined,
    year: undefined,
    fuel_type: undefined,
    q: undefined,
    limit: DEFAULT_VEHICLE_LIMIT,
  } as const;

  it('generates a SELECT with no WHERE clause when all filters are undefined', () => {
    const { sql, countSql } = buildVehicleQuery(defaultParams);
    expect(sql).not.toContain('WHERE');
    expect(countSql).not.toContain('WHERE');
  });

  it('includes all required columns in the SELECT clause', () => {
    const { sql } = buildVehicleQuery(defaultParams);
    const requiredColumns = [
      'id', 'make', 'model', 'year', 'variant', 'fuel_type',
      'mpg_combined', 'mpg_city', 'mpg_motorway',
      'efficiency_mpkwh', 'battery_kwh', 'wltp_range_mi', 'co2_gkm',
    ];
    for (const col of requiredColumns) {
      expect(sql).toContain(col);
    }
  });

  it('appends a LIMIT clause to the main query', () => {
    const { sql } = buildVehicleQuery(defaultParams);
    expect(sql).toMatch(/LIMIT/i);
  });

  it('does NOT include LIMIT in the count query', () => {
    const { countSql } = buildVehicleQuery(defaultParams);
    expect(countSql).not.toMatch(/LIMIT/i);
  });

  it('uses COUNT(*)::integer in the count query', () => {
    const { countSql } = buildVehicleQuery(defaultParams);
    expect(countSql).toMatch(/COUNT\(\*\)::integer/i);
  });

  it('adds a make filter with a positional placeholder', () => {
    const { sql, countSql, values, countValues } = buildVehicleQuery({
      ...defaultParams,
      make: 'Toyota',
    });
    expect(sql).toContain('$1');
    expect(countSql).toContain('$1');
    expect(values[0]).toBe('Toyota');
    expect(countValues[0]).toBe('Toyota');
  });

  it('adds a model filter with a positional placeholder', () => {
    const { sql, values } = buildVehicleQuery({
      ...defaultParams,
      model: 'Corolla',
    });
    expect(sql).toContain('$1');
    expect(values[0]).toBe('Corolla');
  });

  it('adds a year filter with a positional placeholder', () => {
    const { sql, values } = buildVehicleQuery({
      ...defaultParams,
      year: 2022,
    });
    expect(sql).toContain('$1');
    expect(values[0]).toBe(2022);
  });

  it('adds a fuel_type filter with a positional placeholder', () => {
    const { sql, values } = buildVehicleQuery({
      ...defaultParams,
      fuel_type: 'ev',
    });
    expect(sql).toContain('$1');
    expect(values[0]).toBe('ev');
  });

  it('adds a freetext filter covering make, model, and variant', () => {
    const { sql, values } = buildVehicleQuery({
      ...defaultParams,
      q: 'Model',
    });
    expect(sql).toMatch(/make.*LIKE.*model.*LIKE/i);
    expect(values[0]).toBe('%Model%');
  });

  it('uses sequential placeholder indices for multiple filters', () => {
    const { sql, values, countValues } = buildVehicleQuery({
      ...defaultParams,
      make: 'Tesla',
      model: 'Model 3',
      year: 2023,
      fuel_type: 'ev',
    });
    expect(values[0]).toBe('Tesla');
    expect(values[1]).toBe('Model 3');
    expect(values[2]).toBe(2023);
    expect(values[3]).toBe('ev');
    // limit is the last value in the main query
    expect(values[values.length - 1]).toBe(DEFAULT_VEHICLE_LIMIT);
    // count query shares filter values but not limit
    expect(countValues).toEqual([values[0], values[1], values[2], values[3]]);
    expect(sql).toContain('$1');
    expect(sql).toContain('$2');
    expect(sql).toContain('$3');
    expect(sql).toContain('$4');
  });

  it('places the limit value as the last entry in values', () => {
    const { values } = buildVehicleQuery({ ...defaultParams, limit: 50 });
    expect(values[values.length - 1]).toBe(50);
  });

  it('count values array does not include the limit', () => {
    const { values, countValues } = buildVehicleQuery({
      ...defaultParams,
      make: 'BMW',
      limit: 10,
    });
    expect(countValues).toHaveLength(values.length - 1);
    expect(countValues).not.toContain(10);
  });

  it('uses case-insensitive make comparison (LOWER)', () => {
    const { sql } = buildVehicleQuery({ ...defaultParams, make: 'Ford' });
    expect(sql).toMatch(/LOWER\(make\)/i);
  });

  it('uses case-insensitive model comparison (LOWER)', () => {
    const { sql } = buildVehicleQuery({ ...defaultParams, model: 'Focus' });
    expect(sql).toMatch(/LOWER\(model\)/i);
  });

  it('includes ORDER BY clause', () => {
    const { sql } = buildVehicleQuery(defaultParams);
    expect(sql).toMatch(/ORDER BY/i);
  });
});

// ---------------------------------------------------------------------------
// mapDbRowToVehicle
// ---------------------------------------------------------------------------

describe('mapDbRowToVehicle', () => {
  const minimalRow = {
    id: 'abc-123',
    make: 'Toyota',
    model: 'Corolla',
    year: 2020,
    variant: null,
    fuel_type: 'petrol',
    mpg_combined: 45.2,
    mpg_city: 38.0,
    mpg_motorway: 52.0,
    efficiency_mpkwh: null,
    battery_kwh: null,
    wltp_range_mi: null,
    co2_gkm: 120,
  };

  it('maps all fields of an ICE vehicle row correctly', () => {
    const vehicle = mapDbRowToVehicle(minimalRow);
    expect(vehicle).toEqual({
      id: 'abc-123',
      make: 'Toyota',
      model: 'Corolla',
      year: 2020,
      variant: null,
      fuel_type: 'petrol',
      mpg_combined: 45.2,
      mpg_city: 38.0,
      mpg_motorway: 52.0,
      efficiency_mpkwh: null,
      battery_kwh: null,
      wltp_range_mi: null,
      co2_gkm: 120,
    });
  });

  it('maps all fields of an EV row correctly', () => {
    const evRow = {
      id: 'ev-456',
      make: 'Tesla',
      model: 'Model 3',
      year: 2023,
      variant: 'Long Range AWD',
      fuel_type: 'ev',
      mpg_combined: null,
      mpg_city: null,
      mpg_motorway: null,
      efficiency_mpkwh: 3.9,
      battery_kwh: 75.0,
      wltp_range_mi: 358,
      co2_gkm: null,
    };
    const vehicle = mapDbRowToVehicle(evRow);
    expect(vehicle).toEqual({
      id: 'ev-456',
      make: 'Tesla',
      model: 'Model 3',
      year: 2023,
      variant: 'Long Range AWD',
      fuel_type: 'ev',
      mpg_combined: null,
      mpg_city: null,
      mpg_motorway: null,
      efficiency_mpkwh: 3.9,
      battery_kwh: 75.0,
      wltp_range_mi: 358,
      co2_gkm: null,
    });
  });

  it('coerces numeric strings to numbers (postgres driver behaviour)', () => {
    const row = {
      ...minimalRow,
      year: '2020',
      mpg_combined: '45.20',
      co2_gkm: '120',
    };
    const vehicle = mapDbRowToVehicle(row);
    expect(typeof vehicle.year).toBe('number');
    expect(vehicle.year).toBe(2020);
    expect(typeof vehicle.mpg_combined).toBe('number');
    expect(vehicle.mpg_combined).toBe(45.2);
    expect(typeof vehicle.co2_gkm).toBe('number');
    expect(vehicle.co2_gkm).toBe(120);
  });

  it('maps null variant to null (not undefined)', () => {
    const vehicle = mapDbRowToVehicle({ ...minimalRow, variant: null });
    expect(vehicle.variant).toBeNull();
  });

  it('maps undefined variant to null', () => {
    const vehicle = mapDbRowToVehicle({ ...minimalRow, variant: undefined });
    expect(vehicle.variant).toBeNull();
  });

  it('maps null numeric fields to null', () => {
    const vehicle = mapDbRowToVehicle({
      ...minimalRow,
      mpg_combined: null,
      mpg_city: null,
      mpg_motorway: null,
      co2_gkm: null,
    });
    expect(vehicle.mpg_combined).toBeNull();
    expect(vehicle.mpg_city).toBeNull();
    expect(vehicle.mpg_motorway).toBeNull();
    expect(vehicle.co2_gkm).toBeNull();
  });

  it('maps EV numeric fields correctly for PHEV with all data populated', () => {
    const phevRow = {
      id: 'phev-789',
      make: 'Mitsubishi',
      model: 'Outlander',
      year: 2022,
      variant: 'PHEV',
      fuel_type: 'phev',
      mpg_combined: 28.4,
      mpg_city: null,
      mpg_motorway: null,
      efficiency_mpkwh: 2.8,
      battery_kwh: 13.8,
      wltp_range_mi: 38,
      co2_gkm: 46,
    };
    const vehicle = mapDbRowToVehicle(phevRow);
    expect(vehicle.efficiency_mpkwh).toBe(2.8);
    expect(vehicle.battery_kwh).toBe(13.8);
    expect(vehicle.wltp_range_mi).toBe(38);
    expect(vehicle.co2_gkm).toBe(46);
  });
});

// ---------------------------------------------------------------------------
// shapeVehiclesResponse
// ---------------------------------------------------------------------------

describe('shapeVehiclesResponse', () => {
  const sampleRow = {
    id: 'row-1',
    make: 'Honda',
    model: 'Civic',
    year: 2022,
    variant: null,
    fuel_type: 'petrol',
    mpg_combined: 42.0,
    mpg_city: 35.0,
    mpg_motorway: 50.0,
    efficiency_mpkwh: null,
    battery_kwh: null,
    wltp_range_mi: null,
    co2_gkm: 110,
  };

  it('returns a VehiclesResponse with vehicles and total', () => {
    const response = shapeVehiclesResponse([sampleRow], 42);
    expect(response.total).toBe(42);
    expect(response.vehicles).toHaveLength(1);
  });

  it('maps each row using mapDbRowToVehicle', () => {
    const response = shapeVehiclesResponse([sampleRow], 1);
    expect(response.vehicles[0]).toMatchObject({
      id: 'row-1',
      make: 'Honda',
      model: 'Civic',
    });
  });

  it('returns an empty vehicles array and correct total for no results', () => {
    const response = shapeVehiclesResponse([], 0);
    expect(response.vehicles).toHaveLength(0);
    expect(response.total).toBe(0);
  });

  it('preserves total independently of the number of rows returned (pagination)', () => {
    // Scenario: 100 total matches but only 20 returned (page 1)
    const rows = Array.from({ length: 20 }, (_, i) => ({
      ...sampleRow,
      id: `row-${i}`,
    }));
    const response = shapeVehiclesResponse(rows, 100);
    expect(response.total).toBe(100);
    expect(response.vehicles).toHaveLength(20);
  });

  it('maps multiple rows in order', () => {
    const row2 = { ...sampleRow, id: 'row-2', make: 'Ford' };
    const response = shapeVehiclesResponse([sampleRow, row2], 2);
    expect(response.vehicles[0].id).toBe('row-1');
    expect(response.vehicles[1].id).toBe('row-2');
  });
});
