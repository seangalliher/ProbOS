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

export function NotificationCard({ notification }: { notification: NotificationView }) {
  const borderColor = TYPE_COLORS[notification.notification_type] || '#5090d0';
  const isUnread = !notification.acknowledged;
  const acceptLabel = notification.suggested_action?.label;
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const pending = useRef<{ cancel: () => void } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

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
    current.hydrateCrewSession(session.task_id, session);
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
          {notification.detail.length > 120
            ? notification.detail.slice(0, 120) + '\u2026'
            : notification.detail}
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
