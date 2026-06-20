/** AD-1019a: per-agent / per-tool MCP enablement — the operator surface for the
 *  AD-1019 enablement backend.
 *
 *  For a single MCP server, an operator can enable/disable it per crew agent
 *  (server-wide) AND enable/disable each individual tool the server exposes.
 *  Mounted as an expandable "Agent access" section inside each ``McpServersPanel``
 *  server row (so the panel diff stays small and this stays self-contained).
 *
 *  Backend (AD-1019, live):
 *    - ``GET  /api/crew/roster``                                  → crew agents.
 *    - ``GET  /api/mcp/servers/{id}/tools``                       → server tools.
 *    - ``GET  /api/mcp/servers/{id}/agents/{aid}/access``         → resolved access.
 *    - ``POST /api/mcp/servers/{id}/agents/{aid}`` {enabled,tool?}→ grant/restrict.
 *    - ``DELETE /api/mcp/servers/{id}/agents/{aid}?tool=``        → revert to default.
 *
 *  Lazy by design: the roster can be ~100 agents and ``/access`` re-enumerates the
 *  server's tools (a live bridge call) on every request, so per-agent access is
 *  only fetched when its row is expanded — never eagerly for the whole roster.
 *
 *  HXI: inline SVG stroke icons (strokeWidth 1.5), amber active / dim inactive,
 *  NO emoji, a ``data-testid`` on every interactive element, honest-degrade
 *  (a fetch failure shows inline error text; a GET 404 means management disabled).
 */
import { useEffect, useState, useCallback } from 'react';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';
const _RED = '#d05050';

// --------------------------------------------------------------------------- //
// Types — the AD-1019 endpoint shapes.
// --------------------------------------------------------------------------- //
/** A crew agent from ``GET /api/crew/roster`` (``.crew[]``). */
export interface RosterAgent {
  agent_id: string;
  agent_type?: string;
  callsign?: string;
  post?: string | null;
  department?: string | null;
}

/** One tool the server exposes (``GET /api/mcp/servers/{id}/tools``). */
export interface McpToolInfo {
  name: string;
  description?: string;
}

export interface McpToolsResult {
  tools: McpToolInfo[];
  count: number;
  error?: string;
  /** True when GET 404 — management is disabled (or the server vanished). */
  disabled?: boolean;
}

/** A tool's resolved access for one agent (source ∈ tool|server|department|default). */
export interface McpToolAccess {
  name: string;
  enabled: boolean;
  source: string;
}

export interface McpAgentAccessResult {
  server_enabled: boolean;
  tools: McpToolAccess[];
  error?: string;
}

/** The mutate body for ``POST /api/mcp/servers/{id}/agents/{aid}``. */
export interface SetAccessBody {
  enabled: boolean;
  tool?: string;
}

/** Injectable IO seam — every entry defaults to a real ``fetch`` below, with the
 *  component's ``serverId`` prop bound into the default implementations. */
export interface McpAgentAccessDeps {
  fetchRoster: () => Promise<RosterAgent[]>;
  fetchTools: () => Promise<McpToolsResult>;
  fetchAgentAccess: (agentId: string) => Promise<McpAgentAccessResult>;
  setAccess: (agentId: string, body: SetAccessBody) => Promise<void>;
  clearAccess: (agentId: string, tool?: string) => Promise<void>;
}

// --------------------------------------------------------------------------- //
// Real API calls — serverId-parameterized; the component binds its prop in.
// --------------------------------------------------------------------------- //
export async function fetchRosterApi(): Promise<RosterAgent[]> {
  const resp = await fetch('/api/crew/roster');
  if (!resp.ok) throw new Error(`crew roster fetch failed: ${resp.status}`);
  const d = await resp.json();
  return Array.isArray(d?.crew) ? d.crew : [];
}

