/**
 * Utility for aggregating a flat list of Alerts into time-bucketed trend data
 * suitable for rendering in a recharts AreaChart.
 */

import type { Alert } from '../types';

/** A single time bucket with per-severity alert counts */
export interface TrendBucket {
  /** Human-readable label shown on the X axis (e.g. "14:00" or "Feb 25") */
  time: string;
  /** Epoch milliseconds of the bucket start — used for sorting */
  timeMs: number;
  INFO: number;
  WARN: number;
  CRITICAL: number;
}

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/**
 * Compute the appropriate bucket size in milliseconds based on the query window.
 *
 * - Window ≤ 24 h  → 1-hour buckets
 * - Window >  24 h → 1-day  buckets
 */
export function bucketSizeMs(durationMs: number): number {
  return durationMs <= 24 * HOUR_MS ? HOUR_MS : DAY_MS;
}

/**
 * Format a bucket start Date as a short label for the X axis.
 *
 * - Hourly buckets → "HH:MM" (locale time)
 * - Daily  buckets → "Mon DD" (locale date)
 */
export function formatBucketLabel(d: Date, bucketMs: number): string {
  if (bucketMs <= HOUR_MS) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

/**
 * Aggregate `alerts` into uniformly-spaced time buckets spanning [from, to].
 *
 * Buckets that fall within the window but contain zero alerts are still
 * included so the chart renders a continuous, gapless X axis.
 *
 * Alerts whose `timestamp` falls outside [from, to] are silently ignored.
 *
 * @param alerts - Raw alert objects (unsorted is fine)
 * @param from   - Inclusive window start
 * @param to     - Inclusive window end
 */
export function aggregateAlertsByTime(
  alerts: Alert[],
  from: Date,
  to: Date,
): TrendBucket[] {
  const durationMs = to.getTime() - from.getTime();
  const bMs = bucketSizeMs(durationMs);

  // Align bucket boundaries to even multiples so labels are round numbers
  const firstBucket = Math.floor(from.getTime() / bMs) * bMs;
  const lastBucket = Math.floor(to.getTime() / bMs) * bMs;

  // Pre-populate every bucket in the window (including zero-count ones)
  const buckets = new Map<number, TrendBucket>();
  for (let t = firstBucket; t <= lastBucket; t += bMs) {
    buckets.set(t, {
      time: formatBucketLabel(new Date(t), bMs),
      timeMs: t,
      INFO: 0,
      WARN: 0,
      CRITICAL: 0,
    });
  }

  // Bin each alert into its bucket
  for (const alert of alerts) {
    const alertMs = new Date(alert.timestamp).getTime();
    const bucketStart = Math.floor(alertMs / bMs) * bMs;
    const b = buckets.get(bucketStart);
    if (b) {
      b[alert.severity]++;
    }
  }

  return Array.from(buckets.values()).sort((a, b) => a.timeMs - b.timeMs);
}

/**
 * Compute the [from, to] Date range for a given TimeRange preset relative
 * to `now` (defaults to the current system time).
 */
export function timeRangeToDates(
  preset: '1h' | '6h' | '24h' | '7d' | '30d',
  now: Date = new Date(),
): { from: Date; to: Date } {
  const PRESET_MS: Record<string, number> = {
    '1h': HOUR_MS,
    '6h': 6 * HOUR_MS,
    '24h': 24 * HOUR_MS,
    '7d': 7 * DAY_MS,
    '30d': 30 * DAY_MS,
  };
  return {
    from: new Date(now.getTime() - PRESET_MS[preset]),
    to: now,
  };
}
