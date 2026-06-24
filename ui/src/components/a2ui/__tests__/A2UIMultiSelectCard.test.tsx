// AD-811b: A2UIMultiSelectCard renders a resolved multiselect spec, toggles
// options, gates Submit on minSelect, disables unselected at maxSelect, and
// posts the options-order comma-join via onChoice (one-shot lock). Real
// zustand store (BF-287 style); fetchArtifactContent is mocked. HXI no-emoji
// guard. Each test awaits findByText(prompt) (the stable resolved signal)
// BEFORE getByTestId — the loading + resolved nodes share the testid, so a
// bare findByTestId can capture the transient loading span (AD-811a race).
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../artifacts/artifactApi', () => ({
  fetchArtifactContent: vi.fn(),
}));
import { fetchArtifactContent } from '../../artifacts/artifactApi';
import { A2UIMultiSelectCard } from '../A2UIMultiSelectCard';
import cardSource from '../A2UIMultiSelectCard.tsx?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

const MS_JSON = JSON.stringify({
  kind: 'multiselect', prompt: 'Pick halls', options: ['Alpha', 'Beta', 'Gamma'],
});

function mkArtifact(p: {
  id: string; threadId: string; name: string; version: number;
}): ArtifactView {
  return {
    id: p.id, thread_id: p.threadId, name: p.name, version: p.version,
    content_hash: 'h', mime: 'application/json', size_bytes: 10,
    created_by: 'yeo', created_at: 0, supersedes: null,
    _pinned_from_project: false,
  };
}

function seed(threadId: string, artifacts: ArtifactView[]): void {
  useStore.setState({ artifactsByThread: new Map([[threadId, artifacts]]) });
}

function mockContent(text: string): void {
  vi.mocked(fetchArtifactContent).mockResolvedValue({
    blob: new Blob([text]), text, mime: 'application/json',
  });
}

function renderCard(json: string, onChoice: (r: string) => void = () => {}) {
  seed('t1', [mkArtifact({
    id: 'a1', threadId: 't1', name: 'a2ui-multiselect-1.json', version: 1,
  })]);
  mockContent(json);
  return render(
    <A2UIMultiSelectCard
      threadId="t1" name="a2ui-multiselect-1.json" version={1} onChoice={onChoice}
    />,
  );
}

beforeEach(() => {
  useStore.setState({ artifactsByThread: new Map() });
  vi.mocked(fetchArtifactContent).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AD-811b A2UIMultiSelectCard', () => {
  it('renders the prompt + a toggle button per option once resolved', async () => {
    renderCard(MS_JSON);
    expect(await screen.findByText('Pick halls')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-multiselect-card')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-ms-option-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('a2ui-ms-option-1')).toHaveTextContent('Beta');
    expect(screen.getByTestId('a2ui-ms-option-2')).toHaveTextContent('Gamma');
  });

  it('toggles an option on and off', async () => {
    renderCard(MS_JSON);
    await screen.findByText('Pick halls');
    const opt0 = screen.getByTestId('a2ui-ms-option-0');
    expect(opt0).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(opt0);
    expect(opt0).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(opt0);
    expect(opt0).toHaveAttribute('aria-pressed', 'false');
  });

  it('disables Submit until minSelect is met', async () => {
    renderCard(JSON.stringify({
      kind: 'multiselect', prompt: 'Pick halls',
      options: ['Alpha', 'Beta', 'Gamma'], min_select: 2,
    }));
    await screen.findByText('Pick halls');
    const submit = screen.getByTestId('a2ui-ms-submit');
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByTestId('a2ui-ms-option-0'));
    expect(submit).toBeDisabled(); // 1 < min 2
    fireEvent.click(screen.getByTestId('a2ui-ms-option-1'));
    expect(submit).not.toBeDisabled(); // 2 >= min 2
  });

  it('disables unselected options once maxSelect is reached', async () => {
    renderCard(JSON.stringify({
      kind: 'multiselect', prompt: 'Pick halls',
      options: ['Alpha', 'Beta', 'Gamma'], max_select: 1,
    }));
    await screen.findByText('Pick halls');
    fireEvent.click(screen.getByTestId('a2ui-ms-option-0'));
    // at the cap: the unselected options disable; the picked one stays enabled
    expect(screen.getByTestId('a2ui-ms-option-1')).toBeDisabled();
    expect(screen.getByTestId('a2ui-ms-option-2')).toBeDisabled();
    expect(screen.getByTestId('a2ui-ms-option-0')).not.toBeDisabled();
  });

  it('posts the picks in option order joined by commas on submit', async () => {
    const onChoice = vi.fn();
    renderCard(MS_JSON, onChoice);
    await screen.findByText('Pick halls');
    // click out of order (Gamma then Alpha) -> option-order join "Alpha, Gamma"
    fireEvent.click(screen.getByTestId('a2ui-ms-option-2'));
    fireEvent.click(screen.getByTestId('a2ui-ms-option-0'));
    fireEvent.click(screen.getByTestId('a2ui-ms-submit'));
    expect(onChoice).toHaveBeenCalledTimes(1);
    expect(onChoice).toHaveBeenCalledWith('Alpha, Gamma');
  });

  it('locks all controls after submit (one-shot)', async () => {
    const onChoice = vi.fn();
    renderCard(MS_JSON, onChoice);
    await screen.findByText('Pick halls');
    fireEvent.click(screen.getByTestId('a2ui-ms-option-0'));
    fireEvent.click(screen.getByTestId('a2ui-ms-submit'));
    expect(screen.getByTestId('a2ui-ms-option-0')).toBeDisabled();
    expect(screen.getByTestId('a2ui-ms-option-1')).toBeDisabled();
    expect(screen.getByTestId('a2ui-ms-submit')).toBeDisabled();
    // a second submit click is a no-op (already submitted)
    fireEvent.click(screen.getByTestId('a2ui-ms-submit'));
    expect(onChoice).toHaveBeenCalledTimes(1);
  });

  it('shows a loading state when the artifact is unresolved', () => {
    // no seed -> resolve returns null -> placeholder
    render(
      <A2UIMultiSelectCard
        threadId="t1" name="missing.json" version={1} onChoice={() => {}}
      />,
    );
    expect(screen.getByTestId('a2ui-multiselect-card'))
      .toHaveTextContent(/Loading/i);
  });

  it('contains no emoji (HXI #3) in source or rendered DOM', async () => {
    expect(cardSource).not.toMatch(EMOJI_RE);
    renderCard(MS_JSON);
    await screen.findByText('Pick halls');
    const card = screen.getByTestId('a2ui-multiselect-card');
    expect(card.textContent ?? '').not.toMatch(EMOJI_RE);
  });
});
