import { defineConfig, normalizePath, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = realpathSync(fileURLToPath(new URL('.', import.meta.url)));
const candidate = realpathSync(resolve(root, '..'));
const port = Number(process.env.APPROVAL_UI_PORT);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Run via the owned approval-ui Playwright configuration.');
const sources = [
  'src/store/useStore.ts', 'src/store/capabilityApprovals.ts', 'src/store/approvalPolling.ts',
  'src/components/profile/ChatMessageRow.tsx', 'src/components/profile/InlineCapabilityApproval.tsx',
  'src/components/profile/profileTranscript.ts', 'src/components/capability/CapabilityRequestCard.tsx',
  'src/components/capability/CapabilityRequestPanel.tsx', 'src/components/BridgePanel.tsx',
  'src/components/IntentSurface.tsx', 'src/components/approvals/ApprovalsCenterPanel.tsx',
];
const sourceOrigins = Object.fromEntries(sources.map(path => [path, realpathSync(resolve(root, path))]));
for (const path of Object.values(sourceOrigins)) {
  if (!normalizePath(path).startsWith(normalizePath(root) + '/')) throw new Error('Approval UI source escaped its candidate.');
}
const virtualId = '\0virtual:approval-ui-entry';

function fixture(): Plugin {
  let verified: Record<string, unknown>;
  return {
    name: 'isolated-approval-ui',
    configResolved(config) {
      if (normalizePath(realpathSync(config.root)) !== normalizePath(root)
        || JSON.stringify(config.server.proxy) !== '{}' || config.server.host !== '127.0.0.1'
        || config.server.port !== port || !config.server.strictPort) {
        throw new Error('Final approval UI Vite configuration is not isolated.');
      }
      verified = { candidate, root, pid: process.pid, proxy: config.server.proxy, strictPort: config.server.strictPort,
        host: config.server.host, port: config.server.port, sourceOrigins };
    },
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const path = request.url?.split('?')[0];
        if (path === '/__approval_ui__/config') {
          response.setHeader('Content-Type', 'application/json');
          response.end(JSON.stringify(verified));
          return;
        }
        if (path !== '/approval-ui') { next(); return; }
        response.setHeader('Content-Type', 'text/html');
        response.end(await server.transformIndexHtml('/approval-ui', `<!doctype html>
          <html><head><title>Isolated approval UI</title></head>
          <body style="margin:0;background:#0a0a12;color:#e0dcd4;font-family:monospace">
          <div id="root"></div><script type="module" src="/@id/__x00__virtual:approval-ui-entry"></script></body></html>`));
      });
    },
    resolveId(id) { if (id === 'virtual:approval-ui-entry' || id === virtualId) return virtualId; },
    load(id) {
      if (id !== virtualId) return;
      // Test composition, not replacement UI: all authority, hydration, cards,
      // Bridge rows, modal keyboard behavior and the badge are production modules.
      return `
        import React, { useEffect, useState } from 'react';
        import { createRoot } from 'react-dom/client';
        import { useStore } from '/src/store/useStore.ts';
        import { acquireApprovalPolling } from '/src/store/approvalPolling.ts';
        import { loadThreadMessages } from '/src/components/profile/profileTranscript.ts';
        import { ChatMessageRow } from '/src/components/profile/ChatMessageRow.tsx';
        import { IntentSurface } from '/src/components/IntentSurface.tsx';
        import { ApprovalsCenterPanel } from '/src/components/approvals/ApprovalsCenterPanel.tsx';
        const h = React.createElement;
        const params = new URLSearchParams(location.search);
        const threadId = params.get('thread');
        const agentId = params.get('agent');
        if (!threadId || !agentId) throw new Error('Canonical fixture thread and agent are required');
        const empty = [];
        function reconnect() {
          const before = useStore.getState().liveRepairEpoch;
          useStore.getState().handleEvent({
            type: 'state_snapshot', timestamp: Date.now()/1000,
            stream: { generation: crypto.randomUUID().replace(/-/g, ''), sequence: 0 },
            data: { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 },
          });
          if (useStore.getState().liveRepairEpoch !== before + 1) throw new Error('Reconnect snapshot was not accepted');
        }
        reconnect();
        window.__approvalUi = {
          snapshot: () => {
            const state = useStore.getState();
            return { pending: state.pendingApprovals, resource: state.approvalResources.capability,
              feedback: [...state.capabilityDecisionFeedback.entries()], deciding: [...state.capabilityDecidingIds],
              messages: state.threadMessages.get(threadId), liveRepairEpoch: state.liveRepairEpoch,
              issued: state.approvalIssuedSeq, applied: state.approvalAppliedSeq };
          },
          reconnect,
        };
        function Connected() {
          const messages = useStore(state => state.threadMessages.get(threadId) ?? empty);
          useEffect(() => acquireApprovalPolling(['capability', 'skill']), []);
          useEffect(() => { void loadThreadMessages(threadId, useStore.getState().agents, useStore.getState().setThreadMessages); }, []);
          return h(React.Fragment, null,
            h('section', { 'data-testid': 'canonical-chat', 'aria-label': 'Canonical chat transcript',
              style: { margin: '70px 420px 180px 24px', minWidth: 400, maxHeight: 'calc(100vh - 260px)', overflow: 'auto' } },
              messages.map(msg => h(ChatMessageRow, { key: msg.id, msg, activeThreadId: threadId,
                hostAgentId: agentId, hostCallsign: 'Fixture host' }))),
            h(IntentSurface), h(ApprovalsCenterPanel));
        }
        function Harness() {
          const [connected, setConnected] = useState(true);
          return h(React.Fragment, null,
            h('nav', { style: { position: 'relative', zIndex: 26, padding: 12, width: 'fit-content' } },
              h('button', { onClick: reconnect }, 'Reconnect snapshot'),
              h('button', { onClick: () => setConnected(value => !value) }, connected ? 'Disconnect fixture views' : 'Reconnect fixture views')),
            connected ? h(Connected) : h('p', null, 'Fixture views disconnected'));
        }
        createRoot(document.getElementById('root')).render(h(Harness));
      `;
    },
  };
}

export default defineConfig({
  root, plugins: [react(), fixture()],
  cacheDir: 'node_modules/.vite-approval-ui',
  server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, hmr: false },
});
