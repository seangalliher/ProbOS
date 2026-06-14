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
  origin?: string; // AD-1000a: 'built_in' | 'mcp' | 'extension' (tool provenance)
}

/** AD-1000a: a mesh-intent capability (the third axis). Pool-served + ship-wide,
 *  so read-only here — shown for visibility, not per-agent toggled.
 *  AD-1006: ``served`` flags whether THIS agent declares (fulfils) the intent —
 *  its own specialty — vs the ship-wide reachable surface every agent can call. */
export interface MeshIntent {
  id: string;
  name: string;
  description?: string;
  usage_hint?: string;
  requires_consensus: boolean;
  tier: string;
  origin: string;
  reachable: boolean;
  served?: boolean;
}

interface CapabilitiesResponse {
  tools: AgentCapability[];
  skills: AgentCapability[];
  mesh_intents: MeshIntent[];
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
    mesh_intents: Array.isArray(data?.mesh_intents) ? data.mesh_intents : [],
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

/** AD-1000a: human label for the tool source taxonomy (built_in / mcp / extension). */
function originLabel(origin?: string): string {
  switch (origin) {
    case 'built_in': return 'built-in';
    case 'mcp': return 'MCP';
    case 'extension': return 'extension';
    default: return '';
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
      {originLabel(cap.origin) && (
        <span
          data-testid={`cap-origin-${kind}-${cap.id}`}
          style={{ color: '#7a8aa0', fontSize: 9, letterSpacing: 0.5 }}
        >
          {originLabel(cap.origin)}
        </span>
      )}
      <span style={{ color: _DIM, fontSize: 9, letterSpacing: 0.5 }}>{sourceLabel(cap.source)}</span>
    </div>
  );
}

/** AD-1000a: read-only row for a mesh-intent capability. No toggle — mesh intents
 *  are pool-served + ship-wide; a consensus badge flags write intents. */
function MeshIntentRow({ mi }: { mi: MeshIntent }) {
  return (
    <div
      data-testid={`mesh-row-${mi.id}`}
      title={mi.description || mi.name}
      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', fontSize: 11 }}
    >
      <span style={{ color: mi.reachable ? '#c8c8d4' : _DIM }}>{mi.name}</span>
      {mi.requires_consensus && (
        <span
          data-testid={`mesh-consensus-${mi.id}`}
          title="Requires multi-agent consensus to run"
          style={{
            color: _AMBER, fontSize: 9, letterSpacing: 0.5,
            border: `1px solid rgba(240,176,96,0.4)`, borderRadius: 3, padding: '0 4px',
          }}
        >
          consensus
        </span>
      )}
      <span style={{ color: '#7a8aa0', fontSize: 9, letterSpacing: 0.5 }}>{originLabel(mi.origin)}</span>
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
  const [meshIntents, setMeshIntents] = useState<MeshIntent[]>([]);
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
        setMeshIntents(data.mesh_intents);
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

  // AD-1006: partition the mesh capabilities into what THIS agent SERVES (its
  // own specialty intents) vs the ship-wide surface it CAN REQUEST (identical
  // for every agent). A backend without the ``served`` flag leaves every intent
  // in "can request" — byte-identical to the pre-AD-1006 single section.
  const servedIntents = meshIntents.filter((mi) => mi.served);
  const reachableIntents = meshIntents.filter((mi) => !mi.served);

  return (
    <div data-testid="capability-panel">
      <div style={{ fontSize: 10, color: _DIM, letterSpacing: 1, margin: '6px 0 4px' }}>
        TOOLS ({tools.length})
      </div>
      {tools.length === 0 ? (
        <div data-testid="cap-tools-empty" style={{ fontSize: 11, color: '#555568', padding: '2px 0', lineHeight: 1.5 }}>
          No tools wired into this agent&apos;s context. Tools are callable
          functions (file I/O, web fetch, run code) &mdash; granted from the
          agent&apos;s role or enabled individually.
        </div>
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

      {/* AD-1006: capabilities this agent SERVES — its specialty intents. */}
      <div style={{ fontSize: 10, color: _DIM, letterSpacing: 1, margin: '12px 0 1px' }}>
        CAPABILITIES — SERVES ({servedIntents.length})
      </div>
      <div style={{ color: '#555568', fontSize: 9, lineHeight: 1.4, marginBottom: 4 }}>
        Mesh intents only this agent fulfils.
      </div>
      {servedIntents.length === 0 ? (
        <div data-testid="cap-serves-empty" style={{ fontSize: 11, color: '#555568', padding: '2px 0' }}>
          No specialty intents — this agent works through its skills and reasoning.
        </div>
      ) : (
        servedIntents.map((mi) => <MeshIntentRow key={mi.id} mi={mi} />)
      )}

      {/* AD-1006: ship-wide surface any agent can request (served by other crew/pools). */}
      <div style={{ fontSize: 10, color: _DIM, letterSpacing: 1, margin: '12px 0 1px' }}>
        CAPABILITIES — CAN REQUEST ({reachableIntents.length})
      </div>
      <div style={{ color: '#555568', fontSize: 9, lineHeight: 1.4, marginBottom: 4 }}>
        Ship-wide mesh surface any agent can request; served by other crew or pools.
      </div>
      {reachableIntents.length === 0 ? (
        <div style={{ fontSize: 11, color: '#555568', padding: '2px 0' }}>No mesh capabilities.</div>
      ) : (
        reachableIntents.map((mi) => <MeshIntentRow key={mi.id} mi={mi} />)
      )}
    </div>
  );
}

export { fetchCapabilities, setCapability };
