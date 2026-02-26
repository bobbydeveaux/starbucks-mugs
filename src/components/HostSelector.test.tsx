import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { HostSelector } from './HostSelector';
import type { Host } from '../types';

const hosts: Host[] = [
  {
    host_id: 'host-1',
    hostname: 'server-alpha',
    ip_address: '10.0.0.1',
    platform: 'linux',
    agent_version: '1.0.0',
    status: 'ONLINE',
  },
  {
    host_id: 'host-2',
    hostname: 'server-beta',
    ip_address: '10.0.0.2',
    platform: 'linux',
    agent_version: '1.0.0',
    status: 'OFFLINE',
  },
  {
    host_id: 'host-3',
    hostname: 'server-gamma',
    ip_address: '10.0.0.3',
    platform: 'darwin',
    agent_version: '1.1.0',
    status: 'DEGRADED',
  },
];

describe('HostSelector', () => {
  it('renders all host names', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByText('server-alpha')).toBeInTheDocument();
    expect(screen.getByText('server-beta')).toBeInTheDocument();
    expect(screen.getByText('server-gamma')).toBeInTheDocument();
  });

  it('shows the host count in the toolbar', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByText('3 hosts')).toBeInTheDocument();
  });

  it('shows singular "host" when there is exactly one host', () => {
    render(<HostSelector hosts={[hosts[0]]} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByText('1 host')).toBeInTheDocument();
  });

  it('renders a checkbox for each host', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes).toHaveLength(3);
  });

  it('checks the checkbox for pre-selected hosts', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={['host-2']} onChange={vi.fn()} />);
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[0]).not.toBeChecked();
    expect(checkboxes[1]).toBeChecked();
    expect(checkboxes[2]).not.toBeChecked();
  });

  it('calls onChange with the toggled host ID when a checkbox is clicked', () => {
    const onChange = vi.fn();
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={onChange} />);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(onChange).toHaveBeenCalledWith(['host-1']);
  });

  it('calls onChange removing the host ID when a checked checkbox is clicked', () => {
    const onChange = vi.fn();
    render(<HostSelector hosts={hosts} selectedHostIds={['host-1', 'host-2']} onChange={onChange} />);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(onChange).toHaveBeenCalledWith(['host-2']);
  });

  it('selects all hosts when the "Select all" button is clicked', () => {
    const onChange = vi.fn();
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /select all/i }));
    expect(onChange).toHaveBeenCalledWith(['host-1', 'host-2', 'host-3']);
  });

  it('clears all hosts when the "Clear" button is clicked', () => {
    const onChange = vi.fn();
    render(<HostSelector hosts={hosts} selectedHostIds={['host-1', 'host-2']} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('disables the "Select all" button when all hosts are already selected', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={['host-1', 'host-2', 'host-3']} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /select all/i })).toBeDisabled();
  });

  it('disables the "Clear" button when no host is selected', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /clear/i })).toBeDisabled();
  });

  it('shows "No hosts registered" when the host list is empty', () => {
    render(<HostSelector hosts={[]} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByText('No hosts registered')).toBeInTheDocument();
  });

  it('shows "No hosts selected — showing all" summary when selection is empty', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByText('No hosts selected — showing all')).toBeInTheDocument();
  });

  it('shows selection count in summary', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={['host-1', 'host-3']} onChange={vi.fn()} />);
    expect(screen.getByText('2 of 3 selected')).toBeInTheDocument();
  });

  it('renders status badges for each host', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByRole('status', { name: /online/i })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /offline/i })).toBeInTheDocument();
    expect(screen.getByRole('status', { name: /degraded/i })).toBeInTheDocument();
  });

  it('has accessible listbox role', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    expect(screen.getByRole('listbox', { name: /available hosts/i })).toBeInTheDocument();
  });

  it('marks listbox as multiselectable', () => {
    render(<HostSelector hosts={hosts} selectedHostIds={[]} onChange={vi.fn()} />);
    const listbox = screen.getByRole('listbox');
    expect(listbox).toHaveAttribute('aria-multiselectable', 'true');
  });
});
