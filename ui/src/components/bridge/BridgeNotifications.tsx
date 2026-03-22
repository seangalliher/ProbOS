/* Bridge Notifications — notification card extracted from NotificationDropdown (AD-325) */

import type { NotificationView } from '../../store/types';
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
    </div>
  );
}
