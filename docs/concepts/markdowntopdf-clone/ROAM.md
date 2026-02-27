# ROAM Analysis: markdowntopdf-clone

**Feature Count:** 2
**Created:** 2026-02-27T20:26:54Z

## Risks

1. **html2pdf.js PDF Output Quality** (High): `html2pdf.js` uses `html2canvas` to rasterize the preview before embedding in the PDF. This produces image-based (non-searchable, non-copyable) text in the PDF, potential blurriness at non-standard zoom levels, and large file sizes for text-heavy documents. This is the most likely gap between user expectations and actual output.

2. **PDF Generation Performance SLA** (High): The 3-second generation target for 5,000-word documents may be violated on mid-range hardware. `html2canvas` must render the full DOM to a canvas before PDF encoding — a CPU-bound, synchronous-feeling operation. Safari is historically slower at this than Chrome.

3. **html2canvas Cross-Browser Rendering Fidelity** (Medium): `html2canvas` does not support all CSS properties. Certain layout properties (e.g., `position: fixed`, CSS Grid in some versions, custom web fonts loaded via `@font-face`) may render incorrectly or be omitted in the captured canvas, causing the PDF to diverge visually from the on-screen preview.

4. **Bundle Size Impact from html2pdf.js** (Medium): `html2pdf.js` transitively bundles `html2canvas` (~200 KB) and `jsPDF` (~300 KB). Even with lazy import on first click, the first PDF generation triggers a large download. Users on slow connections will face a noticeable delay with no obvious explanation.

5. **DOMPurify Misconfiguration Allowing XSS** (Medium): `marked.js` produces raw HTML from untrusted markdown input. If `DOMPurify.sanitize()` is called with permissive options or bypassed (e.g., via a future refactor), injected `<script>` or event-handler attributes could execute in the user's browser. Risk is scoped to self-harm (user crafting malicious input for themselves) but could affect shared-link scenarios if a share feature is ever added.

6. **TypeScript Type Coverage for html2pdf.js** (Low): `html2pdf.js` does not ship first-party TypeScript types. Community `@types/html2pdf.js` packages are incomplete or absent, requiring manual type declarations. This slows development and suppresses type safety on the PDF generation path.

7. **html2pdf.js Ecosystem Maintenance** (Low): The package is lightly maintained (infrequent releases, open issues with html2canvas compatibility). A breaking change in a transitive dependency (html2canvas or jsPDF) may go unresolved upstream, requiring a fork or library swap.

---

## Obstacles

- **No TypeScript declarations for html2pdf.js**: The library lacks official `@types` support. A manual `declare module 'html2pdf.js'` stub will be required immediately to unblock TypeScript compilation; its accuracy will be unverified against the full API surface.

- **html2canvas CSS limitations require early testing**: The set of unsupported CSS properties in `html2canvas` is only discoverable by rendering real content. Without a working prototype tested against representative markdown (code blocks, tables, nested lists), unknown rendering failures may be discovered late.

- **Unit testing PDF generation is non-trivial**: `html2pdf.js` invokes browser canvas and Blob APIs unavailable in jsdom (the default Vitest/Jest environment). Meaningful test coverage requires either heavy mocking of the entire library or a Playwright-based test, adding setup friction before `DownloadButton.test.tsx` can be written.

- **No existing codebase to extend**: This is a greenfield project. All scaffolding, configuration, and tooling decisions must be made from scratch, so early setup errors (e.g., Vite config, tsconfig paths) can block downstream feature work if not caught quickly.

---

## Assumptions

1. **html2pdf.js produces output acceptable to target users without custom configuration** — Validation approach: Build a working prototype in the first development session and test PDF output against headings, bold/italic, ordered/unordered lists, inline code, and fenced code blocks. Determine acceptable quality before committing to the library.

2. **The 3-second PDF generation SLA is achievable on average consumer hardware** — Validation approach: Benchmark `html2pdf.js` on a mid-range laptop (not a developer machine) with a 5,000-word markdown document. Measure wall-clock time from button click to file download prompt. Accept or revise the SLA before launch.

