/**
 * BF-703: a background message must live-refresh the CompactApp shell too.
 *
 * AD-1133's gate asked only about the profile-panel shell. It begins
 * `activeProfileAgent === null ? null : ...`, and CompactApp never calls
 * `openAgentProfile` -- it reads `activeThreadId`, derives the agent from the
 * thread, and leaves every profile field untouched. So in CompactApp the gate
 * compared the incoming thread against `null` and no background message could
 * ever match an open transcript.
 *
 * On the reference vessel a promoted turn's report was persisted, served by the
 * transcript endpoint, emitted by the runtime, and delivered over the websocket
 * -- verified at each step -- and still never appeared on screen. Reopening the
 * chat showed it, which is what made it read like a rendering fault instead of
 * a refresh one.
 */
import { afterEach, describe, expect, it } from 'vitest';

import { useStore } from '../useStore';
import type { WSEvent } from '../types';

const GENERATION = 'a'.repeat(32);

function frame(
  type: string,
  data: Record<string, unknown>,
  sequence: number,
): WSEvent {
  return { type, data, timestamp: 1, stream: { generation: GENERATION, sequence } };
}

function installSnapshot(): void {
  useStore.getState().handleEvent(frame('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active',
    tc_n: 0, routing_entropy: 0,
  }, 0));
}

function appended(threadId: string, messageId: string, sequence: number): void {
  useStore.getState().handleEvent(frame('chat_thread_message_appended', {
    thread_id: threadId,
    message_id: messageId,
    author_id: 'counselor-ezri',
    role: 'agent',
    created_at: 2,
  }, sequence));
}

afterEach(() => {
  useStore.setState({
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    activeProfileAgent: null,
    activeProfileThreadId: null,
    activeThreadId: null,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
  });
});

describe('BF-703 background messages refresh whichever shell is open', () => {
  it('refreshes when CompactApp owns the thread via activeThreadId', () => {
    installSnapshot();
    // Exactly CompactApp's state: a thread is open, the agent is derived from
    // it, and no profile field is set because openAgentProfile was never called.
    useStore.setState({
      activeThreadId: 'thread-ezri',
      activeProfileAgent: null,
      activeProfileThreadId: null,
    });

    appended('thread-ezri', 'msg-report', 1);

    expect(useStore.getState().liveThreadRefresh).toEqual({
      threadId: 'thread-ezri',
      requestId: 'msg-report',
    });
  });

  it('still refreshes the profile-panel shell (AD-1133 unchanged)', () => {
    installSnapshot();
    useStore.setState({
      activeThreadId: null,
      activeProfileAgent: 'counselor-ezri',
      activeProfileThreadId: 'thread-ezri',
    });

    appended('thread-ezri', 'msg-report', 1);

    expect(useStore.getState().liveThreadRefresh).toEqual({
      threadId: 'thread-ezri',
      requestId: 'msg-report',
    });
  });

  it('still refreshes when the profile shell resolves through threadIdByAgent', () => {
    installSnapshot();
    useStore.setState({
      activeThreadId: null,
      activeProfileAgent: 'counselor-ezri',
      activeProfileThreadId: null,
      threadIdByAgent: new Map([['counselor-ezri', 'thread-ezri']]),
    });

    appended('thread-ezri', 'msg-report', 1);

    expect(useStore.getState().liveThreadRefresh?.threadId).toBe('thread-ezri');
  });

  it('ignores a message for a thread that is not open in either shell', () => {
    installSnapshot();
    useStore.setState({
      activeThreadId: 'thread-open',
      activeProfileAgent: 'counselor-ezri',
      activeProfileThreadId: 'thread-open',
    });

    appended('thread-elsewhere', 'msg-other', 1);

    expect(useStore.getState().liveThreadRefresh).toBeNull();
  });

  it('ignores everything when no thread is open at all', () => {
    installSnapshot();
    useStore.setState({
      activeThreadId: null,
      activeProfileAgent: null,
      activeProfileThreadId: null,
    });

    appended('thread-ezri', 'msg-report', 1);

    expect(useStore.getState().liveThreadRefresh).toBeNull();
  });

  it('still advances last_active_at for a thread that is not open', () => {
    installSnapshot();
    useStore.setState({
      activeThreadId: null,
      chatThreads: new Map([['thread-cold', {
        id: 'thread-cold',
        title: 'Cold',
        participants: [],
        metadata: {},
        last_active_at: 1,
      } as never]]),
    });

    appended('thread-cold', 'msg-cold', 1);

    expect(useStore.getState().chatThreads.get('thread-cold')?.last_active_at).toBe(2);
    expect(useStore.getState().liveThreadRefresh).toBeNull();
  });
});
