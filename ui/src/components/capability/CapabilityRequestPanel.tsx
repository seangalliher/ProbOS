/* Capability-request decision card — alert-driven HXI surface (AD-857)
 *
 * The Captain's approve/deny surface for pending capability requests filed by
 * blocked agents (the BLOCKED -> request -> approve/deny loop). Fetch-driven:
 * polls /api/capability-requests?status=pending and renders one card per
 * request. Approve/Deny POST to /api/capability-requests/{id}/decide.
 *
 * HXI Design Principle #3: inline SVG glyphs only (no emoji), stroke-based,
 * amber active / dim inactive. Principle #9: department-colored context bar.
 */

import { useState, useEffect, useCallback } from 'react';

/* BF-723: type-only — the panel stays store-free at runtime (it is fetch-driven
 * and mountable standalone). Importing the shape keeps the callback contract
 * and the store's reconciliation key from drifting apart. */
import type { DecidedApproval } from '../../store/useStore';

// ── Capability request shape (mirrors the GET serializer) ──────────
export interface CapabilityRequestView {
  id: string;
  agent_id: string;
  kind: string;
  target: string;
  rationale: string;
  work_item_id: string | null;
  status: string;
  created_at: number;
  decided_at: number | null;
  decided_by: string;
  decision_reason: string;
}

// ── Department -> context color (Principle #9, LCARS departments) ──
// No prior constant existed; defined here per AD-857.
const DEPARTMENT_COLORS: Record<string, string> = {
  science: '#4fd0c0',
  engineering: '#e08040',
  medical: '#60c070',
  security: '#d05050',
  command: '#f0b060',
};
const DEFAULT_DEPARTMENT_COLOR = '#666680';

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';
const DENY_RED = '#d05050';

/* BF-710: the module docstring above always claimed this panel polls; it did
 * not. `load` is a stable useCallback, so the mount effect ran exactly once and
 * a request filed afterwards never appeared. 10s matches the established
 * panel-list refresh cadence (CrewRosterPanel.tsx, bridge/FullSystem.tsx,
 * bridge/BridgeSystem.tsx all use 10000). */
const POLL_INTERVAL_MS = 10000;

function departmentColor(kind: string): string {
  // Map the request kind to a department context color. grant/install lean
  // engineering; build leans engineering too — all use the engineering hue
  // unless a future kind maps elsewhere. Falls back to the neutral dim.
  const key = (kind || '').toLowerCase();
  if (key === 'grant' || key === 'install' || key === 'build') {
    return DEPARTMENT_COLORS.engineering;
  }
  return DEPARTMENT_COLORS[key] || DEFAULT_DEPARTMENT_COLOR;
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
  req: CapabilityRequestView;
  onDecide: (id: string, approve: boolean, reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accent = departmentColor(req.kind);

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
      data-testid="capability-request-card"
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
            {req.kind}
          </span>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#c8d0e0' }}>
            {req.target}
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#9098b0', lineHeight: 1.35, marginBottom: 4 }}>
          {req.rationale || <em style={{ color: DIM }}>no rationale provided</em>}
        </div>
        <div style={{ fontSize: 10, color: DIM, marginBottom: 6 }}>
          {req.work_item_id
            ? <span data-testid="linked-work-item">work item {req.work_item_id.slice(0, 12)}</span>
            : <span>unlinked</span>}
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
/* AD-1201: `onDecided` lets the host (the approvals centre) re-read the shared
 * pending-approvals slice the moment a decision lands, so the Bridge section and
 * the BRIDGE badge do not show a stale count until the next poll. Optional —
 * omitted, this panel behaves exactly as before.
 *
 * BF-723: it now says WHAT was decided. It used to take no arguments, so the
 * decision existed only in this component's `requests` state and the shared
 * slice could only be told "refresh" — leaving a failing or late GET free to
 * put the decided row straight back while the card stayed gone from here. The
 * queue is this panel's own identity: it is the panel that talks to
 * /api/capability-requests, so it is the one that knows. */
export default function CapabilityRequestPanel(
  { onDecided }: { onDecided?: (decided: DecidedApproval) => void } = {},
) {
  const [requests, setRequests] = useState<CapabilityRequestView[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const resp = await fetch('/api/capability-requests?status=pending');
      if (!resp.ok) return;
      const data = await resp.json();
      setRequests(Array.isArray(data.requests) ? data.requests : []);
    } catch {
      // Tier-1 swallow: a transient fetch failure leaves the prior list shown.
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { void load(); }, POLL_INTERVAL_MS);
    return () => { window.clearInterval(timer); };
  }, [load]);

  const onDecide = useCallback(async (id: string, approve: boolean, reason: string) => {
    const resp = await fetch(`/api/capability-requests/${id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve, reason }),
    });
    if (!resp.ok) {
      throw new Error(`decision failed (${resp.status})`);
    }
    // Remove the decided request from the pending list.
    setRequests(prev => prev.filter(r => r.id !== id));
    onDecided?.({ queue: 'capability', id });
  }, [onDecided]);

  if (loaded && requests.length === 0) {
    return null;
  }

  return (
    <div data-testid="capability-request-panel" style={{ padding: '8px 0' }}>
      <div style={{
        fontSize: 10, textTransform: 'uppercase', letterSpacing: 1,
        color: ACTIVE_AMBER, fontWeight: 700, marginBottom: 6, padding: '0 2px',
      }}>
        Capability Requests
      </div>
      {requests.map(req => (
        <RequestCard key={req.id} req={req} onDecide={onDecide} />
      ))}
    </div>
  );
}
