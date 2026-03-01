# Low-Level Design: Find images for all the cars

**Created:** 2026-02-28T00:35:00Z
**Status:** Draft

## 1. Implementation Overview

Store JPG images in organized directory structure matching brand and model names. Web server serves static files via HTTP GET. CarCard component loads images from constructed URLs: `/images/{brand}/{model-name}.jpg`. No database or API logic required—purely static asset delivery.

---

## 2. File Structure

- `/public/images/ferrari/` – Directory with 47 JPG files (one per model)
- `/public/images/lamborghini/` – Directory with 43 JPG files (one per model)
- Image naming: Model names from JSON converted to filenames (spaces to hyphens, lowercase)
- Example: "Ferrari 488" → `488.jpg`, "Lamborghini Huracán" → `huracan.jpg`

---

## 3. Detailed Component Designs

**CarCard Component** (`src/components/CarCard.tsx`):
- No modifications required
- Already expects image prop at `/images/{brand}/{model-name}.jpg`
- Lazy loading via existing `img` tag with `loading="lazy"` attribute
- Fallback: CSS background color if image missing

---

## 4. Database Schema Changes

Not applicable. Static file delivery only.

---

## 5. API Implementation Details

Not applicable. HTTP GET for static file serving:
- Route: `/images/ferrari/*` → `/public/images/ferrari/*`
- Route: `/images/lamborghini/*` → `/public/images/lamborghini/*`
- Status 200 if file exists, 404 if missing

---

## 6. Function Signatures

```typescript
// src/utils/imageUrl.ts
function getCarImageUrl(brand: string, modelName: string): string
  // Returns: `/images/${brand}/${modelName}.jpg`
  // Converts spaces to hyphens, lowercase
```

---

## 7. State Management

No state changes. Image URLs computed from existing data (ferrari.json, lamborghini.json) at render time.

---

## 8. Error Handling Strategy

- Missing image: 404 response; browser renders broken image
- CarCard fallback: Display brand/model name as text, grey background
- Server logs: Monitor 404 errors on `/images/` paths to detect missing files
- No user-facing error messages required

---

## 9. Test Plan

### Unit Tests
- `imageUrl.test.ts`: Verify `getCarImageUrl()` converts names correctly (spaces→hyphens, case)
- `CarCard.test.tsx`: Verify image path construction with mock data

### Integration Tests
- Load all 90 models from JSON, verify image URLs are formed correctly
- Mock HTTP server returns 200 for existing, 404 for missing

### E2E Tests
- Render FerrariPage and LamborghiniPage, verify all images load without 404s

---

## 10. Migration Strategy

1. Source 47 Ferrari images and 43 Lamborghini images
2. Convert filenames to match JSON model names (e.g., "488" for "Ferrari 488")
3. Copy to `/public/images/ferrari/` and `/public/images/lamborghini/`
4. Run E2E tests to verify all load
5. Commit images to git (or CDN if size > 100MB total)

---

## 11. Rollback Plan

Delete `/public/images/ferrari/` and `/public/images/lamborghini/` directories. CarCard component degrades gracefully to text-only view.

---

## 12. Performance Considerations

- JPEG compression: Optimize images to ≤200KB each (total ≤18MB)
- Web server caching: Set Cache-Control: `public, max-age=31536000` for static images
- Lazy loading: Existing `loading="lazy"` in CarCard prevents off-screen image downloads
- CDN: Deploy images to CDN (if available) to reduce origin requests