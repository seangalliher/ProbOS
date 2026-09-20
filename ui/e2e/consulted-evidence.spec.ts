// AD-1243 (#1236) — real, mounted-app e2e crossing for the lazy, reply-only
// "consulted evidence" disclosure (ConsultedEvidence.tsx / useConsultedTrace.ts).
//
// This spec drives the REAL production FastAPI app (`probos.api.create_app`)
// through the parent builder's `tests/fixtures/consulted_evidence_bridge.py`
// fixture (not owned by this slice — see `consultedEvidenceBridge.ts`'s header
// for the coordination note). Every `/api/*` request from the real mounted
// UI is reverse-proxied to that real backend with wire bytes preserved
// (`arrayBuffer()` in, `Buffer` out — never `.json()` parse/reserialize), so
// this crossing consumes actual HTTP bytes rather than a synthetic seed.
//
// Isolation mirrors the established `live-tool-progress.spec.ts` /
// `IntentSurface.bf812.test.tsx` precedents: a dedicated, owned
// dynamic-loopback Vite/Playwright pair (`vite.consulted-evidence.config.ts`,
// `playwright.consulted-evidence.config.ts`), every browser guard installed
// via `page.addInitScript` before the first navigation, strict same-origin
// routing (everything else aborted), a resolved `proxy: {}` verified via the
// owner-identity health endpoint, and `reuseExistingServer: false`. Missing
// prerequisites (interpreter, fixture) are hard failures from `bridge.boot()`,
// never a silent skip.
//
// The three Playwright projects declared in playwright.consulted-evidence.config.ts
// (desktop/compact/mobile) already run every test in this file three times,
// once per fixed viewport — this is the "real mounted Desktop/Compact/Mobile
// crossing" requirement, not a separate per-shell test block.
import { test, expect, type Page } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import {
  ConsultedEvidenceBridge,
  SENSITIVE_SENTINEL, OUTPUT_SENTINEL,
  FIXTURE_REPLY_BODY, FIXTURE_REPOSITORY,
  type FixtureThreadMessage, type FixtureThread,
} from '../src/__tests__/helpers/consultedEvidenceBridge';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const ownedBridges = new Set<ConsultedEvidenceBridge>();

test.afterEach(async () => {
  for (const bridge of [...ownedBridges]) {
    ownedBridges.delete(bridge);
    await bridge.stop();
  }
});

/** Plain-object shape written across `page.evaluate`'s structured-clone
 * boundary — the store's own `AgentProfileMessage` field names. */
interface InjectedMessage {
  id: string; threadId: string; authorId: string; role: 'user' | 'agent' | 'system';
  text: string; timestamp: number; metadata: Record<string, unknown> | null;
}

interface WireRead { path: string; status: number; body: Buffer; cacheControl: string | null }

function latch(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>(accept => { resolve = accept; });
  return { promise, resolve };
}

function toInjectedMessage(msg: FixtureThreadMessage): InjectedMessage {
  return {
    id: msg.id, threadId: msg.thread_id, authorId: msg.author_id, role: msg.role as InjectedMessage['role'],
    text: msg.body, timestamp: msg.created_at, metadata: msg.metadata,
  };
}

function shellPath(shell: string, search: string): string {
  if (shell === 'desktop') return `/${search}#desktop`;
  if (shell === 'compact') return `/${search}#compact`;
  return `/${search}`;
}

