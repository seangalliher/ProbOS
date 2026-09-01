/** #787 — Voice end-to-end smoke test (deterministic Vitest integration).
 *
 * Wires the REAL <ProfileChatTab> against the REAL transformers.js STT module
 * (`../audio/transformersStt`, Xenova/whisper-tiny.en), mocking ONLY the two
 * stable boundaries that already expose injection seams:
 *   - the Web Worker (via `_setTransformersWorkerOverride`), and
 *   - the PCM tap (`subscribePcm` from `../audio/voiceActivity`).
 * Everything between — the PTT mic button, the BF-308 arm wiring, the BF-310
 * pre-roll, the BF-311 worker round-trip, the BF-294 mic state machine, and the
 * transcript→composer-input hand-off — runs REAL. This is the single red test
 * for the "voice doesn't work" regression class.
 *
 * Coverage map (honest):
 *   CAUGHT:
 *     - BF-308: PCM subscription + worker arm on mic press.
 *     - BF-310: pre-roll prepend (pre-speech frames lead the posted utterance).
 *     - BF-311: worker transcribe round-trip (samples + sampleRate reach the worker).
 *     - BF-294: idle → listening → processing → idle mic state machine.
 *     - the ProfileChatTab ↔ transformersStt transcript-to-input wiring
 *       ("voice produced text" lands in the composer).
 *   NOT CAUGHT (documented residual — forward marker, needs a real-browser
 *   Playwright spec, out of the per-commit gate):
 *     - BF-305: server model-artifact serving + real getUserMedia.
 *     - BF-306/307: real ORT / transformers dependency + dynamic-import specifier
 *       (the FakeWorker bypasses the real module load).
 *     - BF-309/315: worker-internal `_isMeaningfulTranscript` filter.
 *
 * Mock patterns are copied from `transformersStt.bf301.test.tsx` (FakeWorker +
 * subscribePcm capture) and `ProfileChatTab.bf294.test.tsx` / `.ad826.test.tsx`
 * (peripheral audio mocks + voice-health fetch). Two adaptations vs. those
 * sources, both forced by exercising the REAL component end-to-end:
 *   (a) the subscribePcm capture is an ARRAY, not a single slot — ProfileChatTab's
 *       BF-294b amplitude meter ALSO subscribes a tap on listening=true, so the
 *       test selects the STT tap (the one exposing `onSpeechStart`); and
 *   (b) `/api/voice/health` reports a transformers-primary + healthy engine so the
 *       PTT click reaches the REAL `armTransformersStt` branch (mirrors ad826).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';

// PCM-tap boundary (copied mechanism from transformersStt.bf301.test.tsx; the
// single `captured.handler` slot is widened to an array because the REAL
// ProfileChatTab subscribes a SECOND tap (BF-294b amplitude) while listening).
const pcm = vi.hoisted(() => {
  const handlers: any[] = [];
  const subscribePcmMock = vi.fn((handler: any) => {
    handlers.push(handler);
    return () => {
      const i = handlers.indexOf(handler);
      if (i >= 0) handlers.splice(i, 1);
    };
  });
  return { handlers, subscribePcmMock };
});

vi.mock('../audio/voiceActivity', () => ({
  subscribePcm: pcm.subscribePcmMock,
}));

// Peripheral audio modules — mocked exactly as ProfileChatTab.bf294.test.tsx so
// mount is clean. transformersStt and ProfileChatTab are deliberately REAL.
const mocks = vi.hoisted(() => ({
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  armConversationModeMock: vi.fn(() => () => {}),
  disarmConversationModeMock: vi.fn(),
  markAgentReplyCompleteMock: vi.fn(),
  speakResponseMock: vi.fn(),
  onSpeechEventMock: vi.fn(() => () => {}),
}));

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: mocks.onSpeechEventMock,
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationModeMock,
  disarmConversationMode: mocks.disarmConversationModeMock,
  markAgentReplyComplete: mocks.markAgentReplyCompleteMock,
}));

import {
  _setTransformersWorkerOverride,
  _resetTransformersStt,
} from '../audio/transformersStt';
import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

/** Minimal MessageChannel-free fake Worker (verbatim from transformersStt.bf301.test.tsx). */
class FakeWorker {
  static instances: FakeWorker[] = [];
  posted: any[] = [];
  terminated = false;
  listeners: Array<(e: MessageEvent) => void> = [];

  constructor() {
    FakeWorker.instances.push(this);
  }

  postMessage(message: any, _transfer?: any[]): void {
    this.posted.push(message);
  }

  addEventListener(_type: string, listener: (e: MessageEvent) => void): void {
    this.listeners.push(listener);
  }

