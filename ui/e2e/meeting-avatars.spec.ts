// AD-941 Issue 4 — Start meeting must render the Captain's gallery slot plus a
// live avatar slot for every crew participant. With no camera/screen stream the
// Captain slot falls back to the amber person glyph (captain-icon).
import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { EZRI, YEO, mkThread, mockChatApi, gotoApp, seedAgents, openGroupChat } from './_helpers';

test.use({
  permissions: ['microphone'],
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
});

async function isolateAvatarBrowser(page: Page) {
  const fleet = { created: 0, closed: 0, active: new Set<WebSocketRoute>(), rejected: [] as string[] };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['http://localhost:5173', 'http://127.0.0.1:5173'].includes(url.origin)) {
      fleet.rejected.push(url.origin);
      return route.abort();
    }
    if (url.pathname.startsWith('/api/')) return route.abort();
    return route.continue();
  });
  await page.routeWebSocket(/.*/, socket => {
    if (new URL(socket.url()).pathname !== '/api/agent/avatar-telemetry/stream') return;
    fleet.created += 1;
    fleet.active.add(socket);
    socket.onClose(() => {
      if (fleet.active.delete(socket)) fleet.closed += 1;
    });
    socket.send(JSON.stringify({ type: 'snapshot', agent_id: 'ezri', working_state: 'idle' }));
  });
  return fleet;
}

test.describe('AD-941 Issue 4 — Start meeting renders captain + crew avatar slots', () => {
  test('captain-slot + avatar-slot per crew + captain-icon fallback (no camera)', async ({ page }) => {
    await isolateAvatarBrowser(page);
    const group = mkThread('g1', 'Ezri, Yeo', ['ezri', 'yeo']);
    await mockChatApi(page, { threads: [group], messagesByThread: { g1: [] } });
    await gotoApp(page);
    await seedAgents(page, [EZRI, YEO]);

    // Open the group directly via the store (no CHATS panel overlapping the
    // header), then start the meeting.
    await openGroupChat(page, 'ezri', group);
    await expect(page.getByTestId('group-chat-header')).toBeVisible();

    // Start the meeting -> PATCH meeting_active true -> MeetingView mounts.
    await page.getByTestId('meeting-toggle').click();

    await expect(page.getByTestId('meeting-view')).toBeVisible();
    await expect(page.getByTestId('captain-slot')).toBeVisible();
    await expect(page.getByTestId('avatar-slot-ezri')).toBeVisible();
    await expect(page.getByTestId('avatar-slot-yeo')).toBeVisible();
    // No camera/screen stream in the harness -> the icon fallback renders.
    await expect(page.getByTestId('captain-icon')).toBeVisible();
  });
});