async function isolate(page: Page, shell: string, options: { search?: string } = {}) {
  const bridge = new ConsultedEvidenceBridge(root);
  ownedBridges.add(bridge);
  // `bridge.boot()` returns the real backend fixture's own origin (its real
  // FastAPI/uvicorn server) — the reverse-proxy target for `/api/*`. The
  // mounted app itself is served from the dedicated owned Vite dev server
  // (`playwright.consulted-evidence.config.ts`'s `use.baseURL`), a distinct
  // origin the page navigates to and issues same-origin `/api/*` fetches
  // against. Conflating the two previously sent `/__consulted_evidence_owner`
  // straight to the real backend, which correctly answered its own 404.
  const backendOrigin = await bridge.boot();
  const viteOrigin = `http://127.0.0.1:${process.env.CONSULTED_EVIDENCE_OWNED_PORT}`;
  const reads: string[] = [];
  const wireReads: WireRead[] = [];
  const frames: Array<{ type: string; data: Record<string, unknown> }> = [];
  const delays = new Map<string, { entered: ReturnType<typeof latch>; release: ReturnType<typeof latch> }>();
  const sockets = new Set<WebSocket>();
  const blocked: string[] = [];
  const escaped: string[] = [];
  const pageErrors: string[] = [];
  page.on('pageerror', error => { pageErrors.push(error.message); });

  // Every browser guard is installed before the first navigation.
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('hxi_seen_intro', 'true');
    localStorage.setItem('hxi_voice_enabled', 'false');
    localStorage.setItem('hxi_chat_tts_yeo', '1');
    localStorage.setItem('hxi_chat_tts_other', '1');
    const spoken: string[] = [];
    Object.defineProperty(window, '__consultedSpeech', { value: spoken });
    Object.defineProperty(window, 'SpeechSynthesisUtterance', {
      configurable: true,
      value: class {
        text: string;
        constructor(text: string) { this.text = text; }
      },
    });
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: {
        speak(utterance: { text: string; onstart?: () => void; onend?: () => void }) {
          spoken.push(utterance.text);
          queueMicrotask(() => { utterance.onstart?.(); utterance.onend?.(); });
        },
        cancel() {}, getVoices() { return []; }, addEventListener() {}, removeEventListener() {},
        speaking: false, pending: false, paused: false,
      },
    });
    if (navigator.mediaDevices) {
      for (const name of ['getUserMedia', 'getDisplayMedia'] as const) {
        Object.defineProperty(navigator.mediaDevices, name, {
          configurable: true, value: () => Promise.reject(new DOMException('Isolated test', 'NotAllowedError')),
        });
      }
      Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', { configurable: true, value: async () => [] });
    }
    for (const name of ['Worker', 'SharedWorker', 'SpeechRecognition', 'webkitSpeechRecognition']) {
      Object.defineProperty(window, name, {
        configurable: true,
        value: class { constructor() { throw new DOMException('Isolated test', 'SecurityError'); } },
      });
    }
  });

  // Every `/api/*` request from the real mounted app is reverse-proxied to
  // the real backend with wire bytes preserved end to end — never parsed
  // and reserialized as JSON. Anything the real server answers (including a
  // real 401/404) is forwarded exactly as received, never synthesized here.
  await page.context().route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== viteOrigin) { blocked.push(request.url()); await route.abort('blockedbyclient'); return; }
    const path = url.pathname;
    if (path.startsWith('/api/')) {
      reads.push(`${request.method()} ${path}`);
      try {
        const headers: Record<string, string> = {};
        for (const [key, value] of Object.entries(request.headers())) {
          if (!['host', 'connection', 'content-length'].includes(key.toLowerCase())) headers[key] = value;
        }
        const upstreamBody = request.postDataBuffer();
        const upstream = await fetch(`${backendOrigin}${path}${url.search}`, {
          method: request.method(), headers, body: upstreamBody ? new Uint8Array(upstreamBody) : undefined,
          redirect: 'manual',
        });
        const buffer = Buffer.from(await upstream.arrayBuffer());
        if (/^\/api\/traces\/[^/]+\/consulted$/.test(path)) {
          wireReads.push({ path, status: upstream.status, body: buffer, cacheControl: upstream.headers.get('cache-control') });
          const delay = delays.get(path);
          if (delay) { delay.entered.resolve(); await delay.release.promise; }
        }
        const responseHeaders: Record<string, string> = {};
        upstream.headers.forEach((value, key) => {
          if (!['content-encoding', 'content-length', 'transfer-encoding', 'connection'].includes(key.toLowerCase())) {
            responseHeaders[key] = value;
          }
        });
        await route.fulfill({ status: upstream.status, headers: responseHeaders, body: buffer });
      } catch {
        // A last-reader abort can retire a routed response while an intentional
        // delayed read is still held. Never print request/header/error contents.
        await route.abort('failed').catch(() => {});
      }
      return;
    }
    if (request.method() === 'GET' && (path === '/' || path === '/__consulted_evidence_owner'
      || /^\/(?:src\/|node_modules\/|@vite\/|@id\/|@fs\/|@react-refresh$)/.test(path))) {
      await route.continue();
      return;
    }
    blocked.push(request.url());
    await route.abort('blockedbyclient');
  });

  // The lazy, reply-only, non-polling evidence disclosure never itself
  // depends on the events socket, but the surrounding shell's roster/agent
  // hydration (`agents` map, gating `AgentProfilePanel`) is delivered only
  // over `/ws/events`. Rather than fabricate that hydration, the real
  // backend's own socket is reverse-proxied byte-for-byte (mirroring the
  // `/api/*` HTTP proxy above) so the mounted app hydrates exactly as it
  // would against its real server. Anything outside the app's own origin/
  // path is refused, never silently mocked.
  await page.context().routeWebSocket(/.*/, async (socket) => {
    const url = new URL(socket.url());
    if (url.host !== new URL(viteOrigin).host || url.pathname !== '/ws/events') {
      blocked.push(socket.url());
      socket.close({ code: 1000 });
      return;
    }
    const target = `${backendOrigin.replace(/^http/, 'ws')}${url.pathname}${url.search}`;
    const upstream = new WebSocket(target);
    sockets.add(upstream);
    const outbound: (string | ArrayBufferLike)[] = [];
    let upstreamOpen = false;
    upstream.addEventListener('open', () => {
      upstreamOpen = true;
      for (const message of outbound.splice(0)) upstream.send(message);
    });
    upstream.addEventListener('message', (event) => {
      const raw = event.data as string;
      frames.push(JSON.parse(raw));
      socket.send(raw);
    });
    upstream.addEventListener('close', (event) => {
      sockets.delete(upstream);
      socket.close({ code: event.code }).catch(() => {});
    });
    upstream.addEventListener('error', () => { socket.close({ code: 1011 }).catch(() => {}); });
    socket.onMessage((message) => {
      if (upstreamOpen) upstream.send(message as string);
      else outbound.push(message as string);
    });
    socket.onClose(() => { try { upstream.close(); } catch { /* already closing */ } });
  });

  page.on('response', (response) => {
    if (new URL(response.url()).origin !== viteOrigin) escaped.push(response.url());
  });

  const health = await page.request.get(`${viteOrigin}/__consulted_evidence_owner`);
  expect(await health.json()).toMatchObject({
    owner: process.env.CONSULTED_EVIDENCE_OWNER,
    port: Number(process.env.CONSULTED_EVIDENCE_OWNED_PORT),
    root: resolve(root, 'ui').replace(/\\/g, '/'), proxy: {},
  });
  console.info(`[AD1243] ${shell}: vite origin ${viteOrigin}, backend origin ${backendOrigin}, resolved proxy {}, fixture PID ${bridge.child?.pid}`);

  async function mount(search = ''): Promise<void> {
    await page.goto(shellPath(shell, search));
    // The real roster ('yeo' included) only reaches the store's `agents` map
    // once the real backend's `state_snapshot` frame arrives over the proxied
    // `/ws/events` socket. `AgentProfilePanel` hard-gates its entire render on
    // `agents.get(agentId)` being defined, and `MobileShell` derives its active
    // agent from the same map — so opening the profile / injecting a message
    // before this resolves leaves the surface permanently blank. Mirrors the
    // `bridge.frames.some(frame => frame.type === 'state_snapshot')` wait in
    // the `live-tool-progress.spec.ts` precedent, adapted to poll the store
    // directly since this bridge does not track raw socket frames.
    try {
      await expect.poll(() => page.evaluate(async () => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        return useStore.getState().agents.has('yeo');
      })).toBe(true);
    } catch (error) {
      throw new Error(`Owned shell failed to hydrate: frames=${frames.map(frame => frame.type).join(',')}; `
        + `pageErrors=${pageErrors.join('; ')}`, { cause: error });
    }
    if (shell === 'desktop') {
      await page.evaluate(async () => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        useStore.getState().openAgentProfile('yeo');
      });
    } else {
      await expect(page.getByTestId(shell === 'mobile' ? 'mobile-shell' : 'compact-conversation')).toBeVisible();
    }
  }
  await mount(options.search ?? '');

  return {
    bridge, reads, wireReads, frames, blocked, escaped, mount,
    delayReceipt(ref: string) {
      const delay = { entered: latch(), release: latch() };
      delays.set(`/api/traces/${ref}/consulted`, delay);
      return delay;
    },
    async select(thread: FixtureThread, agent: 'yeo' | 'other' = 'yeo'): Promise<void> {
      // Select the real room, never seed its messages or fabricate metadata.
      await page.evaluate(async ({ thread, agent, shell }) => {
        const { useStore } = await import('/src/store/useStore.ts');
        const state = useStore.getState();
        state.setChatThread(thread);
        if (shell === 'compact') state.setActiveThread(thread.id);
        else if (shell === 'desktop') {
          state.openAgentProfile(agent);
          useStore.setState({ activeProfileThreadId: thread.id });
        } else state.setThreadForAgent('yeo', thread.id);
      }, { thread, agent, shell });
      await expect.poll(() => page.evaluate(async (id) => {
        const { useStore } = await import('/src/store/useStore.ts');
        return useStore.getState().threadMessages.has(id);
      }, thread.id)).toBe(true);
      expect(reads.some(read => read.startsWith(`GET /api/threads/${thread.id}/messages`))).toBe(true);
    },
    /** Places one real thread + one real message directly into the mounted
     * app's store (the established `live-tool-progress.spec.ts` technique),
     * bound as the active thread for whichever shell is under test. */
    async inject(thread: FixtureThread, message: FixtureThreadMessage): Promise<void> {
      const injected = toInjectedMessage(message);
      await page.evaluate(async ({ thread, injected, shell }) => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        const s = useStore.getState();
        s.setChatThread(thread);
        if (shell === 'compact') s.setActiveThread(thread.id);
        else if (shell === 'desktop') useStore.setState({ activeProfileThreadId: thread.id, activeProfileAgent: 'yeo' });
        else s.setThreadForAgent('yeo', thread.id);
        s.setThreadMessages(thread.id, [injected]);
      }, { thread, injected, shell });
    },
    async close(): Promise<void> {
      try {
        expect(escaped).toEqual([]);
        expect(await page.content()).not.toContain(SENSITIVE_SENTINEL);
        expect(await page.content()).not.toContain(OUTPUT_SENTINEL);
        for (const wire of wireReads) {
          expect(wire.body.length).toBeLessThanOrEqual(16 * 1024);
          expect(wire.body.toString('utf8')).not.toContain(SENSITIVE_SENTINEL);
          expect(wire.body.toString('utf8')).not.toContain(OUTPUT_SENTINEL);
          expect(wire.cacheControl).toBe('no-store');
        }
      } finally {
        for (const delay of delays.values()) delay.release.resolve();
        for (const socket of sockets) socket.close();
        ownedBridges.delete(bridge);
        await page.close();
        await bridge.stop();
      }
    },
  };
}

