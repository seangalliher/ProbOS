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

---

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved
**Pass:** 2 of N (Wave 9C, 2026-05-02)
**Tolerance use (convention #15):** none consumed in pass-2 (1/1 was already consumed in pass-1; not refundable, but no new ⚠️ needed).

**One-line headline.** All 4 Required findings resolved verbatim, all 4 Recommended folded in, all 3 Nits applied; pre-check 0 phantoms; v1 isolation preserved (0 cross-wave artifact calls). Ready to ship.

---

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R1 (Section 4 inline import) | ✅ Resolved | Section 4 wiring block (line ~432) now contains `from probos.cognitive.deliberation import DeliberationProtocol` immediately above the constructor call, plus `logger.info("AD-641d: DeliberationProtocol wired (captain=%s)", ...)` on success — matches sibling pattern (finalize.py lines 730/753/767/789/810). |
| R2 (`default_channel_id` dead code) | ✅ Resolved | `DeliberationConfig` (Section 3) now has only `enabled` and `captain_callsign`. Channel default lives in `initiate(channel_id: str = "deliberation")`. Explanatory note in Section 3 documents the deferral path. `grep "default_channel_id" prompts/ad-641d-*.md` returns only revision-notes/explanation hits — zero in production-code sections. |
| R3 (endorse theater → AD-641d-v defer) | ✅ Resolved | All 7 surfaces verified — see detailed audit below. |
| R4 (DECISIONS.md inline draft) | ✅ Resolved | Tracking item #2 contains a fenced ` ```markdown ` block with `## AD-641d: Crew Deliberation Protocol — Captain-Resolved Judgment Surface` heading and full **Decision / Arbitration semantics (v1) / Distinct from existing Captain command paths / Deferred to grandchildren / Closes** sections. All 5 grandchildren listed (i through v). Builder copies verbatim. |

**R3 detailed surface audit (the largest cascading change):**

| R3 surface | Status | Evidence |
|---|---|---|
| (a) Section 2 `endorse` method body removed | ✅ | `DeliberationProtocol` class body in Section 2 has no `async def endorse`. The only `endorse` mention in Section 2 region is the docstring pointer to AD-641d-v. |
| (b) Class docstring updated | ✅ | Public API list reads `initiate / submit_argument / resolve / get_session`; trailing paragraph: "Endorsement is deferred to AD-641d-v (bridges deliberation arguments to `WardRoomService.endorse(target_id=, target_type=, voter_id=, direction=)`)." |
| (c) Solution Overview reads "3 of 8 capabilities ship" | ✅ | Line 28: `**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 8 capabilities ship):**`. Old "4 of 7" / "4 of 8" gone (only revision-notes echoes them as historical). |
| (d) v1-deliverables bullets do NOT mention endorse | ✅ | Lifecycle bullet reads `initiate/submit_argument/resolve` — no `endorse`. |
| (e) Deferred grandchildren add AD-641d-v with forcing function | ✅ | Solution Overview lists 5 wholesale-deferred items; AD-641d-v entry includes the forcing function: *"Requires capturing the `WardRoomPost.id` returned from `create_post` and calling `await self._ward_room.endorse(target_id=post_id, target_type='post', voter_id=agent_id, direction='up')` (verified signature at service.py:412)."* |
| (f) Test 15 updated | ✅ | Old endorse test removed; test 15 is now `test_runtime_deliberation_protocol_is_none_when_disabled` (per Nit #2). Test count stays at 15. |
| (g) Scope boundaries §8 reflects defer | ✅ | "What This Does NOT Change" §8 reads: "Endorsement bridge to `WardRoomService.endorse` — wholesale-deferred to AD-641d-v. v1 ships no `endorse(...)` method on `DeliberationProtocol`..." |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| Rec1 (`DeliberationPhase.OPEN/ENDORSE` unreachable) | ✅ Applied | Enum trimmed to `ARGUE` and `RESOLVED` only. Comment documents the deferral. `grep "DeliberationPhase\.OPEN\|DeliberationPhase\.ENDORSE"` returns 0 hits in production code. |
| Rec2 (VAC per-method-signature grep evidence) | ✅ Applied | VAC enriched with `sed -n` blocks for `create_thread` (357-363), `create_post` (400-406), `endorse` (412-415, included to verify the AD-641d-v deferral target). Added `grep -n "def emit_event"` confirming sync signature, and `grep -n "AD-641a..."` showing inline-import sibling pattern. Wave 9B retro recommendation now adopted in this prompt. |
| Rec3 (`participants` field unread) | ✅ Applied | Inline comment on the dataclass field documents it as captured for future grandchild ADs (scoping/notifications). v1 boundary explicit. |
| Rec4 (defensive `getattr(thread, "id", "")`) | ✅ Applied | Replaced with direct `thread.id` access. The exception arm around `create_thread` already handles the failure case correctly (now with `logger.warning` per Nit #1). |

| Pass-1 Nit | Status | Notes |
|---|---|---|
| Nit1 (six bare `except Exception: pass`) | ✅ Applied | All six sites now use `logger.warning("AD-641d: <action> failed; ...", exc_info=True)`. Verified by reading Section 2: initiate (create_thread + emit_event), submit_argument (create_post + emit_event), resolve (create_post + emit_event). |
| Nit2 (add disabled-config wiring test) | ✅ Applied | Test 15 added (replaces the dropped endorse test); count stays at 15. |
| Nit3 (`DeliberationOutcome.PENDING` sentinel comment) | ✅ Applied | Inline comment in the enum explicitly says "PENDING is the initial sentinel value before resolve(); it is NOT a valid resolve() outcome. resolve(outcome=PENDING) returns None." |

---

### Verification Run Output

```
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-641d-crew-deliberation-protocol.md
=== prompts/ad-641d-crew-deliberation-protocol.md ===
  Clean — no phantom symbols detected.
=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0

$ Select-String -Pattern "observability_bridge|ward_room_hebbian_router|thread_priority_service|learned_shortcut|engineering_sensor"
0
```

**v1 isolation preserved.** Zero direct calls into Wave 9A/9B runtime artifacts. The endorse defer did NOT introduce any new dependency.

---

### New Findings (introduced during revision)

**None.** No new Required-class issues. No new phantom APIs. No new structural defects. No regression of v1 isolation. The revision was surgical and converged cleanly.

---

### Hard-Stop Disposition (pass-2)

| # | Hard-stop condition | Triggered? |
|---|---|---|
| 1 | Required finding missed in revision | No (all 4 resolved) |
| 2 | New Required-class issue introduced | No |
| 3 | Cross-wave artifact dep slipped into v1 | No (0 references) |
| 4 | DECISIONS.md draft is placeholder content | No (substantive arbitration semantics, all 5 grandchildren listed, umbrella closure declared) |

**No hard-stops.** Verdict: ✅ Approved. Builder may execute as a single commit.

---

### Builder Dispatch Recommendation

**Single commit.** AD-641d only.

Suggested commit message: `AD-641d: Crew Deliberation Protocol (Captain-resolved judgment surface)`

Post-commit actions:
1. Update PROGRESS.md with AD-641d CLOSED entry (5 deferred grandchildren).
2. Append DECISIONS.md entry verbatim from the prompt's Tracking section #2 fenced block.
3. Update docs/development/roadmap.md line 7056.
4. **Close GitHub issue #277 (AD-641 umbrella)** — this is the final sub-AD of the four (641a/b/c/d shipped; 641e/f remain in scope of the umbrella per WAVE-9C-DISPATCH but were dispatched in Wave 9A/9B).

---

### Wave 9 Cross-Wave Pattern Status (final)

| Wave | Pass-1 verdicts | Pass-2 verdicts | Total findings closed | Wave 9B defect classes reproduced |
|---|---|---|---|---|
| 9A | 1 ✅ / 0 ⚠️ / 2 ❌ | 3 ✅ | All | n/a (origin wave) |
| 9B | 1 ✅ / 0 ⚠️ / 1 ❌ | 2 ✅ | All | All 3 caught reactively |
| 9C | 0 ✅ / 1 ⚠️ / 0 ❌ | 1 ✅ | All | **0** (proactive isolation discipline held) |

**Wave 9 outcome.** Single-prompt high-risk Captain-protocol wave converged in two passes. Tolerance budget consumed (1 ⚠️) but pass-2 was clean. AD-641 umbrella closes on Builder commit.

---

### Verdict Summary

✅ **Approved for Builder dispatch.** Required-still-open: 0. New findings: 0. Pre-check: 0 phantoms. v1 isolation: preserved. Single commit. AD-641 umbrella ready to close on landing.
