/** AD-1023 vitest — Rich Workspace container overlay (HXI Workspace).
 *
 * Mirrors the AD-1021 WorkstationPanel test: store-flag gated (mounted-but-null
 * when closed), deps-injected (no global fetch mock), honest-degrade on every
 * boundary, and the HXI no-emoji guard. Proves: the single-active-tab host
 * resolves each workstation via the exported AD-1022 WorkstationRender seam, the
 * per-workstation doc is forwarded (DD-5), and the AD-998 backing-store binding
 * is read read-only and degrades to a notice (never a blank panel).
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { WorkspacePanel } from './WorkspacePanel';
import { useStore } from '../../store/useStore';
import type { WorkstationTypeView, NativeWorkstationProps } from '../workstation/WorkstationLauncher';
import type { Workspace, WorkspaceFolder, WorkstationDoc } from '../../store/types';

const EMOJI = /\p{Extended_Pictographic}/u;

function FakeMonaco({ doc }: NativeWorkstationProps) {
  return <div data-testid="fake-monaco" data-doc-title={doc?.title ?? ''} />;
}

const FakeIframeFrame = () => <div data-testid="fake-iframe" />;

function makeCatalog(): WorkstationTypeView[] {
  return [
    { id: 'monaco', label: 'Code Editor', tier: 'oss', available: true, render_kind: 'native' },
    { id: 'browser', label: 'Browser', tier: 'oss', available: false, render_kind: 'native' },
  ];
}

function makeWorkspace(over: Partial<Workspace> = {}): Workspace {
  return { id: 'ws1', label: 'My Workspace', backingStoreRef: null, participants: [], workstations: [], ...over };
}

function makeFolder(over: Partial<WorkspaceFolder> = {}): WorkspaceFolder {
  return {
    agent_id: 'agent-1', enabled: true, persistent: true, root: '/ws', path: '/ws/agent',
    owner: 'agent-1', exists: true,
    files: [{ name: 'a.py', is_dir: false, size_bytes: 1, modified: '' }],
    total_bytes: 1,
    ...over,
  };
}

// Inferred-type deps factory (keeps vi.fn types when a test needs call-tracking;
// otherwise plain async stubs). Assignable to Partial<WorkspacePanelDeps>.
function baseDeps() {
  return {
    fetchTypes: async () => makeCatalog(),
    fetchWorkspaceFolder: async () => makeFolder(),
    nativeComponents: { monaco: FakeMonaco },
    IframeFrame: FakeIframeFrame,
  };
}

beforeEach(() => {
  useStore.setState({ workspaceOpen: true, activeWorkspace: null });
});

afterEach(() => {
  useStore.setState({ workspaceOpen: false, activeWorkspace: null });
  cleanup();
});

describe('AD-1023 WorkspacePanel', () => {
  it('renders nothing when closed and fetches neither types nor the work folder', () => {
    useStore.setState({ workspaceOpen: false, activeWorkspace: null });
    const fetchTypes = vi.fn(async () => makeCatalog());
    const fetchWorkspaceFolder = vi.fn(async () => makeFolder());
    const { container } = render(
      <WorkspacePanel deps={{ fetchTypes, fetchWorkspaceFolder, nativeComponents: { monaco: FakeMonaco }, IframeFrame: FakeIframeFrame }} />,
    );
    expect(container.firstChild).toBeNull();
    expect(fetchTypes).not.toHaveBeenCalled();
    expect(fetchWorkspaceFolder).not.toHaveBeenCalled();
  });

  it('shows the none placeholder when open with no active workspace', async () => {
    useStore.setState({ workspaceOpen: true, activeWorkspace: null });
    render(<WorkspacePanel deps={baseDeps()} />);
    expect(await screen.findByTestId('workspace-none')).toBeTruthy();
  });

  it('shows the empty placeholder when the workspace has no workstations', async () => {
    useStore.setState({ workspaceOpen: true, activeWorkspace: makeWorkspace({ workstations: [] }) });
    render(<WorkspacePanel deps={baseDeps()} />);
    expect(await screen.findByTestId('workspace-empty')).toBeTruthy();
  });

  it('renders the native monaco workstation and forwards its per-workstation doc (DD-5)', async () => {
    const doc: WorkstationDoc = { kind: 'scratch', title: 'notes', language: 'markdown', content: '' };
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ workstations: [{ typeId: 'monaco', doc }] }),
    });
    render(<WorkspacePanel deps={baseDeps()} />);
    const el = await screen.findByTestId('fake-monaco');
    expect(el.getAttribute('data-doc-title')).toBe('notes');
  });

  it('honest-degrades a catalog-unavailable type to the workstation-unavailable notice', async () => {
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ workstations: [{ typeId: 'browser' }] }),
    });
    render(<WorkspacePanel deps={baseDeps()} />);
    expect(await screen.findByTestId('workspace-workstation-unavailable')).toBeTruthy();
  });

  it('shows the unavailable notice for a workstation absent from the catalog', async () => {
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ workstations: [{ typeId: 'ghost' }] }),
    });
    render(<WorkspacePanel deps={baseDeps()} />);
    expect(await screen.findByTestId('workspace-workstation-unavailable')).toBeTruthy();
  });

  it('binds the backing store: path + file count when enabled/persistent/exists', async () => {
    const folder = makeFolder({ path: '/ws/agent', files: [{ name: 'a.py', is_dir: false, size_bytes: 1, modified: '' }] });
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ backingStoreRef: 'agent-1', workstations: [] }),
    });
    render(<WorkspacePanel deps={{ ...baseDeps(), fetchWorkspaceFolder: async () => folder }} />);
    const strip = await screen.findByTestId('workspace-backing-store');
    await waitFor(() => {
      expect(strip.textContent).toContain('/ws/agent');
      expect(strip.textContent).toContain('1 files');
    });
  });

  it('reports no persistent work folder when code execution is disabled', async () => {
    const folder = makeFolder({ enabled: false });
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ backingStoreRef: 'agent-1' }),
    });
    render(<WorkspacePanel deps={{ ...baseDeps(), fetchWorkspaceFolder: async () => folder }} />);
    const strip = await screen.findByTestId('workspace-backing-store');
    await waitFor(() => expect(strip.textContent).toContain('No persistent work folder'));
  });

  it('honest-degrades when the work folder fetch throws (panel never blanks)', async () => {
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ backingStoreRef: 'agent-1' }),
    });
    render(
      <WorkspacePanel
        deps={{ ...baseDeps(), fetchWorkspaceFolder: async () => { throw new Error('boom'); } }}
      />,
    );
    const strip = await screen.findByTestId('workspace-backing-store');
    await waitFor(() => expect(strip.textContent).toContain('Work folder unavailable'));
    expect(screen.getByTestId('workspace-panel')).toBeTruthy();
  });

  it('clicking the second tab swaps the active pane', async () => {
    const first: WorkstationDoc = { kind: 'scratch', title: 'first', language: 'markdown', content: '' };
    const second: WorkstationDoc = { kind: 'scratch', title: 'second', language: 'markdown', content: '' };
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({
        workstations: [
          { typeId: 'monaco', doc: first },
          { typeId: 'monaco', doc: second },
        ],
      }),
    });
    render(<WorkspacePanel deps={baseDeps()} />);
    const el = await screen.findByTestId('fake-monaco');
    expect(el.getAttribute('data-doc-title')).toBe('first');
    fireEvent.click(screen.getByTestId('workspace-tab-1'));
    await waitFor(() =>
      expect(screen.getByTestId('fake-monaco').getAttribute('data-doc-title')).toBe('second'),
    );
  });

  it('closes the panel on Escape', async () => {
    useStore.setState({ workspaceOpen: true, activeWorkspace: makeWorkspace({ workstations: [] }) });
    const { container } = render(<WorkspacePanel deps={baseDeps()} />);
    await screen.findByTestId('workspace-panel');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(container.firstChild).toBeNull());
    expect(useStore.getState().workspaceOpen).toBe(false);
  });

  it('uses no emoji anywhere in the panel (HXI #3)', async () => {
    const doc: WorkstationDoc = { kind: 'scratch', title: 'notes', language: 'markdown', content: '' };
    useStore.setState({
      workspaceOpen: true,
      activeWorkspace: makeWorkspace({ backingStoreRef: 'agent-1', workstations: [{ typeId: 'monaco', doc }] }),
    });
    const { container } = render(<WorkspacePanel deps={baseDeps()} />);
    await screen.findByTestId('fake-monaco');
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