const evidenceButton = (page: Page) => page.getByRole('button', { name: /consulted evidence/i });

async function speechInputs(page: Page): Promise<string[]> {
  return page.evaluate(() => [...(window as unknown as { __consultedSpeech: string[] }).__consultedSpeech]);
}

async function proveDelivery(
  page: Page, shell: string, mode: 'inline' | 'promoted' | 'outbox' | 'lost_ack',
): Promise<void> {
  const h = await isolate(page, shell);
  try {
    const thread = (await h.bridge.listThreads()).find(item => (
      item.participants.length === 1 && item.participants[0] === 'yeo'
    ));
    if (!thread) throw new Error('Actual fixture default thread missing');
    await h.select(thread);
    const query = `wire ${shell} ${mode} query café`;
    const started = await h.bridge.startTurn(mode, { agent: 'yeo', thread: thread.id, query });
    const firstReply = started.messages.at(-1);
    if (!firstReply) throw new Error('Actual reply missing');
    await expect.poll(() => h.frames.some(frame => frame.type === 'chat_thread_message_appended'
      && frame.data.message_id === firstReply.id)).toBe(true);
    if (shell === 'mobile') {
      const diagnostic = () => page.evaluate(async ({ threadId, messageId }) => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        const state = useStore.getState();
        return {
          activeThreadId: state.activeThreadId,
          activeProfileAgent: state.activeProfileAgent,
          activeProfileThreadId: state.activeProfileThreadId,
          associatedThread: state.threadIdByAgent.get('yeo'),
          expectedThread: threadId,
          refresh: state.liveThreadRefresh,
          drops: state.liveDrops.filter(drop => drop.threadId === threadId),
          deliveredToStore: state.threadMessages.get(threadId)?.some(message => message.id === messageId) ?? false,
        };
      }, { threadId: thread.id, messageId: firstReply.id });
      await expect.poll(async () => {
        const state = await diagnostic();
        return state.deliveredToStore || state.drops.length > 0;
      }).toBe(true);
      const state = await diagnostic();
      expect(state.drops, `Actual Mobile live-frame ownership: ${JSON.stringify(state)}`).toEqual([]);
    }
    let delivered = started;
    if (mode !== 'inline') {
      expect(started.released).toBe(false);
      expect(started.llm_calls).toBe(1);
      const acknowledgement = started.messages.at(-1);
      if (!acknowledgement) throw new Error('Actual promotion acknowledgement missing');
      expect(acknowledgement.metadata.tool_trace_ref).toBeUndefined();
      await expect(page.getByText(acknowledgement.body, { exact: true }).last()).toBeVisible();
      await expect(evidenceButton(page)).toHaveCount(0);
      expect(h.frames.some(frame => frame.type === 'chat_thread_message_appended'
        && frame.data.message_id === acknowledgement.id)).toBe(true);
      delivered = await h.bridge.releaseTurn(started.turn);
    }
    if (mode === 'outbox' || mode === 'lost_ack') {
      expect(delivered.pending).toHaveLength(1);
      const pending = delivered.pending[0] as { message_id: string; tool_trace_ref: string };
      expect(pending.tool_trace_ref).toMatch(/^[0-9a-f]{64}$/);
      if (mode === 'outbox') await expect(page.getByText(FIXTURE_REPLY_BODY, { exact: true })).toHaveCount(0);
      const recovered = await h.bridge.recoverTurn(started.turn);
      expect(recovered.pending).toEqual([]);
      expect(recovered.recovered).toEqual(delivered.pending[0]);
      delivered = recovered;
      const report = recovered.messages.find(message => message.id === pending.message_id);
      expect(report?.metadata.tool_trace_ref).toBe(pending.tool_trace_ref);
    }
    const reports = delivered.messages.filter(message => message.body === FIXTURE_REPLY_BODY);
    expect(reports).toHaveLength(1);
    const report = reports[0];
    const ref = report.metadata.tool_trace_ref;
    if (typeof ref !== 'string') throw new Error('Actual stored report did not carry its producer ref');
    expect(report.thread_id).toBe(thread.id);
    expect(report.author_id).toBe('yeo');
    await expect.poll(() => h.frames.some(frame => frame.type === 'chat_thread_message_appended'
      && frame.data.message_id === report.id && frame.data.thread_id === thread.id)).toBe(true);
    const liveDelivery = () => page.evaluate(async ({ threadId, messageId }) => {
      const { useStore } = await import('/src/store/useStore.ts');
      const state = useStore.getState();
      return {
        refresh: state.liveThreadRefresh,
        message: state.threadMessages.get(threadId)?.find(message => message.id === messageId) ?? null,
        activeThreadId: state.activeThreadId,
        activeProfileAgent: state.activeProfileAgent,
        activeProfileThreadId: state.activeProfileThreadId,
      };
    }, { threadId: thread.id, messageId: report.id });
    await expect.poll(liveDelivery).toMatchObject({
      refresh: { threadId: thread.id, requestId: report.id },
      message: {
        id: report.id, threadId: thread.id, authorId: report.author_id,
        text: report.body, metadata: report.metadata,
      },
    });
    if (shell === 'mobile') {
      expect(await liveDelivery()).toMatchObject({
        activeThreadId: thread.id, activeProfileAgent: null, activeProfileThreadId: null,
      });
    }
    await expect(page.getByText(report.body, { exact: true }).last()).toBeVisible();
    await expect(evidenceButton(page)).toHaveCount(1);
    expect(h.wireReads).toEqual([]);
    await expect.poll(() => speechInputs(page)).toContain(report.body);
    const beforeSpeech = await speechInputs(page);
    expect(beforeSpeech.filter(text => text === report.body)).toHaveLength(1);
    const beforeBody = await page.getByText(report.body, { exact: true }).last().textContent();
    await evidenceButton(page).focus();
    await page.keyboard.press('Enter');
    await expect(evidenceButton(page)).toHaveAttribute('aria-expanded', 'true');
    await expect.poll(() => h.wireReads.length).toBe(1);
    const wire = h.wireReads[0];
    expect(wire.path).toBe(`/api/traces/${ref}/consulted`);
    expect(wire.status).toBe(200);
    expect(wire.body.toString('utf8')).not.toContain(SENSITIVE_SENTINEL);
    expect(wire.body.toString('utf8')).not.toContain(OUTPUT_SENTINEL);
    expect(wire.body.length).toBeLessThanOrEqual(16 * 1024);
    expect(wire.body.toString('utf8')).toContain(query);
    await expect.poll(() => evidenceButton(page).locator('..').textContent()).not.toContain('Loading');
    await expect(evidenceButton(page).locator('..')).toContainText(query);
    await expect(evidenceButton(page).locator('..')).toContainText(FIXTURE_REPOSITORY);
    expect(await page.getByText(report.body, { exact: true }).last().textContent()).toBe(beforeBody);
    expect(await speechInputs(page)).toEqual(beforeSpeech);
    const after = await h.bridge.snapshotTurn(started.turn);
    expect(after.messages).toEqual(delivered.messages);
    expect(after.llm_calls).toBe(2);
    expect(after.tool_calls).toBe(1);
    expect(h.frames.some(frame => frame.type === 'chat_thread_message_appended'
      && frame.data.message_id === report.id)).toBe(true);
    expect(h.reads.some(read => read.startsWith(`GET /api/threads/${thread.id}/messages`))).toBe(true);
    expect(await page.getByRole('link', { name: /example.test|langchain|wire .*query/ }).count()).toBe(0);
    console.info(`[AD1243] ${shell}/${mode}: event -> liveThreadRefresh -> stored message ${report.id}`
      + ` -> receipt ${ref}; raw HTTP ${wire.status}/${wire.body.length} bytes;`
      + ` unchanged body/TTS; ${after.llm_calls} LLM calls/${after.tool_calls} tool call`);
  } finally { await h.close(); }
}

