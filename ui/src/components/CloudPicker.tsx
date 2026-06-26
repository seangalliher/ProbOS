/** AD-720c: Cloud file picker modal.
 *
 *  Three-step flow:
 *    1. Provider selector — only providers reported as ``enabled`` by the
 *       /api/cloud-pickers/{provider}/start probe are clickable; others
 *       render with a 503 honest-degrade banner.
 *    2. Authorize button → POST /start → opens the auth URL in a popup
 *       window → listens for ``oauth_complete`` postMessage from the
 *       callback page.
 *    3. File list with search + pagination → file click POSTs /attach →
 *       receives ``{attachment_id, mime, size_bytes, filename}`` (SHA ref
 *       only; AD-731 invariant — bytes never cross the browser boundary)
 *       and invokes ``onAttached``.
 *
 *  HXI Design Principle #3: inline stroke SVG icons, no emoji.
 */
import { useCallback, useEffect, useState, type ReactElement } from 'react';

export type CloudProviderId = 'google_drive' | 'onedrive' | 'dropbox';

export interface CloudProviderFile {
  id: string;
  name: string;
  mime: string;
  size_bytes: number;
  modified_at: string;
}

export interface AttachedFile {
  attachment_id: string;
  mime: string;
  size_bytes: number;
  filename?: string;
}

export interface CloudPickerProps {
  open: boolean;
  onClose: () => void;
  onAttached: (file: AttachedFile) => void;
  // Operator-enabled provider whitelist (from /api/system/status or config).
  enabledProviders?: CloudProviderId[];
}

const ALL_PROVIDERS: { id: CloudProviderId; label: string }[] = [
  { id: 'google_drive', label: 'Google Drive' },
  { id: 'onedrive', label: 'OneDrive' },
  { id: 'dropbox', label: 'Dropbox' },
];

type ErrorState = { kind: 'banner'; message: string } | null;

