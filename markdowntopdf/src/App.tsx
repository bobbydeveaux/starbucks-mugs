import { useCallback, useEffect, useRef, useState } from 'react';
import { Editor } from './components/Editor';
import { Preview } from './components/Preview';
import { DownloadButton } from './components/DownloadButton';

const SAMPLE_MARKDOWN = `# Welcome to Markdown to PDF

Type your **markdown** here and see it rendered live in the preview pane.

## Features

- Live preview as you type
- Syntax-highlighted headings, bold, italic, and lists
- One-click **PDF download**

## Example

Here is some \`inline code\` and a code block:

\`\`\`js
function greet(name) {
  return \`Hello, \${name}!\`;
}
\`\`\`

> Blockquotes work too.

---

Start editing above to see your changes reflected instantly.
`;

/**
 * App is the single state owner for the markdown editor.
 *
 * State:
 *   - markdownText  – the raw markdown string bound to the Editor
 *   - debouncedText – debounced (150ms) version passed to Preview to avoid
 *                     thrashing the parser on rapid keystrokes
 *
 * Refs:
 *   - previewRef – forwarded to Preview's wrapping div; used by DownloadButton
 *                  to capture the rendered content for pdf generation
 */
function App(): JSX.Element {
  const [markdownText, setMarkdownText] = useState<string>(SAMPLE_MARKDOWN);
  const [debouncedText, setDebouncedText] = useState<string>(SAMPLE_MARKDOWN);
  const previewRef = useRef<HTMLDivElement>(null);

  // Debounce markdown parsing: wait 150ms after the last keystroke
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedText(markdownText);
    }, 150);
    return () => clearTimeout(timer);
  }, [markdownText]);

  const handleEditorChange = useCallback((value: string) => {
    setMarkdownText(value);
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">Markdown to PDF</h1>
        <DownloadButton previewRef={previewRef} />
      </header>
      <main className="split-pane">
        <Editor value={markdownText} onChange={handleEditorChange} />
        <Preview ref={previewRef} markdown={debouncedText} />
      </main>
    </div>
  );
}

export default App;
