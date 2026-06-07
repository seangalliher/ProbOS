/**
 * AD-901: Standing Orders & Directives management view.
 *
 * The governed edit surface for an agent's standing orders, rendered inside the
 * Service Record (AD-897) Standing Orders section. Two parts:
 *   1. The read-only four-tier composed orders (AD-893) — unchanged context,
 *      passed down from ServiceRecord.
 *   2. A Directives panel bound to AD-900: list the active + pending-approval
 *      directives for the agent, issue a Captain's order, approve a pending
 *      directive (the governed approval gate made visible), and revoke with a
 *      two-step confirm. Pending directives are amber/awaiting; governing
 *      actions are clearly marked.
 *
 * Read/write surface over the existing governed path — no new consensus gate;
 * the authorization + approval model lives in the AD-900 endpoints.
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji.
 */

import { useState, useEffect, useCallback } from 'react';

interface OrderTier {
  tier: string;
  source_file?: string | null;
  present: boolean;
  text: string;
}

interface Directive {
  id: string;
  directive_type: string;
  content: string;
  status: string;
  priority?: number;
  issued_by?: string;
  target_department?: string | null;
}

interface Props {
  agentId: string;
  tiers: OrderTier[];
}

const TIER_LABELS: Record<string, string> = {
  federation: 'Federation',
  ship: 'Ship',
  department: 'Department',
  agent: 'Agent',
};

const chipStyle = (color: string): React.CSSProperties => ({
  fontSize: 10,
  fontFamily: "'JetBrains Mono', monospace",
  letterSpacing: 0.5,
  color,
  background: 'transparent',
  border: `1px solid ${color}`,
  borderRadius: 3,
  padding: '3px 8px',
  cursor: 'pointer',
});

export default function StandingOrders({ agentId, tiers }: Props) {
  const [directives, setDirectives] = useState<Directive[]>([]);
  const [draft, setDraft] = useState('');
  const [priority, setPriority] = useState(5);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!agentId) return;
    try {
      const resp = await fetch(`/api/crew/${agentId}/directives`);
      if (!resp.ok) {
        setDirectives([]);
        return;
      }
      const data = await resp.json();
      setDirectives(Array.isArray(data?.directives) ? data.directives : []);
    } catch {
      setDirectives([]);
    }
  }, [agentId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refresh();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const issueOrder = useCallback(async () => {
    if (!draft.trim()) return;
    setError(null);
    try {
      const resp = await fetch(`/api/crew/${agentId}/directives`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft.trim(), priority }),
      });
      if (!resp.ok) {
        let detail = 'Order rejected.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setError(detail);
        return;
      }
      setDraft('');
      await refresh();
    } catch {
      setError('Order failed to dispatch.');
    }
  }, [agentId, draft, priority, refresh]);

  const approve = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`/api/crew/directives/${id}/approve`, { method: 'POST' });
      if (resp.ok) await refresh();
    } catch {
      /* honest-degrade: leave the queue as-is */
    }
  }, [refresh]);

  const revoke = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`/api/crew/directives/${id}`, { method: 'DELETE' });
      if (resp.ok) await refresh();
    } catch {
      /* honest-degrade */
    } finally {
      setConfirmRevokeId(null);
    }
  }, [refresh]);

  return (
    <div data-testid="standing-orders">
      {/* Part 1 — read-only four-tier composed orders (AD-893). */}
      {tiers.length === 0 ? (
        <div style={{ fontSize: 11, color: '#666680' }}>No standing orders.</div>
      ) : (
        tiers.map(t => (
          <div key={t.tier} data-testid={`sr-order-tier-${t.tier}`} style={{ margin: '6px 0' }}>
            <div style={{ fontSize: 10, color: t.present ? '#50b0a0' : '#666680', letterSpacing: 1 }}>
              {(TIER_LABELS[t.tier] || t.tier).toUpperCase()}
              {!t.present && ' \u2014 none'}
            </div>
            {t.present && t.text && (
              <div style={{ fontSize: 10, color: '#a8a8b8', whiteSpace: 'pre-wrap', marginTop: 2 }}>
                {t.text.length > 600 ? `${t.text.slice(0, 600)}\u2026` : t.text}
              </div>
            )}
          </div>
        ))
      )}

      {/* Part 2 — governed Directives panel (AD-900). */}
      <div data-testid="so-directives" style={{ marginTop: 16 }}>
        <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '4px 0 8px' }}>
          CAPTAIN'S DIRECTIVES
        </div>

        {directives.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680' }}>No active directives.</div>
        ) : (
          directives.map(d => {
            const pending = d.status === 'pending_approval';
            const accent = pending ? '#d0a030' : '#50b0a0';
            return (
              <div
                key={d.id}
                data-testid={`so-directive-${d.id}`}
                data-status={d.status}
                style={{
                  border: `1px solid ${pending ? 'rgba(208,160,48,0.45)' : 'rgba(80,176,160,0.25)'}`,
                  background: pending ? 'rgba(208,160,48,0.06)' : 'transparent',
                  borderRadius: 4,
                  padding: '8px 10px',
                  margin: '6px 0',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 9, letterSpacing: 1, color: accent }}>
                    {pending ? 'AWAITING APPROVAL' : 'ACTIVE'}
                  </span>
                  <span style={{ fontSize: 9, color: '#666680' }}>P{d.priority ?? 5}</span>
                </div>
                <div style={{ fontSize: 11, color: '#c8c8d4', margin: '4px 0', whiteSpace: 'pre-wrap' }}>
                  {d.content}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                  {pending && (
                    <button
                      type="button"
                      data-testid={`so-approve-${d.id}`}
                      onClick={() => approve(d.id)}
                      style={chipStyle('#50b0a0')}
                    >
                      Approve
                    </button>
                  )}
                  {confirmRevokeId === d.id ? (
                    <button
                      type="button"
                      data-testid={`so-revoke-confirm-${d.id}`}
                      onClick={() => revoke(d.id)}
                      style={chipStyle('#d05050')}
                    >
                      Confirm revoke
                    </button>
                  ) : (
                    <button
                      type="button"
                      data-testid={`so-revoke-${d.id}`}
                      onClick={() => setConfirmRevokeId(d.id)}
                      style={chipStyle('#8888a0')}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Issue a new Captain's order. */}
        <div style={{ marginTop: 12 }}>
          <textarea
            data-testid="so-issue-content"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Issue a Captain's order..."
            rows={2}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: '#c8c8d4',
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(240,176,96,0.2)',
              borderRadius: 4,
              padding: '6px 8px',
              resize: 'vertical',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
            <label style={{ fontSize: 10, color: '#8888a0' }}>Priority</label>
            <input
              type="number"
              data-testid="so-issue-priority"
              value={priority}
              min={1}
              max={10}
              onChange={e => setPriority(Number(e.target.value) || 5)}
              style={{
                width: 56,
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                color: '#c8c8d4',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(240,176,96,0.2)',
                borderRadius: 4,
                padding: '4px 6px',
              }}
            />
            <button
              type="button"
              data-testid="so-issue-submit"
              onClick={issueOrder}
              disabled={!draft.trim()}
              style={{
                ...chipStyle('#f0b060'),
                opacity: draft.trim() ? 1 : 0.4,
                cursor: draft.trim() ? 'pointer' : 'default',
                marginLeft: 'auto',
              }}
            >
              Issue Order
            </button>
          </div>
          {error && (
            <div data-testid="so-issue-error" style={{ fontSize: 10, color: '#d05050', marginTop: 4 }}>
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
