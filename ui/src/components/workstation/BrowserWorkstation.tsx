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
import { useState, useEffect, useRef } from 'react';
import type { NativeWorkstationProps } from './WorkstationLauncher';
import { BrowserStreamPanel } from '../browser/BrowserStreamPanel';
import type { ForwardInputEvent } from '../browser/BrowserStreamPanel';

type BrowserMode = 'embedded' | 'watch' | 'bridge';

/** AD-1052a: one active browser session as projected by GET /api/browser/sessions. */
type SessionSnapshot = {
  session_id: string;
  state?: 'creating' | 'active' | 'ending' | 'cleanup_failed' | 'ended';
  owner_id?: string | null;
  sharing_scope?: string;
  recording_state?: string;
  recording_scope?: string;
  pending_work?: number | null;
  expires_at?: number | null;
  external_browser?: boolean;
};
type SessionRow = SessionSnapshot & { agent_id: string; streaming_url: string | null; last_url: string };
type SessionsResponse = { enabled: boolean; sessions: SessionRow[]; input_forwarding_enabled?: boolean; authority_basis?: string };
type LifecycleAction = 'end' | 'handoff';
type LifecycleResponse = { outcome: string; reason: string; status_code: number; session?: SessionSnapshot | null };
/** AD-1052b: POST /api/browser/bridge/connect response. */
type BridgeConnectResponse = {
  connected: boolean; reason?: string | null;
  session_id?: string | null; streaming_url?: string | null;
};
/** AD-1052c: POST /api/browser/sessions/{id}/input response. */
type ForwardInputResponse = { forwarded: boolean; reason?: string | null };
/** AD-1161: POST /api/browser/sessions response. */
type OpenSessionResponse = {
  opened: boolean; reason?: string | null;
  session_id?: string | null; streaming_url?: string | null;
  url?: string | null; page_title?: string | null;
};
type Props = NativeWorkstationProps & {
  /** Injectable for deterministic tests; defaults to the same-origin fetch (no token — DD-1). */
  fetchSessions?: () => Promise<SessionsResponse>;
  /** AD-1052b: injectable for tests; defaults to the same-origin POST (no token — DD-1). */
  connectBridge?: (endpoint: string) => Promise<BridgeConnectResponse>;
  /** AD-1052c: injectable for tests; defaults to the same-origin POST (no token — DD-1). */
  forwardInput?: (sessionId: string, evt: ForwardInputEvent) => Promise<ForwardInputResponse>;
  /** AD-1161: injectable for tests; defaults to the same-origin POST (no token — DD-1). */
  openSession?: (url: string) => Promise<OpenSessionResponse>;
  changeLifecycle?: (sessionId: string, action: LifecycleAction) => Promise<LifecycleResponse>;
};

