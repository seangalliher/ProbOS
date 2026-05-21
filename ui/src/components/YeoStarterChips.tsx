/*
 * AD-795 — YeoStarterChips
 *
 * Empty-thread quick-action chips for the Compact Yeo surface. Click
 * inserts a starter prompt into the chat input via the `chatDrafts` store
 * mechanism (see useStore.setChatDraft + ProfileChatTab's draft-consume
 * effect). Chips do NOT auto-send — they mirror the Claude Chat behavior
 * where the human can edit the inserted text before pressing Enter.
 *
 * The component only renders when the active Yeo conversation has zero
 * messages; once the first turn lands the parent unmounts it.
 */
import { useStore } from '../store/useStore';

export interface YeoStarterChip {
  id: string;
  label: string;
  prompt: string;
}

export const DEFAULT_CHIPS: readonly YeoStarterChip[] = [
  {
    id: 'brief',
    label: 'Brief me',
    prompt: 'Brief me on the day — what should I focus on right now?',
  },
  {
    id: 'write',
    label: 'Help me write…',
    prompt: 'Help me write ',
  },
  {
    id: 'plan',
    label: 'Plan a task…',
    prompt: 'Help me plan this task: ',
  },
  {
    id: 'code',
    label: 'Code something…',
    prompt: 'I need help with some code: ',
  },
  {
    id: 'remember',
    label: 'Remember this…',
    prompt: 'Please remember this for me: ',
  },
] as const;

interface Props {
  agentId: string;
  chips?: readonly YeoStarterChip[];
}

export function YeoStarterChips({ agentId, chips = DEFAULT_CHIPS }: Props) {
  const setChatDraft = useStore((s) => s.setChatDraft);

  return (
    <div
      data-testid="yeo-starter-chips"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        padding: '8px 12px 12px',
        justifyContent: 'center',
      }}
    >
      {chips.map((chip) => (
        <button
          key={chip.id}
          type="button"
          data-testid={`yeo-chip-${chip.id}`}
          onClick={() => setChatDraft(agentId, chip.prompt)}
          style={{
            background: 'rgba(240, 176, 96, 0.06)',
            border: '1px solid rgba(240, 176, 96, 0.25)',
            borderRadius: 16,
            color: '#f0b060',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            letterSpacing: 0.5,
            padding: '6px 12px',
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
