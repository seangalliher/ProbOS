/** AD-1018: MCP Servers — the HXI management surface for runtime-mutable MCP
 *  server registrations (AD-1015 CRUD + AD-1017 auth endpoints).
 *
 *  The operator-facing counterpart to the read-only Ship's Locker MCP list:
 *  add / edit / remove servers, enable/disable them, test the connection, and
 *  configure auth (static token or OAuth authorization-code) — all without an
 *  edit-config-and-restart cycle. Bound to ``/api/mcp/servers`` (gated on
 *  ``config.mcp.management_enabled``, so a GET 404 means "management disabled").
 *  Opened from the Bridge -> Engineering station ("MCP Servers"); closed via the
 *  header X or Escape.
 *
 *  Secrets discipline (HARD): no token/secret value is ever rendered back. The
 *  token / client_secret inputs are write-only — cleared after save, the panel
 *  shows only an ``auth_kind`` badge + the non-secret config thereafter. The
 *  backend ``to_public_dict`` never emits a secret; this surface never echoes one.
 *
 *  HXI: inline SVG stroke icons (strokeWidth 1.5), amber active / dim inactive,
 *  NO emoji, a ``data-testid`` on every interactive element. Mirrors the
 *  ShipsLockerPanel overlay (store-flag gated, deps-injectable, honest-degrade).
 */
import { useEffect, useState, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { McpAgentAccess } from './McpAgentAccess';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';
const _RED = '#d05050';

// --------------------------------------------------------------------------- //
// Types — the AD-1015 ``to_public_dict`` shape (never carries a secret value).
// --------------------------------------------------------------------------- //
export interface McpServer {
  id: string;
  name: string;
  type: string; // 'http' | 'stdio'
  url: string;
  headers: Record<string, string>;
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  timeout_seconds: number | null;
  enabled: boolean;
  auth_kind: string; // 'none' | 'static' | 'oauth'
  credential_ref: string;
  auth_header_name: string;
  auth_scheme: string;
  auth_env_var: string;
  oauth_json: string;
  created_at: number;
  updated_at: number;
}

/** The non-secret create/edit payload — no auth fields (those go via the modal). */
export interface McpServerInput {
  name: string;
  type: string;
  url: string;
  headers: Record<string, string>;
  command: string;
  args: string[];
  env: Record<string, string>;
  cwd: string;
  timeout_seconds: number | null;
}

export interface CredentialInput {
  value: string;
  header_name: string;
  scheme: string;
  env_var: string;
}

export interface OAuthStartInput {
  client_id: string;
  client_secret: string;
  authorize_url: string;
  token_url: string;
  scopes: string[];
  redirect_uri: string;
}

export interface TestResult { ok: boolean; tool_count?: number; error?: string; }
export interface OAuthStartResult { auth_url: string; state: string; }
export interface McpServersResult { servers: McpServer[]; disabled: boolean; }

export interface McpDeps {
  fetchServers: () => Promise<McpServersResult>;
  createServer: (input: McpServerInput) => Promise<McpServer>;
  updateServer: (id: string, input: Partial<McpServerInput>) => Promise<McpServer>;
  deleteServer: (id: string) => Promise<boolean>;
  setEnabled: (id: string, enabled: boolean) => Promise<McpServer>;
  testServer: (id: string) => Promise<TestResult>;
  putCredential: (id: string, body: CredentialInput) => Promise<McpServer>;
  deleteCredential: (id: string) => Promise<McpServer>;
  startOAuth: (id: string, body: OAuthStartInput) => Promise<OAuthStartResult>;
  refreshOAuth: (id: string) => Promise<boolean>;
}

// --------------------------------------------------------------------------- //
// Real API calls — each ``deps`` entry defaults to one of these.
// --------------------------------------------------------------------------- //
async function _errText(resp: Response): Promise<string> {
  try {
    const d = await resp.json();
    const detail = d?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail.message === 'string') return detail.message;
    return `request failed: ${resp.status}`;
  } catch {
    return `request failed: ${resp.status}`;
  }
}

export async function fetchServersApi(): Promise<McpServersResult> {
  const resp = await fetch('/api/mcp/servers');
  if (resp.status === 404) return { servers: [], disabled: true };
  if (!resp.ok) throw new Error(`mcp servers fetch failed: ${resp.status}`);
  const d = await resp.json();
  return { servers: Array.isArray(d?.servers) ? d.servers : [], disabled: false };
}

