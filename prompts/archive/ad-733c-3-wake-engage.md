# AD-733c-3 — Wake-word → engage

**Status:** Drafted 2026-05-18, awaiting GATE 1.
**Closes (part of):** #675.
**Estimated tests:** +4 pytest, +3 vitest.
**Depends on:** AD-733c-2 (controller + `note_wake_word()`), AD-705 (`startWakeWordLoop`, `routeWakeTranscript`).

## Problem

Today when "Hello Ezri" fires, `wakeWord.ts:onWake` only prepends `@ezri` to the chat input. The perception subsystem doesn't know the operator is now engaged — the supervisor stays at AMBIENT cadence until the DM arrives, by which time the first force-describe may already be running against a stale-baseline frame.

**Solution:** new `POST /api/perception/engage` endpoint flips the controller to `ENGAGED` synchronously. `wakeWord.ts:onWake` fires this BEFORE submitting the chat form when `surface === 'agent'`. Backend cooldown (5s) prevents flap.

## Solution overview

1. **`POST /api/perception/engage`** — body `{agent?: string, phrase?: string, source: "wake_word" | "manual"}`. Calls `controller.note_wake_word()`. Returns the new mode.
2. **Backend cooldown.** The controller's existing `PROGRAMMATIC_COOLDOWN_S = 1.0` is too short for wake-word flap protection. Add per-source cooldown: `_last_wake_word_at` with a 5s floor. If a wake event arrives within 5s of the previous one, return 200 with `cooldown: true` (no transition).
3. **`wakeWord.ts:onWake` hook.** In `IntentSurface.tsx:185-203`, when `routed.surface === 'agent'`, fire-and-forget `POST /api/perception/engage` BEFORE `form.requestSubmit()`. Fire-and-forget = no `await`; failure surfaces as console.warn only.
4. **Avatar surface.** The existing `setActive(true)` + form submit path already brings the agent's chat surface forward. AD-733c-3 does not add a separate avatar API — the chat submit path is the avatar surface for v1. (See WAVE-172-DISPATCH research Q8.)

### Section 1: extend PerceptionModeController with wake-word cooldown

`src/probos/perception/mode_controller.py` — add to the existing class.

SEARCH:
```python
    # Cooldown between programmatic transitions (manual override exempt).
    PROGRAMMATIC_COOLDOWN_S = 1.0
    HISTORY_CAP = 16
```
REPLACE WITH:
```python
    # Cooldown between programmatic transitions (manual override exempt).
    PROGRAMMATIC_COOLDOWN_S = 1.0
    # AD-733c-3: separate floor for wake-word events to prevent UI flap when
    # the detector fires multiple times during the same utterance.
    WAKE_WORD_COOLDOWN_S = 5.0
    HISTORY_CAP = 16
```

SEARCH:
```python
    def __init__(self, runtime: Any, *, initial_mode: Mode = Mode.AMBIENT) -> None:
        self._runtime = runtime
        self._mode: Mode = initial_mode
        self._mode_since: float = time.monotonic()
        self._last_dm_activity_at: float = 0.0
        self._last_transition_at: float = self._mode_since
```
REPLACE WITH:
```python
    def __init__(self, runtime: Any, *, initial_mode: Mode = Mode.AMBIENT) -> None:
        self._runtime = runtime
        self._mode: Mode = initial_mode
        self._mode_since: float = time.monotonic()
        self._last_dm_activity_at: float = 0.0
        self._last_transition_at: float = self._mode_since
        # AD-733c-3: wake-word cooldown tracker. Separate from
        # _last_transition_at so a stream of wake-word events is throttled
        # independently of DM-activity / novelty transitions.
        self._last_wake_word_at: float = 0.0
```

