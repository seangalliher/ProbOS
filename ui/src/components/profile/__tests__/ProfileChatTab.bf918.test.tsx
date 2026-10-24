/** BF-918 (#1626), review round 2, area C finding 1: a conversation-mode reply
 *  stopped before any of its audio started ends with AD-1291's 'dropped'
 *  (`cancelled-before-audio`, D7a), never 'end'. ProfileChatTab must release on
 *  it what an 'end' releases: the BF-718 in-flight key (otherwise a later
 *  identical answer, which loses the speech claim, waits on an 'end' that no
 *  utterance will emit, and the controller stays `agent_speaking`), and the
 *  reply's own completion listener, which completes the turn only while that
 *  reply is still the newest.
 *
 *  Real ProfileChatTab, conversation controller, voice.ts and speech arbiter.
 *  Doubles only at the boundaries: fetch (the TTS POST is HELD until the test
 *  answers it, which is how a stop lands before the audio), the media element,
 *  speechSynthesis, and the microphone / STT / VAD taps. Adapted from the
 *  round-2 reviewer's executed probe.
 *
 *  Assertions are on the controller's state (the turn), never on which branch ran.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react';

const hardware = vi.hoisted(() => ({
  transcripts: new Set<(text: string) => void>(),
  pcm: new Set<{ onSpeechStart?: () => void }>(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: () => () => {},
  disarmTransformersStt: () => {},
  onTransformersTranscript: (fn: (text: string) => void) => {
    hardware.transcripts.add(fn);
    return () => { hardware.transcripts.delete(fn); };
  },
  onTransformersTranscribing: () => () => {},
  onTransformersProgress: () => () => {},
}));

vi.mock('../../../audio/voiceActivity', () => ({
  subscribePcm: (handler: { onSpeechStart?: () => void }) => {
    hardware.pcm.add(handler);
    return () => { hardware.pcm.delete(handler); };
  },
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';
import * as voice from '../../../audio/voice';
import {
  getConversationState,
  onConversationState,
  _resetConversationControllerForTests,
} from '../../../audio/conversationController';
import { _resetForTests as resetMicArbiter } from '../../../audio/speechRecognitionArbiter';

const REPEATED = 'Repeatable answer.';
const CANCELLED: [string, string | undefined] = ['dropped', 'cancelled-before-audio'];

let audios: MediaDouble[] = [];
let held: Array<() => void> = [];
let ttsPosts: string[] = [];
let chats = 0;
let answers: string[] = [];
let events: Array<[string, string | undefined]> = [];
let off: () => void = () => {};

class UtteranceDouble {
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: unknown = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  text: string;
  constructor(text: string) { this.text = text; }
}

/** The media element. `play` resolves: in these cases the stop lands while the
 *  synthesis answer is still held, before any audio exists. */
class MediaDouble {
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  played = false;
  src: string;
  private listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; audios.push(this); }
  addEventListener(type: string, fn: () => void): void { (this.listeners[type] ??= []).push(fn); }
  emit(type: string): void { for (const fn of this.listeners[type] ?? []) fn(); }
  play(): Promise<void> { this.played = true; this.emit('play'); return Promise.resolve(); }
  pause(): void { this.emit('pause'); }
  removeAttribute(): void { this.src = ''; }
  load(): void { /* double */ }
  end(): void { this.emit('ended'); }
}

function respond(body: unknown): Response {
  return { ok: true, json: async () => body } as unknown as Response;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 60; i += 1) await Promise.resolve();
}

async function arm(): Promise<void> {
  render(<ProfileChatTab agentId="a1" />);
  await waitFor(() => expect(getConversationState()).toBe('listening'));
  expect(hardware.transcripts.size).toBe(1);
}

async function captainSays(text: string): Promise<void> {
  await act(async () => { for (const cb of [...hardware.transcripts]) cb(text); await flush(); });
}

async function bargeIn(): Promise<void> {
  await act(async () => { for (const h of [...hardware.pcm]) h.onSpeechStart?.(); await flush(); });
}

