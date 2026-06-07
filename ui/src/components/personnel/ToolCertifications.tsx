/**
 * AD-899: Tool certification management view — the admin console for AD-894.
 *
 * The asset/certification surface: browse the ship-wide tool catalog
 * (`GET /api/tools`), select a crew agent (`GET /api/crew/roster`), view their
 * active certifications (`GET /api/crew/{id}/tools`), grant a certification
 * (`POST /api/crew/{id}/tools`), and revoke one behind an explicit two-step
 * confirm (`DELETE /api/crew/{id}/tools/{grant_id}`).
 *
 * Framed as PQS-style qualification — the asset-management counterpart to the
 * personnel record. A grant is a Captain-authority privilege edit recorded as
 * an auditable ToolAccessGrant; revoke is reversible (soft, retained for
 * audit). No new consensus gate (Minimal Authority); the authority and audit
 * model live in the AD-894 backend.
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji.
 */

import { useState, useEffect, useCallback } from 'react';

interface CatalogTool {
  tool_id: string;
  name: string;
  tool_type: string;
  description: string;
  domain: string;
  department: string;
  enabled: boolean;
}

interface RosterEntry {
  agent_id: string;
  callsign?: string | null;
  post?: string | null;
  department?: string | null;
}

interface Certification {
  grant_id: string;
  tool_id: string;
  permission: string;
  is_restriction: boolean;
  reason: string;
  issued_by: string;
}

interface GrantForm {
  tool_id: string;
  permission: string;
  reason: string;
}

const PERMISSIONS = ['observe', 'read', 'write', 'full'];

const EMPTY_GRANT: GrantForm = {
  tool_id: '',
  permission: 'read',
  reason: '',
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

const fieldStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  color: '#c8c8d4',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(240,176,96,0.2)',
  borderRadius: 4,
  padding: '5px 8px',
};

const labelStyle: React.CSSProperties = {
  fontSize: 9,
  fontFamily: "'JetBrains Mono', monospace",
  letterSpacing: 1,
  color: '#8888a0',
  textTransform: 'uppercase',
  marginBottom: 3,
  display: 'block',
};