async function createServerApi(input: McpServerInput): Promise<McpServer> {
  const resp = await fetch('/api/mcp/servers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function updateServerApi(id: string, input: Partial<McpServerInput>): Promise<McpServer> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function deleteServerApi(id: string): Promise<boolean> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' });
  return resp.ok;
}

async function setEnabledApi(id: string, enabled: boolean): Promise<McpServer> {
  const path = enabled ? 'enable' : 'disable';
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/${path}`, { method: 'POST' });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function testServerApi(id: string): Promise<TestResult> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/test`, { method: 'POST' });
  if (!resp.ok) return { ok: false, error: await _errText(resp) };
  return resp.json();
}

async function putCredentialApi(id: string, body: CredentialInput): Promise<McpServer> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/credential`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function deleteCredentialApi(id: string): Promise<McpServer> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/credential`, { method: 'DELETE' });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function startOAuthApi(id: string, body: OAuthStartInput): Promise<OAuthStartResult> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/auth/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await _errText(resp));
  return resp.json();
}

async function refreshOAuthApi(id: string): Promise<boolean> {
  const resp = await fetch(`/api/mcp/servers/${encodeURIComponent(id)}/auth/refresh`, { method: 'POST' });
  return resp.ok;
}

// --------------------------------------------------------------------------- //
// Inline SVG stroke icons (HXI #3: no emoji, stroke-only glyphs).
// --------------------------------------------------------------------------- //
const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconClose({ color = _DIM }: { color?: string }) {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M6 6 L18 18 M18 6 L6 18" /></svg>);
}
function IconPlus({ color = _AMBER }: { color?: string }) {
  return (<svg {..._svgBase(color)} aria-hidden="true"><path d="M12 5 L12 19 M5 12 L19 12" /></svg>);
}
function IconServers({ color = _AMBER }: { color?: string }) {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="3" y="4" width="18" height="6" rx="1" />
      <rect x="3" y="14" width="18" height="6" rx="1" />
      <path d="M7 7 L7 7 M7 17 L7 17" />
    </svg>
  );
}

// --------------------------------------------------------------------------- //
// Shared styles.
// --------------------------------------------------------------------------- //
const fieldStyle: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  color: _TEXT,
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(240,176,96,0.2)',
  borderRadius: 4,
  padding: '5px 8px',
  width: '100%',
  boxSizing: 'border-box',
};

const labelStyle: React.CSSProperties = {
  fontSize: 9, letterSpacing: 1, color: '#8888a0', textTransform: 'uppercase',
  display: 'block', marginBottom: 3,
};

function btnStyle(active = true): React.CSSProperties {
  const c = active ? _AMBER : _DIM;
  return {
    fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: 0.5,
    color: c, background: 'transparent', border: `1px solid ${c}`, borderRadius: 3,
    padding: '3px 8px', cursor: 'pointer',
  };
}

function badgeStyle(color: string): React.CSSProperties {
  return {
    fontSize: 9, fontFamily: "'JetBrains Mono', monospace", color,
    border: `1px solid ${color}55`, borderRadius: 3, padding: '1px 6px',
  };
}

const _NAME_RE = /^[a-z0-9][a-z0-9-]*$/;

// KV row helpers (headers / env are key/value maps in the form).
interface KvRow { k: string; v: string; }
function rowsToRecord(rows: KvRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) { if (r.k.trim()) out[r.k.trim()] = r.v; }
  return out;
}
function recordToRows(rec: Record<string, string>): KvRow[] {
  return Object.entries(rec || {}).map(([k, v]) => ({ k, v }));
}

interface Props { deps?: Partial<McpDeps>; }

type FormMode = 'list' | 'create' | 'edit';

