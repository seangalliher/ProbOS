# BF-921: the Counselor receives the events it subscribes to (#1636): event-type filters use wire values, no output suppression carries a trust penalty or message, the dead CONDUCT_VIOLATION penalty path is removed and the SPC store is marked inert

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24 (Amendment A1: the order after BF-920, the cascade seam case, the callsign resolution)

**Status:** build-ready. One BF, two milestones (M1 HIGH, M2 STANDARD), batched with BF-922 (#1639): two prompts, one PR, one broad gate. **This prompt builds first in the batch, and the batch lands after BF-920 (#1633)** (section 4). **BF number:** BF-921 (#1636); this contract allocates nothing. **Tier:** M1 **HIGH** (it repairs the shared event-delivery seam `ProbOSRuntime.add_event_listener`, which wakes five listeners that have never received an event; it removes a trust penalty before that penalty can first fire; and it repairs the Counselor's callsign resolution, which lets four handlers' designed crew DMs be sent); M2 STANDARD (removes a handler with no producer; changes one docstring and one log line). The batch is reviewed at HIGH: use the Copilot `Diff Reviewer`. Never lower a tier without the Captain. **Base:** the `origin/main` commit that merges BF-920 (#1633) (its candidate 2 is `bf41e2dd` on `026a682f`); never `cb190f32`. If BF-920 is not merged when the batch starts, do not build: return to the Architect. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Tests:**
- New `tests/test_bf921_counselor_event_delivery.py` (M1, 18 functions; 34 cases with parametrization).
- Updated pins: `tests/test_bf206_confab_feedback.py` (M1: the `TestCounselorFeedback` class, which pinned the warning DM and the trust penalty); `tests/test_ad583_wrong_convergence.py` (M1, A1: `test_counselor_wrong_convergence_extreme_sends_dm`, which pinned the dict-registry lookup); `tests/test_ad489_code_of_conduct.py` (M2: the five tests that drove the removed handler); `tests/test_ad522_spc.py` (M2: one test added).

## 0. Premise: what is present on this tree

| Claim of #1636 (anchors on `4564fbd7`) | On `cb190f32` | Holds |
|---|---|---|
| Emit behind `_rt = getattr(self, '_runtime', None)` / `hasattr(_rt, 'emit_event')`, `cognitive_agent.py:5942-5955` | `cognitive_agent.py:6006-6018` | yes (moved) |
| Counselor handler and penalty, `counselor.py:1738-1746` | handler `counselor.py:1706-1794`, penalty `:1740-1765` | yes (moved) |
| `CONDUCT_VIOLATION` subscribed `counselor.py:709`, handled `:1060`, penalty `:1458-1463`, defined `events.py:93` | same lines; penalty `:1458-1476` | yes |
| SPC `record_observation` at `spc/store.py:38` has no caller; store wired at `startup/finalize.py:3468` | store `:38`; wiring `finalize.py:3519-3536`, called `:4126` | yes (moved) |
| Leading suspect: `_runtime` is `None` at the guard | **refuted**, see section 1 | no |

## 1. Problem (root cause confirmed)

**The emit is not the defect; the subscription is.** `ProbOSRuntime.add_event_listener` builds its filter with `frozenset(str(t) for t in event_types)` (`runtime.py:1706`; `register_live_event_listener` the same at `:1728`). `EventType` is `class EventType(str, Enum)` (`events.py:22`), not a `StrEnum`, so on Python 3.11+ (the venv is 3.12.13, `d:/ProbOS/.venv/pyvenv.cfg`) `str(EventType.CONFABULATION_SUPPRESSED)` is `"EventType.CONFABULATION_SUPPRESSED"`, not `"confabulation_suppressed"` (Python docs, `enum`: `Enum.__str__` "returns the Enum name and member name"; only `ReprEnum`/`StrEnum` use the value). The Counselor passes members (`counselor.py:685-710`), so:
- **NATS mode** (every live session: `AD-637d: SYSTEM_EVENTS 12 listeners wired to NATS` at each boot in `probos.log*`): `_create_nats_event_subscription` subscribes to `system.events.EventType.CONFABULATION_SUPPRESSED` (`runtime.py:1866-1873`), while `_emit_event` publishes to `system.events.confabulation_suppressed` (`runtime.py:1940`).
- **Local mode:** `_emit_event_local` skips the listener because `"confabulation_suppressed" not in type_filter` (`runtime.py:1952`).

So the Counselor has received **none** of its 24 event types in any session, not only this one. Four more listeners pass members and are equally deaf: BF-125 (`finalize.py:5982-5985` on `bf41e2dd`, `GAME_COMPLETED`), AD-532e and AD-534b (`dreaming.py:345-360`), AD-659c (`optimization_counselor.py:115-118`).

**Live evidence (read-only, 2026-10-24, `%LOCALAPPDATA%\ProbOS\data\logs\probos.log` and `.1` to `.5`):** all 67 `probos.cognitive.counselor` lines are the startup line `AD-503: Counselor loaded N persisted profiles`; there are 0 lines of `BF-206: Confabulation suppressed for`, `BF-206: Trust penalty` or `AD-489: Conduct violation handled`. The orchestrator's control ("the Counselor's logger is live") shows the logger works at boot, not that any event handler ever ran: none did. The 1,258 `BF-206: Chain output suppressed` lines show the producer side ran.

**Item 2 (the penalty).** Fixing delivery as-is would start a penalty that has never fired: the handler tells the agent its post "couldn't be verified" and applies a 0.5-weight trust penalty from the second suppression in an hour (`counselor.py:1740-1787`). 949 of the 1,258 suppressions are `quality_gate` (the LLM judge, unmeasured: AD-1350, #1637) and 216 of 309 `confabulation_detected` cases cite real Ward Room ids (BF-922, #1639).

**Item 3.** `CONDUCT_VIOLATION` has no producer (section 12). AD-489 says violations "are assessed by the Counselor (CounselorAgent) or by department Chiefs" (`config/standing_orders/federation.md:180-182`; `prompts/archive/ad-489-federation-code-of-conduct.md:69-81`) and built only the consumer.

**Item 4.** `SPCCalibrationStore.record_observation` has no caller (section 12); the store is built at every boot (`finalize.py:3519-3536`) and its log line says "initialized", not that it is empty.

## 2. Solution overview

- **M1.** One helper, `_event_type_filter`, turns each requested type into its wire value (`EventType` member: `.value`; anything else: `str()`), used by both listener registrations. A failed NATS subscription task is logged instead of discarded. One emitter, `CognitiveAgent._emit_output_suppressed(rejection, observation, *, path)`, replaces the inline guarded emit (BF-922's fallback gate reuses it). The Counselor's suppression handler records only: one INFO line with agent, reason, path and the hourly count; no DM, no trust write. Its event router logs a failing handler at WARNING. The four Counselor handlers that message by callsign (cascade, wrong convergence, echo, observable mismatch) resolve agents through the runtime's `AgentRegistry`, not a dict API it lacks (A1, D2).
- **M2.** The Counselor no longer subscribes to or handles `CONDUCT_VIOLATION` (the member stays in `EventType`). The SPC store's docstring and boot line say it is inert.

## 3. Decisions (for #1636)

**D1, root cause and fix (item 1).** Root cause: section 1. Ranked fixes: (1, chosen) normalize at the one seam, `add_event_listener` and `register_live_event_listener`, so every caller is fixed and no caller can reintroduce it; (2) pass `.value` in the Counselor only: leaves the seam defect and four deaf listeners, and the convergence rule forbids filing them; (3) make `EventType` a `StrEnum`: changes `str()` and `format()` of every member across the codebase and its log lines; out of proportion for a BF. The seam test boots a real `ProbOSRuntime` (`await rt.start()`, as `tests/test_hxi_events.py:101-116` does), takes a crew agent and the Counselor the agent fleet and `finalize` built, and drives the agent's real `_execute_sub_task_chain` with only the chain executor stubbed; the agent's `_runtime` is the one startup set, and the test asserts that.

**D2, waking the dormant listeners.** The seam fix wakes the Counselor's 23 other handlers and the four listeners above. This restores approved designs (AD-495, AD-505, AD-506, BF-125, AD-532e, AD-534b, AD-659c, and the AD-567f and AD-583 handlers below); it weakens no control and needs no Captain decision. Exposure measured in the live logs: 0 `AD-488: Circuit breaker TRIPPED` and 0 `AD-506a: Zone transition` lines, so the handlers with Ward Room posts and mechanical interventions (`_on_circuit_breaker_trip`, `counselor.py:1161-1250`) would not have fired at the observed rate. The only trust writes among the woken handlers are the two this prompt removes (D3, D4). Section 16 counts the first session's handler lines.

*BF-920's three events (A1).* BF-920 (#1633), which lands first (section 4), leaves `SocialVerificationService.check_cascade_risk` as the one emitter of `CASCADE_CONFABULATION_DETECTED` (`social_verification.py:635-645`) and puts it, `WARD_ROOM_ECHO_DETECTED` and `OBSERVABLE_STATE_MISMATCH` (`ward_room/_helpers.py:101-112`, `:153-160`) on the Bridge. On receipt the Counselor does:

| Event | Handler | On receipt | Can reach | Trust or profile write |
|---|---|---|---|---|
| `CASCADE_CONFABULATION_DETECTED` | `_on_cascade_confabulation` (`counselor.py:1582-1608`) | INFO `AD-567f: Cascade confabulation <risk>`; at `high` only, one verification-prompt DM to each callsign in `affected_agents` (the peers, not the post's author) that resolves to an agent | crew agents | none |
| `WARD_ROOM_ECHO_DETECTED` | `_on_ward_room_echo` (`:1965-2002`) | nothing if `independence_score >= 0.3`; else a WARNING and one DM to each affected callsign except the source | crew agents | none |
| `OBSERVABLE_STATE_MISMATCH` | `_on_observable_mismatch` (`:2004-2035`) | nothing if `claims_failed == 0`; else a WARNING and one DM to each of the first three `agents_involved`, quoting the ground-truth summary | crew agents | none |

Each DM is a thread in the Counselor's DM channel with that agent (`_send_therapeutic_dm`, `:2415-2462`) plus an AD-561 intervention record (`COUNSELOR_INTERVENTION`, which nothing in `src/` subscribes to). None of the three posts to a Ward Room channel or messages the Captain; the Captain sees these detections as BF-920's Bridge alerts. Pacing on BF-920 candidate 2: the checks run on every thread and reply that has a peer match (`threads.py:569-572`, `messages.py:314-317`), and no event is deduplicated (cascade at medium and high; echo on each post of an echoing thread; mismatch when an echo of chain length 3 or more has a failed claim); the Bridge alerts have a 300 s per-key cooldown (`bridge_alerts.py:63`, `:92-105`); the Counselor sends any one agent at most one DM an hour from all causes (`DM_COOLDOWN_SECONDS = 3600`, `counselor.py:2411`, `:2427-2429`). A Counselor DM cannot itself raise a high cascade: its DM channel has one other participant, so it has at most one peer (`social_verification.py:592-601`).

*Found by A1: none of these DMs could be sent.* The cascade resolver (`_resolve_agent_id_from_callsign`, `:1610-1616`, `values()`) and the wrong-convergence, echo and mismatch lookups (`:1947`, `:1987`, `:2021`, `items()`) use a dict API on `self._registry`, which production sets to the runtime's `AgentRegistry` (`finalize.py:6061`, `runtime.py:668`). That class has `get()` and `all()` and no `values()` or `items()` (`substrate/registry.py:18-85`). With delivery restored, each qualifying event would raise `AttributeError` before its first DM, logged at WARNING by section 7.3 Pair 2. BF-920 round 1's probe saw DMs only because it passed a dict registry; `tests/test_ad583_wrong_convergence.py:505-509` pins the same dict API.

*Decision: fix the resolution here (section 7.3a); gate nothing.* (1) D1 is what makes the crash reach ordinary traffic, so the convergence rule puts the fix in this prompt; leaving it would ship four built, tested and inert handlers and a WARNING traceback per event. (2) No gate is needed: unlike D3's suppression DM, these handlers write no trust and no profile and send no verdict, only a request to check one's own anchors; the hourly per-agent cooldown caps every crew member at one Counselor DM an hour; only registered agents are messaged. (3) Making them record-only would reverse four approved crew-facing designs (AD-567f, AD-583, AD-583f, AD-583g) with no measured false-positive rate against them; section 16 measures the first session and R7 holds the follow-up. The resolver accepts a callsign or an agent id (the wrong-convergence producers do not declare which: R8) and returns None for a value no registered agent holds; all four handlers skip None, where three of them used to message the raw callsign as an id.

**D3, the penalty rule (item 2).** No suppression reason carries the trust penalty or a message. The handler is delivered and records: it logs `BF-921: Output suppression recorded for <callsign> (<agent_id>): reason=<r> path=<p>, <n> in the last hour; no trust penalty and no message (gauge not qualified)` and keeps a bounded per-agent hourly history. It sends no DM (a neutral DM per suppression would be noise, and would still present an unqualified judgement to the agent) and makes no profile write (the old ad hoc `confabulation_count` attribute has no reader in `src/`, section 12). Restoring a penalty for a reason is the decision of the issue that qualifies that reason's gauge: AD-1350 (#1637) for `quality_gate`, BF-922 (#1639)'s re-measure for `confabulation_detected`. The tests cover each reason, including `raw_json_output`, a future reason and an empty one.

**D4, `CONDUCT_VIOLATION` (item 3): remove the subscription, the dispatch branch and `_on_conduct_violation` with its penalty; keep the `EventType` member.** Reason: AD-489 specified no producer, and a producer is an agent's judgement of conduct, a new gauge that needs its own AD and its own qualification. Once D1 restores delivery, a kept handler would hand that penalty to the first emitter anyone adds, without a gauge. The member stays because it is declared in the AD-1195 persistence contract (`event_persistence.py:194`, `tests/test_ad1195_event_persistence_contract.py:117`); an unproduced, unconsumed member is inert. The federation standing order's sentence about the trust consequence is the Captain's text and is not edited (section 18, R3). This removes no operating control: the handler never ran (section 1).

**D5, SPC (item 4): mark it inert, do not feed it.** A feed must define the measured value per agent; AD-522's calibration projection is the unbuilt AD-522e-1 (`priority4_cleanup.py:282-291`). Choosing it is design work for its own AD. The store keeps its wiring (no consumer reads it, section 12; turning `spc.enabled` off would move the pinned config dumps for no gain).

**D6, scope (the convergence rule).** Items 3 and 4 are in this prompt as M2, not separate slices: both are small, of ordinary reach, and item 3 is coupled to D1 (delivery makes the dead handler reachable). Also fixed here because they are on the seam being repaired: the silently discarded failure of a NATS subscription task (`runtime.py:1881-1885`) and the DEBUG-level swallow in the Counselor's router (`counselor.py:1062-1063`), which together would hide the next delivery loss; and (A1) the Counselor's callsign resolution (D2, section 7.3a), whose crash D1 makes reachable. The runtime-wide NATS callback swallow (`runtime.py:1861-1863`) is registered, not changed (R5): it covers every listener and raising it may flood the log.

## 4. Interaction with the queue

**BF-920 (#1633) lands first; BF-921 is built on the commit that merges it (A1).** BF-920 removes the Ward Room helper's second emission of `CASCADE_CONFABULATION_DETECTED` (`ward_room/_helpers.py:50-57`), so `SocialVerificationService` is its one emitter. If BF-921 landed first, its filter fix would hand the Counselor every cascade twice: two handlings and two log lines per detection, with the second DM held back only by the hourly cooldown. BF-920 touches no file this prompt edits except `startup/finalize.py`, where its one deletion (`:5914`) lies far below section 7.9's pair (`:3533`), which applies once on BF-920 candidate 2. If BF-920 is not merged when this batch starts, stop and return to the Architect. Section 7.5's cascade case closes BF-920's half-chain: one service emission through the booted runtime, one Counselor handling.

**PR text, BF-921's part** (the orchestrator joins it with BF-922's): "BF-921 (#1636), built on BF-920 (#1633)'s merge. `add_event_listener` and `register_live_event_listener` filtered on `str()` of each `EventType` member (`"EventType.NAME"`), so the Counselor and four other listeners had received none of their events in any session; both now filter on wire values, and a failed NATS subscription is logged. Output suppressions reach the Counselor and are recorded with no trust penalty or message until each reason's gauge is qualified (AD-1350, BF-922). The Counselor's cascade, wrong-convergence, echo and observable-mismatch handlers now resolve agents through `AgentRegistry` (they called a dict API it lacks), so BF-920's single cascade event reaches the Counselor once and the designed DMs can be sent. The `CONDUCT_VIOLATION` handler and penalty (no producer) are removed; the SPC store is marked inert. First-session measures: section 16 of the contract."

BF-922 (#1639) is batched with this prompt and builds **after** it. Ownership of the suppression block in `_execute_sub_task_chain` (`cognitive_agent.py:5993-6029` on `cb190f32`, unchanged on `bf41e2dd`):

| Lines on `cb190f32` | Owner |
|---|---|
| `:5993-6001` (the EVALUATE scan and `rejection = ...`) | neither |
| `:6002-6005` (`logger.info("BF-206: Chain output suppressed ...")`) | **BF-922 M2** |
| `:6006-6018` (`# Emit confabulation suppressed event` through the emit's `})`) | **BF-921 M1** (this prompt) |
| `:6019-6029` (the suppressed decision) | neither |

The two SEARCH texts are disjoint. BF-922 M2 calls `_emit_output_suppressed`, which this prompt's M1 adds; that is BF-922's only dependency on BF-921. This prompt's `counselor.py` pairs: M1 owns `_on_event_async`'s `except` (`:1062-1063`), `_on_confabulation_suppressed`, the callsign resolver (`:1610-1616`) and the three lookup blocks (`:1942-1953`, `:1981-1992`, `:2018-2026`); M2 owns the `CONDUCT_VIOLATION` lines (`:709`, `:1060-1061`) and `_on_conduct_violation`; their SEARCH texts do not overlap.

## 5. Consumers of every value this changes

- `_event_type_filter` result: `_event_listeners` (local dispatch `runtime.py:1951-1953`), `_create_nats_event_subscription` subjects (`:1866-1873`), `_LiveEventListenerToken.event_types` (`:1742`, `:1974`). Callers passing strings (`finalize.py:112-113`, `:920`, `:3887-3889`, `:5333`) are unchanged: `str()` of a plain string is itself.
- `CONFABULATION_SUPPRESSED` payload gains `"path"`; its consumer is the Counselor handler (this prompt). No other subscriber in `src/` (section 12). Its `trust_score`, `chain_trust_band`, `intent`, `callsign`, `agent_type`, `agent_id`, `rejection_reason` keys are unchanged (`tests/test_bf206_confab_feedback.py:273-297` pins them).
- `_on_confabulation_suppressed`: called only by `_on_event_async` (`counselor.py:1056-1057`).
- `_resolve_agent_id_from_callsign` (A1, section 7.3a): called by `_on_cascade_confabulation` (`counselor.py:1606`) and, after section 7.3a, by `_on_wrong_convergence_detected`, `_on_ward_room_echo` and `_on_observable_mismatch`; each passes the result only to `_send_therapeutic_dm` as the recipient. No other caller (section 12).
- The SPC log line: no test pins it (section 11).

## 6. Milestones and tests

**M1 (HIGH), §7.1 to §7.5.** Commit "BF-921 M1: event-type filters use wire values; the Counselor receives its events, suppressions carry no penalty, callsign handlers resolve through AgentRegistry", with a body that ends "Built on the BF-920 (#1633) merge commit; BF-920's single CASCADE_CONFABULATION_DETECTED now reaches the Counselor once." Before editing, the Builder greps the tests that pin current behaviour (`grep -rn "_on_confabulation_suppressed\|confab_history\|str(t) for t\|_on_wrong_convergence_detected\|mock_registry" tests/`) and reads §7.4's replacement of `TestCounselorFeedback` and §7.4a's replacement of the dict-registry test, which update the pins and say why inline. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf921_counselor_event_delivery.py tests/test_bf206_confab_feedback.py tests/test_ad583_wrong_convergence.py tests/test_hxi_events.py tests/test_ad637d_system_events_nats.py tests/test_counselor.py tests/test_counselor_activation.py tests/test_counselor_therapeutic.py tests/test_ad489_code_of_conduct.py tests/test_ad659c_optimization_counselor.py tests/test_bf125_working_memory_desync.py tests/test_dreaming.py -n 0 -q
```

A test elsewhere that fails because a listener registered with members now receives events is a real consumer of D2: stop and send it to the Architect; never change its assertion to pass.

**M2 (STANDARD), §7.6 to §7.10.** Commit "BF-921 M2: remove the CONDUCT_VIOLATION handler and penalty (no producer); mark the SPC store inert". Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad489_code_of_conduct.py tests/test_ad522_spc.py tests/test_ad1195_event_persistence_contract.py tests/test_counselor.py tests/test_counselor_activation.py tests/test_bf921_counselor_event_delivery.py -n 0 -q
```

**The broad gate is run once for the batch by the main session, not by the Builder.**

## 7. The contract

### 7.1 `src/probos/runtime.py` (M1)

Pair 1:

SEARCH:
```python
class _LiveNATSSubscriptionOwner(Protocol):
    async def release_raw_subscription(self, subscription: object) -> bool: ...
```
REPLACE:
```python
def _event_type_filter(event_types: Iterable[object] | None) -> frozenset[str] | None:
    """BF-921 (#1636): the wire names of the event types a listener asked for (None: every event).

    ``EventType`` is a ``(str, Enum)``: on Python 3.11+ its ``str()`` is ``"EventType.NAME"``,
    not its value. Before BF-921 a listener that passed members filtered on names no event
    carries, locally and as NATS subjects, and received nothing: the Counselor's 24 types,
    BF-125's GAME_COMPLETED, AD-532e's and AD-534b's dreaming triggers and AD-659c's
    OPTIMIZATION_PROPOSAL_APPLIED.
    """
    if not event_types:
        return None
    return frozenset(
        item.value if isinstance(item, EventType) else str(item) for item in event_types
    )


class _LiveNATSSubscriptionOwner(Protocol):
    async def release_raw_subscription(self, subscription: object) -> bool: ...
```

Pair 2:

SEARCH:
```python
        NATS disconnected.
        """
        type_filter = frozenset(str(t) for t in event_types) if event_types else None
        # Always append to local list (used as fallback when NATS disconnected)
```
REPLACE:
```python
        NATS disconnected.
        """
        type_filter = _event_type_filter(event_types)
        # Always append to local list (used as fallback when NATS disconnected)
```

Pair 3:

SEARCH:
```python
        """Atomically register one live-only listener and await NATS readiness."""
        type_filter = frozenset(str(item) for item in event_types) if event_types else None
        token = _LiveEventListenerToken(fn, type_filter)
```
REPLACE:
```python
        """Atomically register one live-only listener and await NATS readiness."""
        type_filter = _event_type_filter(event_types)  # BF-921: live listeners too
        token = _LiveEventListenerToken(fn, type_filter)
```

Pair 4:

SEARCH:
```python
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_subscribe())
            self._nats_publish_tasks.add(task)
            task.add_done_callback(self._nats_publish_tasks.discard)
        except RuntimeError:
            pass  # No event loop — local-only listener
```
REPLACE:
```python
        def _on_subscribed(done: asyncio.Task[None]) -> None:
            # BF-921 (#1636): a subscription that fails leaves the listener deaf over
            # NATS; say so instead of discarding the task's exception.
            self._nats_publish_tasks.discard(done)
            if not done.cancelled() and done.exception() is not None:
                logger.warning(
                    "BF-921: NATS event subscription failed for %s; the listener receives "
                    "none of these events over NATS: %s",
                    sorted(type_filter) if type_filter else "system.events.>",
                    done.exception(),
                )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_subscribe())
            self._nats_publish_tasks.add(task)
            task.add_done_callback(_on_subscribed)
        except RuntimeError:
            pass  # No event loop — local-only listener
```

### 7.2 `src/probos/cognitive/cognitive_agent.py` (M1)

Pair 1 (the one emitter):

SEARCH:
```python
    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
```
REPLACE:
```python
    def _emit_output_suppressed(self, rejection: str, observation: dict, *, path: str) -> None:
        """BF-206 / BF-921 (#1636): announce an output the gate suppressed.

        The Counselor records it (``CounselorAgent._on_confabulation_suppressed``).
        ``path`` names the gate: ``"chain"`` (the chain's EVALUATE) or, from BF-922
        (#1639), ``"single_call_fallback"``. Log-and-degrade: an announcement that
        cannot be made never un-suppresses the output.
        """
        callsign = getattr(self, "callsign", "") or self.agent_type
        runtime = self._runtime
        if runtime is None:
            logger.warning(
                "BF-921: suppression of %s %s (%s) not announced: the agent has no runtime",
                self.agent_type, callsign, self.id,
            )
            return
        try:
            runtime.emit_event(EventType.CONFABULATION_SUPPRESSED, {
                "agent_id": self.id,
                "agent_type": self.agent_type,
                "callsign": callsign,
                "rejection_reason": rejection,
                "intent": observation.get("intent", ""),
                "trust_score": observation.get("_trust_score", 0.5),
                "chain_trust_band": observation.get("_chain_trust_band", "unknown"),
                "path": path,
            })
        except Exception:
            logger.warning(
                "BF-921: suppression of %s %s (%s) not announced: emit failed",
                self.agent_type, callsign, self.id, exc_info=True,
            )

    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
```

Pair 2 (BF-921's lines of the suppression block, section 4):

SEARCH:
```python
                # Emit confabulation suppressed event
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    from probos.events import EventType
                    _rt.emit_event(EventType.CONFABULATION_SUPPRESSED, {
                        "agent_id": self.id,
                        "agent_type": self.agent_type,
                        "callsign": getattr(self, 'callsign', self.agent_type),
                        "rejection_reason": rejection,
                        "intent": observation.get("intent", ""),
                        "trust_score": observation.get("_trust_score", 0.5),
                        "chain_trust_band": observation.get("_chain_trust_band", "unknown"),
                    })
                return {
```
REPLACE:
```python
                # BF-921 (#1636): one emitter for both suppression paths.
                self._emit_output_suppressed(rejection, observation, path="chain")
                return {
```

Builder note: the removed local `from probos.events import EventType` made `EventType` local to the whole function; the module-level import at `cognitive_agent.py:24` now serves it. Confirm no other line of `_execute_sub_task_chain` relied on the local name being unbound before that point (none on `cb190f32`).

### 7.3 `src/probos/cognitive/counselor.py` (M1)

Pair 1:

SEARCH:
```python
        self._emit_event_fn: Any = None
        self._add_event_listener_fn: Any = None
        self._ward_room_router: Any = None  # AD-495
```
REPLACE:
```python
        self._emit_event_fn: Any = None
        self._add_event_listener_fn: Any = None
        # BF-921 (#1636): per-agent times of recorded output suppressions (pruned to one hour).
        self._suppression_history: dict[str, list[float]] = {}
        self._ward_room_router: Any = None  # AD-495
```

Pair 2:

SEARCH:
```python
        except Exception:
            logger.debug("Counselor event handler failed for %s", event_type, exc_info=True)

    async def _on_dream_complete(self, data: dict[str, Any]) -> None:
```
REPLACE:
```python
        except Exception:
            # BF-921 (#1636): until BF-921 no handler had ever run; a failing one must be visible.
            logger.warning("Counselor event handler failed for %s", event_type, exc_info=True)

    async def _on_dream_complete(self, data: dict[str, Any]) -> None:
```

Pair 3 (the handler, whole):

SEARCH:
```python
    async def _on_confabulation_suppressed(self, data: dict[str, Any]) -> None:
        """BF-206: Handle confabulation suppression events.

        First offense in window: warning DM only (no trust penalty).
        Repeat offenses: trust penalty + escalated DM.
        """
        agent_id = data.get("agent_id", "")
        callsign = data.get("callsign", "")
        rejection_reason = data.get("rejection_reason", "")
        trust_score = data.get("trust_score", 0.5)

        if not agent_id or agent_id == self.id:
            return

        logger.info(
            "BF-206: Confabulation suppressed for %s (reason=%s, trust=%.2f)",
            callsign, rejection_reason, trust_score,
        )

        # Track confabulation count in cognitive profile
        profile = await self._get_or_create_profile(agent_id)
        profile.confabulation_count = getattr(profile, 'confabulation_count', 0) + 1

        # Windowed counting for graduated response
        import time as _time
        now = _time.time()
        if not hasattr(self, '_confab_history'):
            self._confab_history: dict[str, list[float]] = {}
        history = self._confab_history.setdefault(agent_id, [])
        history.append(now)
        cutoff = now - 3600.0
        self._confab_history[agent_id] = [t for t in history if t > cutoff]
        count = len(self._confab_history[agent_id])

        # Trust penalty on repeat offenses (2+ in window)
        trust_adjusted = self._trust_network is None
        if count >= 2 and self._trust_network:
            try:
                self._trust_network.record_outcome(
                    agent_id=agent_id,
                    success=False,
                    weight=0.5,
                    intent_type="confabulation_suppressed",
                    source="confabulation",
                )
                trust_adjusted = True
            except RuntimeError as exc:
                if str(exc) != "trust_write_in_progress":
                    raise
                logger.warning(
                    "AD-1130: Confabulation trust adjustment skipped for "
                    "agent=%s because a durable trust write is in progress; "
                    "the graduated counseling response will still be sent",
                    agent_id,
                )
            if trust_adjusted:
                logger.info(
                    "BF-206: Trust penalty for %s — %d confabulations in window",
                    callsign, count,
                )

        # Therapeutic DM (rate-limited by _send_therapeutic_dm)
        if count == 1:
            message = (
                "I noticed your recent response was held back because it contained "
                "details that couldn't be verified against available context. This is "
                "completely normal during early development — try grounding your "
                "observations in what you can directly observe rather than inferring "
                "specific identifiers or metrics."
            )
        else:
            trust_text = (
                "Your trust rating has been adjusted to reflect this pattern."
                if trust_adjusted
                else "The trust adjustment was skipped because another trust write is in progress."
            )
            message = (
                f"I've noticed this is the {count}{'nd' if count == 2 else 'rd' if count == 3 else 'th'} "
                "time your response contained unverifiable details within the past hour. "
                "I'd encourage you to focus on what you can directly observe — the crew "
                f"benefits most from grounded analysis. {trust_text}"
            )

        await self._send_therapeutic_dm(agent_id, callsign, message)
        if self._profile_store:
            try:
                await self._profile_store.save_profile(profile)
            except Exception:
                logger.debug("BF-206: Failed to persist profile for %s", agent_id[:8], exc_info=True)
```
REPLACE:
```python
    async def _on_confabulation_suppressed(self, data: dict[str, Any]) -> None:
        """BF-206 / BF-921 (#1636): record an output the gate suppressed.

        Delivered and recorded only. No suppression reason carries a trust penalty
        or a message until that reason's gauge is shown to be trustworthy:
        ``quality_gate`` (the LLM judge) until AD-1350 (#1637) shows it repeatable,
        ``confabulation_detected`` (BF-204) until BF-922 (#1639) has re-measured its
        false-positive rate, and every other reason likewise. Restoring a penalty
        for a reason is a decision of the issue that qualifies its gauge.
        """
        agent_id = data.get("agent_id", "")
        if not agent_id or agent_id == self.id:  # BF-921: never the Counselor's own output
            return
        now = time.time()
        history = self._suppression_history.setdefault(agent_id, [])
        history.append(now)
        history[:] = [t for t in history if t > now - 3600.0]
        logger.info(
            "BF-921: Output suppression recorded for %s (%s): reason=%s path=%s, "
            "%d in the last hour; no trust penalty and no message (gauge not qualified)",
            data.get("callsign", "") or agent_id,
            agent_id,
            data.get("rejection_reason", "") or "unknown",
            data.get("path", "chain"),
            len(history),
        )
```

### 7.3a `src/probos/cognitive/counselor.py` (M1, A1: callsign resolution through `AgentRegistry`)

`_on_cascade_confabulation`'s call (`:1606`) is unchanged. The three skip lines carry distinct comments so that each is one mutation row (section 10).

Pair 4 (the resolver):

SEARCH:
```python
    def _resolve_agent_id_from_callsign(self, callsign: str) -> str | None:
        """Best-effort resolve agent_id from callsign using registry."""
        if hasattr(self, '_registry') and self._registry:
            for agent in self._registry.values():
                if getattr(agent, 'callsign', None) == callsign:
                    return getattr(agent, 'id', None)
        return None
```
REPLACE:
```python
    def _resolve_agent_id_from_callsign(self, callsign_or_id: str) -> str | None:
        """The id of the registered agent with this callsign (or this id), else None.

        BF-921 (#1636): ``self._registry`` is the runtime's ``AgentRegistry``
        (finalize passes ``runtime.registry``): it has ``get()`` and ``all()``,
        no ``values()`` or ``items()``. The cascade, wrong-convergence, echo and
        observable-mismatch handlers used the dict API and would have raised
        before their first DM once their events were delivered. A value no
        registered agent holds (the Captain, an agent that has left) resolves
        to None, and the handlers do not message it.
        """
        if not callsign_or_id or self._registry is None:
            return None
        if self._registry.get(callsign_or_id) is not None:
            return callsign_or_id
        for agent in self._registry.all():
            if getattr(agent, "callsign", "") == callsign_or_id:
                return getattr(agent, "id", None)
        return None
```

Pair 5 (wrong convergence):

SEARCH:
```python
            for agent_id_or_callsign in agents:
                # Resolve agent_id from callsign
                agent_id = agent_id_or_callsign
                callsign = agent_id_or_callsign
                if self._registry:
                    for aid, agent in self._registry.items():
                        if getattr(agent, 'callsign', '') == agent_id_or_callsign:
                            agent_id = aid
                            callsign = agent_id_or_callsign
                            break
                if agent_id == self.id:
                    continue
```
REPLACE:
```python
            for agent_id_or_callsign in agents:
                # BF-921 (#1636): resolve through AgentRegistry; never message a value no agent holds.
                agent_id = self._resolve_agent_id_from_callsign(agent_id_or_callsign)
                callsign = agent_id_or_callsign
                if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583)
                    continue
```

Pair 6 (Ward Room echo):

SEARCH:
```python
        for callsign in affected:
            if callsign == source:
                continue  # Don't counsel the source — they made the original observation
            # Resolve agent_id from callsign
            agent_id = callsign
            if self._registry:
                for aid, agent in self._registry.items():
                    if getattr(agent, 'callsign', '') == callsign:
                        agent_id = aid
                        break
            if agent_id == self.id:
                continue
```
REPLACE:
```python
        for callsign in affected:
            if callsign == source:
                continue  # Don't counsel the source — they made the original observation
            # BF-921 (#1636): resolve through AgentRegistry; never message a callsign no agent holds.
            agent_id = self._resolve_agent_id_from_callsign(callsign)
            if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583g)
                continue
```

Pair 7 (observable mismatch):

SEARCH:
```python
        for callsign in agents[:3]:  # Limit DMs
            agent_id = callsign
            if self._registry:
                for aid, agent in self._registry.items():
                    if getattr(agent, 'callsign', '') == callsign:
                        agent_id = aid
                        break
            if agent_id == self.id:
                continue
```
REPLACE:
```python
        for callsign in agents[:3]:  # Limit DMs
            # BF-921 (#1636): resolve through AgentRegistry; never message a callsign no agent holds.
            agent_id = self._resolve_agent_id_from_callsign(callsign)
            if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583f)
                continue
```

### 7.4 `tests/test_bf206_confab_feedback.py` (M1: the pins of the removed DM and penalty)

SEARCH:
```python
class TestCounselorFeedback:
    """Counselor graduated response to confabulation suppression."""

    @pytest.fixture
    def counselor(self, mock_trust_network):
        from probos.cognitive.counselor import CounselorAgent
        c = CounselorAgent.__new__(CounselorAgent)
        c.id = "counselor-1"
        c.agent_type = "counselor"
        c.callsign = "Echo"
        c._trust_network = mock_trust_network
        c._cognitive_profiles = {}
        c._profile_store = None
        c._send_therapeutic_dm = AsyncMock(return_value=True)
        c._dm_cooldowns = {}
        return c

    @pytest.mark.asyncio
    async def test_routes_confabulation_event(self, counselor):
        """Counselor routes CONFABULATION_SUPPRESSED to handler."""
        counselor._on_confabulation_suppressed = AsyncMock()
        data = {"agent_id": "a1", "callsign": "Wesley"}
        await counselor._on_event_async({
            "type": EventType.CONFABULATION_SUPPRESSED.value,
            "data": data,
        })
        counselor._on_confabulation_suppressed.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_first_offense_warning_dm(self, counselor):
        """First confabulation in window sends warning DM, no trust penalty."""
        data = {
            "agent_id": "agent-x",
            "callsign": "Wesley",
            "rejection_reason": "fabricated_hex_ids",
            "trust_score": 0.3,
        }
        await counselor._on_confabulation_suppressed(data)

        counselor._send_therapeutic_dm.assert_awaited_once()
        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "held back" in msg
        assert "completely normal" in msg
        # No trust penalty on first offense
        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_offense_trust_penalty(self, counselor):
        """Second confabulation in window triggers trust penalty + escalated DM."""
        data = {
            "agent_id": "agent-x",
            "callsign": "Wesley",
            "rejection_reason": "fabricated_hex_ids",
            "trust_score": 0.3,
        }
        # First call
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.reset_mock()
        counselor._trust_network.record_outcome.reset_mock()

        # Second call — same window
        await counselor._on_confabulation_suppressed(data)

        # Trust penalty applied
        counselor._trust_network.record_outcome.assert_called_once_with(
            agent_id="agent-x",
            success=False,
            weight=0.5,
            intent_type="confabulation_suppressed",
            source="confabulation",
        )
        # Escalated DM
        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "2nd" in msg
        assert "trust rating has been adjusted" in msg

    @pytest.mark.asyncio
    async def test_second_offense_busy_trust_still_sends_honest_dm(self, counselor):
        data = {
            "agent_id": "agent-x",
            "callsign": "Wesley",
            "rejection_reason": "fabricated_hex_ids",
            "trust_score": 0.3,
        }
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.reset_mock()
        counselor._trust_network.record_outcome.side_effect = RuntimeError(
            "trust_write_in_progress",
        )

        await counselor._on_confabulation_suppressed(data)

        message = counselor._send_therapeutic_dm.await_args.args[2]
        assert "trust adjustment was skipped" in message
        assert "trust rating has been adjusted" not in message
        assert counselor._cognitive_profiles["agent-x"].confabulation_count == 2

    @pytest.mark.asyncio
    async def test_second_offense_other_trust_runtime_error_propagates(self, counselor):
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        await counselor._on_confabulation_suppressed(data)
        counselor._trust_network.record_outcome.side_effect = RuntimeError(
            "trust store defect",
        )

        with pytest.raises(RuntimeError, match="^trust store defect$"):
            await counselor._on_confabulation_suppressed(data)

    @pytest.mark.asyncio
    async def test_trust_penalty_weight(self, counselor):
        """Trust penalty uses weight=0.5 and source='confabulation'."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        # Two offenses to trigger penalty
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)

        call = counselor._trust_network.record_outcome.call_args
        assert call.kwargs["weight"] == 0.5
        assert call.kwargs["source"] == "confabulation"

    @pytest.mark.asyncio
    async def test_outside_window_resets_count(self, counselor):
        """Offenses outside 1h window don't count toward repeat threshold."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}

        # First offense
        await counselor._on_confabulation_suppressed(data)

        # Simulate time passing beyond window
        counselor._confab_history["agent-x"] = [time.time() - 3700]

        # Second offense — but old one expired
        counselor._trust_network.record_outcome.reset_mock()
        await counselor._on_confabulation_suppressed(data)

        # Should NOT trigger trust penalty (only 1 in window after prune)
        # Wait — the second call adds a new entry, prunes old one, so count = 1
        # Actually let's re-check: old timestamp pruned, new one added = count 1
        # But then the append happens first: [old, new], prune removes old → [new] → count=1
        # Actually the code appends THEN prunes. So: [old, new] → prune → [new] → count = 1
        # count >= 2 is False → no penalty
        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_confabulation_count_incremented(self, counselor):
        """confabulation_count incremented in cognitive profile."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        await counselor._on_confabulation_suppressed(data)

        profile = counselor._cognitive_profiles["agent-x"]
        assert profile.confabulation_count == 1

        await counselor._on_confabulation_suppressed(data)
        assert profile.confabulation_count == 2

    @pytest.mark.asyncio
    async def test_ignores_self_events(self, counselor):
        """Counselor ignores events about itself."""
        data = {"agent_id": "counselor-1", "callsign": "Echo"}
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_third_offense_th_suffix(self, counselor):
        """Third+ offenses use 'th' suffix in DM message."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.reset_mock()
        await counselor._on_confabulation_suppressed(data)

        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "3rd" in msg
```
REPLACE:
```python
class TestCounselorFeedback:
    """Counselor response to an output suppression.

    BF-921 (#1636) replaced BF-206's graduated response (a warning DM, then a
    0.5-weight trust penalty from the second suppression in an hour) with a
    record only, because no reason's gauge is qualified yet (quality_gate:
    AD-1350, #1637; confabulation_detected: BF-922, #1639). The tests that pinned
    the DM text, the penalty and its weight now pin their absence; each reason is
    tested in tests/test_bf921_counselor_event_delivery.py.
    """

    @pytest.fixture
    def counselor(self, mock_trust_network):
        from probos.cognitive.counselor import CounselorAgent
        c = CounselorAgent.__new__(CounselorAgent)
        c.id = "counselor-1"
        c.agent_type = "counselor"
        c.callsign = "Echo"
        c._trust_network = mock_trust_network
        c._cognitive_profiles = {}
        c._profile_store = None
        c._send_therapeutic_dm = AsyncMock(return_value=True)
        c._dm_cooldowns = {}
        c._suppression_history = {}  # BF-921: set by __init__, which __new__ skips
        return c

    @pytest.mark.asyncio
    async def test_routes_confabulation_event(self, counselor):
        """Counselor routes CONFABULATION_SUPPRESSED to handler."""
        counselor._on_confabulation_suppressed = AsyncMock()
        data = {"agent_id": "a1", "callsign": "Wesley"}
        await counselor._on_event_async({
            "type": EventType.CONFABULATION_SUPPRESSED.value,
            "data": data,
        })
        counselor._on_confabulation_suppressed.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_first_suppression_sends_no_message(self, counselor):
        """BF-921: was test_first_offense_warning_dm; the "couldn't be verified" DM is gone."""
        data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": "confabulation_detected"}
        await counselor._on_confabulation_suppressed(data)

        counselor._send_therapeutic_dm.assert_not_awaited()
        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_repeated_suppressions_carry_no_trust_penalty(self, counselor):
        """BF-921: was test_second_offense_trust_penalty, test_trust_penalty_weight and test_third_offense_th_suffix."""
        data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": "quality_gate"}
        for _ in range(3):
            await counselor._on_confabulation_suppressed(data)

        counselor._trust_network.record_outcome.assert_not_called()
        counselor._send_therapeutic_dm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_trust_network_that_would_raise_is_never_called(self, counselor):
        """BF-921: was the two RuntimeError tests; with no trust write there is nothing to skip or propagate."""
        counselor._trust_network.record_outcome.side_effect = RuntimeError("trust store defect")
        data = {"agent_id": "agent-x", "callsign": "W"}
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)

        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_suppressions_are_counted_within_one_hour(self, counselor):
        """BF-921: was test_outside_window_resets_count and test_confabulation_count_incremented."""
        counselor._suppression_history["agent-x"] = [time.time() - 3700]
        data = {"agent_id": "agent-x", "callsign": "W"}
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)

        assert len(counselor._suppression_history["agent-x"]) == 2

    @pytest.mark.asyncio
    async def test_ignores_self_events(self, counselor):
        """Counselor ignores events about itself."""
        data = {"agent_id": "counselor-1", "callsign": "Echo"}
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.assert_not_awaited()
        assert "counselor-1" not in counselor._suppression_history
```

### 7.4a `tests/test_ad583_wrong_convergence.py` (M1, A1: the pin of the dict registry)

SEARCH:
```python
    @pytest.mark.asyncio
    async def test_counselor_wrong_convergence_extreme_sends_dm(self):
        """independence_score < 0.1 triggers therapeutic DM."""
        from probos.cognitive.counselor import CounselorAgent
        from probos.cognitive.llm_client import BaseLLMClient

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._send_therapeutic_dm = AsyncMock(return_value=True)
        # Set up registry so agent can resolve callsigns
        mock_registry = {}
        mock_agent_obj = MagicMock()
        mock_agent_obj.callsign = "chapel"
        mock_registry["agent-chapel"] = mock_agent_obj
        agent._registry = mock_registry

        data = {
            "agents": ["chapel"],
            "departments": ["medical"],
            "topic": "plasma-anomaly",
            "independence_score": 0.05,  # Extreme
        }
        await agent._on_wrong_convergence_detected(data)
        # Should attempt DM to converging agent
        assert agent._send_therapeutic_dm.called
```
REPLACE:
```python
    @pytest.mark.asyncio
    async def test_counselor_wrong_convergence_extreme_sends_dm(self):
        """independence_score < 0.1 triggers therapeutic DM.

        BF-921 (#1636): this test used a dict as the registry, and so pinned the
        handler's ``items()`` lookup; production passes the runtime's AgentRegistry
        (``get()``/``all()``, no ``items()``), on which that lookup raised. It now
        uses a real AgentRegistry and pins the resolved agent id.
        """
        from probos.cognitive.counselor import CounselorAgent
        from probos.cognitive.llm_client import BaseLLMClient
        from probos.substrate.registry import AgentRegistry

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._send_therapeutic_dm = AsyncMock(return_value=True)
        registry = AgentRegistry()
        mock_agent_obj = MagicMock()
        mock_agent_obj.id = "agent-chapel"
        mock_agent_obj.agent_type = "medical_officer"
        mock_agent_obj.pool = "medical"
        mock_agent_obj.callsign = "chapel"
        await registry.register(mock_agent_obj)
        agent._registry = registry

        data = {
            "agents": ["chapel"],
            "departments": ["medical"],
            "topic": "plasma-anomaly",
            "independence_score": 0.05,  # Extreme
        }
        await agent._on_wrong_convergence_detected(data)
        # Should DM the converging agent, by its registered id
        agent._send_therapeutic_dm.assert_awaited_once()
        assert agent._send_therapeutic_dm.await_args.args[:2] == ("agent-chapel", "chapel")
```

### 7.5 New file: `tests/test_bf921_counselor_event_delivery.py` (M1)

```python
"""BF-921 (#1636): the Counselor receives the events it subscribes to, and no output suppression carries a penalty.

The contract is ``prompts/bf-921-counselor-event-delivery-and-suppression-penalty.md``.

Root cause (the contract's section 1): ``ProbOSRuntime.add_event_listener`` built its filter with ``str()``.
``EventType`` is a ``(str, Enum)``, whose ``str()`` is ``"EventType.NAME"`` on Python 3.11+, so every listener
that passed members filtered on names no event carries, locally and as NATS subjects.

Stand-ins, named: the chain executor in the suppression seam test (it returns EVALUATE's suppress); the Counselor's
``_send_therapeutic_dm`` (a spy) wherever a DM could be sent; the trust network in the handler tests; a NATS bus double
whose ``js_subscribe`` records subjects; in the cascade seam test (A1), the social verification service's episodic
memory (``_SameThreadEpisodes``: one same-thread episode per peer and one for the author); and, in the callsign tests,
``SimpleNamespace`` agents registered in a real ``AgentRegistry``. In the cascade seam test the handler spy wraps the
real ``_on_cascade_confabulation``; the service, its emitter (``runtime._emit_event``), BF-920's
``check_and_alert_cascade_risk``, the subscription and the Counselor are the booted runtime's own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.config import SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.types import AnchorFrame, Episode
from probos.ward_room._helpers import check_and_alert_cascade_risk

#: The members the five listeners that were deaf before BF-921 pass: counselor.py (one of 24),
#: finalize.py (BF-125), dreaming.py (AD-532e, AD-534b) and optimization_counselor.py (AD-659c).
WOKEN = (
    EventType.CONFABULATION_SUPPRESSED,
    EventType.GAME_COMPLETED,
    EventType.TASK_EXECUTION_COMPLETE,
    EventType.PROCEDURE_FALLBACK_LEARNING,
    EventType.OPTIMIZATION_PROPOSAL_APPLIED,
)

#: Every reason a suppression can carry today, one added later, and none.
REASONS = ("quality_gate", "confabulation_detected", "raw_json_output", "a_reason_added_later", "")


async def _settle(predicate: Any, *, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


def _counselor() -> CounselorAgent:
    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)
    return counselor


def _suppressing_executor() -> MagicMock:
    executor = MagicMock(spec=SubTaskExecutor)
    executor.can_execute.return_value = True
    executor.execute = AsyncMock(return_value=[
        SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": "A reply."}),
        SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name="evaluate-reply",
            result={"recommendation": "suppress", "rejection_reason": "confabulation_detected"},
        ),
    ])
    return executor


# --- the seam: ProbOSRuntime.add_event_listener --------------------------------------------------


def test_a_member_filter_is_stored_as_wire_values(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    fn = MagicMock()
    rt.add_event_listener(fn, event_types=[EventType.CONFABULATION_SUPPRESSED, "trust_update"])

    stored = next(type_filter for listener, type_filter in rt._event_listeners if listener is fn)
    assert stored == frozenset({"confabulation_suppressed", "trust_update"})


def test_no_filter_still_means_every_event(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    fn = MagicMock()
    rt.add_event_listener(fn)

    assert next(type_filter for listener, type_filter in rt._event_listeners if listener is fn) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("member", WOKEN, ids=lambda m: m.value)
async def test_a_member_filter_receives_its_event_locally(tmp_path, member: EventType) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    received: list[dict[str, Any]] = []

    async def listener(event: dict[str, Any]) -> None:
        received.append(event)

    rt.add_event_listener(listener, event_types=[member])
    rt.emit_event(member, {"agent_id": "a1"})

    assert await _settle(lambda: len(received) == 1)
    assert received[0]["type"] == member.value


@pytest.mark.asyncio
async def test_a_live_listener_member_filter_receives_its_event(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    received: list[dict[str, Any]] = []

    async def listener(event: dict[str, Any]) -> None:
        received.append(event)

    await rt.register_live_event_listener(listener, event_types=[EventType.TRUST_UPDATE])
    rt.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1"})

    assert await _settle(lambda: len(received) == 1)


@pytest.mark.asyncio
async def test_a_member_filter_subscribes_to_its_nats_subject(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    rt.nats_bus = SimpleNamespace(connected=True, js_subscribe=AsyncMock())
    rt._nats_events_wired = True

    rt.add_event_listener(AsyncMock(), event_types=[EventType.CONFABULATION_SUPPRESSED])

    assert await _settle(lambda: rt.nats_bus.js_subscribe.await_count == 1)
    assert rt.nats_bus.js_subscribe.await_args.args[0] == "system.events.confabulation_suppressed"


@pytest.mark.asyncio
async def test_a_failed_nats_subscription_is_logged(tmp_path, caplog) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    rt.nats_bus = SimpleNamespace(connected=True, js_subscribe=AsyncMock(side_effect=RuntimeError("no responders")))
    rt._nats_events_wired = True

    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        rt.add_event_listener(AsyncMock(), event_types=[EventType.CONFABULATION_SUPPRESSED])
        assert await _settle(lambda: "BF-921: NATS event subscription failed" in caplog.text)
    assert "confabulation_suppressed" in caplog.text
    assert "no responders" in caplog.text


# --- the seam test through the real startup wiring -------------------------------------------------


@pytest.mark.asyncio
async def test_a_chain_suppression_reaches_the_booted_counselor(tmp_path, caplog, monkeypatch) -> None:
    """A crew agent built by the agent fleet (its runtime set by startup) and the Counselor initialized by
    finalize. Only the chain executor is a stand-in."""
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    await rt.start()
    try:
        counselor = rt.registry.get_by_pool("counselor")[0]
        agent = next(
            a for a in rt.registry.all()
            if isinstance(a, CognitiveAgent) and a.agent_type != "counselor"
        )
        assert agent._runtime is rt  # set by startup, not by this test
        dm = AsyncMock(return_value=True)
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", dm)
        agent._sub_task_executor = _suppressing_executor()
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose-reply")],
            source="bf921-seam",
        )

        with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
            for _ in range(2):  # BF-206's old penalty fired from the second suppression in an hour
                decision = await agent._execute_sub_task_chain(
                    chain, {"intent": "ward_room_notification", "params": {}},
                )
                assert decision is not None and decision["_suppressed"] is True
            assert await _settle(
                lambda: caplog.text.count(f"({agent.id}): reason=confabulation_detected path=chain") == 2,
            )
        assert "BF-206: Trust penalty" not in caplog.text
        assert all(call.args[0] != agent.id for call in dm.await_args_list)
    finally:
        await rt.stop()


# --- BF-920's cascade through the booted runtime (A1) ------------------------------------------------


class _SameThreadEpisodes:
    """Stand-in for the service's episodic memory: one episode per agent id, all in one Ward Room thread.

    BF-920 scores a same-thread set of two or more episodes 0.0 (one episode alone scores 1.0,
    ``social_verification.py:189-190``). ``recall`` keeps the real ``k`` cap; the service filters
    the result by agent id.
    """

    def __init__(self, agent_ids: list[str]) -> None:
        self._episodes = [
            Episode(
                id=f"bf921-episode-{index}",
                agent_ids=[agent_id],
                timestamp=1000.0 + 180.0 * index,
                anchors=AnchorFrame(
                    thread_id="bf921-thread", duty_cycle_id="dc", channel="ward_room", channel_id="ship",
                    department="science", participants=["x"], trigger_agent="x", trigger_type="observation",
                    source_origin_id="", artifact_version="",
                ),
            )
            for index, agent_id in enumerate(agent_ids)
        ]

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        return self._episodes[:k]


@pytest.mark.asyncio
@pytest.mark.parametrize(("peers", "risk"), [(1, "low"), (2, "medium"), (3, "high")], ids=["low", "medium", "high"])
async def test_one_service_cascade_reaches_the_booted_counselor_once(
    tmp_path, monkeypatch, peers: int, risk: str,
) -> None:
    """BF-920's half-chain, closed (A1). The service startup built (``emit_event_fn=runtime._emit_event``), which
    BF-920 leaves as the only emitter of CASCADE_CONFABULATION_DETECTED, is driven through BF-920's Ward Room helper;
    the Counselor that finalize subscribed handles the event once (the removed duplicate would make it twice).
    NATS is off by default, so delivery takes the local path the filter fix repairs."""
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    await rt.start()
    try:
        counselor = rt.registry.get_by_pool("counselor")[0]
        service = rt._social_verification
        assert service is not None
        everyone = rt.registry.all()
        crew = [
            a for a in everyone
            if isinstance(a, CognitiveAgent) and a is not counselor and getattr(a, "callsign", "")
            and sum(getattr(b, "callsign", "") == a.callsign for b in everyone) == 1
        ][:peers]
        assert len(crew) == peers  # callsigns are set by startup; a shortfall is a hard stop (section 17)
        author_id, author_callsign = "bf921-author", "Bf921Author"
        body = "the game state is broken and stale"
        monkeypatch.setattr(service, "_episodic", _SameThreadEpisodes([a.id for a in crew] + [author_id]))
        handled = AsyncMock(wraps=counselor._on_cascade_confabulation)
        monkeypatch.setattr(counselor, "_on_cascade_confabulation", handled)
        dm = AsyncMock(return_value=True)
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", dm)
        wire: list[dict[str, Any]] = []
        rt.add_event_listener(wire.append, event_types=[EventType.CASCADE_CONFABULATION_DETECTED])
        peer_matches = [
            {"author_id": a.id, "author_callsign": a.callsign, "timestamp": 100.0 + index}
            for index, a in enumerate(crew)
        ]

        await check_and_alert_cascade_risk(
            service, bridge_alerts=None, ward_room_router=None, author_id=author_id,
            author_callsign=author_callsign, post_body=body, channel_id="ship", peer_matches=peer_matches,
        )

        events = 0 if risk == "low" else 1
        dms = sorted(a.id for a in crew) if risk == "high" else []
        assert await _settle(
            lambda: len(wire) >= events and handled.await_count >= events and dm.await_count >= len(dms),
        )
        await asyncio.sleep(0.2)  # a second delivery (BF-920's removed duplicate emit) would land in this window
        assert len(wire) == events
        assert handled.await_count == events  # one Counselor handling, not two
        assert sorted(call.args[0] for call in dm.await_args_list) == dms
        if events:
            assert wire[0]["data"]["risk_level"] == risk
        else:
            result = await service.check_cascade_risk(
                author_id, author_callsign, body, "ship", peer_matches=peer_matches,
            )
            assert result is not None and result.risk_level == "low"  # low, not none; nothing below medium is emitted
    finally:
        await rt.stop()


# --- the Counselor's callsign handlers against the runtime's AgentRegistry (A1) ------------------------

#: Each Counselor handler that turns a callsign into an agent id, and its payload naming ``who``.
CALLSIGN_EVENTS: dict[str, tuple[EventType, Any]] = {
    "cascade": (EventType.CASCADE_CONFABULATION_DETECTED, lambda who: {
        "risk_level": "high", "affected_agents": [who], "source_agent": "Source", "detail": "",
    }),
    "echo": (EventType.WARD_ROOM_ECHO_DETECTED, lambda who: {
        "source_callsign": "Source", "affected_callsigns": ["Source", who], "chain_length": 3,
        "independence_score": 0.0,
    }),
    "mismatch": (EventType.OBSERVABLE_STATE_MISMATCH, lambda who: {
        "agents_involved": [who], "claims_failed": 1, "ground_truth_summary": "No active games.",
    }),
    "wrong_convergence": (EventType.WRONG_CONVERGENCE_DETECTED, lambda who: {
        "agents": [who], "departments": ["science"], "topic": "bf921", "independence_score": 0.0,
    }),
}


async def _counselor_with_agent_registry() -> CounselorAgent:
    """A Counselor initialized with the registry type production passes (finalize: ``runtime.registry``)."""
    registry = AgentRegistry()
    await registry.register(
        SimpleNamespace(id="agent-kira", agent_type="science_officer", pool="science", callsign="Kira"),
    )
    counselor = _counselor()
    await counselor.initialize(registry=registry)
    return counselor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "who"),
    [("echo", "Kira"), ("mismatch", "Kira"), ("wrong_convergence", "Kira"), ("wrong_convergence", "agent-kira")],
    ids=["echo", "mismatch", "wrong_convergence", "wrong_convergence-by-id"],
)
async def test_a_callsign_handler_resolves_through_the_agent_registry(handler: str, who: str, caplog) -> None:
    """The dict lookup (``items()``/``values()``) raised on the AgentRegistry before the first DM."""
    counselor = await _counselor_with_agent_registry()
    event_type, payload = CALLSIGN_EVENTS[handler]

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": event_type.value, "data": payload(who)})

    assert "Counselor event handler failed" not in caplog.text
    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[0] == "agent-kira"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", sorted(CALLSIGN_EVENTS))
async def test_a_callsign_no_agent_carries_is_never_messaged(handler: str, caplog) -> None:
    """The Captain, or an agent that has left: no DM goes to an id no registered agent holds."""
    counselor = await _counselor_with_agent_registry()
    event_type, payload = CALLSIGN_EVENTS[handler]

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": event_type.value, "data": payload("Captain")})

    assert "Counselor event handler failed" not in caplog.text
    counselor._send_therapeutic_dm.assert_not_awaited()


# --- the penalty rule: one test per reason ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS, ids=lambda r: r or "empty")
async def test_no_suppression_reason_carries_a_penalty_or_a_message(reason: str, caplog) -> None:
    counselor = _counselor()
    data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": reason, "trust_score": 0.3}

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        for _ in range(3):
            await counselor._on_event_async({"type": EventType.CONFABULATION_SUPPRESSED.value, "data": data})

    counselor._trust_network.record_outcome.assert_not_called()
    counselor._send_therapeutic_dm.assert_not_awaited()
    assert caplog.text.count("BF-921: Output suppression recorded for Wesley (agent-x)") == 3
    assert f"reason={reason or 'unknown'} path=chain, 3 in the last hour" in caplog.text


@pytest.mark.asyncio
async def test_the_path_of_a_fallback_suppression_is_recorded(caplog) -> None:
    counselor = _counselor()
    data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": "confabulation_detected",
            "path": "single_call_fallback"}

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed(data)

    assert "path=single_call_fallback, 1 in the last hour" in caplog.text


@pytest.mark.asyncio
async def test_the_hourly_count_forgets_older_suppressions(caplog) -> None:
    counselor = _counselor()
    counselor._suppression_history["agent-x"] = [time.time() - 3700.0, time.time() - 3650.0]

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed({"agent_id": "agent-x", "callsign": "W"})

    assert "1 in the last hour" in caplog.text
    assert len(counselor._suppression_history["agent-x"]) == 1


@pytest.mark.asyncio
async def test_the_counselor_ignores_its_own_suppression(caplog) -> None:
    counselor = _counselor()

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed({"agent_id": counselor.id, "callsign": "Echo"})

    assert "BF-921: Output suppression recorded" not in caplog.text


@pytest.mark.asyncio
async def test_a_failing_counselor_handler_is_logged_at_warning(caplog) -> None:
    counselor = _counselor()
    counselor._on_trust_update = AsyncMock(side_effect=ValueError("boom"))

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": EventType.TRUST_UPDATE.value, "data": {}})

    assert "Counselor event handler failed for trust_update" in caplog.text


# --- the one emitter -------------------------------------------------------------------------------


def _bare_agent(runtime: Any) -> CognitiveAgent:
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-1"
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent._runtime = runtime
    return agent


def test_the_emitter_names_the_path() -> None:
    runtime = MagicMock()
    _bare_agent(runtime)._emit_output_suppressed("quality_gate", {"intent": "proactive_think"}, path="chain")

    event_type, data = runtime.emit_event.call_args.args
    assert event_type == EventType.CONFABULATION_SUPPRESSED
    assert data["path"] == "chain"
    assert data["rejection_reason"] == "quality_gate"
    assert data["callsign"] == "Kira"


def test_an_emitter_without_a_runtime_warns_and_does_not_raise(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        _bare_agent(None)._emit_output_suppressed("quality_gate", {}, path="chain")

    assert "not announced: the agent has no runtime" in caplog.text


def test_a_failing_emit_is_logged_and_does_not_raise(caplog) -> None:
    runtime = MagicMock()
    runtime.emit_event.side_effect = RuntimeError("bus down")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        _bare_agent(runtime)._emit_output_suppressed("quality_gate", {}, path="chain")

    assert "not announced: emit failed" in caplog.text
```

### 7.6 `src/probos/cognitive/counselor.py` (M2: the subscription)

SEARCH:
```python
                    EventType.REGISTER_SHIFT_DENIED,         # AD-653
                    EventType.CONDUCT_VIOLATION,             # AD-489
                ],
```
REPLACE:
```python
                    EventType.REGISTER_SHIFT_DENIED,         # AD-653
                    # BF-921 (#1636): not CONDUCT_VIOLATION; nothing emits it (AD-489 built
                    # only the consumer), and its penalty would need a qualified gauge.
                ],
```

### 7.7 `src/probos/cognitive/counselor.py` (M2: the dispatch branch and the handler)

Pair 1:

SEARCH:
```python
                await self._on_register_shift(data)
            elif event_type == EventType.CONDUCT_VIOLATION.value:
                await self._on_conduct_violation(data)
```
REPLACE:
```python
                await self._on_register_shift(data)
```

Pair 2:

SEARCH:
```python
    async def _on_conduct_violation(self, event_data: dict[str, Any]) -> None:
        """Handle Code of Conduct violation events (AD-489).

        Issues a private DM to the violating agent for minor violations.
        For repeated violations, applies trust penalty.
        """
        agent_id = event_data.get("agent_id", "")
        principle = event_data.get("principle", "")
        severity = event_data.get("severity", "minor")
        detail = event_data.get("detail", "")

        if not agent_id:
            return

        callsign = agent_id
        if self._registry:
            agent = self._registry.get(agent_id)
            if agent:
                callsign = getattr(agent, "callsign", "") or agent_id

        if severity == "minor":
            await self._send_therapeutic_dm(
                agent_id,
                callsign,
                f"I noticed a Code of Conduct concern regarding the {principle} principle. "
                f"{detail} This is a reminder, not a penalty. "
                f"Our shared norms help us work together effectively.",
            )
            next_step = "sent_private_reminder"
        else:
            trust_adjusted = self._trust_network is None
            if self._trust_network:
                try:
                    self._trust_network.record_outcome(
                        agent_id,
                        success=False,
                        weight=0.5,
                        source="conduct_violation",
                    )
                    trust_adjusted = True
                except RuntimeError as exc:
                    if str(exc) != "trust_write_in_progress":
                        raise
                    logger.warning(
                        "AD-1130: Conduct trust adjustment skipped for agent=%s "
                        "because a durable trust write is in progress; the "
                        "counseling response will still be sent",
                        agent_id,
                    )
            adjustment_text = (
                "A trust adjustment has been applied."
                if trust_adjusted
                else "The trust adjustment was skipped because another trust write is in progress."
            )
            await self._send_therapeutic_dm(
                agent_id,
                callsign,
                f"A Code of Conduct violation has been recorded for the {principle} "
                f"principle (severity: {severity}). {detail} "
                f"{adjustment_text}",
            )
            next_step = (
                "applied_trust_adjustment_and_sent_dm"
                if trust_adjusted
                else "skipped_busy_trust_adjustment_and_sent_dm"
            )
        logger.info(
            "AD-489: Conduct violation handled for %s; principle=%s severity=%s next=%s",
            agent_id,
            principle,
            severity,
            next_step,
        )

    async def _on_qualification_drift(self, data: dict[str, Any]) -> None:
```
REPLACE:
```python
    async def _on_qualification_drift(self, data: dict[str, Any]) -> None:
```

### 7.8 `tests/test_ad489_code_of_conduct.py` (M2: the pins of the removed handler)

SEARCH:
```python
@pytest.mark.asyncio
async def test_counselor_handles_minor_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "agent_id": "agent-1",
            "principle": "Honesty",
            "severity": "minor",
            "detail": "Uncertainty was not stated.",
        },
    })

    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[0] == "agent-1"
    assert counselor._send_therapeutic_dm.await_args.args[1] == "Data"
    assert "reminder, not a penalty" in counselor._send_therapeutic_dm.await_args.args[2]
    counselor._trust_network.record_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_counselor_handles_severe_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "agent_id": "agent-1",
            "principle": "Respect",
            "severity": "severe",
            "detail": "Dismissive conduct repeated.",
        },
    })

    counselor._trust_network.record_outcome.assert_called_once_with(
        "agent-1",
        success=False,
        weight=0.5,
        source="conduct_violation",
    )
    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[1] == "Data"
    assert "trust adjustment has been applied" in counselor._send_therapeutic_dm.await_args.args[2]


@pytest.mark.asyncio
async def test_counselor_busy_trust_still_sends_honest_severe_violation_dm() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._trust_network.record_outcome.side_effect = RuntimeError(
        "trust_write_in_progress",
    )
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_conduct_violation({
        "agent_id": "agent-1",
        "principle": "Respect",
        "severity": "severe",
        "detail": "Dismissive conduct repeated.",
    })

    counselor._send_therapeutic_dm.assert_awaited_once()
    message = counselor._send_therapeutic_dm.await_args.args[2]
    assert "trust adjustment was skipped" in message
    assert "has been applied" not in message


@pytest.mark.asyncio
async def test_counselor_other_trust_runtime_error_propagates() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._trust_network.record_outcome.side_effect = RuntimeError(
        "trust store defect",
    )
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    with pytest.raises(RuntimeError, match="^trust store defect$"):
        await counselor._on_conduct_violation({
            "agent_id": "agent-1",
            "principle": "Respect",
            "severity": "severe",
            "detail": "Dismissive conduct repeated.",
        })
    counselor._send_therapeutic_dm.assert_not_awaited()


@pytest.mark.asyncio
async def test_conduct_violation_without_agent_id_is_noop() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "principle": "Cooperation",
            "severity": "minor",
            "detail": "No agent attached.",
        },
    })

    counselor._send_therapeutic_dm.assert_not_awaited()
    counselor._trust_network.record_outcome.assert_not_called()
```
REPLACE:
```python
# BF-921 (#1636): AD-489 named no producer of CONDUCT_VIOLATION ("assessed by the Counselor or by
# department Chiefs", config/standing_orders/federation.md) and none was built, so the Counselor's
# subscription, handler and trust penalty were removed rather than left as a penalty path that the
# first emitter would inherit without a qualified gauge. The five tests that drove the removed
# handler (minor, severe, busy trust, propagating trust error, no agent id) now pin the removal.


@pytest.mark.asyncio
async def test_counselor_does_not_subscribe_to_conduct_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    add_listener = MagicMock()
    await counselor.initialize(add_event_listener_fn=add_listener)

    (types,) = [call.kwargs["event_types"] for call in add_listener.call_args_list]
    assert EventType.CONDUCT_VIOLATION not in types
    assert EventType.CONFABULATION_SUPPRESSED in types


@pytest.mark.asyncio
async def test_a_conduct_violation_event_changes_nothing() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {"agent_id": "agent-1", "principle": "Respect", "severity": "severe", "detail": "x"},
    })

    counselor._send_therapeutic_dm.assert_not_awaited()
    counselor._trust_network.record_outcome.assert_not_called()
    assert not hasattr(CounselorAgent, "_on_conduct_violation")
```

### 7.9 `src/probos/cognitive/spc/store.py` and `src/probos/startup/finalize.py` (M2: inert)

`store.py`:

SEARCH:
```python
    """Per-agent SPC profiles. AD-522 v1.

    Stores ``AgentCalibrationProfile`` instances; runs ``WesternElectricRules.check``
    on demand. Emits ``SPC_RULE_VIOLATED`` per detected violation.
    """
```
REPLACE:
```python
    """Per-agent SPC profiles. AD-522 v1.

    Stores ``AgentCalibrationProfile`` instances; runs ``WesternElectricRules.check``
    on demand. Emits ``SPC_RULE_VIOLATED`` per detected violation.

    Inert (BF-921, #1636): nothing in ``src/`` calls :meth:`record_observation`,
    so every chart is empty and :meth:`check_rules` finds nothing. AD-522's feed
    (the AD-522e-1 calibration projection) is unbuilt; a producer needs its own
    AD that defines the value each observation measures.
    """
```

`finalize.py`:

SEARCH:
```python
    logger.info(
        "AD-522: SPCCalibrationStore initialized (sample_window=%d; 4 of 8 WE rules)",
        cfg.sample_window,
    )
```
REPLACE:
```python
    # BF-921 (#1636): no producer calls record_observation (AD-522e-1 is unbuilt).
    logger.info(
        "AD-522: SPCCalibrationStore initialized inert (sample_window=%d; 4 of 8 WE rules): "
        "nothing records observations (BF-921, #1636)",
        cfg.sample_window,
    )
```

### 7.10 `tests/test_ad522_spc.py` (M2)

SEARCH:
```python
def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(spc=SPCConfig(enabled=False))
    wired = _wire_spc_calibration(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "spc_calibration_store")
```
REPLACE:
```python
def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(spc=SPCConfig(enabled=False))
    wired = _wire_spc_calibration(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "spc_calibration_store")


def test_the_spc_store_is_announced_inert(caplog) -> None:
    """BF-921 (#1636): nothing records observations, so the boot line says the store is inert."""
    import logging

    runtime = MagicMock(spec=["emit_event", "spc_calibration_store"])
    config = SimpleNamespace(spc=SPCConfig(enabled=True))
    with caplog.at_level(logging.INFO, logger="probos.startup.finalize"):
        assert _wire_spc_calibration(runtime=runtime, config=config) is True
    assert "SPCCalibrationStore initialized inert" in caplog.text
    assert "nothing records observations" in caplog.text
```

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and the `DECISIONS.md` heading `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)` (line 697 on this tree); both stay unique after BF-918's, BF-919's and BF-920's entries. The tracker entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-921 (2026-10-24), #1636 -- the Counselor receives the events it subscribes to; no output suppression carries a penalty.** `ProbOSRuntime.add_event_listener` and `register_live_event_listener` built their type filter with `str()`, which for an `EventType` member is `"EventType.NAME"`, so every listener that passed members (the Counselor's 24 types, BF-125, AD-532e, AD-534b, AD-659c) had received nothing, locally or over NATS; the filter now holds wire values (`_event_type_filter`), and a failed NATS subscription is logged. Suppressions reach the Counselor through one emitter (`CognitiveAgent._emit_output_suppressed`, payload `path`), and the Counselor records them (one INFO line, an hourly count) with no trust penalty and no message until the reason's gauge is qualified (AD-1350 for `quality_gate`, BF-922 for `confabulation_detected`). The Counselor no longer subscribes to or handles `CONDUCT_VIOLATION`, which nothing emits; the SPC store is marked inert (nothing records observations). A failing Counselor handler is logged at WARNING. The Counselor's cascade, wrong-convergence, echo and observable-mismatch handlers resolve agents through the runtime's `AgentRegistry` (they called a dict API it lacks and would have raised before their first DM), and BF-920's single cascade event reaches the Counselor once. Built after BF-920 (#1633). New: `tests/test_bf921_counselor_event_delivery.py`. The contract is `prompts/bf-921-counselor-event-delivery-and-suppression-penalty.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-921 -- The Counselor receives the events it subscribes to; no output suppression carries a penalty (2026-10-24, #1636)

- *Root cause.* `add_event_listener` stringified `EventType` members with `str()` (`"EventType.NAME"` on Python 3.11+), so member filters matched nothing, locally and as NATS subjects. Fixed at the seam for every caller (`_event_type_filter`), not in the Counselor alone. The leading suspect, `_runtime` being `None`, was refuted. Five dormant listeners now receive events.
- *Penalty rule.* An output suppression is delivered and recorded only: no reason carries the Counselor's trust penalty or message until its gauge is qualified (`quality_gate`: AD-1350, #1637; `confabulation_detected`: BF-922, #1639). Restoring a penalty is a decision of the qualifying issue.
- *CONDUCT_VIOLATION.* The subscription, handler and penalty are removed: AD-489 named no producer, and a producer is a new conduct gauge needing its own AD. The `EventType` member and the federation standing order's text stay.
- *SPC.* The AD-522 store stays wired and is marked inert: its feed (AD-522e-1) is unbuilt.
- *Callsign handlers (A1).* The four Counselor handlers that message by callsign resolve through `AgentRegistry` and skip a callsign no registered agent holds. Their DMs (verification prompts; no trust or profile write; at most one Counselor DM per agent an hour) are restored as AD-567f, AD-583, AD-583f and AD-583g designed them, not gated. Order: after BF-920 (#1633), which made the cascade event single.
- *Reversal.* Revert the commits; the listeners go deaf again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916 precedent).

**#1636 checklist text** (the orchestrator records it on the issue):
- [ ] (1) Root cause: `add_event_listener` stringified `EventType` members; fixed at the seam; seam test through `ProbOSRuntime.start()` (M1).
- [ ] (1b) BF-920's cascade reaches the Counselor once through the booted runtime; the four callsign handlers resolve through `AgentRegistry` (M1, A1).
- [ ] (2) No suppression reason carries a penalty or message; one test per reason (M1).
- [ ] (3) `CONDUCT_VIOLATION` subscription, handler and penalty removed (M2).
- [ ] (4) SPC store marked inert (M2).
- [ ] First live session after merge: section 16's counts recorded on #1636.

## 9. What this does NOT change

- `EventType` stays a `(str, Enum)`; `EventType.CONDUCT_VIOLATION` stays; the AD-1195 persistence lists are unchanged (`CONFABULATION_SUPPRESSED` stays `GRANDFATHERED`, R1).
- The emit's existing payload keys and the BF-206 suppression decision (`[NO_RESPONSE]`, `_suppressed`, `_suppression_reason`) are unchanged. The BF-206 log line (`cognitive_agent.py:6002-6005`) is BF-922's (section 4).
- The Counselor's other handlers run unchanged (D2), except that the four callsign handlers resolve agents through `AgentRegistry` and skip a callsign no registered agent holds (section 7.3a); their messages, thresholds and the DM cooldown are unchanged. The runtime-wide NATS callback still logs a listener failure at DEBUG (R5).
- BF-920's files (`social_verification.py`, `observable_state.py`, `ward_room/*`, `bridge_alerts.py`) are not edited.
- `config/standing_orders/federation.md` is not edited (R3). `spc.enabled` stays `True`.
- The trust network, its event, and every other trust writer are unchanged.

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7)

Tier HIGH for M1. Run each row on the applied tree after an unmutated baseline run passes; restore each file before the next row. Command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf921_counselor_event_delivery.py tests/test_bf206_confab_feedback.py tests/test_ad583_wrong_convergence.py tests/test_ad489_code_of_conduct.py tests/test_ad522_spc.py -n 0 -x -q
```

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | `src/probos/runtime.py` | `item.value if isinstance(item, EventType) else str(item) for item in event_types` | `str(item) for item in event_types` | `test_a_member_filter_is_stored_as_wire_values`, `test_a_member_filter_receives_its_event_locally`, the seam test |
| R2 | `src/probos/runtime.py` | `type_filter = _event_type_filter(event_types)` | `type_filter = frozenset(str(t) for t in event_types) if event_types else None` | `test_a_member_filter_receives_its_event_locally` |
| R3 | `src/probos/runtime.py` | `type_filter = _event_type_filter(event_types)  # BF-921: live listeners too` | `type_filter = frozenset(str(item) for item in event_types) if event_types else None` | `test_a_live_listener_member_filter_receives_its_event` |
| R4 | `src/probos/runtime.py` | `if not done.cancelled() and done.exception() is not None:` | `if False:` | `test_a_failed_nats_subscription_is_logged` |
| R5 | `src/probos/cognitive/cognitive_agent.py` | `self._emit_output_suppressed(rejection, observation, path="chain")` | `pass` | the seam test; `TestEventEmission::test_event_emitted_on_suppress` |
| R6 | `src/probos/cognitive/cognitive_agent.py` | `"path": path,` | `"path": "",` | `test_the_emitter_names_the_path` |
| R7 | `src/probos/cognitive/counselor.py` | `if not agent_id or agent_id == self.id:  # BF-921: never the Counselor's own output` | `if not agent_id:` | `test_the_counselor_ignores_its_own_suppression` |
| R8 | `src/probos/cognitive/counselor.py` | `history[:] = [t for t in history if t > now - 3600.0]` | `pass` | `test_the_hourly_count_forgets_older_suppressions` |
| R9 | `src/probos/cognitive/counselor.py` | `logger.warning("Counselor event handler failed for %s", event_type, exc_info=True)` | `logger.debug("Counselor event handler failed for %s", event_type, exc_info=True)` | `test_a_failing_counselor_handler_is_logged_at_warning` |
| R10 | `src/probos/cognitive/counselor.py` | `EventType.REGISTER_SHIFT_DENIED,         # AD-653` | `EventType.REGISTER_SHIFT_DENIED, EventType.CONDUCT_VIOLATION,` | `test_counselor_does_not_subscribe_to_conduct_violation` |
| R11 | `src/probos/startup/finalize.py` | `"AD-522: SPCCalibrationStore initialized inert (sample_window=%d; 4 of 8 WE rules): "` | `"AD-522: SPCCalibrationStore initialized (sample_window=%d; 4 of 8 WE rules) "` | `test_the_spc_store_is_announced_inert` |
| R12 | `src/probos/cognitive/counselor.py` | `for agent in self._registry.all():` | `for agent in self._registry.values():` | `test_a_callsign_handler_resolves_through_the_agent_registry`, `test_a_callsign_no_agent_carries_is_never_messaged`, `test_one_service_cascade_reaches_the_booted_counselor_once[high]` |
| R13 | `src/probos/cognitive/counselor.py` | `if self._registry.get(callsign_or_id) is not None:` | `if False:` | `test_a_callsign_handler_resolves_through_the_agent_registry[wrong_convergence-by-id]` |
| R14 | `src/probos/cognitive/counselor.py` | `if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583)` | `if agent_id == self.id:` | `test_a_callsign_no_agent_carries_is_never_messaged[wrong_convergence]` |
| R15 | `src/probos/cognitive/counselor.py` | `if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583g)` | `if agent_id == self.id:` | `test_a_callsign_no_agent_carries_is_never_messaged[echo]` |
| R16 | `src/probos/cognitive/counselor.py` | `if agent_id is None or agent_id == self.id:  # BF-921: unresolved or self (AD-583f)` | `if agent_id == self.id:` | `test_a_callsign_no_agent_carries_is_never_messaged[mismatch]` |
| R17 | `src/probos/cognitive/social_verification.py` | `if risk_level in ("medium", "high") and self._emit_event:` | `if False:` | `test_one_service_cascade_reaches_the_booted_counselor_once[medium]`, `[high]` |

The removed penalty cannot be mutated back in by one line; `test_no_suppression_reason_carries_a_penalty_or_a_message` (five reasons, three suppressions each) is its pin. Likewise BF-920's removed duplicate cascade emit: the cascade seam case's `== events` assertions after its settle window are its pin.

## 11. Verified Against Codebase (2026-10-24, worktree `d922-draft` at `origin/main` `cb190f32`)

```
grep -n "type_filter = frozenset" src/probos/runtime.py
  1706: type_filter = frozenset(str(t) for t in event_types) if event_types else None
  1728: type_filter = frozenset(str(item) for item in event_types) if event_types else None
grep -n "^class EventType" src/probos/events.py
  22: class EventType(str, Enum):
grep -n "def __str__\|def __format__" src/probos/events.py
  (none: EventType inherits Enum.__str__)
read d:/ProbOS/.venv/pyvenv.cfg
  4: version_info = 3.12.13
grep -n "subject = f\"system.events" src/probos/runtime.py
  1868: subject = f"system.events.{event_type}"
  1940: subject = f"system.events.{type_str}"
grep -n "type_str not in type_filter" src/probos/runtime.py
  1952: if type_filter is not None and type_str not in type_filter:
grep -n "pass  # No event loop" src/probos/runtime.py
  1887: pass  # No event loop — local-only listener
grep -n "^from collections.abc import\|^from probos.events import" src/probos/runtime.py
  16: from collections.abc import Awaitable, Callable, Coroutine, Iterable
  23: from probos.events import BaseEvent, EventType
grep -n "_nats_events_wired: bool\|self.nats_bus: NATSBus" src/probos/runtime.py
  1531, 1679
grep -n "add_event_listener_fn=runtime.add_event_listener\|_setup_nats_event_subscriptions()" src/probos/startup/finalize.py
  on bf41e2dd: 6065 (Counselor initialize), 6667 (after all listeners); 6066 and 6668 on cb190f32 (BF-920 deletes :5914)
grep -n "event_types=\[EventType\." src/probos/startup/finalize.py src/probos/startup/dreaming.py src/probos/cognitive/optimization_counselor.py
  on bf41e2dd: finalize.py:5984 GAME_COMPLETED (5985 on cb190f32); dreaming.py:347 TASK_EXECUTION_COMPLETE; dreaming.py:359 PROCEDURE_FALLBACK_LEARNING; optimization_counselor.py:117 OPTIMIZATION_PROPOSAL_APPLIED
grep -n "EventType.CONFABULATION_SUPPRESSED,\|EventType.CONDUCT_VIOLATION," src/probos/cognitive/counselor.py
  706, 709
grep -n "self._runtime = kwargs.get(\"runtime\")" src/probos/cognitive/cognitive_agent.py
  1320
grep -n "runtime=runtime" src/probos/startup/agent_fleet.py
  167 (architect), 191 (counselor), 248 (security_officer), ... every crew pool
grep -n "^from probos.events import" src/probos/cognitive/cognitive_agent.py
  24: from probos.events import EventType, SensoriumBudgetExceededEvent
grep -n "# Emit confabulation suppressed event\|BF-206: Chain output suppressed" src/probos/cognitive/cognitive_agent.py
  6003, 6006
grep -n "Counselor event handler failed\|async def _on_conduct_violation\|async def _on_confabulation_suppressed\|self._add_event_listener_fn: Any = None\|^import time" src/probos/cognitive/counselor.py
  15, 554, 1063, 1428, 1706
grep -n "4 of 8 WE rules" src/probos/startup/finalize.py
  3533
grep -rn "4 of 8 WE rules\|SPCCalibrationStore initialized" tests/
  (none)
grep -n "def test_" tests/test_bf206_confab_feedback.py (TestCounselorFeedback, 334-506)
  352, 363, 381, 411, 432, 443, 455, 478, 490, 497
grep -n "def test_counselor_handles\|_on_conduct_violation(" tests/test_ad489_code_of_conduct.py
  49, 75, 116, 142
rt.start() in tests: tests/test_hxi_events.py:101-116 (ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path))
grep -n "enabled: bool = True" src/probos/config_models/crew.py
  231 (UtilityAgentsConfig: the counselor and crew pools are built at a default boot, agent_fleet.py:179-193)

A1, re-verified 2026-10-24 on worktree bf921-consult 8e632219 (BF-920 candidate 2 bf41e2dd on origin/main 026a682f, plus this contract)
git diff --stat cb190f32 HEAD -- src/
  finalize.py 1 deletion (:5914, the SystemHealthProvider import); counselor.py, cognitive_agent.py, runtime.py, events.py, spc/store.py unchanged
grep -n "registry=runtime.registry" src/probos/startup/finalize.py
  6061 (Counselor initialize)
grep -n "self.registry = AgentRegistry()" src/probos/runtime.py
  668
grep -n "^class \|def " src/probos/substrate/registry.py
  18 AgentRegistry; 24 __init__, 29 register, 40 unregister, 58 get, 61 get_by_pool, 64 get_by_capability, 71 all, 77 count, 80 crew_count, 85 summary
grep -n "_registry\.\(values\|items\)()" src/probos/cognitive/counselor.py
  1613, 1947, 1987, 2021
grep -n "async def _on_cascade_confabulation\|def _resolve_agent_id_from_callsign\|async def _on_wrong_convergence_detected\|async def _on_ward_room_echo\|async def _on_observable_mismatch\|DM_COOLDOWN_SECONDS = 3600\|async def _send_therapeutic_dm" src/probos/cognitive/counselor.py
  1582, 1610, 1929, 1965, 2004, 2411, 2415
grep -n "if len(episodes) < 2:\|self._episodic = episodic_memory\|if risk_level in (\"medium\", \"high\") and self._emit_event:" src/probos/cognitive/social_verification.py
  189 (one episode scores 1.0), 298, 636
grep -n "emit_event_fn=self._emit_event\|self._social_verification = cog.social_verification" src/probos/runtime.py
  2931 (init_cognitive_services), 2967
grep -n "async def check_and_alert_cascade_risk\|emit_fn(_ET.WARD_ROOM_ECHO_DETECTED\|emit_fn(_ET.OBSERVABLE_STATE_MISMATCH" src/probos/ward_room/_helpers.py
  37 (keyword-only after the service), 103, 154
grep -n "await self._check_cascade_risk(\|await self._check_echo_trace(" src/probos/ward_room/threads.py src/probos/ward_room/messages.py
  threads.py:569, 572; messages.py:314, 317
grep -n "cooldown_seconds: float = 300\|def _should_emit" src/probos/bridge_alerts.py
  63, 92
grep -n "cascade_enabled: bool = True\|echo_analysis_enabled: bool = True\|verification_enabled: bool = True" src/probos/config_models/knowledge.py
  387, 404, 410
grep -n "class NatsConfig" src/probos/config.py
  3640; enabled default=False at 3643-3644 (a default test boot dispatches locally)
grep -n "agent.callsign = callsign" src/probos/agent_onboarding.py
  194 (wire_agent sets each agent's callsign from the callsign registry)
grep -n "mock_registry = {}" tests/test_ad583_wrong_convergence.py
  505 (the pin of the dict API, section 7.4a)
```

## 12. Absence Verified (2026-10-24)

```
CLAIM: nothing emits CONDUCT_VIOLATION
RUN:   rg -n "CONDUCT_VIOLATION|conduct_violation" src/ tests/ config/
FOUND: events.py:93 (definition), event_persistence.py:194 (GRANDFATHERED list), counselor.py:709/1060/1061/1428/1465 (consumer),
       config/standing_orders/federation.md:182 (text), tests only
HOLDS: yes, no emit_event / _emit_event call carries it

CLAIM: nothing calls SPCCalibrationStore.record_observation, and nothing reads the store
RUN:   rg -n "record_observation|spc_calibration_store" src/
FOUND: spc/store.py:38 (def), spc/calibration_profile.py:29 (def, called by store.py:40), agent_working_memory.py:425 and
       evidence_collector.py:215 (other classes' methods) and their callers; finalize.py:3531 (the only spc_calibration_store use)
HOLDS: yes

CLAIM: no Counselor event handler ever ran in the retained live logs
RUN:   Grep "probos\.cognitive\.counselor\s" over %LOCALAPPDATA%\ProbOS\data\logs (count), then "...counselor\s+AD-503: Counselor loaded" (count),
       then "AD-489: Conduct violation handled|BF-206: Trust penalty|BF-206: Confabulation suppressed for"
FOUND: 67, 67, 0
HOLDS: yes: every Counselor line is the startup profile load

CLAIM: nothing else subscribes to CONFABULATION_SUPPRESSED
RUN:   rg -n "CONFABULATION_SUPPRESSED|confabulation_suppressed" src/
FOUND: events.py:220, event_persistence.py:195, counselor.py:706/1056, cognitive_agent.py:6010, counselor.py:1748 (intent_type string)
HOLDS: yes

CLAIM: the old confabulation_count attribute has no reader
RUN:   rg -n "confabulation_count|_confab_history" src/
FOUND: counselor.py:1727 (write), 1732-1738 (the handler's own history)
HOLDS: yes

CLAIM: no live circuit-breaker trip or zone transition in the retained logs (D2's exposure)
RUN:   Grep "AD-488: Circuit breaker TRIPPED" and "AD-506a: Zone transition" over the live logs (count)
FOUND: 0, 0
HOLDS: yes

CLAIM: AgentRegistry has no values() or items(), and no __getattr__ that would supply them (A1)
RUN:   Grep "^class |def __|def [a-z_]+\(" src/probos/substrate/registry.py
FOUND: class AgentRegistry (18); __init__, register, unregister, get, get_by_pool, get_by_capability, all, count, crew_count, summary
HOLDS: yes: the four dict-API lookups raise AttributeError on the production registry

CLAIM: nothing else calls _resolve_agent_id_from_callsign (A1)
RUN:   Grep "_resolve_agent_id_from_callsign" over the repository, logs/ excluded
FOUND: counselor.py:1606 (call), counselor.py:1610 (def)
HOLDS: yes

CLAIM: no test drives the cascade, echo or mismatch handler; one drives wrong convergence with a dict registry (A1)
RUN:   Grep "_on_cascade_confabulation|_on_ward_room_echo|_on_observable_mismatch|_on_wrong_convergence_detected|_resolve_agent_id_from_callsign" tests/ (count)
FOUND: test_ad583_wrong_convergence.py: 3 (491, 517, 536; the dict registry at 505-509)
HOLDS: yes

CLAIM: COUNSELOR_INTERVENTION (recorded with each DM) has no subscriber in src/ (A1)
RUN:   Grep "COUNSELOR_INTERVENTION|counselor_intervention" src/probos
FOUND: event_persistence.py:208, events.py:178, counselor.py:594 (emit), importance_scorer.py:34 (a score table)
HOLDS: yes

CLAIM: the three BF-920 event handlers post to no channel and message no one but DM recipients (A1)
RUN:   Read counselor.py:1582-1608, 1965-2035
FOUND: only logger calls and _send_therapeutic_dm
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- Bug fix: external prior-art review skipped (ProbOS plumbing). The one outside fact relied on, `str()` of a mixed-in `(str, Enum)` member, is from the Python 3.12 `enum` documentation (`Enum.__str__`, `ReprEnum`).
- Internal: AD-637d/637z (the NATS subscription layer), BF-221/222/223 (subject, stream and consumer layers must agree: the same class of defect), AD-1195 (persistence lists), AD-1350 (#1637, the gauge behind `quality_gate`), BF-922 (#1639).
- Blind spots addressed: the four other deaf listeners (D1); the woken handlers' exposure (D2, section 16); a silently failed NATS subscription (D6); a dead penalty path becoming reachable (D4). Considered, deferred: making `CONFABULATION_SUPPRESSED` durable (R1); a guard test that every `add_event_listener` caller's types are known `EventType` values (R6).

## 14. Diff Reviewer: properties to verify

1. A listener registered with `EventType` members, plain strings or a mix stores exactly the members' values and the strings; `None` or an empty list still means every event. Both registration paths use the same helper.
2. In NATS mode a member filter subscribes to `system.events.<value>`, the subject `_emit_event` publishes to; a subscription task that raises is logged with its types and is still removed from `_nats_publish_tasks`.
3. `_execute_sub_task_chain` still returns the same suppressed decision; the emit carries the same keys plus `path`; a missing runtime or a raising `emit_event` never raises out of the chain.
4. `_on_confabulation_suppressed` makes no trust write, sends no message and writes no profile for any reason; it ignores the Counselor's own id; its history is pruned to one hour on every call.
5. The Counselor subscribes to 23 types (no `CONDUCT_VIOLATION`); no code path references `_on_conduct_violation`; `EventType.CONDUCT_VIOLATION` and the persistence lists are unchanged.
6. The seam test uses a booted runtime and the agent's startup-set `_runtime`; it stubs only the chain executor and the Counselor's DM sender.
7. Every replaced test says inline what it used to pin and why it changed; no test was deleted without a replacement pin.
8. (A1) The cascade seam case boots a runtime and uses the service startup built (`rt._social_verification`, wired with `emit_event_fn=runtime._emit_event`). It reaches the service only through BF-920's `check_and_alert_cascade_risk` and never calls `emit_event` itself. Its only stand-ins are the service's episodic memory and the Counselor's DM sender, and the handler spy wraps the real `_on_cascade_confabulation`. It asserts one wire event and one handling at medium and at high (not two); at low, no event and no handling, with the case shown to be low and not none; at high, one DM per resolved peer id and no other DM.
9. (A1) The four callsign handlers resolve through `AgentRegistry.get`/`all`; a value no registered agent holds is never messaged; the replaced dict-registry test says why inline; none of the four writes trust or a profile.

## 15. Acceptance criteria

- The root cause is the stringified filter (section 1), and the seam test passes through `ProbOSRuntime.start()` with the startup-set `_runtime`.
- An EVALUATE `suppress` reaches the Counselor in a booted runtime, locally and (by the subject test) over NATS.
- No suppression reason carries the penalty or the message; one test per reason.
- `CONDUCT_VIOLATION` has no subscriber, handler or penalty; the SPC store is announced inert.
- One `CASCADE_CONFABULATION_DETECTED` from `SocialVerificationService` (BF-920's only emitter), driven through `check_and_alert_cascade_risk` in a booted runtime, is handled by the Counselor exactly once at medium and high risk and not at all at low; at high risk each resolved peer gets one DM (A1).
- The cascade, wrong-convergence, echo and observable-mismatch handlers resolve agents through the runtime's `AgentRegistry` and never message a callsign no registered agent holds (A1).
- BF-921 is built on the commit that merges BF-920 (#1633) (A1).
- Before editing, the tests that pin current behaviour were grepped and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what is read after the first session (read-only)

From `%LOCALAPPDATA%\ProbOS\data\logs\probos.log` after the first vessel session on the merged build, record on #1636:
- the count of `BF-921: Output suppression recorded for` lines against `BF-206: Chain output suppressed` lines (expected equal, less the Counselor's own);
- the count of `probos.cognitive.counselor` lines by message prefix (the woken handlers' activity, D2), and any `Counselor event handler failed` or `BF-921: NATS event subscription failed` line;
- that no `BF-206: Trust penalty` line appears;
- (A1) the counts of `AD-567f: Cascade confabulation medium`, `AD-567f: Cascade confabulation high`, `AD-583g: Ward Room echo detected`, `AD-583f: Observable state mismatch`, `AD-583: Wrong convergence detected` and `AD-505: Sent therapeutic DM to` lines, and that no `Counselor event handler failed for` line names `cascade_confabulation_detected`, `ward_room_echo_detected`, `observable_state_mismatch` or `wrong_convergence_detected`. If most crew reach the hourly DM cap in most hours, file it (R7).

## 17. Not verified

- That a default `SystemConfig()` boot registers at least three crew `CognitiveAgent`s other than the Counselor, each with a callsign no other agent holds, in every test environment (the agent fleet builds them when `utility_agents.enabled`, the default; `wire_agent` sets callsigns, `agent_onboarding.py:192-194`). If not, the seam tests fail at `next(...)` or at `assert len(crew) == peers`, which is a hard stop for the Architect, not a reason to stub.
- (A1) The cascade seam case's classification (low, medium and high from one, two and three same-thread peers plus the author's episode) is read from `social_verification.py:189-190` and `:592-601` and from BF-920 round 1's executed probe of the same episode shape; it was not run here.
- Whether `register_live_event_listener` completes without NATS on an unstarted runtime (read: `_setup` skips the subscription when the bus is absent, `runtime.py:1760-1776`); not run.
- The behaviour of each woken Counselor handler in a live session (section 16 measures it).
- The `str()` behaviour was confirmed from the documentation and the venv's version, not by running the interpreter (the bridge did not allow it). Read-only check for the orchestrator: `d:/ProbOS/.venv/Scripts/python.exe -c "from probos.events import EventType; print(str(EventType.CONFABULATION_SUPPRESSED))"` prints `EventType.CONFABULATION_SUPPRESSED`.

## 18. For the register (found here, not fixed by this change)

- **R1.** `CONFABULATION_SUPPRESSED` is `GRANDFATHERED` in the persistence contract (`event_persistence.py:195`), so `events.db` cannot show suppressions; the log line is the record. Making it durable is an AD-1195 contract change for its own slice.
- **R2.** The woken Counselor handlers (D2) have never run live; section 16's first-session counts decide whether any needs its own issue.
- **R3.** `config/standing_orders/federation.md:180-182` still says a conduct violation carries a trust consequence; no mechanism implements it. The text is the Captain's; editing it is the Captain's decision.
- **R4.** The SPC store's feed (AD-522e-1) is unbuilt.
- **R5.** `_create_nats_event_subscription`'s callback logs a listener's exception at DEBUG (`runtime.py:1861-1863`), for every listener.
- **R6.** No guard test pins that every `add_event_listener` caller passes known event types; one would have caught this defect at the first member-passing caller.
- **R7.** (A1) The cascade, echo, mismatch and wrong-convergence DMs are first sent after BF-921, on detectors BF-920 reworked, whose false-positive rate is unmeasured. If section 16's first session shows the hourly DM cap reached for most crew in most hours, or crew replies disputing the prompts, that is an issue of its own (qualify the gauge or gate the DM); BF-921 does not gate them (D2).
- **R8.** (A1) `WRONG_CONVERGENCE_DETECTED`'s `agents` field does not declare whether it holds callsigns or agent ids (`events.py:990`); its producers build it from `dreaming.py:1088` (`e["agent"]`) and `proactive.py:3345-3346` (`convergence_agents`). The resolver accepts either; the schema should say which.
