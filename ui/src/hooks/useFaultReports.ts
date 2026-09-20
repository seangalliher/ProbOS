import { useEffect, useRef, useState } from 'react';
import {
  failedResource, idleResource, loadingResource, nextResourcePoll, requestResource,
  type ResourcePoll, type ResourceState,
} from '../utils/resourceState';

export interface FaultIssue {
  repository: string;
  number: number;
  url: string;
}

export interface FaultSummary {
  id: string;
  signature: string;
  tool_id: string;
  summary: string;
  status: 'open' | 'diagnosing' | 'repaired' | 'dismissed';
  occurrences: string;
  first_seen_at: number;
  last_seen_at: number;
  issue: FaultIssue | null;
  issue_lookup_available: boolean;
}

export interface FaultDetail extends FaultSummary {
  error_text: string;
  attempted: string;
  recorded_agent_id: string;
  thread_id: string;
  work_item_id: string | null;
  observed_as: string;
  trace_summary: string;
  trace_available: boolean;
  clipped_fields: string[];
}

export interface FaultList {
  faults: FaultSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface FaultDetailPayload { fault: FaultDetail }

export interface FaultReports {
  resource: ResourceState<FaultList>;
  detail: ResourceState<FaultDetailPayload>;
  selectedId: string | null;
  paused: boolean;
  detailPaused: boolean;
  refresh: () => void;
  select: (id: string) => void;
  previousPage: () => void;
  nextPage: () => void;
}

const LIMIT = 50;
const LIST = '/api/faults';
const CLIPPED_FIELDS = [
  'summary', 'tool_id', 'error_text', 'attempted', 'recorded_agent_id',
  'thread_id', 'work_item_id', 'observed_as', 'trace_summary',
];
const freshPoll = (): ResourcePoll => ({ failures: 0, failedAt: null, nextAt: null });
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown, max: number): value is string =>
  typeof value === 'string' && Array.from(value).length <= max;
const integer = (value: unknown, min: number): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= min;
const current = (resource: ResourceState<unknown>): boolean =>
  resource.status === 'ready' || resource.status === 'empty';

function validIssue(value: unknown): value is FaultIssue | null {
  if (value === null) return true;
  if (!object(value) || typeof value.repository !== 'string' || !integer(value.number, 1)
    || typeof value.url !== 'string') return false;
  const repository = value.repository;
  if (!/^(?=[^/]{1,39}\/)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\/[A-Za-z0-9_.-]{1,100}$/.test(repository)
    || ['.', '..'].includes(repository.split('/')[1])) return false;
  return value.url.toLowerCase() === `https://github.com/${repository}/issues/${value.number}`.toLowerCase()
    && /^https:\/\/github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+\/issues\/[1-9][0-9]*$/.test(value.url);
}

function validSummary(value: unknown): value is FaultSummary {
  return object(value)
    && typeof value.id === 'string' && /^[0-9a-f]{12}$/.test(value.id)
    && typeof value.signature === 'string' && /^[0-9a-f]{64}$/.test(value.signature)
    && text(value.tool_id, 128) && text(value.summary, 160) && !!value.summary.trim()
    && ['open', 'diagnosing', 'repaired', 'dismissed'].includes(String(value.status))
    && typeof value.occurrences === 'string' && /^[1-9][0-9]{0,18}$/.test(value.occurrences)
    && (value.occurrences.length < 19 || value.occurrences <= '9223372036854775807')
    && typeof value.first_seen_at === 'number' && Number.isFinite(value.first_seen_at)
    && typeof value.last_seen_at === 'number' && Number.isFinite(value.last_seen_at)
    && typeof value.issue_lookup_available === 'boolean' && validIssue(value.issue)
    && (value.issue_lookup_available || value.issue === null);
}

export function validFaultList(value: unknown): value is FaultList {
  return object(value) && integer(value.total, 0) && integer(value.limit, 1) && value.limit <= 100
    && integer(value.offset, 0) && Array.isArray(value.faults)
    && value.faults.every(row => validSummary(row) && ['open', 'diagnosing'].includes(row.status))
    && value.faults.length === Math.min(value.limit, Math.max(0, value.total - value.offset))
    && new Set(value.faults.map(row => row.id)).size === value.faults.length;
}

export function validFaultDetail(value: unknown): value is FaultDetailPayload {
  if (!object(value) || !validSummary(value.fault)) return false;
  const fault = value.fault as unknown as Record<string, unknown>;
  return text(fault.error_text, 2000) && text(fault.attempted, 1000)
    && text(fault.recorded_agent_id, 128) && text(fault.thread_id, 128)
    && (fault.work_item_id === null || text(fault.work_item_id, 128))
    && text(fault.observed_as, 128) && text(fault.trace_summary, 4000)
    && typeof fault.trace_available === 'boolean'
    && Array.isArray(fault.clipped_fields)
    && fault.clipped_fields.every(field => typeof field === 'string' && CLIPPED_FIELDS.includes(field))
    && new Set(fault.clipped_fields).size === fault.clipped_fields.length;
}

