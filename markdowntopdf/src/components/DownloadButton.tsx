import { RefObject, useState } from 'react';

interface DownloadButtonProps {
  previewRef: RefObject<HTMLDivElement | null>;
}

export function DownloadButton({ previewRef }: DownloadButtonProps): JSX.Element {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = async () => {
    if (!previewRef.current) return;
    setLoading(true);
    setError(null);
    try {
      // Lazy-import: html2pdf.js stays out of the initial bundle
      const html2pdf = (await import('html2pdf.js')).default;
      await html2pdf().from(previewRef.current).save();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF generation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="download-button-wrapper">
      <button
        className="download-button"
        onClick={handleClick}
        disabled={loading}
        aria-busy={loading}
      >
        {loading ? 'Generating…' : 'Download PDF'}
      </button>
      {error && <p className="download-error">{error}</p>}
    </div>
  );
}
