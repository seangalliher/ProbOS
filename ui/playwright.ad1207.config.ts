import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'fault-visibility.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: `./test-results/ad1207-${process.pid}`,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5197',
    browserName: 'chromium',
    serviceWorkers: 'block',
    permissions: [],
    locale: 'en-US',
    timezoneId: 'UTC',
    screenshot: 'off',
    trace: 'off',
    video: 'off',
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 900 } } },
    { name: 'narrow-keyboard', use: { viewport: { width: 360, height: 780 } } },
  ],
  webServer: {
    command: 'npm run dev -- --config vite.ad1207.config.ts',
    url: 'http://127.0.0.1:5197',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
