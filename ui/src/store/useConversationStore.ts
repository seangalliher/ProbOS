/**
 * AD-747 — Conversation Zustand slice.
 *
 * Mirror of the conversationController state machine for HXI consumers
 * (CONV badge, transcript-preview pill, IntentSurface button demotion).
 * The controller is the source of truth; this store is a one-way
 * projection updated by the controller's onStateChange listener.
 */
import { create } from 'zustand';
import type { ConversationState } from '../audio/conversationController';

interface ConversationStoreState {
  state: ConversationState;
  agentId: string | null;
  /** Most-recent transcript surfaced for the preview pill. */
  lastTranscript: string;
  /** Most-recent agent reply surfaced for HXI. */
  lastAgentReply: string;
  setState: (s: ConversationState) => void;
  setAgentId: (id: string | null) => void;
  setLastTranscript: (text: string) => void;
  setLastAgentReply: (text: string) => void;
  resetForTests: () => void;
}

export const useConversationStore = create<ConversationStoreState>((set) => ({
  state: 'inactive',
  agentId: null,
  lastTranscript: '',
  lastAgentReply: '',
  setState: (s) => set({ state: s }),
  setAgentId: (id) => set({ agentId: id }),
  setLastTranscript: (text) => set({ lastTranscript: text }),
  setLastAgentReply: (text) => set({ lastAgentReply: text }),
  resetForTests: () =>
    set({
      state: 'inactive',
      agentId: null,
      lastTranscript: '',
      lastAgentReply: '',
    }),
}));
