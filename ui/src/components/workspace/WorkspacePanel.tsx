/** AD-1023: WorkspacePanel — the HXI Workspace container (Experience layer). A
 *  full-screen overlay that hosts multiple AD-1022 Workstations over one backing
 *  work context, with a single-active-tab rail. DISTINCT from the AD-997
 *  execution work folder it BINDS to (DD-3 naming reconciliation): the folder is
 *  read read-only through the existing AD-998 endpoint
 *  GET /api/agent/{id}/workspace.
 *
 *  Mirrors the AD-1021 WorkstationPanel overlay exactly: store-flag gated
 *  (`workspaceOpen`, default false -> mounted-but-null when closed), close via
 *  the header X or Escape. Each workstation is resolved through the exported
 *  AD-1022 WorkstationRender seam (native component or sandboxed iframe), and a
 *  per-workstation doc is forwarded so the container can host more than one
 *  document at once (DD-5; standalone callers still fall back to the global
 *  store doc, byte-identical to AD-1021).
 *
 *  Deps-injectable (HXI convention, mirrors WorkstationLauncher) so tests need no
 *  global fetch mock. HXI #3: inline stroke-SVG glyphs (strokeWidth 1.5), amber
 *  active / dim inactive, NO emoji, a data-testid on every interactive element.
 */
import { useEffect, useState, type ComponentType } from 'react';
import { useStore } from '../../store/useStore';
import { McpAppFrame } from '../McpAppFrame';
import {
  WorkstationRender,
  DEFAULT_FETCH_TYPES,
  type WorkstationTypeView,
  type WorkstationLauncherDeps,
  type NativeWorkstationProps,
} from '../workstation/WorkstationLauncher';
import { nativeWorkstations } from '../workstation/nativeWorkstations';
import { fetchWorkspaceFolder as defaultFetchWorkspaceFolder } from './workspaceApi';
import type { WorkspaceFolder, WorkspaceWorkstation } from '../../store/types';

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

function IconWorkspace({ color = _AMBER }: { color?: string }): React.ReactElement {
  // Stacked frames (HXI #3: no emoji) — a container holding multiple workstations.
  return (
    <svg {..._svgBase(color)} aria-hidden="true">
      <rect x="3" y="6" width="14" height="12" rx="1.5" />
      <path d="M7 3 H21 a0 0 0 0 1 0 0 M7 3 H19 a2 2 0 0 1 2 2 V14" />
    </svg>
  );
}

export interface WorkspacePanelDeps {
  fetchTypes: () => Promise<WorkstationTypeView[]>;
  fetchWorkspaceFolder: (id: string) => Promise<WorkspaceFolder>;
  nativeComponents: Record<string, ComponentType<NativeWorkstationProps>>;
  IframeFrame: typeof McpAppFrame;
}

