# AD-1270 (#1324): Night Orders escalation, wired: the hook never costs an event its dispatch, a match pages the Captain through the real bridge-alert path, and only triggers with a producer are mapped

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-27

**Status:** build-ready on `a2390998` (the AD-1341 S6 candidate). The orchestrator re-anchors on S6's merge. No new AD or BF number: this is the Night Orders checklist item on #1324 (comment 6230904043, from the BF-897 review F1). **Captain:** no condition met (D8). Overrulable: D2 (`red_alert`/`security_alert` are reported as inert rather than given producers) and D3 (trust pages on the crossing, not while below the floor).

**Re-anchored and reformatted by the orchestrator (2026-10-27).** (1) **Base:** `origin/main` `71ff4785834902c5985ae57344761d23a42245d7`, the merge of AD-1341 S6 (PR #1689). Its tree, `628f874a7b04a5e34878d84f6479e98b314a6cc1`, is the tree the Architect drafted on (`a2390998`), so every SEARCH below applies unchanged. (2) **Pair format:** the Architect wrote each pair as `Pair N:` with bare `SEARCH` and `REPLACE` lines inside one fence, and the 7.6 and section 8 pairs with no label at all; the apply tool reads `SEARCH:` and `REPLACE:` labels with a fence each, so the orchestrator converted all 14 pairs by tool (a round trip proved every body byte for byte; the 7.6 and section 8 labels now name their file). (3) **DECISIONS.md pair (section 8):** moved from the top of the Era V section to after AD-1341 S6's entry, where the file's recent entries are appended in date order; it also carries the just-culture entry the Captain asked to have recorded (#1569 comment 1; follow-up #1690, entry (d)), text by the Architect's 2026-10-27 consult. (4) **M3 also regenerates the AD ledger:** `python scripts/gen_ad_ledger.py`, then stage the two files it rewrites (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`); without it `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` fail (measured on the orchestrator's oracle: 3 failures, then 33 passed). (5) **Dates:** every `2026-10-2X` in section 8 becomes the date of M3's commit.

**Amendment A1 (`claude-architect`, 2026-10-27, after the orchestrator's census of `427546b8`: 24 killed, 2 survived).** (1) **R-7 closed:** D2 now drives a second crossing of the same agent inside the 300 s cooldown. It asserts that the hook reached the service (the conn manager was called twice) and that no delivery was scheduled. It also asserts that the update that stays below the floor matched nothing. D2's body changes; the case count does not. (2) **R-9 recorded as equivalent:** an inactive manager's `check_escalation` is already False. Its §10 row names no test. (3) **§10 made census-ready:** every Killed-by cell names full function names, with `[id]` for a single case. W-2 and B-1 name their measured killers (T3b, D7) plus D2, which A1's assertions are predicted to make a second killer of both. (4) **§6 corrected:** the triggers file holds 32 cases. M2's file fails on 10 of 11 cases on its base: D3 passes there, as a negative case, and mutation R-2 kills it. (5) **Not changed:** §7.1 to §7.4 and §8. Rerun after A1: the baseline, then W-2, B-1, R-4, R-7, R-8.

**Amendment A2 (`claude-architect`, 2026-10-27, after round 1 of the cross-family review of `894526c6`: reviewer A READY, reviewer B NOT READY).** Every repair is in the new §7.8. §7.1 to §7.7 and §8 stay as the record of the original build. (1) **B1** (P2, ordinary, regression): when the TTL has already run out (`/night-orders maintenance -1`), the console's template branch indexed `inert_triggers` on a status that is exactly `{"active": False}`. It raised `KeyError` after printing "Night Orders set". It now reads the field only from an active status. (2) **B2** (P2, ordinary): the hook's docstring and the PROGRESS paragraph said the event "reaches its durable row". So did this contract's §7.6 docstring and §8 PROGRESS text, which §7.8 supersedes. The durable router routes neither `build_failure` nor `trust_update`. What is true: a hook failure no longer stops the durable offer, the NATS publish or the local dispatch. (3) **B3** (P2, injected-only): T2 also rejects a literal `emit_event*` call naming any of the four old event names. DECISIONS and D2 now say what T2 does not catch: a producer behind a renamed emitter (register R11). *(A5: reverted. The split restores round 1's T2, whose emission check names only `security_alert`, so B3 is open again, R11 (a).)* (4) **B4** (P3, injected-only): `_is_score` no longer converts an int to float, so a finite integer too large for a float counts as a score instead of raising `OverflowError`. (5) **B5** (P3, injected-only): T3b gains two cases with a valid old score and an invalid new one. (6) **Review A F1** (P2, injected-only): a raising `ConnManager.check_escalation` is now logged on its own and the page still goes. D4's `[conn]` case pinned the lost page; it becomes D4b, which asserts delivery. **Recorded, not repaired:** review A F2 and F3 (register R9, R10) and B3's alias forms (R11). **Corrected:** register R4 (not every bridge-alert delivery is fire-and-forget) and R8 (mutation R-9 is equivalent for paging and status, not for logging). **Found while verifying, outside this diff:** R12, a console TTL defect that predates AD-1270 (a BF is recommended). **Shared contract:** unchanged (no signature, persisted shape, config, event or wire shape; an inactive `get_status()` is still exactly `{"active": False}`), so round 2 reviews the delta. Predicted: triggers 38 cases, delivery 11, §10 30 rows.

**Amendment A3 (`claude-architect`, 2026-10-27, after round 2 of the cross-family review of `5f4b57ed`: reviewer A READY, reviewer B NOT READY).** *(A5: not built in this slice. A3 was built in `698950a9` and the split reverts it; this paragraph and §7.9 are slice 1b's drafted text, R13.)* Every repair is in the new §7.9. §7.1 to §7.8 stay as the record. (1) **B r2 F2** (P3, injected-only, a regression A2 introduced; repaired): A2's T2 regex matched raw text. A comment showing an `emit_event` call, or a call emitting a longer name such as `red_alert_resolved`, failed the gate with no producer present. (2) **B r2 F1** (P2, injected-only, not a regression; repaired): the regex needed the quoted name right after the parenthesis, so `event_type=`, `event=`, `name=` and a space before the parenthesis passed. (3) **One change repairs both:** T2's two text scans become `_old_producer_calls`, a module-level AST helper in the test file. It is tested on 27 fixture sources: 11 it must flag, 10 it must not, 5 forms it does not resolve (R11) and 1 that does not parse (it raises). The `.set_alert_condition(` regex moves into the same helper, because it had F1's spacing miss and F2's comment match. The `EventType` check stays: it checks enum values, which no comment reaches. (4) **DECISIONS** now says what the helper does and names R11. PROGRESS never described T2 and is unchanged. (5) **Premise corrected:** the four `_emit_event(name, ...)` helpers forward to `runtime.emit_event` in production (`startup/finalize.py:2560`, `:2596-2598`; `security/pairing/service.py:61`, `:78`), so the `name` keyword is covered. **Recorded:** R11, extended to every form the helper does not resolve. **Shared contract:** yes, at the source-scan gate: T2 now rejects producers it missed and accepts text it wrongly rejected. No product signature, persisted shape, config, event or wire shape changes. Predicted: triggers 65 cases, delivery 11, §10 47 rows.

**Amendment A4 (`claude-architect`, 2026-10-27, the round-three brake decision after round 3 of the cross-family review of `698950a9`: reviewer B NOT READY on G1 to G5; the orchestrator added this paragraph from the Architect's decision record).** *(A5: not built in this slice. A4 was built in `6cc1a1a3` and the split reverts it; its premise that `tokenize.open` fails only where the importer fails is false (round 4 F1). This paragraph and §7.10 are slice 1b's drafted text, R13.)* **Decision: continue, narrowed.** Round 4 is one reviewer (B) over Amendment A4, a test-only repair of T2; every repair is in the new §7.10. (1) **G1** (P3, injected-only, a regression A3 introduced): T2 reads only the first positional argument. Every `emit_event*` method in `src/probos` except `_emit_event_local` takes the event first, the forwarders' keywords are payload, and no call binds the event by keyword (enumerated). The keyword forms move to R11 (g), injected-only. (2) **G2** (same class): files are decoded with `tokenize.open` (a BOM and a PEP 263 coding line), behind a new `_scan_tree` with a file-based test. (3) **G3**: the prefilter's effect is described as conditional, in the helper docstring, the DECISIONS sentence and R11 (d), with a fixture for each side. (4) **G4** is recorded as R11 (h), with a fixture. (5) **G5**: bare-setter and suffixed-callee fixtures added, and T2's reading is now tested; T2's one assertion line has no mutation row (R11). **Why not split:** the G1 defect sits in a line A4 deletes, the helper now flags a subset of what A3 flagged (so A4 cannot add a false rejection), and a split would discard 46 killed census rows for the same review round. Round 4 records injected-only recall and coverage gaps rather than repairing them; a false claim is repaired by deleting the claim. **If round 4 finds a regression caused by A4, no round 5 is run: the split to round 1's T2 (`82eac026`) is taken.** Predicted: triggers file 72 cases, delivery 11, census baseline 667, §10 at 51 rows.

**Amendment A5 (`claude-architect`, 2026-10-27, after round 4 of the cross-family review of `6cc1a1a3`: reviewer B NOT READY; the split pre-committed in A4 is taken, and A4 gets no repair round).** (1) **F1** (P3, injected-only, a regression A4 introduced): `tokenize.open` rejects a valid CR-only module whose third line is an unknown coding cookie, which the importer, round 1's read and A3's read all accept (`tokenize.detect_encoding` splits lines on `\n` only; the importer's tokenizer ignores a cookie after line 2). Two Latin-1 modules with a non-ASCII byte in a first-line comment, which the importer accepts, fail every read so far. They are not regressions, but they falsify A4's premise that `tokenize.open` fails only where the importer fails, and with it the encoding claims of §14 items 21 and 22, the helper docstring, the DECISIONS sentence and R11. The orchestrator reproduced all three with the standard library (the probe and its output are session evidence, not in the repository). (2) **F2** (P3, injected-only, not a regression; recorded): positional unpacking, `rt.emit_event(*("red_alert", {}))`, passes the helper and round 1's T2 alike (R11 c). (3) **The split (shape B, §7.11):** T2 returns to round 1's form (`82eac026`). The triggers file is `5f4b57ed`'s with pair A2-1 reversed, so `_old_producer_calls`, `_scan_tree`, `_OLD_EVENT_NAMES` and A3's and A4's tests leave it, and A2's other additions (B1, B4, B5) stay. The DECISIONS sentence says only what round 1's T2 does. (4) **What leaves the slice:** T2's recall becomes slice 1b (register R13): B3, round 2's F1, round 3's G1 to G5, round 4's F1 and F2, and the encoding counterexamples. Its drafted text is §7.9, §7.10, the H rows of §10 and §14 items 16 to 23, none of it built here. The A3 and A4 commits stay in the branch history. (5) **Not changed:** product source, the delivery file, PROGRESS, and the text of §7.1 to §7.10 (A5 adds notes only). **Shared contract:** T2, as a source-scan gate, returns to the form round 1 reviewed. Predicted: triggers 38 cases, delivery 11, focused union 1,017 (as at repair 1); §10's census is the 30 non-H rows, with `5f4b57ed`'s baseline. The reduced candidate gets the one review round the brake allows a split, over §14 items 24 and 25.

**A5.1 (the split's one review round: `gpt-6.1-sol`, reviewer B, over `56811270`, NOT READY solely for one false statement; the orchestrator applied the Architect's rule that a false statement is deleted, and recorded it here).** (1) **F1** (P3, injected-only, not a regression: the statement predates the split): T2's docstring said "If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS." That is false. T2 matches text, so a comment-only module with no call in it, or a valid non-UTF-8 module with no producer, also fails it (R11). The orchestrator's saved probe shows both. The docstring is deleted from the test and from §7.11's quotation of T2. Section 7.3's and §7.9's copies stay as the record of what M1 and A3 contained, and slice 1b must not carry the sentence (R13). (2) **Recorded, no change:** the three other literal names that `5f4b57ed`'s widened regex caught and the restored T2 does not (P2, injected-only; a regression against `5f4b57ed`, none against `82eac026`) are the accepted reopening of B3, R11 (a) and R13. (3) **Properties 24 to 29 held,** with 24 and 25 read as amended by the deletion: T2 is round 1's with its docstring deleted, and the triggers file equals `5f4b57ed`'s except for the reverse of pair A2-1 and that deletion. No further review round runs on this candidate.

**Milestones and tiers:**
- **M1, the trigger truth** (`watch_rotation.py`, the console command, tests). **STANDARD**: Captain-facing Night Orders behaviour and status.
- **M2, delivery and isolation** (`runtime.py` hook, `bridge_alerts.py`, tests). **HIGH**: `ProbOSRuntime._emit_event` is the shared event-emission contract (AD-1195 durable offer, NATS, listeners).
- **M3, trackers.**

Each milestone is one Builder delegation and one local commit, built in order and staged by explicit path, never `git add -A`. M2 gets a cross-family review (`gpt-6.1-sol`). The broad gate is the orchestrator's single canonical run after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-night-orders --receipt logs/gates/ad1270-night-orders.receipt.json`. One mutation campaign runs on the assembled tree (§10).

**Tests:**
- New: `tests/test_ad1270_night_orders_triggers.py` (M1), `tests/test_ad1270_night_orders_delivery.py` (M2).
- Updated, with an inline reason: `tests/test_autonomous_operations.py` (M1). Two tests re-implemented the old inline rule on a `new_trust` field no producer sends, so they pinned the defect.
- No test touches a live system or a real data directory.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| `_emit_event` calls the hook first, unguarded, before durable offer and dispatch | present | `runtime.py:1946-1957` |
| The hook calls `self.bridge_alerts.add_alert(...)`, which does not exist | present | `runtime.py:2179-2185`; Absence AV1 |
| Its map keys `trust_change`, `alert_condition_change`, `build_failure`, `security_alert`, and the trust rule reads `new_trust` | present | `runtime.py:2150-2167` |
| Only `build_failure` has producers | present | `routers/build.py:85,366,410,482,489`; Absence AV2 |
| The trust producer emits `trust_update` with `old_score`, `new_score` | present | `consensus/trust.py:492-499`, `:534-541`, `:659-678` |
| Nothing changes the alert condition; AD-455's monitor reports nothing in v1 | present | `ontology/service.py:105`; `security/trust_integrity.py:64-75`; Absence AV3 |
| Night Orders is built in production when the proactive loop is on | present | `startup/finalize.py:4211-4216`; `runtime.py:3594` |
| The bridge-alert pattern: `BridgeAlertService.check_*` builds, deduplicates (`_should_emit`, AD-580 suppression) and records; the caller delivers via `WardRoomRouter.deliver_bridge_alert` | present | `bridge_alerts.py:92-113`, `:310-347`; `runtime.py:4790-4796`; `ward_room_router.py:1181-1227` |
| The service docstring names `_deliver_bridge_alert()`, which the runtime no longer has | present | `bridge_alerts.py:50-51`; Absence AV1 |
| Per-event tasks are held in `_event_listener_tasks` (BF-639), not `_background_tasks` | present | `runtime.py:1435-1438`, `:1984-1989`, `:3901-3904` |
| Borrowed-method hosts (BF-708) bind the hook with partial collaborators | present | `tests/test_bf897_build_pipeline_scale_and_checkout.py:898-919`; `tests/test_ad1195_durable_event_seam.py:66-82` |
| BF-897's tests pin "an unmarked build_failure still escalates (conn called)" and "a refusal does not" | present | `tests/test_bf897_build_pipeline_scale_and_checkout.py:929-966` |
| `BridgeAlertService` is frozen srp-size debt (no magnitudes stored) | present | `docs/development/architecture-baseline.yaml:331-339` |

## 1. Problem

When Night Orders list `build_failure` (the `maintenance` template, `watch_rotation.py:187`) and a real build fails, `_check_night_order_escalation` raises `AttributeError`. The exception comes out of `_emit_event` before the durable offer, the NATS publish and the local dispatch, so the HXI, the durable log and the stream all lose the event, and the Captain is not paged.

The other three triggers can never fire: their event names are never emitted. `trust_drop` is mapped from `trust_change`, but the producer emits `trust_update`.

## 2. Solution overview

- **M1:** the trigger rule moves beside the templates as `watch_rotation.night_order_trigger(event_type, details, *, trust_floor)`. It maps `build_failure` → `build_failure` (keeping BF-897's `not_executed is True` skip) and `trust_update` → `trust_drop`, raised once as the score crosses below the conn floor. `red_alert` and `security_alert` stay valid names but are unmapped. `get_status()` gains `inert_triggers`, `set_night_orders` logs a warning for them, and `/night-orders` prints them.
- **M2:** the hook becomes log-and-degrade. `BridgeAlertService.check_night_orders_escalation` builds the alert (ALERT severity, deduplicated per trigger and subject, suppressible by the Captain under AD-580). The hook delivers it with `WardRoomRouter.deliver_bridge_alert` on a task held in `_event_listener_tasks`.

## 3. Decisions

- **D1. The rule lives in `watch_rotation.py`**, the owner of the trigger vocabulary. It takes `trust_floor` as an argument, so `watch_rotation` imports nothing from `config`. The runtime passes `TRUST_FLOOR_CONN`, which it already imports (`runtime.py:111`).
- **D2. Inert, not invented.** Giving `red_alert` or `security_alert` a producer would be new capability, which is paused. The templates keep both names, because they become live the day a producer lands. Status, the console and a log line say they never fire. A guard test (T2) fails if an `EventType` value is one of the four old names, or if the text of a `*.py` file under the `probos` package directory matches `\.set_alert_condition\(` or `emit_event\w*\(\s*["']security_alert`. It matches text, not calls; its misses and false matches are register R11. *(A5: round 1's T2, restored by the split after round 4. A2's widening and A3's and A4's parser are reverted; the parser is slice 1b, R13.)*
- **D3. Trust pages on the crossing** (`old >= floor > new`). An update that stays below the floor never pages again. The bridge-alert cooldown (300 s) applies per agent on top.
- **D4. Build in the service, deliver from the caller**, as all ten-plus other alert kinds do. The cost is one cohesive method on frozen srp debt; the baseline row is unchanged (R3).
- **D5. Fetch the loop before the alert is built.** Outside a running loop the alert is never built, so it never uses up its cooldown. (A2: if scheduling fails after the alert is built, the cooldown is still spent; register R9.)
- **D6. Keep `getattr` for collaborators.** BF-708 borrowed-method hosts lack them, which is the same reason `_emit_event` reads `durable_events` that way (`runtime.py:1951-1955`).
- **D7. The hook stays where it is in `_emit_event`.** AD-471's ordering intent (escalate even if dispatch fails) holds; only its failure is contained.
- **D8. Captain conditions:** none. Nothing destructive. No control is weakened: the hook used to raise and kill the event, and now it logs. There is no schema, route or config change, no spending, and no change across the OSS boundary.

## 4. Milestones

Write each milestone's new test file first and run it on the milestone's base: M1's must fail at collection, and M2's must fail on every case except D3, a negative case that passes on the old hook too (§6). If a test outside §7 fails, stop and report it; never delete or loosen a test. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** trigger truth | STANDARD | 7.1 `src/probos/watch_rotation.py`; 7.2 `src/probos/experience/commands/commands_autonomous.py`; 7.3 new `tests/test_ad1270_night_orders_triggers.py`; 7.4 `tests/test_autonomous_operations.py` | `tests/test_ad1270_night_orders_triggers.py tests/test_autonomous_operations.py tests/test_commands_autonomous.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_ad1251_watch_orders_removed.py tests/test_workforce.py` |
| **M2** delivery and isolation | HIGH | 7.5 `src/probos/bridge_alerts.py`; 7.6 `src/probos/runtime.py`; 7.7 new `tests/test_ad1270_night_orders_delivery.py` | `tests/test_ad1270_night_orders_delivery.py tests/test_ad1270_night_orders_triggers.py tests/test_bridge_alerts.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_ad1195_durable_event_seam.py tests/test_ad637d_system_events_nats.py tests/test_ad680_public_runtime_api.py tests/test_bf708_capability_notice.py tests/test_ad1274_report_off_loop.py tests/test_autonomous_operations.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` |
| **M3** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `night_order_trigger`, `NIGHT_ORDER_TRIGGER_EVENTS`, `WIRED_NIGHT_ORDER_TRIGGERS` | `runtime._check_night_order_escalation` (M2), tests | new |
| `get_status()["inert_triggers"]` | `cmd_night_orders`; `GET` in `routers/system.py:429-431` (JSON, additive); no HXI reader (Grep `escalation_triggers\|night.orders` in `ui/src`: none) | additive key |
| `check_night_orders_escalation` | the hook only | new |
| `_check_night_order_escalation` behaviour | `_emit_event` (every producer); BF-708 hosts in `test_bf897_*`, `test_ad1195_*`, `test_ad637d_*` (own copy), `test_ad680_*` (stubbed) | never raises; same signature |
| `trust_update` now matched | trust producer `consensus/trust.py:661,678` → the hook | pages on a crossing under Night Orders |

## 6. Tests

On each milestone's base, the new file fails as follows (measured by the orchestrator, 2026-10-27):
- M1: collection fails, so every case fails: `ImportError: cannot import name 'NIGHT_ORDER_TRIGGER_EVENTS' from 'probos.watch_rotation'` (1 error during collection).
- M2 (on the M1 stage): 10 of the 11 cases fail. D4 ×3 and D7 ×2 raise `AttributeError` (no `check_night_orders_escalation`). D1, D5 and D6 `[router]` raise `AttributeError: 'BridgeAlertService' object has no attribute 'add_alert'`. D6 `[bridge_alerts]` finds no gap logged. D2 fails because the old map keys `trust_change`, so a `trust_update` matches nothing (after A1, its first failing assertion is `call_count == 1`, which sees 0). **D3 passes on the base**, as a negative case must: the old hook also declines a refused build and a trigger the order does not list. It still bites: on the assembled tree, mutation R-2 (the `mgr.check_escalation` test dropped) fails it.

| ID | File | Case | Proves |
|---|---|---|---|
| T1 | triggers | `test_every_mapped_event_has_a_production_producer` | the map names producers (source premise) |
| T2 | triggers | `test_the_inert_triggers_still_have_no_producer` | guard: fails when a producer lands in a form its three checks see (A5: round 1's text scan, restored; its limits are R11) |
| T2c | *(A5: not in this slice; slice 1b's drafted cases, R13)* | `test_old_producer_calls_flags_a_literal_producer` ×11; `test_old_producer_calls_ignores_what_is_not_a_producer` ×10; `test_old_producer_calls_does_not_resolve_these_forms` ×5; `test_a_source_the_guard_cannot_parse_fails_it` | A3 (review B r2 F1, F2): the helper flags positional, keyword (`event`, `event_type`, `name`), spaced, split and nested literal calls and `set_alert_condition` calls. It ignores comments, docstrings, longer names, other callees, a second positional and other keywords. It pins the forms it does not resolve (R11) and raises on a source it cannot parse |
| T2b | triggers | `test_every_template_trigger_is_wired_or_known_inert` | template vocabulary |
| T3 | triggers | `test_build_failure_raises_unless_the_request_ran_nothing` ×6 | BF-897 parity |
| T3b | triggers | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor` ×14 | crossing, bounds, bool/inf/NaN/str/None; A2: an invalid new score beside a valid old one (`[new-bool]`, `[new-neg-inf]`), a finite integer too large for a float (`[huge-int]`) |
| T3c | triggers | `test_events_the_old_map_keyed_raise_nothing` ×4 | the old keys are gone |
| T4 | triggers | `test_status_names_the_triggers_that_can_never_fire` ×3; `test_a_custom_trigger_with_no_producer_is_reported_and_logged`; `test_wired_triggers_report_nothing_inert_and_log_nothing`; `test_inactive_status_is_unchanged` | disclosure |
| T5 | triggers | `test_the_console_says_which_triggers_never_fire`; `test_a_fully_wired_order_prints_no_inert_line`; `test_a_template_order_that_is_already_expired_does_not_break_the_console` ×3 (A2, B1) | operator surface |
| D1 | delivery | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched` | **the crossing test:** real emit → real Night Orders → real service → real router → Ward Room thread and an `action_required` notification, with the listener and durable offer intact |
| D2 | delivery | `test_a_trust_crossing_pages_once` | the trust chain end to end. An update that stays below the floor matches nothing (D3). A second crossing inside the 300 s cooldown reaches the service, which declines it, so no delivery is scheduled and no second thread is created (R-7, R6) |
| D3 | delivery | `test_a_refused_build_or_an_unlisted_trigger_pages_nobody` | negative chain |
| D4 | delivery | `test_an_escalation_that_raises_never_costs_the_event_its_dispatch` ×2 (A2: `[conn]` moved to D4b) | isolation |
| D4b | delivery | `test_a_conn_log_that_raises_still_pages_the_captain` | A2 (review A F1): a raising `ConnManager.check_escalation` is logged under its own message and the Captain is still paged |
| D5 | delivery | `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent` | D5 |
| D6 | delivery | `test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged` ×2 | partial hosts |
| D7 | delivery | `test_the_alert_is_deduplicated_per_subject_and_suppressible`; `test_a_trust_drop_alert_names_the_agent_and_its_scores` | service contract |

Expected new cases: triggers 32, delivery 11 (measured on the orchestrator's oracle `427546b8`; the table above sums to 32). Measured there before A1: M1's focused list 333 passed, M2's 736 passed, and the §10 census baseline over its seven files 627 passed. A1 changes D2's body, not the number of cases, so the expected counts stay delivery 11, M2 736 and census 627. The orchestrator re-measures. **A2 (predicted):** triggers 38 (T3b +3, T5 +3), delivery 11 (D4 −1, D4b +1); M1's list 339, M2's 742, the census baseline 633. Over the candidate's source with the A2 tests applied, five cases fail: `[huge-int]` (`OverflowError`) and the three expired-template cases (`KeyError: 'inert_triggers'`) in the triggers file, and D4b (`create_thread` awaited 0 times). **A3 (predicted):** triggers 65 (T2c +27), delivery 11; M1's list 366, M2's 769, the census baseline 660. No production source changes, so no case fails over the candidate's source. The discriminating run is §7.9's A2-predicate oracle, with 10 disagreements. **A5 (the split):** the triggers file returns to A2's 38 cases, with T2 in round 1's form; delivery 11; the focused union 1,017, as measured at repair 1. The census baseline is `5f4b57ed`'s, re-measured on the restored tree (expected 633, A2's prediction).

## 7. The contract

### 7.1 `src/probos/watch_rotation.py` (M1)

**Pair 1.** SEARCH:
```
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
```
REPLACE:
```
import asyncio
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any
```

**Pair 2.** SEARCH:
```
        "alert_boundary": "green",  # Don't even change to Yellow
    },
}


@dataclass
class NightOrders:
```
REPLACE:
```
        "alert_boundary": "green",  # Don't even change to Yellow
    },
}

# AD-1270 (#1324): emitted event type -> the Night Orders trigger it raises.
# Every key has a production producer: ``build_failure`` (``routers/build.py``)
# and ``trust_update`` (``consensus/trust.py``, which carries ``old_score`` and
# ``new_score``). The AD-471 map keyed ``trust_change``, ``alert_condition_change``
# and ``security_alert``, which nothing emits, and read a ``new_trust`` field
# nothing sends. ``red_alert`` and ``security_alert`` stay valid trigger names
# but have no producer on this build (nothing calls
# ``OntologyService.set_alert_condition``; nothing emits ``security_alert``),
# so status reports them as inert instead of promising a page that never comes.
NIGHT_ORDER_TRIGGER_EVENTS: Mapping[str, str] = MappingProxyType({
    "build_failure": "build_failure",
    "trust_update": "trust_drop",
})
WIRED_NIGHT_ORDER_TRIGGERS: frozenset[str] = frozenset(NIGHT_ORDER_TRIGGER_EVENTS.values())


def night_order_trigger(
    event_type: str,
    details: Mapping[str, Any] | None,
    *,
    trust_floor: float,
) -> str | None:
    """The Night Orders trigger an emitted event raises, or ``None`` (AD-471, AD-1270 #1324).

    ``build_failure`` raises ``build_failure`` unless the request ran nothing
    (BF-897's ``not_executed`` marker, exactly ``True``). ``trust_update`` raises
    ``trust_drop`` once, as the score crosses below ``trust_floor``
    (``old >= floor > new``); an update that stays below the floor, or that
    carries no finite numeric scores, raises nothing.
    """
    trigger = NIGHT_ORDER_TRIGGER_EVENTS.get(event_type)
    if trigger is None:
        return None
    data = details or {}
    if trigger == "build_failure" and data.get("not_executed") is True:
        return None  # BF-897: a refused request ran nothing, so there is no failure to escalate
    if trigger == "trust_drop":
        old, new = data.get("old_score"), data.get("new_score")
        if not (_is_score(old) and _is_score(new)):
            return None
        if not (old >= trust_floor > new):  # once, as the score crosses below the floor
            return None
    return trigger


def _is_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class NightOrders:
```

**Pair 3.** SEARCH:
```
        logger.info(
            "Night Orders set (template=%s, ttl=%.1fh, triggers=%s)",
            template or "custom", ttl_hours, escalation_triggers or [],
        )
        return self._orders
```
REPLACE:
```
        logger.info(
            "Night Orders set (template=%s, ttl=%.1fh, triggers=%s)",
            template or "custom", ttl_hours, escalation_triggers or [],
        )
        inert = sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS)
        if inert:
            logger.warning(
                "AD-1270: Night Orders triggers %s have no producer on this build and will never page the Captain",
                inert,
            )
        return self._orders
```

**Pair 4.** SEARCH:
```
            "escalation_triggers": self._orders.escalation_triggers,
        }
```
REPLACE:
```
            "escalation_triggers": self._orders.escalation_triggers,
            "inert_triggers": sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS),
        }
```

### 7.2 `src/probos/experience/commands/commands_autonomous.py` (M1)

**Pair 1.** SEARCH:
```
            console.print(f"  Alert boundary: {status['alert_boundary']}")
```
REPLACE:
```
            console.print(f"  Alert boundary: {status['alert_boundary']}")
            triggers = status["escalation_triggers"]
            console.print(f"  Escalates on: {', '.join(triggers) if triggers else 'nothing'}")
            if status["inert_triggers"]:
                console.print(f"  [yellow]Never fires on this build: {', '.join(status['inert_triggers'])}[/yellow]")
```

**Pair 2.** SEARCH:
```
        console.print(f"  TTL: {ttl}h")
```
REPLACE:
```
        console.print(f"  TTL: {ttl}h")
        inert = rt._night_orders_mgr.get_status()["inert_triggers"]
        if inert:
            console.print(f"  [yellow]Never fires on this build: {', '.join(inert)}[/yellow]")
```

### 7.3 New file: `tests/test_ad1270_night_orders_triggers.py` (M1)

```python
"""AD-1270 (#1324): Night Orders triggers name only events something emits (M1).

The trigger rule (``watch_rotation.night_order_trigger``), the inert-trigger
disclosure in Night Orders status, and the console's report of it.
"""
from __future__ import annotations

import logging
import math
import re
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import probos
from probos.config import TRUST_FLOOR_CONN
from probos.events import EventType
from probos.experience.commands import commands_autonomous
from probos.runtime import ProbOSRuntime
from probos.watch_rotation import (
    NIGHT_ORDER_TEMPLATES,
    NIGHT_ORDER_TRIGGER_EVENTS,
    WIRED_NIGHT_ORDER_TRIGGERS,
    NightOrdersManager,
    night_order_trigger,
)

_SRC = Path(probos.__file__).resolve().parent
_F = TRUST_FLOOR_CONN
_INERT = {"red_alert", "security_alert"}
_LOGGER = "probos.watch_rotation"


def _trigger(event_type: str, details: dict[str, Any] | None) -> str | None:
    return night_order_trigger(event_type, details, trust_floor=_F)


def _source(*parts: str) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# --- T1, T2: the map names producers, and only producers ---------------------


def test_every_mapped_event_has_a_production_producer() -> None:
    assert set(NIGHT_ORDER_TRIGGER_EVENTS) == {"build_failure", "trust_update"}
    assert EventType("build_failure") is EventType.BUILD_FAILURE
    assert EventType("trust_update") is EventType.TRUST_UPDATE
    assert "emit_event(EventType.BUILD_FAILURE, {" in _source("routers", "build.py")
    trust = _source("consensus", "trust.py")
    assert 'emissions.append(("trust_update", {' in trust
    assert '"new_score": new_score,' in trust


def test_the_inert_triggers_still_have_no_producer() -> None:
    """If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS."""
    values = {m.value for m in EventType}
    assert values.isdisjoint({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    assert [p for p, t in texts.items() if re.search(r"\.set_alert_condition\(", t)] == []
    assert [p for p, t in texts.items() if re.search(r"""emit_event\w*\(\s*["']security_alert""", t)] == []


def test_every_template_trigger_is_wired_or_known_inert() -> None:
    names = {t for tpl in NIGHT_ORDER_TEMPLATES.values() for t in tpl["escalation_triggers"]}
    assert WIRED_NIGHT_ORDER_TRIGGERS == {"build_failure", "trust_drop"}
    assert names - WIRED_NIGHT_ORDER_TRIGGERS == _INERT


# --- T3: the rule --------------------------------------------------------------


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (None, "build_failure"),
        ({}, "build_failure"),
        ({"not_executed": True}, None),
        ({"not_executed": False}, "build_failure"),
        ({"not_executed": "true"}, "build_failure"),
        ({"not_executed": 1}, "build_failure"),
    ],
    ids=["none", "absent", "refused", "false", "string-true", "int-one"],
)
def test_build_failure_raises_unless_the_request_ran_nothing(details: Any, expected: str | None) -> None:
    assert _trigger("build_failure", details) == expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (_F + 0.1, _F - 0.1, "trust_drop"),
        (_F, _F - 0.01, "trust_drop"),
        (_F - 0.01, _F - 0.1, None),
        (_F + 0.1, _F, None),
        (_F - 0.1, _F + 0.1, None),
        (_F - 0.1, _F - 0.1, None),
        (math.inf, _F - 0.1, None),
        (_F + 0.1, math.nan, None),
        (True, False, None),
        ("0.7", "0.5", None),
        (None, _F - 0.1, None),
    ],
    ids=["crosses", "from-floor", "already-below", "lands-on-floor", "rises", "floor-hit",
         "inf", "nan", "bool", "str", "missing"],
)
def test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor(old: Any, new: Any, expected: str | None) -> None:
    assert _trigger("trust_update", {"agent_id": "a1", "old_score": old, "new_score": new}) == expected


@pytest.mark.parametrize("event_type", ["trust_change", "alert_condition_change", "security_alert", "bridge_alert"])
def test_events_the_old_map_keyed_raise_nothing(event_type: str) -> None:
    assert _trigger(event_type, {"new_trust": 0.0, "new_level": "red", "old_score": 0.9, "new_score": 0.1}) is None


# --- T4: status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "inert"),
    [("maintenance", ["security_alert"]), ("build", ["security_alert"]), ("quiet", ["red_alert", "security_alert"])],
)
def test_status_names_the_triggers_that_can_never_fire(template: str, inert: list[str]) -> None:
    mgr = NightOrdersManager()
    mgr.set_night_orders(instructions=[], template=template)
    assert mgr.get_status()["inert_triggers"] == inert


def test_a_custom_trigger_with_no_producer_is_reported_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop", "typo"])
    status = mgr.get_status()
    assert status["escalation_triggers"] == ["build_failure", "trust_drop", "typo"]
    assert status["inert_triggers"] == ["typo"]
    assert any("never page the Captain" in r.getMessage() and "typo" in r.getMessage() for r in caplog.records)


def test_wired_triggers_report_nothing_inert_and_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop"])
    assert mgr.get_status()["inert_triggers"] == []
    assert not [r for r in caplog.records if "never page the Captain" in r.getMessage()]


def test_inactive_status_is_unchanged() -> None:
    assert NightOrdersManager().get_status() == {"active": False}


# --- T5: the console ---------------------------------------------------------------


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=False, width=200)


def _out(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _runtime() -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt.conn_manager = None
    rt._night_orders_mgr = NightOrdersManager()
    return rt


@pytest.mark.asyncio
async def test_the_console_says_which_triggers_never_fire() -> None:
    rt = _runtime()
    set_console = _console()
    await commands_autonomous.cmd_night_orders(rt, set_console, "quiet")
    assert "Never fires on this build: red_alert, security_alert" in _out(set_console)
    status_console = _console()
    await commands_autonomous.cmd_night_orders(rt, status_console, "status")
    text = _out(status_console)
    assert "Escalates on: red_alert, security_alert" in text
    assert "Never fires on this build: red_alert, security_alert" in text


@pytest.mark.asyncio
async def test_a_fully_wired_order_prints_no_inert_line() -> None:
    rt = _runtime()
    rt._night_orders_mgr.set_night_orders([], escalation_triggers=["build_failure"])
    console = _console()
    await commands_autonomous.cmd_night_orders(rt, console, "status")
    text = _out(console)
    assert "Escalates on: build_failure" in text
    assert "Never fires" not in text
```

### 7.4 `tests/test_autonomous_operations.py` (M1)

**Pair 1.** SEARCH:
```
from probos.watch_rotation import (
    NightOrders,
    NightOrdersManager,
    WatchManager,
    WatchType,
    NIGHT_ORDER_TEMPLATES,
)
```
REPLACE:
```
from probos.config import TRUST_FLOOR_CONN
from probos.watch_rotation import (
    NightOrders,
    NightOrdersManager,
    WatchManager,
    WatchType,
    NIGHT_ORDER_TEMPLATES,
    night_order_trigger,
)
```

**Pair 2.** SEARCH:
```
    def test_night_orders_escalation_trust_drop(self):
        """Set Night Orders with trust_drop escalation. Verify bridge alert on low trust."""
        rt = MagicMock(spec=ProbOSRuntime)
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )
        rt._night_orders_mgr = night_mgr
        rt.conn_manager = ConnManager()

        # Mock bridge alerts
        rt.bridge_alerts = MagicMock(spec=BridgeAlertService)

        # Simulate the escalation check
        # Test the escalation logic directly on the manager
        assert night_mgr.check_escalation("trust_drop") is True

    def test_night_orders_escalation_ignored_above_floor(self):
        """Trust above floor (0.8) does not escalate."""
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )

        # Simulate the runtime check logic inline
        details = {"new_trust": 0.8}
        trigger = "trust_drop"

        # The runtime's _check_night_order_escalation would return early
        # because new_trust >= 0.6. Let's verify the logic:
        new_trust = details.get("new_trust", 1.0)
        should_skip = new_trust >= 0.6
        assert should_skip is True  # Would not reach check_escalation
```
REPLACE:
```
    def test_night_orders_escalation_trust_drop(self):
        """A trust_update that crosses below the conn floor raises trust_drop under Night Orders."""
        # AD-1270 (#1324): this test checked only check_escalation and named a
        # bridge alert it never exercised; it now calls the production rule with
        # the producer's own fields (consensus/trust.py). The chain is
        # tests/test_ad1270_night_orders_delivery.py.
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(instructions=[], escalation_triggers=["trust_drop"])
        trigger = night_order_trigger(
            "trust_update", {"old_score": 0.7, "new_score": 0.5}, trust_floor=TRUST_FLOOR_CONN,
        )
        assert trigger == "trust_drop"
        assert night_mgr.check_escalation(trigger) is True

    def test_night_orders_escalation_ignored_above_floor(self):
        """A trust_update that stays above the conn floor raises nothing."""
        # AD-1270 (#1324): this test re-implemented the old inline rule on a
        # ``new_trust`` field no producer sends, so it pinned the defect; it now
        # calls the production rule.
        assert night_order_trigger(
            "trust_update", {"old_score": 0.9, "new_score": 0.8}, trust_floor=TRUST_FLOOR_CONN,
        ) is None
```

(After this pair `MagicMock`, `ConnManager`, `BridgeAlertService` and `ProbOSRuntime` are still used elsewhere in the file, at lines 8, 16, 17 and 337-417. Leave the imports alone.)

### 7.5 `src/probos/bridge_alerts.py` (M2)

**Pair 1.** SEARCH:
```
logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
```
REPLACE:
```
logger = logging.getLogger(__name__)

# AD-1270 (#1324): what of an event's payload a Night Orders alert may carry.
_NIGHT_ORDERS_SUBJECT_MAX = 64
_NIGHT_ORDERS_DETAIL_MAX = 500


def _score_text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return "?"


class AlertSeverity(str, Enum):
```

**Pair 2.** SEARCH:
```
    The service itself does NOT post to the Ward Room — it returns BridgeAlert
    objects that the runtime delivers via _deliver_bridge_alert().
```
REPLACE:
```
    The service itself does NOT post to the Ward Room — it returns BridgeAlert
    objects that the caller delivers via ``WardRoomRouter.deliver_bridge_alert``.
```

**Pair 3.** SEARCH:
```
        self._record(a)
        return a

    def check_emergent_patterns(self, patterns: list) -> list[BridgeAlert]:
```
REPLACE:
```
        self._record(a)
        return a

    def check_night_orders_escalation(
        self, trigger: str, details: dict[str, Any],
    ) -> BridgeAlert | None:
        """AD-471 / AD-1270 (#1324): the alert that pages the Captain under Night Orders.

        ALERT severity, so delivery posts to the ship channel and raises an
        ``action_required`` notification. Deduplicated per trigger and subject
        (the build id or the agent id) and suppressible like every alert (AD-580).
        Only the subject, the scores and a bounded message reach the text.
        """
        subject = str(details.get("build_id") or details.get("agent_id") or "")[:_NIGHT_ORDERS_SUBJECT_MAX]
        key = f"night_orders:{trigger}:{subject}" if subject else f"night_orders:{trigger}"
        if not self._should_emit(key):  # AD-580: cooldown, dismiss, resolve and mute apply
            return None
        if trigger == "trust_drop":
            detail = (
                f"Agent {subject or 'unknown'} fell below the conn trust floor "
                f"({_score_text(details.get('old_score'))} \u2192 {_score_text(details.get('new_score'))}) "
                "while Night Orders were set."
            )
        else:
            message = str(details.get("message") or details.get("error") or "no detail")[:_NIGHT_ORDERS_DETAIL_MAX]
            detail = f"Night Orders escalation ({trigger}): {message}"
        a = BridgeAlert(
            id=str(uuid.uuid4()), severity=AlertSeverity.ALERT, source="night_orders",
            alert_type=f"night_orders_{trigger}",
            title=f"Night Orders escalation: {trigger}",
            detail=detail, department=None, dedup_key=key,
            related_agent_id=(subject or None) if trigger == "trust_drop" else None,
        )
        self._record(a)
        return a

    def check_emergent_patterns(self, patterns: list) -> list[BridgeAlert]:
```

### 7.6 `src/probos/runtime.py` (M2)

**Pair U1 (`src/probos/runtime.py`).** SEARCH:
```
    def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Check if a runtime event should trigger Night Orders escalation.

        Called from event emission points (trust changes, alert changes,
        build results). If the event matches a Night Orders escalation trigger,
        fires a bridge alert to wake the Captain.
        """
        if not hasattr(self, '_night_orders_mgr') or not self._night_orders_mgr:
            return
        if not self._night_orders_mgr.active:
            return

        # Map runtime events to Night Orders trigger names
        trigger_map = {
            "trust_change": "trust_drop",
            "alert_condition_change": "red_alert",
            "build_failure": "build_failure",
            "security_alert": "security_alert",
        }
        trigger = trigger_map.get(event_type)
        if not trigger:
            return

        # Additional condition checks
        if trigger == "build_failure" and details and details.get("not_executed") is True:
            return  # BF-897: a refused request ran nothing, so there is no failure to escalate
        if trigger == "trust_drop" and details:
            # Only escalate if trust dropped below floor
            new_trust = details.get("new_trust", 1.0)
            if new_trust >= TRUST_FLOOR_CONN:  # Not below floor
                return
        if trigger == "red_alert" and details:
            new_level = details.get("new_level", "")
            if new_level.lower() != "red":
                return

        # Check against Night Orders escalation triggers
        if self._night_orders_mgr.check_escalation(trigger):
            # Also notify conn manager
            if self.conn_manager:
                self.conn_manager.check_escalation(trigger, details)
            # Fire bridge alert
            if hasattr(self, 'bridge_alerts') and self.bridge_alerts:
                self.bridge_alerts.add_alert(
                    severity="critical",
                    title=f"Night Orders escalation: {trigger}",
                    source="night_orders",
                    details=details or {},
                )
            logger.warning("Night Orders escalation triggered: %s", trigger)
```
REPLACE:
```
    def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Page the Captain when an emitted event matches an active Night Orders trigger (AD-471).

        AD-1270 (#1324): ``_emit_event`` calls this before durable offer and
        dispatch, so it never raises: a failure is logged and the event still
        reaches its durable row, its NATS publish and its listeners. The trigger
        rule lives beside the templates (``watch_rotation.night_order_trigger``);
        ``BridgeAlertService.check_night_orders_escalation`` builds the alert
        (deduplicated, and suppressible by the Captain, AD-580) and
        ``WardRoomRouter.deliver_bridge_alert`` delivers it, as every other bridge
        alert is delivered. A borrowed-method host (BF-708) may lack any
        collaborator, so each is read with ``getattr``.
        """
        try:
            mgr = getattr(self, "_night_orders_mgr", None)
            if not mgr or not mgr.active:
                return
            from probos.watch_rotation import night_order_trigger

            trigger = night_order_trigger(event_type, details, trust_floor=TRUST_FLOOR_CONN)
            if trigger is None or not mgr.check_escalation(trigger):
                return
            logger.warning("Night Orders escalation triggered: %s", trigger)
            conn = getattr(self, "conn_manager", None)
            if conn:
                conn.check_escalation(trigger, details)
            alerts = getattr(self, "bridge_alerts", None)
            router = getattr(self, "ward_room_router", None)
            if not alerts or not router:
                logger.warning(
                    "AD-1270: Night Orders escalation %s has no bridge-alert path; the Captain is not paged",
                    trigger,
                )
                return
            loop = asyncio.get_running_loop()  # before the alert is built, so an undeliverable alert never spends its cooldown
            tasks = self._event_listener_tasks
            alert = alerts.check_night_orders_escalation(trigger, details or {})
            if alert is None:
                return  # inside the cooldown, or suppressed by the Captain (AD-580)
            task = loop.create_task(router.deliver_bridge_alert(alert), name="night-orders-escalation")
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        except Exception:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch
            logger.warning(
                "AD-1270: Night Orders escalation failed for event %s; the event is still dispatched",
                event_type,
                exc_info=True,
            )
```

(Leave the `_emit_event` comment at `runtime.py:1946-1948` as it is. It is still true, and D7 keeps the hook where it is.)

### 7.7 New file: `tests/test_ad1270_night_orders_delivery.py` (M2)

```python
"""AD-1270 (#1324): a Night Orders escalation pages the Captain through the real
bridge-alert path, and never costs the event its dispatch (M2).

Hosts are the BF-708 shape: the unmodified runtime emission methods on a
minimal object, with a real NightOrdersManager, BridgeAlertService and
WardRoomRouter (its Ward Room is an AsyncMock).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.config import TRUST_FLOOR_CONN, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.ward_room_router import WardRoomRouter
from probos.watch_rotation import NightOrdersManager

_LOGGER = "probos.runtime"
_F = TRUST_FLOOR_CONN
_REAL = object()


class _Host:
    add_event_listener = ProbOSRuntime.add_event_listener
    emit_event = ProbOSRuntime.emit_event
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self, *, template: str = "maintenance", bridge_alerts: Any = _REAL, router: Any = _REAL) -> None:
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[asyncio.Task[Any]] = set()
        self._nats_publish_tasks: set[asyncio.Task[Any]] = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.offers: list[dict[str, Any]] = []
        self.durable_events = SimpleNamespace(offer=self.offers.append)
        self.conn_manager = MagicMock()
        self._night_orders_mgr = NightOrdersManager()
        self._night_orders_mgr.set_night_orders([], template=template)
        self.bridge_alerts = BridgeAlertService() if bridge_alerts is _REAL else bridge_alerts
        self.wr = AsyncMock()
        self.wr.get_channel_by_type.return_value = SimpleNamespace(id="ch-ship")
        self.notify = MagicMock()
        self.ward_room_router = (
            WardRoomRouter(
                ward_room=self.wr, registry=MagicMock(), intent_bus=AsyncMock(),
                trust_network=MagicMock(), ontology=None, callsign_registry=MagicMock(),
                episodic_memory=None, event_emitter=MagicMock(), event_log=AsyncMock(),
                config=SystemConfig(), notify_fn=self.notify,
            )
            if router is _REAL else router
        )
        self.events: list[dict[str, Any]] = []
        self.add_event_listener(self.events.append)

    async def settle(self) -> None:
        pending = list(self._event_listener_tasks)
        if pending:
            await asyncio.gather(*pending)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched() -> None:
    host = _Host()
    host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b9", "message": "Build failed: boom", "error": "boom"})
    assert len(host._event_listener_tasks) == 1  # the delivery is held, not fire-and-forget
    await host.settle()
    assert [e["type"] for e in host.events] == ["build_failure"]
    assert [e["type"] for e in host.offers] == ["build_failure"]
    host.conn_manager.check_escalation.assert_called_once()
    host.wr.create_thread.assert_awaited_once()
    kwargs = host.wr.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "ch-ship"
    assert kwargs["title"] == "[ALERT] Night Orders escalation: build_failure"
    assert "Build failed: boom" in kwargs["body"]
    host.notify.assert_called_once()
    assert host.notify.call_args.kwargs["notification_type"] == "action_required"


@pytest.mark.asyncio
async def test_a_trust_crossing_pages_once() -> None:
    host = _Host()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.1, "new_score": _F - 0.1})
    await host.settle()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F - 0.1, "new_score": _F - 0.2})
    await host.settle()
    assert host.conn_manager.check_escalation.call_count == 1  # staying below the floor is no crossing (D3)
    # A second crossing inside the 300 s cooldown matches; the service declines it (R6, AD-580).
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.05, "new_score": _F - 0.05})
    assert host.conn_manager.check_escalation.call_count == 2
    assert [t for t in host._event_listener_tasks if not t.done()] == []  # a declined alert is never delivered
    await host.settle()
    assert len(host.events) == 3 and len(host.offers) == 3
    host.wr.create_thread.assert_awaited_once()
    assert host.wr.create_thread.await_args.kwargs["title"] == "[ALERT] Night Orders escalation: trust_drop"


@pytest.mark.asyncio
async def test_a_refused_build_or_an_unlisted_trigger_pages_nobody() -> None:
    refused = _Host()
    refused.emit_event(EventType.BUILD_FAILURE, {"build_id": "b1", "not_executed": True})
    unlisted = _Host(template="build")  # security_alert and trust_drop only
    unlisted.emit_event(EventType.BUILD_FAILURE, {"build_id": "b2", "message": "m"})
    for host in (refused, unlisted):
        await host.settle()
        assert len(host.events) == 1 and len(host.offers) == 1
        host.conn_manager.check_escalation.assert_not_called()
        host.wr.create_thread.assert_not_awaited()


@pytest.mark.parametrize("raiser", ["alerts", "orders", "conn"])
@pytest.mark.asyncio
async def test_an_escalation_that_raises_never_costs_the_event_its_dispatch(
    raiser: str, caplog: pytest.LogCaptureFixture,
) -> None:
    alerts = MagicMock(spec=BridgeAlertService)
    alerts.check_night_orders_escalation.side_effect = RuntimeError("boom")
    host = _Host(bridge_alerts=alerts if raiser == "alerts" else _REAL)
    if raiser == "orders":
        host._night_orders_mgr = MagicMock()
        host._night_orders_mgr.active = True
        host._night_orders_mgr.check_escalation.side_effect = RuntimeError("boom")
    if raiser == "conn":
        host.conn_manager.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b3", "message": "m"})
    await host.settle()
    assert len(host.events) == 1
    assert len(host.offers) == 1
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    host.wr.create_thread.assert_not_awaited()


def test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b4", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    assert host._event_listener_tasks == set()
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    assert host.bridge_alerts.check_night_orders_escalation("build_failure", {"build_id": "b4"}) is not None


@pytest.mark.parametrize("missing", ["bridge_alerts", "router"])
def test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged(
    missing: str, caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host(**{missing: None})
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b5", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    host.conn_manager.check_escalation.assert_called_once()
    assert any("has no bridge-alert path; the Captain is not paged" in m for m in _messages(caplog))


def test_the_alert_is_deduplicated_per_subject_and_suppressible() -> None:
    svc = BridgeAlertService()
    first = svc.check_night_orders_escalation("build_failure", {"build_id": "b1", "message": "x" * 900})
    assert first is not None
    assert first.severity is AlertSeverity.ALERT
    assert first.source == "night_orders"
    assert first.alert_type == "night_orders_build_failure"
    assert first.dedup_key == "night_orders:build_failure:b1"
    assert first.detail == "Night Orders escalation (build_failure): " + "x" * 500
    assert first.related_agent_id is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b1"}) is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b2"}) is not None
    svc.mute_alert("night_orders:build_failure:b3")
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b3"}) is None


def test_a_trust_drop_alert_names_the_agent_and_its_scores() -> None:
    svc = BridgeAlertService()
    a = svc.check_night_orders_escalation("trust_drop", {"agent_id": "a1", "old_score": 0.7, "new_score": 0.5})
    assert a is not None
    assert a.related_agent_id == "a1"
    assert a.dedup_key == "night_orders:trust_drop:a1"
    assert "(0.70 \u2192 0.50)" in a.detail
    b = svc.check_night_orders_escalation("build_failure", {})
    assert b is not None and b.dedup_key == "night_orders:build_failure"
```

### 7.8 Repair round 1 (A2)

These pairs apply to `894526c6`, after §7.1 to §7.7 and §8, as one repair commit. Apply them tests-first: A2-1 to A2-5, then run them over the candidate's source, which should fail five cases as §6 predicts; then A2-6 to A2-12. Each SEARCH occurs exactly once in its file. A2-11 and A2-12 match a substring of one long line. The working copies are CRLF.

| Case (over the candidate's source) | Result | First failure |
|---|---|---|
| `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[huge-int]` | fails | `OverflowError: int too large to convert to float` in `_is_score` (`watch_rotation.py:255`) |
| `[new-bool]`, `[new-neg-inf]` | pass (negative cases; they bind W-12) | — |
| `test_a_template_order_that_is_already_expired_does_not_break_the_console[maintenance]`, `[build]`, `[quiet]` | fail | `KeyError: 'inert_triggers'` raised from the `await` (`commands_autonomous.py:176`) |
| `test_a_conn_log_that_raises_still_pages_the_captain` | fails | `host.wr.create_thread.assert_awaited_once()`: awaited 0 times |
| `test_the_inert_triggers_still_have_no_producer` (extended) | passes (guard) | — |
| `test_an_escalation_that_raises_never_costs_the_event_its_dispatch[alerts]`, `[orders]` | pass (unchanged) | — |

**Verified on `894526c6` (2026-10-27):**
```
Read commands_autonomous.py:120-190  -> :176 indexes get_status()["inert_triggers"]; :134 guards the status branch
Read watch_rotation.py:222-256, :285-290, :306-314, :399-417 -> _is_score :254-255; is_expired; inactive status {"active": False}
Read runtime.py:2137-2185 -> docstring :2140-2142; conn :2160-2162; loop :2171; outer except :2179
Read shell.py:345-350 -> handler wraps exceptions as "Command error"
Read tests/test_ad1270_night_orders_triggers.py:24-195; tests/test_ad1270_night_orders_delivery.py:1-159
Grep deliver_bridge_alert\( src/probos -> 8 awaiting sites; runtime.py:4794, :6871 fire-and-forget
grep -c on the PROGRESS and DECISIONS phrases -> 1 each
```

**Absence verified (2026-10-27):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other reader indexes `inert_triggers` without a guard | Grep `inert_triggers` in `src` | `commands_autonomous.py:146` (guarded by `:134`), `:176`; `watch_rotation.py:416` (producer) | yes |
| The extended T2 regex matches nothing today | Grep `emit_event\w*\(\s*["'](trust_change\|alert_condition_change\|red_alert\|security_alert)` in `src` | no matches | yes |
| No test scans the runtime lines A2 changes | Grep `undeliverable\|durable row\|ConnManager escalation failed\|_is_score` in `tests` | unrelated AD-1195/1274/BF-722 matches only | yes |

*(A5: reverted by the split. §7.11 applies this pair's reverse, so T2's last assertion is round 1's line again.)*

**Pair A2-1 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
    assert [p for p, t in texts.items() if re.search(r"""emit_event\w*\(\s*["']security_alert""", t)] == []
```
REPLACE:
```
    # AD-1270 A2 (B3): a literal emission of any of the four old names. A producer behind a renamed
    # emitter is not caught (register R11 on #1324); resolving aliases is out of proportion here.
    emitted = r"""emit_event\w*\(\s*["'](?:security_alert|red_alert|alert_condition_change|trust_change)"""
    assert [p for p, t in texts.items() if re.search(emitted, t)] == []
```

**Pair A2-2 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
        ("0.7", "0.5", None),
        (None, _F - 0.1, None),
    ],
    ids=["crosses", "from-floor", "already-below", "lands-on-floor", "rises", "floor-hit",
         "inf", "nan", "bool", "str", "missing"],
)
```
REPLACE:
```
        ("0.7", "0.5", None),
        (None, _F - 0.1, None),
        # AD-1270 A2 (B5): a valid old score beside an invalid new one that the comparison alone would accept
        (_F + 0.1, False, None),
        (_F + 0.1, -math.inf, None),
        # AD-1270 A2 (B4): a finite integer too large for a float is still a score
        (10**400, _F - 0.1, "trust_drop"),
    ],
    ids=["crosses", "from-floor", "already-below", "lands-on-floor", "rises", "floor-hit",
         "inf", "nan", "bool", "str", "missing", "new-bool", "new-neg-inf", "huge-int"],
)
```

**Pair A2-3 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
    assert "Escalates on: build_failure" in text
    assert "Never fires" not in text
```
REPLACE:
```
    assert "Escalates on: build_failure" in text
    assert "Never fires" not in text


@pytest.mark.parametrize("template", ["maintenance", "build", "quiet"])
@pytest.mark.asyncio
async def test_a_template_order_that_is_already_expired_does_not_break_the_console(template: str) -> None:
    """AD-1270 A2 (B1): the console accepts a TTL that has already run out, so the status is exactly
    ``{"active": False}``; the console must not index ``inert_triggers`` on it. A negative TTL, not 0:
    a TTL of 0 may still be active at the clock's resolution."""
    rt = _runtime()
    console = _console()
    await commands_autonomous.cmd_night_orders(rt, console, f"{template} -1")
    assert rt._night_orders_mgr.orders is not None
    assert rt._night_orders_mgr.get_status() == {"active": False}
    assert "Never fires" not in _out(console)
```

**Pair A2-4 (`tests/test_ad1270_night_orders_delivery.py`).** SEARCH:
```
@pytest.mark.parametrize("raiser", ["alerts", "orders", "conn"])
@pytest.mark.asyncio
async def test_an_escalation_that_raises_never_costs_the_event_its_dispatch(
    raiser: str, caplog: pytest.LogCaptureFixture,
) -> None:
    alerts = MagicMock(spec=BridgeAlertService)
    alerts.check_night_orders_escalation.side_effect = RuntimeError("boom")
    host = _Host(bridge_alerts=alerts if raiser == "alerts" else _REAL)
    if raiser == "orders":
        host._night_orders_mgr = MagicMock()
        host._night_orders_mgr.active = True
        host._night_orders_mgr.check_escalation.side_effect = RuntimeError("boom")
    if raiser == "conn":
        host.conn_manager.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
```
REPLACE:
```
@pytest.mark.parametrize("raiser", ["alerts", "orders"])  # AD-1270 A2: a raising conn log no longer stops the page (D4b)
@pytest.mark.asyncio
async def test_an_escalation_that_raises_never_costs_the_event_its_dispatch(
    raiser: str, caplog: pytest.LogCaptureFixture,
) -> None:
    alerts = MagicMock(spec=BridgeAlertService)
    alerts.check_night_orders_escalation.side_effect = RuntimeError("boom")
    host = _Host(bridge_alerts=alerts if raiser == "alerts" else _REAL)
    if raiser == "orders":
        host._night_orders_mgr = MagicMock()
        host._night_orders_mgr.active = True
        host._night_orders_mgr.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
```

**Pair A2-5 (`tests/test_ad1270_night_orders_delivery.py`).** SEARCH:
```
def test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent(
```
REPLACE:
```
@pytest.mark.asyncio
async def test_a_conn_log_that_raises_still_pages_the_captain(caplog: pytest.LogCaptureFixture) -> None:
    """AD-1270 A2 (review A F1): ``ConnManager.check_escalation`` is bookkeeping; its failure is logged and the page goes."""
    host = _Host()
    host.conn_manager.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b5", "message": "m"})
    await host.settle()
    assert len(host.events) == 1 and len(host.offers) == 1
    host.wr.create_thread.assert_awaited_once()
    messages = _messages(caplog)
    assert any("ConnManager escalation failed for build_failure" in m for m in messages)
    assert not any("Night Orders escalation failed" in m for m in messages)


def test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent(
```

**Pair A2-6 (`src/probos/experience/commands/commands_autonomous.py`).** SEARCH:
```
        inert = rt._night_orders_mgr.get_status()["inert_triggers"]
```
REPLACE:
```
        status = rt._night_orders_mgr.get_status()
        # AD-1270 A2 (#1324): a TTL that has already run out leaves the order inactive, and an
        # inactive status is exactly {"active": False}, with no inert_triggers key.
        inert = status["inert_triggers"] if status["active"] else []
```

**Pair A2-7 (`src/probos/watch_rotation.py`).** SEARCH:
```
def _is_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
```
REPLACE:
```
def _is_score(value: Any) -> bool:
    # AD-1270 A2 (#1324): an int is exact and always finite; math.isfinite would convert it to float and overflow
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))
```

**Pair A2-8 (`src/probos/runtime.py`).** SEARCH:
```
        AD-1270 (#1324): ``_emit_event`` calls this before durable offer and
        dispatch, so it never raises: a failure is logged and the event still
        reaches its durable row, its NATS publish and its listeners. The trigger
```
REPLACE:
```
        AD-1270 (#1324): ``_emit_event`` calls this before durable offer and
        dispatch, so it never raises: a failure is logged and the event still
        goes to the durable offer (the durable router decides whether it is
        persisted), the NATS publish when connected, and its local listeners. The trigger
```

**Pair A2-9 (`src/probos/runtime.py`).** SEARCH:
```
            conn = getattr(self, "conn_manager", None)
            if conn:
                conn.check_escalation(trigger, details)
```
REPLACE:
```
            conn = getattr(self, "conn_manager", None)
            if conn:
                try:
                    conn.check_escalation(trigger, details)
                except Exception:  # AD-1270 A2 (#1324): ConnManager's log is bookkeeping; its failure must not cost the Captain the page
                    logger.warning(
                        "AD-1270: ConnManager escalation failed for %s; the bridge alert still proceeds",
                        trigger,
                        exc_info=True,
                    )
```

**Pair A2-10 (`src/probos/runtime.py`).** SEARCH:
```
            loop = asyncio.get_running_loop()  # before the alert is built, so an undeliverable alert never spends its cooldown
```
REPLACE:
```
            loop = asyncio.get_running_loop()  # before the alert is built: outside a running loop no alert is built, so no cooldown is spent
```

**Pair A2-11 (`PROGRESS.md`).** SEARCH:
```
the hook is now log-and-degrade and the event always reaches its durable row, its NATS publish and its listeners.
```
REPLACE:
```
the hook is now log-and-degrade, so a failure there no longer stops the event's durable offer (the durable router decides what is persisted; neither event type is routed for persistence today), its NATS publish or its listeners.
```

*(A5: superseded. A3-4 and then A4-8 replaced this sentence; §7.11's pair A5-2 replaces A4-8's with a sentence about round 1's T2.)*

**Pair A2-12 (`DECISIONS.md`).** SEARCH:
```
A guard test fails when a producer lands, so mapping it is one line.
```
REPLACE:
```
A guard test (T2) fails when a producer lands in one of the usual forms (an `EventType` member with an old name, a `set_alert_condition` call, or a literal `emit_event*` call naming an old event); a producer behind a renamed emitter is not caught (#1324 register R11). Mapping a producer is one line.
```

### 7.9 Repair round 2 (A3)

*(A5: not built in this slice. Built in `698950a9` and reverted by the split; this section is slice 1b's drafted text, R13. Its prefilter claims must be re-proved there.)*

These pairs apply to `5f4b57ed`, after §7.8, as one repair commit. Apply A3-1 to A3-3 together, since A3-1 removes `import re` and A3-3 removes its last use. Then run the triggers file and the oracle below. Then apply A3-4. Each SEARCH occurs exactly once in its file. A3-4 matches a substring of one long line. The working copies are CRLF.

No production source changes, so every new case passes over the candidate. The discriminating run is the **A2-predicate oracle**. In a scratch script (not committed), evaluate each of the 27 fixture sources with `bool(re.search(r"\.set_alert_condition\(", s) or re.search(r"""emit_event\w*\(\s*["'](?:security_alert|red_alert|alert_condition_change|trust_change)""", s))` and compare the result with the expected truth (flags True; ignores and does-not-resolve False; the syntax case expects a raise).

| Fixture | A2 predicate | Expected | Class |
|---|---|---|---|
| `flags[space-before-paren]`, `[event-type-kw]`, `[event-kw]`, `[name-kw]`, `[set-alert-space]` | False | True | F1: missed producer |
| `ignores[comment]`, `[docstring]`, `[longer-name]`, `[longer-name-trust]` | True | False | F2: false rejection |
| `test_a_source_the_guard_cannot_parse_fails_it` | returns | raises `SyntaxError` | A3 decision |
| the other 17 | agree | — | — |

**Prior art (internal):** parsing source in tests is an existing repo pattern (`ast.walk(ast.parse(` in `tests/test_bf891_*`, `test_bf890_*`, `test_bf877_*`, `test_bf875_*`, `test_bf811_*`). No external search: this is ProbOS-specific plumbing.

**Verified on `5f4b57ed` (2026-10-27):**
```
Read tests/test_ad1270_night_orders_triggers.py:1-120 -> imports :8-10; _source :42-43; T2 :59-68
Grep "\bre\." tests/test_ad1270_night_orders_triggers.py -> :64, :68 only
Grep "def _*emit_event\w*\(" src/probos -> builder.py:1331,1334; protocols.py:244; runtime.py:1930,1977,2018;
  security/pairing/service.py:74; cognitive/self_improvement/approval_gate.py:169, evolution_store.py:1253, proposal.py:269
Read security/pairing/service.py:74-80 (self._emit(name, payload)); Grep :61 self._emit = emit_event
Read cognitive/self_improvement/approval_gate.py:169-175 (self._emit(name, payload))
Grep startup/finalize.py -> :2560 emit = getattr(runtime, "emit_event", None); :2596-2598 ApprovalGate(event_emit_fn=emit)
Grep "_emit_event_local\(|_check_night_order_escalation\(" src/probos -> runtime.py:1949 (hook), :1966, :1975 (local dispatch)
Grep the A2-12 sentence in DECISIONS.md -> 1 match (:871)
pyproject.toml:9 requires-python = ">=3.12"
wc -l runtime.py 7011, workforce.py 12150, watch_rotation.py 424, ontology/service.py 650
```

**Absence verified (2026-10-27):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No call in `src/probos` is flagged today | Grep `["'](security_alert\|red_alert\|alert_condition_change\|trust_change)["']` and `set_alert_condition` in `src/probos` | list items, dict keys and comments only (`conn.py:54,56,202`; `config_models/knowledge.py:310`; `workforce.py:804,822,840`; `cognitive/importance_scorer.py:26`; `watch_rotation.py:190,197,204,216`); the def at `ontology/service.py:105` | yes |
| The prefilter parses 4 files | files with `emit_event` (157) ∩ files with an old name (8) = `runtime.py`, `workforce.py`; files with `set_alert_condition` = `watch_rotation.py`, `ontology/service.py` | 4 files, 20,235 lines | yes |
| PROGRESS does not describe T2 | Grep `guard test\|literal emission` and `\bT2\b` in `PROGRESS.md` | `:417`, `:961`, `:963`, `:993`, none in the AD-1270 paragraph (`:3`) | yes |

**Pair A3-1 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
from __future__ import annotations

import logging
import math
import re
from io import StringIO
```
REPLACE:
```
from __future__ import annotations

import ast
import logging
import math
from io import StringIO
```

**Pair A3-2 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
def _source(*parts: str) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# --- T1, T2: the map names producers, and only producers ---------------------
```
REPLACE:
```
def _source(*parts: str) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# AD-1270 A3 (review B round 2, F1 and F2): T2 finds producers by parsing, not by matching text.
_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
# The keywords that carry the event: ``event`` (``ProbOSRuntime.emit_event``), ``event_type``
# (``_emit_event``) and ``name`` (the ``_emit_event(name, ...)`` helpers that forward to ``emit_event``).
_EVENT_KEYWORDS = frozenset({"event", "event_type", "name"})


def _old_producer_calls(source: str) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for each call in ``source`` that would produce an inert trigger today.

    Flagged: a call whose callee (a name or an attribute) is ``set_alert_condition``; and a call whose
    callee, with leading underscores stripped, starts with ``emit_event`` and whose first positional
    argument, or ``event``, ``event_type`` or ``name`` keyword, is a string literal equal to an old
    event name. Comments, docstrings and longer names never count. Not resolved (register R11 on
    #1324): an emitter under another name, a call through ``getattr``, and a name held in a variable,
    written as an f-string or not present whole in the text (adjacent literals, escapes), which the
    prefilter skips. A source that may hold a producer and does not parse raises ``SyntaxError``:
    the guard fails on a file it cannot read instead of passing it.
    """
    emits_old = "emit_event" in source and any(name in source for name in _OLD_EVENT_NAMES)
    if not emits_old and "set_alert_condition" not in source:
        return []  # neither form can be present, so the source is not parsed
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if callee == "set_alert_condition":
            hits.append((node.lineno, callee))
        if not callee.lstrip("_").startswith("emit_event"):
            continue
        for arg in node.args[:1] + [kw.value for kw in node.keywords if kw.arg in _EVENT_KEYWORDS]:
            if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:
                hits.append((node.lineno, arg.value))
    return sorted(hits)


# --- T1, T2: the map names producers, and only producers ---------------------
```

**Pair A3-3 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
def test_the_inert_triggers_still_have_no_producer() -> None:
    """If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS."""
    values = {m.value for m in EventType}
    assert values.isdisjoint({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    assert [p for p, t in texts.items() if re.search(r"\.set_alert_condition\(", t)] == []
    # AD-1270 A2 (B3): a literal emission of any of the four old names. A producer behind a renamed
    # emitter is not caught (register R11 on #1324); resolving aliases is out of proportion here.
    emitted = r"""emit_event\w*\(\s*["'](?:security_alert|red_alert|alert_condition_change|trust_change)"""
    assert [p for p, t in texts.items() if re.search(emitted, t)] == []
```
REPLACE:
```
def test_the_inert_triggers_still_have_no_producer() -> None:
    """If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS."""
    values = {m.value for m in EventType}
    assert values.isdisjoint(_OLD_EVENT_NAMES)
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    # AD-1270 A3: calls found by parsing (see _old_producer_calls); what it cannot see is register R11 on #1324.
    found = {p: _old_producer_calls(t) for p, t in texts.items()}
    assert {p: hits for p, hits in found.items() if hits} == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('rt.emit_event("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event ("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(\n    "red_alert",\n    {},\n)\n', [(1, "red_alert")]),
        ('emit_event("trust_change", {})\n', [(1, "trust_change")]),
        ('rt._emit_event(event_type="trust_change", data={})\n', [(1, "trust_change")]),
        ('rt.emit_event(event="security_alert")\n', [(1, "security_alert")]),
        ('self._emit_event(name="alert_condition_change", payload={})\n', [(1, "alert_condition_change")]),
        ('log(rt.emit_event("security_alert", {}))\n', [(1, "security_alert")]),
        ('log(rt.emit_event("security_alert", {}))\nrt.emit_event("red_alert", {})\n',
         [(1, "security_alert"), (2, "red_alert")]),
        ('svc.set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        ('svc.set_alert_condition ("RED")\n', [(1, "set_alert_condition")]),
    ],
    ids=["positional", "space-before-paren", "split-lines", "bare-name", "event-type-kw", "event-kw", "name-kw",
         "nested", "two-calls", "set-alert", "set-alert-space"],
)
def test_old_producer_calls_flags_a_literal_producer(source: str, expected: list[tuple[int, str]]) -> None:
    """AD-1270 A3 (review B r2 F1): every supported way of naming the event in a direct call is found."""
    assert _old_producer_calls(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        '# e.g. rt.emit_event("red_alert", {})\nx = 1\n',
        '"""Page with rt.emit_event("red_alert", {}) or svc.set_alert_condition("RED")."""\n',
        'rt.emit_event("red_alert_resolved", {})\n',
        'rt.emit_event("trust_change_summary", {})\n',
        'rt.emit_event("build_failure", {})\nrt.publish("red_alert", {})\n',
        'rt.emit_event("build_failure", "red_alert")\n',
        'rt.emit_event("build_failure", data="red_alert")\n',
        'def set_alert_condition(self, condition):\n    pass\n',
        'rt.emit_event("build_failure", {}\n',
        'def (:\n',
    ],
    ids=["comment", "docstring", "longer-name", "longer-name-trust", "other-callee", "second-positional",
         "other-keyword", "definition-only", "unparsable-without-old-name", "unparsable-unrelated"],
)
def test_old_producer_calls_ignores_what_is_not_a_producer(source: str) -> None:
    """AD-1270 A3 (review B r2 F2): text that only mentions a producer, or names a longer event, is not one."""
    assert _old_producer_calls(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'fire = rt.emit_event\nfire("red_alert", {})\n',
        'getattr(rt, "emit_event")("red_alert", {})\n',
        'name = "red_alert"\nrt.emit_event(name, {})\n',
        'rt.emit_event(f"red_alert", {})\n',
        'rt.emit_event("red_" "alert", {})\n',
    ],
    ids=["alias", "getattr", "variable", "f-string", "split-literal"],
)
def test_old_producer_calls_does_not_resolve_these_forms(source: str) -> None:
    """Register R11 on #1324: forms the guard does not resolve. If one starts to match, update R11 and DECISIONS."""
    assert _old_producer_calls(source) == []


def test_a_source_the_guard_cannot_parse_fails_it() -> None:
    """AD-1270 A3: a file that may hold a producer and does not parse fails T2 instead of being skipped."""
    with pytest.raises(SyntaxError):
        _old_producer_calls('rt.emit_event("red_alert", {}\n')
```

**Pair A3-4 (`DECISIONS.md`).** SEARCH:
```
A guard test (T2) fails when a producer lands in one of the usual forms (an `EventType` member with an old name, a `set_alert_condition` call, or a literal `emit_event*` call naming an old event); a producer behind a renamed emitter is not caught (#1324 register R11). Mapping a producer is one line.
```
REPLACE:
```
A guard test (T2) fails when a producer lands in a form it can see: an `EventType` member with an old name, or a call it finds by parsing `src/probos`, either a `set_alert_condition` call or an `emit_event*` call whose event (the first positional argument, or the `event`, `event_type` or `name` keyword) is a string literal equal to an old name. Comments, docstrings and longer names such as `red_alert_resolved` do not count. It does not resolve an emitter under another name, a call through `getattr`, or a name held in a variable, written as an f-string or split across literals (#1324 register R11). Mapping a producer is one line.
```

### 7.10 Repair round 3 (A4)

*(A5: not built in this slice. Built in `6cc1a1a3` and reverted by the split; this section is slice 1b's drafted text, R13. Its `tokenize.open` premise is false (round 4 F1) and must not be carried into 1b.)*

These pairs apply to `698950a9` as one repair commit, in order. Each SEARCH occurs exactly once in its file at the time it is applied. A4-8 matches a substring of one long line. The working copies are CRLF. No production source changes. The helper change is a deletion: after A4, `_old_producer_calls` flags a subset of what A3 flagged on every source, so it cannot add a false rejection. Decoding with `tokenize.open` fails only where Python's importer also fails.

**Discriminating run.** (1) A scratch oracle, not committed: copy A3's `_old_producer_calls` and `_EVENT_KEYWORDS` from `698950a9` and evaluate them on the A4 fixture sources. Predicted: exactly 5 disagreements with the A4 expectations, all G1 or keyword-scan cases: `ignores[payload-event-type]`, `ignores[payload-keyword-bound]`, `does_not_resolve[event-type-kw]`, `[event-kw]` and `[name-kw]`. The new `flags` cases and `does_not_resolve[normalised-callee]` agree with A3; they are coverage fixtures, not repairs. (2) The census: H-18 puts back a keyword scan (G1) and H-21 puts back the A3 decoding (G2). Both must be killed.

**Verified on `698950a9` (2026-10-27):**
```
Read tests/test_ad1270_night_orders_triggers.py:1-185 -> imports :8-17; helper :46-81; T2 :97-104; fixtures :107-172
Grep "_EVENT_KEYWORDS|tokenize|_scan_tree" tests/test_ad1270_night_orders_*.py -> :50, :78 only
Grep "def _*emit_event\w*\(" src/probos -> builder.py:1331,1334 (self_, event_type, data); runtime.py:1930 (event_type, data);
  protocols.py:244, runtime.py:2018 (event, data); runtime.py:1977 _emit_event_local(event: dict, type_str);
  security/pairing/service.py:74 (name, payload); approval_gate.py:169, evolution_store.py:1253 (name, **payload); proposal.py:269 (name, proposal_id, action, **extra)
grep -o DECISIONS.md -> :871 holds the A3-4 sentence verbatim
Grep "import tokenize" tests -> tests/test_ad1270e2i_agentic_models.py:37 (precedent)
```

**Absence verified (2026-10-27):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No call in `src/probos` binds the event by keyword | Grep, multiline, `emit_event\w*\s*\(\s*(event\|event_type\|name)\s*=` in `src/probos` | none | yes |
| No PEP 263 coding line in `src/probos` | Grep `^#.*coding[:=]` in `src/probos` | `__main__.py:35`, a comment on line 35 (a coding line must be on line 1 or 2) | yes |

**Pair A4-1 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
import ast
import logging
import math
from io import StringIO
```
REPLACE:
```
import ast
import logging
import math
import tokenize
from io import StringIO
```

**Pair A4-2 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
# The keywords that carry the event: ``event`` (``ProbOSRuntime.emit_event``), ``event_type``
# (``_emit_event``) and ``name`` (the ``_emit_event(name, ...)`` helpers that forward to ``emit_event``).
_EVENT_KEYWORDS = frozenset({"event", "event_type", "name"})


def _old_producer_calls(source: str) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for each call in ``source`` that would produce an inert trigger today.

    Flagged: a call whose callee (a name or an attribute) is ``set_alert_condition``; and a call whose
    callee, with leading underscores stripped, starts with ``emit_event`` and whose first positional
    argument, or ``event``, ``event_type`` or ``name`` keyword, is a string literal equal to an old
    event name. Comments, docstrings and longer names never count. Not resolved (register R11 on
    #1324): an emitter under another name, a call through ``getattr``, and a name held in a variable,
    written as an f-string or not present whole in the text (adjacent literals, escapes), which the
    prefilter skips. A source that may hold a producer and does not parse raises ``SyntaxError``:
    the guard fails on a file it cannot read instead of passing it.
    """
```
REPLACE:
```
_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})


def _old_producer_calls(source: str) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for each call in ``source`` that would produce an inert trigger today.

    Flagged: a call whose callee (a name or an attribute) is ``set_alert_condition``; and a call whose
    callee, with leading underscores stripped, starts with ``emit_event`` and whose first positional
    argument is a string literal equal to an old event name. Keywords are never read (AD-1270 A4,
    review B r3 G1): every ``emit_event*`` method in ``src/probos`` but ``_emit_event_local`` takes the
    event as its first parameter, and the forwarders' keywords are payload. Comments, docstrings and
    longer names never count.

    Only a source whose text contains ``set_alert_condition``, or ``emit_event`` and an old name whole,
    is parsed. In a parsed source the parser joins adjacent literals and decodes escapes, so those are
    found; a name split or escaped that way, or a callee Python normalises (NFKC) to ``emit_event`` or
    ``set_alert_condition``, is found only when the text also passes that filter. Not resolved
    (register R11 on #1324): an event passed by keyword, an emitter under another name, a call through
    ``getattr``, and a name held in a variable or written as an f-string. A source the filter admits
    that does not parse raises ``SyntaxError``: the guard fails on a file it cannot read instead of
    passing it.
    """
```

**Pair A4-3 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
        if not callee.lstrip("_").startswith("emit_event"):
            continue
        for arg in node.args[:1] + [kw.value for kw in node.keywords if kw.arg in _EVENT_KEYWORDS]:
            if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:
                hits.append((node.lineno, arg.value))
    return sorted(hits)
```
REPLACE:
```
        if not callee.lstrip("_").startswith("emit_event"):
            continue
        # AD-1270 A4 (review B r3 G1): the event is the first positional argument; a keyword is payload or R11 (g).
        for arg in node.args[:1]:
            if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:
                hits.append((node.lineno, arg.value))
    return sorted(hits)


def _scan_tree(root: Path) -> dict[str, list[tuple[int, str]]]:
    """T2's scan: ``{path relative to root: hits}`` for each ``*.py`` file under ``root`` with a hit.

    AD-1270 A4 (review B r3 G2): a file is decoded as the importer decodes it (``tokenize.open`` honours
    a UTF-8 BOM and a PEP 263 coding line), so a valid module never fails the scan by its encoding.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    for path in root.rglob("*.py"):
        with tokenize.open(path) as handle:
            hits = _old_producer_calls(handle.read())
        if hits:
            found[path.relative_to(root).as_posix()] = hits
    return found
```

**Pair A4-4 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    # AD-1270 A3: calls found by parsing (see _old_producer_calls); what it cannot see is register R11 on #1324.
    found = {p: _old_producer_calls(t) for p, t in texts.items()}
    assert {p: hits for p, hits in found.items() if hits} == {}
```
REPLACE:
```
    # AD-1270 A3, A4: calls found by parsing (_old_producer_calls over _scan_tree); blind spots are R11 on #1324.
    assert _scan_tree(_SRC) == {}
```

**Pair A4-5 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
        ('emit_event("trust_change", {})\n', [(1, "trust_change")]),
        ('rt._emit_event(event_type="trust_change", data={})\n', [(1, "trust_change")]),
        ('rt.emit_event(event="security_alert")\n', [(1, "security_alert")]),
        ('self._emit_event(name="alert_condition_change", payload={})\n', [(1, "alert_condition_change")]),
        ('log(rt.emit_event("security_alert", {}))\n', [(1, "security_alert")]),
        ('log(rt.emit_event("security_alert", {}))\nrt.emit_event("red_alert", {})\n',
         [(1, "security_alert"), (2, "red_alert")]),
        ('svc.set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        ('svc.set_alert_condition ("RED")\n', [(1, "set_alert_condition")]),
    ],
    ids=["positional", "space-before-paren", "split-lines", "bare-name", "event-type-kw", "event-kw", "name-kw",
         "nested", "two-calls", "set-alert", "set-alert-space"],
)
def test_old_producer_calls_flags_a_literal_producer(source: str, expected: list[tuple[int, str]]) -> None:
    """AD-1270 A3 (review B r2 F1): every supported way of naming the event in a direct call is found."""
```
REPLACE:
```
        ('emit_event("trust_change", {})\n', [(1, "trust_change")]),
        ('self._emit_event_fn("alert_condition_change", {})\n', [(1, "alert_condition_change")]),
        ('log(rt.emit_event("security_alert", {}))\n', [(1, "security_alert")]),
        ('log(rt.emit_event("security_alert", {}))\nrt.emit_event("red_alert", {})\n',
         [(1, "security_alert"), (2, "red_alert")]),
        ('x = "security_alert"\nrt.emit_event("red_" "alert", {})\n', [(2, "red_alert")]),
        ('svc.set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        ('svc.set_alert_condition ("RED")\n', [(1, "set_alert_condition")]),
        ('set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
    ],
    ids=["positional", "space-before-paren", "split-lines", "bare-name", "suffixed-callee", "nested", "two-calls",
         "split-literal-admitted", "set-alert", "set-alert-space", "set-alert-bare"],
)
def test_old_producer_calls_flags_a_literal_producer(source: str, expected: list[tuple[int, str]]) -> None:
    """AD-1270 A3, A4: a direct call naming an old event as its first positional argument is found."""
```

**Pair A4-6 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
        'rt.emit_event("build_failure", data="red_alert")\n',
        'def set_alert_condition(self, condition):\n    pass\n',
        'rt.emit_event("build_failure", {}\n',
        'def (:\n',
    ],
    ids=["comment", "docstring", "longer-name", "longer-name-trust", "other-callee", "second-positional",
         "other-keyword", "definition-only", "unparsable-without-old-name", "unparsable-unrelated"],
)
```
REPLACE:
```
        'rt.emit_event("build_failure", data="red_alert")\n',
        'self._emit_event("build_failure", event_type="red_alert")\n',
        'self._emit_event(name="build_failure", event_type="red_alert")\n',
        'def set_alert_condition(self, condition):\n    pass\n',
        'rt.emit_event("build_failure", {}\n',
        'def (:\n',
    ],
    ids=["comment", "docstring", "longer-name", "longer-name-trust", "other-callee", "second-positional",
         "other-keyword", "payload-event-type", "payload-keyword-bound", "definition-only",
         "unparsable-without-old-name", "unparsable-unrelated"],
)
```

**Pair A4-7 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
        'rt.emit_event("red_" "alert", {})\n',
    ],
    ids=["alias", "getattr", "variable", "f-string", "split-literal"],
)
def test_old_producer_calls_does_not_resolve_these_forms(source: str) -> None:
    """Register R11 on #1324: forms the guard does not resolve. If one starts to match, update R11 and DECISIONS."""
    assert _old_producer_calls(source) == []


def test_a_source_the_guard_cannot_parse_fails_it() -> None:
    """AD-1270 A3: a file that may hold a producer and does not parse fails T2 instead of being skipped."""
    with pytest.raises(SyntaxError):
        _old_producer_calls('rt.emit_event("red_alert", {}\n')
```
REPLACE:
```
        'rt.emit_event("red_" "alert", {})\n',
        'rt._emit_event(event_type="trust_change", data={})\n',
        'rt.emit_event(event="security_alert")\n',
        'self._emit_event(name="alert_condition_change", payload={})\n',
        'rt.\uff45mit_event("red_alert", {})\n',
    ],
    ids=["alias", "getattr", "variable", "f-string", "split-literal", "event-type-kw", "event-kw", "name-kw",
         "normalised-callee"],
)
def test_old_producer_calls_does_not_resolve_these_forms(source: str) -> None:
    """Register R11 on #1324: forms the guard does not resolve; split-literal and normalised-callee only because
    the filter skips the file. If one starts to match, update R11 and DECISIONS."""
    assert _old_producer_calls(source) == []


def test_a_source_the_guard_cannot_parse_fails_it() -> None:
    """AD-1270 A3: a file that may hold a producer and does not parse fails T2 instead of being skipped."""
    with pytest.raises(SyntaxError):
        _old_producer_calls('rt.emit_event("red_alert", {}\n')


def test_the_tree_scan_decodes_each_file_as_the_importer_does(tmp_path: Path) -> None:
    """AD-1270 A4 (review B r3 G2, G5): T2's own scan reads a BOM file and a PEP 263 file as Python does."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "bom_markers.py").write_bytes(b'\xef\xbb\xbfMARKERS = ("emit_event", "red_alert")\n')
    (tmp_path / "latin1.py").write_bytes(b"# -*- coding: latin-1 -*-\nLABEL = '\xe9'\n")
    (tmp_path / "pkg" / "bom_producer.py").write_bytes(b'\xef\xbb\xbfrt.emit_event("red_alert", {})\n')
    assert _scan_tree(tmp_path) == {"pkg/bom_producer.py": [(1, "red_alert")]}
```

**Pair A4-8 (`DECISIONS.md`).** SEARCH:
```
A guard test (T2) fails when a producer lands in a form it can see: an `EventType` member with an old name, or a call it finds by parsing `src/probos`, either a `set_alert_condition` call or an `emit_event*` call whose event (the first positional argument, or the `event`, `event_type` or `name` keyword) is a string literal equal to an old name. Comments, docstrings and longer names such as `red_alert_resolved` do not count. It does not resolve an emitter under another name, a call through `getattr`, or a name held in a variable, written as an f-string or split across literals (#1324 register R11). Mapping a producer is one line.
```
REPLACE:
```
A guard test (T2) fails when a producer lands in a form it can see: an `EventType` member with an old name, or a call it finds by parsing `src/probos` (each file decoded as Python decodes it), either a `set_alert_condition` call or an `emit_event*` call whose first positional argument is a string literal equal to an old name. Comments, docstrings, keyword arguments (the forwarders' keywords are payload) and longer names such as `red_alert_resolved` do not count. A file is parsed only if its text contains `set_alert_condition`, or `emit_event` and an old name whole, so a name split across literals or escaped, or a callee spelled so that Python normalises it to one of those names, is found only when the file's text passes that filter. It does not resolve an event passed by keyword, an emitter under another name, a call through `getattr`, or a name held in a variable or written as an f-string (#1324 register R11). Mapping a producer is one line.
```

Then regenerate the ledger as in A3. Predicted counts: the triggers file has 72 cases (65 + 7), the census baseline is 667 passed, and the focused union is 1,051 (1,044 + 7).

### 7.11 The split (A5)

One commit on `6cc1a1a3`, applied by tool rather than by text pairs. (1) `tests/test_ad1270_night_orders_triggers.py`: take the file as it is at `5f4b57ed`, then apply the reverse of pair A2-1. `git diff 5f4b57ed -- tests/test_ad1270_night_orders_triggers.py` must show exactly that hunk and the deleted docstring line of T2 (A5.1, round 5 F1), and `git diff 82eac026 -- tests/test_ad1270_night_orders_triggers.py` exactly A2's B5, B4 and B1 hunks and that deletion. `re` is imported again; `ast` and `tokenize` are not. (2) Pair A5-2 (`DECISIONS.md`) replaces the sentence of A4-8's REPLACE with:

> A guard test (T2) fails if an `EventType` value is one of the four old names (`trust_change`, `alert_condition_change`, `security_alert`, `red_alert`), or if the text of any `*.py` file under the `probos` package directory matches `\.set_alert_condition\(` or `emit_event\w*\(\s*["']security_alert`. It matches text, not calls, so it misses some producers and can fail on text that is not one; its limits are #1324 register R11, and it is a backstop, not a guarantee. Mapping a producer is one line.

(3) Regenerate the ledger as in A3, and stage what it rewrites. No file under `src/`, no other test and no PROGRESS line changes.

T2 after the split (round 1's, byte for byte, except that A5.1 deletes its docstring, a false claim, round 5 F1):

```python
def test_the_inert_triggers_still_have_no_producer() -> None:
    values = {m.value for m in EventType}
    assert values.isdisjoint({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    assert [p for p, t in texts.items() if re.search(r"\.set_alert_condition\(", t)] == []
    assert [p for p, t in texts.items() if re.search(r"""emit_event\w*\(\s*["']security_alert""", t)] == []
```

Before the commit, every factual statement in the sentence above, R11 and R13 is run as a probe with a positive and a negative control, using T2's regexes copied literally from the restored file (probes P0 to P9 of the A5 decision record), and saved with the session evidence.

## 8. Tracking (M3's commit)

`PROGRESS.md`. Re-anchor on S6's merge; the paragraph goes first.
**Pair U2 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 Night Orders item -- Night Orders escalation, wired.** A runtime event matching an active Night Orders trigger now pages the Captain: an ALERT bridge alert posted to the ship channel with an `action_required` notification, built by `BridgeAlertService.check_night_orders_escalation` (deduplicated per trigger and build or agent; the Captain can dismiss or mute it, AD-580) and delivered by `WardRoomRouter.deliver_bridge_alert`. The hook used to call a `BridgeAlertService.add_alert` that does not exist, so a real build failure under Night Orders raised out of `_emit_event` before durable offer and dispatch and the event was lost (found by BF-897's review, #1559); the hook is now log-and-degrade and the event always reaches its durable row, its NATS publish and its listeners. Triggers are mapped only where something emits: `build_failure` (a refused request still escalates nothing, BF-897) and `trust_drop`, from `trust_update`, once as an agent's score crosses below the conn floor (the old `trust_change` key had no producer). `red_alert` and `security_alert` have no producer on this build; Night Orders status, `/night-orders` and a log line say so (`inert_triggers`). No schema, config field, event type or route. New: `tests/test_ad1270_night_orders_triggers.py`, `tests/test_ad1270_night_orders_delivery.py`. The contract is `prompts/ad-1270-night-orders-escalation.md`.

```

`DECISIONS.md`. Re-anchored by the orchestrator (2026-10-27): the file's recent entries are appended in date order after the latest one (AD-1341 S6) and ahead of the older newest-first block, so this entry goes there, before the heading of the entry that follows S6's, and not at the top of the Era V section as the Architect's draft had it.

**Pair U3 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- Night Orders triggers are mapped only where a producer exists; the rest are reported as inert (2026-10-2X)

**Decision.** `watch_rotation.NIGHT_ORDER_TRIGGER_EVENTS` maps `build_failure` and `trust_update` (to `trust_drop`, on the crossing below the conn floor) only. `red_alert` (nothing calls `OntologyService.set_alert_condition`) and `security_alert` (no emitter; AD-455's monitor reports nothing in v1) remain valid names in the templates and are reported in `NightOrdersManager.get_status()["inert_triggers"]`. **Why.** A trigger with no producer is a promise to wake the Captain that cannot be kept; inventing producers is new capability under the pause. A guard test fails when a producer lands, so mapping it is one line. **Rejected.** Dropping the names from the templates (it loses the Captain's stated intent, and the names become live once a producer exists). Paging on every trust update below the floor (it would page repeatedly).

### Just culture for trust scoring: a design note for the next owner of earned agency (2026-10-17, recorded 2026-10-2X; #1569 comment 1)

- *Scope.* A design note; nothing under `src/` changes. Recorded at the Captain's request ("record this for whoever next touches earned agency or trust scoring") from the lessons-learned amendment to AD-1341 (#1569, first comment, 2026-10-17); follow-up #1690, entry (d).
- *The note (Captain).* Naval safety investigations are deliberately non-punitive and privileged, so that people report honestly. For ProbOS, an agent's self-reported error should cost little trust, or earn credit for candour; an error discovered after concealment should cost much more. Otherwise the trust model trains agents to hide mistakes, the Darwin Gödel Machine failure mode (`docs/research/darwin-godel-machine-absorption.md`).
- *Constraints for the owner (Architect).* Trust stays raw `(alpha, beta)`. Whether a report was made before discovery must come from a service record (who reported first, and when), never from the agent's own claim; otherwise candour credit becomes a new reward to game.
- *Not decided.* The weights, and whether a self-report is neutral or a credit.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): tick the Night Orders item with the commit and receipt.

## 9. What this does NOT change

- No producer for `red_alert` or `security_alert`, and no alert-condition writer (R1).
- The `ConnManager` escalation list (`conn.py:54-56`, `:192-202`) and the work-item templates' `escalation_triggers` metadata (`workforce.py:804,822,840`), which do not use this map (R2).
- `deliver_bridge_alert`, the Ward Room, notifications, AD-580 suppression semantics.
- `_emit_event`'s order (the hook still comes first), durable routing (AD-1195), NATS.
- `TrustUpdateEvent` (still never built; the producer emits the string form).
- No config field, event type, route, HXI view or schema.

## 10. Mutation rows (30 rows in this slice after A5; the 21 H rows A4 left, after retiring H-9, H-11 and H-16, are slice 1b's drafted rows and are not run here; one campaign on the assembled tree after an unmutated baseline of both new files passes)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| W-1 | M1 | `watch_rotation.py` | `if trigger == "build_failure" and data.get("not_executed") is True:` | `if trigger == "build_failure" and data.get("not_executed"):` | `test_build_failure_raises_unless_the_request_ran_nothing[string-true]`, `test_build_failure_raises_unless_the_request_ran_nothing[int-one]` |
| W-2 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (new < trust_floor):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[already-below]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[floor-hit]`, `test_a_trust_crossing_pages_once` (A1: the stay-below update now matches, so `call_count == 1` sees 2) |
| W-3 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (old > trust_floor > new):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[from-floor]` |
| W-4 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (old >= trust_floor >= new):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[lands-on-floor]` |
| W-5 | M1 | `watch_rotation.py` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))` | `return isinstance(value, (int, float)) and (isinstance(value, int) or math.isfinite(value))` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[bool]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[new-bool]` |
| W-6 | M1 | `watch_rotation.py` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))` | `return isinstance(value, (int, float)) and not isinstance(value, bool)` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[inf]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[new-neg-inf]` |
| W-7 | M1 | `watch_rotation.py` | `"trust_update": "trust_drop",` | `"trust_change": "trust_drop",` | `test_every_mapped_event_has_a_production_producer`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[crosses]` |
| W-8 | M1 | `watch_rotation.py` | `"inert_triggers": sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS),` | `"inert_triggers": [],` | `test_status_names_the_triggers_that_can_never_fire` |
| W-9 | M1 | `watch_rotation.py` | `if inert:` | `if False:` | `test_a_custom_trigger_with_no_producer_is_reported_and_logged` |
| W-10 | M1 | `watch_rotation.py` | `if not (_is_score(old) and _is_score(new)):` | `if False:` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[str]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[missing]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[bool]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[inf]` |
| C-1 | M1 | `commands_autonomous.py` | `if status["inert_triggers"]:` | `if False:` | `test_the_console_says_which_triggers_never_fire` |
| C-2 | M1 | `commands_autonomous.py` | `inert = status["inert_triggers"] if status["active"] else []` | `inert = []` | `test_the_console_says_which_triggers_never_fire` |
| B-1 | M2 | `bridge_alerts.py` | `if not self._should_emit(key):  # AD-580: cooldown, dismiss, resolve and mute apply` | `if False:` | `test_the_alert_is_deduplicated_per_subject_and_suppressible`, `test_a_trust_crossing_pages_once` (A1: the second crossing inside the cooldown is no longer declined, so a delivery is scheduled) |
| B-2 | M2 | `bridge_alerts.py` | `key = f"night_orders:{trigger}:{subject}" if subject else f"night_orders:{trigger}"` | `key = f"night_orders:{trigger}"` | `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-3 | M2 | `bridge_alerts.py` | `id=str(uuid.uuid4()), severity=AlertSeverity.ALERT, source="night_orders",` | `id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY, source="night_orders",` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-4 | M2 | `bridge_alerts.py` | `message = str(details.get("message") or details.get("error") or "no detail")[:_NIGHT_ORDERS_DETAIL_MAX]` | `message = str(details.get("message") or details.get("error") or "no detail")` | `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-5 | M2 | `bridge_alerts.py` | `related_agent_id=(subject or None) if trigger == "trust_drop" else None,` | `related_agent_id=None,` | `test_a_trust_drop_alert_names_the_agent_and_its_scores` |
| R-1 | M2 | `runtime.py` | `except Exception:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch` | `except ZeroDivisionError:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch` | `test_an_escalation_that_raises_never_costs_the_event_its_dispatch`, `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent` |
| R-2 | M2 | `runtime.py` | `if trigger is None or not mgr.check_escalation(trigger):` | `if trigger is None:` | `test_a_refused_build_or_an_unlisted_trigger_pages_nobody` |
| R-3 | M2 | `runtime.py` | `loop = asyncio.get_running_loop()  # before the alert is built: outside a running loop no alert is built, so no cooldown is spent` | `loop = None` | `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent`, `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched` |
| R-4 | M2 | `runtime.py` | `tasks.add(task)` | `pass` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_a_trust_crossing_pages_once` |
| R-5 | M2 | `runtime.py` | `if not alerts or not router:` | `if not alerts:` | `test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged[router]` |
| R-6 | M2 | `runtime.py` | `conn.check_escalation(trigger, details)` | `pass` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_an_unmarked_build_failure_still_escalates` (BF-897's file), `test_a_conn_log_that_raises_still_pages_the_captain` (A2: with the call gone, nothing is logged) |
| R-7 | M2 | `runtime.py` | `if alert is None:` | `if False:` | `test_a_trust_crossing_pages_once` (A1: the second crossing inside the cooldown reaches this line with `None`; under the mutant a `deliver_bridge_alert(None)` task is scheduled, so the unfinished-task assertion fails) |
| R-8 | M2 | `runtime.py` | `trigger = night_order_trigger(event_type, details, trust_floor=TRUST_FLOOR_CONN)` | `trigger = night_order_trigger(event_type, details, trust_floor=0.0)` | `test_a_trust_crossing_pages_once` |
| W-11 | M1 | `watch_rotation.py` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or math.isfinite(value))` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[huge-int]` (A2, B4) |
| W-12 | M1 | `watch_rotation.py` | `if not (_is_score(old) and _is_score(new)):` | `if not _is_score(old):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[new-bool]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[new-neg-inf]` (A2, B5) |
| C-3 | M1 | `commands_autonomous.py` | `inert = status["inert_triggers"] if status["active"] else []` | `inert = status["inert_triggers"]` | `test_a_template_order_that_is_already_expired_does_not_break_the_console` (A2, B1) |
| R-10 | M2 | `runtime.py` | `except Exception:  # AD-1270 A2 (#1324): ConnManager's log is bookkeeping; its failure must not cost the Captain the page` | `except ZeroDivisionError:  # AD-1270 A2 (#1324): ConnManager's log is bookkeeping; its failure must not cost the Captain the page` | `test_a_conn_log_that_raises_still_pages_the_captain` (A2, review A F1) |
| R-9 | M2 | `runtime.py` | `if not mgr or not mgr.active:` | `if not mgr:` | none: **equivalent for paging and status, not for logging** (A2 qualification, both round-1 reviewers). With an inactive manager the mutant calls the rule. An input that makes the rule raise is then logged once under the mutant and not at all on the candidate. After A2's `_is_score` fix the only such input is a truthy `details` that is not a mapping. Nothing pages either way. Recorded, no test. The original note follows: **equivalent mutant**. An inactive `NightOrdersManager` already returns False from `check_escalation` (`watch_rotation.py:419-423`, re-reading the idempotent `active` property, `:308-314`), so the mutant only adds a call to the pure `night_order_trigger`. It is observable only with a manager whose `active` is false while `check_escalation` is true, which the production class cannot be. The census runs it on all files and reports it survived; record it as equivalent, with no test |
| H-1 | A3 | `test_ad1270_night_orders_triggers.py` | `emits_old = "emit_event" in source and any(name in source for name in _OLD_EVENT_NAMES)` | `emits_old = "emit_event" in source` | `test_old_producer_calls_ignores_what_is_not_a_producer[unparsable-without-old-name]` (now parsed, so it raises `SyntaxError`) |
| H-2 | A3 | `test_ad1270_night_orders_triggers.py` | `if not emits_old and "set_alert_condition" not in source:` | `if not emits_old:` | `test_old_producer_calls_flags_a_literal_producer[set-alert]`, `test_old_producer_calls_flags_a_literal_producer[set-alert-space]` |
| H-3 | A3 | `test_ad1270_night_orders_triggers.py` | `if not emits_old and "set_alert_condition" not in source:` | `if False:` | `test_old_producer_calls_ignores_what_is_not_a_producer[unparsable-without-old-name]`, `test_old_producer_calls_ignores_what_is_not_a_producer[unparsable-unrelated]` |
| H-4 | A3 | `test_ad1270_night_orders_triggers.py` | `callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""` | `callee = func.attr if isinstance(func, ast.Attribute) else ""` | `test_old_producer_calls_flags_a_literal_producer[bare-name]` |
| H-5 | A3 | `test_ad1270_night_orders_triggers.py` | `if callee == "set_alert_condition":` | `if False:` | `test_old_producer_calls_flags_a_literal_producer[set-alert]`, `test_old_producer_calls_flags_a_literal_producer[set-alert-space]` |
| H-6 | A3 | `test_ad1270_night_orders_triggers.py` | `hits.append((node.lineno, callee))` | `pass` | `test_old_producer_calls_flags_a_literal_producer[set-alert]`, `test_old_producer_calls_flags_a_literal_producer[set-alert-space]` |
| H-7 | A3 | `test_ad1270_night_orders_triggers.py` | `if not callee.lstrip("_").startswith("emit_event"):` | `if not callee.startswith("emit_event"):` | `test_old_producer_calls_flags_a_literal_producer[suffixed-callee]` (A4: the callee is `_emit_event_fn`; the keyword fixtures that killed it are now unresolved forms) |
| H-8 | A3 | `test_ad1270_night_orders_triggers.py` | `if not callee.lstrip("_").startswith("emit_event"):` | `if False:` | `test_old_producer_calls_ignores_what_is_not_a_producer[other-callee]`, `test_old_producer_calls_does_not_resolve_these_forms[alias]`, `test_old_producer_calls_does_not_resolve_these_forms[getattr]` |
| H-10 | A3, A4 | `test_ad1270_night_orders_triggers.py` | `for arg in node.args[:1]:` | `for arg in node.args:` | `test_old_producer_calls_ignores_what_is_not_a_producer[second-positional]` |
| H-12 | A3 | `test_ad1270_night_orders_triggers.py` | `if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:` | `if isinstance(arg, ast.Constant) and str(arg.value).startswith(tuple(_OLD_EVENT_NAMES)):` | `test_old_producer_calls_ignores_what_is_not_a_producer[longer-name]`, `test_old_producer_calls_ignores_what_is_not_a_producer[longer-name-trust]` |
| H-13 | A3 | `test_ad1270_night_orders_triggers.py` | `if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:` | `if arg.value in _OLD_EVENT_NAMES:` | `test_old_producer_calls_does_not_resolve_these_forms[variable]`, `test_old_producer_calls_does_not_resolve_these_forms[f-string]` (a `Name` or `JoinedStr` has no `value`, so the mutant raises `AttributeError`) |
| H-14 | A3 | `test_ad1270_night_orders_triggers.py` | `hits.append((node.lineno, arg.value))` | `pass` | `test_old_producer_calls_flags_a_literal_producer[positional]` |
| H-15 | A3 | `test_ad1270_night_orders_triggers.py` | `return sorted(hits)` | `return hits` | `test_old_producer_calls_flags_a_literal_producer[two-calls]` (`ast.walk` is breadth-first, so the nested line-1 call is found after the line-2 call) |
| H-17 | A3 | `test_ad1270_night_orders_triggers.py` | `_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})` | `_OLD_EVENT_NAMES = frozenset({"trust_change", "security_alert", "red_alert"})` | `test_old_producer_calls_flags_a_literal_producer[suffixed-callee]` (A4: the only flagged case naming `alert_condition_change`) |
| H-18 | A4 | `test_ad1270_night_orders_triggers.py` | `for arg in node.args[:1]:` | `for arg in node.args[:1] + [kw.value for kw in node.keywords]:` | `test_old_producer_calls_ignores_what_is_not_a_producer[payload-event-type]`, `test_old_producer_calls_ignores_what_is_not_a_producer[payload-keyword-bound]`, `test_old_producer_calls_does_not_resolve_these_forms[event-type-kw]` (G1: a keyword scan reads payload as the event) |
| H-19 | A4 | `test_ad1270_night_orders_triggers.py` | `if callee == "set_alert_condition":` | `if isinstance(func, ast.Attribute) and callee == "set_alert_condition":` | `test_old_producer_calls_flags_a_literal_producer[set-alert-bare]` (G5) |
| H-20 | A4 | `test_ad1270_night_orders_triggers.py` | `if not callee.lstrip("_").startswith("emit_event"):` | `if callee.lstrip("_") != "emit_event":` | `test_old_producer_calls_flags_a_literal_producer[suffixed-callee]` (G5) |
| H-21 | A4 | `test_ad1270_night_orders_triggers.py` | `with tokenize.open(path) as handle:` | `with open(path, encoding="utf-8") as handle:` | `test_the_tree_scan_decodes_each_file_as_the_importer_does` (G2: the BOM file raises `SyntaxError`; the latin-1 file raises `UnicodeDecodeError`) |
| H-22 | A4 | `test_ad1270_night_orders_triggers.py` | `if hits:` | `if True:` | `test_the_tree_scan_decodes_each_file_as_the_importer_does` |
| H-23 | A4 | `test_ad1270_night_orders_triggers.py` | `found[path.relative_to(root).as_posix()] = hits` | `found[path.name] = hits` | `test_the_tree_scan_decodes_each_file_as_the_importer_does` |
| H-24 | A4 | `test_ad1270_night_orders_triggers.py` | `return found` | `return {}` | `test_the_tree_scan_decodes_each_file_as_the_importer_does` |

Each line occurs once in its file after §7 and §7.9. Lines with no row, and why: the docstrings; `_score_text`'s `"?"` branch (display only); the `"nothing"` arm of `Escalates on` (display only). In `_old_producer_calls` (A3), these have no row: the prefilter's `return []`, whose removal H-3's killers catch; `hits: list[tuple[int, str]] = []`; the `for node in ast.walk(ast.parse(source)):` line; `if not isinstance(node, ast.Call):`; `func = node.func`; and the two `continue` lines. Any whole-line mutant of these raises or empties every result, so every flagged case kills it. A4: three lines of `_scan_tree` have no row: `found: dict[str, list[tuple[int, str]]] = {}`, `for path in root.rglob("*.py"):` and `hits = _old_producer_calls(handle.read())`. A whole-line mutant of any of them raises or empties the scan, which the tree test's expected producer catches. T2's `assert _scan_tree(_SRC) == {}` has no row: on a producer-free tree any weakening of it passes (R11, the G5 residue).

Killed-by cells are census-ready. They name full pytest function names in code spans, with a single parametrised case written `name[id]`. A cell names no function only for R-9, the equivalent mutant. Census of record: orchestrator, 2026-10-27, on `427546b8`: 24 killed, 2 survived (R-7, R-9), baseline 627 passed. A1 changes only D2, so after A1 rerun the unmutated baseline and the rows that claim D2: W-2, B-1, R-4, R-7, R-8. Expected: 25 killed, R-9 survived and recorded as equivalent. Measured (census d, on A1): 25 killed, R-9 survived. **A2:** three source files change, so no row's overlay matches the census of record. Rerun the whole campaign of 30 rows on the repaired tree. Predicted: baseline 633 passed, 29 killed, R-9 survived (qualified above). Measured on `5f4b57ed`: 29 of 30 killed, R-9 survived. **A3:** only `tests/test_ad1270_night_orders_triggers.py` changes. No source file a W, C, B or R row mutates changes, and none of their named killers changes. The `5f4b57ed` rerun therefore stays the campaign of record for those 30 rows. Run the unmutated baseline and the 17 H rows on the repaired tree. The H rows mutate the test file's own helper, so the File cell is under `tests/`. Predicted: baseline 660 passed and 17 H rows killed, so 46 of 47 rows are killed overall, with R-9 survived (equivalent). Measured (census g, on `698950a9`): baseline 660 passed, 46 killed, R-9 survived. **A4:** again only `tests/test_ad1270_night_orders_triggers.py` changes, so the `5f4b57ed` campaign stays the campaign of record for the 30 W, C, B and R rows. Run the unmutated baseline and all 21 H rows on the repaired tree. Predicted: baseline 667 passed and 21 H rows killed, so 50 of 51 rows are killed, with R-9 survived (equivalent). Measured on `6cc1a1a3` (orchestrator): baseline 667, 50 killed, R-9 survived. **A5 (the split):** the H rows mutate lines the restored file does not contain, so they leave this slice's census and stay as slice 1b's drafted rows (R13). The restored triggers file differs from `5f4b57ed`'s only in T2's last assertion and (A5.1) T2's deleted docstring. No row mutates those lines, no Killed-by cell names T2, and no source file changes, so by the rule above `5f4b57ed`'s campaign (29 of 30 killed, R-9 equivalent) remains the campaign of record. The orchestrator reruns the 30 rows on the restored tree anyway and records the baseline it measures (expected 633). Measured on `56811270` (orchestrator): baseline 633, 29 of 30 killed, R-9 survived. T2 has no row: on a producer-free tree any weakening of it passes (R11).

## 11. Verified Against Codebase (2026-10-27, on `a2390998`)

```
Grep "_check_night_order_escalation|add_alert|deliver_bridge_alert" src
  runtime.py:1949 (call), :2137 (def), :2180 (add_alert, its only occurrence)
  ward_room_router.py:1181  async def deliver_bridge_alert(self, alert: Any) -> None:
  bridge_alerts.py:51       objects that the runtime delivers via _deliver_bridge_alert().
Read runtime.py:1930-1975, 1977-2016, 2029-2069, 2137-2186, 3886-3944, 1432-1438, 1512-1532
Grep "^logger = " runtime.py -> :229; watch_rotation.py:22; bridge_alerts.py:21
Grep "TRUST_FLOOR_CONN" runtime.py -> :111 import; config.py:220 TRUST_FLOOR_CONN = 0.6
Grep '"trust_update"' src -> consensus/trust.py:492, :534; payload Read :480-541, :655-678
Grep "BUILD_FAILURE" src -> routers/build.py:85,366,410,482,489; events.py:37
Read bridge_alerts.py:1-120 (AlertSeverity, BridgeAlert fields, _should_emit, _record), :310-349 (check_trust_change), :159 mute_alert
Read ward_room_router.py:43-93 (constructor: config.ward_room read at :79), :1181-1227
Read watch_rotation.py:14-20, :178-366
Read commands_autonomous.py:118-184
Read tests/test_autonomous_operations.py:18-24, :405-439, :468-483
Read tests/test_bf897_build_pipeline_scale_and_checkout.py:898-966
Read tests/test_ad1195_durable_event_seam.py:66-82; Grep tests/test_ad637d_system_events_nats.py:25,39,344; tests/test_ad680_public_runtime_api.py:76
Read tests/test_commands_autonomous.py:1-34 (mocks return {"active": False} only)
Read docs/development/architecture-baseline.yaml:331-339; scripts/check_architecture_principles.py:80-113, :187-188, :930-944
Read startup/finalize.py:4210-4224
```

## Absence Verified (2026-10-27)

| ID | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No `add_alert` method; no `_deliver_bridge_alert` on the runtime | Grep `add_alert\|deliver_bridge_alert` in `src` | only the call at `runtime.py:2180`; `deliver_bridge_alert` methods are only on `WardRoomRouter`; `_deliver_bridge_alert_fn` in `dream_adapter.py` is a parameter | yes |
| AV2 | No producer for `trust_change`, `alert_condition_change`, `security_alert` | Grep `"(trust_change\|alert_condition_change\|security_alert\|build_failure)"` in `src` | the map, lists and scorers only; emitters only for `build_failure` | yes |
| AV3 | Nothing changes the alert condition; no security_alert EventType | Grep `set_alert_condition\(` in `src`; Grep `^    [A-Z_]*(ALERT\|TRUST\|SECURITY\|CONDITION)[A-Z_]* = ` in `events.py` | the def only; members `TRUST_UPDATE, EXOGENOUS_ALERT, BRIDGE_ALERT, TRUST_CASCADE_WARNING, TRUST_INTEGRITY_VIOLATION, SECURITY_INPUT_REJECTED, TIERED_TRUST_INITIALIZED` | yes |
| AV4 | No test source-scans the replaced lines | Grep `trigger_map\|Night Orders escalation\|_deliver_bridge_alert\(\)\|inert_triggers\|night_order_trigger` in `tests` | only comments/docstrings in `test_ad637d_system_events_nats.py:38,233` | yes |
| AV5 | No HXI consumer of Night Orders status keys | Grep `escalation_triggers\|night.orders` in `ui/src` | none | yes |
| AV6 | Night Orders is not a P0 seam | Grep `(?i)night\|bridge_alert\|_emit_event\|escalation` in `docs/development/seams/p0-manifest.yaml` | none | yes |

## Not verified (the orchestrator verifies by running)

1. `SystemConfig()` constructs with no arguments in the test (the zero-config standing rule; not run).
2. `MagicMock(spec=BridgeAlertService)` exposes `check_night_orders_escalation` after 7.5 (true for `spec=` of a class; not run).
3. The focused lists' measured counts.

## 12. Deterministic gate checks, resolved up front

- `check_architecture_principles.py --check`: the new `create_task` result is stored, not a bare expression, so no `unowned-task` row. `BridgeAlertService`'s srp-size row stores triggers, not magnitudes, so it is unchanged. `watch_rotation` is unranked. No new top-level module.
- No config field, so neither `check_config_readers.py` nor `config-reference.md` changes.

## 13. Prior Art and Blind Spots

- **External prior art:** skipped. This is ProbOS-specific plumbing; observer isolation in event dispatch is the repo's own BF-639 pattern, reused here. `docs/research/reference-projects.md` was not consulted, because no external search was made.
- **Internal:** BF-639 (listener isolation), BF-708 (borrowed-method hosts), BF-897 (`not_executed`), AD-580 (suppression), AD-1195 (durable offer). All absorbed.
- **Blind spots found and handled:** the real trust event name (`trust_update`, `old_score`/`new_score`); repeated pages below the floor (D3); alerts built outside a running loop using up their cooldown (D5; a failed scheduling still does, R9); custom typo triggers (reported as inert); a dedup key built from unbounded payload (capped at 64 and 500 characters).
- **Blind spots recorded, not fixed:** R1 to R6; after A2, R9 to R12.

## 14. Diff Reviewer: properties to verify

**M1:**
1. `night_order_trigger` returns `build_failure` for `build_failure` unless `not_executed is True`, and `trust_drop` for `trust_update` only when finite non-bool numeric scores satisfy `old >= floor > new`. Everything else returns `None`.
2. Every key of the map has a production producer; no template name is missing from wired ∪ {`red_alert`, `security_alert`}.
3. `get_status()` of an active order includes `inert_triggers` = the sorted active triggers minus the wired set; an inactive order is still exactly `{"active": False}`.
4. The two rewritten tests in `test_autonomous_operations.py` call production code and carry their inline reason.

**M2:**
5. `_check_night_order_escalation` raises nothing for any exception from Night Orders, `ConnManager`, the service, the loop lookup or task creation; `_emit_event` still offers the event to `durable_events` and dispatches it.
6. A match under an active order with a service, a router and a running loop schedules exactly one `deliver_bridge_alert` task, held in `_event_listener_tasks` until done. A match the service declines (inside the cooldown, or suppressed under AD-580) schedules none: `deliver_bridge_alert` is never handed `None`.
7. Outside a running loop, the service is not called, so the cooldown is unspent.
8. The alert is ALERT severity, keyed `night_orders:{trigger}[:{subject}]`, subject ≤ 64 characters, message ≤ 500, and passes `_should_emit` (cooldown and AD-580 suppression).
9. BF-897's tests pass unchanged: the refusal is not escalated; an unmarked failure calls `conn_manager.check_escalation` once.
10. No other `_emit_event` behaviour, order or signature changed.

**A2 (round 2, the delta only):**
11. `/night-orders <template> <ttl>` never indexes `inert_triggers` on an inactive status (`shell.py:345-350` would otherwise print "Command error"). The output for an active order is unchanged, and an inactive `get_status()` is still exactly `{"active": False}`.
12. A raising `ConnManager.check_escalation` is logged once under its own message, and the alert is still built and delivered. Any other raise in the hook still reaches the outer handler. `_emit_event` still offers the event to `durable_events` and dispatches it.
13. `_is_score` accepts every non-bool `int` (compared exactly with the float floor) and only finite floats. No numeric or bool score makes `night_order_trigger` raise.
14. No shipped text claims persistence. The hook's docstring, PROGRESS and DECISIONS say only that a hook failure no longer stops the durable offer, the NATS publish or dispatch.
15. T2 rejects a literal `emit_event*` call naming any of the four old names, and nothing claims it catches an aliased emitter. *(A3: superseded by 16 to 19. A5: superseded by 24, since A2-1 is reverted.)*

**A3 (round 3, the delta only; a shared contract at the source-scan gate):**
16. `_old_producer_calls` flags exactly two kinds of call. The first: a callee (`Name.id` or `Attribute.attr`) that, with leading underscores stripped, starts with `emit_event`, and whose first positional argument, or `event`, `event_type` or `name` keyword, is a `Constant` **equal** to one of the four old names. The second: any call whose callee is `set_alert_condition`. Nothing in a comment, docstring or other string is flagged, and neither is a longer name, a second positional or another keyword. *(A4: the keyword clause is superseded by 20.)*
17. A source the prefilter admits that does not parse raises `SyntaxError`; a source it excludes is not parsed and returns `[]`. The prefilter can exclude a flaggable call only when the name does not appear whole in the text (R11 d). *(A4: superseded by 22; a normalised callee is excluded too, R11 h.)*
18. On the real tree, T2 passes and the prefilter parses exactly 4 files (`runtime.py`, `workforce.py`, `watch_rotation.py`, `ontology/service.py`). The `EventType` check stays. `re` is no longer imported. No other test changed. The delivery file and every `src` file are unchanged since `5f4b57ed`.
19. The fixture tests discriminate: each H row in §10 is killed by its named case. The DECISIONS sentence claims no more than 16 and 17, and names R11.

**A4 (round 4, the delta only; the source-scan gate). Behaviour A4 did not change is out of scope. A recall gap or a coverage gap is recorded in R11, not repaired.**
20. `_old_producer_calls` reads no keyword argument. The event is the first positional argument only, so `self._emit_event("build_failure", event_type="red_alert")` and its keyword-bound twin return `[]`. On every source, the hits are a subset of A3's. Every `emit_event*` definition in `src/probos` except `_emit_event_local` takes the event first, and no call there binds it by keyword (§7.10 enumerations).
21. T2 is `assert _scan_tree(_SRC) == {}`. `_scan_tree` decodes with `tokenize.open`, so a valid UTF-8-BOM or PEP 263 module never fails it, and a genuine syntax error in an admitted file still raises.
22. The helper docstring, the DECISIONS sentence and R11 describe the prefilter as conditional. A split or escaped name, or an NFKC-normalised callee, is found exactly when the file's text passes the filter (`[split-literal-admitted]` against `[split-literal]` and `[normalised-callee]`). The keyword forms are recorded (R11 g), not claimed.
23. Since `698950a9`, only the triggers test file, the DECISIONS sentence and the ledger capture line changed.

**A5 (the split's one review round; the delta since `5f4b57ed`). Items 16 to 23 describe the helper, which is not built in this slice; they are slice 1b's drafted properties (R13). Behaviour that rounds 1 and 2 reviewed is out of scope. A recall gap is recorded in R11 or R13, and a false statement is repaired by deleting it.**
24. T2 is round 1's (`82eac026`, quoted in §7.11) with its docstring deleted (A5.1, round 5 F1): three assertions, over `p.read_text(encoding="utf-8")` for every `p` in `_SRC.rglob("*.py")`. Check it by running its set and its two regexes. On today's tree each finds nothing (T2 passes). `svc.set_alert_condition("RED")` and `rt.emit_event("security_alert", {})` match, so the guard bites. `rt.emit_event("red_alert", {})` does not (B3, R11 a). The DECISIONS sentence and R11 claim nothing that these runs and probes P0 to P9 do not show.
25. The triggers file equals `5f4b57ed`'s except for the reverse of pair A2-1 and T2's deleted docstring (A5.1). It holds 38 cases and imports `re`, but neither `ast` nor `tokenize`. Since `5f4b57ed`, no file under `src/`, no other test and no PROGRESS line has changed. DECISIONS changed only in the T2 sentence, and the ledger files only as `gen_ad_ledger.py` rewrites them.

## 15. Acceptance criteria

- [ ] M1 to M3 built in order, one delegation and one local commit each, staged by explicit path.
- [ ] Each new test file failed on its milestone's base as §6 states (M1 at collection; M2 on every case but D3, the negative case) before the code was written.
- [ ] Each focused gate (§4) passes with `-n 0`; `check_architecture_principles.py --check` passes after M2.
- [ ] M2 has a cross-family review (`gpt-6.1-sol`) against §14, with its findings repaired.
- [ ] The §10 campaign runs once on the assembled tree; every row is killed, or recorded as equivalent (R-9), or returned to the Architect.
- [ ] `tests/test_bf897_build_pipeline_scale_and_checkout.py` passes unloosened.
- [ ] `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass after M3.
- [ ] The orchestrator's single broad gate passes with its receipt.
- [ ] #1324's Night Orders checklist item is ticked with the commit and receipt; the register rows are posted on #1324.
- [ ] A2: the §7.8 tests failed over the candidate's source as §6 predicts (5 cases) before the source pairs were applied. §7.8 is committed. The §10 campaign was rerun (30 rows). Round 2 reviewed the delta against §14 items 11-15.
- [ ] A3 *(A5: built in `698950a9` and reverted by the split; slice 1b's drafted text, not a criterion of this slice)*: §7.9 applied as one commit. The A2-predicate oracle disagreed with the fixtures where §7.9 predicts (10). The triggers file passes (65 cases). The baseline (660) and the 17 H rows were run. Round 3 (reviewer B) reviewed the delta against §14 items 16-19, including the real-tree consumer check. The ledger was regenerated.
- [ ] A4 *(A5: built in `6cc1a1a3`; round 4 NOT READY on F1; reverted by the split; slice 1b's drafted text, not a criterion of this slice)*: §7.10 applied as one commit. The A3 oracle disagrees with the A4 fixtures in exactly the 5 cases §7.10 names. The triggers file passes (72 cases). The baseline (667) and the 21 H rows were run (50 of 51 killed overall, R-9 equivalent). Round 4 (reviewer B) reviewed the delta against §14 items 20-23. The ledger was regenerated.
- [ ] A5: §7.11 applied as one commit. The triggers file equals `5f4b57ed`'s except A2-1's reversed hunk and T2's deleted docstring (A5.1; blob diff saved) and passes (38 cases). Every factual statement in the DECISIONS sentence, R11 and R13 has a saved probe with a positive and a negative control. The 30 non-H rows of §10 were rerun on the restored tree (29 killed, R-9 equivalent) and the baseline recorded. The split's one review round covered the delta against §14 items 24 and 25. The ledger was regenerated, and the PR states that round 4 had no repair round.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R1.** `red_alert` and `security_alert` never fire: nothing writes the alert condition, nothing emits `security_alert`, and AD-455's `TrustIntegrityMonitor.analyze` reports nothing in v1. Owner: whichever slice wires an alert-condition writer or AD-455b. The guard test T2 names the one-line map change.
- **R2.** `ConnManager`'s own escalation list and the work-item templates' `escalation_triggers` metadata still list `red_alert` and `security_alert`. Not read through this map; not checked whether anything reads the work-item metadata.
- **R3.** `BridgeAlertService` (frozen srp debt, owner AD-1270h) gains one cohesive `check_*` method; the baseline row is unchanged.
- **R4.** A delivery task that raises outside `deliver_bridge_alert`'s own guard (in `get_channel_by_type` or `event_log.log`) surfaces as asyncio's "Task exception was never retrieved". *Corrected in A2 (review A):* not every bridge-alert delivery behaves this way. Only the two fire-and-forget callers do (`runtime.py:4794`, `:6871`), and they do not retain their task. Eight other call sites await the delivery (`counselor.py:2283`, `:2609`; `proactive.py:3923`, `:3938`, `:3953`, `:5134`; `ward_room/_helpers.py:32`; `threshold_alerts.py:238`), and `_helpers.py:32` and `proactive.py:3923` catch with `logger.debug`. The hook's task is like the fire-and-forget pair, but it is held in `_event_listener_tasks` until done. P3. Owner: the change that gives `deliver_bridge_alert` callers one error policy.
- **R5.** Delivery tasks in `_event_listener_tasks` are not drained at shutdown; a page raised during shutdown may be lost. Same as BF-639 listener tasks.
- **R6.** A trust score oscillating across the floor pages once per crossing, beyond the 300 s per-agent cooldown.
- **R7.** No AD-1270a exercise receipt: steps 2 and 3 have no producer yet (`platform-maturity-program.md:755-758`). D1 is the crossing evidence until then.
- **R8.** Mutation census (orchestrator, 2026-10-27, on `427546b8`): 24 of 26 killed. Mutation R-7 (`if alert is None:`) survived because D2's second update was not a crossing and never reached the service. Amendment A1 gives D2 a second crossing inside the cooldown and asserts that no delivery is scheduled; R-7 closes when the rerun kills it. Mutation R-9 is equivalent (an inactive manager's `check_escalation` is already False). W-2 and B-1 were killed, but by T3b and D7, not by D2 as first claimed; A1's D2 assertions are predicted to make D2 a second killer of both. *A2:* census d on A1 measured 25 killed, with R-9 survived. Both round-1 reviewers showed R-9 is equivalent for paging and status, but not for logging (§10 row).
- **R9.** (Review A F2; P3; injected-only; not a regression.) If `loop.create_task` fails after `check_night_orders_escalation` has built the alert, the `deliver_bridge_alert` coroutine is never awaited and that alert's 300 s cooldown is spent. Only an injected fault reaches this: the loop was fetched as running one line earlier. Closing it needs a cooldown-release method owned by the service (frozen srp debt, R3) or building the alert after scheduling. Owner: AD-1270h, the `BridgeAlertService` decomposition.
- **R10.** (Review A F3; P3; injected-only.) `tasks.add` runs after the task exists, so a host whose `_event_listener_tasks` is `None` logs a failure and leaves an unretained task. Only a BF-708 borrowed-method host can be in that state; production initialises a set (`runtime.py:1435-1438`). Trigger: the next change to the hook. The fix is to bind `self._event_listener_tasks.add` before the alert is built.
- **R11.** (B3 residue; A2's widening and A3's and A4's parser reverted by A5, the split after round 4; P2; injected-only.) T2 is round 1's guard (`82eac026`). It fails if an `EventType` value is one of the four old names, or if the text of a `*.py` file under the imported `probos` package directory matches `\.set_alert_condition\(` or `emit_event\w*\(\s*["']security_alert`. **Misses:** (a) a literal emission of `red_alert`, `alert_condition_change` or `trust_change` (B3, round 1 review B); (b) `set_alert_condition` called bare, through `getattr`, or with whitespace before the parenthesis; (c) an emission with whitespace before the parenthesis, or whose event is passed by keyword (`event=`, `event_type=`, `name=`), by positional unpacking (`*("security_alert", {})`, round 4 F2) or `**kwargs`, held in a variable, written with an `f`, `b` or `r` prefix, split across literals or escaped; (d) an emitter under another name, or one called through `getattr`; (e) a producer outside the package directory. **False matches** (T2 fails with no producer): the same text in a comment, docstring or string; a longer name beginning `security_alert`; any callee whose text ends in `emit_event` plus word characters, such as `xemit_event(`. **Reading:** each file is read as UTF-8, so a valid module in another declared encoding that holds a non-UTF-8 byte raises `UnicodeDecodeError` and fails T2 (round 1's behaviour; A4's claim to read files as the importer does is withdrawn, round 4 F1). Untracked files in the directory are read too. T2 has no mutation row: on a producer-free tree any weakening of it passes. Every clause has a probe (A5, P2 to P9). Owner: same as R1; the slice that wires an alert-condition writer, or AD-455b, maps the trigger in the same change. Recall by parsing is slice 1b (R13). T2 is a backstop, not a guarantee.
- **R11 as drafted for slice 1b** (A4's text, kept for R13. It is not true of this slice's T2, and its encoding clause is false, round 4 F1): T2 finds a producer in three forms. The first is an `EventType` member with an old value. The other two are calls it finds by parsing `src/probos`, each file decoded as Python decodes it (`_scan_tree`, `_old_producer_calls`): a `set_alert_condition` call, and a call to an `emit_event*` method whose first positional argument is a string literal equal to an old name. A file is parsed only if its text contains `set_alert_condition`, or `emit_event` and an old name whole. It does not resolve: (a) an emitter under another name (`fire = rt.emit_event`, or the forwarders' own `self._emit(name, ...)`); (b) a call through `getattr`; (c) a name held in a variable, passed through `**kwargs`, or written as an f-string, even one with no placeholder; (d) a name split across adjacent literals or written with escapes, found only when the file's text passes the filter above (A4, G3: inside a parsed file the parser joins them); (e) `_emit_event_local(event, type_str)`, which bypasses the Night Orders hook (`runtime.py:1949` against `:1966`, `:1975`), so it is not a producer the map could use; (f) a producer outside `src/probos`; (g) an event passed by keyword (`event=`, `event_type=`, `name=`). A4 reads only the first positional argument, because the forwarders take payload as keywords (`approval_gate.py:169`, `evolution_store.py:1253`, `proposal.py:269`) and A3's keyword scan read payload as the event (G1). No call in `src/probos` binds the event by keyword (enumerated 2026-10-27). (h) A callee spelled with characters Python normalises (NFKC) to `emit_event` or `set_alert_condition`, found only when the file's text passes the filter (G4). `test_old_producer_calls_does_not_resolve_these_forms` pins (a) to (d), (g) and (h) with `[alias]`, `[getattr]`, `[variable]`, `[f-string]`, `[split-literal]`, `[event-type-kw]`, `[event-kw]`, `[name-kw]` and `[normalised-callee]`. `test_old_producer_calls_flags_a_literal_producer[split-literal-admitted]` pins (d)'s admitted half. T2's own assertion line has no mutation row: on a producer-free tree any weakening of it passes, and the scan it calls is pinned by `test_the_tree_scan_decodes_each_file_as_the_importer_does` (G5). If a fixture starts to match, update this row and DECISIONS. Owner: same as R1. The slice that wires an alert-condition writer, or AD-455b, maps the trigger in the same change; T2 is a backstop, not a guarantee.
- **R12.** (Found during A2 verification. It predates AD-1270: `git blame` dates `commands_autonomous.py:155-175` to `5452ff13`, 2026-03-30. Ordinary reach.) The console accepts any float TTL. With `0` or a negative TTL, the console prints "Night Orders set" for an order that is already expired: the Captain believes orders are on and nothing escalates. With `nan`, or a TTL negative enough that `expires_at <= 0`, the order never expires (`watch_rotation.py:288-290`). It is outside AD-1270's diff; a BF is recommended.
- **R13.** (Slice 1b of the Night Orders item: T2's recall, by parsing. STANDARD, test-only, a source-scan gate. Tracked here and as a sub-item of the Night Orders checklist entry on #1324; no new issue, because the wave is past its discovery budget. Ordered after slice 2, with no dependency on it. Slice 2 asks which classes nothing constructs, a different question, so it does not subsume this.) **Drafted text, not a design of record:** A3 and A4 (`698950a9`, `6cc1a1a3`, kept in the branch history), §7.9, §7.10, the §10 H rows, §14 items 16 to 23, and R11 as drafted. **It must address:** round 3's G1 to G5; round 4's F1 (a CR-only module with an unknown coding line after line 2), the two Latin-1 modules with a non-ASCII byte in a first-line comment, and F2 (positional unpacking); the first-positional-only rule, re-enumerated on its base (on this base each of the ten `emit_event*` definitions takes the event first after the receiver, `_emit_event_local` its event dict, and none of the 248 calls binds it by keyword); and B3's other three names; and it must not carry T2's old docstring claim "If this fails, a producer exists now", which is false (a comment-only module fails T2; round 5 F1). **Design constraints:** parse each tracked file's bytes (`ast.parse(path.read_bytes())`, which compiles bytes as `importlib`'s `SourceLoader.source_to_code` does), proved on F1's three modules, a BOM file and a PEP 263 file before any encoding claim is written. No prefilter unless a measurement needs one; if one is kept, state it conditionally, with a fixture for each side. Take the file list from `scripts/check_architecture_principles.py` `_tracked_python_files` (`git ls-files`), but not from `iter_modules`, which skips files it cannot decode or parse; a guard must fail on them. `import_aliases` resolves imports only, not `fire = rt.emit_event`. Every claim in its DECISIONS text gets a probe with positive and negative controls. Owner: this epic.
