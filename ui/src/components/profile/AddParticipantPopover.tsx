// AD-917: focused, keyboard-navigable crew picker for the group-chat header.
//
// Reuses the SAME data source as the AD-719 @-picker (useStore((s) => s.agents))
// and AgentAvatarBadge for each row, with NO IntentSurface coupling — the
// add-participant flow is a button -> popover -> select -> POST interaction,
// not the caret/@-in-textarea state machine embedded in IntentSurface. The
// parent (GroupChatHeader) owns the POST + strip hydrate, so this popover is a
// pure selector that renders trivially in tests with a seeded `agents` store.
// HXI #3 — amber/dim palette, no emoji.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store/useStore';
import type { Agent } from '../../store/types';
import { AgentAvatarBadge } from '../AgentAvatarBadge';

interface AddParticipantPopoverProps {
  /** Agent ids already in the thread — excluded from the picker. */
  existingParticipantIds: string[];
  /** Parent performs the POST + strip update with the chosen agent id. */
  onAdd: (agentId: string) => void;
  onClose: () => void;
}

interface CrewRow {
  id: string;
  callsign: string;
  displayName: string;
  department: string;
}

export function AddParticipantPopover({
  existingParticipantIds,
  onAdd,
  onClose,
}: AddParticipantPopoverProps) {
  const agents = useStore((s) => s.agents);
  const [prefix, setPrefix] = useState('');
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<Array<HTMLDivElement | null>>([]);

  const crewRows: CrewRow[] = useMemo(() => {
    const existing = new Set(existingParticipantIds);
    return Array.from(agents.values())
      .filter((a) => a.isCrew && !!a.callsign)
      // Exclude agents already in the thread and the literal Captain id.
      .filter((a) => a.id !== 'captain' && !existing.has(a.id))
      .map((a) => ({
        id: a.id,
        callsign: a.callsign,
        displayName: a.displayName || '',
        // ``department`` is not on the base Agent interface — access defensively.
        department: (a as Agent & { department?: string }).department ?? '',
      }))
      // Dedupe by callsign — multiple live agents may share a type/callsign.
      .filter((row, i, arr) => arr.findIndex((r) => r.callsign === row.callsign) === i);
  }, [agents, existingParticipantIds]);

  const matches: CrewRow[] = useMemo(() => {
    const p = prefix.toLowerCase();
    return crewRows
      .filter(
        (r) =>
          r.callsign.toLowerCase().startsWith(p) ||
          r.displayName.toLowerCase().startsWith(p),
      )
      .slice(0, 8);
  }, [crewRows, prefix]);

  // Reset the highlight to the top whenever the filter changes so the index
  // never points past the end of the (possibly shorter) match list.
  useEffect(() => {
    setIndex(0);
  }, [prefix]);

  // Focus the filter input on mount so the popover is keyboard-driven.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Scroll the highlighted row into view (HXI #4 — motion encodes state).
  // ``scrollIntoView`` is absent in jsdom and some embedded webviews, so
  // guard the call (Tier-2 — the highlight still updates either way).
  useEffect(() => {
    const el = rowRefs.current[index];
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' });
    }
  }, [index]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setIndex((i) => Math.min(i + 1, Math.max(matches.length - 1, 0)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      const row = matches[index];
      if (row) {
        e.preventDefault();
        onAdd(row.id);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  }

  return (
    <div
      data-testid="add-participant-popover"
      style={{
        position: 'absolute',
        zIndex: 50,
        minWidth: 220,
        background: '#12121a',
        border: '1px solid rgba(240,176,96,0.25)',
        borderRadius: 6,
        padding: 4,
        boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
      }}
    >
      <input
        ref={inputRef}
        value={prefix}
        onChange={(e) => setPrefix(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Add crew..."
        aria-label="filter crew"
        data-testid="add-participant-filter"
        style={{
          width: '100%',
          boxSizing: 'border-box',
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          color: '#e0dcd4',
          fontSize: 12,
          padding: '4px 6px',
          outline: 'none',
        }}
      />
      <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 4 }}>
        {matches.length === 0 && (
          <div style={{ color: '#666680', fontSize: 11, padding: '6px 8px' }}>
            No crew to add.
          </div>
        )}
        {matches.map((row, i) => (
          <div
            key={row.id}
            ref={(el) => { rowRefs.current[i] = el; }}
            data-testid="add-participant-row"
            onClick={() => onAdd(row.id)}
            onMouseEnter={() => setIndex(i)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '4px 6px',
              borderRadius: 4,
              cursor: 'pointer',
              // Amber wash for the active row; transparent otherwise (HXI #4).
              background: i === index ? 'rgba(240,176,96,0.12)' : 'transparent',
              color: i === index ? '#f0b060' : '#666680',
            }}
          >
            <AgentAvatarBadge
              agentId={row.id}
              callsign={row.callsign}
              department={row.department}
              size={24}
            />
            <span style={{ fontSize: 12, color: '#e0dcd4' }}>{row.callsign}</span>
            {row.displayName && (
              <span style={{ fontSize: 11, color: '#666680' }}>{row.displayName}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
