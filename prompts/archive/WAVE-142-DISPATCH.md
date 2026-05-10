# Wave 142 — Dispatch (Builder-facing)

**Date:** 2026-05-10
**Theme:** Avatar self-image cluster — WebSocket push channel (proprioception)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**ADs in this wave:** AD-722b (#568)
**Mode:** Single-prompt wave, single commit
**Architect approval:** clean (3 review passes documented in §6 below)

---

## 1. Context

Wave 141 shipped AD-722-1 (modulation manifest — single source of truth for TS+Python rule table) and AD-722f (per-agent adaptive sampling state machine — `runtime.avatar_sampling_state` with HIGH 250 ms / NORMAL 2000 ms / LOW 10000 ms tiers wired at DM and chain trigger surfaces). Wave 141 deliberately left **two seams open** for Wave 142:

1. The "popout open" trigger surface in `AvatarSamplingStateMachine`'s docstring (called `enter_subscriber` / `exit_subscriber` as forward markers) — the sampling tier needs a way to know an HXI subscriber is attached.
2. UI continues to poll `GET /api/agent/{id}/avatar-telemetry` every 2 s — at HIGH tier this would be a regression to 4 polls/sec/tab, the opposite of "proprioception."

Wave 142 closes both seams in one AD:

- **AD-722b** — `WS /api/agent/{agent_id}/avatar-telemetry-stream` push channel. Server publishes `AvatarTelemetrySnapshot.to_dict()` JSON frames at the rate dictated by `runtime.avatar_sampling_state.current_rate_ms(agent_id)`. State-changing triggers (DM in/out, chain in/out, reply emitted) wake the publish loop *early* via a per-agent `asyncio.Event`. WS subscribe flips the tier to HIGH via a new `enter_popout(agent_id)` method on the state machine; disconnect flips it back. UI upgrades to WS-first with 5-second open-timeout poll fallback.

Captain ruling 2026-05-10 (Ezri's request, [DECISIONS.md AD-722 addendum (i)](../DECISIONS.md)):

> *"A push model where I receive a signal when something shifts would start to feel more like proprioception than inventory."*

Read-only contract on the snapshot side is preserved (the WS surface is a pure projection of `runtime.avatar_sampling_state` + `build_telemetry_snapshot`).

---

## 2. Build order (one prompt = one commit)

Single build group, single commit:

| # | Prompt | Commit message |
|---|---|---|
| 1 | [`prompts/ad-722b-websocket-push.md`](ad-722b-websocket-push.md) | `AD-722b: WebSocket push channel for avatar telemetry (popout-driven HIGH-tier sampling)` |

---

## 3. Pre-flight checklist (before starting Wave 142)

```pwsh
# 1. Working tree must be clean (or only untracked runtime artifacts).
git status --short
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5
# If any tracked file shows >200 deletions, STOP. Surface to architect.
# DO NOT git stash. DO NOT git reset --hard.

# 2. Establish baselines.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
# Record: pre-Wave-142 Python test count (= Wave 141 baseline = 13112).

cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
# Record: pre-Wave-142 Vitest count (= Wave 141 baseline = ~557 + telemetry-test-fix delta).

cd ui; npm run build 2>&1 | Select-Object -Last 10; cd ..
# Must be clean. UI is the bigger risk surface in this wave.

# 3. Confirm no pending tracked changes from prior session.
git diff --stat
# Should print no output. If anything shows, surface to architect.
```

If the baseline pytest gate is red (tests failing pre-Wave-142), STOP. Surface to architect. Do not begin Wave 142 on a red baseline. Same rule applies to a red `npm run build` baseline — that means the type-check is already broken at HEAD and the Wave 142 changes will mask the cause.

---

## 4. Per-commit workflow

### Commit 1: AD-722b

1. Read [`prompts/ad-722b-websocket-push.md`](ad-722b-websocket-push.md) end-to-end before editing.
2. Apply deliverables in dependency order: D1 (events.py module) → D2 (ws_connection_manager.py module) → D3 (sampling_state.py popout methods) → D4 (config max_connections) → D5 (runtime init) → D6 (trigger-site notifies in routers/agents.py + cognitive_agent.py) → D7 (WS endpoint in routers/agents.py) → D8 (UI WS-first useEffect) → D9 (Python tests) → D10 (Vitest tests) → D11 (telemetry.py docstring marker).
3. Pay special attention to:
   - **D3** — three SEARCH/REPLACE blocks within `sampling_state.py`. Apply in order; each replacement must match exactly.
   - **D6** — adds `_avatar_event_bus = getattr(...)` and `bus.notify(...)` calls **alongside** the existing AD-722f wiring at four sites (DM enter, DM exit, chain enter, chain exit) plus inside `mark_reply_emitted`. The `_sampling_state` and `_avatar_event_bus` locals are bound at the same point so the closure captures both.
   - **D7** — `import asyncio` must be added to the `routers/agents.py` imports if not already present at HEAD. The endpoint is registered on the existing `agents` `APIRouter` via `@router.websocket(...)` — no app-level changes.
   - **D8** — the new `useEffect` body wraps the existing fetch/setInterval inside a WS-first branch. The poll path must remain functional as the fallback. `try/catch` around `new WebSocket(...)` is required so jsdom-test environments without WebSocket stubbed don't break the existing 7 SelfImageTab cases.
4. After all deliverables are applied, run focused gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722_avatar_telemetry.py tests/test_ad722f_adaptive_sampling.py tests/test_ad722b_websocket_push.py -v -n 0
   ```
   Expect: every existing AD-722 / AD-722f case still passes; ≥ 24 new AD-722b cases pass.
5. Run the TS side:
   ```pwsh
   cd ui; npx vitest run; cd ..
   ```
   Expect: existing 7 SelfImageTab cases green + 4 new WS cases green.
6. **Run `cd ui && npm run build` BEFORE pushing** (HARD RULE — TypeScript compilation against production tsconfig is not covered by Vitest alone).
7. Run the full parallel gate:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
   ```
   Expect: Python test count = baseline (13112) + ≥ 24.
8. `git diff --cached --stat` — sanity-check the commit's deletion footprint. Anything that deletes more than ~20 lines in a file you didn't intentionally edit is a red flag (the only intended deletions are the SEARCH-blocks-being-REPLACED in D3/D6/D8).
9. Commit: `git commit -m "AD-722b: WebSocket push channel for avatar telemetry (popout-driven HIGH-tier sampling)"`.

---

## 5. Test gates

| Gate | Command | When |
|---|---|---|
| Full parallel | `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile` | Pre-flight, after commit, post-wave |
| Focused per-prompt | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722*.py -v -n 0` | After commit, before pushing the parallel gate |
| Vitest | `cd ui && npx vitest run` | Pre-flight, after commit |
| TypeScript build | `cd ui && npm run build` | Pre-flight, after commit (HARD RULE) |

**`-n auto` is forbidden** until AD-682 lands. Use `-n 8` (verified ceiling on this codebase).

**Per-commit gate failure interpretation:**
- Failures under the parallel gate that do NOT reproduce under `-n 0` are environmental — document and continue.
- Real failures that reproduce serially in files you changed are blockers. Stop, triage.
- WS endpoint tests (`tests/test_ad722b_websocket_push.py`) are particularly sensitive to event-loop semantics. If a WS test passes serially but flakes under parallel, run it in isolation (`-n 0`) to confirm it's environmental rather than a real concurrency bug introduced in the publish loop.

---

## 6. Architect review status

Three review passes were run against `prompts/review-criteria.md` and `.github/copilot-instructions.md`. Findings:

**Pass 1 (verify-first):**
- ✅ Every API reference, import path, function signature, and line number in the prompt grep-confirmed against HEAD (2026-05-10).
- ✅ License check: zero new Python or JS deps. `mock-socket` (MIT) was considered and rejected — in-tree `MockWebSocket` is simpler. Apache 2.0 boundary preserved.
- ✅ `AvatarSamplingStateMachine.enter_popout` / `exit_popout` are greenfield (verified absent at HEAD); no name collision with the `enter_subscriber` / `exit_subscriber` forward-marker docstring (the docstring is updated by D3).
- ✅ FastAPI 0.115 supports `@router.websocket(...)` on `APIRouter` (feature added in 0.39, codebase has been on ≥ 0.115 since `pyproject.toml:34`).
- ✅ `app.state.runtime` is set at `api.py:161` and is the documented access path for routers — verified.
- ✅ `runtime.emit_event` is a stable public method, but AD-722b does NOT use it for the WS push (we use a dedicated `AvatarEventBus` instead because the existing event bus fans out to all `_ws_clients` and is not per-agent-keyed). Architect rejection of "extend `/ws/events`": the AD-254 broadcast surface is a different concurrency story.
- ✅ Phase-ordering: `runtime.avatar_event_bus` and `runtime.avatar_telemetry_connection_manager` initialize in `runtime.__init__()` adjacent to `self.avatar_sampling_state`, NOT in finalize.py. Avoids the BF-259/260/261/262 trap.
- ✅ Frozen-dataclass field-ordering: AD-722b does NOT add fields to `AvatarTelemetrySnapshot` (pure transport layer). Read-only contract preserved.
- ✅ AD-722 addendum (h) honored: WR (ward_room_notification) is NOT a popout trigger. The new `enter_popout`/`exit_popout` are bound to WS subscribe/unsubscribe only — WR posts do not subscribe to the WS stream.
- ✅ Pre-commit deletion sanity check (200 lines): largest single SEARCH block is the SelfImageTab `useEffect` body (~25 lines). All replacements are well below threshold.

**Pass 2 (revisions):**
- Refined D7 (WS endpoint) to make the cleanup `finally` block defensive — every `register/enter_popout/subscribe` is matched by `deregister/exit_popout/unsubscribe` even on exception paths. Each cleanup line is wrapped in its own `try/except` so a failure in one doesn't prevent the others (cascading-cleanup pattern).
- Added the explicit "feature gates 1 and 2" structure to D7 (avatars disabled vs telemetry disabled) so reviewer can pattern-match against the GET endpoint's two-gate structure (`agents.py:495-505`).
- Refined D8 (UI) to add the 5-second `wsTimeoutId` open-timeout — without it, a WS that NEVER emits `onerror`/`onclose` (e.g., handshake hung) would leave the user without a fallback. Acceptance criterion #9 manual smoke covers this case.
- Added the "publish loop wraps `wait_event` and `wait_timer` in `try/finally` that cancels both pending tasks" explicitly — without that, every iteration would leak one cancelled task per loop turn.
- Made the connection-manager `register` raise rather than return a sentinel so the WS handler's policy-violation path is unambiguous; reviewer fails on any silent over-limit registration.
- Made the test for max-connections (D9 row 22) use `ExitStack` to keep the prior connections open while the over-limit connection attempts to register — this is the only correct test shape; without `ExitStack` the prior connections close at scope-exit before the over-limit attempt.
- Added the "in-tree `MockWebSocket` class" to D10 with explicit lifecycle helpers (`simulateOpen` / `simulateMessage` / `simulateError` / `simulateClose`) so the 4 new vitest cases drive the mock from the outside. No new dep.
- Added the "existing 7 SelfImageTab tests stay green" forcing function — the implementation's WS branch must `try/catch` around `new WebSocket(...)` so jsdom test environments without `WebSocket` stubbed fall back to poll, preserving the existing test bodies.

**Pass 3 (confirmation):**
- ✅ All Pass-2 revisions verified against codebase one more time (`grep` re-run on every changed reference; `app.state.runtime` confirmed via `api.py:161`; `WebSocket` import confirmed available in `fastapi`).
- ✅ Engineering Principles compliance line present in the prompt (§12 row 10).
- ✅ "Out of scope" table explicit; six forward markers (AD-722b-1 through -6) tagged with one-line descriptions; tracking section §11 names them and Captain-files them post-build.
- ✅ No emoji in either prompt or in proposed code.
- ✅ Three-tier exception model honored — every new guard either swallows-with-justification (event_bus.notify failures during `mark_reply_emitted`), logs-and-degrades (publish loop exceptions, cleanup failures), or propagates (config validator rejections, MaxConnectionsExceeded surfacing as a structured WS close).
- ✅ AD-numbering: highest AD at HEAD = **AD-729** (verified via `grep '^### AD-' DECISIONS.md` 2026-05-10). PROGRESS.md L16 cites AD-729 as highest. AD-722b's tracking issue #568 already exists; no new AD numbers are minted by this wave's main prompt. Forward markers AD-722b-1 through -6 are sub-numbers under AD-722b's namespace, not new top-level ADs (no ceiling collision risk).
- ✅ Phantom-API check: every method asserted on `runtime.avatar_sampling_state`, `runtime.avatar_event_bus`, `runtime.avatar_telemetry_connection_manager` is either confirmed at HEAD or being introduced by this AD. The four "introduced by this AD" symbols (`enter_popout`, `exit_popout`, `AvatarEventBus`, `AvatarTelemetryConnectionManager`) are explicitly flagged in §2 with the "DOES NOT EXIST AT HEAD (greenfield)" annotation.
- Pass 3 found nothing new. Prompt is READY FOR BUILDER.

---

## 7. Hard-stop conditions

Surface to architect immediately if any of the following occur:

1. **Tracked-file modifications you didn't make** in `git status` before or during the wave. Do NOT `git stash`. Do NOT `git reset --hard`. (See PROGRESS.md / user memory note about the 2026-05-08 working-tree wipe — this is the canonical trap.)
2. **Phantom API surface** — a method/attribute/import the prompt asserts exists but doesn't (and isn't being added by this AD). Re-grep, then surface.
3. **Architectural change required** — the prompt cannot be built without modifying a base contract (BaseAgent / IntentMessage / AvatarTelemetrySnapshot in ways the prompt doesn't sanction). AD-722b is transport-only; the snapshot dataclass MUST stay unchanged.
4. **Vitest existing 7 SelfImageTab cases break** — the WS branch must `try/catch` around `new WebSocket(...)` so jsdom test environments without WebSocket stubbed fall back to poll. If those tests start failing because the WS constructor throw cascades into a fetch double-count, the implementation has a bug — DO NOT fix the existing tests; fix the implementation.
5. **Existing AD-722 / AD-722f tests fail** — the AD-722f phantom-API guard test (`test_state_machine_does_not_expose_wr_methods`) MUST continue to pass without modification. The AD-722f spurious-exit clamp tests for DM/chain MUST continue to pass; the new spurious-exit-popout test is additive. If any AD-722 / AD-722f case starts failing, the cause is likely a missed propagation in `snapshot_counts` (it now returns `{"dm":0,"chain":0,"popout":0}`) or in `current_tier`.
6. **TypeScript build fails after UI changes** — that means the new branch in `SelfImageTab.tsx` has a type error that the production tsconfig is stricter about than vitest's. Common causes: `WebSocket` global typing, `MessageEvent` shape, `setTimeout` return type drift between Node and browser typings. Fix locally before pushing.
7. **Phantom WebSocket lifecycle** — if a test asserts the WS is in a specific state (open/closed) and the test passes locally but flakes under `-n 8`, the cause is event-loop coupling between TestClient threads. Run `-n 0` to triage. Real concurrency bugs go through architect.

---

## 8. Standing rules (carry forward from `.github/copilot-instructions.md`)

- **AD-numbering hard rule:** if any unforeseen need for a new AD/BF arises during the wave, read DECISIONS.md (current highest is **AD-729** per `grep '^### AD-' DECISIONS.md`), state the highest explicitly in your response, then assign sequentially. Never guess. The six forward markers in this wave (AD-722b-1 through -6) use AD-722b's namespace and do NOT collide with the top-level AD ceiling.
- **Forward markers must have GH issues:** AD-722b's primary tracker is **#568** (already filed; close on commit). The six forward markers are filed by Captain post-build (Builder lacks GH token scope for `seangalliher/ProbOS`). Builder lists the forward-marker text in the build report; Captain runs `gh issue create` after.
- **Pre-commit `git diff --cached --stat` deletion sanity check** — flagged in user memory. Anything that wipes >200 lines you didn't author is a stop-the-line. The largest intended SEARCH/REPLACE in this wave is the SelfImageTab `useEffect` (~25 lines).
- **Three-tier exception handling** — every new guard in the prompt is explicitly tagged: swallow (notify failures inside `mark_reply_emitted`), log-and-degrade (publish loop exceptions, cleanup failures, manifest-load fallbacks), propagate (config validators, `MaxConnectionsExceeded`, malformed config).
- **Cloud-ready storage** — AD-722b adds zero database access. State (event-bus subscribers, connection registry, sampling counts) is in-memory by design — restart resets to empty.
- **HARD RULE — `cd ui && npm run build` AFTER UI code changes BEFORE pushing.** Wave 137's broken TypeScript build cost an extra commit cycle. Do NOT skip this gate.

---

## 9. Post-wave checklist

After the commit lands and gates are green:

```pwsh
git log --oneline -3                 # Confirm AD-722b commit present.
git diff HEAD~1 --stat               # Wave-level diff sanity.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
cd ui; npx vitest run 2>&1 | Select-Object -Last 5; cd ..
cd ui; npm run build 2>&1 | Select-Object -Last 5; cd ..
```

Update `PROGRESS.md`, `docs/development/roadmap.md`, and `DECISIONS.md` per the prompt's tracking table (§11). Close GH issue **#568** with a "shipped in Wave 142 (AD-722b)" comment, citing the commit SHA. Captain files the six forward markers (AD-722b-1 / -2 / -3 / -4 / -5 / -6) as new GH issues after Builder lists the marker text in the build report.

If anything is unclear or any pre-flight gate fails, STOP and surface to architect before proceeding.
