/** AD-760 — voiceActivity AEC constraints + per-frame score fan-out. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  _peekPcmSubscriberCount,
  _processFrame,
  _resetPcmSubscribers,
  startVoiceActivity,
  stopVoiceActivity,
  subscribePcm,
  type PcmTapHandler,
} from '../audio/voiceActivity';
import * as silero from '../audio/silero-vad';

function installFakeMic(): { getUserMedia: ReturnType<typeof vi.fn> } {
  const getUserMedia = vi.fn().mockResolvedValue({
    getTracks: () => [{ stop: vi.fn() }],
  });
  (globalThis as any).navigator = { mediaDevices: { getUserMedia } };
  return { getUserMedia };
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
  stopVoiceActivity();
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetPcmSubscribers();
  stopVoiceActivity();
});

describe('AD-760 voiceActivity — AEC constraints', () => {
  it('startVoiceActivity calls getUserMedia with echo/noise/AGC constraints on', async () => {
    const { getUserMedia } = installFakeMic();
    stubVadSession([0.1]);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    const arg = getUserMedia.mock.calls[0][0];
    expect(arg).toEqual({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  });
});

describe('AD-760 voiceActivity — PcmTapHandler.onFrame score fan-out', () => {
  it('forwards Silero score as the third arg to subscribers', async () => {
    installFakeMic();
    stubVadSession([0.82, 0.41]);
    const received: Array<{ sr: number; score: number | undefined }> = [];
    const handler: PcmTapHandler = {
      onFrame: (_frame, sr, score) => received.push({ sr, score }),
    };
    const unsub = subscribePcm(handler);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });

    await _processFrame(new Float32Array(480).fill(0.2), 1000);
    await _processFrame(new Float32Array(480).fill(0.2), 1030);

    expect(received).toHaveLength(2);
    expect(received[0].sr).toBe(16000);
    expect(received[0].score).toBeCloseTo(0.82, 5);
    expect(received[1].score).toBeCloseTo(0.41, 5);
    unsub();
  });

  it('existing 2-arg subscribers continue to work (backward-compatible)', async () => {
    installFakeMic();
    stubVadSession([0.95]);
    // Subscriber declared without the new score arg; vitest still
    // checks runtime behavior is non-throwing.
    let callCount = 0;
    const handler: PcmTapHandler = {
      onFrame: (frame: Float32Array, sr: number) => {
        callCount += 1;
        expect(sr).toBe(16000);
        expect(frame.length).toBe(480);
      },
    };
    const unsub = subscribePcm(handler);
    await startVoiceActivity({ minSpeechMs: 0, scoreThreshold: 0.5 });
    await _processFrame(new Float32Array(480).fill(0.1), 2000);
    expect(callCount).toBe(1);
    unsub();
    expect(_peekPcmSubscriberCount()).toBe(0);
  });
});
