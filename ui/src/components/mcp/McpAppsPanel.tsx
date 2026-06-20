/** AD-1024: McpAppsPanel — the HXI overlay hosting the MCP-app gallery.
 *
 *  A standalone full-screen overlay (the AD-1023 Rich Workspace entry point is
 *  deferred, so the gallery gets its own reachable host now), mirroring the
 *  AD-1018 McpServersPanel shell exactly: store-flag gated
 *  (``mcpAppsOpen``, default false -> mounted-but-null when closed), closed via
 *  the header X or Escape. The body is the deps-injectable ``McpAppGallery``.
 *
 *  HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5), amber active / dim
 *  inactive, NO emoji, a ``data-testid`` on every interactive element.
 */
import { useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { McpAppGallery, type McpAppGalleryDeps } from './McpAppGallery';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconClose({ color = _DIM }: { color?: string }): React.ReactElement {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M6 6 L18 18 M18 6 L6 18" /></svg>);
}

function IconApps({ color = _AMBER }: { color?: string }): React.ReactElement {
  // Four-pane app grid (HXI #3: no emoji) — the MCP-app gallery glyph.
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

interface Props { deps?: McpAppGalleryDeps; }

export function McpAppsPanel({ deps }: Props): React.ReactElement | null {
  const open = useStore((s) => s.mcpAppsOpen);
  const close = useCallback(() => useStore.setState({ mcpAppsOpen: false }), []);

  // Escape-to-close (mirrors McpServersPanel).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close]);

  if (!open) return null;

  return (
    <div
      data-testid="mcp-apps-panel"
      style={{
        position: 'fixed', inset: 0, zIndex: 30, background: 'rgba(6,6,12,0.94)',
        backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        display: 'flex', flexDirection: 'column', fontFamily: "'JetBrains Mono', monospace",
        color: _TEXT,
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <IconApps />
          <div>
            <div style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>MCP APPS</div>
            <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
              Launch a registered MCP app into a sandboxed frame.
            </div>
          </div>
        </div>
        <button
          data-testid="mcp-apps-close"
          onClick={close}
          aria-label="Close MCP Apps"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconClose />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <McpAppGallery deps={deps} />
      </div>
    </div>
  );
}

export default McpAppsPanel;
