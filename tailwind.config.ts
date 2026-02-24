import type { Config } from 'tailwindcss'

export default {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        starbucks: {
          DEFAULT: '#00704A',
          light: '#1E9963',
          dark: '#004E32',
        },
        costa: {
          DEFAULT: '#6B1E1E',
          light: '#8B2E2E',
          dark: '#4A0E0E',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