const _defaultChangeLifecycle = async (sessionId: string, action: LifecycleAction): Promise<LifecycleResponse> => {
  const response = await fetch(`/api/browser/sessions/${encodeURIComponent(sessionId)}/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  });
  const result = await response.json();
  return {
    outcome: response.ok ? result.outcome : (result.outcome ?? 'rejected'),
    reason: typeof result.reason === 'string' ? result.reason : `Request rejected (${response.status}).`,
    status_code: response.status, session: result.session,
  };
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

/** AD-1052c / DD-1: same-origin POST with NO token. Forwards ONE captured human
 *  input event to the live page; honest-degrades to {forwarded:false} on a
 *  non-2xx so the UI never throws on a refusal. */
const _defaultForwardInput = async (
  sessionId: string, evt: ForwardInputEvent,
): Promise<ForwardInputResponse> => {
  const body: Record<string, unknown> = { kind: evt.kind };
  if (evt.kind === 'click') { body.nx = evt.nx; body.ny = evt.ny; body.button = evt.button; }
  else if (evt.kind === 'scroll') { body.nx = evt.nx; body.ny = evt.ny; body.dx = evt.dx; body.dy = evt.dy; }
  else if (evt.kind === 'type') { body.text = evt.text; }
  else if (evt.kind === 'key') { body.key = evt.key; }
  const res = await fetch(`/api/browser/sessions/${encodeURIComponent(sessionId)}/input`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) return { forwarded: false, reason: `input ${res.status}` };
  return res.json();
};

/** AD-1161 / DD-1: same-origin POST with NO token. Opens a browser session ON THE
 *  CAPTAIN'S BEHALF — the counterpart to a session that only ever existed once an
 *  agent called goto. Honest-degrades to {opened:false} on a non-2xx so the Open
 *  button never throws and never strands a spinner. */
const _defaultOpenSession = async (url: string): Promise<OpenSessionResponse> => {
  const res = await fetch('/api/browser/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) return { opened: false, reason: `open ${res.status}` };
  return res.json();
};

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';
const _ACTION_STYLE: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
  border: '1px solid #33334a', borderRadius: 4, background: 'transparent',
  color: _TEXT, fontSize: 12, fontFamily: 'inherit', cursor: 'pointer',
};

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

function IconClose({ color = _DIM }: { color?: string }): React.ReactElement {
  return <svg {..._svgBase(color)} aria-hidden="true"><path d="M6 6L18 18M18 6L6 18" /></svg>;
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

/** AD-1052c: a stroke-based cursor/pointer glyph for the Drive toggle (HXI #3). */
function IconDrive({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M5 3 L19 12 L12 13 L16 20 L13 21 L9 14 L5 17 Z" />
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

export function BrowserWorkstation({ typeId: _typeId, fetchSessions, connectBridge, forwardInput, openSession, changeLifecycle }: Props): React.ReactElement {
  const _fetchSessions = fetchSessions ?? _defaultFetchSessions;
  const _connectBridge = connectBridge ?? _defaultConnectBridge;
  const _forwardInput = forwardInput ?? _defaultForwardInput;
  const _openSession = openSession ?? _defaultOpenSession;
  const _changeLifecycle = changeLifecycle ?? _defaultChangeLifecycle;
  // AD-1161: `embedded` is an iframe, and every interesting target (Word Online,
  // OneDrive, most SaaS) sends X-Frame-Options/frame-ancestors and refuses to
  // render in one. Landing the Captain on a mode that cannot show the thing they
  // came for is the wrong default, so the mount probe below flips this to
  // 'watch' whenever the backend reports the browser tool enabled.
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
  // AD-1052c: input-forwarding governance. `inputForwardingEnabled` mirrors the
  // backend flag (DD-4) — the Drive toggle only renders when it is true.
  // `driveEnabled` is the Captain's explicit per-session take-the-wheel gesture.
  const [inputForwardingEnabled, setInputForwardingEnabled] = useState<boolean>(false);
  const [driveEnabled, setDriveEnabled] = useState<boolean>(false);

  // AD-1161: watch-mode "open a page for me" state. `openState` drives the
  // button's disabled/label; `openReason` carries the backend honest-degrade
  // string and renders where bridge mode renders `bridgeReason`.
  const [openUrlInput, setOpenUrlInput] = useState<string>('');
  const [openState, setOpenState] = useState<'idle' | 'opening'>('idle');
  const [openReason, setOpenReason] = useState<string | null>(null);

  // AD-1052b: bridge-mode state. The endpoint defaults to the canonical local
  // CDP port; `bridgeState` drives the honest-degrade chain.
  const [bridgeEndpoint, setBridgeEndpoint] = useState<string>(_INITIAL_BRIDGE);
  const [bridgeState, setBridgeState] = useState<'idle' | 'connecting' | 'connected' | 'refused'>('idle');
  const [bridgeReason, setBridgeReason] = useState<string | null>(null);
  const [bridgeSession, setBridgeSession] = useState<{ session_id: string; streaming_url: string | null } | null>(null);
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const inputGeneration = useRef(0);
  const manualMode = useRef(false);
  const [authority, setAuthority] = useState<string>('unknown');
  const [watching, setWatching] = useState(true);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<LifecycleAction | null>(null);
  const [pending, setPending] = useState(false);
  const [streamGeneration, setStreamGeneration] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const dialog = useRef<HTMLDivElement>(null);
  const activeId = mode === 'watch' ? selectedId : mode === 'bridge' ? bridgeSession?.session_id ?? null : null;
  const activeSession = sessions.find((session) => session.session_id === activeId);
  const expired = activeSession?.expires_at != null && activeSession.expires_at * 1000 <= clock;
  const releaseInput = (): void => {
    inputGeneration.current += 1;
    setDriveEnabled(false);
  };
  const resetView = (): void => {
    generation.current += 1;
    listGeneration.current += 1;
    releaseInput();
    setWatching(true);
    setViewerError(null);
    setNotice(null);
    setConfirmation(null);
    setPending(false);
    setOpenState('idle');
    setBridgeState((current) => current === 'connecting' ? 'idle' : current);
  };
  const acceptListing = (data: SessionsResponse): void => {
    setSessions(data.sessions);
    setEnabled(data.enabled);
    setInputForwardingEnabled(data.input_forwarding_enabled ?? false);
    setAuthority(data.authority_basis ?? 'unknown');
    setClock(Date.now());
    setSessionsState('ready');
  };
  const refreshSessions = (): void => {
    generation.current += 1;
    listGeneration.current += 1;
    releaseInput();
    setPending(false);
    setOpenState('idle');
    setConfirmation(null);
    setReloadKey((current) => current + 1);
  };
  useEffect(() => () => {
    generation.current += 1;
    listGeneration.current += 1;
    inputGeneration.current += 1;
  }, []);
  useEffect(() => {
    if (!activeId || !watching || pending || confirmation) return;
    let inFlight = false;
    const timer = window.setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      const request = ++listGeneration.current;
      const view = generation.current;
      void _fetchSessions().then((data) => {
        if (request !== listGeneration.current || view !== generation.current) return;
        acceptListing(data);
        const session = data.sessions.find((row) => row.session_id === activeId);
        if (!data.enabled || !data.input_forwarding_enabled || session?.state !== 'active' || (session.expires_at != null && session.expires_at * 1000 <= Date.now())) releaseInput();
        if (!session || session.state !== 'active' || !data.enabled) setViewerError('Session unavailable. Viewer disconnected.');
      }).catch(() => {
        if (request !== listGeneration.current || view !== generation.current) return;
        releaseInput();
        setSessionsState('error');
        setViewerError('Could not verify session state. Viewer disconnected.');
      }).finally(() => { inFlight = false; });
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, watching, pending, confirmation, mode]);
  useEffect(() => {
    if (!activeSession?.expires_at) return;
    const delay = activeSession.expires_at * 1000 - Date.now();
    if (delay <= 0) { releaseInput(); setClock(Date.now()); return; }
    const timer = window.setTimeout(() => {
      releaseInput();
      setClock(Date.now());
      setReloadKey((current) => current + 1);
    }, Math.min(delay, 2147483647));
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, activeSession?.expires_at]);
  useEffect(() => {
    if (!confirmation) return;
    const previous = document.activeElement;
    dialog.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, [confirmation]);

  // AD-1161: resolve the initial mode from the SAME /api/browser/sessions probe
  // the watch surface already uses (no second endpoint). Mount-only: once the
  // Captain picks a mode by hand, nothing may move it under them.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await _fetchSessions();
        if (cancelled || manualMode.current) return;
        setEnabled(data.enabled);
        setInputForwardingEnabled(data.input_forwarding_enabled ?? false);
        if (data.enabled && !manualMode.current) setMode('watch');
      } catch {
        // Honest-degrade: no backend answer means no browser tool, so the
        // iframe-based embedded mode stays the default. Nothing to surface.
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (mode === 'embedded') return;
    let cancelled = false;
    const request = ++listGeneration.current;
    releaseInput();
    setSessionsState('loading');
    _fetchSessions()
      .then((data) => {
        if (cancelled || request !== listGeneration.current) return;
        acceptListing(data);
      })
      .catch(() => {
        if (cancelled || request !== listGeneration.current) return;
        setSessionsState('error');
        releaseInput();
        setViewerError('Could not verify session state. Viewer disconnected.');
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

  // AD-1161: the Captain's "open a page for me" gesture. Nothing else CREATES a
  // session — before this, one existed only once an agent called goto. On
  // opened:true refresh the picker and auto-select the new session so the
  // stream appears without a second click; else surface the backend reason.
  const onOpen = (): void => {
    const normalized = _normalizeUrl(openUrlInput);
    if (normalized === null) {
      setOpenReason('Only http(s) URLs are supported.');
      return;
    }
    setOpenState('opening');
    setOpenReason(null);
    releaseInput();
    const request = ++generation.current;
    listGeneration.current += 1;
    _openSession(normalized)
      .then((res) => {
      if (request !== generation.current) return;
        if (!res.opened) {
          setOpenReason(res.reason ?? 'Could not open that URL.');
          refreshSessions();
          return;
        }
        const sid = res.session_id ?? '';
        if (sid) { setSelectedId(sid); setWatching(true); setViewerError(null); setConfirmation(null); }
        // A refresh failure must NOT be reported as an open failure — the
        // session is open either way; the list just stays stale until Refresh.
        return _fetchSessions()
          .then((data) => {
            if (request !== generation.current) return;
            acceptListing(data);
          })
          .catch(() => {
            if (request !== generation.current) return;
            setSessionsState('error');
            setOpenReason('Session opened. Refresh sessions to view it.');
          });
      })
      .catch(() => {
        if (request !== generation.current) return;
        setOpenReason('Could not open that URL.');
        refreshSessions();
      })
      .finally(() => {
        if (request === generation.current) setOpenState('idle');
      });
  };

  // AD-1052b: the Captain's explicit Connect gesture. `_connectBridge` sends
  // confirm:true (DD-2 one-time consent). On connected:true store the session +
  // reuse the AD-706a stream panel; else surface the honest-degrade reason.
  const onConnect = (): void => {
    const endpoint = bridgeEndpoint;
    resetView();
    const request = generation.current;
    setBridgeState('connecting');
    setBridgeReason(null);
    setBridgeSession(null);
    _connectBridge(endpoint)
      .then((res) => {
        if (request !== generation.current) return;
        if (res.connected) {
          setBridgeSession({ session_id: res.session_id ?? '', streaming_url: res.streaming_url ?? null });
          setBridgeState('connected');
          setReloadKey((current) => current + 1);
        } else {
          setBridgeReason(res.reason ?? 'Connection refused.');
          setBridgeState('refused');
        }
      })
      .catch(() => {
        if (request !== generation.current) return;
        setBridgeReason(`Could not connect to ${endpoint}`);
        setBridgeState('refused');
      });
  };

  // AD-1052c: the Drive toggle (DD-4). Renders ONLY when the backend
  // input_forwarding_enabled flag is on — never appears (silently) when off.
  // Toggling flips `driveEnabled`, which the panel mounts pass to the stream
  // <img> to switch it from read-only to input-capturing.
  const renderDriveToggle = (): React.ReactElement | null => {
    if (!inputForwardingEnabled) return null;
    return (
      <button
        data-testid="browser-watch-drive"
        onClick={() => { if (driveEnabled) releaseInput(); else setDriveEnabled(true); }}
        disabled={!activeId || !watching || !!viewerError || expired || pending || confirmation !== null || sessionsState !== 'ready' || activeSession?.state !== 'active'}
        aria-pressed={driveEnabled}
        aria-label={driveEnabled ? 'Release control' : 'Drive the browser'}
        title={driveEnabled ? 'Release control in this view only' : 'Drive the browser in this view'}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
          border: '1px solid #33334a', borderRadius: 4,
          background: driveEnabled ? 'rgba(240,176,96,0.12)' : 'transparent',
          color: driveEnabled ? _AMBER : _DIM, cursor: 'pointer', fontSize: 11,
        }}
      >
        <IconDrive color={driveEnabled ? _AMBER : _DIM} />{driveEnabled ? 'Release control' : 'Drive'}
      </button>
    );
  };

  const reconnect = async (): Promise<void> => {
    releaseInput();
    const request = ++generation.current;
    const listingRequest = ++listGeneration.current;
    const sessionId = activeId;
    setPending(true);
    setConfirmation(null);
    try {
      const data = await _fetchSessions();
      if (request !== generation.current || listingRequest !== listGeneration.current) return;
      acceptListing(data);
      const session = data.sessions.find((row) => row.session_id === sessionId);
      if (!data.enabled || session?.state !== 'active' || (session.expires_at != null && session.expires_at * 1000 <= Date.now())) {
        setViewerError('Session unavailable or expired. Viewer remains disconnected.');
        return;
      }
      setViewerError(null);
      setWatching(true);
      setStreamGeneration((current) => current + 1);
    } catch {
      if (request === generation.current) setViewerError('Could not verify session state. Viewer remains disconnected.');
    } finally {
      if (request === generation.current) setPending(false);
    }
  };
  const mutateSession = async (): Promise<void> => {
    if (!activeId || !confirmation || pending) return;
    const sessionId = activeId;
    const action = confirmation;
    releaseInput();
    const request = ++generation.current;
    listGeneration.current += 1;
    setPending(true);
    setOpenState('idle');
    setConfirmation(null);
    setNotice(null);
    try {
      const result = await _changeLifecycle(sessionId, action);
      if (request !== generation.current) return;
      if (result.session?.session_id === sessionId) {
        setSessions((current) => current.map((row) => row.session_id === sessionId ? { ...row, ...result.session } : row));
      }
      if (result.status_code === 200 && result.outcome === 'completed') {
        if (action === 'end') {
          setWatching(false);
          setSessions((current) => current.map((row) => row.session_id === sessionId ? { ...row, state: 'ended' } : row));
          setNotice(activeSession?.external_browser ? 'ProbOS disconnected. The external browser remains open.' : 'Session ended. Recordings retained.');
        } else {
          setNotice('Selected for subsequent crew browser work. No crew job started; ownership is unchanged.');
        }
      } else {
        setNotice(`${result.outcome}: ${result.reason.replace(/_/g, ' ')}. Refresh session details before retrying.`);
      }
    } catch {
      if (request === generation.current) setNotice('Session request failed. Refresh session details before retrying.');
    } finally {
      if (request === generation.current) setPending(false);
    }
  };
  const renderViewer = (session: { session_id: string; streaming_url: string | null }): React.ReactElement => {
    if (activeSession?.state === 'ended' || activeSession?.state === 'ending' || activeSession?.state === 'cleanup_failed' || expired) {
      return <div role="status">Session {expired ? 'expired' : activeSession?.state?.replace(/_/g, ' ')}. Control released.</div>;
    }
    if (!watching || viewerError) return <div style={{ padding: 12 }}>
      <div role={viewerError ? 'alert' : 'status'}>{viewerError ?? 'Not watching. The browser session remains open.'}</div>
      <button type="button" style={_ACTION_STYLE} disabled={pending} onClick={() => { void reconnect(); }} aria-label="Reconnect viewer"><IconRefresh />Reconnect</button>
    </div>;
    return <BrowserStreamPanel
      key={`${session.session_id}:${streamGeneration}`}
      sessionId={session.session_id} streamingUrl={session.streaming_url}
      driveEnabled={inputForwardingEnabled && driveEnabled && sessionsState === 'ready' && activeSession?.state === 'active' && !pending && !confirmation}
      onFailure={(reason) => { releaseInput(); setViewerError(reason); }}
      onReconnect={() => { void reconnect(); }}
      onForwardInput={async (event) => {
        const request = generation.current;
        const inputRequest = inputGeneration.current;
        try {
          const response = await _forwardInput(session.session_id, event);
          if (request !== generation.current || inputRequest !== inputGeneration.current) return;
          if (!response.forwarded) {
            releaseInput();
            setViewerError(`Input rejected: ${response.reason ?? 'unknown reason'}. Control released in this view.`);
          }
        } catch {
          if (request !== generation.current || inputRequest !== inputGeneration.current) return;
          releaseInput();
          setViewerError('Input failed. Control released in this view.');
        }
      }}
    />;
  };
  const metadata = (): React.ReactElement => <dl data-testid="browser-session-metadata" style={{ margin: 0, display: 'grid', gridTemplateColumns: 'max-content minmax(0, 1fr)', gap: '4px 12px', overflowWrap: 'anywhere', fontSize: 12 }}>
    <dt>Session</dt><dd style={{ margin: 0 }}>{activeId}</dd>
    <dt>State</dt><dd style={{ margin: 0 }}>{activeSession?.state?.replace(/_/g, ' ') ?? 'Unknown'}</dd>
    <dt>Owner</dt><dd style={{ margin: 0 }}>{activeSession?.owner_id ?? 'Unknown'}</dd>
    <dt>Authority</dt><dd style={{ margin: 0 }}>{authority.replace(/_/g, ' ')}</dd>
    <dt>Crew sharing</dt><dd style={{ margin: 0 }}>{activeSession?.sharing_scope?.replace(/_/g, ' ') ?? 'Unknown'}</dd>
    <dt>Recording</dt><dd style={{ margin: 0 }}>{activeSession?.recording_state ?? 'Unknown'} / {activeSession?.recording_scope?.replace(/_/g, ' ') ?? 'Unknown'}</dd>
    <dt>Pending browser work</dt><dd style={{ margin: 0 }}>{activeSession?.pending_work ?? 'Unknown'}</dd>
    <dt>Expires</dt><dd style={{ margin: 0 }}>{activeSession?.expires_at != null ? new Date(activeSession.expires_at * 1000).toISOString() : 'Unknown'}{expired ? ' (expired)' : ''}</dd>
  </dl>;
  const blockedReason = !activeSession?.owner_id ? 'Ownership is unknown.'
    : activeSession.pending_work == null ? 'Pending browser work is unknown.'
    : activeSession.pending_work > 0 ? 'Pending browser work must settle before retrying.'
    : sessionsState !== 'ready' ? 'Refresh session details before continuing.'
    : !['shared_crew_scope', 'single_operator_compatibility'].includes(authority) ? 'Operator authority is unknown.'
    : !['active', 'cleanup_failed'].includes(activeSession.state ?? '') ? 'Session is not available for this action.' : null;

  // AD-1052a: the watch surface — a privacy note + Refresh, then the honest-degrade
  // chain (loading -> unavailable -> disabled -> empty -> session list + live MJPEG).
  const renderWatch = (): React.ReactElement => {
    const opening = openState === 'opening';
    const body = ((): React.ReactElement => {
      if ((sessionsState === 'loading' || sessionsState === 'idle') && sessions.length === 0) {
        return (
          <div data-testid="browser-watch-loading" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
            Loading sessions…
          </div>
        );
      }
      if (sessionsState === 'error' && !activeId) {
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
          {selectedId && !sel && <div role="status">Selected session unavailable. Viewer disconnected.</div>}
          <div data-testid="browser-watch-list" role="list" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sessions.map((s) => {
              const active = s.session_id === selectedId;
              return (
                <button
                  key={s.session_id}
                  data-testid={`browser-watch-session-${s.session_id}`}
                  role="listitem"
                  onClick={() => {
                    resetView();
                    setSelectedId(s.session_id);
                    if (sessionsState === 'loading') setReloadKey((current) => current + 1);
                  }}
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
              {renderViewer(sel)}
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
            onClick={refreshSessions}
            aria-label="Refresh sessions"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _DIM, cursor: 'pointer', fontSize: 11 }}
          >
            <IconRefresh />Refresh
          </button>
          {renderDriveToggle()}
        </div>
        {/* AD-1161: the Captain opens the page, signs in by hand, and only then
            hands the session to an agent. Lives in the header (not the body) so
            it is reachable from the empty state — the state it exists to fix. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          <IconGlobe color={opening ? _AMBER : _DIM} />
          <input
            data-testid="browser-watch-open-url"
            type="text"
            value={openUrlInput}
            onChange={(e) => setOpenUrlInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !opening) onOpen(); }}
            placeholder="Open a page (https://…)"
            aria-label="URL to open"
            style={{ flex: 1, minWidth: 140, padding: '4px 8px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: _TEXT, fontSize: 12 }}
          />
          <button
            data-testid="browser-watch-open"
            onClick={onOpen}
            disabled={opening}
            aria-label="Open a browser session"
            title="Open a browser session you can sign into, then hand to an agent"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', border: '1px solid #33334a', borderRadius: 4, background: 'transparent', color: opening ? _DIM : _AMBER, cursor: opening ? 'not-allowed' : 'pointer', fontSize: 11 }}
          >
            <IconGo color={opening ? _DIM : _AMBER} />{opening ? 'Opening…' : 'Open'}
          </button>
        </div>
        {openReason !== null && (
          <div data-testid="browser-watch-open-reason" style={{ padding: '6px 12px', color: _DIM, fontSize: 12, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
            {openReason}
          </div>
        )}
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
          {renderDriveToggle()}
        </div>
        <div data-testid="browser-bridge-consent-note" style={{ padding: '6px 12px', color: _DIM, fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          Connecting lets an agent drive this external browser with your logged-in sessions.
        </div>
        {bridgeState === 'connected' && bridgeSession !== null ? (
          <div data-testid="browser-bridge-stream" style={{ flex: 1, minHeight: 0 }}>
            {/* DD-1: NO token passed to the stream panel. */}
            {renderViewer(bridgeSession)}
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
      style={{ position: 'relative', display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, color: _TEXT }}
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
                onClick={() => { manualMode.current = true; if (!m.disabled && m.id !== mode) { resetView(); setMode(m.id); } }}
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

        {/* BF-694: URL entry belongs to EMBEDDED mode only. It was rendered
            unconditionally, which was invisible while 'embedded' was the default
            mode — AD-1161 made 'watch' the default and the Captain saw two
            address bars stacked (this one, plus watch's own "Open a page"). */}
        {mode === 'embedded' && (
          <>
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
          </>
        )}
      </div>

      {activeId && <section aria-label="Selected browser session" style={{ padding: '8px 12px', borderBottom: '1px solid #33334a' }}>
        {!confirmation && metadata()}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          <button type="button" style={_ACTION_STYLE} onClick={() => { generation.current += 1; releaseInput(); setPending(false); setOpenState('idle'); setConfirmation(null); setWatching(false); }} disabled={!watching}><IconEye />Stop watching</button>
          <button type="button" style={_ACTION_STYLE} disabled={pending || !!blockedReason || activeSession?.owner_id !== 'captain' || activeSession?.state !== 'active' || expired} onClick={() => { releaseInput(); setConfirmation('handoff'); }}><IconLink />Hand to crew</button>
          <button type="button" style={_ACTION_STYLE} disabled={pending || !!blockedReason} onClick={() => { releaseInput(); setConfirmation('end'); }}><IconClose />End session</button>
          {mode === 'bridge' && <button type="button" style={_ACTION_STYLE} aria-label="Refresh sessions" title="Refresh sessions" onClick={refreshSessions}><IconRefresh /></button>}
        </div>
        {blockedReason && <div role="status">{blockedReason}</div>}
      </section>}
      {pending && <div role="status" aria-live="polite">Session request pending. Control released in this view.</div>}
      {notice && <div role="status" aria-live="polite" style={{ padding: '8px 12px', overflowWrap: 'anywhere' }}>{notice}</div>}
      {confirmation && activeId && <div style={{ position: 'absolute', inset: 0, zIndex: 2, background: 'rgba(6,6,12,0.94)', display: 'grid', placeItems: 'center', padding: 12 }}>
        <div ref={dialog} role="dialog" aria-modal="true" aria-label={confirmation === 'end' ? 'End selected session' : 'Hand selected session to crew'} tabIndex={-1}
          style={{ background: '#12121c', border: '1px solid #33334a', borderRadius: 4, padding: 16, width: 'min(100%, 520px)', maxHeight: '100%', overflow: 'auto' }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setConfirmation(null); }
            if (event.key === 'Tab') {
              const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
              const first = buttons[0];
              const last = buttons[buttons.length - 1];
              if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last?.focus(); }
              else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
            }
          }}>
          <h2 style={{ fontSize: 16, marginTop: 0 }}>{confirmation === 'end' ? 'End session?' : 'Hand to crew?'}</h2>
          {metadata()}
          <p>{confirmation === 'end' ? (activeSession?.external_browser ? 'ProbOS will disconnect. The external browser, pages and contexts remain open.' : 'Close this session and its owned pages. Retained recordings are not deleted.') : 'Select this session for subsequent crew browser work. This starts no job and does not change ownership or permissions.'}</p>
          {blockedReason && <p role="status">{blockedReason}</p>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" style={_ACTION_STYLE} onClick={() => setConfirmation(null)}>Cancel</button>
            <button type="button" style={_ACTION_STYLE} disabled={pending || !!blockedReason || (confirmation === 'handoff' && expired)} onClick={() => { void mutateSession(); }}>Confirm {confirmation === 'end' ? 'end session' : 'hand to crew'}</button>
          </div>
        </div>
      </div>}

      {/* URL validation notice (defense-in-depth). BF-694: scoped to embedded
          mode with the input that produces it, so a stale error cannot outlive
          a mode switch. */}
      {mode === 'embedded' && urlError !== null && (
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
