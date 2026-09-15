import {
  test as base, expect, type Locator, type Page, type Route,
  type TestInfo, type WebSocketRoute,
} from '@playwright/test';
import { readFileSync } from 'node:fs';
import type TelemetryFixture from './fixtures/issue1370-telemetry.json';

const telemetryFixture: typeof TelemetryFixture = JSON.parse(
  readFileSync(new URL('./fixtures/issue1370-telemetry.json', import.meta.url), 'utf8'),
);

const ORIGIN = 'http://127.0.0.1:5187';
const FIRST_GENERATION = '13700000000000000000000000000001';
const NEXT_GENERATION = '13700000000000000000000000000002';
const SAMPLE_MS = Date.parse(telemetryFixture.sampleTime);
const SAMPLE_ISO = new Date(SAMPLE_MS).toISOString();
type Profile = typeof telemetryFixture.profile;
type Graph = typeof telemetryFixture.memoryGraph;

interface DevState {
  connected: boolean;
  liveGeneration: string | null;
  liveSequence: number;
  liveDropCount: number;
  agents: Map<string, unknown>;
  openAgentProfile: (id: string) => void;
}

interface BrowserWindow extends Window {
  __store: { getState: () => DevState };
  __issue1370Denied: string[];
  __issue1370PointerEvents: { type: string; x: number; y: number; pointerType: string }[];
}

interface ReadEvidence {
  url: string;
  kind: 'profile' | 'graph';
  scenario: string;
  status: number;
  completion: 'pending' | 'fulfilled' | 'cancelled';
}

interface ResponsePlan {
  payload: Profile | Graph | { detail: string };
  status: number;
  scenario: string;
  gate?: Promise<void>;
}

interface DeferredResponse {
  release: () => void;
  plan: ResponsePlan;
}

function deferredProfile(payload: Profile, scenario: string): DeferredResponse {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  return { release, plan: { payload, status: 200, scenario, gate } };
}

function controlledProfile(increment: number, offsetMs: number): Profile {
  const payload = structuredClone(telemetryFixture.profile);
  const sampledAt = new Date(SAMPLE_MS + offsetMs).toISOString();
  payload.memoryCount += increment;
  payload.uptime += offsetMs / 1000;
  for (const metadata of [payload.memoryCountMetadata, payload.uptimeMetadata]) {
    metadata.sampleStartedAt = sampledAt;
    metadata.sampleCompletedAt = sampledAt;
  }
  return payload;
}

function registryAgent(id: string): Record<string, unknown> {
  return {
    id, agent_type: telemetryFixture.profile.agentType,
    callsign: id === 'alpha' ? 'Alpha' : 'Beta', display_name: id,
    pool: 'science', state: 'active', confidence: 0.8, trust: 0.5,
    tier: 'domain', isCrew: true,
  };
}

class TelemetryHarness {
  readonly reads: ReadEvidence[] = [];
  readonly aborted: string[] = [];
  readonly escaped: string[] = [];
  readonly snapshots: { generation: string; sequence: number; agents: string[] }[] = [];
  readonly snapshotAcknowledgements: {
    generation: string; sequence: number; expectedCount: number;
    observed: Awaited<ReturnType<TelemetryHarness['authority']>>;
  }[] = [];
  readonly dismissedRecreationErrors: number[] = [];
  readonly browserErrors: string[] = [];
  readonly screenshots: string[] = [];
  readonly sockets = new Set<WebSocketRoute>();
  readonly socketUrls: string[] = [];
  readonly socketMessages: string[] = [];
  readonly cancelledRequests: string[] = [];
  readonly fulfilledUrls = new Set<string>();
  profilePlan: ResponsePlan = {
    payload: telemetryFixture.profile, status: 200, scenario: 'canonical-profile',
  };
  readonly profileQueue: ResponsePlan[] = [];
  graphFailure = false;
  emptyGraph = false;
  sequence = 0;

  constructor(readonly page: Page, readonly testInfo: TestInfo) {}

  profileReads(): ReadEvidence[] {
    return this.reads.filter(read => read.kind === 'profile');
  }

  graphReads(): ReadEvidence[] {
    return this.reads.filter(read => read.kind === 'graph');
  }

