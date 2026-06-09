// AD-937: store-level tests for the group-thread override that fixes the
// unreachable-1:1 regression. Drives the REAL zustand store (BF-287 real-fixture
// style, no MagicMock) plus the pure `resolveProfileThreadId` resolver. The
// headline case is the Captain's exact repro: after viewing a group, reopening
// the agent's profile must resolve back to the 1:1, not the group.
import { describe, it, expect, afterEach } from 'vitest';
import { useStore } from '../../../store/useStore';
import { resolveProfileThreadId } from '../profileThreadResolution';

afterEach(() => {
  useStore.setState({
    activeProfileAgent: null,
    activeProfileThreadId: null,
    pinnedAgent: null,
    threadIdByAgent: new Map(),
  });
});

describe('AD-937 group-thread override + resolution', () => {
  it('openGroupChatThread sets the override + host, but does NOT touch threadIdByAgent', () => {
    useStore.setState({ threadIdByAgent: new Map([['ezri', 'one-to-one']]) });
    useStore.getState().openGroupChatThread('ezri', 'group-1');
    expect(useStore.getState().activeProfileThreadId).toBe('group-1');
    expect(useStore.getState().activeProfileAgent).toBe('ezri');
    // The agent's reserved 1:1 slot is untouched (the whole point of AD-937).
    expect(useStore.getState().threadIdByAgent.get('ezri')).toBe('one-to-one');
  });

  it('resolveProfileThreadId only reads the requested agent\'s 1:1 slot', () => {
    const map = new Map([['worf', 'worf-1to1']]);
    // ezri has no slot and no override -> undefined (does not leak worf's slot).
    expect(resolveProfileThreadId(undefined, null, map, 'ezri')).toBeUndefined();
    // worf resolves to its own slot.
    expect(resolveProfileThreadId(undefined, null, map, 'worf')).toBe('worf-1to1');
  });

  it('openGroupChatThread overwrites a prior override', () => {
    useStore.getState().openGroupChatThread('ezri', 'group-1');
    useStore.getState().openGroupChatThread('ezri', 'group-2');
    expect(useStore.getState().activeProfileThreadId).toBe('group-2');
  });

  it('openAgentProfile clears the group override (roster/1:1 open)', () => {
    useStore.getState().openGroupChatThread('ezri', 'group-1');
    expect(useStore.getState().activeProfileThreadId).toBe('group-1');
    useStore.getState().openAgentProfile('ezri');
    expect(useStore.getState().activeProfileThreadId).toBeNull();
    expect(useStore.getState().activeProfileAgent).toBe('ezri');
  });

  it('resolveProfileThreadId: prop > override > per-agent 1:1 > undefined', () => {
    const map = new Map([['ezri', 'one-to-one']]);
    // explicit prop wins over everything
    expect(resolveProfileThreadId('explicit', 'group-1', map, 'ezri')).toBe('explicit');
    // override wins when there is no prop
    expect(resolveProfileThreadId(undefined, 'group-1', map, 'ezri')).toBe('group-1');
    // falls to the per-agent 1:1 when the override is null
    expect(resolveProfileThreadId(undefined, null, map, 'ezri')).toBe('one-to-one');
    // undefined when nothing resolves
    expect(resolveProfileThreadId(undefined, null, new Map(), 'ezri')).toBeUndefined();
  });

  it('HEADLINE (Captain repro): after viewing a group, reopening the profile resolves to the 1:1, not the group', () => {
    // The agent has a 1:1 default thread bound.
    useStore.setState({ threadIdByAgent: new Map([['ezri', 'one-to-one']]) });
    // Open a group in Ezri's profile — the view shows the group.
    useStore.getState().openGroupChatThread('ezri', 'group-1');
    let st = useStore.getState();
    expect(
      resolveProfileThreadId(undefined, st.activeProfileThreadId, st.threadIdByAgent, 'ezri'),
    ).toBe('group-1');
    // Reopen Ezri's profile from the roster (clears the override).
    useStore.getState().openAgentProfile('ezri');
    st = useStore.getState();
    // The resolved thread is the 1:1, NOT the group. (The 1:1 was never mutated.)
    expect(
      resolveProfileThreadId(undefined, st.activeProfileThreadId, st.threadIdByAgent, 'ezri'),
    ).toBe('one-to-one');
  });
});
