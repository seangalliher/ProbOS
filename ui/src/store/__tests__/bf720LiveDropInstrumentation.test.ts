/**
 * BF-720: a live frame that stops travelling must say where it stopped.
 *
 * A promoted turn's report was persisted, emitted and delivered over the
 * websocket, and was invisible in the transcript for 17.5 minutes. It had six
 * places to vanish, none of which left a trace. These tests pin the trace.
 *
 * They also pin the SAFETY half: a frame that should be dropped -- a replay, or
 * one carrying an authority this client has not accepted -- is still dropped.
 * Instrumentation must not become permission.
 */
import { afterEach, describe, expect, it } from 'vitest';

import { useStore } from '../useStore';
import type { LiveDropGate, WSEvent } from '../types';

const GENERATION = 'a'.repeat(32);
const OTHER_GENERATION = 'b'.repeat(32);

function frame(
  type: string,
  data: Record<string, unknown>,
  sequence: number,
  generation: string = GENERATION,
): WSEvent {
  return { type, data, timestamp: 1, stream: { generation, sequence } };
}

function installSnapshot(generation: string = GENERATION): void {
  useStore.getState().handleEvent(frame('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active',
    tc_n: 0, routing_entropy: 0,
  }, 0, generation));
}

function appendFrame(
  threadId: string,
  messageId: string,
  sequence: number,
  generation: string = GENERATION,
): WSEvent {
  return frame('chat_thread_message_appended', {
    thread_id: threadId,
    message_id: messageId,
    author_id: 'counselor-ezri',
    role: 'agent',
    created_at: 2,
  }, sequence, generation);
}

function gates(): LiveDropGate[] {
  return useStore.getState().liveDrops.map((drop) => drop.gate);
}

afterEach(() => {
  useStore.setState({
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveDropCount: 0,
    liveDrops: [],
    activeProfileAgent: null,
    activeProfileThreadId: null,
    activeThreadId: null,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
  });
});

describe('BF-720 gate 1: frame shape', () => {
  it('records a drop when the envelope fails validation', () => {
    installSnapshot();

    useStore.getState().handleEvent({ type: 'chat_thread_message_appended' } as unknown as WSEvent);

    expect(useStore.getState().liveDropCount).toBe(1);
    expect(useStore.getState().liveDrops[0]).toEqual({
      gate: 'frame_shape',
      eventType: 'chat_thread_message_appended',
      threadId: null,
      detail: null,
    });
  });

  it('recovers the thread id from an unparsed frame so the record names the transcript', () => {
    installSnapshot();

    // Well-formed envelope, malformed payload: no ``message_id``.
    useStore.getState().handleEvent(frame('chat_thread_message_appended', {
      thread_id: 'thread-ezri',
      author_id: 'counselor-ezri',
      role: 'agent',
      created_at: 2,
    }, 1));

    expect(useStore.getState().liveDrops[0]).toMatchObject({
      gate: 'frame_shape',
      threadId: 'thread-ezri',
    });
  });

  it('labels a frame with no usable type', () => {
    installSnapshot();

    useStore.getState().handleEvent({ nonsense: true } as unknown as WSEvent);

    expect(useStore.getState().liveDrops[0]).toMatchObject({
      gate: 'frame_shape',
      eventType: '<unparsed>',
      threadId: null,
    });
  });
});