3. **DOMPurify with default configuration is sufficient to sanitize marked.js output** — Validation approach: Run `DOMPurify.sanitize()` against a suite of known XSS payloads embedded in markdown (script tags, `onerror` attributes, `javascript:` hrefs, SVG-based vectors). Verify all are stripped in unit tests.

4. **Users are on modern desktop browsers (Chrome 110+, Firefox 110+, Safari 16+)** — Validation approach: This is stated as a desktop-first MVP in the PRD. Confirm that html2canvas compatibility matrices cover these versions before finalizing the tech stack.

5. **Lazy-importing html2pdf.js on first button click is sufficient UX for bundle size** — Validation approach: Measure perceived latency from button click to PDF download on a throttled 4G connection (DevTools). If delay exceeds ~2 seconds without visual feedback, a loading spinner or progress indicator must be added.

---

## Mitigations

### Risk 1: html2pdf.js PDF Output Quality
- **Action**: Build a throwaway prototype in day one to validate PDF output against all standard markdown elements (headings, lists, tables, code blocks). Do not proceed past the `Project Setup` feature without this validation.
- **Action**: Configure html2pdf.js options explicitly: set `scale: 2` for sharpness, `useCORS: true`, and appropriate margin/page format values. Document these in `DownloadButton.tsx` as named constants.
- **Contingency**: If output quality is unacceptable (e.g., blurry text, broken code block rendering), evaluate `window.print()` with a print-specific CSS stylesheet as a zero-dependency fallback that produces true vector PDF output via the browser's native print engine.

### Risk 2: PDF Generation Performance SLA
- **Action**: Benchmark against the 5,000-word target on non-developer hardware before shipping. If the 3-second SLA is not met, reduce the captured DOM by cloning and stripping the preview node before passing to html2pdf.js.
- **Action**: Show a loading state (`loading: boolean` is already designed into `DownloadButton`) immediately on click so users perceive responsiveness even if generation takes 2-4 seconds.
- **Action**: Add a PDF size/complexity warning if markdown length exceeds a threshold (e.g., >10,000 characters), setting appropriate expectations before generation begins.

### Risk 3: html2canvas Cross-Browser Rendering Fidelity
- **Action**: Establish a manual test checklist (headings, bold, code blocks, tables, images) run against Chrome, Firefox, and Safari before the feature is marked complete.
- **Action**: Restrict Preview CSS to properties with known html2canvas support. Avoid `position: fixed`, CSS Grid, and `@font-face` custom fonts in the preview pane. Use system-safe font stacks.
- **Action**: Add a Safari-specific note in the app UI if html2canvas rendering issues are discovered during testing, rather than silently degrading quality.

### Risk 4: Bundle Size Impact from html2pdf.js
- **Action**: The lazy-import pattern (`dynamic import()` on button click) is already specified in the LLD — ensure it is implemented correctly so html2pdf.js is excluded from the initial bundle.
- **Action**: Run `vite build --report` and inspect the chunk containing html2pdf.js. Confirm it is a separate async chunk, not inlined into the main bundle.
- **Action**: Add a loading indicator to `DownloadButton` that activates immediately on click (before the import resolves) to mask the download latency on slow connections.

### Risk 5: DOMPurify Misconfiguration
- **Action**: Call `DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })` with an explicit profile rather than relying on defaults, making the allowed tag/attribute set deliberate and auditable.
- **Action**: Include XSS payload tests in `Preview.test.tsx` — at minimum: `<script>alert(1)</script>`, `<img onerror="alert(1)" src=x>`, and `<a href="javascript:alert(1)">link</a>`. All must be stripped or neutralized in output.
- **Action**: Never skip DOMPurify in `parseMarkdown.ts` — enforce this with a lint rule or code review checklist item. Do not allow `marked.parse()` output to be used directly in `dangerouslySetInnerHTML`.

