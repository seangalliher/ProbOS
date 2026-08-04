/* Bridge Panel — unified command console (AD-325) */

import { useState, useEffect } from 'react';
import { useStore, type PendingApproval } from '../store/useStore';
import { ChevronDown, ChevronRight, Expand, Close } from './icons/Glyphs';
import { TaskCard } from './bridge/BridgeCards';
import { NotificationCard } from './bridge/BridgeNotifications';
import { BridgeShutdown } from './bridge/BridgeSystem';
import { buildBridgeStations, isPopulated, type StationId, type StationAction } from './bridge/stations';
import { timeAgo } from './wardroom/timeAgo';

/* AD-1201: the ONE approvals poll. The Bridge APPROVALS section, the approvals
 * centre and the BRIDGE badge all read the same store slice this fills, so they
 * cannot disagree about the count. 10s matches the established panel-refresh
 * cadence (CrewRosterPanel.tsx, bridge/FullSystem.tsx, bridge/BridgeSystem.tsx).
 * BridgePanel owns it because it is mounted for the whole session (IntentSurface
 * renders it unconditionally and slides it off-screen when closed). */
const APPROVALS_POLL_INTERVAL_MS = 10000;

/* ── Collapsible Section ── */
function BridgeSection({
  title, count, defaultOpen, accentColor, onExpand, stationId, children,
}: {
  title: string; count: number; defaultOpen: boolean;
  accentColor?: string; onExpand?: () => void;
  stationId?: StationId;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const color = accentColor || '#888';

  return (
    <div>
      <div
        data-station={stationId}
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          // AD-943: the command-station layer carries its accent edge; the
          // activity-feed sections (no stationId) do not — a glanceable
          // distinction (HXI #6), reusing the accent token (no new color).
          borderLeft: stationId ? `2px solid ${color}` : undefined,
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

/* ── Station launch row (AD-944) — a discrete "open destination" item migrated
   from the retired top toolbar. Stroke-SVG glyph, uppercase mono, optional amber
   unread pill; NO emoji (HXI #3). data-testid mirrors the old toolbar testIds so
   existing specs keep resolving. ── */
function StationActionRow({ action, accent }: { action: StationAction; accent: string }) {
  return (
    <div
      data-testid={action.id}
      onClick={action.onInvoke}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 6px',
        cursor: 'pointer',
        userSelect: 'none' as const,
        borderRadius: 4,
      }}
    >
      <span style={{ color: '#666' }}><ChevronRight size={8} /></span>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
        textTransform: 'uppercase' as const, color: accent,
      }}>
        {action.label}
      </span>
      {typeof action.count === 'number' && action.count > 0 && (
        <span style={{
          marginLeft: 'auto',
          background: '#f0b060', color: '#0a0a12',
          borderRadius: 8, padding: '1px 6px', fontSize: 9, fontWeight: 700,
        }}>{action.count}</span>
      )}
    </div>
  );
}

/* ── AD-1201: compact pending-approval summary row. Who asked, what kind, how
   long ago — the full request detail and the approve/deny controls live in the
   approvals centre, not in the feed. BF-709 (#1115): `target` is currently the
   whole assembled prompt for `continue` requests; that is its own issue and is
   deliberately NOT truncated here, because a truncated assembled prompt is still
   noise and hiding it would make #1115 harder to see. ── */
function ApprovalRow({ approval, onOpen }: { approval: PendingApproval; onOpen: () => void }) {
  return (
    <div
      data-testid="bridge-approval-row"
      data-queue={approval.queue}
      onClick={onOpen}
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 6,
        padding: '5px 6px',
        cursor: 'pointer',
        userSelect: 'none' as const,
        borderRadius: 4,
      }}
    >
      <span style={{
        fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
        textTransform: 'uppercase' as const, color: '#f0b060',
      }}>
        {approval.kind || approval.queue}
      </span>
      <span style={{
        fontSize: 10, color: '#9098b0',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
      }}>
        {approval.agent_id || 'unknown agent'}
      </span>
      <span style={{ marginLeft: 'auto', fontSize: 9, color: '#666680', flexShrink: 0 }}>
        {timeAgo(approval.created_at)}
      </span>
    </div>
  );
}

export function BridgePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const agentTasks = useStore(s => s.agentTasks);
  const notifications = useStore(s => s.notifications);
  const missionControlTasks = useStore(s => s.missionControlTasks);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);
  const wardRoomUnread = useStore(s => s.wardRoomUnread);
  const pendingApprovals = useStore(s => s.pendingApprovals);
  const refreshApprovals = useStore(s => s.refreshPendingApprovals);
  const totalUnread = Object.values(wardRoomUnread ?? {}).reduce((sum, n) => sum + n, 0);

  useEffect(() => { refreshDms(); }, [refreshDms]);

  // AD-1201: the single approvals poll. Cleared on unmount — no leaked timer.
  useEffect(() => {
    refreshApprovals();
    const timer = window.setInterval(() => { refreshApprovals(); }, APPROVALS_POLL_INTERVAL_MS);
    return () => { window.clearInterval(timer); };
  }, [refreshApprovals]);

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
        {/* ── COMMAND STATIONS — the Ship's-Computer command layer (AD-943).
            Driven by the typed registry; the 3 existing sections migrate here.
            personnel/science/command are modelled placeholders (no body yet),
            hidden by isPopulated until AD-944/945/946 fill them. ── */}
        {buildBridgeStations({
          dmChannelCount: dmChannels.length,
          kanbanCount: kanbanTasks.length,
          totalUnread,
        })
          .filter(isPopulated)
          .map(st => (
            <BridgeSection
              key={st.id}
              stationId={st.id}
              title={st.title}
              count={st.count ?? 0}
              defaultOpen={st.defaultOpen}
              accentColor={st.accent}
              onExpand={st.onExpand}
            >
              {st.actions.map(a => (
                <StationActionRow key={a.id} action={a} accent={st.accent} />
              ))}
              {st.body?.()}
              {st.config.map(c => (
                <div key={c.id}>{c.render()}</div>
              ))}
            </BridgeSection>
          ))}

        {/* ── ACTIVITY FEED — alert-driven, NOT stations (HXI #9). These rise
            and recede with system state; they carry no stationId. ── */}
        {/* APPROVALS (AD-1201) — an agent is blocked waiting on the Captain.
            Deliberately no stationId: this is a feed item that rises and
            recedes, not a command station. Expand opens the approvals centre,
            where the approve/deny controls live. */}
        {pendingApprovals.length > 0 && (
          <BridgeSection
            title="Approvals"
            count={pendingApprovals.length}
            defaultOpen={true}
            accentColor="#f0b060"
            onExpand={() => useStore.setState({ approvalsCenterOpen: true })}
          >
            {pendingApprovals.map(a => (
              <ApprovalRow
                key={`${a.queue}:${a.id}`}
                approval={a}
                onOpen={() => useStore.setState({ approvalsCenterOpen: true })}
              />
            ))}
          </BridgeSection>
        )}

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

        {/* RECENT */}
        {recentTasks.length > 0 && (
          <BridgeSection title="Recent" count={recentTasks.length} defaultOpen={false} accentColor="#666">
            {recentTasks.map(t => <TaskCard key={t.id} task={t} />)}
          </BridgeSection>
        )}

        {/* Empty state — the activity feed is empty (stations always render). */}
        {pendingApprovals.length === 0 && attentionCount === 0 && activeTasks.length === 0 &&
         infoNotifs.length === 0 && recentTasks.length === 0 && (
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
