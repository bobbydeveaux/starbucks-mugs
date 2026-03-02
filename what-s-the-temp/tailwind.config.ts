import type { Config } from 'tailwindcss'

export default {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        temp: {
          cold: '#3B82F6',    // blue-500 — cold temperatures
          cool: '#06B6D4',    // cyan-500 — cool temperatures
          warm: '#F59E0B',    // amber-500 — warm temperatures
          hot: '#EF4444',     // red-500 — hot temperatures
        },
      },
    },
  },
  plugins: [],
} satisfies Config
