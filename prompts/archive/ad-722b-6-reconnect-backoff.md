# AD-722b-6 — WebSocket Reconnect with Capped Exponential Backoff

**Status:** Ready
**Parent:** AD-722b (Wave 142, shipped commit 7e08110)
**Closes:** GH #603
**Estimated tests:** +4 Vitest (in `ui/src/__tests__/SelfImageTab.test.tsx`)

## Problem

The WS client in `SelfImageTab.tsx` (lines ~125-195) handles open/close/error but does not reconnect. On any close event it falls back to 2 s HTTP polling permanently — even for a transient network hiccup. The HIGH-tier push channel (established by Wave 142 via `enter_popout`) is silently demoted to LOW-tier polling for the rest of the session.

The existing code carries an explicit forward marker:

> `// Whether or not we had opened, fall back to poll. Reconnect with`
> `// backoff is forward marker AD-722b-6.`
> — `SelfImageTab.tsx:~189`

## Solution

Add a reconnect state machine inside the existing `useEffect`. On close:

1. Start poll fallback immediately (no UX gap — same as today).
2. Schedule a reconnect attempt after `delayMs(attempt)`.
3. Backoff schedule: `Math.min(30_000, 1000 * 2 ** attempt)` = 1s, 2s, 4s, 8s, 16s, 30s, 30s, ...
4. Cap at 10 attempts. After the 10th failure, log and remain on poll fallback.
5. On any successful WS open, reset `attempt = 0` and stop poll fallback (current behavior).

## Implementation

### Section 1 — Reconnect state inside the useEffect

`ui/src/components/profile/SelfImageTab.tsx` — the WS-setup `useEffect` block.

Builder must:

1. **Hoist** the existing WS-setup code into a named inner function `openWebSocket()` so it can be re-invoked. Existing variables (`ws`, `wsOpened`, `wsTimeoutId`) move inside the function; the function returns nothing and assigns to outer closure-scoped refs.
2. Add three new closure variables:
   - `let reconnectAttempt = 0;`
   - `let reconnectTimeoutId: number | null = null;`
   - `const MAX_RECONNECT_ATTEMPTS = 10;`
3. Modify `ws.onopen` to reset: `reconnectAttempt = 0;`.
4. Modify `ws.onclose` to schedule reconnect (instead of only falling back to poll):

```typescript
      ws.onclose = () => {
        if (cancelled) return;
        // AD-722b-6: poll fallback covers the gap while we attempt reconnect.
        startPollFallback();
        if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
          // Give up; remain on poll fallback. Visible via existing UI
          // disabled-state pattern from AD-722a-5.
          // eslint-disable-next-line no-console
          console.warn(
            `AD-722b-6: WS reconnect exhausted after ${MAX_RECONNECT_ATTEMPTS} attempts; staying on poll fallback`
          );
          return;
        }
        const delayMs = Math.min(30_000, 1000 * 2 ** reconnectAttempt);
        reconnectAttempt += 1;
        reconnectTimeoutId = window.setTimeout(() => {
          reconnectTimeoutId = null;
          if (!cancelled) openWebSocket();
        }, delayMs);
      };
```

5. Extend the cleanup return function:

```typescript
      if (reconnectTimeoutId !== null) {
        clearTimeout(reconnectTimeoutId);
        reconnectTimeoutId = null;
      }
```

Preserve the existing `try { ... } catch` around the WebSocket constructor — wraps the body of `openWebSocket()`. The first call to `openWebSocket()` happens at the same point in `useEffect` where the WS is currently opened.

### Section 2 — Vitest scenarios

Append to `ui/src/__tests__/SelfImageTab.test.tsx`. The existing test file already stubs `WebSocket`. Use Vitest fake timers:

```typescript
describe('AD-722b-6 reconnect with backoff', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('schedules reconnect at 1s after first close', async () => {
    // 1. Render component, observe WebSocket constructor called once.
    // 2. Trigger ws.onopen, then ws.onclose.
    // 3. Advance timers by 999 ms — assert constructor still called once.
    // 4. Advance timers by 2 ms — assert constructor called twice (reconnect fired).
  });

  it('uses exponential schedule 1s/2s/4s/8s', async () => {
    // Open then close 4 times in succession, advance fake timers,
    // assert constructor call count matches the schedule.
  });

  it('stops reconnecting after 10 failed attempts', async () => {
    // Loop 11 closes, advancing timer by 30 s each iteration.
    // Assert constructor called exactly 1 (initial) + 10 (reconnects) = 11 times.
    // Assert console.warn was called with "AD-722b-6: WS reconnect exhausted".
  });

  it('resets attempt counter on successful reconnect', async () => {
    // Close, reconnect, open (success), close again.
    // Assert second-cycle first reconnect happens at 1s, not at 2s.
  });
});
```

If the existing mock doesn't expose `onopen`/`onclose` simulation hooks, extend it minimally; do not rewrite.

## What this does NOT change

- WS URL, frame protocol, close codes — unchanged.
- 5 s open-timeout-to-poll-fallback behavior — unchanged.
- Poll-fallback interval, fetchOnce behavior — unchanged.
- AD-722a-5 divergence-history panel rendering — unchanged.

## Out of scope (do not build)

- Refactoring the inline WS client into a custom hook or separate module.
- Reconnect for the federation cross-mesh push (AD-722b-5, #602).
- Jittered backoff. The cap + 10-attempt limit is sufficient DOS protection.
- Surfacing "disconnected" badge in the UI; the existing `error` state is reused via `console.warn` for exhausted attempts.

## Acceptance criteria

- [ ] All 4 new Vitest scenarios green.
- [ ] Existing `SelfImageTab.test.tsx` scenarios unchanged and green.
- [ ] `SelfImageTab.divergenceHistory.test.tsx` unchanged and green (AD-722a-5).
- [ ] No new dependencies in `ui/package.json`.
- [ ] Cleanup return function clears `reconnectTimeoutId` on unmount.
- [ ] Backoff cap = 30 s; max attempts = 10; both enforced by tests.
- [ ] Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-11, HEAD e066c0b)

```
grep -n "AD-722b-6" ui/src/components/profile/SelfImageTab.tsx
  ~189: // backoff is forward marker AD-722b-6.
grep -n "ws.onclose" ui/src/components/profile/SelfImageTab.tsx
  ~187: ws.onclose = () => {
grep -n "ws = new WebSocket" ui/src/components/profile/SelfImageTab.tsx
  ~127: ws = new WebSocket(wsUrl);
find ui/src/__tests__ -name "SelfImageTab*"
  ui/src/__tests__/SelfImageTab.test.tsx
  ui/src/__tests__/SelfImageTab.divergenceHistory.test.tsx
```
