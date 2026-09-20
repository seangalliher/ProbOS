// AD-1243 (#1236) — dedicated Playwright config for the consulted-evidence
// e2e crossing. Modeled directly on playwright.ad1174.config.ts: self-selects
// a free loopback port when not already assigned (so parallel/dynamic
// invocations never collide), owned server, reuseExistingServer:false, and
// exactly three fixed-viewport projects (desktop/compact/mobile) for the
// required real crossing. Never points at any live or personal profile.
import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';

// The config process selects once; its owned server and workers inherit these values.
if (!process.env.CONSULTED_EVIDENCE_OWNED_PORT) {
  process.env.CONSULTED_EVIDENCE_OWNED_PORT = execFileSync(process.execPath, ['-e', `
    const server = require('node:net').createServer();
    server.listen(0, '127.0.0.1', () => {
      process.stdout.write(String(server.address().port));
      server.close();
    });
  `], { encoding: 'utf8' }).trim();
  process.env.CONSULTED_EVIDENCE_OWNER = randomBytes(16).toString('hex');
}
const port = Number(process.env.CONSULTED_EVIDENCE_OWNED_PORT);
if (!Number.isInteger(port) || port < 1024 || port > 65535 || !process.env.CONSULTED_EVIDENCE_OWNER) {
  throw new Error('Consulted-evidence owned-port configuration invalid');
}

export default defineConfig({
  testDir: './e2e', testMatch: 'consulted-evidence.spec.ts',
  fullyParallel: false, workers: 1, retries: 0,
  timeout: 90_000, expect: { timeout: 20_000 },
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
    command: 'node node_modules/vite/bin/vite.js --config vite.consulted-evidence.config.ts',
    url: `http://127.0.0.1:${port}/__consulted_evidence_owner`,
    reuseExistingServer: false, timeout: 120_000,
    env: {
      CONSULTED_EVIDENCE_OWNED_PORT: String(port),
      CONSULTED_EVIDENCE_OWNER: process.env.CONSULTED_EVIDENCE_OWNER,
    },
  },
});
