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

import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type {
  CrewSessionDetailProjection,
  CrewSessionState,
  CrewTaskDetailResponse,
  LegacyCrewChildView,
  LegacyCrewTaskTree,
} from '../../store/types';
import { useStore } from '../../store/useStore';
import { fetchCrewTaskDetail } from '../sidebar/threadApi';

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
function SubtaskCard({ child }: { child: LegacyCrewChildView }) {
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

const STATE_LABELS: Record<CrewSessionState, string> = {
  discussing: 'Discussing',
  executing: 'Executing',
  verifying: 'Verifying',
  blocked_needs_captain: 'Needs You',
  done: 'Done',
  failed: 'Failed',
};

function StateGlyph({ state }: { state: CrewSessionState }) {
  const color = state === 'done'
    ? ACCEPT_GREEN
    : state === 'failed' || state === 'blocked_needs_captain'
      ? REJECT_RED
      : ACTIVE_AMBER;
  if (state === 'done') return <CheckGlyph color={color} />;
  if (state === 'failed') return <CrossGlyph color={color} />;
  if (state === 'executing') return <SpinnerGlyph color={color} />;
  if (state === 'blocked_needs_captain') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true">
        <path d="M12 3L22 20H2L12 3Z" />
        <path d="M12 9v5M12 17h.01" />
      </svg>
    );
  }
  if (state === 'verifying') {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
        aria-hidden="true">
        <circle cx="10" cy="10" r="6" />
        <path d="M14.5 14.5L20 20M7 10l2 2 4-4" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M5 8h14M5 12h9M5 16h6" />
    </svg>
  );
}

function PanelStyles() {
  return (
    <style>{`
      @keyframes crewSubtaskPulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(240,176,96,0); }
        50% { box-shadow: 0 0 0 4px rgba(240,176,96,0.18); }
      }
      @keyframes crewSessionBreathe {
        0%, 100% { border-color: rgba(112,144,192,0.24); }
        50% { border-color: rgba(112,144,192,0.58); }
      }
      @keyframes crewSessionAttention {
        0%, 100% { border-left-color: rgba(208,80,80,0.55); }
        50% { border-left-color: rgba(240,176,96,1); }
      }
      @keyframes crewSessionSweep {
        from { transform: translateY(-120%); }
        to { transform: translateY(340%); }
      }
      .crew-subtask-pulse { animation: crewSubtaskPulse 1.6s ease-in-out infinite; }
      .crew-session-band {
        width: 100%; min-width: 0; min-height: 220px; max-width: 100%;
        box-sizing: border-box; padding: 14px 16px; border-top: 1px solid rgba(255,255,255,0.08);
        border-bottom: 1px solid rgba(255,255,255,0.08); border-left: 3px solid #666680;
        background: rgba(6,10,20,0.44); color: #c8d0e0;
      }
      .crew-session-band[data-state="discussing"] { animation: crewSessionBreathe 3.2s ease-in-out infinite; }
      .crew-session-band[data-state="executing"] { border-left-color: #f0b060; }
      .crew-session-band[data-state="verifying"] { border-left-color: #70a0c0; }
      .crew-session-band[data-state="blocked_needs_captain"] {
        border-left-color: #d05050; animation: crewSessionAttention 1.4s ease-in-out infinite;
      }
      .crew-session-band[data-state="done"] { border-left-color: #60c070; }
      .crew-session-band[data-state="failed"] { border-left-color: #d05050; }
      .crew-session-grid {
        display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(220px, .75fr);
        gap: 16px; align-items: start; min-width: 0;
      }
      .crew-session-section { min-width: 0; overflow-wrap: anywhere; white-space: normal; }
      .crew-session-verification { position: relative; overflow: hidden; }
      .crew-session-verification::after {
        content: ''; position: absolute; left: 0; right: 0; top: 0; height: 1px;
        background: #70a0c0; opacity: .7; animation: crewSessionSweep 2.4s linear infinite;
      }
      .crew-session-active { animation: crewSubtaskPulse 1.6s ease-in-out infinite; }
      .crew-session-action {
        border: 1px solid rgba(240,176,96,.7); background: rgba(240,176,96,.08);
        color: #f0b060; padding: 7px 10px; border-radius: 5px; font: inherit; cursor: pointer;
      }
      .crew-session-action:focus-visible, .crew-session-retry:focus-visible {
        outline: 2px solid #f0b060; outline-offset: 2px;
      }
      .crew-session-alert { margin: 0 0 10px; padding: 8px 10px; border-left: 2px solid #d05050; color: #e0a0a0; }
      .crew-session-placeholder { min-height: 220px; padding: 14px 16px; box-sizing: border-box; }
      @media (max-width: 760px) {
        .crew-session-band { padding: 12px; }
        .crew-session-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
      }
      @media (prefers-reduced-motion: reduce) {
        .crew-session-band, .crew-subtask-pulse, .crew-session-active,
        .crew-session-verification::after { animation: none !important; transition: none !important; }
        .crew-session-verification::after { display: none; }
      }
    `}</style>
  );
}

