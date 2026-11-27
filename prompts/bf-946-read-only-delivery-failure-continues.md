# BF-946 (#1723): a read-only call's failed delivery comes back to the agent as an error, and the run goes on

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-02
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-02, before the build: this Status line records the Captain's decision R; the P2-5 and P5-3 docstrings no longer call `is_tier_1_tool_call` "the one existing classifier"; the reversal lines name the BF-946 commits instead of counting them; G1's expected count and the estimated test count are corrected to what the oracle measured (G1 on M1's stage: 5 passed and 7 xfailed, 12 cases; the new file holds 7 test functions in M1 and 8 after M2). Amendment A3 by `claude-architect` (Claude Code, Opus 5.5), 2026-11-02, before the build: sentences of the contract that were false of the head or went beyond their source are corrected or deleted (§1.2, §1.3, §2, §3, §5's M3 subject, §6, §7.5's R-b and R-c, §8's merge note, §9, §10's prefix note, §14, §15, §16, and absence records A1, A3, A4, A5 and A8), and so is the text inside N1-1, P2-4, P3-4, P4-1, P4-2, P5-1, P5-5 and P5-6 that said more than the code; no pair's behaviour or SEARCH changed. Repair after review round 1 by the orchestrator (Claude Sonnet 5.5), 2026-11-02: the `_delivery_stop` docstring in P2-5's REPLACE no longer says the failure that ends the run is the first one issued; no behaviour and no SEARCH changed.
**Status:** M1 to M5 ready to build as one batch: the Captain decided R-a on #1723 (2026-11-02, 22:57Z), so M5 is built with M1 to M4 (§3, §7.5). **Base:** drafted on `0ac7bdf3` (AD-1356 S1's head); built on main after AD-1356 S1 and S2 merge. **Dependencies:** none (independent of AD-1356). **Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD, M4 STANDARD, M5 HIGH. **Estimated tests:** 1 new file (7 test functions in M1, 1 more in M2); M5 edits that file and `tests/test_ad1240_tool_result_delivery.py`.
**BF number:** BF-946, held by the title of #1723 (`gh issue list --state all --search "BF-946 in:title"`: #1723 only; `git log --all -i --grep BF-946`: no commit). Nothing allocated.

**Which text describes the head.** §1 to §3 describe `0ac7bdf3`; their line numbers are that commit's. `git diff --stat e9140fcb 0ac7bdf3` is empty for every file this contract edits, so the SEARCH texts are also `e9140fcb`'s. Before building, re-run that diff stat against main's head after S2 merges. A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. Some SEARCH texts quote earlier pairs: P3-4 quotes P2-2's REPLACE, P5-2 quotes P2-1's, P5-3 and P5-4 quote P2-5's, P5-5 quotes N1-1, and P5-8 to P5-10 quote M4's tracker text. Where prose differs from a REPLACE or new-file block, the block wins. Head text means every docstring, comment, log message, error string, agent-facing string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

On the base:

1. A failed AD-1240 delivery ends the run. `_delivery_stop` (`agentic_loop.py:1245-1261`) returns a stop for every `ResultDelivery` with status `"failed"`, and the loop returns with `stopped_reason="error"` (`:2150-2155`). Every typed refusal raised in `_prepare_result` becomes such a delivery (`result_offload.py:515-520`). That includes a read-only producer's result, which never promised the model anything.
2. **Measured on 2026-11-02** with the probe of record `logs/bf946/probe-output.txt` (gitignored; production bounds `tool_result_max_chars` 6000, threshold 12288; premises held). For an `event_log_query`-shaped plain `ToolResult`:
   - **With the reader granted, these fresh results were delivered:** results of 12,289, 60,000 and 2 × 20,000 characters, and a 13,023-character error result. Each pointer frame was 736 to 790 characters.
   - **Without `read_file` permission it stops** with `reader_unavailable` at `result_offload.py:274 reader <- :570 _prepare_result`.
   - **With 190 rows it stops** with `capture_slots` at `:657 canonical_capture <- :566`.
   - **A read-back of the offloaded artifact over 6000 characters stops** with `delivery_frame_too_large` at `:457 _admit <- :561 _prepare_result`. This happens at limit 6001 and with no limit; limit 6000 is delivered.

   `delivery_frame_too_large` is raised by `_admit` (`:457`, called at `:542`, `:545`, `:561`, `:582`, `:599` and `:604`), by `_evidence_prefix` for a delegated result (`:467`, `:470`; its evidence may take up to `max_chars // 2`, `:468`), and when the prefix leaves no allowance (`:576`). For a result that is not delegated, the prefix is empty or the 67-character error line (`:573`), so `:576` does not fire at the production bound. Its fresh frame (`:582`, `:599`, `:604`) is under 5,600 characters: an outline of at most 1,024 (`workspace_results.py:137`), a worked call as long as its JSON arguments, which are held to 4,096 bytes (`result_offload.py:476`), the error line, and under 400 characters of fixed frame text (`:481-512`). At the production bound such a result is refused for size only at `:542` or `:545` (a `WorkPullReceipt` or `OwnedStepsViewResult`, admitted inline) or at `:561` (a recovery slice).
3. **Live turn of 2026-10-31**, from a read-only copy of `events.db` read on 2026-11-02 (`logs/bf946/live-trace-output.txt`, gitignored). Forge (`engineering_officer_engineering_officer_0_872b75e7`) made 17 tool invocations in five bursts between 21:53:49 and 21:54:03 UTC. The saved trace prints each event's tool, `is_error` and time, not its iteration or arguments.
   - The first burst included an `event_log_query` that returned `invalid_params` (`is_error=True`). That is why the reply named `event_log_query`, because the disclosure keys on `is_error` (`dm/reply_value.py:124`).
   - The last burst was two `read_file` calls. Both returned `is_error=false`, and no tool event follows in the trace. The reply was `Result delivery failed (delivery_frame_too_large).` (the issue's quote).

   Every earlier burst was followed by another, and no AD-1240 warning was logged for the turn (issue body), so the stop was not the lost-reader stop (`agentic_loop.py:1688-1699`); it came from a `read_file` result. That result is not delegated and is neither a `WorkPullReceipt` nor an `OwnedStepsViewResult` (`tools.py` constructs neither), so by §1.2 the failure was a promised read with a slice over the bound (`:561`). The issue's premises ("one tool call, then the run ended", "a fresh read too large", "no reader") do not hold for that turn.
4. A promise survives a read. `SourceRecoveryScope` keeps reserved sources and artifacts for the whole run (`workspace_results.py:243-268`), and `read_file` places no cap on `limit` (`tools.py:470-478`, `workspace_result_store.py:893-895`). A smaller re-read of the same path would be served.
5. The log was silent for the live turn. Typed refusals in `prepare_result` log nothing (`result_offload.py:519-520`).

## 2. Solution

- **M1:** a reproduction file through the real loop. Cases that change in M2 and M3 are written against the new behaviour and marked `xfail(strict=True)`, so they must fail on the base. Each later milestone removes its marks.
- **M2 (O1):** `_continues_after_failed_delivery`. A failed delivery from a tier-1 call (`is_tier_1_tool_call`) no longer ends the run. The model is shown `retry_delivery_error`: the bounded code plus a request to ask for less. Every other failed delivery but M5's, and every R2-1 refusal, still ends the run. The final reply of a stopped run is unchanged.
- **M3:** one content-free WARNING per typed delivery failure, naming the code, tool, agent and raise site, plus the measured length and bound for a frame `_admit` refuses for size.
- **M4:** trackers and ledger.
- **M5 (R-a, decided 2026-11-02):** a recovery slice over the bound is refused with `recovery_slice_too_large`. The model is shown the bound and the run goes on; the promise is unchanged.

## 3. Decisions

- **Continuation (O1, chosen).**
  - **Rule:** the run continues past a failed delivery if `is_tier_1_tool_call(name, arguments)` is true or, with M5, if its code is `recovery_slice_too_large` (§7.5). The native readers are not tier 1 (asserted at `tests/test_ad1240_tool_result_delivery.py:4470`), so every other failed promised read keeps the stop, and R2-1's `InvocationRefusal` stop is untouched.
  - **Ranking:** O1 is first on correctness (nothing was promised) and on safety (a call that changes state is never re-run). It is compatible: no existing test pins a stop on a tier-1 call's failed delivery (Absence A4). It reuses an existing classifier, and is reversible as one predicate.
  - **Rejected:** O2, continuing for every producer (a state-changing call could run twice). O3, truncating an oversized frame (AD-1240 never truncates a delivery, `agentic_loop.py:865-866`). O4, logging only (fails the issue's acceptance 1).
- **Text.** The guidance is rendered at the message boundary. In the loop, a failed delivery reaches `format_tool_result_content` only when the run went on past it, so `ResultDelivery.presentation`, the stop reply and `test_ad1191_delegation_wire.py:657` stay unchanged.
- **Log.** One WARNING per typed failure, emitted in `prepare_result`. The site comes from the refusal's last two traceback frames. `_OversizedFrame`, a subclass of `WorkspaceResultError`, carries the measured length and the bound. The untyped path keeps one ERROR and gains the tool and agent.
- **R (decided: R-a, the Captain on #1723, 2026-11-02, 22:57Z).** The live failure is a promised read over the bound, which the issue's "Do not build" (any change to AD-1240's promised-recovery semantics) kept out of scope. The Captain chose R-a: M5 (§7.5) lets the run go on past that one case and is built with M1 to M4 as one batch.
- **Config:** none. **EventType:** none. **No method is added to `AgenticLoop`** (it stays at or under 13 methods, `tests/test_ad1324_srp_layout.py:61`).

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | STANDARD | N1-1 | G1 |
| M2 | HIGH | P2-1 to P2-12 | G2 |
| M3 | STANDARD | P3-1 to P3-6 | G3 |
| M4 | STANDARD | P4-1, P4-2, the ledger | G4 |
| M5 (R-a only) | HIGH | P5-1 to P5-10 | G5 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf946_read_only_delivery_failures.py -q -n 0`. Expected: 5 passed, 7 xfailed. The xfails are T1's four cases, T6b, and T8's two cases. That is 12 cases.

**G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf946_read_only_delivery_failures.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1240_workspace_results.py tests/test_ad1191_delegation_wire.py tests/test_ad1191_delegated_evidence.py tests/test_ad1146_multiturn_messages.py tests/test_ad1148_tool_result_bounds.py tests/test_ad1147_parallel_tools.py tests/test_ad1324_srp_layout.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`. T8 is still xfailed.

**G3:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf946_read_only_delivery_failures.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1240_workspace_results.py tests/test_ad1191_delegation_wire.py -q -n 0`, then:
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check`

After G3 the file has no xfail left.

**G4:**
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
- `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

**G5:** G3's pytest line, both checks, then G4.

## 5. Commit messages

- M1: `BF-946 M1: a reproduction of read-only delivery failures through the real loop`
- M2: `BF-946 M2: a read-only call's failed delivery comes back to the model and the run goes on`
- M3: `BF-946 M3: one warning per typed delivery failure, naming its raise site`
- M4: `BF-946 M4: trackers and ledger`
- M5: `BF-946 M5: a recovery read over the per-read bound comes back naming the bound`

## 6. Tests (`tests/test_bf946_read_only_delivery_failures.py`)

| Id | Test | Covers | xfail until |
|---|---|---|---|
| T1 | `test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds` (no reader / 190 rows × both transcripts) | Acceptance 1, whole path | M2 |
| T3 | `test_a_failed_delivery_still_ends_the_run_for_a_producer_that_is_not_read_only` | predicate's other side | none |
| T4 | `test_a_recovery_read_over_the_bound_still_ends_the_run` (6000 / 6001) | Acceptance 3 with a promise; the live failure, unchanged without M5 | none (M5 replaces it) |
| T5 | `test_a_promised_read_whose_authority_is_lost_still_ends_the_run` | Acceptance 2 (R2-1) | none |
| T6a | `test_a_fresh_frame_exactly_at_the_bound_is_delivered` | Acceptance 3 with no promise, at the bound | none |
| T6b | `test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error` | Acceptance 3 with no promise, one over | M2 |
| T8 | `test_each_failed_delivery_logs_one_content_free_warning_naming_its_site` | Acceptance 4 | M3 |
| U1 | `test_the_retry_text_fits_the_bound_or_falls_back_to_the_bounded_code` (added by M2) | retry-text bounds | n/a |

Also relied on, unchanged: acceptance 5 by `test_legacy_requests_match_pre_edit_golden` (`test_ad1240:273`). R2-1 through the loop with a tier-1 producer by `test_workspace_promise_refuses_replaced_reader_before_invocation` (`http_fetch` when parallel) and `test_promise_survives_authority_loss_through_the_loop`.

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_bf946_read_only_delivery_failures.py` (new)

```python
"""BF-946 (#1723): a read-only call's failed delivery comes back to the model, and the run goes on.

The loop tests run the real ``AgenticLoop`` over the AD-1240 rig of ``test_ad1240_tool_result_delivery`` (a real
store, registry, native tools and executor) with a scripted model, structured tool messages and the production
bound of 6000 characters unless the test says otherwise.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import result_delivery
from probos.execution.workspace_results import TOOL_RESULT_THRESHOLD_BYTES
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.test_ad1240_tool_result_delivery import (
    _AGENT_ID,
    _RawTool,
    _artifact_count,
    _done,
    _environment,
    _last_result,
    _started,
    _turn,
    _verbatim_call,
)

_BOUND = 6000
_GUIDANCE = (
    "The call ran, but its result was not delivered. Ask for less "
    "(for example a narrower window or a lower limit) and call again."
)
_OFFLOAD_LOGGER = "probos.cognitive.swe_harness.result_offload"


def _retry_text(code: str) -> str:
    return f"Result delivery failed ({code}). {_GUIDANCE}"


def _envelope(rows: int) -> dict[str, Any]:
    """An ``event_log_query``-shaped envelope: about 410 characters and 27 inspection slots per row."""
    return {
        "status": "ok", "order": "desc", "matched_count": rows, "returned_count": rows,
        "scanned_count": rows, "truncated": False, "aggregate": None,
        "window": {"start_time": "2026-10-30T00:00:00Z", "end_time": "2026-10-31T21:53:00Z"},
        "rows": [{
            "id": index, "timestamp": "2026-10-31T21:00:00Z", "category": "system",
            "event": "agent_state_changed", "agent_id": "engineering_officer_0",
            "agent_type": "engineering_officer", "pool": "engineering", "detail": "d" * 100,
            "correlation_id": None, "parent_event_id": None, "data": {"state": "active", "reason": "stasis"},
        } for index in range(rows)],
    }


class _EventLogShaped(_RawTool):
    """``event_log_query``'s result shape: a plain ``ToolResult`` holding ``limit`` rows."""

    input_schema: dict[str, Any] = {"type": "object", "properties": {"limit": {"type": "integer"}}}

    def __init__(self, tool_id: str = "event_log_query") -> None:
        super().__init__(ToolResult(output=None))
        self.tool_id = tool_id
        self.limits: list[int] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        self.limits.append(params["limit"])
        return ToolResult(output=_envelope(params["limit"]))


class _NarrowingLLM:
    """Asks for ``first`` rows, then for 5 rows whatever it was shown, then answers."""

    def __init__(self, tool_id: str, first: int) -> None:
        self.tool_id = tool_id
        self.first = first
        self.requests: list[LLMRequest] = []
        self.frames: list[str] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        number = len(self.requests)
        if number > 1:
            self.frames.append(_last_result(request))
        if number == 1:
            return _turn(self.tool_id, _call_id="query-wide", limit=self.first)
        if number == 2:
            return _turn(self.tool_id, _call_id="query-narrow", limit=5)
        return _done()


class _ReadBackLLM:
    """Calls ``event_log_query`` once, reads its pointer back once per entry of ``limits``, then answers.

    Each read is the worked call the pointer frame printed, with ``limit`` replaced; ``before_read`` runs just
    before the first read is issued.
    """

    def __init__(self, limits: list[int], before_read: Callable[[], None] | None = None) -> None:
        self.limits = list(limits)
        self.before_read = before_read
        self.requests: list[LLMRequest] = []
        self.frames: list[str] = []
        self.worked: dict[str, Any] = {}

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        number = len(self.requests)
        if number == 1:
            return _turn("event_log_query", _call_id="query")
        self.frames.append(_last_result(request))
        if number == 2:
            name, self.worked = _verbatim_call(self.frames[-1])
            assert name == "read_file"
            if self.before_read is not None:
                self.before_read()
        if not self.limits:
            return _done()
        return _turn("read_file", _call_id=f"read-{number}", **{**self.worked, "limit": self.limits.pop(0)})


def _withhold_reader(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent's state before the Captain's grant: ``read_file`` registered, but not permitted."""
    registry = runtime.tool_registry
    permitted = registry.check_permission

    def check_permission(agent_id: str, tool_id: str, required: Any, **kwargs: Any) -> bool:
        return False if tool_id == "read_file" else permitted(agent_id, tool_id, required, **kwargs)

    monkeypatch.setattr(registry, "check_permission", check_permission)


def _loop(llm: Any, executor: Any, runtime: Any, *, bound: int = _BOUND, structured: bool = True) -> AgenticLoop:
    return AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=8, tool_result_max_chars=bound,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )


@pytest.mark.xfail(strict=True, reason="BF-946 M2: on the base a failed delivery ends the run")
@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(("reader", "rows", "code"), [
    pytest.param(False, 100, "reader_unavailable", id="no-reader-before-the-grant"),
    pytest.param(True, 190, "capture_slots", id="too-many-slots-to-capture"),
])
async def test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool, reader: bool, rows: int, code: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _EventLogShaped()
    runtime.tool_registry.register(tool)
    if not reader:
        _withhold_reader(runtime, monkeypatch)
    # Premise: the wide result needs delivery and the narrow one does not.
    assert len(str(_envelope(rows)).encode("utf-8")) > TOOL_RESULT_THRESHOLD_BYTES
    assert len(str(_envelope(5)).encode("utf-8")) <= TOOL_RESULT_THRESHOLD_BYTES
    llm = _NarrowingLLM("event_log_query", rows)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, structured=structured).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    assert result.stopped_reason == "complete" and result.final_text == "done"
    assert tool.limits == [rows, 5] and len(llm.requests) == 3
    wide, narrow = result.tool_results
    failed = result_delivery(wide)
    assert failed is not None and failed.status == "failed" and failed.code == code
    assert wide.is_error is False and wide.output == str(_envelope(rows))
    assert llm.frames[0] == _retry_text(code)
    assert result_delivery(narrow) is None and "'returned_count': 5" in llm.frames[1]
    assert _artifact_count(runtime) == 0


@pytest.mark.asyncio
async def test_a_failed_delivery_still_ends_the_run_for_a_producer_that_is_not_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    tool = _EventLogShaped("fixture_result")
    runtime.tool_registry.register(tool)
    _withhold_reader(runtime, monkeypatch)
    llm = _NarrowingLLM("fixture_result", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reader_unavailable"
    assert result.final_text == "Result delivery failed (reader_unavailable)."
    assert tool.limits == [100] and len(llm.requests) == 1
    assert result_delivery(result.tool_results[0]).status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "delivered"), [
    pytest.param(6000, True, id="read-back-at-the-bound"),
    pytest.param(6001, False, id="read-back-one-over-the-bound"),
])
async def test_a_recovery_read_over_the_bound_still_ends_the_run(
    tmp_path: Path, limit: int, delivered: bool,
) -> None:
    """A read of the offloaded result is a promised recovery; over the bound it still ends the run.

    This is the live failure of 2026-10-31.
    """
    runtime, executor, context = _environment(tmp_path)
    producer = _RawTool(ToolResult(output="L" * 20000))
    producer.tool_id = "event_log_query"
    runtime.tool_registry.register(producer)
    llm = _ReadBackLLM([limit])
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result_delivery(result.tool_results[0]).status == "workspace" and producer.calls == 1
    read = result_delivery(result.tool_results[-1])
    assert result.tool_results[-1].output == "L" * limit
    if delivered:
        assert result.stopped_reason == "complete" and read.status == "recovered"
        assert llm.frames[-1] == "L" * limit and len(llm.requests) == 3
    else:
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        assert read.status == "failed" and read.code == "delivery_frame_too_large"
        assert result.final_text == "Result delivery failed (delivery_frame_too_large)."
        assert len(llm.requests) == 2
    assert _artifact_count(runtime) == 1


@pytest.mark.asyncio
async def test_a_promised_read_whose_authority_is_lost_still_ends_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2-1 is unchanged: the read is refused before it starts, and the run stops."""
    runtime, executor, context = _environment(tmp_path)
    producer = _RawTool(ToolResult(output="L" * 20000))
    producer.tool_id = "event_log_query"
    runtime.tool_registry.register(producer)
    llm = _ReadBackLLM([4096], before_read=lambda: _withhold_reader(runtime, monkeypatch))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert result.final_text == "Result delivery failed (reference_unavailable)."
    assert len(llm.requests) == 2 and len(result.tool_calls) == 2 and len(result.tool_results) == 1


async def _frame_length(owned: Path) -> int:
    """The workspace frame's length for the 100-row result when the worked call's ``limit`` has three digits."""
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    async with _started(runtime):
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=900).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace"
    return len(delivery.presentation)


@pytest.mark.asyncio
async def test_a_fresh_frame_exactly_at_the_bound_is_delivered(tmp_path: Path) -> None:
    """Acceptance 3 with no promise: a bound equal to the frame's length admits it.

    Under 4096 the worked call's ``limit`` is the bound, so every bound here has three digits and the frame
    one length; sibling directories with names of equal length keep the path's length.
    """
    length = await _frame_length(tmp_path / "m")
    assert 100 < length < 900  # premise: three-digit bounds on both sides of the frame
    owned = tmp_path / "a"
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    llm = _NarrowingLLM("event_log_query", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, bound=length).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace" and len(delivery.presentation) == length
    assert llm.frames[0] == delivery.presentation and result.stopped_reason == "complete"


@pytest.mark.xfail(strict=True, reason="BF-946 M2: on the base a failed delivery ends the run")
@pytest.mark.asyncio
async def test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error(tmp_path: Path) -> None:
    """Acceptance 3 with no promise: one character over, the read-only result takes the error path."""
    length = await _frame_length(tmp_path / "m")
    assert 100 < length < 900 and len(_retry_text("delivery_frame_too_large")) < length - 1  # premise
    owned = tmp_path / "b"
    owned.mkdir()
    runtime, executor, context = _environment(owned)
    runtime.tool_registry.register(_EventLogShaped())
    llm = _NarrowingLLM("event_log_query", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime, bound=length - 1).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "failed" and delivery.code == "delivery_frame_too_large"
    assert llm.frames[0] == _retry_text("delivery_frame_too_large")
    assert result.stopped_reason == "complete" and len(llm.requests) == 3
    assert _artifact_count(runtime) == 0


@pytest.mark.xfail(strict=True, reason="BF-946 M3: the base logs no delivery-failure warning")
@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "bound", "code", "site", "measured"), [
    pytest.param(False, _BOUND, "reader_unavailable", r"_prepare_result:\d+ > reader:\d+", r"n/a", id="no-reader"),
    pytest.param(
        True, 200, "delivery_frame_too_large", r"_prepare_result:\d+ > _admit:\d+", r"(\d+) bound=200",
        id="frame-over-a-200-bound",
    ),
])
async def test_each_failed_delivery_logs_one_content_free_warning_naming_its_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    reader: bool, bound: int, code: str, site: str, measured: str,
) -> None:
    runtime, executor, context = _environment(tmp_path)
    runtime.tool_registry.register(_EventLogShaped())
    if not reader:
        _withhold_reader(runtime, monkeypatch)
    caplog.set_level(logging.WARNING, logger=_OFFLOAD_LOGGER)
    async with _started(runtime):
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=bound).run(
            system_prompt="", user_message="", tools=[], context=context,
        )
    assert result_delivery(result.tool_results[0]).code == code  # premise: the case failed as named
    warnings = [
        record.getMessage() for record in caplog.records
        if record.name == _OFFLOAD_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0]
    assert f"code={code} tool=event_log_query agent={_AGENT_ID[:12]} " in message
    found = re.search(f"site={site} measured={measured};", message)
    assert found is not None
    if found.groups():
        assert int(found[1]) > bound  # the frame that did not fit
    assert "dddd" not in message
