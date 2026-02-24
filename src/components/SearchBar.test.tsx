import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBar } from './SearchBar';

describe('SearchBar', () => {
  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  it('renders a text input', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('renders with default placeholder text', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.getByPlaceholderText(/search models/i)).toBeInTheDocument();
  });

  it('renders with custom placeholder text', () => {
    render(<SearchBar value="" onChange={vi.fn()} placeholder="Find a car…" />);
    expect(screen.getByPlaceholderText('Find a car…')).toBeInTheDocument();
  });

  it('renders the current value in the input', () => {
    render(<SearchBar value="Testarossa" onChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toHaveValue('Testarossa');
  });

  // -------------------------------------------------------------------------
  // Clear button visibility
  // -------------------------------------------------------------------------

  it('does not render the clear button when value is empty', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument();
  });

  it('renders the clear button when value is non-empty', () => {
    render(<SearchBar value="Enzo" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /clear search/i })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Interactions
  // -------------------------------------------------------------------------

  it('calls onChange with the new value on input change', () => {
    const onChange = vi.fn();
    render(<SearchBar value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Countach' } });
    expect(onChange).toHaveBeenCalledWith('Countach');
  });

  it('calls onChange with empty string when clear button is clicked', () => {
    const onChange = vi.fn();
    render(<SearchBar value="Enzo" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /clear search/i }));
    expect(onChange).toHaveBeenCalledWith('');
  });

  // -------------------------------------------------------------------------
  // Accessibility
  // -------------------------------------------------------------------------

  it('has an accessible label for the input', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText(/search car models/i)).toBeInTheDocument();
  });
});
