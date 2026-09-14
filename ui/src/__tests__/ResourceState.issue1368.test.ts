import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  classifyResourceResponse, failedResource, idleResource, loadingResource,
  requestResource, resourceMessage, RESOURCE_TIMEOUT_MS, nextResourcePoll,
} from '../utils/resourceState';
import type { ResourceStatus } from '../utils/resourceState';

interface Snapshot { name: string }

const validate = (payload: unknown): payload is Snapshot => (
  payload !== null && typeof payload === 'object' && 'name' in payload && typeof payload.name === 'string'
);
const isEmpty = (payload: Snapshot): boolean => payload.name.length === 0;
const pending = () => loadingResource(idleResource<Snapshot>(), 'same');
const response = (payload: unknown, status = 200): Response => new Response(JSON.stringify(payload), { status });
const metadata = (state: string) => ({ availability: { state, code: 'records_unavailable', message: 'Controlled response', retryable: false } });

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('resource response classification (issue #1368)', () => {
  it.each([['populated', 'ready'], ['', 'empty']] as const)('accepts validated success %s as %s', async (name, status) => {
    const result = await classifyResourceResponse(response({ name }), pending(), validate, isEmpty);
    expect(result).toMatchObject({ status, data: { name }, stale: false, refreshing: false, lastSuccess: status });
    expect(result.observedAt).toEqual(expect.any(Number));
  });

  it.each([
    [401, { error: 'secret' }, 'unauthorized'],
    [403, metadata('disabled'), 'unauthorized'],
    [503, { error: 'Knowledge Browser not available' }, 'unavailable'],
    [503, { detail: 'private diagnostic' }, 'unavailable'],
    [500, { error: 'internal stack trace' }, 'failed'],
    [404, { detail: 'missing' }, 'failed'],
    [503, metadata('disabled'), 'disabled'],
    [200, metadata('unavailable'), 'unavailable'],
    [503, metadata('unauthorized'), 'unauthorized'],
    [500, metadata('failed'), 'failed'],
    [503, { availability: { state: 'disabled' } }, 'unavailable'],
    [503, { availability: { ...metadata('disabled').availability, code: '../private' } }, 'unavailable'],
    [503, { availability: { ...metadata('disabled').availability, message: '' } }, 'unavailable'],
    [503, { availability: { ...metadata('disabled').availability, message: 'x'.repeat(241) } }, 'unavailable'],
    [503, { availability: { ...metadata('disabled').availability, retryable: 'false' } }, 'unavailable'],
    [503, { availability: [] }, 'unavailable'],
    [503, metadata('unknown'), 'unavailable'],
  ] as const)('classifies HTTP %s with %j as %s', async (status, payload, expected) => {
    const result = await classifyResourceResponse(response(payload, status), pending(), validate, isEmpty);
    expect(result.status).toBe(expected);
    expect(result.data).toBeNull();
    expect(result.retryable).toBe(expected === 'unavailable' || expected === 'failed');
    expect(resourceMessage(result.status)).not.toMatch(/secret|diagnostic|trace|private/);
  });

  it.each([null, [], {}, { name: 3 }, { error: 'not actually successful' }])('rejects malformed success %j', async payload => {
    expect((await classifyResourceResponse(response(payload), pending(), validate, isEmpty)).status).toBe('failed');
  });

  it.each([[200, 'failed'], [500, 'failed'], [503, 'unavailable'], [401, 'unauthorized']] as const)(
    'classifies invalid JSON at HTTP %s as %s', async (status, expected) => {
      const result = await classifyResourceResponse(new Response('not JSON', { status }), pending(), validate, isEmpty);
      expect(result.status).toBe(expected);
    },
  );

  it('retains a same-identity snapshot as stale and replaces it on recovery', async () => {
    const good = await classifyResourceResponse(response({ name: 'old' }), pending(), validate, isEmpty);
    const loading = loadingResource(good, 'same');
    expect(loading).toMatchObject({ refreshing: true, data: good.data });
    const stale = await classifyResourceResponse(response({}, 503), loading, validate, isEmpty);
    expect(stale).toMatchObject({ status: 'unavailable', stale: true, observedAt: good.observedAt, data: good.data });
    const recovered = await classifyResourceResponse(response({ name: 'new' }), loadingResource(stale, 'same'), validate, isEmpty);
    expect(recovered).toMatchObject({ status: 'ready', stale: false, refreshing: false, data: { name: 'new' } });
    const different = loadingResource(good, 'different');
    expect(different).toMatchObject({ identity: 'different', data: null, observedAt: null, lastSuccess: null });
  });

  it.each([401, 403])('clears cached content and freshness on HTTP %s', async status => {
    const good = await classifyResourceResponse(response({ name: 'private' }), pending(), validate, isEmpty);
    const result = await classifyResourceResponse(response({}, status), loadingResource(good, 'same'), validate, isEmpty);
    expect(result).toMatchObject({ status: 'unauthorized', data: null, observedAt: null, stale: false, lastSuccess: null });
    expect(loadingResource(result, 'same').data).toBeNull();
  });

  it('labels a retained empty result as stale without turning the failure into empty', async () => {
    const good = await classifyResourceResponse(response({ name: '' }), pending(), validate, isEmpty);
    expect(failedResource(good, 'failed')).toMatchObject({ status: 'failed', lastSuccess: 'empty', stale: true });
    expect(idleResource()).toMatchObject({ identity: '', status: 'idle', data: null });
  });

  it.each<ResourceStatus>(['idle', 'loading', 'ready', 'empty', 'disabled', 'unauthorized', 'unavailable', 'failed'])(
    'provides bounded controlled text for %s', status => {
      expect(resourceMessage(status).length).toBeGreaterThan(0);
      expect(resourceMessage(status).length).toBeLessThan(100);
    },
  );
});

