import { test, expect, type Locator } from '@playwright/test';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import { createHash } from 'node:crypto';
import { mkAgent, mkThread, mkMessage, installIssue1369Isolation, type Issue1369IsolationOptions } from './_helpers';
import type { AgentFixture, MessageFixture, ThreadFixture } from './_helpers';
import type TelemetryFixture from './fixtures/issue1370-telemetry.json';
import type { CrewSessionDetailProjection, StartWorkResult } from '../src/store/types';
import type { TodoStep } from '../src/components/workspace/todosApi';

const telemetry: typeof TelemetryFixture = JSON.parse(
  readFileSync(new URL('./fixtures/issue1370-telemetry.json', import.meta.url), 'utf8'),
);
const alpha = mkAgent('alpha', 'Alpha', 'science');
const generation = '13690000000000000000000000000001';
const messageText = 'Baseline viewport message';
const replyText = 'Fixture received the baseline message.';
const thread = mkThread('baseline-alpha', 'Alpha baseline', [alpha.id]);
const messages = [
  mkMessage('baseline-captain', thread.id, 'captain', 'captain', messageText),
  mkMessage('baseline-reply', thread.id, alpha.id, 'agent', replyText),
];

interface BrowserState {
  connected: boolean;
  liveGeneration: string | null;
  liveSequence: number;
  liveDropCount: number;
  mainViewer: string;
  agents: Map<string, { callsign: string }>;
  activeProfileAgent: string | null;
  activeProfileThreadId: string | null;
  activeThreadId: string | null;
  threadIdByAgent: Map<string, string>;
}

interface BaselineWindow extends Window {
  __store: { getState: () => BrowserState };
  __issue1369: { initialStorage: string[]; blockedCapabilities: string[]; installed: boolean };
}

function assetPaths(): Set<string> {
  const paths = new Set(['/', '/@vite/client', '/@react-refresh', '/node_modules/vite/dist/client/env.mjs']);
  for (const directory of ['src', 'node_modules/.vite/deps']) {
    const root = fileURLToPath(new URL(`../${directory}/`, import.meta.url));
    if (!existsSync(root)) continue;
    for (const file of readdirSync(root, { recursive: true, withFileTypes: false })) {
      const relative = String(file).replaceAll('\\', '/');
      if (/\.(?:tsx?|m?js|css|json)$/.test(relative)) {
        paths.add(`/${directory}/${encodeURI(relative)}`);
      }
    }
  }
  return paths;
}

async function bounds(locator: Locator): Promise<unknown> {
  return locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      clientWidth: element.clientWidth, scrollWidth: element.scrollWidth,
      display: style.display, overflow: style.overflow,
      collapsed: element.getAttribute('data-collapsed'),
    };
  });
}