SEARCH:
```python
    def note_wake_word(self) -> None:
        """Hook called by the AD-733c-3 engage endpoint. Forces ENGAGED."""
        if self._mode is not Mode.ENGAGED:
            self.transition_to(Mode.ENGAGED, trigger="wake_word")
        else:
            # Already engaged — refresh activity so idle timer resets.
            self._last_dm_activity_at = time.monotonic()
```
REPLACE WITH:
```python
    def note_wake_word(self) -> tuple[bool, str]:
        """Hook called by the AD-733c-3 engage endpoint. Forces ENGAGED.

        Returns ``(transitioned, reason)`` where ``reason`` is one of
        ``"transitioned"`` / ``"refreshed"`` / ``"cooldown"``. The endpoint
        uses this to populate its response body so the UI can surface
        cooldown rejections to the operator (Captain may want to know why
        a repeated "Hello Ezri" did nothing).
        """
        now = time.time()
        if now - self._last_wake_word_at < self.WAKE_WORD_COOLDOWN_S:
            logger.debug(
                "AD-733c-3: wake-word ignored (cooldown %.2fs remaining)",
                self.WAKE_WORD_COOLDOWN_S - (now - self._last_wake_word_at),
            )
            return (False, "cooldown")
        self._last_wake_word_at = now
        self._last_dm_activity_at = now
        if self._mode is Mode.ENGAGED:
            return (False, "refreshed")
        ok = self.transition_to(Mode.ENGAGED, trigger="wake_word")
        return (ok, "transitioned" if ok else "blocked")
```

### Section 2: `/api/perception/engage` endpoint

Append at the end of `src/probos/routers/perception.py` (after the `/mode` endpoints from AD-733c-2):

```python


class _PerceptionEngageRequest(BaseModel):
    agent: str | None = None        # callsign of the targeted agent (informational)
    phrase: str | None = None       # the matched phrase (informational, for logs)
    source: str = "wake_word"       # "wake_word" | "manual"


@router.post("/engage", dependencies=[Depends(require_crew_scope)])
async def post_perception_engage(
    body: _PerceptionEngageRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-733c-3: flip the mode controller to ENGAGED on a wake-word event.

    Body fields are informational (logged + journalled); the controller only
    needs the side effect. 5s cooldown enforced at the controller level.
    """
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    if body.source not in ("wake_word", "manual"):
        return JSONResponse(
            status_code=400, content={"error": "invalid_source", "value": body.source},
        )
    transitioned, reason = controller.note_wake_word()
    logger.info(
        "AD-733c-3: engage agent=%s phrase=%s source=%s transitioned=%s reason=%s",
        (body.agent or "*")[:32], (body.phrase or "*")[:64], body.source,
        transitioned, reason,
    )
    return {
        "ok": True,
        "mode": controller.current_mode.value,
        "transitioned": transitioned,
        "reason": reason,
    }
```

### Section 3: UI hook in `IntentSurface.tsx`

`ui/src/components/IntentSurface.tsx` — extend the `onWake` callback to fire-and-forget engage.

SEARCH:
```typescript
    const onWake = (routed: { surface: 'system' | 'agent'; agentCallsign?: string; cleanedText: string }): void => {
      if (cancelled) return;
      const text = (routed.cleanedText || '').trim();
      if (!text) return;
      // For agent-routed wakes prepend @callsign so the existing chat path
      // dispatches to that agent (mirrors the manual `@`-mention pattern).
      const finalText =
        routed.surface === 'agent' && routed.agentCallsign
          ? `@${routed.agentCallsign} ${text}`
          : text;
      setActive(true);
      setInput(finalText);
      // Submit on the next tick so React commits the input before the form
      // reads it (mirrors the click-to-talk pattern below).
      setTimeout(() => {
        const form = inputRef.current?.closest('form');
        if (form) form.requestSubmit();
      }, 50);
    };
```
REPLACE WITH:
```typescript
    const onWake = (routed: { surface: 'system' | 'agent'; agentCallsign?: string; cleanedText: string }): void => {
      if (cancelled) return;
      const text = (routed.cleanedText || '').trim();
      if (!text) return;
      // AD-733c-3: fire-and-forget engage. ONLY for agent-surface wakes —
      // a system-surface wake ("computer ...") does not imply engagement
      // with any particular agent's perception. Failure is non-blocking;
      // the chat submit proceeds regardless.
      if (routed.surface === 'agent' && routed.agentCallsign) {
        void fetch('/api/perception/engage', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent: routed.agentCallsign,
            phrase: routed.cleanedText.slice(0, 64),
            source: 'wake_word',
          }),
        }).catch((err) => {
          // eslint-disable-next-line no-console
          console.warn('[AD-733c-3] /api/perception/engage failed', err);
        });
      }
      // For agent-routed wakes prepend @callsign so the existing chat path
      // dispatches to that agent (mirrors the manual `@`-mention pattern).
      const finalText =
        routed.surface === 'agent' && routed.agentCallsign
          ? `@${routed.agentCallsign} ${text}`
          : text;
      setActive(true);
      setInput(finalText);
      // Submit on the next tick so React commits the input before the form
      // reads it (mirrors the click-to-talk pattern below).
      setTimeout(() => {
        const form = inputRef.current?.closest('form');
        if (form) form.requestSubmit();
      }, 50);
    };
```

