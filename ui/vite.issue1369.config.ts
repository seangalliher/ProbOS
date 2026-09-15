import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const port = Number(process.env.PROBOS_ISSUE1369_PORT ?? '5189');
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error('PROBOS_ISSUE1369_PORT must be an integer between 1024 and 65535');
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port,
    strictPort: true,
    proxy: {},
    hmr: { host: '127.0.0.1', clientPort: port },
  },
});