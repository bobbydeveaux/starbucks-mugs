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

`mugs.json` uses a versioned envelope schema:

```json
{
  "version": "1.0",
  "mugs": [
    {
      "id": 1,
      "name": "string",
      "series": "Siren",
      "year": 2019,
      "region": "Global",
      "edition": "Limited",
      "material": "Ceramic",
      "capacity_oz": 12,
      "price_usd": 12.95,
      "image": "images/example.jpg",
      "description": "string",
      "tags": ["tag1", "tag2"]
    }
  ]
}
```

Required fields: `id`, `name`, `series`, `year`, `region`, `price_usd`, `description`, `image`, `tags`.
Optional fields: `edition`, `material`, `capacity_oz`.

---

## 4. API Contracts

No API. `fetch('./mugs.json')` returns `{ version, mugs[] }` where `mugs` contains 50+ entries across seven series: City Collection, Holiday, You Are Here, Reserve, Siren, Anniversary, and Dot Collection.

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

- **Vanilla JS over framework**: Zero build tooling needed for a 52-item static catalog.
- **JSON flat file over CMS**: Simplest data source; meets scalability needs without infrastructure cost.

---

## Appendix: PRD Reference

*(See PRD: Website Starbucks Mugs, 2026-02-24)*