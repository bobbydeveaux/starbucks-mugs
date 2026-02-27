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