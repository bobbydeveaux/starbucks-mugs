import { describe, it, expect } from 'vitest';
import { toFahrenheit, toCelsius, formatTemp } from './temperature';

describe('toFahrenheit', () => {
  it('converts 0°C to 32°F', () => {
    expect(toFahrenheit(0)).toBe(32);
  });

  it('converts 100°C to 212°F', () => {
    expect(toFahrenheit(100)).toBe(212);
  });

  it('converts -40°C to -40°F (crossover point)', () => {
    expect(toFahrenheit(-40)).toBe(-40);
  });

  it('converts 37°C (body temperature) to 98.6°F', () => {
    expect(toFahrenheit(37)).toBeCloseTo(98.6, 1);
  });

  it('converts negative temperatures correctly', () => {
    expect(toFahrenheit(-10)).toBeCloseTo(14, 1);
  });
});

describe('toCelsius', () => {
  it('converts 32°F to 0°C', () => {
    expect(toCelsius(32)).toBe(0);
  });

  it('converts 212°F to 100°C', () => {
    expect(toCelsius(212)).toBe(100);
  });

  it('converts -40°F to -40°C (crossover point)', () => {
    expect(toCelsius(-40)).toBe(-40);
  });

  it('converts negative temperatures correctly', () => {
    expect(toCelsius(14)).toBeCloseTo(-10, 1);
  });
});

describe('toFahrenheit / toCelsius round-trip', () => {
  const testValues = [0, 25, -10, 37, 100, -40, 15.5];

  testValues.forEach((celsius) => {
    it(`round-trips ${celsius}°C within 0.01°`, () => {
      const roundTripped = toCelsius(toFahrenheit(celsius));
      expect(Math.abs(roundTripped - celsius)).toBeLessThan(0.01);
    });
  });

  it('toFahrenheit and toCelsius are inverse operations for arbitrary values', () => {
    const original = 22.7;
    expect(toCelsius(toFahrenheit(original))).toBeCloseTo(original, 5);
    expect(toFahrenheit(toCelsius(toFahrenheit(original)))).toBeCloseTo(toFahrenheit(original), 5);
  });
});

describe('formatTemp', () => {
  it('formats Celsius values with °C suffix', () => {
    expect(formatTemp(26, 'C')).toBe('26°C');
  });

  it('formats Fahrenheit values with °F suffix', () => {
    expect(formatTemp(0, 'F')).toBe('32°F');
  });

  it('rounds to nearest integer for Celsius', () => {
    expect(formatTemp(25.6, 'C')).toBe('26°C');
    expect(formatTemp(25.4, 'C')).toBe('25°C');
  });

  it('rounds to nearest integer for Fahrenheit', () => {
    // 100°C = 212°F exactly
    expect(formatTemp(100, 'F')).toBe('212°F');
  });

  it('handles negative Celsius values', () => {
    expect(formatTemp(-10, 'C')).toBe('-10°C');
  });

  it('handles negative Fahrenheit values', () => {
    // -10°C = 14°F
    expect(formatTemp(-10, 'F')).toBe('14°F');
  });

  it('handles 0°C as 32°F', () => {
    expect(formatTemp(0, 'C')).toBe('0°C');
    expect(formatTemp(0, 'F')).toBe('32°F');
  });

  it('rounds fractional Fahrenheit to nearest integer', () => {
    // 37°C = 98.6°F → rounds to 99
    expect(formatTemp(37, 'F')).toBe('99°F');
  });
});
