import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchBar } from './SearchBar';

describe('SearchBar', () => {
  it('renders with the provided value', () => {
    render(<SearchBar value="testarossa" onChange={vi.fn()} />);
    const input = screen.getByRole('searchbox');
    expect(input).toHaveValue('testarossa');
  });

  it('renders default placeholder text', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.getByPlaceholderText(/search model names/i)).toBeInTheDocument();
  });

  it('renders custom placeholder text', () => {
    render(<SearchBar value="" onChange={vi.fn()} placeholder="Find a car…" />);
    expect(screen.getByPlaceholderText('Find a car…')).toBeInTheDocument();
  });

  it('calls onChange on every keystroke', async () => {
    const handleChange = vi.fn();
    const user = userEvent.setup();
    render(<SearchBar value="" onChange={handleChange} />);

    await user.type(screen.getByRole('searchbox'), 'abc');

    expect(handleChange).toHaveBeenCalledTimes(3);
    expect(handleChange).toHaveBeenNthCalledWith(1, 'a');
    expect(handleChange).toHaveBeenNthCalledWith(2, 'b');
    expect(handleChange).toHaveBeenNthCalledWith(3, 'c');
  });

  it('shows a clear button when value is non-empty', () => {
    render(<SearchBar value="something" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /clear search/i })).toBeInTheDocument();
  });

  it('does not show a clear button when value is empty', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /clear search/i })).not.toBeInTheDocument();
  });

  it('calls onChange with empty string when clear button is clicked', () => {
    const handleChange = vi.fn();
    render(<SearchBar value="Diablo" onChange={handleChange} />);
    fireEvent.click(screen.getByRole('button', { name: /clear search/i }));
    expect(handleChange).toHaveBeenCalledWith('');
  });

  it('has an accessible label', () => {
    render(<SearchBar value="" onChange={vi.fn()} />);
    // Either via aria-label or label element
    expect(screen.getByRole('searchbox', { name: /search car models/i })).toBeInTheDocument();
  });
});
