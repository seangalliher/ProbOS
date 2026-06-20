/** AD-1021: CodeWorkstation — the OSS native `monaco` workstation type (HXI #11
 *  middle tier). A lightweight code/text editor for VIEWING the Architect ->
 *  Builder loop's proposed file changes (a BuildProposal's file_changes) plus a
 *  general scratch editor. NOT an IDE.
 *
 *  DD-1: the registry/launcher key is `monaco` (the AD-1022 contract) but the v1
 *  ENGINE is a plain editable <textarea> (scratch) + a read-only <pre>
 *  (build/artifact). NO Monaco dependency, NO Vite worker config, NO bundle
 *  growth. The Monaco engine + syntax highlight + DiffEditor are deferred to
 *  AD-1021b; write-through / save-to-artifact are AD-1021b; agent co-editing is
 *  AD-1021c.
 *
 *  Reads the active document from the store (NativeWorkstationProps carries only
 *  `typeId`). Output actions are Copy + Download ONLY (no write-back in v1).
 *  HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5), amber active / dim
 *  inactive, NO emoji, a data-testid on every interactive element.
 */
import { useEffect, useState, lazy, Suspense } from 'react';
import type { NativeWorkstationProps } from './WorkstationLauncher';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent } from '../artifacts/artifactApi';

const MonacoSurface = lazy(() => import('./MonacoSurface'));

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _TEXT = '#c8c8d4';

const _svgBase = (color: string): React.SVGProps<SVGSVGElement> => ({
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: color, strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round',
});

function IconCopy({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="1.5" />
      <path d="M5 15 V5 a1 1 0 0 1 1 -1 h10" />
    </svg>
  );
}

function IconDownload({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M12 4 V14 M8 11 L12 15 L16 11 M5 19 H19" />
    </svg>
  );
}

const _LANG_BY_EXT: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
  py: 'python', md: 'markdown', json: 'json', yaml: 'yaml', yml: 'yaml',
  css: 'css', html: 'html', sh: 'shell', toml: 'toml', txt: 'plaintext',
};

function _languageForPath(path: string | undefined): string {
  const ext = (path ?? '').split('.').pop()?.toLowerCase() ?? '';
  return _LANG_BY_EXT[ext] ?? 'plaintext';
}

function _baseName(path: string | undefined): string {
  if (!path) return '';
  const parts = path.split('/');
  return parts[parts.length - 1] || '';
}

const _badgeStyle = (mode: 'create' | 'modify'): React.CSSProperties => ({
  fontSize: 9,
  letterSpacing: 1,
  padding: '2px 6px',
  borderRadius: 3,
  border: `1px solid ${mode === 'create' ? '#3a6a4a' : '#6a5a2a'}`,
  color: mode === 'create' ? '#6fcf97' : _AMBER,
  background: 'transparent',
});

