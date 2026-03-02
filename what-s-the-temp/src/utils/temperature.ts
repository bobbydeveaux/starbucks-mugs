import { Unit } from '../types';

export function toFahrenheit(celsius: number): number {
  return (celsius * 9) / 5 + 32;
}

export function toCelsius(fahrenheit: number): number {
  return ((fahrenheit - 32) * 5) / 9;
}

export function formatTemp(celsius: number, unit: Unit): string {
  if (unit === 'F') {
    return `${Math.round(toFahrenheit(celsius))}°F`;
  }
  return `${Math.round(celsius)}°C`;
}
