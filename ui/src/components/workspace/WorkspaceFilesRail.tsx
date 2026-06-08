/**
 * AD-929: Unified workspace "Files" rail — the Teams-channel surface.
 *
 * Mounted by ``ProfileChatTab`` behind the ``isWorkspaceRoom`` gate, as a
 * collapsible right rail beside the conversation column. Two stacked
 * sections mirror Teams' "Conversation + Files":
 *   INPUTS  — the AD-926 ``InputsList``, fed by ``fetchThreadInputs``.
 *   OUTPUTS — the AD-797 ``ArtifactList``, fed by ``fetchThreadArtifacts``.
 *
 * Self-contained: it owns its own fetch + local state (mirrors AD-926's
 * ``InputsList`` + ``inputsApi`` pattern), with no coupling to the global
 * ``selectedArtifactId`` / ``artifactsByThread`` slice that the standalone
 * ``ArtifactDrawer`` owns. The full ``ArtifactDrawer`` is therefore never
 * mounted twice — this rail composes the lighter presentational
 * ``ArtifactList`` instead. Outputs rows open ``/api/artifacts/{id}/content``
 * in a new tab (read-only parity with ``InputsList``).
 *
 * Collapse state persists under localStorage ``probos.workspaceFiles.collapsed``
 * (mirrors ``ArtifactDrawer``), but defaults to COLLAPSED on first run — the
 * primary host (``AgentProfilePanel``) is a 420px floating panel where an
 * expanded 300px rail would crowd the chat; the Captain expands on demand
 * (the panel is resizable to make room).
 *
 * HXI Design Principle #3 — inline stroke-SVG glyphs only, no emoji.
 */
import { useCallback, useEffect, useState } from 'react';
import { InputsList } from '../inputs/InputsList';
import { fetchThreadInputs, attachTaskInputs, type TaskInput } from '../inputs/inputsApi';
import { ArtifactList } from '../artifacts/ArtifactList';
import { fetchThreadArtifacts } from '../artifacts/artifactApi';
import type { ArtifactView } from '../../store/useStore';

const AMBER = '#f0b060';
const DIM = '#666680';
const STORAGE_KEY = 'probos.workspaceFiles.collapsed';

function loadCollapsedFromStorage(): boolean | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === '1') return true;
    if (raw === '0') return false;
    return null;
  } catch {
    return null;
  }
}

function persistCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
  } catch {
    // honest-degrade — persistence is best-effort; the rail still works.
  }
}

export interface WorkspaceFilesRailProps {
  threadId: string;
  /** AD-926a: the room's work item id (thread.task_id). When set, the
   *  Inputs section shows a multi-file "+ Attach" affordance. A workspace
   *  room without a bound work item (>=2 crew, no task_id) has no place to
   *  hold inputs, so the button is hidden. */
  taskId?: string | null;
}

