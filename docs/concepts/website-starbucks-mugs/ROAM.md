# ROAM Analysis: website-starbucks-mugs

**Feature Count:** 1
**Created:** 2026-02-24T00:19:24Z

## Risks

1. **Missing Image Assets** (Medium): The `images/` directory is referenced in the file structure but no mug images exist yet. Without real assets, cards will render broken image placeholders, failing the acceptance criteria visually.

2. **fetch() CORS Failure on Local File System** (Medium): Opening `index.html` directly via `file://` protocol causes `fetch('./mugs.json')` to fail in most browsers due to CORS restrictions, blocking development and testing without a local server.

3. **mugs.json Schema Drift** (Low): If mug entries in `mugs.json` omit required fields (`id`, `name`, `price`, `image`, `description`), `renderCards` and `openModal` will silently render incomplete or broken cards with no validation guard.

4. **Keyboard/Focus Accessibility Gap** (Low): The modal close behavior relies on ESC key and overlay click, but without explicit focus management (`focus()` on modal open, `tabIndex`, ARIA roles), keyboard-only users cannot navigate into or out of the modal, creating an accessibility defect.

5. **Browser Compatibility for ES6 fetch** (Low): The PRD lists ES6 `fetch` as a dependency but provides no fallback. Visitors on older browsers (IE11, legacy iOS Safari) will see a blank grid with no error message beyond the catch handler.

6. **Image Performance on Mobile** (Low): Unoptimized mug images (large PNGs/JPEGs) will degrade the 2-second load target on mobile connections even with `loading="lazy"`, since above-the-fold images load eagerly.

---

## Obstacles

- **No mug image assets exist**: The `images/` directory is not yet populated. Cards cannot be visually validated until placeholder or real images are sourced and sized appropriately.
- **No local dev server defined**: The project has no `package.json`, no `http-server` setup, and no documented way to serve files locally, which blocks `fetch()` from working during development.
- **mugs.json content not yet authored**: The data file is referenced throughout all design documents but does not exist in the repository. All rendering logic depends on it being present and correctly structured before any manual or automated testing can proceed.

---

## Assumptions

1. **Six mug records will be authored in mugs.json** — Acceptance criteria and success metrics both state "all 6 mugs." This assumes exactly 6 records will be created. *Validation: confirm count when mugs.json is authored; update AC if count changes.*

2. **Image assets will be local files, not remote URLs** — The HLD data model shows `"image": "url"` which could be a relative path or an absolute URL. The LLD implies local `images/` directory. *Validation: decide and document the image strategy (local vs. CDN URL) before authoring mugs.json.*

3. **A static host with HTTPS will be used for deployment** — Security architecture relies on the hosting provider for HTTPS; no self-signed cert or HTTP-only deploy is assumed. *Validation: confirm target host (GitHub Pages, Netlify, etc.) before deploying.*

4. **No build step is required** — Vanilla JS with no transpilation, bundling, or minification is assumed throughout. Files are served as-is. *Validation: confirm no team member introduces a framework or import syntax that requires a bundler.*

5. **Target browsers support ES6 fetch natively** — No polyfill is planned. *Validation: define minimum browser support explicitly (e.g., Chrome 60+, Firefox 55+, Safari 10.1+) and verify against expected audience.*

---

## Mitigations

**Risk 1 — Missing Image Assets**
- Source or create 6 placeholder mug images (minimum 400×400px) before beginning `renderCards` integration testing.
- Define a naming convention (`mug-1.jpg`, etc.) matching `mugs.json` entries so no path mismatches occur.
- Add an `onerror` handler on `<img>` elements to display a fallback placeholder image rather than a broken icon.

**Risk 2 — fetch() CORS Failure on Local File System**
- Add a one-line dev server setup to the README: `npx serve .` or `python3 -m http.server 8080`.
- Alternatively, include a `package.json` with a `"start": "npx serve ."` script so any contributor can run the site immediately.

**Risk 3 — mugs.json Schema Drift**
- Define and document the exact JSON schema (field names, types, required vs. optional) before authoring data.
- Add a lightweight validation step in `loadMugs()` that filters out records missing required fields and logs a warning, preventing a single bad record from breaking the entire grid.

**Risk 4 — Keyboard/Focus Accessibility Gap**
- In `openModal()`, call `modal.focus()` after making it visible and set `tabIndex="-1"` on the modal container.
- In `closeModal()`, restore focus to the card that triggered the open (`document.activeElement` captured before open).
- Add `role="dialog"` and `aria-modal="true"` to the modal overlay markup in `index.html`.

**Risk 5 — Browser Compatibility for ES6 fetch**
- Add a `<script>` existence check or a `typeof fetch === 'undefined'` guard in `app.js` that renders a static fallback message for unsupported browsers.
- Document the minimum supported browser versions in the README.

**Risk 6 — Image Performance on Mobile**
- Require all mug images be exported at no larger than 800×800px and compressed to under 100 KB each (total image budget: ~600 KB).
- Use `width` and `height` attributes on `<img>` elements to prevent layout shift while images load lazily.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Website Starbucks Mugs

A website about Starbucks mugs

**Created:** 2026-02-24T00:17:41Z
**Status:** Draft

## 1. Overview

**Concept:** Website Starbucks Mugs

A website about Starbucks mugs

**Description:** Website Starbucks Mugs

A website about Starbucks mugs

---

## 2. Goals

