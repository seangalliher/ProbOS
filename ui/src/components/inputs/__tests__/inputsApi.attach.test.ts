/**
 * AD-926a: unit tests for the `attachTaskInputs` inputsApi wrapper.
 *
 * Plain fetch-mock pattern (`vi.stubGlobal('fetch', ...)`), mirroring
 * `threadApi.appendMessage.test.ts`. Verifies the single multipart POST to
 * `/api/work-items/{id}/inputs` (all files under the `files` field), the
 * `body.inputs` return on ok, the honest-degrade throw on non-ok, and a
 * no-emoji guard on the source (HXI Design Principle #3).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { attachTaskInputs, type TaskInput } from '../inputsApi';
import InputsApiSource from '../inputsApi?raw';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const RETURNED: TaskInput[] = [
  { content_hash: 'h1', mime: 'text/plain', filename: 'a.txt', size: 5, source: 'task' },
  { content_hash: 'h2', mime: 'text/plain', filename: 'b.txt', size: 7, source: 'task' },
];

describe('AD-926a attachTaskInputs', () => {
  it('POSTs one multipart request with all files to /api/work-items/{id}/inputs', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ work_item_id: 'wi-1', inputs: RETURNED, skipped: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const f1 = new File(['alpha'], 'a.txt', { type: 'text/plain' });
    const f2 = new File(['bravo!!'], 'b.txt', { type: 'text/plain' });
    await attachTaskInputs('wi-1', [f1, f2]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, { method: string; body: FormData }];
    expect(url).toBe('/api/work-items/wi-1/inputs');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    const sent = init.body.getAll('files') as File[];
    expect(sent.map((f) => f.name)).toEqual(['a.txt', 'b.txt']);
  });

  it('encodes the work item id in the URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ inputs: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);
    await attachTaskInputs('wi/with space', [new File(['x'], 'x.txt', { type: 'text/plain' })]);
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe('/api/work-items/wi%2Fwith%20space/inputs');
  });

  it('returns body.inputs on ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ inputs: RETURNED, skipped: [] }),
      }),
    );
    const result = await attachTaskInputs('wi-1', [new File(['x'], 'x.txt', { type: 'text/plain' })]);
    expect(result).toEqual(RETURNED);
  });

  it('throws on non-ok (honest-degrade)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(
      attachTaskInputs('wi-1', [new File(['x'], 'x.txt', { type: 'text/plain' })]),
    ).rejects.toThrow(/503/);
  });

  it('no-emoji guard: the source carries no emoji', () => {
    expect(InputsApiSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
