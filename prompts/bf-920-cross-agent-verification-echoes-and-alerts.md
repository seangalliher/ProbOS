# BF-920: a same-thread echo is never independent on elapsed time, the cascade names its real origin, emits once and reaches the Bridge, and the observable-mismatch alert is delivered

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24

**Status:** build-ready. One issue: BF-920 (#1633). **Tier HIGH** (Architect's call; it can only be lowered by the Captain). The change rewrites `compute_anchor_independence`, a shared scoring function with seven call sites in five subsystems (dreaming, records, behavioral metrics, thread echo and the verification service). It also puts three Bridge alerts in front of the Captain that never reached it before, and it changes what the Counselor receives. **Base:** `origin/main` `26bec26d`. BF-918 (#1645) and BF-919 do not touch any file this contract edits; the §8 anchors survive their tracker entries (stated there). **Milestones:** one (M1), one gate.

**Tests:** new file `tests/test_bf920_cross_agent_verification.py` (11 functions, 13 cases). Updated: `tests/test_ad583f_observable_state.py` (the two `SystemHealthProvider` tests and their double are removed with the class, and the reason is recorded inline). Focused gate: the new file plus `tests/test_social_verification.py`, `tests/test_ad583f_observable_state.py`, `tests/test_ad583g_source_tracing.py`, `tests/test_ad583_wrong_convergence.py`, `tests/test_peer_repetition_credits.py`, `tests/test_behavioral_metrics.py`, `tests/test_counselor_activation.py`, `tests/test_ad641c_thread_priority.py` (it patches `probos.ward_room._helpers`), all at `-n 0`.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`) and the SEARCH blocks are LF, so match and write each file with its own line endings. Write new files LF.

**Pairs:** 21 code pairs in 7 files, plus one new file and 2 tracker pairs. Each SEARCH occurs exactly once in its base file on `26bec26d`.

---

## 1. Problem (re-anchored on `26bec26d`; the issue's anchors were on `4564fbd7`)

1. **Elapsed time overrides the same-thread rule.** `compute_anchor_independence` (`cognitive/social_verification.py:192`) and `check_corroboration`'s partner count (`:381`) both test `_are_independently_anchored(a, b) or _time_separated(...)`. `_are_independently_anchored` returns False for a shared thread (`:82-88`), but `_time_separated` (`:109-111`) then counts any pair more than 60 s apart. A thread whose replies are minutes apart scores 1.0, so AD-583g's echo alert (`bridge_alerts.py:578-580`, `< 0.3`) cannot fire at real conversation pacing. The tests use 1-5 s gaps (`tests/test_ad583g_source_tracing.py:128-130`, `tests/test_social_verification.py:154-155, 356-358`).
2. **`source_agent` always names the current author.** `check_peer_similarity` (`ward_room/threads.py:23-81`) builds matches with `author_id, author_callsign, body_preview, similarity, post_id` only (`:50-56`, `:69-75`). `check_cascade_risk` reads `match.get("timestamp", float("inf"))` (`social_verification.py:514`), so no peer is ever earlier than `inf`, and `source_agent` stays `author_callsign` (`:509`). `tests/test_social_verification.py:339-342` supplies made-up timestamps, so it tests only half the chain.
3. **`CASCADE_CONFABULATION_DETECTED` is emitted twice per detection.** The service emits it (`social_verification.py:609-618`, through the runtime's `emit_event_fn`, `startup/cognitive_services.py:648-652`). The helper emits it again (`ward_room/_helpers.py:41-48`) through the Ward Room emitter, which calls the same runtime `emit_event_fn` first (`startup/communication.py:425-427`). The Counselor's handler (`cognitive/counselor.py:1042-1043`, `:1582`) therefore runs twice, and on high risk it DMs the affected crew twice.
4. **The observable-mismatch Bridge alert is built and dropped.** `_helpers.py:139-144` discards the list that `check_observable_mismatch` returns (`bridge_alerts.py:608-631`).
5. **Dead entry points.** `SocialVerificationService.check_corroboration` (`:281`) and `get_verification_context` (`:622`), and `BridgeAlertService.check_cascade_risk` (`bridge_alerts.py:806`), have no production caller. `SystemHealthProvider` (`cognitive/observable_state.py:266`) is imported in `startup/finalize.py:5912` but never registered (`:5919-5923`).

Found while re-verifying, and fixed here because they sit on the lines this contract changes:
- **The echo alert says "Affected: ."** The helper passes `dataclasses.asdict(echo_result)` (`_helpers.py:94-96`). `ThreadEchoResult` has no `affected_callsigns` field (`ward_room/thread_echo.py:29-44`), yet the alert reads that key (`bridge_alerts.py:585, 600`). Once item 1 lets the alert fire, the Captain would see an empty list.
- **`cascade_enabled` has no reader.** It is declared at `config_models/knowledge.py:387` and set to `true` in `config/system.yaml:1960`, but nothing reads it. This contract wires the cascade alert to the Captain, and this flag is the switch that turns it off.
- **`SystemHealthProvider` cannot be wired as it stands.** `VitalsMonitorAgent` reports `system_health` as a float (`agents/medical/vitals_monitor.py:264-266`, also `:155`; `bridge_alerts.py:260-262` compares it with `< 0.3`). The provider compares it with strings (`observable_state.py:311, 323`), so a health claim containing "failure", "critical" or "degraded" would always read as contradicted. Its tests feed it the string `"healthy"` (`tests/test_ad583f_observable_state.py:192, 201`), a shape the monitor never produces.

## 2. Solution overview

- **One pairwise rule.** `_pair_independent(ep_a, ep_b)` says a same-thread pair is never independent, and only then applies the existing anchor rule or the time rule. Both call sites use it. `_same_thread` is the single same-thread test, and `_are_independently_anchored` uses it too.
- **Real timestamps.** Both `check_peer_similarity` queries select `created_at` and return it as `timestamp`. `check_cascade_risk`'s earliest-poster logic is unchanged, and now gets real input.
- **One cascade emitter.** The service owns `CASCADE_CONFABULATION_DETECTED` (standing order: the service emits its own state change, and an adapter does not duplicate it). The helper becomes `check_and_alert_cascade_risk`: it emits nothing and raises the Bridge alert AD-567f designed.
- **One delivery path.** `_deliver_bridge_alerts(alerts, router, tag)` in `_helpers.py` delivers the echo, mismatch and cascade alerts the same way, with log-and-degrade per alert.
- **Dead entry points:** the Bridge cascade alert is wired, `SystemHealthProvider` is removed, and `check_corroboration` and `get_verification_context` are kept and marked as not live (§3 D5).

## 3. Decisions (for the record on #1633)

| # | Item | Decision | Ranking and reason |
|---|---|---|---|
| D1 | (1) same thread vs time | **One rule, `_pair_independent`**: same thread vetoes first, then the anchor or time rule | (1) the shared helper; (2) drop `_time_separated` entirely: rejected, because it would also change every pair with no thread anchor, which dreaming's notebook entries (`dreaming.py:1167-1179`) and `test_anchor_independence_time_separation` rely on, and #1633 does not ask for that; (3) patch each call site inline: rejected, because two copies of the rule are how the defect arose. AD-567f's own prior art (circular reporting) says the same: what makes reports independent is their source, not their timing. |
| D2 | (2) cascade origin | **Matches carry `timestamp` = the row's `created_at`**, from both queries | (1) select it where the row is read; (2) look up timestamps by `post_id` inside `check_cascade_risk`: rejected, because that is Ward Room DB access from the cognitive layer; (3) sort matches by time: rejected, because `top_match` (`threads.py:613-646`, `messages.py:369-402`) relies on the similarity-descending order. |
| D3 | (3) double emission | **The service is the single emitter**; the helper's emission is removed and the helper renamed `check_and_alert_cascade_risk` (it no longer takes `emit_fn`) | (1) the service owns it: `test_cascade_event_emitted` (`tests/test_social_verification.py:552`) already pins the service's emission, and the helper's second copy reached only the runtime (a duplicate) and the Ward Room router, which ignores the type (`ward_room_router.py:416`); (2) keep the helper's and drop the service's: rejected, because it would leave the service's other consumers silent. |
| D4 | (4) mismatch alert | **Deliver it** through `_deliver_bridge_alerts`, the echo alert's existing path (`_helpers.py:97-102`) | (1) deliver: AD-583f designed the alert, and the Counselor's DM (`counselor.py:2004`) informs the crew, not the Bridge; (2) remove the call: rejected. Severity and dedup stay `check_observable_mismatch`'s own (ADVISORY at 1 failed claim, ALERT at 2 or more, 300 s per thread, AD-580 dismiss and mute). |
| D5a | (5) `BridgeAlertService.check_cascade_risk` | **Wire it** in `check_and_alert_cascade_risk` | (1) wire: AD-567f's recorded decision names it ("Bridge Alert: `check_cascade_risk()` on BridgeAlertService (ADVISORY for medium, ALERT for high)", `decisions-era-4-evolution.md:2587`); (2) remove: rejected, because it would reverse a recorded decision. The router and the alert service come from `set_echo_services`, the same late binding the echo trace uses. |
| D5b | (5) `SystemHealthProvider` | **Remove it**: the class, `_HEALTH_KEYWORDS`, the `finalize.py` import, its two tests and their `FakeVitalsMonitor` double | (1) remove: it cannot be wired correctly as written (§1, the float-vs-string mismatch), and wiring it would tell crew they are wrong on every health claim, through Counselor DMs and, after D4, Bridge alerts; (2) fix the contract and wire it: rejected for this BF, because it is a new heuristic with new thresholds, a vitals handle in `finalize.py` and its own false-contradiction review, which makes it a design AD; (3) remove only the import: rejected, because the class would stay dead. |
| D5c | (5) `check_corroboration`, `get_verification_context` | **Keep both, marked "no production caller; not live"** in their docstrings, and record them in the register | **Reframe check:** what does acceptance line (5) protect? Against surfaces that read as live and seed false premises (AD-583's premise and AD-1349's "effective witness count" both reasoned from these methods). The docstring removes that risk. (1) Keep and mark: the intended consumer is the agent-invocable verification tool AD-567f deferred (`prompts/archive/ad-567f-social-verification-protocol.md:334, 473`), and AD-1349 deferred its own use "until a consumer exists" (`prompts/ad-1349-s1-shared-error-tracing.md:783`); D1 also corrects their same-thread count, so they are right when wired. (2) Remove: rejected, because it means about 250 source lines, AD-665's privacy-reviewed provenance report (`build_provenance_report`, `ProvenanceValidationResult`), about 20 tests and the only producers of `CORROBORATION_VERIFIED` and `CORROBORATION_PROVENANCE_VALIDATED`. It would also orphan four config fields that `config/system.yaml:1957-1961`, the facade baseline and `config-reference.md` carry. (3) Wire as a crew tool: rejected, because that is a new capability under the new-capability pause. This weakens no security, governance or audit control, so it is in the envelope. **It narrows #1633's acceptance line (5) for these two items.** The orchestrator records that on the issue, and the Captain may overrule it. |
| D6 | found | **`check_cascade_risk` honours `cascade_enabled`** | It is the off switch for the alert D5a wires. Default `True` keeps the current behaviour. |
| D7 | found | **The echo alert carries `affected_callsigns`** | One merged key on the line this contract already changes; the Captain would otherwise read "Affected: .". |
| D8 | tier | **HIGH** | It changes a shared scoring contract (seven call sites) and the Captain-facing alerting. Every changed production file has mutation rows (§10). |

**Disclosed effects.**
- The Captain can now receive these alerts: a cascade alert (ADVISORY for medium, ALERT for high), an observable-mismatch alert (ADVISORY or ALERT), and the echo alert (ALERT) on threads paced over minutes. Each goes through `BridgeAlertService._should_emit` (300 s dedup, AD-580 dismiss and mute).
- The Counselor gets one cascade event per detection, so a high-risk cascade DMs each affected agent once, not twice.
- Pairs in the same thread score 0 in every `compute_anchor_independence` consumer: dream step 7g wrong-convergence detection, the dream step 9 provenance snapshot, `records_store` independence and the behavioral-metrics `independence_score`. Episode sets dominated by one Ward Room thread will score lower; that is what the score is meant to say.
- `ThreadEchoAnalyzer`'s independence becomes 0.0 for any detected echo, because all its synthetic episodes share the thread (register F-4).
- No new EventType, no config field, no schema change.

## 4. Consumers of every value this changes

| Changed value | Consumers (all on `26bec26d`) | Accepts? |
|---|---|---|
| `compute_anchor_independence` result | `social_verification.py:323, 557`; `ward_room/thread_echo.py:151`; `cognitive/dreaming.py:1180, 1406`; `knowledge/records_store.py:900`; `cognitive/behavioral_metrics.py:595` | Yes: a float in [0, 1], same type; only same-thread pairs change |
| `check_peer_similarity` match dict (+`timestamp`) | `threads.py:538-556, 559, 562, 613-646`; `messages.py:285-310, 369-402`; `social_verification.py:511-537` | Yes: an added key; every reader indexes named keys |
| `CASCADE_CONFABULATION_DETECTED` count | `counselor.py:1042`; event persistence (GRANDFATHERED, `event_persistence.py:112-469`); HXI (no consumer: `ui/src` grep is empty) | Yes: the service's payload and type value are unchanged |
| `check_and_emit_cascade_risk` → `check_and_alert_cascade_risk` | `threads.py:198-199`, `messages.py:119-120` (both changed here) | Yes |
| `SystemHealthProvider` (removed) | `finalize.py:5912` (changed here); tests (changed here) | Yes |

## 5. Tests (new file `tests/test_bf920_cross_agent_verification.py`)

| # | Test | Proves | Crosses the seam |
|---|---|---|---|
| T1 | `test_same_thread_minutes_apart_is_not_independent` | three same-thread episodes 120 s apart score 0.0 | scoring |
| T2 | `test_different_threads_keep_the_time_rule` | different threads 120 s apart score 1.0, and 20 s apart 0.0 (the time rule still discriminates) | scoring |
| T3 | `test_corroboration_counts_no_same_thread_partner` | `check_corroboration`: 3 episodes pass the gate (premise), 0 independent anchors, score 0.0 | the `:381` site |
| T4 | `test_echo_minutes_apart_is_dependent_and_alerts` | the real `ThreadEchoAnalyzer` on a minute-paced thread gives independence 0.0, and the real `check_ward_room_echo` raises one alert | analyzer → bridge |
| T5 | `test_peer_matches_carry_created_at` | real schema: the thread match and the reply match each carry their row's `created_at` | DB → matches |
| T6 | `test_cascade_source_is_the_earliest_real_poster` | the real matches from T5's DB, fed to `check_cascade_risk`, name the earliest poster, who is not first in the list | DB → matches → service |
| T7 | `test_one_cascade_event_per_detection[ThreadManager/MessageStore]` | both call sites: one event when service and store share one emitter | store → helper → service |
| T8 | `test_cascade_bridge_alert_is_delivered[ThreadManager/MessageStore]` | medium cascade → one ADVISORY `cascade_confabulation` delivered, naming the source | store → helper → bridge → router |
| T9 | `test_low_cascade_raises_no_alert_and_no_event` | boundary: one peer → no alert, no event | store → helper |
| T10 | `test_cascade_disabled_skips_the_check` | `cascade_enabled=False` → `None`, no recall | service |
| T11 | `test_echo_trace_delivers_echo_and_mismatch_alerts` | the real analyzer, verifier and bridge: echo alert then mismatch alert delivered; the echo alert names Bob and Carol | the whole `check_and_trace_echo` chain |

Removed: `TestHealthProvider` (2 tests) with the class (D5b). No existing test pins a defect this contract fixes. I checked: `test_cascade_source_agent_earliest_post` asserts correct behaviour on made-up input (T6 adds the real input); every same-thread test uses gaps of 60 s or less; `test_anchor_independence_time_separation` uses `anchors=None` pairs, which D1 leaves unchanged.

## 7. The contract

### 7.1 M1: edits to existing files

#### 7.1.1 `src/probos/cognitive/social_verification.py` (7 pairs)

**Pair S1**: the single same-thread test.

SEARCH:
```python
def _are_independently_anchored(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames represent independent observations.

    Two episodes are independently anchored if they have different
    duty_cycle_id OR different channel_id OR timestamps > 60s apart.
    Episodes sharing the same thread_id are NOT independent.
    """
    if anchors_a is None or anchors_b is None:
        return False

    # Same thread = NOT independent (same conversation)
    if (
        anchors_a.thread_id
        and anchors_b.thread_id
        and anchors_a.thread_id == anchors_b.thread_id
    ):
        return False
```
REPLACE:
```python
def _same_thread(anchors_a: Any, anchors_b: Any) -> bool:
    """BF-920: True when both anchor frames name the same non-empty thread."""
    thread_a = getattr(anchors_a, "thread_id", "") or ""
    thread_b = getattr(anchors_b, "thread_id", "") or ""
    return bool(thread_a) and thread_a == thread_b


def _are_independently_anchored(anchors_a: Any, anchors_b: Any) -> bool:
    """Check if two anchor frames represent independent observations.

    Two episodes are independently anchored if they have different
    duty_cycle_id OR different channel_id. Episodes sharing the same
    thread_id are NOT independent. The elapsed-time rule lives in
    ``_pair_independent`` (BF-920), which never applies it to a
    same-thread pair.
    """
    if anchors_a is None or anchors_b is None:
        return False

    # Same thread = NOT independent (same conversation)
    if _same_thread(anchors_a, anchors_b):
        return False
```

**Pair S2**: the one pairwise rule.

SEARCH:
```python
def _time_separated(ep_a: Any, ep_b: Any, threshold: float = 60.0) -> bool:
    """Check if two episodes are separated by more than threshold seconds."""
    return abs(getattr(ep_a, "timestamp", 0) - getattr(ep_b, "timestamp", 0)) > threshold
```
REPLACE:
```python
def _time_separated(ep_a: Any, ep_b: Any, threshold: float = 60.0) -> bool:
    """Check if two episodes are separated by more than threshold seconds."""
    return abs(getattr(ep_a, "timestamp", 0) - getattr(ep_b, "timestamp", 0)) > threshold


def _pair_independent(ep_a: Any, ep_b: Any) -> bool:
    """BF-920: the one pairwise independence rule (artifact ancestry aside).

    A same-thread pair is never independent, however far apart its posts
    are: the elapsed-time rule applies only to pairs in different threads,
    or without thread anchors. Before BF-920 both callers OR-ed
    ``_time_separated`` onto ``_are_independently_anchored``, so a
    same-thread echo spaced over minutes scored as fully independent.
    """
    a = getattr(ep_a, "anchors", None)
    b = getattr(ep_b, "anchors", None)
    if _same_thread(a, b):
        return False
    return _are_independently_anchored(a, b) or _time_separated(ep_a, ep_b)
```

**Pair S3**: `compute_anchor_independence`.

SEARCH:
```python
            elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
                independent_weight += pair_weight
```
REPLACE:
```python
            elif _pair_independent(episodes[i], episodes[j]):
                independent_weight += pair_weight
```

**Pair S4**: `check_corroboration`'s partner count.

SEARCH:
```python
                    if _are_independently_anchored(a, b) or _time_separated(ep, other):
                        independent_count += 1
                        break
```
REPLACE:
```python
                    if _pair_independent(ep, other):
                        independent_count += 1
                        break
```

**Pair S5**: `cascade_enabled` (D6).

SEARCH:
```python
        if not peer_matches:
            return None

        from probos.cognitive.anchor_quality import compute_anchor_confidence

        # Gather episodes for each matched peer
```
REPLACE:
```python
        # BF-920: cascade_enabled is this check's off switch (it had no reader).
        if not peer_matches or not self._config.cascade_enabled:
            return None

        from probos.cognitive.anchor_quality import compute_anchor_confidence

        # Gather episodes for each matched peer
```

**Pair S6**: `check_corroboration` marked not live (D5c).

SEARCH:
```python
        """Check if a claim is independently corroborated by other agents.

        Privacy: returns metadata (who, when, where) but never episode content.
        """
```
REPLACE:
```python
        """Check if a claim is independently corroborated by other agents.

        Privacy: returns metadata (who, when, where) but never episode content.

        BF-920: no production caller. Kept, not wired, for the agent-invocable
        verification tool AD-567f deferred
        (prompts/archive/ad-567f-social-verification-protocol.md); do not
        reason from it as a live path.
        """
```

**Pair S7**: `get_verification_context` marked not live (D5c).

SEARCH:
```python
        Returns a brief text block (under 200 chars) indicating whether
        the claim is verified, unverified, or at cascade risk.
        """
```
REPLACE:
```python
        Returns a brief text block (under 200 chars) indicating whether
        the claim is verified, unverified, or at cascade risk.

        BF-920: no production caller; this is the formatter for the deferred
        verification tool (see ``check_corroboration``). Not a live path.
        """
```

#### 7.1.2 `src/probos/ward_room/threads.py` (4 pairs)

**Pair T0**: docstring.

SEARCH:
```python
    Returns list of matches: [{author_id, author_callsign, body_preview, similarity, post_id}]
```
REPLACE:
```python
    Returns list of matches: [{author_id, author_callsign, body_preview, similarity, post_id, timestamp}]
    ``timestamp`` is the matched row's created_at (BF-920: the cascade check names the earliest).
```

**Pair T1**: the threads query.

SEARCH:
```python
            "SELECT id, author_id, author_callsign, body FROM threads "
            "WHERE channel_id = ? AND created_at > ? AND author_id != ? "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                    })
```
REPLACE:
```python
            "SELECT id, author_id, author_callsign, body, created_at FROM threads "
            "WHERE channel_id = ? AND created_at > ? AND author_id != ? "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                        "timestamp": row[4],  # threads.created_at (BF-920)
                    })
```

**Pair T2**: the replies query.

SEARCH:
```python
            "SELECT p.id, p.author_id, p.author_callsign, p.body FROM posts p "
            "JOIN threads t ON p.thread_id = t.id "
            "WHERE t.channel_id = ? AND p.created_at > ? AND p.author_id != ? AND p.deleted = 0 "
            "ORDER BY p.created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                    })
```
REPLACE:
```python
            "SELECT p.id, p.author_id, p.author_callsign, p.body, p.created_at FROM posts p "
            "JOIN threads t ON p.thread_id = t.id "
            "WHERE t.channel_id = ? AND p.created_at > ? AND p.author_id != ? AND p.deleted = 0 "
            "ORDER BY p.created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                        "timestamp": row[4],  # posts.created_at (BF-920)
                    })
```

**Pair T3**: the cascade call site.

SEARCH:
```python
        """AD-567f: Delegate cascade check to shared helper (BF-113 DRY)."""
        from probos.ward_room._helpers import check_and_emit_cascade_risk
        await check_and_emit_cascade_risk(
            self._social_verification, self._emit,
            author_id=author_id, author_callsign=author_callsign,
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )
```
REPLACE:
```python
        """AD-567f: Delegate cascade check to shared helper (BF-113 DRY).

        BF-920: the helper no longer emits the cascade event (the service
        owns it); it raises the Bridge alert through the bridge_alerts and
        router that set_echo_services late-binds.
        """
        from probos.ward_room._helpers import check_and_alert_cascade_risk
        await check_and_alert_cascade_risk(
            self._social_verification,
            bridge_alerts=getattr(self, '_bridge_alerts', None),
            ward_room_router=getattr(self, '_ward_room_router', None),
            author_id=author_id, author_callsign=author_callsign,
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )
```
(`getattr` follows `_check_echo_trace` at `:212-216`: these attributes exist only after `set_echo_services`.)

#### 7.1.3 `src/probos/ward_room/messages.py` (1 pair)

**Pair M1**: the cascade call site (the same text as T3; it occurs once here, at `:118-125`).

SEARCH:
```python
        """AD-567f: Delegate cascade check to shared helper (BF-113 DRY)."""
        from probos.ward_room._helpers import check_and_emit_cascade_risk
        await check_and_emit_cascade_risk(
            self._social_verification, self._emit,
            author_id=author_id, author_callsign=author_callsign,
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )
```
REPLACE:
```python
        """AD-567f: Delegate cascade check to shared helper (BF-113 DRY).

        BF-920: the helper no longer emits the cascade event (the service
        owns it); it raises the Bridge alert through the bridge_alerts and
        router that set_echo_services late-binds.
        """
        from probos.ward_room._helpers import check_and_alert_cascade_risk
        await check_and_alert_cascade_risk(
            self._social_verification,
            bridge_alerts=getattr(self, '_bridge_alerts', None),
            ward_room_router=getattr(self, '_ward_room_router', None),
            author_id=author_id, author_callsign=author_callsign,
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )
```

#### 7.1.4 `src/probos/ward_room/_helpers.py` (4 pairs)

**Pair H1**: one delivery path, and the cascade helper (D3, D5a).

SEARCH:
```python
async def check_and_emit_cascade_risk(
    social_verification: Any,
    emit_fn: Callable | None,
    *,
    author_id: str,
    author_callsign: str,
    post_body: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """Check cascade confabulation risk and emit event if medium/high (AD-567f)."""
    if not peer_matches or not social_verification:
        return
    try:
        cascade = await social_verification.check_cascade_risk(
            author_id=author_id,
            author_callsign=author_callsign,
            post_body=post_body,
            channel_id=channel_id,
            peer_matches=peer_matches,
        )
        if cascade and cascade.risk_level in ("medium", "high"):
            import dataclasses
            from probos.events import EventType as _ET
            if emit_fn:
                emit_fn(
                    _ET.CASCADE_CONFABULATION_DETECTED,
                    dataclasses.asdict(cascade),
                )
    except Exception:
        logger.debug("AD-567f: cascade check failed", exc_info=True)
```
REPLACE:
```python
async def _deliver_bridge_alerts(
    alerts: list[Any] | None, ward_room_router: Any, tag: str,
) -> None:
    """Deliver Bridge alerts through the Ward Room router (BF-920: one path).

    Log-and-degrade per alert: a failed delivery must not stop the other
    alerts, nor the Ward Room post that triggered the check.
    """
    if not alerts or not ward_room_router:
        return
    for alert in alerts:
        try:
            await ward_room_router.deliver_bridge_alert(alert)
        except Exception:
            logger.debug("%s: Bridge alert delivery failed", tag, exc_info=True)


async def check_and_alert_cascade_risk(
    social_verification: Any,
    *,
    bridge_alerts: Any,
    ward_room_router: Any,
    author_id: str,
    author_callsign: str,
    post_body: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """Check cascade confabulation risk and raise its Bridge alert (AD-567f).

    BF-920: ``SocialVerificationService.check_cascade_risk`` is the single
    owner of ``CASCADE_CONFABULATION_DETECTED``. This helper used to emit it
    a second time, so the Counselor handled every detection twice. It now
    routes the result to the Bridge alert AD-567f designed
    (``BridgeAlertService.check_cascade_risk``: medium and high only),
    which had no caller.
    """
    if not peer_matches or not social_verification:
        return
    try:
        cascade = await social_verification.check_cascade_risk(
            author_id=author_id,
            author_callsign=author_callsign,
            post_body=post_body,
            channel_id=channel_id,
            peer_matches=peer_matches,
        )
        if cascade and bridge_alerts:
            import dataclasses
            alerts = bridge_alerts.check_cascade_risk(dataclasses.asdict(cascade))
            await _deliver_bridge_alerts(alerts, ward_room_router, "AD-567f")
    except Exception:
        logger.debug("AD-567f: cascade check failed", exc_info=True)
```

**Pair H2**: docstring reference.

SEARCH:
```python
    Called after check_and_emit_cascade_risk() when peer_matches are found.
```
REPLACE:
```python
    Called after check_and_alert_cascade_risk() when peer_matches are found.
```

**Pair H3**: the echo alert through the shared path, with its affected crew (D7).

SEARCH:
```python
        # AD-583g: Bridge alert
        if bridge_alerts:
            import dataclasses
            alerts = bridge_alerts.check_ward_room_echo(
                dataclasses.asdict(echo_result),
            )
            if alerts and ward_room_router:
                for alert in alerts:
                    try:
                        await ward_room_router.deliver_bridge_alert(alert)
                    except Exception:
                        logger.debug("AD-583g: Bridge alert delivery failed", exc_info=True)
```
REPLACE:
```python
        # AD-583g: Bridge alert
        if bridge_alerts:
            import dataclasses
            # BF-920: ThreadEchoResult has no affected_callsigns field, so the
            # alert's "Affected:" list was always empty; merge it in.
            echo_alert_input = {
                **dataclasses.asdict(echo_result),
                "affected_callsigns": [step.callsign for step in echo_result.propagation_chain],
            }
            alerts = bridge_alerts.check_ward_room_echo(echo_alert_input)
            await _deliver_bridge_alerts(alerts, ward_room_router, "AD-583g")
```

**Pair H4**: the mismatch alert is delivered (D4).

SEARCH:
```python
                    if bridge_alerts:
                        bridge_alerts.check_observable_mismatch({
                            "thread_id": thread_id,
                            "claims_failed": len(failed),
                            "ground_truth_summary": "; ".join(summaries[:3]),
                        })
```
REPLACE:
```python
                    if bridge_alerts:
                        # BF-920: deliver the alert; it used to be built and dropped.
                        mismatch_alerts = bridge_alerts.check_observable_mismatch({
                            "thread_id": thread_id,
                            "claims_failed": len(failed),
                            "ground_truth_summary": "; ".join(summaries[:3]),
                        })
                        await _deliver_bridge_alerts(
                            mismatch_alerts, ward_room_router, "AD-583f",
                        )
```

#### 7.1.5 `src/probos/cognitive/observable_state.py` (2 pairs)

**Pair O1**: docstring.

SEARCH:
```python
    Each provider handles a narrow domain (games, trust, health).
```
REPLACE:
```python
    Each provider handles a narrow domain (games, trust).
```

**Pair O2**: remove `SystemHealthProvider` (D5b). The SEARCH starts at the end of `TrustStateProvider` and runs to the end of the file; its first and last lines also occur elsewhere, but the block as a whole occurs once.

SEARCH:
```python
            confidence=0.4,
        )


_HEALTH_KEYWORDS = frozenset({
    "health", "pool", "degraded", "critical", "failure",
    "offline", "monitoring",
})


class SystemHealthProvider:
    """Verify system health claims against VitalsMonitor snapshot."""

    def __init__(self, vitals_monitor: Any) -> None:
        self._vitals = vitals_monitor

    @property
    def name(self) -> str:
        return "system_health"

    async def check(
        self, claim_text: str, context: dict[str, Any]
    ) -> VerificationResult | None:
        words = set(claim_text.lower().split())
        if not words & _HEALTH_KEYWORDS:
            return None

        # Try scan_now (async) first, fall back to latest_vitals
        vitals = None
        try:
            if hasattr(self._vitals, "scan_now"):
                vitals = await self._vitals.scan_now()
        except Exception:
            logger.debug("AD-583f: scan_now failed", exc_info=True)

        if vitals is None and hasattr(self._vitals, "latest_vitals"):
            vitals = self._vitals.latest_vitals

        if not vitals:
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=None,
                ground_truth_summary="No vitals data available.",
                confidence=0.2,
            )

        system_health = vitals.get("system_health", "unknown")
        pool_health = vitals.get("pool_health", {})
        summary = f"System health: {system_health}."
        if pool_health:
            summary += f" Pool statuses: {pool_health}."

        claim_lower = claim_text.lower()
        if "failure" in claim_lower or "critical" in claim_lower:
            is_bad = system_health in ("critical", "failure", "degraded")
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=is_bad,
                ground_truth_summary=summary,
                confidence=0.8,
            )
        if "degraded" in claim_lower:
            return VerificationResult(
                provider_name=self.name,
                claim_text=claim_text,
                verified=(system_health == "degraded"),
                ground_truth_summary=summary,
                confidence=0.7,
            )

        return VerificationResult(
            provider_name=self.name,
            claim_text=claim_text,
            verified=None,
            ground_truth_summary=summary,
            confidence=0.4,
        )
```
REPLACE:
```python
            confidence=0.4,
        )
```
After this pair, the file ends with `TrustStateProvider`'s closing `        )` and one newline. `logger` stays used (`:83`), and so do `Any` and `VerificationResult`.

#### 7.1.6 `src/probos/startup/finalize.py` (1 pair)

**Pair F1**: drop the unregistered import (D5b).

SEARCH:
```python
            RecreationStateProvider,
            TrustStateProvider,
            SystemHealthProvider,
        )
```
REPLACE:
```python
            RecreationStateProvider,
            TrustStateProvider,
        )
```

#### 7.1.7 `tests/test_ad583f_observable_state.py` (2 pairs)

**Pair Q1**: remove the double that only the removed tests used.

SEARCH:
```python
class FakeVitalsMonitor:
    def __init__(self, vitals=None):
        self._vitals = vitals

    async def scan_now(self):
        return self._vitals

    @property
    def latest_vitals(self):
        return self._vitals


class FailingProvider:
```
REPLACE:
```python
class FailingProvider:
```

**Pair Q2**: remove the two tests, and record why inline.

SEARCH:
```python
# ---------------------------------------------------------------------------
# SystemHealthProvider tests
# ---------------------------------------------------------------------------


class TestHealthProvider:
    def test_detects_health_claim(self):
        from probos.cognitive.observable_state import SystemHealthProvider
        provider = SystemHealthProvider(FakeVitalsMonitor({"system_health": "healthy"}))
        result = asyncio.run(
            provider.check("system health shows degraded status", {})
        )
        assert result is not None
        assert result.provider_name == "system_health"

    def test_verifies_system_health(self):
        from probos.cognitive.observable_state import SystemHealthProvider
        provider = SystemHealthProvider(FakeVitalsMonitor({"system_health": "healthy"}))
        result = asyncio.run(
            provider.check("critical system failure detected", {})
        )
        assert result is not None
        assert result.verified is False  # Healthy, not critical


# ---------------------------------------------------------------------------
# Provider exception handling
```
REPLACE:
```python
# BF-920 (#1633): SystemHealthProvider was removed. It was never registered, and
# it compared VitalsMonitorAgent's float ``system_health`` to string labels, so
# every health claim would have read as contradicted. Its two tests fed it the
# string "healthy", a shape the monitor never produces; they went with the class.


# ---------------------------------------------------------------------------
# Provider exception handling
```

### 7.2 New file: `tests/test_bf920_cross_agent_verification.py` (M1)

```python
"""BF-920 (#1633): cross-agent verification judges same-thread echoes as
dependent, names the real cascade origin, emits one cascade event per
detection, and delivers the Bridge alerts it builds.

Production objects throughout: the Ward Room schema and
``check_peer_similarity`` for the match shape, ``SocialVerificationService``,
``ThreadManager`` and ``MessageStore`` for the call sites, and
``ThreadEchoAnalyzer``, ``ObservableStateVerifier`` and
``BridgeAlertService`` for the alerts. Only the episodic store, the Ward Room
router and one state provider are doubles.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.cognitive.observable_state import ObservableStateVerifier, VerificationResult
from probos.cognitive.social_verification import (
    SocialVerificationService,
    compute_anchor_independence,
)
from probos.config import SocialVerificationConfig
from probos.types import AnchorFrame, Episode
from probos.ward_room._helpers import check_and_trace_echo
from probos.ward_room.messages import MessageStore
from probos.ward_room.models import _SCHEMA
from probos.ward_room.thread_echo import ThreadEchoAnalyzer
from probos.ward_room.threads import ThreadManager, check_peer_similarity

CASCADE = "cascade_confabulation_detected"
ECHO = "the sensor array reports a coolant leak in sickbay"
PEERS = [
    {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
    {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
]


def _thread_anchors(thread_id: str) -> AnchorFrame:
    """Anchors rich enough for check_corroboration's 0.3 confidence gate."""
    return AnchorFrame(
        duty_cycle_id="dc-1",
        channel="ward_room",
        channel_id="ch-1",
        department="medical",
        participants=["agent-x"],
        trigger_agent="agent-x",
        trigger_type="observation",
        thread_id=thread_id,
    )


def _memory(episodes: list[Episode]) -> SimpleNamespace:
    return SimpleNamespace(recall=AsyncMock(return_value=episodes))


class _Recorder:
    """One emitter shared by the service and the store, as the runtime is."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, event_type, data) -> None:
        self.calls.append((getattr(event_type, "value", event_type), data))

    def count(self, name: str) -> int:
        return sum(1 for event_type, _ in self.calls if event_type == name)


class _Posts:
    """ThreadManagerProtocol double: returns copies (the analyzer adds keys)."""

    def __init__(self, posts: list[dict]) -> None:
        self._posts = posts

    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict]:
        return [dict(p) for p in self._posts]


class _ContradictingProvider:
    name = "test_state"

    async def check(self, claim_text, context):
        return VerificationResult(
            provider_name=self.name, claim_text=claim_text, verified=False,
            ground_truth_summary="No active games.", confidence=0.9,
        )


def _echo_posts(gap: float) -> list[dict]:
    rows = [
        ("p1", "alice", "the game state is broken and stale"),
        ("p2", "bob", "I agree the game state is broken stale"),
        ("p3", "carol", "yes the game state appears broken and stale"),
    ]
    return [
        {
            "id": pid, "thread_id": "thread-1", "author_id": author,
            "author_callsign": author.title(), "body": body,
            "created_at": 1000.0 + i * gap,
        }
        for i, (pid, author, body) in enumerate(rows)
    ]


def _medium_cascade_service(emit) -> SocialVerificationService:
    episodes = [
        Episode(id="ep-b", agent_ids=["B"], timestamp=100.0),
        Episode(id="ep-c", agent_ids=["C"], timestamp=105.0),
        Episode(id="ep-a", agent_ids=["A"], timestamp=110.0),
    ]
    return SocialVerificationService(
        episodic_memory=_memory(episodes), config=SocialVerificationConfig(), emit_event_fn=emit,
    )


async def _real_peer_matches(now: float) -> list[dict]:
    """Bravo's thread (now-120) and Charlie's earlier reply (now-300), as the schema stores them."""
    async with aiosqlite.connect(":memory:") as db:
        await db.executescript(_SCHEMA)
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            ("ch1", "medical", "department", "system", now - 900),
        )
        # The current author's own thread: excluded from matches, it holds Charlie's reply.
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t-own", "ch1", "agent-a", "Rounds", "morning rounds summary", now - 400, now - 120, "Alpha"),
        )
        await db.execute(
            "INSERT INTO posts (id, thread_id, author_id, body, created_at, author_callsign) VALUES (?, ?, ?, ?, ?, ?)",
            ("p-charlie", "t-own", "agent-c", ECHO, now - 300, "Charlie"),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t-bravo", "ch1", "agent-b", "Sensors", ECHO, now - 120, now - 120, "Bravo"),
        )
        await db.commit()
        return await check_peer_similarity(db, "ch1", "agent-a", ECHO)


# --- (1) same thread vs elapsed time -----------------------------------------------------------


def test_same_thread_minutes_apart_is_not_independent() -> None:
    episodes = [
        Episode(id=f"ep-{i}", agent_ids=[f"agent-{i}"], anchors=_thread_anchors("thread-1"),
                timestamp=1000.0 + 120.0 * i)
        for i in range(3)
    ]
    assert compute_anchor_independence(episodes) == 0.0


def test_different_threads_keep_the_time_rule() -> None:
    far = [
        Episode(id="ep-1", anchors=_thread_anchors("thread-1"), timestamp=1000.0),
        Episode(id="ep-2", anchors=_thread_anchors("thread-2"), timestamp=1120.0),
    ]
    near = [
        Episode(id="ep-3", anchors=_thread_anchors("thread-1"), timestamp=1000.0),
        Episode(id="ep-4", anchors=_thread_anchors("thread-2"), timestamp=1020.0),
    ]
    assert compute_anchor_independence(far) == 1.0
    assert compute_anchor_independence(near) == 0.0  # the time rule is what grants `far`


@pytest.mark.asyncio
async def test_corroboration_counts_no_same_thread_partner() -> None:
    episodes = [
        Episode(id=f"ep-{name}", agent_ids=[name], anchors=_thread_anchors("thread-1"),
                timestamp=1000.0 + 300.0 * i)
        for i, name in enumerate(["B", "C", "D"])
    ]
    svc = SocialVerificationService(episodic_memory=_memory(episodes), config=SocialVerificationConfig())
    result = await svc.check_corroboration("A", "coolant leak in sickbay")
    assert result.total_matching_episodes == 3  # premise: all three passed the anchor gate
    assert result.independent_anchor_count == 0
    assert result.anchor_independence_score == 0.0


@pytest.mark.asyncio
async def test_echo_minutes_apart_is_dependent_and_alerts() -> None:
    result = await ThreadEchoAnalyzer(_Posts(_echo_posts(gap=120.0))).analyze("thread-1")
    assert result.echo_detected is True  # premise
    assert result.anchor_independence_score == 0.0
    alerts = BridgeAlertService(clock=lambda: 1000.0).check_ward_room_echo(dataclasses.asdict(result))
    assert [a.alert_type for a in alerts] == ["ward_room_echo_detected"]


# --- (2) the cascade origin --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_matches_carry_created_at() -> None:
    now = time.time()
    by_callsign = {m["author_callsign"]: m for m in await _real_peer_matches(now)}
    assert set(by_callsign) == {"Bravo", "Charlie"}  # premise: one thread match, one reply match
    assert by_callsign["Bravo"]["timestamp"] == pytest.approx(now - 120)
    assert by_callsign["Charlie"]["timestamp"] == pytest.approx(now - 300)


@pytest.mark.asyncio
async def test_cascade_source_is_the_earliest_real_poster() -> None:
    matches = await _real_peer_matches(time.time())
    assert [m["author_callsign"] for m in matches] == ["Bravo", "Charlie"]  # earliest is not first
    svc = SocialVerificationService(episodic_memory=_memory([]), config=SocialVerificationConfig())
    result = await svc.check_cascade_risk("agent-a", "Alpha", ECHO, "ch1", peer_matches=matches)
    assert result is not None
    assert result.source_agent == "Charlie"


# --- (3) one event, and (5) the cascade Bridge alert ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [ThreadManager, MessageStore])
async def test_one_cascade_event_per_detection(store_cls) -> None:
    recorder = _Recorder()
    store = store_cls(db=None, emit_fn=recorder)
    store.set_social_verification(_medium_cascade_service(recorder))
    await store._check_cascade_risk(PEERS, "A", "Alpha", "post body", "ch-1")
    assert recorder.count(CASCADE) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [ThreadManager, MessageStore])
async def test_cascade_bridge_alert_is_delivered(store_cls) -> None:
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    store = store_cls(db=None, emit_fn=_Recorder())
    store.set_social_verification(_medium_cascade_service(None))
    store.set_echo_services(bridge_alerts=BridgeAlertService(clock=lambda: 1000.0), ward_room_router=router)
    await store._check_cascade_risk(PEERS, "A", "Alpha", "post body", "ch-1")
    router.deliver_bridge_alert.assert_awaited_once()
    alert = router.deliver_bridge_alert.await_args.args[0]
    assert alert.alert_type == "cascade_confabulation"
    assert alert.severity == AlertSeverity.ADVISORY
    assert "Source: Bravo" in alert.detail


@pytest.mark.asyncio
async def test_low_cascade_raises_no_alert_and_no_event() -> None:
    recorder = _Recorder()
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    episodes = [Episode(id="ep-b", agent_ids=["B"], timestamp=100.0), Episode(id="ep-a", agent_ids=["A"], timestamp=105.0)]
    store = ThreadManager(db=None, emit_fn=recorder)
    store.set_social_verification(SocialVerificationService(
        episodic_memory=_memory(episodes), config=SocialVerificationConfig(), emit_event_fn=recorder,
    ))
    store.set_echo_services(bridge_alerts=BridgeAlertService(clock=lambda: 1000.0), ward_room_router=router)
    await store._check_cascade_risk([PEERS[0]], "A", "Alpha", "post body", "ch-1")
    router.deliver_bridge_alert.assert_not_awaited()
    assert recorder.count(CASCADE) == 0


@pytest.mark.asyncio
async def test_cascade_disabled_skips_the_check() -> None:
    memory = _memory([])
    svc = SocialVerificationService(episodic_memory=memory, config=SocialVerificationConfig(cascade_enabled=False))
    assert await svc.check_cascade_risk("A", "Alpha", "post body", "ch-1", peer_matches=PEERS) is None
    memory.recall.assert_not_awaited()


# --- (4) the mismatch alert, and the echo alert's affected crew ----------------------------------


@pytest.mark.asyncio
async def test_echo_trace_delivers_echo_and_mismatch_alerts() -> None:
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    await check_and_trace_echo(
        ThreadEchoAnalyzer(_Posts(_echo_posts(gap=120.0))),
        ObservableStateVerifier([_ContradictingProvider()]),
        _Recorder(),
        BridgeAlertService(clock=lambda: 1000.0),
        router,
        thread_id="thread-1",
        channel_id="ch-1",
        peer_matches=[{"author_id": "bob"}],
    )
    delivered = [call.args[0] for call in router.deliver_bridge_alert.await_args_list]
    assert [a.alert_type for a in delivered] == ["ward_room_echo_detected", "observable_state_mismatch"]
    assert "Affected: Bob, Carol." in delivered[0].detail
```

## 8. Tracking (tracker pairs; in M1's commit)

Each pair anchors on a line that occurs once in its file. BF-918's and BF-919's tracker entries are inserted next to these lines and do not change them: `PROGRESS.md` entries go directly under the title, and `DECISIONS.md` entries go before the heading used below. After they land, each anchor is still present exactly once. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title line):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-920 (2026-10-24), closes #1633 -- cross-agent verification: a same-thread echo is never independent on elapsed time, the cascade names its real origin, emits once and reaches the Bridge, and the observable-mismatch alert is delivered.** `compute_anchor_independence` and `check_corroboration` share one pairwise rule, `_pair_independent`: a shared thread vetoes independence before the 60 s rule applies, so an echo paced over minutes scores 0.0, and AD-583g's echo alert can fire (it now names the echoing crew). `check_peer_similarity` returns each match's `created_at` as `timestamp`, so `CascadeRiskResult.source_agent` is the earliest poster, not the current author. `SocialVerificationService` is the single emitter of `CASCADE_CONFABULATION_DETECTED`; the Ward Room helper, renamed `check_and_alert_cascade_risk`, raises AD-567f's `BridgeAlertService.check_cascade_risk` alert instead of a second event. The echo, mismatch and cascade alerts are delivered through one `_deliver_bridge_alerts`. `check_cascade_risk` honours `cascade_enabled`. `SystemHealthProvider` is removed: it was never registered, and it compared the vitals monitor's float health to strings. `check_corroboration` and `get_verification_context` stay, marked not live, for the agent verification tool AD-567f deferred. New: `tests/test_bf920_cross_agent_verification.py`. Updated: `tests/test_ad583f_observable_state.py`. The contract is `prompts/bf-920-cross-agent-verification-echoes-and-alerts.md`.
```

**`DECISIONS.md`** (inserted before this heading):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-920 -- Cross-agent verification: one pairwise independence rule, real cascade origins, one cascade emitter, and delivered Bridge alerts (2026-10-24, #1633)

- *Scope.* `cognitive/social_verification.py` (`_same_thread`, `_pair_independent`, `cascade_enabled`, two not-live docstrings), `ward_room/threads.py` (match `timestamp`, the cascade call), `ward_room/messages.py` (the cascade call), `ward_room/_helpers.py` (`_deliver_bridge_alerts`, `check_and_alert_cascade_risk`, the echo and mismatch alerts), `cognitive/observable_state.py` and `startup/finalize.py` (`SystemHealthProvider` removed). Tests: new `tests/test_bf920_cross_agent_verification.py`; `tests/test_ad583f_observable_state.py` loses the removed class's two tests. Contract: `prompts/bf-920-cross-agent-verification-echoes-and-alerts.md`. Tier HIGH (a shared scoring contract, and the Captain's alerts).
- *D1 (independence).* One rule for both call sites: a pair sharing a non-empty thread is never independent; otherwise different duty cycle, different channel or more than 60 s apart, as before. Rejected: dropping the time rule (it would change every pair without thread anchors), and two inline fixes.
- *D2-D3 (origin and emission).* Matches carry their row's `created_at`. The service owns the cascade event (stores and services emit their own state changes; adapters do not duplicate them); the helper only raises the Bridge alert.
- *D4-D5 (alerts and dead entry points).* The mismatch alert and AD-567f's cascade alert are delivered on the echo alert's path. `SystemHealthProvider` is removed, because it cannot be wired as written (float health versus string labels; every health claim would read as contradicted). `check_corroboration` and `get_verification_context` are kept and marked not live for the deferred agent verification tool. Removing them would take AD-665's provenance report, about 20 tests and four config fields with them, and wiring them is a new capability. This narrows #1633's acceptance line (5) for those two; the Captain may overrule.
- *Disclosed effects.* The Captain can now receive cascade (ADVISORY/ALERT), observable-mismatch and minute-paced echo alerts, all under `_should_emit` dedup and AD-580 suppression. The Counselor handles each cascade once. Same-thread pairs score 0 in every `compute_anchor_independence` consumer (dream steps 7g and 9, records, behavioral metrics, thread echo).
- *Reversal.* Revert the BF-920 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in the commit. Verify them with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**`docs/development/roadmap.md`:** no row (the Bug Tracker has no `BF-9xx` rows; BF-916's and BF-917's precedent).

## 9. What this does NOT change

- AD-1349 (#1634): no effective-witness count, no shared-detail tracing, no change to `check_peer_similarity`'s similarity or window.
- `ThreadEchoAnalyzer`'s algorithm, its thresholds and its synthetic anchors (register F-4).
- `BridgeAlertService`'s methods, severities, dedup keys and cooldowns; `WardRoomRouter.deliver_bridge_alert`.
- The Counselor's handlers; `CascadeRiskResult` and its payload; any EventType; `event_persistence.py`.
- `check_corroboration`'s and `get_verification_context`'s behaviour, apart from D1's same-thread count; `build_provenance_report`; every config field; `config/system.yaml`.
- `RecreationStateProvider`, `TrustStateProvider`, `ObservableStateVerifier`; the `finalize.py` providers list and the `set_echo_services` condition (register F-3).
- The orientation text (register F-2).

## 10. Mutation rows

Tier HIGH: every changed production file has rows. Run each row on the contract-applied tree after an unmutated baseline run passes, against `tests/test_bf920_cross_agent_verification.py`, and restore the file before the next row. After §7, each Line cell occurs exactly once in its file, both as a substring and as a whole line.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | `src/probos/cognitive/social_verification.py` | `if _same_thread(a, b):` | `if False:` | T1; T3; T4; T11 |
| R2 | `src/probos/cognitive/social_verification.py` | `return bool(thread_a) and thread_a == thread_b` | `return False` | T1; T3; T4 |
| R3 | `src/probos/cognitive/social_verification.py` | `elif _pair_independent(episodes[i], episodes[j]):` | `elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):` | T1; T4; T11 |
| R4 | `src/probos/cognitive/social_verification.py` | `if _pair_independent(ep, other):` | `if _are_independently_anchored(a, b) or _time_separated(ep, other):` | T3 |
| R5 | `src/probos/cognitive/social_verification.py` | `return _are_independently_anchored(a, b) or _time_separated(ep_a, ep_b)` | `return _are_independently_anchored(a, b)` | T2 |
| R6 | `src/probos/cognitive/social_verification.py` | `if not peer_matches or not self._config.cascade_enabled:` | `if not peer_matches:` | T10 |
| R7 | `src/probos/ward_room/threads.py` | `"timestamp": row[4],  # threads.created_at (BF-920)` | `"timestamp_unused": row[4],` | T5 |
| R8 | `src/probos/ward_room/threads.py` | `"timestamp": row[4],  # posts.created_at (BF-920)` | `"timestamp_unused": row[4],` | T5; T6 |
| R9 | `src/probos/ward_room/threads.py` | `bridge_alerts=getattr(self, '_bridge_alerts', None),` | `bridge_alerts=None,` | T8 `[ThreadManager]` |
| R10 | `src/probos/ward_room/messages.py` | `bridge_alerts=getattr(self, '_bridge_alerts', None),` | `bridge_alerts=None,` | T8 `[MessageStore]` |
| R11 | `src/probos/ward_room/_helpers.py` | `alerts = bridge_alerts.check_cascade_risk(dataclasses.asdict(cascade))` | `alerts = []` | T8 |
| R12 | `src/probos/ward_room/_helpers.py` | `await _deliver_bridge_alerts(alerts, ward_room_router, "AD-567f")` | `pass` | T8 |
| R13 | `src/probos/ward_room/_helpers.py` | `await _deliver_bridge_alerts(alerts, ward_room_router, "AD-583g")` | `pass` | T11 |
| R14 | `src/probos/ward_room/_helpers.py` | `mismatch_alerts, ward_room_router, "AD-583f",` | `[], ward_room_router, "AD-583f",` | T11 |
| R15 | `src/probos/ward_room/_helpers.py` | `await ward_room_router.deliver_bridge_alert(alert)` | `pass` | T8; T11 |
| R16 | `src/probos/ward_room/_helpers.py` | `"affected_callsigns": [step.callsign for step in echo_result.propagation_chain],` | `"affected_callsigns": [],` | T11 |

Not rows: D3's removed emission, D5b's removed class and F1's removed import are deletions, so no line replacement can restore them. T7 guards D3 (re-adding the helper's `emit_fn(...)` makes it count 2), and the Absence checks after the build (§15 item 6) guard D5b and F1. The docstring pairs (S6, S7, T0, H2, O1) have no behaviour to mutate.

## 11. Verified Against Codebase (2026-10-24, `origin/main` `26bec26d`, clean detached tree)

```
Read src/probos/cognitive/social_verification.py (650 lines)
  72-88:   def _are_independently_anchored ... "# Same thread = NOT independent" ... anchors_a.thread_id == anchors_b.thread_id
  109-111: def _time_separated(ep_a, ep_b, threshold: float = 60.0)
  192:     elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
  281:     async def check_corroboration(
  289-292: docstring "Check if a claim is independently corroborated ... never episode content."
  381:     if _are_independently_anchored(a, b) or _time_separated(ep, other):
  485:     async def check_cascade_risk(
  499-500: if not peer_matches: / return None
  509:     source_agent = author_callsign
  514:     match_ts = match.get("timestamp", float("inf"))
  535-537: if match_ts < earliest_ts: ... source_agent = match_callsign
  609-618: self._emit_event(EventType.CASCADE_CONFABULATION_DETECTED.value, dataclasses.asdict(result))
  622:     async def get_verification_context(
  630-631: "Returns a brief text block (under 200 chars) ... at cascade risk."
Read src/probos/ward_room/_helpers.py (147 lines)
  20-50:   async def check_and_emit_cascade_risk(... emit_fn ...) ... emit_fn(_ET.CASCADE_CONFABULATION_DETECTED, ...)
  66:      Called after check_and_emit_cascade_risk() when peer_matches are found.
  91-102:  # AD-583g: Bridge alert ... check_ward_room_echo(dataclasses.asdict(echo_result)) ... deliver_bridge_alert
  107:     thread_echo_analyzer._thread_manager.get_thread_posts_temporal(
  139-144: bridge_alerts.check_observable_mismatch({...})   (result discarded)
Read src/probos/ward_room/threads.py
  23-29:   async def check_peer_similarity(...)  docstring "[{author_id, author_callsign, body_preview, similarity, post_id}]"
  42-56:   "SELECT id, author_id, author_callsign, body FROM threads " ... "post_id": row[0],
  60-75:   "SELECT p.id, p.author_id, p.author_callsign, p.body FROM posts p " ... "post_id": row[0],
  180-191: def set_echo_services(... bridge_alerts ..., ward_room_router ...)
  193-204: _check_cascade_risk -> check_and_emit_cascade_risk(self._social_verification, self._emit, ...)
  212-216: getattr(self, '_thread_echo_analyzer', None) ... getattr(self, '_bridge_alerts', None) ...
  559, 562: await self._check_cascade_risk(...) / await self._check_echo_trace(...)
  613-646: top_match = peer_matches[0] ... top_match['author_callsign'] / ['similarity'] / .get("post_id", "")
Read src/probos/ward_room/messages.py
  24-34:   MessageStore.__init__(self, db, emit_fn, ...)
  57-68:   def set_echo_services(...)
  114-125: _check_cascade_risk -> check_and_emit_cascade_risk(self._social_verification, self._emit, ...)
Read src/probos/ward_room/thread_echo.py
  29-44:   ThreadEchoResult fields (no affected_callsigns)
  139-151: SimpleNamespace(anchors=SimpleNamespace(thread_id=thread_id), timestamp=...) -> compute_anchor_independence(episodes)
Read src/probos/bridge_alerts.py
  61-76:   BridgeAlertService.__init__(cooldown_seconds=300, ..., *, clock=time.monotonic)
  92-107:  _should_emit (AD-580 suppression, cooldown)
  260-262: sys_health = vitals_data.get("system_health") ... if sys_health < 0.3:
  574-606: check_ward_room_echo ... independence >= 0.3 -> [] ... affected = echo_result.get("affected_callsigns", []) ... f"Affected: {', '.join(affected)}."
  608-631: check_observable_mismatch ... ADVISORY / ALERT (claims_failed >= 2) ... dedup_key state_mismatch:{thread_id}
  806-835: check_cascade_risk ... medium/high only ... alert_type="cascade_confabulation" ... detail=f"Source: {source}. Affected: ..."
Read src/probos/cognitive/observable_state.py (334 lines)
  35:      Each provider handles a narrow domain (games, trust, health).
  47-88:   ObservableStateVerifier(providers, *, max_claims) / verify_claims(claims, context)
  251-257: TrustStateProvider's last return (confidence=0.4)
  260-334: _HEALTH_KEYWORDS ... class SystemHealthProvider ... is_bad = system_health in ("critical", "failure", "degraded")
Read src/probos/agents/medical/vitals_monitor.py
  264-266: metrics["system_health"] = (sum(active_confs) / len(active_confs) if active_confs else 1.0)
Read src/probos/startup/finalize.py
  5907-5913: from probos.cognitive.observable_state import (ObservableStateVerifier, RecreationStateProvider, TrustStateProvider, SystemHealthProvider,)
  5919-5923: providers.append(RecreationStateProvider(...)) / providers.append(TrustStateProvider(...))
  5940-5946: if runtime.ward_room and (thread_echo or observable_verifier): runtime.ward_room.set_echo_services(... bridge_alerts=getattr(runtime, 'bridge_alerts', None), ward_room_router=ward_room_router)
  5410-5427: JetStream consumer "wardroom.events.>" -> ward_room_router.route_event_coalesced
Read src/probos/startup/communication.py
  425-427: def _ward_room_emit(event_type, data): emit_event_fn(event_type, data)   (then NATS / router)
Read src/probos/startup/cognitive_services.py
  648-652: SocialVerificationService(episodic_memory=..., config=config.social_verification, emit_event_fn=emit_event_fn)
Read src/probos/ward_room_router.py
  416:     if event_type not in ("ward_room_thread_created", "ward_room_post_created"): return
  1181-1227: deliver_bridge_alert(alert) -> create_thread in "ship" channel as "captain"; Captain notification for ADVISORY/ALERT
Read src/probos/cognitive/counselor.py
  1042-1043: elif event_type == EventType.CASCADE_CONFABULATION_DETECTED.value: await self._on_cascade_confabulation(data)
  1598-1607: if risk_level == "high": ... for agent_callsign in affected: ... DM
Read src/probos/config_models/knowledge.py
  378-396: class SocialVerificationConfig ... cascade_enabled: bool = True ...
Read src/probos/types.py
  496-523: class AnchorFrame ... duty_cycle_id, channel_id, trigger_type, thread_id: str = ""
  661-670: class Episode ... id, timestamp, user_input, agent_ids
Read src/probos/ward_room/models.py
  106-139: CREATE TABLE threads (... created_at REAL NOT NULL ...) / posts (... created_at REAL NOT NULL, deleted ..., author_callsign ...)
Read decisions-era-4-evolution.md
  2587:    - Bridge Alert: `check_cascade_risk()` on BridgeAlertService (ADVISORY for medium, ALERT for high)
Read tests/test_ad583f_observable_state.py (394 lines)
  43-53:   class FakeVitalsMonitor   184-207: SystemHealthProvider tests (FakeVitalsMonitor({"system_health": "healthy"}))
Read tests/test_social_verification.py
  331-347: test_cascade_source_agent_earliest_post (hand-made "timestamp")   416-421: time separation with anchors=None
Read tests/test_peer_repetition_credits.py
  170-179: aiosqlite ":memory:" + _SCHEMA fixture; 187-191 channels insert columns
grep pyproject.toml: 181: asyncio_mode = "auto"
git rev-parse --short=8 HEAD: 26bec26d ; git status --short: (clean)
```

## Absence Verified (2026-10-24)

```
CLAIM: check_corroboration and get_verification_context have no production caller
RUN:   Grep "check_corroboration|get_verification_context" over src/
FOUND: social_verification.py:281, 622, 633 (definitions and the internal call only)
HOLDS: yes

CLAIM: BridgeAlertService.check_cascade_risk has no caller
RUN:   Grep "bridge_alerts\.check_|\.check_cascade_risk\(" over src/
FOUND: _helpers.py:34 is SocialVerificationService.check_cascade_risk; no bridge_alerts.check_cascade_risk call; bridge_alerts.py:806 is the definition
HOLDS: yes

CLAIM: SystemHealthProvider is never registered and has no other importer
RUN:   Grep "SystemHealthProvider|FakeVitalsMonitor" over the repo (prompts/ excluded)
FOUND: observable_state.py:266; finalize.py:5912; tests/test_ad583f_observable_state.py:43, 185, 191, 192, 200, 201; two historical docs (decisions-era-4-evolution.md:3249, roadmap-era-5-completed.md:4463)
HOLDS: yes (the docs are history, left unchanged)

CLAIM: nothing reads cascade_enabled
RUN:   Grep "cascade_enabled|cascade_cooldown_seconds|expose_episode_content" over src/
FOUND: knowledge.py:387 (declaration); the cascade_cooldown_seconds hits are consensus/trust.py and emergence.py's own fields
HOLDS: yes

CLAIM: peer matches carry no timestamp
RUN:   Read threads.py:42-75
FOUND: keys author_id, author_callsign, body_preview, similarity, post_id only
HOLDS: yes

CLAIM: the helper's second cascade emission reaches no consumer the service's does not
RUN:   Grep "wardroom\.events" over src/; Read ward_room_router.py:388-417; Grep "cascade_confabulation|observable_state_mismatch" over ui/src
FOUND: finalize.py:5421 (router consumer), communication.py:440, nats.py:66; the router returns for any type but thread/post created (:416); ui/src: no files
HOLDS: yes

CLAIM: no test calls the Ward Room helpers or the stores' cascade/echo methods, and no source-scan test reads the changed files
RUN:   Grep "check_and_emit_cascade_risk|check_and_trace_echo|_check_cascade_risk|_check_echo_trace|set_echo_services" over tests/; Grep "ward_room[./]_helpers|cognitive/observable_state|cognitive/social_verification|ward_room/threads\.py|ward_room/messages\.py" over tests/
FOUND: none of the first; the second finds only tests/test_ad641c_thread_priority.py:354 (patches resolve_author_department, unchanged)
HOLDS: yes

CLAIM: the new names are free
RUN:   Grep "check_and_alert_cascade_risk|_deliver_bridge_alerts|_pair_independent|_same_thread" over the repo
FOUND: only unrelated "check_same_thread" (sqlite) and test names containing "same_thread"
HOLDS: yes

CLAIM: events.db cannot answer how often these detections happen
RUN:   Read event_persistence.py:112-469 (GRANDFATHERED)
FOUND: CASCADE_CONFABULATION_DETECTED (:187), OBSERVABLE_STATE_MISMATCH (:318), PEER_REPETITION_DETECTED (:348), WARD_ROOM_ECHO_DETECTED (:450) are all GRANDFATHERED
HOLDS: yes, so their absence there is not evidence
```

BF number: BF-920 is #1633's own title. `gh issue list --state all --search "BF-920 in:title"` → #1633 only. `git log --all -i --grep=BF-92` → only AD-1349 and AD-1350 subjects that cite BF-920 (#1633) and BF-921 (#1636). `prompts/bf-91*.md` ends at bf-917, and no `prompts/bf-92*.md` exists before this file.

## 12. Prior Art and Blind Spots

- **Internal, absorbed:** AD-567f (`decisions-era-4-evolution.md:2567-2589`) and its archive prompt: the same-thread rule, the Bridge cascade alert, and the deferred agent tool (D1, D5a, D5c). AD-583g (`thread_echo.py`) and AD-583f (`observable_state.py`): D4 and D5b. AD-665 provenance: kept intact (D5c). AD-1349's F1-F5 (`prompts/ad-1349-s1-shared-error-tracing.md:788-796`): this issue's source. The 2026-04-08 Medical cascade case study: the motivating incident.
- **External:** skipped. This is ProbOS plumbing, and the one transferable idea (circular reporting: independence comes from the source, not the timing) is already AD-567f's prior art. `docs/research/reference-projects.md` was not reviewed: the rule applies to design ADs, and this is a BF (date used 2026-10-24).
- **Blind spots named:** (a) thread echo's independence is structurally 0 after D1 (F-4); (b) a delivered alert is posted in the ship channel as "captain", and that post goes through peer similarity. It is bounded by the 300 s dedup and by text unlike crew posts, as the echo alert already is; (c) behavioral-metrics independence falls for thread-dominated episode sets (disclosed); (d) the cascade alert needs `set_echo_services`, which runs only when echo analysis or observable verification is on (F-3; both are on by default); (e) the newly delivered alerts reach Captain notifications, and AD-580 mute and dismiss apply; (f) the `TrustStateProvider` heuristic's verdicts become visible to the Captain through D4 (F-5).

## 13. Premise checks that need the live vessel

**None.** No claim in this design depends on live data. The one quantity a live read could add is how often the newly delivered alerts would fire. That would not change the design (dedup, AD-580 suppression), and `events.db` cannot answer it, because all four event types are GRANDFATHERED (Absence Verified). AD-1349 already measured the upstream gate on the April data: 0 peer matches in 241 items.

## 14. Diff Reviewer: properties to verify

1. For every caller of `compute_anchor_independence` (§4), a pair sharing a non-empty `thread_id` adds no independence whatever its timestamps; pairs in different threads, or without thread ids, score exactly as before.
2. `check_peer_similarity` keeps every existing key and adds `timestamp` equal to the row's `created_at` for both the thread and the reply queries; every reader in §4 accepts the dict.
3. On both the `ThreadManager` and the `MessageStore` paths, a medium or high detection produces exactly one `CASCADE_CONFABULATION_DETECTED`, emitted by the service with its unchanged payload, and the Counselor still receives it.
4. Every Bridge alert built in `_helpers.py` is delivered through `ward_room_router.deliver_bridge_alert`. A failed delivery does not stop later alerts, nor the Ward Room post, and nothing is delivered when the router or the alert service is absent.
5. The cascade alert's severity, dedup and suppression are `BridgeAlertService`'s own; low and none produce no alert.
6. `cascade_enabled=False` stops the cascade check and its alert; the default keeps the current behaviour.
7. Nothing anywhere imports `SystemHealthProvider`, `_HEALTH_KEYWORDS` or `FakeVitalsMonitor` after the change, and `observable_state.py` still ends cleanly after `TrustStateProvider`.
8. No test was deleted except the removed class's two, whose reason is recorded inline; no existing assertion was weakened.
9. `check_corroboration` and `get_verification_context` change only by D1's same-thread count and their docstrings.
10. No new EventType, config field, persisted schema or public signature outside the renamed module-private helper.

## 15. Acceptance criteria

1. (1) A same-thread pair is never independent on elapsed time alone: T1, T3 and T4 use gaps of minutes, and AD-583g's echo alert fires on such a thread (T4, T11).
2. (2) Peer matches carry their real timestamp and `source_agent` names the earliest poster, tested on the real schema and match shape (T5, T6).
3. (3) One `CASCADE_CONFABULATION_DETECTED` per detection on both call sites (T7).
4. (4) The observable-mismatch alert is delivered the way the echo alert is (T11).
5. (5) `BridgeAlertService.check_cascade_risk` is wired (T8, T9); `SystemHealthProvider` is removed; `check_corroboration` and `get_verification_context` are kept and marked, a narrowing recorded on #1633 (D5c). No effective-witness count is added.
6. After the build, a repo-wide search for `SystemHealthProvider|check_and_emit_cascade_risk|FakeVitalsMonitor` finds hits only in historical docs and `prompts/`.
7. All 16 mutation rows are killed by their named tests; the focused gate (header) passes at `-n 0`; one receipted broad gate for the issue.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Not verified

- No test was run (instructed). Each SEARCH block was copied from a Read of `26bec26d`; that each occurs exactly once is for the orchestrator's tool to confirm.
- That every new test fails on the base tree. Each is designed to (T1, T3 and T4 score 1.0 there; T5 and T6 lack the key; T7 counts 2; T8 and T11 see no delivery; T10 recalls), but this was not run.
- How the runtime's `emit_event` treats an enum type versus a string value. D3 leaves the service's `.value` form, which the Counselor already matches.
- Whether AD-979d's cross-agent recall gives crew a real way to "check whether other crew members have independently observed the same thing" (`orientation.py:366-369`). See F-2.

## 17. For the register

| # | Finding | Where |
|---|---|---|
| F-1 | `SocialVerificationConfig.cascade_cooldown_seconds` has no reader; the Bridge cooldown is `BridgeAlertService`'s own 300 s. | `config_models/knowledge.py:389` |
| F-2 | Crew orientation says "You can check whether other crew members have independently observed the same thing". The method behind that (`check_corroboration`) has no caller. Check AD-979d, then correct the text or build the tool. | `cognitive/orientation.py:363-370` |
| F-3 | The cascade Bridge alert depends on `set_echo_services`, called only when echo analysis or observable verification is enabled. With both off, the cascade alert stops silently. | `startup/finalize.py:5940` |
| F-4 | `ThreadEchoAnalyzer` builds synthetic episodes that all share the thread, so after D1 its independence is always 0.0, and the echo alert's `< 0.3` gate reduces to "echo detected". Real per-post anchors would make it discriminate (AD-1349 territory). | `ward_room/thread_echo.py:139-151` |
| F-5 | `TrustStateProvider`'s keyword verdicts (any score below 0.3 confirms "declining"; "anomaly" is a 2σ test) now reach the Bridge through D4; their false-contradiction rate is unmeasured. | `cognitive/observable_state.py:190-257` |
| F-6 | `check_and_trace_echo` reads `thread_echo_analyzer._thread_manager` (a private attribute across modules). | `ward_room/_helpers.py:107` |
| F-7 | `CascadeConfabulationEvent.channel_id` is never filled: the service's payload is `asdict(CascadeRiskResult)`, which has no channel. | `events.py:1088`; `social_verification.py:615` |
| F-8 | `CORROBORATION_VERIFIED` and `CORROBORATION_PROVENANCE_VALIDATED` have no live producer while `check_corroboration` has no caller. | `events.py:224-225` |