export function CodeWorkstation({ typeId: _typeId, doc: propDoc }: NativeWorkstationProps): React.ReactElement {
  // AD-1023: a container host may pass a per-workstation doc; standalone callers
  // pass none -> fall back to the global store doc (byte-identical to AD-1021).
  const storeDoc = useStore((s) => s.workstationDoc);
  const doc = propDoc !== undefined ? propDoc : storeDoc;

  // Local editor state — re-seeded whenever the active document changes.
  const [scratch, setScratch] = useState<string>('');
  const [selectedIdx, setSelectedIdx] = useState<number>(0);
  const [artifactText, setArtifactText] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);

  useEffect(() => {
    setScratch(doc && doc.kind === 'scratch' ? (doc.content ?? '') : '');
    setSelectedIdx(0);
    setArtifactText(null);
    setArtifactError(null);
  }, [doc]);

  // Artifact content is fetched lazily (AD-797). Honest-degrade: on failure the
  // body shows a notice, never a blank pane.
  useEffect(() => {
    if (!doc || doc.kind !== 'artifact' || !doc.artifactId) return;
    let cancelled = false;
    const id = doc.artifactId;
    void (async () => {
      try {
        const { text } = await fetchArtifactContent(id);
        if (!cancelled) setArtifactText(text);
      } catch (e) {
        if (!cancelled) setArtifactError(e instanceof Error ? e.message : 'failed to load artifact');
      }
    })();
    return () => { cancelled = true; };
  }, [doc]);

  const changes = doc?.changes ?? [];
  const isMultiFile = doc?.kind === 'build' && changes.length > 1;
  const activeChange = changes.length > 0
    ? changes[Math.min(selectedIdx, changes.length - 1)]
    : null;

  // The content currently shown (and the target of Copy / Download).
  let shownContent = '';
  if (!doc || doc.kind === 'scratch') {
    shownContent = scratch;
  } else if (doc.kind === 'build') {
    shownContent = activeChange ? activeChange.content : (doc.content ?? '');
  } else {
    shownContent = artifactText ?? '';
  }

  const activeMode: 'create' | 'modify' | undefined = activeChange
    ? activeChange.mode
    : doc?.mode;
  const activeAfterLine: string | null | undefined = activeChange
    ? activeChange.after_line
    : doc?.afterLine;
  const activePath = activeChange?.path ?? doc?.path;

  const language = doc?.kind === 'scratch'
    ? (doc.language || 'markdown')
    : _languageForPath(activePath ?? doc?.path);

  const downloadName = _baseName(activePath) || doc?.title || 'workstation.txt';

  // Copy mirrors ArtifactViewer.onCopy (navigator.clipboard.writeText).
  const onCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(shownContent);
    } catch {
      // Clipboard unavailable (e.g. jsdom / insecure context) — honest-degrade.
    }
  };

  // Download mirrors ArtifactViewer.onSave (Blob -> anchor download).
  const onDownload = (): void => {
    const blob = new Blob([shownContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const title = doc?.title || 'Scratch';
  const showEditor = !doc || doc.kind === 'scratch';

  return (
    <div
      data-testid="workstation-code"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, color: _TEXT }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
          borderBottom: '1px solid rgba(255,255,255,0.08)', flexWrap: 'wrap',
        }}
      >
        <span data-testid="workstation-title" style={{ fontSize: 13, color: _AMBER, letterSpacing: 0.5 }}>
          {title}
        </span>
        {doc?.kind === 'build' && activeMode && (
          <span data-testid="workstation-mode-badge" style={_badgeStyle(activeMode)}>
            {activeMode === 'create' ? 'CREATE' : 'MODIFY'}
          </span>
        )}
        {doc?.kind === 'build' && activeMode === 'modify' && activeAfterLine && (
          <span data-testid="workstation-after-line" style={{ fontSize: 10, color: _DIM }}>
            after: {activeAfterLine}
          </span>
        )}
        {showEditor && (
          <span data-testid="workstation-language" style={{ fontSize: 10, color: _DIM, letterSpacing: 1 }}>
            {language.toUpperCase()}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <button
          data-testid="workstation-copy"
          onClick={() => { void onCopy(); }}
          aria-label="Copy contents"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
            border: '1px solid #33334a', borderRadius: 4, background: 'transparent',
            color: _DIM, cursor: 'pointer', fontSize: 11,
          }}
        >
          <IconCopy />Copy
        </button>
        <button
          data-testid="workstation-download"
          onClick={onDownload}
          aria-label="Download contents"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
            border: '1px solid #33334a', borderRadius: 4, background: 'transparent',
            color: _DIM, cursor: 'pointer', fontSize: 11,
          }}
        >
          <IconDownload />Download
        </button>
      </div>

      {/* Body: optional left rail (multi-file build) + editor / viewer */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {isMultiFile && (
          <div
            data-testid="workstation-rail"
            style={{
              width: 200, flexShrink: 0, borderRight: '1px solid rgba(255,255,255,0.08)',
              overflowY: 'auto', padding: 6, display: 'flex', flexDirection: 'column', gap: 4,
            }}
          >
            {changes.map((c, i) => {
              const active = i === Math.min(selectedIdx, changes.length - 1);
              return (
                <button
                  key={`${c.path}-${i}`}
                  data-testid={`workstation-path-${i}`}
                  onClick={() => setSelectedIdx(i)}
                  title={c.path}
                  style={{
                    textAlign: 'left', padding: '4px 8px', borderRadius: 4,
                    border: `1px solid ${active ? _AMBER : '#33334a'}`,
                    background: 'transparent', color: active ? _AMBER : '#aaaac0',
                    cursor: 'pointer', fontSize: 11, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}
                >
                  {_baseName(c.path) || c.path}
                </button>
              );
            })}
          </div>
        )}

        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {doc?.kind === 'artifact' && artifactText === null && artifactError === null ? (
            <div data-testid="workstation-loading" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
              Loading artifact…
            </div>
          ) : doc?.kind === 'artifact' && artifactError !== null ? (
            <div data-testid="workstation-artifact-error" style={{ padding: 16, color: _DIM, fontSize: 12 }}>
              Artifact unavailable: {artifactError}
            </div>
          ) : (
            <Suspense fallback={<div data-testid="workstation-editor-loading" style={{ padding: 16, color: _DIM, fontSize: 12 }}>Loading editor…</div>}>
              <MonacoSurface value={shownContent} language={language} readOnly={!showEditor} onChange={showEditor ? setScratch : undefined} />
            </Suspense>
          )}
        </div>
      </div>
    </div>
  );
}