```

### 7.2 M2

**P2-1** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
def safe_delivery_error(code: str, max_chars: int) -> str:
    WorkspaceResultError(code)
    if type(max_chars) is not int or max_chars < 0:
        return "!"
    text = f"Result delivery failed ({code})."
    return text if len(text) <= min(128, max_chars if max_chars > 0 else 128) else "!"
```
REPLACE:
```python
def safe_delivery_error(code: str, max_chars: int) -> str:
    WorkspaceResultError(code)
    if type(max_chars) is not int or max_chars < 0:
        return "!"
    text = f"Result delivery failed ({code})."
    return text if len(text) <= min(128, max_chars if max_chars > 0 else 128) else "!"


# BF-946: the guidance shown with a read-only call's failed delivery.
_RETRY_GUIDANCE = (
    "The call ran, but its result was not delivered. Ask for less "
    "(for example a narrower window or a lower limit) and call again."
)


def retry_delivery_error(code: str, max_chars: int) -> str:
    """BF-946: the bounded text for a failed delivery the run went on past.

    The loop goes on past a failed delivery only from a read-only call, whose result
    promised nothing, so asking again for less is safe. The text is
    ``safe_delivery_error`` and ``_RETRY_GUIDANCE``; a bound too small for both gives
    ``safe_delivery_error`` alone.
    """
    base = safe_delivery_error(code, max_chars)
    if base == "!":
        return base
    text = f"{base} {_RETRY_GUIDANCE}"
    return text if max_chars == 0 or len(text) <= max_chars else base
```

