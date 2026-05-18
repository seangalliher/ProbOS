/** AD-733c-3: IntentSurface wake-word -> engage fetch tests.
 *
 * Strategy: mock ``startWakeWordLoop`` and capture the ``onWake`` callback
 * it receives, then invoke that callback with synthetic ``WakeRoute``
 * payloads to assert the fetch behaviour. This keeps the test off the
 * actual mic/ONNX pipeline.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';

import { useStore } from '../store/useStore';

// Capture the onWake callback the IntentSurface registers.
let capturedOnWake: ((routed: any) => void) | null = null;

vi.mock('../audio/wakeWord', () => ({
  startWakeWordLoop: (onWake: (routed: any) => void) => {
    capturedOnWake = onWake;
    return Promise.resolve();
  },
  stopWakeWordLoop: () => {},
  getWakeWordState: () => 'idle',
  onWakeWordState: (_cb: any) => () => {},
  _cancelCurrentCapture: () => {},
}));

function makeAgent(id: string, callsign: string, wake_phrase: string) {
  return {
    id,
    agentType: callsign.toLowerCase(),
    callsign,
    displayName: `${callsign} role`,
    pool: callsign.toLowerCase(),
    state: 'active' as const,
    confidence: 0.8,
    trust: 0.7,
    tier: 'domain' as const,
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: 'engineering',
    voice_profile: { wake_phrase },
  };
}

beforeEach(() => {
  capturedOnWake = null;
  // Wake-word enabled so the loop starts and our mock captures onWake.
  try {
    localStorage.setItem('probos.wakeWord.enabled', 'true');
  } catch {
    // ignore
  }
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    wakeWordEnabled: true,
    agents: new Map([['e1', makeAgent('e1', 'ezri', 'Hello Ezri') as any]]),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    localStorage.removeItem('probos.wakeWord.enabled');
  } catch {
    // ignore
  }
});

describe('AD-733c-3 IntentSurface wake -> engage', () => {
  it('agent-surface wake fires POST /api/perception/engage exactly once', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    (globalThis as any).fetch = fetchMock;

    const { IntentSurface } = await import('../components/IntentSurface');
    render(<IntentSurface />);
    // Let the useEffect that calls startWakeWordLoop run.
    await new Promise((r) => setTimeout(r, 10));
    expect(capturedOnWake).not.toBeNull();

    act(() => {
      capturedOnWake!({
        surface: 'agent',
        agentCallsign: 'ezri',
        cleanedText: 'what am I holding',
      });
    });
    await new Promise((r) => setTimeout(r, 5));

    const engageCalls = fetchMock.mock.calls.filter(
      ([url]) => String(url) === '/api/perception/engage',
    );
    expect(engageCalls.length).toBe(1);
    const body = JSON.parse(engageCalls[0][1].body);
    expect(body.agent).toBe('ezri');
    expect(body.source).toBe('wake_word');
    expect(body.phrase).toBe('what am I holding');
  });

  it('system-surface wake does NOT fire engage', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    (globalThis as any).fetch = fetchMock;

    const { IntentSurface } = await import('../components/IntentSurface');
    render(<IntentSurface />);
    await new Promise((r) => setTimeout(r, 10));

    act(() => {
      capturedOnWake!({
        surface: 'system',
        cleanedText: 'computer status report',
      });
    });
    await new Promise((r) => setTimeout(r, 5));

    const engageCalls = fetchMock.mock.calls.filter(
      ([url]) => String(url) === '/api/perception/engage',
    );
    expect(engageCalls.length).toBe(0);
  });

  it('engage fetch failure is swallowed (chat submit still proceeds)', async () => {
    const fetchMock = vi.fn().mockImplementation((url: any) => {
      if (String(url) === '/api/perception/engage') {
        return Promise.reject(new Error('boom'));
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    (globalThis as any).fetch = fetchMock;
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { IntentSurface } = await import('../components/IntentSurface');
    render(<IntentSurface />);
    await new Promise((r) => setTimeout(r, 10));

    // Must not throw.
    act(() => {
      capturedOnWake!({
        surface: 'agent',
        agentCallsign: 'ezri',
        cleanedText: 'help',
      });
    });
    await new Promise((r) => setTimeout(r, 20));
    // We never re-throw -- the test reaching here is the assertion.
    expect(warnSpy).toHaveBeenCalled();
  });
});
