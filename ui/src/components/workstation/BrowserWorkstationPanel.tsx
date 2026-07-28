/** AD-1052: BrowserWorkstationPanel — the reachable v1 host for the Browser/
 *  Web-App Workstation (HXI #11 middle tier). A full-screen overlay that renders
 *  the `browser` native workstation component (embedded-iframe mode).
 *
 *  Mirrors the AD-1021 WorkstationPanel exactly: store-flag gated
 *  (`browserWorkstationOpen`, default false -> mounted-but-null when closed),
 *  close via the header X or Escape. The AD-1022 launcher / AD-1023 container
 *  compose the same BrowserWorkstation component via `nativeWorkstations`, so
 *  this overlay and the container share one component (two hosts) — the launcher
 *  seam is proven by test. HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5),
 *  amber active / dim inactive, NO emoji, a data-testid on every interactive
 *  element.
 */
import { useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { BrowserWorkstation } from './BrowserWorkstation';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconClose({ color = _DIM }: { color?: string }): React.ReactElement {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M6 6 L18 18 M18 6 L6 18" /></svg>);
}

function IconBrowser({ color = _AMBER }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <path d="M3 9 H21 M6 6.5 h0.5 M8.5 6.5 h0.5" />
    </svg>
  );
}

export function BrowserWorkstationPanel(): React.ReactElement | null {
  const open = useStore((s) => s.browserWorkstationOpen);
  const close = useCallback(() => useStore.setState({ browserWorkstationOpen: false }), []);

  // Escape-to-close (mirrors WorkstationPanel / McpServersPanel).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close]);

  if (!open) return null;

  return (
    <div
      data-testid="browser-workstation-panel"
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
          <IconBrowser />
          <div>
            <div style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>BROWSER WORKSTATION</div>
            <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
              Open a page, watch an agent's session, or bridge to your own browser.
            </div>
          </div>
        </div>
        <button
          data-testid="browser-workstation-close"
          onClick={close}
          aria-label="Close Browser Workstation"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconClose />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <BrowserWorkstation typeId="browser" />
      </div>
    </div>
  );
}
