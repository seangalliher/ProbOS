// AD-1243 (#1236) — dedicated, owned dynamic-loopback Vite config for the
// consulted-evidence e2e crossing. Modeled directly on vite.ad1174.config.ts
// (same owned-port/owner-identity/proxy:{} isolation shape); never reused for
// any live or personal profile.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
const port = Number(process.env.CONSULTED_EVIDENCE_OWNED_PORT);
const owner = process.env.CONSULTED_EVIDENCE_OWNER;
if (!Number.isInteger(port) || port < 1024 || port > 65535 || !owner) {
  throw new Error('Consulted-evidence config requires a newly selected owned loopback port and owner identity');
}

export default defineConfig({
  root,
  plugins: [react(), {
    name: 'consulted-evidence-isolated-owner',
    configResolved(config) {
      if (Object.keys(config.server.proxy ?? {}).length !== 0
        || config.server.host !== '127.0.0.1' || config.server.port !== port
        || config.server.strictPort !== true || config.root !== root.replace(/\\/g, '/').replace(/\/$/, '')) {
        throw new Error('Consulted-evidence resolved server isolation failed');
      }
    },
    configureServer(server) {
      server.middlewares.use('/__consulted_evidence_owner', (_request, response) => {
        response.setHeader('Content-Type', 'application/json');
        response.end(JSON.stringify({ owner, port, root: server.config.root, proxy: server.config.server.proxy }));
      });
    },
  }],
  server: {
    host: '127.0.0.1', port, strictPort: true, proxy: {}, hmr: false,
    fs: { strict: true, allow: [root] },
  },
});