  async install(): Promise<void> {
    await this.page.clock.setFixedTime(new Date(SAMPLE_MS));
    this.page.on('pageerror', error => { this.browserErrors.push(error.message.slice(0, 500)); });
    await this.page.addInitScript(() => {
      const browser = window as unknown as BrowserWindow;
      browser.__issue1370Denied = [];
      localStorage.removeItem('hxi_seen_intro');
      const denyMedia = (): Promise<MediaStream> => {
        browser.__issue1370Denied.push('getUserMedia');
        return Promise.reject(new DOMException('Media disabled by issue1370 test', 'NotAllowedError'));
      };
      if (navigator.mediaDevices) {
        Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: denyMedia });
        Object.defineProperty(navigator.mediaDevices, 'getDisplayMedia', { configurable: true, value: denyMedia });
        Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', {
          configurable: true, value: async (): Promise<MediaDeviceInfo[]> => [],
        });
      }
      class DeniedRecognition extends EventTarget {
        onerror: ((event: Event) => void) | null = null;
        start(): void {
          browser.__issue1370Denied.push('SpeechRecognition.start');
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
      const NativeWorker = window.Worker;
      window.Worker = new Proxy(NativeWorker, {
        construct(target, args: [string | URL, WorkerOptions?]): Worker {
          const url = new URL(String(args[0]), location.href);
          if (url.origin !== location.origin || !url.pathname.includes('/monaco-editor/')
            || !url.pathname.endsWith('.js')) {
            browser.__issue1370Denied.push('Worker');
            throw new DOMException('Worker network disabled by issue1370 test', 'SecurityError');
          }
          return Reflect.construct(target, args) as Worker;
        },
      });
      if ('SharedWorker' in window) {
        Object.defineProperty(window, 'SharedWorker', {
          configurable: true,
          value: class {
            constructor() {
              browser.__issue1370Denied.push('SharedWorker');
              throw new DOMException('Shared workers disabled by issue1370 test', 'SecurityError');
            }
          },
        });
      }
    });

    await this.page.context().route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== ORIGIN || request.resourceType() === 'media'
        || /\.(?:onnx|wasm|vrm|glb|gltf|bin|tflite|mp3|wav|mp4)(?:$|\?)/i.test(url.pathname)) {
        this.aborted.push(request.url());
        await route.abort('blockedbyclient');
        return;
      }
      if (url.pathname.startsWith('/api/')) {
        await this.handleApi(route, url);
        return;
      }
      if (request.method() === 'GET' && (url.pathname === '/'
        || /^\/(?:src\/|node_modules\/|@vite\/|@id\/|@fs\/|@react-refresh$)/.test(url.pathname))) {
        await route.continue();
        return;
      }
      this.aborted.push(request.url());
      await route.abort('blockedbyclient');
    });

    await this.page.routeWebSocket(/.*/, socket => {
      const url = new URL(socket.url());
      this.socketUrls.push(socket.url());
      if (url.origin === 'ws://127.0.0.1:5187' && url.pathname === '/ws/events' && !url.search) {
        this.sockets.add(socket);
        socket.onClose(() => { this.sockets.delete(socket); });
        socket.onMessage(message => { this.socketMessages.push(String(message)); });
      } else if (url.origin === 'ws://127.0.0.1:5187' && url.pathname === '/') {
        socket.send(JSON.stringify({ type: 'connected' }));
        socket.onMessage(() => {});
      } else {
        this.aborted.push(socket.url());
        socket.close({ code: 1008, reason: 'Not admitted by issue1370' });
      }
    });
    this.page.on('response', response => {
      const url = new URL(response.url());
      if (url.origin !== ORIGIN
        || (url.pathname.startsWith('/api/') && !this.fulfilledUrls.has(response.url()))) {
        this.escaped.push(response.url());
      }
    });
    this.page.on('requestfailed', request => {
      if (request.url().endsWith('/profile') && request.failure()?.errorText.includes('ABORTED')) {
        this.cancelledRequests.push(request.url());
      }
    });
  }

  async handleApi(route: Route, url: URL): Promise<void> {
    if (route.request().method() !== 'GET') {
      this.aborted.push(route.request().url());
      await route.abort('blockedbyclient');
      return;
    }
    if (url.pathname === '/api/agent/alpha/profile') {
      await this.respond(route, 'profile', this.profileQueue.shift() ?? this.profilePlan);
      return;
    }
    if (url.pathname === '/api/agent/alpha/memory-graph') {
      expect([...url.searchParams.keys()]).toEqual(['ship_wide']);
      expect(['true', 'false']).toContain(url.searchParams.get('ship_wide'));
      const shipWide = url.searchParams.get('ship_wide') === 'true';
      const canonical = shipWide ? telemetryFixture.shipGraph : telemetryFixture.memoryGraph;
      let payload = structuredClone(canonical);
      let scenario = shipWide ? 'canonical-ship-graph' : 'canonical-agent-graph';
      if (this.emptyGraph) {
        payload = { ...payload, nodes: [], edges: [], meta: { ...payload.meta, nodes_shown: 0 } };
        scenario = 'synthetic-unfiltered-empty-selection-not-filtered-fixture';
      }
      expect(payload.meta.selection.time_range_hours).toBeNull();
      await this.respond(route, 'graph', this.graphFailure
        ? { payload: { detail: 'Synthetic graph outage' }, status: 503, scenario: 'synthetic-graph-503' }
        : { payload, status: 200, scenario });
      return;
    }
    if (url.pathname === '/api/config/avatars-enabled') {
      this.fulfilledUrls.add(route.request().url());
      await route.fulfill({ json: { enabled: false } });
      return;
    }
    if (url.pathname === '/api/threads' || url.pathname === '/api/threads/summaries') {
      this.fulfilledUrls.add(route.request().url());
      await route.fulfill({ json: url.pathname.endsWith('/summaries') ? { summaries: {} } : { threads: [] } });
      return;
    }
    this.aborted.push(route.request().url());
    await route.abort('blockedbyclient');
  }

  async respond(route: Route, kind: ReadEvidence['kind'], plan: ResponsePlan): Promise<void> {
    const read: ReadEvidence = {
      url: route.request().url(), kind, scenario: plan.scenario,
      status: plan.status, completion: 'pending',
    };
    this.reads.push(read);
    if (plan.gate) await plan.gate;
    this.fulfilledUrls.add(route.request().url());
    try {
      await route.fulfill({ status: plan.status, json: plan.payload });
      read.completion = 'fulfilled';
    } catch (error) {
      if (!plan.gate || !route.request().failure()) throw error;
      read.completion = 'cancelled';
    }
  }

  async navigate(): Promise<void> {
    await this.page.goto(this.testInfo.project.use.isMobile ? '/#desktop' : '/');
    if (this.testInfo.project.use.isMobile) await expect(this.page).toHaveURL(`${ORIGIN}/#desktop`);
    await this.page.waitForFunction(() => Boolean((window as unknown as BrowserWindow).__store));
    await expect.poll(() => this.sockets.size).toBeGreaterThan(0);
    await expect.poll(() => this.authority()).toMatchObject({ connected: true, generation: null });
    await expect(this.page.getByText('Registered agents: unavailable', { exact: true })).toBeVisible();
  }

  async authority(): Promise<{ connected: boolean; generation: string | null; sequence: number; count: number; drops: number }> {
    return this.page.evaluate(() => {
      const state = (window as unknown as BrowserWindow).__store.getState();
      return {
        connected: state.connected, generation: state.liveGeneration,
        sequence: state.liveSequence, count: state.agents.size, drops: state.liveDropCount,
      };
    });
  }

  async snapshot(ids: string[], generation = FIRST_GENERATION): Promise<void> {
    await expect.poll(() => this.sockets.size).toBeGreaterThan(0);
    const socket = [...this.sockets].at(-1)!;
    const sequence = ++this.sequence;
    const frame = {
      type: 'state_snapshot', timestamp: SAMPLE_MS / 1000,
      stream: { generation, sequence },
      data: {
        agents: ids.map(registryAgent), connections: [], pools: [],
        system_mode: 'active', tc_n: 0, routing_entropy: 0, fresh_boot: false,
      },
    };
    this.snapshots.push({ generation, sequence, agents: ids });
    socket.send(JSON.stringify(frame));
    try {
      await expect.poll(() => this.authority()).toMatchObject({
        connected: true, generation, sequence, count: ids.length, drops: 0,
      });
    } finally {
      this.snapshotAcknowledgements.push({ generation, sequence, expectedCount: ids.length, observed: await this.authority() });
    }
    if (await this.page.getByRole('heading', { name: 'Welcome to ProbOS' }).count() === 0) {
      await this.dismissRecreationError();
    }
  }

  async dismissRecreationError(): Promise<void> {
    await expect.poll(() => this.aborted.filter(url => new URL(url).pathname === '/api/recreation/active').length)
      .toBeGreaterThan(0);
    const panel = this.page.getByRole('region', { name: 'Tic-Tac-Toe game', exact: true });
    await expect(panel.getByRole('alert')).toBeVisible();
    await panel.getByRole('button', { name: 'Close game', exact: true }).click();
    await expect(panel).toHaveCount(0);
    this.dismissedRecreationErrors.push(this.sequence);
  }

  async disconnect(): Promise<void> {
    const sockets = [...this.sockets];
    expect(sockets.length).toBeGreaterThan(0);
    for (const socket of sockets) socket.close({ code: 1001, reason: 'Synthetic reconnect' });
    this.sockets.clear();
    await expect.poll(() => this.authority(), { intervals: [10, 25, 50] })
      .toMatchObject({ connected: false, generation: null });
  }

  async openHealth(): Promise<void> {
    await this.navigate();
    await this.snapshot(['alpha', 'beta']);
    await this.page.getByRole('button', { name: 'Got it', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: 'Welcome to ProbOS' })).toHaveCount(0);
    await this.dismissRecreationError();
    await this.page.evaluate(() => {
      (window as unknown as BrowserWindow).__store.getState().openAgentProfile('alpha');
    });
    await expect.poll(() => this.profileReads().filter(read => read.completion === 'fulfilled').length).toBeGreaterThan(0);
    const before = this.profileReads().length;
    await this.page.getByRole('button', { name: 'Health', exact: true }).click();
    await expect.poll(() => this.profileReads().length).toBeGreaterThan(before);
  }

  profileStatus(): Locator {
    return this.page.getByRole('button', { name: 'Refresh profile', exact: true })
      .locator('..').getByRole('status');
  }

  graphStatus(): Locator {
    return this.page.getByRole('button', { name: 'Refresh memory graph', exact: true })
      .locator('..').getByRole('status');
  }

  async screenshot(name: string, target?: Locator): Promise<void> {
    const path = this.testInfo.outputPath(`${name}.png`);
    if (target) await target.screenshot({ path });
    else await this.page.screenshot({ path });
    this.screenshots.push(path);
    await this.testInfo.attach(name, { path, contentType: 'image/png' });
  }

  async finish(): Promise<void> {
    const browserDenials = this.page.isClosed() ? ['page-closed'] : await this.page.evaluate(() =>
      (window as unknown as BrowserWindow).__issue1370Denied ?? []);
    await this.testInfo.attach('issue1370-network-and-fixture-evidence', {
      contentType: 'application/json',
      body: JSON.stringify({
        fixture: 'ui/e2e/fixtures/issue1370-telemetry.json',
        clock: {
          mode: 'Fixed Date for telemetry races; advancing system time at Memory scenario boundaries for graph debounce; running timers and requestAnimationFrame',
          sampleTime: telemetryFixture.sampleTime,
        },
        reads: this.reads, snapshots: this.snapshots, screenshots: this.screenshots,
        snapshotAcknowledgements: this.snapshotAcknowledgements,
        dismissedRecreationErrors: this.dismissedRecreationErrors, browserErrors: this.browserErrors,
        interceptedWebSockets: this.socketUrls, clientSocketMessages: this.socketMessages,
        intentionallyAborted: this.aborted, browserDenials,
        escapedResponses: this.escaped, cancelledProfileRequests: this.cancelledRequests,
        emptyScenario: 'Explicit synthetic unfiltered response; filteredGraph is not served for unfiltered requests',
      }, null, 2),
    });
    expect(this.escaped, 'No API or external response may bypass interception').toEqual([]);
    expect(browserDenials, 'No physical media, recognition or unadmitted worker may be started').toEqual([]);
    expect(this.browserErrors, 'No uncaught browser error may invalidate the exercised UI').toEqual([]);
  }
}

