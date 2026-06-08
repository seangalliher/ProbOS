/**
 * AD-931: "+ New chat" picker for the unified CHATS surface.
 *
 * Reuses the AD-917 `AddParticipantPopover` (crew filter, keyboard nav,
 * dedupe-by-callsign) as a multi-select surface: each `onAdd` accumulates into
 * a local `selected[]`, and the running selection is fed back as
 * `existingParticipantIds` so picked agents drop out of the list. On confirm
 * the flow BRANCHES ON SELECTION COUNT (AD-931 Decision C) to avoid minting a
 * duplicate/divergent 1:1 thread:
 *   - 1 agent  -> `openAgentProfile(id)` (NO `createThread`; the server-side
 *                 `get_or_create_default_for_agent` owns the 1:1 default thread).
 *   - 2+ agents -> `createThread({ title, participants })` then open the host
 *                 (first selected crew), verbatim AD-919 host pattern.
 *
 * Per HXI Design Principle #3: inline SVG glyphs only, amber `#f0b060`, no emoji.
 */
import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { AddParticipantPopover } from '../profile/AddParticipantPopover';
import { Close } from '../icons/Glyphs';
import { createThread } from '../sidebar/threadApi';
import { COLOR_ACTIVE, COLOR_INACTIVE } from './chatFilters';

export function NewChatModal({ onClose }: { onClose: () => void }) {
  const agents = useStore((s) => s.agents);
  const setThreadForAgent = useStore((s) => s.setThreadForAgent);
  const openAgentProfile = useStore((s) => s.openAgentProfile);
  const closeChats = useStore((s) => s.closeChats);

  const [selected, setSelected] = useState<string[]>([]);

  function removeSelected(id: string): void {
    setSelected((prev) => prev.filter((p) => p !== id));
  }

  async function onStart(): Promise<void> {
    if (selected.length === 0) return;

    // 1 agent -> open the existing 1:1 default thread (NO createThread).
    if (selected.length === 1) {
      openAgentProfile(selected[0]);
      closeChats();
      onClose();
      return;
    }

    // 2+ agents -> create a group, open the host (first selected crew).
    const callsigns = selected.map((id) => agents.get(id)?.callsign ?? id);
    const title = callsigns.join(', ') || 'New group chat';
    const thread = await createThread({ title, participants: selected });
    if (!thread) return; // Tier-2 honest-degrade: keep the modal open, no throw
    setThreadForAgent(selected[0], thread.id);
    openAgentProfile(selected[0]);
    closeChats();
    onClose();
  }

  return (
    <div
      data-testid="new-chat-modal"
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 40,
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(8, 8, 14, 0.97)',
        borderRadius: 8,
        padding: 14,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#c0bab0',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, color: COLOR_ACTIVE }}>
          NEW CHAT
        </span>
        <div style={{ flex: 1 }} />
        <div
          data-testid="new-chat-cancel"
          onClick={onClose}
          style={{ cursor: 'pointer', color: COLOR_INACTIVE, display: 'inline-flex' }}
          aria-label="Cancel new chat"
        >
          <Close size={14} />
        </div>
      </div>

      {/* Selected chips (click to remove -> drops back into the popover list) */}
      {selected.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {selected.map((id) => (
            <button
              key={id}
              data-testid={`new-chat-selected-${id}`}
              onClick={() => removeSelected(id)}
              aria-label={`Remove ${agents.get(id)?.callsign ?? id}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'pointer',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                fontWeight: 600,
                color: COLOR_ACTIVE,
                background: 'rgba(240, 176, 96, 0.08)',
                border: '1px solid rgba(240, 176, 96, 0.35)',
                borderRadius: 12,
                padding: '2px 10px',
              }}
            >
              {agents.get(id)?.callsign ?? id}
              <Close size={10} />
            </button>
          ))}
        </div>
      )}

      {/* Picker — AD-917 popover reused as a multi-select selection surface. */}
      <div style={{ position: 'relative', flex: 1, minHeight: 240 }}>
        <AddParticipantPopover
          existingParticipantIds={selected}
          onAdd={(id) => setSelected((prev) => [...prev, id])}
          onClose={onClose}
        />
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
        <div style={{ flex: 1 }} />
        <button
          data-testid="new-chat-start"
          onClick={() => void onStart()}
          disabled={selected.length < 1}
          style={{
            cursor: selected.length < 1 ? 'default' : 'pointer',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1,
            color: selected.length < 1 ? COLOR_INACTIVE : '#0a0a12',
            background: selected.length < 1 ? 'rgba(240, 176, 96, 0.08)' : COLOR_ACTIVE,
            border: '1px solid rgba(240, 176, 96, 0.35)',
            borderRadius: 6,
            padding: '6px 14px',
            opacity: selected.length < 1 ? 0.5 : 1,
          }}
        >
          Start chat
        </button>
      </div>
    </div>
  );
}