  removeEventListener(_type: string, listener: (e: MessageEvent) => void): void {
    this.listeners = this.listeners.filter((l) => l !== listener);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** Simulate a worker → main thread message. */
  emit(data: any): void {
    const event = { data } as MessageEvent;
    for (const l of this.listeners) l(event);
  }
}

// Extends bf294's setDefaultFetch with the ad826 voice-health branch: a
// transformers-primary + healthy engine, so the PTT handler takes the REAL
// `armTransformersStt` branch instead of falling through to browser SR.
function setDefaultFetch(): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/api/voice/health')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          primary_stt: 'transformers',
          engine: 'transformers',
          backend_available: true,
          healthy: true,
          model: 'Xenova/whisper-tiny.en',
        }),
      }) as any;
    }
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

/** Drain the mount-effect promise chain (fetch → json → setState). Fake timers
 *  do NOT fake the microtask queue, so awaiting resolved promises advances it. */
async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 10; i++) {
      await Promise.resolve();
    }
  });
}

beforeEach(() => {
  // Fake timers keep every setTimeout deterministic — in particular the
  // transcript handler's trailing setTimeout(sendText, 100) (which clears the
  // input) never auto-fires, so the transcript-to-input assertion is stable.
  vi.useFakeTimers();
  FakeWorker.instances = [];
  pcm.handlers.length = 0;
  pcm.subscribePcmMock.mockClear();
  Object.values(mocks).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m) (m as any).mockReset();
  });
  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.onSpeechEventMock.mockReturnValue(() => {});
  localStorage.clear();
  _resetTransformersStt();
  _setTransformersWorkerOverride(() => new FakeWorker() as unknown as Worker);
  useStore.setState({
    voiceEnabled: true,
    agentConversations: new Map(),
  });
  setDefaultFetch();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  _resetTransformersStt();
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('#787 voice end-to-end smoke (REAL ProfileChatTab ↔ REAL transformersStt)', () => {
  it('mic press → arm → utterance → transcribing → transcript-to-input → idle', async () => {
    render(<ProfileChatTab agentId="yeo" />);
    // Settle mount effects so /api/voice/health is applied before the click.
    await flushMicrotasks();

    // (3) idle by default.
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');

    // voiceHealth applied → the button title reflects the transformers engine,
    // confirming the PTT handler will take the local-STT branch.
    const micButton = screen.getByLabelText('Voice input');
    expect(micButton.getAttribute('title')).toMatch(/transformers/);

    // (4) press the mic — REAL armTransformersStt instantiates the (fake) worker
    // and posts init; mic flips to listening. (BF-308 arm wiring)
    fireEvent.click(micButton);
    expect(FakeWorker.instances).toHaveLength(1);
    expect(FakeWorker.instances[0].posted[0]).toMatchObject({
      type: 'init',
      model: 'Xenova/whisper-tiny.en',
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');

    // (5) drive an utterance through the captured PCM tap. ProfileChatTab's
    // BF-294b amplitude meter ALSO subscribes on listening=true, so select the
    // STT tap (the one exposing onSpeechStart). Pre-speech frames seed the
    // BF-310 pre-roll; the prepend makes the posted sample count exceed the
    // in-speech frames. (BF-310 pre-roll + BF-311 worker round-trip)
    const tap = pcm.handlers.find((h) => typeof h?.onSpeechStart === 'function');
    expect(tap).toBeTruthy();
    tap.onFrame(new Float32Array([0.01, 0.02]), 16000); // pre-speech → pre-roll
    tap.onFrame(new Float32Array([0.03]), 16000); // pre-speech → pre-roll
    tap.onSpeechStart(0);
    tap.onFrame(new Float32Array([0.1, 0.2, 0.3]), 16000); // in-speech
    tap.onFrame(new Float32Array([0.4, 0.5]), 16000); // in-speech
    tap.onSpeechEnd(0);

    const worker = FakeWorker.instances[0];
    const transcribeMsg = worker.posted.find((m) => m.type === 'transcribe');
    expect(transcribeMsg).toBeTruthy();
    expect(transcribeMsg.sampleRate).toBe(16000);
    const inSpeechSamples = 5; // [0.1,0.2,0.3] + [0.4,0.5]
    expect(transcribeMsg.samples.length).toBeGreaterThanOrEqual(inSpeechSamples);
    // 3 pre-roll + 5 in-speech — the strict inequality proves the BF-310 prepend.
    expect(transcribeMsg.samples.length).toBe(8);

    // (6) worker signals transcribing → mic flips to processing. (BF-294)
    act(() => {
      worker.emit({ type: 'transcribing', active: true });
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');

    // (7) worker delivers the transcript → REAL transformersStt fans it out to the
    // ProfileChatTab listener, which lands it in the composer input. This is the
    // unique "voice produced text" integration seam.
    act(() => {
      worker.emit({ type: 'transcript', text: 'hello world', isPartial: false });
    });
    const composer = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    expect(composer.value).toBe('hello world');

    // (8) worker clears transcribing → mic returns to idle. (BF-294)
    act(() => {
      worker.emit({ type: 'transcribing', active: false });
    });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });
});
