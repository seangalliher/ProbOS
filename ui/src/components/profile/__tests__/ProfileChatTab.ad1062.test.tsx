// AD-1062: tests for the proactive call-open greeting. The full ProfileChatTab
// is too heavy to render (audio/screen deps) — same rationale as
// ProfileChatTab.groupsend.test.tsx — so the greeting logic is exercised through
// a faithful mirror of triggerCallGreeting + its once/yield guards. Source-level
// assertions (?raw) then pin the production wiring so the mirror can't silently
// drift from the real component.
import { describe, it, expect, vi, afterEach } from 'vitest';
import profileChatSource from '../ProfileChatTab.tsx?raw';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// A short stand-in for the production CALL_OPEN_TRIGGER. The mirror only needs
// *a* trigger string; the source-level suite below pins the real one.
const CALL_OPEN_TRIGGER = '(System: call opened — greet the Captain briefly.)';

// Faithful mirror of ProfileChatTab.triggerCallGreeting + the once/yield guards.
// If the production function changes, update this mirror (the source-level suite
// below will fail-loud if the production invariants disappear).
function makeGreeter(
  isOutputAudioEnabledNow: (agentId: string, threadId: string) => boolean = () => true,
) {
  const greeted = new Set<string>();
  const tokenRef = { current: 0 };
  const added: Array<{ role: string; text: string }> = [];
  const appended: Array<{ tid: string; text: string }> = [];
  const spoken: Array<{ tid: string; text: string }> = [];

  async function triggerCallGreeting(agentId: string, tid: string) {
    if (!tid || greeted.has(tid)) return;
    greeted.add(tid);
    const token = tokenRef.current;
    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: CALL_OPEN_TRIGGER, system_trigger: true, thread_id: tid }),
      });
      const data = await res.json();
      // Yield-if-you-speak-first: the Captain sent a message while the greeting
      // was generating -> drop it.
      if (token !== tokenRef.current) return;
      const reply = (data?.response as string) || '';
      // Honest-degrade: empty / placeholder / system reply -> open quietly.
      if (!reply || reply.startsWith('(') || data?.system === true) return;
      added.push({ role: 'agent', text: reply });
      appended.push({ tid, text: reply });
      if (isOutputAudioEnabledNow(agentId, tid)) spoken.push({ tid, text: reply });
    } catch {
      // Honest-degrade: a failed greeting just means the call opens quietly.
    }
  }

  // Captain speaks -> invalidate any in-flight greeting (sendText bump mirror).
  function captainSpeaks() { tokenRef.current += 1; }
  // End call -> allow a fresh greeting next call (handleEndCall mirror).
  function endCall(tid: string) { greeted.delete(tid); }

  return { triggerCallGreeting, captainSpeaks, endCall, added, appended, spoken, greeted };
}

