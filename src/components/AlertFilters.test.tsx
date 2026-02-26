import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AlertFilters } from './AlertFilters';
import { FilterProvider } from '../contexts/FilterContext';
import { DEFAULT_ALERT_FILTERS } from '../types/alert';
import type { Host } from '../types/alert';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockHosts: Host[] = [
  {
    host_id: 'host-001',
    hostname: 'prod-server-01',
    ip_address: '10.0.0.1',
    platform: 'linux',
    agent_version: '1.2.0',
    last_seen: '2026-02-01T12:00:00Z',
    status: 'ONLINE',
  },
  {
    host_id: 'host-002',
    hostname: 'prod-server-02',
    ip_address: '10.0.0.2',
    platform: 'linux',
    agent_version: '1.2.0',
    last_seen: '2026-02-01T11:00:00Z',
    status: 'DEGRADED',
  },
];

function renderWithProvider(
  ui: React.ReactElement,
  initial = DEFAULT_ALERT_FILTERS,
) {
  return render(<FilterProvider initialFilters={initial}>{ui}</FilterProvider>);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AlertFilters', () => {
  it('renders the filter toolbar with accessible group role', () => {
    renderWithProvider(<AlertFilters />);
    expect(screen.getByRole('group', { name: /alert filters/i })).toBeInTheDocument();
  });

  it('renders severity, type, and host select elements', () => {
    renderWithProvider(<AlertFilters />);
    expect(screen.getByLabelText(/filter by severity/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/filter by type/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/filter by host/i)).toBeInTheDocument();
  });

  it('severity select defaults to "All severities"', () => {
    renderWithProvider(<AlertFilters />);
    const select = screen.getByLabelText(/filter by severity/i) as HTMLSelectElement;
    expect(select.value).toBe('');
  });

  it('severity select shows correct options', () => {
    renderWithProvider(<AlertFilters />);
    expect(screen.getByRole('option', { name: 'All severities' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Critical' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Warning' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Info' })).toBeInTheDocument();
  });

  it('tripwire type select shows correct options', () => {
    renderWithProvider(<AlertFilters />);
    expect(screen.getByRole('option', { name: 'All types' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'File' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Network' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Process' })).toBeInTheDocument();
  });

  it('host select shows all hosts', () => {
    renderWithProvider(<AlertFilters hosts={mockHosts} />);
    expect(screen.getByRole('option', { name: 'prod-server-01' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'prod-server-02' })).toBeInTheDocument();
  });

  it('host select is disabled while hosts are loading', () => {
    renderWithProvider(<AlertFilters hostsLoading />);
    const select = screen.getByLabelText(/filter by host/i);
    expect(select).toBeDisabled();
  });

  it('reset button is hidden when no filters are active', () => {
    renderWithProvider(<AlertFilters />);
    expect(screen.queryByRole('button', { name: /reset/i })).not.toBeInTheDocument();
  });

  it('reset button appears when severity filter is active', () => {
    renderWithProvider(
      <AlertFilters />,
      { ...DEFAULT_ALERT_FILTERS, severity: 'CRITICAL' },
    );
    expect(screen.getByRole('button', { name: /reset/i })).toBeInTheDocument();
  });

  it('changing severity select updates filter context', () => {
    renderWithProvider(<AlertFilters />);
    fireEvent.change(screen.getByLabelText(/filter by severity/i), {
      target: { value: 'WARN' },
    });
    const select = screen.getByLabelText(/filter by severity/i) as HTMLSelectElement;
    expect(select.value).toBe('WARN');
  });

  it('changing type select updates filter context', () => {
    renderWithProvider(<AlertFilters />);
    fireEvent.change(screen.getByLabelText(/filter by type/i), {
      target: { value: 'NETWORK' },
    });
    const select = screen.getByLabelText(/filter by type/i) as HTMLSelectElement;
    expect(select.value).toBe('NETWORK');
  });

  it('changing host select updates filter context', () => {
    renderWithProvider(<AlertFilters hosts={mockHosts} />);
    fireEvent.change(screen.getByLabelText(/filter by host/i), {
      target: { value: 'host-001' },
    });
    const select = screen.getByLabelText(/filter by host/i) as HTMLSelectElement;
    expect(select.value).toBe('host-001');
  });

  it('clicking reset clears all active filters', () => {
    renderWithProvider(
      <AlertFilters />,
      { ...DEFAULT_ALERT_FILTERS, severity: 'CRITICAL', tripwire_type: 'FILE' },
    );
    fireEvent.click(screen.getByRole('button', { name: /reset/i }));
    const severitySelect = screen.getByLabelText(/filter by severity/i) as HTMLSelectElement;
    expect(severitySelect.value).toBe('');
  });

  it('severity select reflects pre-set filter value', () => {
    renderWithProvider(
      <AlertFilters />,
      { ...DEFAULT_ALERT_FILTERS, severity: 'INFO' },
    );
    const select = screen.getByLabelText(/filter by severity/i) as HTMLSelectElement;
    expect(select.value).toBe('INFO');
  });

  it('selecting "All severities" clears the severity filter', () => {
    renderWithProvider(
      <AlertFilters />,
      { ...DEFAULT_ALERT_FILTERS, severity: 'CRITICAL' },
    );
    fireEvent.change(screen.getByLabelText(/filter by severity/i), {
      target: { value: '' },
    });
    const select = screen.getByLabelText(/filter by severity/i) as HTMLSelectElement;
    expect(select.value).toBe('');
  });
});