**P2-2** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
    except Exception:
        logger.error(
            "Workspace result delivery preparation failed; the producer outcome is "
            "retained and the loop will stop without retrying the producer",
        )
        return delivery_failure(captured, context, "delivery_unavailable")
```
REPLACE:
```python
    except Exception:
        logger.error(
            "Workspace result delivery preparation failed (delivery_unavailable); the "
            "producer outcome is retained and is never retried by delivery",
        )
        return delivery_failure(captured, context, "delivery_unavailable")
```

**P2-3** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
    prepare_result,
    safe_delivery_error,
    seal_workspace_results,
)
```
REPLACE:
```python
    prepare_result,
    retry_delivery_error,
    safe_delivery_error,
    seal_workspace_results,
)
```

**P2-4** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
    """Render the typed extension only at the message boundary, never in trace output."""
    delivery = result_delivery(result)
    if delivery is not None:
        # AD-1240: a delivery is a complete, already-admitted frame; it is never
        # truncated, so one that no longer fits is refused rather than clipped.
```
REPLACE:
```python
    """Render the typed extension only at the message boundary, never in trace output."""
    delivery = result_delivery(result)
    if delivery is not None and delivery.status == "failed":
        # BF-946: in the loop a failed delivery reaches the message boundary only when
        # the run went on past it (``_delivery_stop``). The model is shown the bounded
        # code and, when the text fits ``max_chars``, a request to ask for less.
        return retry_delivery_error(delivery.code, max_chars)
    if delivery is not None:
        # AD-1240: a delivery is a complete, already-admitted frame; it is never
        # truncated, so one that no longer fits is refused rather than clipped.
