import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CatalogFilters } from './CatalogFilters';

const AVAILABLE_DECADES = [1960, 1970, 1980, 1990, 2000];

describe('CatalogFilters', () => {
  const defaultProps = {
    era: null,
    availableDecades: AVAILABLE_DECADES,
    onEraChange: vi.fn(),
    search: '',
    onSearchChange: vi.fn(),
  };

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  it('renders the EraFilter and SearchBar sub-components', () => {
    render(<CatalogFilters {...defaultProps} />);
    expect(screen.getByRole('group', { name: /filter by era/i })).toBeInTheDocument();
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('does not render the "Clear all filters" button when no filters are active', () => {
    render(<CatalogFilters {...defaultProps} era={null} search="" />);
    expect(screen.queryByRole('button', { name: /clear all filters/i })).not.toBeInTheDocument();
  });

  it('renders the "Clear all filters" button when an era is selected', () => {
    render(<CatalogFilters {...defaultProps} era={1980} search="" />);
    expect(screen.getByRole('button', { name: /clear all filters/i })).toBeInTheDocument();
  });

  it('renders the "Clear all filters" button when a search is active', () => {
    render(<CatalogFilters {...defaultProps} era={null} search="Enzo" />);
    expect(screen.getByRole('button', { name: /clear all filters/i })).toBeInTheDocument();
  });

  it('renders the "Clear all filters" button when both filters are active', () => {
    render(<CatalogFilters {...defaultProps} era={1980} search="Testa" />);
    expect(screen.getByRole('button', { name: /clear all filters/i })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Interactions
  // -------------------------------------------------------------------------

  it('calls onEraChange when "Clear all filters" is clicked', () => {
    const onEraChange = vi.fn();
    const onSearchChange = vi.fn();
    render(
      <CatalogFilters
        {...defaultProps}
        era={1980}
        search=""
        onEraChange={onEraChange}
        onSearchChange={onSearchChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /clear all filters/i }));
    expect(onEraChange).toHaveBeenCalledWith(null);
  });

  it('calls onSearchChange with empty string when "Clear all filters" is clicked', () => {
    const onEraChange = vi.fn();
    const onSearchChange = vi.fn();
    render(
      <CatalogFilters
        {...defaultProps}
        era={null}
        search="Enzo"
        onEraChange={onEraChange}
        onSearchChange={onSearchChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /clear all filters/i }));
    expect(onSearchChange).toHaveBeenCalledWith('');
  });

  it('forwards era changes from EraFilter to onEraChange', () => {
    const onEraChange = vi.fn();
    render(<CatalogFilters {...defaultProps} onEraChange={onEraChange} />);
    fireEvent.click(screen.getByRole('button', { name: '1980s' }));
    expect(onEraChange).toHaveBeenCalledWith(1980);
  });

  it('forwards search changes from SearchBar to onSearchChange', () => {
    const onSearchChange = vi.fn();
    render(<CatalogFilters {...defaultProps} onSearchChange={onSearchChange} />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Countach' } });
    expect(onSearchChange).toHaveBeenCalledWith('Countach');
  });
});
