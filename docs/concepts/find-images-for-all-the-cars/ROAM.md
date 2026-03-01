# ROAM Analysis: find-images-for-all-the-cars

**Feature Count:** 2
**Created:** 2026-02-28T00:36:22Z

## Risks

1. **Image Sourcing Availability** (High): Finding high-quality, properly licensed images for all 90 specific car models—especially rare or discontinued variants—may be difficult and time-consuming. Some models may have no publicly available images.

2. **Naming Convention Edge Cases** (Medium): Model name to filename conversion could fail on edge cases: special characters (accents in "Huracán"), multiple-word models, and inconsistencies between JSON names and real-world naming. Mismatches cause 404 errors.

3. **Copyright and Licensing Risk** (High): Using unlicensed or improperly attributed images exposes the project to legal liability. Current plan states "public domain or licensed sources" but lacks verification and documentation mechanism.

4. **Image File Size and Deployment** (Medium): Sourced images may far exceed the 200KB/image target (18MB total). Committing 18MB of binary images to git bloats the repository; CDN alternative requires additional infrastructure setup and coordination.

5. **Incomplete Model Coverage at Launch** (Medium): Acceptance criteria require 100% coverage of 90 models. If sourcing effort stalls, shipping with missing images triggers 404 errors and degrades user experience. Decision criteria for handling unavailable models is undefined.

6. **Image Format and Quality Inconsistency** (Low): Sourced images may be different formats (PNG, WEBP), resolutions, and quality levels. Batch processing to JPG may fail on edge cases (corrupted files, incompatible formats).

## Obstacles

- **Manual sourcing effort**: Finding and downloading 90 specific car images requires labor-intensive research across multiple sources with no automation available.
- **Missing image metadata**: JSON files may not specify model year/variant, creating ambiguity about which image to source for models with multiple generations.
- **No image licensing documentation system**: No current process to verify, track, and document licensing/attribution for sourced images.
- **Undefined failure criteria**: No decision documented for handling scenarios where images cannot be found for specific models.

## Assumptions

1. **All 90 models have publicly available images**: Assumes suitable images exist or are easily licensed for all 47 Ferrari and 43 Lamborghini models in the JSON files. Validation: Early sourcing phase (first 10 models) to identify unavailable models within week 1.

2. **Model name conversion is deterministic**: Assumes converting JSON names (spaces→hyphens, lowercase, handle accents) produces correct filenames matching sourced images. Validation: Automated test comparing JSON names to filesystem before sourcing all 90 images.

3. **CarCard component requires no modification**: Assumes the existing component handles `/images/{brand}/{model-name}.jpg` paths without changes and lazy-loads correctly. Validation: Verify current CarCard code and test with 1-2 manual images.

4. **Web server static routing is configured correctly**: Assumes `/images/*` routes properly to `/public/images/*` without deployment changes. Validation: Manual curl test on staging/dev environment.

5. **Sourced images need no processing**: Assumes raw sourced images will be correct dimensions, aspect ratio, and quality without manual adjustment beyond compression. Validation: Spot-check first 5 sourced images against quality standards.

## Mitigations

### Image Sourcing Availability
- **Create sourcing tracker spreadsheet** with all 90 models (name, brand, status, source URL, notes). Assign owner and set weekly review cadence.
- **Identify multiple image sources upfront**: Manufacturer websites, Wikimedia Commons, stock photo services (Unsplash, Pexels), automotive fan wikis. Test 5-10 models against each source before committing to approach.
- **Set hard sourcing deadline** with escalation at day 5: For models without images found, PM decides (use placeholder, remove from catalog, use default car silhouette).
- **Reserve 20% time buffer** in schedule for unavailable models and licensing verification delays.

### Naming Convention Edge Cases
- **Document conversion rules with explicit examples**: "Ferrari 488" → "488.jpg", "Lamborghini Huracán" → "huracan.jpg" (test accent handling). Create reference guide for all edge cases found.
- **Build automated validation before sourcing**: Write test that loads JSON, applies conversion function, checks if corresponding image file exists. Run on sample of 10 models; fix conversion logic before processing all 90.
- **Manual QA spot-check**: First person to source images reviews their file names + naming conversion test output against JSON. Sign-off before bulk import.

### Copyright and Licensing Risk
- **Create licensing checklist and spreadsheet**: For each source, document URL, license type (public domain/CC0/CC-BY/purchased), attribution requirements. No image added without license documented.
- **Restrict to explicit licenses**: Only use images marked as public domain, CC0, CC-BY, or with confirmed commercial license. Exclude ambiguous sources (e.g., unlicensed manufacturer images).
- **Legal review before launch**: Have legal/compliance review sourcing spreadsheet and licensing approach. Document approval before images go live.
- **Include attribution in metadata** (image metadata or separate file) for non-public-domain images to support future licensing disputes.

### Image File Size and Deployment
- **Establish size targets early**: Measure first 10 sourced images; extrapolate to 90. If total > 18MB, trigger decision on CDN vs. git-lfs.
- **Batch optimize images**: Use ImageMagick or similar to convert all images to JPG, compress to ≤200KB. Automate this step; verify output sample.
- **Deploy decision by day 3**: If using CDN, set up CI/CD pipeline to deploy images before source phase ends. If using git-lfs, configure repo before first commit.
- **Document storage procedure**: Add wiki page explaining where images are stored, how to update, and performance implications.

### Incomplete Model Coverage
- **Maintain real-time sourcing status**: Spreadsheet updated daily showing found/pending/unavailable count. Escalate at 80% progress if pacing slips.
- **Early identification of problem models**: Run JSON against image sources by day 2 to flag models with no obvious sources.
- **Define fallback strategy**: PM decision documented: for unavailable models, (a) use generic car placeholder image, (b) remove from JSON/catalog, or (c) skip feature launch. Document before day 1.
- **Automated missing-image detection**: E2E test generates explicit report of any missing images post-deployment, not silent passes.

### Image Format and Quality Inconsistency
- **Establish acceptance criteria upfront**: Minimum resolution (e.g., 400px width), landscape orientation, car clearly visible, no watermarks. Document with examples.
- **Automate format standardization**: Batch conversion script converts all images to JPG and resizes to standard dimensions (e.g., 600×400px). Test on sample before applying to all.
- **Quality spot-check first batch**: Manually review first 10–15 sourced images against criteria. Reject any that don't meet bar; document rejection reason and re-source.

### Testing Coverage Gaps
- **Build parameterized E2E test**: Load all 90 models from JSON, iterate over each, assert HTTP 200 for corresponding image URL. Test reports pass/fail for each model individually.
- **Automated missing-file report**: Test generates CSV of any models with missing images, making it easy to spot and fix gaps before production.
- **Parallel test execution**: Run image load tests in parallel (10–20 concurrent requests) if E2E suite becomes slow.
- **Visual regression baseline**: Take screenshot of car catalog (Ferrari and Lamborghini pages) with all 90 images; compare against future builds to catch broken images or layout shifts.