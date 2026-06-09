// AD-938: unit tests for the listMessages threadApi wrapper. Plain fetch-mock
// pattern (vi.stubGlobal('fetch', ...)), mirroring threadApi.appendMessage.test.ts.
// Verifies the GET endpoint + limit query, the {messages:[...]} unwrap, and the
// Tier-2 [] degrade on !res.ok and on a thrown/parse failure.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { listMessages, type ThreadMessageDTO } from '../threadApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sampleMessages: ThreadMessageDTO[] = [
  { id: 'm1', thread_id: 't1', author_id: 'captain', role: 'captain', body: 'status?', created_at: 1_700_000_000 },
  { id: 'm2', thread_id: 't1', author_id: 'a1', role: 'agent', body: 'nominal', created_at: 1_700_000_005 },
];

describe('AD-938 threadApi listMessages', () => {
  it('GETs /api/threads/{id}/messages with the limit query and returns the messages array', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ thread_id: 't1', messages: sampleMessages }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await listMessages('t1');

    expect(fetchMock).toHaveBeenCalledWith('/api/threads/t1/messages?limit=200');
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ id: 'm1', role: 'captain', body: 'status?' });
    expect(result[1]).toMatchObject({ id: 'm2', role: 'agent', author_id: 'a1' });
  });

  it('honors a custom limit and URL-encodes the thread id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ messages: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await listMessages('t 1/x', 50);

    expect(fetchMock).toHaveBeenCalledWith('/api/threads/t%201%2Fx/messages?limit=50');
  });

  it('returns [] when the response is not ok (Tier-2 honest-degrade)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await listMessages('t1')).toEqual([]);
  });

  it('returns [] when fetch throws (network failure)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));
    expect(await listMessages('t1')).toEqual([]);
  });

  it('returns [] when the payload has no messages array', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ thread_id: 't1' }) }));
    expect(await listMessages('t1')).toEqual([]);
  });
});