export async function fetchToolsApi(serverId: string): Promise<McpToolsResult> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(serverId)}/tools`);
  if (resp.status === 404) return { tools: [], count: 0, disabled: true };
  if (!resp.ok) throw new Error(`mcp tools fetch failed: ${resp.status}`);
  const d = await resp.json();
  return {
    tools: Array.isArray(d?.tools) ? d.tools : [],
    count: typeof d?.count === 'number' ? d.count : 0,
    error: typeof d?.error === 'string' ? d.error : undefined,
  };
}

export async function fetchAgentAccessApi(serverId: string, agentId: string): Promise<McpAgentAccessResult> {
  const resp = await fetch(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/agents/${encodeURIComponent(agentId)}/access`,
  );
  if (!resp.ok) throw new Error(`mcp agent access fetch failed: ${resp.status}`);
  const d = await resp.json();
  return {
    server_enabled: Boolean(d?.server_enabled),
    tools: Array.isArray(d?.tools) ? d.tools : [],
    error: typeof d?.error === 'string' ? d.error : undefined,
  };
}

export async function setAccessApi(serverId: string, agentId: string, body: SetAccessBody): Promise<void> {
  const resp = await fetch(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/agents/${encodeURIComponent(agentId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!resp.ok) throw new Error(`mcp set access failed: ${resp.status}`);
}

export async function clearAccessApi(serverId: string, agentId: string, tool?: string): Promise<void> {
  const base = `/api/mcp/servers/${encodeURIComponent(serverId)}/agents/${encodeURIComponent(agentId)}`;
  const url = tool ? `${base}?tool=${encodeURIComponent(tool)}` : base;
  const resp = await fetch(url, { method: 'DELETE' });
  if (!resp.ok) throw new Error(`mcp clear access failed: ${resp.status}`);
}

// --------------------------------------------------------------------------- //
// Inline SVG stroke icons (HXI #3: no emoji, stroke-only glyphs).
// --------------------------------------------------------------------------- //
const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconChevron({ open, color = _DIM }: { open: boolean; color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true" style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 120ms' }}>
      <path d="M9 6 L15 12 L9 18" />
    </svg>
  );
}

function IconCheck({ color = _AMBER }: { color?: string }) {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M5 12 L10 17 L19 7" /></svg>);
}

function IconBlock({ color = _DIM }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M6.5 6.5 L17.5 17.5" />
    </svg>
  );
}

function IconReset({ color = _DIM }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M4 12 A8 8 0 1 1 7 17.7" />
      <path d="M4 7 L4 12 L9 12" />
    </svg>
  );
}

// --------------------------------------------------------------------------- //
// Shared styles.
// --------------------------------------------------------------------------- //
function btnStyle(active = true): React.CSSProperties {
  const c = active ? _AMBER : _DIM;
  return {
    fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 0.5,
    color: c, background: 'transparent', border: `1px solid ${c}`, borderRadius: 3,
    padding: '2px 7px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5,
  };
}

function sourceColor(source: string): string {
  if (source === 'tool') return _AMBER;
  if (source === 'server') return '#50a0d0';
  if (source === 'department') return '#40b890';
  return _DIM; // default
}

function badgeStyle(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontFamily: "'JetBrains Mono', monospace", color,
    border: `1px solid ${color}55`, borderRadius: 3, padding: '1px 6px',
  };
}

interface Props {
  serverId: string;
  serverName: string;
  deps?: Partial<McpAgentAccessDeps>;
}