export function WorkspaceFilesRail(props: WorkspaceFilesRailProps) {
  const { threadId, taskId } = props;
  const [inputs, setInputs] = useState<TaskInput[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactView[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Default-collapsed on first run (null from storage). Divergence from
  // ArtifactDrawer's default-expanded — justified by the 420px floating
  // AgentProfilePanel host (see module header).
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    const persisted = loadCollapsedFromStorage();
    return persisted ?? true;
  });

  // Fetch inputs + artifacts on threadId change; honest-degrade to [] so a
  // failed endpoint shows an empty section instead of crashing the rail.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchThreadInputs(threadId);
        if (!cancelled) setInputs(list);
      } catch {
        if (!cancelled) setInputs([]);
      }
    })();
    (async () => {
      try {
        const list = await fetchThreadArtifacts(threadId);
        if (!cancelled) setArtifacts(list);
      } catch {
        if (!cancelled) setArtifacts([]);
      }
    })();
    return () => { cancelled = true; };
  }, [threadId]);

  const handleToggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      persistCollapsed(next);
      return next;
    });
  }, []);

  const openArtifact = useCallback((id: string) => {
    setSelectedId(id);
    window.open(
      `/api/artifacts/${encodeURIComponent(id)}/content`,
      '_blank',
      'noopener',
    );
  }, []);

  // AD-926a: attach one or more files to the room's work item (task). One
  // multipart request for all files (mirrors ProfileChatTab.uploadAttachment).
  // On success the rail's local inputs state is replaced by the returned list.
  const handleAttach = useCallback(async (picked: File[]) => {
    if (!taskId || picked.length === 0) return;
    try {
      const updated = await attachTaskInputs(taskId, picked);
      setInputs(updated);
    } catch {
      // honest-degrade — the attach failed; the rail keeps its current list.
    }
  }, [taskId]);

  const totalCount = inputs.length + artifacts.length;

  if (collapsed) {
    return (
      <aside
        data-testid="workspace-files-rail"
        data-collapsed="true"
        style={{
          flex: '0 0 28px', width: 28,
          background: 'rgba(10, 10, 18, 0.92)',
          borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '8px 0',
        }}
      >
        <button
          type="button" onClick={handleToggle}
          data-testid="workspace-files-expand"
          title={`Files (${totalCount})`}
          style={{
            background: 'transparent', border: 'none', color: AMBER,
            cursor: 'pointer', padding: 4,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-label="open files">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span style={{
          writingMode: 'vertical-rl', textOrientation: 'mixed',
          fontSize: 9, letterSpacing: 1.5, color: AMBER, marginTop: 8,
        }}>FILES</span>
        {totalCount > 0 && (
          <span
            data-testid="workspace-files-count"
            style={{
              fontSize: 9, color: AMBER, marginTop: 8,
              border: '1px solid rgba(240, 176, 96, 0.3)',
              borderRadius: 3, padding: '0 4px',
            }}
          >
            {totalCount}
          </span>
        )}
      </aside>
    );
  }

  return (
    <aside
      data-testid="workspace-files-rail"
      data-collapsed="false"
      style={{
        flex: '0 0 300px', width: 300,
        background: 'rgba(10, 10, 18, 0.92)',
        borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
        display: 'flex', flexDirection: 'column',
      }}
    >
      <div
        style={{
          flex: '0 0 auto', display: 'flex', alignItems: 'center',
          gap: 8, padding: '8px 10px',
          borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
        }}
      >
        <span style={{ color: AMBER, display: 'inline-flex' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-label="files">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          </svg>
        </span>
        <span style={{
          flex: '1 1 auto', fontSize: 11, letterSpacing: 1.5, color: AMBER,
        }}>FILES</span>
        <button
          type="button" onClick={handleToggle}
          data-testid="workspace-files-collapse"
          title="Collapse files"
          style={{
            background: 'transparent', border: 'none', color: DIM,
            cursor: 'pointer', padding: 4,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-label="collapse files">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>

      <div style={{ flex: '1 1 50%', overflowY: 'auto', minHeight: 0 }}>
        <div
          data-testid="workspace-files-inputs-label"
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 10, letterSpacing: 1.5, color: DIM,
            padding: '8px 10px 4px',
          }}
        >
          <span style={{ flex: '1 1 auto' }}>INPUTS</span>
          {taskId && (
            <label
              data-testid="workspace-files-attach"
              title="Attach files to this task"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 3,
                color: AMBER, cursor: 'pointer', fontSize: 10,
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth={1.5}
                strokeLinecap="round" strokeLinejoin="round" aria-label="attach">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Attach
              <input
                type="file"
                multiple
                data-testid="workspace-files-attach-input"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []);
                  void handleAttach(picked);
                  if (e.target) e.target.value = '';
                }}
              />
            </label>
          )}
        </div>
        <InputsList inputs={inputs} />
      </div>

      <div
        style={{
          flex: '1 1 50%', overflowY: 'auto', minHeight: 0,
          borderTop: '1px solid rgba(240, 176, 96, 0.10)',
        }}
      >
        <div
          data-testid="workspace-files-outputs-label"
          style={{
            fontSize: 10, letterSpacing: 1.5, color: DIM,
            padding: '8px 10px 4px',
          }}
        >
          OUTPUTS
        </div>
        <ArtifactList
          artifacts={artifacts}
          selectedId={selectedId}
          onSelect={openArtifact}
        />
      </div>
    </aside>
  );
}
