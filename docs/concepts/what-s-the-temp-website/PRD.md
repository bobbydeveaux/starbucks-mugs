# Product Requirements Document: What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

**Created:** 2026-03-02T15:27:42Z
**Status:** Draft

## 1. Overview

**Concept:** What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

**Description:** What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

---

## 2. Goals

- Cover 150+ countries with monthly average temperature data stored as static JSON
- Allow users to filter destinations by target temperature and tolerance (e.g. 27°C ±3°C) for any selected month
- Render filtered results as a responsive, browsable country list with temperature context
- Provide a fast, no-backend experience with sub-second filter response times

---

## 3. Non-Goals

- No real-time or forecast weather data — static historical averages only
- No user accounts, saved searches, or personalisation
- No flight/hotel booking integration or pricing data
- No city-level granularity — country-level averages only

---

## 4. User Stories

- As a traveller, I want to select a month and temperature range so I can discover countries with my preferred climate
- As a user, I want to adjust the temperature tolerance (±°C) so I can broaden or narrow my results
- As a user, I want to switch between Celsius and Fahrenheit so I can use my preferred unit
- As a user, I want to see each result's average temperature for my chosen month so I can compare destinations
- As a user, I want results to update instantly as I change my filters so I don't wait for page reloads

---

## 5. Acceptance Criteria

**Filter by month and temperature:**
- Given a selected month and target temperature with tolerance, when the user sets the filter, then only countries whose average temperature falls within the range are shown

**Celsius/Fahrenheit toggle:**
- Given the default Celsius display, when the user toggles to Fahrenheit, then all temperatures and inputs convert correctly

**Instant results:**
- Given any filter change, when the value updates, then the results list re-renders within 300ms

---

## 6. Functional Requirements

- **FR-001** Month selector (January–December) controls the active temperature dataset
- **FR-002** Temperature target input (numeric) with ± tolerance slider/input (default ±3°C)
- **FR-003** Results list displays matching countries with their average temperature for the selected month
- **FR-004** Celsius/Fahrenheit toggle converts all values throughout the UI
- **FR-005** Static JSON dataset contains monthly average temperatures for 150+ countries
- **FR-006** No-match state displayed when zero countries meet the filter criteria

---

## 7. Non-Functional Requirements

### Performance
Page load under 2s on a standard connection; filter results render within 300ms; static JSON under 200KB

### Security
No backend, no user data collected; no external API calls at runtime; CSP headers on static host

### Scalability
Fully static deployment (Netlify/Vercel/GitHub Pages); no server scaling concerns

### Reliability
100% uptime achievable via CDN-hosted static site; no runtime dependencies on external services

---

## 8. Dependencies

- **React** — UI framework
- **Static JSON** — pre-scraped monthly average temperature data (build-time asset)
- **Temperature data source** — e.g. Wikipedia climate tables or climate-data.org (scrape at build time)
- **Static host** — Netlify, Vercel, or GitHub Pages

---

## 9. Out of Scope

- Real-time weather APIs or live data fetching
- City, region, or sub-country temperature data
- User authentication or saved preferences
- Mobile native apps
- Booking or travel planning integrations
- Precipitation, humidity, or UV index data

---

## 10. Success Metrics

- Dataset covers ≥150 countries with all 12 months populated
- Filter interaction latency ≤300ms (measured in Chrome DevTools)
- Zero runtime external API calls (verified via Network tab)
- Lighthouse performance score ≥90 on desktop

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers