/** AD-1021: WorkstationPanel — the reachable v1 host for the Code/Text
 *  Workstation (HXI #11 middle tier). A full-screen overlay that renders the
 *  `monaco` native workstation component directly from the store's active
 *  document.
 *
 *  The AD-1022 WorkstationLauncher is backend-gated (GET /api/workstations/types)
 *  and not yet mounted into App (its container is AD-1023), so this overlay is
 *  the reachable surface in v1. Same CodeWorkstation component, two hosts — the
 *  launcher seam is proven by test (deps.nativeComponents = nativeWorkstations).
 *
 *  Mirrors the McpServersPanel overlay exactly: store-flag gated
 *  (`workstationOpen`, default false -> mounted-but-null when closed), close via
 *  the header X or Escape. HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5),
 *  amber active / dim inactive, NO emoji, a data-testid on every interactive
 *  element.
 */
import { useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { CodeWorkstation } from './CodeWorkstation';

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

function IconWorkstation({ color = _AMBER }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="3" y="4" width="18" height="13" rx="1.5" />
      <path d="M3 8 H21 M9 21 H15 M12 17 V21" />
    </svg>
  );
}

export function WorkstationPanel(): React.ReactElement | null {
  const open = useStore((s) => s.workstationOpen);
  const close = useCallback(() => useStore.getState().closeWorkstation(), []);

  // Escape-to-close (mirrors McpServersPanel).
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
      data-testid="workstation-panel"
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
          <IconWorkstation />
          <div>
            <div style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>WORKSTATION</div>
            <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
              View proposed file changes or edit a scratch buffer.
            </div>
          </div>
        </div>
        <button
          data-testid="workstation-close"
          onClick={close}
          aria-label="Close Workstation"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconClose />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <CodeWorkstation typeId="monaco" />
      </div>
    </div>
  );
}
