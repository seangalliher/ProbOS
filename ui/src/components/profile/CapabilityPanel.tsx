/** AD-983c: CapabilityPanel — the Captain surface for per-agent tool/skill
 *  enablement (the AD-983 Copilot-parity epic, generalizing the AD-982 vision
 *  toggle from one flag to the full tool/skill set).
 *
 *  Bound to the AD-983b API:
 *    GET  /api/agent/{id}/capabilities      -> { tools: [...], skills: [...] }
 *    POST /api/agent/{id}/capabilities/set   { kind, id, enabled, reason }
 *
 *  Each capability has granted + source (grant / restriction / role_default /
 *  dept_default), so a Captain grant is visually distinct from a role/department
 *  default. Toggling is optimistic with revert-on-failure (the AD-982 pattern).
 *  HXI: stroke-only, amber active / dim inactive, NO emoji.
 */
import { useEffect, useState, useCallback } from 'react';

export interface AgentCapability {
  id: string;
  name: string;
  description?: string;
  granted: boolean;
  source: string;  // 'grant' | 'restriction' | 'role_default' | 'dept_default'
}

interface CapabilitiesResponse {
  tools: AgentCapability[];
  skills: AgentCapability[];
}

const _AMBER = '#f0b060';
const _DIM = '#666680';

async function fetchCapabilities(agentId: string): Promise<CapabilitiesResponse> {
  const resp = await fetch(`/api/agent/${agentId}/capabilities`);
  if (!resp.ok) throw new Error(`capabilities fetch failed: ${resp.status}`);
  const data = await resp.json();
  return {
    tools: Array.isArray(data?.tools) ? data.tools : [],
    skills: Array.isArray(data?.skills) ? data.skills : [],
  };
}

async function setCapability(
  agentId: string,
  kind: 'tool' | 'skill',
  id: string,
  enabled: boolean,
): Promise<boolean> {
  const resp = await fetch(`/api/agent/${agentId}/capabilities/set`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind,
      id,
      enabled,
      reason: enabled ? 'Captain enabled capability' : 'Captain disabled capability',
    }),
  });
  return resp.ok;
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'grant': return 'granted';
    case 'restriction': return 'restricted';
    case 'role_default': return 'role default';
    case 'dept_default': return 'dept default';
    default: return source;
  }
}

interface RowProps {
  cap: AgentCapability;
  kind: 'tool' | 'skill';
  onToggle: (kind: 'tool' | 'skill', cap: AgentCapability) => void;
}

function CapabilityRow({ cap, kind, onToggle }: RowProps) {
  return (
    <div
      data-testid={`cap-row-${kind}-${cap.id}`}
      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0', fontSize: 11 }}
    >
      <button
        data-testid={`cap-toggle-${kind}-${cap.id}`}
        aria-pressed={cap.granted}
        onClick={() => onToggle(kind, cap)}
        title={cap.granted
          ? `Enabled (${sourceLabel(cap.source)}) — click to disable`
          : `Disabled (${sourceLabel(cap.source)}) — click to enable`}
        style={{
          background: cap.granted ? 'rgba(240,176,96,0.15)' : 'rgba(255,255,255,0.05)',
          border: `1px solid ${cap.granted ? 'rgba(240,176,96,0.5)' : 'rgba(255,255,255,0.15)'}`,
          borderRadius: 4, padding: '1px 8px', cursor: 'pointer', flexShrink: 0,
          color: cap.granted ? _AMBER : _DIM, fontSize: 10, minWidth: 52,
        }}
      >
        {cap.granted ? 'On' : 'Off'}
      </button>
      <span style={{ color: '#c8c8d4' }}>{cap.name}</span>
      <span style={{ color: _DIM, fontSize: 9, letterSpacing: 0.5 }}>{sourceLabel(cap.source)}</span>
    </div>
  );
}

interface CapabilityPanelProps {
  agentId: string;
  /** Optional injected fetchers (tests). Default to the real API. */
  deps?: {
    fetchCapabilities?: (agentId: string) => Promise<CapabilitiesResponse>;
    setCapability?: (
      agentId: string, kind: 'tool' | 'skill', id: string, enabled: boolean,
    ) => Promise<boolean>;
  };
}

/** The reusable per-agent capability enablement panel (AD-983c). Rendered on the
 *  AgentProfilePanel and the personnel ServiceRecord. */
export function CapabilityPanel({ agentId, deps }: CapabilityPanelProps) {
  const _fetch = deps?.fetchCapabilities ?? fetchCapabilities;
  const _set = deps?.setCapability ?? setCapability;
  const [tools, setTools] = useState<AgentCapability[]>([]);
  const [skills, setSkills] = useState<AgentCapability[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    setError(false);
    _fetch(agentId)
      .then((data) => {
        if (!alive) return;
        setTools(data.tools);
        setSkills(data.skills);
        setLoaded(true);
      })
      .catch(() => { if (alive) { setError(true); setLoaded(true); } });
    return () => { alive = false; };
  }, [agentId, _fetch]);

  const onToggle = useCallback((kind: 'tool' | 'skill', cap: AgentCapability) => {
    const next = !cap.granted;
    const setList = kind === 'tool' ? setTools : setSkills;
    // optimistic
    setList((prev) => prev.map((c) => (c.id === cap.id ? { ...c, granted: next } : c)));
    void _set(agentId, kind, cap.id, next).then((ok) => {
      if (!ok) {
        // revert on failure
        setList((prev) => prev.map((c) => (c.id === cap.id ? { ...c, granted: cap.granted } : c)));
      }
    }).catch(() => {
      setList((prev) => prev.map((c) => (c.id === cap.id ? { ...c, granted: cap.granted } : c)));
    });
  }, [agentId, _set]);

  if (!loaded) {
    return <div data-testid="cap-panel-loading" style={{ fontSize: 11, color: _DIM, padding: '4px 0' }}>Loading capabilities…</div>;
  }
  if (error) {
    return <div data-testid="cap-panel-error" style={{ fontSize: 11, color: _DIM, padding: '4px 0' }}>Capabilities unavailable.</div>;
  }

  return (
    <div data-testid="capability-panel">
      <div style={{ fontSize: 10, color: _DIM, letterSpacing: 1, margin: '6px 0 4px' }}>
        TOOLS ({tools.length})
      </div>
      {tools.length === 0 ? (
        <div style={{ fontSize: 11, color: '#555568', padding: '2px 0' }}>No tools.</div>
      ) : (
        tools.map((c) => <CapabilityRow key={c.id} cap={c} kind="tool" onToggle={onToggle} />)
      )}
      <div style={{ fontSize: 10, color: _DIM, letterSpacing: 1, margin: '10px 0 4px' }}>
        SKILLS ({skills.length})
      </div>
      {skills.length === 0 ? (
        <div style={{ fontSize: 11, color: '#555568', padding: '2px 0' }}>No skills.</div>
      ) : (
        skills.map((c) => <CapabilityRow key={c.id} cap={c} kind="skill" onToggle={onToggle} />)
      )}
    </div>
  );
}

export { fetchCapabilities, setCapability };
