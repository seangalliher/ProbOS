/** AD-797 (Wave 197) vitest — markdown content renders via react-markdown. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

const ART: ArtifactView = {
  id: 'a1', thread_id: 't1', name: 'doc.md', version: 1,
  content_hash: 'h1', mime: 'text/markdown', size_bytes: 9,
  created_by: 'agent', created_at: 1, supersedes: null,
  _pinned_from_project: false,
};

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map([['t1', [ART]]]),
    selectedArtifactId: 'a1',
    artifactDrawerCollapsed: false,
  });
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    if (u.endsWith('/content')) {
      return Promise.resolve({
        ok: true,
        headers: { get: (k: string) => k.toLowerCase() === 'content-type' ? 'text/markdown' : null },
        blob: async () => new Blob(['# Hello World\n\nBody.'], { type: 'text/markdown' }),
      }) as any;
    }
    return Promise.resolve({
      ok: true, json: async () => ({ thread_id: 't1', artifacts: [ART] }),
    }) as any;
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer markdown render', () => {
  it('renders a markdown artifact via react-markdown', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      expect(screen.getByTestId('artifact-markdown')).toBeInTheDocument();
    });
    // react-markdown turns `# Hello World` into an <h1>.
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Hello World');
    });
  });
});
