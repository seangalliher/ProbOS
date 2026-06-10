// AD-917: in-chat group controls — editable room title (rename), a participant
// avatar strip, and an add-participant @-picker. Drives the AD-913/914 thread
// endpoints via threadApi; renders nothing until a thread exists. Adding the
// 2nd crew participant is what turns a 1:1 into a group (see ProfileChatTab's
// send-routing branch). HXI #3 — inline-SVG glyphs only (UserPlus / Close),
// amber/dim palette, no emoji.
import { useState } from 'react';
import { useStore } from '../../store/useStore';
import type { Agent } from '../../store/types';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { UserPlus, Close } from '../icons/Glyphs';
import { patchThread, addParticipant, removeParticipant, setMeetingActive, appendMessage } from '../sidebar/threadApi';
import { AddParticipantPopover } from './AddParticipantPopover';
import { chatDisplayName } from '../chats/chatFilters';
// AD-937: on a 1:1 (<=1 crew) the add control opens the seeded picker instead
// of the inline mutate path, so converting a 1:1 mints a SEPARATE group thread.
import { NewChatModal } from '../chats/NewChatModal';

interface GroupChatHeaderProps {
  threadId: string;
}

export function GroupChatHeader({ threadId }: GroupChatHeaderProps) {
  const thread = useStore((s) => s.chatThreads.get(threadId));
  const agents = useStore((s) => s.agents);
  const setChatThread = useStore((s) => s.setChatThread);
  // AD-949: call-scoped audio mute (default ON). The in-call toggle below flips
  // it; useMeetingVoice gates group/meeting speech on this flag.
  const callAudioEnabled = useStore((s) => s.callAudioEnabled);
  const setCallAudioEnabled = useStore((s) => s.setCallAudioEnabled);

  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  // AD-937: seeded-picker overlay for the 1:1 -> group non-destructive convert.
  const [convertOpen, setConvertOpen] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  // Empty/cold-start: no thread yet -> render nothing (HXI: the control bar
  // appears only once a thread exists).
  if (!thread) return null;

  const participants = thread.participants ?? [];
  // Resolve each id to its agent, excluding the Captain and any non-crew /
  // unknown id (only crew get an avatar in the strip).
  const crewParticipants = participants
    .filter((id) => id !== 'captain')
    .map((id) => ({ id, agent: agents.get(id) }))
    .filter((p): p is { id: string; agent: Agent } => !!p.agent && p.agent.isCrew);

  // AD-920: meeting-mode flag (persisted on the shared thread). The toggle
  // flips metadata.meeting_active via the scoped set_meeting_active writer.
  const meetingActive = !!(thread.metadata as Record<string, unknown> | undefined)?.meeting_active;

  async function commitTitle() {
    const next = titleDraft.trim();
    setEditing(false);
    // No-op on an empty or unchanged title (no PATCH). Read the freshest
    // title from the store snapshot (avoids closure staleness).
    const currentTitle = useStore.getState().chatThreads.get(threadId)?.title ?? '';
    if (!next || next === currentTitle) return;
    // ``title_locked`` routes through set_title(lock=True) so first-turn
    // auto-naming skips this thread after a manual rename.
    const updated = await patchThread(threadId, { title: next, title_locked: true });
    if (updated) setChatThread(updated);
  }

  async function handleAdd(agentId: string) {
    const updated = await addParticipant(threadId, agentId);
    if (updated) setChatThread(updated);
    setPickerOpen(false);
  }

  async function handleRemove(agentId: string) {
    const updated = await removeParticipant(threadId, agentId);
    if (updated) setChatThread(updated);
  }

  // AD-920: start/end meeting mode. Flips the persisted flag and reflects
  // the returned thread back into the store so the gallery mounts/unmounts.
  // AD-923: ending a meeting writes a deterministic end-of-meeting marker into
  // the thread transcript (the thread IS the transcript) BEFORE the flag is
  // cleared. The marker is client-side + deterministic (no LLM, no backend
  // change): role:'system' reuses the existing append endpoint and skips the
  // AD-914 role=="captain" fan-out gate. Honest-degrade: appendMessage -> null
  // never blocks End.
  async function handleToggleMeeting() {
    if (meetingActive) {
      const n = crewParticipants.length;
      const names = crewParticipants.map((p) => p.agent.callsign).join(', ');
      const marker = names
        ? `Meeting ended — ${n} participant${n === 1 ? '' : 's'}: ${names}.`
        : `Meeting ended — ${n} participants.`;
      await appendMessage(threadId, {
        author_id: 'system',
        role: 'system',
        body: marker,
        metadata: { meeting_end: true, participant_count: n },
      });
    }
    const updated = await setMeetingActive(threadId, !meetingActive);
    if (updated) setChatThread(updated);
  }

  return (
    <div
      data-testid="group-chat-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      {/* Editable room title (click-to-edit; Enter/blur commits, Esc cancels) */}
      {editing ? (
        <input
          data-testid="group-chat-title-input"
          autoFocus
          value={titleDraft}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={() => { void commitTitle(); }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); void commitTitle(); }
            else if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }
          }}
          style={{
            flex: 1,
            minWidth: 0,
            background: 'transparent',
            border: '1px solid rgba(240,176,96,0.3)',
            borderRadius: 4,
            color: '#e0dcd4',
            fontSize: 13,
            padding: '2px 6px',
            outline: 'none',
          }}
        />
      ) : (
        <span
          data-testid="group-chat-title"
          onClick={() => { setTitleDraft(chatDisplayName(thread, agents)); setEditing(true); }}
          title="Rename room"
          style={{
            flex: 1,
            minWidth: 0,
            color: '#e0dcd4',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {chatDisplayName(thread, agents)}
        </span>
      )}

      {/* Participant avatar strip (crew only; hover reveals remove-x) */}
      <div
        data-testid="participant-strip"
        style={{ display: 'flex', alignItems: 'center', gap: 4 }}
      >
        {crewParticipants.map(({ id, agent }) => {
          const dept = (agent as Agent & { department?: string }).department ?? '';
          return (
            <span
              key={id}
              onMouseEnter={() => setHoveredId(id)}
              onMouseLeave={() => setHoveredId((h) => (h === id ? null : h))}
              style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
            >
              <AgentAvatarBadge
                agentId={id}
                callsign={agent.callsign}
                department={dept}
                size={24}
              />
              {hoveredId === id && (
                <button
                  type="button"
                  data-testid={`remove-participant-${id}`}
                  aria-label={`remove ${agent.callsign}`}
                  onClick={() => { void handleRemove(id); }}
                  style={{
                    position: 'absolute',
                    top: -4,
                    right: -4,
                    background: '#12121a',
                    border: 'none',
                    borderRadius: '50%',
                    color: '#666680',
                    cursor: 'pointer',
                    padding: 0,
                    lineHeight: 0,
                    display: 'inline-flex',
                  }}
                >
                  <Close size={10} />
                </button>
              )}
            </span>
          );
        })}
      </div>

      {/* AD-920 / AD-954: Start/End Call toggle. Promotes the group chat to a
          live video call (metadata.meeting_active) so ProfileChatTab mounts the
          AD-947 face-framed avatar gallery + AD-949 call audio — the Teams-style
          "turn the chat into a call" step. Local inline video glyph (HXI #3 —
          no emoji, no Glyphs.tsx export so the Glyphs.test.tsx count is
          untouched). Shown when there is at least one crew participant. */}
      {crewParticipants.length >= 1 && (
        <button
          type="button"
          data-testid="meeting-toggle"
          aria-label={meetingActive ? 'End call' : 'Start call'}
          aria-pressed={meetingActive}
          title={meetingActive ? 'End call' : 'Start call'}
          onClick={() => { void handleToggleMeeting(); }}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: meetingActive ? '#f0b060' : '#666680',
            display: 'inline-flex', alignItems: 'center', padding: 2,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
               strokeLinejoin="round">
            <rect x="1.5" y="4" width="9" height="8" rx="1.5" />
            <path d="M10.5 7 L14.5 5 V11 L10.5 9 Z" />
          </svg>
        </button>
      )}

      {/* AD-949: in-call audio mute/unmute. Group/meeting voice is gated by the
          call-scoped ``callAudioEnabled`` (decoupled from the Ship's-Computer
          ``voiceEnabled``); this flips it so the Captain can silence a live call
          without muting the Ship's Computer. Shown only while a meeting is
          active. Local inline speaker SVG (HXI #3 — no emoji, no Glyphs.tsx
          export; amber when audible, dim when muted). */}
      {meetingActive && (
        <button
          type="button"
          data-testid="call-audio-toggle"
          aria-label={callAudioEnabled ? 'Mute call audio' : 'Unmute call audio'}
          aria-pressed={callAudioEnabled}
          title={callAudioEnabled ? 'Mute call audio' : 'Unmute call audio'}
          onClick={() => setCallAudioEnabled(!callAudioEnabled)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: callAudioEnabled ? '#f0b060' : '#666680',
            display: 'inline-flex', alignItems: 'center', padding: 2,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
               strokeLinejoin="round">
            <path d="M2.5 6 H5 L8.5 3.5 V12.5 L5 10 H2.5 Z" />
            {callAudioEnabled ? (
              <>
                <path d="M11 6.2 Q12.2 8 11 9.8" />
                <path d="M12.8 4.8 Q15 8 12.8 11.2" />
              </>
            ) : (
              <path d="M11.5 6 L14.5 10 M14.5 6 L11.5 10" />
            )}
          </svg>
        </button>
      )}

      {/* AD-937: Add control branches on the thread shape. On a GROUP (>=2 crew)
          it toggles the inline @-picker -> addParticipant (mutation is correct
          there — matches Teams). On a 1:1 (<=1 crew) it opens the AD-931
          NewChatModal SEEDED with the host, so confirming with 2+ mints a
          SEPARATE group thread and the 1:1 row is never mutated. */}
      <div style={{ position: 'relative' }}>
        <button
          type="button"
          data-testid="add-participant-button"
          aria-label="add participant"
          onClick={() => {
            if (crewParticipants.length >= 2) setPickerOpen((o) => !o);
            else setConvertOpen(true);
          }}
          style={{
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
            color: pickerOpen ? '#f0b060' : '#666680',
            padding: 4,
            display: 'inline-flex',
            alignItems: 'center',
          }}
        >
          <UserPlus size={14} />
        </button>
        {crewParticipants.length >= 2 && pickerOpen && (
          <div style={{ position: 'absolute', top: '100%', right: 0 }}>
            <AddParticipantPopover
              existingParticipantIds={participants}
              onAdd={handleAdd}
              onClose={() => setPickerOpen(false)}
            />
          </div>
        )}
      </div>
      {/* AD-937: non-destructive 1:1 -> group convert (seeded picker overlay). */}
      {crewParticipants.length <= 1 && convertOpen && (
        <NewChatModal
          seedParticipantId={crewParticipants[0]?.id}
          onClose={() => setConvertOpen(false)}
        />
      )}
    </div>
  );
}