test('a reply with no trace ref renders nothing and issues zero evidence requests', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  try {
    const thread: FixtureThread = {
      id: 'noref-room', title: 'No ref', participants: ['captain', 'yeo'], project_id: null, task_id: null,
      pinned: false, archived: false, personality_override: null, workspace_root: null,
      created_at: Date.now() / 1000, last_active_at: Date.now() / 1000, preprompt: null, model: null, metadata: {},
    };
    const message: FixtureThreadMessage = {
      id: 'msg-noref', thread_id: thread.id, author_id: 'yeo', role: 'agent',
      body: 'A plain reply with no consulted evidence at all.', created_at: Date.now() / 1000, metadata: {},
    };
    await h.inject(thread, message);
    await expect(page.getByText(message.body)).toBeVisible();
    await expect(evidenceButton(page)).toHaveCount(0);
    await expect(page.getByText(/unreadable/i)).toHaveCount(0);
    expect(h.reads.filter((read) => read.includes('/api/traces/'))).toHaveLength(0);
  } finally { await h.close(); }
});

test('a malformed trace ref is a visible, distinct error with zero network calls', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  try {
    const thread: FixtureThread = {
      id: 'malformed-room', title: 'Malformed', participants: ['captain', 'yeo'], project_id: null, task_id: null,
      pinned: false, archived: false, personality_override: null, workspace_root: null,
      created_at: Date.now() / 1000, last_active_at: Date.now() / 1000, preprompt: null, model: null, metadata: {},
    };
    const message: FixtureThreadMessage = {
      id: 'msg-malformed', thread_id: thread.id, author_id: 'yeo', role: 'agent',
      body: 'A reply whose receipt reference is not a valid trace ref.', created_at: Date.now() / 1000,
      metadata: { tool_trace_ref: 'not-a-64-hex-sha256' },
    };
    await h.inject(thread, message);
    await expect(page.getByText(message.body)).toBeVisible();
    await expect(evidenceButton(page)).toHaveCount(0);
    await expect(page.getByText(/unreadable/i)).toBeVisible();
    expect(h.reads.filter((read) => read.includes('/api/traces/'))).toHaveLength(0);
  } finally { await h.close(); }
});

