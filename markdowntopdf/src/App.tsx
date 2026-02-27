import { useRef, useState } from 'react';
import Editor from './components/Editor';
import Preview from './components/Preview';

const DEFAULT_MARKDOWN = `# Welcome to Markdown to PDF

Type your **markdown** here and see the live preview on the right.

## Features

- Live preview as you type
- Sanitized HTML output (XSS-safe)
- Download as PDF

## Example

Here is some \`inline code\` and a [link](https://example.com).

> A blockquote to demonstrate styling.

\`\`\`js
// A code block
console.log('Hello, world!');
\`\`\`
`;

function App(): JSX.Element {
  const [markdownText, setMarkdownText] = useState<string>(DEFAULT_MARKDOWN);
  const previewRef = useRef<HTMLDivElement>(null);

  return (
    <div className="app-container">
      <div className="app-toolbar">
        <h1>Markdown to PDF</h1>
      </div>
      <div className="pane-container">
        <Editor value={markdownText} onChange={setMarkdownText} />
        <Preview ref={previewRef} markdown={markdownText} />
      </div>
    </div>
  );
}

export default App;
