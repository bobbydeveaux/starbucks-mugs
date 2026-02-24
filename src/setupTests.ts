import '@testing-library/jest-dom';

// Recharts' ResponsiveContainer uses ResizeObserver; jsdom doesn't provide it.
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