async function answerSynthesis(): Promise<void> {
  const next = held.shift();
  expect(next).toBeDefined();
  await act(async () => { next?.(); await flush(); });
}

async function endAudio(audio: MediaDouble): Promise<void> {
  await act(async () => { audio.end(); await flush(); });
}

beforeEach(() => {
  hardware.transcripts.clear();
  hardware.pcm.clear();
  resetMicArbiter();
  _resetConversationControllerForTests();
  voice._resetTtsStatusForTests();
  audios = [];
  held = [];
  ttsPosts = [];
  chats = 0;
  answers = [];
  events = [];
  vi.stubGlobal('Audio', MediaDouble);
  vi.stubGlobal('SpeechSynthesisUtterance', UtteranceDouble);
  vi.stubGlobal('speechSynthesis', { cancel: vi.fn(), speak: vi.fn(), getVoices: () => [], addEventListener: vi.fn() });
  localStorage.clear();
  localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation');
  localStorage.setItem('hxi_chat_tts_a1', '1');
  useStore.setState({
    voiceEnabled: true, agentConversations: new Map(), activeProfileThreadId: null, threadIdByAgent: new Map(),
  });
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
    const path = String(url);
    if (path.endsWith('/tts/status')) {
      return respond({ enabled: true, backend: 'piper', sentence_pipelining_enabled: false });
    }
    if (path === '/api/avatars/tts') {
      ttsPosts.push(JSON.parse(String(options?.body)).text);
      return new Promise<Response>((resolve) => {
        held.push(() => resolve(respond({ backend: 'piper', audio_attachment_id: 'a'.repeat(64), visemes: [] })));
      });
    }
    if (path === '/api/agent/a1/chat') {
      chats += 1;
      return respond({ response: answers.shift() ?? REPEATED });
    }
    if (path.endsWith('/chat/history')) return respond({ memories: [] });
    if (path.endsWith('/profile')) return respond({ voiceProfile: null });
    return respond({});
  }));
  off = voice.onSpeechEvent((e) => { events.push([e.type, e.reason]); });
});

