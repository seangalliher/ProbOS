/** AD-1021b vitest — CodeWorkstation governed write-through (HXI #11 middle tier).
 *
 * The write-through affordance (path input + Load/Save against an agent's AD-997
 * workspace folder, Save routed through the consensus-gated endpoint) is gated on
 * the optional `agentId` prop. With no agentId the component is byte-identical to
 * AD-1021 (plain scratch editor). The lazy MonacoSurface wrapper is module-mocked
 * (a controlled <textarea>) so the heavy monaco-editor core never loads in jsdom;
 * loadFile/saveFile are injected (no fetch mock, no token).
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { CodeWorkstation } from './CodeWorkstation';
import type { WorkspaceFileLoad, WorkspaceSaveResult } from './workspaceFileApi';

// Stub the lazy Monaco wrapper with a controlled textarea (value/readOnly/onChange).
vi.mock('./MonacoSurface', () => ({
  default: ({ value, language, readOnly, onChange }: { value: string; language: string; readOnly: boolean; onChange?: (v: string) => void }) => (
    <textarea data-testid="monaco-editor" data-language={language} value={value} readOnly={readOnly} onChange={(e) => onChange?.(e.target.value)} />
  ),
}));
// CodeWorkstation imports the artifact fetch at module top; mock it (unused here).
vi.mock('../artifacts/artifactApi', () => ({ fetchArtifactContent: vi.fn() }));

const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => cleanup());

describe('CodeWorkstation write-through (AD-1021b)', () => {
  it('hides the affordance and stays a plain scratch editor when no agentId (byte-identical AD-1021)', async () => {
    render(<CodeWorkstation typeId="monaco" doc={null} />);
    expect(screen.queryByTestId('workstation-path-input')).toBeNull();
    expect(screen.queryByTestId('workstation-load')).toBeNull();
    expect(screen.queryByTestId('workstation-save')).toBeNull();
    expect(screen.queryByTestId('workstation-save-status')).toBeNull();
    // The scratch editor is still editable (the AD-1021 behavior is unchanged).
    const ed = (await screen.findByTestId('monaco-editor')) as HTMLTextAreaElement;
    expect(ed.readOnly).toBe(false);
    fireEvent.change(ed, { target: { value: 'hello scratch' } });
    await waitFor(() =>
      expect((screen.getByTestId('monaco-editor') as HTMLTextAreaElement).value).toBe('hello scratch'),
    );
  });

  it('seeds the editor from the workspace file on Load', async () => {
    const loadFile = vi.fn(async (): Promise<WorkspaceFileLoad> => ({ found: true, content: 'loaded body' }));
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={loadFile} saveFile={vi.fn()} />);
    fireEvent.change(screen.getByTestId('workstation-path-input'), { target: { value: 'main.py' } });
    fireEvent.click(screen.getByTestId('workstation-load'));
    await waitFor(() =>
      expect((screen.getByTestId('monaco-editor') as HTMLTextAreaElement).value).toBe('loaded body'),
    );
    expect(loadFile).toHaveBeenCalledWith('cr-1', 'main.py');
  });

  it('shows a committed banner and sends the edited content on a successful governed Save', async () => {
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'committed' }));
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={vi.fn()} saveFile={saveFile} />);
    fireEvent.change(screen.getByTestId('workstation-path-input'), { target: { value: 'main.py' } });
    fireEvent.change(screen.getByTestId('monaco-editor'), { target: { value: 'x = 1' } });
    fireEvent.click(screen.getByTestId('workstation-save'));
    await waitFor(() =>
      expect(screen.getByTestId('workstation-save-status').textContent).toBe('committed'),
    );
    expect(saveFile).toHaveBeenCalledWith('cr-1', 'main.py', 'x = 1');
  });

  it('surfaces the consensus outcome when the governed Save is refused', async () => {
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({
      outcome: 'refused', consensus_outcome: 'rejected', approval_ratio: 0.25,
    }));
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={vi.fn()} saveFile={saveFile} />);
    fireEvent.change(screen.getByTestId('workstation-path-input'), { target: { value: 'main.py' } });
    fireEvent.click(screen.getByTestId('workstation-save'));
    await waitFor(() =>
      expect(screen.getByTestId('workstation-save-status').textContent).toBe('refused: rejected'),
    );
  });

  it('shows a disabled banner when the write master switch is OFF (503 -> disabled)', async () => {
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'disabled' }));
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={vi.fn()} saveFile={saveFile} />);
    fireEvent.change(screen.getByTestId('workstation-path-input'), { target: { value: 'main.py' } });
    fireEvent.click(screen.getByTestId('workstation-save'));
    await waitFor(() =>
      expect(screen.getByTestId('workstation-save-status').textContent).toMatch(/disabled/i),
    );
  });

  it('shows a not-found banner when the workspace file is absent', async () => {
    const loadFile = vi.fn(async (): Promise<WorkspaceFileLoad> => ({ found: false, content: null }));
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={loadFile} saveFile={vi.fn()} />);
    fireEvent.change(screen.getByTestId('workstation-path-input'), { target: { value: 'ghost.py' } });
    fireEvent.click(screen.getByTestId('workstation-load'));
    await waitFor(() =>
      expect(screen.getByTestId('workstation-save-status').textContent).toMatch(/not found/i),
    );
  });

  it('renders no emoji (HXI #3)', () => {
    const { container } = render(
      <CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={vi.fn()} saveFile={vi.fn()} />,
    );
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});

describe('CodeWorkstation co-edit presence (AD-1021c)', () => {
  it('renders no co-edit presence strip when no agentId (byte-identical AD-1021)', () => {
    render(<CodeWorkstation typeId="monaco" doc={null} />);
    // CoEditPanel mounts ONLY when a host passes agentId — absent here.
    expect(screen.queryByTestId('workstation-presence-strip')).toBeNull();
    expect(screen.queryByTestId('coedit-panel')).toBeNull();
  });

  it('renders the co-edit presence strip when agentId is present', () => {
    render(<CodeWorkstation typeId="monaco" doc={null} agentId="cr-1" loadFile={vi.fn()} saveFile={vi.fn()} />);
    // The strip always shows at least the owner (present = owner ∪ authors).
    expect(screen.getByTestId('workstation-presence-strip')).toBeInTheDocument();
    expect(screen.getByTestId('coedit-panel')).toBeInTheDocument();
  });
});
