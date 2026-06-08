// AD-932: discoverable "+ Add people" affordance for a fresh/empty 1:1 chat.
// On a brand-new 1:1 there is no thread until the first message is sent, so the
// AD-917 GroupChatHeader (and its add-participant picker) never mounts — leaving
// no way to add a second crew member. This button materializes the 1:1 thread
// via createThread([agentId]) so the existing GroupChatHeader (+ its picker)
// takes over on the next render; the Captain then uses that picker to convert
// the 1:1 into a group. Mounted by ProfileChatTab only when !activeThreadId
// (mutually exclusive with the header). HXI #3 — inline stroke-SVG glyph,
// amber/dim palette, no emoji.
import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { UserPlus } from '../icons/Glyphs';
import { createThread } from '../sidebar/threadApi';

interface EmptyChatAddPeopleProps {
  agentId: string;
}

export function EmptyChatAddPeople({ agentId }: EmptyChatAddPeopleProps) {
  const agent = useStore((s) => s.agents.get(agentId));
  const setChatThread = useStore((s) => s.setChatThread);
  const setThreadForAgent = useStore((s) => s.setThreadForAgent);
  const [hovered, setHovered] = useState(false);

  // Only a crew 1:1 can become a group. Non-crew / unknown host -> nothing.
  if (!agent?.isCrew) return null;

  // Capture the callsign in the narrowed synchronous scope (control-flow
  // narrowing of `agent` does not propagate into the async closure below).
  const callsign = agent.callsign;

  async function handleAddPeople() {
    // Materialize the 1:1 thread so GroupChatHeader (+ its picker) can mount.
    const t = await createThread({ title: callsign, participants: [agentId] });
    if (!t) return; // Tier-2 honest-degrade: createThread null -> keep the button, no store write.
    setChatThread(t); // GroupChatHeader reads chatThreads.get(threadId).
    setThreadForAgent(agentId, t.id); // -> activeThreadId resolves -> header mounts.
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
      <button
        type="button"
        data-testid="empty-chat-add-people"
        aria-label="add people"
        onClick={() => {
          void handleAddPeople();
        }}
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
  );
}