function LegacyCrewTree({ tree }: { tree: LegacyCrewTaskTree }) {
  return (
    <div data-testid="crew-collaboration-panel" style={{ padding: '8px 0' }}>
      <PanelStyles />
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

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} seconds`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`;
  return `${Math.round(seconds / 3600)} hours`;
}

function SessionBand({
  session,
  stacked,
  refreshing,
  staleError,
  sessionBandRef,
  onRetryFetch,
  onRetryBlockedWork,
  onOpenResultArtifact,
}: {
  session: CrewSessionDetailProjection;
  stacked: boolean;
  refreshing: boolean;
  staleError: boolean;
  sessionBandRef?: RefObject<HTMLElement | null>;
  onRetryFetch: () => void;
  onRetryBlockedWork?: (
    projection: CrewSessionDetailProjection,
    opener: HTMLButtonElement,
  ) => void;
  onOpenResultArtifact?: (
    artifactId: string,
    projection: CrewSessionDetailProjection,
  ) => void;
}) {
  const progress = session.progress;
  return (
    <section
      ref={sessionBandRef}
      tabIndex={-1}
      data-testid="crew-collaboration-panel"
      data-state={session.state}
      data-layout={stacked ? 'stacked' : 'columns'}
      className="crew-session-band"
      aria-busy={refreshing ? 'true' : 'false'}
      aria-labelledby="crew-session-goal"
    >
      <PanelStyles />
      {staleError ? (
        <div role="alert" className="crew-session-alert">
          Session refresh failed. Showing the last known state.{' '}
          <button type="button" className="crew-session-retry" onClick={onRetryFetch}>
            Retry
          </button>
        </div>
      ) : null}
      <header className="crew-session-section" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <StateGlyph state={session.state} />
          <span style={{ color: ACTIVE_AMBER, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0 }}>
            Crew Collaboration
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: session.state === 'failed' ? REJECT_RED : '#9aa4ba' }}>
            {STATE_LABELS[session.state]}
          </span>
        </div>
        <h3 id="crew-session-goal" style={{ margin: '8px 0 0', fontSize: 16, lineHeight: 1.35, letterSpacing: 0, overflowWrap: 'anywhere' }}>
          {session.goal}
        </h3>
      </header>

      <div
        className="crew-session-grid"
        style={{
          gridTemplateColumns: stacked
            ? 'minmax(0, 1fr)'
            : 'minmax(0, 1.25fr) minmax(220px, .75fr)',
          gap: stacked ? 12 : 16,
        }}
      >
        <div className="crew-session-section">
          <div style={{ fontSize: 11, color: '#9aa4ba', marginBottom: 10, overflowWrap: 'anywhere' }}>
            Facilitator <strong style={{ color: '#c8d0e0' }}>{session.facilitator_id}</strong>
            {' · '}Owners {session.owner_ids.join(', ')}
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 0 }}>Success criteria</div>
            <ul aria-label="Success criteria" style={{ margin: '5px 0 0', paddingLeft: 18 }}>
              {session.success_criteria.map(criterion => (
                <li key={criterion} style={{ marginBottom: 4, overflowWrap: 'anywhere' }}>{criterion}</li>
              ))}
            </ul>
          </div>
          <div style={{ marginBottom: 12, overflowWrap: 'anywhere' }}>
            <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 0 }}>Expected deliverable</div>
            <div style={{ marginTop: 4 }}>{session.expected_deliverable}</div>
          </div>
          {progress.active_child ? (
            <div className={session.state === 'executing' ? 'crew-session-active' : undefined}
              data-testid="crew-session-active-child"
              style={{ padding: '8px 0', borderTop: '1px solid rgba(255,255,255,.08)', borderBottom: '1px solid rgba(255,255,255,.08)', minWidth: 0 }}>
              <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 0 }}>Active work</div>
              <div style={{ marginTop: 4, overflowWrap: 'anywhere' }}>
                {progress.active_child.title} · {progress.active_child.status}
                {progress.active_child.owner_id ? ` · ${progress.active_child.owner_id}` : ''}
              </div>
            </div>
          ) : null}
          <div style={{ marginTop: 12, overflowWrap: 'anywhere' }}>
            <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 0 }}>Last result</div>
            <div style={{ marginTop: 4 }}>{session.last_result_summary || 'No result reported yet.'}</div>
          </div>
        </div>

        <aside className={`crew-session-section${session.state === 'verifying' ? ' crew-session-verification' : ''}`}
          aria-label="Crew session status">
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
              <span>Progress</span><strong>{progress.done}/{progress.total}</strong>
            </div>
            <div style={{ height: 4, marginTop: 6, background: 'rgba(255,255,255,.08)', overflow: 'hidden' }}>
              <div style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%`, height: '100%', background: ACCEPT_GREEN }} />
            </div>
            <div style={{ marginTop: 5, fontSize: 10, color: '#9aa4ba' }}>
              {progress.active} active · {progress.failed} failed
            </div>
          </div>
          {session.blocker ? (
            <div data-testid="crew-session-blocker" style={{ marginBottom: 14, overflowWrap: 'anywhere' }}>
              <div style={{ color: REJECT_RED, fontWeight: 700 }}>Captain action required</div>
              <div style={{ margin: '5px 0' }}>{session.blocker.reason}</div>
              <div style={{ color: '#9aa4ba', fontSize: 10 }}>Blocked for {formatDuration(session.blocker.duration_seconds)}</div>
              <button
                type="button"
                className="crew-session-action"
                aria-label="Retry blocked CrewSession work"
                style={{ marginTop: 8 }}
                onClick={(event) => onRetryBlockedWork?.(session, event.currentTarget)}
              >
                Retry Start Work
              </button>
            </div>
          ) : null}
          <div style={{ fontSize: 10, color: '#9aa4ba', marginBottom: 12 }}>
            Duplicate resumes: {session.duplicate_resume_count}
          </div>
          {session.result ? (
            <div data-testid="crew-session-result" style={{ marginBottom: 12, minWidth: 0 }}>
              <div style={{ color: ACCEPT_GREEN, fontWeight: 700 }}>Verified result</div>
              <button
                type="button"
                className="crew-session-action"
                aria-label="Open CrewSession result artifact"
                style={{ marginTop: 7 }}
                onClick={() => onOpenResultArtifact?.(session.result!.artifact_id, session)}
              >
                Open result artifact
              </button>
              <details style={{ marginTop: 8 }}>
                <summary>Evidence ({session.result.evidence_refs.length})</summary>
                <div aria-label="Result content fingerprint" style={{ marginTop: 5, overflowWrap: 'anywhere' }}>
                  Content: <code>{session.result.content_hash}</code>
                </div>
                <div aria-label="Result provenance reference" style={{ marginTop: 4, overflowWrap: 'anywhere' }}>
                  Result: <code>{session.result.result_ref}</code>
                </div>
                <ol aria-label="Evidence references" style={{ paddingLeft: 18 }}>
                  {session.result.evidence_refs.map(ref => (
                    <li key={ref} style={{ overflowWrap: 'anywhere' }}><code>{ref}</code></li>
                  ))}
                </ol>
              </details>
            </div>
          ) : null}
          {session.verification ? (
            <div data-testid="crew-session-verification" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
              <div style={{ fontSize: 10, color: DIM, textTransform: 'uppercase', letterSpacing: 0 }}>Verification</div>
              <div style={{ marginTop: 4 }}>{session.verification.verifier_agent_id} · {(session.verification.confidence * 100).toFixed(0)}%</div>
              <div style={{ marginTop: 4 }}>{session.verification.critique}</div>
              <div style={{ marginTop: 4, color: '#9aa4ba', fontSize: 10 }}>
                {session.verification.accepted_count}/{session.verification.total_count} accepted · {session.verification.convergence_rounds} rounds
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

export interface CrewCollaborationPanelProps {
  threadId: string;
  parentId: string;
  sessionBandRef?: RefObject<HTMLElement | null>;
  onRetryBlockedWork?: (
    projection: CrewSessionDetailProjection,
    opener: HTMLButtonElement,
  ) => void;
  onOpenResultArtifact?: (
    artifactId: string,
    projection: CrewSessionDetailProjection,
  ) => void;
}

type PanelLoadState = 'loading' | 'refreshing' | 'ready' | 'empty' | 'error';

interface PanelStatus {
  readonly ownerKey: string;
  readonly state: PanelLoadState;
  readonly staleError: boolean;
}

interface OwnedLegacyResponse {
  readonly ownerKey: string;
  readonly tree: LegacyCrewTaskTree;
}

interface InFlightRequest {
  readonly ownerKey: string;
  readonly generation: number;
  readonly requestId: number;
}

export default function CrewCollaborationPanel({
  threadId,
  parentId,
  sessionBandRef,
  onRetryBlockedWork,
  onOpenResultArtifact,
}: CrewCollaborationPanelProps) {
  const hydrateCrewSession = useStore(state => state.hydrateCrewSession);
  const cachedSession = useStore(state => state.crewSessionsByParent.get(parentId));
  const ownerKey = `${threadId}\u0000${parentId}`;
  const ownedCachedSession = cachedSession?.thread_id === threadId
    ? cachedSession
    : undefined;
  const requestIdRef = useRef(0);
  const ownerRef = useRef({ threadId, parentId, ownerKey, generation: 0 });
  if (ownerRef.current.ownerKey !== ownerKey) {
    ownerRef.current = {
      threadId,
      parentId,
      ownerKey,
      generation: ownerRef.current.generation + 1,
    };
    requestIdRef.current += 1;
  }
  const [legacyResponse, setLegacyResponse] = useState<OwnedLegacyResponse | null>(null);
  const [status, setStatus] = useState<PanelStatus>({
    ownerKey,
    state: ownedCachedSession ? 'refreshing' : 'loading',
    staleError: false,
  });
  const inFlightRef = useRef<InFlightRequest | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [stacked, setStacked] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= 760,
  );

  const owns = useCallback((
    targetThreadId: string,
    targetParentId: string,
    targetOwnerKey: string,
    targetGeneration: number,
  ): boolean => {
    const current = ownerRef.current;
    return current.threadId === targetThreadId
      && current.parentId === targetParentId
      && current.ownerKey === targetOwnerKey
      && current.generation === targetGeneration;
  }, []);

  const load = useCallback(async (targetThreadId: string, targetParentId: string) => {
    const targetOwnerKey = `${targetThreadId}\u0000${targetParentId}`;
    const targetGeneration = ownerRef.current.generation;
    if (
      !targetThreadId
      || !targetParentId
      || !owns(targetThreadId, targetParentId, targetOwnerKey, targetGeneration)
      || (
        inFlightRef.current?.ownerKey === targetOwnerKey
        && inFlightRef.current.generation === targetGeneration
      )
    ) return;
    const cached = useStore.getState().crewSessionsByParent.get(targetParentId);
    const hasOwnedCache = cached?.thread_id === targetThreadId;
    const requestId = ++requestIdRef.current;
    const inFlight = { ownerKey: targetOwnerKey, generation: targetGeneration, requestId };
    inFlightRef.current = inFlight;
    setStatus({
      ownerKey: targetOwnerKey,
      state: hasOwnedCache ? 'refreshing' : 'loading',
      staleError: false,
    });
    const outcome = await fetchCrewTaskDetail(targetParentId);
    if (
      requestId !== requestIdRef.current
      || !owns(targetThreadId, targetParentId, targetOwnerKey, targetGeneration)
    ) {
      if (inFlightRef.current === inFlight) inFlightRef.current = null;
      return;
    }
    if (outcome.kind === 'success') {
      if ('session' in outcome.response) {
        if (outcome.response.session.thread_id !== targetThreadId) {
          const retained = useStore.getState().crewSessionsByParent.get(targetParentId);
          const retainOwned = retained?.thread_id === targetThreadId;
          setLegacyResponse(null);
          setStatus({
            ownerKey: targetOwnerKey,
            state: retainOwned ? 'ready' : 'error',
            staleError: retainOwned,
          });
          if (inFlightRef.current === inFlight) inFlightRef.current = null;
          return;
        }
        hydrateCrewSession(targetParentId, outcome.response.session);
        setLegacyResponse(null);
      } else {
        setLegacyResponse({ ownerKey: targetOwnerKey, tree: outcome.response });
      }
      setStatus({ ownerKey: targetOwnerKey, state: 'ready', staleError: false });
    } else if (outcome.kind === 'empty') {
      setLegacyResponse(null);
      setStatus({ ownerKey: targetOwnerKey, state: 'empty', staleError: false });
    } else {
      const retained = useStore.getState().crewSessionsByParent.get(targetParentId);
      const retainOwned = retained?.thread_id === targetThreadId;
      setStatus({
        ownerKey: targetOwnerKey,
        state: retainOwned ? 'ready' : 'error',
        staleError: retainOwned,
      });
    }
    if (inFlightRef.current === inFlight) inFlightRef.current = null;
  }, [hydrateCrewSession, owns]);

  useEffect(() => {
    void load(threadId, parentId);
    return () => {
      requestIdRef.current += 1;
    };
  }, [load, parentId, threadId]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const applyWidth = (width: number) => setStacked(width <= 520);
    if (typeof ResizeObserver === 'function') {
      const observer = new ResizeObserver(entries => {
        const entry = entries[0];
        if (entry) applyWidth(entry.contentRect.width);
      });
      observer.observe(host);
      return () => observer.disconnect();
    }
    const applyViewport = () => applyWidth(window.innerWidth);
    window.addEventListener('resize', applyViewport);
    applyViewport();
    return () => window.removeEventListener('resize', applyViewport);
  }, []);

  const ownerStatus = status.ownerKey === ownerKey
    ? status
    : {
        ownerKey,
        state: ownedCachedSession ? 'refreshing' : 'loading',
        staleError: false,
      } satisfies PanelStatus;
  const currentStatus = ownedCachedSession && ownerStatus.state === 'loading'
    ? { ...ownerStatus, state: 'refreshing' as const }
    : ownerStatus;
  const currentLegacy = legacyResponse?.ownerKey === ownerKey
    ? legacyResponse.tree
    : null;
  const response: CrewTaskDetailResponse | null = currentStatus.state === 'empty'
    ? null
    : ownedCachedSession
      ? { session: ownedCachedSession }
      : currentLegacy;

  let content: React.ReactNode;
  if (!response && currentStatus.state === 'loading') {
    content = (
      <div data-testid="crew-session-loading" className="crew-session-placeholder" aria-busy="true">
        <PanelStyles />
        Loading crew session
      </div>
    );
  } else if (!response && currentStatus.state === 'empty') {
    content = (
      <div data-testid="crew-session-empty" className="crew-session-placeholder">
        <PanelStyles />
        No crew session is bound to this work item.
      </div>
    );
  } else if (!response && currentStatus.state === 'error') {
    content = (
      <div role="alert" data-testid="crew-session-error" className="crew-session-placeholder">
        <PanelStyles />
        Crew session details could not be loaded.{' '}
        <button type="button" className="crew-session-retry" onClick={() => void load(threadId, parentId)}>
          Retry
        </button>
      </div>
    );
  } else if (!response) {
    content = null;
  } else if ('session' in response) {
    content = (
      <SessionBand
        session={response.session}
        stacked={stacked}
        refreshing={currentStatus.state === 'refreshing'}
        staleError={currentStatus.staleError}
        sessionBandRef={sessionBandRef}
        onRetryFetch={() => void load(threadId, parentId)}
        onRetryBlockedWork={onRetryBlockedWork}
        onOpenResultArtifact={onOpenResultArtifact}
      />
    );
  } else {
    content = <LegacyCrewTree tree={response} />;
  }

  return (
    <div ref={hostRef} data-testid="crew-session-host" style={{ width: '100%', minWidth: 0 }}>
      {content}
    </div>
  );
}
