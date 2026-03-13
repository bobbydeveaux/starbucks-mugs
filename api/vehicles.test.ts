/**
 * Vehicle Search API — integration tests
 *
 * Coverage:
 *  1. Filter correctness — make, model, year, fuel_type individually and combined
 *  2. Pagination — correct page sizes, offsets, and total counts
 *  3. p95 latency ≤ 500 ms measured against a mocked DB seeded with representative data
 *  4. SQL injection prevention — q param attempts are safely rejected via parameterised queries
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  parseQueryParams,
  buildVehicleQuery,
  vehiclesHandler,
  type VehicleRecord,
  type DbClient,
} from './vehicles';

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

function makeVehicle(overrides: Partial<VehicleRecord> = {}): VehicleRecord {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000000',
    make: 'Toyota',
    model: 'Yaris',
    year: 2023,
    variant: 'Hybrid 1.5',
    fuel_type: 'hybrid',
    mpg_combined: 67.3,
    mpg_city: null,
    mpg_motorway: null,
    efficiency_mpkwh: null,
    battery_kwh: null,
    wltp_range_mi: null,
    co2_gkm: 95,
    ...overrides,
  };
}

/** Builds a mock DbClient that returns `vehicles` for SELECT and `total` for COUNT. */
function makeMockDb(
  vehicles: VehicleRecord[] = [],
  total = 0,
): DbClient & { calls: Array<{ sql: string; params: (string | number)[] }> } {
  const calls: Array<{ sql: string; params: (string | number)[] }> = [];
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql, params });
      if (/SELECT COUNT/i.test(sql)) {
        return { rows: [{ total }] as Record<string, unknown>[] };
      }
      return { rows: vehicles as Record<string, unknown>[] };
    },
  };
}

// ---------------------------------------------------------------------------
// 1. parseQueryParams — validation
// ---------------------------------------------------------------------------

