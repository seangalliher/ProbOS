import { expect, test, type Page, type WebSocketRoute } from '@playwright/test';

import fixture from './fixtures/group-reply-identity.json' with { type: 'json' };
import { computeProcessingDelay, computeTypingDelay } from '../src/chat/staggerReplies';
import type { AgentProfileMessage } from '../src/store/types';
import { gotoApp, mkAgent, mkThread, mockChatApi, openGroupChat, seedAgents } from './_helpers';

const GENERATION_A = 'a'.repeat(32);
const GENERATION_B = 'b'.repeat(32);
const room = mkThread(fixture.thread.id, fixture.thread.title, fixture.thread.participants, {
  created_at: fixture.thread.created_at,
  last_active_at: fixture.thread.last_active_at,
  metadata: fixture.thread.metadata,
});
const otherRoom = mkThread('synthetic-empty-other-room', 'Other room', fixture.thread.participants);
const crew = fixture.response.per_agent_replies.map(reply => mkAgent(reply.agent_id, reply.callsign));
const revealMs = fixture.response.per_agent_replies.map((reply, index) =>
  computeProcessingDelay(index) + computeTypingDelay(reply.message.body));

interface BrowserState {
  threadMessages: Map<string, AgentProfileMessage[]>;
  liveGeneration: string | null;
  liveSequence: number;
  activeProfileThreadId: string | null;
  typingAgent: { threadId: string; agentId: string; callsign: string } | null;
  agents: Map<string, { isCrew: boolean }>;
}

function deferred(): { promise: Promise<void>; release: () => void } {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}

async function state(page: Page): Promise<{
  rows: Record<string, AgentProfileMessage[]>;
  generation: string | null;
  sequence: number;
  activeThread: string | null;
  typing: BrowserState['typingAgent'];
  knownCrew: string[];
}> {
  return page.evaluate(() => {
    const current = (window as unknown as {
      __store: { getState: () => BrowserState };
    }).__store.getState();
    return {
      rows: Object.fromEntries(current.threadMessages),
      generation: current.liveGeneration,
      sequence: current.liveSequence,
      activeThread: current.activeProfileThreadId,
      typing: current.typingAgent,
      knownCrew: [...current.agents].filter(([, agent]) => agent.isCrew).map(([id]) => id),
    };
  });
}

function snapshot(generation: string): string {
  return JSON.stringify({
    type: 'state_snapshot', timestamp: 1, stream: { generation, sequence: 0 },
    data: {
      agents: crew.map(agent => ({
        id: agent.id, agent_type: agent.agentType, callsign: agent.callsign,
        display_name: agent.displayName, pool: agent.pool, state: agent.state,
        confidence: agent.confidence, trust: agent.trust, tier: agent.tier, isCrew: true,
      })),
      connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
      notifications: [],
    },
  });
}

