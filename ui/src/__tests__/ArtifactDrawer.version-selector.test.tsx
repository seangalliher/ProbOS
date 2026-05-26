/** AD-797 (Wave 197) vitest — multi-version artifacts → version dropdown selects. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

const V1: ArtifactView = {
  id: 'a1', thread_id: 't1', name: 'doc.md', version: 1,
  content_hash: 'h1', mime: 'text/markdown', size_bytes: 1,
  created_by: 'agent', created_at: 1, supersedes: null,
  _pinned_from_project: false,
};
const V2: ArtifactView = { ...V1, id: 'a2', version: 2, content_hash: 'h2', supersedes: 'a1' };

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map([['t1', [V1, V2]]]),
    selectedArtifactId: 'a2',
    artifactDrawerCollapsed: false,
  });
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    if (u.endsWith('/content')) {
      return Promise.resolve({
        ok: true,
        headers: { get: (k: string) => k.toLowerCase() === 'content-type' ? 'text/markdown' : null },
        blob: async () => new Blob(['v'], { type: 'text/markdown' }),
      }) as any;
    }
    return Promise.resolve({
      ok: true, json: async () => ({ thread_id: 't1', artifacts: [V1, V2] }),
    }) as any;
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer version-selector', () => {
  it('switches selectedArtifactId when the dropdown changes', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      expect(screen.getByTestId('artifact-version-selector')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('artifact-version-selector'), {
      target: { value: 'a1' },
    });
    expect(useStore.getState().selectedArtifactId).toBe('a1');
  });
});
