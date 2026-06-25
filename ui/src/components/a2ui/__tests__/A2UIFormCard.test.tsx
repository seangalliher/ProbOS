// AD-811b-1: A2UIFormCard renders a resolved form spec, fills free-text
// inputs, gates Submit on the required fields, and posts the "label: value"
// newline-join via onChoice (one-shot lock). Real zustand store (BF-287
// style); fetchArtifactContent is mocked. HXI no-emoji guard. Each test
// awaits findByText(prompt) (the stable resolved signal) BEFORE getByTestId
// — the loading + resolved nodes share the testid, so a bare findByTestId
// can capture the transient loading span (AD-811a race).
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../artifacts/artifactApi', () => ({
  fetchArtifactContent: vi.fn(),
}));
import { fetchArtifactContent } from '../../artifacts/artifactApi';
import { A2UIFormCard } from '../A2UIFormCard';
import cardSource from '../A2UIFormCard.tsx?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

const FORM_JSON = JSON.stringify({
  kind: 'form', prompt: 'Tell me',
  fields: [{ label: 'Name', required: true }, { label: 'Role' }],
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
    id: 'a1', threadId: 't1', name: 'a2ui-form-1.json', version: 1,
  })]);
  mockContent(json);
  return render(
    <A2UIFormCard
      threadId="t1" name="a2ui-form-1.json" version={1} onChoice={onChoice}
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

describe('AD-811b-1 A2UIFormCard', () => {
  it('renders the prompt + a labeled input per field once resolved', async () => {
    renderCard(FORM_JSON);
    expect(await screen.findByText('Tell me')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-form-card')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-form-input-0')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-form-input-1')).toBeInTheDocument();
  });

  it('marks a required field with * and not an optional one', async () => {
    renderCard(FORM_JSON);
    await screen.findByText('Tell me');
    const card = screen.getByTestId('a2ui-form-card');
    expect(card.textContent ?? '').toContain('Name *');
    expect(card.textContent ?? '').toContain('Role');
    expect(card.textContent ?? '').not.toContain('Role *');
  });

  it('disables Submit until every required field is non-empty', async () => {
    renderCard(FORM_JSON);
    await screen.findByText('Tell me');
    const submit = screen.getByTestId('a2ui-form-submit');
    expect(submit).toBeDisabled(); // required Name is empty
    // filling only the optional field does not unblock
    fireEvent.change(screen.getByTestId('a2ui-form-input-1'), {
      target: { value: 'Eng' },
    });
    expect(submit).toBeDisabled();
    // filling the required field enables it
    fireEvent.change(screen.getByTestId('a2ui-form-input-0'), {
      target: { value: 'Ada' },
    });
    expect(submit).not.toBeDisabled();
  });

  it('does not block Submit on a blank optional field', async () => {
    renderCard(FORM_JSON);
    await screen.findByText('Tell me');
    const submit = screen.getByTestId('a2ui-form-submit');
    fireEvent.change(screen.getByTestId('a2ui-form-input-0'), {
      target: { value: 'Ada' },
    });
    expect(submit).not.toBeDisabled(); // optional Role left blank
  });

  it('posts label: value lines in field order via onChoice and locks', async () => {
    const onChoice = vi.fn();
    renderCard(FORM_JSON, onChoice);
    await screen.findByText('Tell me');
    fireEvent.change(screen.getByTestId('a2ui-form-input-0'), {
      target: { value: 'Ada' },
    });
    fireEvent.change(screen.getByTestId('a2ui-form-input-1'), {
      target: { value: 'Engineer' },
    });
    fireEvent.click(screen.getByTestId('a2ui-form-submit'));
    expect(onChoice).toHaveBeenCalledTimes(1);
    expect(onChoice).toHaveBeenCalledWith('Name: Ada\nRole: Engineer');
    // locked
    expect(screen.getByTestId('a2ui-form-input-0')).toBeDisabled();
    expect(screen.getByTestId('a2ui-form-input-1')).toBeDisabled();
    expect(screen.getByTestId('a2ui-form-submit')).toBeDisabled();
    // a second submit click is a no-op (already submitted)
    fireEvent.click(screen.getByTestId('a2ui-form-submit'));
    expect(onChoice).toHaveBeenCalledTimes(1);
  });

  it('shows a loading state when the artifact is unresolved', () => {
    // no seed -> resolve returns null -> placeholder
    render(
      <A2UIFormCard
        threadId="t1" name="missing.json" version={1} onChoice={() => {}}
      />,
    );
    expect(screen.getByTestId('a2ui-form-card')).toHaveTextContent(/Loading/i);
  });

  it('contains no emoji (HXI #3) in source or rendered DOM', async () => {
    expect(cardSource).not.toMatch(EMOJI_RE);
    renderCard(FORM_JSON);
    await screen.findByText('Tell me');
    const card = screen.getByTestId('a2ui-form-card');
    expect(card.textContent ?? '').not.toMatch(EMOJI_RE);
  });
});
