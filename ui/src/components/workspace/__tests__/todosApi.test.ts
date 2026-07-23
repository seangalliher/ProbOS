import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchTaskSteps } from '../todosApi';

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

describe('AD-1133 bounded Todo repair', () => {
  it('returns exact steps and uses the 1001 discriminator', async () => {
    const steps = [{ label: 'Review report', status: 'submitted', submitted_by: 'agent-1' }];
    const fetchMock = vi.fn().mockResolvedValue(response({
      steps, gate_completion: true,
    }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await fetchTaskSteps('parent-1')).toEqual(steps);
    expect(fetchMock).toHaveBeenCalledWith('/api/work-items/parent-1/steps?limit=1001');
  });

  it('accepts authoritative empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      steps: [], gate_completion: false,
    })));
    expect(await fetchTaskSteps('parent-1')).toEqual([]);
  });

  it('rejects count overflow, unknown fields, invalid status, and malformed body whole', async () => {
    const tooMany = Array.from({ length: 1001 }, (_, index) => ({
      label: `Step ${index}`, status: 'pending',
    }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ steps: tooMany, gate_completion: false }))
      .mockResolvedValueOnce(response({ steps: [{ label: 'x', status: 'pending', raw: true }], gate_completion: false }))
      .mockResolvedValueOnce(response({ steps: [{ label: 'x', status: 'unknown' }], gate_completion: false }))
      .mockResolvedValueOnce(response({ steps: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchTaskSteps('parent-1')).rejects.toThrow('count_exceeded');
    await expect(fetchTaskSteps('parent-1')).rejects.toThrow('malformed_row');
    await expect(fetchTaskSteps('parent-1')).rejects.toThrow('malformed_row');
    await expect(fetchTaskSteps('parent-1')).rejects.toThrow('malformed_response');
  });

  it('rejects an over-budget response before JSON parsing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => ' '.repeat(1024 * 1024 + 1),
    } as Response));
    await expect(fetchTaskSteps('parent-1')).rejects.toThrow('response_too_large');
  });
});