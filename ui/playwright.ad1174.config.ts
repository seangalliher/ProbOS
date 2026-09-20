import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';

// The config process selects once; its owned server and workers inherit these values.
if (!process.env.AD1174_OWNED_PORT) {
  process.env.AD1174_OWNED_PORT = execFileSync(process.execPath, ['-e', `
    const server = require('node:net').createServer();
    server.listen(0, '127.0.0.1', () => {
      process.stdout.write(String(server.address().port));
      server.close();
    });
  `], { encoding: 'utf8' }).trim();
  process.env.AD1174_OWNER = randomBytes(16).toString('hex');
}
const port = Number(process.env.AD1174_OWNED_PORT);
if (!Number.isInteger(port) || port < 1024 || port > 65535 || !process.env.AD1174_OWNER) {
  throw new Error('AD1174 owned-port configuration invalid');
}

export default defineConfig({
  testDir: './e2e', testMatch: 'live-tool-progress.spec.ts',
  fullyParallel: false, workers: 1, retries: 0,
  timeout: 90_000, expect: { timeout: 15_000 },
  reporter: [['list']], preserveOutput: 'never',
  use: {
    baseURL: `http://127.0.0.1:${port}`, browserName: 'chromium',
    serviceWorkers: 'block', permissions: [], storageState: { cookies: [], origins: [] },
    locale: 'en-US', timezoneId: 'UTC',
    screenshot: 'off', trace: 'off', video: 'off',
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'compact', use: { viewport: { width: 430, height: 932 } } },
    { name: 'mobile', use: { viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --config vite.ad1174.config.ts',
    url: `http://127.0.0.1:${port}/__ad1174_owner`,
    reuseExistingServer: false, timeout: 120_000,
    env: { AD1174_OWNED_PORT: String(port), AD1174_OWNER: process.env.AD1174_OWNER },
  },
});
