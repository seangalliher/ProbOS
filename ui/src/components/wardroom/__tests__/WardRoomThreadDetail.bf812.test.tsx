/** BF-812: a policy refusal must not be re-sent through the Ward Room path.
 *
 *  The DM send posts to `/api/agent/{id}/chat`. It used to `throw` on any
 *  non-OK response, and the `catch` then called `postCaptain()`, which POSTs
 *  the Captain's text to `/api/wardroom/threads/{id}/posts` so "the proactive
 *  cycle can still respond on the next think tick".
 *
 *  For a transport failure that is the right fallback. For an AD-698 policy
 *  refusal it is a bypass: a policy is evaluated PER INTENT, so a hook that
 *  refuses `direct_message` may permit `ward_room_notification`, and the UI
 *  would complete by another route the exact action policy just refused. That
 *  is strictly worse than the silent no-op it replaced.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act, waitFor, fireEvent } from '@testing-library/react';

import { WardRoomThreadDetail } from '../WardRoomThreadDetail';
import { useStore } from '../../../store/useStore';

const THREAD = 'wr-thread-1';
const AGENT = 'agent-1';

/** Every fetch the component made, in order. */
let calls: Array<{ url: string; method: string; body: any }> = [];
/** What `/api/agent/{id}/chat` answers. */
let chatReply: { status: number; body: unknown } = { status: 200, body: { response: 'ok' } };

function installFetch(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    let parsed: any = null;
    try { parsed = init?.body ? JSON.parse(String(init.body)) : null; } catch { parsed = null; }
    calls.push({ url, method, body: parsed });

    if (url.includes('/chat')) {
      return Promise.resolve({
        ok: chatReply.status >= 200 && chatReply.status < 300,
        status: chatReply.status,
        json: () => Promise.resolve(chatReply.body),
      } as Response);
    }
    // The send's `finally` reselects the thread, which refetches the detail.
    // Answering with `{}` would blank the panel and unmount the notice strip.
    if (method === 'GET' && url.includes('/api/wardroom/threads/')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(threadDetailPayload()),
      } as Response);
    }
    return Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve({}),
    } as Response);
  }));
}

function threadDetailPayload(): any {
  return {
    thread: {
      id: THREAD, title: 'Aria', created_at: 0, last_active_at: 0,
      target_agent_id: AGENT,
    },
    posts: [],
  };
}

/** POSTs that put content into the ward-room thread. */
function wardRoomPosts(): Array<{ url: string; method: string; body: any }> {
  return calls.filter((c) => c.method === 'POST' && c.url.includes('/api/wardroom/threads/'));
}

function seed(): void {
  useStore.setState({
    wardRoomActiveThread: THREAD,
    wardRoomView: 'dm-detail',
    wardRoomActiveChannel: AGENT,
    wardRoomDmChannels: [{ agent_id: AGENT, callsign: 'Aria', unread: 0 }] as any,
    wardRoomDmPending: null,
    wardRoomThreadDetail: {
      thread: {
        id: THREAD, title: 'Aria', created_at: 0, last_active_at: 0,
        target_agent_id: AGENT,
      },
      posts: [],
    } as any,
  });
}

async function sendMessage(text = 'do the thing'): Promise<void> {
  const box = screen.getByPlaceholderText('Reply...');
  fireEvent.change(box, { target: { value: text } });
  await act(async () => {
    fireEvent.keyDown(box, { key: 'Enter' });
    await Promise.resolve();
  });
}

beforeEach(() => {
  calls = [];
  chatReply = { status: 200, body: { response: 'ok' } };
  installFetch();
  seed();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

/** The send is finished when the thinking indicator clears. Synchronising on
 *  this rather than on the `/chat` fetch keeps the security assertion from
 *  racing ahead of the fallback if an await is ever added. */
async function sendSettles(): Promise<void> {
  await waitFor(() => {
    expect(useStore.getState().wardRoomDmPending).toBeNull();
  });
}

describe('BF-812 a refused DM is not rerouted through the Ward Room', () => {
  it('posts nothing to the thread when policy refuses the intent', async () => {
    chatReply = { status: 403, body: { error: 'intent_denied', reason: 'rbac' } };
    render(<WardRoomThreadDetail />);

    await sendMessage();
    await sendSettles();

    expect(calls.some((c) => c.url.includes('/chat'))).toBe(true);
    // The bypass: the Captain's text reaching the thread lets the proactive
    // cycle answer it, completing the refused action by a different intent.
    expect(wardRoomPosts()).toHaveLength(0);
  });

  it.each([
    ['FastAPI detail body', { detail: 'Forbidden' }],
    ['an HTML error page', null],
    ['an empty body', {}],
  ])('posts nothing when a 403 arrives as %s', async (_label, body) => {
    // A 4xx is the server refusing this request whatever the body shape.
    // Recognising only the `intent_denied` marker left every other refusal
    // shape falling through to the reroute.
    chatReply = { status: 403, body };
    render(<WardRoomThreadDetail />);

    await sendMessage();
    await sendSettles();

    expect(wardRoomPosts()).toHaveLength(0);
    expect(screen.getByTestId('wardroom-dm-policy-denial').textContent)
      .toContain('403');
  });

  it('tells the Captain it was refused, naming the reason', async () => {
    chatReply = { status: 403, body: { error: 'intent_denied', reason: 'rbac' } };
    render(<WardRoomThreadDetail />);

    await sendMessage();

    const notice = await screen.findByTestId('wardroom-dm-policy-denial');
    expect(notice.textContent).toContain('rbac');
    expect(notice.textContent?.toLowerCase()).toContain('policy');
  });

  it('still falls back to the thread on a genuine transport failure', async () => {
    // The counterpart. Removing the fallback for real outages would strand the
    // Captain's message, which is the behaviour the fallback exists for.
    chatReply = { status: 500, body: { error: 'internal_error' } };
    render(<WardRoomThreadDetail />);

    await sendMessage();
    await sendSettles();

    expect(wardRoomPosts().length).toBeGreaterThan(0);
    expect(screen.queryByTestId('wardroom-dm-policy-denial')).toBeNull();
  });

  it('is unchanged on a successful turn', async () => {
    chatReply = { status: 200, body: { response: 'acknowledged' } };
    render(<WardRoomThreadDetail />);

    await sendMessage();
    await sendSettles();

    // Captain post + agent post, exactly as before.
    expect(wardRoomPosts().length).toBe(2);
    expect(screen.queryByTestId('wardroom-dm-policy-denial')).toBeNull();
  });
});
