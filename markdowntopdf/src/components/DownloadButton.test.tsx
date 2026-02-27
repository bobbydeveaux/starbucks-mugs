import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { DownloadButton } from './DownloadButton';

const mockSave = vi.fn();
const mockFrom = vi.fn(() => ({ save: mockSave }));
const mockHtml2pdf = vi.fn(() => ({ from: mockFrom }));

vi.mock('html2pdf.js', () => ({ default: mockHtml2pdf }));

describe('DownloadButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSave.mockResolvedValue(undefined);
  });

  it('renders "Download PDF" button', () => {
    const ref = createRef<HTMLDivElement>();
    render(<DownloadButton previewRef={ref} />);
    expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
  });

  it('calls html2pdf().from(node).save() when clicked', async () => {
    const div = document.createElement('div');
    const ref = { current: div } as React.RefObject<HTMLDivElement>;
    render(<DownloadButton previewRef={ref} />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(mockFrom).toHaveBeenCalledWith(div));
    expect(mockSave).toHaveBeenCalled();
  });

  it('disables the button while generating', async () => {
    let resolvePromise!: () => void;
    mockSave.mockReturnValue(
      new Promise<void>((res) => {
        resolvePromise = res;
      }),
    );

    const div = document.createElement('div');
    const ref = { current: div } as React.RefObject<HTMLDivElement>;
    render(<DownloadButton previewRef={ref} />);

    fireEvent.click(screen.getByRole('button'));

    // Button should be disabled while async operation runs
    await waitFor(() =>
      expect(screen.getByRole('button')).toBeDisabled(),
    );

    resolvePromise();

    // Button re-enables after completion
    await waitFor(() =>
      expect(screen.getByRole('button')).not.toBeDisabled(),
    );
  });

  it('shows "Generating…" text while loading', async () => {
    let resolvePromise!: () => void;
    mockSave.mockReturnValue(
      new Promise<void>((res) => {
        resolvePromise = res;
      }),
    );

    const div = document.createElement('div');
    const ref = { current: div } as React.RefObject<HTMLDivElement>;
    render(<DownloadButton previewRef={ref} />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() =>
      expect(screen.getByRole('button')).toHaveTextContent('Generating…'),
    );

    resolvePromise();

    await waitFor(() =>
      expect(screen.getByRole('button')).toHaveTextContent('Download PDF'),
    );
  });

  it('displays an error message when pdf generation fails', async () => {
    mockSave.mockRejectedValue(new Error('pdf failed'));

    const div = document.createElement('div');
    const ref = { current: div } as React.RefObject<HTMLDivElement>;
    render(<DownloadButton previewRef={ref} />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() =>
      expect(screen.getByText('pdf failed')).toBeInTheDocument(),
    );
  });

  it('does nothing when previewRef.current is null', () => {
    const ref = { current: null } as unknown as React.RefObject<HTMLDivElement>;
    render(<DownloadButton previewRef={ref} />);
    fireEvent.click(screen.getByRole('button'));
    expect(mockHtml2pdf).not.toHaveBeenCalled();
  });
});
