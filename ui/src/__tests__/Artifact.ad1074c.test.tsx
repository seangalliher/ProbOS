/** AD-1074c (Cowork epic #1010) vitest — a freshly-produced document opens
 * itself in the split-view: the inline ArtifactCard re-fetches the thread's
 * artifacts when it cannot resolve a just-produced artifact, and the
 * ArtifactDrawer auto-opens (selects + uncollapses) on same-thread growth. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor, cleanup, act } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';
import { ArtifactCard } from '../components/artifacts/ArtifactCard';

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

const DOC: ArtifactView = {
  id: 'doc1', thread_id: 't1', name: 'Report.docx', version: 1,
  content_hash: 'h1', mime: DOCX_MIME, size_bytes: 1200,
  created_by: 'agent', created_at: 5, supersedes: null,
  _pinned_from_project: false,
};

const callsByThread: Record<string, number> = {};

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  localStorage.clear();
  for (const k of Object.keys(callsByThread)) delete callsByThread[k];
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    artifactDrawerCollapsed: true,
  });
  // Default: thread has no artifacts yet.
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
    const tid = m?.[1] ?? '';
    callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
    return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [] }));
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('AD-1074c — produced document auto-opens', () => {
  it('ArtifactCard re-fetches the thread when it cannot resolve a produced artifact', async () => {
    // The card refers to a document that is not yet in the store.
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
      const tid = m?.[1] ?? '';
      callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
      return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [DOC] }));
    });

    render(
      <ArtifactCard
        threadId="t1"
        name="Report.docx"
        version={1}
        lineCount={0}
        mime={DOCX_MIME}
      />,
    );

    await waitFor(() => {
      const list = useStore.getState().artifactsByThread.get('t1') ?? [];
      expect(list.some((a) => a.id === DOC.id)).toBe(true);
    });
    expect(callsByThread['t1']).toBeGreaterThanOrEqual(1);
  });

  it('ArtifactDrawer auto-opens the newest document on same-thread growth', async () => {
    render(<ArtifactDrawer />);
    // Initial fetch settles with an empty list (primes the auto-open baseline).
    await waitFor(() => expect(callsByThread['t1']).toBe(1));
    await waitFor(() =>
      expect(useStore.getState().artifactsByThread.has('t1')).toBe(true),
    );

    // A document is produced live and lands in the thread's artifact list.
    act(() => {
      useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) });
    });

    await waitFor(() => {
      const s = useStore.getState();
      expect(s.selectedArtifactId).toBe(DOC.id);
      expect(s.artifactDrawerCollapsed).toBe(false);
    });
  });

  it('ArtifactDrawer does NOT auto-open on the initial thread load', async () => {
    // Thread already has the document before the drawer mounts (history load),
    // and the fetch confirms it — so the list never grows in place.
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
      const tid = m?.[1] ?? '';
      callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
      return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [DOC] }));
    });
    act(() => {
      useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) });
    });
    render(<ArtifactDrawer />);
    await waitFor(() => expect(callsByThread['t1']).toBe(1));

    // Selection must stay untouched — only live arrivals auto-open.
    expect(useStore.getState().selectedArtifactId).toBeNull();
  });
});
