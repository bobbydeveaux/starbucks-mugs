import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import App from './App';

// Mock html2pdf.js so tests don't try to actually generate PDFs
vi.mock('html2pdf.js', () => ({
  default: () => ({
    from: () => ({
      save: vi.fn().mockResolvedValue(undefined),
    }),
  }),
}));

describe('App integration', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders editor and preview panes', () => {
    render(<App />);
    expect(screen.getByLabelText('Markdown editor')).toBeInTheDocument();
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });

  it('shows default sample markdown in the editor', () => {
    render(<App />);
    const textarea = screen.getByLabelText('Markdown editor') as HTMLTextAreaElement;
    expect(textarea.value).toContain('Welcome to Markdown to PDF');
  });

  it('renders the Download PDF button', () => {
    render(<App />);
    expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
  });

  it('updates the preview after typing in the editor (debounced)', () => {
    vi.useFakeTimers();
    render(<App />);

    const textarea = screen.getByLabelText('Markdown editor');

    // Use fireEvent (synchronous) to avoid userEvent timer interaction issues
    act(() => {
      fireEvent.change(textarea, { target: { value: '# Hello World' } });
    });

    // Advance past the 150ms debounce
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // The preview should now contain the rendered heading
    const preview = document.querySelector('.preview-content');
    expect(preview).not.toBeNull();
    expect(preview?.innerHTML).toContain('<h1>');
  });

  it('sample markdown renders an h1 in the preview on load', () => {
    vi.useFakeTimers();
    render(<App />);

    act(() => {
      vi.advanceTimersByTime(200);
    });

    const preview = document.querySelector('.preview-content');
    expect(preview?.innerHTML).toContain('<h1>');
  });
});
