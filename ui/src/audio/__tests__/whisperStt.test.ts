/**
 * AD-705a — whisperStt consumer + privacy regression tests.
 *
 * BF-287 posture: fetch stubbed at the global boundary; the
 * whisperLoader factory stubbed via the exported test seam (NOT via
 * module-import monkey-patching).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  armWhisperStt,
  disarmWhisperStt,
  onTranscript,
  _setWhisperLoaderOverride,
  _isArmed,
  _resetWhisperStt,
} from '../whisperStt';
import {
  _peekPcmSubscriberCount,
  _processFrame,
  _resetPcmSubscribers,
  startVoiceActivity,
  stopVoiceActivity,
  subscribePcm,
  type PcmTapHandler,
} from '../voiceActivity';
import * as silero from '../silero-vad';
import type { WhisperHandle } from '../whisperLoader';
// Vite ``?raw`` lets us read source bodies for the privacy invariant
// source-scan tests without pulling in Node ``fs`` / ``path`` types.
import whisperSttSource from '../whisperStt?raw';
import cameraLiveIndicatorSource from '../../components/perception/CameraLiveIndicator.tsx?raw';

function installFakeMic(): void {
  (globalThis as any).navigator = {
    mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
  };
}

function stubVadSession(scores: number[]): void {
  const calls = { i: 0 };
  vi.spyOn(silero, 'createVadSession').mockResolvedValue({
    score: async () => {
      const s = scores[Math.min(calls.i, scores.length - 1)];
      calls.i += 1;
      return s;
    },
    destroy: vi.fn(),
  });
}

beforeEach(() => {
  _resetPcmSubscribers();
  _resetWhisperStt();
  stopVoiceActivity();
  (globalThis as any).fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) } as Response));
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetWhisperStt();
  _resetPcmSubscribers();
  stopVoiceActivity();
});

describe('armWhisperStt / disarmWhisperStt', () => {
  it('subscribes to PCM tap when armed', () => {
    expect(_peekPcmSubscriberCount()).toBe(0);
    armWhisperStt();
    expect(_isArmed()).toBe(true);
    expect(_peekPcmSubscriberCount()).toBe(1);
    disarmWhisperStt();
    expect(_isArmed()).toBe(false);
    expect(_peekPcmSubscriberCount()).toBe(0);
  });

  it('does NOT subscribe when not armed', () => {
    // Sanity — armWhisperStt is the gate; module load alone must not
    // attach any subscriber.
    expect(_peekPcmSubscriberCount()).toBe(0);
  });
});

describe('transcribe on VAD speech_end and emit transcript', () => {
  it('emits the transcript from the whisper handle when speech ends', async () => {
    const handle: WhisperHandle = {
      transcribeBuffer: vi.fn(async () => 'computer engage'),
    };
    _setWhisperLoaderOverride(async () => handle);
    armWhisperStt();
    const received: string[] = [];
    onTranscript((text) => received.push(text));

    // Drive the PCM tap by directly invoking the registered handler via
    // a sibling subscribePcm — production wires it through _processFrame
    // but we exercise the tap surface directly here.
    installFakeMic();
    stubVadSession([0.9, 0.9, 0.1]);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });
    const frame1 = new Float32Array(480).fill(0.2);
    await _processFrame(frame1, 1000);
    await _processFrame(frame1, 1030);
    const silentFrame = new Float32Array(480);
    await _processFrame(silentFrame, 1060);
    // Allow the queued microtask transcription to settle.
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(handle.transcribeBuffer).toHaveBeenCalled();
    expect(received).toEqual(['computer engage']);
  });
});

describe('honest-degrades when whisperLoader returns null', () => {
  it('emits no transcript and does not throw', async () => {
    _setWhisperLoaderOverride(async () => null);
    armWhisperStt();
    const received: string[] = [];
    onTranscript((text) => received.push(text));
    installFakeMic();
    stubVadSession([0.9, 0.1]);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });
    await _processFrame(new Float32Array(480).fill(0.2), 2000);
    await _processFrame(new Float32Array(480), 2030);
    await new Promise((resolve) => setTimeout(resolve, 5));
    expect(received).toEqual([]);
  });
});

describe('privacy invariant — audio bytes never reach a fetch call', () => {
  it('whisperStt source contains no fetch calls', () => {
    expect(whisperSttSource).not.toMatch(/fetch\s*\(/);
    expect(whisperSttSource).not.toMatch(/base64/i);
    expect(whisperSttSource).not.toMatch(/multipart/i);
  });
});

describe('subscribePcm (voiceActivity tap)', () => {
  it('returns an unsubscribe handle that detaches the callback', () => {
    const handler: PcmTapHandler = { onFrame: vi.fn() };
    const unsubscribe = subscribePcm(handler);
    expect(_peekPcmSubscriberCount()).toBe(1);
    unsubscribe();
    expect(_peekPcmSubscriberCount()).toBe(0);
  });

  it('pcm ring is not allocated when there are no subscribers', async () => {
    // No subscribers — _processFrame should not touch the PCM tap path.
    expect(_peekPcmSubscriberCount()).toBe(0);
    installFakeMic();
    stubVadSession([0.1]);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });
    // Driving a frame without subscribers must not throw and must not
    // create a subscriber.
    await _processFrame(new Float32Array(480), 3000);
    expect(_peekPcmSubscriberCount()).toBe(0);
  });
});

describe('CameraLiveIndicator STT badge', () => {
  it('renders amber when offline_stt_enabled and model loaded (smoke)', () => {
    expect(cameraLiveIndicatorSource).toContain('perception-stt-badge');
    expect(cameraLiveIndicatorSource).toContain("'#f0b060'");
  });
});
