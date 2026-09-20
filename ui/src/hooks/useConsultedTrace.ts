import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  type ResourceState,
  failedResource,
  idleResource,
  loadingResource,
  requestResource,
} from '../utils/resourceState';

export interface ConsultedReceipt {
  ref: string;
  requests: string[];
  requests_total: number;
  requests_omitted: number;
  invalid_entries: number;
  redacted: boolean;
  truncated: boolean;
  notice: string;
}

const REF_SHAPE = /^[0-9a-f]{64}$/;
export const CONSULTED_TRACE_REF_PATTERN = REF_SHAPE;

const MAX_CACHE_REFS = 32;
const MAX_CACHE_BYTES = 1024 * 1024;
const MAX_RESPONSE_BYTES = 16 * 1024;
const MAX_REQUESTS = 40;
const RECEIPT_KEYS = new Set([
  'invalid_entries',
  'notice',
  'redacted',
  'ref',
  'requests',
  'requests_omitted',
  'requests_total',
  'truncated',
]);

export const CONSULTED_CACHE_MAX_ENTRIES = MAX_CACHE_REFS;
export const CONSULTED_CACHE_MAX_BYTES = MAX_CACHE_BYTES;
export const CONSULTED_RESPONSE_MAX_BYTES = MAX_RESPONSE_BYTES;

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === 'number'
    && Number.isSafeInteger(value)
    && value >= 0;
}

function isConsultedReceipt(payload: unknown, expectedRef: string): payload is ConsultedReceipt {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  const p = payload as Record<string, unknown>;
  const keys = Object.keys(p);
  return keys.length === RECEIPT_KEYS.size
    && keys.every((key) => RECEIPT_KEYS.has(key))
    && p.ref === expectedRef
    && Array.isArray(p.requests)
    && p.requests.length <= MAX_REQUESTS
    && p.requests.every((entry) => typeof entry === 'string')
    && isNonNegativeInt(p.requests_total)
    && isNonNegativeInt(p.requests_omitted)
    && isNonNegativeInt(p.invalid_entries)
    && typeof p.redacted === 'boolean'
    && typeof p.truncated === 'boolean'
    && typeof p.notice === 'string'
    && p.notice.trim().length > 0
    && p.requests_total === p.requests.length + p.requests_omitted;
}

function isEmptyReceipt(data: ConsultedReceipt): boolean {
  return data.requests.length === 0 && data.requests_total === 0;
}

function freezeReceipt(data: ConsultedReceipt): ConsultedReceipt {
  Object.freeze(data.requests);
  return Object.freeze(data);
}

function pageToken(): string {
  return new URLSearchParams(window.location.search).get('token') ?? '';
}

function fetchWithAuth(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  token: string,
): Promise<Response> {
  return fetch(input, {
    ...init,
    mode: 'same-origin',
    redirect: 'error',
    cache: 'no-store',
    headers: token ? { Authorization: `Bearer ${token}` } : init?.headers,
  });
}

interface CacheEntry {
  ref: string;
  readers: Set<symbol>;
  controller: AbortController | null;
  inFlight: Promise<void> | null;
  state: ResourceState<ConsultedReceipt>;
  bytes: number;
  generation: number;
  authGeneration: number;
}

interface Lease {
  entry: CacheEntry;
  reader: symbol;
  ownerKey: string;
  released: boolean;
}

const cache = new Map<string, CacheEntry>();
const listeners = new Set<() => void>();
let currentPageToken: string | null = null;
let authGeneration = 0;

const NULL_STATE: ResourceState<ConsultedReceipt> = idleResource<ConsultedReceipt>('');
const EXHAUSTED_STATE: ResourceState<ConsultedReceipt> = Object.freeze({
  identity: '',
  status: 'unavailable',
  data: null,
  refreshing: false,
  stale: false,
  observedAt: null,
  lastSuccess: null,
  retryable: true,
});

