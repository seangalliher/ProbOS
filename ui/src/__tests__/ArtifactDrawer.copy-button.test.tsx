/** AD-797 (Wave 197) vitest — Copy button calls navigator.clipboard.writeText. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

const ART: ArtifactView = {
  id: 'a1', thread_id: 't1', name: 'plain.txt', version: 1,
  content_hash: 'h1', mime: 'text/plain', size_bytes: 5,
  created_by: 'agent', created_at: 1, supersedes: null,
  _pinned_from_project: false,
};

const writeText = vi.fn(() => Promise.resolve());

beforeEach(() => {
  localStorage.clear();
  writeText.mockClear();
  Object.assign(navigator, {
    clipboard: { writeText },
  });
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
        headers: { get: (k: string) => k.toLowerCase() === 'content-type' ? 'text/plain' : null },
        blob: async () => new Blob(['hello'], { type: 'text/plain' }),
      }) as any;
    }
    return Promise.resolve({
      ok: true, json: async () => ({ thread_id: 't1', artifacts: [ART] }),
    }) as any;
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer copy-button', () => {
  it('writes artifact content to the clipboard on click', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      expect(screen.getByTestId('artifact-copy')).toBeInTheDocument();
    });
    // Wait for content fetch to complete.
    await waitFor(() => {
      expect(screen.getByTestId('artifact-plain')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('artifact-copy'));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('hello');
    });
  });
});
