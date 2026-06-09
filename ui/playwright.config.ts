// AD-941: Playwright e2e harness for the chat collaboration UX.
//
// Deterministic + backend-free: each spec runs against `vite dev` (port 5173),
// seeds the Zustand store through the DEV-only `window.__store` seam
// (useStore.ts:2654), and mocks the REST surface with `page.route('**/api/**')`
// (see e2e/_helpers.ts). No live backend (:18900), no real-data mutation.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://localhost:5173', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
