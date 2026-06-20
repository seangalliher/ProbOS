/** AD-1019d: department lockers — the operator surface for the AD-1019e
 *  department-locker authoring backend (the loop that closes #964).
 *
 *  A "locker" is a department's shared shelf of MCP tools: stock a tool (or a
 *  whole server) into a department and every agent in that department resolves
 *  ``source="department"`` for it (the AD-1019b 3-source resolver). This is the
 *  department-tier authoring surface — distinct from the per-agent grants in
 *  ``McpAgentAccess`` (no agent column here; the unit is the department).
 *
 *  Backend (AD-1019e, live):
 *    - ``GET    /api/mcp/departments/grants``               → active locker grants.
 *    - ``POST   /api/mcp/departments/{department}/tools`` {server_id,tool?,enabled}.
 *    - ``DELETE /api/mcp/departments/grants/{grant_id}``    → unstock.
 *  Department names come from the crew roster (``RosterAgent.department``); the
 *  server + tool dropdowns reuse the AD-1018 / AD-1019e server + tools endpoints.
 *
 *  HXI: inline SVG stroke icons (strokeWidth 1.5), amber active / dim inactive,
 *  NO emoji, a ``data-testid`` on every interactive element, honest-degrade (a
 *  GET 404 on the grants list means management disabled → the surface hides).
 */
import { useEffect, useState, useCallback } from 'react';
import { fetchRosterApi, type RosterAgent } from './McpAgentAccess';
import { fetchServersApi, type McpServer, type McpServersResult } from './McpServersPanel';
import { fetchServerToolsApi, type McpToolRiskResult } from './McpToolRisk';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';
const _RED = '#d05050';

// --------------------------------------------------------------------------- //
// Types — the AD-1019e department-grant shape (``_grant_public``).
// --------------------------------------------------------------------------- //
export interface DepartmentGrant {
  grant_id: string;
  department: string;
  tool_id: string;
  is_restriction: boolean;
  enabled: boolean;
}

export interface DepartmentGrantsResult {
  grants: DepartmentGrant[];
  /** True when GET 404 — management is disabled. */
  disabled?: boolean;
}

/** The stock body for ``POST /api/mcp/departments/{department}/tools``. */
export interface StockBody {
  server_id: string;
  tool?: string;
  enabled: boolean;
}

/** Injectable IO seam — every entry defaults to a real ``fetch`` below. */
export interface McpDepartmentLockersDeps {
  fetchGrants: () => Promise<DepartmentGrantsResult>;
  fetchRoster: () => Promise<RosterAgent[]>;
  fetchServers: () => Promise<McpServersResult>;
  fetchServerTools: (serverId: string) => Promise<McpToolRiskResult>;
  stock: (department: string, body: StockBody) => Promise<void>;
  unstock: (grantId: string) => Promise<void>;
}

// --------------------------------------------------------------------------- //
// Real API calls — locker-specific; roster / servers / tools are reused.
// --------------------------------------------------------------------------- //
export async function fetchGrantsApi(): Promise<DepartmentGrantsResult> {
  const resp = await fetch('/api/mcp/departments/grants');
  if (resp.status === 404) return { grants: [], disabled: true };
  if (!resp.ok) throw new Error(`mcp department grants fetch failed: ${resp.status}`);
  const d = await resp.json();
  return { grants: Array.isArray(d?.grants) ? d.grants : [] };
}