test.describe('issue #1367 controlled microphone and avatar transitions', () => {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 430, height: 932 }]) {
    test(`bounds telemetry and recovers asset errors at ${viewport.width}px`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      const fleet = await isolateAvatarBrowser(page);
      const group = mkThread('g1367', 'Ezri, Yeo', ['captain', 'ezri', 'yeo'], { metadata: { meeting_active: true } });
      const direct = mkThread('d1367', 'Ezri', ['captain', 'ezri']);
      await mockChatApi(page, { threads: [direct, group], messagesByThread: { g1367: [], d1367: [] } });
      let profileReads = 0;
      let assetReads = 0;
      let vadModuleReads = 0;
      await page.route('**/src/audio/silero-vad.ts*', route => {
        vadModuleReads += 1;
        return route.fulfill({ contentType: 'application/javascript', body: `
          export async function _loadOnnxRuntime() { return null; }
          export async function createVadSession() {
            return { score: async () => { window.__avatarProbe.scored++; return 0.1; }, destroy() {} };
          }
        ` });
      });
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/config/avatars-enabled') return route.fulfill({ json: { enabled: true } });
        if (url.pathname === '/api/voice/health') return route.fulfill({ json: { engine: 'browser', enabled: true } });
        if (/^\/api\/agent\/(ezri|yeo)\/profile$/.test(url.pathname)) {
          profileReads += 1;
          const participant = url.pathname.split('/')[3];
          return route.fulfill({ json: {
            id: participant, callsign: participant === 'ezri' ? 'Ezri' : 'Yeo', isCrew: true,
            appearance: { vrm_url: `/api/system/avatars/missing-${participant}.vrm`, expression_overrides: {}, color_palette_hint: '' },
          } });
        }
        if (url.pathname.startsWith('/api/system/avatars/missing-')) {
          assetReads += 1;
          return route.fulfill({ status: 404, body: 'Controlled missing asset' });
        }
        return route.fallback();
      });
      await page.addInitScript(() => {
        const state = { started: 0, stopped: 0, captured: 0, scored: 0, pcm: 0, progress: 0, tracks: [] as MediaStreamTrack[] };
        (window as any).__avatarProbe = state;
        const acquire = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = async options => {
          const stream = await acquire(options);
          state.captured += 1;
          state.tracks.push(...stream.getTracks());
          return stream;
        };
        class ControlledRecognition {
          onresult: ((event: unknown) => void) | null = null;
          onend: (() => void) | null = null;
          start(): void { state.started += 1; }
          stop(): void { state.stopped += 1; this.onend?.(); }
          abort(): void { state.stopped += 1; this.onend?.(); }
        }
        (window as any).SpeechRecognition = ControlledRecognition;
        (window as any).webkitSpeechRecognition = ControlledRecognition;
        localStorage.setItem('hxi_chat_mic_mode_ezri', 'ptt');
      });
      await gotoApp(page);
      await seedAgents(page, [EZRI, YEO]);
      await openGroupChat(page, 'ezri', group);
      await expect(page.getByTestId('meeting-view')).toBeVisible();
      await page.getByRole('button', { name: 'Voice input', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Stop listening', exact: true })).toBeVisible();
      await expect.poll(() => profileReads).toBeGreaterThan(0);
      const started = await page.evaluate(async () => {
        const vad = await import('/src/audio/voiceActivity.ts');
        const transformers = await import('/src/audio/transformersStt.ts');
        const state = (window as any).__avatarProbe;
        const worker = new EventTarget() as EventTarget & { postMessage: () => void; terminate: () => void };
        worker.postMessage = () => {};
        worker.terminate = () => {};
        transformers._setTransformersWorkerOverride(() => worker);
        transformers.armTransformersStt();
        state.emitProgress = (progress: number) => {
          state.progress += 1;
          worker.dispatchEvent(new MessageEvent('message', { data: { type: 'progress', event: { status: 'progress', progress } } }));
        };
        state.unsubscribePcm = vad.subscribePcm({ onFrame: () => { state.pcm += 1; } });
        const active = await vad.startVoiceActivity();
        await vad._processFrame(new Float32Array(480).fill(0.2));
        state.emitProgress(0.25);
        return { active, started: state.started, captured: state.captured, pcm: state.pcm, scored: state.scored };
      });
      expect(started.active).toBe(true);
      expect(started.started).toBeGreaterThan(0);
      expect(started.captured).toBe(1);
      expect(started.scored).toBeGreaterThan(0);
      expect(started.pcm).toBeGreaterThan(0);
      expect(vadModuleReads).toBeGreaterThan(0);
      await expect(page.getByTestId('bf301-progress')).toHaveAttribute('title', 'Loading STT model: 25%');
      await expect.poll(() => fleet.active.size).toBeGreaterThan(0);
      const established = fleet.created;
      for (let progress = 1; progress <= 20; progress += 1) {
        await page.evaluate(async value => {
          const vad = await import('/src/audio/voiceActivity.ts');
          await vad._processFrame(new Float32Array(480).fill(0.2));
          (window as any).__avatarProbe.emitProgress(value / 25);
          await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        }, progress);
      }
      await expect(page.getByTestId('bf301-progress')).toHaveAttribute('title', 'Loading STT model: 80%');
      expect(fleet.created).toBe(established);
      for (let transition = 0; transition < 3; transition += 1) {
        await page.evaluate(thread => {
          const store = (window as any).__store;
          store.getState().setChatThread(thread);
          store.setState({ activeProfileAgent: 'ezri', activeProfileThreadId: thread.id });
        }, direct);
        await expect(page.getByTestId('meeting-view')).toHaveCount(0);
        await openGroupChat(page, 'ezri', group);
        await expect(page.getByTestId('meeting-view')).toBeVisible();
      }
      expect(fleet.created).toBeLessThanOrEqual(established + 3);
      expect(fleet.active.size).toBeLessThanOrEqual(2);
      const beforeRecovery = fleet.created;
      const interrupted = [...fleet.active][0];
      expect(interrupted).toBeDefined();
      await interrupted.close({ code: 1012, reason: 'Controlled reconnect' });
      if (fleet.active.delete(interrupted)) fleet.closed += 1;
      await expect.poll(() => fleet.created).toBe(beforeRecovery + 1);
      expect(fleet.active.size).toBeLessThanOrEqual(2);

      await page.getByRole('button', { name: 'Show avatar', exact: true }).click();
      const popout = page.getByRole('dialog', { name: 'Avatar — ezri', exact: true });
      await expect(popout.getByRole('status', { name: 'Avatar asset status' })).toBeVisible();
      const failedReads = assetReads;
      expect(failedReads).toBeGreaterThan(0);
      await popout.getByRole('button', { name: 'Retry avatar' }).click();
      await expect.poll(() => assetReads).toBe(failedReads + 1);
      await expect(popout.getByRole('status', { name: 'Avatar asset status' })).toBeVisible();
      await popout.getByRole('button', { name: 'Close avatar', exact: true }).click();
      await expect(popout).toHaveCount(0);
      await page.evaluate(() => (window as any).__store.getState().closeAgentProfile());
      await expect(page.getByTestId('meeting-view')).toHaveCount(0);
      const completed = await page.evaluate(async () => {
        const state = (window as any).__avatarProbe;
        const vad = await import('/src/audio/voiceActivity.ts');
        const transformers = await import('/src/audio/transformersStt.ts');
        state.unsubscribePcm();
        transformers.terminateTransformersStt();
        vad.stopVoiceActivity();
        return { captured: state.captured, stopped: state.stopped, pcm: state.pcm, progress: state.progress,
          tracksEnded: state.tracks.every((track: MediaStreamTrack) => track.readyState === 'ended') };
      });
      expect(completed.captured).toBe(1);
      expect(completed.stopped).toBeGreaterThan(0);
      expect(completed.pcm).toBeGreaterThanOrEqual(21);
      expect(completed.progress).toBe(21);
      expect(completed.tracksEnded).toBe(true);
      await expect(page.getByTestId('meeting-view')).toHaveCount(0);
      await expect.poll(() => fleet.active.size).toBeLessThanOrEqual(1);
    });
  }
});

