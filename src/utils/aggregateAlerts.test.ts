import { describe, it, expect } from 'vitest';
import {
  aggregateAlertsByTime,
  bucketSizeMs,
  formatBucketLabel,
  timeRangeToDates,
} from './aggregateAlerts';
import type { Alert } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: 'test-id',
    host_id: 'host-1',
    timestamp: new Date(0).toISOString(),
    tripwire_type: 'FILE',
    rule_name: 'test-rule',
    event_detail: {},
    severity: 'INFO',
    received_at: new Date(0).toISOString(),
    ...overrides,
  };
}

// A fixed "now" so tests are deterministic
const T0 = new Date('2026-02-26T12:00:00Z'); // noon UTC

// ---------------------------------------------------------------------------
// bucketSizeMs
// ---------------------------------------------------------------------------

describe('bucketSizeMs', () => {
  it('returns HOUR_MS for a 1-hour window', () => {
    expect(bucketSizeMs(HOUR_MS)).toBe(HOUR_MS);
  });

  it('returns HOUR_MS for a 24-hour window (inclusive boundary)', () => {
    expect(bucketSizeMs(24 * HOUR_MS)).toBe(HOUR_MS);
  });

  it('returns DAY_MS for a window just over 24 hours', () => {
    expect(bucketSizeMs(24 * HOUR_MS + 1)).toBe(DAY_MS);
  });

  it('returns DAY_MS for a 7-day window', () => {
    expect(bucketSizeMs(7 * DAY_MS)).toBe(DAY_MS);
  });
});

// ---------------------------------------------------------------------------
// formatBucketLabel
// ---------------------------------------------------------------------------

describe('formatBucketLabel', () => {
  it('returns a time string for hourly buckets', () => {
    const d = new Date('2026-02-26T14:00:00Z');
    const label = formatBucketLabel(d, HOUR_MS);
    // Should contain digits and a colon (HH:MM format)
    expect(label).toMatch(/\d{1,2}:\d{2}/);
  });

  it('returns a date string for daily buckets', () => {
    const d = new Date('2026-02-26T00:00:00Z');
    const label = formatBucketLabel(d, DAY_MS);
    // Should contain a month abbreviation or numeric date
    expect(label.length).toBeGreaterThan(3);
  });
});

// ---------------------------------------------------------------------------
// aggregateAlertsByTime
// ---------------------------------------------------------------------------

