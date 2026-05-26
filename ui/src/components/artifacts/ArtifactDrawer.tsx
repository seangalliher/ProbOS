/**
 * AD-797 (Wave 197): top-level Artifacts drawer.
 *
 * Mounted as the third flex child of CompactApp's chat row:
 *   [ThreadSidebar | ProfileChatTab | ArtifactDrawer]
 *
 * 360px expanded / 28px rail collapsed. localStorage persists the
 * collapsed state under ``probos.artifactDrawer.collapsed``. Viewport
 * <1024px defaults to rail (responsive proper → AD-797j).
 *
 * Subscribes to ``useStore.activeThreadId``: on change, fetches the
 * thread's artifacts and replaces drawer state. If the list is empty
 * AND no project pins surface, the drawer auto-collapses to rail
 * unless the Captain manually expanded it.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useStore } from '../../store/useStore';
import { ArtifactList } from './ArtifactList';
import { ArtifactViewer } from './ArtifactViewer';
import { fetchThreadArtifacts } from './artifactApi';

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
}

export function ArtifactDrawer(props: ArtifactDrawerProps) {
  const activeThreadId = useStore((s) => s.activeThreadId);
  const chatThreads = useStore((s) => s.chatThreads);
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const selectedId = useStore((s) => s.selectedArtifactId);
  const collapsed = useStore((s) => s.artifactDrawerCollapsed);
  const hydrateArtifacts = useStore((s) => s.hydrateArtifacts);
  const selectArtifact = useStore((s) => s.selectArtifact);
  const setCollapsed = useStore((s) => s.setArtifactDrawerCollapsed);

  const [userToggled, setUserToggled] = useState<boolean>(false);

  // Hydrate persisted collapsed state on mount.
  useEffect(() => {
    const persisted = loadCollapsedFromStorage();
    let initial: boolean;
    if (props.initialCollapsed !== undefined) {
      initial = props.initialCollapsed;
    } else if (persisted !== null) {
      initial = persisted;
      setUserToggled(true);
    } else if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      // Viewport-based default per architect N2.
      initial = true;
    } else {
      initial = false;
    }
    setCollapsed(initial);
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
        if (!userToggled && list.length === 0) {
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
    setUserToggled(true);
    setCollapsed(!collapsed);
  }, [collapsed, setCollapsed]);

  const handleSelect = useCallback(
    (id: string) => {
      selectArtifact(id);
      if (collapsed) {
        setUserToggled(true);
        setCollapsed(false);
      }
    },
    [selectArtifact, collapsed, setCollapsed],
  );

  if (collapsed) {
    return (
      <aside
        data-testid="artifact-drawer"
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
          data-testid="artifact-drawer-expand"
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
      data-testid="artifact-drawer"
      data-collapsed="false"
      style={{
        flex: '0 0 360px', width: 360,
        background: 'rgba(10, 10, 18, 0.92)',
        borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
        display: 'flex', flexDirection: 'column', position: 'relative',
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
          type="button" onClick={handleToggle}
          data-testid="artifact-drawer-collapse"
          title="Collapse drawer"
          style={{
            background: 'transparent', border: 'none', color: AMBER,
            cursor: 'pointer', padding: 2,
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
    </aside>
  );
}
