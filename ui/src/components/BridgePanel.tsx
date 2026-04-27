/* Bridge Panel — unified command console (AD-325) */

import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import { ChevronDown, ChevronRight, Expand, Close } from './icons/Glyphs';
import { TaskCard } from './bridge/BridgeCards';
import { NotificationCard } from './bridge/BridgeNotifications';
import { BridgeKanban } from './bridge/BridgeKanban';
import { BridgeSystem, BridgeThreads, BridgeShutdown } from './bridge/BridgeSystem';
import { BridgeCommunications } from './bridge/BridgeCommunications';

/* ── Collapsible Section ── */
function BridgeSection({
  title, count, defaultOpen, accentColor, onExpand, children,
}: {
  title: string; count: number; defaultOpen: boolean;
  accentColor?: string; onExpand?: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const color = accentColor || '#888';

  return (
    <div>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <span style={{ color: '#666' }}>{open ? <ChevronDown size={8} /> : <ChevronRight size={8} />}</span>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
          textTransform: 'uppercase' as const, color,
        }}>
          {title} ({count})
        </span>
        {onExpand && (
          <span
            onClick={(e) => { e.stopPropagation(); onExpand(); }}
            style={{
              marginLeft: 'auto', fontSize: 10, color: '#666',
              cursor: 'pointer', padding: '0 4px',
            }}
            title="Expand to full view"
          >
            <Expand size={10} />
          </span>
        )}
      </div>
      {open && <div style={{ padding: '4px 8px 8px' }}>{children}</div>}
    </div>
  );
}

export function BridgePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const agentTasks = useStore(s => s.agentTasks);
  const notifications = useStore(s => s.notifications);
  const missionControlTasks = useStore(s => s.missionControlTasks);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);

  useEffect(() => { refreshDms(); }, [refreshDms]);

  // ATTENTION: requires_action tasks + action_required notifications
  const attentionTasks = (agentTasks ?? []).filter(
    t => t.requires_action && (t.status === 'working' || t.status === 'review')
  );
  const attentionNotifs = (notifications ?? []).filter(
    n => n.notification_type === 'action_required' && !n.acknowledged
  );
  const attentionCount = attentionTasks.length + attentionNotifs.length;

  // ACTIVE: working tasks not in attention
  const attentionTaskIds = new Set(attentionTasks.map(t => t.id));
  const activeTasks = (agentTasks ?? []).filter(
    t => t.status === 'working' && !attentionTaskIds.has(t.id)
  );

  // NOTIFICATIONS: everything not in attention
  const infoNotifs = (notifications ?? []).filter(
    n => !(n.notification_type === 'action_required' && !n.acknowledged)
  );
  const unreadNotifs = infoNotifs.filter(n => !n.acknowledged).length;

  // KANBAN
  const kanbanTasks = missionControlTasks ?? [];

  // RECENT
  const recentTasks = (agentTasks ?? [])
    .filter(t => t.status === 'done' || t.status === 'failed')
    .sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0))
    .slice(0, 10);

  // Notification ack all
  async function handleAckAll() {
    try {
      await fetch('/api/notifications/ack-all', { method: 'POST' });
    } catch { /* swallow */ }
  }

  const allUnread = (notifications ?? []).filter(n => !n.acknowledged).length;

  return (
    <div style={{
      position: 'fixed',
      top: 0, right: 0, bottom: 0,
      width: 380,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(100%)',
      transition: 'transform 0.25s ease-out',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: "'JetBrains Mono', monospace",
      pointerEvents: open ? 'auto' : 'none',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 12px 10px',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 2,
          textTransform: 'uppercase' as const, color: '#f0b060',
        }}>
          Bridge
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {allUnread > 0 && (
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
            <Close size={14} />
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {/* SYSTEM — services only */}
        <BridgeSection title="System" count={0} defaultOpen={false} accentColor="#70a0d0"
          onExpand={() => useStore.setState({ mainViewer: 'system' })}>
          <BridgeSystem />
        </BridgeSection>

        {/* COMMUNICATIONS — threads + DMs */}
        <BridgeSection title="Communications" count={dmChannels.length} defaultOpen={false} accentColor="#b080d0"
          onExpand={() => useStore.setState({ wardRoomOpen: true, wardRoomView: 'channels' })}>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>THREADS</div>
            <BridgeThreads />
          </div>
          <BridgeCommunications />
        </BridgeSection>

        {/* ATTENTION */}
        {attentionCount > 0 && (
          <BridgeSection title="Attention" count={attentionCount} defaultOpen={true} accentColor="#f0b060">
            {attentionTasks.map(t => <TaskCard key={t.id} task={t} />)}
            {attentionNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* ACTIVE */}
        {activeTasks.length > 0 && (
          <BridgeSection title="Active" count={activeTasks.length} defaultOpen={true} accentColor="#50b0a0">
            {activeTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* NOTIFICATIONS */}
        {infoNotifs.length > 0 && (
          <BridgeSection
            title="Notifications"
            count={infoNotifs.length}
            defaultOpen={unreadNotifs > 0}
            accentColor="#5090d0"
          >
            {infoNotifs.map(n => <NotificationCard key={n.id} notification={n} />)}
          </BridgeSection>
        )}

        {/* WORK BOARD — always visible */}
        <BridgeSection
          title="Work Board"
          count={kanbanTasks.length}
          defaultOpen={false}
          accentColor="#d0a030"
          onExpand={() => useStore.setState({ mainViewer: 'work' })}
        >
          <BridgeKanban />
        </BridgeSection>

        {/* RECENT */}
        {recentTasks.length > 0 && (
          <BridgeSection title="Recent" count={recentTasks.length} defaultOpen={false} accentColor="#666">
            {recentTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* Empty state */}
        {attentionCount === 0 && activeTasks.length === 0 && infoNotifs.length === 0 &&
         kanbanTasks.length === 0 && recentTasks.length === 0 && (
          <div style={{
            fontSize: 10, color: '#555', fontStyle: 'italic',
            textAlign: 'center', padding: '32px 0',
          }}>
            No activity
          </div>
        )}
      </div>

      {/* SHUTDOWN — fixed at bottom, outside scroll area */}
      <div style={{
        padding: '8px 12px',
        borderTop: '1px solid rgba(255,255,255,0.08)',
        background: 'rgba(10, 10, 18, 0.95)',
      }}>
        <BridgeShutdown />
      </div>
    </div>
  );
}
