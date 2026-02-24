# Product Requirements Document: Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

**Created:** 2026-02-24T16:10:29Z
**Status:** Draft

## 1. Overview

**Concept:** Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

**Description:** Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

---

## 2. Goals

1. Deliver the definitive drink comparison site with 30+ drinks per brand and complete nutritional data at launch.
2. Enable side-by-side comparison of Starbucks and Costa drinks covering calories, sugar, fat, protein, and caffeine.
3. Build an intuitive React UI with filtering, search, and visual nutrition indicators that load under 2 seconds.
4. Provide a visually stunning, brand-accurate design that makes health-conscious drink selection genuinely delightful.
5. Become the go-to reference for coffee lovers comparing the two biggest UK coffee chains.

---

## 3. Non-Goals

1. No ordering, purchasing, or any e-commerce functionality.
2. No user accounts, saved comparisons, or personalisation.
3. No real-time API integration with Costa or Starbucks live menus.
4. No coffee shop locator or mapping features.
5. No mobile app — responsive web only.

---

## 4. User Stories

- As a health-conscious consumer, I want to compare calorie counts side-by-side so I can choose the lower-calorie drink.
- As a coffee lover, I want to browse all drinks from both brands so I can discover new options.
- As a user, I want to select two drinks for comparison so I can see their full nutritional breakdown together.
- As a user, I want to filter by category (lattes, frappes, teas) so I can compare like-for-like.
- As a user, I want to search by drink name so I can quickly find a specific drink.
- As a user, I want visual nutrition bars so I can grasp differences at a glance without reading raw numbers.
- As a mobile user, I want a responsive layout so I can compare drinks on my phone.

---

## 5. Acceptance Criteria

**Compare two drinks:**
- Given I'm on the homepage, when I select one Starbucks and one Costa drink, then a side-by-side panel shows calories, sugar, fat, protein, and caffeine for both.

**Filter by category:**
- Given I select "Lattes" from the filter, when the list updates, then only latte drinks from both brands are shown.

**Search:**
- Given I type "Flat White" in the search box, when results appear, then both brands' matching drinks are shown.

**Visual indicators:**
- Given the comparison panel is open, when nutritional data is displayed, then each nutrient has a visual bar scaled to the higher value for instant visual comparison.

---

## 6. Functional Requirements

- **FR-001** Drink catalog: 30+ drinks per brand with name, category, size, and image placeholder.
- **FR-002** Nutritional data per drink: calories, sugar (g), total fat (g), protein (g), caffeine (mg), serving size (ml).
- **FR-003** Side-by-side comparison panel: select one drink per brand and view all nutrients together.
- **FR-004** Visual nutrition bars scaled relative to each other within the comparison view.
- **FR-005** Category filter (Hot, Iced, Blended, Tea, Other) applied across both brands simultaneously.
- **FR-006** Instant search by drink name across both brands.
- **FR-007** Brand-differentiated card design (Starbucks green / Costa red) for immediate visual identification.
- **FR-008** Responsive layout supporting desktop, tablet, and mobile viewports.

---

## 7. Non-Functional Requirements

### Performance
Page load under 2 seconds on standard broadband. Comparison panel renders in under 100ms. All data served from static JSON — no blocking API calls.

### Security
Static site with no user data collected, no authentication, and no server-side processing. No third-party trackers beyond optional analytics.

### Scalability
JSON data structured to support 200+ drinks per brand without code changes. React component architecture supports adding new brands in future.

### Reliability
99.9% uptime target via static hosting (GitHub Pages or Netlify). No runtime dependencies on external APIs.

---

## 8. Dependencies

- **React 18+** — component framework for the comparison UI.
- **Vite** — build tooling for fast development experience.
- **Tailwind CSS** — utility-first styling for brand-themed design.
- **Recharts or Chart.js** — visual nutrition bars in the comparison panel.
- **Nutritional data** — sourced manually from Costa and Starbucks official UK websites.
- **Existing modal/card pattern** — reuse interaction patterns from the Starbucks Mugs catalog as reference.

---

## 9. Out of Scope

- Ordering, delivery, or any e-commerce flow.
- User accounts, login, saved comparisons, or personalisation.
- Live menu/price sync via official APIs (data is static JSON).
- Coffee shop locator, map, or store finder.
- Multi-language support or international menu variants.
- Comparison of food items, snacks, or merchandise.

---

## 10. Success Metrics

- 30+ drinks per brand with 100% complete nutritional fields at launch.
- Comparison feature reachable within 2 clicks from the homepage.
- Lighthouse performance score ≥ 90 (page load under 2 seconds).
- WCAG AA accessibility compliance with zero critical errors.
- Visually distinctive, brand-accurate colour schemes for both chains validated by product owner.
- Qualitative bar: "best comparison website ever" — as set by the concept brief.

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers