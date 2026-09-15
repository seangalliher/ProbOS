/**
 * AD-797 (Wave 197): top-level Artifacts drawer.
 *
 * Mounted as the third flex child of CompactApp's chat row:
 *   [ThreadSidebar | ProfileChatTab | ArtifactDrawer]
 *
 * 360px expanded / 28px rail collapsed. localStorage persists the
 * collapsed state under ``probos.artifactDrawer.collapsed``. Narrow
 * hosts present a rail unless the drawer is explicitly opened.
 *
 * Subscribes to ``useStore.activeThreadId``: on change, fetches the
 * thread's artifacts and replaces drawer state. If the list is empty
 * AND no project pins surface, the drawer auto-collapses to rail
 * unless the Captain manually expanded it.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { useStore } from '../../store/useStore';
import { ArtifactList } from './ArtifactList';
import { ArtifactViewer } from './ArtifactViewer';
import { fetchThreadArtifacts } from './artifactApi';
import type { ArtifactOpenRequest } from './ArtifactCard';

const AMBER = '#f0b060';
const DIM = '#888899';
const STORAGE_KEY = 'probos.artifactDrawer.collapsed';

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

export interface ArtifactDrawerProps {
  /** Optional override for tests/storybook. */
  initialCollapsed?: boolean;
  threadId?: string | null;
  openRequest?: ArtifactOpenRequest | null;
  onOpenConsumed?: (request: ArtifactOpenRequest) => void;
  conversationKey?: object;
}

export function ArtifactDrawer(props: ArtifactDrawerProps): ReactElement {
  const globalThreadId = useStore((s) => s.activeThreadId);
  const activeThreadId = props.threadId === undefined ? globalThreadId : props.threadId;
  const chatThreads = useStore((s) => s.chatThreads);
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const selectedId = useStore((s) => s.selectedArtifactId);
  const collapsed = useStore((s) => s.artifactDrawerCollapsed);
  const hydrateArtifacts = useStore((s) => s.hydrateArtifacts);
  const selectArtifact = useStore((s) => s.selectArtifact);
  const setCollapsed = useStore((s) => s.setArtifactDrawerCollapsed);

  const userToggled = useRef(props.initialCollapsed !== undefined);
  const drawerRef = useRef<HTMLElement>(null);
  const expandRef = useRef<HTMLButtonElement>(null);
  const collapseRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const focusExpanded = useRef(false);
  const openerRef = useRef<ArtifactOpenRequest | null>(null);
  const consumedRequests = useRef(new WeakSet<ArtifactOpenRequest>());
  const presentationOwner = useRef({ activeThreadId, conversationKey: props.conversationKey });
  const [hostWidth, setHostWidth] = useState<number | null>(null);
  const [explicitExpanded, setExplicitExpanded] = useState(props.initialCollapsed === false);
  const compact = hostWidth !== null && hostWidth < 660;
  const effectiveCollapsed = collapsed || (!activeThreadId && !userToggled.current) || (compact && !explicitExpanded);
  const overlay = compact && !effectiveCollapsed;

  useLayoutEffect(() => {
    if (presentationOwner.current.activeThreadId === activeThreadId
      && presentationOwner.current.conversationKey === props.conversationKey) return;
    presentationOwner.current = { activeThreadId, conversationKey: props.conversationKey };
    openerRef.current = null;
    restoreFocus.current = false;
    focusExpanded.current = false;
    setExplicitExpanded(false);
  }, [activeThreadId, props.conversationKey]);

  useLayoutEffect(() => {
    const parent = drawerRef.current?.parentElement;
    if (!parent) return;
    let previousWidth: number | null = null;
    const measure = (width: number): void => {
      if (!Number.isFinite(width) || width <= 0) return;
      if (previousWidth !== null && previousWidth >= 660 && width < 660) {
        restoreFocus.current = !!drawerRef.current?.contains(document.activeElement);
        openerRef.current = null;
        setExplicitExpanded(false);
      }
      previousWidth = width;
      setHostWidth(width);
    };
    measure(parent.clientWidth);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
      const entry = entries.find(value => value.target === parent);
      if (entry) measure(entry.contentRect.width);
    });
    observer?.observe(parent);
    const resize = (): void => measure(parent.clientWidth);
    window.addEventListener('resize', resize);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', resize);
    };
  }, []);

  useLayoutEffect(() => {
    if (effectiveCollapsed && restoreFocus.current) {
      const request = openerRef.current;
      const opener = request?.opener;
      if (request?.threadId === activeThreadId && opener?.isConnected
        && opener.dataset.artifactThreadId === activeThreadId
        && opener.dataset.artifactId === request.artifactId && !opener.disabled) {
        opener.focus();
      } else {
        expandRef.current?.focus();
      }
      openerRef.current = null;
      restoreFocus.current = false;
    } else if (!effectiveCollapsed && focusExpanded.current) {
      collapseRef.current?.focus();
      focusExpanded.current = false;
    }
  });

  // Hydrate persisted collapsed state on mount.
  useEffect(() => {
    const persisted = loadCollapsedFromStorage();
    if (props.initialCollapsed !== undefined) {
      setCollapsed(props.initialCollapsed);
    } else if (persisted !== null) {
      userToggled.current = true;
      setCollapsed(persisted);
    }
    // We intentionally run this only on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch on active thread change.
  useEffect(() => {
    if (!activeThreadId) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchThreadArtifacts(activeThreadId);
        if (cancelled) return;
        hydrateArtifacts(activeThreadId, list);
        // Auto-collapse to rail when empty AND Captain hasn't manually
        // expanded. If the operator already toggled, respect it.
        if (!userToggled.current && list.length === 0) {
          setCollapsed(true);
        }
      } catch {
        // honest-degrade — drawer stays in its current state.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId]);

  const artifacts = useMemo(
    () => (activeThreadId ? artifactsByThread.get(activeThreadId) ?? [] : []),
    [artifactsByThread, activeThreadId],
  );

  useLayoutEffect(() => {
    const request = props.openRequest;
    if (!request || consumedRequests.current.has(request)) return;
    consumedRequests.current.add(request);
    if (request.threadId === activeThreadId && artifacts.some(artifact =>
      artifact.id === request.artifactId && artifact.thread_id === activeThreadId)) {
      openerRef.current = request;
      userToggled.current = true;
      restoreFocus.current = false;
      focusExpanded.current = true;
      setExplicitExpanded(true);
      selectArtifact(request.artifactId);
      setCollapsed(false);
      collapseRef.current?.focus();
    }
    props.onOpenConsumed?.(request);
  }, [props.openRequest, props.onOpenConsumed, activeThreadId, artifacts, selectArtifact, setCollapsed]);

  // AD-1074c: auto-open a freshly-produced document. When the active thread's
  // artifact list GROWS in place (a live arrival - not a thread switch or the
  // initial load), select the newest + uncollapse so the document opens in the
  // split-view embedded viewer (the Cowork experience).
  const autoOpenRef = useRef<{ thread: string | null; count: number }>({ thread: null, count: -1 });
  useEffect(() => {
    const t = activeThreadId ?? null;
    const count = artifacts.length;
    const prev = autoOpenRef.current;
    autoOpenRef.current = { thread: t, count };
    if (prev.thread !== t || prev.count < 0) return; // thread switch / first load
    if (count > prev.count) {
      const newest = artifacts.reduce(
        (a, b) => (b.created_at >= a.created_at ? b : a), artifacts[0],
      );
      if (newest) {
        selectArtifact(newest.id);
        setCollapsed(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifacts, activeThreadId]);

  const selectedArtifact = useMemo(
    () => artifacts.find((a) => a.id === selectedId) ?? artifacts[0] ?? null,
    [artifacts, selectedId],
  );

  // Versions of the currently selected artifact (by name + thread).
  const versions = useMemo(() => {
    if (!selectedArtifact) return [];
    return artifacts.filter(
      (a) => a.name === selectedArtifact.name &&
             a.thread_id === selectedArtifact.thread_id,
    );
  }, [artifacts, selectedArtifact]);

  const projectIdForPinning = useMemo(() => {
    if (!activeThreadId) return null;
    const t = chatThreads.get(activeThreadId);
    return t?.project_id ?? null;
  }, [activeThreadId, chatThreads]);

  const handleToggle = useCallback(() => {
    userToggled.current = true;
    setExplicitExpanded(effectiveCollapsed);
    restoreFocus.current = !effectiveCollapsed;
    focusExpanded.current = effectiveCollapsed;
    if (effectiveCollapsed) openerRef.current = null;
    setCollapsed(!effectiveCollapsed);
  }, [effectiveCollapsed, setCollapsed]);

  const handleSelect = useCallback(
    (id: string) => {
      selectArtifact(id);
      setExplicitExpanded(true);
      if (effectiveCollapsed) {
        userToggled.current = true;
        setCollapsed(false);
      }
    },
    [effectiveCollapsed, selectArtifact, setCollapsed],
  );

  if (effectiveCollapsed) {
    return (
      <aside
        ref={drawerRef}
        data-testid="artifact-drawer"
        data-thread-id={activeThreadId ?? undefined}
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
          ref={expandRef}
          type="button" onClick={handleToggle}
          data-testid="artifact-drawer-expand"
          aria-label="Expand artifacts"
          aria-expanded={false}
          title={`Artifacts (${artifacts.length})`}
          style={{
            background: 'transparent', border: 'none', color: AMBER,
            cursor: 'pointer', padding: 4,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-label="open artifacts">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
        <span style={{
          writingMode: 'vertical-rl', textOrientation: 'mixed',
          fontSize: 9, letterSpacing: 1.5, color: AMBER, marginTop: 8,
        }}>ARTIFACTS</span>
        {artifacts.length > 0 && (
          <span
            data-testid="artifact-drawer-count"
            style={{
              fontSize: 9, color: AMBER, marginTop: 8,
              border: '1px solid rgba(240, 176, 96, 0.3)',
              borderRadius: 3, padding: '0 4px',
            }}
          >
            {artifacts.length}
          </span>
        )}
      </aside>
    );
  }

  return (
    <aside
      ref={drawerRef}
      data-testid="artifact-drawer"
      data-thread-id={activeThreadId ?? undefined}
      data-collapsed="false"
      data-overlay={overlay ? 'true' : 'false'}
      style={{
        flex: overlay ? '0 0 28px' : '0 0 360px', width: overlay ? 28 : 360,
        minWidth: 0, minHeight: 0, position: 'relative',
        display: 'flex', flexDirection: 'column',
      }}
    >
      <div
        role={overlay ? 'dialog' : undefined}
        aria-label={overlay ? 'Artifacts' : undefined}
        onKeyDown={event => {
          if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            handleToggle();
          }
        }}
        style={{
        flex: '1 1 auto', minWidth: 0, minHeight: 0,
        width: overlay ? Math.min(360, hostWidth ?? 28) : '100%',
        boxSizing: 'border-box', overflow: 'auto',
        position: overlay ? 'absolute' : 'relative',
        ...(overlay ? { top: 0, bottom: 0, right: 0, zIndex: 10 } : {}),
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
        <span style={{
          flex: '1 1 auto', fontSize: 11, letterSpacing: 1.5, color: AMBER,
          fontWeight: 600,
        }}>ARTIFACTS</span>
        {artifacts.length > 0 && (
          <span style={{
            fontSize: 10, color: AMBER,
            border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 3, padding: '0 4px',
          }}>{artifacts.length}</span>
        )}
        <button
          ref={collapseRef}
          type="button" onClick={handleToggle}
          data-testid="artifact-drawer-collapse"
          aria-label="Collapse artifacts"
          aria-expanded={true}
          title="Collapse drawer"
          style={{
            background: 'transparent', border: 'none', color: AMBER,
            cursor: 'pointer', padding: 2, width: 32, height: 32, flexShrink: 0,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-label="collapse">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>
      <div style={{ flex: '0 0 auto', maxHeight: '40%', overflowY: 'auto' }}>
        <ArtifactList
          artifacts={artifacts}
          selectedId={selectedArtifact?.id ?? null}
          onSelect={handleSelect}
        />
      </div>
      {selectedArtifact ? (
        <ArtifactViewer
          artifact={selectedArtifact}
          versions={versions}
          onSelectVersion={(id) => selectArtifact(id)}
          projectIdForPinning={projectIdForPinning}
        />
      ) : (
        <div
          style={{
            flex: '1 1 auto', display: 'flex', alignItems: 'center',
            justifyContent: 'center', color: DIM, fontSize: 11,
            padding: 12, textAlign: 'center',
            borderTop: '1px solid rgba(240, 176, 96, 0.15)',
          }}
        >
          Select an artifact to preview.
        </div>
      )}
      </div>
    </aside>
  );
}