const test = base.extend<{ harness: TelemetryHarness }>({
  harness: async ({ page }, use, testInfo) => {
    const harness = new TelemetryHarness(page, testInfo);
    await harness.install();
    try {
      await use(harness);
    } finally {
      await harness.finish();
    }
  },
});

async function readableAndSeparate(page: Page, locators: Locator[]): Promise<void> {
  const bounds: { x: number; y: number; width: number; height: number }[] = [];
  const viewport = page.viewportSize()!;
  for (const locator of locators) {
    await expect(locator).toBeVisible();
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(0);
    expect(box!.height).toBeGreaterThan(0);
    expect(box!.x).toBeGreaterThanOrEqual(-1);
    expect(box!.y).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1);
    expect(await locator.evaluate(element => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const parent = element.getBoundingClientRect();
      return Array.from(range.getClientRects()).every(rect =>
        rect.left >= parent.left - 1 && rect.right <= parent.right + 1
        && rect.top >= parent.top - 1 && rect.bottom <= parent.bottom + 1);
    }), 'Text and child controls fit their bounds').toBe(true);
    bounds.push(box!);
  }
  for (let first = 0; first < bounds.length; first += 1) {
    for (let second = first + 1; second < bounds.length; second += 1) {
      const left = bounds[first];
      const right = bounds[second];
      const overlapWidth = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x);
      const overlapHeight = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y);
      expect(overlapWidth <= 1 || overlapHeight <= 1, 'Independent text and controls do not overlap').toBe(true);
    }
  }
}

