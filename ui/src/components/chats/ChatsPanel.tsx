/**
 * AD-931: the unified CHATS surface — one Teams/Slack-style home listing BOTH
 * 1:1 and group conversations, with a prominent "+ New chat" picker.
 *
 * Repurposes the AD-919 `GroupChatListPanel` (a visibility + Join surface for
 * *group* chats only): it now uses the `isChat` filter (1:1 + group, excluding
 * AD-925 task rooms), renders a single-avatar row for 1:1s (no Join), keeps the
 * AD-919 multi-avatar + agent-created badge + Join treatment for groups, and
 * mounts `NewChatModal` for the create flow. The pure helpers moved to
 * `./chatFilters` so the panel and its test share one source of truth.
 *
 * Decision A (AD-931): repurpose + rename — `LeftRail.tsx` stays the forward
 * marker AD-719b-parent-wire (untouched). Decision B: GET /api/threads already
 * returns 1:1 default threads (`get_or_create_default_for_agent`), so this is
 * frontend-only, no backend change.
 *
 * Per HXI Design Principle #3: inline SVG glyphs only (stroke-based, no emoji);
 * amber `#f0b060`, dim `#666680`. Per HXI Design Principle #9: agent-created
 * chats the Captain has not yet joined float to the top (alert-driven ordering).
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import { useStore, type AD791aChatThreadView } from '../../store/useStore';
import type { Agent } from '../../store/types';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { UserPlus, Close } from '../icons/Glyphs';
import { listThreads, addParticipant, getThread } from '../sidebar/threadApi';
import { NewChatModal } from './NewChatModal';
import {
  CAPTAIN_PARTICIPANT_ID,
  COLOR_ACTIVE,
  COLOR_INACTIVE,
  chatDisplayName,
  crewParticipantIds,
  isAgentCreated,
  isChat,
  isGroupChat,
  captainJoined,
  hostAgentId,
} from './chatFilters';

// `department` is a cast on the base Agent (IntentSurface precedent), not a
// declared field — read it defensively for the avatar color.
function deptOf(agent: Agent | undefined): string {
  return (agent as (Agent & { department?: string }) | undefined)?.department ?? '';
}

// AD-1088: compact relative time for room rows (no date/time was visible).
function fmtAgo(tsSeconds: number | undefined): string {
  if (!tsSeconds) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - tsSeconds));
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 604800) return `${Math.floor(s / 86400)}d`;
  return new Date(tsSeconds * 1000).toLocaleDateString();
}

// Local inline header glyph (LeftRail GlyphAgents precedent — keeps Glyphs.tsx
// and its export-count test untouched). Stroke-based, no fill, no emoji.
function GlyphGroup({ color }: { color: string }) {
  return (
    <svg
      width="16" height="16" viewBox="0 0 16 16" fill="none" stroke={color}
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
    >
      <circle cx="6" cy="6" r="2.2" />
      <path d="M2 13c0-2.2 1.8-3.8 4-3.8s4 1.6 4 3.8" />
      <path d="M11 5.2a2 2 0 0 1 0 3.6" />
      <path d="M11.5 9.4c1.8 0 3 1.4 3 3.2" />
    </svg>
  );
}

export default function ChatsPanel() {
  const open = useStore((s) => s.chatsOpen);
  const close = useStore((s) => s.closeChats);
  const agents = useStore((s) => s.agents);
  // AD-937: open a chat row via the group override so a group never clobbers
  // the host's single threadIdByAgent 1:1 slot (the 1:1 stays reachable).
  const openGroupChatThread = useStore((s) => s.openGroupChatThread);
  // AD-938: hydrate the opened thread into chatThreads so GroupChatHeader /
  // MeetingView / the meetingActive selector (all read chatThreads.get(id))
  // resolve, and the thread-keyed transcript can load on open.
  const setChatThread = useStore((s) => s.setChatThread);
  // AD-971: the live chatThreads store. A participant added from the
  // GroupChatHeader writes the updated thread here (setChatThread) and bumps
  // last_active_at, but ChatsPanel keeps its own listThreads() snapshot. Reading
  // the store lets a row reflect a live add (the "chats form did not update" bug)
  // by preferring whichever version is fresher (see the merge in `chats`).
  const storeChatThreads = useStore((s) => s.chatThreads);
  // AD-940: the panel's drag position + setter (GamePanel / profilePanelPos
  // pattern). Lets the Captain move CHATS out of the way of an open chat window.
  const pos = useStore((s) => s.chatsPanelPos);
  const setPos = useStore((s) => s.setChatsPanelPos);

  const [threads, setThreads] = useState<AD791aChatThreadView[]>([]);
  const [newChatOpen, setNewChatOpen] = useState(false);
  // AD-1088: room list controls — search + sort (recent | name).
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<'recent' | 'name'>('recent');
  // AD-1090: status filter chips.
  const [filter, setFilter] = useState<'all' | 'needs' | 'rooms' | 'dms'>('all');

  // Fetch on open. The wrapper already honest-degrades to [] (Tier-2), so no
  // try/catch needed here. The `active` guard avoids a setState after unmount.
  useEffect(() => {
    if (!open) return;
    let active = true;
    void listThreads({ includeArchived: false }).then((list) => {
      if (active) setThreads(list);
    });
    return () => {
      active = false;
    };
  }, [open]);

  // AD-940: header drag (GamePanel.startDrag pattern) — capture the offset on
  // mousedown, track window mousemove, and tear the listeners down on mouseup.
  // The New-chat / Close controls stopPropagation so a click never starts a drag.
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
        y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [pos, setPos]);

  if (!open) return null;

  // 1:1 + group chats (task rooms excluded), with un-joined agent-created chats
  // floated to the top (HXI #9), stable secondary order by recency.
  // AD-971: prefer whichever thread version is fresher (greater last_active_at)
  // between the listThreads() snapshot and the live chatThreads store, so a
  // participant added from the open chat's header reflects in the row instead of
  // staying stale. Strict `>` keeps the canonical fetch winning on ties.
  const chats = threads
    .map((t) => {
      const s = storeChatThreads.get(t.id);
      return s && (s.last_active_at ?? 0) > (t.last_active_at ?? 0) ? s : t;
    })
    .filter((t) => isChat(t, agents))
    .filter((t) => {
      const q = query.trim().toLowerCase();
      return !q || chatDisplayName(t, agents).toLowerCase().includes(q);
    })
    .filter((t) => {
      if (filter === 'needs') return isAgentCreated(t) && !captainJoined(t);
      if (filter === 'rooms') return isGroupChat(t, agents);
      if (filter === 'dms') return !isGroupChat(t, agents);
      return true;
    })
    .sort((a, b) => {
      const aAlert = isAgentCreated(a) && !captainJoined(a) ? 1 : 0;
      const bAlert = isAgentCreated(b) && !captainJoined(b) ? 1 : 0;
      if (aAlert !== bAlert) return bAlert - aAlert;
      if (sort === 'name') return chatDisplayName(a, agents).localeCompare(chatDisplayName(b, agents));
      return (b.last_active_at ?? 0) - (a.last_active_at ?? 0);
    });

  async function handleOpen(thread: AD791aChatThreadView): Promise<void> {
    // AD-917/AD-937: open-on-click is per-host (the chat renders in the first
    // crew participant's profile chat tab). AD-937 addresses it via the group
    // override (activeProfileThreadId) instead of binding it into the host's
    // single threadIdByAgent 1:1 slot — so opening a group never makes the
    // host's 1:1 unreachable.
    // AD-971: re-fetch the thread's CURRENT persisted state before hydrating.
    // Participants added from the GroupChatHeader are persisted on the backend
    // but the ChatsPanel list snapshot is stale; opening with that stale object
    // (the old setChatThread(thread)) CLOBBERED the freshly-added participants in
    // the store, so they vanished on reopen. Fetching fresh (authoritative, and
    // robust across a full page reload) fixes the data loss. Tier-2: a !ok/
    // network failure falls back to the passed thread (prior behavior).
    const fresh = (await getThread(thread.id)) ?? thread;
    if (fresh !== thread) {
      setThreads((prev) => prev.map((t) => (t.id === fresh.id ? fresh : t)));
    }
    const host = hostAgentId(fresh, agents);
    if (!host) return; // Tier-2 honest-degrade: agents not hydrated -> no-op
    // AD-938: hydrate the thread first so its header/participants/meeting flag
    // resolve and ProfileChatTab can load the real transcript for this thread.
    setChatThread(fresh);
    openGroupChatThread(host, fresh.id);
  }

  async function handleJoin(thread: AD791aChatThreadView): Promise<void> {
    const updated = await addParticipant(thread.id, CAPTAIN_PARTICIPANT_ID);
    if (updated) {
      setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    }
    void handleOpen(updated ?? thread);
  }

  return (
    <div
      data-testid="chats-panel"
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: 440,
        // AD-940: drag replaces the old top/bottom:60 vertical pin. A maxHeight
        // keeps the list bounded (the flex:1 body still scrolls) while the panel
        // moves freely; 120 = the prior 60 top + 60 bottom margins.
        maxHeight: 'calc(100vh - 120px)',
        zIndex: 30,
        background: 'rgba(10, 10, 18, 0.95)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(240, 176, 96, 0.25)',
        borderRadius: 8,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#c0bab0',
      }}
    >
      {/* Header — AD-940 drag handle */}
      <div
        data-testid="chats-drag-handle"
        onMouseDown={onHeaderMouseDown}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '12px 14px',
          borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
          cursor: 'move',
          userSelect: 'none',
        }}
      >
        <GlyphGroup color={COLOR_ACTIVE} />
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, color: COLOR_ACTIVE }}>
          CREW COLLABORATION
        </span>
        <div style={{ flex: 1 }} />
        <button
          data-testid="new-chat-button"
          onClick={() => setNewChatOpen(true)}
          onMouseDown={(e) => e.stopPropagation()}
          aria-label="New chat"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            cursor: 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1,
            color: COLOR_ACTIVE,
            background: 'rgba(240, 176, 96, 0.08)',
            border: '1px solid rgba(240, 176, 96, 0.35)',
            borderRadius: 6,
            padding: '4px 10px',
          }}
        >
          <UserPlus size={12} />
          New chat
        </button>
        <div
          data-testid="chats-close"
          onClick={close}
          onMouseDown={(e) => e.stopPropagation()}
          style={{ cursor: 'pointer', color: COLOR_INACTIVE, display: 'inline-flex' }}
          aria-label="Close chats"
        >
          <Close size={14} />
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {/* AD-1088: search + sort controls */}
        <div style={{ display: 'flex', gap: 6, padding: '0 4px 8px', alignItems: 'center' }} onMouseDown={(e) => e.stopPropagation()}>
          <input
            data-testid="rooms-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search rooms..."
            style={{
              flex: 1, fontSize: 12, color: '#e0dcd4', background: 'rgba(0,0,0,0.3)',
              border: '1px solid rgba(240,176,96,0.2)', borderRadius: 6, padding: '5px 8px',
              outline: 'none', fontFamily: "'JetBrains Mono', monospace",
            }}
          />
          <button
            data-testid="rooms-sort"
            onClick={() => setSort((s) => (s === 'recent' ? 'name' : 'recent'))}
            title="Toggle sort"
            style={{
              fontSize: 10, color: COLOR_ACTIVE, background: 'rgba(240,176,96,0.08)',
              border: '1px solid rgba(240,176,96,0.3)', borderRadius: 6, padding: '5px 8px',
              cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            {sort === 'recent' ? 'Recent' : 'A-Z'}
          </button>
        </div>
        {/* AD-1090: status filter chips */}
        <div style={{ display: 'flex', gap: 6, padding: '0 4px 8px' }} onMouseDown={(e) => e.stopPropagation()}>
          {([['all', 'All'], ['needs', 'Needs you'], ['rooms', 'Rooms'], ['dms', 'DMs']] as const).map(([k, label]) => (
            <button
              key={k}
              data-testid={`rooms-filter-${k}`}
              onClick={() => setFilter(k)}
              style={{
                fontSize: 10, cursor: 'pointer', borderRadius: 12, padding: '3px 10px',
                color: filter === k ? '#0a0a12' : COLOR_ACTIVE,
                background: filter === k ? COLOR_ACTIVE : 'rgba(240,176,96,0.08)',
                border: '1px solid rgba(240,176,96,0.3)', whiteSpace: 'nowrap',
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {chats.length === 0 ? (
          <div
            data-testid="chats-empty"
            style={{ color: COLOR_INACTIVE, fontSize: 12, padding: 16, textAlign: 'center' }}
          >
            No chats yet.
          </div>
        ) : (
          chats.map((thread) => {
            const group = isGroupChat(thread, agents);
            const crewIds = crewParticipantIds(thread, agents);

            // ── 1:1 row — a single crew avatar + callsign, no Join, no badge.
            if (!group) {
              const soloId = crewIds[0];
              const solo = agents.get(soloId);
              return (
                <div
                  key={thread.id}
                  data-testid={`chat-row-${thread.id}`}
                  onClick={() => void handleOpen(thread)}
                  style={{
                    cursor: 'pointer',
                    padding: '10px 12px',
                    marginBottom: 6,
                    borderRadius: 6,
                    border: '1px solid rgba(240, 176, 96, 0.12)',
                    background: 'rgba(240, 176, 96, 0.04)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <AgentAvatarBadge
                    agentId={soloId}
                    callsign={solo?.callsign ?? '?'}
                    department={deptOf(solo)}
                    size={24}
                  />
                  <span style={{ fontSize: 13, fontWeight: 600, color: COLOR_ACTIVE }}>
                    {chatDisplayName(thread, agents)}
                  </span>
                  <div style={{ flex: 1 }} />
                  <span data-testid={`room-time-${thread.id}`} style={{ fontSize: 10, color: COLOR_INACTIVE }}>
                    {fmtAgo(thread.last_active_at)}
                  </span>
                </div>
              );
            }

            // ── Group row — AD-919 treatment: avatars, agent-created badge, Join.
            const agentCreated = isAgentCreated(thread);
            const joined = captainJoined(thread);
            const creatorRaw = thread.metadata?.created_by_agent;
            const creatorId = typeof creatorRaw === 'string' ? creatorRaw : '';
            const creatorCallsign = agents.get(creatorId)?.callsign ?? creatorId;
            return (
              <div
                key={thread.id}
                data-testid={`chat-row-${thread.id}`}
                onClick={() => void handleOpen(thread)}
                style={{
                  cursor: 'pointer',
                  padding: '10px 12px',
                  marginBottom: 6,
                  borderRadius: 6,
                  border: '1px solid rgba(240, 176, 96, 0.12)',
                  background: 'rgba(240, 176, 96, 0.04)',
                }}
              >
                {/* Title line + agent-created badge */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: COLOR_ACTIVE }}>
                    {chatDisplayName(thread, agents)}
                  </span>
                  {agentCreated && (
                    <span
                      data-testid="chat-agent-badge"
                      style={{
                        fontSize: 9,
                        fontWeight: 700,
                        letterSpacing: 0.5,
                        color: '#0a0a12',
                        background: COLOR_ACTIVE,
                        borderRadius: 8,
                        padding: '1px 8px',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      Started by {creatorCallsign}
                    </span>
                  )}
                  <div style={{ flex: 1 }} />
                  <span style={{ fontSize: 10, color: COLOR_INACTIVE }}>{fmtAgo(thread.last_active_at)}</span>
                </div>

                {/* Participant avatars + Join control */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {crewIds.map((id) => (
                    <AgentAvatarBadge
                      key={id}
                      agentId={id}
                      callsign={agents.get(id)?.callsign ?? '?'}
                      department={deptOf(agents.get(id))}
                      size={24}
                    />
                  ))}
                  <div style={{ flex: 1 }} />
                  {!joined ? (
                    <button
                      data-testid={`chat-join-${thread.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleJoin(thread);
                      }}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        cursor: 'pointer',
                        fontFamily: "'JetBrains Mono', monospace",
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: 1,
                        color: COLOR_ACTIVE,
                        background: 'rgba(240, 176, 96, 0.08)',
                        border: '1px solid rgba(240, 176, 96, 0.35)',
                        borderRadius: 6,
                        padding: '4px 10px',
                      }}
                    >
                      <UserPlus size={12} />
                      Join
                    </button>
                  ) : (
                    <span
                      data-testid={`chat-joined-${thread.id}`}
                      style={{ fontSize: 10, fontWeight: 700, letterSpacing: 1, color: COLOR_INACTIVE }}
                    >
                      Joined
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {newChatOpen && <NewChatModal onClose={() => setNewChatOpen(false)} />}
    </div>
  );
}