afterEach(() => {
  off();
  cleanup();
  _resetConversationControllerForTests();
  resetMicArbiter();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('BF-918 review round 2: a dropped reply releases what its end would have released', () => {
  it('C1 control: a reply that ended leaves no in-flight claim, so a later identical answer completes at once', async () => {
    await arm();
    await captainSays('First question.');
    expect(chats).toBe(1);
    expect(ttsPosts).toEqual([REPEATED]);
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios).toHaveLength(1);
    expect(audios[0].played).toBe(true);
    await endAudio(audios[0]);
    expect(getConversationState()).toBe('silence_pending');
    await captainSays('Second question.');
    expect(chats).toBe(2);
    // BF-718: the same text was already said in this scope, so it is not spoken again.
    expect(ttsPosts).toEqual([REPEATED]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C2: a reply stopped before its audio leaves no in-flight claim, so a later identical answer completes at once', async () => {
    await arm();
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await bargeIn();
    expect(getConversationState()).toBe('listening');
    await answerSynthesis(); // the stopped reply's synthesis answers late
    expect(events).toEqual([CANCELLED]);
    expect(audios.every((audio) => !audio.played)).toBe(true);
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(ttsPosts).toEqual([REPEATED]);
    // Before the fix: `agent_speaking`, waiting on an 'end' that nothing emits.
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C3: the late drop of a stopped reply does not complete the newer turn', async () => {
    answers = ['First answer.', 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await bargeIn();
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    // The newer reply waits in the arbiter behind the stopped one, whose synthesis is held.
    expect(ttsPosts).toEqual(['First answer.']);
    await answerSynthesis();
    expect(events).toEqual([CANCELLED]);
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.', 'Second answer.']));
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(events.map(([type]) => type)).toEqual(['dropped', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C4: a reply whose own audio never started completes its turn while it is still the newest', async () => {
    await arm();
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    // A stop the controller did not make (GUARD 2's newer dispatch lands the same
    // 'dropped'): the controller is still waiting on this turn's speech.
    await act(async () => { voice.stopSpeaking(); await flush(); });
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(events).toEqual([CANCELLED]);
    // Before the fix: `agent_speaking`, with no silence-release timer.
    expect(getConversationState()).toBe('silence_pending');
  });
});

/** BF-918 (#1626), review round 3, area C finding 1: a reply's completion
 *  listener ends with the conversation arm that set it up. The controller's
 *  `markAgentReplyComplete` completes whichever arm owns it when it is called,
 *  so a listener that outlived its arm ended the NEXT arm's turn on its own late
 *  'dropped' (the round-2 repair) or 'end' (as on main). One case per way an arm
 *  ends. Each old reply is agent a1's; each replacement queues in the speech
 *  arbiter behind it, so the replacement's controller is in `agent_speaking`
 *  when the old terminal event lands. Assertions are on the controller's state. */
describe('BF-918 review round 3: a reply completion ends with its arm', () => {
  let voiceProfileAnswer: unknown = null;
  let byAgent: Array<[string, string | undefined]> = [];
  let states: string[] = [];
  let offAgents: () => void = () => {};
  let offStates: () => void = () => {};

  beforeEach(() => {
    voiceProfileAnswer = null;
    byAgent = [];
    states = [];
    localStorage.setItem('hxi_chat_mic_mode_a2', 'conversation');
    localStorage.setItem('hxi_chat_tts_a2', '1');
    const outer = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      const path = String(url);
      if (path === '/api/agent/a2/chat') {
        chats += 1;
        return respond({ response: answers.shift() ?? REPEATED });
      }
      if (path.endsWith('/profile')) return respond({ voiceProfile: voiceProfileAnswer });
      // A thread id (C9) is answered "not found": its transcript stays empty.
      if (path.startsWith('/api/threads/')) {
        return { ok: false, status: 404, json: async () => ({}) } as unknown as Response;
      }
      return outer(url, options);
    }));
    offAgents = voice.onSpeechEvent((e) => { byAgent.push([e.type, e.agent_id]); });
    offStates = onConversationState((state) => { states.push(state); });
  });

  afterEach(() => {
    offAgents();
    offStates();
  });

  async function armFor(agentId: string): Promise<RenderResult> {
    const view = render(<ProfileChatTab agentId={agentId} />);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    return view;
  }

  /** The first reply's synthesis answers and its audio plays: an 'end' is coming. */
  async function oldReplyPlays(): Promise<MediaDouble> {
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios).toHaveLength(1);
    expect(audios[0].played).toBe(true);
    return audios[0];
  }

  /** The arm ends by `change` and a new arm takes the controller. */
  async function armEnds(change: () => Promise<void>): Promise<void> {
    await change();
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    expect(states).toContain('inactive');
  }

  /** The new arm's own reply. It queues behind the old utterance, which still
   *  owns the device, so its synthesis is not requested yet. */
  async function replacementAsks(): Promise<void> {
    await captainSays('Replacement question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    expect(ttsPosts).toHaveLength(1);
  }

  async function oldEndLands(old: MediaDouble): Promise<void> {
    await endAudio(old);
    expect(byAgent.filter(([type, agent]) => type === 'end' && agent === 'a1')).toHaveLength(1);
  }

  /** Only the replacement's own audio ending may complete its turn. */
  async function replacementPlaysAndEnds(): Promise<void> {
    await waitFor(() => expect(ttsPosts).toHaveLength(2));
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(getConversationState()).toBe('silence_pending');
  }

  async function selectMicMode(mode: 'ptt' | 'conversation'): Promise<void> {
    await act(async () => {
      fireEvent.contextMenu(screen.getByRole('button', { name: 'Voice input' }));
      await flush();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId(`profile-chat-mic-mode-${mode}`));
      await flush();
    });
  }

  it('C5: after an unmount, the old reply\'s late drop does not complete the next profile\'s turn', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    await captainSays('First question.');
    expect(ttsPosts).toEqual(['Unmounted answer.']);
    await bargeIn(); // stopped while its synthesis is held: its terminal event will be 'dropped'
    expect(getConversationState()).toBe('listening');
    first.unmount();
    expect(getConversationState()).toBe('inactive');
    await armFor('a2');
    await replacementAsks();
    await answerSynthesis(); // the unmounted reply's synthesis answers late
    expect(events).toEqual([CANCELLED]);
    expect(byAgent).toEqual([['dropped', 'a1']]);
    // Before the fix: `silence_pending`, the replacement's turn ended by the old drop.
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C6: after an unmount, the old reply\'s late end does not complete the next profile\'s turn', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    const old = await oldReplyPlays();
    first.unmount(); // its utterance is dispatched, so the unmount's flush leaves it playing
    expect(getConversationState()).toBe('inactive');
    await armFor('a2');
    await replacementAsks();
    await oldEndLands(old);
    // Before the fix, and on main: `silence_pending`, ended by the old reply's 'end'.
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C7: after the agent changes on the same mount, the old reply\'s late end does not complete the new turn', async () => {
    answers = ['Old agent answer.', 'New agent answer.'];
    const view = await armFor('a1');
    const old = await oldReplyPlays();
    await armEnds(async () => {
      await act(async () => { view.rerender(<ProfileChatTab agentId="a2" />); await flush(); });
    });
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C8: after mic mode goes conversation, off and back, the old reply\'s late end does not complete the re-armed turn', async () => {
    answers = ['Before the mode change.', 'After the mode change.'];
    await armFor('a1');
    const old = await oldReplyPlays();
    await selectMicMode('ptt');
    expect(getConversationState()).toBe('inactive');
    await armEnds(() => selectMicMode('conversation'));
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  // `ttsKey` is derived from `agentId` and `speechOwner` is fixed per mount, so
  // C7 and C5/C6 are their cases. `meetingActive` reaches a 1:1 arm again only
  // through a second change: the same React cleanup, with call speech this
  // harness does not model.
  const dependencyChanges: Array<[string, (view: RenderResult) => Promise<void>]> = [
    ['threadId', async (view) => {
      await act(async () => {
        view.rerender(<ProfileChatTab agentId="a1" threadId="bf918-thread" />);
        await flush();
      });
    }],
    ['voiceProfile', async () => {
      voiceProfileAnswer = { voice_name: 'test', pitch: 1, rate: 1, volume: 1 };
      await act(async () => {
        window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: 'a1' } }));
        await flush();
      });
    }],
    ['callAudioEnabled', async () => {
      await act(async () => {
        useStore.setState({ callAudioEnabled: !useStore.getState().callAudioEnabled });
        await flush();
      });
    }],
  ];

  it.each(dependencyChanges)('C9 (%s): after the arm re-runs on that change, the old reply\'s late end does not complete the new turn', async (_name, change) => {
    answers = ['Before the change.', 'After the change.'];
    const view = await armFor('a1');
    const old = await oldReplyPlays();
    await armEnds(() => change(view));
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C10: when a second profile arms, the first profile\'s late end does not complete the second one\'s turn', async () => {
    answers = ['First surface answer.', 'Second surface answer.'];
    await armFor('a1');
    const old = await oldReplyPlays();
    // The first profile stays mounted, so React never cleans its arm up: only the
    // controller's 'inactive' to its options tells it that its arm has ended.
    await armEnds(async () => { render(<ProfileChatTab agentId="a2" />); });
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C11 control: under StrictMode\'s double effect run, a reply still completes on its own end', async () => {
    render(<React.StrictMode><ProfileChatTab agentId="a1" /></React.StrictMode>);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios[0].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    // BF-290's stuck turn would stay `agent_speaking` here.
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C12: an unmount retires the reply even when the controller dropped the arm without telling it', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    const old = await oldReplyPlays();
    // The controller's test seam tears the arm down with no 'inactive' to its
    // options (as a pre-empted arm whose queued 'inactive' a later job superseded
    // would be): only the React cleanup is left to retire the reply.
    act(() => { _resetConversationControllerForTests(); });
    expect(getConversationState()).toBe('inactive');
    first.unmount();
    await armFor('a2');
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });
});
