import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GamePanel } from '../components/GamePanel';
import { ProfileInfoTab } from '../components/profile/ProfileInfoTab';
import { useStore } from '../store/useStore';
import type { Agent, AgentProfileData } from '../store/types';

vi.mock('../audio/voice', () => ({
  getAvailableVoices: () => [],
  getServerPiperVoices: async () => [],
  speakResponse: vi.fn(),
}));

const fetchMock = vi.fn<typeof fetch>();
let sequence = 0;

function snapshot(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    game_id: 'game-1', game_type: 'tictactoe', board: Array(9).fill(''),
    current_player: 'Captain', status: 'in_progress', winner: '',
    valid_moves: ['0', '1', '2', '3', '4', '5', '6', '7', '8'], moves_count: 0,
    opponent: 'Ezri', opponent_agent_id: 'counselor-1', thread_id: 'thread-1',
    participants: ['Captain', 'Ezri'],
    revision: 1, opponent_turn_status: 'idle', opponent_turn_reason: '',
    turn_id: '', attempt_id: '', event_id: '', ...overrides,
  };
}

function reply(data: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => data } as Response;
}

function renderProfile(): ReturnType<typeof within> {
  const agent: Agent = {
    id: 'counselor-1', agentType: 'counselor', callsign: 'Ezri', displayName: 'Counselor',
    pool: 'counselor', state: 'active', confidence: 1, trust: 0.8, tier: 'domain',
    isCrew: true, position: [0, 0, 0],
  };
  const profile: AgentProfileData = {
    ...agent, rank: 'lieutenant', agencyLevel: 'autonomous', department: 'medical',
    personality: {}, specialization: [], trustHistory: [], hebbianConnections: [],
    memoryCount: 0, uptime: 0, proactiveCooldown: null,
  };
  useStore.setState({ refreshWardRoomDmChannels: vi.fn(async () => {}) });
  render(<div data-testid="profile-info"><ProfileInfoTab agent={agent} profileData={profile} /></div>);
  return within(screen.getByTestId('profile-info'));
}

function emit(type: string, data: Record<string, unknown>): void {
  useStore.getState().handleEvent({ type, data, timestamp: 1,
    stream: { generation: 'a'.repeat(32), sequence: sequence++ } });
}

async function mount(overrides: Record<string, unknown> = {}): Promise<void> {
  fetchMock.mockResolvedValueOnce(reply({ game: snapshot(overrides) }));
  act(() => emit('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
  }));
  await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
  expect(useStore.getState().activeGame?.gameId).toBe('game-1');
  fetchMock.mockClear();
  render(<GamePanel />);
}

