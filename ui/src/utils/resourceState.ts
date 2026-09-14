export type ResourceStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'disabled' | 'unauthorized' | 'unavailable' | 'failed';

export interface ResourceState<Data> {
  identity: string;
  status: ResourceStatus;
  data: Data | null;
  refreshing: boolean;
  stale: boolean;
  observedAt: number | null;
  lastSuccess: 'ready' | 'empty' | null;
  retryable: boolean;
}

export const RESOURCE_TIMEOUT_MS = 15_000;

export interface ResourcePoll {
  failures: number;
  failedAt: number | null;
  nextAt: number | null;
}

export function nextResourcePoll(previous: ResourcePoll, status: ResourceStatus, startedAt: number): ResourcePoll {
  if (status === 'ready' || status === 'empty') return { failures: 0, failedAt: null, nextAt: startedAt + 10_000 };
  if (status === 'disabled' || status === 'unauthorized') return { failures: 0, failedAt: null, nextAt: null };
  const failedAt = previous.failedAt ?? startedAt;
  const failures = previous.failures + 1;
  return { failures, failedAt, nextAt: failures > 2 ? null : failedAt + (failures === 1 ? 10_000 : 30_000) };
}

export function idleResource<Data>(identity = ''): ResourceState<Data> {
  return { identity, status: 'idle', data: null, refreshing: false, stale: false, observedAt: null, lastSuccess: null, retryable: false };
}

export function loadingResource<Data>(previous: ResourceState<Data>, identity: string): ResourceState<Data> {
  const retained = previous.identity === identity ? previous : idleResource<Data>(identity);
  return { ...retained, status: 'loading', refreshing: retained.data !== null, retryable: false };
}

export function failedResource<Data>(
  previous: ResourceState<Data>,
  status: 'disabled' | 'unauthorized' | 'unavailable' | 'failed',
): ResourceState<Data> {
  const retained = status === 'unauthorized' ? idleResource<Data>(previous.identity) : previous;
  return {
    ...retained, status, refreshing: false, stale: retained.data !== null,
    retryable: status === 'unavailable' || status === 'failed',
  };
}

function availabilityStatus(payload: unknown): 'disabled' | 'unauthorized' | 'unavailable' | 'failed' | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const availability = (payload as Record<string, unknown>).availability;
  if (!availability || typeof availability !== 'object' || Array.isArray(availability)) return null;
  const { state, code, message, retryable } = availability as Record<string, unknown>;
  if (typeof code !== 'string' || !/^[a-z][a-z0-9_.-]{0,79}$/.test(code)
    || typeof message !== 'string' || !message.trim() || message.length > 240
    || typeof retryable !== 'boolean') return null;
  return state === 'disabled' || state === 'unauthorized' || state === 'unavailable' || state === 'failed'
    ? state : null;
}

export async function classifyResourceResponse<Data>(
  response: Response,
  previous: ResourceState<Data>,
  validate: (payload: unknown) => payload is Data,
  isEmpty: (data: Data) => boolean,
): Promise<ResourceState<Data>> {
  if (response.status === 401 || response.status === 403) return failedResource(previous, 'unauthorized');
  if (response.status === 404 || response.status === 410) return failedResource(idleResource<Data>(previous.identity), 'failed');
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return failedResource(previous, response.status === 503 ? 'unavailable' : 'failed');
  }
  const availability = availabilityStatus(payload);
  if (availability) return failedResource(previous, availability);
  if (!response.ok) return failedResource(previous, response.status === 503 ? 'unavailable' : 'failed');
  if (!validate(payload)) return failedResource(previous, 'failed');
  const status = isEmpty(payload) ? 'empty' : 'ready';
  return {
    identity: previous.identity, status, data: payload,
    refreshing: false, stale: false, observedAt: Date.now(), lastSuccess: status, retryable: false,
  };
}

export async function requestResource<Data>(
  url: string,
  previous: ResourceState<Data>,
  validate: (payload: unknown) => payload is Data,
  isEmpty: (data: Data) => boolean,
  signal: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<ResourceState<Data> | null> {
  if (signal.aborted) return null;
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let cancel = (): void => {};
  const interrupted = new Promise<never>((_resolve, reject) => {
    cancel = () => { controller.abort(); reject(new Error('Request canceled')); };
    signal.addEventListener('abort', cancel, { once: true });
    timeout = setTimeout(() => {
      controller.abort();
      reject(new Error('Request timed out'));
    }, RESOURCE_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      fetchImpl(url, { signal: controller.signal }).then(response => classifyResourceResponse(response, previous, validate, isEmpty)),
      interrupted,
    ]);
  } catch {
    return signal.aborted ? null : failedResource(previous, 'unavailable');
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener('abort', cancel);
  }
}

export function resourceMessage(status: ResourceStatus): string {
  switch (status) {
    case 'idle': return 'Not requested.';
    case 'loading': return 'Loading.';
    case 'disabled': return 'Disabled. Review configuration with the operator.';
    case 'unauthorized': return 'Access denied. Request appropriate access.';
    case 'unavailable': return 'Unavailable. Retry the request.';
    case 'failed': return 'Request failed. Retry the request.';
    case 'empty': return 'No results.';
    case 'ready': return 'Available.';
  }
}