import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { GAME_TOMBSTONE_LIMIT, useStore } from '../store/useStore';
import type { WSEvent } from '../store/types';

const GENERATION = 'a'.repeat(32);
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

function deferred(): { promise: Promise<Response>; resolve: (response: Response) => void } {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(complete => { resolve = complete; });
  return { promise, resolve };
}

function emit(type: string, data: Record<string, unknown>, generation = GENERATION): void {
  const event: WSEvent = { type, data, timestamp: 1, stream: { generation, sequence: sequence++ } };
  useStore.getState().handleEvent(event);
}

async function connect(game: Record<string, unknown> | null = snapshot()): Promise<void> {
  fetchMock.mockResolvedValueOnce(reply({ game }));
  emit('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 });
  await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
  expect(fetchMock).toHaveBeenCalledWith('/api/recreation/active');
  expect(useStore.getState().activeGame?.gameId ?? null).toBe(game?.game_id ?? null);
  fetchMock.mockClear();
}

function recreationState() {
  const state = useStore.getState();
  return {
    activeGame: state.activeGame, gamePending: state.gamePending, gameSyncing: state.gameSyncing,
    gameError: state.gameError, gameRequestGeneration: state.gameRequestGeneration,
    gameConnectionGeneration: state.gameConnectionGeneration,
    gameHydrationGeneration: state.gameHydrationGeneration, gameSnapshotEpoch: state.gameSnapshotEpoch,
    gameChallengeAgentId: state.gameChallengeAgentId, gameTombstones: state.gameTombstones,
  };
}

async function evictFirstRetiredGame(): Promise<void> {
  expect(useStore.getState().gameTombstones.has('game-1')).toBe(true);
  for (let index = 0; index <= GAME_TOMBSTONE_LIMIT; index += 1) {
    const before = recreationState();
    const gameId = `retired-${index}`;
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: gameId })));
    await useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().activeGame?.gameId).toBe(gameId);
    emit('game_update', snapshot({ game_id: gameId, revision: 2, status: 'draw', valid_moves: [] }));
    expect(useStore.getState().activeGame?.status).toBe('draw');
    expect(useStore.getState().gameTombstones.size).toBeLessThanOrEqual(GAME_TOMBSTONE_LIMIT);
    expect(useStore.getState().gameRequestGeneration).toBeGreaterThan(before.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBeGreaterThan(before.gameSnapshotEpoch);
    expect(useStore.getState().gameConnectionGeneration).toBe(before.gameConnectionGeneration);
    expect(useStore.getState().gameHydrationGeneration).toBe(before.gameHydrationGeneration);
  }
  expect(useStore.getState().gameTombstones.size).toBe(GAME_TOMBSTONE_LIMIT);
  expect(useStore.getState().gameTombstones.has('game-1')).toBe(false);
  expect(useStore.getState().gameTombstones.has('retired-0')).toBe(false);
  expect(useStore.getState().gamePending).toBeNull();
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
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('recreation reconciliation', () => {
  it('preserves a valid chess snapshot without reporting a tic-tac-toe refresh failure', async () => {
    const board = Array.from({ length: 8 }, () => Array(8).fill(''));
    board[0][0] = 'r';
    await connect(snapshot({ game_type: 'chess', board, valid_moves: ['e2e4'] }));
    expect(useStore.getState().activeGame?.gameType).toBe('chess');
    expect(useStore.getState().activeGame?.board).toEqual(board);
    expect(useStore.getState().gameError).toBeNull();
  });

  it('hydrates the exact server projection, including zero counts and empty fields', async () => {
    await connect();
    expect(useStore.getState().activeGame).toMatchObject({
      revision: 1, movesCount: 0, currentPlayer: 'Captain', winner: '',
      opponentAgentId: 'counselor-1', opponentTurnStatus: 'idle', opponentTurnReason: '',
      turnId: '', attemptId: '', eventId: '', validMoves: ['0', '1', '2', '3', '4', '5', '6', '7', '8'],
    });
  });

  it('ignores older, duplicate and nonmatching event snapshots', async () => {
    await connect();
    emit('game_update', snapshot({ revision: 4, board: ['O', '', '', '', 'X', '', '', '', ''], moves_count: 2 }));
    const accepted = useStore.getState().activeGame;
    expect(accepted?.revision).toBe(4);
    emit('game_update', snapshot({ revision: 3 }));
    emit('game_update', snapshot({ revision: 4 }));
    emit('game_update', snapshot({ game_id: 'unrelated', revision: 99 }));
    emit('game_update', snapshot({ opponent_agent_id: 'replacement', revision: 99 }));
    expect(useStore.getState().activeGame).toBe(accepted);
  });

  it('keeps an opponent move that arrives before the Captain move response', async () => {
    await connect();
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const moving = useStore.getState().makeGameMove('4');
    expect(useStore.getState().gamePending).toBe('move');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ game_id: 'game-1', position: '4', revision: 1 });
    emit('game_update', snapshot({ revision: 4, moves_count: 2, board: ['O', '', '', '', 'X', '', '', '', ''] }));
    expect(useStore.getState().activeGame?.movesCount).toBe(2);
    delayed.resolve(reply(snapshot({ revision: 2, current_player: 'Ezri', opponent_turn_status: 'queued', moves_count: 1 })));
    await moving;
    expect(useStore.getState().activeGame?.board[0]).toBe('O');
    expect(useStore.getState().activeGame?.revision).toBe(4);
    expect(useStore.getState().gamePending).toBeNull();
  });

  it('confirms the initial event before the challenge response without regressing it', async () => {
    await connect(null);
    const delayed = deferred();
    const confirmation = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    fetchMock.mockReturnValueOnce(confirmation.promise);
    const challenge = useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().gamePending).toBe('challenge');
    const pending = recreationState();
    emit('game_update', snapshot({ opponent_agent_id: 'other', game_id: 'other' }));
    expect(useStore.getState().activeGame).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    emit('game_update', snapshot({ revision: 3, opponent_turn_status: 'thinking', current_player: 'Ezri' }));
    expect(useStore.getState().activeGame).toBeNull();
    expect(useStore.getState().gameRequestGeneration).toBe(pending.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBe(pending.gameSnapshotEpoch);
    expect(useStore.getState().gameHydrationGeneration).toBe(pending.gameHydrationGeneration + 1);
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/challenge', '/api/recreation/active']);
    confirmation.resolve(reply({ game: snapshot({ revision: 3, opponent_turn_status: 'thinking', current_player: 'Ezri' }) }));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame?.revision).toBe(3);
    expect(useStore.getState().gamePending).toBe('challenge');
    delayed.resolve(reply(snapshot()));
    await challenge;
    expect(useStore.getState().activeGame?.revision).toBe(3);
    expect(useStore.getState().activeGame?.opponentTurnStatus).toBe('thinking');
    expect(useStore.getState().gamePending).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('blocks duplicate challenges before any response or event', async () => {
    await connect(null);
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const first = useStore.getState().challengeAgent('counselor-1');
    await useStore.getState().challengeAgent('counselor-1');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    delayed.resolve(reply(snapshot()));
    await first;
    expect(useStore.getState().activeGame?.gameId).toBe('game-1');
  });

  it('blocks all duplicate mutation clicks while a request is pending', async () => {
    await connect();
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const first = useStore.getState().makeGameMove('4');
    await useStore.getState().makeGameMove('0');
    await useStore.getState().forfeitGame();
    await useStore.getState().challengeAgent('other');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    delayed.resolve(reply(snapshot({ revision: 2, current_player: 'Ezri', opponent_turn_status: 'queued' })));
    await first;
  });

  it.each([
    { current_player: 'Ezri' }, { valid_moves: ['0'] }, { status: 'draw', valid_moves: [] },
  ])('blocks moves outside the authoritative turn and legal cells: %j', async overrides => {
    await connect(snapshot(overrides));
    await useStore.getState().makeGameMove('4');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ignores empty input and actions without a game', async () => {
    await connect(null);
    await useStore.getState().challengeAgent(' ');
    await useStore.getState().makeGameMove('');
    await useStore.getState().retryGame();
    await useStore.getState().forfeitGame();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('retries only a recoverable opponent turn with the current revision', async () => {
    await connect(snapshot({ revision: 5, current_player: 'Ezri', opponent_turn_status: 'recoverable' }));
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const retrying = useStore.getState().retryGame();
    await useStore.getState().retryGame();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/recreation/retry');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ game_id: 'game-1', revision: 5 });
    emit('game_update', snapshot({ revision: 7, current_player: 'Ezri', opponent_turn_status: 'thinking' }));
    delayed.resolve(reply(snapshot({ revision: 6, current_player: 'Ezri', opponent_turn_status: 'queued' })));
    await retrying;
    expect(useStore.getState().activeGame?.opponentTurnStatus).toBe('thinking');
    await useStore.getState().retryGame();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not retry a Captain turn', async () => {
    await connect(snapshot({ opponent_turn_status: 'recoverable' }));
    await useStore.getState().retryGame();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('repairs a stale request using the real active endpoint', async () => {
    await connect();
    fetchMock.mockResolvedValueOnce(reply({ detail: 'Stale game revision' }, 409));
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot({ revision: 8, current_player: 'Ezri', opponent_turn_status: 'recoverable' }) }));
    await useStore.getState().makeGameMove('4');
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/move', '/api/recreation/active']);
    expect(useStore.getState().activeGame?.revision).toBe(8);
    expect(useStore.getState().gameError).toBe('Stale game revision');
    expect(useStore.getState().gamePending).toBeNull();
  });

  it.each([403, 500])('preserves the board and displays HTTP %i forfeit failure', async status => {
    await connect();
    const before = useStore.getState().activeGame;
    fetchMock.mockResolvedValueOnce(reply({ detail: 'Forfeit denied' }, status));
    await useStore.getState().forfeitGame();
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ game_id: 'game-1', revision: 1 });
    expect(useStore.getState().activeGame).toBe(before);
    expect(useStore.getState().gameError).toBe('Forfeit denied');
    expect(useStore.getState().gamePending).toBeNull();
  });

  it('preserves a truthful game after network failure', async () => {
    await connect();
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    await useStore.getState().forfeitGame();
    expect(useStore.getState().activeGame?.status).toBe('in_progress');
    expect(useStore.getState().gameError).toMatch(/connection/);
  });

  it('retains the terminal forfeit snapshot and rejects resurrection after close', async () => {
    await connect();
    fetchMock.mockResolvedValueOnce(reply(snapshot({ revision: 2, status: 'forfeited', valid_moves: [] })));
    await useStore.getState().forfeitGame();
    expect(useStore.getState().activeGame?.status).toBe('forfeited');
    expect(useStore.getState().gameTombstones.has('game-1')).toBe(true);
    useStore.getState().closeGame();
    emit('game_update', snapshot({ revision: 99 }));
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot({ revision: 99 }) }));
    await useStore.getState().refreshActiveGame();
    expect(useStore.getState().activeGame).toBeNull();
  });

  it('does not hide an active game through closeGame', async () => {
    await connect();
    useStore.getState().closeGame();
    expect(useStore.getState().activeGame?.status).toBe('in_progress');
  });

  it('repairs unknown-game forfeit using null active instead of inventing a terminal board', async () => {
    await connect();
    fetchMock.mockResolvedValueOnce(reply({ status: 'forfeited' }));
    fetchMock.mockResolvedValueOnce(reply({ game: null }));
    await useStore.getState().forfeitGame();
    expect(fetchMock.mock.calls[1][0]).toBe('/api/recreation/active');
    expect(useStore.getState().activeGame).toBeNull();
    expect(useStore.getState().gameTombstones.has('game-1')).toBe(true);
  });

  it('ignores a late move response after a terminal event and a new challenge', async () => {
    await connect();
    const old = deferred();
    fetchMock.mockReturnValueOnce(old.promise);
    const moving = useStore.getState().makeGameMove('4');
    expect(useStore.getState().gamePending).toBe('move');
    emit('game_update', snapshot({ revision: 5, status: 'won', winner: 'Ezri',
      board: ['O', 'O', 'O', 'X', 'X', '', '', '', ''], valid_moves: [] }));
    expect(useStore.getState().activeGame?.status).toBe('won');
    expect(useStore.getState().gamePending).toBeNull();
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: 'game-2' })));
    await useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
    old.resolve(reply(snapshot({ revision: 2 })));
    await moving;
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
  });

  it('ignores an old forfeit response after its event and a new challenge', async () => {
    await connect();
    const old = deferred();
    fetchMock.mockReturnValueOnce(old.promise);
    const forfeiting = useStore.getState().forfeitGame();
    expect(useStore.getState().gamePending).toBe('forfeit');
    emit('game_update', snapshot({ revision: 2, status: 'forfeited', valid_moves: [] }));
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: 'game-2' })));
    await useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
    old.resolve(reply(snapshot({ revision: 2, status: 'forfeited', valid_moves: [] })));
    await forfeiting;
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
  });

  it('ignores a late failed request after terminal state and a new challenge', async () => {
    await connect();
    const old = deferred();
    fetchMock.mockReturnValueOnce(old.promise);
    const moving = useStore.getState().makeGameMove('4');
    emit('game_update', snapshot({ revision: 2, status: 'draw', valid_moves: [] }));
    fetchMock.mockResolvedValueOnce(reply(snapshot({ game_id: 'game-2' })));
    await useStore.getState().challengeAgent('counselor-1');
    old.resolve(reply({ detail: 'Old failure' }, 409));
    await moving;
    expect(useStore.getState().gameError).toBeNull();
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
  });

  it('rejects old connection HTTP and events after reconnect clears an abandoned game', async () => {
    await connect();
    const old = deferred();
    fetchMock.mockReturnValueOnce(old.promise);
    const moving = useStore.getState().makeGameMove('4');
    useStore.getState().setConnected(false);
    await useStore.getState().makeGameMove('0');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    useStore.getState().setConnected(true);
    fetchMock.mockResolvedValueOnce(reply({ game: null }));
    emit('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 }, 'b'.repeat(32));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame).toBeNull();
    old.resolve(reply(snapshot({ revision: 2 })));
    await moving;
    emit('game_update', snapshot({ revision: 9 }));
    expect(useStore.getState().activeGame).toBeNull();
  });

  it('repairs resync_required and preserves terminal display on null active', async () => {
    await connect();
    emit('game_update', snapshot({ revision: 2, status: 'draw', valid_moves: [] }));
    fetchMock.mockResolvedValueOnce(reply({ game: null }));
    emit('resync_required', {});
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(fetchMock).toHaveBeenCalledWith('/api/recreation/active');
    expect(useStore.getState().activeGame?.status).toBe('draw');
  });

  it('ignores delayed null hydration after a newer event', async () => {
    await connect();
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const refreshing = useStore.getState().refreshActiveGame();
    expect(useStore.getState().gameSyncing).toBe(true);
    emit('game_update', snapshot({ revision: 3 }));
    delayed.resolve(reply({ game: null }));
    await refreshing;
    expect(useStore.getState().activeGame?.revision).toBe(3);
    expect(useStore.getState().gameTombstones.has('game-1')).toBe(false);
  });

  it('accepts a newer same-game hydration revision after an intervening event', async () => {
    await connect();
    const delayed = deferred();
    fetchMock.mockReturnValueOnce(delayed.promise);
    const refreshing = useStore.getState().refreshActiveGame();
    expect(useStore.getState().gameSyncing).toBe(true);
    emit('game_update', snapshot({ revision: 3 }));
    expect(useStore.getState().activeGame?.revision).toBe(3);
    delayed.resolve(reply({ game: snapshot({ revision: 5 }) }));
    await refreshing;
    expect(useStore.getState().activeGame?.revision).toBe(5);
  });

  it('checks request generation again after a delayed JSON body', async () => {
    await connect();
    let resolveBody!: (data: unknown) => void;
    const body = new Promise<unknown>(resolve => { resolveBody = resolve; });
    const json = vi.fn(() => body);
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json } as unknown as Response);
    const moving = useStore.getState().makeGameMove('4');
    await waitFor(() => expect(json).toHaveBeenCalledOnce());
    emit('game_update', snapshot({ revision: 5, status: 'forfeited', valid_moves: [] }));
    useStore.getState().closeGame();
    resolveBody(snapshot({ revision: 2 }));
    await moving;
    expect(useStore.getState().activeGame).toBeNull();
    expect(useStore.getState().gamePending).toBeNull();
  });

  it('ignores superseded hydration and blocks moves until the latest hydration finishes', async () => {
    await connect();
    const old = deferred();
    fetchMock.mockReturnValueOnce(old.promise);
    const refreshing = useStore.getState().refreshActiveGame();
    await useStore.getState().makeGameMove('4');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot({ game_id: 'game-2' }) }));
    await useStore.getState().refreshActiveGame();
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
    old.resolve(reply({ game: null }));
    await refreshing;
    expect(useStore.getState().activeGame?.gameId).toBe('game-2');
  });

  it.each([{}, { game: {} }, { game: snapshot({ revision: -1 }) }, { game: snapshot({ board: [] }) }])(
    'preserves truthful state on malformed active response %j', async data => {
      await connect();
      fetchMock.mockResolvedValueOnce(reply(data));
      await useStore.getState().refreshActiveGame();
      expect(useStore.getState().activeGame?.revision).toBe(1);
      expect(useStore.getState().gameError).toMatch(/could not be refreshed/);
    },
  );

  it('ignores malformed live snapshots and repairs malformed successful HTTP', async () => {
    await connect();
    emit('game_update', snapshot({ revision: '2' }));
    expect(useStore.getState().activeGame?.revision).toBe(1);
    fetchMock.mockResolvedValueOnce(reply({}));
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot({ revision: 2 }) }));
    await useStore.getState().makeGameMove('4');
    expect(useStore.getState().activeGame?.revision).toBe(2);
    expect(useStore.getState().gameError).toMatch(/Invalid game response/);
  });

  it('hydrates unsolicited initial game events through authoritative active state', async () => {
    await connect(null);
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot() }));
    emit('game_update', snapshot());
    await waitFor(() => expect(useStore.getState().activeGame?.gameId).toBe('game-1'));
    expect(fetchMock).toHaveBeenCalledWith('/api/recreation/active');
  });

  it.each([['Captain', 'Ezri'], ['Ezri', 'Captain']])('retains authoritative participant order %j, %j', async (first, second) => {
    await connect(snapshot({ participants: [first, second] }));
    expect(useStore.getState().activeGame?.participants).toEqual([first, second]);
    expect(useStore.getState().activeGame?.opponentAgentId).toBe('counselor-1');
  });

  it.each([null, undefined, {}, 'Captain', [], ['Captain'], ['Captain', 'Ezri', 'Lynx'],
    ['Captain', null], ['Captain', 1], ['Captain', ''], ['Captain', ' Ezri'], ['Captain', '   ']])(
    'rejects explicitly malformed participants in events and hydration: %j', async participants => {
      await connect();
      const before = recreationState();
      emit('game_update', snapshot({ game_id: 'malformed', participants }));
      expect(recreationState()).toEqual(before);
      expect(fetchMock).not.toHaveBeenCalled();
      fetchMock.mockResolvedValueOnce(reply({ game: snapshot({ participants }) }));
      await useStore.getState().refreshActiveGame();
      expect(useStore.getState().activeGame).toBe(before.activeGame);
      expect(useStore.getState().gameError).toMatch(/could not be refreshed/);
      expect(useStore.getState().gameSnapshotEpoch).toBe(before.gameSnapshotEpoch);
    },
  );

  it('rejects malformed response participants without treating corruption as no game', async () => {
    await connect();
    const before = useStore.getState().activeGame;
    fetchMock.mockResolvedValueOnce(reply(snapshot({ participants: null, revision: 2 })));
    fetchMock.mockResolvedValueOnce(reply({ game: snapshot() }));
    await useStore.getState().makeGameMove('4');
    expect(useStore.getState().activeGame).toBe(before);
    expect(useStore.getState().gameError).toMatch(/Invalid game response/);
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['/api/recreation/move', '/api/recreation/active']);
  });

  it('accepts genuinely absent legacy participants only through authoritative hydration or correlated responses', async () => {
    const legacy = snapshot();
    delete legacy.participants;
    await connect(null);
    const before = recreationState();
    emit('game_update', legacy);
    expect(recreationState()).toEqual(before);
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(reply(legacy));
    await useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().activeGame?.gameId).toBe('game-1');
    expect(useStore.getState().activeGame?.participants).toBeUndefined();
    fetchMock.mockResolvedValueOnce(reply({ game: { ...legacy, revision: 2 } }));
    await useStore.getState().refreshActiveGame();
    expect(useStore.getState().activeGame?.revision).toBe(2);
    expect(useStore.getState().gameError).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(['empty', 'terminal', 'pending'])('ignores repeated crew-only events with %s Captain state', async scenario => {
    await connect(scenario === 'terminal' ? snapshot({ status: 'draw', valid_moves: [] }) : null);
    const response = deferred();
    let challenge: Promise<void> | undefined;
    if (scenario === 'pending') {
      fetchMock.mockReturnValueOnce(response.promise);
      challenge = useStore.getState().challengeAgent('counselor-1');
      expect(useStore.getState().gamePending).toBe('challenge');
    }
    const before = recreationState();
    for (let index = 0; index < 5; index += 1) {
      emit('game_update', snapshot({ game_id: `crew-${index}`, participants: ['Lynx', 'Ezri'],
        opponent: 'Ezri', opponent_agent_id: 'counselor-1', revision: index + 1 }));
      expect(recreationState()).toEqual(before);
    }
    expect(fetchMock).toHaveBeenCalledTimes(scenario === 'pending' ? 1 : 0);
    expect(fetchMock.mock.calls.filter(call => call[0] === '/api/recreation/active')).toHaveLength(0);
    if (challenge) {
      response.resolve(reply(snapshot()));
      await challenge;
      expect(useStore.getState().activeGame?.gameId).toBe('game-1');
    }
  });

  it('requires authority for an evicted ID and preserves a newer same-opponent challenge across stale and null replies', async () => {
    await connect();
    const oldResponse = deferred();
    fetchMock.mockReturnValueOnce(oldResponse.promise);
    const oldMove = useStore.getState().makeGameMove('4');
    expect(useStore.getState().gamePending).toBe('move');
    emit('game_update', snapshot({ revision: 2, status: 'draw', valid_moves: [] }));
    await evictFirstRetiredGame();
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 2);
    const retired = useStore.getState().activeGame;
    const newResponse = deferred();
    fetchMock.mockReturnValueOnce(newResponse.promise);
    const challenge = useStore.getState().challengeAgent('counselor-1');
    expect(useStore.getState().gamePending).toBe('challenge');
    const pending = recreationState();
    const nullRepair = deferred();
    fetchMock.mockReturnValueOnce(nullRepair.promise);
    for (let index = 0; index < 5; index += 1) emit('game_update', snapshot({ revision: 99 + index }));
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 4);
    expect(fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[0]).toBe('/api/recreation/active');
    expect(useStore.getState().activeGame).toBe(retired);
    expect(useStore.getState().gameRequestGeneration).toBe(pending.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBe(pending.gameSnapshotEpoch);
    expect(useStore.getState().gameHydrationGeneration).toBe(pending.gameHydrationGeneration + 1);
    expect(useStore.getState().gamePending).toBe('challenge');
    expect(useStore.getState().gameSyncing).toBe(true);
    oldResponse.resolve(reply(snapshot({ revision: 50 })));
    await oldMove;
    expect(useStore.getState().activeGame).toBe(retired);
    expect(useStore.getState().gameRequestGeneration).toBe(pending.gameRequestGeneration);
    expect(useStore.getState().gamePending).toBe('challenge');
    nullRepair.resolve(reply({ game: null }));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame).toBe(retired);
    expect(useStore.getState().gamePending).toBe('challenge');
    expect(useStore.getState().gameChallengeAgentId).toBe('counselor-1');
    expect(useStore.getState().gameRequestGeneration).toBe(pending.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBe(pending.gameSnapshotEpoch);
    const staleRepair = deferred();
    fetchMock.mockReturnValueOnce(staleRepair.promise);
    emit('game_update', snapshot({ revision: 200 }));
    expect(useStore.getState().gameSyncing).toBe(true);
    expect(useStore.getState().gameHydrationGeneration).toBe(pending.gameHydrationGeneration + 2);
    await useStore.getState().makeGameMove('4');
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 5);
    newResponse.resolve(reply(snapshot({ game_id: 'fresh-game', board: ['X', '', '', '', '', '', '', '', ''] })));
    await challenge;
    expect(useStore.getState().activeGame?.gameId).toBe('fresh-game');
    expect(useStore.getState().gamePending).toBeNull();
    expect(useStore.getState().gameSnapshotEpoch).toBe(pending.gameSnapshotEpoch + 1);
    staleRepair.resolve(reply({ game: snapshot({ revision: 200 }) }));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame?.gameId).toBe('fresh-game');
    expect(useStore.getState().activeGame?.board[0]).toBe('X');
    expect(useStore.getState().gameRequestGeneration).toBe(pending.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBe(pending.gameSnapshotEpoch + 1);
    expect(useStore.getState().gameConnectionGeneration).toBe(pending.gameConnectionGeneration);
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 5);
  });

  it('rejects evicted-game callbacks across reconnect and accepts a fresh game only after current confirmation', async () => {
    await connect();
    emit('game_update', snapshot({ revision: 2, status: 'draw', valid_moves: [] }));
    await evictFirstRetiredGame();
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 1);
    const retired = useStore.getState().activeGame;
    const oldChallengeResponse = deferred();
    fetchMock.mockReturnValueOnce(oldChallengeResponse.promise);
    const oldChallenge = useStore.getState().challengeAgent('counselor-1');
    const oldRepair = deferred();
    fetchMock.mockReturnValueOnce(oldRepair.promise);
    emit('game_update', snapshot({ revision: 99 }));
    expect(useStore.getState().gamePending).toBe('challenge');
    expect(useStore.getState().gameSyncing).toBe(true);
    const beforeReconnect = recreationState();
    useStore.getState().setConnected(false);
    useStore.getState().setConnected(true);
    const currentRepair = deferred();
    fetchMock.mockReturnValueOnce(currentRepair.promise);
    emit('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 }, 'b'.repeat(32));
    const reconnecting = recreationState();
    expect(reconnecting.gameConnectionGeneration).toBeGreaterThan(beforeReconnect.gameConnectionGeneration);
    expect(reconnecting.gameRequestGeneration).toBeGreaterThan(beforeReconnect.gameRequestGeneration);
    expect(reconnecting.gameHydrationGeneration).toBeGreaterThan(beforeReconnect.gameHydrationGeneration);
    expect(reconnecting.gameSnapshotEpoch).toBeGreaterThanOrEqual(beforeReconnect.gameSnapshotEpoch);
    oldChallengeResponse.resolve(reply(snapshot({ revision: 99 })));
    await oldChallenge;
    oldRepair.resolve(reply({ game: snapshot({ revision: 99 }) }));
    await Promise.resolve();
    expect(recreationState()).toEqual(reconnecting);
    expect(useStore.getState().gameSyncing).toBe(true);
    currentRepair.resolve(reply({ game: null }));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame).toBe(retired);
    expect(useStore.getState().gamePending).toBeNull();
    const hydrated = recreationState();
    emit('game_update', snapshot({ revision: 500 }));
    expect(recreationState()).toEqual(hydrated);
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 4);
    const confirmation = deferred();
    fetchMock.mockReturnValueOnce(confirmation.promise);
    for (let index = 0; index < 5; index += 1) {
      emit('game_update', snapshot({ game_id: 'confirmed-game', revision: 3 }), 'b'.repeat(32));
    }
    expect(fetchMock).toHaveBeenCalledTimes(GAME_TOMBSTONE_LIMIT + 5);
    expect(useStore.getState().activeGame).toBe(retired);
    expect(useStore.getState().gamePending).toBeNull();
    expect(useStore.getState().gameRequestGeneration).toBe(hydrated.gameRequestGeneration);
    expect(useStore.getState().gameSnapshotEpoch).toBe(hydrated.gameSnapshotEpoch);
    expect(useStore.getState().gameHydrationGeneration).toBe(hydrated.gameHydrationGeneration + 1);
    confirmation.resolve(reply({ game: snapshot({ game_id: 'confirmed-game', revision: 3 }) }));
    await waitFor(() => expect(useStore.getState().gameSyncing).toBe(false));
    expect(useStore.getState().activeGame?.gameId).toBe('confirmed-game');
    expect(useStore.getState().activeGame?.participants).toEqual(['Captain', 'Ezri']);
    expect(useStore.getState().gameSnapshotEpoch).toBe(hydrated.gameSnapshotEpoch + 1);
    expect(useStore.getState().gameRequestGeneration).toBe(hydrated.gameRequestGeneration);
    expect(useStore.getState().gameConnectionGeneration).toBe(hydrated.gameConnectionGeneration);
  });
});