import type { Unit } from '../types';

/**
 * Converts a Celsius temperature to Fahrenheit.
 */
export function toFahrenheit(celsius: number): number {
  return (celsius * 9) / 5 + 32;
}

/**
 * Converts a Fahrenheit temperature to Celsius.
 */
export function toCelsius(fahrenheit: number): number {
  return ((fahrenheit - 32) * 5) / 9;
}

/**
 * Formats a Celsius temperature value as a display string in the requested unit.
 * The value is rounded to the nearest integer.
 *
 * @param celsius - Temperature in Celsius
 * @param unit    - 'C' or 'F'
 * @returns e.g. "26°C" or "79°F"
 */
export function formatTemp(celsius: number, unit: Unit): string {
  const value = unit === 'F' ? toFahrenheit(celsius) : celsius;
  return `${Math.round(value)}°${unit}`;
}
