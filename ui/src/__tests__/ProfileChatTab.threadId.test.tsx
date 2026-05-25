/**
 * AD-791a vitest #11 — ProfileChatTab thread_id round-trip.
 *
 * The 1:1 /api/agent/{id}/chat endpoint now returns a `thread_id` field
 * (Section 5.5 of the spec). The UI must:
 *   - Cache the returned `thread_id` keyed by `agentId` in
 *     `useStore.threadIdByAgent`.
 *   - Send the same `thread_id` back on the NEXT request so the server
 *     routes the turn to the same thread.
 *
 * This test stubs the network layer and inspects the request body of
 * the second POST to assert the round-trip wire is correct. It does
 * NOT mount the heavy ProfileChatTab component (which has many other
 * dependencies); instead it invokes the round-trip helper directly so
 * the assertion is focused on the AD-791a contract.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { useStore } from '../store/useStore';

// Lightweight emulation of the ProfileChatTab sendText round-trip. The
// real handler in ``components/profile/ProfileChatTab.tsx`` does the
// same dance: read ``threadIdByAgent.get(agentId)``, attach it to the
// JSON body, parse ``data.thread_id`` from the response, and write it
// back into the store via ``setThreadForAgent``. Replicating that
// shape here gives us a focused assertion without dragging in the
// component's full dependency surface (TTS, attachments, voice, ...).
async function sendChatTurn(agentId: string, message: string): Promise<{ ok: boolean }> {
  const knownThreadId = useStore.getState().threadIdByAgent.get(agentId);
  const body: Record<string, unknown> = { message, history: [], attachment_ids: [] };
  if (knownThreadId) body.thread_id = knownThreadId;
  const res = await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (typeof data?.thread_id === 'string' && data.thread_id.length > 0) {
    useStore.getState().setThreadForAgent(agentId, data.thread_id);
  }
  return { ok: true };
}

beforeEach(() => {
  useStore.setState({
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AD-791a ProfileChatTab thread_id round-trip', () => {
  it('caches thread_id from the first response and reuses it on the second request', async () => {
    const captured: Array<{ url: string; body: any }> = [];
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any, init: any) => {
      const parsed = init?.body ? JSON.parse(init.body as string) : {};
      captured.push({ url: String(url), body: parsed });
      // Both turns return the same thread_id (server's implicit default).
      return new Response(
        JSON.stringify({ response: 'ack', thread_id: 'thread-abc-123' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });

    // First turn — no thread_id sent; server creates default and returns it.
    await sendChatTurn('agent-ezri', 'Status?');
    // Second turn — store should have cached thread-abc-123 and send it back.
    await sendChatTurn('agent-ezri', 'Continue.');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(captured[0].body.thread_id).toBeUndefined();
    expect(captured[1].body.thread_id).toBe('thread-abc-123');

    // Store reflects the cached mapping.
    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-abc-123');
  });

  it('does NOT cache a thread_id when the server omits it (older backend compat)', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(JSON.stringify({ response: 'ack' }), { status: 200 }),
    );
    await sendChatTurn('agent-worf', 'hi');
    expect(useStore.getState().threadIdByAgent.get('agent-worf')).toBeUndefined();
  });

  it('keeps per-agent threads isolated (different agents → different cached IDs)', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      const id = String(url).includes('agent-ezri') ? 'thread-ezri' : 'thread-worf';
      return new Response(JSON.stringify({ response: 'ok', thread_id: id }), { status: 200 });
    });

    await sendChatTurn('agent-ezri', 'a');
    await sendChatTurn('agent-worf', 'b');

    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-ezri');
    expect(useStore.getState().threadIdByAgent.get('agent-worf')).toBe('thread-worf');
  });
});
