import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  CONSULTED_CACHE_MAX_BYTES,
  CONSULTED_CACHE_MAX_ENTRIES,
  CONSULTED_TRACE_REF_PATTERN,
  type ConsultedReceipt,
  resetConsultedTraceCacheForTests,
  useConsultedTrace,
} from './useConsultedTrace';

const REF_A = 'a'.repeat(64);
const REF_B = 'b'.repeat(64);

function receipt(ref: string, requests: string[] = ['GET /repo/README.md']): ConsultedReceipt {
  return {
    ref, requests, requests_total: requests.length, requests_omitted: 0,
    invalid_entries: 0, redacted: false, truncated: false, notice: 'Consulted evidence.',
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function rawJsonResponse(status: number, body: string): Response {
  return new Response(body, { status, headers: { 'content-type': 'application/json' } });
}

beforeEach(() => {
  resetConsultedTraceCacheForTests();
  vi.stubGlobal('fetch', vi.fn());
  window.history.replaceState({}, '', '/');
});

afterEach(() => {
  resetConsultedTraceCacheForTests();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('useConsultedTrace', () => {
  it('does not acquire, fetch, or leave the idle state when ref is null', () => {
    const { result } = renderHook(() => useConsultedTrace(null, true, 'owner-a'));
    expect(result.current.state.status).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not fetch while collapsed even when a ref is bound', () => {
    const { result } = renderHook(() => useConsultedTrace(REF_A, false, `msg\u0000thread\u0000author\u0000${REF_A}`));
    expect(result.current.state.status).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('rejects a malformed ref client-side without any network round trip', () => {
    const { result } = renderHook(() => useConsultedTrace('not-a-valid-ref', true, 'owner-a'));
    expect(result.current.state.status).toBe('idle');
    expect(fetch).not.toHaveBeenCalled();
    expect(CONSULTED_TRACE_REF_PATTERN.test('not-a-valid-ref')).toBe(false);
  });

  it('fetches once expanded with a bound ref and resolves to ready', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    expect(result.current.state.data?.requests).toEqual(['GET /repo/README.md']);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(`/api/traces/${REF_A}/consulted`);
  });

  it('freezes successful receipts and their request arrays', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('ready'));

    expect(Object.isFrozen(result.current.state.data)).toBe(true);
    expect(Object.isFrozen(result.current.state.data?.requests)).toBe(true);
  });

  it('rejects a successful response whose actual UTF-8 wire body exceeds 16 KiB', async () => {
    const oversizedWhitespace = `${JSON.stringify(receipt(REF_A)).slice(0, -1)},${' '.repeat(16_384)}}`;
    expect(new TextEncoder().encode(oversizedWhitespace).byteLength).toBeGreaterThan(16_384);
    vi.mocked(fetch).mockResolvedValue(rawJsonResponse(200, oversizedWhitespace));

    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('unavailable'));
    expect(result.current.state.data).toBeNull();
  });

  it('rejects a Unicode response whose wire bytes exceed 16 KiB despite fewer code units', async () => {
    const requests = ['\u754c'.repeat(5_400)];
    const body = JSON.stringify(receipt(REF_A, requests));
    expect(body.length).toBeLessThan(16_384);
    expect(new TextEncoder().encode(body).byteLength).toBeGreaterThan(16_384);
    vi.mocked(fetch).mockResolvedValue(rawJsonResponse(200, body));

    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('unavailable'));
  });

  it.each([
    ['more than 40 requests', { ...receipt(REF_A), requests: Array.from({ length: 41 }, (_, i) => `GET /${i}`), requests_total: 41 }],
    ['an extra response property', { ...receipt(REF_A), unexpected: true }],
    ['a non-finite count', rawJsonResponse(200, JSON.stringify(receipt(REF_A)).replace('"requests_total":1', '"requests_total":1e309'))],
    ['a foreign response ref', receipt(REF_B)],
  ])('rejects %s', async (_label, payload) => {
    vi.mocked(fetch).mockResolvedValue(payload instanceof Response ? payload : jsonResponse(200, payload));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('failed'));
    expect(result.current.state.data).toBeNull();
  });

  it('rejects a malformed successful body', async () => {
    vi.mocked(fetch).mockResolvedValue(rawJsonResponse(200, '{"ref":'));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('failed'));
  });

  it('rejects a redirected response even when its final body looks valid', async () => {
    const redirected = jsonResponse(200, receipt(REF_A));
    Object.defineProperty(redirected, 'redirected', { value: true });
    vi.mocked(fetch).mockResolvedValue(redirected);
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe('unavailable'));
    expect(result.current.state.data).toBeNull();
  });

  it.each([
    [404, 'failed'],
    [503, 'unavailable'],
  ])('maps HTTP %i to %s without retaining response data', async (status, expected) => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(status, {}));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(result.current.state.status).toBe(expected));
    expect(result.current.state.data).toBeNull();
  });

  it('dedups concurrent readers of the same ref behind one request', async () => {
    let resolveFetch!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise((resolve) => { resolveFetch = resolve; }));
    const ownerA = `owner-a\u0000${REF_A}`;
    const ownerB = `owner-b\u0000${REF_A}`;
    const first = renderHook(() => useConsultedTrace(REF_A, true, ownerA));
    const second = renderHook(() => useConsultedTrace(REF_A, true, ownerB));
    expect(fetch).toHaveBeenCalledTimes(1);
    resolveFetch(jsonResponse(200, receipt(REF_A)));
    await waitFor(() => expect(first.result.current.state.status).toBe('ready'));
    await waitFor(() => expect(second.result.current.state.status).toBe('ready'));
    expect(fetch).toHaveBeenCalledTimes(1);
    first.unmount();
    second.unmount();
  });

  it('aborts the in-flight request when the last reader releases', async () => {
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((_url, init) => {
      capturedSignal = (init as RequestInit).signal ?? undefined;
      return new Promise(() => {}); // Never resolves.
    });
    const { unmount } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(capturedSignal).toBeDefined());
    expect(capturedSignal?.aborted).toBe(false);
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
  });

  it('reports unavailable after the 15s race-safe deadline and allows an explicit retry', async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.state.status).toBe('unavailable');
    expect(result.current.state.retryable).toBe(true);

    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    await act(async () => { await result.current.retry(); });
    expect(result.current.state.status).toBe('ready');
  });

  it('never auto-retries or polls on its own', async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValue(jsonResponse(503, { availability: {} }));
    renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const calls = vi.mocked(fetch).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
  });

  it('clears the entire cache and forces a re-fetch after an auth failure (401)', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, receipt(REF_A)));
    const ownerA = `owner\u0000${REF_A}`;
    const first = renderHook(() => useConsultedTrace(REF_A, true, ownerA));
    await waitFor(() => expect(first.result.current.state.status).toBe('ready'));

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(401, {}));
    const ownerB = `owner\u0000${REF_B}`;
    const second = renderHook(() => useConsultedTrace(REF_B, true, ownerB));
    await waitFor(() => expect(second.result.current.state.status).toBe('unauthorized'));
    await waitFor(() => expect(first.result.current.state.data).toBeNull());
    first.unmount();
    second.unmount();
  });

  describe.each([401, 403])('HTTP %i denial', (status) => {
    it.each(['oversized', 'throwing', 'stalled'] as const)(
      'invalidates active and inactive receipts without reading a %s body or accepting a late success',
      async (bodyKind) => {
        const inactiveRef = 'c'.repeat(64);
        const lateRef = 'd'.repeat(64);
        vi.mocked(fetch)
          .mockResolvedValueOnce(jsonResponse(200, receipt(REF_A, ['GET /active'])))
          .mockResolvedValueOnce(jsonResponse(200, receipt(inactiveRef, ['GET /inactive'])));
        const active = renderHook(() => useConsultedTrace(REF_A, true, 'active-owner'));
        const inactive = renderHook(() => useConsultedTrace(inactiveRef, true, 'inactive-owner'));
        await waitFor(() => {
          expect(active.result.current.state.status).toBe('ready');
          expect(inactive.result.current.state.status).toBe('ready');
        });
        inactive.unmount();
        const retained = renderHook(() => useConsultedTrace(inactiveRef, true, 'retained-owner'));
        expect(retained.result.current.state.data?.requests).toEqual(['GET /inactive']);
        expect(fetch).toHaveBeenCalledTimes(2);
        retained.unmount();

        vi.useFakeTimers();
        let resolveLate!: (value: Response) => void;
        vi.mocked(fetch).mockReturnValueOnce(new Promise((resolve) => { resolveLate = resolve; }));
        const late = renderHook(() => useConsultedTrace(lateRef, true, 'late-owner'));
        const lateSignal = vi.mocked(fetch).mock.calls[2]?.[1]?.signal;
        expect(late.result.current.state.status).toBe('loading');
        expect(lateSignal?.aborted).toBe(false);

        let finishDenialBody = (): void => {};
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            if (bodyKind === 'oversized') {
              controller.enqueue(new Uint8Array(16_385));
              controller.close();
            } else if (bodyKind === 'throwing') {
              controller.error(new Error('Unreadable denial body'));
            } else {
              finishDenialBody = () => controller.error(new Error('Test teardown'));
            }
          },
          cancel() {
            if (bodyKind === 'stalled') {
              return new Promise<void>((resolve) => { finishDenialBody = resolve; });
            }
          },
        });
        const deniedResponse = new Response(body, { status });
        const arrayBuffer = vi.spyOn(deniedResponse, 'arrayBuffer');
        const json = vi.spyOn(deniedResponse, 'json');
        const text = vi.spyOn(deniedResponse, 'text');
        const getReader = vi.spyOn(body, 'getReader');
        const cancel = vi.spyOn(body, 'cancel');
        vi.mocked(fetch).mockResolvedValueOnce(deniedResponse);
        const denied = renderHook(() => useConsultedTrace(REF_B, true, 'denied-owner'));
        const lateResponse = jsonResponse(200, receipt(lateRef, ['GET /late']));

        try {
          await act(async () => { await vi.advanceTimersByTimeAsync(0); });
          for (const hook of [active, late, denied]) {
            expect(hook.result.current.state.status).toBe('unauthorized');
            expect(hook.result.current.state.data).toBeNull();
          }
          expect(lateSignal?.aborted).toBe(true);
          expect(cancel).toHaveBeenCalledTimes(1);
          expect(arrayBuffer).not.toHaveBeenCalled();
          expect(json).not.toHaveBeenCalled();
          expect(text).not.toHaveBeenCalled();
          expect(getReader).not.toHaveBeenCalled();

          const reopened = renderHook(() => useConsultedTrace(inactiveRef, true, 'reopened-owner'));
          expect(reopened.result.current.state.status).toBe('unauthorized');
          expect(reopened.result.current.state.data).toBeNull();
          reopened.unmount();

          await act(async () => {
            resolveLate(lateResponse);
            await vi.advanceTimersByTimeAsync(60_000);
          });
          for (const hook of [active, late, denied]) {
            expect(hook.result.current.state.status).toBe('unauthorized');
            expect(hook.result.current.state.data).toBeNull();
          }
          expect(fetch).toHaveBeenCalledTimes(4);
        } finally {
          active.unmount();
          late.unmount();
          denied.unmount();
          await act(async () => {
            finishDenialBody();
            resolveLate(lateResponse);
          });
        }
      },
    );

    it.each(['absent', 'cancelled', 'cancel throws'] as const)(
      'classifies a denial with a %s body without waiting for disposal',
      async (bodyKind) => {
        vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, receipt(REF_A)));
        const active = renderHook(() => useConsultedTrace(REF_A, true, 'active-owner'));
        await waitFor(() => expect(active.result.current.state.status).toBe('ready'));

        const response = bodyKind === 'absent'
          ? new Response(null, { status })
          : jsonResponse(status, {});
        if (bodyKind === 'cancelled') await response.body!.cancel();
        if (bodyKind === 'cancel throws') {
          vi.spyOn(response.body!, 'cancel').mockImplementation(() => { throw new Error('Disposal failed'); });
        }
        const arrayBuffer = vi.spyOn(response, 'arrayBuffer');
        const json = vi.spyOn(response, 'json');
        vi.mocked(fetch).mockResolvedValueOnce(response);
        const denied = renderHook(() => useConsultedTrace(REF_B, true, 'denied-owner'));

        await waitFor(() => expect(denied.result.current.state.status).toBe('unauthorized'));
        expect(active.result.current.state.status).toBe('unauthorized');
        expect(active.result.current.state.data).toBeNull();
        expect(denied.result.current.state.data).toBeNull();
        expect(arrayBuffer).not.toHaveBeenCalled();
        expect(json).not.toHaveBeenCalled();
        expect(fetch).toHaveBeenCalledTimes(2);
        active.unmount();
        denied.unmount();
      },
    );
  });

  it('keeps shared leases coherent when a 403 clears mounted readers and one reader releases', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(403, {}));
    const first = renderHook(() => useConsultedTrace(REF_A, true, `owner-a\u0000${REF_A}`));
    const second = renderHook(() => useConsultedTrace(REF_A, true, `owner-b\u0000${REF_A}`));
    await waitFor(() => expect(first.result.current.state.status).toBe('unauthorized'));
    expect(second.result.current.state.status).toBe('unauthorized');

    first.unmount();
    window.history.replaceState({}, '', '/?token=re-authorized');
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, receipt(REF_A, ['GET /authorized'])));
    second.rerender();
    await waitFor(() => expect(second.result.current.state.data?.requests).toEqual(['GET /authorized']));
    expect(fetch).toHaveBeenCalledTimes(2);
    second.unmount();
  });

  it('invalidates mounted protected data and starts one fresh read when the page token changes', async () => {
    window.history.replaceState({}, '', '/?token=first-token');
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, receipt(REF_A, ['GET /first'])));
    const { result, rerender } = renderHook(
      ({ owner }: { owner: string }) => useConsultedTrace(REF_A, true, owner),
      { initialProps: { owner: `owner\u0000${REF_A}` } },
    );
    await waitFor(() => expect(result.current.state.data?.requests).toEqual(['GET /first']));

    window.history.replaceState({}, '', '/?token=second-token');
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, receipt(REF_A, ['GET /second'])));
    rerender({ owner: `owner\u0000${REF_A}` });

    await waitFor(() => expect(result.current.state.data?.requests).toEqual(['GET /second']));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetch).mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      headers: { Authorization: 'Bearer second-token' },
    }));
  });

  it('invalidates the previous owner and re-acquires when ownerKey changes for the same ref', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    const { result, rerender } = renderHook(
      ({ owner }: { owner: string }) => useConsultedTrace(REF_A, true, owner),
      { initialProps: { owner: `room-1\u0000${REF_A}` } },
    );
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
    rerender({ owner: `room-2\u0000${REF_A}` });
    // A fresh owner re-acquires; the cached successful result may still be
    // served immediately from the shared entry, but the request must be a
    // deliberate, ref-identified read for the new owner, not a stale carry-over.
    await waitFor(() => expect(result.current.state.status).toBe('ready'));
  });

  it('retains a failed entry across reopen and waits for explicit Retry', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(500, {}));
    const first = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(first.result.current.state.status).toBe('failed'));
    first.unmount();

    // The earlier assertion expected an automatic reopen fetch. That pinned
    // the defect: failed receipts must remain failed until explicit Retry.
    vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    const second = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    expect(second.result.current.state.status).toBe('failed');
    expect(fetch).not.toHaveBeenCalled();
    await act(async () => { await second.result.current.retry(); });
    await waitFor(() => expect(second.result.current.state.status).toBe('ready'));
    expect(fetch).toHaveBeenCalledTimes(1);
    second.unmount();
  });

  it('deduplicates simultaneous explicit retries and does not abort the shared retry', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(503, {}));
    const first = renderHook(() => useConsultedTrace(REF_A, true, `owner-a\u0000${REF_A}`));
    const second = renderHook(() => useConsultedTrace(REF_A, true, `owner-b\u0000${REF_A}`));
    await waitFor(() => expect(first.result.current.state.status).toBe('unavailable'));

    let resolveRetry!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValueOnce(new Promise((resolve) => { resolveRetry = resolve; }));
    const retries = [first.result.current.retry(), second.result.current.retry()];
    expect(fetch).toHaveBeenCalledTimes(2);
    resolveRetry(jsonResponse(200, receipt(REF_A)));
    await act(async () => { await Promise.all(retries); });
    expect(first.result.current.state.status).toBe('ready');
    expect(second.result.current.state.status).toBe('ready');
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('releasing one shared reader does not abort or detach the remaining reader', async () => {
    let capturedSignal: AbortSignal | undefined;
    let resolveFetch!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation((_url, init) => {
      capturedSignal = (init as RequestInit).signal ?? undefined;
      return new Promise((resolve) => { resolveFetch = resolve; });
    });
    const first = renderHook(() => useConsultedTrace(REF_A, true, `owner-a\u0000${REF_A}`));
    const second = renderHook(() => useConsultedTrace(REF_A, true, `owner-b\u0000${REF_A}`));
    await waitFor(() => expect(capturedSignal).toBeDefined());

    first.unmount();
    expect(capturedSignal?.aborted).toBe(false);
    resolveFetch(jsonResponse(200, receipt(REF_A)));
    await waitFor(() => expect(second.result.current.state.status).toBe('ready'));
    second.unmount();
  });

  it('does not expose a late response from a released owner under a new ref', async () => {
    const resolvers = new Map<string, (value: Response) => void>();
    vi.mocked(fetch).mockImplementation((url) => new Promise((resolve) => {
      resolvers.set(String(url), resolve);
    }));
    const { result, rerender } = renderHook(
      ({ ref, owner }: { ref: string; owner: string }) => useConsultedTrace(ref, true, owner),
      { initialProps: { ref: REF_A, owner: `owner-a\u0000${REF_A}` } },
    );
    await waitFor(() => expect(resolvers.has(`/api/traces/${REF_A}/consulted`)).toBe(true));

    rerender({ ref: REF_B, owner: `owner-b\u0000${REF_B}` });
    await waitFor(() => expect(resolvers.has(`/api/traces/${REF_B}/consulted`)).toBe(true));
    resolvers.get(`/api/traces/${REF_B}/consulted`)?.(jsonResponse(200, receipt(REF_B, ['GET /new'])));
    await waitFor(() => expect(result.current.state.data?.ref).toBe(REF_B));
    resolvers.get(`/api/traces/${REF_A}/consulted`)?.(jsonResponse(200, receipt(REF_A, ['GET /old'])));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.state.data?.ref).toBe(REF_B);
    expect(result.current.state.data?.requests).toEqual(['GET /new']);
  });

  it('retains a successful result across a zero-refcount gap (LRU-cacheable)', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, receipt(REF_A)));
    const first = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    await waitFor(() => expect(first.result.current.state.status).toBe('ready'));
    first.unmount();

    vi.mocked(fetch).mockClear();
    const second = renderHook(() => useConsultedTrace(REF_A, true, `owner\u0000${REF_A}`));
    expect(second.result.current.state.status).toBe('ready');
    expect(fetch).not.toHaveBeenCalled();
    second.unmount();
  });

  it('reports unavailable, not a crash, once the bound is exhausted by active readers', async () => {
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}));
    const holders: { unmount: () => void }[] = [];
    for (let index = 0; index < CONSULTED_CACHE_MAX_ENTRIES; index += 1) {
      const ref = index.toString(16).padStart(64, '0');
      holders.push(renderHook(() => useConsultedTrace(ref, true, `owner\u0000${ref}`)));
    }
    const overflowRef = 'f'.repeat(64);
    const { result } = renderHook(() => useConsultedTrace(overflowRef, true, `owner\u0000${overflowRef}`));
    expect(result.current.state.status).toBe('unavailable');
    expect(result.current.state.retryable).toBe(true);
    holders.forEach((holder) => holder.unmount());
  });

  it('evicts an inactive success before admitting the 33rd ref', async () => {
    vi.mocked(fetch).mockImplementation((url) => {
      const parts = String(url).split('/');
      const ref = parts[parts.length - 2] ?? '';
      return Promise.resolve(jsonResponse(200, receipt(ref)));
    });
    for (let index = 0; index < CONSULTED_CACHE_MAX_ENTRIES; index += 1) {
      const ref = index.toString(16).padStart(64, '0');
      const holder = renderHook(() => useConsultedTrace(ref, true, `owner\u0000${ref}`));
      await waitFor(() => expect(holder.result.current.state.status).toBe('ready'));
      holder.unmount();
    }

    const overflowRef = 'f'.repeat(64);
    const overflow = renderHook(() => useConsultedTrace(overflowRef, true, `owner\u0000${overflowRef}`));
    await waitFor(() => expect(overflow.result.current.state.status).toBe('ready'));
    expect(fetch).toHaveBeenCalledTimes(CONSULTED_CACHE_MAX_ENTRIES + 1);
    overflow.unmount();
  });

  it('keeps retained successful wire data within the declared one MiB cache bound', () => {
    expect(CONSULTED_CACHE_MAX_ENTRIES * 16_384).toBeLessThanOrEqual(CONSULTED_CACHE_MAX_BYTES);
  });
});
