/**
 * Unit tests for GET /api/pricing serverless handler.
 *
 * The pg Pool is fully mocked so these tests run without a real database.
 * Tests cover:
 *  - Happy path: correct JSON shape and Cache-Control header
 *  - 404 when the pricing_defaults table is empty
 *  - 405 for non-GET methods
 *  - 500 when the DB query throws
 *  - Null-tolerant tariff/public_charging fields
 */

import { describe, it, expect, vi, beforeEach, type MockInstance } from 'vitest';
import type { IncomingMessage, ServerResponse } from 'node:http';

// ---------------------------------------------------------------------------
// Mock the pg module before importing the handler so getPool() returns our stub
// ---------------------------------------------------------------------------
const mockRelease = vi.fn();
const mockQuery = vi.fn();
const mockConnect = vi.fn().mockResolvedValue({
  query: mockQuery,
  release: mockRelease,
});

vi.mock('pg', () => {
  return {
    Pool: vi.fn().mockImplementation(() => ({
      connect: mockConnect,
    })),
  };
});

// Import AFTER mocking so the handler picks up the mock
import handler, { getPool } from './pricing';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal mock IncomingMessage. */
function makeReq(method = 'GET'): IncomingMessage {
  return { method } as unknown as IncomingMessage;
}

/** Build a spy-equipped mock ServerResponse and capture written data. */
function makeRes(): {
  res: ServerResponse;
  statusCode: () => number;
  body: () => string;
  header: (name: string) => string | undefined;
} {
  let writtenHead: number | undefined;
  let writtenBody = '';
  const headers: Record<string, string> = {};

  const res = {
    setHeader: (name: string, value: string) => {
      headers[name.toLowerCase()] = value;
    },
    writeHead: (code: number, _headers?: Record<string, string>) => {
      writtenHead = code;
      if (_headers) {
        for (const [k, v] of Object.entries(_headers)) {
          headers[k.toLowerCase()] = v;
        }
      }
    },
    end: (chunk: string) => {
      writtenBody = chunk;
    },
  } as unknown as ServerResponse;

  return {
    res,
    statusCode: () => writtenHead ?? 200,
    body: () => writtenBody,
    header: (name: string) => headers[name.toLowerCase()],
  };
}

/** A full seed row matching db/migrations/006_pricing_defaults.up.sql */
const SEED_ROW = {
  petrol_ppl: '145.20',
  diesel_ppl: '151.40',
  electricity_ppkwh: '24.50',
  economy7_ppkwh: '13.00',
  octopus_go_ppkwh: '7.50',
  ovo_drive_ppkwh: '9.00',
  public_slow_ppkwh: '30.00',
  public_rapid_ppkwh: '55.00',
  public_ultrarapid_ppkwh: '79.00',
  updated_at: '2026-03-10T12:00:00.000Z',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('GET /api/pricing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnect.mockResolvedValue({ query: mockQuery, release: mockRelease });
  });

  it('returns 200 with correct JSON shape and Cache-Control header', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [SEED_ROW] });

    const { res, statusCode, body, header } = makeRes();
    await handler(makeReq('GET'), res);

    expect(statusCode()).toBe(200);
    expect(header('cache-control')).toBe('public, max-age=3600, s-maxage=3600');

    const json = JSON.parse(body());
    expect(json).toEqual({
      petrol_ppl: 145.2,
      diesel_ppl: 151.4,
      electricity_ppkwh: 24.5,
      tariffs: {
        economy7: 13.0,
        octopus_go: 7.5,
        ovo_drive: 9.0,
      },
      public_charging: {
        slow: 30.0,
        rapid: 55.0,
        ultra_rapid: 79.0,
      },
      updated_at: '2026-03-10T12:00:00.000Z',
    });
  });

  it('releases the DB client after a successful query', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [SEED_ROW] });

    const { res } = makeRes();
    await handler(makeReq('GET'), res);

    expect(mockRelease).toHaveBeenCalledOnce();
  });

  it('returns 404 when pricing_defaults table has no rows', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [] });

    const { res, statusCode, body } = makeRes();
    await handler(makeReq('GET'), res);

    expect(statusCode()).toBe(404);
    expect(JSON.parse(body())).toEqual({ error: 'No pricing data found' });
  });

  it('returns 405 for non-GET methods', async () => {
    for (const method of ['POST', 'PUT', 'DELETE', 'PATCH']) {
      const { res, statusCode, body } = makeRes();
      await handler(makeReq(method), res);

      expect(statusCode(), `expected 405 for ${method}`).toBe(405);
      expect(JSON.parse(body())).toEqual({ error: 'Method Not Allowed' });
    }
    // DB should never be touched for non-GET requests
    expect(mockConnect).not.toHaveBeenCalled();
  });

  it('returns 500 and releases client when DB query throws', async () => {
    mockQuery.mockRejectedValueOnce(new Error('DB connection refused'));

    const { res, statusCode, body } = makeRes();
    await handler(makeReq('GET'), res);

    expect(statusCode()).toBe(500);
    expect(JSON.parse(body())).toEqual({ error: 'Internal Server Error' });
    expect(mockRelease).toHaveBeenCalledOnce();
  });

  it('returns 500 and releases client when pool.connect throws', async () => {
    mockConnect.mockRejectedValueOnce(new Error('Pool exhausted'));

    const { res, statusCode, body } = makeRes();
    await handler(makeReq('GET'), res);

    expect(statusCode()).toBe(500);
    expect(JSON.parse(body())).toEqual({ error: 'Internal Server Error' });
  });

  it('coerces null optional tariff fields to null in JSON output', async () => {
    const rowWithNulls = {
      ...SEED_ROW,
      economy7_ppkwh: null,
      octopus_go_ppkwh: null,
      ovo_drive_ppkwh: null,
      public_slow_ppkwh: null,
      public_rapid_ppkwh: null,
      public_ultrarapid_ppkwh: null,
    };
    mockQuery.mockResolvedValueOnce({ rows: [rowWithNulls] });

    const { res, statusCode, body } = makeRes();
    await handler(makeReq('GET'), res);

    expect(statusCode()).toBe(200);
    const json = JSON.parse(body());
    expect(json.tariffs).toEqual({ economy7: null, octopus_go: null, ovo_drive: null });
    expect(json.public_charging).toEqual({ slow: null, rapid: null, ultra_rapid: null });
  });

  it('queries the most recent row (ORDER BY id DESC LIMIT 1)', async () => {
    mockQuery.mockResolvedValueOnce({ rows: [SEED_ROW] });

    const { res } = makeRes();
    await handler(makeReq('GET'), res);

    const queryCall = mockQuery.mock.calls[0][0] as string;
    expect(queryCall).toMatch(/ORDER BY id DESC/i);
    expect(queryCall).toMatch(/LIMIT 1/i);
  });

  it('getPool() returns the same Pool instance on repeated calls', () => {
    const p1 = getPool();
    const p2 = getPool();
    expect(p1).toBe(p2);
  });
});