test('baseline: fresh desktop Alpha conversation preserves usable chat and Send', async ({ page, context, baseURL }, testInfo) => {
  if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
  const origin = new URL(baseURL).origin;
  const socketOrigin = origin.replace('http:', 'ws:');
  const allowedAssets = assetPaths();
  const continued = new Set<string>();
  const fulfilled = new Set<string>();
  const deniedHttp: string[] = [];
  const deniedSockets: string[] = [];
  const escapedHttp: string[] = [];
  const escapedSockets: string[] = [];
  const socketRoutes = new Set<string>();
  const snapshots: unknown[] = [];
  const fixtureReads: string[] = [];
  const sends: unknown[] = [];
  const browserErrors: string[] = [];
  const measurements: Record<string, unknown> = {};
  let premiseEstablished = false;
  let sent = false;

  const authority = () => page.evaluate(() => {
    const state = (window as unknown as BaselineWindow).__store.getState();
    return {
      connected: state.connected, generation: state.liveGeneration,
      sequence: state.liveSequence, drops: state.liveDropCount,
      agents: [...state.agents.keys()], alphaCallsign: state.agents.get('alpha')?.callsign,
      mainViewer: state.mainViewer, selectedAgent: state.activeProfileAgent,
      activeProfileThreadId: state.activeProfileThreadId, activeThreadId: state.activeThreadId,
      alphaThread: state.threadIdByAgent.get('alpha') ?? null,
      windowWidth: innerWidth, windowHeight: innerHeight,
      finePointer: matchMedia('(pointer: fine)').matches,
    };
  });

  await context.addInitScript(() => {
    const browser = window as unknown as BaselineWindow;
    browser.__issue1369 = { initialStorage: Object.keys(localStorage), blockedCapabilities: [], installed: false };
    const deny = (name: string): never => {
      browser.__issue1369.blockedCapabilities.push(name);
      throw new DOMException(`${name} disabled by issue1369 isolation`, 'NotAllowedError');
    };
    if (navigator.mediaDevices) {
      for (const name of ['getUserMedia', 'getDisplayMedia']) {
        Object.defineProperty(navigator.mediaDevices, name, {
          configurable: true, value: async () => deny(name),
        });
      }
      Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', {
        configurable: true, value: async () => [],
      });
    }
    for (const name of ['getUserMedia', 'webkitGetUserMedia', 'mozGetUserMedia']) {
      Object.defineProperty(navigator, name, { configurable: true, value: () => deny(name) });
    }
    for (const name of ['Worker', 'SharedWorker', 'AudioContext', 'webkitAudioContext', 'RTCPeerConnection']) {
      Object.defineProperty(window, name, {
        configurable: true, value: class { constructor() { deny(name); } },
      });
    }
    class DeniedRecognition extends EventTarget {
      onerror: ((event: Event) => void) | null = null;
      start(): void {
        browser.__issue1369.blockedCapabilities.push('SpeechRecognition.start');
        const event = new Event('error');
        Object.defineProperty(event, 'error', { value: 'not-allowed' });
        queueMicrotask(() => { this.onerror?.(event); this.dispatchEvent(event); });
      }
      stop(): void {}
      abort(): void {}
    }
    for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) {
      Object.defineProperty(window, name, { configurable: true, value: DeniedRecognition });
    }
    if (window.speechSynthesis) {
      Object.defineProperty(window.speechSynthesis, 'speak', {
        configurable: true, value: () => { browser.__issue1369.blockedCapabilities.push('speechSynthesis.speak'); },
      });
    }
    Object.defineProperty(HTMLMediaElement.prototype, 'play', {
      configurable: true, value: async () => deny('HTMLMediaElement.play'),
    });
    if (navigator.serviceWorker) {
      Object.defineProperty(navigator.serviceWorker, 'register', {
        configurable: true, value: async () => deny('serviceWorker.register'),
      });
    }
    browser.__issue1369.installed = true;
  });

  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}${url.search}`;
    const respond = async (json: unknown): Promise<void> => {
      fulfilled.add(request.url());
      await route.fulfill({ json });
      fixtureReads.push(key);
    };
    if (url.origin === origin && request.resourceType() !== 'media') {
      if (request.method() === 'GET' && !url.search) {
        const fixtures = new Map<string, unknown>([
          ['/api/config/avatars-enabled', { enabled: false }],
          ['/api/agent/alpha/profile', telemetry.profile],
          ['/api/agent/alpha/chat/history', { memories: [] }],
          ['/api/threads', { threads: sent ? [thread] : [] }],
          ['/api/threads/summaries', { summaries: {} }],
          ['/api/ontology/crew-manifest', { manifest: [{
            agent_id: alpha.id, agent_type: alpha.agentType, callsign: alpha.callsign,
            department: alpha.department, post: 'Baseline fixture', rank: 'ensign', trust_score: alpha.trust,
          }] }],
          ['/api/crew/presence', { presence: { alpha: 'available' } }],
        ]);
        if (fixtures.has(url.pathname)) return respond(fixtures.get(url.pathname));
      }
      if (key === `GET /api/artifacts/thread/${thread.id}?limit=1001`) {
        return respond({ thread_id: thread.id, artifacts: [] });
      }
      if (key === `GET /api/threads/${thread.id}/messages?limit=200`) {
        return respond({ thread_id: thread.id, messages: sent ? messages : [] });
      }
      if (key === 'GET /api/agent/alpha/memory-graph?ship_wide=false') return respond(telemetry.memoryGraph);
      if (key === 'GET /api/agent/alpha/memory-graph?ship_wide=true') return respond(telemetry.shipGraph);
      if (key === 'POST /api/agent/alpha/chat') {
        const body = request.postDataJSON() as Record<string, unknown>;
        if (!sent && body.message === messageText && !('thread_id' in body)) {
          sends.push({ path: url.pathname, body });
          sent = true;
          return respond({ response: replyText, thread_id: thread.id, title: thread.title });
        }
      }
      if (request.method() === 'GET' && !url.pathname.startsWith('/api/')) {
        if (!allowedAssets.has(url.pathname) && url.pathname.startsWith('/node_modules/.vite/deps/')) {
          for (const path of assetPaths()) allowedAssets.add(path);
        }
        if (allowedAssets.has(url.pathname)
          && [...url.searchParams.keys()].every(key => ['v', 't', 'import', 'url'].includes(key))) {
          continued.add(request.url());
          return route.continue();
        }
      }
    }
    deniedHttp.push(key);
    await route.abort('blockedbyclient');
  });

  await context.routeWebSocket(/.*/, socket => {
    const url = new URL(socket.url());
    socketRoutes.add(socket.url());
    if (url.origin === socketOrigin && url.pathname === '/ws/events' && !url.search) {
      const frame = {
        type: 'state_snapshot', timestamp: 1_789_437_344,
        stream: { generation, sequence: 1 },
        data: {
          agents: [{
            id: alpha.id, agent_type: alpha.agentType, callsign: alpha.callsign,
            display_name: alpha.displayName, pool: alpha.pool, state: alpha.state,
            confidence: alpha.confidence, trust: alpha.trust, tier: alpha.tier, isCrew: alpha.isCrew,
          }],
          connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0, fresh_boot: false,
        },
      };
      socket.onMessage(() => {});
      socket.send(JSON.stringify(frame));
      snapshots.push(frame);
    } else if (url.origin === socketOrigin && url.pathname === '/'
      && [...url.searchParams.keys()].every(key => key === 'token')) {
      socket.onMessage(() => {});
      socket.send(JSON.stringify({ type: 'connected' }));
    } else {
      deniedSockets.push(socket.url());
      socket.close({ code: 1008, reason: 'Denied by issue1369 isolation' });
    }
  });
  context.on('response', response => {
    if (!continued.has(response.url()) && !fulfilled.has(response.url())) escapedHttp.push(response.url());
  });
  page.on('websocket', socket => {
    socket.on('framereceived', () => {
      if (!socketRoutes.has(socket.url())) escapedSockets.push(socket.url());
    });
  });
  page.on('pageerror', error => { browserErrors.push(error.message); });

  try {
    await test.step('establish isolated real-App baseline premise', async () => {
      await page.goto('/');
      await page.waitForFunction(() => Boolean((window as unknown as BaselineWindow).__store));
      await expect.poll(authority).toMatchObject({
        connected: true, generation, sequence: 1, drops: 0, agents: ['alpha'], alphaCallsign: 'Alpha',
        mainViewer: 'canvas', selectedAgent: null, activeThreadId: null,
        windowWidth: 1440, windowHeight: 1000, finePointer: true,
      });
      expect(snapshots.length, 'snapshot producer delivered').toBeGreaterThan(0);
      measurements.snapshotConsumer = await authority();
      const isolation = await page.evaluate(() => (window as unknown as BaselineWindow).__issue1369);
      expect(isolation.installed).toBe(true);
      expect(isolation.initialStorage, 'fresh browser context').toEqual([]);
      await page.getByRole('button', { name: 'Got it', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Welcome to ProbOS' })).toHaveCount(0);
      const game = page.getByRole('region', { name: 'Tic-Tac-Toe game', exact: true });
      await expect(game.getByRole('alert')).toBeVisible();
      await game.getByRole('button', { name: 'Close game', exact: true }).click();
      await page.getByRole('button', { name: /^BRIDGE(?: \(\d+\))?$/ }).click();
      await page.getByRole('button', { name: /^Personnel(?: \(\d+\))?$/ }).click();
      await page.getByTestId('crew-action').click();
      await expect.poll(() => fixtureReads).toContain('GET /api/ontology/crew-manifest');
      await page.getByRole('button', { name: 'Close Bridge', exact: true }).click();
      const roster = page.getByText("SHIP'S COMPLEMENT", { exact: true }).locator('../..');
      await roster.getByText('Alpha', { exact: true }).click();
      await roster.getByText('x', { exact: true }).click();
      await expect(page.getByText("SHIP'S COMPLEMENT", { exact: true })).toHaveCount(0);
      await expect.poll(authority).toMatchObject({
        selectedAgent: 'alpha', activeThreadId: null, activeProfileThreadId: null, alphaThread: null,
      });
      await expect.poll(() => fixtureReads).toContain('GET /api/agent/alpha/profile');
      await expect.poll(() => fixtureReads).toContain('GET /api/agent/alpha/chat/history');
      const drawer = page.getByTestId('artifact-drawer');
      await expect(drawer).toBeVisible();
      const content = drawer.locator('..');
      const profile = content.locator('../..');
      measurements.profile = await bounds(profile);
      measurements.content = await bounds(content);
      measurements.drawer = await bounds(drawer);
      measurements.transcript = await bounds(page.getByTestId('chat-transcript'));
      measurements.input = await bounds(page.getByPlaceholder('Message...', { exact: true }));
      measurements.authority = await authority();
      await expect(page.locator('canvas')).toHaveCount(1);
      const profileBox = await profile.boundingBox();
      const contentBox = await content.boundingBox();
      expect(profileBox).not.toBeNull();
      expect(contentBox).not.toBeNull();
      expect(Math.abs(profileBox!.width - 420)).toBeLessThanOrEqual(1);
      expect(Math.abs(contentBox!.width - 418)).toBeLessThanOrEqual(1);
      expect(escapedHttp).toEqual([]);
      expect(escapedSockets).toEqual([]);
      expect(deniedSockets.every(value => {
        const url = new URL(value);
        return url.origin === socketOrigin && url.pathname === '/api/agent/avatar-telemetry/stream';
      }), 'Only the expected unadmitted avatar telemetry socket is denied').toBe(true);
      premiseEstablished = true;
      await testInfo.attach('baseline-setup-and-bounds', {
        body: JSON.stringify({ premiseEstablished, measurements, snapshots, fixtureReads }, null, 2),
        contentType: 'application/json',
      });
      await testInfo.attach('baseline-initial-layout', { body: await page.screenshot(), contentType: 'image/png' });
    });

    await test.step('require usable geometry and real Send hit target', async () => {
      const transcript = await page.getByTestId('chat-transcript').boundingBox();
      const input = page.getByPlaceholder('Message...', { exact: true });
      const inputBox = await input.boundingBox();
      expect.soft(transcript!.width, 'transcript width after established premise').toBeGreaterThanOrEqual(280);
      expect.soft(transcript!.height, 'transcript visible height').toBeGreaterThanOrEqual(120);
      expect.soft(inputBox!.width, 'composer input width').toBeGreaterThanOrEqual(120);
      await input.fill(messageText);
      const profile = page.getByTestId('artifact-drawer').locator('../../..');
      const send = profile.getByRole('button', { name: 'Send', exact: true });
      await expect(send).toBeEnabled();
      measurements.send = await bounds(send);
      const hit = await send.evaluate(element => {
        const rect = element.getBoundingClientRect();
        const points = [[rect.left + rect.width / 4, rect.top + rect.height / 2],
          [rect.right - rect.width / 4, rect.top + rect.height / 2],
          [rect.left + rect.width / 2, rect.top + rect.height / 2]];
        return points.map(([x, y]) => ({
          x, y, insideViewport: rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight,
          hitsSend: element.contains(document.elementFromPoint(x, y)),
        }));
      });
      measurements.sendHitTargets = hit;
      expect(hit.every(point => point.insideViewport && point.hitsSend), 'Send is the actual pointer target').toBe(true);
      await send.click();
      await expect.poll(() => sends.length).toBe(1);
      await expect.poll(authority).toMatchObject({ selectedAgent: 'alpha', alphaThread: thread.id });
      await expect(page.getByTestId('chat-transcript')).toContainText(replyText);
      await expect.poll(() => fixtureReads).toContain(`GET /api/artifacts/thread/${thread.id}?limit=1001`);
      await expect(page.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    });
  } finally {
    const isolation = await page.evaluate(() => ({
      capabilities: (window as unknown as BaselineWindow).__issue1369,
      activeMedia: [...document.querySelectorAll('audio, video')].filter(element => {
        const media = element as HTMLMediaElement;
        return media.srcObject !== null || !media.paused;
      }).map(element => element.tagName),
    })).catch(error => ({ unavailable: String(error) }));
    await testInfo.attach('baseline-evidence', {
      body: JSON.stringify({
        premiseEstablished, measurements, snapshots, fixtureReads, sends, isolation,
        continued: [...continued], fulfilled: [...fulfilled], deniedHttp, deniedSockets,
        escapedHttp, escapedSockets, browserErrors, errors: testInfo.errors,
      }, null, 2),
      contentType: 'application/json',
    });
    if (!page.isClosed()) {
      await testInfo.attach('baseline-final-layout', {
        body: await page.screenshot({ timeout: 5_000 }), contentType: 'image/png',
      });
    }
    expect(escapedHttp, 'no HTTP response escaped the allowlist').toEqual([]);
    expect(escapedSockets, 'no WebSocket frame escaped context routing').toEqual([]);
    expect(isolation).toHaveProperty('activeMedia', []);
    expect(isolation).toHaveProperty('capabilities.installed', true);
    expect(isolation).toHaveProperty('capabilities.blockedCapabilities', ['serviceWorker.register']);
    expect(context.serviceWorkers()).toEqual([]);
    expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
    expect(browserErrors).toEqual([]);
    expect(sends).toHaveLength(1);
    expect([...new Set(deniedHttp)].sort()).toEqual([
      'GET /api/capability-requests?status=pending',
      'GET /api/config',
      'GET /api/perception/budget',
      'GET /api/recreation/active',
      'GET /api/skill-requests?status=pending',
      'GET /api/system/extensions',
      'GET /api/voice/health',
      'GET /api/wardroom/dms',
    ]);
  }
});

const mobileProbeViewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1440, height: 1000 },
  { width: 1920, height: 1080 },
];

async function visibleBounds(locator: Locator): Promise<{
  width: number; height: number; visibleWidth: number; visibleHeight: number;
}> {
  return locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    let left = Math.max(0, rect.left);
    let right = Math.min(innerWidth, rect.right);
    let top = Math.max(0, rect.top);
    let bottom = Math.min(innerHeight, rect.bottom);
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      const clip = parent.getBoundingClientRect();
      if (style.overflowX !== 'visible') {
        left = Math.max(left, clip.left);
        right = Math.min(right, clip.right);
      }
      if (style.overflowY !== 'visible') {
        top = Math.max(top, clip.top);
        bottom = Math.min(bottom, clip.bottom);
      }
    }
    return {
      width: rect.width, height: rect.height,
      visibleWidth: Math.max(0, right - left), visibleHeight: Math.max(0, bottom - top),
    };
  });
}

async function pointerHits(locator: Locator): Promise<{
  x: number; y: number; insideViewport: boolean; hitsTarget: boolean;
}[]> {
  return locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return [0.25, 0.5, 0.75].map(fraction => {
      const x = rect.left + rect.width * fraction;
      const y = rect.top + rect.height / 2;
      return {
        x, y, insideViewport: rect.width > 0 && rect.height > 0
          && rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight,
        hitsTarget: element.contains(document.elementFromPoint(x, y)),
      };
    });
  });
}

test.describe('MobileShell mounted-host boundary', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  for (const viewport of mobileProbeViewports) {
    const cell = `MobileShell / coarse 390x844 entry -> ${viewport.width}x${viewport.height}`;
    test(`matrix: ${cell} native DM and real mesh controls`, async ({ page, context, baseURL }, testInfo) => {
      if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
      const yeo = mkAgent('yeo', 'Yeo');
      const dm = mkThread('mobile-probe-yeo', 'Yeo mobile boundary probe', [yeo.id]);
      const text = `Viewport ${viewport.width}x${viewport.height} message`;
      const reply = `Yeo fixture received ${text}.`;
      const hydrated = 'Persisted fixture row proves GET hydration after native Send.';
      const persisted = [
        mkMessage('mobile-captain', dm.id, 'captain', 'captain', text),
        mkMessage('mobile-reply', dm.id, yeo.id, 'agent', reply),
        mkMessage('mobile-hydration', dm.id, yeo.id, 'agent', hydrated),
      ];
      let sent = false;
      const fixtures: Issue1369IsolationOptions['fixtures'] = new Map([
        ['GET /api/config/avatars-enabled', () => ({ enabled: false })],
        ['GET /api/agent/yeo/chat/history', () => ({ memories: [] })],
        ['GET /api/threads', () => ({ threads: sent ? [dm] : [] })],
        ['GET /api/threads/summaries', () => ({ summaries: {} })],
        [`GET /api/threads/${dm.id}/messages?limit=200`, () => sent
          ? { thread_id: dm.id, messages: persisted } : undefined],
        [`GET /api/artifacts/thread/${dm.id}?limit=1001`, () => ({ thread_id: dm.id, artifacts: [] })],
        ['POST /api/agent/yeo/chat', request => {
          if (sent || !isDeepStrictEqual(request.postDataJSON(), {
            message: text, history: [], attachment_ids: [],
          })) return undefined;
          sent = true;
          return { response: reply, thread_id: dm.id, title: dm.title };
        }],
      ]);
      const isolation = await installIssue1369Isolation(context, { baseURL, agents: [yeo], generation, assetPaths, fixtures });
      const measurements: Record<string, unknown> = {};
      const stages: string[] = [];
      const authority = () => page.evaluate(() => {
        const state = (window as unknown as BaselineWindow).__store.getState();
        return {
          connected: state.connected, generation: state.liveGeneration, sequence: state.liveSequence,
          drops: state.liveDropCount, agents: [...state.agents].map(([id, agent]) => [id, agent.callsign]),
          selectedAgent: state.activeProfileAgent, activeProfileThreadId: state.activeProfileThreadId,
          activeThreadId: state.activeThreadId, yeoThread: state.threadIdByAgent.get('yeo') ?? null,
          timeOrigin: performance.timeOrigin, hash: location.hash,
          width: innerWidth, height: innerHeight, coarsePointer: matchMedia('(pointer: coarse)').matches,
        };
      });
      const bank = async (stage: string): Promise<void> => {
        stages.push(stage);
        await testInfo.attach(`${viewport.width}x${viewport.height}-${stage}`, {
          body: await page.screenshot(), contentType: 'image/png',
        });
        await testInfo.attach(`${viewport.width}x${viewport.height}-${stage}-bounds`, {
          body: JSON.stringify({ cell, stages, measurements, authority: await authority() }, null, 2),
          contentType: 'application/json',
        });
      };
      const measureChat = async (stage: string): Promise<void> => {
        const transcript = await visibleBounds(page.getByTestId('chat-transcript'));
        const input = await visibleBounds(page.getByPlaceholder('Message...', { exact: true }));
        const documentWidth = await page.evaluate(() => ({
          viewport: innerWidth, root: document.documentElement.scrollWidth, body: document.body.scrollWidth,
        }));
        measurements[stage] = { transcript, input, documentWidth };
        await bank(stage);
        expect(transcript.width).toBeGreaterThanOrEqual(280);
        expect(transcript.visibleWidth).toBeGreaterThanOrEqual(280);
        expect(transcript.visibleHeight).toBeGreaterThanOrEqual(120);
        expect(input.width).toBeGreaterThanOrEqual(120);
        expect(input.visibleWidth).toBeGreaterThanOrEqual(120);
        expect(documentWidth.root).toBeLessThanOrEqual(documentWidth.viewport);
        expect(documentWidth.body).toBeLessThanOrEqual(documentWidth.viewport);
      };
      try {
        await test.step(`${cell}: establish actual mobile entry and snapshot consumer`, async () => {
          await page.goto('/');
          await expect(page.getByTestId('mobile-shell')).toBeVisible();
          await page.waitForFunction(() => Boolean((window as unknown as BaselineWindow).__store));
          await expect.poll(authority).toMatchObject({
            connected: true, generation, sequence: 1, drops: 0, agents: [['yeo', 'Yeo']],
            selectedAgent: null, activeThreadId: null, activeProfileThreadId: null, yeoThread: null,
            width: 390, height: 844, coarsePointer: true, hash: '',
          });
          expect(isolation.snapshots.length).toBeGreaterThan(0);
          const capabilities = await page.evaluate(() => (window as unknown as BaselineWindow).__issue1369);
          expect(capabilities).toMatchObject({ installed: true, initialStorage: [], blockedCapabilities: ['serviceWorker.register'] });
          expect(context.serviceWorkers()).toEqual([]);
          expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
          await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
            .toContain('GET /api/agent/yeo/chat/history');
          await expect(page.getByTestId('empty-chat-add-people')).toBeVisible();
          await expect(page.locator('canvas')).toHaveCount(0);
          measurements.entry = await authority();
          const timeOrigin = (await authority()).timeOrigin;
          await page.setViewportSize(viewport);
          await expect.poll(authority).toMatchObject({ ...viewport, coarsePointer: true, timeOrigin });
          await expect(page.getByTestId('mobile-shell')).toBeVisible();
          await measureChat('no-thread');
        });
        await test.step(`${cell}: native touch Send crosses exact route and GET hydration`, async () => {
          await page.getByPlaceholder('Message...', { exact: true }).fill(text);
          const send = page.getByTestId('mobile-shell-chat').getByRole('button', { name: 'Send', exact: true });
          await expect(send).toBeEnabled();
          const hits = await pointerHits(send);
          measurements.sendHits = hits;
          expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
          await send.tap();
          await expect.poll(() => isolation.deliveries.filter(delivery => delivery.key === 'POST /api/agent/yeo/chat'))
            .toHaveLength(1);
          await expect.poll(authority).toMatchObject({ yeoThread: dm.id, selectedAgent: null });
          await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
            .toContain(`GET /api/threads/${dm.id}/messages?limit=200`);
          await expect(page.getByTestId('chat-transcript')).toContainText(hydrated);
          await expect(page.getByTestId('chat-transcript')).toContainText(reply);
          await measureChat('hydrated-dm');
        });
        await test.step(`${cell}: real mesh paint and keyboard chat return`, async () => {
          const toggle = page.getByRole('button', { name: 'MESH', exact: true });
          const hits = await pointerHits(toggle);
          measurements.meshToggleHits = hits;
          expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
          await toggle.tap();
          const mesh = page.getByTestId('mobile-mesh');
          await expect(mesh).toBeVisible();
          await expect(mesh.getByTestId('mobile-mesh-node')).toHaveCount(1);
          const screenshot = await mesh.screenshot();
          await testInfo.attach(`${viewport.width}x${viewport.height}-real-mobile-mesh`, {
            body: screenshot, contentType: 'image/png',
          });
          const paint = await page.evaluate(async bytes => {
            const image = await createImageBitmap(new Blob([new Uint8Array(bytes)], { type: 'image/png' }));
            try {
              const canvas = document.createElement('canvas');
              canvas.width = image.width;
              canvas.height = image.height;
              const rendering = canvas.getContext('2d');
              if (!rendering) throw new Error('Screenshot pixel decoder requires a 2D context');
              rendering.drawImage(image, 0, 0);
              const pixels = rendering.getImageData(0, 0, image.width, image.height).data;
              let nonBackgroundPixels = 0;
              for (let offset = 0; offset < pixels.length; offset += 4) {
                if (pixels[offset + 3] > 0 && (Math.abs(pixels[offset] - 10) > 16
                  || Math.abs(pixels[offset + 1] - 10) > 16 || Math.abs(pixels[offset + 2] - 20) > 16)) {
                  nonBackgroundPixels += 1;
                }
              }
              return { width: image.width, height: image.height, nonBackgroundPixels };
            } finally { image.close(); }
          }, [...screenshot]);
          measurements.mesh = { bounds: await bounds(mesh), paint };
          await bank('mesh-painted');
          expect(paint.width).toBe(viewport.width);
          expect(paint.nonBackgroundPixels).toBeGreaterThan(100);
          const chat = page.getByRole('button', { name: 'CHAT', exact: true });
          await chat.focus();
          await page.keyboard.press('Enter');
          await expect(chat).toBeFocused();
          await expect(chat).toHaveAttribute('aria-pressed', 'true');
          await expect(page.getByTestId('chat-transcript')).toContainText(hydrated);
          measurements.keyboardChatReturn = { focused: await chat.evaluate(element => element === document.activeElement) };
          await measureChat('keyboard-chat-return');
        });
        await test.step(`${cell}: keyboard mesh entry and touch return preserve Yeo identity`, async () => {
          const meshToggle = page.getByRole('button', { name: 'MESH', exact: true });
          await meshToggle.focus();
          await page.keyboard.press('Space');
          await expect(meshToggle).toHaveAttribute('aria-pressed', 'true');
          await expect(meshToggle).toBeFocused();
          const mesh = page.getByTestId('mobile-mesh');
          await expect(mesh).toBeVisible();
          await expect(mesh.getByTestId('mobile-mesh-node')).toHaveCount(1);
          await expect.poll(authority).toMatchObject({ agents: [['yeo', 'Yeo']], yeoThread: dm.id });
          const chat = page.getByRole('button', { name: 'CHAT', exact: true });
          const hits = await pointerHits(chat);
          measurements.chatToggleHits = hits;
          expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
          await chat.tap();
          await expect(chat).toHaveAttribute('aria-pressed', 'true');
          await expect(page.getByTestId('mobile-shell').locator(':scope > div').first().getByText('Yeo', { exact: true })).toBeVisible();
          await expect(page.getByTestId('chat-transcript')).toContainText(hydrated);
          await expect(page.getByTestId('chat-transcript')).toContainText(reply);
          await expect.poll(authority).toMatchObject({ agents: [['yeo', 'Yeo']], yeoThread: dm.id });
          measurements.mobileIdentity = { callsign: 'Yeo', agentId: yeo.id, threadId: dm.id, pickingClaimed: false };
          await measureChat('touch-chat-return');
        });
      } finally {
        const rendered = await page.evaluate(() => ({
          capabilities: (window as unknown as BaselineWindow).__issue1369,
          controls: [...document.querySelectorAll('button, [role], [tabindex]')].map(element => ({
            tag: element.tagName, text: element.textContent, label: element.getAttribute('aria-label'),
            role: element.getAttribute('role'), tabindex: element.getAttribute('tabindex'),
          })),
          activeMedia: [...document.querySelectorAll('audio, video')].filter(element => {
            const media = element as HTMLMediaElement;
            return media.srcObject !== null || !media.paused;
          }).map(element => element.tagName),
        })).catch(error => ({ unavailable: String(error) }));
        const finalAuthority = await authority().catch(error => ({ unavailable: String(error) }));
        await testInfo.attach(`${viewport.width}x${viewport.height}-mobile-boundary-evidence`, {
          body: JSON.stringify({ cell, stages, measurements, isolation, rendered, finalAuthority, errors: testInfo.errors }, null, 2),
          contentType: 'application/json',
        });
        if (!page.isClosed()) {
          await testInfo.attach(`${viewport.width}x${viewport.height}-mobile-final`, {
            body: await page.screenshot({ timeout: 5_000 }), contentType: 'image/png',
          });
        }
        expect(isolation.escapedHttp).toEqual([]);
        expect(isolation.escapedSockets).toEqual([]);
        expect(isolation.deniedSockets).toEqual([]);
        expect(isolation.browserErrors).toEqual([]);
        expect(rendered).toHaveProperty('activeMedia', []);
        expect(rendered).toHaveProperty('capabilities.installed', true);
        expect(rendered).toHaveProperty('capabilities.blockedCapabilities', ['serviceWorker.register']);
        expect(context.serviceWorkers()).toEqual([]);
        expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
      }
    });
  }
});

interface ViewportDM {
  agent: AgentFixture;
  thread: ThreadFixture;
  initialMessages: MessageFixture[];
  text: string;
  reply: string;
  hydrated: string;
  initiallySaved: boolean;
}

const artifactText = 'Synthetic local report.\nNo network, model, media, or production data.\n';
const artifactName = `${'long-local-report-'.repeat(8)}.txt`;

function viewportArtifact(threadId: string) {
  return {
    id: `artifact-${threadId}`, thread_id: threadId, name: artifactName, version: 1,
    content_hash: createHash('sha256').update(artifactText).digest('hex'), mime: 'text/plain',
    size_bytes: Buffer.byteLength(artifactText), created_by: 'alpha', created_at: 2000, supersedes: null,
  };
}

function viewportDMs(cell: string): ViewportDM[] {
  return [
    { agent: mkAgent('yeo', 'Yeo'), state: 'no-thread', initiallySaved: false },
    { agent: alpha, state: 'empty', initiallySaved: true },
    { agent: mkAgent('beta', 'Beta', 'science'), state: 'long', initiallySaved: true },
  ].map(({ agent, state, initiallySaved }) => {
    const dm = mkThread(`viewport-${state}-${agent.id}`, `${agent.callsign} ${state} ${'saved conversation title '.repeat(8)}`, [agent.id]);
    return {
      agent, thread: dm, initiallySaved,
      initialMessages: state === 'long' ? Array.from({ length: 48 }, (_, index) => mkMessage(
        `saved-${index}`, dm.id, index % 2 ? agent.id : 'captain', index % 2 ? 'agent' : 'captain',
        `Saved row ${index}: ${'A long persisted message that must wrap inside the conversation. '.repeat(12)}${index === 47 ? `\n[Artifact: ${artifactName} v1 - 2 lines, text/plain]` : ''}`,
        1000 + index,
      )) : [],
      text: `${cell}: ${state} native Send`,
      reply: `${agent.callsign} accepted ${state} Send.`,
      hydrated: `${cell}: ${state} GET-only persistence receipt`,
    };
  });
}

function viewportFixtures(dms: ViewportDM[]): Issue1369IsolationOptions['fixtures'] {
  const sent = new Set<string>();
  const list = (): { threads: ThreadFixture[] } => ({
    threads: dms.filter(dm => dm.initiallySaved || sent.has(dm.thread.id)).map(dm => dm.thread),
  });
  const fixtures = new Map<string, (request: import('@playwright/test').Request) => unknown>([
    ['GET /api/config/avatars-enabled', () => ({ enabled: false })],
    ['GET /api/threads', list],
    ['GET /api/threads?include_archived=false&limit=100', list],
    ['GET /api/projects?include_archived=false&limit=100', () => ({ projects: [] })],
    ['GET /api/threads/summaries', () => ({ summaries: {} })],
  ]);
  for (const dm of dms) {
    const profile: typeof telemetry.profile = {
      ...telemetry.profile, id: dm.agent.id, callsign: dm.agent.callsign, displayName: dm.agent.callsign,
      sovereignId: `sovereign-${dm.agent.id}`, department: dm.agent.department,
      memoryCountMetadata: { ...telemetry.profile.memoryCountMetadata, subjectId: `sovereign-${dm.agent.id}` },
    };
    fixtures.set(`GET /api/agent/${dm.agent.id}/profile`, () => profile);
    fixtures.set(`GET /api/agent/${dm.agent.id}/chat/history`, () => ({ memories: [] }));
    fixtures.set(`GET /api/threads/${dm.thread.id}`, () => dm.initiallySaved || sent.has(dm.thread.id) ? dm.thread : undefined);
    fixtures.set(`GET /api/threads/${dm.thread.id}/messages?limit=200`, () => {
      if (!dm.initiallySaved && !sent.has(dm.thread.id)) return undefined;
      const persisted: MessageFixture[] = sent.has(dm.thread.id) ? [
        ...dm.initialMessages,
        mkMessage(`${dm.thread.id}-captain`, dm.thread.id, 'captain', 'captain', dm.text, 2000),
        mkMessage(`${dm.thread.id}-reply`, dm.thread.id, dm.agent.id, 'agent', dm.reply, 2001),
        mkMessage(`${dm.thread.id}-get-only`, dm.thread.id, dm.agent.id, 'agent', dm.hydrated, 2002),
      ] : dm.initialMessages;
      return { thread_id: dm.thread.id, messages: persisted };
    });
    const artifact = viewportArtifact(dm.thread.id);
    const hasArtifact = dm.initialMessages.some(message => message.body.includes(`[Artifact: ${artifactName} v1`));
    fixtures.set(`GET /api/artifacts/thread/${dm.thread.id}?limit=1001`, () => ({ thread_id: dm.thread.id, artifacts: hasArtifact ? [{ ...artifact, _pinned_from_project: false }] : [] }));
    if (hasArtifact) {
      fixtures.set(`GET /api/artifacts/${artifact.id}`, () => artifact);
      fixtures.set(`GET /api/artifacts/${artifact.id}/content`, () => new Response(artifactText, { headers: { 'Content-Type': 'text/plain' } }));
    }
    fixtures.set(`POST /api/agent/${dm.agent.id}/chat`, request => {
      const expected = {
        message: dm.text, history: [], attachment_ids: [],
        ...(dm.initiallySaved ? { thread_id: dm.thread.id } : {}),
      };
      if (sent.has(dm.thread.id) || !isDeepStrictEqual(request.postDataJSON(), expected)) return undefined;
      sent.add(dm.thread.id);
      return { response: dm.reply, thread_id: dm.thread.id, title: dm.thread.title };
    });
  }
  return fixtures;
}

function taskViewportFixture(cell: string) {
  const dms = viewportDMs(cell);
  let room = mkThread('viewport-group', 'Yeo, Alpha', ['yeo', 'alpha']);
  const parentId = 'viewport-group-task';
  const goal = `Review the local synthetic report. ${'Keep every decision scoped to this task and preserve its evidence. '.repeat(8)}`.trim();
  const criteria = ['The local report is readable.', 'The Captain can confirm the submitted checklist step.'];
  const deliverable = 'A synthetic plain-text report with no external resources.';
  const decision = `Confirm the report. ${'Verify the bounded local output and retain the approval evidence. '.repeat(10)}`;
  const session: CrewSessionDetailProjection = {
    task_id: parentId, thread_id: room.id, goal, origin: 'captain', originator_id: 'captain',
    facilitator_id: 'yeo', owner_ids: ['yeo', 'alpha'], state: 'executing', revision: 1,
    success_criteria: criteria, expected_deliverable: deliverable,
    timestamps: { created_at: 1, transitioned_at: 2, started_at: 2, first_result_at: null, verified_at: null, completed_at: null },
    progress: { total: 1, done: 0, failed: 0, active: 1, active_child: { id: 'viewport-child', title: decision, status: 'in_progress', owner_id: 'alpha' } },
    last_result_summary: '', blocker: null, result: null, verification: null, duplicate_resume_count: 0,
  };
  let steps: TodoStep[] = [{ label: decision, status: 'submitted', assigned_to: 'alpha', submitted_by: 'alpha', confirmed_by: null, note: 'Synthetic report awaiting Captain confirmation.' }];
  let created = false;
  let started = false;
  let confirmed = false;
  let renamed = false;
  let sent = false;
  let sidebarCreated = false;
  const longTitle = `Viewport group ${'local review and evidence '.repeat(10)}`.trim();
  const text = `${cell}: ${'A native group message remains scoped to this room. '.repeat(10)}`.trim();
  const hydrated = `${cell}: group GET-only persistence receipt`;
  const sidebarThread = mkThread('viewport-sidebar-yeo', 'Yeo', ['yeo']);
  const rows = Array.from({ length: 24 }, (_, index) => mkMessage(
    `group-row-${index}`, room.id, index % 2 ? 'alpha' : 'yeo', 'agent',
    `Group persisted row ${index}: ${'This synthetic conversation stays inside the created group. '.repeat(12)}`, 1000 + index,
  ));
  const fixtures = new Map(viewportFixtures(dms));
  const list = () => ({ threads: [...dms.filter(dm => dm.initiallySaved).map(dm => dm.thread), ...(created ? [room] : []), ...(sidebarCreated ? [sidebarThread] : [])] });
  fixtures.set('GET /api/threads', list);
  fixtures.set('GET /api/threads?include_archived=false&limit=100', list);
  fixtures.set('POST /api/threads', request => {
    if (created && !sidebarCreated && isDeepStrictEqual(request.postDataJSON(), { title: 'Yeo', participants: ['yeo'] })) {
      sidebarCreated = true;
      return sidebarThread;
    }
    if (created || !isDeepStrictEqual(request.postDataJSON(), { title: 'Yeo, Alpha', participants: ['yeo', 'alpha'] })) return undefined;
    created = true;
    return room;
  });
  fixtures.set(`GET /api/threads/${room.id}`, () => created ? room : undefined);
  fixtures.set(`PATCH /api/threads/${room.id}`, request => {
    if (!created || renamed || !isDeepStrictEqual(request.postDataJSON(), { title: longTitle, title_locked: true })) return undefined;
    renamed = true;
    room = { ...room, title: longTitle, metadata: { title_locked: true } };
    return room;
  });
  fixtures.set(`POST /api/threads/${room.id}/messages`, request => {
    const body = request.postDataJSON();
    const clientId = body?.metadata?.client_message_id;
    if (!created || sent || typeof clientId !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(clientId)
      || !isDeepStrictEqual(body, { author_id: 'captain', role: 'captain', body: text, attachment_ids: [], metadata: { client_message_id: clientId } })) return undefined;
    sent = true;
    const captain = { ...mkMessage('group-native-send', room.id, 'captain', 'captain', text, 2000), metadata: { client_message_id: clientId } };
    rows.push(captain, mkMessage('group-get-only', room.id, 'alpha', 'agent', hydrated, 2001));
    return { ...captain, per_agent_replies: [] };
  });
  fixtures.set(`GET /api/threads/${sidebarThread.id}`, () => sidebarCreated ? sidebarThread : undefined);
  fixtures.set(`GET /api/threads/${sidebarThread.id}/messages?limit=200`, () => sidebarCreated ? { thread_id: sidebarThread.id, messages: [] } : undefined);
  fixtures.set(`GET /api/artifacts/thread/${sidebarThread.id}?limit=1001`, () => sidebarCreated ? { thread_id: sidebarThread.id, artifacts: [] } : undefined);
  fixtures.set(`GET /api/threads/${room.id}/messages?limit=200`, () => created ? { thread_id: room.id, messages: [...rows] } : undefined);
  fixtures.set(`GET /api/threads/${room.id}/inputs`, () => created ? { inputs: [] } : undefined);
  const output = viewportArtifact(room.id);
  fixtures.set(`GET /api/artifacts/thread/${room.id}?limit=1001`, () => created ? { thread_id: room.id, artifacts: [{ ...output, _pinned_from_project: false }] } : undefined);
  fixtures.set(`GET /api/artifacts/${output.id}/content`, () => created ? new Response(artifactText, { headers: { 'Content-Type': 'text/plain' } }) : undefined);
  fixtures.set(`POST /api/threads/${room.id}/start-work`, request => {
    if (!created || started || !isDeepStrictEqual(request.postDataJSON(), {
      goal, success_criteria: criteria, expected_deliverable: deliverable, retry_blocked: false,
    })) return undefined;
    started = true;
    room = { ...room, task_id: parentId };
    const result: StartWorkResult = {
      disposition: 'created', parent_id: parentId, thread_id: room.id, state: session.state,
      facilitator_id: 'yeo', owner_ids: ['yeo', 'alpha'], duplicate_resume_count: 0, scheduled: true, session,
    };
    return result;
  });
  fixtures.set(`GET /api/crew-tasks/${parentId}`, () => started ? { session } : undefined);
  fixtures.set(`GET /api/work-items/${parentId}/steps?limit=1001`, () => started ? { steps, gate_completion: true } : undefined);
  fixtures.set(`PATCH /api/work-items/${parentId}/steps/0`, request => {
    if (!started || confirmed || !isDeepStrictEqual(request.postDataJSON(), { status: 'done', actor: 'captain' })) return undefined;
    confirmed = true;
    steps = [{ ...steps[0], status: 'done', confirmed_by: 'captain' }];
    return { steps, gate_completion: true };
  });
  return { fixtures, dms, roomId: room.id, parentId, goal, criteria, deliverable, decision, longTitle, text, hydrated, sidebarThread };
}

const conversationHosts = [
  { name: 'FullApp fine', route: '/', touch: false, compact: false },
  { name: 'FullApp touch', route: '/#desktop', touch: true, compact: false },
  { name: 'Compact touch', route: '/#compact', touch: true, compact: true },
] as const;

const taskHosts = [
  ...conversationHosts.map(host => ({ ...host, mobile: false })),
  { name: 'MobileShell coarse', route: '/', touch: true, compact: false, mobile: true },
];

for (const compact of [false, true]) {
  test.describe(`${compact ? 'CompactApp' : 'FullApp'} live artifact`, () => {
    test.use({ hasTouch: compact, isMobile: compact, viewport: { width: 390, height: 844 } });
    test('live artifact: actual Send arrival stays in rail until same-id card activation', async ({ page, context, baseURL }, testInfo) => {
      if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
      const dm = viewportDMs('live artifact')[0];
      dm.initiallySaved = true;
      dm.reply = `Produced local output.\n[Artifact: ${artifactName} v1 - 1 lines, text/plain]`;
      const artifact = viewportArtifact(dm.thread.id);
      const fixtures = new Map(viewportFixtures([dm]));
      let arrived = false;
      const sendKey = `POST /api/agent/${dm.agent.id}/chat`;
      const sendFixture = fixtures.get(sendKey)!;
      fixtures.set(sendKey, async request => {
        const response = await sendFixture(request);
        if (response !== undefined) arrived = true;
        return response;
      });
      fixtures.set(`GET /api/artifacts/thread/${dm.thread.id}?limit=1001`, () => ({ thread_id: dm.thread.id, artifacts: arrived ? [{ ...artifact, _pinned_from_project: false }] : [] }));
      fixtures.set(`GET /api/artifacts/${artifact.id}/content`, () => new Response(artifactText, { headers: { 'Content-Type': 'text/plain' } }));
      const isolation = await installIssue1369Isolation(context, { baseURL, agents: [dm.agent], generation, assetPaths, fixtures });
      const evidence: Record<string, unknown> = {};
      try {
        await page.goto(compact ? '/#compact' : '/');
        if (compact) {
          await expect(page.getByTestId('compact-conversation')).toBeVisible();
          await page.getByRole('button', { name: 'Expand sidebar', exact: true }).tap();
          await page.getByTestId(`thread-row-${dm.thread.id}`).tap();
        } else {
          await page.getByRole('button', { name: 'Got it', exact: true }).click();
          await page.getByRole('button', { name: 'Close game', exact: true }).click();
          await page.getByTestId('crew-collab-pill').click();
          await page.getByTestId(`chat-row-${dm.thread.id}`).click();
        }
        const drawer = page.getByTestId('artifact-drawer');
        await expect(drawer).toHaveAttribute('data-thread-id', dm.thread.id);
        await expect(drawer).toHaveAttribute('data-collapsed', 'true');
        const state = () => page.evaluate(threadId => {
          const current = (window as unknown as { __store: { getState: () => BrowserState & {
            selectedArtifactId: string | null; artifactDrawerCollapsed: boolean; artifactsByThread: Map<string, unknown[]>;
          } } }).__store.getState();
          return { selected: current.selectedArtifactId, collapsed: current.artifactDrawerCollapsed, count: current.artifactsByThread.get(threadId)?.length };
        }, dm.thread.id);
        await expect.poll(state).toEqual({ selected: null, collapsed: true, count: 0 });
        expect(arrived).toBe(false);
        await page.getByPlaceholder('Message...', { exact: true }).fill(dm.text);
        const send = page.getByRole('button', { name: 'Send', exact: true });
        const hits = await pointerHits(send);
        expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
        if (compact) await send.tap();
        else await send.click();
        await expect.poll(() => isolation.deliveries.filter(value => value.key === sendKey)).toHaveLength(1);
        const card = page.getByTestId('chat-transcript').getByRole('button', { name: `Open ${artifactName} v1`, exact: true });
        await expect(card).toBeEnabled();
        await expect.poll(state).toEqual({ selected: artifact.id, collapsed: false, count: 1 });
        await expect(drawer).toHaveAttribute('data-collapsed', 'true');
        await expect(page.getByRole('dialog', { name: 'Artifacts', exact: true })).toHaveCount(0);
        const chat = await visibleBounds(page.getByTestId('chat-transcript'));
        expect(chat.visibleWidth).toBeGreaterThanOrEqual(280);
        expect(chat.visibleHeight).toBeGreaterThanOrEqual(120);
        evidence.automaticArrival = { state: await state(), chat, sendHits: hits };
        await testInfo.attach('live-arrival-keeps-conversation', { body: await page.screenshot(), contentType: 'image/png' });
        await card.scrollIntoViewIfNeeded();
        const cardHits = await pointerHits(card);
        expect(cardHits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
        if (compact) await card.tap();
        else await card.click();
        await expect(drawer).toHaveAttribute('data-collapsed', 'false');
        await expect(drawer).toContainText('Synthetic local report.');
        await expect(page.getByRole('button', { name: 'Collapse artifacts', exact: true })).toBeFocused();
        expect(await state()).toEqual({ selected: artifact.id, collapsed: false, count: 1 });
        await page.keyboard.press('Escape');
        await expect(card).toBeFocused();
        await expect(drawer).toHaveAttribute('data-collapsed', 'true');
        evidence.explicitOpen = { cardHits, selectedUnchanged: artifact.id, focusReturned: true };
        await testInfo.attach('live-artifact-focus-return', { body: await page.screenshot(), contentType: 'image/png' });
      } finally {
        await testInfo.attach('live-artifact-evidence', { body: JSON.stringify({ compact, evidence, isolation, errors: testInfo.errors }, null, 2), contentType: 'application/json' });
        expect(isolation.escapedHttp).toEqual([]);
        expect(isolation.escapedSockets).toEqual([]);
        expect(isolation.browserErrors).toEqual([]);
        expect(isolation.deniedHttp.filter(value => /^(POST|PATCH|PUT|DELETE) /.test(value.key))).toEqual([]);
      }
    });
  });
}

for (const host of taskHosts) {
  test.describe(`${host.name} group task viewport boundary`, () => {
    test.use({ hasTouch: host.touch, isMobile: host.touch });
    for (const viewport of mobileProbeViewports) {
      for (const storage of ['clean', 'oversized-saved'] as const) {
      const cell = `${host.name} ${viewport.width}x${viewport.height} ${storage}`;
      test(`task matrix: ${cell} native create rename Send Start Work decision and reopen`, async ({ page, context, baseURL }, testInfo) => {
        test.setTimeout(120_000);
        if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
        const preferences: Record<string, string> = storage === 'clean' ? {} : {
          'probos.chatsPanel.size': JSON.stringify({ w: 2400, h: 1600 }),
          'hxi_profile_panel_size': JSON.stringify({ w: 2400, h: 1600 }),
          'probos.sidebar.collapsed': '0',
        };
        await context.addInitScript(values => {
          for (const [key, value] of Object.entries(values)) localStorage.setItem(key, value);
        }, preferences);
        const fixture = taskViewportFixture(cell);
        const isolation = await installIssue1369Isolation(context, {
          baseURL, agents: fixture.dms.map(dm => dm.agent), generation, assetPaths, fixtures: fixture.fixtures,
        });
        const measurements: Record<string, unknown> = {};
        const stages: string[] = [];
        const transcript = page.getByTestId('chat-transcript');
        const input = page.getByPlaceholder('Message...', { exact: true });
        const rail = page.getByTestId('workspace-files-rail');
        const authority = () => page.evaluate(() => {
          const state = (window as unknown as { __store: { getState: () => BrowserState & { chatThreads: Map<string, ThreadFixture> } } }).__store.getState();
          return {
            connected: state.connected, generation: state.liveGeneration, sequence: state.liveSequence, drops: state.liveDropCount,
            agents: [...state.agents.keys()], selected: state.activeProfileAgent,
            profileThread: state.activeProfileThreadId, activeThread: state.activeThreadId,
            room: state.chatThreads.get('viewport-group') ?? null, bindings: Object.fromEntries(state.threadIdByAgent),
            width: innerWidth, height: innerHeight, coarse: matchMedia('(pointer: coarse)').matches,
            timeOrigin: performance.timeOrigin, hash: location.hash,
          };
        });
        const writes = () => isolation.deliveries.filter(delivery => /^(POST|PATCH|PUT|DELETE) /.test(delivery.key));
        const bank = async (stage: string): Promise<void> => {
          stages.push(stage);
          await testInfo.attach(`${stage}-layout`, { body: await page.screenshot(), contentType: 'image/png' });
          await testInfo.attach(`${stage}-bounds`, { body: JSON.stringify({ cell, measurements, authority: await authority(), writes: writes() }, null, 2), contentType: 'application/json' });
        };
        const activate = async (control: Locator, label: string, keyboard = false): Promise<void> => {
          await expect(control).toBeVisible();
          await expect(control).toBeEnabled();
          await control.scrollIntoViewIfNeeded();
          const hits = await pointerHits(control);
          measurements[`${label}-hits`] = hits;
          expect(hits.every(hit => hit.insideViewport && hit.hitsTarget), `${label}: native target`).toBe(true);
          if (keyboard) {
            await control.focus();
            await expect(control).toBeFocused();
            await page.keyboard.press('Enter');
          } else if (host.touch) await control.tap();
          else await control.click();
        };
        const measureChat = async (stage: string): Promise<void> => {
          await expect(transcript).toBeVisible();
          await expect.poll(async () => {
            const chat = await visibleBounds(transcript);
            const composer = await visibleBounds(input);
            measurements[stage] = { chat, composer, rail: await bounds(rail) };
            return chat.visibleWidth >= 280 && chat.visibleHeight >= 120 && composer.visibleWidth >= 120;
          }, { message: `${stage}: visible transcript 280x120 and input 120` }).toBe(true);
          const documentBounds = await page.evaluate(() => ({ width: innerWidth, root: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
          measurements[`${stage}-document`] = documentBounds;
          expect(documentBounds.root).toBeLessThanOrEqual(documentBounds.width);
          expect(documentBounds.body).toBeLessThanOrEqual(documentBounds.width);
          if (!host.compact && !host.mobile) {
            const hits = await pointerHits(page.getByRole('button', { name: 'Close profile', exact: true }));
            measurements[`${stage}-close-hits`] = hits;
            expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
          }
          const status = page.getByRole('region', { name: 'Task status', exact: true });
          if (await status.count()) {
            const statusBounds = await status.evaluate(element => ({
              height: element.getBoundingClientRect().height,
              parentHeight: element.parentElement!.getBoundingClientRect().height,
              overflow: getComputedStyle(element).overflowY,
            }));
            measurements[`${stage}-task-status`] = statusBounds;
            expect(statusBounds.height).toBeLessThanOrEqual(statusBounds.parentHeight * 0.25 + 1);
            expect(statusBounds.overflow).toBe('auto');
            await expect(status).toHaveAttribute('tabindex', '0');
            await status.focus();
            await expect(status).toBeFocused();
            await page.keyboard.press('PageDown');
          }
          await bank(stage);
        };
        const collapseFiles = async (label: string): Promise<void> => {
          await activate(page.getByTestId('workspace-files-collapse'), label, true);
          await expect(rail).toHaveAttribute('data-collapsed', 'true');
          await expect.soft(page.getByTestId('workspace-files-expand'), 'Files dismissal restores local control focus').toBeFocused();
          await measureChat(`${label}-restored`);
        };
        const reopen = async (stage: string): Promise<void> => {
          const readsBefore = isolation.deliveries.filter(delivery => delivery.key === `GET /api/threads/${fixture.roomId}/messages?limit=200`).length;
          const writesBefore = writes().length;
          if (host.mobile) {
            await activate(page.getByRole('button', { name: 'MESH', exact: true }), `${stage}-mesh`);
            await expect(transcript).toHaveCount(0);
            await expect(page.getByTestId('mobile-mesh')).toBeVisible();
            await activate(page.getByRole('button', { name: 'CHAT', exact: true }), `${stage}-chat`, true);
          } else if (host.compact) {
            if (viewport.width < 600) await activate(page.getByRole('button', { name: 'Expand sidebar', exact: true }), `${stage}-sidebar`);
            await activate(page.getByTestId(`thread-row-${fixture.dms[1].thread.id}`), `${stage}-away`);
            if (viewport.width < 600) await activate(page.getByRole('button', { name: 'Expand sidebar', exact: true }), `${stage}-sidebar-return`);
            await activate(page.getByTestId(`thread-row-${fixture.roomId}`), `${stage}-room`);
            await expect(input).toBeFocused();
          } else {
            await activate(page.getByRole('button', { name: 'Close profile', exact: true }), `${stage}-close`);
            await expect(transcript).toHaveCount(0);
            await activate(page.getByTestId('crew-collab-pill'), `${stage}-launcher`, true);
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain('GET /api/threads?include_archived=false&limit=100');
            await activate(page.getByTestId(`chat-row-${fixture.roomId}`), `${stage}-room`);
            await expect(page.getByTestId('chats-panel')).toHaveCount(0);
            await expect(input).toBeFocused();
          }
          await expect.poll(() => isolation.deliveries.filter(delivery => delivery.key === `GET /api/threads/${fixture.roomId}/messages?limit=200`).length).toBeGreaterThan(readsBefore);
          await expect(page.getByTestId('group-chat-title')).toHaveText(fixture.longTitle);
          await expect(transcript).toContainText(fixture.hydrated);
          await expect(transcript).toContainText(fixture.text);
          expect(writes().length, 'reopen is GET-only').toBe(writesBefore);
          await measureChat(stage);
        };
        try {
          await test.step('native group creation on the genuine host', async () => {
            await page.setViewportSize(host.mobile ? { width: 390, height: 844 } : viewport);
            await page.goto(host.route);
            await page.waitForFunction(() => Boolean((window as unknown as BaselineWindow).__store));
            await expect.poll(authority).toMatchObject({ connected: true, generation, sequence: 1, drops: 0, coarse: host.touch, agents: ['yeo', 'alpha', 'beta'], selected: null, activeThread: null, room: null });
            expect(isolation.snapshots.length).toBeGreaterThan(0);
            expect((await page.evaluate(() => (window as unknown as BaselineWindow).__issue1369.initialStorage)).sort()).toEqual(Object.keys(preferences).sort());
            const entry = await authority();
            if (host.mobile) {
              await expect(page.getByTestId('mobile-shell')).toBeVisible();
              expect(entry).toMatchObject({ width: 390, height: 844, coarse: true, hash: '' });
              await page.setViewportSize(viewport);
              await expect.poll(authority).toMatchObject({ ...viewport, timeOrigin: entry.timeOrigin });
              await expect(page.getByTestId('mobile-shell')).toBeVisible();
            } else {
              await expect(page.getByTestId('mobile-shell')).toHaveCount(0);
              await expect(page.getByTestId('compact-conversation')).toHaveCount(host.compact ? 1 : 0);
            }
            await expect(page.locator('canvas')).toHaveCount(host.compact || host.mobile ? 0 : 1);
            if (host.compact || host.mobile) {
              await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain('GET /api/agent/yeo/chat/history');
              await activate(page.getByTestId('empty-chat-add-people'), 'seeded-group-picker');
              await expect(page.getByTestId('new-chat-seed-yeo')).toBeVisible();
            } else {
              await activate(page.getByRole('button', { name: 'Got it', exact: true }), 'welcome');
              const game = page.getByRole('region', { name: 'Tic-Tac-Toe game', exact: true });
              await expect(game.getByRole('alert')).toBeVisible();
              await activate(game.getByRole('button', { name: 'Close game', exact: true }), 'close-game');
              await activate(page.getByTestId('crew-collab-pill'), 'group-launcher');
              await activate(page.getByRole('button', { name: 'New chat', exact: true }), 'new-group');
              await activate(page.getByTestId('add-participant-row').filter({ hasText: 'Yeo' }), 'select-yeo');
            }
            await activate(page.getByTestId('add-participant-row').filter({ hasText: 'Alpha' }), 'select-alpha');
            expect(writes(), 'picker navigation causes no passive writes').toEqual([]);
            await activate(page.getByTestId('new-chat-start'), 'create-group');
            await expect.poll(writes).toHaveLength(1);
            await expect(page.getByTestId('new-chat-modal')).toHaveCount(0);
            await expect(page.getByTestId('chats-panel')).toHaveCount(0);
            await expect.poll(authority).toMatchObject({ profileThread: fixture.roomId, room: { id: fixture.roomId, participants: ['yeo', 'alpha'] }, bindings: {} });
            await expect(page.getByTestId('group-chat-title')).toHaveText('Yeo, Alpha');
            await expect(transcript).toContainText('Group persisted row 23:');
            await expect(rail).toHaveAttribute('data-collapsed', 'true');
            await expect(page.getByTestId('artifact-drawer')).toHaveCount(0);
            await activate(page.getByRole('button', { name: 'Rename room', exact: true }), 'rename-group', true);
            await page.getByTestId('group-chat-title-input').fill(fixture.longTitle);
            await page.keyboard.press('Enter');
            await expect(page.getByTestId('group-chat-title')).toHaveText(fixture.longTitle);
            await measureChat('created-long-group');
            await input.fill(fixture.text);
            await activate(rail.locator('..').getByRole('button', { name: 'Send', exact: true }), 'group-send');
            await expect.poll(() => writes().filter(delivery => delivery.key === `POST /api/threads/${fixture.roomId}/messages`)).toHaveLength(1);
            await expect(input).toHaveValue('');
            if (host.compact) {
              await activate(page.getByTestId('sidebar-new-chat'), 'compact-native-new-chat');
              await expect.poll(authority).toMatchObject({ activeThread: fixture.sidebarThread.id, bindings: { yeo: fixture.sidebarThread.id } });
              await expect(input).toBeFocused();
            }
            await reopen('group-reopened');
          });
          await test.step('Start Work binds the session and a native decision refetches the checklist', async () => {
            const beforeStart = writes().length;
            await activate(page.getByTestId('workspace-files-expand'), 'files-expand');
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(`GET /api/threads/${fixture.roomId}/inputs`);
            await activate(page.getByTestId('workspace-start-work-open'), 'start-work-open', true);
            const goalInput = page.getByTestId('workspace-start-work-goal');
            await expect(goalInput).toBeFocused();
            expect(writes().length).toBe(beforeStart);
            await goalInput.fill(fixture.goal);
            await page.getByTestId('workspace-start-work-criteria').fill(fixture.criteria.join('\n'));
            await page.getByTestId('workspace-start-work-deliverable').fill(fixture.deliverable);
            await expect(page.getByTestId('workspace-start-work-retry')).not.toBeChecked();
            await bank('start-work-form');
            await activate(page.getByTestId('workspace-start-work-confirm'), 'start-work-submit');
            await expect(page.getByTestId('workspace-start-work-dialog')).toHaveCount(0);
            await expect(page.getByTestId('workspace-start-work-open')).toBeFocused();
            await expect(page.getByTestId('crew-collaboration-panel')).toHaveAttribute('data-state', 'executing');
            await expect(page.getByTestId('crew-collaboration-panel')).toContainText(fixture.goal);
            const stepKey = `GET /api/work-items/${fixture.parentId}/steps?limit=1001`;
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(stepKey);
            await expect(page.getByTestId('todo-row-0')).toContainText(fixture.decision);
            const readsBefore = isolation.deliveries.filter(delivery => delivery.key === stepKey).length;
            const railBox = await rail.boundingBox();
            const hostBox = await rail.locator('..').boundingBox();
            measurements.files = { rail: railBox, host: hostBox, compact: await rail.getAttribute('data-compact') };
            expect(railBox!.width).toBeLessThanOrEqual(hostBox!.width + 1);
            await bank('task-decision');
            await activate(page.getByTestId('todo-confirm-0'), 'confirm-step');
            await expect.poll(() => isolation.deliveries.filter(delivery => delivery.key === stepKey).length).toBeGreaterThan(readsBefore);
            await expect(page.getByTestId('todo-confirm-0')).toHaveCount(0);
            await expect(page.getByTestId('todo-row-0').locator('[aria-label="done"]')).toBeVisible();
            await expect(page.getByTestId('workspace-files-todos-label')).toHaveText('TODOS (1/1)');
            const output = viewportArtifact(fixture.roomId);
            const outputRow = page.getByTestId(`artifact-row-${output.id}`);
            const beforePreview = writes().length;
            await activate(outputRow, 'workspace-output-open');
            const preview = page.getByTestId('workspace-files-preview');
            await expect(preview).toContainText('Synthetic local report.');
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(`GET /api/artifacts/${output.id}/content`);
            const previewBox = await preview.boundingBox();
            const previewHost = await rail.locator('..').boundingBox();
            measurements.preview = { previewBox, host: previewHost, rail: await bounds(rail) };
            expect(previewBox!.width).toBeLessThanOrEqual(previewHost!.width + 1);
            expect(previewBox!.x).toBeGreaterThanOrEqual(previewHost!.x - 1);
            expect(previewBox!.x + previewBox!.width).toBeLessThanOrEqual(previewHost!.x + previewHost!.width + 1);
            await bank('workspace-output-preview');
            await activate(page.getByTestId('workspace-files-preview-close'), 'workspace-preview-dismiss', true);
            await expect(preview).toHaveCount(0);
            await expect.soft(outputRow, 'Output preview dismissal restores its local opener').toBeFocused();
            expect(writes().length, 'viewing a local output is GET-only').toBe(beforePreview);
            await collapseFiles('files-dismiss');
            await reopen('task-reopened');
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(`GET /api/crew-tasks/${fixture.parentId}`);
            await expect(page.getByTestId('crew-collaboration-panel')).toHaveAttribute('data-state', 'executing');
            await expect(page.getByTestId('crew-collaboration-panel')).toContainText(fixture.goal);
            const beforeFiles = writes().length;
            await activate(page.getByTestId('workspace-files-expand'), 'task-files-reopen');
            await expect(page.getByTestId('workspace-files-todos-label')).toHaveText('TODOS (1/1)');
            expect(writes().length).toBe(beforeFiles);
            await bank('task-persistence');
            await collapseFiles('task-files-dismiss');
            expect(writes().map(delivery => delivery.key)).toEqual([
              'POST /api/threads', `PATCH /api/threads/${fixture.roomId}`, `POST /api/threads/${fixture.roomId}/messages`,
              ...(host.compact ? ['POST /api/threads'] : []),
              `POST /api/threads/${fixture.roomId}/start-work`, `PATCH /api/work-items/${fixture.parentId}/steps/0`,
            ]);
            const beforeResize = await authority();
            const saved = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)])));
            const writeCount = writes().length;
            for (const size of [{ width: 1920, height: 1080 }, { width: 390, height: 844 }, { width: 1920, height: 1080 }, viewport]) {
              await page.setViewportSize(size);
              await expect.poll(authority).toMatchObject({ ...size, timeOrigin: beforeResize.timeOrigin, room: { id: fixture.roomId, task_id: fixture.parentId } });
              await expect(page.getByTestId('crew-collaboration-panel')).toHaveAttribute('data-state', 'executing');
              await expect(transcript).toContainText(fixture.hydrated);
              await measureChat(`task-resize-${stages.length}-${size.width}`);
              expect(await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)])))).toEqual(saved);
              expect(writes().length).toBe(writeCount);
            }
          });
        } finally {
          const rendered = await page.evaluate(() => ({
            capabilities: (window as unknown as BaselineWindow).__issue1369,
            activeMedia: [...document.querySelectorAll('audio, video')].filter(element => {
              const media = element as HTMLMediaElement;
              return media.srcObject !== null || !media.paused;
            }).map(element => element.tagName),
            focus: { tag: document.activeElement?.tagName, testId: document.activeElement?.getAttribute('data-testid') },
          })).catch(String);
          await testInfo.attach('task-matrix-evidence', { body: JSON.stringify({ cell, stages, measurements, isolation, rendered, authority: await authority().catch(String), errors: testInfo.errors }, null, 2), contentType: 'application/json' });
          if (!page.isClosed()) await testInfo.attach('task-matrix-final', { body: await page.screenshot({ timeout: 5_000 }), contentType: 'image/png' });
          expect(isolation.escapedHttp).toEqual([]);
          expect(isolation.escapedSockets).toEqual([]);
          expect(isolation.deniedSockets).toEqual([]);
          expect(isolation.browserErrors).toEqual([]);
          expect(isolation.deniedHttp.filter(request => /^(POST|PATCH|PUT|DELETE) /.test(request.key))).toEqual([]);
          expect(rendered).toHaveProperty('activeMedia', []);
          expect(rendered).toHaveProperty('capabilities.blockedCapabilities', ['serviceWorker.register']);
          expect(context.serviceWorkers()).toEqual([]);
          expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
        }
      });
      }
    }
  });
}

for (const touch of [false, true]) {
  test.describe(`FullApp canvas ${touch ? 'touch' : 'fine'}`, () => {
    test.use({ hasTouch: touch, isMobile: touch });
    for (const viewport of mobileProbeViewports) {
      test(`canvas picking: ${touch ? 'touch' : 'fine'} ${viewport.width}x${viewport.height} real pixels and selected identity`, async ({ page, context, baseURL }, testInfo) => {
        if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
        await page.setViewportSize(viewport);
        const dm = viewportDMs('canvas')[1];
        const isolation = await installIssue1369Isolation(context, { baseURL, agents: [alpha], generation, assetPaths, fixtures: viewportFixtures([dm]) });
        const evidence: Record<string, unknown> = {};
        const selected = () => page.evaluate(() => (window as unknown as BaselineWindow).__store.getState().activeProfileAgent);
        try {
          await page.goto(touch ? '/#desktop' : '/');
          await expect.poll(() => page.evaluate(() => {
            const state = (window as unknown as BaselineWindow).__store.getState();
            return { connected: state.connected, generation: state.liveGeneration, agents: [...state.agents.keys()], selected: state.activeProfileAgent };
          })).toEqual({ connected: true, generation, agents: ['alpha'], selected: null });
          await page.getByRole('button', { name: 'Got it', exact: true }).click();
          const game = page.getByRole('region', { name: 'Tic-Tac-Toe game', exact: true });
          await expect(game.getByRole('alert')).toBeVisible();
          await game.getByRole('button', { name: 'Close game', exact: true }).click();
          await expect(game).toHaveCount(0);
          await expect(page.getByRole('heading', { name: 'Welcome to ProbOS' })).toHaveCount(0);
          const canvas = page.locator('canvas');
          await expect(canvas).toHaveCount(1);
          const idleFrame = await canvas.screenshot();
          const first = await canvas.screenshot();
          expect(idleFrame.equals(first), 'The connected scene changes without intervening input or selection').toBe(false);
          await expect.poll(selected).toBeNull();
          await testInfo.attach('canvas-idle-motion-start', { body: idleFrame, contentType: 'image/png' });
          await testInfo.attach('canvas-before-picking', { body: first, contentType: 'image/png' });
          const pixels = await page.evaluate(async bytes => {
            const image = await createImageBitmap(new Blob([new Uint8Array(bytes)], { type: 'image/png' }));
            try {
              const copy = document.createElement('canvas');
              copy.width = image.width;
              copy.height = image.height;
              const rendering = copy.getContext('2d');
              if (!rendering) throw new Error('Canvas screenshot decoder unavailable');
              rendering.drawImage(image, 0, 0);
              const data = rendering.getImageData(0, 0, copy.width, copy.height).data;
              const matching = new Set<number>();
              let visiblePixels = 0;
              for (let row = 0; row < copy.height; row += 1) {
                for (let column = 0; column < copy.width; column += 1) {
                  const offset = (row * copy.width + column) * 4;
                  const red = data[offset];
                  const green = data[offset + 1];
                  const blue = data[offset + 2];
                  if (Math.max(red, green, blue) > 50) visiblePixels += 1;
                  if (column > copy.width * 0.2 && column < copy.width * 0.8
                    && row > copy.height * 0.05 && row < copy.height * 0.8
                    && blue > 90 && green > 60 && blue > red + 12) matching.add(row * copy.width + column);
                }
              }
              const regions: { x: number; y: number; pixels: number }[] = [];
              while (matching.size > 0) {
                const firstPixel = matching.values().next().value!;
                matching.delete(firstPixel);
                const region = [firstPixel];
                for (let index = 0; index < region.length; index += 1) {
                  const point = region[index];
                  for (const neighbor of [point - 1, point + 1, point - copy.width, point + copy.width]) {
                    if (matching.delete(neighbor)) region.push(neighbor);
                  }
                }
                if (region.length < 12) continue;
                const centerX = region.reduce((sum, point) => sum + point % copy.width, 0) / region.length;
                const centerY = region.reduce((sum, point) => sum + Math.floor(point / copy.width), 0) / region.length;
                regions.push({ x: centerX + 0.5, y: centerY + 0.5, pixels: region.length });
              }
              return { width: copy.width, height: copy.height, visiblePixels, regions: regions.sort((left, right) => right.pixels - left.pixels) };
            } finally { image.close(); }
          }, [...first]);
          evidence.pixels = pixels;
          expect(pixels.visiblePixels).toBeGreaterThan(100);
          expect(pixels.regions.length).toBeGreaterThan(0);
          const canvasBox = (await canvas.boundingBox())!;
          const target = pixels.regions[0];
          const point = { x: canvasBox.x + target.x * canvasBox.width / pixels.width, y: canvasBox.y + target.y * canvasBox.height / pixels.height };
          evidence.target = point;
          expect(await canvas.evaluate((element, position) => element === document.elementFromPoint(position.x, position.y), point)).toBe(true);
          await canvas.evaluate(element => element.addEventListener('pointerup', () => element.setAttribute('data-picking-pointerup', 'true'), { once: true }));
          if (touch) await page.touchscreen.tap(point.x, point.y);
          else await page.mouse.click(point.x, point.y);
          await expect(canvas).toHaveAttribute('data-picking-pointerup', 'true');
          await expect.poll(selected).toBe('alpha');
          const profile = page.getByTestId('artifact-drawer').locator('../../..');
          await expect(profile).toContainText('Alpha');
          await expect(profile.getByPlaceholder('Message...', { exact: true })).toBeVisible();
          await testInfo.attach('canvas-selected-profile', { body: await page.screenshot(), contentType: 'image/png' });
          await page.getByRole('button', { name: 'Close profile', exact: true }).focus();
          await page.keyboard.press('Enter');
          await expect.poll(selected).toBeNull();
          const second = await canvas.screenshot();
          await testInfo.attach('canvas-after-picking', { body: second, contentType: 'image/png' });
          await page.getByTestId('crew-collab-pill').focus();
          await page.keyboard.press('Enter');
          await page.getByRole('button', { name: 'New chat', exact: true }).focus();
          await page.keyboard.press('Enter');
          await page.getByTestId('add-participant-row').filter({ hasText: 'Alpha' }).focus();
          await page.keyboard.press('Enter');
          await page.getByTestId('new-chat-start').focus();
          await page.keyboard.press('Enter');
          await expect.poll(selected).toBe('alpha');
          await expect(page.getByTestId('chats-panel')).toHaveCount(0);
          await expect(profile).toContainText('Alpha');
          evidence.keyboardAlternativeSelected = await selected();
        } finally {
          await testInfo.attach('canvas-picking-evidence', { body: JSON.stringify({ viewport, touch, evidence, isolation, errors: testInfo.errors }, null, 2), contentType: 'application/json' });
          expect(isolation.escapedHttp).toEqual([]);
          expect(isolation.escapedSockets).toEqual([]);
          expect(isolation.browserErrors).toEqual([]);
          expect(isolation.deniedSockets).toEqual([]);
        }
      });
    }
  });
}

for (const host of conversationHosts) {
  test.describe(`${host.name} DM viewport boundary`, () => {
    test.use({ hasTouch: host.touch, isMobile: host.touch });
    for (const viewport of mobileProbeViewports) {
      for (const storage of ['clean', 'oversized-saved'] as const) {
        const cell = `${host.name} ${host.route} ${viewport.width}x${viewport.height} ${storage}`;
        test(`DM matrix: ${cell} no-thread empty long Send reopen panels and width restoration`, async ({ page, context, baseURL }, testInfo) => {
          test.setTimeout(180_000);
          if (!baseURL) throw new Error('The isolated issue1369 config must supply baseURL');
          const preferences: Record<string, string> = storage === 'clean' ? {} : {
            'probos.chatsPanel.size': JSON.stringify({ w: 2400, h: 1600 }),
            'hxi_profile_panel_size': JSON.stringify({ w: 2400, h: 1600 }),
            'probos.sidebar.collapsed': '0',
            'probos.artifactDrawer.collapsed': '0',
          };
          await context.addInitScript(values => {
            for (const [key, value] of Object.entries(values)) localStorage.setItem(key, value);
          }, preferences);
          await page.setViewportSize(viewport);
          const dms = viewportDMs(cell);
          const isolation = await installIssue1369Isolation(context, {
            baseURL, agents: dms.map(dm => dm.agent), generation, assetPaths, fixtures: viewportFixtures(dms),
          });
          const measurements: Record<string, unknown> = {};
          const stages: string[] = [];
          const input = page.getByPlaceholder('Message...', { exact: true });
          const transcript = page.getByTestId('chat-transcript');
          const drawer = page.getByTestId('artifact-drawer');
          const authority = () => page.evaluate(() => {
            const state = (window as unknown as {
              __store: { getState: () => BrowserState & { chatThreads: Map<string, ThreadFixture> } };
            }).__store.getState();
            return {
              connected: state.connected, generation: state.liveGeneration, sequence: state.liveSequence,
              drops: state.liveDropCount, mainViewer: state.mainViewer,
              agents: [...state.agents].map(([id, agent]) => [id, agent.callsign]),
              selectedAgent: state.activeProfileAgent, profileThread: state.activeProfileThreadId,
              activeThread: state.activeThreadId,
              participants: state.activeThreadId ? state.chatThreads.get(state.activeThreadId)?.participants : null,
              bindings: Object.fromEntries(state.threadIdByAgent),
              hash: location.hash, timeOrigin: performance.timeOrigin,
              width: innerWidth, height: innerHeight, coarsePointer: matchMedia('(pointer: coarse)').matches,
            };
          });
          const storedLayout = () => page.evaluate(() => Object.fromEntries([
            'probos.chatsPanel.size', 'hxi_profile_panel_size', 'probos.sidebar.collapsed', 'probos.artifactDrawer.collapsed',
          ].map(key => [key, localStorage.getItem(key)])));
          const bank = async (stage: string): Promise<void> => {
            stages.push(stage);
            await testInfo.attach(`${stage}-layout`, { body: await page.screenshot(), contentType: 'image/png' });
            await testInfo.attach(`${stage}-measurements`, {
              body: JSON.stringify({ cell, measurements, authority: await authority(), storage: await storedLayout() }, null, 2),
              contentType: 'application/json',
            });
          };
          const activate = async (control: Locator, label: string, keyboard = false): Promise<void> => {
            await expect(control).toBeVisible();
            await expect(control).toBeEnabled();
            const hits = await pointerHits(control);
            measurements[`${label}-hits`] = hits;
            expect(hits.every(hit => hit.insideViewport && hit.hitsTarget), `${label} interior hit targets`).toBe(true);
            if (keyboard) {
              await control.focus();
              await expect(control).toBeFocused();
              await page.keyboard.press('Enter');
            } else if (host.touch) {
              await control.tap();
            } else {
              await control.click();
            }
          };
          const measureChat = async (stage: string): Promise<void> => {
            await expect(transcript).toBeVisible();
            await expect.poll(async () => {
              const chat = await visibleBounds(transcript);
              const composer = await visibleBounds(input);
              measurements[stage] = { chat, composer, drawer: await bounds(drawer) };
              return chat.width >= 280 && chat.visibleWidth >= 280 && chat.visibleHeight >= 120
                && composer.width >= 120 && composer.visibleWidth >= 120;
            }, { message: `${stage}: transcript 280x120 and input 120 visible pixels` }).toBe(true);
            const documentWidth = await page.evaluate(() => ({
              width: innerWidth, root: document.documentElement.scrollWidth, body: document.body.scrollWidth,
            }));
            measurements[`${stage}-document`] = documentWidth;
            expect(documentWidth.root).toBeLessThanOrEqual(documentWidth.width);
            expect(documentWidth.body).toBeLessThanOrEqual(documentWidth.width);
            if (!host.compact) {
              const current = await authority();
              const profile = drawer.locator('../../..');
              await expect.poll(async () => {
                const box = await profile.boundingBox();
                return box !== null && Math.abs(box.width - Math.min(storage === 'clean' ? 420 : 2400, current.width)) <= 1
                  && Math.abs(box.height - Math.min(storage === 'clean' ? 580 : 1600, current.height)) <= 1
                  && box.x >= 0 && box.y >= 0 && box.x + box.width <= current.width && box.y + box.height <= current.height;
              }, { message: `${stage}: profile restores preferred size within viewport` }).toBe(true);
              measurements[`${stage}-profile`] = await bounds(profile);
              const hits = await pointerHits(page.getByRole('button', { name: 'Close profile', exact: true }));
              measurements[`${stage}-close-hits`] = hits;
              expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
            } else {
              const narrow = (await authority()).width < 600;
              const sidebar = page.getByTestId('thread-sidebar');
              await expect(sidebar).toHaveAttribute('data-collapsed', String(narrow));
              await expect.poll(async () => {
                const box = await sidebar.boundingBox();
                return box !== null && Math.abs(box.width - (narrow ? 56 : 240)) <= 1;
              }, { message: `${stage}: sidebar restores expanded desktop preference` }).toBe(true);
              measurements[`${stage}-sidebar`] = await bounds(sidebar);
            }
            await bank(stage);
          };
          const launcher = async (keyboard = false): Promise<void> => {
            await activate(page.getByTestId('crew-collab-pill'), `launcher-${stages.length}`, keyboard);
            await expect(page.getByTestId('chats-panel')).toBeVisible();
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
              .toContain('GET /api/threads?include_archived=false&limit=100');
          };
          const selectSaved = async (dm: ViewportDM, label: string): Promise<void> => {
            if (host.compact) {
              if ((await authority()).width < 600) {
                await activate(page.getByRole('button', { name: 'Expand sidebar', exact: true }), `${label}-sidebar`);
                await expect(page.getByRole('dialog', { name: 'Thread navigation', exact: true })).toBeVisible();
              }
              await activate(page.getByTestId(`thread-row-${dm.thread.id}`), `${label}-row`);
              await expect(page.getByRole('dialog', { name: 'Thread navigation', exact: true })).toHaveCount(0);
              await expect.poll(authority).toMatchObject({ activeThread: dm.thread.id, participants: [dm.agent.id] });
            } else {
              await activate(page.getByRole('button', { name: 'Close profile', exact: true }), `${label}-close-profile`);
              await expect(transcript).toHaveCount(0);
              await launcher(true);
              await activate(page.getByTestId(`chat-row-${dm.thread.id}`), `${label}-row`);
              await expect(page.getByTestId('chats-panel')).toHaveCount(0);
              await expect.poll(authority).toMatchObject({ selectedAgent: dm.agent.id, profileThread: dm.thread.id });
              await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
                .toContain(`GET /api/threads/${dm.thread.id}`);
            }
            await expect(input).toBeFocused();
            await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
              .toContain(`GET /api/threads/${dm.thread.id}/messages?limit=200`);
          };
          const exerciseDrawer = async (label: string): Promise<void> => {
            if (await drawer.getAttribute('data-collapsed') === 'false') {
              await activate(page.getByRole('button', { name: 'Collapse artifacts', exact: true }), `${label}-initial-collapse`);
              await expect(page.getByRole('button', { name: 'Expand artifacts', exact: true })).toBeFocused();
            }
            await activate(page.getByRole('button', { name: 'Expand artifacts', exact: true }), `${label}-expand`, true);
            const collapse = page.getByRole('button', { name: 'Collapse artifacts', exact: true });
            await expect(collapse).toBeFocused();
            measurements[`${label}-expanded`] = await bounds(drawer);
            await bank(`${label}-expanded`);
            await activate(collapse, `${label}-dismiss`);
            await expect(page.getByRole('button', { name: 'Expand artifacts', exact: true })).toBeFocused();
            await measureChat(`${label}-dismissed`);
          };
          const exerciseInlineArtifact = async (label: string, modes: readonly string[] = ['Enter', 'Space', 'pointer']): Promise<void> => {
            const dm = dms[2];
            const artifact = viewportArtifact(dm.thread.id);
            const card = transcript.getByRole('button', { name: `Open ${artifactName} v1`, exact: true });
            await expect(card).toBeEnabled();
            await expect(card).toHaveAttribute('data-artifact-thread-id', dm.thread.id);
            await expect(card).toHaveAttribute('data-artifact-id', artifact.id);
            const writeCount = isolation.deliveries.filter(delivery => /^(POST|PATCH|PUT|DELETE) /.test(delivery.key)).length;
            for (const mode of modes) {
              await card.scrollIntoViewIfNeeded();
              const hits = await pointerHits(card);
              measurements[`${label}-${mode}-card-hits`] = hits;
              expect(hits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
              await page.evaluate(() => {
                const events: string[] = [];
                const listener = (event: FocusEvent): void => {
                  const target = event.target;
                  if (target instanceof HTMLElement) events.push(target.outerHTML.slice(0, 600));
                };
                document.addEventListener('focusin', listener);
                (window as unknown as { __artifactFocusProbe: { events: string[]; stop: () => void } }).__artifactFocusProbe = {
                  events, stop: () => document.removeEventListener('focusin', listener),
                };
              });
              if (mode === 'pointer') {
                if (host.touch) await card.tap();
                else await card.click();
              } else {
                for (let attempts = 0; attempts < 80 && !await card.evaluate(element => element === document.activeElement); attempts += 1) {
                  await page.keyboard.press('Shift+Tab');
                }
                await expect(card).toBeFocused();
                await page.keyboard.press(mode);
              }
              await expect(drawer).toHaveAttribute('data-collapsed', 'false');
              const collapse = page.getByRole('button', { name: 'Collapse artifacts', exact: true });
              try {
                await expect(collapse).toBeFocused();
                const retained = await collapse.evaluate(element => new Promise<boolean>(resolve => {
                  const started = performance.now();
                  let focused = true;
                  const observe = (): void => {
                    focused = focused && document.activeElement === element;
                    if (performance.now() - started >= 150) resolve(focused);
                    else requestAnimationFrame(observe);
                  };
                  observe();
                }));
                expect(retained, 'native activation retains drawer focus beyond the 50ms global input timer').toBe(true);
              } finally {
                const focus = await page.evaluate(() => {
                  const probe = (window as unknown as { __artifactFocusProbe: { events: string[]; stop: () => void } }).__artifactFocusProbe;
                  return { events: probe.events, active: document.activeElement?.outerHTML.slice(0, 600) };
                });
                await testInfo.attach(`${label}-${mode}-focus`, { body: JSON.stringify(focus), contentType: 'application/json' });
              }
              await expect(drawer).toContainText('Synthetic local report.');
              await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(`GET /api/artifacts/${artifact.id}/content`);
              const selected = await page.evaluate(() => {
                const state = (window as unknown as { __store: { getState: () => BrowserState & { selectedArtifactId: string | null; artifactDrawerCollapsed: boolean } } }).__store.getState();
                return { artifactId: state.selectedArtifactId, collapsed: state.artifactDrawerCollapsed };
              });
              expect(selected).toEqual({ artifactId: artifact.id, collapsed: false });
              await expect(drawer).toHaveAttribute('data-thread-id', dm.thread.id);
              measurements[`${label}-${mode}-selected`] = selected;
              const dismissHits = await pointerHits(collapse);
              measurements[`${label}-${mode}-dismiss-hits`] = dismissHits;
              expect(dismissHits.every(hit => hit.insideViewport && hit.hitsTarget)).toBe(true);
              await bank(`${label}-${mode}-opened`);
              if (mode === 'Space') await activate(collapse, `${label}-${mode}-dismiss`);
              else await page.keyboard.press('Escape');
              await expect(drawer).toHaveAttribute('data-collapsed', 'true');
              await expect(card).toBeFocused();
              await expect(card).toHaveAttribute('data-artifact-id', artifact.id);
              await measureChat(`${label}-${mode}-focus-return`);
              const focusEvents = await page.evaluate(() => {
                const probe = (window as unknown as { __artifactFocusProbe: { events: string[]; stop: () => void } }).__artifactFocusProbe;
                probe.stop();
                return probe.events;
              });
              expect(focusEvents.filter(event => event.includes('Ask ProbOS...')), 'global input never steals artifact navigation focus').toEqual([]);
              await expect(page.getByPlaceholder('Ask ProbOS...', { exact: true })).toHaveCount(0);
            }
            expect(isolation.deliveries.filter(delivery => /^(POST|PATCH|PUT|DELETE) /.test(delivery.key)).length, 'explicit artifact views are GET-only').toBe(writeCount);
          };
          try {
            await test.step('establish genuine module-load host and exact fixtures', async () => {
              await page.goto(host.route);
              await page.waitForFunction(() => Boolean((window as unknown as BaselineWindow).__store));
              await expect.poll(authority).toMatchObject({
                connected: true, generation, sequence: 1, drops: 0,
                agents: [['yeo', 'Yeo'], ['alpha', 'Alpha'], ['beta', 'Beta']],
                ...viewport, coarsePointer: host.touch, hash: new URL(host.route, baseURL).hash,
                selectedAgent: null, activeThread: null,
              });
              expect(isolation.snapshots.length).toBeGreaterThan(0);
              if (storage === 'clean') {
                expect(await page.evaluate(() => (window as unknown as BaselineWindow).__issue1369.initialStorage)).toEqual([]);
              } else {
                expect(await storedLayout()).toMatchObject(preferences);
              }
              await expect(page.getByTestId('mobile-shell')).toHaveCount(0);
              if (host.compact) {
                await expect(page.getByTestId('compact-conversation')).toBeVisible();
                await expect(page.locator('canvas')).toHaveCount(0);
                await expect.poll(() => isolation.deliveries.map(delivery => delivery.key))
                  .toContain('GET /api/projects?include_archived=false&limit=100');
              } else {
                await expect(page.getByTestId('compact-conversation')).toHaveCount(0);
                await expect(page.locator('canvas')).toHaveCount(1);
                await activate(page.getByRole('button', { name: 'Got it', exact: true }), 'welcome');
                const game = page.getByRole('region', { name: 'Tic-Tac-Toe game', exact: true });
                await expect(game.getByRole('alert')).toBeVisible();
                await activate(game.getByRole('button', { name: 'Close game', exact: true }), 'game-close');
                await launcher();
                const initialLayout = await storedLayout();
                for (const size of [{ width: 1920, height: 1080 }, { width: 390, height: 844 }, viewport]) {
                  await page.setViewportSize(size);
                  const panel = page.getByTestId('chats-panel');
                  await expect.poll(() => panel.evaluate(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight;
                  })).toBe(true);
                  await expect.poll(async () => {
                    const box = await panel.boundingBox();
                    return box !== null && Math.abs(box.width - Math.min(storage === 'clean' ? 440 : 2400, size.width - 16)) <= 1
                      && Math.abs(box.height - Math.min(storage === 'clean' ? 600 : 1600, size.height - 16)) <= 1;
                  }, { message: 'launcher restores saved dimensions after temporary clamp' }).toBe(true);
                  measurements[`launcher-${size.width}`] = await bounds(panel);
                  await bank(`launcher-${size.width}`);
                  expect(await storedLayout()).toEqual(initialLayout);
                }
                await activate(page.getByRole('button', { name: 'Close chats', exact: true }), 'launcher-close');
                await expect(page.getByTestId('chats-panel')).toHaveCount(0);
                await launcher(true);
                await activate(page.getByRole('button', { name: 'New chat', exact: true }), 'new-chat');
                await activate(page.getByRole('button', { name: 'Cancel new chat', exact: true }), 'new-chat-cancel', true);
                await expect(page.getByTestId('new-chat-modal')).toHaveCount(0);
                await activate(page.getByRole('button', { name: 'New chat', exact: true }), 'new-chat-again');
                await activate(page.getByTestId('add-participant-row').filter({ hasText: 'Yeo' }), 'choose-yeo');
                await activate(page.getByTestId('new-chat-start'), 'start-solo');
                await expect(page.getByTestId('chats-panel')).toHaveCount(0);
                await expect.poll(authority).toMatchObject({ selectedAgent: 'yeo', profileThread: null, activeThread: null });
                expect(isolation.deliveries.filter(delivery => delivery.key === 'POST /api/threads')).toEqual([]);
              }
              await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain('GET /api/agent/yeo/chat/history');
              await expect(page.getByTestId('empty-chat-add-people')).toBeVisible();
              await measureChat('initial-no-thread');
            });
            for (const [index, dm] of dms.entries()) {
              await test.step(`${dm.agent.callsign}: ${index === 0 ? 'no-thread' : index === 1 ? 'saved empty' : 'saved long'} native Send and reopen`, async () => {
                if (index > 0) await selectSaved(dm, `${dm.agent.id}-open`);
                const initialRead = isolation.deliveries.filter(delivery => delivery.key === `GET /api/threads/${dm.thread.id}/messages?limit=200`);
                if (dm.initiallySaved) {
                  expect(initialRead.length).toBeGreaterThan(0);
                  expect(initialRead.at(-1)?.response).toEqual({ thread_id: dm.thread.id, messages: dm.initialMessages });
                }
                if (index === 2) {
                  await expect(transcript).toContainText('Saved row 47:');
                  expect(await transcript.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
                }
                await measureChat(`${dm.agent.id}-before-send`);
                await input.fill(dm.text);
                const conversation = host.compact ? page.getByTestId('compact-conversation') : drawer.locator('../../..');
                await activate(conversation.getByRole('button', { name: 'Send', exact: true }), `${dm.agent.id}-send`);
                const sendKey = `POST /api/agent/${dm.agent.id}/chat`;
                await expect.poll(() => isolation.deliveries.filter(delivery => delivery.key === sendKey)).toHaveLength(1);
                await expect(transcript).toContainText(dm.reply);
                await expect.poll(authority).toMatchObject({ bindings: { [dm.agent.id]: dm.thread.id } });
                const readCount = isolation.deliveries.filter(delivery => delivery.key === `GET /api/threads/${dm.thread.id}/messages?limit=200`).length;
                if (host.compact) await selectSaved(dms[index === 1 ? 2 : 1], `${dm.agent.id}-away`);
                await selectSaved(dm, `${dm.agent.id}-reopen`);
                await expect.poll(() => isolation.deliveries.filter(delivery => delivery.key === `GET /api/threads/${dm.thread.id}/messages?limit=200`).length)
                  .toBeGreaterThan(readCount);
                await expect(transcript).toContainText(dm.hydrated);
                await expect(transcript).toContainText(dm.text);
                await expect(transcript).toContainText(dm.reply);
                expect(isolation.deliveries.find(delivery => delivery.key === sendKey)?.response).not.toHaveProperty('messages');
                await measureChat(`${dm.agent.id}-get-only-reopened`);
                await exerciseDrawer(`${dm.agent.id}-drawer`);
                if (index === 2) await exerciseInlineArtifact('saved-long-inline-card');
              });
            }
            await test.step('mounted width down/up restores preferences, selection and usable chat', async () => {
              const before = await storedLayout();
              const original = await authority();
              for (const size of [{ width: 1920, height: 1080 }, { width: 390, height: 844 }, { width: 1920, height: 1080 }, viewport]) {
                await page.setViewportSize(size);
                await expect.poll(authority).toMatchObject({ ...size, timeOrigin: original.timeOrigin, activeThread: original.activeThread });
                await measureChat(`restore-${stages.length}-${size.width}`);
                expect(await storedLayout()).toEqual(before);
                await exerciseInlineArtifact(`restored-${stages.length}-${size.width}`, ['pointer']);
                expect(await storedLayout()).toEqual(before);
                if (host.compact && size.width === 390) {
                  const expand = page.getByRole('button', { name: 'Expand sidebar', exact: true });
                  await activate(expand, `sidebar-expand-${stages.length}`, true);
                  const navigation = page.getByRole('dialog', { name: 'Thread navigation', exact: true });
                  await expect(navigation).toBeVisible();
                  const collapse = navigation.getByRole('button', { name: 'Collapse sidebar', exact: true });
                  await expect(collapse).toBeFocused();
                  await bank('sidebar-overlay');
                  await activate(collapse, 'sidebar-dismiss');
                  await expect(expand).toBeFocused();
                  await expect(navigation).toHaveCount(0);
                  expect(await storedLayout()).toEqual(before);
                  await measureChat('sidebar-dismissed');
                }
              }
              if (!host.compact) {
                await activate(page.getByRole('button', { name: 'Close profile', exact: true }), 'final-close-profile');
                await expect(transcript).toHaveCount(0);
                await expect.poll(authority).toMatchObject({ selectedAgent: null });
              }
            });
          } finally {
            const rendered = await page.evaluate(() => ({
              capabilities: (window as unknown as BaselineWindow).__issue1369,
              activeMedia: [...document.querySelectorAll('audio, video')].filter(element => {
                const media = element as HTMLMediaElement;
                return media.srcObject !== null || !media.paused;
              }).map(element => element.tagName),
              focus: { tag: document.activeElement?.tagName, label: document.activeElement?.getAttribute('aria-label') },
            })).catch(error => ({ unavailable: String(error) }));
            await testInfo.attach('dm-matrix-evidence', {
              body: JSON.stringify({
                cell, stages, measurements, preferences, storage: await storedLayout().catch(String),
                authority: await authority().catch(String), isolation, rendered, errors: testInfo.errors,
                pending: ['FullApp canvas picking and pixel analysis', 'group create/reopen/Start Work/task decisions', 'workspace Files rail', 'inline artifact-card activation'],
              }, null, 2), contentType: 'application/json',
            });
            if (!page.isClosed()) await testInfo.attach('dm-matrix-final', { body: await page.screenshot({ timeout: 5_000 }), contentType: 'image/png' });
            expect(isolation.escapedHttp).toEqual([]);
            expect(isolation.escapedSockets).toEqual([]);
            expect(isolation.deniedSockets).toEqual([]);
            expect(isolation.browserErrors).toEqual([]);
            expect(isolation.deniedHttp.filter(request => /^(POST|PATCH|PUT|DELETE) /.test(request.key)), 'no unexpected or duplicate write request').toEqual([]);
            expect(rendered).toHaveProperty('activeMedia', []);
            expect(rendered).toHaveProperty('capabilities.installed', true);
            expect(rendered).toHaveProperty('capabilities.blockedCapabilities', ['serviceWorker.register']);
            expect(context.serviceWorkers()).toEqual([]);
            expect(await page.evaluate(() => navigator.serviceWorker.controller)).toBeNull();
          }
        });
      }
    }
  });
}