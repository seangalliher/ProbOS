import { defineConfig } from '@playwright/test';

const port = Number(process.env.PROBOS_ISSUE1369_PORT ?? '5189');
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error('PROBOS_ISSUE1369_PORT must be an integer between 1024 and 65535');
}
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'conversation-viewport.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: './test-results/issue1369',
  reporter: [['list']],
  use: {
    baseURL: origin,
    browserName: 'chromium',
    launchOptions: { args: process.platform === 'win32' ? ['--use-angle=d3d11'] : [] },
    serviceWorkers: 'block',
    permissions: [],
    deviceScaleFactor: 1,
    locale: 'en-US',
    timezoneId: 'UTC',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 }, isMobile: false, hasTouch: false } },
  ],
  webServer: {
    command: 'npm run dev -- --config vite.issue1369.config.ts',
    url: origin,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});