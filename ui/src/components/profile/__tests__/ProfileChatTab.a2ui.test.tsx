// AD-811a: proves ProfileChatTab wires the A2UI stub -> A2UIChoiceCard (tested
// BEFORE the artifact stub) and the card's pick posts back through sendText.
// The full ProfileChatTab is too heavy to render under jsdom (audio/screen
// deps — the groupsend / threadTranscript / MeetingMic.routing precedent), so
// the wiring is asserted via a ?raw source scan and the round-trip via a
// faithful mirror of the sendText 1:1 branch fed by a real A2UIChoiceCard
// click. Artifact + A2UI cards are also shown to coexist. Real zustand store
// (BF-287 style); fetchArtifactContent + fetch are mocked.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../artifacts/artifactApi')>();
  return { ...actual, fetchArtifactContent: vi.fn() };
});
import { fetchArtifactContent } from '../../artifacts/artifactApi';
import { A2UIChoiceCard } from '../../a2ui/A2UIChoiceCard';
import { ArtifactCard } from '../../artifacts/ArtifactCard';

// ?raw import does not execute the heavy module — safe to scan the source.
import profileChatSource from '../ProfileChatTab.tsx?raw';

const CHOICE_JSON = JSON.stringify({
  kind: 'choice', prompt: 'Pick a plan', options: ['Alpha', 'Beta'],
});

function mkArtifact(p: {
  id: string; threadId: string; name: string; version: number; mime?: string;
}): ArtifactView {
  return {
    id: p.id, thread_id: p.threadId, name: p.name, version: p.version,
    content_hash: 'h', mime: p.mime ?? 'application/json', size_bytes: 10,
    created_by: 'yeo', created_at: 0, supersedes: null,
    _pinned_from_project: false,
  };
}

// Faithful mirror of the ProfileChatTab.sendText 1:1 branch (POST
// /api/agent/{id}/chat with {message}). The A2UI card feeds the chosen option
// here via onChoice={(opt) => sendText(opt)}. If the production 1:1 send branch
// changes, update this mirror.
async function sendTextMirror(agentId: string, text: string): Promise<void> {
  await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text || '(attachment)', attachment_ids: [] }),
  });
}

beforeEach(() => {
  useStore.setState({ artifactsByThread: new Map() });
  vi.mocked(fetchArtifactContent).mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-811a ProfileChatTab A2UI wiring (source contract)', () => {
  it('tests the A2UI stub BEFORE the artifact stub (precedence)', () => {
    const a2uiIdx = profileChatSource.indexOf('parseA2UIStub(line)');
    const artifactIdx = profileChatSource.indexOf('parseArtifactStub(line)');
    expect(a2uiIdx).toBeGreaterThan(-1);
    expect(artifactIdx).toBeGreaterThan(-1);
    expect(a2uiIdx).toBeLessThan(artifactIdx);
  });

  it('renders A2UIChoiceCard with the onA2UIChoice callback', () => {
    expect(profileChatSource).toMatch(/<A2UIChoiceCard[\s\S]*?onChoice=\{onA2UIChoice/);
  });

  it('passes (opt) => sendText(opt) into renderMessageBodyWithArtifacts at the call site', () => {
    expect(profileChatSource).toContain(
      'renderMessageBodyWithArtifacts(msg.text, threadId, (opt) => sendText(opt))',
    );
  });
});

describe('AD-811a A2UI <-> artifact cards coexist', () => {
  it('renders an A2UIChoiceCard and an ArtifactCard side by side', async () => {
    useStore.setState({
      artifactsByThread: new Map([[
        't1',
        [
          mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 }),
          mkArtifact({ id: 'a2', threadId: 't1', name: 'helper.py', version: 1, mime: 'text/x-python' }),
        ],
      ]]),
    });
    vi.mocked(fetchArtifactContent).mockResolvedValue({
      blob: new Blob([CHOICE_JSON]), text: CHOICE_JSON, mime: 'application/json',
    });
    render(
      <>
        <A2UIChoiceCard threadId="t1" name="a2ui-choice-1.json" version={1} onChoice={() => {}} />
        <ArtifactCard threadId="t1" name="helper.py" version={1} lineCount={73} mime="text/x-python" />
      </>,
    );
    // Wait for the A2UI card to RESOLVE (stable signal) before querying the
    // testid — the loading span and the resolved div share the testid, so a
    // bare findByTestId can capture the transient loading span.
    expect(await screen.findByText('Pick a plan')).toBeInTheDocument();
    expect(screen.getByTestId('a2ui-choice-card')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-card')).toBeInTheDocument();
  });
});

describe('AD-811a A2UI choice round-trip (mirror of sendText)', () => {
  it('posts the chosen option back through the 1:1 chat route', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
    vi.stubGlobal('fetch', fetchMock);

    useStore.setState({
      artifactsByThread: new Map([[
        't1', [mkArtifact({ id: 'a1', threadId: 't1', name: 'a2ui-choice-1.json', version: 1 })],
      ]]),
    });
    vi.mocked(fetchArtifactContent).mockResolvedValue({
      blob: new Blob([CHOICE_JSON]), text: CHOICE_JSON, mime: 'application/json',
    });

    render(
      <A2UIChoiceCard
        threadId="t1"
        name="a2ui-choice-1.json"
        version={1}
        onChoice={(opt) => sendTextMirror('yeo', opt)}
      />,
    );
    await screen.findByText('Pick a plan');
    fireEvent.click(screen.getByTestId('a2ui-option-1'));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/agent/yeo/chat');
    expect(JSON.parse((init as RequestInit).body as string).message).toBe('Beta');
  });
});