export function useFaultReports(open: boolean): FaultReports {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [authPaused, setAuthPaused] = useState(false);
  const [paused, setPaused] = useState(false);
  const [detailPaused, setDetailPaused] = useState(false);
  const [resource, setResource] = useState<ResourceState<FaultList>>(() => idleResource(LIST));
  const [detail, setDetail] = useState<ResourceState<FaultDetailPayload>>(() => idleResource());
  const listState = useRef(resource);
  const detailState = useRef(detail);
  const selection = useRef(selectedId);
  const denied = useRef(false);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);

  const publishList = (next: ResourceState<FaultList>): void => {
    listState.current = next;
    setResource(next);
  };
  const publishDetail = (next: ResourceState<FaultDetailPayload>): void => {
    detailState.current = next;
    setDetail(next);
  };
  const clearSelection = (): void => {
    selection.current = null;
    detailController.current?.abort();
    setSelectedId(null);
    publishDetail(idleResource());
  };
  const deny = (): void => {
    // A denial from either read invalidates all diagnostic data immediately.
    denied.current = true;
    listController.current?.abort();
    clearSelection();
    publishList(failedResource(listState.current, 'unauthorized'));
    setAuthPaused(true);
    setPaused(true);
  };

  useEffect(() => {
    if (open) {
      denied.current = false;
      setAuthPaused(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || authPaused) return;
    const identity = `${LIST}?limit=${LIMIT}&offset=${offset}`;
    let active = true;
    let previous = loadingResource(listState.current, identity);
    let poll = freshPoll();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    publishList(previous);
    setPaused(false);

    const load = async (): Promise<void> => {
      if (!active || denied.current) return;
      controller = new AbortController();
      listController.current = controller;
      publishList({ ...previous, refreshing: previous.data !== null });
      const result = await requestResource(
        identity, previous,
        (value): value is FaultList => validFaultList(value) && value.limit === LIMIT && value.offset === offset,
        data => data.total === 0, controller.signal,
      );
      if (!active || controller.signal.aborted || denied.current || result === null) return;
      if (result.status === 'unauthorized') { deny(); return; }
      previous = result;
      publishList(result);
      if (current(result) && result.data) {
        if (!result.data.faults.some(row => row.id === selection.current)) clearSelection();
        if (offset > 0 && offset >= result.data.total) {
          setOffset(Math.max(0, Math.floor((result.data.total - 1) / LIMIT) * LIMIT));
          return;
        }
      }
      poll = nextResourcePoll(poll, result.status, Date.now());
      setPaused(poll.nextAt === null);
      if (poll.nextAt !== null) timer = setTimeout(() => { void load(); }, Math.max(0, poll.nextAt - Date.now()));
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [open, offset, revision, authPaused]);

  useEffect(() => {
    if (!open || !selectedId || authPaused) return;
    const id = selectedId;
    const identity = `${LIST}/${id}`;
    let active = true;
    let previous = loadingResource(detailState.current, identity);
    let poll = freshPoll();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    publishDetail(previous);
    setDetailPaused(false);
    const load = async (): Promise<void> => {
      if (!active || denied.current || selection.current !== id) return;
      controller = new AbortController();
      detailController.current = controller;
      publishDetail({ ...previous, refreshing: previous.data !== null });
      const result = await requestResource(
        identity, previous,
        (value): value is FaultDetailPayload => validFaultDetail(value) && value.fault.id === id,
        () => false, controller.signal,
      );
      if (!active || controller.signal.aborted || denied.current || selection.current !== id || result === null) return;
      if (result.status === 'unauthorized') { deny(); return; }
      previous = result;
      publishDetail(result);
      poll = nextResourcePoll(poll, result.status, Date.now());
      setDetailPaused(poll.nextAt === null);
      if (poll.nextAt !== null) timer = setTimeout(() => { void load(); }, Math.max(0, poll.nextAt - Date.now()));
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [open, selectedId, revision, authPaused]);

  const refresh = (): void => {
    if (!open) return;
    listController.current?.abort();
    detailController.current?.abort();
    denied.current = false;
    setAuthPaused(false);
    setRevision(value => value + 1);
  };
  const page = (next: number): void => {
    if (!open || authPaused || !current(listState.current)) return;
    listController.current?.abort();
    clearSelection();
    setOffset(next);
  };
  return {
    resource, detail, selectedId, paused, detailPaused, refresh,
    select: (id): void => {
      if (!open || denied.current || !listState.current.data?.faults.some(row => row.id === id)) return;
      const next = selection.current === id ? null : id;
      detailController.current?.abort();
      selection.current = next;
      setSelectedId(next);
      publishDetail(idleResource(next ? `${LIST}/${next}` : ''));
    },
    previousPage: (): void => page(Math.max(0, offset - LIMIT)),
    nextPage: (): void => {
      if (listState.current.data && offset + LIMIT < listState.current.data.total) page(offset + LIMIT);
    },
  };
}
