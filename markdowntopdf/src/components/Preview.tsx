import { forwardRef } from 'react';
import { parseMarkdown } from '../utils/parseMarkdown';

interface PreviewProps {
  markdown: string;
}

const Preview = forwardRef<HTMLDivElement, PreviewProps>(
  ({ markdown }, ref): JSX.Element => {
    const html = parseMarkdown(markdown);
    return (
      <div
        ref={ref}
        className="preview-pane"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  },
);

Preview.displayName = 'Preview';

export default Preview;