- Display a browsable catalog of Starbucks mugs with name, price, and image
- Allow users to view detailed information for any mug via a modal
- Provide a responsive layout usable on desktop and mobile

---

## 3. Non-Goals

- No e-commerce or checkout functionality
- No user accounts or authentication
- No real-time inventory or Starbucks API integration

---

## 4. User Stories

- As a visitor, I want to browse all available mugs so I can see what's offered
- As a visitor, I want to click a mug to see its full details so I can learn more before purchasing elsewhere

---

## 5. Acceptance Criteria

- **Given** the page loads, **when** the grid renders, **then** all 6 mugs display with image, name, and price
- **Given** a mug card is clicked, **when** the modal opens, **then** it shows image, name, price, and description with a close button

---

## 6. Functional Requirements

- FR-001: Fetch mug data from `mugs.json` and render cards dynamically into `#grid`
- FR-002: Modal overlay displays full mug details on card click and closes on dismiss

---

## 7. Non-Functional Requirements

### Performance
Page loads and grid renders within 2 seconds on a standard connection.

### Security
Static site only; no user input or server-side processing required.

### Scalability
JSON data file supports adding new mugs without code changes.

### Reliability
No external API dependencies; site functions fully offline after initial load.

---

## 8. Dependencies

- Static JSON file (`mugs.json`) as data source
- Modern browser with ES6 `fetch` support

---

## 9. Out of Scope

- Shopping cart, checkout, or payment processing
- Search, filtering, or sorting of mugs
- Backend server or database

---

## 10. Success Metrics

- All 6 mugs render correctly on page load
- Modal opens and closes without errors on all cards
- Layout is usable on viewports 320px and wider

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
# High-Level Design: starbucks-mugs

**Created:** 2026-02-24T00:18:31Z
**Status:** Draft

## 1. Architecture Overview

Static single-page application. Browser fetches `mugs.json` and renders the UI entirely client-side. No backend.

---

## 2. System Components

- **index.html** — Page structure, grid container (`#grid`), and modal overlay
- **app.js** — Fetches `mugs.json`, renders cards, handles modal open/close
- **mugs.json** — Static data source for all mug records

---

## 3. Data Model

```json
{ "id": 1, "name": "string", "price": 9.99, "image": "url", "description": "string" }
```

---

## 4. API Contracts

No API. `fetch('./mugs.json')` returns an array of mug objects as defined above.

---

## 5. Technology Stack

### Backend
None — fully static.

### Frontend
HTML5, CSS3 (Flexbox/Grid), vanilla ES6 JavaScript.

### Infrastructure
Static file host (GitHub Pages, Netlify, or any CDN).

### Data Storage
`mugs.json` flat file bundled with the site.

---

## 6. Integration Points

None. No external APIs or webhooks.

---

## 7. Security Architecture

Static files only; no user input, no server, no secrets. Standard HTTPS via host provider.

---

## 8. Deployment Architecture

Deploy static files (`index.html`, `app.js`, `style.css`, `mugs.json`, images) to any static host.

---

## 9. Scalability Strategy

Add mugs by appending entries to `mugs.json`. No code changes required.

---

## 10. Monitoring & Observability

Browser console for local debugging. Host provider analytics (e.g., Netlify analytics) for traffic visibility.

---

## 11. Architectural Decisions (ADRs)

- **Vanilla JS over framework**: Zero build tooling needed for a 6-item static catalog.
- **JSON flat file over CMS**: Simplest data source; meets scalability needs without infrastructure cost.

---

## Appendix: PRD Reference

*(See PRD: Website Starbucks Mugs, 2026-02-24)*

### LLD
# Low-Level Design: starbucks-mugs

**Created:** 2026-02-24T00:18:50Z
**Status:** Draft

## 1. Implementation Overview

Static HTML/CSS/JS site. `app.js` fetches `mugs.json` and renders a grid of cards with a click-to-expand modal.

---

## 2. File Structure

```
index.html       — Shell, grid container, modal markup
style.css        — Grid layout, card styles, modal overlay
app.js           — Data fetch, render, modal logic
mugs.json        — Mug records array
images/          — Mug image assets
```

---

## 3. Detailed Component Designs

**Card grid:** `#grid` div populated by `renderCards(mugs)` — one `.card` div per mug.
**Modal:** `#modal` overlay shown on card click; closed via overlay click or ESC key.

---

## 4. Database Schema Changes

None.

---

## 5. API Implementation Details

None. `fetch('./mugs.json')` → JSON array.

---

## 6. Function Signatures

```js
async function loadMugs(): Promise<Mug[]>
function renderCards(mugs: Mug[]): void
function openModal(mug: Mug): void
function closeModal(): void
```

---

## 7. State Management

Module-level `let currentMug = null`. No framework needed.

---

## 8. Error Handling Strategy

`fetch` failure → display "Failed to load mugs." message in `#grid`.

---

## 9. Test Plan

### Unit Tests
Verify `renderCards` produces correct card count.

### Integration Tests
Mock `fetch`; assert grid renders and modal opens on click.

### E2E Tests
None required for this complexity tier.

---

## 10. Migration Strategy

Drop files onto static host. No existing state to migrate.

---

## 11. Rollback Plan

Redeploy previous file versions from git.

---

## 12. Performance Considerations

Lazy-load images via `loading="lazy"`. Keep `mugs.json` under 10 KB.

---

## Appendix: Existing Repository Structure

```
.git
docs/
  concepts/
    website-starbucks-mugs/
      HLD.md
      PRD.md
      README.md
```