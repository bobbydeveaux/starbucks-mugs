import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AlertTable } from './AlertTable';
import { FilterProvider } from '../contexts/FilterContext';
import { DEFAULT_ALERT_FILTERS } from '../types/alert';
import type { Alert, AlertsResponse } from '../types/alert';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: 'alert-001',
    host_id: 'host-abc',
    timestamp: '2026-02-01T12:00:00Z',
    tripwire_type: 'FILE',
    rule_name: 'etc-passwd-watch',
    event_detail: { path: '/etc/passwd' },
    severity: 'CRITICAL',
    received_at: '2026-02-01T12:00:01Z',
    ...overrides,
  };
}

function makeResponse(alerts: Alert[], total?: number): AlertsResponse {
  return {
    alerts,
    total: total ?? alerts.length,
    limit: DEFAULT_ALERT_FILTERS.limit,
    offset: 0,
  };
}

function renderTable(
  props: Partial<Parameters<typeof AlertTable>[0]> = {},
  initialFilters = DEFAULT_ALERT_FILTERS,
) {
  return render(
    <FilterProvider initialFilters={initialFilters}>
      <AlertTable
        data={props.data}
        isLoading={props.isLoading ?? false}
        isFetching={props.isFetching ?? false}
        error={props.error ?? null}
        {...props}
      />
    </FilterProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AlertTable', () => {
  it('shows a loading indicator when isLoading is true', () => {
    renderTable({ isLoading: true });
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });

  it('shows an error message when error is set', () => {
    renderTable({ error: new Error('Server error') });
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/server error/i)).toBeInTheDocument();
  });

  it('shows empty state when alerts array is empty', () => {
    renderTable({ data: makeResponse([]) });
    expect(screen.getByText(/no alerts match/i)).toBeInTheDocument();
  });

  it('renders a table row for each alert', () => {
    const alerts = [
      makeAlert({ alert_id: 'a1', rule_name: 'rule-one' }),
      makeAlert({ alert_id: 'a2', rule_name: 'rule-two' }),
    ];
    renderTable({ data: makeResponse(alerts) });
    expect(screen.getByText('rule-one')).toBeInTheDocument();
    expect(screen.getByText('rule-two')).toBeInTheDocument();
  });

  it('displays severity badge for each alert', () => {
    renderTable({ data: makeResponse([makeAlert({ severity: 'WARN' })]) });
    expect(screen.getByText('Warning')).toBeInTheDocument();
  });

  it('displays tripwire type label', () => {
    renderTable({ data: makeResponse([makeAlert({ tripwire_type: 'NETWORK' })]) });
    expect(screen.getByText('Network')).toBeInTheDocument();
  });

  it('shows a refreshing indicator when isFetching is true and data exists', () => {
    renderTable({
      data: makeResponse([makeAlert()]),
      isFetching: true,
      isLoading: false,
    });
    expect(screen.getByRole('status', { name: /refreshing/i })).toBeInTheDocument();
  });

  it('does not show pagination when there is only one page', () => {
    renderTable({ data: makeResponse([makeAlert()]) });
    expect(screen.queryByRole('button', { name: /previous/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument();
  });

  it('shows pagination controls when there are multiple pages', () => {
    const alerts = [makeAlert()];
    renderTable(
      { data: { alerts, total: 200, limit: 50, offset: 0 } },
      { ...DEFAULT_ALERT_FILTERS, limit: 50, offset: 0 },
    );
    expect(screen.getByRole('button', { name: /previous/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument();
  });

  it('previous button is disabled on the first page', () => {
    renderTable(
      { data: { alerts: [makeAlert()], total: 200, limit: 50, offset: 0 } },
      { ...DEFAULT_ALERT_FILTERS, limit: 50, offset: 0 },
    );
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled();
  });

  it('next button is disabled on the last page', () => {
    // Page 2 of 2: offset=50, limit=50, total=100
    renderTable(
      { data: { alerts: [makeAlert()], total: 100, limit: 50, offset: 50 } },
      { ...DEFAULT_ALERT_FILTERS, limit: 50, offset: 50 },
    );
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('clicking next page updates offset via FilterContext', () => {
    renderTable(
      { data: { alerts: [makeAlert()], total: 100, limit: 50, offset: 0 } },
      { ...DEFAULT_ALERT_FILTERS, limit: 50, offset: 0 },
    );
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    // After clicking next, the page text should update
    expect(screen.getByText(/page 2 of 2/i)).toBeInTheDocument();
  });

  it('renders column headers', () => {
    renderTable({ data: makeResponse([makeAlert()]) });
    expect(screen.getByText('Time')).toBeInTheDocument();
    expect(screen.getByText('Severity')).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Rule')).toBeInTheDocument();
    expect(screen.getByText('Host')).toBeInTheDocument();
  });
});