function notifyAll(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function totalBytes(): number {
  let sum = 0;
  for (const entry of cache.values()) sum += entry.bytes;
  return sum;
}

function removeEntry(entry: CacheEntry): void {
  entry.controller?.abort();
  entry.generation += 1;
  entry.controller = null;
  entry.inFlight = null;
  entry.bytes = 0;
  if (cache.get(entry.ref) === entry) cache.delete(entry.ref);
}

function evictOneInactive(except?: CacheEntry): boolean {
  for (const entry of cache.values()) {
    if (entry !== except && entry.readers.size === 0) {
      removeEntry(entry);
      return true;
    }
  }
  return false;
}

function makeEntryRoom(): boolean {
  while (cache.size >= MAX_CACHE_REFS) {
    if (!evictOneInactive()) return false;
  }
  return true;
}

function makeByteRoom(entry: CacheEntry, nextBytes: number): boolean {
  while (totalBytes() - entry.bytes + nextBytes > MAX_CACHE_BYTES) {
    if (!evictOneInactive(entry)) return false;
  }
  return true;
}

function acquire(ref: string, ownerKey: string): Lease | null {
  let entry = cache.get(ref);
  if (entry && entry.authGeneration !== authGeneration) {
    removeEntry(entry);
    entry = undefined;
  }
  if (!entry) {
    if (!makeEntryRoom()) return null;
    entry = {
      ref,
      readers: new Set(),
      controller: null,
      inFlight: null,
      state: idleResource<ConsultedReceipt>(ref),
      bytes: 0,
      generation: 0,
      authGeneration,
    };
    cache.set(ref, entry);
  } else {
    cache.delete(ref);
    cache.set(ref, entry);
  }
  const reader = Symbol(ownerKey);
  entry.readers.add(reader);
  return { entry, reader, ownerKey, released: false };
}

function release(lease: Lease): void {
  if (lease.released) return;
  lease.released = true;
  const { entry } = lease;
  entry.readers.delete(lease.reader);
  if (entry.readers.size > 0) return;
  if (entry.state.status === 'loading' || entry.state.status === 'idle') {
    removeEntry(entry);
  }
}

function clearForTokenChange(token: string): void {
  currentPageToken = token;
  authGeneration += 1;
  for (const entry of [...cache.values()]) {
    entry.state = idleResource<ConsultedReceipt>(entry.ref);
    removeEntry(entry);
  }
  queueMicrotask(notifyAll);
}

function synchronizeAuthContext(token: string): void {
  if (currentPageToken === null) {
    currentPageToken = token;
  } else if (currentPageToken !== token) {
    clearForTokenChange(token);
  }
}

function invalidateForAuthFailure(): void {
  for (const entry of cache.values()) {
    entry.controller?.abort();
    entry.generation += 1;
    entry.controller = null;
    entry.inFlight = null;
    entry.bytes = 0;
    entry.state = failedResource(idleResource<ConsultedReceipt>(entry.ref), 'unauthorized');
  }
  notifyAll();
}

async function readBoundedResponse(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  token: string,
  onBytes: (bytes: number) => void,
): Promise<Response> {
  const response = await fetchWithAuth(input, init, token);
  if (response.redirected) throw new Error('Redirected consulted receipt rejected');
  if (response.status === 401 || response.status === 403) {
    // Disposal is best-effort: a thrown, rejected, or stalled cancel must not delay auth invalidation.
    void Promise.resolve().then(() => response.body?.cancel()).catch(() => {});
    return response;
  }
  const body = await response.arrayBuffer();
  if (body.byteLength > MAX_RESPONSE_BYTES) throw new Error('Consulted receipt exceeds wire limit');
  onBytes(body.byteLength);
  const bodyInit = response.status === 204 || response.status === 205 || response.status === 304
    ? null
    : body;
  return new Response(bodyInit, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

function beginFetch(ref: string, entry: CacheEntry): Promise<void> {
  if (entry.inFlight) return entry.inFlight;

  const token = pageToken();
  entry.generation += 1;
  const generation = entry.generation;
  const requestAuthGeneration = authGeneration;
  const controller = new AbortController();
  entry.controller = controller;
  entry.state = loadingResource(entry.state, ref);
  notifyAll();

  let wireBytes = 0;
  const validate = (payload: unknown): payload is ConsultedReceipt => isConsultedReceipt(payload, ref);
  const boundedFetch: typeof fetch = (input, init) => readBoundedResponse(
    input,
    init,
    token,
    (bytes) => { wireBytes = bytes; },
  );

  const operation = (async (): Promise<void> => {
    const url = `/api/traces/${encodeURIComponent(ref)}/consulted`;
    const result = await requestResource(
      url,
      entry.state,
      validate,
      isEmptyReceipt,
      controller.signal,
      boundedFetch,
    );

    if (cache.get(ref) !== entry
      || entry.generation !== generation
      || requestAuthGeneration !== authGeneration
      || result === null) return;

    if (result.status === 'unauthorized') {
      invalidateForAuthFailure();
      return;
    }

    if (result.status === 'ready' || result.status === 'empty') {
      if (!result.data || !makeByteRoom(entry, wireBytes)) {
        entry.bytes = 0;
        entry.state = failedResource(idleResource<ConsultedReceipt>(ref), 'unavailable');
      } else {
        entry.bytes = wireBytes;
        entry.state = { ...result, data: freezeReceipt(result.data) };
      }
    } else {
      entry.bytes = 0;
      entry.state = result;
    }
    notifyAll();
  })();

  entry.inFlight = operation;
  void operation.finally(() => {
    if (entry.inFlight === operation) {
      entry.inFlight = null;
      entry.controller = null;
    }
  });
  return operation;
}

export interface UseConsultedTraceResult {
  state: ResourceState<ConsultedReceipt>;
  retry: () => Promise<void>;
}

export function useConsultedTrace(
  ref: string | null,
  expanded: boolean,
  ownerKey: string,
): UseConsultedTraceResult {
  const token = pageToken();
  synchronizeAuthContext(token);
  const active = expanded && typeof ref === 'string' && REF_SHAPE.test(ref);
  const effectiveRef = active ? ref : null;
  const leaseRef = useRef<Lease | null>(null);
  const [exhaustedOwner, setExhaustedOwner] = useState<string | null>(null);
  const activeOwner = effectiveRef ? `${ownerKey}\u0000${effectiveRef}` : '';

  useEffect(() => {
    if (!effectiveRef) {
      setExhaustedOwner(null);
      return undefined;
    }

    const lease = acquire(effectiveRef, activeOwner);
    leaseRef.current = lease;
    if (!lease) {
      setExhaustedOwner(activeOwner);
      return () => {
        const current = leaseRef.current;
        if (current?.ownerKey === activeOwner) {
          leaseRef.current = null;
          release(current);
        }
      };
    }

    setExhaustedOwner(null);
    if (lease.entry.state.status === 'idle') {
      void beginFetch(effectiveRef, lease.entry);
    } else {
      notifyAll();
    }

    return () => {
      const current = leaseRef.current;
      if (current?.ownerKey === activeOwner) {
        leaseRef.current = null;
        release(current);
      } else {
        release(lease);
      }
    };
  }, [activeOwner, effectiveRef, token]);

  const getSnapshot = useCallback((): ResourceState<ConsultedReceipt> => {
    if (!effectiveRef) return NULL_STATE;
    if (exhaustedOwner === activeOwner) return EXHAUSTED_STATE;
    const lease = leaseRef.current;
    return lease?.entry.ref === effectiveRef && !lease.released
      ? lease.entry.state
      : NULL_STATE;
  }, [activeOwner, effectiveRef, exhaustedOwner]);

  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const currentInputs = useRef({ effectiveRef, activeOwner });
  currentInputs.current = { effectiveRef, activeOwner };
  const retry = useCallback(async (): Promise<void> => {
    const inputs = currentInputs.current;
    if (!inputs.effectiveRef) return;

    const latestToken = pageToken();
    synchronizeAuthContext(latestToken);
    let lease = leaseRef.current;
    if (!lease
      || lease.released
      || lease.entry.ref !== inputs.effectiveRef
      || lease.entry.authGeneration !== authGeneration) {
      if (lease) release(lease);
      lease = acquire(inputs.effectiveRef, inputs.activeOwner);
      leaseRef.current = lease;
      if (!lease) {
        setExhaustedOwner(inputs.activeOwner);
        return;
      }
      setExhaustedOwner(null);
    }
    await beginFetch(inputs.effectiveRef, lease.entry);
  }, []);

  return { state, retry };
}

export function resetConsultedTraceCacheForTests(): void {
  for (const entry of [...cache.values()]) removeEntry(entry);
  listeners.clear();
  currentPageToken = null;
  authGeneration = 0;
}
