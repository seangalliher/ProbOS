import { useEffect, useRef, useState } from 'react';
import { idleResource, loadingResource, requestResource, resourceMessage, nextResourcePoll } from '../utils/resourceState';
import type { ResourceState, ResourcePoll } from '../utils/resourceState';

export interface ServiceStatus {
  name: string;
  status: 'online' | 'offline' | 'degraded';
}

type IntegrationId = 'records' | 'knowledge_browser' | 'skill_requests' | 'ontology_graph' | 'spatial_layout' | 'nats';
type IntegrationState = 'initialized' | 'ready' | 'disabled' | 'unauthorized' | 'unavailable' | 'failed';

interface Integration {
  id: IntegrationId;
  state: IntegrationState;
  scope: 'initialization' | 'connection';
  code: string;
  message: string;
  retryable: boolean;
}

interface ServicesPayload {
  services: ServiceStatus[];
  integrations?: unknown;
}

export interface IntegrationRow {
  id: IntegrationId;
  label: string;
  scope: 'initialization' | 'connection';
  state: IntegrationState | 'unknown';
  message: string;
}

export interface ServiceStatusResult {
  resource: ResourceState<ServicesPayload>;
  services: ServiceStatus[];
  integrations: IntegrationRow[];
  summary: string;
  population: string;
  paused: boolean;
  refresh: () => void;
}

const LABELS: Record<IntegrationId, string> = {
  records: 'Records access', knowledge_browser: 'Knowledge Browser',
  skill_requests: 'Skill requests', ontology_graph: 'Ontology graph',
  spatial_layout: 'Spatial layout', nats: 'NATS',
};
const IDS = Object.keys(LABELS) as IntegrationId[];
const IDENTITY = '/api/system/services';

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function validPayload(value: unknown): value is ServicesPayload {
  if (!object(value) || !Array.isArray(value.services)) return false;
  return value.services.every(service => object(service)
    && typeof service.name === 'string' && !!service.name.trim() && service.name.length <= 120
    && ['online', 'offline', 'degraded'].includes(String(service.status)))
    && new Set(value.services.map(service => service.name)).size === value.services.length;
}

function integrationsOf(value: unknown): Integration[] | null {
  if (!Array.isArray(value) || value.length !== IDS.length) return null;
  const valid = value.every(entry => object(entry)
    && IDS.includes(entry.id as IntegrationId)
    && entry.scope === (entry.id === 'nats' ? 'connection' : 'initialization')
    && ['initialized', 'ready', 'disabled', 'unauthorized', 'unavailable', 'failed'].includes(String(entry.state))
    && (entry.state !== 'ready' || entry.id === 'nats')
    && (entry.state !== 'initialized' || entry.id !== 'nats')
    && typeof entry.code === 'string' && /^[a-z][a-z0-9_.-]{0,79}$/.test(entry.code)
    && typeof entry.message === 'string' && !!entry.message.trim() && entry.message.length <= 240
    && typeof entry.retryable === 'boolean');
  return valid && new Set(value.map(entry => entry.id)).size === IDS.length ? value as Integration[] : null;
}

function integrationMessage(state: IntegrationRow['state']): string {
  if (state === 'unknown') return 'Readiness unknown.';
  if (state === 'initialized') return 'Initialized. Read operations have not been checked.';
  if (state === 'ready') return 'Connected. JetStream operations have not been checked.';
  return resourceMessage(state);
}

export function useServiceStatus(): ServiceStatusResult {
  const [resource, setResource] = useState<ResourceState<ServicesPayload>>(() => idleResource(IDENTITY));
  const [paused, setPaused] = useState(false);
  const refreshRef = useRef<() => void>(() => {});

  useEffect(() => {
    let active = true;
    let pending = false;
    let previous = idleResource<ServicesPayload>(IDENTITY);
    let poll: ResourcePoll = { failures: 0, failedAt: null, nextAt: null };
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;

    const load = async (): Promise<void> => {
      if (!active || pending) return;
      pending = true;
      setPaused(false);
      setResource(previous.data ? { ...previous, refreshing: true } : loadingResource(previous, IDENTITY));
      controller = new AbortController();
      const result = await requestResource(IDENTITY, previous, validPayload, data => data.services.length === 0, controller.signal);
      pending = false;
      if (!active || result === null) return;
      previous = result;
      setResource(result);
      poll = nextResourcePoll(poll, result.status, Date.now());
      if (poll.nextAt === null) setPaused(true);
      else timer = setTimeout(() => { void load(); }, Math.max(0, poll.nextAt - Date.now()));
    };

    refreshRef.current = (): void => {
      if (!active || pending) return;
      clearTimeout(timer);
      poll = { failures: 0, failedAt: null, nextAt: null };
      void load();
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
      refreshRef.current = () => {};
    };
  }, []);

  const services = resource.data?.services ?? [];
  const observations = integrationsOf(resource.data?.integrations);
  const integrations: IntegrationRow[] = IDS.map(id => {
    const state = observations?.find(entry => entry.id === id)?.state ?? 'unknown';
    return { id, label: LABELS[id], scope: id === 'nats' ? 'connection' : 'initialization', state, message: integrationMessage(state) };
  });
  const successful = resource.status === 'ready' || resource.status === 'empty';
  const summary = !successful ? resourceMessage(resource.status)
    : !observations ? 'Integration readiness unknown.'
      : observations.some(entry => entry.state !== 'initialized' && entry.state !== 'ready')
        ? 'Integration checks degraded.' : 'Scoped integration observations available.';
  return {
    resource, services, integrations, summary, paused,
    population: `${services.filter(service => service.status === 'online').length}/${services.length} initialized components (legacy population)`,
    refresh: (): void => refreshRef.current(),
  };
}