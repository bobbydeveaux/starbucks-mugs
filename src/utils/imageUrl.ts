/**
 * Generates a URL path for a car image.
 *
 * Removes the brand prefix from the model name, then converts to a kebab-case
 * filename (spaces → hyphens, lowercase). Constructs a static image URL at
 * `/images/{brand}/{model-name}.jpg`.
 *
 * @param brand - The car brand (e.g., "ferrari", "lamborghini")
 * @param modelName - The full model name (e.g., "Ferrari 488", "Lamborghini Huracán")
 * @returns A URL path for the car image (e.g., "/images/ferrari/488.jpg")
 *
 * @example
 * getCarImageUrl("ferrari", "Ferrari 488")
 * // Returns: "/images/ferrari/488.jpg"
 *
 * @example
 * getCarImageUrl("lamborghini", "Lamborghini Huracán")
 * // Returns: "/images/lamborghini/huracan.jpg"
 */
export function getCarImageUrl(brand: string, modelName: string): string {
  // Trim and normalize to lowercase, removing diacritics (é → e, etc.)
  const normalized = modelName
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

  // Remove brand prefix (e.g., "ferrari " from "ferrari 488")
  const brandPrefix = brand.toLowerCase();
  let modelPart = normalized.startsWith(brandPrefix)
    ? normalized.slice(brandPrefix.length).trim()
    : normalized;

  // Replace spaces with hyphens
  const kebabCase = modelPart.replace(/\s+/g, '-');

  return `/images/${brand.toLowerCase()}/${kebabCase}.jpg`;
}
