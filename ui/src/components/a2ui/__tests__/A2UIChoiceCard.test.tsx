// AD-811a: A2UIChoiceCard renders a resolved choice spec, posts the pick via
// onChoice, and locks after a click. Real zustand store (BF-287 style);
// fetchArtifactContent is mocked. HXI no-emoji guard included.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../artifacts/artifactApi', () => ({
  fetchArtifactContent: vi.fn(),
}));
import { fetchArtifactContent } from '../../artifacts/artifactApi';
import { A2UIChoiceCard } from '../A2UIChoiceCard';
import cardSource from '../A2UIChoiceCard.tsx?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

const CHOICE_JSON = JSON.stringify({
  kind: 'choice', prompt: 'Pick a plan', options: ['Alpha', 'Beta'],
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

beforeEach(() => {
  useStore.setState({ artifactsByThread: new Map() });
  vi.mocked(fetchArtifactContent).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AD-811a A2UIChoiceCard', () => {
  it('renders the prompt + one button per option once resolved', async () => {
    seed('t1', [mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 })]);
    mockContent(CHOICE_JSON);
    render(
      <A2UIChoiceCard threadId="t1" name="a2ui-choice-1.json" version={1} onChoice={() => {}} />,
    );
    expect(await screen.findByText('Pick a plan')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-option-0')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('a2ui-option-1')).toHaveTextContent('Beta');
  });

  it('calls onChoice with the chosen option on click', async () => {
    seed('t1', [mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 })]);
    mockContent(CHOICE_JSON);
    const onChoice = vi.fn();
    render(
      <A2UIChoiceCard threadId="t1" name="a2ui-choice-1.json" version={1} onChoice={onChoice} />,
    );
    await screen.findByText('Pick a plan');
    fireEvent.click(screen.getByTestId('a2ui-option-1'));
    expect(onChoice).toHaveBeenCalledWith('Beta');
  });

  it('shows a loading state when the artifact is unresolved', () => {
    // no seed -> resolve returns null -> placeholder
    render(
      <A2UIChoiceCard threadId="t1" name="missing.json" version={1} onChoice={() => {}} />,
    );
    expect(screen.getByTestId('a2ui-choice-card')).toHaveTextContent(/Loading/i);
  });

  it('disables all buttons + highlights the pick after a click (one-shot)', async () => {
    seed('t1', [mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 })]);
    mockContent(CHOICE_JSON);
    const onChoice = vi.fn();
    render(
      <A2UIChoiceCard threadId="t1" name="a2ui-choice-1.json" version={1} onChoice={onChoice} />,
    );
    await screen.findByText('Pick a plan');
    fireEvent.click(screen.getByTestId('a2ui-option-0'));
    expect(screen.getByTestId('a2ui-option-0')).toBeDisabled();
    expect(screen.getByTestId('a2ui-option-1')).toBeDisabled();
    // a second click is a no-op (already chosen)
    fireEvent.click(screen.getByTestId('a2ui-option-1'));
    expect(onChoice).toHaveBeenCalledTimes(1);
    expect(onChoice).toHaveBeenCalledWith('Alpha');
  });

  it('contains no emoji (HXI #3) in source or rendered DOM', async () => {
    expect(cardSource).not.toMatch(EMOJI_RE);
    seed('t1', [mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 })]);
    mockContent(CHOICE_JSON);
    render(
      <A2UIChoiceCard threadId="t1" name="a2ui-choice-1.json" version={1} onChoice={() => {}} />,
    );
    // Wait for the resolved card (stable) before reading its DOM.
    await screen.findByText('Pick a plan');
    const card = screen.getByTestId('a2ui-choice-card');
    expect(card.textContent ?? '').not.toMatch(EMOJI_RE);
  });
});
