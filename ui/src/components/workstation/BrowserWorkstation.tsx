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
import { useState, useEffect } from 'react';
import type { NativeWorkstationProps } from './WorkstationLauncher';
import { BrowserStreamPanel } from '../browser/BrowserStreamPanel';

type BrowserMode = 'embedded' | 'watch' | 'bridge';

/** AD-1052a: one active browser session as projected by GET /api/browser/sessions. */
type SessionRow = { session_id: string; agent_id: string; streaming_url: string | null; last_url: string };
type SessionsResponse = { enabled: boolean; sessions: SessionRow[] };
/** AD-1052b: POST /api/browser/bridge/connect response. */
type BridgeConnectResponse = {
  connected: boolean; reason?: string | null;
  session_id?: string | null; streaming_url?: string | null;
};
type Props = NativeWorkstationProps & {
  /** Injectable for deterministic tests; defaults to the same-origin fetch (no token — DD-1). */
  fetchSessions?: () => Promise<SessionsResponse>;
  /** AD-1052b: injectable for tests; defaults to the same-origin POST (no token — DD-1). */
  connectBridge?: (endpoint: string) => Promise<BridgeConnectResponse>;
};

/** AD-1052a / DD-1: same-origin fetch with NO token. The HXI calls require_crew_scope
 *  endpoints same-origin (pass-through while auth.crew_scope_token==""); a set token
 *  honest-degrades to the "unavailable" state exactly like every other HXI surface. */
const _defaultFetchSessions = async (): Promise<SessionsResponse> => {
  const res = await fetch('/api/browser/sessions');
  if (!res.ok) throw new Error(`sessions ${res.status}`);
  return res.json();
};

/** AD-1052b / DD-1: same-origin POST with NO token. `confirm:true` is the Captain's
 *  explicit consent, sent ONLY on the explicit Connect gesture (DD-2). */
const _defaultConnectBridge = async (endpoint: string): Promise<BridgeConnectResponse> => {
  const res = await fetch('/api/browser/bridge/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint, confirm: true }),
  });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
};

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

/** AD-1052b: the canonical local CDP endpoint a Captain-launched Chrome exposes
 *  via ``--remote-debugging-port=9222``. */
const _INITIAL_BRIDGE = 'http://127.0.0.1:9222';

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

function IconRefresh({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M3 12 a9 9 0 1 0 3 -6.7 L3 8" />
      <path d="M3 3 V8 H8" />
    </svg>
  );
}

