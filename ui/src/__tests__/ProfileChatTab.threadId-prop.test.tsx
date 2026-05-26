/** AD-792 (Wave 195) vitest — ProfileChatTab.threadId prop precedence
 * regression test (spec Section 8).
 *
 * Precedence rules:
 *   - effectiveThreadId = props.threadId ?? threadIdByAgent.get(agentId)
 *   - Prop wins on request.
 *   - Response wins on mismatch — setThreadForAgent is still called
 *     so the store reflects the latest server-confirmed thread
 *     (preserves the AD-791a invariant).
 *
 * Verified inline at ``components/profile/ProfileChatTab.tsx`` around
 * the chat fetch site (search for ``threadId ?? useStore.getState()
 * .threadIdByAgent.get(agentId)``).
 *
 * Note: the heavy ProfileChatTab component depends on TTS / VAD /
 * camera / attachment subsystems. To avoid pulling those into this
 * focused contract test, we replicate the round-trip shape in a thin
 * helper that mirrors the production logic. This mirrors the
 * established precedent in ``ProfileChatTab.threadId.test.tsx``
 * (AD-791a) which uses the same approach.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../store/useStore';

interface ChatPostBody {
  message: string;
  history: unknown[];
  attachment_ids: string[];
  thread_id?: string;
}

let lastPost: ChatPostBody | null = null;

// Production shape (from ProfileChatTab.tsx) compressed for testability.
async function sendChatTurn(agentId: string, threadIdProp: string | undefined, message: string): Promise<void> {
  const knownThreadId = threadIdProp ?? useStore.getState().threadIdByAgent.get(agentId);
  const body: ChatPostBody = { message, history: [], attachment_ids: [] };
  if (knownThreadId) body.thread_id = knownThreadId;
  const res = await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  lastPost = body;
  const data = await res.json();
  if (typeof data?.thread_id === 'string' && data.thread_id.length > 0) {
    // Response wins on mismatch; setThreadForAgent always called.
    useStore.getState().setThreadForAgent(agentId, data.thread_id);
  }
}

beforeEach(() => {
  lastPost = null;
  useStore.setState({
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
  });
});

function mockServerResponse(threadId: string) {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ response: 'ack', thread_id: threadId }),
    }) as any,
  );
}

describe('ProfileChatTab threadId prop precedence', () => {
  it('uses props.threadId when set, overriding threadIdByAgent', async () => {
    useStore.getState().setThreadForAgent('agent-1', 'store-thread');
    mockServerResponse('explicit-thread');

    await sendChatTurn('agent-1', 'explicit-thread', 'hi');

    expect(lastPost?.thread_id).toBe('explicit-thread');
  });

  it('falls back to threadIdByAgent when props.threadId is undefined', async () => {
    useStore.getState().setThreadForAgent('agent-1', 'store-thread');
    mockServerResponse('store-thread');

    await sendChatTurn('agent-1', undefined, 'hi');

    expect(lastPost?.thread_id).toBe('store-thread');
  });

  it('omits thread_id entirely when both prop and store are unset (default-thread path unchanged)', async () => {
    mockServerResponse('server-default');

    await sendChatTurn('agent-1', undefined, 'hi');

    expect(lastPost?.thread_id).toBeUndefined();
  });

  it('response thread_id wins on mismatch; setThreadForAgent is still called', async () => {
    mockServerResponse('server-assigned-different');

    await sendChatTurn('agent-1', 'prop-thread', 'hi');

    // Request used the prop.
    expect(lastPost?.thread_id).toBe('prop-thread');
    // Store mirrors the server's authoritative response (AD-791a invariant).
    expect(useStore.getState().threadIdByAgent.get('agent-1')).toBe('server-assigned-different');
  });
});
