/** AD-1052: BrowserWorkstation — the OSS native `browser` workstation type (HXI
 *  #11 middle tier), the third and last workstation alongside the AD-1021
 *  `monaco` editor and the AD-1024 `mcp-app` gallery.
 *
 *  v1 ships the EMBEDDED mode: a sandboxed <iframe> to a human-entered http(s)
 *  URL (the VS Code Simple-Browser pattern), plus the unifying MODE MODEL that
 *  names the follow-on surfaces — Watch (AD-1052a: an MJPEG screencast of an
 *  AD-706 headless session) and Bridge (AD-1052b: connectOverCDP to an external
 *  Chrome) — as visible-but-disabled selector segments. The three modes share
 *  one observation/action contract (the AD-706 vocabulary); v1 reuses NO browser
 *  engine (it is a pure presentational surface) and is default-OFF.
 *
 *  Self-contained: ignores `doc` (mirrors the AD-1024 mcp-app adapter). HXI #3:
 *  inline stroke-SVG glyphs (strokeWidth 1.5), amber active / dim inactive, NO
 *  emoji, a data-testid on every interactive element. Defense-in-depth: a URL
 *  scheme allowlist (http/https only) blocks javascript:/data:/file:/about:
 *  injection before anything reaches the iframe `src`.
 */
import { useState } from 'react';
import type { NativeWorkstationProps } from './WorkstationLauncher';

type BrowserMode = 'embedded' | 'watch' | 'bridge';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconGo({ color = _DIM }: { color?: string }): React.ReactElement {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M5 12 H19 M13 6 L19 12 L13 18" /></svg>);
}

function IconGlobe({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12 H21 M12 3 a14 14 0 0 1 0 18 a14 14 0 0 1 0 -18" />
    </svg>
  );
}

/** Accept http(s) only; prepend `https://` when scheme-less; reject dangerous
 *  schemes (javascript:/data:/file:/blob:/about:/vbscript:) -> null. Exported so
 *  the validation contract is unit-testable independent of the React tree. */
export function _normalizeUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  // Reject dangerous schemes explicitly before any parse (defense-in-depth).
  if (/^(javascript|data|file|blob|about|vbscript):/i.test(trimmed)) return null;
  const candidate = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  return candidate;
}

const _MODES: { id: BrowserMode; label: string; title?: string; disabled: boolean }[] = [
  { id: 'embedded', label: 'Embedded', disabled: false },
  { id: 'watch', label: 'Watch', title: 'Available in AD-1052a', disabled: true },
  { id: 'bridge', label: 'Bridge', title: 'Available in AD-1052b', disabled: true },
];

export function BrowserWorkstation({ typeId: _typeId }: NativeWorkstationProps): React.ReactElement {
  const [mode, setMode] = useState<BrowserMode>('embedded');
  const [urlInput, setUrlInput] = useState<string>('');
  const [committedUrl, setCommittedUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);

  const onGo = (): void => {
    const normalized = _normalizeUrl(urlInput);
    if (normalized === null) {
      setUrlError('Only http(s) URLs are supported.');
      setCommittedUrl(null);
      return;
    }
    setUrlError(null);
    setCommittedUrl(normalized);
  };

  return (
    <div
      data-testid="browser-workstation"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, color: _TEXT }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
          borderBottom: '1px solid rgba(255,255,255,0.08)', flexWrap: 'wrap',
        }}
      >
        {/* Mode selector — the unifying mode model (embedded active; watch/bridge
            visible-but-disabled, named for their follow-on ADs). */}
        <div role="group" aria-label="Browser mode" style={{ display: 'inline-flex', border: '1px solid #33334a', borderRadius: 4, overflow: 'hidden' }}>
          {_MODES.map((m) => {
            const active = m.id === mode;
            return (
              <button
                key={m.id}
                data-testid={`browser-mode-${m.id}`}
                onClick={() => { if (!m.disabled) setMode(m.id); }}
                disabled={m.disabled}
                title={m.title}
                aria-pressed={active}
                style={{
                  padding: '4px 10px', border: 'none',
                  background: active ? 'rgba(240,176,96,0.12)' : 'transparent',
                  color: m.disabled ? _DIM : (active ? _AMBER : '#aaaac0'),
                  cursor: m.disabled ? 'not-allowed' : 'pointer', fontSize: 11, letterSpacing: 0.5,
                }}
              >
                {m.label}
              </button>
            );
          })}
        </div>

        {/* URL entry (embedded mode) */}
        <input
          data-testid="browser-url-input"
          type="text"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onGo(); }}
          placeholder="Enter a URL (https://…)"
          aria-label="URL"
          style={{ flex: 1, minWidth: 140, padding: '4px 8px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _TEXT, fontSize: 12 }}
        />
        <button
          data-testid="browser-go"
          onClick={onGo}
          aria-label="Load URL"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _DIM, cursor: 'pointer', fontSize: 11 }}
        >
          <IconGo />Go
        </button>
      </div>

      {/* URL validation notice (defense-in-depth) */}
      {urlError !== null && (
        <div data-testid="browser-url-error" style={{ padding: '6px 12px', color: _AMBER, fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          {urlError}
        </div>
      )}

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {mode !== 'embedded' ? (
          <div data-testid="browser-mode-pending" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            This mode is not yet available.
          </div>
        ) : committedUrl !== null ? (
          <iframe
            data-testid="browser-frame"
            src={committedUrl}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            referrerPolicy="no-referrer"
            title="Embedded browser"
            style={{ border: 0, width: '100%', height: '100%' }}
          />
        ) : (
          <div
            data-testid="browser-empty"
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, padding: 24, color: _DIM, fontSize: 12, textAlign: 'center' }}
          >
            <IconGlobe />
            <div style={{ maxWidth: 420 }}>
              Enter a URL to load a page. Some sites refuse to embed
              (X-Frame-Options / Content-Security-Policy frame-ancestors); for
              those, use Watch mode (AD-1052a) or Bridge mode (AD-1052b).
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
