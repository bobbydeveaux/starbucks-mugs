# High-Level Design: Find images for all the cars

**Created:** 2026-02-28T00:34:26Z
**Status:** Draft

## 1. Architecture Overview

Static file hosting architecture. Image files organized in directories by brand (Ferrari, Lamborghini) matching existing CarCard component expectations. No application logic required—purely static asset delivery via existing web infrastructure.

---

## 2. System Components

- **Image Repository**: Organized directory structure at `/images/ferrari/` and `/images/lamborghini/`
- **CarCard Component**: Existing React component renders images with lazy loading from static paths
- **Data Files**: Existing ferrari.json and lamborghini.json mapped to image locations

---

## 3. Data Model

No new data model required. Existing data structure:
- ferrari.json: Array of 47 models with name fields
- lamborghini.json: Array of 43 models with name fields
- Mapping: model name → `/images/{brand}/{model-name}.jpg`

---

## 4. API Contracts

No API required. Static file serving via HTTP GET:
- `GET /images/ferrari/{model-name}.jpg` → Image (200 OK)
- `GET /images/lamborghini/{model-name}.jpg` → Image (200 OK)
- Missing images → 404 Not Found

---

## 5. Technology Stack

### Backend
Static file serving (existing web server/CDN)

### Frontend
React CarCard component with lazy loading

### Infrastructure
Existing web server (Nginx/Apache)

### Data Storage
File system: `/public/images/` directory

---

## 6. Integration Points

- CarCard component expects images at `/images/{brand}/{model-name}.jpg`
- JSON data files: Filenames derived from model names
- Web server static file routing configuration

---

## 7. Security Architecture

- All images from public domain or properly licensed sources
- No authentication required for static serving
- Standard static file serving security (directory traversal prevention)

---

## 8. Deployment Architecture

- Copy image files to `/public/images/ferrari/` and `/public/images/lamborghini/`
- Ensure web server routes `/images/*` to static files
- No build process changes required

---

## 9. Scalability Strategy

Directory structure supports unlimited future model additions. Static file serving naturally scales with CDN distribution.

---

## 10. Monitoring & Observability

Monitor HTTP 404 errors on `/images/` paths to detect missing images. Track image load times via existing web server metrics.

---

## 11. Architectural Decisions (ADRs)

**ADR-001: Static Files vs. Database**
- Decision: Use static JPG files in organized directories
- Rationale: Simplicity, no database overhead, natural CDN caching, matches existing infrastructure

**ADR-002: Directory Structure by Brand**
- Decision: `/images/ferrari/` and `/images/lamborghini/` organization
- Rationale: Matches CarCard component expectations, supports new brands, intuitive for maintenance

**ADR-003: JPG Format Standardization**
- Decision: Standardize on JPG format
- Rationale: Existing infrastructure requirement, efficient compression, web standard, universal support

---

## Appendix: PRD Reference

*See provided PRD documentation above*