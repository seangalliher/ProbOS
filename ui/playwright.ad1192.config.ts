import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

function reserveLoopbackPort(): number {
  const value = execFileSync(process.execPath, ['-e', `
    const server = require('node:net').createServer();
    server.once('error', error => { throw error; });
    server.listen({ host: '127.0.0.1', port: 0, exclusive: true }, () => {
      process.stdout.write(String(server.address().port));
      server.close();
    });
  `], { encoding: 'utf8' }).trim();
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error('AD-1192 dynamic loopback port selection failed');
  }
  return port;
}

if (!process.env.AD1192_UI_PORT || !process.env.AD1192_BACKEND_PORT) {
  const uiPort = reserveLoopbackPort();
  let backendPort = reserveLoopbackPort();
  while (backendPort === uiPort) backendPort = reserveLoopbackPort();
  process.env.AD1192_UI_PORT = String(uiPort);
  process.env.AD1192_BACKEND_PORT = String(backendPort);
  process.env.AD1192_PROCESS_OWNER = randomBytes(16).toString('hex');
}

const uiPort = Number(process.env.AD1192_UI_PORT);
const backendPort = Number(process.env.AD1192_BACKEND_PORT);
if (
  !Number.isInteger(uiPort) || !Number.isInteger(backendPort)
  || uiPort === backendPort || !process.env.AD1192_PROCESS_OWNER
) {
  throw new Error('AD-1192 owned process configuration invalid');
}

const uiRoot = path.dirname(fileURLToPath(import.meta.url));
const candidateRoot = path.resolve(uiRoot, '..');
const selectedPython = process.env.PROBOS_TEST_PYTHON;
if (!selectedPython) {
  throw new Error('PROBOS_TEST_PYTHON must select the approved Python interpreter');
}
const pythonPath = [candidateRoot, path.join(candidateRoot, 'src')].join(path.delimiter);
const viteScript = `(async () => {
  const { createServer } = await import('vite');
  const react = (await import('@vitejs/plugin-react')).default;
  const server = await createServer({
    root: process.cwd(),
    configFile: false,
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: ${uiPort},
      strictPort: true,
      proxy: {
        '/api': { target: 'http://127.0.0.1:${backendPort}' },
        '/__ad1192__': { target: 'http://127.0.0.1:${backendPort}' }
      }
    }
  });
  await server.listen();
})().catch(error => {
  console.error(error);
  process.exit(1);
});`;
const encodedViteScript = Buffer.from(viteScript, 'utf8').toString('base64');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'ad1192-owned-steps.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  preserveOutput: 'never',
  use: {
    baseURL: `http://127.0.0.1:${uiPort}`,
    browserName: 'chromium',
    serviceWorkers: 'block',
    permissions: [],
    storageState: { cookies: [], origins: [] },
    locale: 'en-US',
    timezoneId: 'UTC',
    screenshot: 'off',
    trace: 'off',
    video: 'off',
    launchOptions: { args: ['--enable-unsafe-swiftshader'] },
  },
  webServer: [
    {
      command: `"${selectedPython}" e2e/fixtures/ad1192_backend.py --port ${backendPort}`,
      cwd: uiRoot,
      url: `http://127.0.0.1:${backendPort}/__ad1192__/state`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
        PROBOS_NATS_ENABLED: 'false',
        AD1192_PROCESS_OWNER: process.env.AD1192_PROCESS_OWNER,
      },
    },
    {
      command: `"${process.execPath}" -e "eval(Buffer.from('${encodedViteScript}','base64').toString('utf8'))"`,
      cwd: uiRoot,
      url: `http://127.0.0.1:${uiPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        AD1192_PROCESS_OWNER: process.env.AD1192_PROCESS_OWNER,
      },
    },
  ],
  metadata: {
    backendPort,
    uiPort,
    processOwner: process.env.AD1192_PROCESS_OWNER,
    candidateRoot,
  },
});
