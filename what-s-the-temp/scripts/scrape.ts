/**
 * scrape.ts – Temperature data generator for What's the Temp?
 *
 * Fetches monthly average temperature normals (°C) for 150+ countries from
 * the Open-Meteo ERA5 climate reanalysis API (https://open-meteo.com/).
 * Falls back to embedded reference data when network access is unavailable.
 *
 * Run with:   npx tsx scripts/scrape.ts
 * Output:     public/temperatures.json
 */

import { writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

interface Country {
  country: string;
  code: string;
  avgTemps: Record<string, number>;
}

// Country list: name, ISO 3166-1 alpha-2 code, representative lat/lng
const COUNTRIES: { name: string; code: string; lat: number; lng: number }[] = [
  { name: "Afghanistan", code: "AF", lat: 34.52, lng: 69.18 },
  { name: "Albania", code: "AL", lat: 41.33, lng: 19.83 },
  { name: "Algeria", code: "DZ", lat: 36.74, lng: 3.06 },
  { name: "Angola", code: "AO", lat: -8.84, lng: 13.23 },
  { name: "Argentina", code: "AR", lat: -34.61, lng: -58.37 },
  { name: "Armenia", code: "AM", lat: 40.18, lng: 44.51 },
  { name: "Australia", code: "AU", lat: -33.87, lng: 151.21 },
  { name: "Austria", code: "AT", lat: 48.21, lng: 16.37 },
  { name: "Azerbaijan", code: "AZ", lat: 40.41, lng: 49.87 },
  { name: "Bangladesh", code: "BD", lat: 23.72, lng: 90.41 },
  { name: "Belarus", code: "BY", lat: 53.9, lng: 27.57 },
  { name: "Belgium", code: "BE", lat: 50.85, lng: 4.35 },
  { name: "Belize", code: "BZ", lat: 17.25, lng: -88.77 },
  { name: "Benin", code: "BJ", lat: 6.37, lng: 2.42 },
  { name: "Bolivia", code: "BO", lat: -16.5, lng: -68.15 },
  { name: "Bosnia and Herzegovina", code: "BA", lat: 43.85, lng: 18.36 },
  { name: "Botswana", code: "BW", lat: -24.65, lng: 25.91 },
  { name: "Brazil", code: "BR", lat: -15.78, lng: -47.93 },
  { name: "Brunei", code: "BN", lat: 4.94, lng: 114.95 },
  { name: "Bulgaria", code: "BG", lat: 42.7, lng: 23.32 },
  { name: "Burkina Faso", code: "BF", lat: 12.37, lng: -1.52 },
  { name: "Burundi", code: "BI", lat: -3.38, lng: 29.36 },
  { name: "Cabo Verde", code: "CV", lat: 14.93, lng: -23.51 },
  { name: "Cambodia", code: "KH", lat: 11.56, lng: 104.92 },
  { name: "Cameroon", code: "CM", lat: 3.87, lng: 11.52 },
  { name: "Canada", code: "CA", lat: 45.42, lng: -75.69 },
  { name: "Central African Republic", code: "CF", lat: 4.36, lng: 18.56 },
  { name: "Chad", code: "TD", lat: 12.11, lng: 15.04 },
  { name: "Chile", code: "CL", lat: -33.46, lng: -70.65 },
  { name: "China", code: "CN", lat: 39.93, lng: 116.39 },
  { name: "Colombia", code: "CO", lat: 4.71, lng: -74.07 },
  { name: "Comoros", code: "KM", lat: -11.7, lng: 43.26 },
  { name: "Costa Rica", code: "CR", lat: 9.93, lng: -84.08 },
  { name: "Croatia", code: "HR", lat: 45.81, lng: 15.98 },
  { name: "Cuba", code: "CU", lat: 23.13, lng: -82.38 },
  { name: "Cyprus", code: "CY", lat: 35.17, lng: 33.37 },
  { name: "Czech Republic", code: "CZ", lat: 50.08, lng: 14.44 },
  { name: "Democratic Republic of the Congo", code: "CD", lat: -4.32, lng: 15.32 },
  { name: "Denmark", code: "DK", lat: 55.68, lng: 12.57 },
  { name: "Djibouti", code: "DJ", lat: 11.59, lng: 43.15 },
  { name: "Dominican Republic", code: "DO", lat: 18.48, lng: -69.9 },
  { name: "Ecuador", code: "EC", lat: -0.22, lng: -78.51 },
  { name: "Egypt", code: "EG", lat: 30.06, lng: 31.25 },
  { name: "El Salvador", code: "SV", lat: 13.7, lng: -89.2 },
  { name: "Equatorial Guinea", code: "GQ", lat: 3.75, lng: 8.78 },
  { name: "Eritrea", code: "ER", lat: 15.34, lng: 38.93 },
  { name: "Estonia", code: "EE", lat: 59.44, lng: 24.75 },
  { name: "Eswatini", code: "SZ", lat: -26.32, lng: 31.14 },
  { name: "Ethiopia", code: "ET", lat: 9.03, lng: 38.74 },
  { name: "Finland", code: "FI", lat: 60.17, lng: 24.94 },
  { name: "France", code: "FR", lat: 48.85, lng: 2.35 },
  { name: "Gabon", code: "GA", lat: 0.39, lng: 9.45 },
  { name: "Gambia", code: "GM", lat: 13.45, lng: -16.58 },
  { name: "Georgia", code: "GE", lat: 41.69, lng: 44.83 },
  { name: "Germany", code: "DE", lat: 52.52, lng: 13.4 },
  { name: "Ghana", code: "GH", lat: 5.56, lng: -0.2 },
  { name: "Greece", code: "GR", lat: 37.98, lng: 23.73 },
  { name: "Guatemala", code: "GT", lat: 14.64, lng: -90.51 },
  { name: "Guinea", code: "GN", lat: 9.54, lng: -13.68 },
  { name: "Guinea-Bissau", code: "GW", lat: 11.86, lng: -15.6 },
  { name: "Guyana", code: "GY", lat: 6.8, lng: -58.15 },
  { name: "Haiti", code: "HT", lat: 18.54, lng: -72.34 },
  { name: "Honduras", code: "HN", lat: 14.09, lng: -87.21 },
  { name: "Hungary", code: "HU", lat: 47.5, lng: 19.04 },
  { name: "Iceland", code: "IS", lat: 64.14, lng: -21.94 },
  { name: "India", code: "IN", lat: 28.64, lng: 77.22 },
  { name: "Indonesia", code: "ID", lat: -6.21, lng: 106.85 },
  { name: "Iran", code: "IR", lat: 35.69, lng: 51.42 },
  { name: "Iraq", code: "IQ", lat: 33.34, lng: 44.4 },
  { name: "Ireland", code: "IE", lat: 53.33, lng: -6.25 },
  { name: "Israel", code: "IL", lat: 31.77, lng: 35.23 },
  { name: "Italy", code: "IT", lat: 41.9, lng: 12.5 },
  { name: "Ivory Coast", code: "CI", lat: 6.82, lng: -5.27 },
  { name: "Jamaica", code: "JM", lat: 18.0, lng: -76.8 },
  { name: "Japan", code: "JP", lat: 35.69, lng: 139.69 },
  { name: "Jordan", code: "JO", lat: 31.95, lng: 35.93 },
  { name: "Kazakhstan", code: "KZ", lat: 51.18, lng: 71.45 },
  { name: "Kenya", code: "KE", lat: -1.29, lng: 36.82 },
  { name: "Kosovo", code: "XK", lat: 42.67, lng: 21.17 },
  { name: "Kuwait", code: "KW", lat: 29.37, lng: 47.98 },
  { name: "Kyrgyzstan", code: "KG", lat: 42.87, lng: 74.59 },
  { name: "Laos", code: "LA", lat: 17.97, lng: 102.6 },
  { name: "Latvia", code: "LV", lat: 56.95, lng: 24.11 },
  { name: "Lebanon", code: "LB", lat: 33.89, lng: 35.5 },
  { name: "Lesotho", code: "LS", lat: -29.32, lng: 27.48 },
  { name: "Liberia", code: "LR", lat: 6.3, lng: -10.8 },
  { name: "Libya", code: "LY", lat: 32.9, lng: 13.18 },
  { name: "Lithuania", code: "LT", lat: 54.69, lng: 25.28 },
  { name: "Luxembourg", code: "LU", lat: 49.61, lng: 6.13 },
  { name: "Madagascar", code: "MG", lat: -18.91, lng: 47.54 },
  { name: "Malawi", code: "MW", lat: -13.97, lng: 33.79 },
  { name: "Malaysia", code: "MY", lat: 3.15, lng: 101.7 },
  { name: "Maldives", code: "MV", lat: 4.17, lng: 73.51 },
  { name: "Mali", code: "ML", lat: 12.65, lng: -8.0 },
  { name: "Malta", code: "MT", lat: 35.9, lng: 14.51 },
  { name: "Mauritania", code: "MR", lat: 18.08, lng: -15.97 },
  { name: "Mexico", code: "MX", lat: 19.43, lng: -99.13 },
  { name: "Moldova", code: "MD", lat: 47.0, lng: 28.86 },
  { name: "Mongolia", code: "MN", lat: 47.91, lng: 106.88 },
  { name: "Montenegro", code: "ME", lat: 42.44, lng: 19.26 },
  { name: "Morocco", code: "MA", lat: 34.01, lng: -6.85 },
  { name: "Mozambique", code: "MZ", lat: -25.97, lng: 32.59 },
  { name: "Myanmar", code: "MM", lat: 19.74, lng: 96.12 },
  { name: "Namibia", code: "NA", lat: -22.56, lng: 17.08 },
  { name: "Nepal", code: "NP", lat: 27.7, lng: 85.32 },
  { name: "Netherlands", code: "NL", lat: 52.37, lng: 4.9 },
  { name: "New Zealand", code: "NZ", lat: -41.29, lng: 174.78 },
  { name: "Nicaragua", code: "NI", lat: 12.14, lng: -86.29 },
  { name: "Niger", code: "NE", lat: 13.51, lng: 2.12 },
  { name: "Nigeria", code: "NG", lat: 9.07, lng: 7.48 },
  { name: "North Korea", code: "KP", lat: 39.02, lng: 125.75 },
  { name: "North Macedonia", code: "MK", lat: 42.0, lng: 21.43 },
  { name: "Norway", code: "NO", lat: 59.91, lng: 10.75 },
  { name: "Oman", code: "OM", lat: 23.61, lng: 58.59 },
  { name: "Pakistan", code: "PK", lat: 33.72, lng: 73.04 },
  { name: "Panama", code: "PA", lat: 8.99, lng: -79.52 },
  { name: "Papua New Guinea", code: "PG", lat: -9.44, lng: 147.18 },
  { name: "Paraguay", code: "PY", lat: -25.29, lng: -57.65 },
  { name: "Peru", code: "PE", lat: -12.06, lng: -77.04 },
  { name: "Philippines", code: "PH", lat: 14.6, lng: 120.98 },
  { name: "Poland", code: "PL", lat: 52.23, lng: 21.01 },
  { name: "Portugal", code: "PT", lat: 38.72, lng: -9.14 },
  { name: "Qatar", code: "QA", lat: 25.29, lng: 51.53 },
  { name: "Republic of the Congo", code: "CG", lat: -4.27, lng: 15.28 },
  { name: "Romania", code: "RO", lat: 44.43, lng: 26.11 },
  { name: "Russia", code: "RU", lat: 55.75, lng: 37.62 },
  { name: "Rwanda", code: "RW", lat: -1.95, lng: 30.06 },
  { name: "Saudi Arabia", code: "SA", lat: 24.69, lng: 46.72 },
  { name: "Senegal", code: "SN", lat: 14.73, lng: -17.47 },
  { name: "Serbia", code: "RS", lat: 44.8, lng: 20.46 },
  { name: "Sierra Leone", code: "SL", lat: 8.49, lng: -13.23 },
  { name: "Singapore", code: "SG", lat: 1.29, lng: 103.85 },
  { name: "Slovakia", code: "SK", lat: 48.15, lng: 17.12 },
  { name: "Slovenia", code: "SI", lat: 46.05, lng: 14.51 },
  { name: "Somalia", code: "SO", lat: 2.05, lng: 45.34 },
  { name: "South Africa", code: "ZA", lat: -25.75, lng: 28.19 },
  { name: "South Korea", code: "KR", lat: 37.57, lng: 126.98 },
  { name: "South Sudan", code: "SS", lat: 4.86, lng: 31.6 },
  { name: "Spain", code: "ES", lat: 40.42, lng: -3.7 },
  { name: "Sri Lanka", code: "LK", lat: 6.93, lng: 79.85 },
  { name: "Sudan", code: "SD", lat: 15.55, lng: 32.53 },
  { name: "Suriname", code: "SR", lat: 5.87, lng: -55.17 },
  { name: "Sweden", code: "SE", lat: 59.33, lng: 18.07 },
  { name: "Switzerland", code: "CH", lat: 46.95, lng: 7.44 },
  { name: "Syria", code: "SY", lat: 33.51, lng: 36.29 },
  { name: "Taiwan", code: "TW", lat: 25.04, lng: 121.53 },
  { name: "Tajikistan", code: "TJ", lat: 38.56, lng: 68.77 },
  { name: "Tanzania", code: "TZ", lat: -6.18, lng: 35.74 },
  { name: "Thailand", code: "TH", lat: 13.75, lng: 100.52 },
  { name: "Timor-Leste", code: "TL", lat: -8.56, lng: 125.58 },
  { name: "Togo", code: "TG", lat: 6.14, lng: 1.22 },
  { name: "Trinidad and Tobago", code: "TT", lat: 10.65, lng: -61.52 },
  { name: "Tunisia", code: "TN", lat: 36.82, lng: 10.18 },
  { name: "Turkey", code: "TR", lat: 39.93, lng: 32.86 },
  { name: "Turkmenistan", code: "TM", lat: 37.95, lng: 58.38 },
  { name: "Uganda", code: "UG", lat: 0.32, lng: 32.58 },
  { name: "Ukraine", code: "UA", lat: 50.45, lng: 30.52 },
  { name: "United Arab Emirates", code: "AE", lat: 24.47, lng: 54.37 },
  { name: "United Kingdom", code: "GB", lat: 51.51, lng: -0.13 },
  { name: "United States", code: "US", lat: 38.9, lng: -77.04 },
  { name: "Uruguay", code: "UY", lat: -34.9, lng: -56.19 },
  { name: "Uzbekistan", code: "UZ", lat: 41.3, lng: 69.27 },
  { name: "Venezuela", code: "VE", lat: 10.49, lng: -66.88 },
  { name: "Vietnam", code: "VN", lat: 21.03, lng: 105.85 },
  { name: "Yemen", code: "YE", lat: 15.35, lng: 44.21 },
  { name: "Zambia", code: "ZM", lat: -15.42, lng: 28.28 },
  { name: "Zimbabwe", code: "ZW", lat: -17.83, lng: 31.05 },
];

const MONTH_KEYS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

async function fetchMonthlyTemps(lat: number, lng: number): Promise<number[] | null> {
  // Use Open-Meteo ERA5 climate API to get 30-year monthly means
  // We'll use a representative multi-year window and average by month
  const url =
    `https://archive-api.open-meteo.com/v1/archive` +
    `?latitude=${lat}&longitude=${lng}` +
    `&start_date=1991-01-01&end_date=2020-12-31` +
    `&monthly=temperature_2m_mean` +
    `&timezone=auto`;

  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
    if (!res.ok) return null;
    const data = (await res.json()) as {
      monthly?: { time?: string[]; temperature_2m_mean?: number[] };
    };
    const monthly = data.monthly;
    if (!monthly?.time || !monthly.temperature_2m_mean) return null;

    // Aggregate by month index (0=jan … 11=dec)
    const sums = new Array(12).fill(0);
    const counts = new Array(12).fill(0);
    for (let i = 0; i < monthly.time.length; i++) {
      const m = new Date(monthly.time[i]).getUTCMonth(); // 0-based
      const t = monthly.temperature_2m_mean[i];
      if (t != null && !isNaN(t)) {
        sums[m] += t;
        counts[m]++;
      }
    }
    return sums.map((s, i) => (counts[i] > 0 ? Math.round((s / counts[i]) * 10) / 10 : 0));
  } catch {
    return null;
  }
}