describe('bounded resource reads (issue #1368)', () => {
  it('bounds retry offsets and resets only on successful observations', () => {
    const first = nextResourcePoll({ failures: 0, failedAt: null, nextAt: null }, 'unavailable', 1_000);
    expect(first).toEqual({ failures: 1, failedAt: 1_000, nextAt: 11_000 });
    const second = nextResourcePoll(first, 'failed', 11_000);
    expect(second).toEqual({ failures: 2, failedAt: 1_000, nextAt: 31_000 });
    expect(nextResourcePoll(second, 'unavailable', 31_000).nextAt).toBeNull();
    for (const status of ['ready', 'empty'] as const) {
      expect(nextResourcePoll(second, status, 40_000)).toEqual({ failures: 0, failedAt: null, nextAt: 50_000 });
    }
    for (const status of ['disabled', 'unauthorized'] as const) {
      expect(nextResourcePoll(first, status, 11_000)).toEqual({ failures: 0, failedAt: null, nextAt: null });
    }
  });

  it('uses the injected transport with the same timeout and abort boundary', async () => {
    vi.useFakeTimers();
    const transport = vi.fn<typeof fetch>().mockImplementation(() => new Promise<Response>(() => {}));
    const result = requestResource('/skills', pending(), validate, isEmpty, new AbortController().signal, transport);
    expect(transport).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS);
    expect(await result).toMatchObject({ status: 'unavailable' });
    expect(transport.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['fetch', 'body'])('bounds a hung %s and never automatically retries', async phase => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(() => phase === 'fetch'
      ? new Promise<Response>(() => {})
      : Promise.resolve({ ok: true, status: 200, json: () => new Promise(() => {}) } as Response));
    const result = requestResource('/records', pending(), validate, isEmpty, new AbortController().signal);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS);
    expect(await result).toMatchObject({ status: 'unavailable', retryable: true });
    expect((fetchMock.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('ignores cancellation and cleans its timer even when fetch ignores abort', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(() => new Promise<Response>(() => {}));
    const controller = new AbortController();
    const result = requestResource('/records', pending(), validate, isEmpty, controller.signal);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    controller.abort();
    expect(await result).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
    expect(await requestResource('/records', pending(), validate, isEmpty, controller.signal)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('classifies a network rejection as unavailable', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('private transport failure'));
    expect(await requestResource('/records', pending(), validate, isEmpty, new AbortController().signal))
      .toMatchObject({ status: 'unavailable', data: null });
  });

  it('returns successful data and removes the timeout', async () => {
    vi.useFakeTimers();
    vi.spyOn(global, 'fetch').mockResolvedValue(response({ name: 'good' }));
    expect(await requestResource('/records', pending(), validate, isEmpty, new AbortController().signal))
      .toMatchObject({ status: 'ready', data: { name: 'good' } });
    expect(vi.getTimerCount()).toBe(0);
  });
});