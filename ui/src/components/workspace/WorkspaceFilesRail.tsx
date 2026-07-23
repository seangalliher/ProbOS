/**
 * AD-929: Unified workspace "Files" rail — the Teams-channel surface.
 *
 * Mounted by ``ProfileChatTab`` behind the ``isWorkspaceRoom`` gate, as a
 * collapsible right rail beside the conversation column. Two stacked
 * sections mirror Teams' "Conversation + Files":
 *   INPUTS  — the AD-926 ``InputsList``, fed by ``fetchThreadInputs``.
 *   OUTPUTS — the AD-797 ``ArtifactList``, fed by ``fetchThreadArtifacts``.
 *
 * AD-1083: a TODOS section (the AD-1080 senior-validation checklist) sits above
 * Inputs when the room has a bound task; the Captain confirms/rejects submitted
 * steps inline. Self-contained: it owns its own fetch + local state (mirrors AD-926's
 * ``InputsList`` + ``inputsApi`` pattern), with no coupling to the global
 * ``selectedArtifactId`` / ``artifactsByThread`` slice that the standalone
 * ``ArtifactDrawer`` owns. The full ``ArtifactDrawer`` is therefore never
 * mounted twice — this rail composes the lighter presentational
 * ``ArtifactList`` instead. BF-642: clicking an Output opens an in-app
 * ``ArtifactViewer`` preview overlay (Cowork parity) — no new tab. The
 * standalone ``ArtifactDrawer`` is suppressed in workspace rooms (gated in
 * ``AgentProfilePanel``) so this is the single Files surface.
 *
 * Collapse state persists under localStorage ``probos.workspaceFiles.collapsed``
 * (mirrors ``ArtifactDrawer``), but defaults to COLLAPSED on first run — the
 * primary host (``AgentProfilePanel``) is a 420px floating panel where an
 * expanded 300px rail would crowd the chat; the Captain expands on demand
 * (the panel is resizable to make room).
 *
 * HXI Design Principle #3 — inline stroke-SVG glyphs only, no emoji.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { InputsList } from '../inputs/InputsList';
import { fetchThreadInputs, attachTaskInputs, type TaskInput } from '../inputs/inputsApi';
import { ArtifactList } from '../artifacts/ArtifactList';
import { ArtifactViewer } from '../artifacts/ArtifactViewer';
import { fetchArtifactMetadata, fetchThreadArtifacts } from '../artifacts/artifactApi';
import { TodosList } from './TodosList';
import { fetchTaskSteps, startRoomWork, updateTaskStep, type TodoStep } from './todosApi';
import type { ArtifactView } from '../../store/useStore';
import { useStore } from '../../store/useStore';
import type {
  CrewSessionArtifactCommand,
  CrewSessionRetryCommand,
  StartWorkResult,
} from '../../store/types';

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
  retryCommand?: CrewSessionRetryCommand | null;
  artifactCommand?: CrewSessionArtifactCommand | null;
  onSessionBound?: (result: StartWorkResult) => void;
}

export function WorkspaceFilesRail(props: WorkspaceFilesRailProps) {
  const {
    threadId,
    taskId,
    retryCommand = null,
    artifactCommand = null,
    onSessionBound,
  } = props;
  const [inputs, setInputs] = useState<TaskInput[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactView[]>([]);
  const [artifactsLoaded, setArtifactsLoaded] = useState(false);
  const [steps, setSteps] = useState<TodoStep[]>([]);
  const [startedSessionBinding, setStartedSessionBinding] = useState<{
    threadId: string;
    parentId: string;
  } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const [startGoal, setStartGoal] = useState('');
  const [startCriteria, setStartCriteria] = useState('');
  const [startDeliverable, setStartDeliverable] = useState('');
  const [retryBlocked, setRetryBlocked] = useState(false);
  const [startPending, setStartPending] = useState(false);
  const [startError, setStartError] = useState('');
  const startSubmittingRef = useRef(false);
  const startGenerationRef = useRef(0);
  const startDialogRef = useRef<HTMLDivElement | null>(null);
  const startGoalRef = useRef<HTMLTextAreaElement | null>(null);
  const startOpenerRef = useRef<HTMLButtonElement | null>(null);
  const startOpenerOwnerRef = useRef<{ threadId: string; generation: number } | null>(null);
  const blockedRetryOriginRef = useRef(false);
  const lastRetryRequestRef = useRef(0);
  const lastArtifactRequestRef = useRef(0);
  const artifactGenerationRef = useRef(0);
  const [artifactCommandError, setArtifactCommandError] = useState('');
  const [artifactLookupPending, setArtifactLookupPending] = useState(false);
  const roomTokenRef = useRef({ threadId, generation: 0 });
  if (roomTokenRef.current.threadId !== threadId) {
    roomTokenRef.current = {
      threadId,
      generation: roomTokenRef.current.generation + 1,
    };
    startGenerationRef.current += 1;
    artifactGenerationRef.current += 1;
    lastRetryRequestRef.current = 0;
    lastArtifactRequestRef.current = 0;
  }
  const ownsRoom = useCallback((token: { threadId: string; generation: number }): boolean => (
    roomTokenRef.current.threadId === token.threadId
    && roomTokenRef.current.generation === token.generation
  ), []);
  const startedParentId = startedSessionBinding?.threadId === threadId
    ? startedSessionBinding.parentId
    : null;
  const effectiveTaskId = taskId ?? startedParentId;
  const effectiveTaskIdRef = useRef(effectiveTaskId);
  effectiveTaskIdRef.current = effectiveTaskId;
  useEffect(() => {
    startSubmittingRef.current = false;
    setStartPending(false);
    setStartDialogOpen(false);
    setStartError('');
    setStartedSessionBinding(null);
    startOpenerRef.current = null;
    startOpenerOwnerRef.current = null;
    blockedRetryOriginRef.current = false;
    setArtifactCommandError('');
    setArtifactLookupPending(false);
    setSelectedId(null);
    setArtifactsLoaded(false);
  }, [threadId]);
  useEffect(() => {
    if (taskId) setStartedSessionBinding(null);
  }, [taskId]);
  useEffect(() => {
    if (!startDialogOpen) return;
    startGoalRef.current?.focus();
  }, [startDialogOpen]);
  useEffect(() => {
    if (!startDialogOpen || !startPending) return;
    startDialogRef.current?.focus();
  }, [startDialogOpen, startPending]);
  // Default-collapsed on first run (null from storage). Divergence from
  // ArtifactDrawer's default-expanded — justified by the 420px floating
  // AgentProfilePanel host (see module header).
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    const persisted = loadCollapsedFromStorage();
    return persisted ?? true;
  });
  // BF-649: enlargeable preview width (Cowork-style), drag the left edge.
  const [previewWidth, setPreviewWidth] = useState<number>(() => {
    const n = Number(localStorage.getItem('probos.workspaceFiles.previewW'));
    return n >= 360 ? n : 560;
  });
  const [showDetails, setShowDetails] = useState(false);
  const dragRef = useRef<{ x: number; w: number } | null>(null);
  const startPreviewDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.current = { x: e.clientX, w: previewWidth };
    const move = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const w = Math.max(360, Math.min(1100, dragRef.current.w + (dragRef.current.x - ev.clientX)));
      setPreviewWidth(w);
    };
    const up = () => {
      try { localStorage.setItem('probos.workspaceFiles.previewW', String(previewWidth)); } catch { /* best-effort */ }
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }, [previewWidth]);

  // Fetch inputs + artifacts on threadId change; honest-degrade to [] so a
  // failed endpoint shows an empty section instead of crashing the rail.
  useEffect(() => {
    const token = roomTokenRef.current;
    (async () => {
      try {
        const list = await fetchThreadInputs(threadId);
        if (ownsRoom(token)) setInputs(list);
      } catch {
        if (ownsRoom(token)) setInputs([]);
      }
    })();
    (async () => {
      try {
        const list = await fetchThreadArtifacts(threadId);
        if (ownsRoom(token)) {
          setArtifacts(list);
          setArtifactsLoaded(true);
        }
      } catch {
        if (ownsRoom(token)) {
          setArtifacts([]);
          setArtifactsLoaded(true);
        }
      }
    })();
  }, [ownsRoom, threadId]);

  // BF-644: poll outputs + todos every 5s so files/steps the crew produce
  // mid-session fill in without reopening the rail (no WS yet). Stops when the
  // rail is collapsed (offscreen) to avoid needless fetches.
  useEffect(() => {
    if (collapsed) return;
    const token = roomTokenRef.current;
    const t = setInterval(() => {
      (async () => {
        try {
          const nextArtifacts = await fetchThreadArtifacts(threadId);
          if (ownsRoom(token)) setArtifacts(nextArtifacts);
        } catch { /* keep */ }
      })();
      if (effectiveTaskId) {
        const targetTaskId = effectiveTaskId;
        (async () => {
          try {
            const nextSteps = await fetchTaskSteps(targetTaskId);
            if (ownsRoom(token) && effectiveTaskIdRef.current === targetTaskId) {
              setSteps(nextSteps);
            }
          } catch { /* keep */ }
        })();
      }
    }, 5000);
    return () => clearInterval(t);
  }, [collapsed, effectiveTaskId, ownsRoom, threadId]);

  const handleToggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      persistCollapsed(next);
      return next;
    });
  }, []);

  useEffect(() => {
    if (
      !retryCommand
      || retryCommand.threadId !== threadId
      || retryCommand.projection.thread_id !== threadId
      || retryCommand.parentId !== retryCommand.projection.task_id
      || !retryCommand.opener.isConnected
      || retryCommand.requestId <= lastRetryRequestRef.current
    ) return;
    lastRetryRequestRef.current = retryCommand.requestId;
    const token = roomTokenRef.current;
    startOpenerRef.current = retryCommand.opener;
    startOpenerOwnerRef.current = token;
    blockedRetryOriginRef.current = true;
    setCollapsed(false);
    persistCollapsed(false);
    setStartedSessionBinding({ threadId, parentId: retryCommand.parentId });
    setStartGoal(retryCommand.projection.goal);
    setStartCriteria(retryCommand.projection.success_criteria.join('\n'));
    setStartDeliverable(retryCommand.projection.expected_deliverable);
    setRetryBlocked(true);
    setStartError('');
    setStartDialogOpen(true);
  }, [retryCommand, threadId]);

  const criteriaValues = startCriteria
    .split('\n')
    .map((criterion) => criterion.trim())
    .filter(Boolean);
  const startFormValid = (
    startGoal.trim().length > 0
    && startGoal.trim().length <= 4096
    && criteriaValues.length > 0
    && criteriaValues.length <= 16
    && criteriaValues.every((criterion) => criterion.length <= 512)
    && new Set(criteriaValues.map((criterion) => criterion.toLocaleLowerCase())).size === criteriaValues.length
    && startDeliverable.trim().length > 0
    && startDeliverable.trim().length <= 2048
  );

  const restoreStartOpener = useCallback(() => {
    const opener = startOpenerRef.current;
    const owner = startOpenerOwnerRef.current;
    if (opener?.isConnected && owner && ownsRoom(owner)) {
      const restore = () => {
        if (opener.isConnected && ownsRoom(owner)) opener.focus();
      };
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(restore);
      } else {
        queueMicrotask(restore);
      }
    }
  }, [ownsRoom]);

  const closeStartDialog = useCallback(() => {
    if (startSubmittingRef.current) return;
    setStartDialogOpen(false);
    setStartError('');
    restoreStartOpener();
  }, [restoreStartOpener]);

  const handleStartDialogKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (!startPending) closeStartDialog();
      return;
    }
    if (event.key !== 'Tab') return;
    const dialog = startDialogRef.current;
    if (!dialog) return;
    const focusableSelector = 'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])';
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>('*'))
      .filter((control) => control.isConnected && control.matches(focusableSelector));
    if (controls.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    event.preventDefault();
    const currentIndex = controls.indexOf(document.activeElement as HTMLElement);
    const nextIndex = currentIndex < 0
      ? (event.shiftKey ? controls.length - 1 : 0)
      : (currentIndex + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
    controls[nextIndex].focus();
  }, [closeStartDialog, startPending]);

  const handleStartWork = useCallback(async (event: React.FormEvent) => {
    event.preventDefault();
    if (!startFormValid || startSubmittingRef.current) return;
    const roomToken = roomTokenRef.current;
    if (roomToken.threadId !== threadId) return;
    const generation = startGenerationRef.current;
    startSubmittingRef.current = true;
    setStartPending(true);
    setStartError('');
    try {
      const result = await startRoomWork(threadId, {
        goal: startGoal.trim(),
        success_criteria: criteriaValues,
        expected_deliverable: startDeliverable.trim(),
        retry_blocked: retryBlocked,
      });
      if (startGenerationRef.current !== generation || !ownsRoom(roomToken)) return;
      if (result.thread_id !== threadId) {
        setStartError('Start Work returned a different room');
        return;
      }
      setStartedSessionBinding({ threadId, parentId: result.parent_id });
      useStore.getState().hydrateCrewSession(result.parent_id, result.session);
      onSessionBound?.(result);
      setStartDialogOpen(false);
      if (!blockedRetryOriginRef.current) restoreStartOpener();
    } catch (error) {
      if (startGenerationRef.current !== generation || !ownsRoom(roomToken)) return;
      const message = error instanceof Error ? error.message : 'Start Work failed';
      setStartError(message.slice(0, 256));
    } finally {
      if (startGenerationRef.current === generation && ownsRoom(roomToken)) {
        startSubmittingRef.current = false;
        setStartPending(false);
      }
    }
  }, [criteriaValues, onSessionBound, ownsRoom, restoreStartOpener, retryBlocked, startDeliverable, startFormValid, startGoal, threadId]);

  const openArtifact = useCallback((id: string) => {
    // BF-642: open the in-app ArtifactViewer preview (Cowork parity) rather
    // than dumping raw bytes in a new tab. The selected output renders in an
    // overlay below; the Captain closes it to return to the lists.
    const row = artifacts.find(artifact => (
      artifact.id === id && artifact.thread_id === roomTokenRef.current.threadId
    ));
    if (row) setSelectedId(id);
  }, [artifacts]);

  const loadCommandArtifact = useCallback(async (command: CrewSessionArtifactCommand) => {
    if (command.threadId !== threadId) return;
    const roomToken = roomTokenRef.current;
    if (!ownsRoom(roomToken)) return;
    const generation = ++artifactGenerationRef.current;
    setCollapsed(false);
    persistCollapsed(false);
    setArtifactCommandError('');
    const existing = artifacts.find(artifact => (
      artifact.id === command.artifactId && artifact.thread_id === command.threadId
    ));
    if (existing) {
      setSelectedId(existing.id);
      return;
    }
    if (artifacts.some(artifact => artifact.id === command.artifactId)) {
      setArtifactCommandError('Result artifact metadata could not be loaded.');
      setSelectedId(null);
      return;
    }
    setArtifactLookupPending(true);
    const metadata = await fetchArtifactMetadata(command.artifactId);
    if (
      artifactGenerationRef.current !== generation
      || !ownsRoom(roomToken)
      || command.threadId !== threadId
    ) return;
    setArtifactLookupPending(false);
    if (
      metadata === null
      || metadata.id !== command.artifactId
      || metadata.thread_id !== command.threadId
    ) {
      setArtifactCommandError('Result artifact metadata could not be loaded.');
      setSelectedId(null);
      return;
    }
    setArtifacts(current => current.some(row => (
      row.id === metadata.id && row.thread_id === metadata.thread_id
    )) ? current : [...current.filter(row => row.thread_id === command.threadId), metadata]);
    setSelectedId(metadata.id);
  }, [artifacts, ownsRoom, threadId]);

  useEffect(() => {
    if (
      !artifactCommand
      || artifactCommand.threadId !== threadId
      || !artifactsLoaded
      || artifactCommand.requestId <= lastArtifactRequestRef.current
    ) return;
    lastArtifactRequestRef.current = artifactCommand.requestId;
    void loadCommandArtifact(artifactCommand);
  }, [artifactCommand, artifactsLoaded, loadCommandArtifact, threadId]);

  // AD-926a: attach one or more files to the room's work item (task). One
  // multipart request for all files (mirrors ProfileChatTab.uploadAttachment).
  // On success the rail's local inputs state is replaced by the returned list.
  const handleAttach = useCallback(async (picked: File[]) => {
    if (!effectiveTaskId || picked.length === 0) return;
    const roomToken = roomTokenRef.current;
    const targetTaskId = effectiveTaskId;
    try {
      const updated = await attachTaskInputs(targetTaskId, picked);
      if (ownsRoom(roomToken) && effectiveTaskIdRef.current === targetTaskId) {
        setInputs(updated);
      }
    } catch {
      // honest-degrade — the attach failed; the rail keeps its current list.
    }
  }, [effectiveTaskId, ownsRoom]);

  // AD-1083: load the room Todo checklist when the task changes, and on
  // confirm/reject by the Captain. Honest-degrade to [] (no task / no steps).
  const refreshSteps = useCallback(async () => {
    if (!effectiveTaskId) { setSteps([]); return; }
    const roomToken = roomTokenRef.current;
    const targetTaskId = effectiveTaskId;
    try {
      const nextSteps = await fetchTaskSteps(targetTaskId);
      if (ownsRoom(roomToken) && effectiveTaskIdRef.current === targetTaskId) {
        setSteps(nextSteps);
      }
    } catch {
      if (ownsRoom(roomToken) && effectiveTaskIdRef.current === targetTaskId) {
        setSteps([]);
      }
    }
  }, [effectiveTaskId, ownsRoom]);
  useEffect(() => { void refreshSteps(); }, [refreshSteps]);
  const handleConfirm = useCallback(async (idx: number) => {
    if (!effectiveTaskId) return;
    const roomToken = roomTokenRef.current;
    const targetTaskId = effectiveTaskId;
    try { await updateTaskStep(targetTaskId, idx, { status: 'done', actor: 'captain' }); } catch { /* keep list */ }
    if (!ownsRoom(roomToken) || effectiveTaskIdRef.current !== targetTaskId) return;
    void refreshSteps();
  }, [effectiveTaskId, ownsRoom, refreshSteps]);
  const handleReject = useCallback(async (idx: number) => {
    if (!effectiveTaskId) return;
    const roomToken = roomTokenRef.current;
    const targetTaskId = effectiveTaskId;
    try { await updateTaskStep(targetTaskId, idx, { status: 'rejected', actor: 'captain' }); } catch { /* keep list */ }
    if (!ownsRoom(roomToken) || effectiveTaskIdRef.current !== targetTaskId) return;
    void refreshSteps();
  }, [effectiveTaskId, ownsRoom, refreshSteps]);
  const doneCount = steps.filter((s) => s.status === 'done').length;

  const totalCount = inputs.length + artifacts.length + steps.length;
  // BF-642: the output selected for in-app preview (Cowork-style file preview).
  const selectedArtifact = selectedId ? (
    artifacts.find(artifact => (
      artifact.id === selectedId && artifact.thread_id === threadId
    )) ?? null
  ) : null;

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
        flex: `0 0 ${selectedArtifact ? previewWidth : 300}px`, width: selectedArtifact ? previewWidth : 300, position: 'relative',
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
          type="button"
          onClick={(event) => {
            startOpenerRef.current = event.currentTarget;
            startOpenerOwnerRef.current = roomTokenRef.current;
            blockedRetryOriginRef.current = false;
            setStartError('');
            setRetryBlocked(false);
            setStartDialogOpen(true);
          }}
          data-testid="workspace-start-work-open"
          title="Start work"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            background: 'transparent', border: '1px solid rgba(240, 176, 96, 0.35)',
            borderRadius: 4, color: AMBER, cursor: 'pointer', padding: '3px 6px',
            fontSize: 10,
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 5v14l11-7z" />
          </svg>
          Start Work
        </button>
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

      {artifactCommandError && artifactCommand ? (
        <div role="alert" data-testid="workspace-artifact-command-error" style={{ padding: '8px 10px', color: '#f08b8b', fontSize: 11, overflowWrap: 'anywhere' }}>
          {artifactCommandError}{' '}
          <button
            type="button"
            disabled={artifactLookupPending}
            onClick={() => { void loadCommandArtifact(artifactCommand); }}
            data-testid="workspace-artifact-command-retry"
          >
            Retry
          </button>
        </div>
      ) : null}

      {startDialogOpen && (
        <div
          ref={startDialogRef}
          role="dialog"
          tabIndex={-1}
          aria-modal="true"
          aria-labelledby="workspace-start-work-title"
          data-testid="workspace-start-work-dialog"
          onKeyDown={handleStartDialogKeyDown}
          style={{
            position: 'absolute', inset: 0, zIndex: 40,
            background: 'rgba(8, 8, 14, 0.98)', padding: 12,
            overflowY: 'auto',
          }}
        >
          <form onSubmit={(event) => { void handleStartWork(event); }}>
            <div id="workspace-start-work-title" style={{ color: AMBER, fontSize: 12, letterSpacing: 1.2, marginBottom: 12 }}>
              START WORK
            </div>
            <label htmlFor="workspace-start-goal" style={{ display: 'block', color: DIM, fontSize: 10, marginBottom: 4 }}>
              GOAL
            </label>
            <textarea
              ref={startGoalRef}
              id="workspace-start-goal"
              data-testid="workspace-start-work-goal"
              value={startGoal}
              maxLength={4096}
              onChange={(event) => setStartGoal(event.target.value)}
              disabled={startPending}
              style={{ width: '100%', minHeight: 74, boxSizing: 'border-box', resize: 'vertical', borderRadius: 4, border: '1px solid #353548', background: '#11111c', color: '#e5e5ef', padding: 7, marginBottom: 10 }}
            />
            <label htmlFor="workspace-start-criteria" style={{ display: 'block', color: DIM, fontSize: 10, marginBottom: 4 }}>
              SUCCESS CRITERIA
            </label>
            <textarea
              id="workspace-start-criteria"
              data-testid="workspace-start-work-criteria"
              value={startCriteria}
              maxLength={8208}
              onChange={(event) => setStartCriteria(event.target.value)}
              disabled={startPending}
              style={{ width: '100%', minHeight: 82, boxSizing: 'border-box', resize: 'vertical', borderRadius: 4, border: '1px solid #353548', background: '#11111c', color: '#e5e5ef', padding: 7, marginBottom: 10 }}
            />
            <label htmlFor="workspace-start-deliverable" style={{ display: 'block', color: DIM, fontSize: 10, marginBottom: 4 }}>
              EXPECTED DELIVERABLE
            </label>
            <textarea
              id="workspace-start-deliverable"
              data-testid="workspace-start-work-deliverable"
              value={startDeliverable}
              maxLength={2048}
              onChange={(event) => setStartDeliverable(event.target.value)}
              disabled={startPending}
              style={{ width: '100%', minHeight: 58, boxSizing: 'border-box', resize: 'vertical', borderRadius: 4, border: '1px solid #353548', background: '#11111c', color: '#e5e5ef', padding: 7, marginBottom: 10 }}
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#cfcfe0', fontSize: 11, marginBottom: 10 }}>
              <input
                type="checkbox"
                data-testid="workspace-start-work-retry"
                checked={retryBlocked}
                onChange={(event) => setRetryBlocked(event.target.checked)}
                disabled={startPending}
              />
              Retry blocked work
            </label>
            {startError && (
              <div role="alert" data-testid="workspace-start-work-error" style={{ color: '#f08b8b', fontSize: 11, marginBottom: 10, overflowWrap: 'anywhere' }}>
                {startError}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                type="button"
                onClick={closeStartDialog}
                disabled={startPending}
                data-testid="workspace-start-work-cancel"
                style={{ borderRadius: 4, border: '1px solid #353548', background: 'transparent', color: DIM, padding: '5px 9px', cursor: startPending ? 'default' : 'pointer' }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!startFormValid || startPending}
                data-testid="workspace-start-work-confirm"
                style={{ borderRadius: 4, border: `1px solid ${AMBER}`, background: startFormValid && !startPending ? 'rgba(240, 176, 96, 0.12)' : 'transparent', color: startFormValid && !startPending ? AMBER : DIM, padding: '5px 9px', cursor: startFormValid && !startPending ? 'pointer' : 'default' }}
              >
                {startPending ? 'Starting' : 'Start'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* AD-1083: room Todo checklist (the AD-1080 senior-validation loop). Only
          when the room has a bound task; the Captain confirms/rejects submitted
          steps inline. */}
      {effectiveTaskId && (
        <div data-testid="workspace-files-todos" style={{ flex: '0 0 auto', maxHeight: '34%', overflowY: 'auto', borderBottom: '1px solid rgba(240, 176, 96, 0.10)' }}>
          <div
            data-testid="workspace-files-todos-label"
            style={{ fontSize: 10, letterSpacing: 1.5, color: DIM, padding: '8px 10px 4px' }}
          >
            TODOS{steps.length > 0 ? ` (${doneCount}/${steps.length})` : ''}
          </div>
          <TodosList steps={steps} onConfirm={handleConfirm} onReject={handleReject} />
        </div>
      )}

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
          {effectiveTaskId && (
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
      {/* BF-642: in-app preview overlay (Cowork parity) — clicking an output
          opens the ArtifactViewer here instead of a raw new tab. */}
      {selectedArtifact && (
        <div
          data-testid="workspace-files-preview"
          style={{
            position: 'absolute', inset: 0, zIndex: 30,
            display: 'flex', flexDirection: 'column',
            background: 'rgba(8, 8, 14, 0.98)',
          }}
        >
          <div
            data-testid="workspace-files-preview-resize"
            onMouseDown={startPreviewDrag}
            title="Drag to resize preview"
            style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 6, cursor: 'ew-resize', zIndex: 31 }}
          />
          <div style={{
            flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8,
            padding: '6px 10px', borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
          }}>
            <span style={{ flex: '1 1 auto', fontSize: 11, letterSpacing: 1, color: AMBER, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {selectedArtifact.name}
            </span>
            <button
              type="button" onClick={() => setShowDetails((d) => !d)}
              data-testid="workspace-files-details-toggle" title="Details"
              style={{ background: 'transparent', border: 'none', color: showDetails ? AMBER : DIM, cursor: 'pointer', padding: 4 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"
                strokeLinejoin="round" aria-label="details">
                <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" />
              </svg>
            </button>
            <button
              type="button" onClick={() => setSelectedId(null)}
              data-testid="workspace-files-preview-close" title="Close preview"
              style={{ background: 'transparent', border: 'none', color: DIM, cursor: 'pointer', padding: 4 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth={1.5} strokeLinecap="round"
                strokeLinejoin="round" aria-label="close preview">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', display: 'flex' }}>
            <div style={{ flex: '1 1 auto', minWidth: 0, overflow: 'auto' }}>
              <ArtifactViewer
                artifact={selectedArtifact}
                versions={artifacts}
                onSelectVersion={setSelectedId}
                projectIdForPinning={null}
              />
            </div>
            {showDetails && (
              <div data-testid="workspace-files-details" style={{
                flex: '0 0 180px', borderLeft: '1px solid rgba(240,176,96,0.15)',
                padding: '8px 10px', fontSize: 11, color: '#cfcfe0', overflowY: 'auto',
              }}>
                <div style={{ color: DIM, letterSpacing: 1, marginBottom: 6 }}>DETAILS</div>
                <div style={{ marginBottom: 4 }}><span style={{ color: DIM }}>Name </span>{selectedArtifact.name}</div>
                <div style={{ marginBottom: 4 }}><span style={{ color: DIM }}>Version </span>v{selectedArtifact.version}</div>
                <div style={{ marginBottom: 4 }}><span style={{ color: DIM }}>Type </span>{selectedArtifact.mime.split('.').pop()}</div>
                <div style={{ marginBottom: 4 }}><span style={{ color: DIM }}>Size </span>{Math.max(1, Math.round((selectedArtifact.size_bytes || 0) / 1024))} KB</div>
                <div><span style={{ color: DIM }}>By </span>{selectedArtifact.created_by}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