```

**P2-5** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
def _delivery_stop(
    results: list[ToolCallResult | InvocationRefusal], max_chars: int,
) -> tuple[str, str] | None:
    """AD-1240: the ``(code, text)`` that ends the run, or ``None`` to continue.

    A refused request (R2-1) and a result whose delivery failed both end the run:
    no further model request can honestly follow either. ``results`` is in request
    order, so the failure that ends the run is the first one issued.
    """
    for item in results:
        if isinstance(item, InvocationRefusal):
            return item.code, safe_delivery_error(item.code, max_chars)
        delivery = result_delivery(item)
        if delivery is not None and delivery.status == "failed":
            # ``ResultDelivery`` validates that a failed delivery carries its code.
            return delivery.code, delivery.presentation
    return None
```
REPLACE:
```python
def _continues_after_failed_delivery(use: ToolUseBlock) -> bool:
    """BF-946: whether the run goes on past a failed delivery of ``use``'s result.

    Only a read-only (tier-1) call does, as ``is_tier_1_tool_call`` judges it: its
    result promised nothing, and asking again cannot repeat an effect. The native
    readers are not tier 1, so a failed recovery or source read still ends the run.
    """
    return is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)


def _delivery_stop(
    tool_uses: list[ToolUseBlock], results: list[ToolCallResult | InvocationRefusal], max_chars: int,
) -> tuple[str, str] | None:
    """AD-1240: the ``(code, text)`` that ends the run, or ``None`` to continue.

    A refused request (R2-1) ends the run: no further model request can honestly
    follow it. So does a result whose delivery failed, unless
    ``_continues_after_failed_delivery`` lets the run go on (BF-946); the model is
    then shown the failure and may ask again for less. ``results`` is aligned with
    ``tool_uses`` and in request order.
    """
    for use, item in zip(tool_uses, results, strict=True):
        if isinstance(item, InvocationRefusal):
            return item.code, safe_delivery_error(item.code, max_chars)
        delivery = result_delivery(item)
        if (
            delivery is not None and delivery.status == "failed"
            and not _continues_after_failed_delivery(use)
        ):
            # ``ResultDelivery`` validates that a failed delivery carries its code.
            return delivery.code, delivery.presentation
    return None
```

**P2-6** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
            # AD-1240: a refused request (R2-1) or a result whose delivery failed ends
            # the run, selected by request order. The issued request stays in
            # ``tool_calls``; ``tool_results`` holds genuine outcomes only. No further
            # model request is made, and the model is told only a bounded code.
            if delivery_run is not None:
                stop = _delivery_stop(tool_results, delivery_run.settings.max_chars)
```
REPLACE:
```python
            # AD-1240: a refused request (R2-1) or a result whose delivery failed ends
            # the run, selected by request order, except a failed delivery that
            # ``_continues_after_failed_delivery`` lets the run go on past (BF-946); the
            # model is shown it. The issued request stays in ``tool_calls``;
            # ``tool_results`` holds genuine outcomes only. When the run ends, no further
            # model request is made and the reply is only the bounded code.
            if delivery_run is not None:
                stop = _delivery_stop(tool_uses, tool_results, delivery_run.settings.max_chars)
```

**P2-7** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
            # AD-1240: this group carries a delivered result's pointer or slice. It is
            # kept whole for the rest of the run, so compaction cannot summarise away
            # the path and offsets the model still has to read.
```
REPLACE:
```python
            # AD-1240: this group carries a delivery: a pointer or slice, or (BF-946) a
            # failed delivery's bounded text. It is kept whole for the rest of the run, so
            # compaction cannot summarise away a path and offsets the model still has to
            # read; a group whose only delivery failed holds none and is kept all the same.
```

**P2-8** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
            # AD-1240: delivery is deliberately outside the producer exception window.
            # Every observer has already seen the original outcome, and a delivery
            # failure is never reported as a producer error: ``prepare_result`` turns
            # one into a typed refusal on the result, and the run stops on it.
```
REPLACE:
```python
            # AD-1240: delivery is deliberately outside the producer exception window.
            # Every observer has already seen the original outcome, and a delivery
            # failure is never reported as a producer error: ``prepare_result`` turns
            # one into a typed refusal on the result. The run stops on it unless
            # ``_continues_after_failed_delivery`` lets it go on (BF-946).
```

**P2-9** `tests/test_bf946_read_only_delivery_failures.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason="BF-946 M2: on the base a failed delivery ends the run")
@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
```

**P2-10** `tests/test_bf946_read_only_delivery_failures.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason="BF-946 M2: on the base a failed delivery ends the run")
@pytest.mark.asyncio
async def test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error(tmp_path: Path) -> None:
```

**P2-11** `tests/test_bf946_read_only_delivery_failures.py`

SEARCH:
```python
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import result_delivery
```
REPLACE:
```python
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.result_offload import retry_delivery_error, safe_delivery_error
from probos.cognitive.swe_harness.tool_call import result_delivery
```

**P2-12** `tests/test_bf946_read_only_delivery_failures.py`

SEARCH:
```python
    if found.groups():
        assert int(found[1]) > bound  # the frame that did not fit
    assert "dddd" not in message
```
REPLACE:
```python
    if found.groups():
        assert int(found[1]) > bound  # the frame that did not fit
    assert "dddd" not in message


def test_the_retry_text_fits_the_bound_or_falls_back_to_the_bounded_code() -> None:
    full = retry_delivery_error("capture_slots", 0)
    assert full == _retry_text("capture_slots")
    assert retry_delivery_error("capture_slots", len(full)) == full
    assert retry_delivery_error("capture_slots", len(full) - 1) == safe_delivery_error("capture_slots", len(full) - 1)
    assert retry_delivery_error("capture_slots", 10) == "!"
    with pytest.raises(ValueError):
        retry_delivery_error("Not A Code", _BOUND)
```

### 7.3 M3

**P3-1** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
import os
import secrets
from collections.abc import Mapping
```
REPLACE:
```python
import os
import secrets
import traceback
from collections.abc import Mapping
```

**P3-2** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
@dataclass(frozen=True)
class DeliveryContext:
    run: DeliveryRun
    remaining_iterations: int
```
REPLACE:
```python
@dataclass(frozen=True)
class DeliveryContext:
    run: DeliveryRun
    remaining_iterations: int
    # BF-946: the producing call's tool name, for the delivery-failure log only.
    tool_name: str = ""
```

**P3-3** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
def _admit(text: str, maximum: int) -> str:
    if maximum > 0 and len(text) > maximum:
        raise WorkspaceResultError("delivery_frame_too_large")
    return text
```
REPLACE:
```python
class _OversizedFrame(WorkspaceResultError):
    """A frame refused for its size, with the measured length and the bound, for BF-946's log only."""

    def __init__(self, code: str, measured: int, bound: int) -> None:
        super().__init__(code)
        self.measured = measured
        self.bound = bound


def _admit(text: str, maximum: int) -> str:
    if maximum > 0 and len(text) > maximum:
        raise _OversizedFrame("delivery_frame_too_large", len(text), maximum)
    return text
```

**P3-4** `src/probos/cognitive/swe_harness/result_offload.py` (quotes P2-2)

SEARCH:
```python
async def prepare_result(captured: CapturedConversion, context: DeliveryContext) -> ToolCallResult:
    """Prepare delivery without changing or retrying the producer's outcome."""
    try:
        return await _prepare_result(captured, context)
    except WorkspaceResultError as exc:
        return delivery_failure(captured, context, exc.code)
    except Exception:
        logger.error(
            "Workspace result delivery preparation failed (delivery_unavailable); the "
            "producer outcome is retained and is never retried by delivery",
        )
        return delivery_failure(captured, context, "delivery_unavailable")
```
REPLACE:
```python
def _log_delivery_failure(exc: WorkspaceResultError, context: DeliveryContext) -> None:
    """BF-946: one content-free WARNING per typed delivery failure.

    It names the code, the tool, the agent, the raise site (the last two frames of
    the refusal's traceback) and, for an ``_OversizedFrame``, the measured length
    against the bound.
    """
    site = " > ".join(
        f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)[-2:]
    )
    measured = f"{exc.measured} bound={exc.bound}" if isinstance(exc, _OversizedFrame) else "n/a"
    logger.warning(
        "BF-946: result delivery failed code=%s tool=%s agent=%s site=%s measured=%s; "
        "the producer outcome is retained and is never retried by delivery",
        exc.code, context.tool_name or "<unnamed>", context.run.agent_id[:12], site, measured,
    )


async def prepare_result(captured: CapturedConversion, context: DeliveryContext) -> ToolCallResult:
    """Prepare delivery without changing or retrying the producer's outcome."""
    try:
        return await _prepare_result(captured, context)
    except WorkspaceResultError as exc:
        _log_delivery_failure(exc, context)
        return delivery_failure(captured, context, exc.code)
    except Exception:
        logger.error(
            "Workspace result delivery preparation failed (delivery_unavailable) tool=%s "
            "agent=%s; the producer outcome is retained and is never retried by delivery",
            context.tool_name or "<unnamed>", context.run.agent_id[:12],
        )
        return delivery_failure(captured, context, "delivery_unavailable")
```

