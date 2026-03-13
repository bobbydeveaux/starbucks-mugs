/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    css: false,
    // Pick up TypeScript tests from src/ and api/.
    // Excludes the legacy vanilla-JS app.test.js which uses its own test runner.
    include: ['src/**/*.{test,spec}.{ts,tsx}', 'api/**/*.{test,spec}.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/petrol-vs-ev/costEngine.ts'],
      thresholds: {
        lines: 90,
        branches: 90,
        functions: 90,
        statements: 90,
      },
    },
  },
});
