// AD-920: unit tests for the setMeetingActive threadApi wrapper. Plain
// fetch-mock pattern (vi.stubGlobal('fetch', ...)), mirroring
// threadApi.participants.test.ts. Verifies the PATCH endpoint, method, body
// {meeting_active}, the updated-thread return, the Tier-2 null degrade, and a
// no-emoji guard on the serialized request body.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { setMeetingActive } from '../threadApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sampleThread = {
  id: 't1',
  title: 'Quarterly sync',
  participants: ['captain', 'a1'],
  created_at: 0,
  last_active_at: 0,
  metadata: { meeting_active: true },
};

describe('AD-920 threadApi setMeetingActive', () => {
  it('PATCHes /api/threads/{id} with {meeting_active}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleThread),
    });
    vi.stubGlobal('fetch', fetchMock);

    await setMeetingActive('t1', true);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/threads/t1',
      expect.objectContaining({
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_active: true }),
      }),
    );
  });

  it('returns the updated thread on ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(sampleThread) }),
    );
    const result = await setMeetingActive('t1', true);
    expect(result?.id).toBe('t1');
  });

  it('returns null on !res.ok', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await setMeetingActive('t1', false)).toBeNull();
  });

  it('no-emoji guard: the serialized PATCH body carries no emoji', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleThread),
    });
    vi.stubGlobal('fetch', fetchMock);
    await setMeetingActive('t1', true);
    const body = String((fetchMock.mock.calls[0][1] as { body: string }).body);
    expect(body).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
