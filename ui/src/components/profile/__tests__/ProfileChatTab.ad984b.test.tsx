// AD-984b: tests for the ProfileChatTab transcript a11y + meeting-condensed
// strip + empty-state contrast. Mirrors ProfileChatTabVoice.test.tsx's mock
// header (../audio/voice, ../audio/speechInput, global.fetch, scrollIntoView
// polyfill) with the relative depths adjusted for this __tests__ location, plus
// two additions the meeting path needs: `prewarmTts` in the voice mock (called
// by useMeetingVoice when meetingActive=true) and a MeetingView stub (it mounts
// when meeting_active, pulling in R3F/VRM otherwise). Seeds the REAL store
// (BF-287).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  speakResponseMock: vi.fn(),
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  supportedRef: { v: true },
}));

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  // AD-718d-1: ModulationIndicator subscribes via onSpeechEvent — no-op unsub.
  onSpeechEvent: vi.fn(() => () => {}),
  // AD-984b: useMeetingVoice prewarms TTS when meetingActive=true.
  prewarmTts: vi.fn(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => mocks.supportedRef.v,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

// AD-984b: the condensed test sets meeting_active=true, which mounts MeetingView
// (R3F/VRM). Stub it to a marker div so this DOM-only test stays isolated.
vi.mock('../MeetingView', () => ({
  MeetingView: () => <div data-testid="meeting-view-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew ?? true,
    position: [0, 0, 0] as [number, number, number],
    department: '',
  } as Agent;
}

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    id: over.id,
    title: over.title ?? 'Room',
    participants: over.participants ?? [],
    created_at: over.created_at ?? 0,
    last_active_at: over.last_active_at ?? 0,
    metadata: over.metadata,
  };
}

beforeEach(() => {
  mocks.speakResponseMock.mockReset();
  mocks.startListeningMock.mockReset();
  mocks.stopListeningMock.mockReset();
  mocks.supportedRef.v = true;
  // jsdom does not implement scrollIntoView.
  if (!(Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView) {
    (Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = vi.fn();
  }
  localStorage.clear();
  useStore.setState({
    voiceEnabled: false,
    agentConversations: new Map(),
    agents: new Map(),
    chatThreads: new Map(),
    threadMessages: new Map(),
    meetingChatVisible: true,
  });
  global.fetch = vi.fn((url: unknown) => {
    const u = String(url);
    if (u.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ memories: [] }) }) as unknown as Promise<Response>;
    }
    if (u.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as unknown as Promise<Response>;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as unknown as Promise<Response>;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map(), threadMessages: new Map(), meetingChatVisible: true });
  vi.clearAllMocks();
});

describe('AD-984b ProfileChatTab transcript a11y + condensed + contrast', () => {
  it('the transcript is an aria-live polite log region', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const transcript = await screen.findByTestId('chat-transcript');
    expect(transcript.getAttribute('role')).toBe('log');
    expect(transcript.getAttribute('aria-live')).toBe('polite');
    expect(transcript.getAttribute('aria-label')).toBe('Conversation transcript');
  });

  it('out of a meeting the transcript is not condensed', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const transcript = await screen.findByTestId('chat-transcript');
    expect(transcript.getAttribute('data-condensed')).toBe('false');
  });

  it('in a meeting with the chat shown the transcript is condensed + height-sized', async () => {
    useStore.setState({
      agents: new Map([['a1', mkAgent({ id: 'a1', callsign: 'Vex' })]]),
      chatThreads: new Map([
        ['t1', mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } })],
      ]),
      meetingChatVisible: true,
    });
    render(<ProfileChatTab agentId="agent-007" threadId="t1" />);
    const transcript = await screen.findByTestId('chat-transcript');
    expect(transcript.getAttribute('data-condensed')).toBe('true');
    // AD-1075: the condensed transcript is now a resizable, height-driven strip
    // (default 200px, persisted) instead of the old fixed maxHeight:160 cap.
    expect((transcript as HTMLElement).style.height).toBe('200px');
  });

  it('the empty-state hint uses the AA-contrast color (rgb(154,154,178))', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const hint = await screen.findByText('Send a message to start a conversation.');
    expect((hint as HTMLElement).style.color).toBe('rgb(154, 154, 178)');
  });
});
