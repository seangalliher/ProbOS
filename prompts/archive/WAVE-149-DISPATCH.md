# Wave 149 Dispatch — Complete the AD-722b WebSocket Push Loop

**Date filed:** 2026-05-11
**Issues closed:** #599 (AD-722b-2), #603 (AD-722b-6)

## One-line summary

Two-prompt sweep that closes the AD-722b WebSocket push channel: backend writes the broadcast snapshot to the agent's own `_last_self_avatar_snap` cache (kills the stale-between-DMs window), and the UI gains capped exponential-backoff reconnect so a transient drop doesn't permanently demote the connection to poll fallback.

## Prompts (build in order)

1. `prompts/ad-722b-2-agent-side-consumer.md` — backend, ~2 LOC of side-effect + tests.
2. `prompts/ad-722b-6-reconnect-backoff.md` — frontend, reconnect state machine inside the existing `useEffect` in `SelfImageTab.tsx` + Vitest.

Both prompts ship in the same wave commit. Independently buildable.

## Pre-flight gate

1. `git status` clean; HEAD at `e066c0b` (Wave 148) or later.
2. `pytest tests/test_ad722b_websocket_push.py -q -n 0` — green baseline.
3. `cd ui && npx vitest run src/__tests__/SelfImageTab.test.tsx` — green baseline.

## Hard-stop conditions

1. Option 1 for AD-722b-2 turns out architecturally impossible (e.g. agent reference not in scope where prompt says it is) — surface to Architect with grep evidence. **Do NOT fall back to Option 2** (self-WS per agent) unilaterally.
2. AD-722b-6 reconnect logic would require restructuring the existing `useEffect` into a hook/module (out of scope for this wave).

## Anti-patterns to avoid (wave-specific)

- Putting the cache-write inside `build_telemetry_snapshot` (couples a pure data builder to agent state mutation; also makes the HTTP GET endpoint mutate agent state — idempotent-read regression).
- Infinite reconnect retries (DOS vector against ourselves; cap at 10 attempts).
- Removing the existing poll fallback (it is the safety net; reconnect supplements it).

## Commit message format

```
AD-722b-2 + AD-722b-6 (Wave 149): close the WebSocket push loop

Closes #599. WS handler writes each snapshot to agent._last_self_avatar_snap so
agent's INTEROCEPTION stays fresh between DMs without re-polling.
Closes #603. Client reconnects with capped exponential backoff (1s, 2s, 4s, 8s,
16s, 30s cap, 10 attempts max).
```

## Tracking

- `PROGRESS.md` — close #599, #603, update test count.
- `docs/development/roadmap.md` — mark AD-722b-2 and AD-722b-6 shipped.
- `prompts/wave-plan.yaml` — Wave 149 entry status `shipped`.
- GH #599, #603 closed with commit reference.

## Acceptance criteria

- AD-722b-2: stale `_last_self_avatar_snap` becomes fresh within one WS publish interval without an `observe_self_avatar()` call.
- AD-722b-2: HTTP GET `/avatar-telemetry` endpoint behavior unchanged (idempotent read; does NOT mutate `_last_self_avatar_snap`).
- AD-722b-6: simulated WS close triggers reconnect at 1s, 2s, 4s, 8s, 16s, 30s, 30s (capped).
- AD-722b-6: after 10 failed attempts, no further reconnects; component stays on poll fallback.
- AD-722b-6: successful reconnect resets attempt counter.
- All changes comply with Engineering Principles in `.github/copilot-instructions.md`.
