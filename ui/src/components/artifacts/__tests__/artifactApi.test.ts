import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchThreadArtifacts } from '../artifactApi';

function artifact(overrides: Record<string, unknown> = {}) {
  return {
    id: 'artifact-1',
    thread_id: 'thread-1',
    name: 'report.md',
    version: 1,
    content_hash: 'a'.repeat(64),
    mime: 'text/markdown',
    size_bytes: 12,
    created_by: 'agent-1',
    created_at: 1,
    supersedes: null,
    _pinned_from_project: false,
    ...overrides,
  };
}

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('AD-1133 bounded artifact metadata repair', () => {
  it('returns an exact authoritative list and uses the 1001 discriminator', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      thread_id: 'thread-1', artifacts: [artifact()],
    }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await fetchThreadArtifacts('thread-1')).toEqual([artifact()]);
    expect(fetchMock).toHaveBeenCalledWith('/api/artifacts/thread/thread-1?limit=1001');
  });

  it('accepts authoritative empty without conflating it with failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      thread_id: 'thread-1', artifacts: [],
    })));
    expect(await fetchThreadArtifacts('thread-1')).toEqual([]);
  });

  it('rejects count overflow, duplicate ids, malformed rows, and room mismatch whole', async () => {
    const tooMany = Array.from({ length: 1001 }, (_, index) => artifact({ id: `artifact-${index}` }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ thread_id: 'thread-1', artifacts: tooMany }))
      .mockResolvedValueOnce(response({ thread_id: 'thread-1', artifacts: [artifact(), artifact()] }))
      .mockResolvedValueOnce(response({ thread_id: 'thread-1', artifacts: [{ id: 'partial' }] }))
      .mockResolvedValueOnce(response({ thread_id: 'other', artifacts: [] }))
      .mockResolvedValueOnce(response({
        thread_id: 'thread-1', artifacts: [artifact({ thread_id: 'other' })],
      }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('count_exceeded');
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('malformed_row');
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('malformed_row');
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('owner_mismatch');
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('owner_mismatch');
  });

  it('rejects an over-budget response before JSON parsing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => ' '.repeat(1024 * 1024 + 1),
    } as Response));
    await expect(fetchThreadArtifacts('thread-1')).rejects.toThrow('response_too_large');
  });
});