export async function stockApi(department: string, body: StockBody): Promise<void> {
  const resp = await fetch(`/api/mcp/departments/${encodeURIComponent(department)}/tools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`mcp stock failed: ${resp.status}`);
}

export async function unstockApi(grantId: string): Promise<void> {
  const resp = await fetch(`/api/mcp/departments/grants/${encodeURIComponent(grantId)}`, {
    method: 'DELETE',
  });
  if (!resp.ok) throw new Error(`mcp unstock failed: ${resp.status}`);
}

// --------------------------------------------------------------------------- //
// Shared styles.
// --------------------------------------------------------------------------- //
function btnStyle(active = true): React.CSSProperties {
  const c = active ? _AMBER : _DIM;
  return {
    fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 0.5,
    color: c, background: 'transparent', border: `1px solid ${c}`, borderRadius: 3,
    padding: '3px 9px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5,
  };
}

const fieldStyle: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: _TEXT,
  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: 3, padding: '4px 7px',
};

function distinctDepartments(roster: RosterAgent[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const a of roster) {
    const d = (a.department || '').trim();
    if (d && !seen.has(d)) { seen.add(d); out.push(d); }
  }
  out.sort();
  return out;
}

interface Props {
  deps?: Partial<McpDepartmentLockersDeps>;
}

export function McpDepartmentLockers({ deps }: Props) {
  const _fetchGrants = deps?.fetchGrants ?? fetchGrantsApi;
  const _fetchRoster = deps?.fetchRoster ?? fetchRosterApi;
  const _fetchServers = deps?.fetchServers ?? fetchServersApi;
  const _fetchServerTools = deps?.fetchServerTools ?? fetchServerToolsApi;
  const _stock = deps?.stock ?? stockApi;
  const _unstock = deps?.unstock ?? unstockApi;

  const [grants, setGrants] = useState<DepartmentGrant[] | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [error, setError] = useState(false);
  const [roster, setRoster] = useState<RosterAgent[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [serverTools, setServerTools] = useState<string[]>([]);

  // Stock-form selections.
  const [dept, setDept] = useState('');
  const [serverId, setServerId] = useState('');
  const [tool, setTool] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const reloadGrants = useCallback(async () => {
    try {
      const r = await _fetchGrants();
      setGrants(r.grants);
      setDisabled(r.disabled === true);
      setError(false);
    } catch {
      setError(true);
    }
  }, [_fetchGrants]);

  useEffect(() => {
    let alive = true;
    setGrants(null);
    setDisabled(false);
    setError(false);
    _fetchGrants()
      .then((r) => { if (alive) { setGrants(r.grants); setDisabled(r.disabled === true); } })
      .catch(() => { if (alive) setError(true); });
    _fetchRoster()
      .then((r) => { if (alive) setRoster(r); })
      .catch(() => { /* honest-degrade: empty department picker */ });
    _fetchServers()
      .then((r) => { if (alive) setServers(r.servers); })
      .catch(() => { /* honest-degrade: empty server picker */ });
    return () => { alive = false; };
  }, [_fetchGrants, _fetchRoster, _fetchServers]);

  // When the chosen server changes, (re)load its tools for the optional tool
  // dropdown — a blank tool stocks the whole server.
  useEffect(() => {
    let alive = true;
    setTool('');
    setServerTools([]);
    if (!serverId) return;
    _fetchServerTools(serverId)
      .then((r) => { if (alive) setServerTools(r.tools.map((t) => t.name)); })
      .catch(() => { /* honest-degrade: whole-server only */ });
    return () => { alive = false; };
  }, [serverId, _fetchServerTools]);

  const onStock = useCallback(async () => {
    setFormError(null);
    if (!dept || !serverId) {
      setFormError('Pick a department and a server.');
      return;
    }
    try {
      await _stock(dept, { server_id: serverId, tool: tool || undefined, enabled: true });
      setTool('');
      await reloadGrants();
    } catch {
      setFormError('Stock failed.');
    }
  }, [dept, serverId, tool, _stock, reloadGrants]);

  const onUnstock = useCallback(async (grantId: string) => {
    try {
      await _unstock(grantId);
      await reloadGrants();
    } catch { /* honest-degrade: leave list as-is */ }
  }, [_unstock, reloadGrants]);

  const departments = distinctDepartments(roster);

  // Group the locker grants by department for display.
  const byDept = new Map<string, DepartmentGrant[]>();
  for (const g of grants ?? []) {
    const list = byDept.get(g.department) ?? [];
    list.push(g);
    byDept.set(g.department, list);
  }
  const deptOrder = Array.from(byDept.keys()).sort();

  return (
    <div data-testid="mcp-lockers" style={{ fontFamily: "'JetBrains Mono', monospace", color: _TEXT }}>
      <div style={{ fontSize: 12, color: _AMBER, letterSpacing: 1, marginBottom: 4 }}>DEPARTMENT LOCKERS</div>
      <div style={{ fontSize: 10, color: _DIM, marginBottom: 12 }}>
        Stock an MCP tool (or a whole server) into a department's shared locker — every agent in that department inherits it.
      </div>

      {disabled ? (
        <div data-testid="mcp-lockers-disabled" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>
          MCP management is disabled.
        </div>
      ) : error ? (
        <div data-testid="mcp-lockers-error" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>
          Department lockers unavailable.
        </div>
      ) : grants === null ? (
        <div data-testid="mcp-lockers-loading" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>Loading lockers…</div>
      ) : (
        <>
          {/* Stock form. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
            <select
              data-testid="mcp-locker-dept-select"
              value={dept}
              onChange={(e) => setDept(e.target.value)}
              style={fieldStyle}
              aria-label="Department"
            >
              <option value="">Department…</option>
              {departments.map((d) => (<option key={d} value={d}>{d}</option>))}
            </select>
            <select
              data-testid="mcp-locker-server-select"
              value={serverId}
              onChange={(e) => setServerId(e.target.value)}
              style={fieldStyle}
              aria-label="Server"
            >
              <option value="">Server…</option>
              {servers.map((s) => (<option key={s.id} value={s.id}>{s.name}</option>))}
            </select>
            <select
              data-testid="mcp-locker-tool-select"
              value={tool}
              onChange={(e) => setTool(e.target.value)}
              style={fieldStyle}
              aria-label="Tool (blank = whole server)"
            >
              <option value="">Whole server</option>
              {serverTools.map((t) => (<option key={t} value={t}>{t}</option>))}
            </select>
            <button data-testid="mcp-locker-stock" onClick={onStock} style={btnStyle(!!dept && !!serverId)}>Stock</button>
          </div>
          {formError && (
            <div data-testid="mcp-locker-form-error" style={{ color: _RED, fontSize: 10, marginBottom: 10 }}>{formError}</div>
          )}

          {/* Locker list grouped by department. */}
          {grants.length === 0 ? (
            <div data-testid="mcp-lockers-empty" style={{ color: '#555568', fontSize: 11 }}>No tools stocked in any locker.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {deptOrder.map((d) => (
                <div key={d}>
                  <div style={{ fontSize: 11, color: '#40b890', letterSpacing: 0.5, marginBottom: 4 }}>{d}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {(byDept.get(d) ?? []).map((g) => (
                      <div
                        key={g.grant_id}
                        data-testid={`mcp-locker-grant-${g.grant_id}`}
                        style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid rgba(255,255,255,0.06)', borderLeft: `3px solid ${g.enabled ? '#40b890' : _RED}`, borderRadius: 4, padding: '5px 9px' }}
                      >
                        <span style={{ color: _TEXT, fontSize: 10, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.tool_id}</span>
                        {g.is_restriction && (
                          <span style={{ color: _RED, fontSize: 9 }}>restriction</span>
                        )}
                        <button
                          data-testid={`mcp-locker-unstock-${g.grant_id}`}
                          onClick={() => onUnstock(g.grant_id)}
                          style={{ ...btnStyle(false), color: _RED, borderColor: _RED }}
                          aria-label={`Unstock ${g.tool_id} from ${d}`}
                        >
                          Unstock
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default McpDepartmentLockers;
