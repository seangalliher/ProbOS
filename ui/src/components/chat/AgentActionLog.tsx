/**
 * AD-745: AgentActionLog - per-DM-thread surface for agent-proposed
 * browser actions. Collapsed by default (HXI #5 progressive disclosure).
 *
 * Renders entries from ``GET /api/browser/actions/by-thread/{thread_id}``
 * via the ``useActionLogStore`` polling slice. Per-entry:
 *
 *   - verb + intent (mono, stroke-bordered card)
 *   - tier glyph (1/2/3 - stroke-density encoded, no color reliance)
 *   - status badge: proposed | ack_pending (pulsing per HXI #4) |
 *     confirm_pending (faster pulse) | executed | aborted | failed
 *   - before/after frame thumbnails (when refs are set)
 *   - per-action ABORT button -> POST /abort
 *
 * HXI #3: stroke SVG icons only, no emoji.
 */
import { useEffect, useState } from 'react';

export interface ActionEntry {
  action_id: string;
  agent_id: string;
  thread_id: string | null;
  verb: string;
  raw_intent: string;
  tier: number;
  status:
    | 'proposed'
    | 'executed'
    | 'ack_pending'
    | 'confirm_pending'
    | 'aborted'
    | 'timed_out'
    | 'failed';
  page_url: string | null;
  before_frame_ref?: string | null;
  after_frame_ref?: string | null;
  destructive_pattern_match?: string | null;
  error?: string | null;
}

interface AgentActionLogProps {
  threadId: string;
  // Optional fetch override for tests (avoids polling timer flake).
  fetcher?: (threadId: string) => Promise<ActionEntry[]>;
  // Optional poll interval override (ms). Defaults to 2000.
  pollIntervalMs?: number;
}

async function _defaultFetch(threadId: string): Promise<ActionEntry[]> {
  try {
    const r = await fetch(`/api/browser/actions/by-thread/${encodeURIComponent(threadId)}`);
    if (!r.ok) return [];
    const j = await r.json();
    return Array.isArray(j.actions) ? (j.actions as ActionEntry[]) : [];
  } catch {
    return [];
  }
}

function _TierGlyph({ tier }: { tier: number }) {
  const strokeWidth = tier === 1 ? 1.0 : tier === 2 ? 1.5 : 2.5;
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
         stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
         aria-label={`tier-${tier}`}
         data-testid={`action-tier-glyph-${tier}`}>
      {Array.from({ length: tier }).map((_, i) => (
        <line key={i} x1={3} y1={4 + i * 3} x2={13} y2={4 + i * 3} />
      ))}
    </svg>
  );
}

function _StatusBadge({ status }: { status: ActionEntry['status'] }) {
  const isPulsing = status === 'ack_pending' || status === 'confirm_pending';
  const pulseDuration =
    status === 'confirm_pending' ? '0.6s' : status === 'ack_pending' ? '1.2s' : '0s';
  const color =
    status === 'executed' ? '#80e080' :
    status === 'aborted' ? '#ff8080' :
    status === 'failed' || status === 'timed_out' ? '#ffaa60' :
    '#f0b060';
  return (
    <span
      data-testid={`action-status-${status}`}
      data-pulsing={isPulsing ? 'true' : 'false'}
      style={{
        color, fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
        textTransform: 'uppercase' as const, letterSpacing: 0.5,
        animation: isPulsing ? `actionPulse ${pulseDuration} ease-in-out infinite` : 'none',
      }}
    >
      {status.replace('_', ' ')}
    </span>
  );
}

async function _postAbort(actionId: string): Promise<void> {
  try {
    await fetch(`/api/browser/actions/${encodeURIComponent(actionId)}/abort`, {
      method: 'POST',
    });
  } catch {
    // Tier-2 honest-degrade; the polling refresh will reflect server state.
  }
}

export function AgentActionLog({ threadId, fetcher, pollIntervalMs = 2000 }: AgentActionLogProps) {
  const [expanded, setExpanded] = useState(false);
  const [entries, setEntries] = useState<ActionEntry[]>([]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const next = await (fetcher ? fetcher(threadId) : _defaultFetch(threadId));
      if (!cancelled) setEntries(next);
    };
    run();
    const iv = window.setInterval(run, pollIntervalMs);
    return () => { cancelled = true; window.clearInterval(iv); };
  }, [threadId, fetcher, pollIntervalMs]);

  if (!entries.length) return null;

  return (
    <div
      data-testid="agent-action-log"
      style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
        padding: '4px 12px', fontSize: 11,
      }}
    >
      <button
        type="button"
        data-testid="agent-action-log-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((x) => !x)}
        style={{
          background: 'transparent', border: 'none',
          color: '#f0b060', cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          padding: '2px 0',
        }}
      >
        {expanded ? '▼' : '▶'} agent actions ({entries.length})
      </button>
      {expanded && (
        <div data-testid="agent-action-log-entries" style={{ marginTop: 4 }}>
          {entries.map((e) => (
            <div key={e.action_id}
                 data-testid={`agent-action-entry-${e.action_id}`}
                 style={{
                   display: 'flex', alignItems: 'center', gap: 6,
                   padding: '2px 0',
                   border: '1px solid rgba(240,176,96,0.20)',
                   borderRadius: 4, marginBottom: 2,
                   paddingLeft: 6, paddingRight: 6,
                 }}>
              <span style={{ color: '#666680' }}><_TierGlyph tier={e.tier} /></span>
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                color: '#e0dcd4', fontSize: 11,
              }}>{e.verb}</span>
              <span style={{
                color: '#8888a0', fontSize: 10, flex: 1,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{e.raw_intent}</span>
              <_StatusBadge status={e.status} />
              {(e.status === 'ack_pending' || e.status === 'confirm_pending' ||
                e.status === 'proposed') && (
                <button
                  type="button"
                  data-testid={`agent-action-abort-${e.action_id}`}
                  onClick={() => _postAbort(e.action_id)}
                  aria-label="abort action"
                  title="abort"
                  style={{
                    background: 'transparent', border: 'none',
                    color: '#ff8080', cursor: 'pointer',
                    padding: 2, lineHeight: 1,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 12 12" fill="none"
                       stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                    <line x1="3" y1="3" x2="9" y2="9" />
                    <line x1="9" y1="3" x2="3" y2="9" />
                  </svg>
                </button>
              )}
              {(e.before_frame_ref || e.after_frame_ref) && (
                <span
                  data-testid={`agent-action-frames-${e.action_id}`}
                  style={{
                    border: '1px solid rgba(240,176,96,0.35)',
                    borderRadius: 2, padding: '0 4px',
                    fontSize: 9, color: '#f0b060',
                  }}
                >FRAME</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
