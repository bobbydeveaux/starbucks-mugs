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
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
    css: false,
    // Only pick up TypeScript tests from src/; exclude the legacy vanilla-JS
    // app.test.js at the project root which uses its own custom test runner.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
