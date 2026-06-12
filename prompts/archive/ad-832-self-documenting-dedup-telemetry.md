# AD-832 — Self-Documenting Pipeline Dedup Telemetry

**Status:** Ready
**Dependencies:** BF-237 (closed), BF-238 (closed), AD-664 (event_log `data` payload)
**Estimated tests:** 1 modified assertion + 2 new assertions (benign-marker payload)

## Problem

The ward-room pipeline emits a single telemetry event when BF-237's per-invocation
post budget suppresses a redundant main post (the action extractor already posted a
`[REPLY]`/`[MOVE]` in the same invocation). The event is **working as designed** — it
is a dedup *success* signal, not a fault. But three surface details make it read like
an error to any observer (human or agent) scanning the event log:

1. **Log level is `warning`** ([`ward_room_pipeline.py:346`](../src/probos/ward_room_pipeline.py#L346)) for expected, healthy behavior.
2. **Event name `pipeline_post_budget_exceeded`** ([`ward_room_pipeline.py:361`](../src/probos/ward_room_pipeline.py#L361)) — the words "budget" + "exceeded" pattern-match as a resource-exhaustion fault.
3. **`detail` carries only `thread_id=...`** — no statement that this is benign/expected.

This has a concrete, observed cost. On 2026-05-31 a validation pass found **~13 of 18**
agent-authored improvement proposals in the Ward Room "Improvement Proposals" channel
were a single confabulation cascade: multiple crew agents independently read this benign
event in the event log, classified it as a recurring "oracle reliability constraint" /
"pipeline budget exhaustion" fault, and spun up cross-department investigations and
proposals around a non-issue. The root cause is observability framing, not logic.

The emission site is the **only** producer of this event
(`grep -rn pipeline_post_budget_exceeded src/` → one hit, line 361) and **no code
consumes it by name** — it is purely observational. The only string-coupling is a single
test assertion. This makes a rename + enrichment safe.

## Solution

Make the event self-documenting so it can never again be mistaken for a fault:

1. Drop the log level from `warning` → `info`, and reword the message to state it is
   expected dedup behavior.
2. Rename the event `pipeline_post_budget_exceeded` → `pipeline_duplicate_post_suppressed`
   (descriptive of the *action*, not an error condition).
3. Enrich `detail` with an explicit benign statement.
4. Attach a structured `data` payload (AD-664) carrying machine-readable benign markers
   so the oracle / knowledge-graph layer and any agent reading the event has unambiguous
   signal: `severity="info"`, `benign=True`, `reason="action_extractor_already_posted"`.

This does NOT change any control flow — the suppression itself (BF-237) and the
BF-238 telemetry counter are untouched. Only the human/agent-facing framing changes.

## Implementation

### Section 1 — Reframe the log + event emission

File: `src/probos/ward_room_pipeline.py`

```python
===MODIFY: src/probos/ward_room_pipeline.py===
===SEARCH===
        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            logger.warning(
                "BF-237: Suppressing main post for %s — action extractor already posted in this invocation",
                agent.agent_type,
            )
            # BF-238: Aggregate counter + threshold-alert surface.
            if self._post_budget_telemetry is not None:
                self._post_budget_telemetry.record_exhaustion(
                    agent.agent_type, thread_id,
                )
            # BF-237: Emit telemetry event for observability
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_post_budget_exceeded",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=f"thread_id={thread_id}",
                    )
                except Exception:
                    logger.debug("BF-237: telemetry log failed", exc_info=True)
===REPLACE===
        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            # AD-832: This is expected dedup behavior, not a fault. Logged at INFO.
            logger.info(
                "BF-237: Deduplicated main post for %s — action extractor already "
                "posted in this invocation (working as designed, no fault)",
                agent.agent_type,
            )
            # BF-238: Aggregate counter + threshold-alert surface.
            if self._post_budget_telemetry is not None:
                self._post_budget_telemetry.record_exhaustion(
                    agent.agent_type, thread_id,
                )
            # AD-832: Emit self-documenting telemetry. Renamed from the
            # fault-sounding "pipeline_post_budget_exceeded" so observers (human or
            # agent) reading the event log cannot mistake a dedup success for a
            # reliability constraint. The structured payload carries explicit
            # benign markers for the oracle/knowledge-graph layer.
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_duplicate_post_suppressed",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=(
                            f"thread_id={thread_id} — duplicate main post suppressed "
                            "(dedup working as designed; action extractor already "
                            "posted this invocation; this is not a fault)"
                        ),
                        data={
                            "severity": "info",
                            "benign": True,
                            "reason": "action_extractor_already_posted",
                            "thread_id": thread_id,
                            "category": "pipeline_dedup",
                        },
                    )
                except Exception:
                    logger.debug("AD-832: telemetry log failed", exc_info=True)
===END REPLACE===
```

### Section 2 — Update the test assertion

File: `tests/test_bf237_pipeline_post_budget.py`

```python
===MODIFY: tests/test_bf237_pipeline_post_budget.py===
===SEARCH===
    event_log.log.assert_called_once()
    call_kwargs = event_log.log.call_args[1]
    assert call_kwargs["category"] == "pipeline"
    assert call_kwargs["event"] == "pipeline_post_budget_exceeded"
===REPLACE===
    event_log.log.assert_called_once()
    call_kwargs = event_log.log.call_args[1]
    assert call_kwargs["category"] == "pipeline"
    # AD-832: event renamed + carries self-documenting benign markers.
    assert call_kwargs["event"] == "pipeline_duplicate_post_suppressed"
    assert call_kwargs["data"]["benign"] is True
    assert call_kwargs["data"]["severity"] == "info"
    assert call_kwargs["data"]["reason"] == "action_extractor_already_posted"
===END REPLACE===
```

## Tests

- `test_bf237_pipeline_post_budget.py` existing dedup-emission test (updated above):
  asserts the new event name + the three benign-marker fields in `data`.
- Full BF-237 file must remain green: `pytest tests/test_bf237_pipeline_post_budget.py -v -n 0`.

## What This Does NOT Change

- BF-237 suppression logic / `PostBudget` contract — untouched.
- BF-238 telemetry counter (`record_exhaustion`) — untouched.
- The similarity guard (BF-197), novelty gate (AD-493), recreation commands (BF-123),
  bracket stripping (BF-174) — all untouched.
- No new config, no new event-log schema (uses the existing AD-664 `data` param).
- Does NOT touch the improvement-proposal pipeline or the wardroom router.

## Tracking

- `PROGRESS.md` — add AD-832 CLOSED entry (one line).
- `decisions-era-5-unification.md` — append AD-832 with the root-cause note
  (benign dedup telemetry misclassified as fault → confabulation cascade in the
  Improvement Proposals channel on 2026-05-31).

## Acceptance Criteria

1. `grep -rn pipeline_post_budget_exceeded src/ tests/` returns **zero** hits.
2. `pytest tests/test_bf237_pipeline_post_budget.py -v -n 0` passes.
3. The emitted event carries `data["benign"] is True`.
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
grep -n "pipeline_post_budget_exceeded" src/probos/ward_room_pipeline.py
  361:                        event="pipeline_post_budget_exceeded",

grep -rn "pipeline_post_budget_exceeded" src/    # one producer, zero consumers
  src/probos/ward_room_pipeline.py:361

ward_room_pipeline.py:345-365   # if budget.spent: warning + record_exhaustion + event_log.log
substrate/event_log.py:142-153  # async def log(..., detail, *, data: dict|None)  (AD-664)
tests/test_bf237_pipeline_post_budget.py:318   # assert event == "pipeline_post_budget_exceeded"
```