### Risk 6: TypeScript Type Coverage for html2pdf.js
- **Action**: Create a `src/types/html2pdf.d.ts` declaration file in the first development session, declaring only the API surface actually used (`.from().set().save()`). This unblocks TypeScript immediately without relying on incomplete community types.
- **Action**: Pin `html2pdf.js` to an exact version in `package.json` (no `^` or `~`) to prevent unexpected API changes from transitive updates.

### Risk 7: html2pdf.js Ecosystem Maintenance
- **Action**: Pin the version and audit open issues on the `html2pdf.js` GitHub repository before committing to it. Check whether current open issues affect any target markdown elements.
- **Contingency**: If html2pdf.js becomes unmaintained or a blocking bug is discovered, the fallback path is `window.print()` with a `@media print` CSS stylesheet — this requires no additional dependencies and produces native-quality PDFs at the cost of user needing to confirm a print dialog.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: MarkdownToPdf Clone

I want a website like markdowntopdf. I use it all the time but people pay for it! Would be good to have a similar one ! MVP can be just the free version. Can probably do it all in react at first without the need for backend API. Unless I'm wrong.

**Created:** 2026-02-27T20:22:58Z
**Status:** Draft

## 1. Overview

**Concept:** MarkdownToPdf Clone

I want a website like markdowntopdf. I use it all the time but people pay for it! Would be good to have a similar one ! MVP can be just the free version. Can probably do it all in react at first without the need for backend API. Unless I'm wrong.

**Description:** MarkdownToPdf Clone

I want a website like markdowntopdf. I use it all the time but people pay for it! Would be good to have a similar one ! MVP can be just the free version. Can probably do it all in react at first without the need for backend API. Unless I'm wrong.

---

## 2. Goals

- Provide free, unlimited markdown-to-PDF conversion entirely in the browser (no backend required)
- Deliver a live side-by-side preview so users see rendered output before downloading
- Produce clean, well-formatted PDF output matching standard markdown styling
- Keep the UI minimal and fast — no signup, no friction, immediate value

---

## 3. Non-Goals

- No paid/premium tiers or paywalls
- No user accounts, authentication, or saved history
- No server-side processing or cloud storage of documents
- No support for custom CSS themes or advanced PDF layout options in MVP

---

## 4. User Stories

- As a writer, I want to paste markdown into an editor so that I can convert it to PDF without installing software.
- As a user, I want a live preview of rendered markdown so that I can verify formatting before downloading.
- As a user, I want to click one button to download a PDF so that the process is fast and effortless.
- As a developer, I want the tool to work offline after initial load so that I can use it without internet access.
- As a user, I want my content to stay private so that my documents are never sent to a server.

---

## 5. Acceptance Criteria

**Markdown Editor:**
- Given the page loads, when I type or paste markdown, then the editor displays my input immediately.

**Live Preview:**
- Given I have markdown in the editor, when I view the preview pane, then I see correctly rendered HTML (headings, bold, lists, code blocks).

**PDF Download:**
- Given I have markdown in the editor, when I click "Download PDF", then a PDF file is generated client-side and saved to my device within 3 seconds.

**Privacy:**
- Given I enter any content, when I use the app, then no network requests containing my content are made.

---

## 6. Functional Requirements

- **FR-001:** Split-pane layout with a markdown text editor on the left and a rendered HTML preview on the right.
- **FR-002:** Real-time markdown rendering using a client-side parser (e.g., `marked.js`).
- **FR-003:** "Download PDF" button that triggers client-side PDF generation (e.g., `html2pdf.js`) from the rendered preview.
- **FR-004:** Default markdown content shown on load as a usage example/placeholder.

---

## 7. Non-Functional Requirements

### Performance
PDF generation must complete in under 3 seconds for documents up to 5,000 words. Page initial load under 2 seconds on a standard connection.

### Security
All processing is client-side only. No user content is transmitted over the network. No external analytics or tracking scripts.

### Scalability
Deployed as a static site (e.g., Vercel, Netlify, GitHub Pages) — scales to any traffic volume with zero backend infrastructure.

### Reliability
App must function fully offline after initial page load. No dependency on external APIs at runtime.

---

## 8. Dependencies

