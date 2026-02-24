import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EraFilter } from './EraFilter';

const DECADES = [1960, 1970, 1980, 1990];

describe('EraFilter', () => {
  it('renders an "All" button', () => {
    render(<EraFilter value={undefined} onChange={vi.fn()} decades={DECADES} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
  });

  it('renders a button for each decade', () => {
    render(<EraFilter value={undefined} onChange={vi.fn()} decades={DECADES} />);
    expect(screen.getByRole('button', { name: /1960s/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /1970s/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /1980s/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /1990s/i })).toBeInTheDocument();
  });

  it('marks the "All" button as pressed when value is undefined', () => {
    render(<EraFilter value={undefined} onChange={vi.fn()} decades={DECADES} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('marks the selected decade button as pressed', () => {
    render(<EraFilter value={1980} onChange={vi.fn()} decades={DECADES} />);
    expect(screen.getByRole('button', { name: /1980s/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('marks non-selected decade buttons as not pressed', () => {
    render(<EraFilter value={1980} onChange={vi.fn()} decades={DECADES} />);
    expect(screen.getByRole('button', { name: /1960s/i })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: /1970s/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls onChange with the decade when a decade button is clicked', () => {
    const handleChange = vi.fn();
    render(<EraFilter value={undefined} onChange={handleChange} decades={DECADES} />);
    fireEvent.click(screen.getByRole('button', { name: /1970s/i }));
    expect(handleChange).toHaveBeenCalledWith(1970);
  });

  it('calls onChange with undefined when "All" is clicked', () => {
    const handleChange = vi.fn();
    render(<EraFilter value={1980} onChange={handleChange} decades={DECADES} />);
    fireEvent.click(screen.getByRole('button', { name: /^all$/i }));
    expect(handleChange).toHaveBeenCalledWith(undefined);
  });

  it('toggles off the active decade when clicked again (calls onChange with undefined)', () => {
    const handleChange = vi.fn();
    render(<EraFilter value={1980} onChange={handleChange} decades={DECADES} />);
    fireEvent.click(screen.getByRole('button', { name: /1980s/i }));
    expect(handleChange).toHaveBeenCalledWith(undefined);
  });

  it('renders with default decades when none provided', () => {
    render(<EraFilter value={undefined} onChange={vi.fn()} />);
    // Should at least have 1950s as a default decade
    expect(screen.getByRole('button', { name: /1950s/i })).toBeInTheDocument();
  });
});
