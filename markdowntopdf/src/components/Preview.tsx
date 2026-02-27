import { forwardRef } from 'react';
import { parseMarkdown } from '../utils/parseMarkdown';

interface PreviewProps {
  markdown: string;
}

export const Preview = forwardRef<HTMLDivElement, PreviewProps>(
  ({ markdown }, ref): JSX.Element => {
    const html = parseMarkdown(markdown);
    return (
      <div className="pane preview-pane">
        <div className="pane-header">Preview</div>
        <div
          ref={ref}
          className="preview-content"
          // parseMarkdown sanitizes via DOMPurify before injection
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    );
  },
);

Preview.displayName = 'Preview';
