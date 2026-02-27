Here is the filled LLD document (written to `docs/concepts/markdowntopdf-clone/LLD.md`):

---

# Low-Level Design: MarkdownToPdf Clone

**Created:** 2026-02-27T20:24:36Z
**Status:** Draft

## 1. Implementation Overview

Self-contained Vite + React 18 SPA in `markdowntopdf/`. Four components wired by a single `useState` hook. `marked.js` parses markdown on every keystroke (debounced 150ms); `DOMPurify` sanitizes output before DOM injection; `html2pdf.js` is lazy-imported and captures the Preview node on button click.

---

## 2. File Structure

```
markdowntopdf/
  index.html              # Vite entry point
  package.json            # deps: react, marked, dompurify, html2pdf.js
  vite.config.ts
  src/
    main.tsx              # ReactDOM.createRoot mount
    App.tsx               # state owner + split-pane layout
    App.css               # flexbox split-pane styles
    utils/
      parseMarkdown.ts    # marked.parse + DOMPurify.sanitize
    components/
      Editor.tsx
      Preview.tsx
      DownloadButton.tsx
    App.test.tsx
    components/
      Preview.test.tsx
      DownloadButton.test.tsx
```

---

## 3. Detailed Component Designs

**App.tsx** — owns `markdownText: string` state (default = sample markdown); renders `<Editor>` left + `<Preview>` right in a flex row; holds `previewRef` passed to `<DownloadButton>`.

**Editor.tsx** — controlled `<textarea>` with `value` + `onChange` props; no internal state.

**Preview.tsx** — calls `parseMarkdown(markdown)`, injects via `dangerouslySetInnerHTML`; exposes forwarded `ref` for PDF capture.

**DownloadButton.tsx** — lazy-imports `html2pdf.js` on click; sets `loading` state during generation; renders inline error on failure.

---

## 4. Database Schema Changes

None — fully client-side, no persistence.

---

## 5. API Implementation Details

None — no network requests at runtime.

---

## 6. Function Signatures

```ts
// utils/parseMarkdown.ts
function parseMarkdown(raw: string): string  // marked.parse → DOMPurify.sanitize

// Editor.tsx
interface EditorProps { value: string; onChange: (v: string) => void }
function Editor(props: EditorProps): JSX.Element

// Preview.tsx
interface PreviewProps { markdown: string }
const Preview = forwardRef<HTMLDivElement, PreviewProps>(
  ({ markdown }, ref): JSX.Element
)

// DownloadButton.tsx
interface DownloadButtonProps { previewRef: RefObject<HTMLDivElement> }
function DownloadButton(props: DownloadButtonProps): JSX.Element
```

---

## 7. State Management

Single `useState<string>` in `App`; initialized with a default sample markdown (satisfies FR-004). No context, no external store. `DownloadButton` has local `loading: boolean` and `error: string | null` state only.

---

## 8. Error Handling Strategy

`DownloadButton` wraps `html2pdf` call in try/catch; on error renders an inline message beneath the button. `parseMarkdown` is pure — both `marked` and `DOMPurify` handle malformed input without throwing.

---

## 9. Test Plan

### Unit Tests
- `Preview.test.tsx`: heading/bold/list/code render correctly; `<script>` tags stripped by DOMPurify
- `DownloadButton.test.tsx`: mocks `html2pdf`, asserts `.from().save()` called on ref node; asserts button disabled during async op

### Integration Tests
- `App.test.tsx`: typing in Editor updates Preview; clicking DownloadButton invokes mocked pdf lib

### E2E Tests
- Playwright smoke: paste markdown → assert `<h1>` in preview → click Download → assert zero fetch/XHR with content body

---

## 10. Migration Strategy

New standalone directory `markdowntopdf/`. No changes to existing repo files. Add subpath config to `vercel.json` or `netlify.toml` if deploying under the root domain.

---

## 11. Rollback Plan

Revert the commit adding `markdowntopdf/`. Static host redeploys previous build via dashboard rollback or `git revert` + push to `main`.

---

## 12. Performance Considerations

- Debounce `parseMarkdown` calls to 150ms on Editor `onChange` to avoid thrashing on large pastes
- Lazy-import `html2pdf.js` on first button click (dynamic `import()`) — keeps initial JS bundle lean
- No memoization needed; parse is fast for typical document sizes (≤5,000 words per PRD NFR)