describe('AD-1062 call-open greeting (mirror)', () => {
  it('posts the system-triggered greeting to /api/agent/{id}/chat with system_trigger=true', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ response: 'Good to see you, Captain.' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const g = makeGreeter();

    await g.triggerCallGreeting('a1', 't1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/a1/chat');
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.system_trigger).toBe(true);
    expect(body.thread_id).toBe('t1');
    expect(typeof body.message).toBe('string');
    expect(body.message.length).toBeGreaterThan(0);
    // The agent's reply is rendered as the greeting (per-agent buffer + thread).
    expect(g.added).toEqual([{ role: 'agent', text: 'Good to see you, Captain.' }]);
    expect(g.appended).toEqual([{ tid: 't1', text: 'Good to see you, Captain.' }]);
  });

  it('greets once per call — a second open of the same thread does not re-post', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ response: 'Hello.' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const g = makeGreeter();

    await g.triggerCallGreeting('a1', 't1');
    await g.triggerCallGreeting('a1', 't1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(g.added).toHaveLength(1);
  });

  it('re-greets after the call ends and reopens (End clears the once-flag)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, json: () => Promise.resolve({ response: 'Hello again.' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const g = makeGreeter();

    await g.triggerCallGreeting('a1', 't1');
    g.endCall('t1');
    await g.triggerCallGreeting('a1', 't1');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(g.added).toHaveLength(2);
  });

  it('yields if the Captain speaks first — an in-flight greeting that resolves late is dropped', async () => {
    // The json() resolves on a deferred promise we control, so the Captain can
    // "speak" (bump the token) before the greeting reply lands.
    let resolveJson: (v: unknown) => void = () => {};
    const jsonPromise = new Promise((r) => { resolveJson = r; });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => jsonPromise });
    vi.stubGlobal('fetch', fetchMock);
    const g = makeGreeter();

    const p = g.triggerCallGreeting('a1', 't1');
    g.captainSpeaks();                  // Captain sends a real message mid-greeting
    resolveJson({ response: 'Hi.' });   // the greeting reply finally arrives
    await p;

    // The greeting was dropped — no agent message added (no double-greeting / no
    // talking over the Captain's real turn).
    expect(g.added).toHaveLength(0);
    expect(g.appended).toHaveLength(0);
  });

  it('honest-degrade: an empty / placeholder / system / error reply yields no greeting', async () => {
    const g1 = makeGreeter();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ response: '' }) }));
    await g1.triggerCallGreeting('a1', 't1');
    expect(g1.added).toHaveLength(0);

    const g2 = makeGreeter();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ response: '(no response)' }) }));
    await g2.triggerCallGreeting('a1', 't2');
    expect(g2.added).toHaveLength(0);

    const g3 = makeGreeter();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ system: true, response: 'Personality set.' }) }));
    await g3.triggerCallGreeting('a1', 't3');
    expect(g3.added).toHaveLength(0);

    const g4 = makeGreeter();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')));
    await g4.triggerCallGreeting('a1', 't4');
    expect(g4.added).toHaveLength(0);
  });

  it('decides output audio after the deferred response by calling the injected live reader', async () => {
    let resolveJson: (v: unknown) => void = () => {};
    const jsonPromise = new Promise((resolve) => { resolveJson = resolve; });
    let audible = false;
    const liveReader = vi.fn((agentId: string, threadId: string) => (
      agentId === 'a1' && threadId === 't1' && audible
    ));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => jsonPromise }));
    const g = makeGreeter(liveReader);

    const pending = g.triggerCallGreeting('a1', 't1');
    audible = true;
    resolveJson({ response: 'Current state wins.' });
    await pending;

    expect(liveReader).toHaveBeenCalledWith('a1', 't1');
    expect(g.spoken).toEqual([{ tid: 't1', text: 'Current state wins.' }]);
  });
});

describe('AD-1062 production wiring (source-level)', () => {
  it('triggerCallGreeting posts the call-open trigger with system_trigger: true', () => {
    expect(profileChatSource).toMatch(/triggerCallGreeting/);
    expect(profileChatSource).toMatch(/system_trigger:\s*true/);
    expect(profileChatSource).toMatch(/CALL_OPEN_TRIGGER/);
  });

  it('uses a once-per-call ref and a yield-token ref', () => {
    expect(profileChatSource).toMatch(/greetedThreadsRef/);
    expect(profileChatSource).toMatch(/greetTokenRef/);
  });

  it('handleStartCall triggers the greeting and handleEndCall clears the once-flag', () => {
    expect(profileChatSource).toMatch(/void triggerCallGreeting\(tid\)/);
    expect(profileChatSource).toMatch(/greetedThreadsRef\.current\.delete\(activeThreadId\)/);
  });

  it('sendText bumps the yield token so the Captain speaking drops an in-flight greeting', () => {
    expect(profileChatSource).toMatch(/greetTokenRef\.current\s*\+=\s*1/);
  });

  it('uses the component live output-policy reader at the post-await greeting boundary', () => {
    expect(profileChatSource).toMatch(/isOutputAudioEnabledNow/);
    // BF-718 wrapped this call in the shared speech claim, so it is no longer
    // the head of its own `if (`. The property being guarded is unchanged: the
    // LIVE reader is consulted with the request's own agent and thread AFTER
    // the await, and its RESULT still gates the utterance — hence requiring a
    // `speakResponse` inside the block it opens, which keeps this from passing
    // if the call is moved or its result ignored. The bounded `[\s\S]` span
    // tolerates bookkeeping statements before the utterance without pinning
    // their exact formatting, which an exact match would turn into a false
    // regression on every unrelated edit. The behavioural proof is the mounted
    // BF-671 greeting tests in ProfileChatTab.audioControl.test.tsx.
    expect(profileChatSource).toMatch(
      /&& isOutputAudioEnabledNow\(requestAgentId, tid\)\s*\)\s*\{[\s\S]{0,400}?speakResponse\(/,
    );
  });

  it('the call-open trigger has no capability-gap phrasing', () => {
    // Pull the CALL_OPEN_TRIGGER literal out of source and assert it never
    // contains the gap phrases that confabulation/gap guards watch for.
    const m = profileChatSource.match(/const CALL_OPEN_TRIGGER =([\s\S]*?);/);
    expect(m).not.toBeNull();
    const triggerLiteral = (m?.[1] ?? '').toLowerCase();
    expect(triggerLiteral).not.toMatch(/can't|cannot|don't have|unable to/);
  });
});