beforeEach(() => {
  sequence = 0;
  localStorage.clear();
  useStore.setState({ ...useStore.getInitialState(), connected: true }, true);
  fetchMock.mockReset();
  fetchMock.mockRejectedValue(new Error('Unexpected fetch'));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('GamePanel', () => {
  it('does not render a tic-tac-toe panel or error for a valid chess game', async () => {
    await mount({ game_type: 'chess', board: Array.from({ length: 8 }, () => Array(8).fill('')) });
    expect(screen.queryByRole('region', { name: 'Tic-Tac-Toe game' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('names all nine cells by one-based row, column and occupancy', async () => {
    await mount({ board: ['X', '', '', '', 'O', '', '', '', ''], valid_moves: ['1', '2', '3', '5', '6', '7', '8'] });
    const board = screen.getByRole('group', { name: 'Game board' });
    expect(within(board).getAllByRole('button')).toHaveLength(9);
    for (let index = 0; index < 9; index += 1) {
      const occupancy = index === 0 ? 'X' : index === 4 ? 'O' : 'empty';
      expect(within(board).getByRole('button', {
        name: `Row ${Math.floor(index / 3) + 1}, column ${index % 3 + 1}, ${occupancy}`,
      })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Row 1, column 1, X' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Row 2, column 2, O' })).toBeDisabled();
  });

  it.each(['{Enter}', ' '])('submits a legal move using native keyboard activation %s', async key => {
    const user = userEvent.setup();
    await mount();
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(complete => { resolve = complete; }));
    const center = screen.getByRole('button', { name: 'Row 2, column 2, empty' });
    center.focus();
    expect(center).toHaveFocus();
    await user.keyboard(key);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/recreation/move');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ game_id: 'game-1', position: '4', revision: 1 });
    expect(screen.getByRole('status')).toHaveTextContent('Submitting move');
    expect(screen.getByRole('group', { name: 'Game board' })).toHaveAttribute('aria-busy', 'true');
    expect(within(screen.getByRole('group', { name: 'Game board' })).getAllByRole('button').every(button => button.hasAttribute('disabled'))).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Forfeit game' }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => resolve(reply(snapshot({ revision: 2, board: ['', '', '', '', 'X', '', '', '', ''],
      current_player: 'Ezri', opponent_turn_status: 'queued', valid_moves: ['0', '1', '2', '3', '5', '6', '7', '8'] }))));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Turn queued for Ezri'));
    expect(screen.getByRole('button', { name: 'Row 2, column 2, X' })).toBeDisabled();
  });

  it('includes legal cells in normal tab order', async () => {
    const user = userEvent.setup();
    await mount({ valid_moves: ['4'] });
    await user.tab();
    expect(screen.getByRole('button', { name: 'Forfeit game' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Row 2, column 2, empty' })).toHaveFocus();
  });

  it.each([
    { current_player: 'Ezri', opponent_turn_status: 'queued' },
    { current_player: 'Ezri', opponent_turn_status: 'thinking' },
    { current_player: 'Ezri', opponent_turn_status: 'recoverable' },
    { valid_moves: [] },
    { status: 'draw', valid_moves: [] },
  ])('blocks busy, wrong-turn, invalid and terminal cells: %j', async overrides => {
    const user = userEvent.setup();
    await mount(overrides);
    const center = screen.getByRole('button', { name: 'Row 2, column 2, empty' });
    expect(center).toBeDisabled();
    await user.click(center);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('distinguishes queued delivery from actual thinking and announces recovery', async () => {
    await mount({ current_player: 'Ezri', opponent_turn_status: 'queued' });
    expect(screen.getByRole('status')).toHaveTextContent('Turn queued for Ezri');
    expect(screen.getByRole('status')).not.toHaveTextContent('thinking');
    expect(screen.queryByRole('button', { name: 'Retry opponent turn' })).not.toBeInTheDocument();
    act(() => emit('game_update', snapshot({ revision: 2, current_player: 'Ezri', opponent_turn_status: 'thinking' })));
    expect(screen.getByRole('status')).toHaveTextContent('Ezri is thinking');
    act(() => emit('game_update', snapshot({ revision: 3, current_player: 'Ezri', opponent_turn_status: 'recoverable', opponent_turn_reason: 'deadline_expired' })));
    expect(screen.getByRole('status')).toHaveTextContent('Opponent turn timed out. Retry when ready.');
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('button', { name: 'Retry opponent turn' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Forfeit game' })).toBeEnabled();
  });

  it.each([
    ['actor_unavailable', 'Opponent is unavailable'],
    ['invalid_move', 'Opponent returned an invalid move'],
    ['no_usable_move', 'Opponent returned no move'],
    ['cognitive_failed', 'Opponent could not process the turn'],
    ['cognitive_cancelled', 'Opponent turn was interrupted'],
    ['service_stopped', 'Recreation has stopped'],
    ['unknown_reason', 'Opponent could not complete the turn'],
  ])('renders useful recovery feedback for %s', async (reason, message) => {
    await mount({ current_player: 'Ezri', opponent_turn_status: 'recoverable', opponent_turn_reason: reason });
    expect(screen.getByRole('status')).toHaveTextContent(message);
  });

  it('retries through the real store action and displays queued feedback', async () => {
    const user = userEvent.setup();
    await mount({ current_player: 'Ezri', opponent_turn_status: 'recoverable', opponent_turn_reason: 'deadline_expired' });
    fetchMock.mockResolvedValueOnce(reply(snapshot({ revision: 2, current_player: 'Ezri', opponent_turn_status: 'queued' })));
    const retry = screen.getByRole('button', { name: 'Retry opponent turn' });
    expect(retry).toHaveAttribute('title', 'Retry opponent turn');
    await user.click(retry);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/recreation/retry');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ game_id: 'game-1', revision: 1 });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Turn queued for Ezri'));
  });

  it('announces retry failure while preserving recoverable state', async () => {
    const user = userEvent.setup();
    await mount({ current_player: 'Ezri', opponent_turn_status: 'recoverable' });
    fetchMock.mockResolvedValueOnce(reply({ detail: 'Opponent unavailable' }, 503));
    await user.click(screen.getByRole('button', { name: 'Retry opponent turn' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Opponent unavailable');
    expect(screen.getByRole('button', { name: 'Retry opponent turn' })).toBeEnabled();
    expect(useStore.getState().activeGame?.opponentTurnStatus).toBe('recoverable');
  });

  it('announces failed forfeit without clearing the board', async () => {
    const user = userEvent.setup();
    await mount({ board: ['X', '', '', '', '', '', '', '', ''], valid_moves: ['1'] });
    fetchMock.mockResolvedValueOnce(reply({ detail: 'Forfeit failed' }, 500));
    await user.click(screen.getByRole('button', { name: 'Forfeit game' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Forfeit failed');
    expect(screen.getByRole('button', { name: 'Row 1, column 1, X' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Forfeit game' })).toBeEnabled();
    expect(useStore.getState().activeGame?.status).toBe('in_progress');
  });

  it('retains the terminal board after forfeit until explicitly closed', async () => {
    const user = userEvent.setup();
    await mount({ board: ['X', '', '', '', '', '', '', '', ''] });
    fetchMock.mockResolvedValueOnce(reply(snapshot({ revision: 2, status: 'forfeited',
      board: ['X', '', '', '', '', '', '', '', ''], valid_moves: [] })));
    await user.click(screen.getByRole('button', { name: 'Forfeit game' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Game forfeited'));
    expect(screen.getByRole('button', { name: 'Row 1, column 1, X' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Forfeit game' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close game' }));
    expect(screen.queryByRole('region', { name: 'Tic-Tac-Toe game' })).not.toBeInTheDocument();
  });

  it.each([['Captain', 'You won!'], ['Ezri', 'Ezri wins']])('keeps a coherent winning display for %s', async (winner, message) => {
    const board = winner === 'Captain' ? ['X', 'X', 'X', 'O', 'O', '', '', '', '']
      : ['O', 'O', 'O', 'X', 'X', '', 'X', '', ''];
    await mount({ status: 'won', winner, board, valid_moves: [] });
    expect(screen.getByRole('status')).toHaveTextContent(message);
    expect(screen.getByRole('button', { name: 'Close game' })).toBeEnabled();
  });

  it('disables actions while disconnected and repairs on a real state snapshot', async () => {
    await mount();
    act(() => useStore.getState().setConnected(false));
    expect(screen.getByRole('status')).toHaveTextContent('Disconnected');
    expect(screen.getByRole('button', { name: 'Forfeit game' })).toBeDisabled();
    fetchMock.mockResolvedValueOnce(reply({ game: null }));
    act(() => {
      useStore.getState().setConnected(true);
      emit('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 });
    });
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Tic-Tac-Toe game' })).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith('/api/recreation/active');
  });

  it('announces challenge failure even when no game was created', async () => {
    render(<GamePanel />);
    fetchMock.mockResolvedValueOnce(reply({ detail: 'Opponent unavailable' }, 503));
    await act(async () => useStore.getState().challengeAgent('counselor-1'));
    expect(screen.getByRole('alert')).toHaveTextContent('Opponent unavailable');
    expect(screen.queryByRole('group', { name: 'Game board' })).not.toBeInTheDocument();
  });
});

describe('ProfileInfoTab recreation integration', () => {
  it.each(['won', 'draw', 'forfeited'])('allows an explicit challenge after retained %s', async status => {
    const user = userEvent.setup();
    await mount({ status, winner: status === 'won' ? 'Captain' : '', valid_moves: [],
      board: ['X', 'X', 'X', 'O', 'O', '', '', '', ''] });
    const profile = renderProfile();
    const challenge = profile.getByRole('button', { name: 'Challenge to Tic-Tac-Toe' });
    expect(challenge).toBeEnabled();
    expect(useStore.getState().activeGame?.status).toBe(status);
    expect(screen.getByRole('button', { name: 'Row 1, column 1, X' })).toBeInTheDocument();
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: 'next-game' })));
    await user.click(challenge);
    await waitFor(() => expect(useStore.getState().activeGame?.gameId).toBe('next-game'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/recreation/challenge');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      opponent_agent_id: 'counselor-1', game_type: 'tictactoe',
    });
    expect(profile.getByRole('button', { name: 'Game in progress...' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Row 1, column 1, empty' })).toBeEnabled();
  });

  it('blocks in-progress challenges with truthful feedback', async () => {
    const user = userEvent.setup();
    await mount();
    const profile = renderProfile();
    const button = profile.getByRole('button', { name: 'Game in progress...' });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useStore.getState().activeGame?.status).toBe('in_progress');
  });

  it('announces pending submission and sends no duplicate challenge', async () => {
    const user = userEvent.setup();
    const profile = renderProfile();
    render(<GamePanel />);
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(complete => { resolve = complete; }));
    await user.click(profile.getByRole('button', { name: 'Challenge to Tic-Tac-Toe' }));
    expect(useStore.getState().gamePending).toBe('challenge');
    const blocked = profile.getByRole('button', { name: 'Submitting game request...' });
    expect(blocked).toBeDisabled();
    expect(profile.getByRole('status')).toHaveTextContent('Submitting game request');
    await user.click(blocked);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => resolve(reply(snapshot())));
    await waitFor(() => expect(useStore.getState().gamePending).toBeNull());
    expect(screen.getByRole('group', { name: 'Game board' })).toBeInTheDocument();
  });

  it('announces disconnection and blocks challenge submission', async () => {
    const user = userEvent.setup();
    useStore.getState().setConnected(false);
    const profile = renderProfile();
    const button = profile.getByRole('button', { name: 'Disconnected' });
    expect(button).toBeDisabled();
    expect(profile.getByRole('status')).toHaveTextContent('Disconnected');
    await user.click(button);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useStore.getState().gamePending).toBeNull();
  });

  it('requires a fresh explicit click after refresh and never queues the blocked click', async () => {
    const user = userEvent.setup();
    await mount({ status: 'draw', valid_moves: [] });
    const retained = useStore.getState().activeGame;
    const profile = renderProfile();
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(complete => { resolve = complete; }));
    let refreshing!: Promise<void>;
    act(() => { refreshing = useStore.getState().refreshActiveGame(); });
    const blocked = profile.getByRole('button', { name: 'Refreshing game state...' });
    expect(blocked).toBeDisabled();
    expect(profile.getByRole('status')).toHaveTextContent('Refreshing');
    await user.click(blocked);
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/active']);
    expect(useStore.getState().gamePending).toBeNull();
    await act(async () => { resolve(reply({ game: null })); await refreshing; });
    expect(useStore.getState().activeGame).toBe(retained);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const enabled = profile.getByRole('button', { name: 'Challenge to Tic-Tac-Toe' });
    expect(enabled).toBeEnabled();
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: 'fresh-game' })));
    await user.click(enabled);
    await waitFor(() => expect(useStore.getState().activeGame?.gameId).toBe('fresh-game'));
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/active', '/api/recreation/challenge']);
    expect(screen.getByRole('button', { name: 'Row 2, column 2, empty' })).toBeEnabled();
  });

  it('shows refresh failure and clears only that feedback after successful recovery', async () => {
    const user = userEvent.setup();
    const profile = renderProfile();
    render(<GamePanel />);
    fetchMock.mockResolvedValueOnce(reply({}, 503));
    await act(async () => useStore.getState().refreshActiveGame());
    expect(profile.getByRole('alert')).toHaveTextContent('Game state could not be refreshed');
    expect(useStore.getState().gameSyncing).toBe(false);
    fetchMock.mockResolvedValueOnce(reply({ game: null }));
    await act(async () => useStore.getState().refreshActiveGame());
    expect(profile.queryByRole('alert')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/active', '/api/recreation/active']);
    fetchMock.mockResolvedValueOnce(reply(snapshot()));
    await user.click(profile.getByRole('button', { name: 'Challenge to Tic-Tac-Toe' }));
    await waitFor(() => expect(useStore.getState().activeGame?.gameId).toBe('game-1'));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('group', { name: 'Game board' })).toBeInTheDocument();
  });
});