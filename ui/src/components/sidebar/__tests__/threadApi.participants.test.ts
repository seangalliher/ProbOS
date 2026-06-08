// AD-917: unit tests for the threadApi participant wrappers (add/remove).
// Plain fetch-mock pattern (vi.stubGlobal('fetch', ...)), mirroring
// McpAppBridge.test.ts. Verifies the endpoint, method, body, URL-encoding,
// and the Tier-2 honest-degrade-to-null behavior.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { addParticipant, removeParticipant } from '../threadApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sampleThread = {
  id: 't1',
  title: 'Bridge crew',
  participants: ['captain', 'a1'],
  created_at: 0,
  last_active_at: 0,
};

describe('AD-917 threadApi participant wrappers', () => {
  it('addParticipant POSTs {agent_id} to /participants and returns the parsed thread', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleThread),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await addParticipant('t1', 'a1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/threads/t1/participants',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: 'a1' }),
      }),
    );
    expect(result).toEqual(sampleThread);
  });

  it('addParticipant returns null on !res.ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await addParticipant('t1', 'a1')).toBeNull();
  });

  it('addParticipant returns null on fetch throw (honest-degrade)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')));
    expect(await addParticipant('t1', 'a1')).toBeNull();
  });

  it('removeParticipant DELETEs the URL-encoded participant path and returns the parsed thread', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleThread),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await removeParticipant('t 1', 'a/1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/threads/t%201/participants/a%2F1',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(result).toEqual(sampleThread);
  });

  it('removeParticipant returns null on !res.ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await removeParticipant('t1', 'a1')).toBeNull();
  });
});