describe('BF-720 gate 2: generation', () => {
  it('records a drop when a frame carries a different generation', () => {
    installSnapshot();

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-report', 1, OTHER_GENERATION));

    expect(useStore.getState().liveDrops).toEqual([{
      gate: 'generation',
      eventType: 'chat_thread_message_appended',
      threadId: 'thread-ezri',
      detail: 'generation_changed',
    }]);
  });

  it('records a drop when no snapshot has established authority', () => {
    // Exactly the post-reconnect window: ``useWebSocket`` nulls the generation
    // on close and the next snapshot has not arrived yet.
    useStore.setState({ liveGeneration: null });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-report', 1));

    expect(useStore.getState().liveDrops).toEqual([{
      gate: 'generation',
      eventType: 'chat_thread_message_appended',
      threadId: 'thread-ezri',
      detail: 'no_authority',
    }]);
  });

  // SAFETY. Instrumenting the gate must not open it.
  it('still drops a foreign-generation frame rather than applying it', () => {
    installSnapshot();
    useStore.setState({ activeThreadId: 'thread-ezri' });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-report', 9, OTHER_GENERATION));

    expect(useStore.getState().liveThreadRefresh).toBeNull();
    expect(useStore.getState().liveSequence).toBe(0);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);
  });

  // The recovery path that makes gate 2 self-healing: the server sends a
  // snapshot as the first frame of every connection (``ws_event_stream.serve``),
  // and a snapshot bumps ``liveRepairEpoch``, which is what drives a full
  // transcript refetch. Gate 2 therefore closes for at most one round trip.
  it('re-establishes authority and requests repair when the snapshot arrives', () => {
    installSnapshot();
    const epochBefore = useStore.getState().liveRepairEpoch;
    useStore.setState({ liveGeneration: null });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-lost', 1));
    installSnapshot(OTHER_GENERATION);

    expect(useStore.getState().liveGeneration).toBe(OTHER_GENERATION);
    expect(useStore.getState().liveRepairEpoch).toBe(epochBefore + 1);
  });
});

describe('BF-720 gate 3: sequence', () => {
  it('records a drop for a replayed sequence', () => {
    installSnapshot();
    useStore.setState({ activeThreadId: 'thread-ezri' });
    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-first', 5));
    useStore.setState({ liveDropCount: 0, liveDrops: [], liveThreadRefresh: null });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-replay', 5));

    expect(useStore.getState().liveDrops).toEqual([{
      gate: 'sequence',
      eventType: 'chat_thread_message_appended',
      threadId: 'thread-ezri',
      detail: 'replay_or_stale',
    }]);
  });

  // SAFETY. A replay must not reach the transcript.
  it('still drops the replay rather than re-issuing a refresh', () => {
    installSnapshot();
    useStore.setState({ activeThreadId: 'thread-ezri' });
    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-first', 5));
    useStore.setState({ liveThreadRefresh: null });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-replay', 5));

    expect(useStore.getState().liveThreadRefresh).toBeNull();
    expect(useStore.getState().liveSequence).toBe(5);
  });
});

describe('BF-720 gate 4: no shell owns the thread', () => {
  it('records a drop when neither shell claims the thread', () => {
    installSnapshot();
    useStore.setState({ activeThreadId: 'thread-open', activeProfileAgent: null });

    useStore.getState().handleEvent(appendFrame('thread-elsewhere', 'msg-other', 1));

    expect(useStore.getState().liveDrops).toEqual([{
      gate: 'thread_not_open',
      eventType: 'chat_thread_message_appended',
      threadId: 'thread-elsewhere',
      detail: 'no_shell_owns_thread',
    }]);
  });

  it('records nothing when a shell does own the thread', () => {
    installSnapshot();
    useStore.setState({ activeThreadId: 'thread-ezri' });

    useStore.getState().handleEvent(appendFrame('thread-ezri', 'msg-report', 1));

    expect(useStore.getState().liveDropCount).toBe(0);
    expect(useStore.getState().liveThreadRefresh).toEqual({
      threadId: 'thread-ezri',
      requestId: 'msg-report',
    });
  });
});

describe('BF-720 drop log bounds', () => {
  it('keeps the total count while retaining only the most recent records', () => {
    installSnapshot();

    for (let index = 0; index < 40; index += 1) {
      useStore.getState().handleEvent(
        appendFrame('thread-ezri', `msg-${index}`, index + 1, OTHER_GENERATION),
      );
    }

    expect(useStore.getState().liveDropCount).toBe(40);
    expect(useStore.getState().liveDrops).toHaveLength(32);
    expect(useStore.getState().liveDrops[31].threadId).toBe('thread-ezri');
    expect(gates().every((gate) => gate === 'generation')).toBe(true);
  });
});
