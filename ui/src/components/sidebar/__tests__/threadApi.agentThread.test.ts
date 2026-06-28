// AD-1058: unit tests for the getOrCreateAgentThread threadApi wrapper. Plain
// fetch-mock pattern (mirrors threadApi.meeting.test.ts). Verifies the POST
// endpoint + method, the returned default thread, id encoding, and the
// honest-degrade null paths (404 unknown agent / 400 non-crew / network error).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { getOrCreateAgentThread } from '../threadApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const defaultThread = {
  id: 'thr-ezri',
  title: 'Ezri',
  participants: ['agent-ezri'],
  created_at: 0,
  last_active_at: 0,
  metadata: { is_default: true },
};

describe('AD-1058 threadApi getOrCreateAgentThread', () => {
  it('POSTs /api/agent/{id}/thread', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(defaultThread) });
    vi.stubGlobal('fetch', fetchMock);
    await getOrCreateAgentThread('agent-ezri');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agent/agent-ezri/thread',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('returns the default 1:1 thread on ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(defaultThread) }));
    const t = await getOrCreateAgentThread('agent-ezri');
    expect(t?.id).toBe('thr-ezri');
    expect(t?.participants).toEqual(['agent-ezri']);
  });

  it('returns null on !res.ok (404 unknown / 400 non-crew)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await getOrCreateAgentThread('ghost')).toBeNull();
  });

  it('returns null on a network error (honest-degrade)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect(await getOrCreateAgentThread('agent-ezri')).toBeNull();
  });

  it('encodes the agent id in the path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(defaultThread) });
    vi.stubGlobal('fetch', fetchMock);
    await getOrCreateAgentThread('a/b');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/a%2Fb/thread');
  });
});
