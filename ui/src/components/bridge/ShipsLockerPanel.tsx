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
  deps?: { fetchCatalog?: () => Promise<Catalog> };
}

export function ShipsLockerPanel({ deps }: Props) {
  const open = useStore((s) => s.shipsLockerOpen);
  const _fetch = deps?.fetchCatalog ?? fetchCatalog;
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState(false);

  const close = useCallback(() => useStore.setState({ shipsLockerOpen: false }), []);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setCatalog(null);
    setError(false);
    _fetch().then((c) => { if (alive) setCatalog(c); }).catch(() => { if (alive) setError(true); });
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
          </>
        )}
      </div>
    </div>
  );
}
