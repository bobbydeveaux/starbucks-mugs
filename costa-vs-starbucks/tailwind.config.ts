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
          light: '#1E3932',
          accent: '#CBA258',
        },
        costa: {
          DEFAULT: '#6B1E1E',
          light: '#8B2020',
          accent: '#F5A623',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