describe('aggregateAlertsByTime', () => {
  it('returns an empty bucket array (all zeros) when alerts list is empty', () => {
    const from = new Date(T0.getTime() - HOUR_MS);
    const to = T0;
    const buckets = aggregateAlertsByTime([], from, to);

    expect(buckets.length).toBeGreaterThanOrEqual(1);
    buckets.forEach((b) => {
      expect(b.INFO).toBe(0);
      expect(b.WARN).toBe(0);
      expect(b.CRITICAL).toBe(0);
    });
  });

  it('counts a single INFO alert in the correct bucket', () => {
    const from = new Date(T0.getTime() - HOUR_MS);
    const to = T0;

    const alert = makeAlert({
      timestamp: new Date(T0.getTime() - 30 * 60_000).toISOString(), // 30 min ago
      severity: 'INFO',
    });

    const buckets = aggregateAlertsByTime([alert], from, to);
    const total = buckets.reduce((sum, b) => sum + b.INFO, 0);
    expect(total).toBe(1);
  });

  it('counts per-severity independently', () => {
    const from = new Date(T0.getTime() - HOUR_MS);
    const to = T0;

    const midPoint = new Date(T0.getTime() - 30 * 60_000).toISOString();
    const alerts = [
      makeAlert({ timestamp: midPoint, severity: 'INFO' }),
      makeAlert({ timestamp: midPoint, severity: 'INFO' }),
      makeAlert({ timestamp: midPoint, severity: 'WARN' }),
      makeAlert({ timestamp: midPoint, severity: 'CRITICAL' }),
    ];

    const buckets = aggregateAlertsByTime(alerts, from, to);
    const totalInfo = buckets.reduce((s, b) => s + b.INFO, 0);
    const totalWarn = buckets.reduce((s, b) => s + b.WARN, 0);
    const totalCrit = buckets.reduce((s, b) => s + b.CRITICAL, 0);

    expect(totalInfo).toBe(2);
    expect(totalWarn).toBe(1);
    expect(totalCrit).toBe(1);
  });

  it('ignores alerts whose timestamp falls outside [from, to]', () => {
    const from = new Date(T0.getTime() - HOUR_MS);
    const to = T0;

    const outside = makeAlert({
      timestamp: new Date(T0.getTime() + HOUR_MS).toISOString(), // 1h in the future
      severity: 'CRITICAL',
    });

    const buckets = aggregateAlertsByTime([outside], from, to);
    const total = buckets.reduce((s, b) => s + b.CRITICAL, 0);
    expect(total).toBe(0);
  });

  it('produces buckets sorted ascending by timeMs', () => {
    const from = new Date(T0.getTime() - 3 * HOUR_MS);
    const to = T0;
    const buckets = aggregateAlertsByTime([], from, to);

    for (let i = 1; i < buckets.length; i++) {
      expect(buckets[i].timeMs).toBeGreaterThan(buckets[i - 1].timeMs);
    }
  });

  it('uses hourly buckets for a 6-hour window', () => {
    const from = new Date(T0.getTime() - 6 * HOUR_MS);
    const to = T0;
    const buckets = aggregateAlertsByTime([], from, to);
    // 6 hours → 6 or 7 buckets (boundary alignment may add one)
    expect(buckets.length).toBeGreaterThanOrEqual(6);
    expect(buckets.length).toBeLessThanOrEqual(7);
  });

  it('uses daily buckets for a 7-day window', () => {
    const from = new Date(T0.getTime() - 7 * DAY_MS);
    const to = T0;
    const buckets = aggregateAlertsByTime([], from, to);
    // 7 days → 7 or 8 buckets
    expect(buckets.length).toBeGreaterThanOrEqual(7);
    expect(buckets.length).toBeLessThanOrEqual(8);
  });

  it('populates zero-count buckets between populated ones (continuous X axis)', () => {
    const from = new Date(T0.getTime() - 3 * HOUR_MS);
    const to = T0;

    // Only alert at the very start of the window
    const alert = makeAlert({
      timestamp: new Date(from.getTime() + 5 * 60_000).toISOString(),
      severity: 'WARN',
    });

    const buckets = aggregateAlertsByTime([alert], from, to);

    // Every bucket must have a time label
    buckets.forEach((b) => expect(b.time).toBeTruthy());

    // Total WARN == 1; zero-count buckets exist
    const totalWarn = buckets.reduce((s, b) => s + b.WARN, 0);
    expect(totalWarn).toBe(1);

    const zeroBuckets = buckets.filter((b) => b.INFO === 0 && b.WARN === 0 && b.CRITICAL === 0);
    expect(zeroBuckets.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// timeRangeToDates
// ---------------------------------------------------------------------------

describe('timeRangeToDates', () => {
  it('returns a range ending at `now`', () => {
    const { to } = timeRangeToDates('1h', T0);
    expect(to).toEqual(T0);
  });

  it('1h preset spans exactly 1 hour', () => {
    const { from, to } = timeRangeToDates('1h', T0);
    expect(to.getTime() - from.getTime()).toBe(HOUR_MS);
  });

  it('6h preset spans exactly 6 hours', () => {
    const { from, to } = timeRangeToDates('6h', T0);
    expect(to.getTime() - from.getTime()).toBe(6 * HOUR_MS);
  });

  it('24h preset spans exactly 24 hours', () => {
    const { from, to } = timeRangeToDates('24h', T0);
    expect(to.getTime() - from.getTime()).toBe(24 * HOUR_MS);
  });

  it('7d preset spans exactly 7 days', () => {
    const { from, to } = timeRangeToDates('7d', T0);
    expect(to.getTime() - from.getTime()).toBe(7 * DAY_MS);
  });

  it('30d preset spans exactly 30 days', () => {
    const { from, to } = timeRangeToDates('30d', T0);
    expect(to.getTime() - from.getTime()).toBe(30 * DAY_MS);
  });
});