export function McpServersPanel({ deps }: Props) {
  const open = useStore((s) => s.mcpServersOpen);
  const _fetchServers = deps?.fetchServers ?? fetchServersApi;
  const _createServer = deps?.createServer ?? createServerApi;
  const _updateServer = deps?.updateServer ?? updateServerApi;
  const _deleteServer = deps?.deleteServer ?? deleteServerApi;
  const _setEnabled = deps?.setEnabled ?? setEnabledApi;
  const _testServer = deps?.testServer ?? testServerApi;
  const _putCredential = deps?.putCredential ?? putCredentialApi;
  const _deleteCredential = deps?.deleteCredential ?? deleteCredentialApi;
  const _startOAuth = deps?.startOAuth ?? startOAuthApi;
  const _refreshOAuth = deps?.refreshOAuth ?? refreshOAuthApi;

  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [error, setError] = useState(false);
  const [mode, setMode] = useState<FormMode>('list');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [confirmDeleteFor, setConfirmDeleteFor] = useState<string | null>(null);
  const [credFor, setCredFor] = useState<McpServer | null>(null);

  // Create/edit form state.
  const [fName, setFName] = useState('');
  const [fType, setFType] = useState('http');
  const [fUrl, setFUrl] = useState('');
  const [fHeaders, setFHeaders] = useState<KvRow[]>([]);
  const [fCommand, setFCommand] = useState('');
  const [fArgs, setFArgs] = useState('');
  const [fEnv, setFEnv] = useState<KvRow[]>([]);
  const [fCwd, setFCwd] = useState('');
  const [fTimeout, setFTimeout] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const close = useCallback(() => useStore.setState({ mcpServersOpen: false }), []);

  const reload = useCallback(async () => {
    try {
      const r = await _fetchServers();
      setServers(r.servers);
      setDisabled(r.disabled);
      setError(false);
    } catch {
      setError(true);
    }
  }, [_fetchServers]);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setServers(null);
    setError(false);
    setDisabled(false);
    setMode('list');
    setEditingId(null);
    setCredFor(null);
    setConfirmDeleteFor(null);
    _fetchServers()
      .then((r) => { if (alive) { setServers(r.servers); setDisabled(r.disabled); } })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [open, _fetchServers]);

  // Escape-to-close (mirrors ShipsLockerPanel). A credential modal swallows
  // Escape first (closes itself), then the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (credFor) { setCredFor(null); return; }
      if (mode !== 'list') { setMode('list'); setEditingId(null); return; }
      close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, close, credFor, mode]);

  // AD-1017 OAuth popup completion: the callback posts {type:'oauth_complete'};
  // refresh the list + close the credential modal when it arrives.
  useEffect(() => {
    if (!open) return;
    const onMessage = (e: MessageEvent) => {
      if (e?.data?.type === 'oauth_complete') {
        void reload();
        setCredFor(null);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [open, reload]);

  const resetForm = useCallback(() => {
    setFName(''); setFType('http'); setFUrl(''); setFHeaders([]);
    setFCommand(''); setFArgs(''); setFEnv([]); setFCwd(''); setFTimeout('');
    setFormError(null);
  }, []);

  const openCreate = useCallback(() => {
    resetForm();
    setEditingId(null);
    setMode('create');
  }, [resetForm]);

  const openEdit = useCallback((s: McpServer) => {
    setFName(s.name);
    setFType(s.type);
    setFUrl(s.url);
    setFHeaders(recordToRows(s.headers));
    setFCommand(s.command);
    setFArgs((s.args || []).join('\n'));
    setFEnv(recordToRows(s.env));
    setFCwd(s.cwd);
    setFTimeout(s.timeout_seconds === null || s.timeout_seconds === undefined ? '' : String(s.timeout_seconds));
    setFormError(null);
    setEditingId(s.id);
    setMode('edit');
  }, []);

  const submitForm = useCallback(async () => {
    setFormError(null);
    // Client validation mirrors the backend ``validate_record``.
    if (!_NAME_RE.test(fName)) {
      setFormError('Name must be kebab-case (lowercase letters, digits, hyphens).');
      return;
    }
    if (fType === 'http' && !fUrl.trim()) {
      setFormError('An http server requires a URL.');
      return;
    }
    if (fType === 'stdio' && !fCommand.trim()) {
      setFormError('A stdio server requires a command.');
      return;
    }
    const timeoutVal = fTimeout.trim() === '' ? null : Number(fTimeout);
    if (timeoutVal !== null && (!Number.isFinite(timeoutVal) || timeoutVal <= 0)) {
      setFormError('Timeout must be a positive number of seconds.');
      return;
    }
    const input: McpServerInput = {
      name: fName.trim(),
      type: fType,
      url: fType === 'http' ? fUrl.trim() : '',
      headers: fType === 'http' ? rowsToRecord(fHeaders) : {},
      command: fType === 'stdio' ? fCommand.trim() : '',
      args: fType === 'stdio' ? fArgs.split('\n').map((s) => s.trim()).filter(Boolean) : [],
      env: fType === 'stdio' ? rowsToRecord(fEnv) : {},
      cwd: fType === 'stdio' ? fCwd.trim() : '',
      timeout_seconds: timeoutVal,
    };
    try {
      if (mode === 'edit' && editingId) {
        await _updateServer(editingId, input);
      } else {
        await _createServer(input);
      }
      await reload();
      setMode('list');
      setEditingId(null);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Save failed.');
    }
  }, [fName, fType, fUrl, fHeaders, fCommand, fArgs, fEnv, fCwd, fTimeout, mode, editingId, _createServer, _updateServer, reload]);

  const onToggle = useCallback(async (s: McpServer) => {
    try {
      await _setEnabled(s.id, !s.enabled);
      await reload();
    } catch { /* honest-degrade: leave list as-is */ }
  }, [_setEnabled, reload]);

  const onTest = useCallback(async (s: McpServer) => {
    setTestResults((prev) => ({ ...prev, [s.id]: { ok: false, error: 'testing…' } }));
    try {
      const res = await _testServer(s.id);
      setTestResults((prev) => ({ ...prev, [s.id]: res }));
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [s.id]: { ok: false, error: e instanceof Error ? e.message : 'failed' } }));
    }
  }, [_testServer]);

  const onDelete = useCallback(async (id: string) => {
    try {
      await _deleteServer(id);
      await reload();
    } catch { /* honest-degrade */ } finally {
      setConfirmDeleteFor(null);
    }
  }, [_deleteServer, reload]);

  if (!open) return null;

  return (
    <div
      data-testid="mcp-servers-panel"
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
          <IconServers />
          <div>
            <div style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>MCP SERVERS</div>
            <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
              Manage MCP server registrations — add, edit, test, and configure auth.
            </div>
          </div>
        </div>
        <button
          data-testid="mcp-close"
          onClick={close}
          aria-label="Close MCP Servers"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconClose />
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 18px 24px', fontSize: 12 }}>
        {error && (
          <div data-testid="mcp-error" style={{ color: _DIM, padding: '16px 0' }}>
            MCP servers unavailable.
          </div>
        )}
        {!error && disabled && (
          <div data-testid="mcp-disabled" style={{ color: _DIM, padding: '16px 0' }}>
            MCP management is disabled. Enable <code style={{ color: '#7a8aa0' }}>mcp.management_enabled</code> to manage servers.
          </div>
        )}
        {!error && !disabled && servers === null && (
          <div data-testid="mcp-loading" style={{ color: _DIM, padding: '16px 0' }}>Loading servers…</div>
        )}

        {!error && !disabled && servers !== null && mode === 'list' && (
          <>
            <button data-testid="mcp-add" onClick={openCreate} style={{ ...btnStyle(true), display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
              <IconPlus />Add server
            </button>
            {servers.length === 0 ? (
              <div data-testid="mcp-empty" style={{ color: '#555568', fontSize: 11 }}>No MCP servers configured.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {servers.map((s) => (
                  <ServerRow
                    key={s.id}
                    server={s}
                    test={testResults[s.id]}
                    confirmDelete={confirmDeleteFor === s.id}
                    onToggle={() => onToggle(s)}
                    onTest={() => onTest(s)}
                    onEdit={() => openEdit(s)}
                    onAuth={() => setCredFor(s)}
                    onAskDelete={() => setConfirmDeleteFor(s.id)}
                    onCancelDelete={() => setConfirmDeleteFor(null)}
                    onConfirmDelete={() => onDelete(s.id)}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {!error && !disabled && servers !== null && (mode === 'create' || mode === 'edit') && (
          <ServerForm
            mode={mode}
            name={fName} setName={setFName}
            type={fType} setType={setFType}
            url={fUrl} setUrl={setFUrl}
            headers={fHeaders} setHeaders={setFHeaders}
            command={fCommand} setCommand={setFCommand}
            args={fArgs} setArgs={setFArgs}
            env={fEnv} setEnv={setFEnv}
            cwd={fCwd} setCwd={setFCwd}
            timeout={fTimeout} setTimeout={setFTimeout}
            formError={formError}
            onSubmit={submitForm}
            onCancel={() => { setMode('list'); setEditingId(null); }}
          />
        )}
      </div>

      {credFor && (
        <CredentialModal
          server={credFor}
          onClose={() => setCredFor(null)}
          putCredential={_putCredential}
          deleteCredential={_deleteCredential}
          startOAuth={_startOAuth}
          refreshOAuth={_refreshOAuth}
          onChanged={reload}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Server row.
// --------------------------------------------------------------------------- //
function authBadgeColor(kind: string): string {
  if (kind === 'oauth') return '#8a70d0';
  if (kind === 'static') return _AMBER;
  return _DIM;
}

interface RowProps {
  server: McpServer;
  test?: TestResult;
  confirmDelete: boolean;
  onToggle: () => void;
  onTest: () => void;
  onEdit: () => void;
  onAuth: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

function ServerRow(p: RowProps) {
  const s = p.server;
  const [showAccess, setShowAccess] = useState(false);
  const summary = s.type === 'http'
    ? s.url
    : [s.command, ...(s.args || [])].filter(Boolean).join(' ');
  let testText: string | null = null;
  let testColor = _DIM;
  if (p.test) {
    if (p.test.error === 'testing…') { testText = 'testing…'; testColor = _DIM; }
    else if (p.test.ok) { testText = `OK · ${p.test.tool_count ?? 0} tools`; testColor = '#60c080'; }
    else { testText = `FAILED${p.test.error ? ` — ${p.test.error}` : ''}`; testColor = _RED; }
  }
  return (
    <div
      data-testid={`mcp-row-${s.id}`}
      style={{ border: '1px solid rgba(255,255,255,0.08)', borderLeft: `3px solid ${s.enabled ? _AMBER : _DIM}`, borderRadius: 5, padding: '8px 12px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ color: '#c8d0e0', fontSize: 12, minWidth: 120 }}>{s.name}</span>
        <span data-testid={`mcp-type-${s.id}`} style={badgeStyle(s.type === 'stdio' ? '#d0a030' : '#50a0d0')}>{s.type}</span>
        <span data-testid={`mcp-auth-kind-${s.id}`} style={badgeStyle(authBadgeColor(s.auth_kind))}>auth: {s.auth_kind}</span>
        <span style={{ color: _DIM, fontSize: 10, fontFamily: 'monospace', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</span>
      </div>

      {s.type === 'stdio' && (
        <div data-testid={`mcp-trust-${s.id}`} style={{ color: '#c08040', fontSize: 10, margin: '6px 0 2px' }}>
          Runs a local command on this machine.
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <button data-testid={`mcp-toggle-${s.id}`} onClick={p.onToggle} style={btnStyle(s.enabled)}>
          {s.enabled ? 'Enabled' : 'Disabled'}
        </button>
        <button data-testid={`mcp-test-${s.id}`} onClick={p.onTest} style={btnStyle(true)}>Test</button>
        {testText && (
          <span data-testid={`mcp-test-result-${s.id}`} style={{ color: testColor, fontSize: 10 }}>{testText}</span>
        )}
        <button data-testid={`mcp-auth-${s.id}`} onClick={p.onAuth} style={btnStyle(true)}>Auth</button>
        <button data-testid={`mcp-edit-${s.id}`} onClick={p.onEdit} style={btnStyle(true)}>Edit</button>
        {p.confirmDelete ? (
          <>
            <button data-testid={`mcp-delete-confirm-${s.id}`} onClick={p.onConfirmDelete} style={btnStyle(false)}>Confirm delete</button>
            <button data-testid={`mcp-delete-cancel-${s.id}`} onClick={p.onCancelDelete} style={btnStyle(true)}>Cancel</button>
          </>
        ) : (
          <button data-testid={`mcp-delete-${s.id}`} onClick={p.onAskDelete} style={{ ...btnStyle(false), color: _RED, borderColor: _RED }}>Delete</button>
        )}
      </div>

      <div style={{ marginTop: 8 }}>
        <button
          data-testid={`mcp-access-section-${s.id}`}
          onClick={() => setShowAccess((v) => !v)}
          style={btnStyle(showAccess)}
        >
          {showAccess ? 'Hide agent access' : 'Agent access'}
        </button>
      </div>
      {showAccess && <McpAgentAccess serverId={s.id} serverName={s.name} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Create/Edit form.
// --------------------------------------------------------------------------- //
interface FormProps {
  mode: FormMode;
  name: string; setName: (v: string) => void;
  type: string; setType: (v: string) => void;
  url: string; setUrl: (v: string) => void;
  headers: KvRow[]; setHeaders: (v: KvRow[]) => void;
  command: string; setCommand: (v: string) => void;
  args: string; setArgs: (v: string) => void;
  env: KvRow[]; setEnv: (v: KvRow[]) => void;
  cwd: string; setCwd: (v: string) => void;
  timeout: string; setTimeout: (v: string) => void;
  formError: string | null;
  onSubmit: () => void;
  onCancel: () => void;
}

function KvEditor({ testid, rows, setRows }: { testid: string; rows: KvRow[]; setRows: (v: KvRow[]) => void }) {
  return (
    <div data-testid={`mcp-kv-${testid}`}>
      {rows.map((row, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
          <input
            data-testid={`mcp-kv-${testid}-key-${i}`}
            value={row.k}
            placeholder="key"
            onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, k: e.target.value } : r)))}
            style={{ ...fieldStyle, flex: 1 }}
          />
          <input
            data-testid={`mcp-kv-${testid}-val-${i}`}
            value={row.v}
            placeholder="value"
            onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, v: e.target.value } : r)))}
            style={{ ...fieldStyle, flex: 1 }}
          />
          <button
            data-testid={`mcp-kv-${testid}-del-${i}`}
            onClick={() => setRows(rows.filter((_, j) => j !== i))}
            style={btnStyle(false)}
            aria-label="Remove row"
          >
            <IconClose />
          </button>
        </div>
      ))}
      <button data-testid={`mcp-kv-${testid}-add`} onClick={() => setRows([...rows, { k: '', v: '' }])} style={btnStyle(true)}>
        + Add row
      </button>
    </div>
  );
}

function ServerForm(p: FormProps) {
  return (
    <div data-testid="mcp-form" style={{ maxWidth: 560 }}>
      <div style={{ fontSize: 12, color: _AMBER, letterSpacing: 0.5, marginBottom: 12 }}>
        {p.mode === 'edit' ? 'Edit server' : 'New MCP server'}
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>Name (kebab-case)</label>
        <input data-testid="mcp-form-name" value={p.name} onChange={(e) => p.setName(e.target.value)} style={fieldStyle} placeholder="my-server" />
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={labelStyle}>Type</label>
        <select data-testid="mcp-form-type" value={p.type} onChange={(e) => p.setType(e.target.value)} style={fieldStyle}>
          <option value="http">http</option>
          <option value="stdio">stdio</option>
        </select>
      </div>

      {p.type === 'http' ? (
        <>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>URL</label>
            <input data-testid="mcp-form-url" value={p.url} onChange={(e) => p.setUrl(e.target.value)} style={fieldStyle} placeholder="https://host/mcp" />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Headers (non-secret only — use Auth for tokens)</label>
            <KvEditor testid="headers" rows={p.headers} setRows={p.setHeaders} />
          </div>
        </>
      ) : (
        <>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Command</label>
            <input data-testid="mcp-form-command" value={p.command} onChange={(e) => p.setCommand(e.target.value)} style={fieldStyle} placeholder="uvx" />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Args (one per line)</label>
            <textarea data-testid="mcp-form-args" value={p.args} onChange={(e) => p.setArgs(e.target.value)} style={{ ...fieldStyle, minHeight: 56, resize: 'vertical' }} placeholder={'mcp-server-foo\n--flag'} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Env (non-secret only — use Auth for tokens)</label>
            <KvEditor testid="env" rows={p.env} setRows={p.setEnv} />
          </div>
          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>Working directory</label>
            <input data-testid="mcp-form-cwd" value={p.cwd} onChange={(e) => p.setCwd(e.target.value)} style={fieldStyle} placeholder="/path/to/dir" />
          </div>
          <div data-testid="mcp-form-trust" style={{ color: '#c08040', fontSize: 10, marginBottom: 10 }}>
            Runs a local command on this machine.
          </div>
        </>
      )}

      <div style={{ marginBottom: 12 }}>
        <label style={labelStyle}>Timeout (seconds, optional)</label>
        <input data-testid="mcp-form-timeout" value={p.timeout} onChange={(e) => p.setTimeout(e.target.value)} style={{ ...fieldStyle, width: 120 }} placeholder="30" />
      </div>

      {p.formError && (
        <div data-testid="mcp-form-error" style={{ color: _RED, fontSize: 11, marginBottom: 10 }}>{p.formError}</div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button data-testid="mcp-form-submit" onClick={p.onSubmit} style={btnStyle(true)}>
          {p.mode === 'edit' ? 'Save changes' : 'Create server'}
        </button>
        <button data-testid="mcp-form-cancel" onClick={p.onCancel} style={btnStyle(false)}>Cancel</button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Credential modal (static token / OAuth). No secret value is ever rendered back.
// --------------------------------------------------------------------------- //
interface CredModalProps {
  server: McpServer;
  onClose: () => void;
  putCredential: (id: string, body: CredentialInput) => Promise<McpServer>;
  deleteCredential: (id: string) => Promise<McpServer>;
  startOAuth: (id: string, body: OAuthStartInput) => Promise<OAuthStartResult>;
  refreshOAuth: (id: string) => Promise<boolean>;
  onChanged: () => Promise<void> | void;
}

function CredentialModal(p: CredModalProps) {
  const s = p.server;
  const [kind, setKind] = useState<'static' | 'oauth'>(s.auth_kind === 'oauth' ? 'oauth' : 'static');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [modalError, setModalError] = useState<string | null>(null);

  // Static (write-only token).
  const [token, setToken] = useState('');
  const [headerName, setHeaderName] = useState(s.auth_header_name || 'Authorization');
  const [scheme, setScheme] = useState(s.auth_scheme || 'Bearer');
  const [envVar, setEnvVar] = useState(s.auth_env_var || '');

  // OAuth (client_secret write-only). Non-secret config seeded from oauth_json.
  const oauthCfg = (() => {
    try { const d = JSON.parse(s.oauth_json || '{}'); return d && typeof d === 'object' ? d : {}; } catch { return {}; }
  })();
  const [clientId, setClientId] = useState(String(oauthCfg.client_id || ''));
  const [authorizeUrl, setAuthorizeUrl] = useState(String(oauthCfg.authorize_url || ''));
  const [tokenUrl, setTokenUrl] = useState(String(oauthCfg.token_url || ''));
  const [scopes, setScopes] = useState<string>(Array.isArray(oauthCfg.scopes) ? oauthCfg.scopes.join(' ') : '');
  const [redirectUri, setRedirectUri] = useState(String(oauthCfg.redirect_uri || ''));
  const [clientSecret, setClientSecret] = useState('');

  const saveStatic = useCallback(async () => {
    setModalError(null);
    setBusy(true);
    try {
      await p.putCredential(s.id, { value: token, header_name: headerName, scheme, env_var: envVar });
      setToken(''); // write-only: never keep / echo the secret
      await p.onChanged();
      p.onClose();
    } catch (e) {
      setModalError(e instanceof Error ? e.message : 'Save failed.');
    } finally {
      setBusy(false);
    }
  }, [p, s.id, token, headerName, scheme, envVar]);

  const connectOAuth = useCallback(async () => {
    setModalError(null);
    setBusy(true);
    try {
      const res = await p.startOAuth(s.id, {
        client_id: clientId,
        client_secret: clientSecret,
        authorize_url: authorizeUrl,
        token_url: tokenUrl,
        scopes: scopes.split(/\s+/).map((x) => x.trim()).filter(Boolean),
        redirect_uri: redirectUri,
      });
      setClientSecret(''); // write-only
      if (res?.auth_url) {
        window.open(res.auth_url, '_blank', 'width=600,height=720');
        setNote('Authorize in the opened window; this panel refreshes when complete.');
      }
    } catch (e) {
      setModalError(e instanceof Error ? e.message : 'Connect failed.');
    } finally {
      setBusy(false);
    }
  }, [p, s.id, clientId, clientSecret, authorizeUrl, tokenUrl, scopes, redirectUri]);

  const refresh = useCallback(async () => {
    setModalError(null);
    setBusy(true);
    try {
      const ok = await p.refreshOAuth(s.id);
      setNote(ok ? 'Token refreshed.' : 'Refresh failed.');
      await p.onChanged();
    } catch (e) {
      setModalError(e instanceof Error ? e.message : 'Refresh failed.');
    } finally {
      setBusy(false);
    }
  }, [p, s.id]);

  const removeCred = useCallback(async () => {
    setModalError(null);
    setBusy(true);
    try {
      await p.deleteCredential(s.id);
      await p.onChanged();
      p.onClose();
    } catch (e) {
      setModalError(e instanceof Error ? e.message : 'Remove failed.');
    } finally {
      setBusy(false);
    }
  }, [p, s.id]);

  return (
    <div
      data-testid="mcp-cred-modal"
      style={{ position: 'fixed', inset: 0, zIndex: 40, background: 'rgba(4,4,8,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <div style={{ width: 460, maxHeight: '86vh', overflowY: 'auto', background: '#0c0c14', border: `1px solid ${_AMBER}40`, borderRadius: 8, padding: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: _AMBER, letterSpacing: 0.5 }}>Auth — {s.name}</div>
          <button data-testid="mcp-cred-close" onClick={p.onClose} aria-label="Close" style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 26, height: 26, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <IconClose />
          </button>
        </div>

        <div data-testid="mcp-cred-status" style={{ fontSize: 11, color: s.auth_kind === 'none' ? _DIM : '#60c080', marginBottom: 12 }}>
          {s.auth_kind === 'none' ? 'No credential configured.' : `Credential configured (${s.auth_kind}).`}
        </div>

        <div style={{ display: 'flex', gap: 14, marginBottom: 12 }}>
          <label data-testid="mcp-cred-kind-static" style={{ fontSize: 11, color: kind === 'static' ? _AMBER : _DIM, cursor: 'pointer' }}>
            <input type="radio" name="cred-kind" checked={kind === 'static'} onChange={() => setKind('static')} style={{ marginRight: 6 }} />
            Static token
          </label>
          <label data-testid="mcp-cred-kind-oauth" style={{ fontSize: 11, color: kind === 'oauth' ? _AMBER : _DIM, cursor: 'pointer' }}>
            <input type="radio" name="cred-kind" checked={kind === 'oauth'} onChange={() => setKind('oauth')} style={{ marginRight: 6 }} />
            OAuth
          </label>
        </div>

        {kind === 'static' ? (
          <div data-testid="mcp-cred-static">
            <div style={{ marginBottom: 10 }}>
              <label style={labelStyle}>Token (write-only — never shown again)</label>
              <input data-testid="mcp-cred-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} style={fieldStyle} placeholder="paste token" autoComplete="off" />
            </div>
            {s.type === 'http' ? (
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <div style={{ flex: 1 }}>
                  <label style={labelStyle}>Header name</label>
                  <input data-testid="mcp-cred-header-name" value={headerName} onChange={(e) => setHeaderName(e.target.value)} style={fieldStyle} />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={labelStyle}>Scheme</label>
                  <input data-testid="mcp-cred-scheme" value={scheme} onChange={(e) => setScheme(e.target.value)} style={fieldStyle} />
                </div>
              </div>
            ) : (
              <div style={{ marginBottom: 10 }}>
                <label style={labelStyle}>Env var name</label>
                <input data-testid="mcp-cred-env-var" value={envVar} onChange={(e) => setEnvVar(e.target.value)} style={fieldStyle} placeholder="API_KEY" />
              </div>
            )}
            <button data-testid="mcp-cred-save" onClick={saveStatic} disabled={busy} style={btnStyle(true)}>
              {busy ? 'Saving…' : 'Save token'}
            </button>
          </div>
        ) : (
          <div data-testid="mcp-cred-oauth">
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Client ID</label>
              <input data-testid="mcp-oauth-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)} style={fieldStyle} />
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Client secret (write-only)</label>
              <input data-testid="mcp-oauth-client-secret" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} style={fieldStyle} placeholder="paste client secret" autoComplete="off" />
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Authorize URL</label>
              <input data-testid="mcp-oauth-authorize-url" value={authorizeUrl} onChange={(e) => setAuthorizeUrl(e.target.value)} style={fieldStyle} />
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Token URL</label>
              <input data-testid="mcp-oauth-token-url" value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} style={fieldStyle} />
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={labelStyle}>Scopes (space-separated)</label>
              <input data-testid="mcp-oauth-scopes" value={scopes} onChange={(e) => setScopes(e.target.value)} style={fieldStyle} />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Redirect URI</label>
              <input data-testid="mcp-oauth-redirect-uri" value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)} style={fieldStyle} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button data-testid="mcp-oauth-connect" onClick={connectOAuth} disabled={busy} style={btnStyle(true)}>
                {busy ? 'Connecting…' : 'Connect'}
              </button>
              <button data-testid="mcp-oauth-refresh" onClick={refresh} disabled={busy} style={btnStyle(false)}>Refresh token</button>
            </div>
          </div>
        )}

        {s.auth_kind !== 'none' && (
          <button data-testid="mcp-cred-remove" onClick={removeCred} disabled={busy} style={{ ...btnStyle(false), color: _RED, borderColor: _RED, marginTop: 12 }}>
            Remove credential
          </button>
        )}

        {note && <div data-testid="mcp-cred-note" style={{ fontSize: 10, color: _DIM, marginTop: 10 }}>{note}</div>}
        {modalError && <div data-testid="mcp-cred-error" style={{ fontSize: 11, color: _RED, marginTop: 10 }}>{modalError}</div>}
      </div>
    </div>
  );
}

export default McpServersPanel;
