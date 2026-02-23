# ROAM Analysis: starbucks-mugs-website

**Feature Count:** 1
**Created:** 2026-02-19T17:09:43Z
**Refined:** 2026-02-23

## Risks

1. **Trademark and Intellectual Property Exposure** (High): Using Starbucks branding and product names without authorization may constitute trademark infringement. `mugs.json` mug names explicitly reference "Starbucks" in 4 of 6 records (e.g., "Starbucks Classic White Mug", "Starbucks Reserve Black Mug"), and descriptions mention Starbucks throughout. The page `<title>` and any visible `<h1>` headings should also be audited — site-level branding carries the same exposure as individual mug names. A footer disclaimer is present ("Fan site. Not affiliated with Starbucks Corporation.") and images source from Unsplash rather than Starbucks.com, which reduces — but does not eliminate — exposure.

2. **Image URL Rot** (Medium): `mugs.json` references six Unsplash URLs with query-string transform parameters (`?w=400&h=400&fit=crop`). If Unsplash restructures its CDN, changes URL patterns, or images are removed, cards render broken with no fallback. No `onerror` handler is currently implemented in `createCard()` (app.js:31) nor on the detail image populated in `openDetail()` (app.js:68–69).

3. **`fetch()` and ES Module Blocked on `file://` Protocol** (Medium): `app.js` is loaded as `type="module"` (index.html:41) and uses `fetch('mugs.json')`. Browsers block both ES module loading and fetch requests over the `file://` protocol. Opening `index.html` directly from the filesystem silently breaks all rendering. `README.md` still contains only `# starbucks-mugs` with no dev server instructions, leaving contributors without a documented local setup path.

4. **CSS Grid Browser Coverage** (Very Low): No `display: flex; flex-wrap: wrap;` fallback precedes the Grid declaration in `style.css`. This risk is substantially reduced: three explicit responsive breakpoints now cover narrow phones (single column), mid-range phones (2 columns), and tablets+ (auto-fill). CSS Grid has near-universal browser support as of 2026. A flex fallback remains a best-practice hardening measure only.

5. **Single Point of Failure in Hosting** (Low): GitHub Pages and Netlify free tiers impose bandwidth and build limits. A traffic spike could trigger rate limiting or temporary unavailability.

6. **`innerHTML` XSS Surface** (Low): `createCard()` injects `mug.imageUrl` and `mug.name` via template literals in `innerHTML` (app.js:29–37) without sanitization. Safe with static `mugs.json`, but creates an XSS vector if the data source ever changes. Note: `openDetail()` correctly uses `textContent` and direct property assignment — only `createCard()` is affected.

7. **Modal Focus Trap Absent** (Low): The detail overlay uses `role="dialog"` and `aria-modal="true"` (index.html:25), and `openDetail()` correctly moves focus to the close button (app.js:75). However, no focus trap is implemented — keyboard users can tab past the close button into background content behind the overlay. This is a WCAG 2.1 AA violation and may affect keyboard and screen-reader users.

---

## Resolved Since Last Review

- **Risk 3 (Detail Page Routing Undefined)** — Resolved. Implemented as a modal overlay (`#detail-overlay`) in `index.html` controlled by `openDetail()` / `closeDetail()` in `app.js`. No separate HTML file or URL change occurs.
- **Risk 5 (Mug Data Gap)** — Resolved. `mugs.json` contains 6 records with names, prices, descriptions, and Unsplash image URLs.
- **Obstacle: No mug content** — Resolved.
- **Obstacle: Detail view not decided** — Resolved (modal overlay).

---

## Obstacles

- **No dev server documented:** `README.md` is still `# starbucks-mugs` only. Both `fetch()` and `type="module"` require an HTTP origin. This must be documented before onboarding contributors.
- **Test plan not implemented:** The LLD specifies unit tests for `createCard()`, integration tests for `loadMugs()`, and an E2E assertion on grid visibility. No test files or test infrastructure exist in the repository (`index.html`, `style.css`, `app.js`, `mugs.json` only). Tests must be written before the site can be considered release-validated.

---

## Assumptions

