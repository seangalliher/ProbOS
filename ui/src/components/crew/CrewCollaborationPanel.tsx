/* Crew-collaboration surface — parent goal + fanned-out subtasks (AD-862)
 *
 * Renders one crew-collaboration tree fetched from GET /api/crew-tasks/{parentId}:
 * the parent WorkItem and its children. Each child's LIVE persisted status drives
 * the motion (HXI Principle #4 — motion encodes state): a child PULSES while
 * `in_progress` and SETTLES (static, dim border) once `done`. Per-subtask
 * verdict/rounds appear only post-completion (the API attaches them by dereffing
 * the AD-861 provenance blob); while a subtask is still running they are null and
 * the card shows a neutral "awaiting verification" state — never a fabricated
 * verdict.
 *
 * HXI Design Principle #3: inline SVG glyphs only (no emoji), stroke-based,
 * amber active (#f0b060) / dim inactive (#666680).
 */

import { useState, useEffect, useCallback } from 'react';

// ── Wire shapes (mirror the GET /api/crew-tasks serializer) ────────
export interface CrewVerdict {
  accepted: boolean | null;
  confidence: number | null;
  critique: string;
  verifier_agent_id: string;
}

export interface CrewChildView {
  id: string;
  title: string;
  status: string;
  assigned_to: string | null;
  verdict: CrewVerdict | null;
  rounds: number | null;
  [key: string]: unknown;
}

export interface CrewTaskTree {
  parent: { id: string; title: string; status: string; [key: string]: unknown };
  children: CrewChildView[];
  count: number;
}

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';
const ACCEPT_GREEN = '#60c070';
const REJECT_RED = '#d05050';

// ── Inline SVG glyphs (stroke-based, no emoji) ─────────────────────
function SpinnerGlyph({ color }: { color: string }) {
  // A broken ring — paired with the pulse animation it reads as "working".
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round"
      aria-hidden="true">
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

function CheckGlyph({ color }: { color: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

function CrossGlyph({ color }: { color: string }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

// ── Single subtask card ────────────────────────────────────────────
function SubtaskCard({ child }: { child: CrewChildView }) {
  const inProgress = child.status === 'in_progress';
  const done = child.status === 'done';
  // Border accent: amber while live, dim once settled.
  const accent = inProgress ? ACTIVE_AMBER : DIM;

  let statusGlyph = <SpinnerGlyph color={accent} />;
  if (done) {
    if (child.verdict && child.verdict.accepted === true) {
      statusGlyph = <CheckGlyph color={ACCEPT_GREEN} />;
    } else if (child.verdict && child.verdict.accepted === false) {
      statusGlyph = <CrossGlyph color={REJECT_RED} />;
    } else {
      statusGlyph = <CheckGlyph color={DIM} />;
    }
  }

  return (
    <div
      data-testid="crew-subtask-card"
      data-status={child.status}
      // Pulse while in_progress (motion = alive); static once settled.
      className={inProgress ? 'crew-subtask-pulse' : undefined}
      style={{
        marginBottom: 6, borderRadius: 6, overflow: 'hidden',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderLeft: `3px solid ${accent}`,
        padding: '8px 10px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {statusGlyph}
        <span style={{ fontSize: 12, fontWeight: 600, color: '#c8d0e0' }}>
          {child.title}
        </span>
        <span style={{
          marginLeft: 'auto', fontSize: 9, textTransform: 'uppercase',
          letterSpacing: 0.5, color: accent, fontWeight: 700,
        }}>
          {child.status}
        </span>
      </div>

      {child.verdict ? (
        <div data-testid="crew-subtask-verdict" style={{ marginTop: 5, fontSize: 11, color: '#9aa4ba' }}>
          <span style={{ color: child.verdict.accepted ? ACCEPT_GREEN : REJECT_RED }}>
            {child.verdict.accepted ? 'accepted' : 'rejected'}
          </span>
          {typeof child.verdict.confidence === 'number' ? (
            <span> · conf {child.verdict.confidence.toFixed(2)}</span>
          ) : null}
          {typeof child.rounds === 'number' ? (
            <span> · {child.rounds} round{child.rounds === 1 ? '' : 's'}</span>
          ) : null}
          {child.verdict.critique ? (
            <div style={{ marginTop: 2, color: '#7e8aa0', fontStyle: 'italic' }}>
              {child.verdict.critique}
            </div>
          ) : null}
        </div>
      ) : (
        <div data-testid="crew-subtask-pending" style={{ marginTop: 5, fontSize: 11, color: DIM }}>
          awaiting verification
        </div>
      )}
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────────────
export default function CrewCollaborationPanel({ parentId }: { parentId: string }) {
  const [tree, setTree] = useState<CrewTaskTree | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    if (!parentId) {
      setLoaded(true);
      return;
    }
    try {
      const resp = await fetch(`/api/crew-tasks/${parentId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      setTree(data && Array.isArray(data.children) ? data : null);
    } catch {
      // Tier-1 swallow: a transient fetch failure leaves the prior tree shown.
    } finally {
      setLoaded(true);
    }
  }, [parentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loaded && !tree) {
    return null;
  }
  if (!tree) {
    return null;
  }

  return (
    <div data-testid="crew-collaboration-panel" style={{ padding: '8px 0' }}>
      <style>{`
        @keyframes crewSubtaskPulse {
          0% { box-shadow: 0 0 0 0 rgba(240,176,96,0.25); }
          50% { box-shadow: 0 0 0 4px rgba(240,176,96,0.0); }
          100% { box-shadow: 0 0 0 0 rgba(240,176,96,0.0); }
        }
        .crew-subtask-pulse { animation: crewSubtaskPulse 1.6s ease-in-out infinite; }
      `}</style>
      <div style={{
        fontSize: 10, textTransform: 'uppercase', letterSpacing: 1,
        color: ACTIVE_AMBER, fontWeight: 700, marginBottom: 6, padding: '0 2px',
      }}>
        Crew Collaboration
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: '#c8d0e0', marginBottom: 8, padding: '0 2px' }}>
        {tree.parent.title}
        <span style={{
          marginLeft: 8, fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5,
          color: tree.parent.status === 'done' ? DIM : ACTIVE_AMBER, fontWeight: 700,
        }}>
          {tree.parent.status}
        </span>
      </div>
      {tree.children.map(child => (
        <SubtaskCard key={child.id} child={child} />
      ))}
    </div>
  );
}
