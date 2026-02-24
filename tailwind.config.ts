import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
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
          light: '#8B2323',
          accent: '#C8A96E',
        },
      },
    },
  },
  plugins: [],
}

export default config