test('a valid ref is fetched lazily on expand and renders real, sentinel-free evidence', async ({ page }, info) => {
  // The earlier check injected a stored row into UI state. Keep its lazy-read
  // assertion, but cross real commit events and transcript HTTP repair as well.
  await proveDelivery(page, info.project.name, 'promoted');
});

for (const mode of ['inline', 'outbox', 'lost_ack'] as const) {
  test(`real ${mode} delivery retains producer identity, raw HTTP safety, body and TTS`, async ({ page }, info) => {
    await proveDelivery(page, info.project.name, mode);
  });
}

test('owner invalidation collapses the disclosure when the bound thread changes', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  let delayed: ReturnType<typeof h.delayReceipt> | null = null;
  try {
    // The old test copied a traced message into an invented room. That could
    // not prove attribution. Both rooms and both authors now come from storage.
    const first = await h.bridge.startTurn('inline', { query: 'previous room query café' });
    const created = await h.bridge.fetchWire('/api/threads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Owned workspace with Other', participants: ['other', 'yeo'], workspace_root: root,
      }),
    });
    expect(created.status).toBe(200);
    const room = await created.json() as FixtureThread;
    const second = await h.bridge.startTurn('inline', {
      agent: 'other', thread: room.id, query: 'other participant workspace query café',
    });
    const firstMessage = first.messages.at(-1)!;
    const secondMessage = second.messages.at(-1)!;
    expect(firstMessage.author_id).toBe('yeo');
    expect(secondMessage.author_id).toBe('other');
    const firstRef = firstMessage.metadata.tool_trace_ref;
    const secondRef = secondMessage.metadata.tool_trace_ref;
    if (typeof firstRef !== 'string' || typeof secondRef !== 'string') throw new Error('Produced references missing');
    expect(firstRef).not.toBe(secondRef);
    await h.select(first.thread);
    delayed = h.delayReceipt(firstRef);
    await evidenceButton(page).click();
    await delayed.entered.promise;
    await h.select(second.thread, 'other');
    await expect(page.getByRole('button', { name: /^show consulted evidence$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /hide consulted evidence/i })).toHaveCount(0);
    expect(h.wireReads).toHaveLength(1);
    delayed.release.resolve();
    await expect(page.getByText(first.query, { exact: false })).toHaveCount(0);
    await evidenceButton(page).click();
    await expect(page.getByText(second.query, { exact: false })).toBeVisible();
    await expect(page.getByText(first.query, { exact: false })).toHaveCount(0);
    await expect(page.getByText('Other', { exact: true }).last()).toBeVisible();
    await expect.poll(() => h.wireReads.length).toBe(2);
    expect(h.wireReads[1].path).toBe(`/api/traces/${secondRef}/consulted`);
    expect((await h.bridge.snapshotTurn(first.turn)).messages).toEqual(first.messages);
    expect((await h.bridge.snapshotTurn(second.turn)).messages).toEqual(second.messages);
  } finally { delayed?.release.resolve(); await h.close(); }
});

