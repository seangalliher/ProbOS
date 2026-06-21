/** AD-1021c: CoEditPanel — the agent co-editing / presence strip for the Monaco
 *  workstation (HXI #11). NOT an IDE: no CRDT, no operational transform, no live
 *  char-by-char editing, no multi-cursor. A crew agent proposes a FULL
 *  replacement body for one file in this agent's AD-997 workspace folder; the
 *  human Previews it (loads into the scratch editor), Accepts it (a governed
 *  AD-1021b write through consensus — reusing `saveWorkspaceFile`, never a raw
 *  write), or Dismisses it. Agents never silently write.
 *
 *  Presence reuses AD-930: `present` = the owner ∪ the distinct suggestion
 *  authors, each rendered with a `PresenceDot` driven by the ambient presence
 *  map. NO new realtime transport.
 *
 *  HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5), amber active / dim
 *  inactive, NO emoji, a data-testid on every interactive element. Every
 *  data dep (presence/agents + the fetchers) is injectable so the panel is
 *  fully testable with no fetch mock and no token; all paths honest-degrade.
 */
import { useEffect, useMemo, useState } from 'react';
import { PresenceDot } from '../presence/PresenceDot';
import type { Agent, CrewPresenceMap, PresenceState } from '../../store/types';
import {
  listWorkspaceSuggestions,
  dismissWorkspaceSuggestion,
  type WorkspaceSuggestion,
} from './workspaceSuggestionsApi';
import { saveWorkspaceFile } from './workspaceFileApi';
import type { WorkspaceSaveResult } from './workspaceFileApi';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';
const _GREEN = '#6fcf97';
const _RED = '#d98a8a';

