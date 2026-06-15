/** AD-1001b: Ship's Locker — the global capabilities catalog overlay.
 *
 *  The ship-wide counterpart to the per-agent Service Configuration tab
 *  (AD-1000c): "what can the ship do, and who holds what." Read-only. Bound to
 *  the AD-1001a GET /api/tools/catalog. Opened from the Bridge → Engineering
 *  station ("Ship's Locker"); closed via the header X or Escape.
 *
 *  HXI: stroke/text only, no emoji; amber active / dim inactive. Aligns with the
 *  WardRoom/Settings overlay pattern (fixed full-screen, store-flag gated).
 */
import { useEffect, useState, useCallback } from 'react';
import { useStore } from '../../store/useStore';

const _AMBER = '#f0b060';
const _DIM = '#666680';

export interface CatalogTool { id: string; name: string; description?: string; origin: string; tool_type?: string; department?: string | null; held_by: string[]; }
export interface CatalogSkill { id: string; name: string; description?: string; department?: string; min_rank?: string; held_by: string[]; }
export interface CatalogMeshIntent { id: string; name: string; description?: string; requires_consensus: boolean; tier: string; origin: string; reachable: boolean; }
export interface CatalogMcp { url: string; origin: string; }
export interface Catalog {
  tools: CatalogTool[];
  skills: CatalogSkill[];
  mesh_intents: CatalogMeshIntent[];
  mcp_servers: CatalogMcp[];
  counts: { tools: number; skills: number; mesh_intents: number; mcp_servers: number };
}

export async function fetchCatalog(): Promise<Catalog> {
  const resp = await fetch('/api/tools/catalog');
  if (!resp.ok) throw new Error(`catalog fetch failed: ${resp.status}`);
  const d = await resp.json();
  return {
    tools: Array.isArray(d?.tools) ? d.tools : [],
    skills: Array.isArray(d?.skills) ? d.skills : [],
    mesh_intents: Array.isArray(d?.mesh_intents) ? d.mesh_intents : [],
    mcp_servers: Array.isArray(d?.mcp_servers) ? d.mcp_servers : [],
    counts: d?.counts ?? { tools: 0, skills: 0, mesh_intents: 0, mcp_servers: 0 },
  };
}

// AD-1003d: the read-only installed-pack inventory (Capability Packs, cross-tool
// agent-plugin format). Bound to GET /api/packs (AD-1003c); default-disabled, so
// an empty/absent list is the normal case.
export interface PackInfo {
  name: string;
  version?: string;
  description?: string;
  ok: boolean;
  error?: string | null;
  has_hooks?: boolean;
  has_mcp?: boolean;
}
export interface PacksInventory {
  enabled: boolean;
  packs: PackInfo[];
  counts: { total: number; valid: number; error: number };
}

export async function fetchPacks(): Promise<PacksInventory> {
  const resp = await fetch('/api/packs');
  if (!resp.ok) return { enabled: false, packs: [], counts: { total: 0, valid: 0, error: 0 } };
  const d = await resp.json();
  return {
    enabled: !!d?.enabled,
    packs: Array.isArray(d?.packs) ? d.packs : [],
    counts: d?.counts ?? { total: 0, valid: 0, error: 0 },
  };
}

// AD-1003f: a pack's declared component inventory (skills/agents), fetched on
// expand from GET /api/packs/{name} (AD-1003e). Read-only — the API only lists
// the component files; nothing is loaded or executed.
export interface PackComponentInfo { name: string; rel: string; }
export interface PackDetail {
  name: string;
  skills: PackComponentInfo[];
  agents: PackComponentInfo[];
  has_hooks?: boolean;
  has_mcp?: boolean;
  counts?: { skills: number; agents: number };
}

export async function fetchPackDetail(name: string): Promise<PackDetail | null> {
  const resp = await fetch(`/api/packs/${encodeURIComponent(name)}`);
  if (!resp.ok) return null;
  const d = await resp.json();
  return {
    name: d?.name ?? name,
    skills: Array.isArray(d?.skills) ? d.skills : [],
    agents: Array.isArray(d?.agents) ? d.agents : [],
    has_hooks: !!d?.has_hooks,
    has_mcp: !!d?.has_mcp,
    counts: d?.counts,
  };
}

function originLabel(origin?: string): string {
  switch (origin) {
    case 'built_in': return 'built-in';
    case 'mcp': return 'MCP';
    case 'extension': return 'extension';
    default: return origin ?? '';
  }
}

function heldByLabel(held: string[]): string {
  if (!held || held.length === 0) return 'no explicit grants';
  if (held.length <= 3) return held.join(', ');
  return `${held.slice(0, 3).join(', ')} +${held.length - 3}`;
}

