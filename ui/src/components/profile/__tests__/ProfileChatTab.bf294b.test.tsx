/**
 * BF-294b — PCM-tap subscription lifecycle tests for the audio-intensity
 * wiring added to ProfileChatTab. Uses a minimal wrapper component that
 * mirrors the same useEffect/useState pattern; the goal is to verify
 * the contract with voiceActivity.subscribePcm, not to render the full
 * ProfileChatTab (which has heavy store dependencies).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { useState, useEffect, useRef } from 'react';
import { render, act, cleanup } from '@testing-library/react';

const mockUnsubscribe = vi.fn();
const subscribers: Array<{ onFrame: (f: Float32Array, sr: number, s?: number) => void }> = [];

vi.mock('../../../audio/voiceActivity', () => ({
  subscribePcm: vi.fn((handler: any) => {
    subscribers.push(handler);
    return () => {
      mockUnsubscribe();
      const idx = subscribers.indexOf(handler);
      if (idx >= 0) subscribers.splice(idx, 1);
    };
  }),
}));

import { subscribePcm } from '../../../audio/voiceActivity';

function MicHarness({ listening }: { listening: boolean }) {
  const [intensity, setIntensity] = useState(0);
  const intensityRef = useRef(0);
  const rafPendingRef = useRef(false);
  useEffect(() => {
    if (!listening) {
      intensityRef.current = 0;
      setIntensity(0);
      return;
    }
    const EMA_ALPHA = 0.3;
    const GAIN = 3.0;
    const flush = () => {
      rafPendingRef.current = false;
      setIntensity(intensityRef.current);
    };
    const schedule = () => {
      if (rafPendingRef.current) return;
      rafPendingRef.current = true;
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flush);
      else flush();
    };
    const unsub = subscribePcm({
      onFrame(frame: Float32Array) {
        let sumSq = 0;
        for (let i = 0; i < frame.length; i++) sumSq += frame[i] * frame[i];
        const rms = frame.length > 0 ? Math.sqrt(sumSq / frame.length) : 0;
        const raw = Math.max(0, Math.min(1, rms * GAIN));
        intensityRef.current = EMA_ALPHA * raw + (1 - EMA_ALPHA) * intensityRef.current;
        schedule();
      },
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      intensityRef.current = 0;
      rafPendingRef.current = false;
      setIntensity(0);
    };
  }, [listening]);
  return <div data-testid="intensity">{intensity.toFixed(4)}</div>;
}

describe('ProfileChatTab BF-294b PCM-tap lifecycle', () => {
  beforeEach(() => {
    mockUnsubscribe.mockClear();
    subscribers.length = 0;
    (globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    };
  });
  afterEach(() => {
    cleanup();
    delete (globalThis as any).requestAnimationFrame;
  });

  it('listening=true subscribes to PCM tap', () => {
    render(<MicHarness listening={true} />);
    expect(subscribers.length).toBe(1);
    expect(mockUnsubscribe).not.toHaveBeenCalled();
  });

  it('listening=true → false unsubscribes and resets intensity', () => {
    const { rerender, getByTestId } = render(<MicHarness listening={true} />);
    act(() => {
      const frame = new Float32Array(480).fill(0.3);
      subscribers[0].onFrame(frame, 16000);
    });
    expect(parseFloat(getByTestId('intensity').textContent || '0')).toBeGreaterThan(0);
    rerender(<MicHarness listening={false} />);
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    expect(subscribers.length).toBe(0);
    expect(parseFloat(getByTestId('intensity').textContent || '0')).toBe(0);
  });

  it('unmount during listening unsubscribes (no leak)', () => {
    const { unmount } = render(<MicHarness listening={true} />);
    expect(subscribers.length).toBe(1);
    unmount();
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    expect(subscribers.length).toBe(0);
  });

  it('PCM frames drive non-zero intensity via RMS + EMA + GAIN', () => {
    const { getByTestId } = render(<MicHarness listening={true} />);
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const after1 = parseFloat(getByTestId('intensity').textContent || '0');
    expect(after1).toBeGreaterThan(0.25);
    expect(after1).toBeLessThan(0.35);
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const after2 = parseFloat(getByTestId('intensity').textContent || '0');
    expect(after2).toBeGreaterThan(after1);
    expect(after2).toBeLessThan(0.55);
  });

  it('silent frame (RMS=0) drives intensity toward 0 from previous high', () => {
    const { getByTestId } = render(<MicHarness listening={true} />);
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const peak = parseFloat(getByTestId('intensity').textContent || '0');
    expect(peak).toBeGreaterThan(0.5);
    act(() => {
      subscribers[0].onFrame(new Float32Array(480), 16000);
      subscribers[0].onFrame(new Float32Array(480), 16000);
    });
    const decayed = parseFloat(getByTestId('intensity').textContent || '0');
    expect(decayed).toBeLessThan(peak);
  });
});
