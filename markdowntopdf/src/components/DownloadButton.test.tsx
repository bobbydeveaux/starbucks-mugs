import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DownloadButton } from './DownloadButton';

// Factory that returns a mock html2pdf builder chain
const makeMockHtml2pdf = (resolvesOrRejects: 'resolve' | 'reject' = 'resolve') => {
  const save = resolvesOrRejects === 'resolve'
    ? vi.fn().mockResolvedValue(undefined)
    : vi.fn().mockRejectedValue(new Error('PDF generation failed'));
  const from = vi.fn().mockReturnValue({ save });
  const instance = vi.fn().mockReturnValue({ from });
  return { instance, from, save };
};

// Helper: build a real DOM div and a React ref pointing to it
function makePreviewRef(exists = true): React.RefObject<HTMLDivElement | null> {
  const el = exists ? document.createElement('div') : null;
  return { current: el } as React.RefObject<HTMLDivElement | null>;
}

describe('DownloadButton', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('renders the "Download PDF" button', () => {
    const ref = makePreviewRef();
    render(<DownloadButton previewRef={ref} />);
    expect(screen.getByRole('button', { name: /download pdf/i })).toBeInTheDocument();
  });

  it('button is enabled by default', () => {
    const ref = makePreviewRef();
    render(<DownloadButton previewRef={ref} />);
    expect(screen.getByRole('button', { name: /download pdf/i })).not.toBeDisabled();
  });

  it('shows "Generating…" and disables button while PDF is being generated', async () => {
    const { instance, save } = makeMockHtml2pdf('resolve');
    // Make save hang until we resolve manually
    let resolveSave!: () => void;
    save.mockReturnValue(new Promise<void>((res) => { resolveSave = res; }));

    vi.doMock('html2pdf.js', () => ({ default: instance }));
    const { DownloadButton: DB } = await import('./DownloadButton');

    const ref = makePreviewRef();
    render(<DB previewRef={ref} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download pdf/i }));

    // Button becomes disabled and shows generating text
    expect(await screen.findByRole('button', { name: /generating/i })).toBeDisabled();

    // Resolve the hanging promise so the component can unmount cleanly
    await act(async () => {
      resolveSave();
    });
  });

  it('restores button after successful PDF generation', async () => {
    const { instance } = makeMockHtml2pdf('resolve');
    vi.doMock('html2pdf.js', () => ({ default: instance }));
    const { DownloadButton: DB } = await import('./DownloadButton');

    const ref = makePreviewRef();
    render(<DB previewRef={ref} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /download pdf/i })).not.toBeDisabled()
    );
  });

  it('shows an inline error message when html2pdf.js throws', async () => {
    const { instance } = makeMockHtml2pdf('reject');
    vi.doMock('html2pdf.js', () => ({ default: instance }));
    const { DownloadButton: DB } = await import('./DownloadButton');

    const ref = makePreviewRef();
    render(<DB previewRef={ref} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(() =>
      expect(screen.getByText('PDF generation failed')).toBeInTheDocument()
    );
  });

  it('does not call html2pdf when previewRef is null', async () => {
    const { instance } = makeMockHtml2pdf('resolve');
    vi.doMock('html2pdf.js', () => ({ default: instance }));
    const { DownloadButton: DB } = await import('./DownloadButton');

    const ref = makePreviewRef(false); // ref.current is null
    render(<DB previewRef={ref} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download pdf/i }));

    // html2pdf constructor must not be called
    await waitFor(() => expect(instance).not.toHaveBeenCalled());
  });

  it('calls html2pdf().from() with the previewRef node', async () => {
    const { instance, from } = makeMockHtml2pdf('resolve');
    vi.doMock('html2pdf.js', () => ({ default: instance }));
    const { DownloadButton: DB } = await import('./DownloadButton');

    const el = document.createElement('div');
    const ref = { current: el } as React.RefObject<HTMLDivElement | null>;
    render(<DB previewRef={ref} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /download pdf/i }));

    await waitFor(() => expect(from).toHaveBeenCalledWith(el));
  });
});
