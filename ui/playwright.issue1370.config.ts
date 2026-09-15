import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'agent-telemetry.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  outputDir: './test-results/issue1370',
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5187',
    browserName: 'chromium',
    serviceWorkers: 'block',
    permissions: [],
    locale: 'en-US',
    timezoneId: 'UTC',
    deviceScaleFactor: 1,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 430, height: 932 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'npm run dev -- --config vite.issue1370.config.ts',
    url: 'http://127.0.0.1:5187',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});