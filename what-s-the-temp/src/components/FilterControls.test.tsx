import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { FilterControls } from './FilterControls';
import { FilterState } from '../types';

const defaultFilter: FilterState = {
  month: 'jan',
  targetTemp: 25,
  tolerance: 3,
  unit: 'C',
};

describe('FilterControls', () => {
  describe('initial render', () => {
    it('renders 12 month options', () => {
      render(<FilterControls filter={defaultFilter} onChange={vi.fn()} />);
      expect(screen.getAllByRole('option')).toHaveLength(12);
    });

    it('renders all month labels', () => {
      render(<FilterControls filter={defaultFilter} onChange={vi.fn()} />);
      const months = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ];
      months.forEach(month => {
        expect(screen.getByText(month)).toBeInTheDocument();
      });
    });

    it('shows the selected month', () => {
      render(<FilterControls filter={{ ...defaultFilter, month: 'jun' }} onChange={vi.fn()} />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      expect(select.value).toBe('jun');
    });

    it('renders C and F unit toggle buttons', () => {
      render(<FilterControls filter={defaultFilter} onChange={vi.fn()} />);
      expect(screen.getByText('°C')).toBeInTheDocument();
      expect(screen.getByText('°F')).toBeInTheDocument();
    });

    it('renders targetTemp input with correct value', () => {
      render(<FilterControls filter={defaultFilter} onChange={vi.fn()} />);
      const input = screen.getByLabelText(/target temperature/i) as HTMLInputElement;
      expect(input.value).toBe('25');
    });

    it('renders tolerance input with correct value', () => {
      render(<FilterControls filter={defaultFilter} onChange={vi.fn()} />);
      const input = screen.getByLabelText(/tolerance/i) as HTMLInputElement;
      expect(input.value).toBe('3');
    });
  });

  describe('month change', () => {
    it('calls onChange with updated month', () => {
      const onChange = vi.fn();
      render(<FilterControls filter={defaultFilter} onChange={onChange} />);
      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'jul' } });
      expect(onChange).toHaveBeenCalledWith({ ...defaultFilter, month: 'jul' });
    });
  });

  describe('targetTemp change', () => {
    it('calls onChange with updated targetTemp as a number', () => {
      const onChange = vi.fn();
      render(<FilterControls filter={defaultFilter} onChange={onChange} />);
      const input = screen.getByLabelText(/target temperature/i);
      fireEvent.change(input, { target: { value: '30' } });
      expect(onChange).toHaveBeenCalledWith({ ...defaultFilter, targetTemp: 30 });
    });
  });

  describe('tolerance change', () => {
    it('calls onChange with updated tolerance as a number', () => {
      const onChange = vi.fn();
      render(<FilterControls filter={defaultFilter} onChange={onChange} />);
      const input = screen.getByLabelText(/tolerance/i);
      fireEvent.change(input, { target: { value: '5' } });
      expect(onChange).toHaveBeenCalledWith({ ...defaultFilter, tolerance: 5 });
    });
  });

  describe('unit toggle', () => {
    it('converts targetTemp from C to F when switching to Fahrenheit', () => {
      const onChange = vi.fn();
      render(
        <FilterControls
          filter={{ ...defaultFilter, targetTemp: 25, unit: 'C' }}
          onChange={onChange}
        />
      );
      fireEvent.click(screen.getByText('°F'));
      expect(onChange).toHaveBeenCalledWith({
        ...defaultFilter,
        targetTemp: 77, // 25°C → 77°F
        unit: 'F',
      });
    });

    it('converts targetTemp from F to C when switching to Celsius', () => {
      const onChange = vi.fn();
      const filterF: FilterState = { month: 'jan', targetTemp: 77, tolerance: 3, unit: 'F' };
      render(<FilterControls filter={filterF} onChange={onChange} />);
      fireEvent.click(screen.getByText('°C'));
      const updatedFilter: FilterState = onChange.mock.calls[0][0];
      expect(updatedFilter.unit).toBe('C');
      expect(updatedFilter.month).toBe('jan');
      expect(updatedFilter.tolerance).toBe(3);
      expect(updatedFilter.targetTemp).toBeCloseTo(25, 5); // 77°F → 25°C
    });

    it('does not call onChange when clicking the already active unit', () => {
      const onChange = vi.fn();
      render(<FilterControls filter={defaultFilter} onChange={onChange} />);
      // defaultFilter.unit is 'C', click °C again
      fireEvent.click(screen.getByText('°C'));
      expect(onChange).not.toHaveBeenCalled();
    });

    it('marks the active unit button with aria-pressed=true', () => {
      render(<FilterControls filter={{ ...defaultFilter, unit: 'F' }} onChange={vi.fn()} />);
      const celsiusBtn = screen.getByText('°C').closest('button')!;
      const fahrenheitBtn = screen.getByText('°F').closest('button')!;
      expect(celsiusBtn).toHaveAttribute('aria-pressed', 'false');
      expect(fahrenheitBtn).toHaveAttribute('aria-pressed', 'true');
    });
  });
});
