import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import type { AgentProfileData, ProfileMeasurement } from '../store/types';
import {
  idleResource, loadingResource, nextResourcePoll, requestResource, resourceMessage,
  RESOURCE_TIMEOUT_MS, type ResourcePoll, type ResourceState,
} from '../utils/resourceState';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function isNonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

export function isSampleTime(value: unknown): value is string {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)
    && Number.isFinite(Date.parse(value));
}

export function validMeasurement(
  value: unknown, measured: unknown, subject: string | null,
  population: string, unit: string, source: string,
): value is ProfileMeasurement {
  if (!isRecord(value)) return false;
  const keys = ['subjectId', 'population', 'unit', 'source', 'sampleStartedAt', 'sampleCompletedAt', 'status'];
  if (Object.keys(value).length !== keys.length || !keys.every(key => key in value)) return false;
  if (value.population !== population || value.unit !== unit || value.source !== source) return false;
  if (value.status !== 'available' && value.status !== 'unavailable' && value.status !== 'failed') return false;
  if (value.subjectId !== null && (typeof value.subjectId !== 'string' || !value.subjectId.trim())) return false;
  if (subject !== null && value.subjectId !== null && value.subjectId !== subject) return false;
  const start = value.sampleStartedAt;
  const end = value.sampleCompletedAt;
  if (start !== null && !isSampleTime(start)) return false;
  if (end !== null && !isSampleTime(end)) return false;
  if ((start === null) !== (end === null)) return false;
  if (typeof start === 'string' && typeof end === 'string' && Date.parse(start) > Date.parse(end)) return false;
  if (value.status === 'available') {
    return value.subjectId !== null && start !== null && end !== null
      && isNonnegative(measured) && (unit !== 'episodes' || Number.isSafeInteger(measured));
  }
  return measured === null;
}

export function validProfile(value: unknown, agentId: string): value is AgentProfileData {
  if (!isRecord(value) || value.id !== agentId) return false;
  const strings = ['agentType', 'callsign', 'displayName', 'rank', 'agencyLevel', 'department', 'state', 'tier', 'pool'];
  if (!strings.every(key => typeof value[key] === 'string')) return false;
  if ('sovereignId' in value && typeof value.sovereignId !== 'string') return false;
  if (typeof value.isCrew !== 'boolean' || ('visionCapable' in value && typeof value.visionCapable !== 'boolean')) return false;
  if (!isNonnegative(value.trust) || value.trust > 1 || !isNonnegative(value.confidence) || value.confidence > 1) return false;
  if (!Array.isArray(value.trustHistory) || !value.trustHistory.every(score => isNonnegative(score) && score <= 1)) return false;
  if (!isRecord(value.personality) || !Object.values(value.personality).every(isNonnegative)) return false;
  if (!Array.isArray(value.specialization) || !value.specialization.every(entry => typeof entry === 'string')) return false;
  if (!Array.isArray(value.hebbianConnections) || !value.hebbianConnections.every(connection =>
    isRecord(connection) && typeof connection.targetId === 'string' && typeof connection.relType === 'string'
    && typeof connection.weight === 'number' && Number.isFinite(connection.weight))) return false;
  if (value.proactiveCooldown !== null && !isNonnegative(value.proactiveCooldown)) return false;
  if (value.memoryCount !== null && (!isNonnegative(value.memoryCount) || !Number.isSafeInteger(value.memoryCount))) return false;
  if (value.uptime !== null && !isNonnegative(value.uptime)) return false;
  const subject = typeof value.sovereignId === 'string' && value.sovereignId ? value.sovereignId : agentId;
  if ('memoryCountMetadata' in value && !validMeasurement(value.memoryCountMetadata, value.memoryCount,
    subject, 'stored_agent_membership', 'episodes', 'episodic_memory.count_for_agent')) return false;
  if ('uptimeMetadata' in value && !validMeasurement(value.uptimeMetadata, value.uptime,
    'system', 'system_runtime', 'seconds', 'runtime.get_uptime_seconds')) return false;
  if ('voiceProfile' in value) {
    const voice = value.voiceProfile;
    if (!isRecord(voice) || typeof voice.voice_name !== 'string'
      || !['pitch', 'rate', 'volume'].every(key => isNonnegative(voice[key]))
      || ('wake_phrase' in voice && typeof voice.wake_phrase !== 'string')) return false;
  }
  if ('appearance' in value) {
    const appearance = value.appearance;
    if (!isRecord(appearance) || typeof appearance.vrm_url !== 'string'
      || typeof appearance.color_palette_hint !== 'string' || !isRecord(appearance.expression_overrides)
      || !Object.values(appearance.expression_overrides).every(entry => typeof entry === 'number' && Number.isFinite(entry))) return false;
  }
  return true;
}

