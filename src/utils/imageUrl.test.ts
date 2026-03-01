import { describe, it, expect } from 'vitest';
import { getCarImageUrl } from './imageUrl';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('getCarImageUrl', () => {
  // -------------------------------------------------------------------------
  // Basic functionality
  // -------------------------------------------------------------------------

  it('constructs image URL for Ferrari model', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari 488');
    expect(result).toBe('/images/ferrari/488.jpg');
  });

  it('constructs image URL for Lamborghini model', () => {
    const result = getCarImageUrl('lamborghini', 'Lamborghini Gallardo');
    expect(result).toBe('/images/lamborghini/gallardo.jpg');
  });

  // -------------------------------------------------------------------------
  // Case normalization
  // -------------------------------------------------------------------------

  it('converts uppercase model names to lowercase', () => {
    const result = getCarImageUrl('ferrari', 'FERRARI F8');
    expect(result).toBe('/images/ferrari/f8.jpg');
  });

  it('converts mixed-case brand to lowercase', () => {
    const result = getCarImageUrl('Ferrari', 'Ferrari 488');
    expect(result).toBe('/images/ferrari/488.jpg');
  });

  it('converts mixed-case brand and model to lowercase', () => {
    const result = getCarImageUrl('Lamborghini', 'Lamborghini HURACÁN');
    expect(result).toBe('/images/lamborghini/huracan.jpg');
  });

  // -------------------------------------------------------------------------
  // Space to hyphen conversion
  // -------------------------------------------------------------------------

  it('converts spaces to hyphens in model name', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari F8 Tributo');
    expect(result).toBe('/images/ferrari/f8-tributo.jpg');
  });

  it('converts multiple consecutive spaces to single hyphen', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari  488  Pista');
    expect(result).toBe('/images/ferrari/488-pista.jpg');
  });

  it('handles leading/trailing spaces in model name', () => {
    const result = getCarImageUrl('ferrari', '  Ferrari 488  ');
    expect(result).toBe('/images/ferrari/488.jpg');
  });

  // -------------------------------------------------------------------------
  // Diacritical mark removal
  // -------------------------------------------------------------------------

  it('removes diacriticals (é → e)', () => {
    const result = getCarImageUrl('lamborghini', 'Lamborghini Huracán');
    expect(result).toBe('/images/lamborghini/huracan.jpg');
  });

  it('removes diacriticals (ò → o)', () => {
    const result = getCarImageUrl('lamborghini', 'Lamborghini Murciélago');
    expect(result).toBe('/images/lamborghini/murcielago.jpg');
  });

  it('removes multiple diacriticals', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari Élite Édition');
    expect(result).toBe('/images/ferrari/elite-edition.jpg');
  });

  // -------------------------------------------------------------------------
  // Complex combinations
  // -------------------------------------------------------------------------

  it('handles model name with spaces and diacriticals', () => {
    const result = getCarImageUrl('lamborghini', 'Lamborghini Murciélago S');
    expect(result).toBe('/images/lamborghini/murcielago-s.jpg');
  });

  it('handles full conversion: mixed case + spaces + diacriticals', () => {
    const result = getCarImageUrl('Lamborghini', 'LAMBORGHINI Murciélago LP 640');
    expect(result).toBe('/images/lamborghini/murcielago-lp-640.jpg');
  });

  // -------------------------------------------------------------------------
  // Edge cases
  // -------------------------------------------------------------------------

  it('handles single-word model names', () => {
    const result = getCarImageUrl('ferrari', 'Testarossa');
    expect(result).toBe('/images/ferrari/testarossa.jpg');
  });

  it('handles numeric model names', () => {
    const result = getCarImageUrl('ferrari', '458 Italia');
    expect(result).toBe('/images/ferrari/458-italia.jpg');
  });

  it('handles brand name in model string (redundant but valid)', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari 488');
    expect(result).toBe('/images/ferrari/488.jpg');
  });

  it('handles empty-like input (edge case)', () => {
    const result = getCarImageUrl('ferrari', '   ');
    // Trimming spaces results in empty string
    expect(result).toBe('/images/ferrari/.jpg');
  });

  // -------------------------------------------------------------------------
  // URL format verification
  // -------------------------------------------------------------------------

  it('always includes /images/ prefix', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari 488');
    expect(result).toMatch(/^\/images\//);
  });

  it('always ends with .jpg extension', () => {
    const result = getCarImageUrl('lamborghini', 'Lamborghini Gallardo');
    expect(result).toMatch(/\.jpg$/);
  });

  it('includes brand in the path', () => {
    const result = getCarImageUrl('ferrari', 'Ferrari 488');
    expect(result).toMatch(/\/ferrari\//);
  });

  // -------------------------------------------------------------------------
  // Real-world examples
  // -------------------------------------------------------------------------

  it('handles real Ferrari models (examples)', () => {
    expect(getCarImageUrl('ferrari', 'Ferrari 488')).toBe(
      '/images/ferrari/488.jpg'
    );
    expect(getCarImageUrl('ferrari', 'Ferrari F8 Tributo')).toBe(
      '/images/ferrari/f8-tributo.jpg'
    );
    expect(getCarImageUrl('ferrari', 'Ferrari 458 Italia')).toBe(
      '/images/ferrari/458-italia.jpg'
    );
  });

  it('handles real Lamborghini models (examples)', () => {
    expect(getCarImageUrl('lamborghini', 'Lamborghini Gallardo')).toBe(
      '/images/lamborghini/gallardo.jpg'
    );
    expect(getCarImageUrl('lamborghini', 'Lamborghini Huracán')).toBe(
      '/images/lamborghini/huracan.jpg'
    );
    expect(getCarImageUrl('lamborghini', 'Lamborghini Murciélago')).toBe(
      '/images/lamborghini/murcielago.jpg'
    );
  });
});
