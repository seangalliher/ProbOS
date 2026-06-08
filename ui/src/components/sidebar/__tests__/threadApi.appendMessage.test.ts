// AD-923: unit tests for the appendMessage threadApi wrapper. Plain fetch-mock
// pattern (vi.stubGlobal('fetch', ...)), mirroring threadApi.meeting.test.ts.
// Verifies the POST endpoint, method/headers, the serialized role:'system'
// body, the message-dict return, the Tier-2 null degrade on !res.ok, and a
// no-emoji guard on the serialized request body.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { appendMessage } from '../threadApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sampleMessage = {
  id: 'm1',
  author_id: 'system',
  role: 'system',
  body: 'Meeting ended - 2 participants: Vex, Bones.',
};

describe('AD-923 threadApi appendMessage', () => {
  it('POSTs /api/threads/{id}/messages with the role:system body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleMessage),
    });
    vi.stubGlobal('fetch', fetchMock);

    await appendMessage('t1', {
      author_id: 'system',
      role: 'system',
      body: 'Meeting ended - 2 participants: Vex, Bones.',
      metadata: { meeting_end: true, participant_count: 2 },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/threads/t1/messages',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as { body: string }).body));
    expect(sent).toMatchObject({
      author_id: 'system',
      role: 'system',
      body: 'Meeting ended - 2 participants: Vex, Bones.',
      metadata: { meeting_end: true, participant_count: 2 },
    });
  });

  it('returns the appended message dict on ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(sampleMessage) }),
    );
    const result = await appendMessage('t1', { author_id: 'system', role: 'system', body: 'x' });
    expect(result).toMatchObject({ id: 'm1', role: 'system' });
  });

  it('returns null on !res.ok (Tier-2 degrade)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: () => Promise.resolve({}) }));
    expect(await appendMessage('t1', { author_id: 'system', role: 'system', body: 'x' })).toBeNull();
  });

  it('no-emoji guard: the serialized POST body carries no emoji', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sampleMessage),
    });
    vi.stubGlobal('fetch', fetchMock);
    await appendMessage('t1', {
      author_id: 'system',
      role: 'system',
      body: 'Meeting ended - 2 participants: Vex, Bones.',
    });
    const body = String((fetchMock.mock.calls[0][1] as { body: string }).body);
    expect(body).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