function IconEye({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M2 12 s3.5 -7 10 -7 s10 7 10 7 s-3.5 7 -10 7 s-10 -7 -10 -7 Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function IconLink({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M9 15 L15 9" />
      <path d="M11 7 L13 5 a3.5 3.5 0 0 1 5 5 L16 12" />
      <path d="M13 17 L11 19 a3.5 3.5 0 0 1 -5 -5 L8 12" />
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
  { id: 'watch', label: 'Watch', disabled: false },
  { id: 'bridge', label: 'Bridge', disabled: false },
];

export function BrowserWorkstation({ typeId: _typeId, fetchSessions, connectBridge }: Props): React.ReactElement {
  const _fetchSessions = fetchSessions ?? _defaultFetchSessions;
  const _connectBridge = connectBridge ?? _defaultConnectBridge;
  const [mode, setMode] = useState<BrowserMode>('embedded');
  const [urlInput, setUrlInput] = useState<string>('');
  const [committedUrl, setCommittedUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);

  // AD-1052a: watch-mode session state. Fetched once on entering watch + on Refresh.
  const [sessionsState, setSessionsState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [enabled, setEnabled] = useState<boolean>(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState<number>(0);

  // AD-1052b: bridge-mode state. The endpoint defaults to the canonical local
  // CDP port; `bridgeState` drives the honest-degrade chain.
  const [bridgeEndpoint, setBridgeEndpoint] = useState<string>(_INITIAL_BRIDGE);
  const [bridgeState, setBridgeState] = useState<'idle' | 'connecting' | 'connected' | 'refused'>('idle');
  const [bridgeReason, setBridgeReason] = useState<string | null>(null);
  const [bridgeSession, setBridgeSession] = useState<{ session_id: string; streaming_url: string | null } | null>(null);

  useEffect(() => {
    if (mode !== 'watch') return;
    let cancelled = false;
    setSessionsState('loading');
    setSelectedId(null);
    _fetchSessions()
      .then((data) => {
        if (cancelled) return;
        setSessions(data.sessions);
        setEnabled(data.enabled);
        setSessionsState('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setSessionsState('error');
      });
    return () => {
      cancelled = true;
    };
    // Re-fetch on watch-enter and on Refresh (reloadKey). _fetchSessions is stable
    // (an injected prop in tests, a module const by default) — no auto-poll timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, reloadKey]);

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

  // AD-1052b: the Captain's explicit Connect gesture. `_connectBridge` sends
  // confirm:true (DD-2 one-time consent). On connected:true store the session +
  // reuse the AD-706a stream panel; else surface the honest-degrade reason.
  const onConnect = (): void => {
    const endpoint = bridgeEndpoint;
    setBridgeState('connecting');
    setBridgeReason(null);
    setBridgeSession(null);
    _connectBridge(endpoint)
      .then((res) => {
        if (res.connected) {
          setBridgeSession({ session_id: res.session_id ?? '', streaming_url: res.streaming_url ?? null });
          setBridgeState('connected');
        } else {
          setBridgeReason(res.reason ?? 'Connection refused.');
          setBridgeState('refused');
        }
      })
      .catch(() => {
        setBridgeReason(`Could not connect to ${endpoint}`);
        setBridgeState('refused');
      });
  };

  // AD-1052a: the watch surface — a privacy note + Refresh, then the honest-degrade
  // chain (loading -> unavailable -> disabled -> empty -> session list + live MJPEG).
  const renderWatch = (): React.ReactElement => {
    const body = ((): React.ReactElement => {
      if (sessionsState === 'loading' || sessionsState === 'idle') {
        return (
          <div data-testid="browser-watch-loading" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            Loading sessions…
          </div>
        );
      }
      if (sessionsState === 'error') {
        return (
          <div data-testid="browser-watch-unavailable" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            Browser streaming unavailable.
          </div>
        );
      }
      if (!enabled) {
        return (
          <div data-testid="browser-watch-disabled" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            Browser tool is disabled.
          </div>
        );
      }
      if (sessions.length === 0) {
        return (
          <div data-testid="browser-watch-empty" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            No active browser session.
          </div>
        );
      }
      const sel = selectedId !== null ? sessions.find((s) => s.session_id === selectedId) ?? null : null;
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, minHeight: 0, flex: 1 }}>
          <div data-testid="browser-watch-list" role="list" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sessions.map((s) => {
              const active = s.session_id === selectedId;
              return (
                <button
                  key={s.session_id}
                  data-testid={`browser-watch-session-${s.session_id}`}
                  role="listitem"
                  onClick={() => setSelectedId(s.session_id)}
                  aria-pressed={active}
                  style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
                    padding: '6px 10px', border: '1px solid #33334a', borderRadius: 4,
                    background: active ? 'rgba(240,176,96,0.12)' : 'transparent',
                    color: active ? _AMBER : _TEXT, cursor: 'pointer', fontSize: 12, textAlign: 'left',
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{s.agent_id}</span>
                  <span style={{ color: _DIM, fontSize: 11 }}>{s.last_url || '(no navigation yet)'}</span>
                </button>
              );
            })}
          </div>
          {sel !== null && (
            <div data-testid="browser-watch-stream" style={{ flex: 1, minHeight: 0 }}>
              {/* DD-1: NO token passed to the stream panel. */}
              <BrowserStreamPanel sessionId={sel.session_id} streamingUrl={sel.streaming_url} />
            </div>
          )}
        </div>
      );
    })();

    return (
      <div data-testid="browser-watch" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <IconEye />
          <span data-testid="browser-watch-note" style={{ flex: 1, color: _DIM, fontSize: 11 }}>
            Watching surfaces whatever the agent browses.
          </span>
          <button
            data-testid="browser-watch-refresh"
            onClick={() => setReloadKey((k) => k + 1)}
            aria-label="Refresh sessions"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _DIM, cursor: 'pointer', fontSize: 11 }}
          >
            <IconRefresh />Refresh
          </button>
        </div>
        {body}
      </div>
    );
  };

  // AD-1052b: the bridge surface — an endpoint input + an explicit consent note +
  // a Connect button. On connected, reuse the AD-706a stream panel (DD-6); on
  // refused, surface the backend honest-degrade reason (DD-4).
  const renderBridge = (): React.ReactElement => {
    const connecting = bridgeState === 'connecting';
    return (
      <div data-testid="browser-bridge" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <IconLink color={bridgeState === 'connected' ? _AMBER : _DIM} />
          <input
            data-testid="browser-bridge-endpoint"
            type="text"
            value={bridgeEndpoint}
            onChange={(e) => setBridgeEndpoint(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !connecting) onConnect(); }}
            placeholder="http://127.0.0.1:9222"
            aria-label="CDP endpoint"
            style={{ flex: 1, minWidth: 140, padding: '4px 8px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _TEXT, fontSize: 12 }}
          />
          <button
            data-testid="browser-bridge-connect"
            onClick={onConnect}
            disabled={connecting}
            aria-label="Connect to external browser"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: connecting ? _DIM : _AMBER, cursor: connecting ? 'not-allowed' : 'pointer', fontSize: 11 }}
          >
            <IconLink color={connecting ? _DIM : _AMBER} />Connect
          </button>
        </div>
        <div data-testid="browser-bridge-consent-note" style={{ padding: '6px 12px', color: _DIM, fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          Connecting lets an agent drive this external browser with your logged-in sessions.
        </div>
        {bridgeState === 'connected' && bridgeSession !== null ? (
          <div data-testid="browser-bridge-stream" style={{ flex: 1, minHeight: 0 }}>
            {/* DD-1: NO token passed to the stream panel. */}
            <BrowserStreamPanel sessionId={bridgeSession.session_id} streamingUrl={bridgeSession.streaming_url} />
          </div>
        ) : bridgeState === 'refused' ? (
          <div data-testid="browser-bridge-reason" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            {bridgeReason ?? 'Connection refused.'}
          </div>
        ) : (
          <div data-testid="browser-bridge-idle" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, padding: 24, color: _DIM, fontSize: 12, textAlign: 'center' }}>
            <IconLink />
            <div style={{ maxWidth: 420 }}>
              {connecting
                ? 'Connecting…'
                : 'Launch Chrome with --remote-debugging-port=9222, then Connect to drive it from here.'}
            </div>
          </div>
        )}
      </div>
    );
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
        {mode === 'watch' ? (
          renderWatch()
        ) : mode === 'bridge' ? (
          renderBridge()
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
