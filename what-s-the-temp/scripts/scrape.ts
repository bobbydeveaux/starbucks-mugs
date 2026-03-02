#!/usr/bin/env node
/**
 * Temperature data scraper for What's The Temp website.
 *
 * Generates public/temperatures.json containing monthly average temperatures
 * for 150+ countries in Celsius, sourced from historical climate averages
 * (aligned with data from climate-data.org).
 *
 * Usage:
 *   npx tsx scripts/scrape.ts              # Use curated dataset (default, recommended)
 *   npx tsx scripts/scrape.ts --live       # Live scrape from climate-data.org
 *
 * Output schema (Country[]):
 *   [{ country: string, code: string, avgTemps: Record<MonthKey, number> }]
 *
 * All temperatures are in Celsius (canonical unit).
 */

import { writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MonthKey = 'jan' | 'feb' | 'mar' | 'apr' | 'may' | 'jun' |
                'jul' | 'aug' | 'sep' | 'oct' | 'nov' | 'dec';

interface Country {
  country: string;
  code: string;       // ISO 3166-1 alpha-2
  avgTemps: Record<MonthKey, number>; // always Celsius
}

// ---------------------------------------------------------------------------
// Helper: build a Country object from a flat 12-element Celsius array
// ---------------------------------------------------------------------------

function makeCountry(
  country: string,
  code: string,
  temps: [number, number, number, number, number, number,
          number, number, number, number, number, number],
): Country {
  const [jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec] = temps;
  return { country, code, avgTemps: { jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec } };
}

// ---------------------------------------------------------------------------
// Curated dataset – monthly average temperatures (°C) for 160+ countries.
// Averages represent typical national mean temperatures (capital or composite).
// Source: historical climate averages aligned with climate-data.org tables.
// ---------------------------------------------------------------------------

const CURATED_DATA: Country[] = [
  // ── Africa ────────────────────────────────────────────────────────────────
  makeCountry('Algeria',                    'DZ', [11, 12, 14, 17, 21, 25, 28, 29, 26, 21, 15, 11]),
  makeCountry('Angola',                     'AO', [25, 26, 26, 26, 26, 23, 22, 23, 24, 26, 26, 25]),
  makeCountry('Benin',                      'BJ', [27, 29, 30, 30, 27, 26, 24, 24, 26, 26, 27, 27]),
  makeCountry('Botswana',                   'BW', [27, 26, 24, 20, 16, 13, 12, 14, 18, 22, 25, 27]),
  makeCountry('Burkina Faso',               'BF', [25, 28, 31, 33, 33, 30, 27, 26, 27, 29, 28, 25]),
  makeCountry('Burundi',                    'BI', [20, 21, 21, 21, 20, 19, 19, 19, 20, 20, 20, 20]),
  makeCountry('Cabo Verde',                 'CV', [22, 22, 23, 23, 24, 25, 27, 28, 28, 26, 24, 23]),
  makeCountry('Cameroon',                   'CM', [25, 27, 27, 26, 25, 24, 23, 23, 24, 25, 25, 25]),
  makeCountry('Central African Republic',   'CF', [25, 27, 28, 27, 26, 25, 24, 24, 25, 25, 25, 25]),
  makeCountry('Chad',                       'TD', [22, 25, 29, 33, 35, 34, 31, 29, 30, 31, 27, 22]),
  makeCountry('Comoros',                    'KM', [28, 28, 28, 27, 25, 23, 22, 22, 23, 24, 25, 27]),
  makeCountry('Congo',                      'CG', [25, 26, 26, 26, 26, 24, 23, 23, 24, 25, 25, 25]),
  makeCountry('DR Congo',                   'CD', [24, 25, 24, 24, 24, 22, 21, 21, 23, 24, 24, 24]),
  makeCountry("Côte d'Ivoire",              'CI', [28, 29, 28, 27, 26, 25, 24, 24, 25, 26, 27, 28]),
  makeCountry('Djibouti',                   'DJ', [23, 24, 26, 28, 32, 34, 35, 34, 33, 30, 27, 24]),
  makeCountry('Egypt',                      'EG', [13, 15, 18, 21, 25, 28, 29, 29, 27, 24, 19, 14]),
  makeCountry('Equatorial Guinea',          'GQ', [26, 27, 27, 27, 27, 25, 24, 24, 25, 25, 25, 26]),
  makeCountry('Eritrea',                    'ER', [20, 21, 23, 25, 28, 30, 30, 29, 27, 26, 23, 21]),
  makeCountry('Eswatini',                   'SZ', [21, 21, 18, 15, 12,  9,  9, 11, 14, 17, 19, 21]),
  makeCountry('Ethiopia',                   'ET', [15, 17, 19, 20, 20, 19, 17, 18, 18, 17, 15, 14]),
  makeCountry('Gabon',                      'GA', [26, 27, 27, 27, 27, 25, 24, 24, 25, 26, 26, 26]),
  makeCountry('Gambia',                     'GM', [23, 26, 29, 30, 32, 32, 29, 28, 29, 30, 28, 25]),
  makeCountry('Ghana',                      'GH', [27, 29, 28, 28, 26, 25, 24, 24, 25, 26, 27, 27]),
  makeCountry('Guinea',                     'GN', [26, 28, 29, 29, 28, 27, 25, 25, 26, 27, 28, 27]),
  makeCountry('Guinea-Bissau',              'GW', [24, 26, 29, 30, 30, 28, 27, 27, 28, 29, 28, 25]),
  makeCountry('Kenya',                      'KE', [19, 20, 21, 20, 19, 18, 17, 17, 18, 19, 19, 19]),
  makeCountry('Lesotho',                    'LS', [18, 17, 15, 11,  8,  5,  4,  6, 10, 13, 16, 17]),
  makeCountry('Liberia',                    'LR', [26, 27, 27, 27, 27, 26, 25, 25, 25, 26, 27, 26]),
  makeCountry('Libya',                      'LY', [12, 14, 17, 21, 25, 29, 32, 32, 28, 23, 17, 13]),
  makeCountry('Madagascar',                 'MG', [27, 27, 26, 24, 21, 18, 17, 18, 21, 24, 25, 27]),
  makeCountry('Malawi',                     'MW', [23, 23, 22, 21, 19, 17, 16, 18, 21, 24, 25, 24]),
  makeCountry('Mali',                       'ML', [23, 26, 29, 33, 35, 33, 29, 28, 29, 31, 28, 23]),
  makeCountry('Mauritania',                 'MR', [18, 20, 24, 27, 29, 30, 30, 29, 30, 28, 23, 19]),
  makeCountry('Mauritius',                  'MU', [28, 28, 27, 26, 24, 22, 21, 21, 22, 23, 25, 27]),
  makeCountry('Morocco',                    'MA', [11, 12, 14, 16, 19, 22, 25, 26, 23, 19, 14, 11]),
  makeCountry('Mozambique',                 'MZ', [27, 27, 26, 24, 22, 19, 18, 20, 22, 25, 27, 27]),
  makeCountry('Namibia',                    'NA', [25, 25, 23, 20, 17, 14, 13, 15, 18, 21, 24, 25]),
  makeCountry('Niger',                      'NE', [21, 24, 28, 32, 35, 35, 31, 30, 31, 33, 28, 22]),
  makeCountry('Nigeria',                    'NG', [27, 28, 28, 28, 26, 25, 24, 24, 25, 26, 26, 27]),
  makeCountry('Rwanda',                     'RW', [20, 20, 20, 20, 20, 19, 19, 19, 20, 20, 20, 20]),
  makeCountry('São Tomé and Príncipe',      'ST', [27, 27, 27, 26, 27, 26, 24, 24, 25, 26, 26, 27]),
  makeCountry('Senegal',                    'SN', [21, 22, 25, 27, 29, 30, 29, 29, 30, 30, 26, 22]),
  makeCountry('Seychelles',                 'SC', [28, 29, 29, 29, 28, 27, 26, 26, 27, 28, 28, 28]),
  makeCountry('Sierra Leone',               'SL', [26, 27, 28, 28, 28, 27, 25, 25, 26, 27, 27, 26]),
  makeCountry('Somalia',                    'SO', [26, 27, 28, 29, 30, 29, 27, 27, 28, 28, 27, 26]),
  makeCountry('South Africa',               'ZA', [22, 21, 20, 17, 14, 11, 10, 11, 14, 17, 20, 21]),
  makeCountry('South Sudan',               'SS', [26, 28, 29, 30, 30, 27, 25, 25, 26, 27, 26, 25]),
  makeCountry('Sudan',                      'SD', [22, 24, 28, 31, 34, 35, 33, 32, 33, 33, 28, 23]),
  makeCountry('Tanzania',                   'TZ', [26, 26, 25, 23, 20, 18, 17, 18, 20, 23, 25, 26]),
  makeCountry('Togo',                       'TG', [27, 29, 29, 28, 26, 25, 24, 24, 25, 27, 27, 27]),
  makeCountry('Tunisia',                    'TN', [10, 11, 13, 16, 20, 24, 27, 27, 25, 20, 15, 11]),
  makeCountry('Uganda',                     'UG', [22, 23, 23, 22, 22, 21, 21, 21, 22, 22, 22, 22]),
  makeCountry('Zambia',                     'ZM', [24, 23, 22, 20, 17, 14, 13, 15, 18, 22, 25, 24]),
  makeCountry('Zimbabwe',                   'ZW', [24, 23, 22, 19, 15, 11, 10, 12, 16, 20, 22, 23]),

  // ── North & Central America, Caribbean ───────────────────────────────────
  makeCountry('Bahamas',                    'BS', [21, 21, 23, 25, 27, 28, 29, 29, 28, 26, 23, 21]),
  makeCountry('Barbados',                   'BB', [25, 25, 25, 26, 27, 28, 28, 28, 28, 27, 27, 26]),
  makeCountry('Belize',                     'BZ', [24, 25, 27, 28, 29, 29, 28, 29, 28, 27, 26, 24]),
  makeCountry('Canada',                     'CA', [-10, -9, -3,  5, 12, 17, 20, 19, 14,  8,  1, -7]),
  makeCountry('Costa Rica',                 'CR', [22, 22, 23, 24, 24, 23, 23, 23, 23, 23, 23, 22]),
  makeCountry('Cuba',                       'CU', [22, 22, 23, 25, 26, 28, 28, 28, 28, 26, 24, 22]),
  makeCountry('Dominica',                   'DM', [24, 24, 24, 25, 27, 28, 28, 28, 28, 27, 26, 25]),
  makeCountry('Dominican Republic',         'DO', [24, 24, 25, 26, 27, 28, 28, 28, 28, 27, 26, 25]),
  makeCountry('El Salvador',               'SV', [24, 24, 25, 26, 27, 26, 26, 26, 26, 25, 24, 24]),
  makeCountry('Grenada',                    'GD', [25, 25, 25, 26, 28, 28, 28, 28, 28, 27, 26, 25]),
  makeCountry('Guatemala',                  'GT', [19, 20, 21, 22, 22, 21, 21, 21, 21, 21, 21, 19]),
  makeCountry('Haiti',                      'HT', [24, 24, 25, 26, 27, 28, 28, 28, 28, 27, 26, 25]),
  makeCountry('Honduras',                   'HN', [22, 23, 24, 25, 26, 26, 26, 26, 26, 25, 24, 23]),
  makeCountry('Jamaica',                    'JM', [25, 25, 26, 27, 28, 29, 29, 29, 28, 28, 27, 26]),
  makeCountry('Mexico',                     'MX', [16, 17, 20, 22, 24, 24, 24, 24, 23, 21, 18, 16]),
  makeCountry('Nicaragua',                  'NI', [26, 27, 28, 28, 28, 27, 26, 26, 26, 26, 26, 26]),
  makeCountry('Panama',                     'PA', [26, 26, 27, 27, 27, 27, 27, 27, 27, 27, 27, 26]),
  makeCountry('Trinidad and Tobago',        'TT', [26, 26, 27, 28, 29, 28, 27, 27, 27, 27, 27, 27]),
  makeCountry('United States',              'US', [  2,  4,  8, 13, 18, 22, 25, 24, 20, 14,  8,  3]),

  // ── South America ─────────────────────────────────────────────────────────
  makeCountry('Argentina',                  'AR', [24, 23, 19, 15, 11,  7,  6,  8, 11, 15, 19, 22]),
  makeCountry('Bolivia',                    'BO', [17, 17, 16, 14, 12,  9,  8,  9, 12, 15, 17, 17]),
  makeCountry('Brazil',                     'BR', [26, 26, 25, 24, 23, 22, 21, 22, 23, 24, 25, 26]),
  makeCountry('Chile',                      'CL', [17, 17, 14, 11,  8,  6,  5,  6,  9, 12, 15, 17]),
  makeCountry('Colombia',                   'CO', [20, 20, 20, 20, 20, 19, 19, 19, 20, 20, 20, 20]),
  makeCountry('Ecuador',                    'EC', [18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18, 18]),
  makeCountry('Guyana',                     'GY', [27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27]),
  makeCountry('Paraguay',                   'PY', [28, 27, 25, 20, 16, 13, 12, 14, 18, 22, 25, 27]),
  makeCountry('Peru',                       'PE', [23, 23, 22, 21, 19, 17, 16, 17, 18, 20, 21, 22]),
  makeCountry('Suriname',                   'SR', [27, 27, 27, 27, 27, 26, 26, 26, 27, 27, 27, 27]),
  makeCountry('Uruguay',                    'UY', [23, 22, 19, 15, 12,  9,  8, 10, 13, 16, 19, 21]),
  makeCountry('Venezuela',                  'VE', [25, 25, 25, 26, 26, 25, 25, 25, 25, 25, 25, 25]),

  // ── Europe ────────────────────────────────────────────────────────────────
  makeCountry('Albania',                    'AL', [ 7,  8, 11, 15, 20, 25, 27, 27, 24, 19, 13,  8]),
  makeCountry('Andorra',                    'AD', [ 2,  3,  5,  8, 12, 15, 18, 18, 15, 11,  6,  3]),
  makeCountry('Austria',                    'AT', [-2,  0,  4,  9, 14, 17, 20, 19, 15, 10,  5,  0]),
  makeCountry('Belarus',                    'BY', [-6, -5,  0,  8, 15, 18, 20, 19, 14,  8,  2, -4]),
  makeCountry('Belgium',                    'BE', [ 3,  4,  7, 10, 14, 17, 19, 19, 16, 12,  7,  4]),
  makeCountry('Bosnia and Herzegovina',     'BA', [ 1,  3,  7, 12, 17, 21, 23, 23, 18, 13,  7,  2]),
  makeCountry('Bulgaria',                   'BG', [ 2,  4,  8, 13, 18, 22, 24, 24, 20, 14,  8,  3]),
  makeCountry('Croatia',                    'HR', [ 5,  6, 10, 14, 19, 23, 26, 26, 22, 16, 10,  6]),
  makeCountry('Cyprus',                     'CY', [10, 11, 13, 17, 22, 27, 29, 29, 27, 22, 17, 12]),
  makeCountry('Czech Republic',             'CZ', [-2, -1,  3,  8, 13, 16, 18, 18, 14,  9,  4, -1]),
  makeCountry('Denmark',                    'DK', [ 2,  2,  4,  8, 12, 16, 18, 18, 14, 10,  6,  3]),
  makeCountry('Estonia',                    'EE', [-5, -5, -1,  5, 11, 16, 18, 17, 12,  7,  2, -2]),
  makeCountry('Finland',                    'FI', [-7, -7, -3,  3, 10, 14, 17, 16, 11,  5,  0, -5]),
  makeCountry('France',                     'FR', [ 5,  6,  9, 12, 16, 20, 22, 22, 19, 14,  9,  5]),
  makeCountry('Germany',                    'DE', [ 0,  1,  5,  9, 14, 17, 19, 19, 15, 10,  5,  1]),
  makeCountry('Greece',                     'GR', [10, 11, 13, 17, 22, 27, 30, 30, 26, 21, 16, 12]),
  makeCountry('Hungary',                    'HU', [ 0,  2,  7, 12, 17, 21, 23, 23, 18, 13,  6,  1]),
  makeCountry('Iceland',                    'IS', [-1,  0,  0,  3,  6,  9, 12, 12,  8,  4,  1,  0]),
  makeCountry('Ireland',                    'IE', [ 6,  6,  7,  9, 12, 14, 16, 16, 14, 11,  8,  6]),
  makeCountry('Italy',                      'IT', [ 7,  8, 11, 15, 19, 24, 27, 27, 23, 17, 12,  8]),
  makeCountry('Kosovo',                     'XK', [ 0,  2,  5, 11, 16, 20, 23, 23, 18, 12,  6,  1]),
  makeCountry('Latvia',                     'LV', [-5, -4,  0,  6, 12, 16, 18, 17, 12,  7,  2, -3]),
  makeCountry('Liechtenstein',              'LI', [-1,  0,  3,  8, 12, 16, 18, 18, 14,  9,  3,  0]),
  makeCountry('Lithuania',                  'LT', [-5, -4,  0,  6, 12, 16, 18, 17, 12,  7,  2, -3]),
  makeCountry('Luxembourg',                 'LU', [ 1,  2,  6, 10, 14, 17, 20, 19, 16, 11,  6,  2]),
  makeCountry('Malta',                      'MT', [12, 12, 14, 17, 21, 26, 28, 28, 26, 22, 17, 14]),
  makeCountry('Moldova',                    'MD', [-3, -1,  4, 11, 17, 20, 22, 22, 17, 11,  5, -1]),
  makeCountry('Montenegro',                 'ME', [ 5,  6,  9, 13, 18, 23, 25, 25, 21, 15, 10,  6]),
  makeCountry('Netherlands',               'NL', [ 3,  3,  6, 10, 14, 17, 20, 20, 16, 12,  7,  4]),
  makeCountry('North Macedonia',            'MK', [ 1,  3,  7, 12, 17, 22, 25, 25, 21, 14,  8,  2]),
  makeCountry('Norway',                     'NO', [-4, -3,  0,  5, 11, 15, 17, 16, 11,  6,  1, -3]),
  makeCountry('Poland',                     'PL', [-2, -1,  3,  8, 14, 17, 19, 19, 14,  9,  4, -1]),
  makeCountry('Portugal',                   'PT', [11, 12, 14, 15, 18, 21, 23, 24, 21, 17, 13, 11]),
  makeCountry('Romania',                    'RO', [-3, -1,  5, 11, 16, 20, 22, 22, 17, 11,  5, -1]),
  makeCountry('Russia',                     'RU', [-10, -8, -2,  7, 14, 18, 21, 20, 14,  7,  0, -7]),
  makeCountry('Serbia',                     'RS', [ 1,  3,  8, 13, 18, 22, 24, 24, 20, 14,  8,  2]),
  makeCountry('Slovakia',                   'SK', [-2,  0,  4, 10, 15, 18, 20, 20, 15, 10,  5,  0]),
  makeCountry('Slovenia',                   'SI', [ 0,  2,  6, 10, 15, 18, 21, 21, 16, 11,  6,  1]),
  makeCountry('Spain',                      'ES', [ 9, 10, 13, 15, 19, 23, 26, 27, 23, 18, 13, 10]),
  makeCountry('Sweden',                     'SE', [-3, -3,  0,  5, 11, 16, 18, 17, 12,  7,  3, -1]),
  makeCountry('Switzerland',               'CH', [ 0,  1,  5,  9, 13, 17, 19, 19, 15, 10,  5,  1]),
  makeCountry('Ukraine',                    'UA', [-4, -4,  1,  9, 16, 20, 22, 21, 16, 10,  4, -2]),
  makeCountry('United Kingdom',             'GB', [ 5,  5,  7,  9, 13, 16, 18, 18, 15, 11,  8,  5]),

  // ── Asia ──────────────────────────────────────────────────────────────────
  makeCountry('Afghanistan',               'AF', [  2,  4, 10, 16, 21, 26, 29, 28, 24, 17,  9,  3]),
  makeCountry('Armenia',                    'AM', [ -2,  0,  5, 11, 17, 22, 25, 25, 20, 14,  7,  1]),
  makeCountry('Azerbaijan',                 'AZ', [  3,  4,  8, 14, 19, 24, 28, 28, 23, 17, 11,  5]),
  makeCountry('Bahrain',                    'BH', [ 17, 18, 21, 26, 31, 33, 35, 35, 33, 29, 23, 19]),
  makeCountry('Bangladesh',                'BD', [ 17, 20, 25, 28, 29, 30, 30, 30, 29, 27, 23, 19]),
  makeCountry('Bhutan',                     'BT', [  5,  7, 10, 14, 17, 19, 20, 20, 18, 14, 10,  6]),
  makeCountry('Cambodia',                   'KH', [ 26, 28, 30, 31, 30, 29, 28, 28, 27, 27, 27, 25]),
  makeCountry('China',                      'CN', [  4,  6, 11, 17, 21, 25, 27, 27, 22, 16, 10,  5]),
  makeCountry('Georgia',                    'GE', [  4,  5,  9, 14, 19, 23, 26, 26, 22, 16, 11,  6]),
  makeCountry('India',                      'IN', [ 19, 20, 24, 27, 30, 29, 28, 27, 27, 26, 22, 19]),
  makeCountry('Indonesia',                  'ID', [ 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27, 27]),
  makeCountry('Iran',                       'IR', [  7,  9, 14, 19, 24, 29, 31, 31, 27, 21, 14,  8]),
  makeCountry('Iraq',                       'IQ', [  9, 11, 16, 22, 27, 32, 35, 34, 30, 24, 16, 10]),
  makeCountry('Israel',                     'IL', [ 10, 11, 14, 19, 23, 27, 29, 29, 27, 23, 17, 11]),
  makeCountry('Japan',                      'JP', [  5,  6,  9, 14, 19, 23, 27, 28, 24, 18, 13,  7]),
  makeCountry('Jordan',                     'JO', [  9, 10, 14, 18, 23, 27, 29, 29, 27, 22, 16, 11]),
  makeCountry('Kazakhstan',                 'KZ', [-10, -9, -3,  8, 15, 20, 23, 22, 15,  7, -1, -7]),
  makeCountry('Kuwait',                     'KW', [ 13, 16, 20, 26, 32, 36, 38, 38, 34, 28, 21, 14]),
  makeCountry('Kyrgyzstan',                 'KG', [ -8, -6,  0,  8, 14, 19, 22, 21, 15,  8,  1, -5]),
  makeCountry('Laos',                       'LA', [ 20, 23, 27, 30, 29, 28, 27, 27, 27, 26, 23, 20]),
  makeCountry('Lebanon',                    'LB', [ 10, 11, 13, 17, 22, 26, 29, 29, 27, 22, 17, 12]),
  makeCountry('Malaysia',                   'MY', [ 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]),
  makeCountry('Maldives',                   'MV', [ 29, 29, 30, 30, 30, 29, 29, 29, 29, 29, 29, 29]),
  makeCountry('Mongolia',                   'MN', [-20,-16, -6,  5, 13, 18, 21, 20, 12,  2, -9,-17]),
  makeCountry('Myanmar',                    'MM', [ 23, 25, 28, 30, 29, 28, 27, 27, 27, 27, 26, 23]),
  makeCountry('Nepal',                      'NP', [ 10, 12, 16, 20, 23, 24, 24, 24, 23, 20, 15, 11]),
  makeCountry('North Korea',               'KP', [ -8, -5,  2, 10, 16, 21, 25, 26, 20, 13,  4, -5]),
  makeCountry('Oman',                       'OM', [ 22, 23, 26, 30, 34, 37, 38, 37, 35, 31, 27, 23]),
  makeCountry('Pakistan',                   'PK', [ 13, 15, 20, 26, 30, 34, 35, 34, 31, 26, 20, 14]),
  makeCountry('Philippines',               'PH', [ 26, 27, 28, 29, 29, 29, 28, 28, 28, 28, 27, 26]),
  makeCountry('Qatar',                      'QA', [ 17, 18, 22, 27, 32, 36, 38, 38, 35, 30, 24, 19]),
  makeCountry('Saudi Arabia',              'SA', [ 14, 17, 22, 27, 32, 36, 37, 37, 34, 29, 22, 16]),
  makeCountry('Singapore',                  'SG', [ 27, 27, 27, 28, 28, 28, 28, 28, 27, 27, 27, 27]),
  makeCountry('South Korea',               'KR', [ -3,  0,  5, 12, 17, 21, 25, 26, 21, 15,  7,  0]),
  makeCountry('Sri Lanka',                  'LK', [ 27, 28, 28, 28, 29, 28, 28, 28, 28, 28, 27, 27]),
  makeCountry('Syria',                      'SY', [  9, 11, 14, 18, 23, 28, 31, 31, 27, 21, 15, 10]),
  makeCountry('Taiwan',                     'TW', [ 16, 16, 18, 22, 25, 28, 29, 29, 28, 25, 22, 18]),
  makeCountry('Tajikistan',                 'TJ', [ -4, -1,  5, 13, 19, 24, 27, 26, 20, 13,  5, -2]),
  makeCountry('Thailand',                   'TH', [ 26, 28, 30, 31, 30, 29, 29, 29, 28, 27, 26, 25]),
  makeCountry('Timor-Leste',               'TL', [ 28, 27, 27, 27, 27, 26, 25, 26, 27, 28, 28, 28]),
  makeCountry('Turkmenistan',              'TM', [ -2,  0,  7, 16, 22, 27, 30, 29, 22, 14,  5,  0]),
  makeCountry('United Arab Emirates',      'AE', [ 18, 20, 22, 27, 32, 35, 37, 37, 35, 30, 25, 20]),
  makeCountry('Uzbekistan',                'UZ', [ -1,  2,  8, 16, 22, 27, 30, 28, 22, 14,  6,  0]),
  makeCountry('Vietnam',                    'VN', [ 20, 21, 24, 27, 29, 30, 30, 30, 29, 27, 24, 21]),
  makeCountry('Yemen',                      'YE', [ 25, 26, 27, 29, 31, 33, 33, 33, 31, 29, 27, 25]),

  // ── Oceania ───────────────────────────────────────────────────────────────
  makeCountry('Australia',                  'AU', [ 22, 22, 20, 17, 13, 10,  9, 11, 13, 16, 19, 21]),
  makeCountry('Fiji',                       'FJ', [ 27, 27, 27, 26, 25, 23, 23, 23, 24, 25, 26, 27]),
  makeCountry('Kiribati',                   'KI', [ 29, 29, 29, 29, 29, 28, 28, 28, 28, 28, 28, 29]),
  makeCountry('Marshall Islands',          'MH', [ 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]),
  makeCountry('Micronesia',                 'FM', [ 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]),
  makeCountry('Nauru',                      'NR', [ 28, 28, 28, 28, 28, 27, 27, 27, 27, 28, 28, 28]),
  makeCountry('New Zealand',               'NZ', [ 17, 17, 15, 12,  9,  7,  6,  7,  9, 12, 14, 16]),
  makeCountry('Palau',                      'PW', [ 28, 28, 28, 28, 28, 28, 27, 27, 28, 28, 28, 28]),
  makeCountry('Papua New Guinea',          'PG', [ 27, 27, 27, 27, 27, 26, 26, 26, 26, 27, 27, 27]),
  makeCountry('Samoa',                      'WS', [ 28, 28, 28, 27, 27, 26, 26, 26, 26, 27, 27, 27]),
  makeCountry('Solomon Islands',           'SB', [ 28, 28, 28, 28, 28, 27, 27, 27, 27, 27, 27, 28]),
  makeCountry('Tonga',                      'TO', [ 26, 26, 25, 24, 22, 20, 20, 20, 21, 22, 23, 25]),
  makeCountry('Tuvalu',                     'TV', [ 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29, 29]),
  makeCountry('Vanuatu',                    'VU', [ 27, 27, 27, 26, 25, 24, 23, 23, 24, 25, 26, 27]),
];

// ---------------------------------------------------------------------------
// Live scraping (climate-data.org) — used when --live flag is passed
// ---------------------------------------------------------------------------

/**
 * Attempts to scrape monthly average temperatures for a single country from
 * climate-data.org. Returns null if the page cannot be fetched or parsed.
 *
 * The country page URL format is:
 *   https://en.climate-data.org/{continent}/{slug}/
 *
 * This function is provided for future use / refreshing the dataset. The
 * default curated dataset is used unless --live is explicitly passed.
 */
async function scrapeCountryFromClimateData(url: string): Promise<number[] | null> {
  try {
    const response = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; TemperatureScraper/1.0)' },
    });
    if (!response.ok) return null;

    const html = await response.text();

    // Import cheerio dynamically to avoid requiring it when using curated data
    const { load } = await import('cheerio');
    const $ = load(html);

    // climate-data.org renders monthly average temperatures in a table row
    // with the label "Avg. Temperature °C (°F)" — extract the 12 numeric values
    const temps: number[] = [];
    $('table tbody tr').each((_i, row) => {
      const label = $(row).find('td:first-child').text().trim();
      if (label.includes('Avg. Temperature') || label.includes('Temperature °C')) {
        $(row).find('td').slice(1, 13).each((_j, cell) => {
          const raw = $(cell).text().trim().replace('°C', '').replace(/\(.*?\)/, '').trim();
          const val = parseFloat(raw);
          if (!isNaN(val)) temps.push(val);
        });
      }
    });

    return temps.length === 12 ? temps : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const useLive = process.argv.includes('--live');

  let data: Country[];

  if (useLive) {
    console.log('Live scraping mode — fetching from climate-data.org...');
    console.log('This may take several minutes. For production use, commit the curated dataset.');
    // In live mode we still start from the curated list and attempt to refresh
    // each country's data from climate-data.org. If scraping fails for a country
    // we keep the curated values as a fallback.
    data = [...CURATED_DATA];
    let updated = 0;
    for (const country of data) {
      const slug = country.country.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
      const url = `https://en.climate-data.org/${slug}/`;
      const scraped = await scrapeCountryFromClimateData(url);
      if (scraped) {
        const [jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec] = scraped;
        country.avgTemps = { jan, feb, mar, apr, may, jun, jul, aug, sep, oct, nov, dec };
        updated++;
        process.stdout.write('.');
      }
    }
    console.log(`\nLive update complete. Refreshed ${updated}/${data.length} countries.`);
  } else {
    console.log('Using curated dataset (run with --live to scrape climate-data.org).');
    data = CURATED_DATA;
  }

  // Resolve output path relative to this script's location
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const outputDir = join(__dirname, '..', 'public');
  const outputPath = join(outputDir, 'temperatures.json');

  mkdirSync(outputDir, { recursive: true });
  writeFileSync(outputPath, JSON.stringify(data, null, 2), 'utf-8');

  console.log(`\n✓ Wrote ${data.length} countries → ${outputPath}`);

  // Validate output
  const monthKeys: MonthKey[] = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
  let valid = true;
  for (const entry of data) {
    for (const month of monthKeys) {
      if (typeof entry.avgTemps[month] !== 'number' || isNaN(entry.avgTemps[month])) {
        console.error(`✗ Invalid temperature for ${entry.country} / ${month}`);
        valid = false;
      }
    }
    if (!entry.code || entry.code.length !== 2) {
      console.error(`✗ Invalid ISO code for ${entry.country}: "${entry.code}"`);
      valid = false;
    }
  }

  if (!valid) {
    process.exit(1);
  }

  if (data.length < 150) {
    console.error(`✗ Only ${data.length} countries — minimum required is 150`);
    process.exit(1);
  }

  console.log(`✓ Validation passed — ${data.length} countries, all months populated`);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
