/**
 * AD-1010: Role Picker — the Ship's Office surface for the role-template
 * framework (AD-1009 backend).
 *
 * Browse role templates (`GET /api/crew/roles`): each role's post title /
 * department, required skills, the tools those skills resolve to, and the mesh
 * capabilities the role serves. Then apply a role's skill+tool template to a
 * crew agent (`POST /api/crew/{id}/apply-role`) — "use this role as a starting
 * template," after which per-agent grants/restrictions (AD-1007/1008/909a)
 * override it. Applying is additive + reversible and never clobbers a per-agent
 * override (the AD-889 commission guard, agent-precedence).
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji.
 */

import { useState, useEffect, useCallback } from 'react';

interface RoleSkill {
  id: string;
  min_proficiency: number;
}

interface RoleView {
  role_id: string;
  agent_type: string;
  callsign: string;
  title: string;
  department: string;
  skills: RoleSkill[];
  tools: string[];
  capabilities: string[];
}

interface RosterEntry {
  agent_id: string;
  callsign?: string | null;
  post?: string | null;
  department?: string | null;
}

interface ApplyResult {
  applied_role: string;
  agent_type: string;
  skills_acquired: string[];
  tools_granted: string[];
}

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  counseling: '#a070d0',
  operations: '#d0a030',
};

function deptColor(dept: string): string {
  return DEPT_COLORS[(dept || '').toLowerCase()] || '#8888a0';
}

const chipStyle = (color: string, clickable = true): React.CSSProperties => ({
  fontSize: 10,
  fontFamily: "'JetBrains Mono', monospace",
  letterSpacing: 0.5,
  color,
  background: 'transparent',
  border: `1px solid ${color}`,
  borderRadius: 3,
  padding: '3px 8px',
  cursor: clickable ? 'pointer' : 'default',
});

const tagStyle = (color: string): React.CSSProperties => ({
  fontSize: 9,
  fontFamily: "'JetBrains Mono', monospace",
  color,
  border: `1px solid ${color}55`,
  borderRadius: 3,
  padding: '1px 6px',
  marginRight: 4,
  marginBottom: 4,
  display: 'inline-block',
});

const fieldStyle: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  color: '#c8c8d4',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(240,176,96,0.2)',
  borderRadius: 4,
  padding: '5px 8px',
};

export interface RolePickerProps {
  /** Optional injected fetchers (tests). Default to the real API. */
  deps?: {
    fetchRoles?: () => Promise<RoleView[]>;
    fetchRoster?: () => Promise<RosterEntry[]>;
    applyRole?: (agentId: string, roleId: string) => Promise<ApplyResult | null>;
  };
}

async function fetchRolesApi(): Promise<RoleView[]> {
  const resp = await fetch('/api/crew/roles');
  if (!resp.ok) return [];
  const data = await resp.json();
  return Array.isArray(data?.roles) ? data.roles : [];
}

async function fetchRosterApi(): Promise<RosterEntry[]> {
  const resp = await fetch('/api/crew/roster');
  if (!resp.ok) return [];
  const data = await resp.json();
  return Array.isArray(data?.crew) ? data.crew : [];
}

