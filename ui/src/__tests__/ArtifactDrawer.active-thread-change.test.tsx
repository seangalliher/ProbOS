/** AD-797 (Wave 197) vitest — drawer re-fetches when activeThreadId changes. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor, cleanup, act } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

const callsByThread: Record<string, number> = {};

beforeEach(() => {
  localStorage.clear();
  for (const k of Object.keys(callsByThread)) delete callsByThread[k];
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
      ['t2', { id: 't2', title: 'T2', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    artifactDrawerCollapsed: false,
  });
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
    const tid = m?.[1] ?? '';
    callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
    return Promise.resolve({
      ok: true,
      json: async () => ({ thread_id: tid, artifacts: [] }),
    }) as any;
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer active-thread change', () => {
  it('re-fetches when activeThreadId changes', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => expect(callsByThread['t1']).toBe(1));

    act(() => {
      useStore.setState({ activeThreadId: 't2' });
    });

    await waitFor(() => expect(callsByThread['t2']).toBe(1));
  });
});