export function profileSampleTime(profile: AgentProfileData): number | null {
  const samples = [profile.memoryCountMetadata, profile.uptimeMetadata];
  if (samples.some(sample => !sample || sample.status !== 'available' || !sample.sampleCompletedAt)) return null;
  return Math.min(...samples.map(sample => Date.parse(sample!.sampleCompletedAt!)));
}

interface ProfileResourceOptions<Data> {
  identity: string;
  url: string;
  eligible: boolean;
  independentReads?: boolean;
  pollWhen?: (payload: Data | null) => boolean;
  validate: (payload: unknown) => payload is Data;
  isEmpty: (payload: Data) => boolean;
  sampleTime: (payload: Data) => number | null;
}

interface ProfileResource<Data> {
  state: ResourceState<Data>;
  refresh: () => Promise<Data | null>;
  message: string;
}

export function useProfileResource<Data>(options: ProfileResourceOptions<Data>): ProfileResource<Data> {
  const connected = useStore(state => state.connected);
  const generation = useStore(state => state.liveGeneration);
  const repairEpoch = useStore(state => state.liveRepairEpoch);
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  const identity = JSON.stringify([options.identity, options.url, generation, repairEpoch]);
  const [entry, setEntry] = useState<ResourceState<Data>>(() => idleResource(identity));
  const wantsPoll = options.pollWhen?.(entry.identity === identity ? entry.data : null) ?? true;
  const enabled = options.eligible && connected && visible && wantsPoll;
  const canRead = options.eligible && (options.independentReads === true || connected && visible);
  const lifecycleKey = JSON.stringify([identity, options.eligible, options.independentReads, connected, visible, wantsPoll]);
  const [lifetime, setLifetime] = useState({ key: lifecycleKey, token: {} });
  if (lifetime.key !== lifecycleKey) setLifetime({ key: lifecycleKey, token: {} });
  const current = useRef<ResourceState<Data>>(entry);
  const callbacks = useRef(options);
  const ticket = useRef(0);
  const owner = useRef<{ token: object; refresh: () => Promise<Data | null> } | null>(null);
  const previousLifecycle = useRef<{
    key: string; identity: string; eligible: boolean; connected: boolean; visible: boolean; wantsPoll: boolean;
  } | null>(null);

  useLayoutEffect(() => { callbacks.current = options; });
  useEffect(() => {
    const onVisibility = (): void => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  useLayoutEffect(() => {
    const previous = previousLifecycle.current;
    previousLifecycle.current = { key: lifecycleKey, identity, eligible: options.eligible, connected, visible, wantsPoll };
    let disposed = false;
    let controller: AbortController | null = null;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;
    let poll: ResourcePoll = { failures: 0, failedAt: null, nextAt: null };
    const refreshWaiters = new Set<{
      minimumTicket: number; resolve: (data: Data | null) => void; timeout?: ReturnType<typeof setTimeout>;
    }>();
    const settleRefreshes = (requestTicket: number, data: Data | null): void => {
      for (const waiter of refreshWaiters) {
        if (waiter.minimumTicket > requestTicket) continue;
        clearTimeout(waiter.timeout);
        refreshWaiters.delete(waiter);
        waiter.resolve(data);
      }
    };
    const token = lifetime.token;
    const publish = (next: ResourceState<Data>): void => {
      if (disposed || owner.current?.token !== token) return;
      current.current = next;
      setEntry(next);
    };
    const expire = (): void => {
      clearTimeout(expiryTimer);
      const sample = current.current.observedAt;
      if (sample === null || current.current.data === null) return;
      const remaining = sample + 10_000 - Date.now();
      if (remaining <= 0) publish({ ...current.current, stale: true });
      else expiryTimer = setTimeout(() => publish({ ...current.current, stale: true }), remaining);
    };
    const load = (manual = false): Promise<Data | null> => {
      if (!canRead || disposed || owner.current?.token !== token) return Promise.resolve(null);
      clearTimeout(pollTimer);
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      const requestTicket = ++ticket.current;
      const completion = manual ? new Promise<Data | null>(resolve => {
        const waiter = { minimumTicket: requestTicket, resolve, timeout: undefined as ReturnType<typeof setTimeout> | undefined };
        refreshWaiters.add(waiter);
        waiter.timeout = setTimeout(() => {
          refreshWaiters.delete(waiter);
          resolve(null);
        }, RESOURCE_TIMEOUT_MS);
      }) : null;
      const accepts = (): boolean => !disposed && !signal.aborted
        && owner.current?.token === token && requestTicket === ticket.current;
      if (manual) poll = { failures: 0, failedAt: null, nextAt: null };
      const previous = current.current.identity === identity ? current.current : idleResource<Data>(identity);
      publish(loadingResource(previous, identity));
      expire();
      const config = callbacks.current;
      const guardedFetch: typeof fetch = async (input, init) => {
        const response = await fetch(input, init);
        if (!accepts()) throw new Error('Superseded profile request');
        return response;
      };
      const operation = requestResource(config.url, previous,
        (payload): payload is Data => accepts() && config.validate(payload),
        config.isEmpty, signal, guardedFetch).then(result => {
        if (!accepts() || !result) return null;
        const successful = result.status === 'ready' || result.status === 'empty';
        const sampledAt = successful && result.data !== null ? config.sampleTime(result.data) : result.observedAt;
        publish({ ...result, observedAt: sampledAt,
          stale: result.stale || (result.data !== null && (!connected || !visible || sampledAt === null || Date.now() >= sampledAt + 10_000)) });
        expire();
        poll = nextResourcePoll(poll, result.status, Date.now());
        if (enabled && poll.nextAt !== null) pollTimer = setTimeout(() => { void load(); }, Math.max(0, poll.nextAt - Date.now()));
        settleRefreshes(requestTicket, successful ? result.data : null);
        return successful ? result.data : null;
      });
      return completion ?? operation;
    };
    owner.current = { token, refresh: () => load(true) };
    const retained = current.current.identity === identity ? current.current : idleResource<Data>(identity);
    publish(connected && visible ? { ...retained, refreshing: false,
      status: retained.status === 'loading' ? retained.lastSuccess ?? 'idle' : retained.status }
      : { ...retained, status: retained.lastSuccess ?? 'unavailable', refreshing: false, stale: retained.data !== null });
    expire();
    const suspended = previous !== null && (previous.connected && !connected || previous.visible && !visible);
    const firstRead = options.independentReads === true && options.eligible && !suspended
      && (previous === null || previous.identity !== identity || !previous.eligible
        || previous.key === lifecycleKey && retained.data === null);
    const activated = enabled && (options.independentReads !== true || previous === null
      || previous.identity !== identity || !previous.eligible || !previous.connected || !previous.visible || !previous.wantsPoll);
    if (firstRead || activated) void load();
    return () => {
      disposed = true;
      ++ticket.current;
      controller?.abort();
      clearTimeout(pollTimer);
      clearTimeout(expiryTimer);
      settleRefreshes(Number.POSITIVE_INFINITY, null);
      if (owner.current?.token === token) owner.current = null;
    };
  }, [identity, enabled, canRead, connected, visible, wantsPoll, options.eligible, options.independentReads, lifecycleKey, lifetime.token]);

  const refresh = useCallback((): Promise<Data | null> => {
    return owner.current?.token === lifetime.token ? owner.current.refresh() : Promise.resolve(null);
  }, [lifetime.token]);
  const state = entry.identity === identity ? entry : idleResource<Data>(identity);
  const sampled = state.observedAt === null ? 'Sample time/scope unverified.'
    : `Sampled ${new Date(state.observedAt).toISOString()}.`;
  const message = state.data === null ? resourceMessage(state.status)
    : `${state.stale || !connected || !visible ? 'Stale. ' : 'Current. '}${sampled}${state.status === 'loading' ? ' Refreshing.'
      : state.status !== 'ready' && state.status !== 'empty' ? ` ${resourceMessage(state.status)}` : ''}`;
  return { state, refresh, message };
}