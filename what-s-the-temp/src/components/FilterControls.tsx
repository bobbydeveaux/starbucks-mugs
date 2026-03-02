import { ChangeEvent } from 'react';
import { FilterState, MonthKey } from '../types';
import { toCelsius, toFahrenheit } from '../utils/temperature';

interface FilterControlsProps {
  filter: FilterState;
  onChange: (filter: FilterState) => void;
}

const MONTH_OPTIONS: { value: MonthKey; label: string }[] = [
  { value: 'jan', label: 'January' },
  { value: 'feb', label: 'February' },
  { value: 'mar', label: 'March' },
  { value: 'apr', label: 'April' },
  { value: 'may', label: 'May' },
  { value: 'jun', label: 'June' },
  { value: 'jul', label: 'July' },
  { value: 'aug', label: 'August' },
  { value: 'sep', label: 'September' },
  { value: 'oct', label: 'October' },
  { value: 'nov', label: 'November' },
  { value: 'dec', label: 'December' },
];

export function FilterControls({ filter, onChange }: FilterControlsProps) {
  const handleMonthChange = (e: ChangeEvent<HTMLSelectElement>) => {
    onChange({ ...filter, month: e.target.value as MonthKey });
  };

  const handleTargetTempChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filter, targetTemp: Number(e.target.value) });
  };

  const handleToleranceChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filter, tolerance: Number(e.target.value) });
  };

  const handleUnitToggle = (newUnit: 'C' | 'F') => {
    if (newUnit === filter.unit) return;
    const convertedTemp =
      newUnit === 'F'
        ? toFahrenheit(filter.targetTemp)
        : toCelsius(filter.targetTemp);
    onChange({ ...filter, targetTemp: convertedTemp, unit: newUnit });
  };

  return (
    <div className="bg-white rounded-lg shadow-sm p-4">
      <div className="flex flex-wrap gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="month-select" className="text-sm font-medium text-gray-700">
            Month
          </label>
          <select
            id="month-select"
            value={filter.month}
            onChange={handleMonthChange}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {MONTH_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="target-temp" className="text-sm font-medium text-gray-700">
            Target Temperature (°{filter.unit})
          </label>
          <input
            id="target-temp"
            type="number"
            step="1"
            value={filter.targetTemp}
            onChange={handleTargetTempChange}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="tolerance" className="text-sm font-medium text-gray-700">
            Tolerance (±°{filter.unit})
          </label>
          <input
            id="tolerance"
            type="number"
            min="1"
            max="15"
            step="1"
            value={filter.tolerance}
            onChange={handleToleranceChange}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-gray-700">Unit</span>
          <div className="flex rounded-md border border-gray-300 overflow-hidden">
            <button
              type="button"
              onClick={() => handleUnitToggle('C')}
              className={`px-4 py-2 text-sm font-medium ${
                filter.unit === 'C'
                  ? 'bg-blue-500 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
              aria-pressed={filter.unit === 'C'}
            >
              °C
            </button>
            <button
              type="button"
              onClick={() => handleUnitToggle('F')}
              className={`px-4 py-2 text-sm font-medium ${
                filter.unit === 'F'
                  ? 'bg-blue-500 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
              aria-pressed={filter.unit === 'F'}
            >
              °F
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
