import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const python = 'D:\\ProbOS\\.venv\\Scripts\\python.exe';
const origin = `http://127.0.0.1:${process.env.AD1174_OWNED_PORT}`;
type Thread = { id: string; participants: string[]; [key: string]: unknown };
type Turn = { turn: string; thread: Thread; calls: number; promoted: boolean };
type Reply = { response: string; thread_id: string };
type Frame = { type: string; data: Record<string, unknown>; stream: { generation: string; sequence: number } };
const ownedBridges = new Set<Bridge>();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

class Bridge {
  readonly child: ChildProcessWithoutNullStreams;
  readonly ready = deferred<Record<string, string>>();
  readonly sockets = new Map<string, WebSocketRoute>();
  readonly frames: Frame[] = [];
  private sequence = 0;
  private stderr = '';
  private pending = new Map<number, ReturnType<typeof deferred<unknown>>>();
  private replies = new Map<string, Reply>();
  private waitingReplies = new Map<string, ReturnType<typeof deferred<Reply>>>();

  constructor() {
    ownedBridges.add(this);
    this.child = spawn(python, ['-u', 'tests/fixtures/ad1174_progress_bridge.py', root], {
      cwd: root, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      env: {
        SystemRoot: process.env.SystemRoot ?? 'C:\\Windows',
        PATH: `${dirname(python)};${process.env.SystemRoot ?? 'C:\\Windows'}\\System32`,
        PYTHONPATH: `${resolve(root, 'src')};${root}`,
        PYTHONNOUSERSITE: '1', PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1',
      },
    });
    this.child.stderr.on('data', chunk => { this.stderr = (this.stderr + String(chunk)).slice(-12_000); });
    const lines = createInterface({ input: this.child.stdout });
    lines.on('line', line => {
      const message = JSON.parse(line);
      if (message.kind === 'ready') this.ready.resolve(message);
      if (message.kind === 'response') {
        const request = this.pending.get(message.id);
        if (message.error) request?.reject(new Error(`${message.error}: ${this.stderr}`));
        else request?.resolve(message.data);
        this.pending.delete(message.id);
      }
      if (message.kind === 'frame') {
        this.frames.push(message.frame);
        if (this.frames.length > 4096) this.frames.shift();
        this.sockets.get(message.socket)?.send(JSON.stringify(message.frame));
      }
      if (message.kind === 'socket_closed') {
        const socket = this.sockets.get(message.socket);
        this.sockets.delete(message.socket);
        socket?.close({ code: message.code });
      }
      if (message.kind === 'chat_reply') {
        this.replies.set(message.turn, message.data);
        this.waitingReplies.get(message.turn)?.resolve(message.data);
        this.waitingReplies.delete(message.turn);
      }
    });
    const failed = (error: Error): void => {
      this.ready.reject(error);
      for (const pending of this.pending.values()) pending.reject(error);
      for (const pending of this.waitingReplies.values()) pending.reject(error);
    };
    this.child.on('error', failed);
    this.child.on('exit', code => {
      lines.close();
      failed(new Error(`Owned progress fixture exited ${code}: ${this.stderr}`));
    });
  }

  async command<T = unknown>(data: Record<string, unknown>): Promise<T> {
    const id = ++this.sequence;
    const result = deferred<unknown>();
    this.pending.set(id, result);
    const timer = setTimeout(() => {
      this.pending.delete(id);
      result.reject(new Error(`Progress fixture command timed out: ${data.op}; ${this.stderr}`));
    }, 20_000);
    try {
      this.child.stdin.write(JSON.stringify({ ...data, id }) + '\n');
      return await result.promise as T;
    } finally {
      clearTimeout(timer);
    }
  }

  reply(turn: string): Promise<Reply> {
    const known = this.replies.get(turn);
    if (known) return Promise.resolve(known);
    const waiting = deferred<Reply>();
    this.waitingReplies.set(turn, waiting);
    return waiting.promise;
  }

  async stop(): Promise<void> {
    if (this.child.exitCode !== null || this.child.signalCode !== null) {
      ownedBridges.delete(this);
      return;
    }
    try {
      await this.command({ op: 'stop' });
      this.child.stdin.end();
      await new Promise<void>(resolveExit => {
        if (this.child.exitCode !== null) return resolveExit();
        const timer = setTimeout(() => { this.child.kill(); resolveExit(); }, 5000);
        this.child.once('exit', () => { clearTimeout(timer); resolveExit(); });
      });
    } finally {
      if (this.child.exitCode === null) this.child.kill();
      ownedBridges.delete(this);
    }
  }
}

test.afterEach(async () => {
  for (const bridge of ownedBridges) await bridge.stop();
});