async function proveGraphPixelsAndInteraction(harness: TelemetryHarness): Promise<void> {
  const { page, testInfo } = harness;
  const canvas = page.locator('.scene-container canvas');
  await expect(canvas).toHaveCount(1);
  await expect(canvas).toBeVisible();
  expect(await canvas.evaluate(element => ({
    width: (element as HTMLCanvasElement).width, height: (element as HTMLCanvasElement).height,
  }))).toEqual({ width: expect.any(Number), height: expect.any(Number) });

  await canvas.evaluate(element => {
    const browser = window as unknown as BrowserWindow;
    browser.__issue1370PointerEvents = [];
    for (const type of ['pointermove', 'pointerdown', 'pointerup']) {
      element.addEventListener(type, event => {
        const pointer = event as PointerEvent;
        browser.__issue1370PointerEvents.push({ type, x: pointer.clientX, y: pointer.clientY, pointerType: pointer.pointerType });
        if (browser.__issue1370PointerEvents.length > 24) browser.__issue1370PointerEvents.shift();
      }, { passive: true });
    }
  });

  const measure = async (): Promise<{
    colors: number; nodePixels: number; x: number; y: number; width: number; height: number;
    candidates: { x: number; y: number; pixels: number }[];
  }> => {
    const png = await canvas.screenshot();
    return page.evaluate(async encoded => {
      const image = new Image();
      image.src = `data:image/png;base64,${encoded}`;
      await image.decode();
      const copy = document.createElement('canvas');
      copy.width = image.naturalWidth;
      copy.height = image.naturalHeight;
      const context = copy.getContext('2d');
      if (!context) throw new Error('Screenshot pixel decoding requires Canvas2D');
      context.drawImage(image, 0, 0);
      const pixels = context.getImageData(0, 0, copy.width, copy.height).data;
      const colors = new Set<number>();
      const matchingPixels = new Set<number>();
      let nodePixels = 0;
      let strongest = 0;
      let pointX = 0;
      let pointY = 0;
      for (let row = 20; row < copy.height - 80; row += 1) {
        for (let column = 20; column < copy.width - 20; column += 1) {
          const offset = (row * copy.width + column) * 4;
          const red = pixels[offset];
          const green = pixels[offset + 1];
          const blue = pixels[offset + 2];
          colors.add((red << 16) | (green << 8) | blue);
          if (blue > red * 1.1 && red > green * 1.1 && red + blue > 35) {
            nodePixels += 1;
            matchingPixels.add(row * copy.width + column);
            const strength = red + blue - 2 * green;
            if (strength > strongest) {
              strongest = strength;
              pointX = column;
              pointY = row;
            }
          }
        }
      }
      const candidates: { x: number; y: number; pixels: number }[] = [];
      while (matchingPixels.size > 0) {
        const first = matchingPixels.values().next().value!;
        matchingPixels.delete(first);
        const region = [first];
        let sumX = 0;
        let sumY = 0;
        for (let cursor = 0; cursor < region.length; cursor += 1) {
          const current = region[cursor];
          const column = current % copy.width;
          const row = Math.floor(current / copy.width);
          sumX += column;
          sumY += row;
          for (const neighbor of [
            column > 0 ? current - 1 : -1, column + 1 < copy.width ? current + 1 : -1,
            row > 0 ? current - copy.width : -1, row + 1 < copy.height ? current + copy.width : -1,
          ]) {
            if (matchingPixels.delete(neighbor)) region.push(neighbor);
          }
        }
        const centerX = sumX / region.length;
        const centerY = sumY / region.length;
        const distance = (pixel: number): number => (pixel % copy.width - centerX) ** 2
          + (Math.floor(pixel / copy.width) - centerY) ** 2;
        const interior = region.reduce((best, pixel) => distance(pixel) < distance(best) ? pixel : best);
        candidates.push({ x: interior % copy.width + 0.5, y: Math.floor(interior / copy.width) + 0.5, pixels: region.length });
      }
      candidates.sort((left, right) => right.pixels - left.pixels);
      return {
        colors: colors.size, nodePixels, x: pointX, y: pointY, width: copy.width, height: copy.height,
        candidates: candidates.slice(0, 3),
      };
    }, png.toString('base64'));
  };
  await expect.poll(async () => (await measure()).nodePixels).toBeGreaterThan(3);
  await harness.screenshot('memory-agent-canvas', canvas);
  let pixels = await measure();
  let position = { x: 0, y: 0 };
  const attempts: Record<string, unknown>[] = [];
  try {
    await expect.poll(async () => {
      if (await page.getByText('Episode Detail', { exact: true }).isVisible()) return true;
      await page.mouse.move(1, 1);
      pixels = await measure();
      expect(pixels.candidates.length).toBeGreaterThan(0);
      const bounds = (await canvas.boundingBox())!;
      const graphResponses = harness.graphReads().length;
      for (const candidate of pixels.candidates.slice(0, 1)) {
        await page.mouse.move(1, 1);
        position = { x: candidate.x * bounds.width / pixels.width, y: candidate.y * bounds.height / pixels.height };
        await canvas.hover({ position });
        const frames = await page.evaluate(() => new Promise<number[]>(resolve => {
          requestAnimationFrame(first => requestAnimationFrame(second => resolve([first, second])));
        }));
        const observed = await canvas.evaluate(element => {
          const pointer = (window as unknown as BrowserWindow).__issue1370PointerEvents.at(-1)!;
          const rect = element.getBoundingClientRect();
          return {
            clickable: element.classList.contains('clickable'), pointer, devicePixelRatio: window.devicePixelRatio,
            unobstructed: document.elementFromPoint(pointer.x, pointer.y) === element,
            bounds: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          };
        });
        expect(observed.unobstructed, 'Delivered pointer reaches the real canvas').toBe(true);
        expect(Math.abs(observed.pointer.x - bounds.x - position.x)).toBeLessThanOrEqual(1);
        expect(Math.abs(observed.pointer.y - bounds.y - position.y)).toBeLessThanOrEqual(1);
        const sameResponseAndBounds = graphResponses === harness.graphReads().length
          && JSON.stringify(bounds) === JSON.stringify(observed.bounds);
        if (attempts.length < 32) attempts.push({
          kind: 'interior', candidate, position, frames, observed,
          screenshot: { width: pixels.width, height: pixels.height }, graphResponses,
          currentGraphResponses: harness.graphReads().length, sameResponseAndBounds,
        });
        if (!sameResponseAndBounds) return false;
        if (observed.clickable) {
          await page.mouse.click(observed.pointer.x, observed.pointer.y);
          await page.evaluate(() => new Promise<void>(resolve => {
            requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
          }));
          return page.getByText('Episode Detail', { exact: true }).isVisible();
        }
      }
      return false;
    }, { intervals: [100, 250, 500] }).toBe(true);
    expect(pixels.nodePixels).toBeGreaterThan(3);
    expect(pixels.colors).toBeGreaterThan(8);
    expect(pixels.width).toBeGreaterThan(100);
    expect(pixels.height).toBeGreaterThan(100);
    await expect(page.getByText('Episode Detail', { exact: true })).toBeVisible();
    await expect(page.getByText(/^Input: (Alpha observation|Shared observation|Older observation)$/, { exact: true })).toBeVisible();
    await harness.screenshot('memory-node-interaction');
  } finally {
    await testInfo.attach('memory-canvas-pixel-proof', { body: JSON.stringify(pixels), contentType: 'application/json' });
    await testInfo.attach('memory-canvas-target-diagnostic', { body: JSON.stringify(attempts), contentType: 'application/json' });
  }
}

