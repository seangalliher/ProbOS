import { defineConfig, configDefaults } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
    // AD-941: the Playwright e2e specs live in ./e2e and use the @playwright/test
    // runner — keep them out of the Vitest default ``**/*.spec.ts`` glob so
    // ``vitest run`` never tries to execute them (it would error on the
    // Playwright ``test()`` API).
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
});