test.describe('issue1367 ownership', () => {
  for (const width of [1440, 430]) {
    test(`retired worker job cannot enter a new participant capture at ${width}px`, async ({ page }) => {
      test.setTimeout(60_000);
      await page.setViewportSize({ width, height: 1000 });
      const isolation = await isolateAvatarBrowser(page);
      const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
      let vadLoads = 0;
      const workletRequests: string[] = [];
      page.on('request', request => {
        if (request.url().includes('pcmCaptureWorklet')) workletRequests.push(request.url());
      });
      await page.route('**/src/audio/silero-vad.ts*', route => {
        vadLoads += 1;
        return route.fulfill({ contentType: 'application/javascript', body: `
          export async function _loadOnnxRuntime(){return null;}
          export async function createVadSession(){return {score:async()=>window.__ownershipScore,destroy(){}};}
        ` });
      });
      await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/voice/health') return route.fulfill({ json: {
          engine: 'transformers', primary_stt: 'transformers', healthy: true, backend_available: true,
        } });
        if (path.endsWith('/profile')) return route.fulfill({ json: { isCrew: true, voiceProfile: null } });
        if (path.endsWith('/chat/history')) return route.fulfill({ json: { memories: [] } });
        if (path.endsWith('/chat') && route.request().method() === 'POST') {
          posts.push({ path, body: route.request().postDataJSON() });
          return route.fulfill({ json: { response: 'ack' } });
        }
        return route.abort();
      });
      await page.addInitScript(() => {
        (window as any).__ownershipScore = 0.9;
        (window as any).SpeechRecognition = class { start(): void {} abort(): void {} stop(): void {} };
        const loads: Array<{ url: string; completed: boolean; error?: string }> = [];
        (window as any).__ownershipWorkletLoads = loads;
        const addModule = Worklet.prototype.addModule;
        Worklet.prototype.addModule = async function (moduleURL, options) {
          if (new URL(String(moduleURL), location.href).pathname !== '/src/audio/pcmCaptureWorklet.js') {
            return addModule.call(this, moduleURL, options);
          }
          const load = { url: String(moduleURL), completed: false, error: undefined as string | undefined };
          loads.push(load);
          const processor = `
            class ControlledCapture extends AudioWorkletProcessor { process() { return true; } }
            registerProcessor('pcm-capture', ControlledCapture);
          `;
          const controlledURL = URL.createObjectURL(new Blob([processor], { type: 'application/javascript' }));
          try {
            await addModule.call(this, controlledURL, options);
            load.completed = true;
          } catch (error) {
            load.error = String(error);
            throw error;
          } finally {
            URL.revokeObjectURL(controlledURL);
          }
        };
      });
      try {
        await gotoApp(page);
        await seedAgents(page, [EZRI, YEO]);
        await page.evaluate(async () => {
          const stt = await import('/src/audio/transformersStt.ts');
          const worker = new EventTarget() as any;
          worker.messages = [];
          worker.postMessage = (message: unknown) => worker.messages.push(message);
          worker.terminate = () => {};
          (window as any).__ownershipWorker = worker;
          stt._setTransformersWorkerOverride(() => worker);
          (window as any).__store.setState({ voiceEnabled: false, activeProfileAgent: 'ezri', activeProfileThreadId: null });
        });
        await expect(page.getByRole('button', { name: 'Voice input', exact: true })).toHaveAttribute('title', /transformers/);
        const collapse = page.getByTestId('artifact-drawer-collapse');
        if (await collapse.count()) await collapse.click();
        await page.getByRole('button', { name: 'Voice input', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Stop listening', exact: true })).toBeVisible();
        const premise = await page.evaluate(async () => {
          const vad = await import('/src/audio/voiceActivity.ts');
          const stt = await import('/src/audio/transformersStt.ts');
          const active = await vad.startVoiceActivity();
          for (let frame = 0; frame < 40; frame += 1) {
            await vad._processFrame(new Float32Array(480).fill(0.2), 1000 + frame * 30);
          }
          (window as any).__ownershipScore = 0.1;
          await vad._processFrame(new Float32Array(480), 3000);
          await vad._processFrame(new Float32Array(480), 3800);
          const jobs = (window as any).__ownershipWorker.messages.filter((message: any) => message.type === 'transcribe');
          (window as any).__oldOwnershipJob = jobs[0];
          return { active, armed: stt._isArmed(), jobs: jobs.length, samples: jobs[0]?.samples.length };
        });
        expect(vadLoads).toBeGreaterThan(0);
        const workletLoads = await page.evaluate(() => (window as any).__ownershipWorkletLoads);
        expect(workletRequests).toEqual(['http://localhost:5173/src/audio/pcmCaptureWorklet.js?url']);
        expect(workletLoads).toEqual([{ url: '/src/audio/pcmCaptureWorklet.js', completed: true, error: undefined }]);
        expect(premise).toEqual({ active: true, armed: true, jobs: 1, samples: 20160 });
        await expect(page.getByTestId('mic-indicator')).toHaveAttribute('data-bf294-state', 'processing');
        await page.getByRole('button', { name: 'Transcribing speech', exact: true }).click();
        await page.evaluate(() => (window as any).__store.setState({ activeProfileAgent: 'yeo' }));
        await page.getByRole('button', { name: 'Voice input', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Stop listening', exact: true })).toBeVisible();
        await page.clock.install();
        await page.evaluate(() => {
          const job = (window as any).__oldOwnershipJob;
          (window as any).__ownershipWorker.dispatchEvent(new MessageEvent('message', { data: {
            type: 'transcript', text: 'retired ownership phrase', isPartial: false,
            captureId: job.captureId, jobId: job.jobId, sequence: 1,
          } }));
        });
        await page.clock.runFor(200);
        expect(posts).toEqual([]);
        await expect(page.getByPlaceholder('Message...')).toHaveValue('');
        const messages = await page.evaluate(() => (window as any).__store.getState().agentConversations.get('yeo')?.messages ?? []);
        expect(messages).toEqual([]);
        await expect(page.getByRole('button', { name: 'Stop listening', exact: true })).toBeVisible();
        const fresh = await page.evaluate(async () => {
          const vad = await import('/src/audio/voiceActivity.ts');
          (window as any).__ownershipScore = 0.9;
          for (let frame = 0; frame < 40; frame += 1) {
            await vad._processFrame(new Float32Array(480).fill(0.4), 4000 + frame * 30);
          }
          (window as any).__ownershipScore = 0.1;
          await vad._processFrame(new Float32Array(480), 6000);
          await vad._processFrame(new Float32Array(480), 6800);
          const jobs = (window as any).__ownershipWorker.messages.filter((message: any) => message.type === 'transcribe');
          const job = jobs[1];
          (window as any).__freshOwnershipJob = job;
          return { jobs: jobs.length, samples: job?.samples.length,
            ownSamples: [...job.samples].every(value => value === Math.fround(0.4) || value === 0),
            newCapture: job.captureId !== (window as any).__oldOwnershipJob.captureId,
            newJob: job.jobId !== (window as any).__oldOwnershipJob.jobId };
        });
        expect(fresh).toEqual({ jobs: 2, samples: 20160, ownSamples: true, newCapture: true, newJob: true });
        await page.evaluate(() => {
          const job = (window as any).__freshOwnershipJob;
          (window as any).__ownershipWorker.dispatchEvent(new MessageEvent('message', { data: {
            type: 'transcript', text: 'unfinished phrase', isPartial: true,
            captureId: job.captureId, jobId: job.jobId, sequence: 1,
          } }));
        });
        await page.clock.runFor(200);
        expect(posts).toEqual([]);
        await expect(page.getByPlaceholder('Message...')).toHaveValue('');
        await page.evaluate(() => {
          const job = (window as any).__freshOwnershipJob;
          for (const sequence of [2, 2, 3]) {
            (window as any).__ownershipWorker.dispatchEvent(new MessageEvent('message', { data: {
              type: 'transcript', text: 'current capture phrase', isPartial: false,
              captureId: job.captureId, jobId: job.jobId, sequence,
            } }));
          }
        });
        await page.clock.runFor(200);
        expect(posts).toEqual([{ path: '/api/agent/yeo/chat', body: {
          message: 'current capture phrase', history: [], attachment_ids: [],
        } }]);
        await expect(page.getByText('current capture phrase', { exact: true })).toHaveCount(1);
        await expect(page.getByRole('log', { name: 'Conversation transcript' })).not.toContainText('retired ownership phrase');
        await expect(page.getByRole('button', { name: 'Voice input', exact: true })).toBeVisible();
        await page.evaluate(async () => {
          const stt = await import('/src/audio/transformersStt.ts');
          const scope = Symbol();
          (window as any).__ownershipSiblingText = [];
          (window as any).__ownershipSiblingUnsubscribe = stt.onTransformersTranscript(
            text => (window as any).__ownershipSiblingText.push(text), scope,
          );
          (window as any).__ownershipSiblingCancel = stt.armTransformersStt(scope);
        });
        await page.getByRole('button', { name: 'Voice input', exact: true }).click();
        const pending = await page.evaluate(async () => {
          const vad = await import('/src/audio/voiceActivity.ts');
          (window as any).__ownershipScore = 0.9;
          for (let frame = 0; frame < 20; frame += 1) {
            await vad._processFrame(new Float32Array(480).fill(0.7), 7000 + frame * 30);
          }
          return (window as any).__ownershipWorker.messages.filter((message: any) => message.type === 'transcribe').length;
        });
        expect(pending).toBe(2);
        await page.getByRole('button', { name: 'Stop listening', exact: true }).click();
        await page.evaluate(() => (window as any).__store.getState().closeAgentProfile());
        await expect(page.getByRole('button', { name: 'Voice input', exact: true })).toHaveCount(0);
        await page.evaluate(() => (window as any).__store.setState({ activeProfileAgent: 'ezri', activeProfileThreadId: null }));
        await expect(page.getByRole('button', { name: 'Voice input', exact: true })).toHaveAttribute('title', /transformers/);
        await page.getByRole('button', { name: 'Voice input', exact: true }).click();
        const unmatched = await page.evaluate(async () => {
          const vad = await import('/src/audio/voiceActivity.ts');
          for (let frame = 0; frame < 40; frame += 1) {
            await vad._processFrame(new Float32Array(480).fill(0.3), 8000 + frame * 30);
          }
          (window as any).__ownershipScore = 0.1;
          await vad._processFrame(new Float32Array(480), 10000);
          await vad._processFrame(new Float32Array(480), 10800);
          const jobs = (window as any).__ownershipWorker.messages.filter((message: any) => message.type === 'transcribe');
          (window as any).__ownershipSiblingJob = jobs[2];
          return { jobs: jobs.length, samples: jobs[2]?.samples.length,
            includesPriorFrames: jobs[2]?.samples.includes(Math.fround(0.7)) };
        });
        expect(unmatched).toEqual({ jobs: 3, samples: 29760, includesPriorFrames: true });
        await page.evaluate(() => {
          const job = (window as any).__ownershipSiblingJob;
          (window as any).__ownershipWorker.dispatchEvent(new MessageEvent('message', { data: {
            type: 'transcript', text: 'independent sibling phrase', isPartial: false,
            captureId: job.captureId, jobId: job.jobId, sequence: 1,
          } }));
        });
        await page.clock.runFor(200);
        expect(await page.evaluate(() => (window as any).__ownershipSiblingText)).toEqual(['independent sibling phrase']);
        expect(posts).toHaveLength(1);
        await expect(page.getByPlaceholder('Message...')).toHaveValue('');
        const reopened = await page.evaluate(async () => {
          const vad = await import('/src/audio/voiceActivity.ts');
          (window as any).__ownershipScore = 0.9;
          for (let frame = 0; frame < 40; frame += 1) {
            await vad._processFrame(new Float32Array(480).fill(0.6), 11000 + frame * 30);
          }
          (window as any).__ownershipScore = 0.1;
          await vad._processFrame(new Float32Array(480), 13000);
          await vad._processFrame(new Float32Array(480), 13800);
          const jobs = (window as any).__ownershipWorker.messages.filter((message: any) => message.type === 'transcribe');
          const freshJobs = jobs.slice(3);
          const profileJob = freshJobs.find((job: any) => job.captureId !== (window as any).__ownershipSiblingJob.captureId);
          (window as any).__reopenedOwnershipJob = profileJob;
          (window as any).__ownershipSiblingCancel();
          (window as any).__ownershipSiblingUnsubscribe();
          return { jobs: jobs.length, samples: profileJob?.samples.length,
            ownSamples: [...profileJob.samples].every(value => value === Math.fround(0.6) || value === 0) };
        });
        expect(reopened).toEqual({ jobs: 5, samples: 20160, ownSamples: true });
        await page.evaluate(() => {
          const job = (window as any).__reopenedOwnershipJob;
          (window as any).__ownershipWorker.dispatchEvent(new MessageEvent('message', { data: {
            type: 'transcript', text: 'reopened capture phrase', isPartial: false,
            captureId: job.captureId, jobId: job.jobId, sequence: 1,
          } }));
        });
        await page.clock.runFor(200);
        expect(posts).toHaveLength(2);
        expect(posts[1]).toEqual({ path: '/api/agent/ezri/chat', body: {
          message: 'reopened capture phrase', history: [], attachment_ids: [],
        } });
        await expect(page.getByText('reopened capture phrase', { exact: true })).toHaveCount(1);
        expect(isolation.rejected).toEqual([]);
      } finally {
        await page.evaluate(async () => {
          (window as any).__ownershipSiblingCancel?.();
          (window as any).__ownershipSiblingUnsubscribe?.();
          (window as any).__store?.getState().closeAgentProfile();
          (await import('/src/audio/transformersStt.ts')).terminateTransformersStt();
          (await import('/src/audio/voiceActivity.ts')).stopVoiceActivity();
        }).catch(() => {});
      }
    });
  }
});
