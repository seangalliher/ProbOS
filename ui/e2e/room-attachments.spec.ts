import { createHash } from 'node:crypto';
import { expect, test, type WebSocketRoute } from '@playwright/test';

import fixtures from './fixtures/room-attachments.json' with { type: 'json' };
import { computeProcessingDelay, computeTypingDelay } from '../src/chat/staggerReplies';
import { gotoApp, mkAgent, mkThread, mockChatApi, openGroupChat, seedAgents } from './_helpers';

for (const scenario of ['message', 'task-upload'] as const) {
  for (const width of [1440, 390]) {
    test(`room attachment ${scenario} remains readable at ${width}px`, async ({ page }, testInfo) => {
      test.setTimeout(90000);
      const fixture = fixtures[scenario];
      const crew = fixture.response.per_agent_replies.map(reply => mkAgent(reply.agent_id, reply.callsign));
      const room = mkThread(fixture.thread.id, fixture.thread.title, fixture.thread.participants, {
        created_at: fixture.thread.created_at, last_active_at: fixture.thread.last_active_at,
        metadata: fixture.thread.metadata, task_id: fixture.thread.task_id ?? undefined,
      });
      const other = mkThread('other-input-room', 'Other input room', crew.map(agent => agent.id));
      expect(createHash('sha256').update(fixture.file.text).digest('hex')).toBe(fixture.file.sha256);
      expect(fixture.model_reads).toHaveLength(2);
      for (const read of fixture.model_reads) {
        expect(read.rows).toHaveLength(12);
        expect(read.result).toEqual({ unanswered_reviews: ['T04', 'T07', 'T08'], reworks: ['T03', 'T08', 'T12'] });
      }
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript(({ viewportWidth }) => {
        localStorage.setItem('hxi_profile_panel_size', JSON.stringify({ w: Math.min(1060, viewportWidth - 24), h: 880 }));
        localStorage.setItem('probos.workspaceFiles.collapsed', '1');
      }, { viewportWidth: width });
      let uploaded = 0;
      let posts = 0;
      let persisted = false;
      let unavailable = false;
      let rejectUpload = false;
      let inputGets = 0;
      let releaseUpload!: () => void;
      const uploadGate = new Promise<void>(resolve => { releaseUpload = resolve; });
      const sockets: WebSocketRoute[] = [];
      await mockChatApi(page, { threads: [room, other] });
      await page.route('**/api/threads/*/inputs', async route => {
        const threadId = new URL(route.request().url()).pathname.split('/')[3];
        inputGets += 1;
        if (threadId === room.id && unavailable) return route.fulfill({ status: 503, json: { detail: 'Room inputs unavailable' } });
        return route.fulfill({ json: threadId === room.id && persisted
          ? fixture.inputs : { thread_id: threadId, task_id: threadId === room.id ? fixture.thread.task_id : null, inputs: [] } });
      });
      await page.route('**/api/chat/attachments/multipart', async route => {
        uploaded += 1;
        const request = route.request();
        const bytes = request.postDataBuffer();
        expect(request.method()).toBe('POST');
        expect(bytes).not.toBeNull();
        const form = await new Response(bytes, { headers: { 'Content-Type': request.headers()['content-type'] } }).formData();
        const file = form.get('file');
        expect(file).not.toBeNull();
        expect(typeof file).not.toBe('string');
        const picked = file as File;
        expect(picked.name).toBe(fixture.file.filename);
        expect(createHash('sha256').update(Buffer.from(await picked.arrayBuffer())).digest('hex')).toBe(fixture.file.sha256);
        if (rejectUpload) return route.fulfill({ status: 503, json: { error: 'attachment_store_full' } });
        await uploadGate;
        return route.fulfill({ json: fixture.upload });
      });
      await page.route('**/api/threads/*/messages*', async route => {
        const request = route.request();
        const threadId = new URL(request.url()).pathname.split('/')[3];
        if (request.method() === 'POST') {
          expect(threadId).toBe(room.id);
          expect(request.postDataJSON()).toEqual(fixture.request);
          posts += 1;
          persisted = true;
          return route.fulfill({ json: fixture.response });
        }
        return route.fulfill({ json: threadId === room.id
          ? persisted ? fixture.history : fixture.initial_history
          : { thread_id: threadId, messages: [] } });
      });
      await page.route('**/api/threads/*', route => {
        const threadId = new URL(route.request().url()).pathname.split('/')[3];
        return threadId === room.id ? route.fulfill({ json: fixture.thread }) : route.fallback();
      });
      await page.routeWebSocket('**/ws/events*', socket => { sockets.push(socket); });
      const snapshot = (generation: string): string => JSON.stringify({
        type: 'state_snapshot', timestamp: 1000, stream: { generation, sequence: 0 },
        data: {
          agents: crew.map(agent => ({ id: agent.id, agent_type: 'crew', callsign: agent.callsign, display_name: agent.displayName, pool: 'bridge',
            state: 'active', confidence: 1, trust: 0.5, tier: 'domain', isCrew: true })),
          connections: [], pools: [], notifications: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
        },
      });
      try {
        await gotoApp(page);
        await expect.poll(() => sockets.length).toBe(1);
        sockets[0].send(snapshot('a'.repeat(32)));
        await expect.poll(() => page.evaluate(() => (window as unknown as {
          __store: { getState: () => { liveGeneration: string | null } };
        }).__store.getState().liveGeneration)).toBe('a'.repeat(32));
        await seedAgents(page, crew);
        await page.evaluate(() => (window as unknown as { __store: { setState: (value: unknown) => void } }).__store.setState({ voiceEnabled: false, callAudioEnabled: false }));
        await openGroupChat(page, crew[0].id, room);
        const composer = page.getByPlaceholder('Message...', { exact: true });
        await expect(composer).toBeVisible();
        await expect(page.getByTestId('chat-transcript').getByText(fixture.initial_history.messages[0].body, { exact: true })).toBeVisible();
        const picker = page.waitForEvent('filechooser');
        await page.getByRole('button', { name: 'attach file', exact: true }).click();
        await (await picker).setFiles({ name: fixture.file.filename, mimeType: fixture.file.mime, buffer: Buffer.from(fixture.file.text) });
        await expect.poll(() => uploaded).toBe(1);
        await expect(page.getByRole('status').filter({ hasText: 'Uploading attachments...' })).toBeVisible();
        expect(posts).toBe(0);
        releaseUpload();
        await expect(page.getByRole('button', { name: 'remove attachment' })).toBeVisible();
        await expect(page.getByText('Uploading attachments...', { exact: true })).toHaveCount(0);
        await composer.fill(fixture.request.body);
        await composer.evaluate((element, token) => {
          element.addEventListener('keydown', event => {
            if ((event as KeyboardEvent).key !== 'Enter') return;
            const previous = crypto.randomUUID;
            Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => {
              Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: previous });
              return token;
            } });
          }, { once: true, capture: true });
        }, fixture.request.metadata.client_message_id);
        await composer.press('Enter');
        await expect.poll(() => posts).toBe(1);
        for (const [index, event] of fixture.events.entries()) {
          sockets[0].send(JSON.stringify({ ...event, stream: { generation: 'a'.repeat(32), sequence: index + 1 } }));
          await expect.poll(() => page.evaluate(() => (window as unknown as {
            __store: { getState: () => { liveSequence: number } };
          }).__store.getState().liveSequence)).toBe(index + 1);
        }
        const transcript = page.getByTestId('chat-transcript');
        const revealBudget = fixture.response.per_agent_replies.reduce((total, reply, index) => total + computeProcessingDelay(index) + computeTypingDelay(reply.text), 5000);
        await expect.poll(() => page.evaluate(threadId => (window as unknown as {
          __store: { getState: () => { threadMessages: Map<string, { id: string }[]> } };
        }).__store.getState().threadMessages.get(threadId)?.map(message => message.id), room.id), { timeout: revealBudget }).toEqual(fixture.history.messages.map(message => message.id));
        await expect(transcript.getByText(fixture.response.per_agent_replies[0].message.body, { exact: true })).toHaveCount(2);
        await page.getByRole('button', { name: 'open files', exact: true }).click();
        const row = page.getByTestId(`input-row-${fixture.file.sha256}`);
        await expect(row).toContainText('records.csv');
        await expect(row).toContainText('Ready');
        await expect(row).toHaveAttribute('href', fixture.upload.url);
        const composerBounds = await composer.boundingBox();
        expect(composerBounds).not.toBeNull();
        expect(composerBounds!.width).toBeGreaterThan(120);
        if (width < 660) await expect(page.getByTestId('workspace-files-rail')).toHaveAttribute('data-compact', 'true');
        const bounds = await row.boundingBox();
        expect(bounds).not.toBeNull();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
        await page.screenshot({ path: testInfo.outputPath(`room-input-${scenario}-${width}.png`) });
        unavailable = true;
        await page.getByTestId('workspace-files-refresh').click();
        await expect(page.getByRole('alert').filter({ hasText: 'Inputs unavailable.' })).toBeVisible();
        await expect(row).toContainText('records.csv');
        await expect(row).not.toHaveAttribute('href');
        unavailable = false;
        const previousGets = inputGets;
        sockets[0].close({ code: 1000 });
        await expect.poll(() => sockets.length).toBeGreaterThan(1);
        sockets[sockets.length - 1].send(snapshot('b'.repeat(32)));
        await expect.poll(() => inputGets).toBeGreaterThan(previousGets);
        await expect(row).toContainText('Ready');
        await openGroupChat(page, crew[0].id, other);
        await expect(page.getByTestId('inputs-list-empty')).toBeVisible();
        await expect(row).toHaveCount(0);
        await openGroupChat(page, crew[0].id, room);
        await expect(row).toContainText('Ready');
        expect(uploaded).toBe(1);
        await page.getByTestId('workspace-files-collapse').click();
        await expect(composer).toBeVisible();
        expect((await composer.boundingBox())!.width).toBeGreaterThan(120);
        await page.screenshot({ path: testInfo.outputPath(`room-conversation-${scenario}-${width}.png`) });
        rejectUpload = true;
        const failedPicker = page.waitForEvent('filechooser');
        await page.getByRole('button', { name: 'attach file', exact: true }).click();
        await (await failedPicker).setFiles({ name: fixture.file.filename, mimeType: fixture.file.mime, buffer: Buffer.from(fixture.file.text) });
        await expect(page.getByText('Upload failed: attachment_store_full', { exact: true })).toBeVisible();
        expect(uploaded).toBe(2);
        expect(posts).toBe(1);
      } finally {
        releaseUpload();
      }
    });
  }
}