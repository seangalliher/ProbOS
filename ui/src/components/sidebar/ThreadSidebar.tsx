/*
 * AD-792 (Wave 195) — ThreadSidebar: chat-thread navigation rail for
 * Compact Yeo (Yeoman desktop tray). The sidebar shows the operator
 * which conversations exist, organized Pinned -> Projects (AD-793)
 * -> Recents (Today / Yesterday / Earlier), and lets them switch
 * between threads, search, pin/archive/delete, and start new chats.
 *
 * Pure UI. All state mutations go through ``threadApi`` /
 * ``projectApi`` -> existing Wave 193/194/196 backend endpoints.
 *
 * HXI design constraints honored:
 *   #1 system understands the human  -> sections sorted by salience
 *   #3 no emoji                       -> inline SVG glyphs only
 *   #4 motion communicates state      -> amber border + glow on active row
 *   #5 progressive disclosure         -> 240px <-> 56px collapse w/ localStorage
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useStore, type AD791aChatThreadView, type ProjectView } from '../../store/useStore';
import {
  createThread,
  deleteThread,
  listThreads,
  patchThread,
  searchThreads,
} from './threadApi';
import {
  createProject,
  deleteProject,
  listProjects,
  patchProject,
} from './projectApi';
import { ProjectRow } from './ProjectRow';
import { NewProjectModal } from './NewProjectModal';
import {
  ProjectContextMenu,
  ProjectDeleteConfirm,
  EditDescriptionModal,
} from './ProjectContextMenu';
import { MoveToProjectMenu } from './MoveToProjectMenu';
import { TIME_OF_LIFE_LABELS, timeOfLifeGroup, type TimeOfLifeGroup } from './threadGrouping';

const AMBER = '#f0b060';
const DIM = '#666680';
const TEXT = '#e0dcd4';
const BG = '#0a0a14';
const BG_HOVER = 'rgba(240, 176, 96, 0.08)';
const BG_ACTIVE = 'rgba(240, 176, 96, 0.12)';
const BORDER = 'rgba(240, 176, 96, 0.15)';

const SIDEBAR_WIDTH_EXPANDED = 240;
const SIDEBAR_WIDTH_COLLAPSED = 56;
const COLLAPSED_KEY = 'probos.sidebar.collapsed';
const SEARCH_DEBOUNCE_MS = 300; // matches useStore.ts:549 precedent
const MAX_PER_GROUP = 50;
// AD-793 (Wave 196): persisted Projects-section expansion state.
const PROJECTS_EXPANDED_KEY = 'probos.sidebar.projects.expanded';

export interface ThreadSidebarProps {
  /** When undefined, sidebar renders un-collapsed. */
  initialCollapsed?: boolean;
  /** Called when operator picks a thread; host re-mounts ProfileChatTab. */
  onThreadSelected: (threadId: string) => void;
  /** Current active thread (drives the active-row visual). */
  activeThreadId: string | null;
}

export function loadSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function persistSidebarCollapsed(v: boolean): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, v ? '1' : '0');
  } catch {
    // localStorage may be unavailable (private mode, quota); ignore.
  }
}

// AD-793 (Wave 196): per-project expansion state persistence.
function loadProjectsExpanded(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(PROJECTS_EXPANDED_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === 'object') {
      return parsed as Record<string, boolean>;
    }
    return {};
  } catch {
    return {};
  }
}

function persistProjectsExpanded(state: Record<string, boolean>): void {
  try {
    localStorage.setItem(PROJECTS_EXPANDED_KEY, JSON.stringify(state));
  } catch {
    // localStorage may be unavailable; ignore.
  }
}

// ---------- Inline SVG glyphs (HXI #3 — no emoji) ------------------------