1. **Unsplash image URLs are stable.** Images confirmed from Unsplash (not Starbucks.com), but remain external dependencies with CDN query parameters. *Validation: Monitor for 404s; migrate to `/images` self-hosting if breakage occurs.*

2. **Footer disclaimer is sufficient for fan-site use.** Disclaimer ("Fan site. Not affiliated with Starbucks Corporation.") is implemented. No legal review conducted. *Validation: Consider expanding disclaimer language and auditing mug name copy — including page title and headings — before wide public promotion.*

3. **Detail view is a modal overlay on a single `index.html`.** `openDetail()` / `closeDetail()` control an overlay panel; no URL changes occur. *Status: Implemented and confirmed.*

4. **`mugs.json` will remain small enough that no pagination is needed.** 6 records currently; well within the ~10–30 target. *Status: Confirmed; revisit if collection exceeds 50.*

5. **Developers will use a local HTTP server during development.** *Validation: Not yet documented in `README.md` — still outstanding.*

6. **No automated tests are required for initial release.** The LLD test plan exists as documentation but no test runner, framework, or test files have been provisioned. *Validation: Confirm with team whether pre-release testing is manual only or if a lightweight framework (e.g., Playwright for E2E) should be added.*

---

## Mitigations

**Risk 1 — Trademark and IP Exposure**
- Footer disclaimer is present — consider expanding to: "Unofficial fan site — not affiliated with or endorsed by Starbucks Corporation. All trademarks belong to their respective owners."
- Audit all visible branding: `mugs.json` mug names and descriptions, the page `<title>` tag, and any `<h1>` / site header text. Replace explicit "Starbucks" prefixes with descriptive names where possible (e.g., "Classic White Ceramic Mug").
- Confirm Unsplash image licensing covers non-commercial fan-site use.

**Risk 2 — Image URL Rot**
- Add an `onerror` handler on `<img>` inside `createCard()` (app.js:31) to swap in a local placeholder (`images/placeholder.png`) on load failure.
- Add the same fallback to the detail image populated in `openDetail()` (app.js:68).
- Consider migrating images to a `/images` folder in the repository to eliminate the external URL dependency.

**Risk 3 — `fetch()` and ES Module Blocked on `file://`**
- Document the required dev server command in `README.md` (e.g., `npx serve .` or `python -m http.server 8080`) as a mandatory setup step.
- Note that `app.js` is an ES module (`type="module"`) and requires an HTTP origin for both module loading and `fetch()`.

**Risk 4 — CSS Grid Browser Coverage**
- Existing responsive breakpoints in `style.css` already handle narrow and mid-range phone layouts explicitly.
- Optionally add `display: flex; flex-wrap: wrap;` fallback ahead of the Grid declaration for belt-and-suspenders coverage on legacy browsers.
- Cross-browser smoke test on current Chrome, Firefox, Safari, and Edge before final release.

**Risk 5 — Hosting Single Point of Failure**
- Enable Netlify's free CDN caching to absorb traffic spikes.
- Document GitHub Pages as a fallback deployment target.

**Risk 6 — `innerHTML` XSS Surface**
- No action required for the current static implementation.
- If the data source ever changes, refactor `createCard()` to use `document.createElement` and set properties directly rather than `innerHTML`, consistent with how `openDetail()` is already implemented.

**Risk 7 — Modal Focus Trap Absent**
- Implement a focus trap in `openDetail()`: capture Tab and Shift+Tab keydown events to cycle focus within the overlay's focusable elements.
- On close, restore focus to the card that triggered the overlay (store a reference to `document.activeElement` before opening).

---

**Changes made vs. prior version:**

- Removed the implementation-state notes that were prepended to the file (those belong in a review log, not the ROAM document itself).
- **Risk 1**: Extended scope to include `<title>` and `<h1>` headings as trademark exposure surfaces, not just `mugs.json` content.
- **Assumption #2**: Aligned with Risk 1 expansion — now explicitly calls out page title and headings in the validation note.
- **Risk 1 mitigation**: Audit scope updated to cover all visible branding (title, headings, data file).
- **Obstacles**: Added "Test plan not implemented" — the LLD documents unit/integration/E2E tests but no test infrastructure exists in the file tree.
- **Assumption #6**: Added to capture the open question of whether automated testing is expected before release.