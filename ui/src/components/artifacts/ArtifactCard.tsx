/**
 * AD-797 (Wave 197): inline card rendered in place of stub lines
 * inside ProfileChatTab message bodies.
 *
 * The agent's body contains stub lines like:
 *
 *     [Artifact: helper.py v1 - 73 lines, text/x-python]
 *
 * After ``step_4f_extract_artifacts`` replaces the original block.
 * ProfileChatTab splits the message body by newlines; each line is
 * passed through ``parseArtifactStub`` and, if it matches, rendered
 * as this card. Click opens the drawer (if collapsed) and selects
 * the corresponding artifact.
 *
 * Resolution: the stub doesn't carry the UUID, so the card matches
 * ``(threadId, name, version)`` against
 * ``useStore.artifactsByThread`` to find the row.
 */
import { useEffect, useMemo, useRef } from 'react';
import { useStore } from '../../store/useStore';

const AMBER = '#f0b060';
const DIM = '#888899';

export interface ArtifactCardProps {
  /** The chat thread the message belongs to. */
  threadId: string;
  /** Parsed-from-stub fields. */
  name: string;
  version: number;
  lineCount: number;
  mime: string;
}

export function ArtifactCard(props: ArtifactCardProps) {
  const { threadId, name, version, lineCount, mime } = props;
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const selectArtifact = useStore((s) => s.selectArtifact);
  const setCollapsed = useStore((s) => s.setArtifactDrawerCollapsed);
  const hydrateArtifacts = useStore((s) => s.hydrateArtifacts);

  const resolved = useMemo(() => {
    const list = artifactsByThread.get(threadId) ?? [];
    return list.find((a) => a.name === name && a.version === version) ?? null;
  }, [artifactsByThread, threadId, name, version]);

  // AD-1074c: a freshly-produced artifact's card mounts before the thread's
  // artifact list has been (re)fetched, so it can't resolve. Pull the thread's
  // artifacts once so the card resolves and the drawer surfaces + auto-opens
  // the new document (ArtifactDrawer AD-1074c). Honest-degrade on failure.
  const fetchedRef = useRef(false);
  useEffect(() => {
    if (resolved || fetchedRef.current || !threadId) return;
    fetchedRef.current = true;
    (async () => {
      try {
        const { fetchThreadArtifacts } = await import('./artifactApi');
        const list = await fetchThreadArtifacts(threadId);
        hydrateArtifacts(threadId, list);
      } catch { /* honest-degrade - the card stays in its loading state */ }
    })();
  }, [resolved, threadId, hydrateArtifacts]);

  const onClick = () => {
    if (!resolved) return;
    selectArtifact(resolved.id);
    setCollapsed(false);
  };

  return (
    <span
      onClick={onClick}
      role="button"
      tabIndex={resolved ? 0 : -1}
      data-testid="artifact-card"
      title={resolved
        ? `Open ${name} v${version}`
        : `Loading ${name} v${version}…`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        margin: '4px 0', padding: '4px 8px',
        border: `1px solid ${resolved ? AMBER : 'rgba(255,255,255,0.1)'}`,
        borderRadius: 4,
        background: 'rgba(240, 176, 96, 0.06)',
        color: resolved ? '#e0dcd4' : DIM,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        cursor: resolved ? 'pointer' : 'wait',
        whiteSpace: 'nowrap',
      }}
    >
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
        stroke={AMBER} strokeWidth={1.5}
        strokeLinecap="round" strokeLinejoin="round" aria-label="artifact">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
      <span>{name}</span>
      <span style={{
        color: AMBER, border: '1px solid rgba(240, 176, 96, 0.3)',
        borderRadius: 2, padding: '0 3px', fontSize: 10,
      }}>v{version}</span>
      <span style={{ color: DIM, fontSize: 10 }}>
        {lineCount} lines · {mime}
      </span>
    </span>
  );
}
