/** AD-797 (Wave 197) vitest — ArtifactDrawer renders the 28px rail when
 * no artifacts and no project pins surface for the active thread. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    activeThreadId: 't-empty',
    chatThreads: new Map([
      ['t-empty', { id: 't-empty', title: 'Empty', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    artifactDrawerCollapsed: false,
  });
  const body = { thread_id: 't-empty', artifacts: [] };
  global.fetch = vi.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  }) as any);
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer empty-state', () => {
  it('collapses to a 28px rail when the thread has no artifacts', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      const drawer = screen.getByTestId('artifact-drawer');
      expect(drawer.getAttribute('data-collapsed')).toBe('true');
    });
    expect(screen.getByTestId('artifact-drawer-expand')).toBeInTheDocument();
  });
});