async function expectCanonical(page: Page): Promise<void> {
  await expect.poll(async () => (await state(page)).rows[room.id]?.map(message => ({
    id: message.id, thread_id: message.threadId, author_id: message.authorId,
    role: message.role === 'user' ? 'captain' : message.role,
    body: message.text, created_at: message.timestamp, metadata: message.metadata,
  }))).toEqual(fixture.history.messages);
  const transcript = page.getByTestId('chat-transcript');
  await expect(transcript.getByTestId('chat-msg-time')).toHaveCount(3);
  for (const message of fixture.history.messages) {
    const body = transcript.getByText(message.body, { exact: true });
    await expect(body).toHaveCount(1);
    await expect(body).toBeVisible();
  }
  for (const reply of fixture.response.per_agent_replies) {
    await expect(transcript.getByText(reply.callsign, { exact: true })).toHaveCount(1);
  }
  const formattedTimes = await page.evaluate(messages => messages.map(message =>
    new Date(message.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
  fixture.history.messages);
  await expect(transcript.getByTestId('chat-msg-time')).toHaveText(formattedTimes);
  expect((await state(page)).rows[room.id].some(message => message.optimistic)).toBe(false);
}

async function expectProfileFit(page: Page, viewport: { width: number; height: number }): Promise<void> {
  const geometry = await page.getByTitle('Close', { exact: true }).evaluate(button => {
    let panel = button.parentElement;
    while (panel && getComputedStyle(panel).position !== 'fixed') panel = panel.parentElement;
    if (!panel) throw new Error('Profile close control has no fixed outer panel');
    const bounds = button.getBoundingClientRect();
    return {
      panel: panel.getBoundingClientRect().toJSON(), close: bounds.toJSON(),
      reachable: [
        [bounds.left + 1, bounds.top + 1], [bounds.right - 1, bounds.top + 1],
        [bounds.left + 1, bounds.bottom - 1], [bounds.right - 1, bounds.bottom - 1],
        [bounds.left + bounds.width / 2, bounds.top + bounds.height / 2],
      ].every(([horizontal, vertical]) => button.contains(document.elementFromPoint(horizontal, vertical))),
    };
  });
  expect(geometry.reachable).toBe(true);
  for (const bounds of [geometry.panel, geometry.close]) {
    expect(bounds.width).toBeGreaterThan(0);
    expect(bounds.height).toBeGreaterThan(0);
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.top).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(viewport.width);
    expect(bounds.bottom).toBeLessThanOrEqual(viewport.height);
  }
  const transcript = page.getByTestId('chat-transcript');
  const transcriptBox = await transcript.boundingBox();
  const composerBox = await page.getByPlaceholder('Message...', { exact: true }).boundingBox();
  expect(transcriptBox).not.toBeNull();
  expect(composerBox).not.toBeNull();
  expect(transcriptBox!.y + transcriptBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
  expect(composerBox!.x).toBeGreaterThanOrEqual(geometry.panel.left);
  expect(composerBox!.x + composerBox!.width).toBeLessThanOrEqual(geometry.panel.right);
  expect(composerBox!.y + composerBox!.height).toBeLessThanOrEqual(geometry.panel.bottom);
  const rows = await transcript.getByTestId('chat-msg-time').evaluateAll(times => times.map(time => {
    const row = time.parentElement!.parentElement!;
    return {
      bounds: row.getBoundingClientRect().toJSON(),
      fits: [row, ...row.querySelectorAll<HTMLElement>('div, span, p')]
        .every(element => element.scrollWidth <= element.clientWidth + 1),
    };
  }));
  expect(rows).toHaveLength(3);
  for (const [index, row] of rows.entries()) {
    expect(row.fits).toBe(true);
    expect(row.bounds.left).toBeGreaterThanOrEqual(transcriptBox!.x);
    expect(row.bounds.right).toBeLessThanOrEqual(transcriptBox!.x + transcriptBox!.width);
    expect(row.bounds.top).toBeGreaterThanOrEqual(transcriptBox!.y);
    expect(row.bounds.bottom).toBeLessThanOrEqual(transcriptBox!.y + transcriptBox!.height);
    if (index > 0) expect(rows[index - 1].bounds.bottom).toBeLessThanOrEqual(row.bounds.top);
  }
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 900, height: 1000 }]) {
  for (const ordering of ['event-before-http', 'http-before-event', 'room-switch-during-reveal'] as const) {
    test(`canonical group replies: ${ordering} at ${viewport.width}px`, async ({ page }, testInfo) => {
      test.setTimeout(90000);
      await page.setViewportSize(viewport);
      await page.addInitScript(({ width, height }) => {
        localStorage.setItem('hxi_profile_panel_size', JSON.stringify({ w: Math.min(1060, width - 80), h: height - 120 }));
        localStorage.setItem('probos.workspaceFiles.collapsed', width < 1000 ? '1' : '0');
      }, viewport);
      expect(fixture.thread.participants).toHaveLength(2);
      expect(crew.map(agent => agent.id)).toEqual(fixture.thread.participants);
      expect(fixture.events.map(event => event.data.message_id)).toEqual(fixture.history.messages.map(message => message.id));
      expect(fixture.response.per_agent_replies.map(reply => reply.message)).toEqual(fixture.history.messages.slice(1));
      expect(revealMs).toEqual([6000, 3500]);

      const sockets: WebSocketRoute[] = [];
      const postGate = deferred();
      const historyGate = deferred();
      let holdHistory = false;
      let history = { ...fixture.history, messages: [] as typeof fixture.history.messages };
      let historyRequests = 0;
      let historyResponses = 0;
      let otherHistoryRequests = 0;
      let postResponses = 0;
      let sequence = 0;
      const posts: unknown[] = [];
      const mutations: string[] = [];
      page.on('request', request => {
        const path = new URL(request.url()).pathname;
        if (path.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method())) {
          mutations.push(`${request.method()} ${path}`);
        }
      });
      await mockChatApi(page, { threads: [room, otherRoom] });
      await page.route('**/api/threads/*', async route => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (request.method() === 'GET' && path === `/api/threads/${room.id}`) {
          return route.fulfill({ json: fixture.thread });
        }
        if (request.method() === 'GET' && path === `/api/threads/${otherRoom.id}`) {
          return route.fulfill({ json: otherRoom });
        }
        return route.fallback();
      });
      await page.route('**/api/threads/*/messages*', async route => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (request.method() === 'POST' && path === `/api/threads/${room.id}/messages`) {
          posts.push(request.postDataJSON());
          await postGate.promise;
          await route.fulfill({ json: fixture.response });
          postResponses += 1;
          return;
        }
        if (request.method() === 'GET' && path === `/api/threads/${room.id}/messages`) {
          historyRequests += 1;
          const requestedHistory = history;
          if (holdHistory) await historyGate.promise;
          await route.fulfill({ json: requestedHistory, headers: { 'Cache-Control': 'no-store' } });
          historyResponses += 1;
          return;
        }
        if (request.method() === 'GET' && path === `/api/threads/${otherRoom.id}/messages`) {
          otherHistoryRequests += 1;
          return route.fulfill({ json: { thread_id: otherRoom.id, messages: [] } });
        }
        return route.abort();
      });
      await page.routeWebSocket('**/ws/events*', socket => { sockets.push(socket); });
      try {
        await gotoApp(page);
        await expect.poll(() => sockets.length).toBe(1);
        sockets[0].send(snapshot(GENERATION_A));
        await expect.poll(async () => (await state(page)).generation).toBe(GENERATION_A);
        await seedAgents(page, crew);
        await page.evaluate(() => (window as unknown as {
          __store: { setState: (value: unknown) => void };
        }).__store.setState({ voiceEnabled: false, callAudioEnabled: false }));
        await openGroupChat(page, crew[0].id, room);
        await expect.poll(() => historyResponses).toBeGreaterThan(0);
        await expect.poll(async () => (await state(page)).rows[room.id]).toEqual([]);
        expect((await state(page)).knownCrew).toEqual(fixture.thread.participants);
        const transcript = page.getByTestId('chat-transcript');
        await expect(transcript.getByTestId('chat-msg-time')).toHaveCount(0);
        const composer = page.getByPlaceholder('Message...', { exact: true });
        await composer.fill(fixture.request.body);
        await composer.evaluate((element, token) => {
          element.setAttribute('data-correlation-calls', '0');
          element.addEventListener('keydown', event => {
            if ((event as KeyboardEvent).key !== 'Enter') return;
            const descriptor = Object.getOwnPropertyDescriptor(crypto, 'randomUUID');
            const restore = (): void => {
              if (descriptor) Object.defineProperty(crypto, 'randomUUID', descriptor);
              else Reflect.deleteProperty(crypto, 'randomUUID');
            };
            Object.defineProperty(crypto, 'randomUUID', {
              configurable: true,
              value: () => {
                restore();
                element.setAttribute('data-correlation-calls', '1');
                return token;
              },
            });
            window.setTimeout(restore, 0);
          }, { capture: true, once: true });
        }, fixture.request.metadata.client_message_id);
        await composer.press('Enter');
        await expect.poll(() => posts.length).toBe(1);
        await expect(composer).toHaveAttribute('data-correlation-calls', '1');
        expect(posts).toEqual([{ ...fixture.request, attachment_ids: [] }]);
        expect(postResponses).toBe(0);
        await expect.poll(async () => (await state(page)).rows[room.id]?.map(message => ({
          id: message.id, optimistic: message.optimistic, metadata: message.metadata,
        }))).toEqual([{
          id: `optimistic:${fixture.request.metadata.client_message_id}`,
          optimistic: true, metadata: fixture.request.metadata,
        }]);

        const publish = async (eventIndex: number, generation = GENERATION_A, socket = sockets[0]): Promise<string> => {
          const payload = JSON.stringify({ ...fixture.events[eventIndex], stream: { generation, sequence: ++sequence } });
          socket.send(payload);
          await expect.poll(async () => (await state(page)).sequence).toBe(sequence);
          return payload;
        };
        const refreshFromEvent = async (eventIndex: number): Promise<string> => {
          const beforeRequests = historyRequests;
          const beforeResponses = historyResponses;
          const payload = await publish(eventIndex);
          await expect.poll(() => historyRequests).toBeGreaterThan(beforeRequests);
          await expect.poll(() => historyResponses).toBeGreaterThan(beforeResponses);
          await expectCanonical(page);
          return payload;
        };

        if (ordering !== 'event-before-http') {
          postGate.release();
          await expect.poll(() => postResponses).toBe(1);
          await expect.poll(async () => (await state(page)).typing?.agentId).toBe(crew[0].id);
          expect((await state(page)).rows[room.id].map(message => message.id)).toEqual([fixture.history.messages[0].id]);
          await expect(transcript.getByText(fixture.history.messages[1].body, { exact: true })).toHaveCount(0);
        }

        if (ordering === 'room-switch-during-reveal') {
          await openGroupChat(page, crew[0].id, otherRoom);
          await expect.poll(() => otherHistoryRequests).toBeGreaterThan(0);
          await expect.poll(async () => (await state(page)).activeThread).toBe(otherRoom.id);
          await expect(transcript.getByTestId('chat-msg-time')).toHaveCount(0);
          await expect(transcript).not.toContainText('is typing');
          await expect.poll(async () => (await state(page)).rows[room.id]?.map(message => message.id), {
            timeout: revealMs.reduce((total, delay) => total + delay, 0) + 5000,
          }).toEqual(fixture.history.messages.map(message => message.id));
          expect((await state(page)).rows[otherRoom.id]).toEqual([]);
          await expect(transcript.getByTestId('chat-msg-time')).toHaveCount(0);
          for (const message of fixture.history.messages) await expect(transcript).not.toContainText(message.body);
          history = fixture.history;
          const beforeReturn = historyResponses;
          await openGroupChat(page, crew[0].id, room);
          await expect.poll(() => historyResponses).toBeGreaterThan(beforeReturn);
          await expectCanonical(page);
        } else {
          if (ordering === 'http-before-event') {
            await expect.poll(async () => (await state(page)).rows[room.id]?.map(message => message.id), {
              timeout: revealMs[0] + 5000,
            }).toEqual(fixture.history.messages.slice(0, 2).map(message => message.id));
            await expect(transcript.getByText(fixture.history.messages[1].body, { exact: true })).toBeVisible();
            await expect.poll(async () => (await state(page)).typing?.agentId).toBe(crew[1].id);
            await expect(transcript.getByText(fixture.history.messages[2].body, { exact: true })).toHaveCount(0);
          }
          history = fixture.history;
          holdHistory = true;
          const beforeRequests = historyRequests;
          const beforeResponses = historyResponses;
          await publish(0);
          await expect.poll(() => historyRequests).toBeGreaterThan(beforeRequests);
          expect(historyResponses).toBe(beforeResponses);
          if (ordering === 'event-before-http') {
            expect(postResponses).toBe(0);
            expect((await state(page)).rows[room.id][0].optimistic).toBe(true);
          }
          holdHistory = false;
          historyGate.release();
          await expect.poll(() => historyResponses).toBeGreaterThan(beforeResponses);
          await expectCanonical(page);
          if (ordering === 'event-before-http') {
            expect(postResponses).toBe(0);
            postGate.release();
            await expect.poll(() => postResponses).toBe(1);
          }
          await expect.poll(async () => (await state(page)).typing, { timeout: revealMs[1] + 5000 }).toBeNull();
          await expectCanonical(page);
        }

        for (let eventIndex = 0; eventIndex < fixture.events.length; eventIndex += 1) {
          const payload = await refreshFromEvent(eventIndex);
          sockets[0].send(payload);
          await refreshFromEvent(eventIndex);
        }
        const beforeReconnect = historyResponses;
        await sockets[0].close({ code: 1012, reason: 'group identity reconnect test' });
        await expect.poll(() => sockets.length, { timeout: 10000 }).toBe(2);
        sockets[1].send(snapshot(GENERATION_B));
        await expect.poll(async () => (await state(page)).generation).toBe(GENERATION_B);
        await expect.poll(() => historyResponses).toBeGreaterThan(beforeReconnect);
        await expectCanonical(page);
        sequence = 0;
        const beforeReplay = historyResponses;
        await publish(2, GENERATION_B, sockets[1]);
        await expect.poll(() => historyResponses).toBeGreaterThan(beforeReplay);
        await expectCanonical(page);
        expect((await state(page)).rows[otherRoom.id] ?? []).toEqual([]);
        expect(posts).toHaveLength(1);
        expect(postResponses).toBe(1);
        expect(mutations).toEqual([`POST /api/threads/${room.id}/messages`]);
        await expectProfileFit(page, viewport);
        await page.screenshot({ path: testInfo.outputPath(`group-reply-identity-${viewport.width}.png`) });
      } finally {
        postGate.release();
        historyGate.release();
      }
    });
  }
}