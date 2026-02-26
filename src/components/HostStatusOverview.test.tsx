import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HostStatusOverview } from './HostStatusOverview';
import type { Host } from '../types';

const hosts: Host[] = [
  {
    host_id: 'host-1',
    hostname: 'server-alpha',
    ip_address: '10.0.0.1',
    platform: 'linux',
    agent_version: '1.2.3',
    last_seen: new Date().toISOString(),
    status: 'ONLINE',
  },
  {
    host_id: 'host-2',
    hostname: 'server-beta',
    ip_address: '10.0.0.2',
    platform: 'darwin',
    agent_version: '1.1.0',
    last_seen: new Date(Date.now() - 10_000).toISOString(),
    status: 'DEGRADED',
  },
  {
    host_id: 'host-3',
    hostname: 'server-gamma',
    status: 'OFFLINE',
  },
];

describe('HostStatusOverview', () => {
  it('renders the section with accessible label', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByRole('region', { name: /host status overview/i })).toBeInTheDocument();
  });

  it('shows summary count cards for Online, Degraded, Offline', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByRole('img', { name: /1 online hosts/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /1 degraded hosts/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /1 offline hosts/i })).toBeInTheDocument();
  });

  it('renders a row for each host', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByText('server-alpha')).toBeInTheDocument();
    expect(screen.getByText('server-beta')).toBeInTheDocument();
    expect(screen.getByText('server-gamma')).toBeInTheDocument();
  });

  it('renders IP address for hosts that have one', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.2')).toBeInTheDocument();
  });

  it('renders em-dash for missing IP address', () => {
    render(<HostStatusOverview hosts={hosts} />);
    // server-gamma has no ip_address — expect at least one em-dash cell
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
  });

  it('renders platform and agent version for populated hosts', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByText('linux')).toBeInTheDocument();
    expect(screen.getByText('darwin')).toBeInTheDocument();
    expect(screen.getByText('1.2.3')).toBeInTheDocument();
    expect(screen.getByText('1.1.0')).toBeInTheDocument();
  });

  it('shows only selected hosts when selectedHostIds is non-empty', () => {
    render(<HostStatusOverview hosts={hosts} selectedHostIds={['host-1']} />);
    expect(screen.getByText('server-alpha')).toBeInTheDocument();
    expect(screen.queryByText('server-beta')).not.toBeInTheDocument();
    expect(screen.queryByText('server-gamma')).not.toBeInTheDocument();
  });

  it('shows all hosts when selectedHostIds is empty', () => {
    render(<HostStatusOverview hosts={hosts} selectedHostIds={[]} />);
    expect(screen.getByText('server-alpha')).toBeInTheDocument();
    expect(screen.getByText('server-beta')).toBeInTheDocument();
    expect(screen.getByText('server-gamma')).toBeInTheDocument();
  });

  it('shows "no hosts match" message when selection matches no host', () => {
    render(<HostStatusOverview hosts={hosts} selectedHostIds={['nonexistent']} />);
    expect(screen.getByText(/no hosts match/i)).toBeInTheDocument();
  });

  it('shows "no hosts registered" when the host list is empty', () => {
    render(<HostStatusOverview hosts={[]} />);
    expect(screen.getByText(/no hosts registered/i)).toBeInTheDocument();
  });

  it('summary counts always reflect the full host list, not the filtered view', () => {
    render(<HostStatusOverview hosts={hosts} selectedHostIds={['host-1']} />);
    // All 3 hosts in summary even though only 1 is shown in the table
    expect(screen.getByRole('img', { name: /1 online hosts/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /1 degraded hosts/i })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /1 offline hosts/i })).toBeInTheDocument();
  });

  it('renders status badges in the host table', () => {
    render(<HostStatusOverview hosts={hosts} />);
    // 3 status badges in the table rows (one per host)
    const statusBadges = screen.getAllByRole('status');
    expect(statusBadges.length).toBeGreaterThanOrEqual(3);
  });

  it('renders the host table with accessible label', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByRole('table', { name: /host list/i })).toBeInTheDocument();
  });

  it('renders "Never" for hosts with no last_seen timestamp', () => {
    render(<HostStatusOverview hosts={hosts} />);
    expect(screen.getByText('Never')).toBeInTheDocument();
  });
});
