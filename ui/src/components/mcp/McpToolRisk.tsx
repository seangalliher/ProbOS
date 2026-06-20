/** AD-1019d: per-tool risk-tier authoring — the operator surface for the
 *  AD-1019e risk-override backend (the "keys" governance model).
 *
 *  For a single MCP server, an operator sets each tool's effective risk tier:
 *  ``open`` (routine — runs without a gate), ``confirm`` (ask — a human/agent
 *  confirmation), or ``consensus`` (quorum — a multi-agent vote). A tier write
 *  is a per-(server, tool) override; "Default" reverts to the server default.
 *  Mounted as an expandable "Tool risk" section inside each ``McpServersPanel``
 *  server row (sibling to the AD-1019a "Agent access" section), so the panel
 *  diff stays small and this stays self-contained.
 *
 *  Backend (AD-1019e, live):
 *    - ``GET    /api/mcp/servers/{id}/tools``                → tools + risk/risk_source.
 *    - ``PUT    /api/mcp/servers/{id}/tools/{tool}/risk`` {risk} → set override.
 *    - ``DELETE /api/mcp/servers/{id}/tools/{tool}/risk``   → clear override.
 *
 *  HXI: inline SVG stroke glyphs (strokeWidth 1.5) — hammer (open), sidearm
 *  (confirm), torpedo (consensus) — amber active / dim inactive, NO emoji, a
 *  ``data-testid`` on every interactive element, honest-degrade (a GET 404 means
 *  management disabled; the risk fields are simply absent when no risk store).
 */
import { useEffect, useState, useCallback } from 'react';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

// --------------------------------------------------------------------------- //
// Types — the AD-1019e tools endpoint shape (risk fields are optional: they are
// omitted when the runtime has no risk store).
// --------------------------------------------------------------------------- //
export interface McpServerTool {
  name: string;
  description?: string;
  risk?: string;
  risk_source?: string;
}

export interface McpToolRiskResult {
  tools: McpServerTool[];
  count: number;
  error?: string;
  /** True when GET 404 — management is disabled (or the server vanished). */
  disabled?: boolean;
}

/** Injectable IO seam — every entry defaults to a real ``fetch`` below, with the
 *  component's ``serverId`` prop bound into the default implementations. */
export interface McpToolRiskDeps {
  fetchTools: () => Promise<McpToolRiskResult>;
  setRisk: (tool: string, risk: string) => Promise<void>;
  clearRisk: (tool: string) => Promise<void>;
}

// --------------------------------------------------------------------------- //
// Real API calls — serverId-parameterized; the component binds its prop in.
// --------------------------------------------------------------------------- //
export async function fetchServerToolsApi(serverId: string): Promise<McpToolRiskResult> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(serverId)}/tools`);
  if (resp.status === 404) return { tools: [], count: 0, disabled: true };
  if (!resp.ok) throw new Error(`mcp tools fetch failed: ${resp.status}`);
  const d = await resp.json();
  // Pass rows untouched — preserve risk / risk_source when present.
  return {
    tools: Array.isArray(d?.tools) ? d.tools : [],
    count: typeof d?.count === 'number' ? d.count : 0,
    error: typeof d?.error === 'string' ? d.error : undefined,
  };
}

export async function setRiskApi(serverId: string, tool: string, risk: string): Promise<void> {
  const resp = await fetch(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(tool)}/risk`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ risk }),
    },
  );
  if (!resp.ok) throw new Error(`mcp set risk failed: ${resp.status}`);
}

export async function clearRiskApi(serverId: string, tool: string): Promise<void> {
  const resp = await fetch(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(tool)}/risk`,
    { method: 'DELETE' },
  );
  if (!resp.ok) throw new Error(`mcp clear risk failed: ${resp.status}`);
}

// --------------------------------------------------------------------------- //
// Inline SVG stroke glyphs (HXI #3: no emoji, stroke-only, no fills). One per
// risk tier — visually distinct, escalating consequence: hammer → sidearm →
// torpedo.
// --------------------------------------------------------------------------- //
const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

/** Hammer — ``open`` (routine: build/act without a gate). */
function IconHammer({ color = _DIM }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M14 3 L21 10 L17.5 13.5 L10.5 6.5 Z" />
      <path d="M12 8 L4 16 L6 18 L14 10" />
    </svg>
  );
}

/** Sidearm — ``confirm`` (ask: a human/agent confirmation gate). */
function IconSidearm({ color = _DIM }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M4 8 H19 V11 H11 L9 15 H6 L7 11 H4 Z" />
      <path d="M16 8 V6" />
    </svg>
  );
}

/** Torpedo — ``consensus`` (quorum: a multi-agent vote). */
function IconTorpedo({ color = _DIM }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M5 12 C5 9.5 9 9 13 9 C16.5 9 19 10.5 19 12 C19 13.5 16.5 15 13 15 C9 15 5 14.5 5 12 Z" />
      <path d="M5 12 L2 9.5 M5 12 L2 14.5" />
      <path d="M12 9.5 L12 14.5" />
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
// Shared styles + tier metadata.
// --------------------------------------------------------------------------- //
function btnStyle(active = true): React.CSSProperties {
  const c = active ? _AMBER : _DIM;
  return {
    fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 0.5,
    color: c, background: 'transparent', border: `1px solid ${c}`, borderRadius: 3,
    padding: '2px 7px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5,
  };
}

function badgeStyle(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontFamily: "'JetBrains Mono', monospace", color,
    border: `1px solid ${color}55`, borderRadius: 3, padding: '1px 6px',
  };
}

interface Tier {
  value: string;
  label: string;
  Icon: ({ color }: { color?: string }) => React.ReactElement;
}

const _TIERS: Tier[] = [
  { value: 'open', label: 'Routine', Icon: IconHammer },
  { value: 'confirm', label: 'Ask', Icon: IconSidearm },
  { value: 'consensus', label: 'Quorum', Icon: IconTorpedo },
];

function sourceColor(source: string | undefined): string {
  return source === 'override' ? _AMBER : _DIM;
}

interface Props {
  serverId: string;
  serverName: string;
  deps?: Partial<McpToolRiskDeps>;
}

export function McpToolRisk({ serverId, serverName, deps }: Props) {
  const _fetchTools = deps?.fetchTools ?? (() => fetchServerToolsApi(serverId));
  const _setRisk = deps?.setRisk ?? ((tool: string, risk: string) => setRiskApi(serverId, tool, risk));
  const _clearRisk = deps?.clearRisk ?? ((tool: string) => clearRiskApi(serverId, tool));

  const [result, setResult] = useState<McpToolRiskResult | null>(null);
  const [error, setError] = useState(false);

  const reload = useCallback(async () => {
    try {
      const r = await _fetchTools();
      setResult(r);
      setError(false);
    } catch {
      setError(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  // On mount (per serverId): fetch the server's tools + their resolved risk.
  useEffect(() => {
    let alive = true;
    setResult(null);
    setError(false);
    _fetchTools()
      .then((r) => { if (alive) setResult(r); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverId]);

  const onSet = useCallback(async (tool: string, risk: string) => {
    try {
      await _setRisk(tool, risk);
      await reload();
    } catch {
      setError(true);
    }
  }, [_setRisk, reload]);

  const onClear = useCallback(async (tool: string) => {
    try {
      await _clearRisk(tool);
      await reload();
    } catch {
      setError(true);
    }
  }, [_clearRisk, reload]);

  const disabled = result?.disabled === true;

  return (
    <div
      data-testid={`mcp-tool-risk-${serverId}`}
      style={{
        marginTop: 8, border: '1px solid rgba(255,255,255,0.06)', borderRadius: 5,
        padding: '8px 10px', background: 'rgba(255,255,255,0.015)',
        fontFamily: "'JetBrains Mono', monospace", color: _TEXT,
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: 1, color: _AMBER, textTransform: 'uppercase', marginBottom: 8 }}>
        Tool risk — {serverName}
      </div>

      {disabled ? (
        <div data-testid={`mcp-risk-disabled-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>
          MCP management is disabled.
        </div>
      ) : error ? (
        <div data-testid={`mcp-risk-error-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>
          Tool risk unavailable.
        </div>
      ) : result === null ? (
        <div data-testid={`mcp-risk-loading-${serverId}`} style={{ color: _DIM, fontSize: 11 }}>Loading tools…</div>
      ) : result.tools.length === 0 ? (
        <div data-testid={`mcp-risk-empty-${serverId}`} style={{ color: '#555568', fontSize: 11 }}>No tools enumerated.</div>
      ) : (
        <>
          {result.error && (
            <div data-testid={`mcp-risk-note-${serverId}`} style={{ color: _DIM, fontSize: 10, marginBottom: 6 }}>
              Tool list partial ({result.error}).
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {result.tools.map((t) => {
              const active = t.risk ?? 'open';
              return (
                <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ color: _TEXT, fontSize: 10, minWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</span>
                  {t.risk_source && (
                    <span
                      data-testid={`mcp-risk-source-${serverName}-${t.name}`}
                      style={badgeStyle(sourceColor(t.risk_source))}
                    >
                      {t.risk_source}
                    </span>
                  )}
                  <span style={{ flex: 1 }} />
                  {_TIERS.map((tier) => {
                    const on = active === tier.value;
                    return (
                      <button
                        key={tier.value}
                        data-testid={`mcp-risk-${serverName}-${t.name}-${tier.value}`}
                        onClick={() => onSet(t.name, tier.value)}
                        style={btnStyle(on)}
                        aria-label={`Set ${t.name} risk to ${tier.label}`}
                        aria-pressed={on}
                      >
                        <tier.Icon color={on ? _AMBER : _DIM} />{tier.label}
                      </button>
                    );
                  })}
                  <button
                    data-testid={`mcp-risk-reset-${serverName}-${t.name}`}
                    onClick={() => onClear(t.name)}
                    style={btnStyle(false)}
                    aria-label={`Reset ${t.name} risk to default`}
                  >
                    <IconReset />Default
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

export default McpToolRisk;
