/**
 * AD-747 — ConversationController state-machine + wiring tests.
 *
 * Mocks the cross-module collaborators at the import boundary so the
 * controller's logic is exercised in isolation:
 *   - whisperStt (armWhisperStt, disarmWhisperStt, onTranscript)
 *   - voiceActivity (subscribePcm)
 *   - voice (stopSpeaking)
 *   - speechRecognitionArbiter (acquire, release)
 *
 * Network: fetch is stubbed via vi.spyOn(global, 'fetch').
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// --- Mocks at the module boundary --------------------------------------------

const _whisperState: {
  armed: boolean;
  listener: ((text: string) => void) | null;
} = { armed: false, listener: null };

vi.mock('../transformersStt', () => ({
  armTransformersStt: () => {
    _whisperState.armed = true;
    return () => { _whisperState.armed = false; };
  },
  disarmTransformersStt: () => { _whisperState.armed = false; },
  onTransformersTranscript: (l: (text: string) => void) => {
    _whisperState.listener = l;
    return () => { _whisperState.listener = null; };
  },
}));

const _vadState: {
  handler: { onSpeechStart?: () => void; onSpeechEnd?: () => void } | null;
  handlers: Set<{ onSpeechStart?: () => void; onSpeechEnd?: () => void; onFrame?: (...args: unknown[]) => void }>;
} = { handler: null, handlers: new Set() };

vi.mock('../voiceActivity', () => ({
  subscribePcm: (h: { onSpeechStart?: () => void; onSpeechEnd?: () => void }) => {
    _vadState.handler = h;
    _vadState.handlers.add(h as never);
    return () => {
      _vadState.handlers.delete(h as never);
      if (_vadState.handler === h) _vadState.handler = null;
    };
  },
}));

const _voiceState: { stopSpeakingCalls: number } = { stopSpeakingCalls: 0 };
vi.mock('../voice', () => ({
  stopSpeaking: () => { _voiceState.stopSpeakingCalls += 1; },
}));

// Imports must come AFTER vi.mock declarations.
import {
  armConversationMode,
  disarmConversationMode,
  getConversationState,
  markAgentReplyComplete,
  onConversationState,
  _resetConversationControllerForTests,
} from '../conversationController';
import {
  _resetForTests as _resetArbiter,
  PRIORITY_PRESS_TO_TALK,
  acquire as arbiterAcquire,
  currentHolder,
  release as arbiterRelease,
} from '../speechRecognitionArbiter';

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function chatResponse(body: unknown | Promise<unknown>): Response {
  return {
    ok: true,
    json: () => Promise.resolve(body),
  } as Response;
}

async function flushAsync(): Promise<void> {
  await Promise.resolve();
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
}

function _resetAll(): void {
  _resetConversationControllerForTests();
  _resetArbiter();
  _whisperState.armed = false;
  _whisperState.listener = null;
  _vadState.handler = null;
  _vadState.handlers.clear();
  _voiceState.stopSpeakingCalls = 0;
}

beforeEach(() => {
  _resetAll();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('AD-747 ConversationController', () => {
  it('arm grants arbiter lease at PRIORITY_CONVERSATION', () => {
    armConversationMode({ agentId: 'counselor-001' });
    expect(currentHolder()).toEqual({
      holder: 'conversation',
      priority: 75,
    });
    expect(getConversationState()).toBe('listening');
    expect(_whisperState.armed).toBe(true);
    expect(_vadState.handler).not.toBeNull();
  });

  it('arm without agentId is a no-op', () => {
    armConversationMode({ agentId: '' });
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('disarm releases lease and cancels silence timer', () => {
    armConversationMode({ agentId: 'a' });
    disarmConversationMode();
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
    expect(_whisperState.armed).toBe(false);
    expect(_vadState.handler).toBeNull();
  });

  it('VAD speech_end + whisper transcript triggers POST to /api/agent/{id}/chat', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hello, Captain.' }),
    } as unknown as Response);
    armConversationMode({ agentId: 'counselor-001' });
    expect(_whisperState.listener).not.toBeNull();
    // Whisper fires a finalized transcript.
    _whisperState.listener!('how are you');
    // Allow the awaited fetch chain to resolve.
    await vi.runAllTimersAsync();
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/agent/counselor-001/chat',
      expect.objectContaining({ method: 'POST' }),
    );
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({
      message: 'how are you',
    });
  });

  it('non-empty reply enters agent_speaking before callback and preserves synchronous completion', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    const callbackStates: string[] = [];
    armConversationMode({
      agentId: 'counselor-001',
      onAgentReply: () => {
        callbackStates.push(getConversationState());
        markAgentReplyComplete();
      },
    });
    _whisperState.listener!('hello');
    await vi.advanceTimersByTimeAsync(0);

    expect(callbackStates).toEqual(['agent_speaking']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('audible reply remains agent_speaking until real completion reaches silence_pending', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    const callbackStates: string[] = [];
    armConversationMode({
      agentId: 'counselor-001',
      onAgentReply: () => callbackStates.push(getConversationState()),
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();

    expect(callbackStates).toEqual(['agent_speaking']);
    expect(getConversationState()).toBe('agent_speaking');
    markAgentReplyComplete();
    expect(getConversationState()).toBe('silence_pending');
  });

  it.each([
    { body: { reply: '' }, name: 'empty reply' },
    { body: { message: '' }, name: 'empty message fallback' },
  ])('$name invokes no callback and returns to listening', async ({ body }) => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => body,
    } as unknown as Response);
    const onAgentReply = vi.fn();
    armConversationMode({ agentId: 'counselor-001', onAgentReply });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();

    expect(onAgentReply).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });

  it('non-OK response returns to listening without invoking reply callback', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      json: async () => ({ reply: 'must not surface' }),
    } as unknown as Response);
    const onAgentReply = vi.fn();
    armConversationMode({ agentId: 'counselor-001', onAgentReply });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();

    expect(onAgentReply).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });

  it('network error returns to listening without invoking reply callback', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('offline'));
    const onAgentReply = vi.fn();
    armConversationMode({ agentId: 'counselor-001', onAgentReply });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();

    expect(onAgentReply).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });

  it('reply callback error degrades to listening', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({
      agentId: 'counselor-001',
      onAgentReply: () => { throw new Error('callback failed'); },
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();

    expect(getConversationState()).toBe('listening');
  });

  it('barge-in: VAD speech_start during agent_speaking calls stopSpeaking and re-enters listening', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({ agentId: 'counselor-001' });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    // User barges in via the always-on VAD handler (the AD-760 Schmitt
    // detector also subscribes during agent_speaking; firing either
    // routes to _onVadSpeechStart()).
    const speechHandler = [..._vadState.handlers].find((h) => typeof h.onSpeechStart === 'function');
    expect(speechHandler).toBeTruthy();
    speechHandler!.onSpeechStart!();
    expect(_voiceState.stopSpeakingCalls).toBe(1);
    expect(getConversationState()).toBe('listening');
  });

  it('barge-in OFF: VAD speech_start during agent_speaking does NOT call stopSpeaking', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({
      agentId: 'counselor-001',
      bargeInEnabled: false,
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    const speechHandler = [..._vadState.handlers].find((h) => typeof h.onSpeechStart === 'function');
    expect(speechHandler).toBeTruthy();
    speechHandler!.onSpeechStart!();
    expect(_voiceState.stopSpeakingCalls).toBe(0);
    expect(getConversationState()).toBe('agent_speaking');
  });

  it('silence timer: markAgentReplyComplete starts the timer; expiry disarms', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({
      agentId: 'counselor-001',
      silenceTimeoutMs: 5000,
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    markAgentReplyComplete();
    expect(getConversationState()).toBe('silence_pending');
    vi.advanceTimersByTime(5000);
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('press-to-talk preempts the conversation lease and disarms cleanly', () => {
    armConversationMode({ agentId: 'counselor-001' });
    expect(currentHolder()!.holder).toBe('conversation');
    arbiterAcquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    // Preemption fired the controller's onPreempted → disarm.
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()!.holder).toBe('press_to_talk');
  });

  it('transcript hook fires before submission (HXI preview pill seam)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'ok' }),
    } as unknown as Response);
    const captured: string[] = [];
    armConversationMode({
      agentId: 'counselor-001',
      onTranscript: (t) => captured.push(t),
    });
    _whisperState.listener!('what is the weather');
    await vi.runAllTimersAsync();
    expect(captured).toEqual(['what is the weather']);
  });

  it('empty transcript is dropped (no fetch fired)', async () => {
    armConversationMode({ agentId: 'counselor-001' });
    // Spy AFTER arm so we only see fetches caused by transcript handling.
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as unknown as Response);
    fetchSpy.mockClear();
    _whisperState.listener!('   ');
    await vi.runAllTimersAsync();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });
});

describe('BF-671 Option A controller ownership', () => {
  it.each(['resolve', 'reject'] as const)(
    'drops stale A when deferred fetch %s occurs after B arms',
    async (outcome) => {
      const pendingFetch = deferred<Response>();
      vi.spyOn(global, 'fetch').mockReturnValue(pendingFetch.promise);
      const onAReply = vi.fn();
      const onBReply = vi.fn();

      armConversationMode({ agentId: 'agent-a', onAgentReply: onAReply });
      _whisperState.listener!('A request');
      await flushAsync();
      expect(getConversationState()).toBe('submitted');

      armConversationMode({ agentId: 'agent-b', onAgentReply: onBReply });
      expect(getConversationState()).toBe('listening');
      if (outcome === 'resolve') {
        pendingFetch.resolve(chatResponse({ response: 'stale A reply' }));
      } else {
        pendingFetch.reject(new Error('stale A fetch failure'));
      }
      await flushAsync();

      expect(onAReply).not.toHaveBeenCalled();
      expect(onBReply).not.toHaveBeenCalled();
      expect(getConversationState()).toBe('listening');
      expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
    },
  );

  it.each(['resolve', 'reject'] as const)(
    'drops stale A when deferred JSON %s occurs after B arms',
    async (outcome) => {
      const pendingJson = deferred<unknown>();
      const json = vi.fn(() => pendingJson.promise);
      vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json } as unknown as Response);
      const onAReply = vi.fn();
      const onBReply = vi.fn();

      armConversationMode({ agentId: 'agent-a', onAgentReply: onAReply });
      _whisperState.listener!('A request');
      await flushAsync();
      expect(json).toHaveBeenCalledTimes(1);

      armConversationMode({ agentId: 'agent-b', onAgentReply: onBReply });
      if (outcome === 'resolve') {
        pendingJson.resolve({ response: 'stale A JSON reply' });
      } else {
        pendingJson.reject(new Error('stale A JSON failure'));
      }
      await flushAsync();

      expect(onAReply).not.toHaveBeenCalled();
      expect(onBReply).not.toHaveBeenCalled();
      expect(getConversationState()).toBe('listening');
      expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
    },
  );

  it('same-agent re-arm replaces exact options ownership and drops old work', async () => {
    const pendingFetch = deferred<Response>();
    const fetchSpy = vi.spyOn(global, 'fetch')
      .mockReturnValueOnce(pendingFetch.promise)
      .mockResolvedValueOnce(chatResponse({ response: 'new owner reply' }));
    const onOldReply = vi.fn();
    const onNewReply = vi.fn();

    armConversationMode({ agentId: 'same-agent', onAgentReply: onOldReply });
    _whisperState.listener!('old request');
    await flushAsync();
    armConversationMode({ agentId: 'same-agent', onAgentReply: onNewReply });
    pendingFetch.resolve(chatResponse({ response: 'old owner reply' }));
    await flushAsync();

    expect(onOldReply).not.toHaveBeenCalled();
    expect(onNewReply).not.toHaveBeenCalled();
    _whisperState.listener!('new request');
    await flushAsync();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(onNewReply).toHaveBeenCalledWith('new owner reply');
  });

  it.each([
    { boundary: 'fetch', outcome: 'resolve' },
    { boundary: 'fetch', outcome: 'reject' },
    { boundary: 'json', outcome: 'resolve' },
    { boundary: 'json', outcome: 'reject' },
  ] as const)(
    'public disarm drops $boundary $outcome without replacement',
    async ({ boundary, outcome }) => {
      const pending = deferred<unknown>();
      if (boundary === 'fetch') {
        vi.spyOn(global, 'fetch').mockReturnValue(pending.promise as Promise<Response>);
      } else {
        vi.spyOn(global, 'fetch').mockResolvedValue({
          ok: true,
          json: () => pending.promise,
        } as unknown as Response);
      }
      const onAgentReply = vi.fn();
      armConversationMode({ agentId: 'agent-a', onAgentReply });
      _whisperState.listener!('request');
      await flushAsync();

      disarmConversationMode();
      if (outcome === 'resolve') {
        if (boundary === 'fetch') pending.resolve(chatResponse({ response: 'stale' }));
        else pending.resolve({ response: 'stale' });
      } else {
        pending.reject(new Error('stale failure'));
      }
      await flushAsync();

      expect(onAgentReply).not.toHaveBeenCalled();
      expect(getConversationState()).toBe('inactive');
      expect(currentHolder()).toBeNull();
    },
  );

  it.each(['resolve', 'reject'] as const)(
    'drops stale group submit %s after B arms without starting A timer',
    async (outcome) => {
      const pendingSubmit = deferred<void>();
      const onBState = vi.fn();
      armConversationMode({
        agentId: 'agent-a',
        submitTranscript: () => pendingSubmit.promise,
        silenceTimeoutMs: 20,
      });
      _whisperState.listener!('group request');
      await flushAsync();
      armConversationMode({ agentId: 'agent-b', onStateChange: onBState });

      if (outcome === 'resolve') pendingSubmit.resolve(undefined);
      else pendingSubmit.reject(new Error('stale submit failure'));
      await flushAsync();
      await vi.advanceTimersByTimeAsync(50);

      expect(getConversationState()).toBe('listening');
      expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
      expect(onBState).toHaveBeenLastCalledWith('listening');
    },
  );

  it('owner-bound disposer cannot disarm a replacement owner', () => {
    const disposeA = armConversationMode({ agentId: 'agent-a' });
    const disposeB = armConversationMode({ agentId: 'agent-b' });

    disposeA();
    expect(getConversationState()).toBe('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });

    disposeB();
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('queued null acquisition releases its stale grant without wiring or orphaning', () => {
    const blocker = arbiterAcquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    expect(blocker).not.toBeNull();

    armConversationMode({ agentId: 'queued-agent' });
    expect(getConversationState()).toBe('inactive');
    expect(_whisperState.armed).toBe(false);
    arbiterRelease(blocker!);

    expect(currentHolder()).toBeNull();
    expect(getConversationState()).toBe('inactive');
    expect(_whisperState.armed).toBe(false);
    expect(_vadState.handler).toBeNull();
  });

  it.each(['later arm', 'public disarm', 'test reset'] as const)(
    '%s supersedes queued acquisition bookkeeping and leaves no orphan grant',
    (superseder) => {
      const blocker = arbiterAcquire({
        holder: 'press_to_talk',
        priority: PRIORITY_PRESS_TO_TALK,
      });
      armConversationMode({ agentId: 'queued-a' });

      if (superseder === 'later arm') armConversationMode({ agentId: 'queued-b' });
      else if (superseder === 'public disarm') disarmConversationMode();
      else _resetConversationControllerForTests();

      arbiterRelease(blocker!);
      expect(currentHolder()).toBeNull();
      expect(getConversationState()).toBe('inactive');
      expect(_whisperState.armed).toBe(false);
    },
  );

  it('synchronous acquisition adopts the lease before listening callback disarms', () => {
    const states: string[] = [];
    armConversationMode({
      agentId: 'agent-a',
      onStateChange: (state) => {
        states.push(state);
        if (state === 'listening') disarmConversationMode();
      },
    });

    expect(states).toEqual(['listening', 'inactive']);
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
    expect(_whisperState.armed).toBe(false);
  });

  it('current preemption tears down once while the higher-priority holder remains', async () => {
    const states: string[] = [];
    armConversationMode({ agentId: 'agent-a', onStateChange: (state) => states.push(state) });

    arbiterAcquire({ holder: 'press_to_talk', priority: PRIORITY_PRESS_TO_TALK });
    await flushAsync();

    expect(states).toEqual(['listening', 'inactive']);
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toEqual({ holder: 'press_to_talk', priority: PRIORITY_PRESS_TO_TALK });
  });

  it.each(['option', 'global'] as const)(
    'preempted A %s inactive observer re-arms B only after the higher-priority grant',
    async (observerSource) => {
      const aStates: string[] = [];
      const bStates: string[] = [];
      const holdersSeenByInactive: Array<ReturnType<typeof currentHolder>> = [];
      const trailingInactive = vi.fn();
      let unsubscribe: () => void = () => undefined;
      const armB = () => {
        holdersSeenByInactive.push(currentHolder());
        armConversationMode({
          agentId: 'agent-b',
          onStateChange: (state) => bStates.push(state),
        });
      };
      if (observerSource === 'global') {
        unsubscribe = onConversationState((state) => {
          if (state === 'inactive') armB();
        });
      }
      const unsubscribeTrailing = onConversationState((state) => {
        if (state === 'inactive') trailingInactive();
      });
      armConversationMode({
        agentId: 'agent-a',
        onStateChange: (state) => {
          aStates.push(state);
          if (observerSource === 'option' && state === 'inactive') armB();
        },
      });

      const blocker = arbiterAcquire({
        holder: 'press_to_talk',
        priority: PRIORITY_PRESS_TO_TALK,
      });
      expect(blocker).not.toBeNull();
      expect(getConversationState()).toBe('inactive');
      expect(currentHolder()).toEqual({
        holder: 'press_to_talk',
        priority: PRIORITY_PRESS_TO_TALK,
      });

      await flushAsync();

      expect(aStates).toEqual(['listening', 'inactive']);
      expect(holdersSeenByInactive).toEqual([{
        holder: 'press_to_talk',
        priority: PRIORITY_PRESS_TO_TALK,
      }]);
      expect(bStates).toEqual([]);
      expect(trailingInactive).not.toHaveBeenCalled();
      expect(getConversationState()).toBe('inactive');
      expect(currentHolder()).toEqual({
        holder: 'press_to_talk',
        priority: PRIORITY_PRESS_TO_TALK,
      });

      arbiterRelease(blocker!);
      expect(currentHolder()).toBeNull();
      expect(getConversationState()).toBe('inactive');
      expect(_whisperState.armed).toBe(false);
      unsubscribe();
      unsubscribeTrailing();
    },
  );

  it('callback re-arm followed by throw cannot move replacement B to listening', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'A reply' }));
    const onBState = vi.fn();
    armConversationMode({
      agentId: 'agent-a',
      onAgentReply: () => {
        armConversationMode({ agentId: 'agent-b', onStateChange: onBState });
        throw new Error('A callback failed after replacement');
      },
    });

    _whisperState.listener!('A request');
    await flushAsync();

    expect(getConversationState()).toBe('listening');
    expect(onBState).toHaveBeenLastCalledWith('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
  });

  it('A silence timer cannot disarm B while current B stays coherent', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'A reply' }));
    armConversationMode({ agentId: 'agent-a', silenceTimeoutMs: 25 });
    _whisperState.listener!('A request');
    await flushAsync();
    markAgentReplyComplete();
    expect(getConversationState()).toBe('silence_pending');

    armConversationMode({ agentId: 'agent-b' });
    await vi.advanceTimersByTimeAsync(50);

    expect(getConversationState()).toBe('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
  });

  it('current-owner echo activity refreshes only its own silence timer', async () => {
    let canListen = true;
    armConversationMode({
      agentId: 'meeting-owner',
      submitTranscript: async () => undefined,
      canListen: () => canListen,
      silenceTimeoutMs: 100,
    });
    _whisperState.listener!('Captain turn');
    await flushAsync();
    expect(getConversationState()).toBe('silence_pending');

    await vi.advanceTimersByTimeAsync(60);
    canListen = false;
    _whisperState.listener!('crew echo');
    await flushAsync();
    await vi.advanceTimersByTimeAsync(60);
    expect(getConversationState()).toBe('silence_pending');

    await vi.advanceTimersByTimeAsync(40);
    expect(getConversationState()).toBe('inactive');
  });

  it('stale VAD/barge callback cannot stop or move speaking B', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'B reply' }));
    armConversationMode({ agentId: 'agent-a' });
    const staleVad = _vadState.handler;
    armConversationMode({ agentId: 'agent-b' });
    _whisperState.listener!('B request');
    await flushAsync();
    expect(getConversationState()).toBe('agent_speaking');

    staleVad?.onSpeechStart?.();

    expect(_voiceState.stopSpeakingCalls).toBe(0);
    expect(getConversationState()).toBe('agent_speaking');
  });

  it.each([
    {
      name: 'response wins over conflicting fallbacks',
      body: { response: 'canonical', reply: 'legacy reply', message: 'legacy message' },
      expected: 'canonical',
    },
    { name: 'reply fallback remains accepted', body: { reply: 'legacy reply' }, expected: 'legacy reply' },
    { name: 'message fallback remains accepted', body: { message: 'legacy message' }, expected: 'legacy message' },
  ])('$name', async ({ body, expected }) => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse(body));
    const onAgentReply = vi.fn();
    armConversationMode({ agentId: 'agent-a', onAgentReply });

    _whisperState.listener!('request');
    await flushAsync();

    expect(onAgentReply).toHaveBeenCalledWith(expected);
    expect(getConversationState()).toBe('agent_speaking');
  });

  it('stale installed transcript callback does no work after replacement', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'unexpected' }));
    armConversationMode({ agentId: 'agent-a' });
    const staleTranscript = _whisperState.listener;
    armConversationMode({ agentId: 'agent-b' });
    fetchSpy.mockClear();

    staleTranscript?.('stale A transcript');
    await flushAsync();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });

  it('current transcript hook and history preserve callback order and request payload', async () => {
    const order: string[] = [];
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async () => {
      order.push('fetch');
      return chatResponse({ response: '' });
    });
    armConversationMode({
      agentId: 'agent-a',
      onTranscript: (text) => order.push(`transcript:${text}`),
      historyProvider: () => {
        order.push('history');
        return [{ role: 'user', content: 'earlier' }];
      },
    });

    _whisperState.listener!('  current request  ');
    await flushAsync();

    expect(order).toEqual(['transcript:current request', 'history', 'fetch']);
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      message: 'current request',
      history: [{ role: 'user', content: 'earlier' }],
    });
    expect(getConversationState()).toBe('listening');
  });

  it('test reset invalidates deferred async work', async () => {
    const pendingFetch = deferred<Response>();
    vi.spyOn(global, 'fetch').mockReturnValue(pendingFetch.promise);
    const onAgentReply = vi.fn();
    armConversationMode({ agentId: 'agent-a', onAgentReply });
    _whisperState.listener!('request');
    await flushAsync();

    _resetConversationControllerForTests();
    pendingFetch.resolve(chatResponse({ response: 'stale after reset' }));
    await flushAsync();

    expect(onAgentReply).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('inactive');
  });

  it('test reset invalidates a captured silence timer', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'reply' }));
    armConversationMode({ agentId: 'agent-a', silenceTimeoutMs: 25 });
    _whisperState.listener!('request');
    await flushAsync();
    markAgentReplyComplete();

    _resetConversationControllerForTests();
    await vi.advanceTimersByTimeAsync(50);

    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('listening callback can re-arm B without A orphaning the acquired lease', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'B reply' }));
    const onAReply = vi.fn();
    const onBReply = vi.fn();
    armConversationMode({
      agentId: 'agent-a',
      onAgentReply: onAReply,
      onStateChange: (state) => {
        if (state === 'listening') {
          armConversationMode({ agentId: 'agent-b', onAgentReply: onBReply });
        }
      },
    });

    expect(getConversationState()).toBe('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
    _whisperState.listener!('B request');
    await flushAsync();
    expect(onAReply).not.toHaveBeenCalled();
    expect(onBReply).toHaveBeenCalledWith('B reply');
  });

  it('agent_speaking callback re-arm stops A before reply delivery', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(chatResponse({ response: 'A reply' }));
    const onAReply = vi.fn();
    const onBState = vi.fn();
    armConversationMode({
      agentId: 'agent-a',
      onAgentReply: onAReply,
      onStateChange: (state) => {
        if (state === 'agent_speaking') {
          armConversationMode({ agentId: 'agent-b', onStateChange: onBState });
        }
      },
    });

    _whisperState.listener!('A request');
    await flushAsync();

    expect(onAReply).not.toHaveBeenCalled();
    expect(onBState).toHaveBeenLastCalledWith('listening');
    expect(getConversationState()).toBe('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
  });

  it('global state listener re-arm stops the superseded A transition remainder', () => {
    const observed: string[] = [];
    const unsubscribe = onConversationState((state) => {
      observed.push(state);
      if (state === 'listening' && observed.length === 1) {
        armConversationMode({ agentId: 'agent-b' });
      }
    });

    armConversationMode({ agentId: 'agent-a' });

    unsubscribe();
    expect(observed).toEqual(['listening', 'inactive', 'listening']);
    expect(getConversationState()).toBe('listening');
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
  });

  it('reset supersedes a queued callback and its later grant releases itself', () => {
    const blocker = arbiterAcquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    armConversationMode({ agentId: 'queued-a' });
    _resetConversationControllerForTests();

    arbiterRelease(blocker!);

    expect(currentHolder()).toBeNull();
    expect(getConversationState()).toBe('inactive');
    expect(_whisperState.armed).toBe(false);
  });

  it('current observers see transitions once and stale A emits nothing after replacement', async () => {
    const pendingFetch = deferred<Response>();
    vi.spyOn(global, 'fetch').mockReturnValue(pendingFetch.promise);
    const observed: string[] = [];
    const unsubscribe = onConversationState((state) => observed.push(state));
    armConversationMode({ agentId: 'agent-a' });
    _whisperState.listener!('A request');
    await flushAsync();
    armConversationMode({ agentId: 'agent-b' });
    const beforeStale = observed.slice();

    pendingFetch.resolve(chatResponse({ response: 'stale A reply' }));
    await flushAsync();
    expect(observed).toEqual(beforeStale);

    disarmConversationMode();
    unsubscribe();
    expect(observed).toEqual([
      'listening',
      'transcribing',
      'submitted',
      'inactive',
      'listening',
      'inactive',
    ]);
  });
});
