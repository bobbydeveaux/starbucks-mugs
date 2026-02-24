# High-Level Design: starbucks-mugs

**Created:** 2026-02-24T15:58:39Z
**Status:** Draft

## 1. Architecture Overview

Static single-page application. All assets (HTML, CSS, JS, JSON) served as flat files with no backend or build step.

---

## 2. System Components

- `index.html`: Page shell, card grid, modal markup
- `app.js`: Fetch catalog, render cards, search/filter logic, modal handler
- `data/mugs.json`: Versioned catalog data file

---

## 3. Data Model

```json
{ "version": "1.0", "mugs": [{ "id", "name", "series", "region", "material", "price_usd", "image_url", "description" }] }
```

---

## 4. API Contracts

No API. `app.js` calls `fetch('data/mugs.json')` on load; all filtering is client-side in memory.

---

## 5. Technology Stack

### Backend
None.

### Frontend
Vanilla HTML/CSS/JS — no framework, matches existing Starbucks mugs `app.js` pattern.

### Infrastructure
GitHub Pages or any static file host.

### Data Storage
`data/mugs.json` flat file (up to 200 entries).

---

## 6. Integration Points

None. Fully self-contained static site with no external dependencies.

---

## 7. Security Architecture

Static files only. No user input persisted, no auth, no secrets, no third-party scripts.

---

## 8. Deployment Architecture

Push static files to `main`; GitHub Pages serves them automatically. No CI/CD pipeline required.

---

## 9. Scalability Strategy

Client-side JS handles up to 200 catalog entries without degradation. No server-side scaling needed.

---

## 10. Monitoring & Observability

None required. GitHub Pages provides basic uptime; browser DevTools sufficient for debugging.

---

## 11. Architectural Decisions (ADRs)

- **Vanilla JS over a framework**: Zero build tooling; consistent with existing Starbucks mugs codebase.
- **Static JSON over an API**: Satisfies no-backend requirement; catalog updated by editing one file.

---

## Appendix: PRD Reference

# Product Requirements Document: Costa Mugs

I want a website about Costa Mugs

**Created:** 2026-02-24T15:57:56Z
**Status:** Draft

## 1. Overview

**Concept:** Costa Mugs

I want a website about Costa Mugs

**Description:** Costa Mugs

I want a website about Costa Mugs

---

## 2. Goals

- Display a browsable catalog of Costa Coffee mugs with names, images, and prices
- Allow users to filter and search mugs by series, region, or material
- Provide a detail view for each mug

---

## 3. Non-Goals

- No e-commerce or purchasing functionality
- No user accounts or authentication
- No backend server or database

---

## 4. User Stories

- As a collector, I want to browse Costa mugs so that I can discover new items
- As a user, I want to search mugs by name so that I can find specific ones quickly
- As a user, I want to view mug details so that I can see full specs before buying elsewhere

---

## 5. Acceptance Criteria

- Given the page loads, when mugs are fetched, then all catalog cards render with name, image, and price
- Given a search term is entered, when typed, then only matching mugs are shown
- Given a mug card is clicked, when opened, then a modal displays full mug details

---

## 6. Functional Requirements

- FR-001: Load mug catalog from a versioned JSON file
- FR-002: Render mug cards with name, image, series, and price
- FR-003: Support text search and filter by series/region/material
- FR-004: Show a detail modal on card click

---

## 7. Non-Functional Requirements

### Performance
Page loads and renders all cards within 2 seconds on a standard connection.

### Security
Static site only; no user data collected or stored.

### Scalability
JSON catalog supports up to 200 entries without UI degradation.

### Reliability
No external API dependencies; all data served as static files.

---

## 8. Dependencies

- Vanilla JS (no framework); reuse existing `app.js` pattern from Starbucks mugs site
- Static JSON catalog file modeled on existing `mugs.json` schema

---

## 9. Out of Scope

- Purchasing, cart, or checkout flows
- User login, profiles, or wishlists
- CMS or admin interface for managing catalog data

---

## 10. Success Metrics

- All catalog mugs render correctly on page load
- Search and filter return accurate results
- Detail modal displays correct data for every mug

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers