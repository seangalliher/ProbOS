/** AD-1019d: agent toolbox — the resolved, read-only view of every MCP tool a
 *  single crew agent can actually reach right now (the payoff of #964).
 *
 *  Pick an agent; the surface iterates every enabled MCP server, asks the
 *  AD-1019 resolver for that agent's per-tool access, and lists only the tools
 *  that resolve ``enabled``. Each tool carries a 3-bucket provenance badge so an
 *  operator can see WHY it is in the toolbox: an "agent" grant (per-agent/tool),
 *  a "department" locker (AD-1019e), or the "ship" default. Read-only — authoring
 *  happens in ``McpAgentAccess`` (agent) and ``McpDepartmentLockers`` (department).
 *
 *  Backend (AD-1019, live): ``GET /api/mcp/servers/{id}/agents/{aid}/access``
 *  per enabled server, plus ``GET /api/crew/roster`` and ``GET /api/mcp/servers``.
 *
 *  HXI: inline SVG stroke icons (strokeWidth 1.5), amber/green/blue provenance,
 *  NO emoji, a ``data-testid`` on every interactive element, honest-degrade (a
 *  per-server ``/access`` failure shows an inline note — never throws; a servers
 *  GET 404 means management disabled → the surface hides).
 */
import { useEffect, useState, useCallback } from 'react';
import {
  fetchRosterApi,
  fetchAgentAccessApi,
  type RosterAgent,
  type McpToolAccess,
  type McpAgentAccessResult,
} from './McpAgentAccess';
import { fetchServersApi, type McpServer, type McpServersResult } from './McpServersPanel';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

// --------------------------------------------------------------------------- //
// Types.
// --------------------------------------------------------------------------- //
/** Injectable IO seam — every entry defaults to a reused real ``fetch`` below. */
export interface McpAgentToolboxDeps {
  fetchRoster: () => Promise<RosterAgent[]>;
  fetchServers: () => Promise<McpServersResult>;
  fetchAgentAccess: (serverId: string, agentId: string) => Promise<McpAgentAccessResult>;
}

interface ServerToolbox {
  server: McpServer;
  tools: McpToolAccess[];
  error?: string;
}

// --------------------------------------------------------------------------- //
// Provenance: collapse the 4 resolver sources into 3 operator-facing buckets.
// --------------------------------------------------------------------------- //
function toolboxSource(raw: string): { label: string; color: string } {
  if (raw === 'tool' || raw === 'server') return { label: 'agent', color: '#f0b060' };
  if (raw === 'department') return { label: 'department', color: '#40b890' };
  return { label: 'ship', color: '#50a0d0' }; // default
}

function badgeStyle(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontFamily: "'JetBrains Mono', monospace", color,
    border: `1px solid ${color}55`, borderRadius: 3, padding: '1px 6px',
  };
}

const fieldStyle: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: _TEXT,
  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: 3, padding: '4px 7px',
};

interface Props {
  deps?: Partial<McpAgentToolboxDeps>;
}

export function McpAgentToolbox({ deps }: Props) {
  const _fetchRoster = deps?.fetchRoster ?? fetchRosterApi;
  const _fetchServers = deps?.fetchServers ?? fetchServersApi;
  const _fetchAgentAccess = deps?.fetchAgentAccess ?? fetchAgentAccessApi;

  const [roster, setRoster] = useState<RosterAgent[]>([]);
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [error, setError] = useState(false);
  const [agentId, setAgentId] = useState('');
  const [resolved, setResolved] = useState<ServerToolbox[] | null>(null);

  useEffect(() => {
    let alive = true;
    setServers(null);
    setDisabled(false);
    setError(false);
    _fetchServers()
      .then((r) => { if (alive) { setServers(r.servers); setDisabled(r.disabled === true); } })
      .catch(() => { if (alive) setError(true); });
    _fetchRoster()
      .then((r) => { if (alive) setRoster(r); })
      .catch(() => { /* honest-degrade: empty agent picker */ });
    return () => { alive = false; };
  }, [_fetchServers, _fetchRoster]);

  const loadToolbox = useCallback(async (aid: string, srv: McpServer[]) => {
    const enabled = srv.filter((s) => s.enabled);
    // Honest-degrade per server: a failed /access yields an inline note, never throws.
    const entries = await Promise.all(
      enabled.map(async (s): Promise<ServerToolbox> => {
        try {
          const res = await _fetchAgentAccess(s.id, aid);
          return { server: s, tools: res.tools.filter((t) => t.enabled) };
        } catch {
          return { server: s, tools: [], error: 'access unavailable' };
        }
      }),
    );
    setResolved(entries);
  }, [_fetchAgentAccess]);

  const onSelectAgent = useCallback((aid: string) => {
    setAgentId(aid);
    if (!aid || servers === null) { setResolved(null); return; }
    setResolved(null);
    void loadToolbox(aid, servers);
  }, [servers, loadToolbox]);

  return (
    <div data-testid="mcp-toolbox" style={{ fontFamily: "'JetBrains Mono', monospace", color: _TEXT }}>
      <div style={{ fontSize: 12, color: _AMBER, letterSpacing: 1, marginBottom: 4 }}>AGENT TOOLBOX</div>
      <div style={{ fontSize: 10, color: _DIM, marginBottom: 12 }}>
        The resolved set of MCP tools an agent can reach — across every enabled server — with the provenance of each grant.
      </div>

      {disabled ? (
        <div data-testid="mcp-toolbox-disabled" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>
          MCP management is disabled.
        </div>
      ) : error ? (
        <div data-testid="mcp-toolbox-error" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>
          Agent toolbox unavailable.
        </div>
      ) : servers === null ? (
        <div data-testid="mcp-toolbox-loading" style={{ color: _DIM, fontSize: 11, padding: '8px 0' }}>Loading servers…</div>
      ) : (
        <>
          <select
            data-testid="mcp-toolbox-agent-select"
            value={agentId}
            onChange={(e) => onSelectAgent(e.target.value)}
            style={{ ...fieldStyle, marginBottom: 14 }}
            aria-label="Agent"
          >
            <option value="">Agent…</option>
            {roster.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>{a.callsign || a.agent_type || a.agent_id}</option>
            ))}
          </select>

          {agentId === '' ? (
            <div data-testid="mcp-toolbox-prompt" style={{ color: '#555568', fontSize: 11 }}>Pick an agent to resolve their toolbox.</div>
          ) : resolved === null ? (
            <div data-testid="mcp-toolbox-resolving" style={{ color: _DIM, fontSize: 11 }}>Resolving toolbox…</div>
          ) : resolved.length === 0 ? (
            <div data-testid="mcp-toolbox-no-servers" style={{ color: '#555568', fontSize: 11 }}>No enabled MCP servers.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {resolved.map((entry) => (
                <div key={entry.server.id}>
                  <div style={{ fontSize: 11, color: '#c8d0e0', letterSpacing: 0.5, marginBottom: 4 }}>{entry.server.name}</div>
                  {entry.error ? (
                    <div data-testid={`mcp-toolbox-server-error-${entry.server.name}`} style={{ color: _DIM, fontSize: 10 }}>{entry.error}</div>
                  ) : entry.tools.length === 0 ? (
                    <div data-testid={`mcp-toolbox-server-empty-${entry.server.name}`} style={{ color: '#555568', fontSize: 10 }}>No tools reachable.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {entry.tools.map((t) => {
                        const prov = toolboxSource(t.source);
                        return (
                          <div
                            key={t.name}
                            data-testid={`mcp-toolbox-tool-${entry.server.name}-${t.name}`}
                            style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid rgba(255,255,255,0.06)', borderRadius: 4, padding: '5px 9px' }}
                          >
                            <span style={{ color: _TEXT, fontSize: 10, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</span>
                            <span data-testid={`mcp-toolbox-source-${entry.server.name}-${t.name}`} style={badgeStyle(prov.color)}>{prov.label}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default McpAgentToolbox;