export function McpAgentAccess({ serverId, serverName, deps }: Props) {
  const _fetchRoster = deps?.fetchRoster ?? fetchRosterApi;
  const _fetchTools = deps?.fetchTools ?? (() => fetchToolsApi(serverId));
  const _fetchAgentAccess = deps?.fetchAgentAccess ?? ((aid: string) => fetchAgentAccessApi(serverId, aid));
  const _setAccess = deps?.setAccess ?? ((aid: string, body: SetAccessBody) => setAccessApi(serverId, aid, body));
  const _clearAccess = deps?.clearAccess ?? ((aid: string, tool?: string) => clearAccessApi(serverId, aid, tool));

  const [roster, setRoster] = useState<RosterAgent[] | null>(null);
  const [tools, setTools] = useState<McpToolsResult | null>(null);
  const [rosterError, setRosterError] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [accessByAgent, setAccessByAgent] = useState<Record<string, McpAgentAccessResult>>({});
  const [accessError, setAccessError] = useState<Record<string, string>>({});

  // On mount (per serverId): fetch the roster + the server's tool list. The tool
  // fetch doubles as the management-disabled probe (a GET 404 → disabled).
  useEffect(() => {
    let alive = true;
    setRoster(null);
    setTools(null);
    setRosterError(false);
    setExpanded({});
    setAccessByAgent({});
    setAccessError({});
    _fetchRoster()
      .then((r) => { if (alive) setRoster(r); })
      .catch(() => { if (alive) setRosterError(true); });
    _fetchTools()
      .then((t) => { if (alive) setTools(t); })
      .catch(() => { if (alive) setTools({ tools: [], count: 0, error: 'tools unavailable' }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  const loadAccess = useCallback(async (agentId: string) => {
    setAccessError((prev) => { const n = { ...prev }; delete n[agentId]; return n; });
    try {
      const res = await _fetchAgentAccess(agentId);
      setAccessByAgent((prev) => ({ ...prev, [agentId]: res }));
    } catch {
      setAccessError((prev) => ({ ...prev, [agentId]: 'Access unavailable.' }));
    }
  }, [_fetchAgentAccess]);

  const toggleExpand = useCallback((agentId: string) => {
    setExpanded((prev) => {
      const next = !prev[agentId];
      if (next && !accessByAgent[agentId]) void loadAccess(agentId);
      return { ...prev, [agentId]: next };
    });
  }, [accessByAgent, loadAccess]);

  const onSetServer = useCallback(async (agentId: string, enabled: boolean) => {
    try {
      await _setAccess(agentId, { enabled });
      await loadAccess(agentId);
    } catch {
      setAccessError((prev) => ({ ...prev, [agentId]: 'Update failed.' }));
    }
  }, [_setAccess, loadAccess]);

  const onSetTool = useCallback(async (agentId: string, tool: string, enabled: boolean) => {
    try {
      await _setAccess(agentId, { enabled, tool });
      await loadAccess(agentId);
    } catch {
      setAccessError((prev) => ({ ...prev, [agentId]: 'Update failed.' }));
    }
  }, [_setAccess, loadAccess]);

  const onReset = useCallback(async (agentId: string, tool?: string) => {
    try {
      await _clearAccess(agentId, tool);
      await loadAccess(agentId);
    } catch {
      setAccessError((prev) => ({ ...prev, [agentId]: 'Reset failed.' }));
    }
  }, [_clearAccess, loadAccess]);

  const disabled = tools?.disabled === true;

  return (
    <div
      data-testid={`mcp-agent-access-${serverId}`}
      style={{
        marginTop: 8, border: '1px solid rgba(255,255,255,0.06)', borderRadius: 5,
        padding: '8px 10px', background: 'rgba(255,255,255,0.015)',
        fontFamily: "'JetBrains Mono', monospace", color: _TEXT,
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: 1, color: _AMBER, textTransform: 'uppercase', marginBottom: 8 }}>
        Agent access — {serverName}
      </div>

      {disabled ? (
        <div data-testid={`mcp-access-disabled-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>
          MCP management is disabled.
        </div>
      ) : rosterError ? (
        <div data-testid={`mcp-access-error-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>
          Crew roster unavailable.
        </div>
      ) : roster === null ? (
        <div data-testid={`mcp-access-loading-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>Loading crew…</div>
      ) : roster.length === 0 ? (
        <div data-testid={`mcp-access-empty-${serverId}`} style={{ color: '#555568', fontSize: 11 }}>No crew agents.</div>
      ) : (
        <>
          {tools?.error && (
            <div data-testid={`mcp-access-tools-note-${serverId}`} style={{ color: _DIM, fontSize: 10, marginBottom: 6 }}>
              Tool list unavailable ({tools.error}); server-wide toggles still apply.
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {roster.map((agent) => (
              <AgentRow
                key={agent.agent_id}
                agent={agent}
                serverName={serverName}
                expanded={!!expanded[agent.agent_id]}
                access={accessByAgent[agent.agent_id]}
                error={accessError[agent.agent_id]}
                onToggleExpand={() => toggleExpand(agent.agent_id)}
                onSetServer={(enabled) => onSetServer(agent.agent_id, enabled)}
                onSetTool={(tool, enabled) => onSetTool(agent.agent_id, tool, enabled)}
                onReset={(tool) => onReset(agent.agent_id, tool)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Per-agent row: a server-wide toggle + reset, and an expander revealing the
// per-tool toggles (each with its resolved source badge + a per-tool reset).
// --------------------------------------------------------------------------- //
interface AgentRowProps {
  agent: RosterAgent;
  serverName: string;
  expanded: boolean;
  access?: McpAgentAccessResult;
  error?: string;
  onToggleExpand: () => void;
  onSetServer: (enabled: boolean) => void;
  onSetTool: (tool: string, enabled: boolean) => void;
  onReset: (tool?: string) => void;
}

function AgentRow(p: AgentRowProps) {
  const agentId = p.agent.agent_id;
  const display = p.agent.callsign || p.agent.agent_type || agentId;
  const serverEnabled = p.access?.server_enabled ?? false;

  return (
    <div
      data-testid={`mcp-access-row-${agentId}`}
      style={{ border: '1px solid rgba(255,255,255,0.05)', borderLeft: `3px solid ${serverEnabled ? _AMBER : _DIM}`, borderRadius: 4, padding: '6px 8px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button
          data-testid={`mcp-access-expand-${p.serverName}-${agentId}`}
          onClick={p.onToggleExpand}
          aria-label={p.expanded ? 'Collapse tools' : 'Expand tools'}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center' }}
        >
          <IconChevron open={p.expanded} color={p.expanded ? _AMBER : _DIM} />
        </button>
        <span style={{ color: '#c8d0e0', fontSize: 11, minWidth: 120 }}>{display}</span>
        {p.agent.post && <span style={{ color: _DIM, fontSize: 9 }}>{p.agent.post}</span>}
        <span style={{ flex: 1 }} />
        <button
          data-testid={`mcp-access-${p.serverName}-${agentId}`}
          onClick={() => p.onSetServer(!serverEnabled)}
          style={btnStyle(serverEnabled)}
        >
          {serverEnabled ? <IconCheck /> : <IconBlock />}
          {serverEnabled ? 'Enabled' : 'Disabled'}
        </button>
        <button
          data-testid={`mcp-access-reset-${p.serverName}-${agentId}`}
          onClick={() => p.onReset()}
          style={btnStyle(false)}
          aria-label="Reset to default (server-wide)"
        >
          <IconReset />Default
        </button>
      </div>

      {p.error && (
        <div data-testid={`mcp-access-row-error-${agentId}`} style={{ color: _RED, fontSize: 10, marginTop: 5 }}>{p.error}</div>
      )}

      {p.expanded && !p.error && (
        <div data-testid={`mcp-access-tools-${agentId}`} style={{ marginTop: 6, paddingLeft: 21, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {p.access === undefined ? (
            <div style={{ color: _DIM, fontSize: 10 }}>Loading access…</div>
          ) : p.access.tools.length === 0 ? (
            <div data-testid={`mcp-access-tools-empty-${agentId}`} style={{ color: '#555568', fontSize: 10 }}>No tools enumerated.</div>
          ) : (
            p.access.tools.map((t) => {
              const sc = sourceColor(t.source);
              return (
                <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: _TEXT, fontSize: 10, minWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</span>
                  <span data-testid={`mcp-access-tool-source-${p.serverName}-${agentId}-${t.name}`} style={badgeStyle(sc)}>{t.source}</span>
                  <span style={{ flex: 1 }} />
                  <button
                    data-testid={`mcp-access-tool-${p.serverName}-${agentId}-${t.name}`}
                    onClick={() => p.onSetTool(t.name, !t.enabled)}
                    style={btnStyle(t.enabled)}
                  >
                    {t.enabled ? <IconCheck /> : <IconBlock />}
                    {t.enabled ? 'On' : 'Off'}
                  </button>
                  <button
                    data-testid={`mcp-access-reset-${p.serverName}-${agentId}-${t.name}`}
                    onClick={() => p.onReset(t.name)}
                    style={btnStyle(false)}
                    aria-label={`Reset ${t.name} to default`}
                  >
                    <IconReset />
                  </button>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

export default McpAgentAccess;
