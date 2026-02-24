# Product Requirements Document: Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

**Created:** 2026-02-24T19:36:37Z
**Status:** Draft

## 1. Overview

**Concept:** Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

**Description:** Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

---

## 2. Goals

1. Catalog every Ferrari and Lamborghini production model from both brands' full histories with accurate specs.
2. Enable head-to-head comparison of any Ferrari vs any Lambo via top-trump-style stat cards.
3. Surface era-matched rivals (e.g. 1970s Ferrari vs 1970s Lambo) so users can explore historical matchups.
4. Deliver a visually stunning, brand-authentic design that feels premium and enthusiast-grade.
5. Achieve fast page loads so the full model catalog is browsable without frustration.

---

## 3. Non-Goals

1. No user accounts, logins, or saved comparisons in this version.
2. No real-time pricing, market data, or auction integrations.
3. No video or 3D model rendering — static imagery only.
4. No coverage of non-production concept cars, one-offs, or racing-only variants.
5. No mobile-native app — responsive web only.

---

## 4. User Stories

1. As a car enthusiast, I want to browse all Ferrari models by decade so I can explore the brand's full history.
2. As a car enthusiast, I want to browse all Lamborghini models by decade so I can see the brand's evolution.
3. As a user, I want to select one Ferrari and one Lambo and see their stats side by side so I can decide which wins.
4. As a user, I want to filter cars by era so I can find period-correct rivals.
5. As a user, I want to view a car's full stat card (HP, torque, 0–60, top speed, year, engine) at a glance.
6. As a user, I want an era-matched suggestion so the site shows me the Lambo rival to a chosen Ferrari automatically.
7. As a user, I want to search by model name so I can jump directly to a specific car.

---

## 5. Acceptance Criteria

**Browse catalog:**
- Given I open the site, when I select Ferrari or Lamborghini, then I see all models listed chronologically with card thumbnails.

**Head-to-head comparison:**
- Given I have selected one car from each brand, when I click Compare, then a side-by-side stat panel shows all key metrics with visual win/lose highlights per stat.

**Era filter:**
- Given I apply a decade filter (e.g. 1980s), when the filter is active, then only cars from that decade appear in both brand catalogs.

**Search:**
- Given I type a model name in the search box, when results appear, then only matching cards are shown within 300 ms.

---

## 6. Functional Requirements

- **FR-001** Display all Ferrari production models (1947–present) as top-trump stat cards.
- **FR-002** Display all Lamborghini production models (1963–present) as top-trump stat cards.
- **FR-003** Each card shows: model name, year, image, HP, torque, 0–60 mph, top speed, engine config.
- **FR-004** Users can select one car per brand and trigger a head-to-head comparison view.
- **FR-005** Comparison view highlights the winning stat per metric in brand colour.
- **FR-006** Decade/era filter narrows both catalogs simultaneously.
- **FR-007** Text search filters cards by model name in real time.
- **FR-008** Era-matched rival suggestion automatically pairs a selected car with its closest contemporary opponent.

---

## 7. Non-Functional Requirements

### Performance
Initial page load under 3 s on a 4G connection; catalog filtering and search respond within 300 ms client-side.

### Security
Static data only — no user input stored server-side; no third-party auth tokens; CSP headers enforced.

### Scalability
All car data served as static JSON; no backend required; CDN-deployable with zero server scaling concerns.

### Reliability
Target 99.9% uptime via static hosting (Vercel/Netlify); no runtime database dependency.

---

## 8. Dependencies

- **React 18 + TypeScript + Vite** — existing project scaffold from Costa vs Starbucks codebase.
- **Tailwind CSS** — existing styling framework; extend with Ferrari red and Lambo yellow brand tokens.
- **Static JSON data files** — one per brand, matching existing `useDrinks`-style data envelope pattern.
- **Car imagery** — Creative Commons or licensed press photos per model (self-hosted).
- **Vitest + React Testing Library** — existing CI test setup.

---

## 9. Out of Scope

- User authentication or personalisation features.
- Real-time or dynamic data APIs (pricing, availability, news).
- Video, 360° views, or AR features.
- Race/track performance data beyond standard road specs.
- Any brand other than Ferrari and Lamborghini.

---

## 10. Success Metrics

1. Full model catalogs published: ≥ 50 Ferrari models and ≥ 30 Lamborghini models at launch.
2. Head-to-head comparison flow completable end-to-end with zero console errors.
3. Lighthouse performance score ≥ 85 on mobile.
4. All stat-card unit tests passing in CI on merge to main.
5. Era filter correctly narrows both catalogs to period-correct models in manual QA.

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers