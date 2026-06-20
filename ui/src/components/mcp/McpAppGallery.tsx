/** AD-1024: McpAppGallery — the inner MCP-app launcher surface.
 *
 *  Lists the registered MCP apps from GET /api/mcp-apps (via the injectable
 *  ``fetchApps`` dep) and opens one into the already-built sandboxed
 *  ``McpAppFrame`` (AD-597a) — reusing the AD-597 engine end-to-end (the frame
 *  fetches ``GET /api/mcp/resource?uri=`` for the app's ``ui://`` resource). The
 *  list+active pattern mirrors the AD-1022 WorkstationLauncher.
 *
 *  Deps-injectable (HXI convention, mirrors WorkstationLauncher/McpServersPanel)
 *  so tests need no global fetch mock. Honest-degrade: a fetch throw collapses to
 *  ``{apps:[], disabled:true}`` (never a crash). HXI #3: stroke-SVG glyph, NO
 *  emoji; amber active / dim inactive.
 */
import { useEffect, useState } from 'react';
import { McpAppFrame } from '../McpAppFrame';
import { fetchMcpAppsApi, type McpApp, type McpAppsResult } from './mcpAppsApi';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

export interface McpAppGalleryDeps {
  /** Fetch the registered MCP apps. Defaults to the real endpoint. */
  fetchApps?: () => Promise<McpAppsResult>;
  /** Sandboxed iframe renderer. Defaults to the AD-597a McpAppFrame. */
  IframeFrame?: typeof McpAppFrame;
}

const glyphStyle = {
  width: 14,
  height: 14,
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  fill: 'none',
};

function AppGlyph({ external }: { external: boolean }): React.ReactElement {
  // Stroke-only SVG glyph (HXI #3: no emoji). A framed app window; a small
  // outbound notch marks an external-server app.
  return (
    <svg viewBox="0 0 16 16" style={glyphStyle} stroke="currentColor" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M2 6h12" />
      {external ? <path d="M10 9l3 -3 M13 6v2 M13 6h-2" /> : null}
    </svg>
  );
}

export function McpAppGallery({ deps }: { deps?: McpAppGalleryDeps }): React.ReactElement {
  const fetchApps = deps?.fetchApps ?? fetchMcpAppsApi;
  const IframeFrame = deps?.IframeFrame ?? McpAppFrame;

  const [apps, setApps] = useState<McpApp[] | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [activeName, setActiveName] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchApps()
      .then((r) => {
        if (alive) {
          setApps(r.apps);
          setDisabled(r.disabled);
        }
      })
      .catch(() => {
        // Network/parse errors honest-degrade to a disabled-style empty state.
        if (alive) {
          setApps([]);
          setDisabled(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [fetchApps]);

  if (apps === null) {
    return (
      <div data-testid="mcp-app-gallery" style={{ height: '100%', color: _TEXT }}>
        <div data-testid="mcp-app-loading" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
          Loading MCP apps…
        </div>
      </div>
    );
  }

  const active = apps.find((a) => a.name === activeName) ?? null;

  return (
    <div
      data-testid="mcp-app-gallery"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', color: _TEXT }}
    >
      {disabled ? (
        <div data-testid="mcp-app-disabled" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
          MCP App Host disabled.
        </div>
      ) : apps.length === 0 ? (
        <div data-testid="mcp-app-empty" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
          No MCP apps available.
        </div>
      ) : (
        <>
          <div
            data-testid="mcp-app-list"
            style={{ display: 'flex', gap: 6, padding: 8, flexWrap: 'wrap' }}
          >
            {apps.map((app) => {
              const isActive = app.name === activeName;
              return (
                <button
                  key={app.name}
                  type="button"
                  data-testid={`mcp-app-${app.name}`}
                  title={app.description || app.name}
                  onClick={() => setActiveName(app.name)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '4px 10px',
                    border: `1px solid ${isActive ? _AMBER : '#33334a'}`,
                    borderRadius: 4,
                    background: 'transparent',
                    color: isActive ? _AMBER : _DIM,
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  <AppGlyph external={app.external} />
                  <span>{app.name}</span>
                </button>
              );
            })}
          </div>
          {active && (
            <div data-testid="mcp-app-frame" style={{ flex: 1, minHeight: 0 }}>
              <IframeFrame
                resourceUri={active.resource_uri}
                toolName={active.name}
                external={active.external}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default McpAppGallery;
