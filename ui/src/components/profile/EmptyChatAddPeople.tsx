// AD-932 / AD-937: discoverable "+ Add people" affordance for a fresh/empty 1:1
// chat. On a brand-new 1:1 there is no thread until the first message is sent,
// so the AD-917 GroupChatHeader (and its add-participant picker) never mounts —
// leaving no way to add a second crew member. AD-937 makes this NON-DESTRUCTIVE:
// instead of materializing the 1:1 row and mutating it into a group (the old
// AD-932 flow, which destroyed the 1:1), the button opens the AD-931 NewChatModal
// PRE-SEEDED with this agent as the locked host. Confirming with 2+ mints a
// SEPARATE new group thread (createThread) opened via the group override, so the
// agent's 1:1 is never touched and stays reachable. The 1:1 itself is created
// lazily by the server (get_or_create_default_for_agent) on first message.
// Mounted by ProfileChatTab only when !activeThreadId (mutually exclusive with
// the header). HXI #3 — inline stroke-SVG glyph, amber/dim palette, no emoji.
import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { UserPlus } from '../icons/Glyphs';
import { NewChatModal } from '../chats/NewChatModal';

interface EmptyChatAddPeopleProps {
  agentId: string;
}

export function EmptyChatAddPeople({ agentId }: EmptyChatAddPeopleProps) {
  const agent = useStore((s) => s.agents.get(agentId));
  const [hovered, setHovered] = useState(false);
  // AD-937: the seeded picker overlays the profile chat area when opened.
  const [pickerOpen, setPickerOpen] = useState(false);

  // Only a crew 1:1 can become a group. Non-crew / unknown host -> nothing.
  if (!agent?.isCrew) return null;

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
        <button
          type="button"
          data-testid="empty-chat-add-people"
          aria-label="add people"
          onClick={() => setPickerOpen(true)}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: hovered ? 'rgba(240, 176, 96, 0.08)' : 'transparent',
            border: `1px solid ${hovered ? 'rgba(240, 176, 96, 0.6)' : 'rgba(240, 176, 96, 0.3)'}`,
            borderRadius: 6,
            color: '#f0b060',
            cursor: 'pointer',
            padding: '6px 12px',
            fontSize: 12,
            letterSpacing: 0.3,
            filter: hovered ? 'drop-shadow(0 0 4px rgba(240, 176, 96, 0.4))' : 'none',
            transition: 'background 120ms ease, border-color 120ms ease, filter 120ms ease',
          }}
        >
          <UserPlus size={14} />
          Add people
        </button>
      </div>
      {/* AD-937: non-destructive convert — opens the AD-931 picker seeded with
          this agent as the locked host; createThread mints a SEPARATE group. */}
      {pickerOpen && (
        <NewChatModal seedParticipantId={agentId} onClose={() => setPickerOpen(false)} />
      )}
    </>
  );
}
