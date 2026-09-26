/* Bridge Notifications — notification card extracted from NotificationDropdown (AD-325) */

import { useEffect, useRef, useState, type MouseEvent } from 'react';

import type { NotificationView } from '../../store/types';
import { useStore } from '../../store/useStore';
import { fetchNotificationContext } from '../sidebar/threadApi';
import { hostAgentId } from '../chats/chatFilters';
import { DEPT_COLORS } from './BridgeCards';

export const TYPE_COLORS: Record<string, string> = {
  info: '#5090d0',
  action_required: '#f0b060',
  error: '#ff5555',
};

export function formatRelativeTime(timestamp: number): string {
  const sec = Math.max(0, Math.floor((Date.now() / 1000) - timestamp));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

// AD-1214: a delegated decision's notification may offer to pre-clear its exact class.
// The server wrote the marker; the card posts only its opaque offer id, never a scope.
const PRE_CLEAR_OFFER_RE = /^approval-pre-clear:([0-9a-f]{32})$/;
const PRE_CLEAR_ROUTE = '/api/decision-pre-clearances';

type PreClearState = { state: 'idle' | 'busy' | 'done' | 'undone' | 'failed'; text: string; recordId?: string };
type PreClearResult = { ok: true; id: string; expiresAt: number } | { ok: false; status: number | null };

function operatorHeaders(json: boolean): Record<string, string> {
  const token = new URLSearchParams(window.location.search).get('token');
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function preClearOffer(offerId: string): Promise<PreClearResult> {
  try {
    const response = await fetch(PRE_CLEAR_ROUTE, {
      method: 'POST', mode: 'same-origin', redirect: 'error', cache: 'no-store',
      headers: operatorHeaders(true), body: JSON.stringify({ offer_id: offerId }),
    });
    if (!response.ok || response.redirected) return { ok: false, status: response.status };
    const body: unknown = await response.json();
    const record: unknown = typeof body === 'object' && body !== null
      ? (body as { pre_clearance?: unknown }).pre_clearance : undefined;
    const { id, expires_at: expiresAt } = (typeof record === 'object' && record !== null ? record : {}) as {
      id?: unknown; expires_at?: unknown;
    };
    if (typeof id !== 'string' || typeof expiresAt !== 'number' || !Number.isFinite(expiresAt)) {
      return { ok: false, status: response.status };
    }
    return { ok: true, id, expiresAt };
  } catch {
    return { ok: false, status: null };
  }
}

async function undoPreClearance(recordId: string): Promise<{ ok: boolean; status: number | null }> {
  try {
    const response = await fetch(`${PRE_CLEAR_ROUTE}/${encodeURIComponent(recordId)}`, {
      method: 'DELETE', mode: 'same-origin', redirect: 'error', cache: 'no-store',
      headers: operatorHeaders(false),
    });
    return { ok: response.ok && !response.redirected, status: response.status };
  } catch {
    return { ok: false, status: null };
  }
}

function preClearFailure(status: number | null, creating: boolean): string {
  if (status === 401) return 'Pre-clear refused: authentication required.';
  if (creating && status === 404) return 'This offer has lapsed; the next decision of this class offers it again.';
  return status === null ? 'Pre-clear failed. Retry to try again.' : `Pre-clear failed (${status}). Retry to try again.`;
}

export function NotificationCard({ notification }: { notification: NotificationView }) {
  const borderColor = TYPE_COLORS[notification.notification_type] || '#5090d0';
  const isUnread = !notification.acknowledged;
  const acceptLabel = notification.suggested_action?.label;
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<{ cancel: () => void } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const offerId = PRE_CLEAR_OFFER_RE.exec(notification.action_url ?? '')?.[1] ?? null;
  const [preClear, setPreClear] = useState<PreClearState>({ state: 'idle', text: '' });

  useEffect(() => () => { pending.current?.cancel(); }, [notification.id]);

  async function handleOpen(): Promise<void> {
    pending.current?.cancel();
    const sourceCard = cardRef.current;
    const sourceVisible = (): boolean => {
      if (!sourceCard?.isConnected) return false;
      for (let element: HTMLElement | null = sourceCard; element; element = element.parentElement) {
        const style = getComputedStyle(element);
        if (element.hidden || element.inert || element.getAttribute('aria-hidden') === 'true'
          || style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') return false;
      }
      return true;
    };
    if (!sourceVisible()) return;
    const source = useStore.getState();
    const requestId = Symbol('notification-context');
    const generation = source.liveGeneration;
    const controller = new AbortController();
    let cancelled = false;
    let unsubscribe = () => {};
    let visibilityObserver: MutationObserver | null = null;
    const cancel = (): void => {
      if (cancelled) return;
      cancelled = true;
      unsubscribe();
      visibilityObserver?.disconnect();
      controller.abort();
      const current = useStore.getState();
      if (current.notificationNavigation?.requestId === requestId
        && !current.notificationNavigation.destination) {
        current.setNotificationNavigation(null);
      }
    };
    pending.current = { cancel };
    source.setNotificationNavigation({ requestId, generation, destination: null });
    setLoading(true);
    setMessage(null);
    const cancelFromSource = (): void => {
      cancel();
      setLoading(false);
      setMessage('Context opening cancelled. Retry to open it from this view.');
    };
    visibilityObserver = new MutationObserver(() => {
      if (!sourceVisible()) cancelFromSource();
    });
    for (let element: HTMLElement | null = sourceCard; element; element = element.parentElement) {
      visibilityObserver.observe(element, {
        attributes: true, attributeFilter: ['style', 'class', 'hidden', 'inert', 'aria-hidden'],
      });
    }
    unsubscribe = useStore.subscribe((current) => {
      if (current.notificationNavigation?.requestId !== requestId
        || current.liveGeneration !== generation
        || current.activeProfileAgent !== source.activeProfileAgent
        || current.activeProfileThreadId !== source.activeProfileThreadId
        || current.activeThreadId !== source.activeThreadId) {
        cancelFromSource();
      }
    });
    const issuedAt = useStore.getState().beginLiveRead();
    const outcome = await fetchNotificationContext(notification.id, controller.signal);
    if (cancelled) return;
    if (!sourceVisible()) {
      cancelFromSource();
      return;
    }
    unsubscribe();
    visibilityObserver.disconnect();
    pending.current = null;
    setLoading(false);
    if (outcome.kind !== 'success') {
      cancel();
      setMessage(outcome.status === 401
        ? 'Context unavailable: authentication required.'
        : outcome.status === 410
          ? 'Context unavailable: this room is archived.'
          : 'Context unavailable. Retry to check again.');
      return;
    }
    const { thread, session, delivery_revision: deliveryRevision } = outcome.context;
    const current = useStore.getState();
    const hostId = hostAgentId(thread, current.agents);
    const existingSession = current.crewSessionsByParent.get(session.task_id);
    if (!hostId || (existingSession && existingSession.thread_id !== thread.id)) {
      cancel();
      setMessage('Context unavailable: this room has no usable current host or matching session.');
      return;
    }
    current.setChatThread(thread);
    current.hydrateCrewSession(session.task_id, session, issuedAt);
    current.openGroupChatThread(hostId, thread.id);
    current.setNotificationNavigation({
      requestId, generation,
      destination: {
        hostId, threadId: thread.id, parentId: session.task_id,
        updated: Math.max(session.revision, existingSession?.revision ?? 0) > deliveryRevision,
      },
    });
    setMessage('Room context opened.');
  }

  async function handleAck() {
    try {
      await fetch(`/api/notifications/${notification.id}/ack`, { method: 'POST' });
    } catch { /* swallow */ }
  }

  async function handleAccept(e: MouseEvent) {
    e.stopPropagation();
    try {
      await fetch(`/api/notifications/${notification.id}/accept`, { method: 'POST' });
    } catch { /* swallow */ }
  }

  async function handlePreClear(e: MouseEvent) {
    e.stopPropagation();
    if (offerId === null) return;
    setPreClear({ state: 'busy', text: '' });
    const result = await preClearOffer(offerId);
    setPreClear(result.ok
      ? { state: 'done', text: `Pre-cleared until ${new Date(result.expiresAt * 1000).toLocaleString()}.`, recordId: result.id }
      : { state: 'failed', text: preClearFailure(result.status, true) });
  }

  async function handleUndoPreClear(e: MouseEvent) {
    e.stopPropagation();
    const recordId = preClear.recordId;
    if (recordId === undefined) return;
    setPreClear({ state: 'busy', text: '', recordId });
    const result = await undoPreClearance(recordId);
    setPreClear(result.ok
      ? { state: 'undone', text: 'Pre-clearance undone; this class notifies again.' }
      : { state: 'failed', text: preClearFailure(result.status, false), recordId });
  }

  return (
    <div
      ref={cardRef}
      style={{
        marginBottom: 6,
        padding: '6px 8px 6px 12px',
        borderRadius: 6,
        background: isUnread ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)',
        borderLeft: `3px solid ${borderColor}`,
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.08)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = isUnread ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)'; }}
    >
      <button
        type="button"
        onClick={handleOpen}
        disabled={loading}
        aria-label={`Open room context: ${notification.title}`}
        aria-busy={loading}
        style={{ display: 'block', width: '100%', border: 0, padding: 0, background: 'transparent', textAlign: 'left', font: 'inherit', cursor: loading ? 'wait' : 'pointer', overflowWrap: 'anywhere' }}
      >
      <div style={{
        fontSize: 11,
        fontWeight: isUnread ? 700 : 400,
        color: isUnread ? '#ddd' : '#999',
        marginBottom: 2,
      }}>
        {notification.title}
      </div>

      {notification.detail && (
        <div style={{ fontSize: 10, color: '#777', marginBottom: 3 }}>
          {offerId !== null || notification.detail.length <= 120
            ? notification.detail
            : notification.detail.slice(0, 120) + '\u2026'}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 9, color: '#666' }}>
        <span>{notification.agent_type}</span>
        {notification.department && (
          <>
            <span style={{ color: '#444' }}>{'\u00B7'}</span>
            <span style={{ color: DEPT_COLORS[notification.department?.toLowerCase()] || '#666', textTransform: 'capitalize' }}>
              {notification.department}
            </span>
          </>
        )}
        <span style={{ color: '#444' }}>{'\u00B7'}</span>
        <span>{formatRelativeTime(notification.created_at)}</span>
      </div>
      </button>
      {(loading || message) && (
        <div role="status" style={{ marginTop: 6, fontSize: 11, color: '#bbb', overflowWrap: 'anywhere' }}>
          {loading ? 'Opening room context...' : message}
        </div>
      )}
      {offerId !== null && preClear.recordId === undefined && preClear.state !== 'undone' && (
        <button
          type="button"
          data-testid="notification-pre-clear"
          onClick={handlePreClear}
          disabled={preClear.state === 'busy'}
          style={{
            marginTop: 6,
            marginRight: 8,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '3px 8px',
            borderRadius: 5,
            border: '1px solid #f0b060',
            background: 'rgba(240,176,96,0.12)',
            color: '#f0b060',
            fontSize: 10,
            fontWeight: 600,
            cursor: preClear.state === 'busy' ? 'wait' : 'pointer',
          }}
        >
          <svg width={11} height={11} viewBox="0 0 24 24" fill="none"
            stroke="#f0b060" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
            aria-hidden="true">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
            <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            <path d="M3 3l18 18" />
          </svg>
          Pre-clear
        </button>
      )}
      {preClear.recordId !== undefined && preClear.state !== 'undone' && (
        <button
          type="button"
          data-testid="notification-pre-clear-undo"
          onClick={handleUndoPreClear}
          disabled={preClear.state === 'busy'}
          style={{ marginTop: 6, marginRight: 8, color: '#bbb', background: 'transparent', border: '1px solid #666680', borderRadius: 4, cursor: preClear.state === 'busy' ? 'wait' : 'pointer' }}
        >
          Undo pre-clearance
        </button>
      )}
      {preClear.text && (
        <div role="status" data-testid="notification-pre-clear-status" style={{ marginTop: 6, fontSize: 11, color: '#bbb', overflowWrap: 'anywhere' }}>
          {preClear.text}
        </div>
      )}
      {isUnread && (
        <button type="button" onClick={handleAck} style={{ marginTop: 6, marginRight: 8, color: '#bbb', background: 'transparent', border: '1px solid #666680', borderRadius: 4, cursor: 'pointer' }}>
          Mark read
        </button>
      )}
      {message?.includes('unavailable') || message?.includes('cancelled') ? (
        <button type="button" onClick={handleOpen} disabled={loading} style={{ marginTop: 6, marginRight: 8, color: '#bbb', background: 'transparent', border: '1px solid #666680', borderRadius: 4, cursor: 'pointer' }}>
          Retry opening context
        </button>
      ) : null}
      {acceptLabel && (
        <button
          type="button"
          data-testid="notification-accept"
          onClick={handleAccept}
          style={{
            marginTop: 6,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '3px 8px',
            borderRadius: 5,
            border: '1px solid #f0b060',
            background: 'rgba(240,176,96,0.12)',
            color: '#f0b060',
            fontSize: 10,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          <svg width={11} height={11} viewBox="0 0 24 24" fill="none"
            stroke="#f0b060" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
            aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
          </svg>
          {acceptLabel}
        </button>
      )}    </div>
  );
}
