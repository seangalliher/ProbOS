// AD-952: store slice tests for the typingAgent progressive-reveal indicator
// state. Session-scoped (no localStorage), default null.
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../useStore';

describe('AD-952 typingAgent store slice', () => {
  beforeEach(() => {
    useStore.getState().setTypingAgent(null);
  });

  it('defaults to null (nobody typing on boot)', () => {
    expect(useStore.getState().typingAgent).toBeNull();
  });

  it('setTypingAgent stores the agent + thread + callsign', () => {
    useStore.getState().setTypingAgent({ threadId: 't1', agentId: 'a1', callsign: 'Scout' });
    expect(useStore.getState().typingAgent).toEqual({ threadId: 't1', agentId: 'a1', callsign: 'Scout' });
  });

  it('setTypingAgent(null) clears it', () => {
    useStore.getState().setTypingAgent({ threadId: 't1', agentId: 'a1', callsign: 'Scout' });
    useStore.getState().setTypingAgent(null);
    expect(useStore.getState().typingAgent).toBeNull();
  });

  it('does not persist to localStorage (session-scoped)', () => {
    useStore.getState().setTypingAgent({ threadId: 't1', agentId: 'a1', callsign: 'Scout' });
    // No hxi_* key is written for the typing indicator.
    const keys = Object.keys(localStorage).filter((k) => k.toLowerCase().includes('typing'));
    expect(keys).toEqual([]);
  });

  // AD-962: the optional verb carries the generation-phase ("thinking") vs
  // compose-phase ("typing") distinction.
  it('carries the AD-962 "thinking" verb when set', () => {
    useStore.getState().setTypingAgent({ threadId: 't1', agentId: '', callsign: 'The crew', verb: 'thinking' });
    expect(useStore.getState().typingAgent).toEqual({ threadId: 't1', agentId: '', callsign: 'The crew', verb: 'thinking' });
  });
});
