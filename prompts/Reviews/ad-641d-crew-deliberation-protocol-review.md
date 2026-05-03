# Review: AD-641d — Crew Deliberation Protocol (v1)

**Verdict:** ⚠️ Conditional — fixable in one revision pass; closes umbrella when shipped.
**Pass:** 1 of N (Wave 9C, 2026-05-02)
**Tolerance use (convention #15):** consumed (1 of 1 ⚠️ allowed for the wave).

**One-line headline.** v1 isolation honored, cross-wave deps verified, zero Wave 9B structural defects reproduced — but Section 4 is missing the inline import, `DeliberationConfig.default_channel_id` is dead code, `endorse()` is theater, and the DECISIONS.md draft block is descriptive (not inline) per the Wave 8.5 Captain-protocol convention.

---

## Required (must fix before building)

1. **Section 4 — missing inline import.**
   The wiring appends `runtime.deliberation_protocol = DeliberationProtocol(...)` but never imports `DeliberationProtocol`. Every sibling AD-641X wiring in [src/probos/startup/finalize.py](src/probos/startup/finalize.py#L728-L815) uses an inline `from probos.cognitive.X import Y` immediately above the constructor call (verified at lines 730, 754, 768, 786, 810). Add the same:

   ```python
   # AD-641d: Crew Deliberation Protocol
   delib_cfg = getattr(getattr(runtime, "config", None), "deliberation", None)
   if delib_cfg is not None and delib_cfg.enabled:
       from probos.cognitive.deliberation import DeliberationProtocol
       runtime.deliberation_protocol = DeliberationProtocol(
           ward_room=getattr(runtime, "ward_room", None),
           emit_event=runtime.emit_event,
           captain_callsign=delib_cfg.captain_callsign,
       )
       logger.info("AD-641d: DeliberationProtocol wired (captain=%s)", delib_cfg.captain_callsign)
   else:
       runtime.deliberation_protocol = None
   ```

   Also add the `logger.info(...)` line — every sibling wiring logs on success. Without it the wave audit log lacks a per-AD signature.

2. **`DeliberationConfig.default_channel_id` is dead code.**
   Section 3 defines `default_channel_id: str = "deliberation"` but Section 4's constructor call never passes it, the constructor doesn't accept it, and `initiate()` hardcodes `channel_id: str = "deliberation"` instead. Either:
   - **(a)** Add `default_channel_id: str = "deliberation"` to `DeliberationProtocol.__init__`, store it on `self`, and use it as the default in `initiate(channel_id: str | None = None)` (`channel_id = channel_id or self._default_channel_id`); pass it from finalize.py.
   - **(b)** Remove `default_channel_id` from `DeliberationConfig` for v1 and defer the configurable channel to a grandchild AD.

   Either is fine; the prompt must pick one. Defining a config field that never reaches behavior is a SRP/DRY violation and a no-theater (convention #14) violation.

3. **`endorse()` is theater (convention #14).**
   The docstring claims "delegated to existing Ward Room endorsement surface … consumers endorse it via `WardRoomService.endorse()`" but the body just validates that the argument id exists and returns `True`. `agent_id` is unused. No call into `WardRoomService.endorse()` is made. Worse: `submit_argument()` never captures the post_id returned by `create_post`, so even a future caller cannot wire the WardRoom endorsement back to a deliberation argument.

   Pick one:
   - **(a) Defer:** Remove `endorse()` from v1's API surface entirely. Add a fifth wholesale-deferred grandchild — call it **AD-641d-v: Endorsement bridge to WardRoomService.endorse** — and document in "What This Does NOT Change". This brings v1 to 3 real capabilities + 5 deferred grandchildren, perfectly inside the dispatch's "2-3 capabilities, 4-5+ deferred" envelope.
   - **(b) Make it real:** Modify `submit_argument` to capture the `WardRoomPost.id` returned by `await self._ward_room.create_post(...)` and store it on the `DeliberationArgument` (or a parallel dict). `endorse()` then calls `await self._ward_room.endorse(post_id=arg.post_id, agent_id=agent_id)`. Verify [src/probos/ward_room/service.py](src/probos/ward_room/service.py)'s `endorse` signature first via grep before drafting.

   (a) is strongly preferred for v1 — it preserves no-theater discipline; (b) doubles the test surface and risks the Wave 9B "tree-shape / wrong kwarg" pattern resurfacing.

4. **DECISIONS.md inline draft block missing (Wave 8.5 Captain-protocol convention).**
   WAVE-9C-DISPATCH.md verification point #6 and the original Wave 8.5 dispatch require an explicit DECISIONS.md draft block inline in the Tracking section, not just a description. Current Section "Tracking" item 2 only says *"Add an entry: rationale for separation between `QuorumEngine` (mechanical) and `DeliberationProtocol` (judgment); v1 single-Captain resolve; deferred grandchildren."* — that is a TODO, not a draft. Replace with a fenced block, e.g.:

   ```markdown
   ## AD-641d: Crew Deliberation Protocol — Captain-Resolved Judgment Surface

   **Era:** V (HXI Foundation)
   **Date:** 2026-05-02

   **Decision.** Crew deliberation is a separate surface from `QuorumEngine`. `QuorumEngine` is **mechanical** (confidence-weighted vote among tool agents for destructive ops; pass/fail). `DeliberationProtocol` is **judgment-level** (structured argument turns; Captain resolves with `ADOPTED` / `REJECTED` / `DEFERRED`).

   **Arbitration semantics (v1).**
   - Single Captain resolves; identity verified by callsign equality (case-insensitive) — same v1 convention as BF-257 DM rate limiter Captain exemption.
   - `resolve()` is idempotent: a second call after `RESOLVED` returns the existing resolved session unchanged (no overwrite).
   - `outcome=PENDING` is rejected at `resolve()` (returns `None`); only terminal outcomes `ADOPTED`/`REJECTED`/`DEFERRED` close a session.
   - Ward Room thread is the durable record; in-memory `_sessions` map is process-local. Persistence is best-effort (Ward Room calls log-and-degrade on `Exception`).

   **Distinct from existing Captain command paths.** AD-641d does NOT touch `_from_captain` priority routing in [src/probos/cognitive/sub_tasks/](src/probos/cognitive/sub_tasks/) or `captain_engagement.py`. Those are queue/quality concerns; deliberation is a strategic-decision surface invoked explicitly via `DeliberationProtocol.initiate(...)`.

   **Deferred to grandchildren.** AD-641d-i (multi-Captain quorum), AD-641d-ii (Counselor mediation), AD-641d-iii (structured argument schema), AD-641d-iv (Hebbian feedback to deliberation invitations), [add **AD-641d-v** if Required #3(a) is taken].

   **Closes:** AD-641 umbrella (issue #277).
   ```

   The Builder will copy this verbatim into DECISIONS.md under Era V; the Tracking section currently provides nothing to copy.

---

## Recommended (should fix)

1. **`DeliberationPhase.OPEN` and `DeliberationPhase.ENDORSE` are never set.**
   The enum has four values; only `ARGUE` and `RESOLVED` are reachable. `initiate()` jumps straight to `ARGUE`; `ENDORSE` has no transition. Either advance through them (e.g., `OPEN` until first argument; `ENDORSE` after a Captain calls a hypothetical `close_arguments()`) or trim the enum to the two reachable values for v1 and document phase progression as a deferred grandchild capability. Phantom enum values are a minor no-theater concern.

2. **VAC missing per-method-signature grep evidence (Wave 9B retrospective recommendation).**
   Wave 9B's pass-2 retrospective recommended that consumer prompts include a `grep -n "def <method>" <file>` line per consumed method, not just `grep -n "<symbol>"`. Current VAC shows `async def create_thread` exists at line 357 — but does NOT show the full kwarg list. Add:

   ```
   sed -n '357,365p' src/probos/ward_room/service.py
     async def create_thread(
         self, channel_id: str, author_id: str, title: str, body: str,
         author_callsign: str = "", thread_mode: str = "discuss", max_responders: int = 0,
     ) -> WardRoomThread:
   ```

   And the equivalent for `create_post` (line 400). This pre-empts the Wave 9B kwarg-drift defect class proactively rather than reactively.

3. **`participants` field is stored but never read.**
   `DeliberationSession.participants: list[str]` is captured in `initiate()` but no v1 method consults it (no scoping of `submit_argument` to participants only, no notification fan-out). Either document it as "captured for future grandchild ADs (scoping / notifications)" in a comment, or remove from v1. Storing data that no v1 path reads is a SRP/no-theater concern.

4. **`thread.id` access uses `getattr` defensively where it shouldn't.**
   `thread_id = str(getattr(thread, "id", "") or "")` in `initiate()`. `WardRoomThread.id: str` is a declared dataclass field (verified in [src/probos/ward_room/models.py](src/probos/ward_room/models.py)); `getattr(...)` with default suggests uncertainty about the API. Use `thread.id` directly. The defensive guard hides a real failure (a `WardRoomThread` without `id` would be a contract violation worth surfacing, not silently coercing to `""`). Same pattern as Wave 5 anti-pattern catalog ("defensive `getattr(obj, 'method', None)` for APIs defined elsewhere").

---

## Nits (style/minor)

1. **Bare `except Exception: pass` at three sites** (`initiate`, `submit_argument`, `resolve` Ward Room calls; plus three more around `_emit_event`). Per the three-tier exception model in `.github/copilot-instructions.md`, "Log-and-degrade" requires a `logger.warning(...)` line. Replace each with:
   ```python
   except Exception:
       logger.warning("AD-641d: <action> failed; continuing", exc_info=True)
   ```
   Six sites total.

2. **Test list could add `test_runtime_deliberation_protocol_is_none_when_disabled`** — round-trip the `enabled: bool = False` config path through finalize.py. Brings the count to 16, still inside the ~15 estimate.

3. **`DeliberationOutcome.PENDING` is a sentinel.** Document with a comment: `# PENDING is the initial value before resolve(); not a valid resolve() outcome.` Otherwise readers will wonder why `resolve(outcome=PENDING)` returns `None` rather than DEFERRED.

---

## Verified

- **EventType collision-free.** `DELIBERATION_INITIATED`, `DELIBERATION_ARGUMENT_SUBMITTED`, `DELIBERATION_RESOLVED` all absent from [src/probos/events.py](src/probos/events.py). Confirmed against Wave 9A's 5 added types (`OBSERVABILITY_SNAPSHOT_PUBLISHED`, `OBSERVABILITY_BRIDGE_FAILED`, `WARD_ROOM_HEBBIAN_UPDATED`, `WARD_ROOM_HEBBIAN_DECAYED`, `ENGINEERING_SENSOR_REPORT`) and Wave 9B's 3 added types (`LEARNED_SHORTCUT_REGISTERED`, `LEARNED_SHORTCUT_HIT`, `THREAD_PRIORITY_SCORED`). Zero collisions.
- **Cross-wave dep artifacts shipped.**
  - AD-641a `runtime.observability_bridge` — wired in [src/probos/startup/finalize.py](src/probos/startup/finalize.py#L731). ✓
  - AD-641b `runtime.ward_room_hebbian_router` — wired in [src/probos/startup/finalize.py](src/probos/startup/finalize.py#L754). ✓
  - AD-641c `runtime.thread_priority_service` — wired in [src/probos/startup/finalize.py](src/probos/startup/finalize.py#L814). ✓
  - **AD-641d makes ZERO direct calls into any of them.** v1 isolation is honored exactly as the dispatch dictated. (Hebbian feedback is wholesale-deferred to AD-641d-iv.)
- **Wave 9B structural-defect pattern: 0 reproductions.**
  - Async/sync mismatch: `runtime.emit_event` is sync (`def emit_event(self, event, data=None) -> None` at [src/probos/runtime.py:802](src/probos/runtime.py#L802)); prompt calls it sync. `create_thread`/`create_post` are async; prompt awaits both. ✓
  - Wrong kwargs: prompt's `create_thread(channel_id=, author_id=, title=, body=, author_callsign=, thread_mode=)` matches live signature exactly. `create_post(thread_id=, author_id=, body=, author_callsign=)` matches live signature. ✓
  - Wrong row shape: N/A — no `event_log.query*` usage. ✓
  - Tree-vs-flat: N/A — no `ward_room.get_thread` usage. ✓
  - Missing field assumption: N/A — no department/author resolution. ✓
  - Cross-wave artifact attribute drift: N/A — no `runtime.X.Y` access. ✓
- **WardRoomService method signatures match.**
  - `create_thread` at [src/probos/ward_room/service.py:357](src/probos/ward_room/service.py#L357) — kwargs match.
  - `create_post` at [src/probos/ward_room/service.py:400](src/probos/ward_room/service.py#L400) — kwargs match.
- **No conflict with existing Captain command paths.** Captain-flagged paths (`_from_captain` in [src/probos/cognitive/sub_tasks/evaluate.py](src/probos/cognitive/sub_tasks/evaluate.py#L438), [src/probos/cognitive/captain_engagement.py](src/probos/cognitive/captain_engagement.py)) are queue-priority and quality-gate concerns; AD-641d's `resolve()` is an explicit RPC-shaped surface invoked by code calling `DeliberationProtocol.resolve(...)`. No semantic overlap. Hard-stop #5 not triggered.
- **Frozen-dataclass field ordering correct.** `DeliberationSession`'s defaulted fields (`ended_at`, `thread_id`, `outcome`, `rationale`, `arguments`) come after non-defaulted; same for `DeliberationArgument`. ✓
- **`requires_consensus` not applicable.** `DeliberationProtocol` is not a tool agent; mutations are Captain-gated by callsign check at `resolve()`. Different consensus model — judgment vs mechanical — explicitly per the prompt's design. ✓
- **Captain identity check uses lowercased canonical callsign** — matches BF-257 pattern (DM rate limiter Captain exemption). v1 acceptable; AD-499 ShipNamingPolicy canonical. ✓
- **Pre-deferral aggressive.** 4 grandchildren wholesale-deferred (`AD-641d-i` through `AD-641d-iv`); v1 capabilities are 3 (lifecycle, captain-only resolve with outcome enum, Ward Room persistence) **once Required #3 is applied** (which trims `endorse()` from v1). At 3 capabilities + 5 deferred (counting AD-641d-v from Required #3a), the dispatch's "2-3 capabilities, 4-5+ deferred" envelope is hit cleanly. As currently drafted (4 + 4), it's at the upper threshold and the `endorse()` capability is theater. Fixing Required #3 resolves both concerns.

---

## Wave 9 Cross-Wave Pattern Status

| Wave | Pass-1 verdicts | Wave 9A defect classes reproduced | Notes |
|---|---|---|---|
| 9A | 1 ✅ / 0 ⚠️ / 2 ❌ | n/a (origin wave) | First exposure to async/sync, kwarg, row-shape defects |
| 9B | 1 ✅ / 0 ⚠️ / 1 ❌ | All 3 reproduced in 641c original; caught | Reactive review pipeline worked; proactive drafting did not |
| 9C | 0 ✅ / 1 ⚠️ / 0 ❌ | **0 reproduced** | Single prompt; HIGH-risk; isolation discipline held |

**Cross-wave lesson update.** The Wave 9B retrospective recommended that consumer prompts include per-method-signature grep evidence in VAC (not just symbol existence). AD-641d's VAC does NOT yet adopt that recommendation (Recommended #2). However, the structural defect classes did NOT reproduce — likely because AD-641d is mostly self-contained (one new module + one config + one wiring block), with the only consumed live API surface being `WardRoomService.create_thread` / `create_post`, which the author appears to have verified by reading. **The proactive drafting pipeline still has not been hardened by tooling**; the next time a prompt consumes `event_log.query*` or `ward_room.get_thread` shapes, the Wave 9B defect classes are likely to recur unless Recommended #2 becomes a hard procedural rule (or the phantom-API pre-check is extended per the Wave 9B retro recommendation).

## Hard-Stop Disposition

| # | Condition | Triggered? |
|---|---|---|
| 1 | Phantom API not introduced by the prompt itself | No |
| 2 | Cross-wave dep claim mismatches shipped code | No (zero direct calls; isolation honored) |
| 3 | Section 0 EventType collision | No |
| 4 | v1 absorbs >4 capabilities | Borderline — currently 4 (`lifecycle`, `resolve+outcome`, `endorse`, `persistence`); fixing Required #3 reduces to 3. Not over the wall. |
| 5 | Conflicts with existing Captain command paths | No |

**No hard-stops.** Required findings #1-#4 are mechanical fixes for the revision pass. Verdict: ⚠️ Conditional → expected to converge to ✅ at pass-2 after revision applies Required + folds Recommended.
