/** AD-1074c (Cowork epic #1010) vitest — a freshly-produced document opens
 * itself in the split-view: the inline ArtifactCard re-fetches the thread's
 * artifacts when it cannot resolve a just-produced artifact, and the
 * ArtifactDrawer auto-opens (selects + uncollapses) on same-thread growth. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, act, fireEvent, configure, getConfig } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { useStore, type ArtifactView } from '../store/useStore';
import { useSettingsStore } from '../store/useSettingsStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';
import { ArtifactCard, type ArtifactOpenRequest } from '../components/artifacts/ArtifactCard';

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => {} }));
vi.mock('../components/CognitiveCanvas', () => ({ CognitiveCanvas: () => null }));
vi.mock('../components/GlassLayer', () => ({ GlassLayer: () => null }));
vi.mock('../components/BridgePanel', () => ({ BridgePanel: () => null }));
vi.mock('../components/WelcomeOverlay', () => ({ WelcomeOverlay: () => null }));
vi.mock('../components/perception/VisionBudgetBadge', () => ({ VisionBudgetBadge: () => null }));
vi.mock('../audio/voiceActivity', () => ({ startVoiceActivity: vi.fn(), stopVoiceActivity: vi.fn() }));

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

const DOC: ArtifactView = {
  id: 'doc1', thread_id: 't1', name: 'Report.docx', version: 1,
  content_hash: 'h1', mime: DOCX_MIME, size_bytes: 1200,
  created_by: 'agent', created_at: 5, supersedes: null,
  _pinned_from_project: false,
};

const callsByThread: Record<string, number> = {};
let hostWidth = 900;
let resizeHost: (width: number) => void;
let savedStore: ReturnType<typeof useStore.getState>;
let savedFetch: typeof global.fetch;

function ExplicitOpenHarness({ onOpen, showCard = true, showDrawer = true }: {
  onOpen?: (request: ArtifactOpenRequest) => void;
  showCard?: boolean;
  showDrawer?: boolean;
}) {
  const [request, setRequest] = useState<ArtifactOpenRequest | null>(null);
  return <>
    {showCard && <ArtifactCard threadId="t1" name={DOC.name} version={DOC.version} lineCount={0} mime={DOC.mime}
      onArtifactOpen={activation => { onOpen?.(activation); setRequest({ ...activation }); }} />}
    {showDrawer && <ArtifactDrawer openRequest={request}
      onOpenConsumed={consumed => setRequest(current => current === consumed ? null : current)} />}
  </>;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  savedStore = useStore.getState();
  savedFetch = global.fetch;
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
  for (const k of Object.keys(callsByThread)) delete callsByThread[k];
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    artifactDrawerCollapsed: true,
  });
  // Default: thread has no artifacts yet.
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
    const tid = m?.[1] ?? '';
    callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
    return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [] }));
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useStore.setState(savedStore, true);
  global.fetch = savedFetch;
});

describe('AD-1074c — produced document auto-opens', () => {
  it('keeps a long artifact name wrapped within its containing transcript', () => {
    const name = `${'long-local-report-'.repeat(12)}.txt`;
    render(<ArtifactCard threadId="t1" name={name} version={1} lineCount={1} mime="text/plain" />);
    expect(screen.getByRole('button', { name: `Open ${name} v1` })).toHaveStyle({ maxWidth: '100%', whiteSpace: 'normal', overflowWrap: 'anywhere', flexWrap: 'wrap' });
  });

  it('keeps selecting an already-expanded row separate from an explicit expansion preference', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'false');
    const user = userEvent.setup();
    await user.click(screen.getByTestId('artifact-row-doc1'));
    act(() => useStore.setState({ activeThreadId: 'empty-next' }));
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('empty-next')).toBe(true));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
  });

  it('ArtifactCard re-fetches the thread when it cannot resolve a produced artifact', async () => {
    // The card refers to a document that is not yet in the store.
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
      const tid = m?.[1] ?? '';
      callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
      return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [DOC] }));
    });

    render(
      <ArtifactCard
        threadId="t1"
        name="Report.docx"
        version={1}
        lineCount={0}
        mime={DOCX_MIME}
      />,
    );

    await waitFor(() => {
      const list = useStore.getState().artifactsByThread.get('t1') ?? [];
      expect(list.some((a) => a.id === DOC.id)).toBe(true);
    });
    expect(callsByThread['t1']).toBeGreaterThanOrEqual(1);
  });

  it('ArtifactDrawer auto-opens the newest document on same-thread growth', async () => {
    render(<ArtifactDrawer />);
    // Initial fetch settles with an empty list (primes the auto-open baseline).
    await waitFor(() => expect(callsByThread['t1']).toBe(1));
    await waitFor(() =>
      expect(useStore.getState().artifactsByThread.has('t1')).toBe(true),
    );

    // A document is produced live and lands in the thread's artifact list.
    act(() => {
      useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) });
    });

    await waitFor(() => {
      const s = useStore.getState();
      expect(s.selectedArtifactId).toBe(DOC.id);
      expect(s.artifactDrawerCollapsed).toBe(false);
    });
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'false');
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
  });

  it('keeps narrow automatic arrivals in rail while retaining selection for width recovery', async () => {
    hostWidth = 418;
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    expect(window.innerWidth).toBe(1440);
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    expect(useStore.getState().artifactDrawerCollapsed).toBe(false);
    expect(screen.getByTestId('artifact-drawer-count')).toHaveTextContent('1');
    expect(screen.queryByTestId('artifact-viewer')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const preference = localStorage.getItem('probos.artifactDrawer.collapsed');
    act(() => resizeHost(900));
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe(preference);
  });

  it('opens a live document from its real inline card in a narrow host', async () => {
    hostWidth = 418;
    const user = userEvent.setup();
    render(<ExplicitOpenHarness />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    expect(window.innerWidth).toBe(1440);
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    expect(useStore.getState().artifactDrawerCollapsed).toBe(false);
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    const card = screen.getByRole('button', { name: `Open ${DOC.name} v1` });
    expect(card).toBeEnabled();
    card.focus();
    expect(card).toHaveFocus();
    await user.click(card);
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
  });

  it('allows narrow explicit version viewing and retains selection after dismissal', async () => {
    hostWidth = 418;
    const user = userEvent.setup();
    render(<ArtifactDrawer />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    const nextVersion = { ...DOC, id: 'doc2', version: 2, created_at: 6, supersedes: DOC.id };
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC, nextVersion]]]) }));
    expect(useStore.getState().selectedArtifactId).toBe(nextVersion.id);
    await user.click(screen.getByRole('button', { name: 'Expand artifacts' }));
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    await user.selectOptions(screen.getByTestId('artifact-version-selector'), DOC.id);
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    await user.click(screen.getByRole('button', { name: 'Collapse artifacts' }));
    expect(screen.getByRole('button', { name: 'Expand artifacts' })).toHaveFocus();
    act(() => resizeHost(900));
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    await user.click(screen.getByRole('button', { name: 'Expand artifacts' }));
    expect(screen.getByTestId('artifact-version-selector')).toHaveValue(DOC.id);
  });

  it('emits once for Enter and Space, restores the opener, and reopens the same id after geometry changes', async () => {
    hostWidth = 418;
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ExplicitOpenHarness onOpen={onOpen} />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    const card = screen.getByTestId('artifact-card');
    const focusBeforeArrival = document.activeElement;
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    expect(document.activeElement).toBe(focusBeforeArrival);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    for (const [index, key] of ['{Enter}', ' '].entries()) {
      card.focus();
      await user.keyboard(key);
      expect(onOpen).toHaveBeenCalledTimes(index + 1);
      expect(onOpen.mock.calls[index][0]).toEqual({ artifactId: DOC.id, threadId: 't1', opener: card });
      expect(screen.getByRole('button', { name: 'Collapse artifacts' })).toHaveFocus();
      await user.keyboard('{Escape}');
      expect(card).toHaveFocus();
    }
    for (const width of [900, 418, 900, 418]) {
      const preference = localStorage.getItem('probos.artifactDrawer.collapsed');
      const collapsed = useStore.getState().artifactDrawerCollapsed;
      act(() => resizeHost(width));
      expect(localStorage.getItem('probos.artifactDrawer.collapsed')).toBe(preference);
      expect(useStore.getState().artifactDrawerCollapsed).toBe(collapsed);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      await user.click(card);
      expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Collapse artifacts' }));
      expect(card).toHaveFocus();
    }
    expect(onOpen).toHaveBeenCalledTimes(6);
  });

  it('falls back to the local rail when the originating card is detached', async () => {
    hostWidth = 418;
    const user = userEvent.setup();
    const view = render(<ExplicitOpenHarness />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    await user.click(screen.getByTestId('artifact-card'));
    view.rerender(<ExplicitOpenHarness showCard={false} />);
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: 'Expand artifacts' })).toHaveFocus();
  });

  it('does not replay a consumed request when the drawer remounts', async () => {
    hostWidth = 418;
    const user = userEvent.setup();
    const view = render(<ExplicitOpenHarness />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    await user.click(screen.getByTestId('artifact-card'));
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    view.rerender(<ExplicitOpenHarness showDrawer={false} />);
    view.rerender(<ExplicitOpenHarness />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it.each(['wrong-thread', 'missing-artifact'])('acknowledges a %s request without opening or replaying it', async (invalid) => {
    hostWidth = 418;
    const onConsumed = vi.fn();
    const request: ArtifactOpenRequest = {
      artifactId: invalid === 'missing-artifact' ? 'absent' : DOC.id,
      threadId: invalid === 'wrong-thread' ? 'other' : 't1',
      opener: document.createElement('button'),
    };
    const view = render(<ArtifactDrawer openRequest={request} onOpenConsumed={onConsumed} />);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    expect(onConsumed).toHaveBeenCalledTimes(1);
    expect(onConsumed).toHaveBeenCalledWith(request);
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    view.rerender(<ArtifactDrawer openRequest={request} onOpenConsumed={onConsumed} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it('keeps omitted callbacks backward compatible', async () => {
    useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) });
    const user = userEvent.setup();
    render(<ArtifactCard threadId="t1" name={DOC.name} version={1} lineCount={0} mime={DOC.mime} />);
    await user.click(screen.getByTestId('artifact-card'));
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    expect(useStore.getState().artifactDrawerCollapsed).toBe(false);
  });

  it.each(['empty', 'failed'])('does not activate an unresolved card after %s resolution', async (result) => {
    const onOpen = vi.fn();
    if (result === 'failed') global.fetch = vi.fn().mockRejectedValue(new Error('offline'));
    const user = userEvent.setup();
    render(<ArtifactCard threadId="t1" name={DOC.name} version={1} lineCount={0} mime={DOC.mime} onArtifactOpen={onOpen} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.getByTestId('artifact-card')).toBeDisabled();
    await user.click(screen.getByTestId('artifact-card'));
    await user.keyboard('{Enter} ');
    expect(onOpen).not.toHaveBeenCalled();
    expect(useStore.getState().selectedArtifactId).toBeNull();
    expect(useStore.getState().artifactDrawerCollapsed).toBe(true);
  });

  it('ArtifactDrawer does NOT auto-open on the initial thread load', async () => {
    // Thread already has the document before the drawer mounts (history load),
    // and the fetch confirms it — so the list never grows in place.
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      const m = /\/api\/artifacts\/thread\/([^?]+)/.exec(u);
      const tid = m?.[1] ?? '';
      callsByThread[tid] = (callsByThread[tid] ?? 0) + 1;
      return Promise.resolve(jsonResponse({ thread_id: tid, artifacts: [DOC] }));
    });
    act(() => {
      useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) });
    });
    render(<ArtifactDrawer />);
    await waitFor(() => expect(callsByThread['t1']).toBe(1));

    // Selection must stay untouched — only live arrivals auto-open.
    expect(useStore.getState().selectedArtifactId).toBeNull();
  });
});

describe('native-button Space ownership with real App and IntentSurface', () => {
  let savedSettings: ReturnType<typeof useSettingsStore.getState>;
  let listeners: AbortController;
  let savedAsyncWrapper: ReturnType<typeof getConfig>['asyncWrapper'];

  beforeEach(() => {
    savedAsyncWrapper = getConfig().asyncWrapper;
    savedSettings = useSettingsStore.getState();
    listeners = new AbortController();
    useSettingsStore.setState({ snapshot: null });
    vi.spyOn(useSettingsStore.getState(), 'loadSnapshot').mockResolvedValue(undefined);
    const { activeThreadId, chatThreads } = useStore.getState();
    useStore.setState({ ...useStore.getInitialState(), activeThreadId, chatThreads,
      artifactsByThread: new Map(), selectedArtifactId: null, artifactDrawerCollapsed: true,
      voiceEnabled: false, wakeWordEnabled: false, bridgeOpen: false });
  });

  afterEach(() => {
    configure({ asyncWrapper: savedAsyncWrapper });
    cleanup();
    listeners.abort();
    vi.clearAllTimers();
    vi.useRealTimers();
    useSettingsStore.setState(savedSettings, true);
  });

  function globalInput(): HTMLInputElement | null {
    return document.querySelector<HTMLInputElement>('input[placeholder="Ask ProbOS..."]');
  }

  function expectInactiveComposer(): void {
    expect(screen.getByText(/Ask ProbOS/)).toBeInTheDocument();
    expect(globalInput()).toBeNull();
    expect(useStore.getState().pendingChar).toBeFalsy();
  }

  async function mountApp(onOpen = vi.fn()) {
    hostWidth = 418;
    render(<>
      <App />
      <div data-testid="keyboard-background" tabIndex={-1}>
        <ExplicitOpenHarness onOpen={onOpen} />
        <input aria-label="Local input" />
        <textarea aria-label="Local textarea" />
      </div>
    </>);
    await waitFor(() => expect(useStore.getState().artifactsByThread.has('t1')).toBe(true));
    const focusBeforeArrival = document.activeElement;
    act(() => useStore.setState({ artifactsByThread: new Map([['t1', [DOC]]]) }));
    const card = screen.getByRole('button', { name: `Open ${DOC.name} v1` });
    expect(card.tagName).toBe('BUTTON');
    expect(card).toBeEnabled();
    expect(card).toHaveAttribute('data-artifact-thread-id', 't1');
    expect(card).toHaveAttribute('data-artifact-id', DOC.id);
    expect(useStore.getState().artifactsByThread.get('t1')).toEqual([DOC]);
    expect(useStore.getState().selectedArtifactId).toBe(DOC.id);
    expect(useStore.getState().artifactDrawerCollapsed).toBe(false);
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(focusBeforeArrival);
    expectInactiveComposer();
    configure({ asyncWrapper: async callback => {
      let result: unknown;
      await act(async () => { result = await callback(); });
      return result;
    } });
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    return { card, user, onOpen, background: screen.getByTestId('keyboard-background') };
  }

  async function advanceFocusTimer(milliseconds: number): Promise<void> {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
  }

  function observeKeydown(): ReturnType<typeof vi.fn> {
    const observe = vi.fn((event: KeyboardEvent) => ({
      target: event.target, defaultPrevented: event.defaultPrevented,
    }));
    window.addEventListener('keydown', observe, { signal: listeners.signal });
    return observe;
  }

  it.each([
    ['Space', ' '],
    ['Enter', '{Enter}'],
    ['Shift-Space', '{Shift>} {/Shift}'],
  ])('keeps native %s artifact activation focused after the real 50ms consumer timer', async (_label, keys) => {
    const { card, user, onOpen } = await mountApp();
    for (let attempts = 0; document.activeElement !== card && attempts < 80; attempts += 1) {
      await user.tab();
    }
    expect(card).toHaveFocus();
    expectInactiveComposer();
    const observe = observeKeydown();
    const globalFocus = vi.fn();
    document.addEventListener('focusin', event => {
      if (event.target === globalInput()) globalFocus();
    }, { signal: listeners.signal });

    await user.keyboard(keys);
    expect(onOpen).toHaveBeenCalledExactlyOnceWith({ artifactId: DOC.id, threadId: 't1', opener: card });
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
    const dismiss = screen.getByRole('button', { name: 'Collapse artifacts' });
    expect(dismiss).toHaveFocus();
    const activationKey = keys === '{Enter}' ? 'Enter' : ' ';
    const observedActivation = observe.mock.calls.filter(([event]) => event.key === activationKey);
    expect(observedActivation).toHaveLength(1);
    expect(observedActivation[0][0].defaultPrevented).toBe(false);
    await advanceFocusTimer(49);
    expect(dismiss).toHaveFocus();
    await advanceFocusTimer(1);
    await advanceFocusTimer(100);
    expect.soft(dismiss).toHaveFocus();
    expect.soft(globalInput()).toBeNull();
    expect.soft(globalFocus).not.toHaveBeenCalled();
    expect.soft(useStore.getState().pendingChar).toBeFalsy();

    await user.keyboard(' ');
    await advanceFocusTimer(150);
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    expect(card).toHaveFocus();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expectInactiveComposer();
    expect(globalFocus).not.toHaveBeenCalled();
  });

  it.each(['span', 'svg', 'focus-moved'] as const)('leaves descendant Space uncancelled with %s event origin', async origin => {
    const { card, background, onOpen } = await mountApp();
    const descendant = card.querySelector(origin === 'svg' ? 'svg' : 'span');
    expect(descendant).not.toBeNull();
    card.focus();
    const moveFocus = vi.fn(() => background.focus());
    if (origin === 'focus-moved') {
      card.addEventListener('keydown', moveFocus, { signal: listeners.signal });
    }
    const observe = observeKeydown();
    const event = new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true, cancelable: true });
    act(() => { expect(descendant!.dispatchEvent(event)).toBe(true); });
    expect(observe).toHaveBeenCalledTimes(1);
    expect(observe.mock.results[0].value).toEqual({ target: descendant, defaultPrevented: false });
    if (origin === 'focus-moved') {
      expect(moveFocus).toHaveBeenCalledTimes(1);
      expect(background).toHaveFocus();
    }
    await advanceFocusTimer(150);
    expect(origin === 'focus-moved' ? background : card).toHaveFocus();
    expectInactiveComposer();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it.each([
    ['background letter', 'a', 'background', false],
    ['background Space', ' ', 'background', false],
    ['background Shift-letter', 'A', 'background', true],
    ['button non-Space', 'x', 'button', false],
    ['background focus moved to button', ' ', 'moving-background', false],
    ['non-Element window', ' ', 'window', false],
    ['non-Element document', 'a', 'document', false],
  ] as const)('preserves %s through the real delayed consumer', async (_label, key, origin, shiftKey) => {
    const { card, background } = await mountApp();
    const target = origin === 'button' ? card : origin === 'window' ? window
      : origin === 'document' ? document : background;
    if (origin === 'button') card.focus();
    else background.focus();
    const moveFocus = vi.fn(() => card.focus());
    if (origin === 'moving-background') {
      background.addEventListener('keydown', moveFocus, { signal: listeners.signal });
    }
    const focusBeforeKey = document.activeElement;
    const observe = observeKeydown();
    act(() => {
      expect(target.dispatchEvent(new KeyboardEvent('keydown', {
        key, shiftKey, bubbles: true, cancelable: true,
      }))).toBe(true);
    });
    expect(observe).toHaveBeenCalledTimes(1);
    if (origin === 'moving-background') expect(moveFocus).toHaveBeenCalledTimes(1);
    const input = globalInput();
    expect(input).not.toBeNull();
    expect(input).toHaveValue(key);
    expect(useStore.getState().pendingChar).toBeFalsy();
    expect(input).not.toHaveFocus();
    await advanceFocusTimer(49);
    expect(origin === 'moving-background' ? card : focusBeforeKey).toHaveFocus();
    await advanceFocusTimer(1);
    expect(input).toHaveFocus();
    expect(input).toHaveValue(key);
  });

  it.each(['ctrlKey', 'metaKey', 'altKey'] as const)('preserves the %s exclusion for background Space and letters', async modifier => {
    const { background } = await mountApp();
    background.focus();
    const observe = observeKeydown();
    for (const key of [' ', 'a']) {
      fireEvent.keyDown(background, { key, [modifier]: true });
      await advanceFocusTimer(150);
      expect(background).toHaveFocus();
      expectInactiveComposer();
    }
    expect(observe).toHaveBeenCalledTimes(2);
  });

  it.each(['Local input', 'Local textarea'])('preserves native Space and letter editing in %s', async label => {
    const { user } = await mountApp();
    const input = screen.getByRole('textbox', { name: label });
    await user.click(input);
    const observe = observeKeydown();
    await user.keyboard('a b');
    await advanceFocusTimer(150);
    expect(input).toHaveValue('a b');
    expect(input).toHaveFocus();
    expect(observe).toHaveBeenCalledTimes(3);
    expectInactiveComposer();
  });
});