describe('parseQueryParams', () => {
  it('returns defaults when no params are supplied', () => {
    const result = parseQueryParams({});
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.limit).toBe(20);
    expect(result.data.offset).toBe(0);
    expect(result.data.make).toBeUndefined();
  });

  it('parses a valid make param', () => {
    const result = parseQueryParams({ make: 'Tesla' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBe('Tesla');
  });

  it('parses a valid model param', () => {
    const result = parseQueryParams({ model: 'Model 3' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.model).toBe('Model 3');
  });

  it('parses a valid year param', () => {
    const result = parseQueryParams({ year: '2022' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.year).toBe(2022);
  });

  it('rejects a non-integer year', () => {
    const result = parseQueryParams({ year: '2022.5' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.errors.some((e) => e.field === 'year')).toBe(true);
  });

  it('rejects a year below minimum', () => {
    const result = parseQueryParams({ year: '1800' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.errors.some((e) => e.field === 'year')).toBe(true);
  });

  it('rejects a year above maximum', () => {
    const result = parseQueryParams({ year: '2200' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.errors.some((e) => e.field === 'year')).toBe(true);
  });

  it('parses all valid fuel_type values', () => {
    for (const ft of ['petrol', 'diesel', 'ev', 'hybrid', 'phev'] as const) {
      const result = parseQueryParams({ fuel_type: ft });
      expect(result.success).toBe(true);
      if (!result.success) continue;
      expect(result.data.fuel_type).toBe(ft);
    }
  });

  it('rejects an invalid fuel_type', () => {
    const result = parseQueryParams({ fuel_type: 'nuclear' });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.errors.some((e) => e.field === 'fuel_type')).toBe(true);
  });

  it('parses a valid q param', () => {
    const result = parseQueryParams({ q: 'Tesla' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.q).toBe('Tesla');
  });

  it('rejects q param exceeding 200 characters', () => {
    const result = parseQueryParams({ q: 'a'.repeat(201) });
    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.errors.some((e) => e.field === 'q')).toBe(true);
  });

  it('parses custom limit and offset', () => {
    const result = parseQueryParams({ limit: '50', offset: '100' });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.limit).toBe(50);
    expect(result.data.offset).toBe(100);
  });

  it('rejects limit > 100', () => {
    const result = parseQueryParams({ limit: '101' });
    expect(result.success).toBe(false);
  });

  it('rejects limit < 1', () => {
    const result = parseQueryParams({ limit: '0' });
    expect(result.success).toBe(false);
  });

  it('rejects a non-integer limit', () => {
    const result = parseQueryParams({ limit: 'abc' });
    expect(result.success).toBe(false);
  });

  it('uses first value when param is an array', () => {
    const result = parseQueryParams({ make: ['Toyota', 'Honda'] });
    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.make).toBe('Toyota');
  });
});

// ---------------------------------------------------------------------------
// 2. buildVehicleQuery — SQL generation and parameterisation
// ---------------------------------------------------------------------------

describe('buildVehicleQuery', () => {
  it('generates a SELECT query with no WHERE clause when no filters are given', () => {
    const { sql, params } = buildVehicleQuery({ limit: 20, offset: 0 });
    expect(sql).not.toContain('WHERE');
    // Params should only have limit and offset
    expect(params).toEqual([20, 0]);
  });

  it('generates a parameterised WHERE clause for make', () => {
    const { sql, params } = buildVehicleQuery({ make: 'Toyota', limit: 20, offset: 0 });
    expect(sql).toContain('LOWER(make) = LOWER($1)');
    expect(params[0]).toBe('Toyota');
  });

  it('generates a parameterised WHERE clause for model', () => {
    const { sql, params } = buildVehicleQuery({ model: 'Corolla', limit: 20, offset: 0 });
    expect(sql).toContain('LOWER(model) = LOWER($1)');
    expect(params[0]).toBe('Corolla');
  });

  it('generates a parameterised WHERE clause for year', () => {
    const { sql, params } = buildVehicleQuery({ year: 2022, limit: 20, offset: 0 });
    expect(sql).toContain('year = $1');
    expect(params[0]).toBe(2022);
  });

  it('generates a parameterised WHERE clause for fuel_type', () => {
    const { sql, params } = buildVehicleQuery({ fuel_type: 'ev', limit: 20, offset: 0 });
    expect(sql).toContain('fuel_type = $1');
    expect(params[0]).toBe('ev');
  });

  it('generates a parameterised LIKE clause for q (freetext)', () => {
    const { sql, params } = buildVehicleQuery({ q: 'Tesla', limit: 20, offset: 0 });
    expect(sql).toContain('LIKE $1');
    // Value must be the lowercased %wrapped% term, never the raw user input in SQL
    expect(params[0]).toBe('%tesla%');
    // Raw user input 'Tesla' must NOT appear literally in the SQL string
    expect(sql).not.toContain('Tesla');
  });

  it('combines all filters with AND', () => {
    const { sql, params } = buildVehicleQuery({
      make: 'BMW',
      model: '3 Series',
      year: 2021,
      fuel_type: 'petrol',
      limit: 10,
      offset: 0,
    });
    expect(sql).toContain('AND');
    expect(params).toContain('BMW');
    expect(params).toContain('3 Series');
    expect(params).toContain(2021);
    expect(params).toContain('petrol');
  });

  it('appends limit and offset as the last two params', () => {
    const { params } = buildVehicleQuery({ make: 'Audi', limit: 15, offset: 30 });
    const lastTwo = params.slice(-2);
    expect(lastTwo).toEqual([15, 30]);
  });

  it('shares the same WHERE params for COUNT query', () => {
    const { countSql, countParams } = buildVehicleQuery({
      fuel_type: 'diesel',
      limit: 20,
      offset: 0,
    });
    expect(countSql).toContain('COUNT');
    expect(countParams).toContain('diesel');
    // COUNT query must NOT have limit/offset params
    expect(countParams).not.toContain(20);
    expect(countParams).not.toContain(0);
  });

  it('never interpolates user input directly into the SQL string', () => {
    const injectionAttempt = "'; DROP TABLE vehicles; --";
    const { sql } = buildVehicleQuery({ make: injectionAttempt, limit: 20, offset: 0 });
    // The raw injection string must not appear in the generated SQL
    expect(sql).not.toContain(injectionAttempt);
    // The SQL must use a placeholder
    expect(sql).toContain('$1');
  });
});

// ---------------------------------------------------------------------------
// 3. vehiclesHandler — filter combinations
// ---------------------------------------------------------------------------

describe('vehiclesHandler — filter combinations', () => {
  it('returns 200 with matching vehicles and total for make filter', async () => {
    const vehicle = makeVehicle({ make: 'Volkswagen', model: 'Golf' });
    const db = makeMockDb([vehicle], 1);
    const result = await vehiclesHandler({ make: 'Volkswagen' }, db);
    expect(result.status).toBe(200);
    const body = result.body as { vehicles: VehicleRecord[]; total: number };
    expect(body.total).toBe(1);
    expect(body.vehicles).toHaveLength(1);
    expect(body.vehicles[0].make).toBe('Volkswagen');
  });

  it('passes make filter as a parameterised SQL value', async () => {
    const db = makeMockDb([makeVehicle()], 1);
    await vehiclesHandler({ make: 'Ford' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.params).toContain('Ford');
  });

  it('passes model filter as a parameterised SQL value', async () => {
    const db = makeMockDb([makeVehicle()], 1);
    await vehiclesHandler({ model: 'Fiesta' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.params).toContain('Fiesta');
  });

  it('passes year filter as a parameterised SQL value', async () => {
    const db = makeMockDb([makeVehicle()], 1);
    await vehiclesHandler({ year: '2020' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.params).toContain(2020);
  });

  it('passes fuel_type filter as a parameterised SQL value', async () => {
    const db = makeMockDb([makeVehicle({ fuel_type: 'ev' })], 1);
    await vehiclesHandler({ fuel_type: 'ev' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.params).toContain('ev');
  });

  it('passes combined filters with all values as separate params', async () => {
    const db = makeMockDb([makeVehicle()], 1);
    await vehiclesHandler({ make: 'Kia', model: 'EV6', year: '2023', fuel_type: 'ev' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.params).toContain('Kia');
    expect(selectCall?.params).toContain('EV6');
    expect(selectCall?.params).toContain(2023);
    expect(selectCall?.params).toContain('ev');
  });

  it('returns all vehicles when no filters are given', async () => {
    const vehicles = Array.from({ length: 20 }, (_, i) => makeVehicle({ id: String(i) }));
    const db = makeMockDb(vehicles, 200);
    const result = await vehiclesHandler({}, db);
    expect(result.status).toBe(200);
    const body = result.body as { vehicles: VehicleRecord[]; total: number };
    expect(body.vehicles).toHaveLength(20);
    expect(body.total).toBe(200);
  });

  it('returns 400 for an invalid fuel_type', async () => {
    const db = makeMockDb();
    const result = await vehiclesHandler({ fuel_type: 'hydrogen' }, db);
    expect(result.status).toBe(400);
    expect(db.calls).toHaveLength(0);
  });

  it('returns 400 for an out-of-range year', async () => {
    const db = makeMockDb();
    const result = await vehiclesHandler({ year: '1850' }, db);
    expect(result.status).toBe(400);
    expect(db.calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 4. vehiclesHandler — pagination correctness
// ---------------------------------------------------------------------------

describe('vehiclesHandler — pagination', () => {
  it('uses default limit of 20 and offset 0 when not specified', async () => {
    const db = makeMockDb([], 0);
    await vehiclesHandler({}, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    const params = selectCall?.params ?? [];
    const lastTwo = params.slice(-2);
    expect(lastTwo).toEqual([20, 0]);
  });

  it('passes custom limit to the query', async () => {
    const db = makeMockDb([], 0);
    await vehiclesHandler({ limit: '5' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    const params = selectCall?.params ?? [];
    expect(params.slice(-2)).toEqual([5, 0]);
  });

  it('passes custom offset to the query', async () => {
    const db = makeMockDb([], 0);
    await vehiclesHandler({ offset: '40' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    const params = selectCall?.params ?? [];
    expect(params.slice(-2)).toEqual([20, 40]);
  });

  it('passes both limit and offset to the query', async () => {
    const db = makeMockDb([], 0);
    await vehiclesHandler({ limit: '10', offset: '30' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    const params = selectCall?.params ?? [];
    expect(params.slice(-2)).toEqual([10, 30]);
  });

  it('returns the correct total from the COUNT query', async () => {
    const db = makeMockDb(
      [makeVehicle(), makeVehicle({ id: 'id-2' })],
      347,
    );
    const result = await vehiclesHandler({ limit: '2', offset: '0' }, db);
    const body = result.body as { total: number };
    expect(body.total).toBe(347);
  });

  it('returns empty vehicles array when offset exceeds total', async () => {
    const db = makeMockDb([], 10);
    const result = await vehiclesHandler({ offset: '999' }, db);
    const body = result.body as { vehicles: VehicleRecord[]; total: number };
    expect(body.vehicles).toHaveLength(0);
    expect(body.total).toBe(10);
  });

  it('returns 400 when limit exceeds maximum of 100', async () => {
    const db = makeMockDb();
    const result = await vehiclesHandler({ limit: '200' }, db);
    expect(result.status).toBe(400);
  });

  it('returns 400 when limit is zero', async () => {
    const db = makeMockDb();
    const result = await vehiclesHandler({ limit: '0' }, db);
    expect(result.status).toBe(400);
  });

  it('issues both SELECT and COUNT queries in every successful request', async () => {
    const db = makeMockDb([makeVehicle()], 1);
    await vehiclesHandler({}, db);
    expect(db.calls).toHaveLength(2);
    expect(db.calls.some((c) => /COUNT/i.test(c.sql))).toBe(true);
    expect(db.calls.some((c) => !/COUNT/i.test(c.sql))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 5. vehiclesHandler — response headers
// ---------------------------------------------------------------------------

describe('vehiclesHandler — response headers', () => {
  it('sets Cache-Control: public, max-age=86400 on success', async () => {
    const db = makeMockDb([], 0);
    const result = await vehiclesHandler({}, db);
    expect(result.headers['Cache-Control']).toBe('public, max-age=86400');
  });

  it('sets Content-Type: application/json on success', async () => {
    const db = makeMockDb([], 0);
    const result = await vehiclesHandler({}, db);
    expect(result.headers['Content-Type']).toBe('application/json');
  });

  it('sets Content-Type: application/json on 400 error', async () => {
    const db = makeMockDb();
    const result = await vehiclesHandler({ fuel_type: 'unknown' }, db);
    expect(result.status).toBe(400);
    expect(result.headers['Content-Type']).toBe('application/json');
  });
});

// ---------------------------------------------------------------------------
// 6. SQL injection prevention
// ---------------------------------------------------------------------------

describe('SQL injection prevention via q param', () => {
  it('wraps the q value in LIKE wildcards and binds it as a param', async () => {
    const db = makeMockDb([], 0);
    await vehiclesHandler({ q: 'Tesla' }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    // The search term must be bound as a LIKE parameter, not interpolated
    expect(selectCall?.params).toContain('%tesla%');
    expect(selectCall?.sql).not.toContain('Tesla');
  });

  it('safely binds a classic SQL injection attempt as a literal parameter', async () => {
    const injection = "'; DROP TABLE vehicles; --";
    const db = makeMockDb([], 0);
    const result = await vehiclesHandler({ q: injection }, db);
    // Handler should succeed (injection string is ≤200 chars)
    expect(result.status).toBe(200);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    // The injection string must NOT appear in the SQL — only in the params
    expect(selectCall?.sql).not.toContain(injection);
    expect(selectCall?.sql).not.toContain('DROP TABLE');
    // It must be passed as a bound value (lowercased and wrapped in %)
    expect(selectCall?.params).toContain(`%${injection.toLowerCase()}%`);
  });

  it('safely binds a UNION-based injection attempt as a literal parameter', async () => {
    const injection = "' UNION SELECT * FROM pricing_defaults; --";
    const db = makeMockDb([], 0);
    await vehiclesHandler({ q: injection }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.sql).not.toContain('UNION');
    expect(selectCall?.params).toContain(`%${injection.toLowerCase()}%`);
  });

  it('safely binds a tautology injection attempt via make param', async () => {
    const injection = "' OR '1'='1";
    const db = makeMockDb([], 0);
    await vehiclesHandler({ make: injection }, db);
    const selectCall = db.calls.find((c) => !/COUNT/i.test(c.sql));
    expect(selectCall?.sql).not.toContain(injection);
    expect(selectCall?.params).toContain(injection);
  });

  it('rejects q param exceeding 200 characters (returns 400)', async () => {
    const longInjection = "' OR '1'='1' ".repeat(20); // > 200 chars
    const db = makeMockDb();
    const result = await vehiclesHandler({ q: longInjection }, db);
    expect(result.status).toBe(400);
    expect(db.calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 7. p95 latency ≤ 500 ms
// ---------------------------------------------------------------------------

describe('vehiclesHandler — p95 latency ≤ 500 ms', () => {
  /**
   * Simulates a DB call with a realistic but small fixed latency to represent
   * "local DB with representative row count". The handler overhead (parsing,
   * query building, response construction) must stay well below the 500 ms
   * budget even when the DB itself takes a representative slice of that budget.
   */
  const ITERATIONS = 50;
  const P95_BUDGET_MS = 500;

  // Simulate a DB that takes ~5ms to respond (realistic for local Postgres)
  function makeTimedDb(vehicles: VehicleRecord[], total: number): DbClient {
    return {
      async query(sql, _params) {
        await new Promise((r) => setTimeout(r, 5));
        if (/COUNT/i.test(sql)) {
          return { rows: [{ total }] as Record<string, unknown>[] };
        }
        return { rows: vehicles as Record<string, unknown>[] };
      },
    };
  }

  beforeEach(() => {
    vi.useRealTimers();
  });

  it(`completes ${ITERATIONS} requests with p95 latency under ${P95_BUDGET_MS} ms`, async () => {
    const vehicles = Array.from({ length: 20 }, (_, i) =>
      makeVehicle({ id: String(i), make: 'Nissan', model: 'Leaf', fuel_type: 'ev' }),
    );
    const db = makeTimedDb(vehicles, 200);

    const latencies: number[] = [];

    for (let i = 0; i < ITERATIONS; i++) {
      const t0 = performance.now();
      await vehiclesHandler(
        { make: 'Nissan', fuel_type: 'ev', limit: '20', offset: String(i * 20) },
        db,
      );
      latencies.push(performance.now() - t0);
    }

    latencies.sort((a, b) => a - b);
    const p95Index = Math.ceil(ITERATIONS * 0.95) - 1;
    const p95 = latencies[p95Index];

    expect(p95).toBeLessThan(P95_BUDGET_MS);
  });

  it('completes a no-filter request (full table scan scenario) under p95 budget', async () => {
    const db = makeTimedDb([], 500);
    const latencies: number[] = [];

    for (let i = 0; i < ITERATIONS; i++) {
      const t0 = performance.now();
      await vehiclesHandler({}, db);
      latencies.push(performance.now() - t0);
    }

    latencies.sort((a, b) => a - b);
    const p95Index = Math.ceil(ITERATIONS * 0.95) - 1;
    const p95 = latencies[p95Index];

    expect(p95).toBeLessThan(P95_BUDGET_MS);
  });
});