interface Props {
  deps?: { fetchCatalog?: () => Promise<Catalog>; fetchPacks?: () => Promise<PacksInventory>; fetchPackDetail?: (name: string) => Promise<PackDetail | null> };
}

export function ShipsLockerPanel({ deps }: Props) {
  const open = useStore((s) => s.shipsLockerOpen);
  const _fetch = deps?.fetchCatalog ?? fetchCatalog;
  const _fetchPacks = deps?.fetchPacks ?? fetchPacks;
  const _fetchPackDetail = deps?.fetchPackDetail ?? fetchPackDetail;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [packs, setPacks] = useState<PacksInventory | null>(null);
  const [expandedPack, setExpandedPack] = useState<string | null>(null);
  const [packDetail, setPackDetail] = useState<PackDetail | null>(null);
  const [error, setError] = useState(false);

  const close = useCallback(() => useStore.setState({ shipsLockerOpen: false }), []);

  // AD-1003f: expand a valid pack to load + show its declared components.
  const togglePack = useCallback((name: string) => {
    if (expandedPack === name) {
      setExpandedPack(null);
      setPackDetail(null);
      return;
    }
    setExpandedPack(name);
    setPackDetail(null);
    void _fetchPackDetail(name).then((d) => {
      // Guard against a stale response after another row was clicked.
      setPackDetail((prev) => (d && d.name === name ? d : prev));
    }).catch(() => { /* honest-degrade: leave detail null (shows "no components") */ });
  }, [expandedPack, _fetchPackDetail]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setCatalog(null);
    setError(false);
    _fetch().then((c) => { if (alive) setCatalog(c); }).catch(() => { if (alive) setError(true); });
    // AD-1003d: packs are an independent, honest-degrade fetch — a packs failure
    // never blocks the catalog (the locker's primary content).
    setPacks(null);
    setExpandedPack(null);
    setPackDetail(null);
    _fetchPacks().then((p) => { if (alive) setPacks(p); }).catch(() => { if (alive) setPacks({ enabled: false, packs: [], counts: { total: 0, valid: 0, error: 0 } }); });
    return () => { alive = false; };
  }, [open, _fetch]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close]);

  if (!open) return null;

  const sectionHeader = (label: string, n: number) => (
    <div style={{ fontSize: 11, color: _AMBER, letterSpacing: 1, margin: '14px 0 6px', fontWeight: 600 }}>
      {label} ({n})
    </div>
  );

  return (
    <div
      data-testid="ships-locker-panel"
      style={{
        position: 'fixed', inset: 0, zIndex: 30, background: 'rgba(6,6,12,0.94)',
        backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        display: 'flex', flexDirection: 'column', fontFamily: "'JetBrains Mono', monospace",
        color: '#c8c8d8', padding: '0',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div>
          <div style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>SHIP'S LOCKER</div>
          <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
            Ship-wide capabilities catalog — what the ship can do, and who holds what.
          </div>
        </div>
        <button
          data-testid="ships-locker-close"
          onClick={close}
          aria-label="Close Ship's Locker"
          style={{
            background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4,
            color: _DIM, fontSize: 14, width: 28, height: 28, cursor: 'pointer', lineHeight: 1,
          }}
        >
          {'\u00D7'}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 18px 24px', fontSize: 12 }}>
        {error && <div data-testid="ships-locker-error" style={{ color: _DIM, padding: '16px 0' }}>Catalog unavailable.</div>}
        {!error && catalog === null && <div data-testid="ships-locker-loading" style={{ color: _DIM, padding: '16px 0' }}>Loading catalog…</div>}
        {!error && catalog !== null && (
          <>
            {sectionHeader('TOOLS', catalog.counts.tools)}
            {catalog.tools.map((t) => (
              <div key={t.id} data-testid={`locker-tool-${t.id}`} style={{ display: 'flex', gap: 10, padding: '2px 0' }}>
                <span style={{ color: '#c8d0e0', minWidth: 160 }}>{t.name}</span>
                <span style={{ color: '#7a8aa0', fontSize: 9, minWidth: 64 }}>{originLabel(t.origin)}</span>
                <span style={{ color: _DIM, fontSize: 10 }}>{heldByLabel(t.held_by)}</span>
              </div>
            ))}

            {sectionHeader('SKILLS', catalog.counts.skills)}
            {catalog.skills.map((s) => (
              <div key={s.id} data-testid={`locker-skill-${s.id}`} style={{ display: 'flex', gap: 10, padding: '2px 0' }}>
                <span style={{ color: '#c8d0e0', minWidth: 160 }}>{s.name}</span>
                <span style={{ color: '#7a8aa0', fontSize: 9, minWidth: 64 }}>{s.department}</span>
                <span style={{ color: _DIM, fontSize: 10 }}>{heldByLabel(s.held_by)}</span>
              </div>
            ))}

            {sectionHeader('CAPABILITIES (mesh)', catalog.counts.mesh_intents)}
            {catalog.mesh_intents.map((mi) => (
              <div key={mi.id} data-testid={`locker-mesh-${mi.id}`} style={{ display: 'flex', gap: 10, padding: '2px 0' }}>
                <span style={{ color: '#c8d0e0', minWidth: 160 }}>{mi.name}</span>
                {mi.requires_consensus && (
                  <span style={{ color: _AMBER, fontSize: 9, border: '1px solid rgba(240,176,96,0.4)', borderRadius: 3, padding: '0 4px' }}>
                    consensus
                  </span>
                )}
                <span style={{ color: _DIM, fontSize: 10 }}>ship-served · {mi.tier}</span>
              </div>
            ))}

            {sectionHeader('MCP SERVERS', catalog.counts.mcp_servers)}
            {catalog.mcp_servers.length === 0 ? (
              <div style={{ color: '#555568', fontSize: 11 }}>No MCP servers configured.</div>
            ) : (
              catalog.mcp_servers.map((m) => (
                <div key={m.url} data-testid={`locker-mcp-${m.url}`} style={{ color: '#c8d0e0', padding: '2px 0', fontFamily: 'monospace', fontSize: 11 }}>
                  {m.url}
                </div>
              ))
            )}

            {/* AD-1003d: installed Capability Packs (cross-tool agent-plugin
                format). Default-disabled, so the common case is the disabled
                note; a bad pack shows as an error row (honest-degrade). */}
            {sectionHeader('INSTALLED PACKS', packs?.counts.total ?? 0)}
            {packs === null ? (
              <div data-testid="locker-packs-loading" style={{ color: '#555568', fontSize: 11 }}>Loading packs…</div>
            ) : !packs.enabled ? (
              <div data-testid="locker-packs-disabled" style={{ color: '#555568', fontSize: 11 }}>
                Capability Packs are disabled. Enable <code style={{ color: '#7a8aa0' }}>packs.enabled</code> to load packs.
              </div>
            ) : packs.packs.length === 0 ? (
              <div data-testid="locker-packs-empty" style={{ color: '#555568', fontSize: 11 }}>No packs installed.</div>
            ) : (
              packs.packs.map((p) => (
                <div key={p.name} data-testid={`locker-pack-${p.name}`}>
                  <div style={{ display: 'flex', gap: 10, padding: '2px 0', alignItems: 'center' }}>
                    {p.ok ? (
                      <button
                        data-testid={`locker-pack-expand-${p.name}`}
                        onClick={() => togglePack(p.name)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#c8d0e0', padding: 0, minWidth: 160, textAlign: 'left', fontFamily: 'inherit', fontSize: 'inherit' }}
                      >
                        {expandedPack === p.name ? '\u2212 ' : '+ '}{p.name}
                      </button>
                    ) : (
                      <span style={{ color: '#d05050', minWidth: 160 }}>{p.name}</span>
                    )}
                    {p.ok ? (
                      <>
                        {p.version && <span style={{ color: '#7a8aa0', fontSize: 9, minWidth: 48 }}>v{p.version}</span>}
                        {p.has_hooks && <span style={{ color: _AMBER, fontSize: 9 }}>hooks</span>}
                        {p.has_mcp && <span style={{ color: _AMBER, fontSize: 9 }}>mcp</span>}
                        <span style={{ color: _DIM, fontSize: 10 }}>{p.description}</span>
                      </>
                    ) : (
                      <span style={{ color: '#d05050', fontSize: 10 }}>invalid manifest</span>
                    )}
                  </div>
                  {/* AD-1003f: expanded component preview (read-only — listed, not loaded). */}
                  {expandedPack === p.name && (
                    <div data-testid={`locker-pack-detail-${p.name}`} style={{ paddingLeft: 16, paddingBottom: 4 }}>
                      {packDetail === null || packDetail.name !== p.name ? (
                        <div style={{ color: '#555568', fontSize: 10 }}>Loading components…</div>
                      ) : (packDetail.skills.length === 0 && packDetail.agents.length === 0) ? (
                        <div style={{ color: '#555568', fontSize: 10 }}>No declared components.</div>
                      ) : (
                        <>
                          {packDetail.skills.length > 0 && (
                            <div style={{ fontSize: 10, color: _DIM, padding: '1px 0' }}>
                              <span style={{ color: '#7a8aa0' }}>skills:</span> {packDetail.skills.map((s) => s.name).join(', ')}
                            </div>
                          )}
                          {packDetail.agents.length > 0 && (
                            <div style={{ fontSize: 10, color: _DIM, padding: '1px 0' }}>
                              <span style={{ color: '#7a8aa0' }}>agents:</span> {packDetail.agents.map((a) => a.name).join(', ')}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
