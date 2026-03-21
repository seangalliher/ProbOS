/* Notification Dropdown — bell-triggered panel for agent notifications (AD-323) */

import { useStore } from '../store/useStore';
import type { NotificationView } from '../store/types';

const TYPE_COLORS: Record<string, string> = {
  info: '#5090d0',
  action_required: '#f0b060',
  error: '#ff5555',
};

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

function formatRelativeTime(timestamp: number): string {
  const sec = Math.max(0, Math.floor((Date.now() / 1000) - timestamp));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function NotificationCard({ notification }: { notification: NotificationView }) {
  const borderColor = TYPE_COLORS[notification.notification_type] || '#5090d0';
  const isUnread = !notification.acknowledged;

  async function handleAck() {
    try {
      await fetch(`/api/notifications/${notification.id}/ack`, { method: 'POST' });
    } catch { /* swallow */ }
  }

  return (
    <div
      onClick={handleAck}
      style={{
        marginBottom: 6,
        padding: '6px 8px 6px 12px',
        borderRadius: 6,
        background: isUnread ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)',
        borderLeft: `3px solid ${borderColor}`,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.08)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = isUnread ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)'; }}
    >
      {/* Title */}
      <div style={{
        fontSize: 11,
        fontWeight: isUnread ? 700 : 400,
        color: isUnread ? '#ddd' : '#999',
        marginBottom: 2,
      }}>
        {notification.title}
      </div>

      {/* Detail */}
      {notification.detail && (
        <div style={{ fontSize: 10, color: '#777', marginBottom: 3 }}>
          {notification.detail.length > 120
            ? notification.detail.slice(0, 120) + '\u2026'
            : notification.detail}
        </div>
      )}

      {/* Tags + time */}
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
    </div>
  );
}

export function NotificationDropdown({ open, onClose }: { open: boolean; onClose: () => void }) {
  const notifications = useStore((s) => s.notifications);
  const items = notifications ?? [];
  const unreadCount = items.filter(n => !n.acknowledged).length;

  async function handleAckAll() {
    try {
      await fetch('/api/notifications/ack-all', { method: 'POST' });
    } catch { /* swallow */ }
  }

  if (!open) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 40,
      right: 210,
      width: 320,
      maxHeight: 400,
      zIndex: 30,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 8,
      display: 'flex',
      flexDirection: 'column' as const,
      fontFamily: "'JetBrains Mono', monospace",
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 12px 8px',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 2,
          textTransform: 'uppercase' as const, color: '#f0b060',
        }}>
          Notifications
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {unreadCount > 0 && (
            <button
              onClick={handleAckAll}
              style={{
                background: 'none', border: 'none', color: '#888',
                fontSize: 9, cursor: 'pointer', padding: 0,
                textDecoration: 'underline',
              }}
            >
              Mark all read
            </button>
          )}
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: '#888',
              fontSize: 16, cursor: 'pointer', padding: '0 4px',
              lineHeight: 1,
            }}
          >
            {'\u00D7'}
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '6px 8px' }}>
        {items.length === 0 ? (
          <div style={{
            fontSize: 10, color: '#555', fontStyle: 'italic',
            textAlign: 'center', padding: '24px 0',
          }}>
            No notifications
          </div>
        ) : (
          items.map(n => <NotificationCard key={n.id} notification={n} />)
        )}
      </div>
    </div>
  );
}
