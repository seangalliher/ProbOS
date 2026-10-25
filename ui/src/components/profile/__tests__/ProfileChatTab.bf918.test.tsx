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
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, type RenderResult } from '@testing-library/react';

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
import { AgentProfilePanel } from '../AgentProfilePanel';
import { useStore } from '../../../store/useStore';
import type { Agent } from '../../../store/types';
import * as voice from '../../../audio/voice';
import { useMeetingVoice } from '../../../audio/useMeetingVoice';
import {
  armConversationMode,
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
/** BF-918 M7: when true, the media double delivers 'pause' after `pause()` returns. */
let deferPause = false;

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
  /** By default 'pause' fires inside `pause()`. BF-918 M7: `deferPause` delivers it a
   *  microtask later, after the caller has returned (a browser queues the event). C16
   *  runs both orders, so no case depends on either. */
  pause(): void {
    if (deferPause) {
      void Promise.resolve().then(() => this.emit('pause'));
      return;
    }
    this.emit('pause');
  }
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
  deferPause = false;
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

/** BF-918 (#1626) slices M6 and M7. M6: an older reply's 'end' must not complete a
 *  newer reply's turn in the same arm. M7: with AD-1071 pipelining on, a reply's turn
 *  completes on its last sentence's 'end' (M5's `final` is not `false`), not its
 *  first, and the BF-300 PTT gate stays closed between two sentences of one reply.
 *
 *  Same doubles as above. `/tts/status` answers `sentence_pipelining_enabled:
 *  pipelining`. Every TTS POST is held until the test answers it, oldest first, and
 *  the queue prepares one sentence ahead, so the next sentence's POST is made while
 *  the current one plays. Assertions are on the controller's state and on the
 *  rendered mic indicator, never on which branch ran. */
describe('BF-918 M6 and M7: a reply completes its turn on its own last sentence', () => {
  let pipelining = true;
  const GAP_MS = 5000; // ProfileChatTab's PTT_SENTENCE_GAP_MS (not exported)
  const TWO = 'First sentence. Second sentence.';
  const pauseOrders: Array<[string, boolean]> = [['inside pause()', false], ['after pause() returns', true]];

  beforeEach(() => {
    pipelining = true;
    const outer = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      if (String(url).endsWith('/tts/status')) {
        return respond({ enabled: true, backend: 'piper', sentence_pipelining_enabled: pipelining });
      }
      return outer(url, options);
    }));
  });

  const muted = (): boolean => screen.queryByTestId('mic-indicator-ring-muted') !== null;

  async function plays(index: number): Promise<void> {
    await waitFor(() => expect(audios[index]?.played).toBe(true));
  }

  /** The reply's first sentence is synthesized and plays; the second's POST is made. */
  async function firstSentencePlays(): Promise<void> {
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.']));
    await answerSynthesis();
    await plays(0);
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.']));
  }

  it('C13 (M6): an older reply\'s end does not complete the newer reply\'s turn, pipelining off', async () => {
    pipelining = false;
    answers = ['First answer.', 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.']));
    await answerSynthesis();
    await plays(0);
    // A transcript while the reply plays, with no barge-in (the Captain began talking
    // before the reply arrived): a newer reply takes the turn and queues behind it.
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    expect(ttsPosts).toEqual(['First answer.']);
    await endAudio(audios[0]);
    // Before M6: `silence_pending`, the newer turn ended by the older reply's 'end'.
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.', 'Second answer.']));
    await answerSynthesis();
    await plays(1);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C14 (M6 with M7): an older pipelined reply\'s sentences do not complete the newer reply\'s turn', async () => {
    answers = [TWO, 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await firstSentencePlays();
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    // Before M6 and M7: `silence_pending`, ended by the older reply's first sentence.
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await plays(1);
    await endAudio(audios[1]); // the older reply's last sentence: `final: true`
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.', 'Second answer.']));
    await answerSynthesis();
    await plays(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[2]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C15 (M7): a pipelined reply keeps its turn until its last sentence ends', async () => {
    answers = [TWO];
    await arm();
    await captainSays('Question.');
    expect(getConversationState()).toBe('agent_speaking');
    await firstSentencePlays();
    await endAudio(audios[0]);
    // Before M7: `silence_pending`, with the second sentence still to play.
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await plays(1);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it.each(pauseOrders)('C16 (M7, pause %s): barge-in still stops a pipelined reply after its first sentence', async (_order, deferred) => {
    deferPause = deferred;
    answers = [TWO];
    await arm();
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    await answerSynthesis();
    await plays(1);
    await bargeIn();
    // Before M7: `silence_pending` (the first sentence completed the turn), where barge-in does nothing.
    expect(getConversationState()).toBe('listening');
    // The second sentence was stopped, and its 'end' (`final: true`) delivered.
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
  });

  it('C17 control: with pipelining on, a one-sentence reply completes on its only end', async () => {
    answers = ['Only sentence.'];
    await arm();
    await captainSays('Question.');
    await waitFor(() => expect(ttsPosts).toEqual(['Only sentence.']));
    await answerSynthesis();
    await plays(0);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C18 (M7): a barge-in between two sentences leaves nothing that completes the next turn', async () => {
    answers = [TWO, 'Next answer.'];
    await arm();
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    await bargeIn(); // between the sentences: nothing plays, so no further 'end' comes
    // Before M7: `silence_pending`, where barge-in does nothing.
    expect(getConversationState()).toBe('listening');
    await answerSynthesis(); // the second sentence's synthesis answers late and is discarded
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(false);
    await captainSays('Next question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    await waitFor(() => expect(ttsPosts).toEqual(['First sentence.', 'Second sentence.', 'Next answer.']));
    await answerSynthesis();
    await plays(2);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[2]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C19 (M7, R25): the PTT gate stays closed between two sentences of one reply', async () => {
    answers = [TWO];
    await arm();
    expect(muted()).toBe(false);
    await captainSays('Question.');
    await firstSentencePlays();
    expect(muted()).toBe(true);
    await endAudio(audios[0]);
    // Before M7: false, and a mic press here started a capture that heard the next sentence.
    expect(muted()).toBe(true);
    await answerSynthesis();
    await plays(1);
    expect(muted()).toBe(true);
    await endAudio(audios[1]);
    expect(muted()).toBe(false);
  });

  it('C20 (M7, R25): a stop between two sentences reopens the PTT gate within the gap ceiling', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      answers = [TWO];
      await arm();
      await captainSays('Question.');
      await firstSentencePlays();
      await endAudio(audios[0]);
      // Before M7: false (every gap opened the gate).
      expect(muted()).toBe(true);
      await bargeIn();
      expect(getConversationState()).toBe('listening');
      await answerSynthesis(); // discarded: nothing more of this reply will play
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(GAP_MS - 2000); });
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      // BF-655's 45 s ceiling alone would still hold it closed here.
      expect(muted()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('C21 (M7, R25): the gate\'s ceiling follows the sentence that is playing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      answers = [TWO];
      await arm();
      await captainSays('Question.');
      await firstSentencePlays(); // the first sentence's 'start' arms BF-655's 45 s ceiling
      await endAudio(audios[0]);
      expect(muted()).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(4000); }); // inside the gap ceiling
      expect(muted()).toBe(true);
      await answerSynthesis();
      await plays(1); // the second sentence's 'start' re-arms the 45 s ceiling from here
      // 45.5 s after the first sentence's start, 41.5 s after the second's.
      await act(async () => { await vi.advanceTimersByTimeAsync(41500); });
      expect(muted()).toBe(true);
      await endAudio(audios[1]);
      expect(muted()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([['between two sentences', true], ['while a sentence plays', false]] as Array<[string, boolean]>)(
    'C22 (M7, review round 1): opening another crew member\'s profile %s leaves the new agent\'s mic ungated',
    async (_phase, inGap) => {
      const first: Agent = {
        id: 'a1', agentType: 'scout', callsign: 'First', displayName: 'First', pool: 'scout',
        state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain', isCrew: true, position: [0, 0, 0],
      };
      useStore.setState({
        agents: new Map([['a1', first], ['a2', { ...first, id: 'a2', callsign: 'Second', displayName: 'Second' }]]),
        activeProfileAgent: 'a1',
        activeProfileThreadId: null,
        activeThreadId: null,
        chatThreads: new Map(),
        threadIdByAgent: new Map(),
      });
      try {
        answers = [TWO];
        render(<AgentProfilePanel />);
        await waitFor(() => expect(getConversationState()).toBe('listening'));
        const composer = screen.getByPlaceholderText('Message...');
        await captainSays('Question.');
        await firstSentencePlays();
        if (inGap) await endAudio(audios[0]);
        expect(muted()).toBe(true);
        act(() => { useStore.getState().openAgentProfile('a2'); });
        await act(async () => { await flush(); });
        // The panel re-points the same composer at a2; it does not remount it.
        expect(screen.getByPlaceholderText('Message...')).toBe(composer);
        // Before A1: still `muted`, with no timer left to open it, because a2's
        // subscription ignores a1's later events. Between two sentences that was M7's
        // regression; during a sentence the base already did it.
        expect(muted()).toBe(false);
        const info = vi.spyOn(console, 'info');
        fireEvent.click(screen.getByTestId('mic-indicator').closest('button')!);
        expect(info.mock.calls.some((args) => String(args[0]).includes('mic press ignored for agent a2'))).toBe(false);
      } finally {
        useStore.setState({ activeProfileAgent: null, agents: new Map() });
      }
    },
  );

  it('C23 control (M7, review round 1): a re-render that keeps the agent keeps the gate closed between two sentences', async () => {
    answers = [TWO];
    const surface = render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    await captainSays('Question.');
    await firstSentencePlays();
    await endAudio(audios[0]);
    expect(muted()).toBe(true);
    surface.rerender(<ProfileChatTab agentId="a1" threadId="another-thread" />);
    await act(async () => { await flush(); });
    // The gate's effect depends on `agentId` only, so its cleanup did not run.
    expect(muted()).toBe(true);
    await answerSynthesis();
    await plays(1);
    expect(muted()).toBe(true);
    await endAudio(audios[1]);
    expect(muted()).toBe(false);
  });

  it('C24 (M7, review round 1): in a meeting the open mic stays refused until the reply\'s last sentence ends', async () => {
    let submits = 0;
    // The meeting's own gate: C9 (callAudioEnabled) above leaves the call audio muted in the shared store.
    useStore.setState({ callAudioEnabled: true });
    const meeting = renderHook(() => useMeetingVoice({ meetingActive: true, scopeKey: 'c24', owner: 'c24' }));
    // ProfileChatTab's meeting arm passes this predicate (AD-922's echo gate).
    const dispose = armConversationMode({
      agentId: 'a1',
      canListen: () => meeting.result.current.speakingAgentId == null,
      submitTranscript: async () => { submits += 1; },
    });
    try {
      await waitFor(() => expect(getConversationState()).toBe('listening'));
      expect(hardware.transcripts.size).toBe(1);
      act(() => { meeting.result.current.speakReplies([{ agent_id: 'a1', text: TWO }]); });
      await firstSentencePlays();
      expect(meeting.result.current.speakingAgentId).toBe('a1');
      await captainSays('Heard during the first sentence.');
      expect(submits).toBe(0);
      await endAudio(audios[0]);
      // Before A1: null (the first sentence's 'end' ended the wait), and the
      // transcript below was submitted while the second sentence played.
      expect(meeting.result.current.speakingAgentId).toBe('a1');
      await answerSynthesis();
      await plays(1);
      await captainSays('Heard during the second sentence.');
      expect(submits).toBe(0);
      await endAudio(audios[1]);
      await waitFor(() => expect(meeting.result.current.speakingAgentId).toBe(null));
      // Control: once the reply is over, the open mic submits.
      await captainSays('The Captain, after the reply.');
      expect(submits).toBe(1);
    } finally {
      dispose();
    }
  });
});