export function CloudPicker({
  open,
  onClose,
  onAttached,
  enabledProviders = ['google_drive'],
}: CloudPickerProps): ReactElement | null {
  const [provider, setProvider] = useState<CloudProviderId | null>(null);
  const [authorized, setAuthorized] = useState(false);
  const [files, setFiles] = useState<CloudProviderFile[]>([]);
  const [query, setQuery] = useState('');
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [error, setError] = useState<ErrorState>(null);

  // Reset transient state when the modal closes.
  useEffect(() => {
    if (!open) {
      setProvider(null);
      setAuthorized(false);
      setFiles([]);
      setQuery('');
      setNextPageToken(null);
      setError(null);
    }
  }, [open]);

  const startAuthorize = useCallback(async () => {
    if (!provider) return;
    setError(null);
    let res: Response;
    try {
      res = await fetch(`/api/cloud-pickers/${provider}/start`, {
        method: 'POST',
      });
    } catch (e) {
      setError({ kind: 'banner', message: 'Network error contacting ProbOS.' });
      return;
    }
    if (res.status === 503) {
      const body = await safeJson(res);
      setError({
        kind: 'banner',
        message: `Cloud picker unavailable: ${body?.detail ?? 'feature_disabled'}`,
      });
      return;
    }
    if (!res.ok) {
      setError({ kind: 'banner', message: `Authorization start failed (${res.status}).` });
      return;
    }
    const body = await res.json();
    // Listen for the callback page's postMessage before opening the popup
    // so we don't miss the event if the popup completes before the listener
    // is attached (rare with manual login, but tight loops can race).
    const onMessage = (ev: MessageEvent) => {
      // BF-640 (security hygiene): defense-in-depth — only trust a SAME-ORIGIN
      // oauth_complete message. The callback page is served from our own origin,
      // so any cross-origin postMessage is forged and must be ignored (otherwise
      // any script/iframe could drive setAuthorized(true) + loadFiles('')).
      if (ev.origin !== window.location.origin) return;
      if (
        ev?.data &&
        typeof ev.data === 'object' &&
        ev.data.type === 'oauth_complete' &&
        ev.data.provider === provider
      ) {
        window.removeEventListener('message', onMessage);
        setAuthorized(true);
        void loadFiles('');
      }
    };
    window.addEventListener('message', onMessage);
    window.open(body.auth_url, 'cloud_picker_oauth', 'width=520,height=640');
  }, [provider]);

  const loadFiles = useCallback(
    async (q: string, pageToken: string | null = null) => {
      if (!provider) return;
      setError(null);
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (pageToken) params.set('page_token', pageToken);
      const url = `/api/cloud-pickers/${provider}/files${
        params.toString() ? `?${params.toString()}` : ''
      }`;
      let res: Response;
      try {
        res = await fetch(url);
      } catch {
        setError({ kind: 'banner', message: 'Network error contacting ProbOS.' });
        return;
      }
      if (res.status === 401) {
        setAuthorized(false);
        setFiles([]);
        setError({
          kind: 'banner',
          message: 'Session expired — please reauthorize.',
        });
        return;
      }
      if (!res.ok) {
        setError({ kind: 'banner', message: `File listing failed (${res.status}).` });
        return;
      }
      const body = await res.json();
      const incoming = (body.files ?? []) as CloudProviderFile[];
      setFiles(pageToken ? [...files, ...incoming] : incoming);
      setNextPageToken(body.next_page_token ?? null);
    },
    [provider, files],
  );

  const attachFile = useCallback(
    async (file: CloudProviderFile) => {
      if (!provider) return;
      setError(null);
      let res: Response;
      try {
        res = await fetch(`/api/cloud-pickers/${provider}/attach`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ file_id: file.id }),
        });
      } catch {
        setError({ kind: 'banner', message: 'Network error contacting ProbOS.' });
        return;
      }
      if (res.status === 401) {
        setAuthorized(false);
        setError({
          kind: 'banner',
          message: 'Session expired — please reauthorize.',
        });
        return;
      }
      if (!res.ok) {
        setError({ kind: 'banner', message: `Attach failed (${res.status}).` });
        return;
      }
      const body = (await res.json()) as AttachedFile;
      onAttached(body);
      onClose();
    },
    [provider, onAttached, onClose],
  );

  if (!open) return null;

  return (
    <div
      data-testid="cloud-picker-modal"
      role="dialog"
      aria-label="Attach from cloud storage"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: 480,
          maxHeight: '80vh',
          background: 'rgba(10, 10, 18, 0.96)',
          border: '1px solid rgba(240, 176, 96, 0.3)',
          borderRadius: 6,
          padding: 16,
          color: '#e0dcd4',
          fontFamily: "'Inter', sans-serif",
          fontSize: 13,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: '#f0b060', fontWeight: 600 }}>Attach from cloud</span>
          <button
            type="button"
            aria-label="Close"
            data-testid="cloud-picker-close"
            onClick={onClose}
            style={{
              border: 'none',
              background: 'transparent',
              color: '#8888a0',
              cursor: 'pointer',
              fontSize: 16,
            }}
          >
            ×
          </button>
        </div>

        {error && (
          <div
            data-testid="cloud-picker-error"
            role="alert"
            style={{
              padding: '6px 8px',
              background: 'rgba(240, 96, 96, 0.12)',
              border: '1px solid rgba(240, 96, 96, 0.35)',
              borderRadius: 4,
              color: '#f0b0b0',
            }}
          >
            {error.message}
          </div>
        )}

        {!authorized && (
          <div data-testid="cloud-picker-provider-list" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {ALL_PROVIDERS.filter((p) => enabledProviders.includes(p.id)).map((p) => (
              <button
                key={p.id}
                type="button"
                data-testid={`cloud-picker-provider-${p.id}`}
                onClick={() => setProvider(p.id)}
                aria-pressed={provider === p.id}
                style={{
                  padding: '8px 10px',
                  background: provider === p.id ? 'rgba(240, 176, 96, 0.12)' : 'transparent',
                  border: '1px solid rgba(240, 176, 96, 0.25)',
                  borderRadius: 4,
                  color: '#e0dcd4',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                {p.label}
              </button>
            ))}
            <button
              type="button"
              data-testid="cloud-picker-authorize"
              disabled={!provider}
              onClick={startAuthorize}
              style={{
                marginTop: 8,
                padding: '8px 10px',
                background: provider ? '#f0b060' : 'rgba(240,176,96,0.2)',
                border: 'none',
                borderRadius: 4,
                color: '#0a0a12',
                fontWeight: 600,
                cursor: provider ? 'pointer' : 'not-allowed',
              }}
            >
              Authorize
            </button>
          </div>
        )}

        {authorized && (
          <>
            <input
              type="text"
              data-testid="cloud-picker-search"
              placeholder="Search files…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void loadFiles(query, null);
              }}
              style={{
                padding: '6px 8px',
                background: 'rgba(0, 0, 0, 0.4)',
                border: '1px solid rgba(240, 176, 96, 0.25)',
                borderRadius: 4,
                color: '#e0dcd4',
                fontSize: 13,
              }}
            />
            <div
              data-testid="cloud-picker-file-list"
              style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}
            >
              {files.length === 0 && (
                <span style={{ color: '#666680', padding: '8px 0' }}>No files.</span>
              )}
              {files.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  data-testid={`cloud-picker-file-${f.id}`}
                  onClick={() => void attachFile(f)}
                  style={{
                    padding: '6px 8px',
                    background: 'transparent',
                    border: '1px solid rgba(240, 176, 96, 0.15)',
                    borderRadius: 4,
                    color: '#e0dcd4',
                    cursor: 'pointer',
                    textAlign: 'left',
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 8,
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {f.name}
                  </span>
                  <span style={{ color: '#666680', flexShrink: 0 }}>
                    {formatSize(f.size_bytes)}
                  </span>
                </button>
              ))}
            </div>
            {nextPageToken && (
              <button
                type="button"
                data-testid="cloud-picker-load-more"
                onClick={() => void loadFiles(query, nextPageToken)}
                style={{
                  padding: '6px 10px',
                  background: 'transparent',
                  border: '1px solid rgba(240, 176, 96, 0.35)',
                  borderRadius: 4,
                  color: '#f0b060',
                  cursor: 'pointer',
                }}
              >
                Load more
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

async function safeJson(res: Response): Promise<Record<string, unknown> | null> {
  try {
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
