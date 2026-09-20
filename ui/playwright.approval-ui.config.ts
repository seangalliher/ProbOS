import { defineConfig } from '@playwright/test';
import { createServer } from 'node:net';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const ui = realpathSync(fileURLToPath(new URL('.', import.meta.url)));
const candidate = realpathSync(resolve(ui, '..'));

async function ownedPort(key: string, other?: number): Promise<number> {
  const inherited = process.env[key];
  if (inherited) {
    const port = Number(inherited);
    if (!Number.isInteger(port) || port < 1024 || port > 65535 || port === other) throw new Error(`Invalid owned port: ${key}`);
    return port;
  }
  const port = await new Promise<number>((resolvePort, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address === 'string') { server.close(); reject(new Error('No loopback port allocated')); return; }
      server.close(error => error ? reject(error) : resolvePort(address.port));
    });
  });
  if (port === other) return ownedPort(key, other);
  process.env[key] = String(port);
  return port;
}

const port = await ownedPort('APPROVAL_UI_PORT');
const bridgePort = await ownedPort('APPROVAL_UI_BRIDGE_PORT', port);
const baseURL = `http://127.0.0.1:${port}`;
const bridgeURL = `http://127.0.0.1:${bridgePort}`;
process.env.APPROVAL_UI_CANDIDATE = candidate;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'approval-ui.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  globalTimeout: 600_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  outputDir: './test-results/approval-ui',
  use: {
    baseURL, browserName: 'chromium', serviceWorkers: 'block', permissions: [],
    viewport: { width: 1440, height: 1000 }, locale: 'en-US', timezoneId: 'UTC',
    screenshot: 'off', trace: 'off', video: 'off',
  },
  webServer: [
    {
      command: `"D:/ProbOS/.venv/Scripts/python.exe" -u tests/fixtures/approval_ui_bridge.py --port ${bridgePort}`,
      cwd: candidate, url: `${bridgeURL}/__approval_ui__/health`, reuseExistingServer: false,
      timeout: 60_000, stdout: 'ignore', stderr: 'pipe',
      env: { PYTHONPATH: `${resolve(candidate, 'src')};${candidate}`, PYTHONDONTWRITEBYTECODE: '1' },
    },
    {
      command: 'npm run dev -- --config vite.approval-ui.config.ts',
      cwd: ui, url: `${baseURL}/__approval_ui__/config`, reuseExistingServer: false,
      timeout: 60_000, stdout: 'ignore', stderr: 'pipe',
      env: { APPROVAL_UI_PORT: String(port) },
    },
  ],
});