### Tests

**pytest (+4)** in `tests/test_ad733c3_engage_endpoint.py`:

1. `test_engage_endpoint_flips_to_engaged` — boot a controller in AMBIENT, POST to `/api/perception/engage`, assert 200 + `mode: "engaged"` + `transitioned: True`.
2. `test_engage_endpoint_cooldown_returns_no_transition` — two POSTs within 5s; first transitions, second returns `transitioned: False, reason: "cooldown"`.
3. `test_engage_endpoint_already_engaged_refreshes` — controller already in ENGAGED; POST returns `transitioned: False, reason: "refreshed"`; `last_dm_activity_at` updated.
4. `test_engage_endpoint_invalid_source` — POST `{source: "bogus"}` → 400.

**vitest (+3)** in `ui/src/__tests__/IntentSurface.engage.test.tsx`:

1. Agent-surface wake fires `POST /api/perception/engage` exactly once.
2. System-surface wake (`computer ...`) does NOT fire engage.
3. Engage fetch failure is swallowed (chat submit still proceeds).

### What this does NOT change

- `wakeWord.ts` itself — untouched. The hook is in IntentSurface's `onWake` callback.
- `wakeWord.router.ts` — untouched. The router's `WakeRoute` contract is consumed as-is.
- AD-733c-1 force-describe path — untouched. Engaged mode just means the supervisor will admit more frames before the next DM force-describe lands.
- Avatar API — none added. The existing chat submit path is the avatar surface.

### Tracking

- **PROGRESS.md:** AD-733c-3 entry under Wave 172. Tracker += 7 (4 pytest + 3 vitest).
- **DECISIONS.md:** append AD-733c-3 paragraph.

### Acceptance criteria

- All 4 new pytest pass under `pytest -n 4 --dist=loadfile`.
- All 3 new vitest pass under `cd ui; npx vitest run`.
- `cd ui; npm run build` succeeds (Wave 155 lesson).
- Existing wakeWord tests (~12 across `wakeWord.*.test.ts`) still pass.
- Manual smoke: with mic enabled + ProbOS running, say "Hello Ezri, what am I holding?" → CameraLiveIndicator badge flips ENGAGED → Ezri's reply references the held object (this depends on AD-733c-1 also being shipped).
- Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-18)

```
grep -n "startWakeWordLoop(onWake" ui/src/components/IntentSurface.tsx
  204: void startWakeWordLoop(onWake, { agentTriggers });

grep -n "routed.surface === 'agent'" ui/src/components/IntentSurface.tsx
  192: routed.surface === 'agent' && routed.agentCallsign

grep -n "form.requestSubmit" ui/src/components/IntentSurface.tsx
  200: if (form) form.requestSubmit();

grep -n "require_crew_scope" src/probos/routers/perception.py
  103: @router.post("/camera/frame", dependencies=[Depends(require_crew_scope)])

grep -n "WakeRoute" ui/src/audio/wakeWord.router.ts
  16: export interface WakeRoute {
```

`note_wake_word()` exists at HEAD as a stub introduced in AD-733c-2 — this prompt rewrites it to return `(bool, str)` and adds the cooldown. Build order enforces AD-733c-2 lands before AD-733c-3.
