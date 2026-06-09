// AD-946: integration test for the omnibox command palette (leading '>').
// Mirrors the IntentSurface.pickerKeyboard / atMention harness (render the
// surface, open the shell via the pill, drive the input by its placeholder,
// seed the REAL store, stub global.fetch). The headline case is the NL
// regression guard: a plain question (no '>') still submits via /api/chat
// byte-for-byte and never opens the palette.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

// Capture the real store actions so per-test spies stay isolated.
const realOpenWardRoom = useStore.getState().openWardRoom;
const realOpenPersonnelConsole = useStore.getState().openPersonnelConsole;

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map(),
    // The registry the palette derives its launches from needs these slices.
    wardRoomDmChannels: [],
    missionControlTasks: [],
    wardRoomUnread: {},
    mainViewer: 'canvas',
  });
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ response: '', mentions: [], per_agent_replies: [] }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // Restore the real actions + reset the seeded slices so tests stay isolated.
  useStore.setState({
    openWardRoom: realOpenWardRoom,
    openPersonnelConsole: realOpenPersonnelConsole,
    mainViewer: 'canvas',
    chatHistory: [],
    wardRoomDmChannels: [],
    missionControlTasks: [],
    wardRoomUnread: {},
  });
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  return input;
}

function chatCalls(): unknown[][] {
  return (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.filter(
    (c) => c[0] === '/api/chat',
  );
}

describe('AD-946 IntentSurface command palette (leading ">")', () => {
  it('>ward → Enter runs the Ward Room launch, never a chat submit', () => {
    const openWardRoom = vi.fn();
    useStore.setState({ openWardRoom });
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '>ward' } });
    expect(screen.queryByTestId('command-palette')).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(openWardRoom).toHaveBeenCalledTimes(1);
    expect(chatCalls().length).toBe(0);
    expect(input.value).toBe('');
    expect(screen.queryByTestId('command-palette')).toBeNull();
  });

  it('>work → Enter fires the same setState the Bridge fires (mainViewer:work)', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '>work' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(useStore.getState().mainViewer).toBe('work');
    expect(chatCalls().length).toBe(0);
  });

  it('ArrowDown then Enter runs the SECOND match', () => {
    const openPersonnelConsole = vi.fn();
    useStore.setState({ openPersonnelConsole });
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    // '>personnel' matches all three Personnel launches: Crew, Personnel, Metrics.
    fireEvent.change(input, { target: { value: '>personnel' } });
    fireEvent.keyDown(input, { key: 'ArrowDown' }); // index 0 → 1 (the Personnel launch)
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(openPersonnelConsole).toHaveBeenCalledTimes(1);
  });

  it('Esc closes the palette on the first press without collapsing the shell', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '>ward' } });
    expect(screen.queryByTestId('command-palette')).toBeTruthy();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('command-palette')).toBeNull();
    // The shell stays active (the input is still mounted).
    expect(document.querySelector('input[placeholder="Ask ProbOS..."]')).toBeTruthy();
  });

  it('NL GUARANTEE: a plain question (no ">") submits via /api/chat and never opens the palette', async () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    const form = input.closest('form') as HTMLFormElement;
    expect(screen.queryByTestId('command-palette')).toBeNull();
    fireEvent.change(input, { target: { value: 'what is the weather' } });
    // Still no palette for a non-'>' input.
    expect(screen.queryByTestId('command-palette')).toBeNull();
    await act(async () => {
      fireEvent.submit(form);
      await Promise.resolve();
      await Promise.resolve();
    });
    // The NL path ran: user message added + /api/chat POSTed.
    expect(chatCalls().length).toBe(1);
    const history = useStore.getState().chatHistory;
    expect(history.some((m) => m.role === 'user' && m.text === 'what is the weather')).toBe(true);
    expect(screen.queryByTestId('command-palette')).toBeNull();
  });

  it('belt-and-suspenders: ">zzz" (no matches) submit is a no-op, never a chat POST', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    const form = input.closest('form') as HTMLFormElement;
    fireEvent.change(input, { target: { value: '>zzz' } });
    expect(() => fireEvent.submit(form)).not.toThrow();
    expect(chatCalls().length).toBe(0);
    expect(input.value).toBe('');
  });
});
