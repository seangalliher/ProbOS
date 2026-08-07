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

/* ── BF-724: UA-chrome neutraliser for the semantic controls ──
 *
 * The collapsible header, its expand affordance and the approval row were
 * clickable `div`/`span`s: no tab stop, no key handler, no role. The only route
 * to a pending approval could not be operated from a keyboard. They are now
 * real `<button>`s — but a `<button>` arrives with UA chrome a `<div>` never
 * had: a `buttonface` background, an outset border, `1px 6px` padding, centred
 * text, and its OWN font (buttons do not inherit `font-family`, so the panel's
 * JetBrains Mono would silently become Arial inside every converted control).
 *
 * Resetting it here keeps the rendered output identical to the divs these
 * replaced. This change is semantics and focus, never appearance — the amber /
 * blue / violet trust spectrum and the stroke-SVG glyphs are untouched (HXI #3).
 *
 * `outline` is deliberately NOT set inline: an inline declaration outranks the
 * stylesheet, which would make the amber focus ring below unreachable. */
const BARE_BUTTON: React.CSSProperties = {
  appearance: 'none',
  WebkitAppearance: 'none',
  background: 'none',
  border: 'none',
  borderRadius: 0,
  margin: 0,
  padding: 0,
  fontFamily: 'inherit',
  fontSize: 'inherit',
  fontWeight: 'inherit',
  fontStyle: 'inherit',
  lineHeight: 'inherit',
  color: 'inherit',
  textAlign: 'left',
  // A `display:flex` button must not inherit the UA's centring behaviour; the
  // divs these replaced laid their children out from the start edge.
  alignItems: 'stretch',
  justifyContent: 'flex-start',
};

/* HXI #3: the default UA focus ring breaks the visual language. Focus is drawn
 * with the same amber the panel already uses for an active/alerting state.
 * `:focus-visible` only, so a pointer click does not paint a ring. Both rules
 * carry equal specificity, so the ring rule must come second. */
const FOCUS_RING_CSS = `
[data-hxi-focus]:focus{outline:none}
[data-hxi-focus]:focus-visible{outline:1px solid #f0b060;outline-offset:-1px}
`;