function GlyphPlus({ color }: { color: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function GlyphChevron({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={AMBER} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" style={{ transform: collapsed ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}>
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

function GlyphPin({ filled }: { filled: boolean }) {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill={filled ? AMBER : 'none'} stroke={AMBER} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 17v5" />
      <path d="M5 9V4h14v5l-2 4H7l-2-4z" />
    </svg>
  );
}

function GlyphSearch() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={DIM} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.5" y2="16.5" />
    </svg>
  );
}

// ---------- Sub-components ----------------------------------------------

interface ThreadRowProps {
  thread: AD791aChatThreadView;
  active: boolean;
  collapsed: boolean;
  onSelect: (id: string) => void;
  onContextMenu: (id: string, x: number, y: number) => void;
  renaming: boolean;
  onRenameSubmit: (id: string, title: string) => void;
  onRenameCancel: () => void;
}

function ThreadRow({
  thread,
  active,
  collapsed,
  onSelect,
  onContextMenu,
  renaming,
  onRenameSubmit,
  onRenameCancel,
}: ThreadRowProps) {
  const [draft, setDraft] = useState<string>(thread.title);
  const inputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (renaming) {
      setDraft(thread.title);
      // Focus on next tick so the input exists.
      window.setTimeout(() => inputRef.current?.select(), 0);
    }
  }, [renaming, thread.title]);

  if (collapsed) {
    const letter = (thread.title || '?').trim().charAt(0).toUpperCase() || '?';
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={`Open thread ${thread.title}`}
        data-testid={`thread-row-${thread.id}`}
        onClick={() => onSelect(thread.id)}
        onContextMenu={(e) => {
          e.preventDefault();
          onContextMenu(thread.id, e.clientX, e.clientY);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') onSelect(thread.id);
        }}
        style={{
          width: 32,
          height: 32,
          margin: '4px auto',
          borderRadius: 4,
          background: active ? BG_ACTIVE : 'transparent',
          borderLeft: active ? `2px solid ${AMBER}` : '2px solid transparent',
          color: active ? AMBER : TEXT,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 12,
          cursor: 'pointer',
          boxShadow: active ? `0 0 4px ${AMBER}` : undefined,
        }}
      >
        {letter}
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Open thread ${thread.title}`}
      data-testid={`thread-row-${thread.id}`}
      onClick={() => !renaming && onSelect(thread.id)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(thread.id, e.clientX, e.clientY);
      }}
      onKeyDown={(e) => {
        if (e.key === 'F10' && e.shiftKey) {
          e.preventDefault();
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          onContextMenu(thread.id, rect.left + 8, rect.bottom);
        } else if (!renaming && (e.key === 'Enter' || e.key === ' ')) {
          onSelect(thread.id);
        }
      }}
      style={{
        padding: '6px 10px',
        margin: '1px 4px',
        borderRadius: 4,
        background: active ? BG_ACTIVE : 'transparent',
        borderLeft: active ? `3px solid ${AMBER}` : '3px solid transparent',
        color: active ? AMBER : TEXT,
        fontSize: 12,
        cursor: renaming ? 'text' : 'pointer',
        boxShadow: active ? `0 0 6px rgba(240, 176, 96, 0.25)` : undefined,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.background = BG_HOVER;
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent';
      }}
    >
      {thread.pinned && <GlyphPin filled />}
      {renaming ? (
        <input
          ref={inputRef}
          data-testid={`thread-rename-input-${thread.id}`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Enter') onRenameSubmit(thread.id, draft);
            else if (e.key === 'Escape') onRenameCancel();
          }}
          onBlur={() => onRenameSubmit(thread.id, draft)}
          style={{
            flex: 1,
            minWidth: 0,
            background: BG,
            border: `1px solid ${AMBER}`,
            color: TEXT,
            fontFamily: 'inherit',
            fontSize: 12,
            padding: '2px 4px',
            borderRadius: 2,
          }}
        />
      ) : (
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          {thread.title || 'Untitled thread'}
        </span>
      )}
    </div>
  );
}

interface SectionHeaderProps {
  label: string;
}

function SectionHeader({ label }: SectionHeaderProps) {
  return (
    <div
      style={{
        fontSize: 9,
        letterSpacing: 1.5,
        color: DIM,
        padding: '10px 12px 4px',
        textTransform: 'uppercase',
      }}
    >
      {label}
    </div>
  );
}

function GroupLabel({ label }: { label: string }) {
  return (
    <div style={{ fontSize: 9, color: DIM, padding: '6px 12px 2px', letterSpacing: 0.5 }}>
      {label}
    </div>
  );
}

interface ContextMenuState {
  threadId: string;
  x: number;
  y: number;
}

interface ContextMenuViewProps {
  state: ContextMenuState;
  thread: AD791aChatThreadView | undefined;
  onRename: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onMoveToProject: (x: number, y: number) => void;
  onClose: () => void;
}

function ContextMenuView({ state, thread, onRename, onTogglePin, onArchive, onDelete, onMoveToProject, onClose }: ContextMenuViewProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  // Boundary detection (best-effort under jsdom which returns 0 for innerWidth).
  const vw = typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1024;
  const vh = typeof window !== 'undefined' && window.innerHeight ? window.innerHeight : 768;
  const menuWidth = 180;
  const menuHeight = 140;
  const x = state.x + menuWidth > vw ? Math.max(0, vw - menuWidth - 4) : state.x;
  const y = state.y + menuHeight > vh ? Math.max(0, vh - menuHeight - 4) : state.y;

  const pinned = Boolean(thread?.pinned);
  return (
    <div
      ref={menuRef}
      data-testid="thread-context-menu"
      role="menu"
      style={{
        position: 'fixed',
        top: y,
        left: x,
        zIndex: 9999,
        background: BG,
        border: `1px solid ${BORDER}`,
        boxShadow: '0 4px 12px rgba(0,0,0,0.6)',
        minWidth: menuWidth,
        padding: 4,
        fontSize: 12,
        color: TEXT,
        fontFamily: 'inherit',
      }}
    >
      <MenuItem testid="ctx-rename" label="Rename" onClick={onRename} />
      <MenuItem testid="ctx-pin" label={pinned ? 'Unpin' : 'Pin'} onClick={onTogglePin} />
      <MenuItem
        testid="ctx-move-to-project"
        label="Move to project…"
        onClick={() => {
          // AD-793: position the submenu just to the right of this item.
          const rect = menuRef.current?.getBoundingClientRect();
          if (rect) onMoveToProject(rect.right + 4, rect.top);
          else onMoveToProject(state.x + menuWidth, state.y);
        }}
      />
      <MenuItem testid="ctx-archive" label="Archive" onClick={onArchive} />
      <MenuItem testid="ctx-delete" label="Delete" onClick={onDelete} danger />
    </div>
  );
}

function MenuItem({ label, onClick, testid, danger }: { label: string; onClick: () => void; testid: string; danger?: boolean }) {
  return (
    <div
      role="menuitem"
      tabIndex={0}
      data-testid={testid}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick();
      }}
      style={{
        padding: '6px 10px',
        cursor: 'pointer',
        color: danger ? '#d06868' : TEXT,
        borderRadius: 2,
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = BG_HOVER)}
      onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
    >
      {label}
    </div>
  );
}

interface DeleteConfirmProps {
  thread: AD791aChatThreadView;
  onConfirm: () => void;
  onCancel: () => void;
}

function DeleteConfirm({ thread, onConfirm, onCancel }: DeleteConfirmProps) {
  return (
    <div
      data-testid="thread-delete-confirm"
      role="dialog"
      aria-label="Confirm delete thread"
      style={{
        position: 'fixed',
        top: '40%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 10000,
        background: BG,
        border: `1px solid ${BORDER}`,
        padding: 16,
        minWidth: 320,
        color: TEXT,
        fontSize: 12,
        boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
      }}
    >
      <div style={{ marginBottom: 12 }}>
        Delete thread <strong>{thread.title || 'Untitled'}</strong>? Messages will be removed; episodes and agent memory are preserved.
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" data-testid="thread-delete-cancel" onClick={onCancel} style={btnStyle()}>Cancel</button>
        <button type="button" data-testid="thread-delete-confirm-btn" onClick={onConfirm} style={btnStyle({ danger: true })}>Delete</button>
      </div>
    </div>
  );
}

function btnStyle({ danger }: { danger?: boolean } = {}) {
  return {
    background: 'transparent',
    border: `1px solid ${danger ? '#d06868' : BORDER}`,
    color: danger ? '#d06868' : AMBER,
    fontFamily: 'inherit',
    fontSize: 11,
    padding: '4px 10px',
    borderRadius: 3,
    cursor: 'pointer',
    letterSpacing: 1,
  } as const;
}

// ---------- Yeo lookup (mirrors CompactApp pattern) ----------------------

function findYeoFromStore(): { id: string; callsign?: string } | null {
  const agents = useStore.getState().agents;
  for (const agent of agents.values()) {
    if (agent.callsign === 'Yeo') return agent;
  }
  return null;
}

// ---------- Main component ---------------------------------------------

export function ThreadSidebar({ initialCollapsed, onThreadSelected, activeThreadId }: ThreadSidebarProps) {
  const chatThreads = useStore((s) => s.chatThreads);
  const hydrateChatThreads = useStore((s) => s.hydrateChatThreads);
  const setChatThread = useStore((s) => s.setChatThread);
  const setActiveThread = useStore((s) => s.setActiveThread);
  const setThreadForAgent = useStore((s) => s.setThreadForAgent);
  const agents = useStore((s) => s.agents);
  // AD-793: projects slice.
  const projects = useStore((s) => s.projects);
  const hydrateProjects = useStore((s) => s.hydrateProjects);
  const setProject = useStore((s) => s.setProject);
  const removeProject = useStore((s) => s.removeProject);

  const [collapsed, setCollapsed] = useState<boolean>(() => initialCollapsed ?? loadSidebarCollapsed());
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<AD791aChatThreadView[] | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  // AD-793: project UI state.
  const [projectsExpanded, setProjectsExpanded] = useState<Record<string, boolean>>(
    () => loadProjectsExpanded(),
  );
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [projectContextMenu, setProjectContextMenu] = useState<{
    projectId: string;
    x: number;
    y: number;
  } | null>(null);
  const [projectDeletingId, setProjectDeletingId] = useState<string | null>(null);
  const [editDescriptionProjectId, setEditDescriptionProjectId] = useState<string | null>(null);
  const [moveSubmenu, setMoveSubmenu] = useState<{
    threadId: string;
    x: number;
    y: number;
  } | null>(null);

  // Hydrate once on mount. The store action absorbs the response.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      // AD-793: hydrate threads + projects in parallel.
      const [threads, projectList] = await Promise.all([
        listThreads({ includeArchived: false, limit: 100 }),
        listProjects({ includeArchived: false, limit: 100 }),
      ]);
      if (cancelled) return;
      if (threads.length > 0) hydrateChatThreads(threads);
      if (projectList.length > 0) hydrateProjects(projectList);
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrateChatThreads, hydrateProjects]);

  // Persist collapse preference.
  useEffect(() => {
    persistSidebarCollapsed(collapsed);
  }, [collapsed]);

  // Debounced search: 300ms (matches useStore.ts:549 precedent).
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    const handle = window.setTimeout(async () => {
      const results = await searchThreads(q);
      setSearchResults(results);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchQuery]);

  // ---------- Section partitions ----------
  const allThreads = useMemo(() => Array.from(chatThreads.values()), [chatThreads]);

  const pinned = useMemo(
    () =>
      allThreads
        .filter((t) => Boolean(t.pinned) && !t.archived)
        .sort((a, b) => b.last_active_at - a.last_active_at),
    [allThreads],
  );

  const recents = useMemo(
    () =>
      allThreads
        // AD-793 (Wave 196): exclude project-bound threads from Recents
        // (they appear under their project section instead). Pinned
        // overrides project grouping — pinned threads stay in Pinned
        // regardless of project_id (handled by the `pinned` slice above).
        .filter((t) => !t.pinned && !t.archived && t.project_id == null)
        .sort((a, b) => b.last_active_at - a.last_active_at),
    [allThreads],
  );

  // AD-793: derive threads-per-project map for the Projects section.
  const projectsList = useMemo(() => Array.from(projects.values()), [projects]);
  const threadsByProject = useMemo(() => {
    const map = new Map<string, AD791aChatThreadView[]>();
    for (const t of allThreads) {
      if (t.archived || t.pinned) continue; // pinned go to Pinned section
      const pid = t.project_id;
      if (!pid) continue;
      const bucket = map.get(pid) ?? [];
      bucket.push(t);
      map.set(pid, bucket);
    }
    // Sort each bucket by last_active_at desc.
    for (const bucket of map.values()) {
      bucket.sort((a, b) => b.last_active_at - a.last_active_at);
    }
    return map;
  }, [allThreads]);

  // Persist projects-expanded changes.
  useEffect(() => {
    persistProjectsExpanded(projectsExpanded);
  }, [projectsExpanded]);

  const groupedRecents = useMemo(() => {
    const now = Date.now();
    const groups: Record<TimeOfLifeGroup, AD791aChatThreadView[]> = { today: [], yesterday: [], earlier: [] };
    for (const t of recents) {
      const g = timeOfLifeGroup(t.last_active_at, now);
      if (groups[g].length < MAX_PER_GROUP) groups[g].push(t);
    }
    return groups;
  }, [recents]);

  // ---------- Handlers ----------
  const handleSelect = useCallback(
    (id: string) => {
      setActiveThread(id);
      onThreadSelected(id);
    },
    [onThreadSelected, setActiveThread],
  );

  const handleNewChat = useCallback(async () => {
    const yeo = findYeoFromStore();
    if (!yeo) return;
    const thread = await createThread({
      title: yeo.callsign ?? 'New thread',
      participants: [yeo.id],
    });
    if (!thread) return;
    setChatThread(thread);
    setActiveThread(thread.id);
    setThreadForAgent(yeo.id, thread.id);
    onThreadSelected(thread.id);
  }, [onThreadSelected, setActiveThread, setChatThread, setThreadForAgent]);

  const handleContextMenu = useCallback((threadId: string, x: number, y: number) => {
    setContextMenu({ threadId, x, y });
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const handleRenameStart = useCallback(() => {
    if (!contextMenu) return;
    setRenamingId(contextMenu.threadId);
    setContextMenu(null);
  }, [contextMenu]);

  const handleRenameSubmit = useCallback(
    async (id: string, title: string) => {
      const trimmed = title.trim();
      setRenamingId(null);
      if (!trimmed) return;
      const current = chatThreads.get(id);
      if (current && current.title === trimmed) return;
      // Optimistic update.
      if (current) {
        setChatThread({ ...current, title: trimmed });
      }
      const updated = await patchThread(id, { title: trimmed, title_locked: true });
      if (updated) setChatThread(updated);
    },
    [chatThreads, setChatThread],
  );

  const handleRenameCancel = useCallback(() => setRenamingId(null), []);

  const handleTogglePin = useCallback(async () => {
    if (!contextMenu) return;
    const current = chatThreads.get(contextMenu.threadId);
    if (!current) {
      setContextMenu(null);
      return;
    }
    const nextPinned = !current.pinned;
    // Optimistic update.
    setChatThread({ ...current, pinned: nextPinned });
    setContextMenu(null);
    const updated = await patchThread(contextMenu.threadId, { pinned: nextPinned });
    if (updated) setChatThread(updated);
  }, [chatThreads, contextMenu, setChatThread]);

  const handleArchive = useCallback(async () => {
    if (!contextMenu) return;
    const current = chatThreads.get(contextMenu.threadId);
    setContextMenu(null);
    if (!current) return;
    // Optimistic: mark archived so the row disappears from the sidebar.
    setChatThread({ ...current, archived: true });
    await patchThread(current.id, { archived: true });
  }, [chatThreads, contextMenu, setChatThread]);

  const handleDeleteRequest = useCallback(() => {
    if (!contextMenu) return;
    setDeletingId(contextMenu.threadId);
    setContextMenu(null);
  }, [contextMenu]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deletingId) return;
    const id = deletingId;
    setDeletingId(null);
    const ok = await deleteThread(id);
    if (ok) {
      // Remove from store map so the sidebar updates immediately.
      const next = new Map(useStore.getState().chatThreads);
      next.delete(id);
      useStore.setState({ chatThreads: next });
      // If the deleted thread was active, clear active.
      if (useStore.getState().activeThreadId === id) {
        useStore.getState().setActiveThread(null);
      }
    }
  }, [deletingId]);

  const handleDeleteCancel = useCallback(() => setDeletingId(null), []);

  // AD-793 (Wave 196): project handlers.
  const toggleProjectExpanded = useCallback((projectId: string) => {
    setProjectsExpanded((prev) => ({ ...prev, [projectId]: !prev[projectId] }));
  }, []);

  const handleProjectContextMenu = useCallback(
    (projectId: string, x: number, y: number) => {
      setProjectContextMenu({ projectId, x, y });
    },
    [],
  );

  const handleNewProjectSubmit = useCallback(
    async (name: string, description: string) => {
      const project = await createProject({ name, description });
      if (project) {
        setProject(project);
        // Auto-expand the newly-created project so the operator sees it.
        setProjectsExpanded((prev) => ({ ...prev, [project.id]: true }));
      }
      setNewProjectOpen(false);
    },
    [setProject],
  );

  const handleProjectRename = useCallback(() => {
    if (!projectContextMenu) return;
    const current = projects.get(projectContextMenu.projectId);
    if (!current) {
      setProjectContextMenu(null);
      return;
    }
    // Reuse prompt() for v1 simple rename (matches the simple Rename in
    // ThreadRow's context menu before the inline-edit affordance).
    const next = window.prompt('Project name', current.name);
    setProjectContextMenu(null);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === current.name) return;
    void (async () => {
      const updated = await patchProject(current.id, { name: trimmed });
      if (updated) setProject(updated);
    })();
  }, [projectContextMenu, projects, setProject]);

  const handleProjectEditDescription = useCallback(() => {
    if (!projectContextMenu) return;
    setEditDescriptionProjectId(projectContextMenu.projectId);
    setProjectContextMenu(null);
  }, [projectContextMenu]);

  const handleProjectEditDescriptionSubmit = useCallback(
    (description: string) => {
      const id = editDescriptionProjectId;
      setEditDescriptionProjectId(null);
      if (!id) return;
      void (async () => {
        const updated = await patchProject(id, { description });
        if (updated) setProject(updated);
      })();
    },
    [editDescriptionProjectId, setProject],
  );

  const handleProjectArchive = useCallback(() => {
    if (!projectContextMenu) return;
    const id = projectContextMenu.projectId;
    setProjectContextMenu(null);
    void (async () => {
      const updated = await patchProject(id, { archived: true });
      if (updated) {
        // Archived → drop from the in-memory map so the section refreshes.
        removeProject(id);
      }
    })();
  }, [projectContextMenu, removeProject]);

  const handleProjectDeleteRequest = useCallback(() => {
    if (!projectContextMenu) return;
    setProjectDeletingId(projectContextMenu.projectId);
    setProjectContextMenu(null);
  }, [projectContextMenu]);

  const handleProjectDeleteConfirm = useCallback(
    (cascade: boolean) => {
      const id = projectDeletingId;
      setProjectDeletingId(null);
      if (!id) return;
      void (async () => {
        const result = await deleteProject(id, { cascade });
        if (result?.deleted) {
          removeProject(id);
          if (cascade) {
            // Remove contained threads from the store.
            const next = new Map(useStore.getState().chatThreads);
            for (const [tid, t] of next.entries()) {
              if (t.project_id === id) next.delete(tid);
            }
            useStore.setState({ chatThreads: next });
          } else {
            // Unparent contained threads in the store.
            const next = new Map(useStore.getState().chatThreads);
            for (const [tid, t] of next.entries()) {
              if (t.project_id === id) {
                next.set(tid, { ...t, project_id: null });
              }
            }
            useStore.setState({ chatThreads: next });
          }
        }
      })();
    },
    [projectDeletingId, removeProject],
  );

  const handleMoveToProject = useCallback((x: number, y: number) => {
    if (!contextMenu) return;
    setMoveSubmenu({ threadId: contextMenu.threadId, x, y });
    setContextMenu(null);
  }, [contextMenu]);

  const handleMoveToProjectPick = useCallback(
    async (newProjectId: string | null) => {
      if (!moveSubmenu) return;
      const id = moveSubmenu.threadId;
      const current = chatThreads.get(id);
      setMoveSubmenu(null);
      if (!current) return;
      // Optimistic store update.
      setChatThread({ ...current, project_id: newProjectId });
      const updated = await patchThread(id, { project_id: newProjectId });
      if (updated) setChatThread(updated);
    },
    [chatThreads, moveSubmenu, setChatThread],
  );

  // ---------- Render helpers ----------
  const yeoLoaded = useMemo(() => {
    for (const a of agents.values()) {
      if (a.callsign === 'Yeo') return true;
    }
    return false;
  }, [agents]);

  const ctxThread = contextMenu ? chatThreads.get(contextMenu.threadId) : undefined;
  const delThread = deletingId ? chatThreads.get(deletingId) : undefined;

  if (collapsed) {
    return (
      <div
        data-testid="thread-sidebar"
        data-collapsed="true"
        style={{
          width: SIDEBAR_WIDTH_COLLAPSED,
          flex: `0 0 ${SIDEBAR_WIDTH_COLLAPSED}px`,
          height: '100%',
          background: BG,
          borderRight: `1px solid ${BORDER}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <div style={{ flex: '0 0 auto', padding: 6, borderBottom: `1px solid ${BORDER}`, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
          <button
            type="button"
            data-testid="sidebar-collapse-toggle"
            aria-label="Expand sidebar"
            onClick={() => setCollapsed(false)}
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 4 }}
          >
            <GlyphChevron collapsed />
          </button>
          <button
            type="button"
            data-testid="sidebar-new-chat"
            aria-label="New chat"
            disabled={!yeoLoaded}
            title={yeoLoaded ? 'New chat' : 'Loading agents…'}
            onClick={() => void handleNewChat()}
            style={{
              background: 'transparent',
              border: `1px solid ${BORDER}`,
              padding: 6,
              borderRadius: 4,
              cursor: yeoLoaded ? 'pointer' : 'not-allowed',
              opacity: yeoLoaded ? 1 : 0.4,
            }}
          >
            <GlyphPlus color={AMBER} />
          </button>
        </div>
        <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: 4 }}>
          {pinned.map((t) => (
            <ThreadRow
              key={t.id}
              thread={t}
              active={t.id === activeThreadId}
              collapsed
              onSelect={handleSelect}
              onContextMenu={handleContextMenu}
              renaming={false}
              onRenameSubmit={handleRenameSubmit}
              onRenameCancel={handleRenameCancel}
            />
          ))}
        </div>
        {contextMenu && <ContextMenuView state={contextMenu} thread={ctxThread} onRename={handleRenameStart} onTogglePin={handleTogglePin} onArchive={handleArchive} onDelete={handleDeleteRequest} onMoveToProject={handleMoveToProject} onClose={closeContextMenu} />}
        {delThread && <DeleteConfirm thread={delThread} onConfirm={handleDeleteConfirm} onCancel={handleDeleteCancel} />}
      </div>
    );
  }

  return (
    <div
      data-testid="thread-sidebar"
      data-collapsed="false"
      style={{
        width: SIDEBAR_WIDTH_EXPANDED,
        flex: `0 0 ${SIDEBAR_WIDTH_EXPANDED}px`,
        height: '100%',
        background: BG,
        borderRight: `1px solid ${BORDER}`,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {/* Header: collapse toggle + new chat. */}
      <div style={{ flex: '0 0 auto', padding: '8px 10px', borderBottom: `1px solid ${BORDER}`, display: 'flex', alignItems: 'center', gap: 6 }}>
        <button
          type="button"
          data-testid="sidebar-collapse-toggle"
          aria-label="Collapse sidebar"
          onClick={() => setCollapsed(true)}
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 4 }}
        >
          <GlyphChevron collapsed={false} />
        </button>
        <span style={{ fontSize: 10, letterSpacing: 1.5, color: AMBER, flex: 1 }}>THREADS</span>
        <button
          type="button"
          data-testid="sidebar-new-chat"
          aria-label="New chat"
          disabled={!yeoLoaded}
          title={yeoLoaded ? 'New chat' : 'Loading agents…'}
          onClick={() => void handleNewChat()}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            background: 'transparent',
            border: `1px solid ${BORDER}`,
            color: AMBER,
            fontFamily: 'inherit',
            fontSize: 10,
            letterSpacing: 1.2,
            padding: '3px 8px',
            borderRadius: 3,
            cursor: yeoLoaded ? 'pointer' : 'not-allowed',
            opacity: yeoLoaded ? 1 : 0.4,
          }}
        >
          <GlyphPlus color={AMBER} />
          <span>NEW</span>
        </button>
      </div>

      {/* Search */}
      <div style={{ flex: '0 0 auto', padding: '6px 10px', borderBottom: `1px solid ${BORDER}`, display: 'flex', alignItems: 'center', gap: 6 }}>
        <GlyphSearch />
        <input
          type="text"
          data-testid="sidebar-search-input"
          aria-label="Search threads"
          placeholder="Search threads"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: TEXT,
            fontFamily: 'inherit',
            fontSize: 12,
          }}
        />
      </div>

      {/* Sections / search results */}
      <div style={{ flex: '1 1 auto', overflowY: 'auto' }} data-testid="sidebar-body">
        {searchResults !== null ? (
          <div data-testid="sidebar-search-results">
            <SectionHeader label={`Search: ${searchQuery}`} />
            {searchResults.length === 0 ? (
              <div style={{ padding: '6px 12px', fontSize: 11, color: DIM }}>{`No threads match '${searchQuery}'.`}</div>
            ) : (
              searchResults.map((t) => (
                <ThreadRow
                  key={t.id}
                  thread={t}
                  active={t.id === activeThreadId}
                  collapsed={false}
                  onSelect={handleSelect}
                  onContextMenu={handleContextMenu}
                  renaming={renamingId === t.id}
                  onRenameSubmit={handleRenameSubmit}
                  onRenameCancel={handleRenameCancel}
                />
              ))
            )}
          </div>
        ) : (
          <>
            <section data-testid="sidebar-section-pinned">
              <SectionHeader label="Pinned" />
              {pinned.length === 0 ? (
                <div style={{ padding: '4px 12px', fontSize: 11, color: DIM }}>No pinned threads yet</div>
              ) : (
                pinned.map((t) => (
                  <ThreadRow
                    key={t.id}
                    thread={t}
                    active={t.id === activeThreadId}
                    collapsed={false}
                    onSelect={handleSelect}
                    onContextMenu={handleContextMenu}
                    renaming={renamingId === t.id}
                    onRenameSubmit={handleRenameSubmit}
                    onRenameCancel={handleRenameCancel}
                  />
                ))
              )}
            </section>
            <section data-testid="sidebar-section-projects">
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  paddingRight: 8,
                }}
              >
                <SectionHeader label="Projects" />
                <button
                  type="button"
                  data-testid="sidebar-new-project"
                  aria-label="New project"
                  title="New project"
                  onClick={() => setNewProjectOpen(true)}
                  style={{
                    background: 'transparent',
                    border: `1px solid ${BORDER}`,
                    color: AMBER,
                    padding: '2px 6px',
                    borderRadius: 3,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <GlyphPlus color={AMBER} />
                </button>
              </div>
              {projectsList.length === 0 ? (
                <div
                  data-testid="sidebar-projects-empty"
                  style={{ padding: '4px 12px', fontSize: 11, color: DIM }}
                >
                  No projects yet
                </div>
              ) : (
                projectsList.map((p) => {
                  const threadsInProject = threadsByProject.get(p.id) ?? [];
                  const expanded = Boolean(projectsExpanded[p.id]);
                  return (
                    <div key={p.id} data-testid={`project-block-${p.id}`}>
                      <ProjectRow
                        projectId={p.id}
                        name={p.name}
                        threadCount={threadsInProject.length}
                        expanded={expanded}
                        onToggle={toggleProjectExpanded}
                        onContextMenu={handleProjectContextMenu}
                      />
                      {expanded &&
                        (threadsInProject.length === 0 ? (
                          <div
                            data-testid={`project-empty-${p.id}`}
                            style={{
                              padding: '2px 12px 4px 28px',
                              fontSize: 11,
                              color: DIM,
                            }}
                          >
                            No threads yet
                          </div>
                        ) : (
                          <div style={{ paddingLeft: 12 }}>
                            {threadsInProject.map((t) => (
                              <ThreadRow
                                key={t.id}
                                thread={t}
                                active={t.id === activeThreadId}
                                collapsed={false}
                                onSelect={handleSelect}
                                onContextMenu={handleContextMenu}
                                renaming={renamingId === t.id}
                                onRenameSubmit={handleRenameSubmit}
                                onRenameCancel={handleRenameCancel}
                              />
                            ))}
                          </div>
                        ))}
                    </div>
                  );
                })
              )}
            </section>
            <section data-testid="sidebar-section-recents">
              <SectionHeader label="Recents" />
              {(['today', 'yesterday', 'earlier'] as TimeOfLifeGroup[]).map((g) =>
                groupedRecents[g].length === 0 ? null : (
                  <div key={g} data-testid={`recents-group-${g}`}>
                    <GroupLabel label={TIME_OF_LIFE_LABELS[g]} />
                    {groupedRecents[g].map((t) => (
                      <ThreadRow
                        key={t.id}
                        thread={t}
                        active={t.id === activeThreadId}
                        collapsed={false}
                        onSelect={handleSelect}
                        onContextMenu={handleContextMenu}
                        renaming={renamingId === t.id}
                        onRenameSubmit={handleRenameSubmit}
                        onRenameCancel={handleRenameCancel}
                      />
                    ))}
                  </div>
                ),
              )}
              {recents.length === 0 && (
                <div style={{ padding: '4px 12px', fontSize: 11, color: DIM }}>No recent threads</div>
              )}
            </section>
          </>
        )}
      </div>

      {contextMenu && (
        <ContextMenuView
          state={contextMenu}
          thread={ctxThread}
          onRename={handleRenameStart}
          onTogglePin={handleTogglePin}
          onArchive={handleArchive}
          onDelete={handleDeleteRequest}
          onMoveToProject={handleMoveToProject}
          onClose={closeContextMenu}
        />
      )}
      {delThread && <DeleteConfirm thread={delThread} onConfirm={handleDeleteConfirm} onCancel={handleDeleteCancel} />}
      {/* AD-793 (Wave 196): project UI overlays. */}
      {newProjectOpen && (
        <NewProjectModal
          onSubmit={handleNewProjectSubmit}
          onCancel={() => setNewProjectOpen(false)}
        />
      )}
      {projectContextMenu && (
        <ProjectContextMenu
          projectId={projectContextMenu.projectId}
          x={projectContextMenu.x}
          y={projectContextMenu.y}
          onRename={handleProjectRename}
          onEditDescription={handleProjectEditDescription}
          onArchive={handleProjectArchive}
          onDelete={handleProjectDeleteRequest}
          onClose={() => setProjectContextMenu(null)}
        />
      )}
      {projectDeletingId && (() => {
        const p = projects.get(projectDeletingId);
        if (!p) return null;
        const count = (threadsByProject.get(projectDeletingId) ?? []).length;
        return (
          <ProjectDeleteConfirm
            projectName={p.name}
            threadCount={count}
            onConfirm={handleProjectDeleteConfirm}
            onCancel={() => setProjectDeletingId(null)}
          />
        );
      })()}
      {editDescriptionProjectId && (() => {
        const p = projects.get(editDescriptionProjectId);
        if (!p) return null;
        return (
          <EditDescriptionModal
            projectName={p.name}
            initialDescription={p.description}
            onSubmit={handleProjectEditDescriptionSubmit}
            onCancel={() => setEditDescriptionProjectId(null)}
          />
        );
      })()}
      {moveSubmenu && (
        <MoveToProjectMenu
          threadId={moveSubmenu.threadId}
          x={moveSubmenu.x}
          y={moveSubmenu.y}
          projects={projectsList}
          currentProjectId={chatThreads.get(moveSubmenu.threadId)?.project_id ?? null}
          onPick={(pid) => void handleMoveToProjectPick(pid)}
          onClose={() => setMoveSubmenu(null)}
        />
      )}
    </div>
  );
}

export default ThreadSidebar;
