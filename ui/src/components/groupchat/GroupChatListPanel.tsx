/**
 * AD-919: Group Chats visibility surface (final Phase-1 AD).
 *
 * A focused, self-contained floating panel — surfaced by a TopNav toggle
 * exactly like NotebooksPanel — that lists every *group* chat the Captain
 * can see, including the ones agents started on their own (AD-918
 * `metadata.created_by_agent`). It badges the agent-created ones, shows
 * participant avatars, lets the Captain **Join** (AD-913 add_participant),
 * and **opens** the existing AD-917 chat on click.
 *
 * Decision A (build prompt): this is NOT the full LeftRail wire (that stays
 * forward marker AD-719b-parent-wire). LeftRail.tsx is untouched.
 * Decision B: GET /api/threads already returns metadata/participants/title —
 * frontend-only, no backend change.
 *
 * Per HXI Design Principle #3: inline SVG glyphs only (stroke-based, no
 * emoji). Active accent amber `#f0b060`; inactive `#666680`.
 * Per HXI Design Principle #9: agent-created chats the Captain has not yet
 * joined surface to the top (alert-driven ordering).
 */
import { useEffect, useState } from 'react';
import { useStore, type AD791aChatThreadView } from '../../store/useStore';
import type { Agent } from '../../store/types';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { UserPlus, Close } from '../icons/Glyphs';
import { listThreads, addParticipant } from '../sidebar/threadApi';

// Decision C: the Captain participant is the literal "captain" sentinel.
// Verified consistent across the stack (AD-914 fan-out crew gate excludes it,
// AD-917 GroupChatHeader strips it, era-4/5 Captain posts use author_id="captain").
// era-5 note: if a future AD introduces a canonical captain DID / is_captain()
// helper, this becomes a one-line swap to identity-based.
const CAPTAIN_PARTICIPANT_ID = 'captain';

const COLOR_ACTIVE = '#f0b060';
const COLOR_INACTIVE = '#666680';

type AgentMap = Map<string, Agent>;

// ── Pure helpers (module-scope, exported for the unit test) ──────────────

/** Crew participant ids: not the Captain sentinel, resolves as a crew agent. */
export function crewParticipantIds(thread: AD791aChatThreadView, agents: AgentMap): string[] {
  return thread.participants.filter(
    (p) => p !== CAPTAIN_PARTICIPANT_ID && agents.get(p)?.isCrew === true,
  );
}

/** AD-918 agent-initiated tag. */
export function isAgentCreated(thread: AD791aChatThreadView): boolean {
  return !!thread.metadata?.created_by_agent;
}

/** A group chat = agent-initiated OR >=2 crew participants (Decision C). */
export function isGroupChat(thread: AD791aChatThreadView, agents: AgentMap): boolean {
  return isAgentCreated(thread) || crewParticipantIds(thread, agents).length >= 2;
}

/** Whether the Captain sentinel is already a participant. */
export function captainJoined(thread: AD791aChatThreadView): boolean {
  return thread.participants.includes(CAPTAIN_PARTICIPANT_ID);
}

/** Host = first crew participant (the AD-917 chat is rendered in its panel). */
export function hostAgentId(thread: AD791aChatThreadView, agents: AgentMap): string | null {
  return crewParticipantIds(thread, agents)[0] ?? null;
}

// `department` is a cast on the base Agent (IntentSurface precedent), not a
// declared field — read it defensively for the avatar color.
function deptOf(agent: Agent | undefined): string {
  return (agent as (Agent & { department?: string }) | undefined)?.department ?? '';
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

export default function GroupChatListPanel() {
  const open = useStore((s) => s.groupChatListOpen);
  const close = useStore((s) => s.closeGroupChatList);
  const agents = useStore((s) => s.agents);
  const setThreadForAgent = useStore((s) => s.setThreadForAgent);
  const openAgentProfile = useStore((s) => s.openAgentProfile);

  const [threads, setThreads] = useState<AD791aChatThreadView[]>([]);

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

  if (!open) return null;

  // Group chats only, with un-joined agent-created chats floated to the top
  // (HXI #9), stable secondary order by recency.
  const groupChats = threads
    .filter((t) => isGroupChat(t, agents))
    .sort((a, b) => {
      const aAlert = isAgentCreated(a) && !captainJoined(a) ? 1 : 0;
      const bAlert = isAgentCreated(b) && !captainJoined(b) ? 1 : 0;
      if (aAlert !== bAlert) return bAlert - aAlert;
      return (b.last_active_at ?? 0) - (a.last_active_at ?? 0);
    });

  function handleOpen(thread: AD791aChatThreadView): void {
    // Open-on-click is per-host (Decision D): the AD-917 group chat is hosted
    // in the first crew participant's profile chat tab via threadIdByAgent,
    // NOT the store's top-level activeThreadId.
    const host = hostAgentId(thread, agents);
    if (!host) return; // Tier-2 honest-degrade: agents not hydrated -> no-op
    setThreadForAgent(host, thread.id);
    openAgentProfile(host);
  }

  async function handleJoin(thread: AD791aChatThreadView): Promise<void> {
    const updated = await addParticipant(thread.id, CAPTAIN_PARTICIPANT_ID);
    if (updated) {
      setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    }
    handleOpen(updated ?? thread);
  }

  return (
    <div
      data-testid="group-chat-list-panel"
      style={{
        position: 'fixed',
        top: 60,
        left: 60,
        width: 440,
        bottom: 60,
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
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '12px 14px',
          borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
        }}
      >
        <GlyphGroup color={COLOR_ACTIVE} />
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, color: COLOR_ACTIVE }}>
          GROUP CHATS
        </span>
        <div style={{ flex: 1 }} />
        <div
          data-testid="group-chat-close"
          onClick={close}
          style={{ cursor: 'pointer', color: COLOR_INACTIVE, display: 'inline-flex' }}
          aria-label="Close group chats"
        >
          <Close size={14} />
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {groupChats.length === 0 ? (
          <div
            data-testid="group-chat-empty"
            style={{ color: COLOR_INACTIVE, fontSize: 12, padding: 16, textAlign: 'center' }}
          >
            No group chats yet.
          </div>
        ) : (
          groupChats.map((thread) => {
            const crewIds = crewParticipantIds(thread, agents);
            const agentCreated = isAgentCreated(thread);
            const joined = captainJoined(thread);
            const creatorRaw = thread.metadata?.created_by_agent;
            const creatorId = typeof creatorRaw === 'string' ? creatorRaw : '';
            const creatorCallsign = agents.get(creatorId)?.callsign ?? creatorId;
            return (
              <div
                key={thread.id}
                data-testid={`group-chat-row-${thread.id}`}
                onClick={() => handleOpen(thread)}
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
                    {thread.title}
                  </span>
                  {agentCreated && (
                    <span
                      data-testid="group-chat-agent-badge"
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
                      data-testid={`group-chat-join-${thread.id}`}
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
                      data-testid={`group-chat-joined-${thread.id}`}
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
    </div>
  );
}
