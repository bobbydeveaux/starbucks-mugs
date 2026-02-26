import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TrendChart } from './TrendChart';
import type { Alert } from '../types';

// ---------------------------------------------------------------------------
// Mock recharts — ResponsiveContainer requires a real browser layout engine
// (ResizeObserver + measured DOM nodes) which is unavailable in jsdom.
// We replace every recharts component with simple, testable stubs.
// ---------------------------------------------------------------------------

vi.mock('recharts', () => ({
  ResponsiveContainer: ({
    children,
  }: {
    children: React.ReactNode;
    width?: string | number;
    height?: string | number;
  }) => <div data-testid="responsive-container">{children}</div>,

  AreaChart: ({
    children,
    data,
  }: {
    children: React.ReactNode;
    data?: unknown[];
  }) => (
    <div data-testid="area-chart" data-point-count={data?.length ?? 0}>
      {children}
    </div>
  ),

  Area: ({ name, dataKey }: { name?: string; dataKey?: string }) => (
    <div data-testid={`area-${name ?? dataKey}`} />
  ),

  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HOUR_MS = 3_600_000;
const T0 = new Date('2026-02-26T12:00:00Z');
const from = new Date(T0.getTime() - HOUR_MS);
const to = T0;

const noopChange = vi.fn();

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: 'a1',
    host_id: 'h1',
    timestamp: new Date(T0.getTime() - 30 * 60_000).toISOString(),
    tripwire_type: 'FILE',
    rule_name: 'rule',
    event_detail: {},
    severity: 'INFO',
    received_at: T0.toISOString(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TrendChart', () => {
  beforeEach(() => {
    noopChange.mockClear();
  });

  // ── Accessibility ──────────────────────────────────────────────────────────

  it('renders a labelled <section> for screen readers', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(
      screen.getByRole('region', { name: /alert volume trend chart/i }),
    ).toBeInTheDocument();
  });

  it('renders the "Alert Volume" heading', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(
      screen.getByRole('heading', { name: /alert volume/i }),
    ).toBeInTheDocument();
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  it('shows a loading message when loading=true', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
        loading
      />,
    );
    expect(screen.getByText(/loading alerts/i)).toBeInTheDocument();
  });

  it('hides the chart while loading', () => {
    render(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
        loading
      />,
    );
    expect(screen.queryByTestId('area-chart')).not.toBeInTheDocument();
  });

  // ── Error state ────────────────────────────────────────────────────────────

  it('shows an error alert when error prop is set', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
        error="HTTP 503"
      />,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/HTTP 503/)).toBeInTheDocument();
  });

  // ── Empty state ────────────────────────────────────────────────────────────

  it('shows an empty-state message when alerts array is empty (no error)', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.getByText(/no alerts in this time window/i)).toBeInTheDocument();
  });

  it('does not render the recharts chart when alerts is empty', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.queryByTestId('area-chart')).not.toBeInTheDocument();
  });

  // ── Chart rendering ────────────────────────────────────────────────────────

  it('renders the recharts AreaChart when alerts are present', () => {
    render(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.getByTestId('area-chart')).toBeInTheDocument();
  });

  it('renders three Area series (INFO, WARN, CRITICAL)', () => {
    render(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.getByTestId('area-INFO')).toBeInTheDocument();
    expect(screen.getByTestId('area-WARN')).toBeInTheDocument();
    expect(screen.getByTestId('area-CRITICAL')).toBeInTheDocument();
  });

  it('renders chart axes, grid, tooltip, and legend', () => {
    render(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.getByTestId('x-axis')).toBeInTheDocument();
    expect(screen.getByTestId('y-axis')).toBeInTheDocument();
    expect(screen.getByTestId('cartesian-grid')).toBeInTheDocument();
    expect(screen.getByTestId('tooltip')).toBeInTheDocument();
    expect(screen.getByTestId('legend')).toBeInTheDocument();
  });

  it('passes bucketed data points to AreaChart', () => {
    render(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    const chart = screen.getByTestId('area-chart');
    const count = Number(chart.getAttribute('data-point-count'));
    expect(count).toBeGreaterThanOrEqual(1);
  });

  // ── Re-renders when alerts change ─────────────────────────────────────────

  it('updates rendered data when a new alert is added (simulates WS push)', () => {
    const { rerender } = render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );

    // No chart while empty
    expect(screen.queryByTestId('area-chart')).not.toBeInTheDocument();

    // WS pushes a new alert → parent updates alerts prop
    rerender(
      <TrendChart
        alerts={[makeAlert()]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );

    expect(screen.getByTestId('area-chart')).toBeInTheDocument();
  });

  // ── Time-range selector ────────────────────────────────────────────────────

  it('renders all five time-range buttons', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    for (const label of ['1h', '6h', '24h', '7d', '30d']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('marks the active time-range button as aria-pressed=true', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="24h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(screen.getByRole('button', { name: '24h' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: '1h' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('calls onTimeRangeChange with the clicked preset', () => {
    const onTimeRangeChange = vi.fn();
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={onTimeRangeChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '7d' }));
    expect(onTimeRangeChange).toHaveBeenCalledOnce();
    expect(onTimeRangeChange).toHaveBeenCalledWith('7d');
  });

  it('time-range button group has an accessible label', () => {
    render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
      />,
    );
    expect(
      screen.getByRole('group', { name: /select time range/i }),
    ).toBeInTheDocument();
  });

  // ── className passthrough ──────────────────────────────────────────────────

  it('applies a custom className to the root element', () => {
    const { container } = render(
      <TrendChart
        alerts={[]}
        from={from}
        to={to}
        timeRange="1h"
        onTimeRangeChange={noopChange}
        className="custom-class"
      />,
    );
    expect(container.firstChild).toHaveClass('custom-class');
  });
});