const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconPreview({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M2 12 S5 5 12 5 S22 12 22 12 S19 19 12 19 S2 12 2 12 Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconAccept({ color = _GREEN }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M5 13 L10 18 L19 6" />
    </svg>
  );
}

function IconDismiss({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M6 6 L18 18 M18 6 L6 18" />
    </svg>
  );
}

/** AD-1021c: all data deps injectable (DD-1). `listSuggestions`/`dismiss`/
 *  `saveFile` default to the same-origin, no-token helpers; `presence`/
 *  `agentsById` come from the AD-930 store (passed by the host). */
export type CoEditPanelProps = {
  ownerId: string;
  path: string;
  presence: CrewPresenceMap;
  agentsById: Map<string, Agent>;
  onPreview?: (content: string) => void;
  listSuggestions?: (agentId: string, path: string) => Promise<WorkspaceSuggestion[]>;
  dismissSuggestion?: (agentId: string, suggestionId: string) => Promise<boolean>;
  saveFile?: (agentId: string, path: string, content: string) => Promise<WorkspaceSaveResult>;
};

function _label(id: string, agentsById: Map<string, Agent>): string {
  const a = agentsById.get(id);
  return a?.callsign || a?.displayName || id;
}

export function CoEditPanel({
  ownerId,
  path,
  presence,
  agentsById,
  onPreview,
  listSuggestions = listWorkspaceSuggestions,
  dismissSuggestion = dismissWorkspaceSuggestion,
  saveFile = saveWorkspaceFile,
}: CoEditPanelProps): React.ReactElement {
  const [suggestions, setSuggestions] = useState<WorkspaceSuggestion[]>([]);
  const [banner, setBanner] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Fetch suggestions for the current (owner, path). Honest-degrade: an empty
  // path lists nothing; a failed fetch yields []. The cancelled flag prevents a
  // state update after unmount / a stale path resolving late.
  useEffect(() => {
    const p = path.trim();
    if (!ownerId || !p) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await listSuggestions(ownerId, p);
        if (!cancelled) setSuggestions(list);
      } catch {
        if (!cancelled) setSuggestions([]);
      }
    })();
    return () => { cancelled = true; };
  }, [ownerId, path, listSuggestions]);

  // present = owner ∪ distinct suggestion authors (owner first, first-seen order).
  const present = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    if (ownerId) { out.push(ownerId); seen.add(ownerId); }
    for (const s of suggestions) {
      if (s.author_id && !seen.has(s.author_id)) {
        out.push(s.author_id);
        seen.add(s.author_id);
      }
    }
    return out;
  }, [ownerId, suggestions]);

  const onAccept = async (s: WorkspaceSuggestion): Promise<void> => {
    setBusyId(s.id);
    setBanner(null);
    try {
      const r = await saveFile(ownerId, s.path, s.content);
      if (r.outcome === 'committed') {
        setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
        setBanner(`accepted ${s.path}`);
      } else if (r.outcome === 'disabled') {
        setBanner('workspace write disabled');
      } else {
        setBanner(`refused: ${r.consensus_outcome ?? 'rejected'}`);
      }
    } catch (e) {
      setBanner(`refused: ${e instanceof Error ? e.message : 'error'}`);
    } finally {
      setBusyId(null);
    }
  };

  const onDismiss = async (s: WorkspaceSuggestion): Promise<void> => {
    setBusyId(s.id);
    try {
      const ok = await dismissSuggestion(ownerId, s.id);
      if (ok) {
        setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
      } else {
        setBanner('dismiss failed');
      }
    } catch {
      setBanner('dismiss failed');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div
      data-testid="coedit-panel"
      style={{
        display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 12px',
        borderTop: '1px solid rgba(255,255,255,0.08)', color: _TEXT,
      }}
    >
      {/* Presence strip — owner ∪ suggestion authors (AD-930 dots). */}
      <div
        data-testid="workstation-presence-strip"
        style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}
      >
        <span style={{ fontSize: 10, color: _DIM, letterSpacing: 1 }}>PRESENT</span>
        {present.map((id) => {
          const state: PresenceState = presence[id] ?? 'offline';
          return (
            <span
              key={id}
              data-testid={`coedit-present-${id}`}
              data-presence={state}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}
            >
              <PresenceDot state={state} size={8} />
              <span style={{ color: id === ownerId ? _AMBER : _TEXT }}>{_label(id, agentsById)}</span>
            </span>
          );
        })}
      </div>

      {/* Honest-degrade banner (accept committed / refused / disabled / dismiss). */}
      {banner && (
        <div
          data-testid="coedit-banner"
          role="status"
          style={{
            fontSize: 11, letterSpacing: 0.3,
            color: banner.startsWith('accepted') ? _GREEN
              : banner.startsWith('refused') ? _RED
              : _DIM,
          }}
        >
          {banner}
        </div>
      )}

      {/* Suggestions list — Preview / Accept / Dismiss per proposal. */}
      {suggestions.length === 0 ? (
        <div data-testid="coedit-empty" style={{ fontSize: 11, color: _DIM }}>
          No pending suggestions
        </div>
      ) : (
        <div data-testid="coedit-suggestions" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {suggestions.map((s) => {
            const busy = busyId === s.id;
            const who = s.author_callsign || _label(s.author_id, agentsById);
            return (
              <div
                key={s.id}
                data-testid={`coedit-suggestion-${s.id}`}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '4px 6px',
                  border: '1px solid #33334a', borderRadius: 4,
                }}
              >
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>
                  <span style={{ color: _AMBER }}>{who}</span>
                  <span style={{ color: _DIM }}> · {s.path}</span>
                  {s.note && <span style={{ color: _DIM }}> — {s.note}</span>}
                </span>
                <button
                  data-testid={`coedit-preview-${s.id}`}
                  onClick={() => onPreview?.(s.content)}
                  aria-label={`Preview suggestion from ${who}`}
                  style={_btn(_DIM, false)}
                >
                  <IconPreview />Preview
                </button>
                <button
                  data-testid={`coedit-accept-${s.id}`}
                  onClick={() => { void onAccept(s); }}
                  disabled={busy}
                  aria-label={`Accept suggestion from ${who}`}
                  style={_btn(_GREEN, busy)}
                >
                  <IconAccept color={busy ? _DIM : _GREEN} />Accept
                </button>
                <button
                  data-testid={`coedit-dismiss-${s.id}`}
                  onClick={() => { void onDismiss(s); }}
                  disabled={busy}
                  aria-label={`Dismiss suggestion from ${who}`}
                  style={_btn(_DIM, busy)}
                >
                  <IconDismiss />Dismiss
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function _btn(color: string, busy: boolean): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 8px',
    border: '1px solid #33334a', borderRadius: 4, background: 'transparent',
    color: busy ? _DIM : color, cursor: busy ? 'default' : 'pointer', fontSize: 11,
    opacity: busy ? 0.5 : 1,
  };
}
