/** AD-797 (Wave 197) vitest — ArtifactDrawer renders the 28px rail when
 * no artifacts and no project pins surface for the active thread. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useStore } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

let hostWidth = 900;
let resizeHost: (width: number) => void;

beforeEach(() => {
  localStorage.clear();
  hostWidth = 900;
  vi.stubGlobal('innerWidth', 1440);
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => hostWidth);
  vi.stubGlobal('ResizeObserver', class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element): void {
      resizeHost = (width: number): void => {
        hostWidth = width;
        this.callback([{ target, contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      };
    }
    disconnect(): void {}
  });
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

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('ArtifactDrawer empty-state', () => {
  it('collapses to a 28px rail when the thread has no artifacts', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      const drawer = screen.getByTestId('artifact-drawer');
      expect(drawer.getAttribute('data-collapsed')).toBe('true');
    });
    expect(screen.getByTestId('artifact-drawer-expand')).toBeInTheDocument();
  });

  it('defaults a fresh no-thread conversation to rail without fetching', () => {
    useStore.setState({ activeThreadId: null });
    render(<ArtifactDrawer />);
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBeNull();
  });

  it('uses an explicit host thread without changing the global thread', async () => {
    useStore.setState({ activeThreadId: 'another-host' });
    render(<ArtifactDrawer threadId="t-empty" />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t-empty')).toBe(true));
    expect(global.fetch).toHaveBeenCalledWith('/api/artifacts/thread/t-empty?limit=1001');
    expect(useStore.getState().activeThreadId).toBe('another-host');
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-thread-id', 't-empty');
  });

  it('keeps an explicit no-thread host separate from a stale global thread', () => {
    render(<ArtifactDrawer threadId={null} />);
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.getByTestId('artifact-drawer')).not.toHaveAttribute('data-thread-id');
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
  });

  it.each([null, 't-empty'])('preserves an explicit expanded override for %s', async (threadId) => {
    useStore.setState({ activeThreadId: threadId });
    render(<ArtifactDrawer initialCollapsed={false} />);
    if (threadId) await waitFor(() => expect(useStore.getState().artifactsByThread.has(threadId)).toBe(true));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'false');
  });

  it('does not let a delayed empty response undo manual expansion', async () => {
    const user = userEvent.setup();
    let resolveFetch!: (response: Response) => void;
    global.fetch = vi.fn(() => new Promise<Response>(resolve => { resolveFetch = resolve; }));
    render(<ArtifactDrawer initialCollapsed />);
    expect(global.fetch).toHaveBeenCalledWith('/api/artifacts/thread/t-empty?limit=1001');
    await user.click(screen.getByRole('button', { name: 'Expand artifacts' }));
    await act(async () => {
      resolveFetch(new Response(JSON.stringify({ thread_id: 't-empty', artifacts: [] }), { status: 200 }));
    });
    expect(useStore.getState().artifactsByThread.has('t-empty')).toBe(true);
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'false');
  });

  it('contains an explicit narrow-parent expansion and restores keyboard focus on Escape', async () => {
    hostWidth = 418;
    useStore.setState({ activeThreadId: null });
    const user = userEvent.setup();
    render(<ArtifactDrawer />);
    expect(window.innerWidth).toBe(1440);
    await user.tab();
    expect(screen.getByRole('button', { name: 'Expand artifacts' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    expect(screen.getByTestId('artifact-drawer')).toHaveStyle({ width: '28px' });
    expect(screen.getByRole('button', { name: 'Collapse artifacts' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Expand artifacts' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Expand artifacts' }));
    await user.click(screen.getByRole('button', { name: 'Collapse artifacts' }));
    expect(screen.getByRole('button', { name: 'Expand artifacts' })).toHaveFocus();
  });

  it.each(['0', '1'])('preserves desktop preference %s across narrow-parent resizing', async (preference) => {
    localStorage.setItem('probos.artifactDrawer.collapsed', preference);
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t-empty')).toBe(true));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', String(preference === '1'));
    act(() => resizeHost(418));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe(preference);
    expect(useStore.getState().artifactDrawerCollapsed).toBe(preference === '1');
    act(() => resizeHost(900));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', String(preference === '1'));
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe(preference);
  });

  it('restores a saved expanded preference only when a narrow initial host recovers', async () => {
    hostWidth = 418;
    localStorage.setItem('probos.artifactDrawer.collapsed', '0');
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t-empty')).toBe(true));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    act(() => resizeHost(900));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'false');
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe('0');
  });

  it('collapses a new no-thread conversation after leaving an untouched thread', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t-empty')).toBe(true));
    localStorage.setItem('probos.artifactDrawer.collapsed', '0');
    act(() => useStore.setState({ activeThreadId: null, artifactDrawerCollapsed: false }));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    expect(useStore.getState().artifactDrawerCollapsed).toBe(false);
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe('0');
  });
});
