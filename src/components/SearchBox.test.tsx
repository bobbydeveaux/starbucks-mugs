import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SearchBox } from './SearchBox';

describe('SearchBox', () => {
  it('renders a search input', () => {
    render(<SearchBox query="" onQueryChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('displays the current query value', () => {
    render(<SearchBox query="latte" onQueryChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toHaveValue('latte');
  });

  it('calls onQueryChange on each keystroke', () => {
    const onQueryChange = vi.fn();
    render(<SearchBox query="" onQueryChange={onQueryChange} />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mo' } });
    expect(onQueryChange).toHaveBeenCalledOnce();
    expect(onQueryChange).toHaveBeenCalledWith('mo');
  });

  it('has an accessible label', () => {
    render(<SearchBox query="" onQueryChange={vi.fn()} />);
    expect(screen.getByLabelText(/search drinks/i)).toBeInTheDocument();
  });

  it('renders an empty input when query is empty string', () => {
    render(<SearchBox query="" onQueryChange={vi.fn()} />);
    expect(screen.getByRole('searchbox')).toHaveValue('');
  });
});
