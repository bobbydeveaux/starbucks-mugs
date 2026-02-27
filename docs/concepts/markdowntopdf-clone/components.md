# MarkdownToPDF Clone — Component Reference

**Location:** `markdowntopdf/src/`

Self-contained Vite + React 18 SPA. Four components wired by a single `useState` hook in `App.tsx`.

---

## Architecture

```
App (markdowntopdf/src/App.tsx)
├── state: markdownText (string, debounced 150ms → debouncedText)
├── ref:   previewRef (HTMLDivElement)
├── <Editor value={markdownText} onChange={setMarkdownText} />
├── <Preview ref={previewRef} markdown={debouncedText} />
└── <DownloadButton previewRef={previewRef} />
```

---

## App.tsx

**File:** `markdowntopdf/src/App.tsx`

Single state owner. Owns `markdownText: string` (initialised with sample markdown) and `previewRef: RefObject<HTMLDivElement>`. Debounces parse updates to 150ms via `useEffect` + `setTimeout`. Renders a flex-row split-pane with `<Editor>` left and `<Preview>` right, and a header bar with `<DownloadButton>`.

---

## App.css

**File:** `markdowntopdf/src/App.css`

Global resets + flexbox layout. Key classes:

| Class | Purpose |
|---|---|
| `.app` | Root column flex container (full-height) |
| `.app-header` | Top bar with title and download button |
| `.split-pane` | Flex-row wrapper that fills remaining height |
| `.pane` | Shared 50% flex child (Editor or Preview) |
| `.editor-textarea` | Full-height monospace textarea, no resize |
| `.preview-content` | Scrollable prose area with markdown styles |
| `.download-button` | Styled CTA button in the header |

Stacks panes vertically on screens ≤ 640 px.

---

## Editor.tsx

**File:** `markdowntopdf/src/components/Editor.tsx`

Controlled `<textarea>` — no internal state.

```ts
interface EditorProps {
  value: string;
  onChange: (value: string) => void;
}
```

---

## Preview.tsx

**File:** `markdowntopdf/src/components/Preview.tsx`

Calls `parseMarkdown(markdown)` and injects via `dangerouslySetInnerHTML`. Forwards its `ref` to the wrapping `<div>` for PDF capture.

```ts
interface PreviewProps { markdown: string }
const Preview = forwardRef<HTMLDivElement, PreviewProps>(...)
```

---

## DownloadButton.tsx

**File:** `markdowntopdf/src/components/DownloadButton.tsx`

Lazy-imports `html2pdf.js` on click (dynamic `import()` — not top-level). Manages `loading: boolean` and `error: string | null` state. Disables button during generation; renders inline error on failure.

```ts
interface DownloadButtonProps {
  previewRef: RefObject<HTMLDivElement | null>;
}
```

---

## parseMarkdown utility

**File:** `markdowntopdf/src/utils/parseMarkdown.ts`

```ts
function parseMarkdown(raw: string): string
```

Chains `marked.parse()` → `DOMPurify.sanitize()`. Returns empty string for blank input.

---

## Tests

| File | Coverage |
|---|---|
| `markdowntopdf/src/App.test.tsx` | Editor↔Preview integration, debounce, default content, Download button render |