async function isolate(page: Page, shell: string, enabled: boolean | undefined) {
  const bridge = new Bridge();
  const ready = await bridge.ready.promise;
  expect(resolve(ready.root)).toBe(root);
  expect(ready.python.toLowerCase()).toBe(python.toLowerCase());
  for (const field of ['producer', 'runtime', 'hub']) expect(ready[field]).toContain(`${root}\\src\\probos\\`);
  await bridge.command({ op: 'config', enabled: enabled !== false });
  const turns: Turn[] = [];
  const reads: string[] = [];
  const associations: string[] = [];
  const escaped: string[] = [];
  const blocked: string[] = [];
  let socketSequence = 0;

  // Every browser guard is installed before the first navigation.
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem('hxi_seen_intro', 'true');
    localStorage.setItem('hxi_voice_enabled', 'false');
    if (navigator.mediaDevices) {
      for (const name of ['getUserMedia', 'getDisplayMedia']) {
        Object.defineProperty(navigator.mediaDevices, name, {
          configurable: true, value: () => Promise.reject(new DOMException('Isolated test', 'NotAllowedError')),
        });
      }
      Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', { configurable: true, value: async () => [] });
    }
    for (const name of ['Worker', 'SharedWorker', 'SpeechRecognition', 'webkitSpeechRecognition']) {
      Object.defineProperty(window, name, { configurable: true, value: class {
        constructor() { throw new DOMException('Isolated test', 'SecurityError'); }
      } });
    }
  });
  await page.context().route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      blocked.push(request.url());
      await route.abort('blockedbyclient');
      return;
    }
    const path = url.pathname;
    if (path.startsWith('/api/')) {
      reads.push(`${request.method()} ${path}`);
      try {
        if (path === '/api/config') {
          await route.fulfill({ json: {
            config: { agentic_loop: { event_correlation_enabled: enabled } },
            sections: [], secret_present: {}, domain_counts: {}, domain_order: [],
            section_count: 0, config_path: '', uptime_seconds: 0, csrf_token: '',
          } });
        } else if (/^\/api\/agent\/(yeo|other)\/thread$/.test(path) && request.method() === 'POST') {
          associations.push(path);
          await route.fulfill({ json: await bridge.command({ op: 'associate', agent: path.split('/')[3] }) });
        } else if (/^\/api\/agent\/(yeo|other)\/chat$/.test(path) && request.method() === 'POST') {
          const body = request.postDataJSON();
          const turn = await bridge.command<Turn>({
            op: 'start', agent: path.split('/')[3], thread: body.thread_id,
            promoted: String(body.message).startsWith('promote'), error: String(body.message).includes('error'),
          });
          turns.push(turn);
          await route.fulfill({ json: await bridge.reply(turn.turn) });
        } else if (path === '/api/threads') {
          await route.fulfill({ json: { threads: await bridge.command({ op: 'threads' }) } });
        } else if (path === '/api/threads/summaries') {
          await route.fulfill({ json: { summaries: {} } });
        } else if (/^\/api\/threads\/[^/]+$/.test(path) && request.method() === 'GET') {
          const thread = await bridge.command({ op: 'thread', thread: decodeURIComponent(path.split('/')[3]) });
          await route.fulfill({ status: thread ? 200 : 404, json: thread ?? {} });
        } else if (/^\/api\/threads\/[^/]+\/messages$/.test(path) && request.method() === 'GET') {
          await route.fulfill({ json: { messages: await bridge.command({ op: 'messages', thread: path.split('/')[3] }) } });
        } else if (path.endsWith('/chat/history')) {
          await route.fulfill({ json: { messages: [], seed_memories: [] } });
        } else if (path === '/api/config/avatars-enabled') {
          await route.fulfill({ json: { enabled: false } });
        } else if (path === '/api/voice/health') {
          await route.fulfill({ json: { engine: 'browser', primary_stt: 'browser', healthy: false, backend_available: false } });
        } else if (path === '/api/capability-requests/actionable') {
          await route.fulfill({ json: { view: 'actionable', requests: [] } });
        } else if (path === '/api/skill-requests') {
          await route.fulfill({ json: { requests: [] } });
        } else if (path === '/api/wardroom/dms') {
          await route.fulfill({ json: [] });
        } else if (path === '/api/recreation/active') {
          await route.fulfill({ json: { game: null } });
        } else {
          // Unrelated owners are explicitly unavailable, never proxied to a vessel.
          await route.fulfill({ status: 404, json: { detail: 'isolated_fixture_unavailable' } });
        }
      } catch (error) {
        console.error('AD1174 owned fixture request failed; crossing evidence is invalid and the request is aborted:', String(error));
        await route.abort('failed').catch(() => {});
      }
      return;
    }
    if (request.method() === 'GET' && (path === '/' || path === '/__ad1174_owner'
      || /^\/(?:src\/|node_modules\/|@vite\/|@id\/|@fs\/|@react-refresh$)/.test(path))) {
      await route.continue();
      return;
    }
    blocked.push(request.url());
    await route.abort('blockedbyclient');
  });
  await page.context().routeWebSocket(/.*/, async socket => {
    const url = new URL(socket.url());
    if (url.origin !== origin.replace('http:', 'ws:') || url.pathname !== '/ws/events' || url.search) {
      blocked.push(socket.url());
      socket.close({ code: 1008 });
      return;
    }
    const identity = String(++socketSequence);
    bridge.sockets.set(identity, socket);
    await bridge.command({ op: 'connect', socket: identity });
  });
  page.on('response', response => {
    if (new URL(response.url()).origin !== origin) escaped.push(response.url());
  });
  const health = await page.request.get(`${origin}/__ad1174_owner`);
  expect(await health.json()).toEqual({
    owner: process.env.AD1174_OWNER, port: Number(process.env.AD1174_OWNED_PORT),
    root: `${root.replace(/\\/g, '/')}/ui`, proxy: {},
  });
  console.info(`[AD1174] ${shell}: owned origin ${origin}, resolved proxy {}, fixture PID ${bridge.child.pid}, candidate origins verified`);
  await page.goto(shell === 'desktop' ? '/#desktop' : shell === 'compact' ? '/#compact' : '/');
  await expect.poll(() => bridge.frames.some(frame => frame.type === 'state_snapshot')).toBe(true);
  if (shell === 'desktop') {
    await page.evaluate(async () => {
      const modulePath = '/src/store/useStore.ts';
      const { useStore } = await import(modulePath);
      useStore.getState().openAgentProfile('yeo');
    });
  } else {
    await expect(page.getByTestId(shell === 'mobile' ? 'mobile-shell' : 'compact-conversation')).toBeVisible();
  }
  await expect(page.getByRole('region', { name: 'Live tool progress' })).toBeVisible();
  expect(associations).toHaveLength(0);
  return {
    bridge, turns, reads, associations, escaped, blocked,
    async select(thread: Thread): Promise<void> {
      await page.evaluate(async ({ thread, shell }) => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        useStore.getState().setChatThread(thread);
        if (shell === 'compact') useStore.getState().setActiveThread(thread.id);
        else if (shell === 'desktop') useStore.setState({ activeProfileThreadId: thread.id, activeProfileAgent: 'yeo' });
        else useStore.getState().setThreadForAgent('yeo', thread.id);
      }, { thread, shell });
      await expect.poll(async () => page.evaluate(async () => {
        const modulePath = '/src/store/useStore.ts';
        const { useStore } = await import(modulePath);
        const s = useStore.getState();
        return {
          profile: s.activeProfileAgent, desktopThread: s.activeProfileThreadId,
          compactThread: s.activeThreadId, mobileThread: s.threadIdByAgent.get('yeo'),
        };
      })).toMatchObject(shell === 'compact'
        ? { profile: null, compactThread: thread.id }
        : shell === 'desktop' ? { profile: 'yeo', desktopThread: thread.id }
          : { profile: null, mobileThread: thread.id });
    },
    async close(): Promise<void> {
      try {
        expect(escaped).toEqual([]);
        expect(bridge.frames.every(frame => !JSON.stringify(frame).includes('private-fixture'))).toBe(true);
      } finally {
        await page.close();
        await bridge.stop();
      }
    },
  };
}

