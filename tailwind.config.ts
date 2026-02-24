import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        starbucks: '#00704A',
        'starbucks-light': '#D4EDDA',
        costa: '#6B1E1E',
        'costa-light': '#F8D7D7',
      },
    },
  },
  plugins: [],
} satisfies Config;