test('real store unavailability remains visible and only explicit retry reads again', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  try {
    const turn = await h.bridge.startTurn('inline');
    await h.select(turn.thread);
    await h.bridge.setReceiptStoreAvailable(false);
    await evidenceButton(page).click();
    await expect(page.getByText('Receipt unavailable.')).toBeVisible();
    expect(h.wireReads.map(read => read.status)).toEqual([503]);
    await h.bridge.setReceiptStoreAvailable(true);
    expect(h.wireReads).toHaveLength(1);
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(page.getByText(turn.query, { exact: false })).toBeVisible();
    expect(h.wireReads.map(read => read.status)).toEqual([503, 200]);
    const unchanged = await h.bridge.snapshotTurn(turn.turn);
    expect(unchanged.messages).toEqual(turn.messages);
    expect(unchanged.llm_calls).toBe(2);
  } finally { await h.bridge.setReceiptStoreAvailable(true).catch(() => {}); await h.close(); }
});

test('a syntactically valid but nonexistent ref shows a real 404 with a visible retry', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  try {
    const thread: FixtureThread = {
      id: 'retry-room', title: 'Retry', participants: ['captain', 'yeo'], project_id: null, task_id: null,
      pinned: false, archived: false, personality_override: null, workspace_root: null,
      created_at: Date.now() / 1000, last_active_at: Date.now() / 1000, preprompt: null, model: null, metadata: {},
    };
    const nonexistentRef = randomBytes(32).toString('hex');
    const message: FixtureThreadMessage = {
      id: 'msg-retry', thread_id: thread.id, author_id: 'yeo', role: 'agent',
      body: 'A reply whose receipt was never actually recorded.', created_at: Date.now() / 1000,
      metadata: { tool_trace_ref: nonexistentRef },
    };
    await h.inject(thread, message);
    await evidenceButton(page).click();
    await expect(page.getByText('Receipt unavailable.')).toBeVisible();
    const retry = page.getByRole('button', { name: 'Retry' });
    await expect(retry).toBeVisible();
    await expect.poll(() => h.reads.filter((read) => read.includes('/api/traces/')).length).toBe(1);
    await retry.click();
    await expect.poll(() => h.reads.filter((read) => read.includes('/api/traces/')).length).toBe(2);
    await expect(page.getByText('Receipt unavailable.')).toBeVisible();
  } finally { await h.close(); }
});

