/** AD-1021c vitest — CoEditPanel (agent co-editing / presence for the Monaco
 *  workstation). Every data dep is injected (presence/agents as props, the three
 *  fetchers as props), so there is NO fetch mock and NO token. Presence reuses
 *  the AD-930 PresenceDot. Accept reuses the AD-1021b governed write seam
 *  (saveFile) — committed drops the suggestion, refused/disabled keep it + a
 *  banner. Dismiss drops it. All paths honest-degrade.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { CoEditPanel } from './CoEditPanel';
import type { WorkspaceSuggestion } from './workspaceSuggestionsApi';
import type { WorkspaceSaveResult } from './workspaceFileApi';
import type { Agent, CrewPresenceMap } from '../../store/types';

const EMOJI = /\p{Extended_Pictographic}/u;

afterEach(() => cleanup());

function mkSug(id: string, authorId: string, extra: Partial<WorkspaceSuggestion> = {}): WorkspaceSuggestion {
  return {
    id,
    owner: 'cr-1',
    path: 'main.py',
    content: `body-${id}`,
    author_id: authorId,
    author_callsign: '',
    note: '',
    created_at: 0,
    ...extra,
  };
}

const PRESENCE: CrewPresenceMap = { 'cr-1': 'online', 'forge-1': 'working', 'scout-1': 'offline' };
const AGENTS = new Map<string, Agent>([
  ['cr-1', { callsign: 'Captain' } as Agent],
  ['forge-1', { callsign: 'Forge' } as Agent],
]);

function renderPanel(props: Partial<React.ComponentProps<typeof CoEditPanel>> = {}) {
  const listSuggestions = props.listSuggestions ?? vi.fn(async () => [] as WorkspaceSuggestion[]);
  return render(
    <CoEditPanel
      ownerId="cr-1"
      path="main.py"
      presence={PRESENCE}
      agentsById={AGENTS}
      listSuggestions={listSuggestions}
      dismissSuggestion={props.dismissSuggestion ?? vi.fn(async () => true)}
      saveFile={props.saveFile ?? vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'committed' }))}
      onPreview={props.onPreview}
    />,
  );
}

describe('CoEditPanel (AD-1021c)', () => {
  it('renders a presence strip of owner ∪ distinct suggestion authors (deduped)', async () => {
    const listSuggestions = vi.fn(async () => [
      mkSug('s1', 'forge-1'),
      mkSug('s2', 'forge-1'), // duplicate author -> one dot
      mkSug('s3', 'scout-1'),
    ]);
    renderPanel({ listSuggestions });
    await screen.findByTestId('coedit-suggestion-s1');
    expect(screen.getByTestId('workstation-presence-strip')).toBeInTheDocument();
    expect(screen.getByTestId('coedit-present-cr-1')).toBeInTheDocument();
    expect(screen.getAllByTestId('coedit-present-forge-1')).toHaveLength(1);
    expect(screen.getByTestId('coedit-present-scout-1')).toBeInTheDocument();
  });

  it('lists suggestions from the injected fetcher', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1', { note: 'tidy' })]);
    renderPanel({ listSuggestions });
    expect(await screen.findByTestId('coedit-suggestion-s1')).toBeInTheDocument();
    expect(listSuggestions).toHaveBeenCalledWith('cr-1', 'main.py');
  });

  it('does not fetch and shows the empty state when the path is blank', () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    render(
      <CoEditPanel ownerId="cr-1" path="" presence={PRESENCE} agentsById={AGENTS} listSuggestions={listSuggestions} />,
    );
    expect(listSuggestions).not.toHaveBeenCalled();
    expect(screen.getByTestId('coedit-empty')).toBeInTheDocument();
    // The owner is still present even with no suggestions.
    expect(screen.getByTestId('coedit-present-cr-1')).toBeInTheDocument();
  });

  it('Preview loads the proposed content via onPreview (human-in-control)', async () => {
    const onPreview = vi.fn();
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    renderPanel({ listSuggestions, onPreview });
    await screen.findByTestId('coedit-suggestion-s1');
    fireEvent.click(screen.getByTestId('coedit-preview-s1'));
    expect(onPreview).toHaveBeenCalledWith('body-s1');
  });

  it('Accept routes through saveFile, drops the suggestion on commit, and banners', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'committed' }));
    renderPanel({ listSuggestions, saveFile });
    await screen.findByTestId('coedit-suggestion-s1');
    fireEvent.click(screen.getByTestId('coedit-accept-s1'));
    await waitFor(() => expect(screen.queryByTestId('coedit-suggestion-s1')).toBeNull());
    expect(saveFile).toHaveBeenCalledWith('cr-1', 'main.py', 'body-s1');
    expect(screen.getByTestId('coedit-banner').textContent).toMatch(/accepted/i);
  });

  it('Accept that is refused keeps the suggestion and banners the consensus outcome', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'refused', consensus_outcome: 'rejected' }));
    renderPanel({ listSuggestions, saveFile });
    await screen.findByTestId('coedit-suggestion-s1');
    fireEvent.click(screen.getByTestId('coedit-accept-s1'));
    await waitFor(() => expect(screen.getByTestId('coedit-banner').textContent).toBe('refused: rejected'));
    expect(screen.getByTestId('coedit-suggestion-s1')).toBeInTheDocument();
  });

  it('Accept when the write switch is OFF keeps the suggestion and shows a disabled banner', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    const saveFile = vi.fn(async (): Promise<WorkspaceSaveResult> => ({ outcome: 'disabled' }));
    renderPanel({ listSuggestions, saveFile });
    await screen.findByTestId('coedit-suggestion-s1');
    fireEvent.click(screen.getByTestId('coedit-accept-s1'));
    await waitFor(() => expect(screen.getByTestId('coedit-banner').textContent).toMatch(/disabled/i));
    expect(screen.getByTestId('coedit-suggestion-s1')).toBeInTheDocument();
  });

  it('Dismiss removes the suggestion via the injected fetcher', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1')]);
    const dismissSuggestion = vi.fn(async () => true);
    renderPanel({ listSuggestions, dismissSuggestion });
    await screen.findByTestId('coedit-suggestion-s1');
    fireEvent.click(screen.getByTestId('coedit-dismiss-s1'));
    await waitFor(() => expect(screen.queryByTestId('coedit-suggestion-s1')).toBeNull());
    expect(dismissSuggestion).toHaveBeenCalledWith('cr-1', 's1');
  });

  it('honest-degrades to the empty state when the list fetch throws', async () => {
    const listSuggestions = vi.fn(async () => { throw new Error('boom'); });
    renderPanel({ listSuggestions });
    expect(await screen.findByTestId('coedit-empty')).toBeInTheDocument();
    // The owner strip still renders (never a blank pane).
    expect(screen.getByTestId('coedit-present-cr-1')).toBeInTheDocument();
  });

  it('renders no emoji (HXI #3)', async () => {
    const listSuggestions = vi.fn(async () => [mkSug('s1', 'forge-1', { note: 'tidy' })]);
    const { container } = renderPanel({ listSuggestions });
    await screen.findByTestId('coedit-suggestion-s1');
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
