# Review: AD-722b-4 — Fleet-level avatar telemetry stream
**Verdict:** ⚠️ Conditional
**Server endpoint is correctly shaped, but the HXI hook URL omits the router prefix and several test scaffolds reference paths that won't resolve.**

## Required (must fix before building)

1. **Hook URL is missing the `/api/agent` router prefix.**
   `src/probos/routers/agents.py:30`:
   ```python
   router = APIRouter(prefix="/api/agent", tags=["agents"])
   ```
   The full fleet endpoint path is `/api/agent/avatar-telemetry/stream`, NOT `/api/avatar-telemetry/stream`. The TS hook in Section 3 derives the URL as:
   ```typescript
   return `${proto}//${window.location.host}/api/avatar-telemetry/stream`;
   ```
   This will 404. **Change to `/api/agent/avatar-telemetry/stream`** in `deriveFleetUrl()`. The per-agent endpoint in the existing HXI similarly mounts under `/api/agent/{id}/avatar-telemetry-stream` — confirm the convention by reading any existing per-agent hook (e.g., `ui/src/avatars/useAvatarTelemetry.ts` if it exists; if not, the test for the per-agent endpoint is enough to verify the prefix).

2. **pytest tests in Section 4 must use the prefixed URL.**
   `test_fleet_stream_disabled_closes_1008`, `test_no_crew_closes_1008`, `test_initial_snapshot_per_agent`, etc. all call `TestClient.websocket_connect(...)`. The URL passed MUST be `/api/agent/avatar-telemetry/stream`. The prompt doesn't specify the URL in the test descriptions but Builder will copy the path from Section 2. Add an explicit reminder to Section 4: **"All pytest WS connections use `/api/agent/avatar-telemetry/stream` (router prefix `/api/agent` applies)."**

3. **Routing precedence claim in the dispatch's wave-specific reminders is true but the prompt's anchor comment is misleading.**
   The dispatch says "Reviewer should NOT flag insertion order as a routing bug." Confirmed — `/{agent_id}/avatar-telemetry-stream` (literal suffix) cannot match `/avatar-telemetry/stream` (different literal token). Section 2's Builder verification step 6 says "FastAPI uses declaration order for non-prefix paths; verify by inserting at line ~937." That phrasing implies declaration order matters HERE; it doesn't (the literals diverge). Replace step 6 with: "Insertion order does NOT affect routing for this pair (literal suffix `avatar-telemetry-stream` vs literal segment `avatar-telemetry`/`stream`). Insert at line ~937 for code-layout proximity to the existing per-agent handler."

## Recommended

1. **`asyncio.create_task` ref-store discipline.** `publish_tasks: list[asyncio.Task] = []` and `receive_task: asyncio.Task | None = None` are stored — good, matches AD-722-era pattern. But Section 2's `_publish_one` creates `wait_event = asyncio.create_task(event.wait())` and `wait_timer = asyncio.create_task(asyncio.sleep(interval_s))` WITHOUT storing references in a set. Per `.github/copilot-instructions.md` standing rule: "Always hold a reference to tasks created with `asyncio.create_task()`. Fire-and-forget tasks silently swallow exceptions and can be garbage collected." The current pattern works because `await asyncio.wait({wait_event, wait_timer}, ...)` holds them on the stack, but a Pylance / ruff strict pass will flag the pattern. Acceptable as-is (this is the pattern used in the per-agent handler too); just acknowledge in a comment line.

2. **Disconnect cleanup is missing `event_bus.unsubscribe` arg validation.** The `finally:` block iterates `for agent_id in events:` and calls `event_bus.unsubscribe(agent_id, events[agent_id])`. If `event_bus.subscribe(agent_id)` failed mid-loop (Tier-2 fall-through earlier?), `events[agent_id]` is the wrong type for `unsubscribe`. Wrap the unsubscribe in `try/except` more narrowly (per-agent already wrapped — confirmed good).

3. **`build_telemetry_snapshot` returns `agent._last_self_avatar_snap` shape.** Section 2 stores `agent._last_self_avatar_snap = initial` and `agent._last_self_avatar_snap = snap` inside the publish loop — this is a cross-handler write to a per-agent attribute that other code paths (`apply_divergence_check`) also read. If the per-agent endpoint is ALSO connected for the same agent (Captain views agent twice), the two endpoints race on the same `_last_self_avatar_snap` attr. Per-agent endpoint cap is 4, but the FLEET endpoint adds an extra writer. **Document in Section 2 that this race exists, is benign (last-write-wins, no torn read because Python attr writes are atomic), and matches the existing per-agent endpoint's behavior.**

4. **Vitest test asserts `MockWebSocket` behavior** — the hook's effect cleanup function calls `ws.close()`; the test must verify cleanup runs on unmount. Add a third Vitest test: `closes WebSocket on unmount` — covers the `useEffect` cleanup path.

5. **Diff frames in `_publish_one` lose the `agent_id` field when `diff` is `None` after the compute_diff fallback.** The fallback sends `{"type": "snapshot", "agent_id": agent_id, **snap_dict}` — correct. When `diff` is truthy: `{"type": "diff", "agent_id": agent_id, "changed": diff}` — correct. When `diff` is falsy (no changes): NO frame is sent (silent skip). This matches AD-722b-3 semantics; acknowledge in a comment line so reviewers don't flag the "silent skip" as a bug.

## Nits

1. Forward marker AD-722b-4a trigger "4+ avatar tiles open simultaneously AND profiling shows per-agent hook setup cost dominates initial paint" — measurable; good. AD-722b-4-1 "crew spawn/despawn during a fleet-stream lifetime is observed in production AND the disconnect-reconnect cost is measurable" — measurable. Both pass the technical-trigger rule.
2. `from probos.avatars.telemetry import build_telemetry_snapshot` is imported inside the handler body (lazy) — matches existing per-agent endpoint pattern. OK.
3. `crew_agents.append((agent.agent_id, agent))` — tuple of (id, agent) — discovery is a snapshot; documented in the comment. OK.

## Verified

- Per-agent WS handler at line 669-920 (approx); fleet endpoint inserted at line ~937 has correct path-divergence vs per-agent literal. ✅
- AD-722b-3 diff config fields (`ws_diff_enabled`, `ws_full_snapshot_every_n`, `ws_diff_threshold`) live in `AvatarTelemetryConfig` and are referenced consistently in `_publish_one`. ✅
- Starlette `WebSocket.close(code: int, reason: str)` kwargs match the signatures used throughout Section 2. ✅
- `is_crew_agent` imported at module level (line 1005 confirms in-scope). ✅
- UI gate inclusion: verification commands run BOTH `vitest run` AND `npm run build` (AD-738b / BF-279 compliance). ✅
- No emoji in `useFleetAvatarTelemetry.ts` (pure logic file, no JSX). ✅
- No new pip / npm deps. Apache 2.0 internal.
- Frame shape `{type, agent_id, ...payload}` is backward-compatible with AD-722b-3 snapshot-diff format at the per-agent endpoint (which omits `agent_id`). ✅

## Build-go criteria

Required findings 1, 2, 3 fixed → re-review for URL prefix correctness once. After re-review, LOW-MED risk holds.


### Re-review (pass-2) — 2026-05-14

**Verdict:** ✅ Approved.

All 3 Required findings from pass-1 are resolved:

1. **Hook URL prefix** — deriveFleetUrl() at `prompts/ad-722b-4-multi-agent-telemetry-stream.md:387` now returns:
   `\\\	ypescript
   return `///api/agent/avatar-telemetry/stream`;
   \\\`
   Full path resolves correctly under the outers/agents.py:30 `APIRouter(prefix="/api/agent")` mount. Solution Overview (line 13) and Files-to-modify anchors (line 42) re-quote the full resolved path. The acceptance section line 498 explicitly calls out *"NOT /api/avatar-telemetry/stream"* as a defensive reminder.
2. **pytest WS test URL** — Section 4 (line 395) leads with the bold reminder: *"All TestClient.websocket_connect(...) calls use the URL /api/agent/avatar-telemetry/stream — the gents router prefix /api/agent applies."*
3. **Routing precedence wording** — Section 2 Builder verification step 6 (line 314) rewritten: *"Insertion order does NOT affect routing for this pair. The literal segments /avatar-telemetry/stream (fleet endpoint, no path parameter) and /{agent_id}/avatar-telemetry-stream (per-agent endpoint, one path parameter with a literal suffix) cannot collide... Insert at line ~937 for code-layout proximity; insertion order is purely cosmetic."*

No new Required findings. Recommended #1-5 (task-ref discipline comment, unsubscribe narrow try/except, _last_self_avatar_snap race documentation, Vitest unmount-close test, silent-skip diff comment) and Nits remain Builder-discretion.

UI gate (AD-738b / BF-279) compliance preserved: verification commands run BOTH 
px vitest run AND 
pm run build. ✅

**Risk classification:** LOW-MED (unchanged from pass-1 build-go criteria).
