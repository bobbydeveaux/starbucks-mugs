import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBox } from './SearchBox';

describe('SearchBox', () => {
  it('renders a search input', () => {
    render(<SearchBox value="" onChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('renders with the default placeholder', () => {
    render(<SearchBox value="" onChange={vi.fn()} />);
    expect(screen.getByPlaceholderText('Search drinks…')).toBeInTheDocument();
  });

  it('renders with a custom placeholder', () => {
    render(<SearchBox value="" onChange={vi.fn()} placeholder="Find a drink…" />);
    expect(screen.getByPlaceholderText('Find a drink…')).toBeInTheDocument();
  });

  it('displays the current value in the input', () => {
    render(<SearchBox value="latte" onChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toHaveValue('latte');
  });

  it('calls onChange with the new value when typing', () => {
    const onChange = vi.fn();
    render(<SearchBox value="" onChange={onChange} />);
    const input = screen.getByRole('searchbox');
    fireEvent.change(input, { target: { value: 'flat white' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('flat white');
  });

  it('does not show a clear button when value is empty', () => {
    render(<SearchBox value="" onChange={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument();
  });

  it('shows a clear button when value is non-empty', () => {
    render(<SearchBox value="latte" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /clear search/i })).toBeInTheDocument();
  });

  it('calls onChange with empty string when clear button is clicked', () => {
    const onChange = vi.fn();
    render(<SearchBox value="latte" onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /clear search/i }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('has a visually hidden label for accessibility', () => {
    render(<SearchBox value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText(/search drinks/i)).toBeInTheDocument();
  });
});