export default function ToolCertifications() {
  const [catalog, setCatalog] = useState<CatalogTool[]>([]);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [certifications, setCertifications] = useState<Certification[]>([]);
  const [grant, setGrant] = useState<GrantForm>(EMPTY_GRANT);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const refreshCatalog = useCallback(async () => {
    try {
      const resp = await fetch('/api/tools');
      if (!resp.ok) {
        setCatalog([]);
        return;
      }
      const data = await resp.json();
      setCatalog(Array.isArray(data?.tools) ? data.tools : []);
    } catch {
      setCatalog([]);
    }
  }, []);

  const refreshRoster = useCallback(async () => {
    try {
      const resp = await fetch('/api/crew/roster');
      if (!resp.ok) {
        setRoster([]);
        return;
      }
      const data = await resp.json();
      setRoster(Array.isArray(data?.crew) ? data.crew : []);
    } catch {
      setRoster([]);
    }
  }, []);

  const refreshCertifications = useCallback(async (agentId: string) => {
    if (!agentId) {
      setCertifications([]);
      return;
    }
    try {
      const resp = await fetch(`/api/crew/${encodeURIComponent(agentId)}/tools`);
      if (!resp.ok) {
        setCertifications([]);
        return;
      }
      const data = await resp.json();
      setCertifications(Array.isArray(data?.certifications) ? data.certifications : []);
    } catch {
      setCertifications([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.all([refreshCatalog(), refreshRoster()]);
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshCatalog, refreshRoster]);

  useEffect(() => {
    refreshCertifications(selectedAgentId);
    setConfirmRevokeId(null);
    setRowError(null);
  }, [selectedAgentId, refreshCertifications]);

  const submitGrant = useCallback(async () => {
    setGrantError(null);
    if (!selectedAgentId) {
      setGrantError('Select a crew member first.');
      return;
    }
    if (!grant.tool_id) {
      setGrantError('Tool is required.');
      return;
    }
    if (!grant.permission) {
      setGrantError('Permission is required.');
      return;
    }
    try {
      const resp = await fetch(`/api/crew/${encodeURIComponent(selectedAgentId)}/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_id: grant.tool_id,
          permission: grant.permission,
          reason: grant.reason,
        }),
      });
      if (!resp.ok) {
        let detail = 'Grant rejected.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setGrantError(detail);
        return;
      }
      setGrant(EMPTY_GRANT);
      await refreshCertifications(selectedAgentId);
    } catch {
      setGrantError('Grant failed.');
    }
  }, [selectedAgentId, grant, refreshCertifications]);

  const revoke = useCallback(async (grantId: string) => {
    setRowError(null);
    try {
      const resp = await fetch(
        `/api/crew/${encodeURIComponent(selectedAgentId)}/tools/${encodeURIComponent(grantId)}`,
        { method: 'DELETE' },
      );
      if (!resp.ok) {
        let detail = 'Revoke rejected.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setRowError(detail);
        return;
      }
      await refreshCertifications(selectedAgentId);
    } catch {
      setRowError('Revoke failed.');
    } finally {
      setConfirmRevokeId(null);
    }
  }, [selectedAgentId, refreshCertifications]);

  return (
    <div data-testid="tool-certifications" style={{ fontFamily: "'JetBrains Mono', monospace", color: '#c8c8d4' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 14,
          gap: 12,
        }}
      >
        <div style={{ fontSize: 13, letterSpacing: 1, color: '#f0b060' }}>TOOL QUALIFICATIONS</div>
        <select
          data-testid="tool-agent-select"
          value={selectedAgentId}
          onChange={(e) => setSelectedAgentId(e.target.value)}
          style={{ ...fieldStyle, width: 'auto', minWidth: 200 }}
        >
          <option value="">Select crew member…</option>
          {roster.map((r) => (
            <option key={r.agent_id} value={r.agent_id}>
              {(r.callsign || r.agent_id) + (r.post ? ` — ${r.post}` : '')}
            </option>
          ))}
        </select>
      </div>

      {/* Grant form */}
      <div
        data-testid="tool-grant-form"
        style={{
          border: '1px solid rgba(240,176,96,0.18)',
          borderRadius: 6,
          padding: 12,
          marginBottom: 16,
          background: 'rgba(255,255,255,0.02)',
        }}
      >
        <div style={{ fontSize: 11, color: '#a8a8b8', marginBottom: 10, letterSpacing: 0.5 }}>
          Certify a crew member on a ship tool (PQS qualification).
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10, marginBottom: 10 }}>
          <div>
            <label style={labelStyle}>Tool</label>
            <select
              data-testid="tool-grant-tool"
              value={grant.tool_id}
              onChange={(e) => setGrant({ ...grant, tool_id: e.target.value })}
              style={fieldStyle}
            >
              <option value="">Select tool…</option>
              {catalog.map((t) => (
                <option key={t.tool_id} value={t.tool_id}>
                  {t.name || t.tool_id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Permission</label>
            <select
              data-testid="tool-grant-permission"
              value={grant.permission}
              onChange={(e) => setGrant({ ...grant, permission: e.target.value })}
              style={fieldStyle}
            >
              {PERMISSIONS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ marginBottom: 10 }}>
          <label style={labelStyle}>Reason</label>
          <input
            data-testid="tool-grant-reason"
            value={grant.reason}
            onChange={(e) => setGrant({ ...grant, reason: e.target.value })}
            placeholder="Qualification rationale (optional)"
            style={fieldStyle}
          />
        </div>
        {grantError && (
          <div data-testid="tool-grant-error" style={{ fontSize: 11, color: '#d05050', marginBottom: 8 }}>
            {grantError}
          </div>
        )}
        <button data-testid="tool-grant-submit" onClick={submitGrant} style={chipStyle('#f0b060')}>
          Certify
        </button>
      </div>

      {/* Certification list */}
      {rowError && (
        <div data-testid="tool-row-error" style={{ fontSize: 11, color: '#d05050', marginBottom: 8 }}>
          {rowError}
        </div>
      )}
      {!selectedAgentId ? (
        <div style={{ fontSize: 11, color: '#8888a0', padding: '8px 0' }}>
          Select a crew member to view their tool qualifications.
        </div>
      ) : certifications.length === 0 ? (
        <div data-testid="tool-cert-empty" style={{ fontSize: 11, color: '#8888a0', padding: '8px 0' }}>
          No tool certifications.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {certifications.map((c) => {
            const accent = c.is_restriction ? '#d05050' : '#50b0a0';
            return (
              <div
                key={c.grant_id}
                data-testid={`tool-cert-${c.grant_id}`}
                style={{
                  border: `1px solid ${accent}40`,
                  borderLeft: `3px solid ${accent}`,
                  borderRadius: 5,
                  padding: '8px 12px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: '#c8c8d4' }}>
                    {c.tool_id}
                    <span style={{ ...chipStyle(accent), marginLeft: 8, cursor: 'default' }}>
                      {c.permission.toUpperCase()}
                    </span>
                    {c.is_restriction && (
                      <span style={{ ...chipStyle('#d05050'), marginLeft: 6, cursor: 'default' }}>
                        RESTRICTION
                      </span>
                    )}
                  </div>
                  {c.reason && (
                    <div style={{ fontSize: 10, color: '#8888a0', marginTop: 3 }}>{c.reason}</div>
                  )}
                </div>
                {confirmRevokeId === c.grant_id ? (
                  <button
                    data-testid={`tool-revoke-confirm-${c.grant_id}`}
                    onClick={() => revoke(c.grant_id)}
                    style={chipStyle('#d05050')}
                  >
                    Confirm revoke
                  </button>
                ) : (
                  <button
                    data-testid={`tool-revoke-${c.grant_id}`}
                    onClick={() => {
                      setConfirmRevokeId(c.grant_id);
                      setRowError(null);
                    }}
                    style={chipStyle('#d05050')}
                  >
                    Revoke
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