test('a real 401 is a visible, non-retryable effect, and the same ref succeeds once the page carries the token', async ({ page }, info) => {
  const h = await isolate(page, info.project.name);
  const authToken = randomBytes(16).toString('hex');
  try {
    const started = await h.bridge.startTurn('promoted', { agent: 'yeo' });
    const released = await h.bridge.releaseTurn(started.turn);
    const withRef = released.messages.find((message) => typeof message.metadata?.tool_trace_ref === 'string');
    if (!withRef) throw new Error('Real promoted+released turn produced no message with a tool_trace_ref');

    await h.bridge.setAuth(authToken);
    await h.inject(released.thread, withRef);
    await evidenceButton(page).click();
    await expect(page.getByText('Receipt unavailable.')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: 'Retry' })).toHaveCount(0);
    await expect.poll(() => h.reads.filter((read) => read.includes('/api/traces/')).length).toBe(1);

    // Auth cache invalidation: a fresh navigation carrying the token must not
    // be haunted by the prior unauthorized result — the hook re-acquires
    // rather than serving a stale cached failure for the same ref.
    await h.mount(`?token=${authToken}`);
    await h.inject(released.thread, withRef);
    await evidenceButton(page).click();
    await expect(page.getByText(/sensitive values are redacted/i)).toBeVisible({ timeout: 20_000 });
  } finally {
    await h.bridge.setAuth('').catch(() => {});
    await h.close();
  }
});