test('first inline producer start is visible before release, with keyboard details and real error evidence', async ({ page }, info) => {
  const h = await isolate(page, info.project.name, true);
  try {
    const band = page.getByRole('region', { name: 'Live tool progress' });
    await page.getByPlaceholder('Message...').fill('Use a tool');
    await page.getByPlaceholder('Message...').press('Enter');
    await expect.poll(() => h.turns.length).toBe(1);
    expect(h.associations).toHaveLength(1);
    const start = h.bridge.frames.find(frame => frame.type === 'agentic_tool_call_started')!;
    expect(h.turns[0].calls).toBe(1);
    expect(h.bridge.frames.some(frame => frame.type === 'agentic_tool_call_completed')).toBe(false);
    await expect(band).toContainText('1 started');
    expect(start.data.thread_id).toBe(h.turns[0].thread.id);
    const summary = band.locator('summary');
    await summary.focus();
    await page.keyboard.press('Enter');
    await expect(band.getByText('Start observed', { exact: true })).toBeVisible();
    await expect(band.getByText('progress_probe', { exact: true })).toBeVisible();
    const bounds = await band.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
    await h.bridge.command({ op: 'release', turn: h.turns[0].turn });
    await expect(band.getByText('Completed', { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('Message...')).toBeEnabled();
    await page.getByPlaceholder('Message...').fill('Use an error tool');
    await page.getByPlaceholder('Message...').press('Enter');
    await expect.poll(() => h.turns.length).toBe(2);
    await h.bridge.command({ op: 'release', turn: h.turns[1].turn });
    await expect(band.getByText('Tool error', { exact: true })).toBeVisible();
    expect(h.associations).toHaveLength(1);
    await expect(band).toContainText('not confirmation that the task succeeded or was delivered');
  } finally { await h.close(); }
});

test('promoted and late runs remain scoped; real retention, cancellation and reconnect disclose uncertainty', async ({ page }, info) => {
  const h = await isolate(page, info.project.name, true);
  try {
    await page.getByPlaceholder('Message...').fill('promote this tool');
    await page.getByPlaceholder('Message...').press('Enter');
    await expect.poll(() => h.turns.length).toBe(1);
    expect(h.turns[0].promoted).toBe(true);
    const home = h.turns[0].thread;
    const room = await h.bridge.command<Thread>({ op: 'room' });
    await h.select(room);
    let band = page.getByRole('region', { name: 'Live tool progress' });
    await expect(band).toContainText('No tool activity observed');
    await h.bridge.command({ op: 'release', turn: h.turns[0].turn });
    await expect(band).not.toContainText('Completed');
    const foreign = await h.bridge.command<Turn>({ op: 'start', agent: 'other', thread: room.id, calls: 65 });
    await expect(band).toContainText('1 started');
    await h.bridge.command({ op: 'release', turn: foreign.turn });
    await expect(band).toContainText('1 call records omitted');
    for (let run = 0; run < 32; run += 1) {
      const turn = await h.bridge.command<Turn>({ op: 'start', agent: 'other', thread: room.id });
      await h.bridge.command({ op: 'release', turn: turn.turn });
    }
    await expect(band).toContainText('run records');
    await expect.poll(async () => page.evaluate(async () => {
      const modulePath = '/src/store/useStore.ts';
      const { useStore } = await import(modulePath);
      return useStore.getState().toolProgress.runs.length;
    })).toBe(32);
    await h.select(home);
    band = page.getByRole('region', { name: 'Live tool progress' });
    await expect(band).toContainText('No tool activity observed');
    const held = await h.bridge.command<Turn>({ op: 'start', agent: 'yeo', thread: home.id });
    await expect(band).toContainText('1 started');
    const completedBeforeCancel = h.bridge.frames.filter(frame => frame.type === 'agentic_tool_call_completed').length;
    await h.bridge.command({ op: 'cancel', turn: held.turn });
    expect(h.bridge.frames.filter(frame => frame.type === 'agentic_tool_call_completed')).toHaveLength(completedBeforeCancel);
    const previousSockets = h.bridge.sockets.size;
    await h.bridge.command({ op: 'disconnect', socket: [...h.bridge.sockets.keys()][0] });
    await expect(band).toContainText('Delivery is incomplete');
    await expect.poll(() => h.bridge.sockets.size).toBe(previousSockets);
    await expect(band).toContainText('Completion unconfirmed');
    await expect(band).not.toContainText('cancelled');
    expect(h.bridge.frames.filter(frame => frame.type === 'state_snapshot').length).toBeGreaterThan(1);
  } finally { await h.close(); }
});

for (const enabled of [false, undefined]) {
  test(`saved readiness ${String(enabled)} does not invent activity or create an empty thread`, async ({ page }, info) => {
    const h = await isolate(page, info.project.name, enabled);
    try {
      const band = page.getByRole('region', { name: 'Live tool progress' });
      await expect(band).toContainText(enabled === false ? 'off in saved settings' : 'availability is unknown');
      expect(h.associations).toHaveLength(0);
      await page.getByPlaceholder('Message...').fill('Normal send still works');
      await page.getByPlaceholder('Message...').press('Enter');
      await expect.poll(() => h.turns.length).toBe(1);
      expect(h.associations).toHaveLength(0);
      await expect(band).toContainText('association unverified');
      await h.bridge.command({ op: 'release', turn: h.turns[0].turn });
      await expect(page.getByPlaceholder('Message...')).toBeEnabled();
      if (enabled === false) await expect(band).not.toContainText('Completed');
      else await expect(band).toContainText('Completed');
    } finally { await h.close(); }
  });
}