**P3-5** `src/probos/cognitive/swe_harness/agentic_loop.py`

SEARCH:
```python
            tcr = await prepare_result(captured, DeliveryContext(delivery_run, delivery_remaining))
```
REPLACE:
```python
            tcr = await prepare_result(
                captured, DeliveryContext(delivery_run, delivery_remaining, use.tool_call.name),
            )
```

**P3-6** `tests/test_bf946_read_only_delivery_failures.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason="BF-946 M3: the base logs no delivery-failure warning")
@pytest.mark.asyncio
```
REPLACE:
```python
@pytest.mark.asyncio
```

### 7.4 M4

M4 changes no `src` or `tests` file. Its pairs are P4-1 and P4-2 (§8) plus the ledger.

### 7.5 M5: built only on the Captain's decision R-a

M5 shares lines with M2: P5-2 to P5-4 quote M2's REPLACE text. It is ordered after M4.

**P5-1** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
    if recovery:
        if context.remaining_iterations < 1:
            raise WorkspaceResultError("recovery_iterations_unavailable")
        _admit(text, settings.max_chars)
```
REPLACE:
```python
    if recovery:
        if context.remaining_iterations < 1:
            raise WorkspaceResultError("recovery_iterations_unavailable")
        if settings.max_chars > 0 and len(text) > settings.max_chars:
            # BF-946: the slice is over the bound, not the promise, so the run goes on; when its
            # text fits, ``retry_delivery_error`` names the bound and asks for a smaller range.
            raise _OversizedFrame("recovery_slice_too_large", len(text), settings.max_chars)
```

**P5-2** `src/probos/cognitive/swe_harness/result_offload.py` (quotes P2-1)

SEARCH:
```python
def retry_delivery_error(code: str, max_chars: int) -> str:
    """BF-946: the bounded text for a failed delivery the run went on past.

    The loop goes on past a failed delivery only from a read-only call, whose result
    promised nothing, so asking again for less is safe. The text is
    ``safe_delivery_error`` and ``_RETRY_GUIDANCE``; a bound too small for both gives
    ``safe_delivery_error`` alone.
    """
    base = safe_delivery_error(code, max_chars)
    if base == "!":
        return base
    text = f"{base} {_RETRY_GUIDANCE}"
    return text if max_chars == 0 or len(text) <= max_chars else base
```
REPLACE:
```python
def retry_delivery_error(code: str, max_chars: int) -> str:
    """BF-946: the bounded text for a failed delivery the run went on past.

    The loop goes on past a failed delivery from a read-only call, whose result
    promised nothing, and past a recovery read over the per-read bound
    (``recovery_slice_too_large``), whose promise still holds; asking again for less
    is safe in both. The text is ``safe_delivery_error`` and the guidance, which for
    the recovery read names the bound; a bound too small for both gives
    ``safe_delivery_error`` alone.
    """
    base = safe_delivery_error(code, max_chars)
    if base == "!":
        return base
    guidance = (
        f"One read returns at most {max_chars} characters. Read the same path again over a smaller range."
        if code == "recovery_slice_too_large" and max_chars > 0 else _RETRY_GUIDANCE
    )
    text = f"{base} {guidance}"
    return text if max_chars == 0 or len(text) <= max_chars else base
```

**P5-3** `src/probos/cognitive/swe_harness/agentic_loop.py` (quotes P2-5)

SEARCH:
```python
def _continues_after_failed_delivery(use: ToolUseBlock) -> bool:
    """BF-946: whether the run goes on past a failed delivery of ``use``'s result.

    Only a read-only (tier-1) call does, as ``is_tier_1_tool_call`` judges it: its
    result promised nothing, and asking again cannot repeat an effect. The native
    readers are not tier 1, so a failed recovery or source read still ends the run.
    """
    return is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)
```
REPLACE:
```python
def _continues_after_failed_delivery(use: ToolUseBlock, code: str) -> bool:
    """BF-946: whether the run goes on past a failed delivery of ``use``'s result.

    A read-only (tier-1) call does, as ``is_tier_1_tool_call`` judges it: its result
    promised nothing, and asking again cannot repeat an effect. So does a recovery read over the per-read bound
    (``recovery_slice_too_large``): its promise, reader and artifact are unchanged,
    and the same path read over a smaller range is served. The native readers are
    not tier 1, so every other failed recovery or source read still ends the run.
    """
    return code == "recovery_slice_too_large" or is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)
```

**P5-4** `src/probos/cognitive/swe_harness/agentic_loop.py` (quotes P2-5)

SEARCH:
```python
            and not _continues_after_failed_delivery(use)
```
REPLACE:
```python
            and not _continues_after_failed_delivery(use, delivery.code)
