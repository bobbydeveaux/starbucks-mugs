import { describe, it, expect } from 'vitest';
import { eraMatchSuggestion } from './eraMatchSuggestion';

describe('eraMatchSuggestion', () => {
  // ---------------------------------------------------------------------------
  // Decade boundary years
  // ---------------------------------------------------------------------------

  it('maps the first year of a decade to that decade', () => {
    expect(eraMatchSuggestion(1950)).toBe('1950s');
    expect(eraMatchSuggestion(1960)).toBe('1960s');
    expect(eraMatchSuggestion(1970)).toBe('1970s');
    expect(eraMatchSuggestion(1980)).toBe('1980s');
    expect(eraMatchSuggestion(1990)).toBe('1990s');
    expect(eraMatchSuggestion(2000)).toBe('2000s');
    expect(eraMatchSuggestion(2010)).toBe('2010s');
    expect(eraMatchSuggestion(2020)).toBe('2020s');
  });

  it('maps the last year of a decade to that decade', () => {
    expect(eraMatchSuggestion(1959)).toBe('1950s');
    expect(eraMatchSuggestion(1969)).toBe('1960s');
    expect(eraMatchSuggestion(1979)).toBe('1970s');
    expect(eraMatchSuggestion(1989)).toBe('1980s');
    expect(eraMatchSuggestion(1999)).toBe('1990s');
    expect(eraMatchSuggestion(2009)).toBe('2000s');
    expect(eraMatchSuggestion(2019)).toBe('2010s');
    expect(eraMatchSuggestion(2029)).toBe('2020s');
  });

  // ---------------------------------------------------------------------------
  // Mid-decade years from the actual car catalog
  // ---------------------------------------------------------------------------

  it('maps Ferrari Testarossa (1984) to 1980s', () => {
    expect(eraMatchSuggestion(1984)).toBe('1980s');
  });

  it('maps Ferrari 250 GTO (1962) to 1960s', () => {
    expect(eraMatchSuggestion(1962)).toBe('1960s');
  });

  it('maps Lamborghini 350 GT (1963) to 1960s', () => {
    expect(eraMatchSuggestion(1963)).toBe('1960s');
  });

  it('maps Ferrari F40 (1987) to 1980s', () => {
    expect(eraMatchSuggestion(1987)).toBe('1980s');
  });

  it('maps Ferrari Enzo (2002) to 2000s', () => {
    expect(eraMatchSuggestion(2002)).toBe('2000s');
  });

  it('maps Ferrari Roma (2020) to 2020s', () => {
    expect(eraMatchSuggestion(2020)).toBe('2020s');
  });

  it('maps Ferrari Roma Spider (2023) to 2020s', () => {
    expect(eraMatchSuggestion(2023)).toBe('2020s');
  });

  // ---------------------------------------------------------------------------
  // Return type and format
  // ---------------------------------------------------------------------------

  it('always returns a string', () => {
    expect(typeof eraMatchSuggestion(1984)).toBe('string');
    expect(typeof eraMatchSuggestion(2023)).toBe('string');
  });

  it('returned string ends with "s"', () => {
    expect(eraMatchSuggestion(1984)).toMatch(/s$/);
    expect(eraMatchSuggestion(2023)).toMatch(/s$/);
  });

  it('returned string contains a four-digit decade number followed by "s"', () => {
    const result = eraMatchSuggestion(1984);
    expect(result).toMatch(/^\d{4}s$/);
  });

  // ---------------------------------------------------------------------------
  // Consistency: decade derived from year matches CarModel.decade field pattern
  // ---------------------------------------------------------------------------

  it('decade number embedded in label equals Math.floor(year / 10) * 10', () => {
    const year = 1975;
    const label = eraMatchSuggestion(year);
    const expectedDecadeNum = Math.floor(year / 10) * 10;
    expect(label).toBe(`${expectedDecadeNum}s`);
  });
});
