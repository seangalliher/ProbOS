// AD-938: tests for the thread-keyed display-transcript store slice
// (threadMessages + setThreadMessages/appendThreadMessage). Real zustand store
// via useStore.getState()/setState (BF-287 real-fixture style, no MagicMock).
import { describe, it, expect, afterEach } from 'vitest';
import { useStore } from '../useStore';
import type { AgentProfileMessage } from '../types';

function mkMsg(id: string, role: AgentProfileMessage['role'] = 'agent'): AgentProfileMessage {
  return { id, role, text: id, timestamp: 1_700_000_000 };
}

afterEach(() => {
  useStore.setState({ threadMessages: new Map() });
});

describe('AD-938 threadMessages store slice', () => {
  it('boots with an empty threadMessages map', () => {
    expect(useStore.getState().threadMessages).toBeInstanceOf(Map);
    expect(useStore.getState().threadMessages.size).toBe(0);
  });

  it('setThreadMessages sets a thread list and replaces it on a second call (immutable Map)', () => {
    const before = useStore.getState().threadMessages;
    useStore.getState().setThreadMessages('t1', [mkMsg('a'), mkMsg('b')]);
    const after = useStore.getState().threadMessages;
    expect(after).not.toBe(before); // new Map reference (reactive update)
    expect(after.get('t1')?.map((m) => m.id)).toEqual(['a', 'b']);

    useStore.getState().setThreadMessages('t1', [mkMsg('c')]);
    expect(useStore.getState().threadMessages.get('t1')?.map((m) => m.id)).toEqual(['c']);
  });

  it('setThreadMessages keeps other threads isolated', () => {
    useStore.getState().setThreadMessages('t1', [mkMsg('a')]);
    useStore.getState().setThreadMessages('t2', [mkMsg('b')]);
    expect(useStore.getState().threadMessages.get('t1')?.[0].id).toBe('a');
    expect(useStore.getState().threadMessages.get('t2')?.[0].id).toBe('b');
  });

  it('appendThreadMessage appends to an existing list (and seeds an empty one)', () => {
    useStore.getState().appendThreadMessage('t1', mkMsg('a'));
    useStore.getState().appendThreadMessage('t1', mkMsg('b'));
    expect(useStore.getState().threadMessages.get('t1')?.map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('appendThreadMessage caps the list to the last 200 messages', () => {
    for (let i = 0; i < 250; i++) {
      useStore.getState().appendThreadMessage('t1', mkMsg(`m${i}`));
    }
    const list = useStore.getState().threadMessages.get('t1')!;
    expect(list).toHaveLength(200);
    expect(list[0].id).toBe('m50');   // oldest retained
    expect(list[199].id).toBe('m249'); // newest
  });
});