```

**P5-5** `tests/test_bf946_read_only_delivery_failures.py` (quotes N1-1). SEARCH is T4 whole, from `@pytest.mark.asyncio` above `@pytest.mark.parametrize(("limit", "delivered"), [` through `    assert _artifact_count(runtime) == 1` before `@pytest.mark.asyncio` / `async def test_a_promised_read_whose_authority_is_lost_still_ends_the_run`. REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize(("limits", "requests"), [
    pytest.param([6000], 3, id="read-back-at-the-bound"),
    pytest.param([6001, 6000], 4, id="read-back-one-over-then-at-the-bound"),
])
async def test_a_recovery_read_over_the_bound_comes_back_naming_the_bound_and_a_smaller_read_is_served(
    tmp_path: Path, limits: list[int], requests: int,
) -> None:
    """The live failure's shape (2026-10-31): a promised read over the bound no longer ends the run.

    The model is shown the bound, reads the same path again over a smaller range, and that read is served.
    """
    runtime, executor, context = _environment(tmp_path)
    producer = _RawTool(ToolResult(output="L" * 20000))
    producer.tool_id = "event_log_query"
    runtime.tool_registry.register(producer)
    llm = _ReadBackLLM(list(limits))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete" and len(llm.requests) == requests and producer.calls == 1
    assert result_delivery(result.tool_results[0]).status == "workspace"
    assert result_delivery(result.tool_results[-1]).status == "recovered" and llm.frames[-1] == "L" * 6000
    if len(limits) == 2:
        refused = result_delivery(result.tool_results[1])
        assert refused.status == "failed" and refused.code == "recovery_slice_too_large"
        assert result.tool_results[1].output == "L" * 6001
        assert llm.frames[1] == (
            "Result delivery failed (recovery_slice_too_large). One read returns at most 6000 characters. "
            "Read the same path again over a smaller range."
        )
    assert _artifact_count(runtime) == 1
```

**P5-6** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
            assert case == "last_iteration" and number == 3
            assert _last_result(request) == body[:1]
            return _turn("read_file", _call_id="read-3", **self.arguments)
```
REPLACE:
```python
            assert number == 3
            if case == "oversized_slice":
                # BF-946 M5: the slice over the bound came back as the bounded recovery_slice_too_large error.
                assert _last_result(request).startswith("Result delivery failed (recovery_slice_too_large).")
                return _done()
            assert _last_result(request) == body[:1]
            return _turn("read_file", _call_id="read-3", **self.arguments)
```

**P5-7** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
        expected = "delivery_frame_too_large" if case == "oversized_slice" else "recovery_iterations_unavailable"
        assert result.stopped_reason == "error" and result.error == expected
        assert result_delivery(result.tool_results[-1]).code == expected
        assert all(not item.is_error for item in result.tool_results)
        assert result.tool_results[-1].output == body[:llm.arguments["limit"]]
        assert len(llm.requests) == (2 if case == "oversized_slice" else 3)
        assert len(result.tool_calls) == len(llm.requests) and raw.calls == 1
        assert _artifact_count(runtime) == 1
```
REPLACE:
```python
        expected = "recovery_slice_too_large" if case == "oversized_slice" else "recovery_iterations_unavailable"
        assert result_delivery(result.tool_results[-1]).code == expected
        if case == "oversized_slice":
            # BF-946 M5: the promise holds, so the run went on and ended when the model answered.
            assert result.stopped_reason == "complete" and len(result.tool_calls) == len(llm.requests) - 1
        else:
            assert result.stopped_reason == "error" and result.error == expected
            assert len(result.tool_calls) == len(llm.requests)
        assert all(not item.is_error for item in result.tool_results)
        assert result.tool_results[-1].output == body[:llm.arguments["limit"]]
        assert len(llm.requests) == 3 and raw.calls == 1
        assert _artifact_count(runtime) == 1
```

**P5-8** `PROGRESS.md` (quotes P4-1)

SEARCH:
```
A failed delivery from any other call, and every refused promised read (R2-1), still ends the run.
```
REPLACE:
```
A failed delivery from any other call still ends the run, except a promised read whose slice is over the bound, and every refused promised read (R2-1) still ends it.
```

**P5-9** `PROGRESS.md` (quotes P4-1)

SEARCH:
```
not a fresh result; that promised read still ends the run, and whether it should go on is the Captain's decision on #1723.
```
REPLACE:
```
not a fresh result. On the Captain's decision on #1723 that read is now refused with `recovery_slice_too_large`, which names the bound to the model; the promise, reader and artifact are unchanged, and the run goes on.
```

**P5-10** `DECISIONS.md` (quotes P4-2). Three exact-line edits inside BF-946's entry:
- SEARCH `- *Continuation.* A failed delivery ends the run unless its call is tier 1 by `is_tier_1_tool_call`; the native readers are not, so every failed recovery or source read still ends it, and R2-1's refusals are unchanged.`
  REPLACE `- *Continuation.* A failed delivery ends the run unless its call is tier 1 by `is_tier_1_tool_call`, or it is a recovery read whose slice is over the bound (`recovery_slice_too_large`, the Captain's decision on #1723); every other failed recovery or source read still ends it, and R2-1's refusals are unchanged.`
- SEARCH the two lines `- *Residual.* Recorded limits L1 to L11 of the contract; the promised read over the bound is the Captain's decision on #1723.` and `- *Reversal.* Revert the BF-946 commits.`
  REPLACE `- *Residual.* Recorded limits L1 to L7 and L9 to L11 of the contract.` and `- *Reversal.* Revert the BF-946 commits; reverting M5 alone restores the stop on a promised read over the bound.`

M5's commit message is in §5.

## 8. Tracking (M4's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-02. If M4 is committed later (`git log -1 --format=%cs`), use that date in both heads.

**P4-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-946 (2026-11-02), #1723 -- a read-only tool's result that cannot be delivered comes back to the agent as an error.** On the base any failed AD-1240 delivery ended the whole run. Now the run goes on past a failed delivery whose call is read-only by `is_tier_1_tool_call` (the `PARALLEL_SAFE_TOOL_IDS` allowlist, such as `event_log_query`, or a tier-1 browser action): that result promised nothing, so the model is shown `retry_delivery_error` (the bounded code and a request to ask for less) and the run continues within its iteration and token caps. A failed delivery from any other call, and every refused promised read (R2-1), still ends the run. Each typed delivery failure logs one WARNING naming the code, tool, agent, raise site and, for a frame `_admit` refuses for size, the measured length against the bound. The live failure of 2026-10-31 (Forge; a read-only copy of `events.db`, read on 2026-11-02) was a `read_file` of a promised result, in the turn's last two tool calls, with a slice over the 6,000-character bound, not a fresh result; that promised read still ends the run, and whether it should go on is the Captain's decision on #1723. No config field. The contract is `prompts/bf-946-read-only-delivery-failure-continues.md`.

```

**P4-2** `DECISIONS.md`

SEARCH:
```
### AD-1356 S1 -- Agent work stops filing what a rule can decide (2026-11-02, #1722)
```
REPLACE:
```
### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)

- *Scope.* `cognitive/swe_harness/agentic_loop.py` (`_continues_after_failed_delivery`, `_delivery_stop`, `format_tool_result_content`), `cognitive/swe_harness/result_offload.py` (`retry_delivery_error`, `_OversizedFrame`, `_log_delivery_failure`, `DeliveryContext.tool_name`), tests. Contract `prompts/bf-946-read-only-delivery-failure-continues.md`.
- *Continuation.* A failed delivery ends the run unless its call is tier 1 by `is_tier_1_tool_call`; the native readers are not, so every failed recovery or source read still ends it, and R2-1's refusals are unchanged.
- *Text.* The model is shown `retry_delivery_error`: `safe_delivery_error` and a request to ask for less, or `safe_delivery_error` alone when the bound is too small. A stopped run's reply is unchanged.
- *Log.* One WARNING per typed delivery failure: code, tool, agent, raise site, and the measured length against the bound for a frame `_admit` refuses for size.
- *Measured.* At the 6,000 bound a fresh pointer frame of a result that is not delegated is under 5,600 characters; the live failure was a promised read over the bound (`_prepare_result`'s recovery branch), shown on a read-only copy of `events.db`.
- *Rejected.* Continuing after any producer's failed delivery (a state-changing call could run twice); truncating an oversized frame (AD-1240 never truncates a delivery); raising `tool_result_max_chars`.
- *Residual.* Recorded limits L1 to L11 of the contract; the promised read over the bound is the Captain's decision on #1723.
- *Reversal.* Revert the BF-946 commits.

### AD-1356 S1 -- Agent work stops filing what a rule can decide (2026-11-02, #1722)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them.

**Not updated:** `docs/development/roadmap.md`. Its Bug Tracker table lists BFs that were filed and deliberately not fixed (`:1139`).

**Merge note:** the build base already holds AD-1356 S2's entries: in PROGRESS.md directly under `# ProbOS Progress`, in DECISIONS.md after S1's entry. P4-1 puts BF-946's entry above S2's; P4-2 puts it above S1's heading, so above both AD-1356 entries. Neither pair needs a merge.

## 9. What this does NOT change

- R2-1, and AD-1240's promised-recovery semantics except one case: M5 (R-a) lets the run go on past a promised read whose slice is over the bound (`recovery_slice_too_large`), with the promise, reader and artifact unchanged. M1 to M4 alone keep that stop (T4).
- `ResultDelivery`, `delivery_failure`, `safe_delivery_error` and a failed delivery's `presentation`. The final reply of a stopped run is byte-identical.
- `tool_result_max_chars` and every config field. Also `EventType`, the AD-1151 trace schema, the strict profile (no delivery run, `_open_delivery_run`), `PARALLEL_SAFE_TOOL_IDS` and `is_tier_1_tool_call`.
- The results under the threshold. Their legacy delivery stays byte-identical (golden test `test_ad1240:273`).
- AD-1347 and AD-1356's agent-work routing, and the tool-offer gap Forge reported. Not edited.

## 10. Mutation rows (campaign of record on M3's head for MX-1 to MX-8; on M5's head for MX-9 to MX-11)

The Line cells hold the source line without its leading indentation. Prefix `MX` (absent from `DECISIONS.md`; `prompts/ad-1328-s2c-command-escalation-resume.md` uses it for its own rows).

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| MX-1 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `return is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)` | `return False` | `test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds` |
| MX-2 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `return is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)` | `return True` | `test_a_failed_delivery_still_ends_the_run_for_a_producer_that_is_not_read_only` |
| MX-3 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `if isinstance(item, InvocationRefusal):` (in `_delivery_stop`) | `if False:` | `test_a_promised_read_whose_authority_is_lost_still_ends_the_run` |
| MX-4 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `if delivery is not None and delivery.status == "failed":` (in `format_tool_result_content`) | `if False:` | `test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds` |
| MX-5 | `src/probos/cognitive/swe_harness/result_offload.py` | `return text if max_chars == 0 or len(text) <= max_chars else base` | `return text if max_chars == 0 or len(text) < max_chars else base` | `test_the_retry_text_fits_the_bound_or_falls_back_to_the_bounded_code` |
| MX-6 | `src/probos/cognitive/swe_harness/result_offload.py` | `raise _OversizedFrame("delivery_frame_too_large", len(text), maximum)` | `raise WorkspaceResultError("delivery_frame_too_large")` | `test_each_failed_delivery_logs_one_content_free_warning_naming_its_site` |
| MX-7 | `src/probos/cognitive/swe_harness/result_offload.py` | `_log_delivery_failure(exc, context)` | delete the line | `test_each_failed_delivery_logs_one_content_free_warning_naming_its_site` |
| MX-8 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `captured, DeliveryContext(delivery_run, delivery_remaining, use.tool_call.name),` | `captured, DeliveryContext(delivery_run, delivery_remaining),` | `test_each_failed_delivery_logs_one_content_free_warning_naming_its_site` |
| MX-9 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `return code == "recovery_slice_too_large" or is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)` | `return is_tier_1_tool_call(use.tool_call.name, use.tool_call.arguments)` | `test_a_recovery_read_over_the_bound_comes_back_naming_the_bound_and_a_smaller_read_is_served` |
| MX-10 | `src/probos/cognitive/swe_harness/result_offload.py` | `if settings.max_chars > 0 and len(text) > settings.max_chars:` | `if settings.max_chars > 0 and len(text) >= settings.max_chars:` | `test_a_recovery_read_over_the_bound_comes_back_naming_the_bound_and_a_smaller_read_is_served` |
| MX-11 | `src/probos/cognitive/swe_harness/result_offload.py` | `if code == "recovery_slice_too_large" and max_chars > 0 else _RETRY_GUIDANCE` | `if False else _RETRY_GUIDANCE` | `test_a_recovery_read_over_the_bound_comes_back_naming_the_bound_and_a_smaller_read_is_served` |

**Campaign of record.** Run an unmutated baseline of the new file first. Then run each row against the file that holds its killer. Record the base tree and the sha256 of every mutated `src` file.

## 11. Recorded limits

- **L1.** A continued failure keeps the producer's `is_error`. The flattened transcript (`structured_tool_messages: false`) shows `error=False` beside the failure text. The structured transcript, which the live config uses, has no such flag.
- **L2.** The DM disclosure and `detect_tool_defect` read `is_error`, so a continued delivery failure is neither disclosed nor counted.
- **L3.** The model may ask again for the same oversized result. Only the iteration and token caps bound that.
- **L4.** The trace's `presentation_chars` for a failed delivery measures the bounded code, not the retry text the model was shown.
- **L5.** An agent without the reader can only narrow below 12,288 bytes; it never sees an offloaded artifact.
- **L6.** The WARNING's site names the build's function names and line numbers.
- **L7.** A delegated result is not tier 1. Its failed delivery, and every refused promised read, still ends the run.
- **L8.** Without M5, a promised read whose slice is over the bound still ends the run. This was the live failure of 2026-10-31.
- **L9.** The untyped `delivery_unavailable` path logs one ERROR, which names no site.
- **L10.** A group whose only delivery failed is kept whole from compaction.
- **L11.** Forge's observation that `read_file` was not offered before a grant, despite the rank defaults, is not addressed.

## 12. Verified Against Codebase (2026-11-02, on `0ac7bdf3`)

```
git diff --stat e9140fcb 0ac7bdf3 -- result_offload.py agentic_loop.py workspace_results.py tool_call.py tools.py
  workspace_result_store.py event_log_query_tool.py dm/reply_value.py tests/test_ad1240_tool_result_delivery.py -> empty
Read src/probos/cognitive/swe_harness/result_offload.py :1-671
  24-32 imports; 193-198 DeliverySettings; 260-283 reader (274 reader_unavailable); 295-352 invocation_context;
  428-431 DeliveryContext; 434-444 delivery_failure; 447-452 safe_delivery_error; 455-458 _admit; 461-471 _evidence_prefix;
  474-488 _worked_call/_workspace_frame; 515-526 prepare_result; 529-608 _prepare_result (555-563 recovery, 561 _admit;
  564-565 threshold; 566 canonical_capture; 569-570 bind/reader; 574-576 allowance; 599, 604 workspace _admit); 657 capture raise
Read src/probos/cognitive/swe_harness/agentic_loop.py :20-45, :155-163, :250-278, :640-756, :845-922, :1188-1261,
  :1296-1335, :1540-1585, :1660-1699, :2085-2229, :2536-2611, :2700-2911
  34-45 result_offload imports; 155-163 PARALLEL_SAFE_TOOL_IDS (event_log_query; no reader); 725-754 is_tier_1_tool_call;
  855-869 format_tool_result_content; 893-922 build_tool_result_messages; 1192-1223 _open_delivery_run; 1245-1261
  _delivery_stop; 1562-1565 DeliverySettings(self._tool_result_max_chars, ...); 2094-2111 delivery_remaining;
  2121-2155 outcomes, extend, stop; 2162-2204 render paths; 2225-2229 protected groups; 2576-2587 refusal; 2859-2868 delivery
Read src/probos/execution/workspace_results.py :15-164, :217-399 (19 threshold; 22 outline; 25 read args; 37-44 error;
  243-268 promises kept for the run; 351-367 ResultDelivery)
Read src/probos/execution/workspace_result_store.py :858-897, :1103-1132 (893-895 slice without a cap)
Read src/probos/cognitive/swe_harness/tools.py :360-395, grep "limit" (470-478 no cap); grep constructions (372, 376, 393, 490, 796)
Read src/probos/cognitive/swe_harness/tool_call.py :690-911 (762-802 inspection, 817-848 result/legacy, 891-911)
Read src/probos/tools/event_log_query_tool.py :206-341, :590-615 (615 ToolResult(output=dict))
Read src/probos/cognitive/dm/reply_value.py :69-130 (124 is_error); src/probos/cognitive/agentic_dispatch.py :2251-2281, :3988-4141, :4340-4368
grep tool_result_max_chars config/system.yaml -> 2483: 6000 (2466 structured, 2472 parallel); d:\ProbOS\config\system.yaml 2489, 2472, 2478
Read tests/test_ad1240_tool_result_delivery.py :27-195, :400-404, :665-766, :795-823, :1606-1676, :1736-1765, :1822-1840,
  :1867-1918, :1930-2047, :2645-2859, :3532-3576, :3690-3711, :4355-4372, :4404-4547, :5030-5074
docs/development/architecture-baseline.yaml :649-656 (AgenticLoop srp row, trigger "lines")
tests/test_ad1324_srp_layout.py :32, :61 (AgenticLoop <= 13 methods)
scripts/gen_ad_ledger.py :124-139 (status keywords, head window 120); PROGRESS.md :1-8; DECISIONS.md :1-13, :1244, :1255
logs/bf946/probe-output.txt (gitignored; premises held, exit 0); logs/bf946/live-trace-output.txt (gitignored; rows 415370-415406)
```

## Absence Verified (2026-11-02, on `0ac7bdf3`; A1, A3, A4, A5 and A8 re-run by amendment A3 on `04bc58bb`, where the cited `src` and test lines are unchanged)

```
A1 CLAIM: in src a ResultDelivery is read only through result_delivery (tool_call.py:891-896), from agentic_loop.py and
          result_offload.py. Of its readers, only _delivery_stop and format_tool_result_content use a failed delivery's
          code or presentation; delivery_trace records its status, code and presentation length; the render and
          compaction checks test only whether a delivery is present. delivery_failure is called only in
          result_offload.py; safe_delivery_error is called in result_offload.py and in agentic_loop.py at the R2-1 stop
          and at the lost-reader stop (:1698), which builds its reply from a code, not from a delivery.
   RUN:   Grep "delivery_failure\(|safe_delivery_error|status == \"failed\"|delivery\.status|result_delivery\(" over src;
          Grep "\.delivery\b|\.presentation\b|delivery_trace\(" over src;
          Grep "asdict\(|dataclasses\.fields\(|vars\(" over swe_harness/*.py and agentic_dispatch.py
   FOUND: workspace_results.py:361, :366 (validation); tool_call.py:891, :895 (the accessor); agentic_loop.py:43 (import),
          :589 (delivery_trace), :863, :867, :869 (formatter), :1256-1260 (_delivery_stop), :1698 (lost-reader stop),
          :2179, :2200, :2221, :2228 (presence checks); result_offload.py:434-439, :447, :520, :526 (construction),
          :612, :616, :617, :636 (delivery_trace); checkpoint.py:56, crew_session.py:6619, crew_orchestrator.py:861,
          crew_finalizer.py:623, decomposer.py:840, :1066 (other statuses); message_receipts_tool.py:229 and media-type
          strings (other meanings); no asdict, fields or vars walker
   HOLDS: yes
A2 CLAIM: format_tool_result_content and build_tool_result_messages are called in src only inside agentic_loop.py.
   RUN:   Grep "format_tool_result_content\(|build_tool_result_messages\(" over src
   FOUND: agentic_loop.py:855, :893 (definitions), :914, :2163, :2193
   HOLDS: yes
A3 CLAIM: no test builds a failed delivery for the formatter. test_ad1191_delegation_wire.py:657 asserts a failed
          delivery's presentation directly (delegate_task, not tier 1: its run still stops, and the presentation is
          unchanged); the other "Result delivery failed" hits assert a stopped run's final_text, which M2 leaves unchanged.
   RUN:   Grep "ResultDelivery\(\"failed\"|Result delivery failed|presentation_chars" over tests;
          Grep "format_tool_result_content\(|build_tool_result_messages\(" over tests
   FOUND: ResultDelivery("failed": test_ad1240:618, :1763 (with_result_delivery only); "Result delivery failed":
          test_ad1191_delegation_wire.py:655, test_ad1240 :618 :1096 :1763 :2832 :3573 :3709 (final_text or
          safe_delivery_error); formatter calls: test_ad1146:181,:188, test_ad1148:286,:299,:318,
          test_ad1191_delegated_evidence:163,:164,:648,:673,:691, test_ad1240:2652-2669 (status "workspace"), test_bf761:341
   HOLDS: yes for direct constructions; loop runs are covered by A4
A4 CLAIM: no existing loop test asserts a stop on a failed delivery of a tier-1 call.
   RUN:   Grep "workspace_results=|loop\.workspace_results =" over tests; Grep tier-1 ids over tests/test_ad1240_*.py;
          Grep "stopped_reason == \"error\"" over test_ad1240; Grep the delivery codes over tests (files only)
   FOUND: loops armed by that keyword only in test_ad1240_tool_result_delivery.py and test_ad1240_workspace_results.py
          (no tier-1 id there); test_ad1191_delegation_wire.py arms one through dispatch (delegate_task, not tier 1, A3);
          test_ad1240_workspace_result_lifecycle.py names the codes and runs no loop; tier-1 producers test_ad1240:3541,
          :3662 (small sibling), :4463 (http_fetch "ok"), :4527 (http_fetch 13,000, asserts complete), :5042 (http_fetch,
          then an InvocationRefusal); 27 lines in test_ad1240 assert stopped_reason == "error"; the stops read at :2044
          :2256 :2285 :2577 :2640 :2829 :2855 :4109 :4507 use a producer that is not tier 1, and the rest were not read one
          by one. G5 on the oracle's last stage (785 passed, 8 skipped; the orchestrator's run) runs
          test_ad1240_tool_result_delivery.py, test_ad1240_workspace_results.py and test_ad1191_delegation_wire.py, and a
          pinned stop on a tier-1 call's failed delivery would fail there
   HOLDS: yes
A5 CLAIM: of the test lines the two searches below find, only test_ad1240's oversized_slice case
          (test_owned_recovery_refuses_unconsumable_slice_without_recursive_offload, :2710-2752) pins the stop on a
          recovery slice over the bound.
   RUN:   Grep "delivery_frame_too_large" over tests;
          Grep "WorkspaceSliceToolResult|recovery=True|recovery_iterations_unavailable" over tests
   FOUND: test_ad1240 :1675 (fresh, direct), :1839 (receipt), :2027-2028 (fixture_result, fresh), :2658, :2662
          (formatter), :2696 (delegation), :2745 (oversized_slice), :2855 (error outcome, fresh), :4371 (owned steps);
          second search: test_ad1240 :74 (import), :1532, :1712, :4725, :4730 (slices served), :1427, :2029, :4448,
          :4451, :4454 (iterations)
   HOLDS: yes
A6 CLAIM: no .py file names retry_delivery_error, recovery_slice_too_large, _OversizedFrame, _continues_after_failed_delivery,
          _log_delivery_failure or _RETRY_GUIDANCE, and no test file test_bf946* exists.
   RUN:   Grep "retry_delivery_error|recovery_slice_too_large|_Oversize" and
          "_continues_after_failed_delivery|_log_delivery_failure|_RETRY_GUIDANCE|tool_name: str = \"\"" (*.py);
          git ls-files tests/test_bf946*
   FOUND: none; none; none
   HOLDS: yes
A7 CLAIM: DeliveryContext is built in src only at agentic_loop.py:2868, and in tests only positionally with two arguments.
   RUN:   Grep "DeliveryContext\(" (*.py)
   FOUND: agentic_loop.py:2868; test_ad1240 :762 :802 :1424 :1426 :1638 :1662 :1669 :1700 :1728 :1742 :1834 :1838
          :1852 :1856 :4365 :4370 :4387 :4400 :5302
   HOLDS: yes
A8 CLAIM: no test calls _delivery_stop or _executed_outcomes, and no test names agentic_loop.py or result_offload.py
          except the hits below.
   RUN:   Grep "_delivery_stop|_executed_outcomes" over tests; Grep "(result_offload|agentic_loop)\.py" over tests;
          Grep "rglob\(\s*["']\*\.py|glob\(\s*["']\*\*/\*\.py" over tests (files only)
   FOUND: none; ad1152_agentic_off_golden.json:6 (a historical base blob; test_ad1152_agentic_correlation.py:518-528
          compares a run's observation, not the blob), test_ad1320:663 (budget_awareness_state hits),
          test_ad1324_srp_layout.py:32, :61 (method count); 61 test files walk every .py under a root
   HOLDS: yes for the first two searches; the 61 walkers were not read one by one (Not verified, below)
```

**Not verified (the orchestrator measures):** T6's premise that 100 < frame length < 900 for the 100-row envelope at a three-digit bound. The `_envelope` docstring's "about 410 characters and 27 inspection slots per row". The 61 test files that walk every `.py` under a root (A8); the broad gate runs them. That `_environment` accepts a freshly created subdirectory. The two checker scripts' verdicts. That the flattened transcript's `_last_result` returns exactly the retry text.

## 13. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** no method is added to `AgenticLoop` (its srp row freezes the "lines" trigger only). `_continues_after_failed_delivery`, `retry_delivery_error` and `_log_delivery_failure` are module functions. `traceback` is stdlib. No `create_task` and no database connect.
- **`check_dormant_classes.py --check`:** `_OversizedFrame` is instantiated in `_admit` (M3) and in the recovery branch (M5).
- **Config:** no field. **EventType:** none.
- **`gen_ad_ledger.py --check`:** passes once M4 regenerates the ledger. The heads are free of status keywords in their first 120 characters.
- **Collection:** one new file under `tests/`. M1's strict xfails make G1 green on the base.

## 14. Prior Art and Blind Spots

- **Internal:**
  - AD-1240 R2-1 is kept as is, and T5 pins it.
  - AD-1147's read-only allowlist is reused through `is_tier_1_tool_call` (AD-1208), the predicate `_counts_toward_max_iterations` already uses. AD-1356 S2's `tools/effect_tiers.py` tiers agent-work calls for approval and lists `read_file` and `codebase_read_source` as routine; BF-946 does not consult it.
  - AD-1148's elision marker (`_ELISION_MARKER`), which tells the model to re-run the tool with a narrower query, has the same intent as `_RETRY_GUIDANCE`.
- **External** (date used: 2026-11-02):
  - OpenCode (overdue; examined). PR 23770 makes its tool-output truncation limits configurable (defaults 2,000 lines and 50 KB) and says output over them is truncated and saved to a truncation directory. In PR 22660 the shell tool shows the agent a truncated part and the saved file's path (`Full output saved to: <file>`). This matches the AD-1240 pointer (the whole result kept, a bounded frame naming its path); nothing adopted for BF-946. ([PR 22660](https://github.com/anomalyco/opencode/pull/22660/files), [PR 23770](https://github.com/anomalyco/opencode/pull/23770))
  - SWE-agent (overdue; examined). Its ACI page says the file viewer "works best when displaying just 100 lines in each turn", and its file editor has "commands for scrolling up and down and for performing a search within the file". A stated per-read window is the same idea as a per-read bound; adapted as M5's text naming the bound. ([ACI](https://swe-agent.com/latest/background/aci/))
  - Claude Code (not overdue; cited). A user report quotes its file-read error: "File content (93214 tokens) exceeds maximum allowed tokens (25000). Please use offset and limit parameters to read specific portions of the file, or use the GrepTool to search for specific content." The error names the limit and asks for a smaller read, which is M5's shape. ([anthropics/claude-code#19085](https://github.com/anthropics/claude-code/issues/19085))
  - LangGraph `ToolNode.handle_tool_errors` returns selected error classes to the model as a tool message and re-raises the rest. That matches O1's selective continuation. ([reference](https://reference.langchain.com/python/langgraph.prebuilt/prebuilt/tool_node/ToolNode))
  - Considered, deferred (overdue, not relevant here): MCP Apps, AG-UI.
- **Blind spots found:**
  1. The issue's premise that the turn made one call was wrong (§1.3). The fix it proposed would not have touched the live site.
  2. The pointer frame does not state the per-read bound, so a model can ask for a slice over it (the probe's `limit` 6001 and no-`limit` reads, §1.2). M5 states the bound only after such a read is refused; the frame is unchanged.
  3. The failing read may have targeted either the `event_log_query` artifact or a source promised by the previous burst's `codebase_read_source`. Both go through the same branch, so M5's text says "characters" and "range", which is true for both.
  4. Continuing after a failed delivery from a state-changing call could run its effect twice, which is why the predicate is read-only only.
  5. Limits L1 to L11.

**Row updates for `docs/research/reference-projects.md`** (the orchestrator applies them in its next docs change):
- OpenCode (magic context): ``2026-11-02 | absorption | `opencode-magic-context-absorption.md`; BF-946 (#1723) Prior Art, `prompts/bf-946-read-only-delivery-failure-continues.md` (checked: tool output over the configurable 2,000-line / 50 KB limits is truncated and saved to a file; the shell tool shows a truncated part and the saved file's path)``
- SWE-agent: ``2026-11-02 | checked | BF-946 (#1723) Prior Art, `prompts/bf-946-read-only-delivery-failure-continues.md` (the ACI file viewer works best showing 100 lines per turn; the editor has scroll and search commands); AD-360 builder guardrails (container-scoped isolation)``

## 15. Diff Reviewer: properties to verify

1. `_delivery_stop` returns a stop for every `InvocationRefusal`, and for every failed delivery except those `_continues_after_failed_delivery` admits. Without M5 that is exactly the tier-1 calls; with M5, also `recovery_slice_too_large`.
2. A stopped run's `final_text` is byte-identical to the base for every code. `ResultDelivery.presentation` is unchanged.
3. `format_tool_result_content` renders `retry_delivery_error` only for a failed delivery, and the rendered text is never longer than `max_chars` when `max_chars > 0`.
4. Every new or rewritten docstring, comment, log line, agent-facing text and test docstring is true of the head in the code's branch order. No text claims a read-only continuation for a reader.
5. The WARNING carries no payload text: only the code, tool name, agent prefix, function names with line numbers, integers, and the constants `n/a` and `<unnamed>`.
6. No config field, `EventType`, persisted key or `AgenticLoop` method is added. `DeliveryContext.tool_name` defaults to `""`.
7. M5 only: the promise is not consumed; the same path at a smaller range is served (T4').
8. T1, T5 and T6b each start at the producer call and end at the run's result.

## 16. Acceptance criteria

1. T1: an oversized `event_log_query`-shaped result (no reader, or too many slots) comes back as the retry text, and a narrower call in the same run succeeds. This holds on both transcripts.
2. T5, `test_promise_survives_authority_loss_through_the_loop` and `test_workspace_promise_refuses_replaced_reader_before_invocation`: a promised read whose authority is lost still ends the run with `stopped_reason=error`.
3. T6a and T6b: a fresh frame at the bound is delivered, and one character over takes the error path. On M1 to M4, T4: a promised read at 6000 is served and at 6001 stops. With M5, T4' replaces it: the 6001 read comes back naming the bound, and the 6000 re-read is served.
4. T8: one WARNING per typed failure, naming the site and, for a frame `_admit` refuses for size, the measured length.
5. `test_legacy_requests_match_pre_edit_golden` passes: results under the threshold are byte-identical.
6. Every §10 mutant is killed. G1 to G5 pass, the §13 checks pass, and the broad gate's receipt is green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
