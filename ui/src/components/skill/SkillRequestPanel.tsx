/* Skill-request decision card — alert-driven HXI surface (AD-908)
 *
 * The Captain's approve/deny surface for pending crew skill-acquisition
 * requests (the AD-906 requested -> approved|denied -> in_training -> completed
 * loop). Fetch-driven: polls /api/skill-requests?status=pending and renders one
 * card per request. Approve/Deny POST to /api/skill-requests/{id}/decide.
 *
 * Structurally mirrors CapabilityRequestPanel (AD-857). HXI Design Principle #3:
 * inline SVG glyphs only (no emoji), stroke-based, amber active / dim inactive.
 * Principle #9: source-colored context bar. Deps-injectable: an optional
 * fetchImpl prop (defaults to the global fetch) keeps the panel testable
 * without global stubbing.
 */

import { useState, useEffect, useCallback } from 'react';

// ── Skill request shape (mirrors the GET serializer) ───────────────
export interface SkillRequestView {
  id: string;
  agent_id: string;
  skill_id: string;
  skill_label: string;
  source: string;
  justification: string;
  status: string;
  linked_simulation_id: string | null;
  created_at: number;
  decided_at: number | null;
  decided_by: string;
  decision_reason: string;
  pre_metric: number | null;
  post_metric: number | null;
}

type FetchImpl = typeof fetch;

// ── Source -> context color (Principle #9, LCARS departments) ──────
// Who filed the request maps to a department context hue.
const SOURCE_COLORS: Record<string, string> = {
  self: '#4fd0c0',       // science — the agent's own growth
  counselor: '#60c070',  // medical — Counselor-filed
  chief: '#e08040',      // engineering — Department-Chief-filed
};
const DEFAULT_SOURCE_COLOR = '#666680';

// ── Status -> badge color ──────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  requested: '#f0b060',
  approved: '#4fd0c0',
  denied: '#d05050',
  in_training: '#8090e0',
  completed: '#60c070',
};

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';
const DENY_RED = '#d05050';

function sourceColor(source: string): string {
  const key = (source || '').toLowerCase();
  return SOURCE_COLORS[key] || DEFAULT_SOURCE_COLOR;
}

function statusColor(status: string): string {
  const key = (status || '').toLowerCase();
  return STATUS_COLORS[key] || DIM;
}

// ── Inline SVG glyphs (stroke-based, no emoji) ─────────────────────
function CheckGlyph({ color }: { color: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

function CrossGlyph({ color }: { color: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

// ── Single request card ────────────────────────────────────────────
function RequestCard({ req, onDecide }: {
  req: SkillRequestView;
  onDecide: (id: string, approve: boolean, reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accent = sourceColor(req.source);

  const decide = useCallback(async (approve: boolean) => {
    if (!approve && !reason.trim()) {
      setError('A reason is required to deny.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onDecide(req.id, approve, reason.trim());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Decision failed.');
      setBusy(false);
    }
  }, [onDecide, req.id, reason]);

  return (
    <div
      data-testid="skill-request-card"
      style={{
        marginBottom: 8, borderRadius: 6, overflow: 'hidden',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderLeft: `3px solid ${accent}`,
      }}
    >
      <div style={{ padding: '9px 11px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{
            fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5,
            color: accent, fontWeight: 700,
          }}>
            {req.source}
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#c8d0e0' }}>
            {req.skill_label || req.skill_id}
          </span>
          <span
            data-testid="skill-request-status"
            style={{
              marginLeft: 'auto', fontSize: 9, textTransform: 'uppercase',
              letterSpacing: 0.5, color: statusColor(req.status), fontWeight: 700,
            }}
          >
            {req.status}
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#9098b0', lineHeight: 1.35, marginBottom: 4 }}>
          {req.justification || <em style={{ color: DIM }}>no justification provided</em>}
        </div>
        <div style={{ fontSize: 10, color: DIM, marginBottom: 6 }}>
          {req.linked_simulation_id
            ? <span data-testid="linked-simulation">simulation {req.linked_simulation_id.slice(0, 12)}</span>
            : <span>agent {req.agent_id.slice(0, 12)}</span>}
        </div>

        <input
          type="text"
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="Reason (required to deny)"
          aria-label="decision reason"
          disabled={busy}
          style={{
            width: '100%', boxSizing: 'border-box', marginBottom: 7,
            padding: '5px 7px', fontSize: 11, borderRadius: 4,
            background: 'rgba(0,0,0,0.25)', color: '#c8d0e0',
            border: '1px solid rgba(255,255,255,0.1)',
          }}
        />

        {error && (
          <div role="alert" style={{ fontSize: 10, color: DENY_RED, marginBottom: 6 }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide(true)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
              background: 'rgba(240,176,96,0.12)', color: ACTIVE_AMBER,
              border: `1px solid ${ACTIVE_AMBER}55`,
            }}
          >
            <CheckGlyph color={ACTIVE_AMBER} /> Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide(false)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 10px', fontSize: 11, borderRadius: 4, cursor: 'pointer',
              background: 'rgba(208,80,80,0.1)', color: DENY_RED,
              border: `1px solid ${DENY_RED}55`,
            }}
          >
            <CrossGlyph color={DENY_RED} /> Deny
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────────────
export default function SkillRequestPanel({ fetchImpl }: { fetchImpl?: FetchImpl } = {}) {
  const doFetch: FetchImpl = fetchImpl ?? ((...args) => fetch(...args));
  const [requests, setRequests] = useState<SkillRequestView[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await doFetch('/api/skill-requests?status=pending');
      if (!resp.ok) return;
      const data = await resp.json();
      setRequests(Array.isArray(data.requests) ? data.requests : []);
    } catch {
      // Tier-1 swallow: a transient fetch failure leaves the prior list shown.
    } finally {
      setLoaded(true);
    }
  }, [doFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  const onDecide = useCallback(async (id: string, approve: boolean, reason: string) => {
    const resp = await doFetch(`/api/skill-requests/${id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve, reason }),
    });
    if (!resp.ok) {
      throw new Error(`decision failed (${resp.status})`);
    }
    // Remove the decided request from the pending list.
    setRequests(prev => prev.filter(r => r.id !== id));
  }, [doFetch]);

  if (loaded && requests.length === 0) {
    return null;
  }

  return (
    <div data-testid="skill-request-panel" style={{ padding: '8px 0' }}>
      <div style={{
        fontSize: 10, textTransform: 'uppercase', letterSpacing: 1,
        color: ACTIVE_AMBER, fontWeight: 700, marginBottom: 6, padding: '0 2px',
      }}>
        Skill Requests
      </div>
      {requests.map(req => (
        <RequestCard key={req.id} req={req} onDecide={onDecide} />
      ))}
    </div>
  );
}
