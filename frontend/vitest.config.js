import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Frontend test runner. jsdom gives the components a DOM; setup.js wires up
// jest-dom matchers and resets mocks between tests.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
  },
});