/* ── Collapsible Section ── */
function BridgeSection({
  title, count, defaultOpen, accentColor, onExpand, stationId, alerting, children,
}: {
  title: string; count: number; defaultOpen: boolean;
  accentColor?: string; onExpand?: () => void;
  stationId?: StationId;
  /** BF-716: this section is waiting on the Captain. Pulses its edge (HXI #4:
   *  motion encodes state, never decoration). Only the approvals feed sets it —
   *  if everything pulses, nothing does. */
  alerting?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const color = accentColor || '#888';

  return (
    <div>
      {alerting && (
        <style>{`@keyframes bridgeApprovalAttention{0%,100%{border-left-color:rgba(240,176,96,0.35)}50%{border-left-color:rgba(240,176,96,1)}}`}</style>
      )}
      <div
        data-station={stationId}
        data-alerting={alerting ? 'true' : undefined}
        style={{
          // BF-724: the vertical padding moved onto the two buttons so the full
          // row height stays clickable now that the row itself is inert. The
          // rendered box is unchanged: 8px + content + 8px, inset 12px.
          padding: '0 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          // AD-943: the command-station layer carries its accent edge; the
          // activity-feed sections (no stationId) do not — a glanceable
          // distinction (HXI #6), reusing the accent token (no new color).
          // BF-716: an alerting feed section is the one exception — a blocked
          // agent earns an edge, and that edge pulses.
          borderLeft: stationId
            ? `2px solid ${color}`
            : alerting ? `2px solid ${color}` : undefined,
          animation: alerting
            ? 'bridgeApprovalAttention 2s ease-in-out infinite'
            : undefined,
        }}
      >
        {/* BF-724: the disclosure control. Two SIBLING buttons, not a nested
            pair — a button inside a button is invalid interactive content and
            would reintroduce the very unreachability this fixes. `flex: 1`
            keeps the whole row up to the expand affordance clickable, exactly
            as the div it replaced. Its accessible name is the visible label
            (WCAG 2.5.3), so no aria-label competes with it. */}
        <button
          type="button"
          data-hxi-focus=""
          aria-expanded={open}
          onClick={() => setOpen(o => !o)}
          style={{
            ...BARE_BUTTON,
            flex: 1,
            minWidth: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '8px 0',
            cursor: 'pointer',
          }}
        >
          <span style={{ color: '#666' }}>{open ? <ChevronDown size={8} /> : <ChevronRight size={8} />}</span>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
            textTransform: 'uppercase' as const, color,
          }}>
            {title} ({count})
          </span>
        </button>
        {onExpand && (
          <button
            type="button"
            data-hxi-focus=""
            onClick={onExpand}
            /* Glyph-only, so content gives it no accessible name. `title` alone
               would leave it to the UA's last-resort fallback; the label is
               explicit and section-scoped, and the title stays as the tooltip. */
            aria-label={`Expand ${title} to full view`}
            style={{
              ...BARE_BUTTON,
              marginLeft: 'auto', fontSize: 10, color: '#666',
              cursor: 'pointer', padding: '8px 4px',
              display: 'flex', alignItems: 'center',
            }}
            title="Expand to full view"
          >
            <Expand size={10} />
          </button>
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
  /* BF-716: the ASK is the headline, not the agent id.
   *
   * AD-1201 shipped this row rendering `kind` + `agent_id`, so the Captain saw
   * "CONTINUE counselor_counselor_0_67c601cb" — an opaque identifier — while
   * `target` sat unused one property away. BF-709 had just done the work to
   * make `target` the Captain's raw request instead of the assembled prompt;
   * this row discarded that entirely. The human-readable text is the reason a
   * card is glanceable, so it leads. */
  const ask = (approval.target || '').trim();
  const label = ask || approval.agent_id || 'unknown request';
  return (
    <button
      type="button"
      data-hxi-focus=""
      data-testid="bridge-approval-row"
      data-queue={approval.queue}
      onClick={onOpen}
      /* BF-724: the row's own content reads as "continue · 7m ago · <the ask>",
         which is a serviceable name but buries the action. This says what
         activating it does, and still carries the ask so two pending rows are
         distinguishable by name alone. */
      aria-label={`Open approval request: ${label}`}
      style={{
        ...BARE_BUTTON,
        display: 'flex',
        flexDirection: 'column' as const,
        gap: 2,
        // A block-level `div` filled its parent; `width: 100%` restates that
        // for the button. There is no global `box-sizing: border-box` in this
        // app, so without the override the 6px side padding would be ADDED to
        // the 100% and the row would render 12px wider than the div it
        // replaced — the markup change dragging the layout with it.
        width: '100%',
        boxSizing: 'border-box' as const,
        padding: '5px 6px',
        cursor: 'pointer',
        userSelect: 'none' as const,
        borderRadius: 4,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span
          data-testid="bridge-approval-kind"
          style={{
            fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
            textTransform: 'uppercase' as const, color: '#f0b060', flexShrink: 0,
          }}
        >
          {approval.kind || approval.queue}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: '#666680', flexShrink: 0 }}>
          {timeAgo(approval.created_at)}
        </span>
      </div>
      <span
        data-testid="bridge-approval-ask"
        style={{
          fontSize: 11, color: '#c8cee0', lineHeight: 1.35,
          display: '-webkit-box', WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical' as const, overflow: 'hidden',
        }}
      >
        {ask || approval.agent_id || 'unknown request'}
      </span>
    </button>
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
      {/* BF-724: one focus-ring rule for every control this panel made
          keyboard-reachable. Mounted here rather than per-section so it is
          declared once for the whole panel. */}
      <style>{FOCUS_RING_CSS}</style>
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
        {/* ── APPROVALS — ABOVE the stations, deliberately (BF-716, HXI #9).
            AD-1201 put this at the top of the activity feed, which renders
            AFTER every command station. Measured on the reference vessel: a
            blocked agent sat below PERSONNEL (0), SCIENCE (0), OPERATIONS (0),
            ENGINEERING (0) and COMMAND (0) — outranked by five sections
            containing nothing. HXI #9 is explicit that pending decisions rise
            to the top and the layout reshapes around what matters right now,
            so an agent waiting on the Captain outranks a station at rest.

            It still carries no stationId: it is a feed item that rises and
            recedes, not a command station. `alerting` gives it the one pulsing
            edge in the panel — the exception that makes the rule readable. ── */}
        {pendingApprovals.length > 0 && (
          <BridgeSection
            title="Approvals"
            count={pendingApprovals.length}
            defaultOpen={true}
            accentColor="#f0b060"
            alerting={true}
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
            and recede with system state; they carry no stationId. Approvals
            render ABOVE the stations (BF-716); everything below is ordinary
            feed. ── */}
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
