// BF-671: one composer-owned output-audio control across ordinary 1:1,
// active 1:1, ended 1:1, and active group scopes. Real components + DEV store;
// backend-free and no real audio.
import { test, expect, type Page } from '@playwright/test';
import {
  EZRI,
  YEO,
  gotoApp,
  mkThread,
  mockChatApi,
  openGroupChat,
  seedAgents,
  type ThreadFixture,
} from './_helpers';

const ONE_TO_ONE = mkThread(
  'dm-ezri',
  'Ezri',
  ['captain', 'ezri'],
  { metadata: { is_default: true } },
);
const GROUP = mkThread('group-ezri-yeo', 'Ezri, Yeo', ['captain', 'ezri', 'yeo']);

async function mockAudioControlApi(
  page: Page,
  oneToOne: ThreadFixture,
  group: ThreadFixture,
): Promise<void> {
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;
    const fulfill = (body: unknown): Promise<void> => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (method === 'POST' && path === '/api/agent/ezri/chat') {
      return fulfill({ response: '', system: true, thread_id: oneToOne.id });
    }
    if (method === 'POST' && path === '/api/agent/ezri/thread') {
      return fulfill(oneToOne);
    }
    const messages = path.match(/^\/api\/threads\/([^/]+)\/messages$/);
    if (messages && method === 'GET') {
      return fulfill({ thread_id: decodeURIComponent(messages[1]), messages: [] });
    }
    if (messages && method === 'POST') {
      return fulfill({
        id: 'message',
        thread_id: decodeURIComponent(messages[1]),
        per_agent_replies: [],
      });
    }
    const thread = path.match(/^\/api\/threads\/([^/]+)$/);
    if (thread && method === 'PATCH') {
      const base = decodeURIComponent(thread[1]) === oneToOne.id ? oneToOne : group;
      const body = (request.postDataJSON() ?? {}) as { meeting_active?: boolean };
      return fulfill({
        ...base,
        metadata: { ...(base.metadata ?? {}), meeting_active: body.meeting_active === true },
      });
    }
    return route.fallback();
  });
}

async function seedOrdinaryOneToOne(page: Page): Promise<void> {
  await page.evaluate((thread) => {
    const store = (window as unknown as {
      __store: {
        setState: (state: unknown) => void;
        getState: () => {
          setThreadForAgent: (agentId: string, threadId: string) => void;
          openAgentProfile: (agentId: string) => void;
        };
      };
    }).__store;
    localStorage.setItem('hxi_chat_tts_ezri', '0');
    localStorage.setItem('probos.artifactDrawer.collapsed', '1');
    store.setState({
      chatThreads: new Map([[thread.id, thread]]),
      threadMessages: new Map([[thread.id, []]]),
      callAudioEnabled: true,
      meetingChatVisible: true,
      artifactDrawerCollapsed: true,
    });
    const state = store.getState();
    state.setThreadForAgent('ezri', thread.id);
    state.openAgentProfile('ezri');
  }, ONE_TO_ONE);
}

async function callAudioState(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const store = (window as unknown as { __store: { getState: () => { callAudioEnabled: boolean } } }).__store;
    return store.getState().callAudioEnabled;
  });
}

test.describe('BF-671 unified output-audio control', () => {
  test('one composer control switches scopes and restores the per-agent preference', async ({ page }) => {
    await mockChatApi(page, { threads: [ONE_TO_ONE, GROUP], messagesByThread: {} });
    await mockAudioControlApi(page, ONE_TO_ONE, GROUP);
    await gotoApp(page);
    await seedAgents(page, [EZRI, YEO]);
    await seedOrdinaryOneToOne(page);

    const output = page.getByTestId('output-audio-toggle');
    await expect(output).toHaveCount(1);
    await expect(output).toHaveAttribute('aria-pressed', 'false');
    await expect(output).toHaveAttribute('aria-label', 'Unmute call audio');
    await expect(output).toHaveAttribute('title', 'Unmute call audio');
    await expect(page.getByTestId('call-audio-toggle')).toHaveCount(0);

    await output.click();
    await expect(output).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => localStorage.getItem('hxi_chat_tts_ezri'))).toBe('1');
    expect(await callAudioState(page)).toBe(true);

    await page.evaluate(() => {
      const store = (window as unknown as {
        __store: { getState: () => { setCallAudioEnabled: (value: boolean) => void } };
      }).__store;
      store.getState().setCallAudioEnabled(false);
    });
    await expect(output).toHaveAttribute('aria-pressed', 'true');

    await page.getByTestId('call-start').click();
    await page.getByTestId('call-audio').click();
    await expect(page.getByTestId('call-end')).toBeVisible();
    await expect(output).toHaveCount(1);
    await expect(output).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('call-audio-toggle')).toHaveCount(0);

    await output.click();
    expect(await callAudioState(page)).toBe(true);
    expect(await page.evaluate(() => localStorage.getItem('hxi_chat_tts_ezri'))).toBe('1');

    await page.getByTestId('call-end').click();
    await expect(page.getByTestId('call-start')).toBeVisible();
    await expect(output).toHaveCount(1);
    await expect(output).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => localStorage.getItem('hxi_chat_tts_ezri'))).toBe('1');

    await openGroupChat(page, 'ezri', GROUP);
    await expect(page.getByTestId('group-chat-header')).toBeVisible();
    await page.getByTestId('meeting-toggle').click();
    await expect(page.getByTestId('meeting-view')).toBeVisible();
    await expect(output).toHaveCount(1);
    await expect(page.getByTestId('call-audio-toggle')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Mute call audio' })).toHaveCount(1);
  });
});