export function WorkspacePanel({
  deps,
}: {
  deps?: Partial<WorkspacePanelDeps>;
}): React.ReactElement | null {
  const open = useStore((s) => s.workspaceOpen);
  const activeWorkspace = useStore((s) => s.activeWorkspace);
  const close = () => useStore.getState().closeWorkspace();

  const merged: WorkspacePanelDeps = {
    fetchTypes: deps?.fetchTypes ?? DEFAULT_FETCH_TYPES,
    fetchWorkspaceFolder: deps?.fetchWorkspaceFolder ?? defaultFetchWorkspaceFolder,
    nativeComponents: deps?.nativeComponents ?? nativeWorkstations,
    IframeFrame: deps?.IframeFrame ?? McpAppFrame,
  };

  const [catalog, setCatalog] = useState<WorkstationTypeView[]>([]);
  const [folder, setFolder] = useState<WorkspaceFolder | null>(null);
  const [folderError, setFolderError] = useState<boolean>(false);
  const [activeIdx, setActiveIdx] = useState<number>(0);

  const backingStoreRef = activeWorkspace?.backingStoreRef ?? null;

  // Escape-to-close (mirrors WorkstationPanel).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Fetch the workstation catalog once when the container opens. Honest-degrade
  // to an empty catalog on any error (never a blank, never a throw).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const list = await merged.fetchTypes();
        if (!cancelled) setCatalog(list);
      } catch {
        if (!cancelled) setCatalog([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Bind the backing store (AD-998). Only when the workspace declares a
  // backingStoreRef (per-agent id, DD-2). Cancel-on-unmount guard; honest-degrade
  // to a folderError flag so the strip shows a notice instead of going blank.
  useEffect(() => {
    if (!open || !backingStoreRef) {
      setFolder(null);
      setFolderError(false);
      return;
    }
    let cancelled = false;
    setFolder(null);
    setFolderError(false);
    void (async () => {
      try {
        const f = await merged.fetchWorkspaceFolder(backingStoreRef);
        if (!cancelled) setFolder(f);
      } catch {
        if (!cancelled) setFolderError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, backingStoreRef]);

  if (!open) return null;

  const renderDeps: WorkstationLauncherDeps = {
    fetchTypes: merged.fetchTypes,
    IframeFrame: merged.IframeFrame,
    nativeComponents: merged.nativeComponents,
  };

  const workstations: WorkspaceWorkstation[] = activeWorkspace?.workstations ?? [];
  const safeIdx = workstations.length > 0 ? Math.min(activeIdx, workstations.length - 1) : 0;
  const activeW = workstations.length > 0 ? workstations[safeIdx] : null;

  // Backing-store strip content (only meaningful when a backingStoreRef exists).
  let backingText: string | null = null;
  if (folderError) {
    backingText = 'Work folder unavailable.';
  } else if (folder) {
    if (folder.enabled && folder.persistent && folder.exists) {
      backingText = `${folder.path} · ${folder.files.length} files`;
    } else {
      backingText = 'No persistent work folder (code execution disabled or ephemeral).';
    }
  } else {
    backingText = 'Loading work folder…';
  }

  return (
    <div
      data-testid="workspace-panel"
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
          <IconWorkspace />
          <div>
            <div data-testid="workspace-title" style={{ fontSize: 14, color: _AMBER, letterSpacing: 1 }}>
              {activeWorkspace?.label ?? 'WORKSPACE'}
            </div>
            <div style={{ fontSize: 10, color: _DIM, marginTop: 2 }}>
              A container hosting multiple workstations over one work context.
            </div>
          </div>
        </div>
        <button
          data-testid="workspace-close"
          onClick={close}
          aria-label="Close Workspace"
          style={{ background: 'none', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: _DIM, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <IconClose />
        </button>
      </div>

      {backingStoreRef && (
        <div
          data-testid="workspace-backing-store"
          style={{ padding: '8px 18px', borderBottom: '1px solid rgba(255,255,255,0.06)', fontSize: 11, color: _DIM }}
        >
          {backingText}
        </div>
      )}

      {!activeWorkspace ? (
        <div data-testid="workspace-none" style={{ padding: 18, color: _DIM, fontSize: 12 }}>
          No workspace open.
        </div>
      ) : workstations.length === 0 ? (
        <div data-testid="workspace-empty" style={{ padding: 18, color: _DIM, fontSize: 12 }}>
          This workspace has no workstations yet.
        </div>
      ) : (
        <>
          <div
            data-testid="workspace-tabs"
            style={{ display: 'flex', gap: 6, padding: 8, flexWrap: 'wrap', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
          >
            {workstations.map((w, idx) => {
              const isActive = idx === safeIdx;
              const catalogView = catalog.find((v) => v.id === w.typeId);
              const label = w.label ?? catalogView?.label ?? w.typeId;
              return (
                <button
                  key={`${w.typeId}-${idx}`}
                  type="button"
                  data-testid={`workspace-tab-${idx}`}
                  onClick={() => setActiveIdx(idx)}
                  style={{
                    padding: '4px 10px',
                    border: `1px solid ${isActive ? _AMBER : '#33334a'}`,
                    borderRadius: 4,
                    background: 'transparent',
                    color: isActive ? _AMBER : _DIM,
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div data-testid="workspace-active" style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {(() => {
              if (!activeW) return null;
              const view = catalog.find((v) => v.id === activeW.typeId);
              const label = activeW.label ?? view?.label ?? activeW.typeId;
              if (view && view.available) {
                return <WorkstationRender type={view} deps={renderDeps} doc={activeW.doc} />;
              }
              return (
                <div
                  data-testid="workspace-workstation-unavailable"
                  style={{ padding: 16, color: _DIM, fontSize: 12 }}
                >
                  {label} is not yet available.
                </div>
              );
            })()}
          </div>
        </>
      )}
    </div>
  );
}

export default WorkspacePanel;