test('Welcome reflects accepted registry authority, zero, change and reconnect', async ({ harness, page }) => {
  await harness.navigate();
  const population = page.getByText(/^Registered agents:/);
  await harness.screenshot('welcome-unavailable');
  await harness.snapshot(['alpha', 'beta']);
  await expect(population).toHaveText('Registered agents: 2');
  await expect(page.getByText(/47 AI agents|input box above/i)).toHaveCount(0);
  await readableAndSeparate(page, [
    page.getByRole('heading', { name: 'Welcome to ProbOS' }), population,
    page.getByText('Ask it anything in the input box', { exact: true }),
    page.getByRole('button', { name: 'Got it', exact: true }),
  ]);
  await harness.screenshot('welcome-two-registered');
  await harness.snapshot([]);
  await expect(population).toHaveText('Registered agents: 0');
  await harness.screenshot('welcome-authoritative-zero');
  await harness.snapshot(['alpha']);
  await expect(population).toHaveText('Registered agents: 1');
  await harness.disconnect();
  await expect(population).toHaveText('Registered agents: unavailable');
  await expect.poll(() => harness.authority()).toMatchObject({ connected: true, generation: null });
  await expect(population).toHaveText('Registered agents: unavailable');
  await harness.snapshot(['alpha', 'beta'], NEXT_GENERATION);
  await expect(population).toHaveText('Registered agents: 2');
  await harness.screenshot('welcome-reconnected');
  await page.getByRole('button', { name: 'Got it', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to ProbOS' })).toHaveCount(0);
});

test('Health and Profile use fixture reads, bounded polling, stale samples and fenced refreshes', async ({ harness, page }) => {
  expect(telemetryFixture.profile.memoryCount).toBe(telemetryFixture.selfQuery.domains.memory.episode_count);
  expect(telemetryFixture.profile.uptime).toBe(telemetryFixture.selfQuery.domains.temporal.system_uptime_seconds);
  await harness.openHealth();
  await expect(page.getByText('4 episodes', { exact: true })).toBeVisible();
  await expect(page.getByText('11m', { exact: true })).toBeVisible();
  await expect(harness.profileStatus()).toContainText(`Current. Sampled ${SAMPLE_ISO}`);
  await readableAndSeparate(page, [
    harness.profileStatus(), page.getByRole('button', { name: 'Refresh profile', exact: true }),
    page.getByText('Stored agent-membership episodes', { exact: true }),
    page.getByText('4 episodes', { exact: true }),
    page.getByText('System runtime uptime', { exact: true }), page.getByText('11m', { exact: true }),
  ]);
  await expect(page.getByText(`available; subject sovereign-alpha; sampled ${telemetryFixture.sampleTime}`, { exact: true })).toBeVisible();
  await harness.screenshot('health-canonical-sample');

  await page.clock.setFixedTime(new Date(SAMPLE_MS + 1000));
  harness.profilePlan = { payload: controlledProfile(10, 1000), status: 200, scenario: 'synthetic-manual-count-plus-ten' };
  const manualBefore = harness.profileReads().length;
  await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
  await expect.poll(() => harness.profileReads().length).toBeGreaterThan(manualBefore);
  await expect(page.getByText('14 episodes', { exact: true })).toBeVisible();

  await page.clock.setFixedTime(new Date(SAMPLE_MS + 11_000));
  harness.profilePlan = { payload: controlledProfile(20, 11_000), status: 200, scenario: 'synthetic-poll-count-plus-twenty' };
  const pollBefore = harness.profileReads().length;
  await expect.poll(() => harness.profileReads().length, { timeout: 16_000 }).toBeGreaterThan(pollBefore);
  await expect(page.getByText('24 episodes', { exact: true })).toBeVisible();
  const currentSample = new Date(SAMPLE_MS + 11_000).toISOString();
  await expect(harness.profileStatus()).toContainText(`Current. Sampled ${currentSample}`);

  const oldRead = deferredProfile(controlledProfile(900, 11_000), 'synthetic-delayed-superseded-profile');
  harness.profileQueue.push(oldRead.plan);
  const raceBefore = harness.profileReads().length;
  await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
  await expect.poll(() => harness.profileReads().length).toBeGreaterThan(raceBefore);
  const cancellationsBefore = harness.cancelledRequests.length;
  try {
    harness.profilePlan = { payload: controlledProfile(30, 11_000), status: 200, scenario: 'synthetic-newer-same-agent-profile' };
    await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
    await expect(page.getByText('34 episodes', { exact: true })).toBeVisible();
    await expect.poll(() => harness.cancelledRequests.length).toBeGreaterThan(cancellationsBefore);
  } finally {
    oldRead.release();
  }
  await expect.poll(() => harness.reads.find(read => read.scenario === oldRead.plan.scenario)?.completion).not.toBe('pending');
  await expect(page.getByText('904 episodes', { exact: true })).toHaveCount(0);

  harness.profilePlan = { payload: { detail: 'Synthetic profile outage' }, status: 503, scenario: 'synthetic-profile-503' };
  await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
  await expect(harness.profileStatus()).toContainText(`Stale. Sampled ${currentSample}`);
  await expect(harness.profileStatus()).toContainText('Unavailable. Retry the request.');
  await expect(page.getByText('34 episodes', { exact: true })).toBeVisible();
  await harness.screenshot('health-stale-after-503');

  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await expect(harness.profileStatus()).toContainText(`Stale. Sampled ${currentSample}`);
  await expect(page.getByText('Identity', { exact: true })).toBeVisible();
  await harness.screenshot('profile-stale-after-503');

  harness.profilePlan = { payload: controlledProfile(40, 11_000), status: 200, scenario: 'synthetic-generation-recovery' };
  const restartRead = deferredProfile(controlledProfile(800, 11_000), 'synthetic-pre-restart-profile');
  harness.profileQueue.push(restartRead.plan);
  const restartBefore = harness.profileReads().length;
  await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
  await expect.poll(() => harness.profileReads().length).toBeGreaterThan(restartBefore);
  try {
    await harness.disconnect();
    await expect(page.getByText('Identity', { exact: true })).toHaveCount(0);
    await harness.snapshot(['alpha', 'beta'], NEXT_GENERATION);
    await expect(harness.profileStatus()).toContainText('Current.');
  } finally {
    restartRead.release();
  }
  await expect.poll(() => harness.reads.find(read => read.scenario === restartRead.plan.scenario)?.completion).not.toBe('pending');
  await harness.screenshot('profile-new-generation-current');
  await page.getByRole('button', { name: 'Health', exact: true }).click();
  await expect(page.getByText('44 episodes', { exact: true })).toBeVisible();
  await expect(page.getByText('804 episodes', { exact: true })).toHaveCount(0);
  expect(harness.profileReads().some(read => read.scenario === 'canonical-profile' && read.completion === 'fulfilled')).toBe(true);
  expect(harness.profileReads().some(read => read.scenario === 'synthetic-poll-count-plus-twenty' && read.completion === 'fulfilled')).toBe(true);
});

test('Memory renders real graph nodes and distinguishes scope, stale data and synthetic empty selection', async ({ harness, page }) => {
  await harness.openHealth();
  await expect(page.getByText('4 episodes', { exact: true })).toBeVisible();
  await page.clock.setSystemTime(new Date(SAMPLE_MS));
  await page.getByRole('button', { name: 'Memory', exact: true }).click();
  await expect.poll(() => harness.graphReads().length).toBeGreaterThan(0);
  const agentScope = page.getByText('Displayed bounded agent sample: 3 episodes; 0 edges', { exact: true });
  const storedScope = page.getByText('Selected-agent stored membership: 4 episodes', { exact: true });
  await expect(agentScope).toBeVisible();
  await expect(storedScope).toBeVisible();
  await expect(harness.graphStatus()).toContainText(`Current. Sampled ${SAMPLE_ISO}`);
  await expect(page.getByText(/Showing .* of/)).toHaveCount(0);
  await readableAndSeparate(page, [
    agentScope, storedScope, page.getByRole('checkbox', { name: 'Ship-wide' }).locator('..'),
    harness.graphStatus(), page.getByRole('button', { name: 'Refresh memory graph', exact: true }),
  ]);
  await harness.screenshot('memory-agent-scope');
  await proveGraphPixelsAndInteraction(harness);

  const shipBefore = harness.graphReads().length;
  await page.clock.setSystemTime(new Date(SAMPLE_MS));
  await page.getByRole('checkbox', { name: 'Ship-wide' }).check();
  await expect.poll(() => harness.graphReads().length).toBeGreaterThan(shipBefore);
  await expect(page.getByText('Displayed bounded registered-crew sample: 4 episodes; 0 edges', { exact: true })).toBeVisible();
  await expect(storedScope).toBeVisible();
  await expect(page.getByText(/Showing .* of/)).toHaveCount(0);
  await harness.screenshot('memory-ship-scope');

  harness.graphFailure = true;
  const failedBefore = harness.graphReads().length;
  await page.clock.setSystemTime(new Date(SAMPLE_MS));
  await page.getByRole('button', { name: 'Refresh memory graph', exact: true }).click();
  await expect.poll(() => harness.graphReads().length).toBeGreaterThan(failedBefore);
  await expect(harness.graphStatus()).toContainText(`Stale. Sampled ${SAMPLE_ISO}`);
  await expect(harness.graphStatus()).toContainText('Unavailable. Retry the request.');
  await expect(storedScope).toBeVisible();
  await expect(page.getByText('No episodes in this bounded selection.', { exact: true })).toHaveCount(0);
  await harness.screenshot('memory-stale-after-503');

  expect(telemetryFixture.filteredGraph.meta.selection.time_range_hours).toBe(1);
  harness.graphFailure = false;
  harness.emptyGraph = true;
  await page.clock.setSystemTime(new Date(SAMPLE_MS));
  await page.getByRole('checkbox', { name: 'Ship-wide' }).uncheck();
  await expect(page.getByText('No episodes in this bounded selection.', { exact: true })).toBeVisible();
  await expect(page.getByText('Displayed bounded agent sample: 0 episodes; 0 edges', { exact: true })).toBeVisible();
  await expect(storedScope).toBeVisible();
  await expect(harness.graphStatus()).toContainText('Current.');
  await expect(page.locator('.scene-container canvas')).toHaveCount(0);
  await harness.screenshot('memory-synthetic-unfiltered-empty');
  expect(harness.graphReads().some(read => read.scenario === 'canonical-agent-graph' && read.completion === 'fulfilled')).toBe(true);
  expect(harness.graphReads().some(read => read.scenario === 'canonical-ship-graph' && read.completion === 'fulfilled')).toBe(true);
  expect(harness.graphReads().some(read => read.scenario === 'synthetic-unfiltered-empty-selection-not-filtered-fixture')).toBe(true);
});

test('initial profile outage is unavailable on Health and Profile, then recovers through HTTP', async ({ harness, page }) => {
  harness.profilePlan = { payload: { detail: 'Synthetic initial outage' }, status: 503, scenario: 'synthetic-initial-profile-503' };
  await harness.openHealth();
  await expect(harness.profileStatus()).toContainText('Unavailable.');
  await expect(harness.profileStatus()).toContainText('Unavailable. Retry the request.');
  await expect(page.getByText('4 episodes', { exact: true })).toHaveCount(0);
  await expect(page.getByText('11m', { exact: true })).toHaveCount(0);
  await harness.screenshot('health-initial-unavailable');
  await page.getByRole('button', { name: 'Profile', exact: true }).click();
  await expect(harness.profileStatus()).toContainText('Unavailable.');
  await expect(page.getByText('Identity', { exact: true })).toHaveCount(0);
  await harness.screenshot('profile-initial-unavailable');
  harness.profilePlan = { payload: telemetryFixture.profile, status: 200, scenario: 'canonical-profile-recovery' };
  const before = harness.profileReads().length;
  await page.getByRole('button', { name: 'Refresh profile', exact: true }).click();
  await expect.poll(() => harness.profileReads().length).toBeGreaterThan(before);
  await expect(harness.profileStatus()).toContainText(`Current. Sampled ${SAMPLE_ISO}`);
  await expect(page.getByText('Identity', { exact: true })).toBeVisible();
  await readableAndSeparate(page, [harness.profileStatus(), page.getByRole('button', { name: 'Refresh profile', exact: true })]);
  await harness.screenshot('profile-canonical-recovery');
});