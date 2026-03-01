/**
 * Generates a normalized image URL for a car model.
 *
 * Transforms the model name to a lowercase, hyphen-separated filename format.
 * Removes or normalizes special characters (accents, diacritics).
 * Strips the brand prefix from the model name if present.
 *
 * Transformation rules:
 * - Convert to lowercase
 * - Remove brand prefix if present (e.g., "Ferrari" from "Ferrari 488")
 * - Replace spaces with hyphens
 * - Remove accents (é → e, á → a, etc.)
 * - Keep numbers and alphanumeric characters
 * - Remove other special characters
 *
 * @param brand - The car brand (e.g., "ferrari", "lamborghini")
 * @param modelName - The full model name (e.g., "250 Testa Rossa", "Ferrari 488", "Huracán LP610-4")
 * @returns A normalized image URL path (e.g., "/images/ferrari/250-testa-rossa.jpg")
 *
 * @example
 * getCarImageUrl("ferrari", "250 Testa Rossa")
 * // Returns: "/images/ferrari/250-testa-rossa.jpg"
 *
 * @example
 * getCarImageUrl("ferrari", "Ferrari 488")
 * // Returns: "/images/ferrari/488.jpg"
 *
 * @example
 * getCarImageUrl("lamborghini", "Huracán LP610-4")
 * // Returns: "/images/lamborghini/huracan-lp610-4.jpg"
 */
export function getCarImageUrl(brand: string, modelName: string): string {
  // Step 0: Trim leading and trailing whitespace
  const trimmed = modelName.trim();

  // Step 1: Normalize accents and diacritics
  // Use NFD (Normalization Form Decomposed) to separate base characters from accents,
  // then filter out the accent marks (diacritical marks in the range \u0300-\u036f)
  const normalized = trimmed
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

  // Step 2: Convert to lowercase
  const lowercase = normalized.toLowerCase();

  // Step 3: Remove brand prefix if present (e.g., "ferrari " from "ferrari 488")
  const brandPrefix = brand.toLowerCase();
  const withoutBrand = lowercase.startsWith(brandPrefix)
    ? lowercase.slice(brandPrefix.length).trim()
    : lowercase;

  // Step 4: Replace spaces/whitespace with hyphens and remove other special characters
  // Keep alphanumeric, hyphens, and numbers
  const transformed = withoutBrand
    .replace(/\s+/g, '-') // Replace one or more whitespace with a single hyphen
    .replace(/[^a-z0-9-]/g, ''); // Remove any character that's not alphanumeric or hyphen

  // Step 5: Build and return the URL
  return `/images/${brand.toLowerCase()}/${transformed}.jpg`;
}
