/**
 * GET /api/pricing
 *
 * Returns the current default fuel and electricity pricing row used to seed the
 * cost-comparison calculator.  Reads the most recent row from the
 * `pricing_defaults` table and reshapes it into the canonical JSON contract
 * defined in docs/concepts/petrol-vs-ev-cost-comparison-website/HLD.md.
 *
 * Cache strategy: responses are valid for 1 hour at the CDN edge and in
 * shared caches, matching the HLD caching recommendation.
 */

import type { IncomingMessage, ServerResponse } from 'node:http';
import { Pool } from 'pg';

/** Lazily-initialised connection pool (re-used across warm invocations). */
let pool: Pool | undefined;

export function getPool(): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: process.env.DATABASE_URL });
  }
  return pool;
}

/** Shape of a row returned from `pricing_defaults`. */
interface PricingRow {
  petrol_ppl: string;
  diesel_ppl: string;
  electricity_ppkwh: string;
  economy7_ppkwh: string | null;
  octopus_go_ppkwh: string | null;
  ovo_drive_ppkwh: string | null;
  public_slow_ppkwh: string | null;
  public_rapid_ppkwh: string | null;
  public_ultrarapid_ppkwh: string | null;
  updated_at: string;
}

/** Parse a nullable NUMERIC string from pg into a number or null. */
function parseNum(value: string | null): number | null {
  return value != null ? parseFloat(value) : null;
}

/** Vercel/Node serverless handler. */
export default async function handler(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    res.writeHead(405, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Method Not Allowed' }));
    return;
  }

  let client;
  try {
    client = await getPool().connect();
  } catch (err) {
    console.error('GET /api/pricing error:', err);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Internal Server Error' }));
    return;
  }

  try {
    const result = await client.query<PricingRow>(
      `SELECT petrol_ppl, diesel_ppl, electricity_ppkwh,
              economy7_ppkwh, octopus_go_ppkwh, ovo_drive_ppkwh,
              public_slow_ppkwh, public_rapid_ppkwh, public_ultrarapid_ppkwh,
              updated_at
         FROM pricing_defaults
         ORDER BY id DESC
         LIMIT 1`,
    );

    if (result.rows.length === 0) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'No pricing data found' }));
      return;
    }

    const row = result.rows[0];

    const body = {
      petrol_ppl: parseFloat(row.petrol_ppl),
      diesel_ppl: parseFloat(row.diesel_ppl),
      electricity_ppkwh: parseFloat(row.electricity_ppkwh),
      tariffs: {
        economy7: parseNum(row.economy7_ppkwh),
        octopus_go: parseNum(row.octopus_go_ppkwh),
        ovo_drive: parseNum(row.ovo_drive_ppkwh),
      },
      public_charging: {
        slow: parseNum(row.public_slow_ppkwh),
        rapid: parseNum(row.public_rapid_ppkwh),
        ultra_rapid: parseNum(row.public_ultrarapid_ppkwh),
      },
      updated_at: row.updated_at,
    };

    res.setHeader('Cache-Control', 'public, max-age=3600, s-maxage=3600');
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  } catch (err) {
    console.error('GET /api/pricing error:', err);
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Internal Server Error' }));
  } finally {
    client.release();
  }
}
