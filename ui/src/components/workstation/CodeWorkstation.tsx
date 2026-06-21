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
import { loadWorkspaceFile, saveWorkspaceFile } from './workspaceFileApi';
import type { WorkspaceFileLoad, WorkspaceSaveResult } from './workspaceFileApi';
import { CoEditPanel } from './CoEditPanel';

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

function IconLoad({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M4 14 V18 a1 1 0 0 0 1 1 H19 a1 1 0 0 0 1 -1 V14" />
      <path d="M12 4 V14 M8 10 L12 14 L16 10" />
    </svg>
  );
}

function IconSave({ color = _DIM }: { color?: string }): React.ReactElement {
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <path d="M5 5 a1 1 0 0 1 1 -1 H16 L19 7 V19 a1 1 0 0 1 -1 1 H6 a1 1 0 0 1 -1 -1 Z" />
      <path d="M8 4 V8 H15 M8 20 V14 H16 V20" />
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

/** AD-1021b: optional write-through props. When ``agentId`` is present the
 *  toolbar gains a path input + Load/Save against that agent's AD-997 workspace
 *  folder (the Save routes through the governed, consensus-gated endpoint). All
 *  three are OPTIONAL so ``CodeWorkstation`` stays assignable to
 *  ``ComponentType<NativeWorkstationProps>`` (nativeWorkstations.ts) and the
 *  scratch/prop-doc experience is BYTE-IDENTICAL to AD-1021 when ``agentId`` is
 *  absent. ``loadFile``/``saveFile`` are injectable for tests; they default to
 *  the same-origin, no-token ``workspaceFileApi`` helpers (DD-1). */
type CodeWorkstationProps = NativeWorkstationProps & {
  agentId?: string;
  loadFile?: (agentId: string, path: string) => Promise<WorkspaceFileLoad>;
  saveFile?: (agentId: string, path: string, content: string) => Promise<WorkspaceSaveResult>;
};

export function CodeWorkstation({
  typeId: _typeId,
  doc: propDoc,
  agentId,
  loadFile = loadWorkspaceFile,
  saveFile = saveWorkspaceFile,
}: CodeWorkstationProps): React.ReactElement {
  // AD-1023: a container host may pass a per-workstation doc; standalone callers
  // pass none -> fall back to the global store doc (byte-identical to AD-1021).
  const storeDoc = useStore((s) => s.workstationDoc);
  const doc = propDoc !== undefined ? propDoc : storeDoc;

  // AD-1021c: co-edit presence reuses the AD-930 ambient slices. `agents` is the
  // store's by-id map (used to label present agents); `presence` is the ambient
  // {id: state} map. Read unconditionally (hook order is stable) but only acted
  // on when agentId enables the co-edit surface below.
  const presence = useStore((s) => s.presence);
  const agentsById = useStore((s) => s.agents);
  const fetchPresence = useStore((s) => s.fetchPresence);

  // Local editor state — re-seeded whenever the active document changes.
  const [scratch, setScratch] = useState<string>('');
  const [selectedIdx, setSelectedIdx] = useState<number>(0);
  const [artifactText, setArtifactText] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  // AD-1021b write-through state (only ever surfaced when agentId is present).
  const [filePath, setFilePath] = useState<string>('');
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

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

  // AD-1021c: hydrate the ambient presence map for the co-edit strip while a
  // co-edit-enabled (agentId) workstation is mounted. The store fn is honest-
  // degrading (a failed /api/crew/presence is swallowed), so this is a no-op
  // when no backend is present (byte-identical to AD-1021b otherwise).
  useEffect(() => {
    if (agentId) void fetchPresence();
  }, [agentId, fetchPresence]);

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

  // AD-1021b: Load a confined workspace file into the scratch buffer. Honest-
  // degrade: a not-found / too-large / failed read sets a banner, never throws.
  const onLoad = async (): Promise<void> => {
    const p = filePath.trim();
    if (!agentId || !p) return;
    setBusy(true);
    setSaveStatus(null);
    try {
      const r = await loadFile(agentId, p);
      if (r.found) {
        setScratch(r.content ?? '');
        setSaveStatus(`loaded ${p}`);
      } else {
        setSaveStatus(r.too_large ? 'file too large to load' : `not found: ${p}`);
      }
    } catch (e) {
      setSaveStatus(`load failed: ${e instanceof Error ? e.message : 'error'}`);
    } finally {
      setBusy(false);
    }
  };

  // AD-1021b: governed Save through the consensus-gated endpoint. Consensus is
  // synchronous + terminal: the in-flight await resolves to committed / refused
  // / disabled — there is NO durable pending-approval queue.
  const onSave = async (): Promise<void> => {
    const p = filePath.trim();
    if (!agentId || !p) return;
    setBusy(true);
    setSaveStatus('Saving — awaiting consensus…');
    try {
      const r = await saveFile(agentId, p, shownContent);
      if (r.outcome === 'committed') {
        setSaveStatus('committed');
      } else if (r.outcome === 'disabled') {
        setSaveStatus('workspace write disabled');
      } else {
        setSaveStatus(`refused: ${r.consensus_outcome ?? 'rejected'}`);
      }
    } catch (e) {
      setSaveStatus(`refused: ${e instanceof Error ? e.message : 'error'}`);
    } finally {
      setBusy(false);
    }
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
        {/* AD-1021b: governed write-through affordance — present ONLY when a host
            passes agentId (otherwise this toolbar is byte-identical to AD-1021). */}
        {agentId && (
          <>
            <input
              data-testid="workstation-path-input"
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              placeholder="path/in/workspace.py"
              aria-label="Workspace file path"
              spellCheck={false}
              style={{
                fontSize: 11, fontFamily: 'inherit', color: _TEXT, background: 'rgba(255,255,255,0.04)',
                border: '1px solid #33334a', borderRadius: 4, padding: '4px 8px', minWidth: 160,
              }}
            />
            <button
              data-testid="workstation-load"
              onClick={() => { void onLoad(); }}
              disabled={busy || !filePath.trim()}
              aria-label="Load file from workspace"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
                border: '1px solid #33334a', borderRadius: 4, background: 'transparent',
                color: _DIM, cursor: busy || !filePath.trim() ? 'default' : 'pointer', fontSize: 11,
                opacity: busy || !filePath.trim() ? 0.5 : 1,
              }}
            >
              <IconLoad />Load
            </button>
            <button
              data-testid="workstation-save"
              onClick={() => { void onSave(); }}
              disabled={busy || !filePath.trim()}
              aria-label="Save file to workspace"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
                border: `1px solid ${busy || !filePath.trim() ? '#33334a' : '#6a5a2a'}`, borderRadius: 4,
                background: 'transparent', color: busy || !filePath.trim() ? _DIM : _AMBER,
                cursor: busy || !filePath.trim() ? 'default' : 'pointer', fontSize: 11,
                opacity: busy || !filePath.trim() ? 0.5 : 1,
              }}
            >
              <IconSave />Save
            </button>
          </>
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

      {/* AD-1021b: honest-degrade write-through banner (committed / refused /
          disabled / in-flight). Only rendered when a host enabled the affordance. */}
      {agentId && saveStatus && (
        <div
          data-testid="workstation-save-status"
          role="status"
          style={{
            padding: '6px 12px', fontSize: 11, letterSpacing: 0.3,
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            color: saveStatus === 'committed' ? '#6fcf97'
              : saveStatus.startsWith('refused') ? '#d98a8a'
              : _DIM,
          }}
        >
          {saveStatus}
        </div>
      )}

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

      {/* AD-1021c: agent co-editing / presence strip — present ONLY when a host
          passes agentId (otherwise byte-identical to AD-1021/1021b). Accept
          reuses the same governed write seam (saveFile); Preview loads a
          proposal into the scratch editor (human-in-control). */}
      {agentId && (
        <CoEditPanel
          ownerId={agentId}
          path={filePath}
          presence={presence}
          agentsById={agentsById}
          onPreview={(content) => setScratch(content)}
          saveFile={saveFile}
        />
      )}
    </div>
  );
}
