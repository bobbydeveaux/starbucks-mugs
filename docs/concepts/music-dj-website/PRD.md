# Product Requirements Document: Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

**Created:** 2026-03-02T15:50:33Z
**Status:** Draft

## 1. Overview

**Concept:** Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

**Description:** Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

---

## 2. Goals

- Provide DJs with real-time access to current top charting songs from major music charts (Billboard, Spotify, etc.)
- Enable random song selection from top hits to reduce decision fatigue during live events
- Deliver a fast, distraction-free UI optimized for use during active DJ sets
- Surface genre/mood filters so DJs can narrow randomization to crowd-appropriate tracks

---

## 3. Non-Goals

- This is not a music streaming or playback platform
- This is not a playlist management or library organization tool
- This is not a social or collaborative platform for multiple DJs
- This is not a music recommendation engine based on user history or ML

---

## 4. User Stories

- As a DJ, I want to see current top 100 hits so that I always have up-to-date song choices
- As a DJ, I want to randomly select a song from the charts so that I can make quick, crowd-pleasing decisions
- As a DJ, I want to filter by genre before randomizing so that the suggestion fits the event vibe
- As a DJ, I want to see song metadata (title, artist, chart position) so that I can confidently introduce tracks
- As a DJ, I want to re-roll for a new random suggestion so that I'm not locked into one result

---

## 5. Acceptance Criteria

**Chart Data Display:**
- Given the app loads, when chart data is fetched, then top hits are displayed with title, artist, and rank

**Random Selection:**
- Given chart data is loaded, when the DJ clicks "Pick Random", then one song is selected uniformly at random from the visible list

**Genre Filter:**
- Given the DJ selects a genre filter, when they click "Pick Random", then only songs matching that genre are candidates

**Re-roll:**
- Given a song has been selected, when the DJ clicks "Re-roll", then a different song is returned from the same filtered set

---

## 6. Functional Requirements

- FR-001: Fetch and display current top chart data from at least one music chart API on page load
- FR-002: Refresh chart data automatically (max 1-hour cache) to reflect current market data
- FR-003: Display each track with title, artist name, chart position, and genre tag
- FR-004: Provide a "Pick Random" button that selects one track at random from the displayed list
- FR-005: Support genre/mood filter to narrow the pool before random selection
- FR-006: Provide a "Re-roll" action to get a new random pick without changing filters
- FR-007: Highlight the currently selected track prominently on screen

---

## 7. Non-Functional Requirements

### Performance
- Chart data must load within 2 seconds on standard broadband; random selection must respond in under 100ms

### Security
- All chart API keys stored server-side; no credentials exposed to the client browser

### Scalability
- Support up to 500 concurrent users without degraded performance using cached chart responses

### Reliability
- Display a graceful fallback (last cached chart or error message) if the upstream chart API is unavailable

---

## 8. Dependencies

- Music chart API (e.g., Billboard API, Spotify Charts, or Last.fm API) for real-time top hits data
- Backend caching layer (e.g., Redis or in-memory) to limit upstream API call frequency
- Frontend framework (e.g., React or plain JS) for responsive single-page UI

---

## 9. Out of Scope

- Audio playback, previews, or streaming of any kind
- User accounts, login, or saved preferences
- Integration with DJ hardware or software (e.g., Serato, rekordbox)
- Historical chart data or trend analysis
- Mobile native app (web only)

---

## 10. Success Metrics

- 80% of sessions result in at least one "Pick Random" action (tool is actively used, not just visited)
- Chart data freshness: 95% of page loads show data no older than 1 hour
- Page load time under 2 seconds for 90th percentile of users
- Zero client-side API key exposure incidents

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers