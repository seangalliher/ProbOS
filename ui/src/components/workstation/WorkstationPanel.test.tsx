/** AD-1021 vitest — Code/Text Workstation overlay (HXI #11 middle tier).
 *
 * Mirrors the AD-1018 McpServersPanel test: store-flag gated (mounted-but-null
 * when closed), deps-free (the component reads `workstationDoc` from the store),
 * the artifact fetch is module-mocked, and the HXI no-emoji guard is asserted.
 * Also proves the AD-1022 launcher seam: the `nativeWorkstations` map opens
 * CodeWorkstation for the `monaco` type (not the honest-degrade placeholder).
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { WorkstationPanel } from './WorkstationPanel';
import { WorkstationLauncher, type WorkstationTypeView } from './WorkstationLauncher';
import { nativeWorkstations } from './nativeWorkstations';
import { useStore } from '../../store/useStore';
import type { WorkstationDoc } from '../../store/types';
import { fetchArtifactContent } from '../artifacts/artifactApi';

vi.mock('../artifacts/artifactApi', () => ({ fetchArtifactContent: vi.fn() }));
const mockFetchArtifact = vi.mocked(fetchArtifactContent);

const EMOJI = /\p{Extended_Pictographic}/u;

function buildDoc(over: Partial<WorkstationDoc> = {}): WorkstationDoc {
  return {
    kind: 'build',
    title: 'Build AD-X',
    language: 'typescript',
    content: '',
    changes: [
      { path: 'src/a.ts', content: 'AAA-content', mode: 'modify', after_line: 'def foo' },
      { path: 'src/b.ts', content: 'BBB-content', mode: 'create', after_line: null },
    ],
    ...over,
  };
}

function scratchDoc(over: Partial<WorkstationDoc> = {}): WorkstationDoc {
  return { kind: 'scratch', title: 'Scratch', language: 'markdown', content: 'hello world', ...over };
}

function artifactDoc(over: Partial<WorkstationDoc> = {}): WorkstationDoc {
  return { kind: 'artifact', title: 'Artifact', language: 'plaintext', content: '', artifactId: 'art-1', ...over };
}

beforeEach(() => {
  useStore.setState({ workstationOpen: true, workstationDoc: null });
});

afterEach(() => {
  useStore.setState({ workstationOpen: false, workstationDoc: null });
  cleanup();
  mockFetchArtifact.mockReset();
});

describe('AD-1021 WorkstationPanel', () => {
  it('renders nothing when closed and does not fetch an artifact', () => {
    useStore.setState({ workstationOpen: false, workstationDoc: artifactDoc() });
    const { container } = render(<WorkstationPanel />);
    expect(container.firstChild).toBeNull();
    expect(mockFetchArtifact).not.toHaveBeenCalled();
  });

  it('renders a build doc: content, MODIFY/CREATE badge, and the multi-file rail', async () => {
    useStore.setState({ workstationDoc: buildDoc() });
    render(<WorkstationPanel />);
    // First change is shown by default (modify + after_line anchor).
    expect(screen.getByTestId('workstation-view').textContent).toContain('AAA-content');
    expect(screen.getByTestId('workstation-mode-badge').textContent).toContain('MODIFY');
    expect(screen.getByTestId('workstation-after-line').textContent).toContain('def foo');
    // Two changes -> a left rail of path buttons.
    expect(screen.getByTestId('workstation-rail')).toBeTruthy();
    expect(screen.getByTestId('workstation-path-0')).toBeTruthy();
    expect(screen.getByTestId('workstation-path-1')).toBeTruthy();
    // Switching to the second change swaps content + badge (create, no anchor).
    fireEvent.click(screen.getByTestId('workstation-path-1'));
    await waitFor(() => expect(screen.getByTestId('workstation-view').textContent).toContain('BBB-content'));
    expect(screen.getByTestId('workstation-mode-badge').textContent).toContain('CREATE');
    expect(screen.queryByTestId('workstation-after-line')).toBeNull();
  });

  it('renders a scratch doc: editable textarea + language label + Copy + Download', () => {
    useStore.setState({ workstationDoc: scratchDoc() });
    render(<WorkstationPanel />);
    const editor = screen.getByTestId('workstation-editor') as HTMLTextAreaElement;
    expect(editor.tagName).toBe('TEXTAREA');
    expect(editor.value).toBe('hello world');
    expect(screen.getByTestId('workstation-language').textContent).toContain('MARKDOWN');
    expect(screen.getByTestId('workstation-copy')).toBeTruthy();
    expect(screen.getByTestId('workstation-download')).toBeTruthy();
    // The textarea is editable (local state).
    fireEvent.change(editor, { target: { value: 'edited' } });
    expect((screen.getByTestId('workstation-editor') as HTMLTextAreaElement).value).toBe('edited');
  });

  it('renders no editor + no rail for a single-change build doc', () => {
    useStore.setState({ workstationDoc: buildDoc({ changes: [{ path: 'only.ts', content: 'SOLO', mode: 'create', after_line: null }] }) });
    render(<WorkstationPanel />);
    expect(screen.getByTestId('workstation-view').textContent).toContain('SOLO');
    expect(screen.queryByTestId('workstation-rail')).toBeNull();
    expect(screen.queryByTestId('workstation-editor')).toBeNull();
  });

  it('fetches and renders artifact content', async () => {
    mockFetchArtifact.mockResolvedValue({ blob: new Blob(['x']), text: 'ARTIFACT BODY', mime: 'text/plain' });
    useStore.setState({ workstationDoc: artifactDoc() });
    render(<WorkstationPanel />);
    await waitFor(() => expect(screen.getByTestId('workstation-view').textContent).toContain('ARTIFACT BODY'));
    expect(mockFetchArtifact).toHaveBeenCalledWith('art-1');
  });

  it('honest-degrades to a notice when the artifact fetch rejects', async () => {
    mockFetchArtifact.mockRejectedValue(new Error('boom'));
    useStore.setState({ workstationDoc: artifactDoc() });
    render(<WorkstationPanel />);
    await waitFor(() => expect(screen.getByTestId('workstation-artifact-error')).toBeTruthy());
    expect(screen.getByTestId('workstation-artifact-error').textContent).toContain('Artifact unavailable');
  });

  it('closes via the header X (workstationOpen -> false)', async () => {
    useStore.setState({ workstationDoc: scratchDoc() });
    render(<WorkstationPanel />);
    fireEvent.click(screen.getByTestId('workstation-close'));
    await waitFor(() => expect(useStore.getState().workstationOpen).toBe(false));
    expect(screen.queryByTestId('workstation-panel')).toBeNull();
  });

  it('closes via Escape (workstationOpen -> false)', async () => {
    useStore.setState({ workstationDoc: scratchDoc() });
    render(<WorkstationPanel />);
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(useStore.getState().workstationOpen).toBe(false));
    expect(screen.queryByTestId('workstation-panel')).toBeNull();
  });

  it('uses no emoji (HXI #3)', () => {
    useStore.setState({ workstationDoc: buildDoc() });
    const { container } = render(<WorkstationPanel />);
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });

  it('opens CodeWorkstation through the AD-1022 launcher seam (nativeWorkstations)', async () => {
    const fetchTypes = async (): Promise<WorkstationTypeView[]> => [
      { id: 'monaco', label: 'Code', tier: 'oss', available: true, render_kind: 'native' },
    ];
    useStore.setState({ workstationDoc: scratchDoc() });
    render(<WorkstationLauncher deps={{ fetchTypes, nativeComponents: nativeWorkstations }} />);
    await waitFor(() => screen.getByTestId('workstation-type-monaco'));
    fireEvent.click(screen.getByTestId('workstation-type-monaco'));
    // The registered OSS component renders — NOT the honest-degrade placeholder.
    expect(screen.getByTestId('workstation-code')).toBeTruthy();
    expect(screen.queryByTestId('workstation-unavailable')).toBeNull();
  });
});