- **React** — UI framework
- **marked.js** — Client-side markdown parsing
- **html2pdf.js** — Client-side HTML-to-PDF conversion (wraps html2canvas + jsPDF)
- **Static hosting** — Vercel, Netlify, or GitHub Pages for deployment

---

## 9. Out of Scope

- Backend API, server-side rendering, or any cloud processing
- User authentication, accounts, or document history
- File upload (`.md` file import) — type/paste only in MVP
- Custom PDF styling, page size selection, or margin controls
- Mobile-optimized layout (desktop-first MVP)

---

## 10. Success Metrics

- PDF download success rate ≥ 99% across Chrome, Firefox, and Safari
- Page load time ≤ 2 seconds on a standard broadband connection
- Zero server-side data storage incidents (fully client-side by design)
- Functional parity with free tier of markdowntopdf.com (basic conversion)

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
# High-Level Design: MarkdownToPdf Clone

**Created:** 2026-02-27T20:24:02Z
**Status:** Draft

## 1. Architecture Overview

Single-page application (SPA) with no backend. All logic runs in the browser. React manages UI state; markdown parsing and PDF generation are performed entirely client-side using bundled libraries.

---

## 2. System Components

- **`App`** — Root component; holds markdown string in state, passes it down
- **`Editor`** — Controlled `<textarea>` for markdown input
- **`Preview`** — Renders HTML from parsed markdown via `dangerouslySetInnerHTML`
- **`DownloadButton`** — Triggers `html2pdf.js` on the Preview DOM node

---

## 3. Data Model

No persistent data. Single ephemeral state value:

```
markdownText: string  // lives in App component state, never leaves the browser
```

---

## 4. API Contracts

None. No network requests are made at runtime. All processing is local.

---

## 5. Technology Stack

### Backend
None — fully client-side.

### Frontend
- **React 18** — UI framework (Vite for build tooling)
- **marked.js** — Markdown-to-HTML parser (client-side)
- **html2pdf.js** — HTML-to-PDF via html2canvas + jsPDF (client-side)
- **CSS** — Split-pane layout via flexbox; no UI framework needed

### Infrastructure
- **Vercel / Netlify / GitHub Pages** — Static file hosting; no server required

### Data Storage
None — stateless by design.

---

## 6. Integration Points

None at runtime. `marked.js` and `html2pdf.js` are bundled into the build artifact — no CDN calls or external APIs.

---

## 7. Security Architecture

- No user data leaves the browser — no network requests containing content
- No authentication surface
- `marked.js` output should be sanitized (use `DOMPurify`) before injecting into the DOM to prevent XSS from malicious markdown input
- No cookies, local storage, or analytics

---

## 8. Deployment Architecture

```
Build: vite build  →  /dist (static HTML/JS/CSS)
         ↓
Static host (Vercel/Netlify/GitHub Pages)
         ↓
Browser (all runtime logic executes here)
```

Deploy on every push to `main` via host's built-in CI integration.

---

## 9. Scalability Strategy

Static assets served from CDN edge nodes. No backend means no scaling concerns — traffic volume has zero infrastructure impact.

---

## 10. Monitoring & Observability

Minimal: host-provided analytics (request counts, bandwidth) is sufficient. No application-level logging needed given there is no backend.

---

## 11. Architectural Decisions (ADRs)

**ADR-1: No backend** — All PRD requirements (parsing, PDF generation, privacy) are achievable client-side. Eliminating a backend removes hosting cost, ops burden, and the privacy risk of transmitting user content.

**ADR-2: html2pdf.js over jsPDF direct** — `html2pdf.js` renders the styled HTML preview directly to PDF, preserving visual fidelity with zero extra mapping logic.

**ADR-3: DOMPurify for XSS prevention** — `marked.js` produces raw HTML; sanitization before DOM injection is necessary to prevent script injection from crafted markdown.

**ADR-4: Vite over CRA** — Faster dev server and smaller production bundles; no meaningful tradeoff for a project this size.

---

## Appendix: PRD Reference

*(See PRD document: MarkdownToPdf Clone, created 2026-02-27)*

### LLD
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