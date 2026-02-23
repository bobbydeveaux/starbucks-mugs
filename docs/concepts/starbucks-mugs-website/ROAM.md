# ROAM Analysis: starbucks-mugs-website

**Feature Count:** 1
**Created:** 2026-02-19T17:09:43Z
**Refined:** 2026-02-23

## Risks

1. **Trademark and Intellectual Property Exposure** (High): Using Starbucks branding and product names without authorization may constitute trademark infringement. `mugs.json` mug names explicitly reference "Starbucks" (e.g., "Starbucks Classic White Mug", "Starbucks Reserve Black Mug"). A footer disclaimer is in place and images now source from Unsplash rather than Starbucks.com, which reduces — but does not eliminate — exposure. The Starbucks name in mug titles and the overall site branding remain the primary risk.

2. **Image URL Rot** (Medium): `mugs.json` references six Unsplash URLs with query-string transform parameters (`?w=400&h=400&fit=crop`). If Unsplash restructures its CDN, changes URL patterns, or images are removed, cards render broken with no fallback. No `onerror` handler is currently implemented in `createCard()`.

3. **`fetch()` and ES Module Blocked on `file://` Protocol** (Medium): `app.js` is loaded as `type="module"` and uses `fetch('mugs.json')`. Browsers block both ES module loading and fetch requests over the `file://` protocol. Opening `index.html` directly from the filesystem silently breaks all rendering. `README.md` currently contains only `# starbucks-mugs` with no dev server instructions, leaving contributors without a documented local setup path.

4. **CSS Grid Browser Coverage** (Low): No `display: flex; flex-wrap: wrap;` fallback is present in `style.css`.

5. **Single Point of Failure in Hosting** (Low): GitHub Pages and Netlify free tiers impose bandwidth and build limits. A traffic spike could trigger rate limiting or temporary unavailability.

6. **`innerHTML` XSS Surface** (Low): `createCard()` injects `mug.imageUrl` and `mug.name` via `innerHTML` without sanitization. Safe with static `mugs.json`, but creates an XSS vector if the data source ever changes.

---

## Resolved Since Last Review

- **Risk 3 (Detail Page Routing Undefined)** — Resolved. Implemented as a modal overlay (`#detail-overlay`) in `index.html` controlled by `openDetail()` / `closeDetail()` in `app.js`. No separate HTML file or URL change occurs.
- **Risk 5 (Mug Data Gap)** — Resolved. `mugs.json` contains 6 records with names, prices, descriptions, and Unsplash image URLs.
- **Obstacle: No mug content** — Resolved.
- **Obstacle: Detail view not decided** — Resolved (modal overlay).

---

## Obstacles

- **No dev server documented:** `README.md` is still `# starbucks-mugs` only. Both `fetch()` and `type="module"` require an HTTP origin. This must be documented before onboarding contributors.

---

## Assumptions

1. **Unsplash image URLs are stable.** Images now confirmed from Unsplash (not Starbucks.com), but remain external dependencies with CDN query parameters. *Validation: Monitor for 404s; migrate to `/images` self-hosting if breakage occurs.*

2. **Footer disclaimer is sufficient for fan-site use.** Disclaimer ("Fan site. Not affiliated with Starbucks Corporation.") is implemented but brief. No legal review conducted. *Validation: Consider expanding disclaimer language before wide public promotion.*

3. **Detail view is a modal overlay on a single `index.html`.** *(Previously assumed query-param routing — superseded by implementation.)* `openDetail()` / `closeDetail()` control an overlay panel; no URL changes occur. *Status: Implemented and confirmed.*

4. **`mugs.json` will remain small enough that no pagination is needed.** 6 records currently; well within the ~10–30 target. *Status: Confirmed; revisit if collection exceeds 50.*

5. **Developers will use a local HTTP server during development.** *Validation: Not yet documented in `README.md` — still outstanding.*

---

## Mitigations

**Risk 1 — Trademark and IP Exposure**
- Footer disclaimer is present — consider expanding to: "Unofficial fan site — not affiliated with or endorsed by Starbucks Corporation."
- Audit `mugs.json` mug names; consider replacing explicit "Starbucks" prefixes with descriptive names where possible.
- Confirm Unsplash image licensing covers non-commercial fan-site use.

**Risk 2 — Image URL Rot**
- Add an `onerror` handler on `<img>` inside `createCard()` to swap in a local placeholder (`images/placeholder.png`) on load failure.
- Consider migrating images to a `/images` folder in the repository to eliminate the external URL dependency.

**Risk 3 — `fetch()` and ES Module Blocked on `file://`**
- Document the required dev server command in `README.md` (e.g., `npx serve .` or `python -m http.server 8080`) as a mandatory setup step.
- Note that `app.js` is an ES module and requires an HTTP origin for both module loading and `fetch()`.

**Risk 4 — CSS Grid Browser Coverage**
- Test on current Chrome, Firefox, Safari, and Edge before marking the feature complete.
- Add `display: flex; flex-wrap: wrap;` fallback ahead of the Grid declaration in `style.css`.

**Risk 5 — Hosting Single Point of Failure**
- Enable Netlify's free CDN caching to absorb traffic spikes.
- Document GitHub Pages as a fallback deployment target.

**Risk 6 — `innerHTML` XSS Surface**
- No action required for the current static implementation.
- If the data source ever changes, refactor `createCard()` to use `document.createElement` and set properties directly rather than `innerHTML`.