async function applyRoleApi(agentId: string, roleId: string): Promise<ApplyResult | null> {
  const resp = await fetch(`/api/crew/${encodeURIComponent(agentId)}/apply-role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role_id: roleId }),
  });
  if (!resp.ok) return null;
  return resp.json();
}

export default function RolePicker({ deps }: RolePickerProps = {}) {
  const _fetchRoles = deps?.fetchRoles ?? fetchRolesApi;
  const _fetchRoster = deps?.fetchRoster ?? fetchRosterApi;
  const _applyRole = deps?.applyRole ?? applyRoleApi;

  const [roles, setRoles] = useState<RoleView[]>([]);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busyRole, setBusyRole] = useState<string | null>(null);
  const [result, setResult] = useState<{ roleId: string; res: ApplyResult } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [r, c] = await Promise.all([_fetchRoles(), _fetchRoster()]);
      if (!alive) return;
      setRoles(r);
      setRoster(c);
    })();
    return () => { alive = false; };
  }, [_fetchRoles, _fetchRoster]);

  const apply = useCallback(async (roleId: string) => {
    setError(null);
    setResult(null);
    if (!selectedAgentId) {
      setError('Select a crew member to apply the role to.');
      return;
    }
    setBusyRole(roleId);
    try {
      const res = await _applyRole(selectedAgentId, roleId);
      if (res) {
        setResult({ roleId, res });
      } else {
        setError('Apply failed.');
      }
    } catch {
      setError('Apply failed.');
    } finally {
      setBusyRole(null);
    }
  }, [selectedAgentId, _applyRole]);

  return (
    <div data-testid="role-picker" style={{ fontFamily: "'JetBrains Mono', monospace", color: '#c8c8d4' }}>
      <div style={{ fontSize: 11, color: '#a8a8b8', marginBottom: 10, letterSpacing: 0.5 }}>
        Apply a role as a starting template (skills + tools). Per-agent grants and
        restrictions override the role.
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: 9, letterSpacing: 1, color: '#8888a0', textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>
          Apply to crew member
        </label>
        <select
          data-testid="role-agent-select"
          value={selectedAgentId}
          onChange={(e) => { setSelectedAgentId(e.target.value); setResult(null); setError(null); }}
          style={{ ...fieldStyle, minWidth: 240 }}
        >
          <option value="">Select crew member…</option>
          {roster.map((r) => (
            <option key={r.agent_id} value={r.agent_id}>
              {r.callsign || r.agent_id}{r.post ? ` — ${r.post}` : ''}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div data-testid="role-error" style={{ fontSize: 11, color: '#d05050', marginBottom: 8 }}>
          {error}
        </div>
      )}

      {roles.length === 0 ? (
        <div data-testid="role-empty" style={{ fontSize: 11, color: '#8888a0', padding: '8px 0' }}>
          No roles available.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {roles.map((role) => {
            const accent = deptColor(role.department);
            const isOpen = expanded === role.role_id;
            return (
              <div
                key={role.role_id}
                data-testid={`role-${role.role_id}`}
                style={{
                  border: `1px solid ${accent}40`,
                  borderLeft: `3px solid ${accent}`,
                  borderRadius: 5,
                  padding: '8px 12px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                  <button
                    data-testid={`role-expand-${role.role_id}`}
                    onClick={() => setExpanded(isOpen ? null : role.role_id)}
                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', color: '#c8c8d4', padding: 0 }}
                  >
                    <span style={{ fontSize: 12 }}>{role.title || role.agent_type}</span>
                    {role.department && (
                      <span style={{ ...chipStyle(accent, false), marginLeft: 8 }}>
                        {role.department.toUpperCase()}
                      </span>
                    )}
                    <span style={{ fontSize: 9, color: '#8888a0', marginLeft: 8 }}>
                      {role.skills.length} skills · {role.tools.length} tools · {role.capabilities.length} caps
                    </span>
                  </button>
                  <button
                    data-testid={`role-apply-${role.role_id}`}
                    onClick={() => apply(role.role_id)}
                    disabled={busyRole === role.role_id}
                    style={chipStyle('#f0b060')}
                  >
                    {busyRole === role.role_id ? 'Applying…' : 'Apply'}
                  </button>
                </div>

                {isOpen && (
                  <div data-testid={`role-detail-${role.role_id}`} style={{ marginTop: 8 }}>
                    {role.skills.length > 0 && (
                      <div style={{ marginBottom: 6 }}>
                        <div style={{ fontSize: 9, color: '#8888a0', marginBottom: 3 }}>SKILLS</div>
                        <div>{role.skills.map((s) => <span key={s.id} style={tagStyle('#50b0a0')}>{s.id}</span>)}</div>
                      </div>
                    )}
                    {role.tools.length > 0 && (
                      <div style={{ marginBottom: 6 }}>
                        <div style={{ fontSize: 9, color: '#8888a0', marginBottom: 3 }}>TOOLS</div>
                        <div>{role.tools.map((t) => <span key={t} style={tagStyle('#f0b060')}>{t}</span>)}</div>
                      </div>
                    )}
                    {role.capabilities.length > 0 && (
                      <div style={{ marginBottom: 2 }}>
                        <div style={{ fontSize: 9, color: '#8888a0', marginBottom: 3 }}>CAPABILITIES (SERVES)</div>
                        <div>{role.capabilities.map((c) => <span key={c} style={tagStyle('#a070d0')}>{c}</span>)}</div>
                      </div>
                    )}
                  </div>
                )}

                {result && result.roleId === role.role_id && (
                  <div data-testid={`role-result-${role.role_id}`} style={{ marginTop: 8, fontSize: 10, color: '#50b0a0' }}>
                    Applied — {result.res.skills_acquired.length} skills, {result.res.tools_granted.length} tools granted.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export { fetchRolesApi, fetchRosterApi, applyRoleApi };
