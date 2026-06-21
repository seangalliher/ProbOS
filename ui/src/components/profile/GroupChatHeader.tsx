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
  // AD-984a: meeting-mode chat visibility (default ON). The in-call toggle below
  // hides/shows the transcript so the Captain can make a meeting avatars+voice
  // only; ProfileChatTab gates the message-list on this flag while meetingActive.
  const meetingChatVisible = useStore((s) => s.meetingChatVisible);
  const setMeetingChatVisible = useStore((s) => s.setMeetingChatVisible);

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

  // AD-969: the add-control's branch key. ONLY the Captain's 1:1 home DM
  // (metadata.is_default) mints a SEPARATE group thread when adding a peer (the
  // AD-937 non-destructive convert that keeps the pristine 1:1). EVERY other
  // room — a group OR an agent-created room — adds the participant IN PLACE
  // (the Teams behavior). Keying on is_default (not crew count) fixes the
  // Captain-reported bug where adding a member to an agent-created room minted
  // a brand-new chat instead of joining the existing one.
  const isDefaultOneOnOne = !!(thread.metadata as { is_default?: unknown } | undefined)?.is_default;

  // AD-984b: enter title-edit mode (seed the draft from the current display
  // name). Extracted so the click handler and the keyboard (Enter/Space)
  // handler open the editor from one place.
  const beginEdit = () => {
    setTitleDraft(chatDisplayName(thread, agents));
    setEditing(true);
  };

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
          role="button"
          tabIndex={0}
          aria-label="Rename room"
          onClick={beginEdit}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); beginEdit(); }
          }}
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

      {/* AD-984a: in-call chat-visibility toggle. A meeting is one conversation
          viewed by voice; this lets the Captain hide the text transcript so the
          avatars + voice are the whole surface (the message-list is gated on
          this flag in ProfileChatTab while meetingActive; the conversation,
          persistence, and BF-621 voice reveal are unaffected). Shown only while
          a meeting is active. Local inline speech-bubble stroke-SVG (HXI #3 — no
          emoji, no Glyphs.tsx export; amber when the chat is shown, dim with a
          slash when hidden). */}
      {meetingActive && (
        <button
          type="button"
          data-testid="chat-visibility-toggle"
          aria-label={meetingChatVisible ? 'Hide chat' : 'Show chat'}
          aria-pressed={meetingChatVisible}
          title={meetingChatVisible ? 'Hide chat' : 'Show chat'}
          onClick={() => setMeetingChatVisible(!meetingChatVisible)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: meetingChatVisible ? '#f0b060' : '#666680',
            display: 'inline-flex', alignItems: 'center', padding: 2,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
               strokeLinejoin="round">
            <path d="M2 4.5 A1.5 1.5 0 0 1 3.5 3 H12.5 A1.5 1.5 0 0 1 14 4.5 V9.5 A1.5 1.5 0 0 1 12.5 11 H6 L3 13.5 V11 H3.5 A1.5 1.5 0 0 1 2 9.5 Z" />
            {!meetingChatVisible && <path d="M1.5 1.5 L14.5 14.5" />}
          </svg>
        </button>
      )}

      {/* AD-937/AD-969: Add control branches on whether this is the Captain's
          1:1 HOME DM (metadata.is_default). On the 1:1 home DM it opens the
          AD-931 NewChatModal SEEDED with the host, so confirming with 2+ mints a
          SEPARATE group thread and the pristine 1:1 is never mutated. On EVERY
          other room — a group OR an agent-created room — it toggles the inline
          @-picker -> addParticipant (in-place mutation, matches Teams). */}
      <div style={{ position: 'relative' }}>
        <button
          type="button"
          data-testid="add-participant-button"
          aria-label="add participant"
          onClick={() => {
            if (isDefaultOneOnOne) setConvertOpen(true);
            else setPickerOpen((o) => !o);
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
        {!isDefaultOneOnOne && pickerOpen && (
          <div style={{ position: 'absolute', top: '100%', right: 0 }}>
            <AddParticipantPopover
              existingParticipantIds={participants}
              onAdd={handleAdd}
              onClose={() => setPickerOpen(false)}
            />
          </div>
        )}
      </div>
      {/* AD-937: non-destructive 1:1 -> group convert (seeded picker overlay).
          Only the Captain's 1:1 home DM reaches this path (AD-969). */}
      {isDefaultOneOnOne && convertOpen && (
        <NewChatModal
          seedParticipantId={crewParticipants[0]?.id}
          onClose={() => setConvertOpen(false)}
        />
      )}
    </div>
  );
}
