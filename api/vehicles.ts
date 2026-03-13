/**
 * GET /api/vehicles — Vehicle Search API
 *
 * Vercel serverless function that searches the vehicles catalog.
 *
 * Query parameters (all optional):
 *   make      - Manufacturer name (case-insensitive exact match)
 *   model     - Model name (case-insensitive exact match)
 *   year      - Model year (integer)
 *   fuel_type - One of: petrol | diesel | ev | hybrid | phev
 *   q         - Freetext search across make, model, variant
 *   limit     - Max results (default: 20, max: 100)
 *
 * Response 200:
 *   { vehicles: Vehicle[], total: number }
 *
 * Response 400:
 *   { error: string }
 *
 * Response 405:
 *   { error: "Method Not Allowed" }
 *
 * Response 500:
 *   { error: "Internal Server Error" }
 *
 * Cache-Control: public, max-age=86400, s-maxage=86400 (24-hour CDN cache)
 *
 * See HLD: docs/concepts/petrol-vs-ev-cost-comparison-website/HLD.md §4
 */

import type { VercelRequest, VercelResponse } from '@vercel/node';
import postgres from 'postgres';
import {
  parseSearchParams,
  buildVehicleQuery,
  shapeVehiclesResponse,
} from '../src/petrol-vs-ev/vehicleSearch';

// ---------------------------------------------------------------------------
// Database connection (lazy singleton — reused across warm invocations)
// ---------------------------------------------------------------------------

let _sql: ReturnType<typeof postgres> | null = null;

function getDb(): ReturnType<typeof postgres> {
  if (!_sql) {
    const url = process.env['DATABASE_URL'];
    if (!url) {
      throw new Error('DATABASE_URL environment variable is not set');
    }
    _sql = postgres(url, {
      // Vercel serverless: short idle timeout to release connections promptly
      idle_timeout: 20,
      max_lifetime: 60 * 30,
    });
  }
  return _sql;
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default async function handler(
  req: VercelRequest,
  res: VercelResponse,
): Promise<void> {
  // Only GET is supported
  if (req.method !== 'GET') {
    res.status(405).json({ error: 'Method Not Allowed' });
    return;
  }

  // Parse and validate query parameters
  const parseResult = parseSearchParams(
    req.query as Record<string, string | string[] | undefined>,
  );
  if (!parseResult.success) {
    res.status(400).json({ error: parseResult.error });
    return;
  }

  const { sql: querySql, countSql, values, countValues } = buildVehicleQuery(
    parseResult.data,
  );

  try {
    const sql = getDb();

    // Run the data query and count query in parallel for performance
    const [countRows, dataRows] = await Promise.all([
      sql.unsafe(countSql, countValues as string[]),
      sql.unsafe(querySql, values as string[]),
    ]);

    const total = (countRows[0] as { total: number }).total;
    const response = shapeVehiclesResponse(
      dataRows as Record<string, unknown>[],
      total,
    );

    // Cache vehicle catalog responses at the CDN edge for 24 hours (HLD §9)
    res.setHeader(
      'Cache-Control',
      'public, max-age=86400, s-maxage=86400, stale-while-revalidate=3600',
    );
    res.status(200).json(response);
  } catch (err) {
    console.error('[api/vehicles] Database error:', err);
    res.status(500).json({ error: 'Internal Server Error' });
  }
}