// Embedded reference data (used when API is unavailable)
// Monthly averages in °C for capital / representative city
const REFERENCE_TEMPS: Record<string, number[]> = {
  AF: [1, 3, 9, 15, 20, 25, 26, 25, 21, 14, 7, 2],
  AL: [5, 7, 10, 14, 18, 22, 25, 25, 21, 16, 10, 6],
  DZ: [12, 13, 15, 17, 21, 25, 28, 29, 25, 20, 16, 12],
  AO: [26, 27, 27, 27, 26, 24, 22, 23, 24, 25, 26, 26],
  AR: [24, 23, 21, 17, 13, 10, 10, 11, 13, 17, 20, 23],
  AM: [-2, 0, 6, 13, 18, 22, 26, 26, 21, 14, 7, 1],
  AU: [23, 23, 22, 19, 16, 13, 12, 13, 15, 18, 20, 22],
  AT: [1, 2, 6, 11, 16, 19, 21, 21, 17, 11, 6, 2],
  AZ: [3, 4, 8, 14, 20, 25, 28, 28, 23, 17, 11, 6],
  BD: [19, 22, 27, 29, 30, 30, 29, 29, 30, 28, 25, 21],
  BY: [-5, -4, 0, 8, 14, 18, 20, 19, 14, 7, 2, -3],
  BE: [3, 4, 7, 10, 14, 17, 19, 19, 16, 12, 7, 4],
  BZ: [23, 24, 26, 27, 28, 28, 28, 28, 27, 27, 25, 23],
  BJ: [28, 29, 29, 29, 27, 26, 25, 24, 26, 27, 28, 28],
  BO: [10, 10, 10, 10, 8, 6, 6, 7, 9, 11, 11, 10],
  BA: [-1, 1, 5, 11, 15, 19, 21, 21, 17, 11, 5, 1],
  BW: [27, 26, 23, 20, 16, 13, 12, 15, 20, 24, 26, 27],
  BR: [22, 22, 22, 21, 20, 19, 19, 21, 22, 23, 22, 22],
  BN: [27, 27, 28, 28, 28, 28, 28, 28, 28, 27, 27, 27],
  BG: [-1, 1, 5, 11, 16, 20, 23, 23, 18, 12, 5, 1],
  BF: [26, 29, 32, 34, 34, 30, 27, 27, 28, 29, 28, 26],
  BI: [23, 23, 23, 23, 22, 22, 22, 23, 23, 23, 23, 23],
  CV: [22, 21, 22, 22, 23, 25, 26, 27, 27, 27, 25, 23],
  KH: [26, 28, 30, 31, 31, 30, 29, 29, 28, 28, 27, 26],
  CM: [24, 25, 25, 24, 24, 23, 22, 22, 23, 23, 23, 23],
  CA: [-9, -8, -2, 7, 14, 18, 21, 20, 15, 8, 2, -6],
  CF: [26, 27, 28, 27, 27, 26, 25, 25, 25, 26, 26, 26],
  TD: [22, 25, 29, 33, 35, 34, 31, 29, 30, 29, 26, 22],
  CL: [21, 20, 18, 15, 12, 9, 8, 9, 11, 14, 17, 20],
  CN: [-4, -1, 5, 14, 20, 25, 27, 26, 20, 13, 4, -2],
  CO: [14, 14, 15, 15, 15, 14, 13, 13, 14, 14, 14, 14],
  KM: [27, 27, 27, 27, 26, 25, 24, 24, 25, 26, 27, 27],
  CR: [19, 19, 21, 22, 22, 21, 21, 21, 21, 21, 21, 20],
  HR: [1, 3, 7, 12, 17, 21, 23, 23, 18, 12, 6, 2],
  CU: [22, 22, 24, 25, 26, 27, 28, 28, 27, 26, 24, 23],
  CY: [10, 11, 13, 18, 23, 28, 31, 31, 27, 22, 17, 12],
  CZ: [-1, 1, 5, 10, 15, 18, 20, 20, 16, 10, 4, 0],
  CD: [26, 26, 26, 26, 25, 24, 23, 23, 24, 25, 25, 25],
  DK: [2, 2, 4, 8, 13, 17, 19, 19, 15, 11, 6, 3],
  DJ: [25, 26, 28, 30, 32, 35, 36, 35, 32, 29, 26, 25],
  DO: [24, 24, 25, 26, 27, 28, 28, 28, 28, 27, 26, 25],
  EC: [14, 14, 14, 14, 14, 13, 13, 13, 14, 14, 14, 14],
  EG: [13, 15, 18, 23, 27, 30, 32, 31, 28, 24, 19, 14],
  SV: [23, 24, 26, 27, 27, 25, 25, 25, 25, 24, 23, 23],
  GQ: [25, 25, 26, 26, 25, 24, 23, 23, 24, 25, 25, 25],
  ER: [16, 17, 20, 22, 24, 25, 22, 22, 22, 21, 19, 16],
  EE: [-3, -4, -1, 5, 11, 15, 18, 17, 12, 7, 2, -1],
  SZ: [20, 20, 18, 16, 13, 10, 10, 12, 15, 17, 18, 20],
  ET: [15, 16, 18, 19, 19, 17, 15, 15, 16, 16, 14, 14],
  FI: [-4, -5, -1, 5, 11, 15, 17, 16, 11, 6, 1, -2],
  FR: [5, 6, 9, 13, 17, 20, 22, 22, 19, 14, 9, 6],
  GA: [26, 26, 27, 27, 26, 25, 23, 23, 24, 25, 26, 26],
  GM: [23, 24, 26, 27, 28, 28, 27, 27, 28, 28, 26, 23],
  GE: [1, 3, 7, 13, 18, 22, 25, 25, 20, 14, 8, 3],
  DE: [0, 1, 5, 9, 14, 17, 19, 19, 15, 10, 5, 1],
  GH: [27, 28, 28, 27, 27, 26, 25, 25, 26, 27, 28, 28],
  GR: [10, 11, 13, 17, 22, 27, 30, 29, 25, 20, 15, 11],
  GT: [16, 17, 19, 20, 20, 19, 19, 19, 19, 18, 17, 16],
  GN: [26, 27, 28, 28, 27, 26, 25, 25, 26, 27, 27, 26],
  GW: [24, 26, 28, 29, 29, 28, 27, 27, 28, 28, 27, 24],
  GY: [27, 27, 28, 28, 28, 27, 27, 27, 28, 28, 28, 27],
  HT: [25, 25, 26, 27, 28, 29, 29, 30, 29, 28, 27, 26],
  HN: [20, 21, 23, 25, 25, 24, 24, 24, 23, 22, 21, 20],
  HU: [-1, 1, 6, 12, 17, 21, 23, 23, 18, 12, 5, 1],
  IS: [1, 1, 2, 4, 8, 11, 13, 12, 10, 6, 3, 1],
  IN: [14, 17, 23, 29, 33, 33, 30, 29, 29, 26, 20, 15],
  ID: [27, 27, 28, 28, 28, 28, 27, 27, 27, 28, 28, 27],
  IR: [3, 5, 10, 16, 22, 27, 30, 30, 25, 18, 11, 5],
  IQ: [10, 13, 17, 24, 30, 35, 38, 37, 32, 26, 17, 11],
  IE: [5, 5, 7, 9, 12, 15, 17, 17, 14, 11, 7, 5],
  IL: [9, 10, 13, 17, 22, 25, 27, 27, 25, 20, 15, 11],
  IT: [8, 9, 12, 15, 20, 24, 27, 27, 23, 18, 13, 9],
  CI: [27, 28, 28, 27, 27, 25, 24, 24, 24, 25, 26, 26],
  JM: [25, 25, 26, 27, 28, 29, 29, 30, 30, 29, 28, 26],
  JP: [5, 6, 9, 14, 19, 23, 27, 28, 24, 18, 13, 8],
  JO: [7, 9, 13, 18, 23, 27, 29, 29, 26, 21, 15, 9],
  KZ: [-11, -9, -2, 8, 16, 21, 24, 22, 16, 7, -1, -8],
  KE: [19, 20, 21, 20, 19, 18, 17, 18, 19, 20, 18, 18],
  XK: [-1, 1, 5, 11, 16, 20, 23, 22, 17, 11, 5, 0],
  KW: [13, 15, 20, 26, 32, 37, 39, 39, 35, 28, 21, 15],
  KG: [-4, -1, 6, 13, 18, 22, 25, 23, 17, 10, 3, -2],
  LA: [21, 24, 27, 29, 29, 29, 28, 28, 27, 26, 23, 20],
  LV: [-3, -3, 1, 7, 13, 17, 19, 18, 13, 8, 3, -1],
  LB: [13, 14, 16, 20, 24, 27, 30, 30, 28, 23, 19, 15],
  LS: [23, 22, 20, 17, 12, 9, 8, 11, 15, 19, 22, 23],
  LR: [27, 27, 27, 27, 27, 26, 25, 25, 26, 27, 27, 27],
  LY: [12, 14, 17, 20, 24, 27, 30, 30, 27, 22, 17, 13],
  LT: [-3, -3, 1, 8, 14, 17, 20, 19, 14, 8, 2, -1],
  LU: [2, 3, 7, 10, 15, 18, 20, 20, 17, 12, 6, 3],
  MG: [20, 20, 20, 19, 17, 15, 14, 14, 16, 18, 19, 20],
  MW: [22, 22, 22, 21, 19, 17, 16, 18, 21, 24, 24, 23],
  MY: [27, 28, 28, 28, 28, 28, 28, 28, 27, 27, 27, 27],
  MV: [28, 28, 29, 29, 30, 29, 29, 29, 29, 29, 29, 29],
  ML: [24, 27, 32, 35, 36, 33, 30, 29, 30, 31, 28, 25],
  MT: [13, 13, 15, 18, 22, 26, 29, 29, 26, 23, 19, 15],
  MR: [18, 20, 23, 26, 28, 31, 33, 33, 31, 28, 23, 19],
  MX: [14, 15, 18, 20, 20, 19, 17, 17, 17, 17, 15, 14],
  MD: [-3, -2, 3, 11, 17, 21, 24, 23, 18, 11, 4, -1],
  MN: [-20, -14, -5, 6, 14, 20, 22, 21, 13, 3, -9, -18],
  ME: [5, 7, 10, 15, 20, 25, 28, 28, 23, 16, 10, 6],
  MA: [12, 13, 15, 17, 20, 23, 26, 27, 23, 19, 15, 12],
  MZ: [26, 26, 25, 23, 21, 19, 19, 20, 22, 24, 25, 26],
  MM: [21, 24, 29, 33, 32, 29, 28, 28, 28, 27, 24, 21],
  NA: [24, 23, 22, 19, 16, 14, 13, 16, 19, 22, 23, 24],
  NP: [10, 12, 17, 21, 24, 25, 25, 25, 24, 21, 16, 12],
  NL: [4, 4, 7, 10, 14, 17, 19, 19, 17, 13, 8, 5],
  NZ: [18, 18, 17, 14, 12, 10, 9, 10, 11, 13, 15, 17],
  NI: [27, 28, 30, 31, 30, 28, 28, 28, 28, 27, 27, 27],
  NE: [23, 27, 32, 36, 38, 38, 34, 32, 33, 33, 29, 24],
  NG: [27, 29, 30, 29, 28, 26, 24, 24, 26, 27, 28, 27],
  KP: [-7, -4, 3, 11, 17, 21, 25, 25, 19, 12, 4, -4],
  MK: [1, 4, 9, 14, 19, 23, 26, 26, 21, 15, 8, 3],
  NO: [-4, -3, 1, 6, 12, 17, 19, 18, 13, 8, 2, -2],
  OM: [20, 22, 26, 30, 34, 36, 36, 34, 33, 29, 24, 21],
  PK: [7, 10, 15, 21, 26, 30, 30, 28, 26, 21, 14, 9],
  PA: [27, 28, 29, 29, 29, 28, 27, 27, 27, 27, 27, 27],
  PG: [27, 27, 27, 27, 26, 25, 25, 25, 26, 27, 27, 27],
  PY: [29, 28, 25, 22, 18, 15, 15, 17, 20, 24, 27, 29],
  PE: [22, 23, 22, 20, 18, 16, 15, 15, 16, 17, 19, 21],
  PH: [26, 27, 29, 31, 32, 30, 29, 29, 28, 28, 27, 26],
  PL: [-1, 1, 4, 10, 15, 18, 21, 20, 16, 10, 4, 0],
  PT: [12, 13, 15, 17, 20, 24, 27, 27, 24, 20, 15, 12],
  QA: [17, 19, 23, 29, 35, 38, 39, 39, 36, 31, 24, 19],
  CG: [26, 26, 27, 27, 26, 24, 22, 23, 25, 26, 26, 26],
  RO: [-2, 0, 5, 12, 18, 22, 25, 24, 19, 12, 5, 0],
  RU: [-8, -7, -2, 6, 13, 17, 20, 18, 12, 5, -1, -5],
  RW: [20, 20, 20, 20, 20, 19, 18, 19, 20, 20, 20, 20],
  SA: [15, 18, 23, 28, 34, 37, 37, 37, 34, 29, 22, 16],
  SN: [22, 22, 23, 23, 25, 27, 28, 29, 29, 29, 26, 23],
  RS: [0, 2, 7, 13, 18, 22, 24, 24, 19, 13, 6, 2],
  SL: [26, 27, 28, 28, 28, 26, 25, 25, 26, 27, 27, 26],
  SG: [26, 27, 28, 28, 28, 28, 28, 28, 28, 27, 27, 27],
  SK: [0, 2, 6, 12, 17, 21, 23, 23, 18, 12, 5, 1],
  SI: [0, 2, 6, 11, 16, 20, 22, 22, 17, 11, 5, 1],
  SO: [27, 28, 29, 30, 29, 28, 27, 27, 28, 28, 28, 27],
  ZA: [25, 24, 23, 19, 15, 12, 11, 14, 18, 21, 23, 25],
  KR: [-2, 1, 6, 13, 18, 22, 26, 27, 22, 15, 8, 1],
  SS: [27, 29, 31, 32, 31, 29, 27, 27, 28, 28, 27, 27],
  ES: [7, 9, 12, 15, 19, 24, 28, 28, 23, 17, 11, 7],
  LK: [27, 28, 29, 29, 29, 28, 28, 28, 28, 28, 28, 27],
  SD: [22, 25, 29, 33, 36, 37, 34, 33, 33, 31, 27, 23],
  SR: [27, 27, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
  SE: [-1, -1, 3, 8, 14, 18, 21, 20, 14, 9, 4, 0],
  CH: [1, 3, 7, 11, 15, 18, 21, 20, 17, 12, 6, 2],
  SY: [7, 9, 14, 19, 24, 29, 32, 32, 28, 23, 15, 9],
  TW: [17, 17, 19, 23, 26, 29, 31, 31, 28, 25, 22, 18],
  TJ: [1, 4, 10, 16, 22, 27, 30, 28, 22, 15, 7, 3],
  TZ: [22, 22, 22, 21, 20, 19, 18, 19, 21, 22, 22, 22],
  TH: [27, 29, 30, 31, 30, 29, 29, 29, 28, 28, 27, 26],
  TL: [27, 27, 28, 28, 27, 26, 25, 26, 27, 28, 28, 27],
  TG: [27, 28, 28, 27, 27, 26, 25, 24, 26, 27, 28, 27],
  TT: [24, 24, 25, 26, 27, 27, 27, 27, 27, 27, 27, 25],
  TN: [12, 13, 16, 19, 23, 27, 30, 30, 26, 21, 16, 13],
  TR: [-1, 1, 5, 11, 16, 20, 23, 23, 18, 12, 6, 2],
  TM: [1, 4, 10, 17, 23, 29, 32, 30, 24, 16, 9, 3],
  UG: [23, 23, 23, 22, 22, 22, 21, 22, 22, 22, 22, 22],
  UA: [-4, -3, 2, 10, 16, 20, 22, 22, 16, 10, 3, -2],
  AE: [18, 19, 23, 27, 32, 35, 37, 37, 34, 30, 25, 20],
  GB: [6, 6, 9, 12, 15, 18, 20, 20, 17, 14, 10, 7],
  US: [3, 4, 9, 15, 20, 25, 28, 27, 22, 16, 10, 5],
  UY: [23, 23, 21, 17, 14, 11, 11, 12, 14, 17, 19, 22],
  UZ: [1, 4, 11, 17, 23, 28, 31, 30, 24, 16, 9, 3],
  VE: [19, 19, 21, 22, 21, 20, 20, 20, 20, 20, 20, 19],
  VN: [17, 18, 21, 24, 28, 30, 30, 30, 28, 25, 22, 18],
  YE: [14, 15, 18, 21, 24, 26, 24, 23, 22, 20, 17, 14],
  ZM: [22, 22, 21, 21, 20, 18, 17, 20, 23, 26, 25, 23],
  ZW: [22, 22, 21, 19, 17, 14, 14, 16, 19, 23, 24, 23],
};

function buildFromReference(code: string): number[] | null {
  return REFERENCE_TEMPS[code] ?? null;
}

async function main() {
  const results: Country[] = [];
  let apiHits = 0;
  let refHits = 0;
  let skipped = 0;

  console.log(`Fetching temperature data for ${COUNTRIES.length} countries…`);

  for (const c of COUNTRIES) {
    // Try the Open-Meteo ERA5 archive first, fall back to embedded data
    let temps = await fetchMonthlyTemps(c.lat, c.lng);
    if (temps) {
      apiHits++;
    } else {
      temps = buildFromReference(c.code);
      if (temps) {
        refHits++;
      } else {
        console.warn(`  ⚠ No data for ${c.name} (${c.code}) – skipping`);
        skipped++;
        continue;
      }
    }

    const avgTemps: Record<string, number> = {};
    for (let i = 0; i < 12; i++) {
      avgTemps[MONTH_KEYS[i]] = temps[i];
    }

    results.push({ country: c.name, code: c.code, avgTemps });
    process.stdout.write(`  ✓ ${c.name} (${temps[0]}°C in Jan)\n`);
  }

  console.log(`\nSummary: ${results.length} countries (API: ${apiHits}, embedded: ${refHits}, skipped: ${skipped})`);

  if (results.length < 150) {
    console.error(`ERROR: Only ${results.length} entries – need at least 150. Aborting.`);
    process.exit(1);
  }

  const outPath = join(__dirname, "..", "public", "temperatures.json");
  writeFileSync(outPath, JSON.stringify(results, null, 2));
  console.log(`\nWrote ${results.length} entries to ${outPath}`);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
