export type MonthKey = 'jan' | 'feb' | 'mar' | 'apr' | 'may' | 'jun' |
                       'jul' | 'aug' | 'sep' | 'oct' | 'nov' | 'dec';

export type Unit = 'C' | 'F';

export interface Country {
  country: string;
  code: string;
  avgTemps: Record<MonthKey, number>; // always Celsius
}

export interface FilterState {
  month: MonthKey;
  targetTemp: number;  // in selected unit
  tolerance: number;   // ± degrees, default 3
  unit: Unit;
}
