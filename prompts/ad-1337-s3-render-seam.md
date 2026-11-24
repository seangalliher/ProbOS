# AD-1337 S3 (#1560): the render seam and the routes. What the agentic loop hands a model is masked, and every route past the tool executor is masked or has a recorded reason

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-21
**Revised by:** claude-architect (Claude Code, Opus 5.5), 2026-11-21, rev1
**Revised by:** claude-architect (Claude Code, Opus 5.5), 2026-11-21, section 17 (repair after review round 1)
**Revised by:** claude-architect (Claude Code, Opus 5.5), 2026-11-22, section 18 (repair after review round 2)

**Status:** rev1, repaired after review round 1 by section 17, which amends 7.1, 7.2, 10 and the trackers and edits `crew_verifier.py` and the AD-1320 blob pin, and after review round 2 by section 18, which amends 7.1, 7.2, 10 and the trackers. Proven as a draft on an oracle where S3 sat on S1 before its section 17 repair and on S2 rev0: the tests alone gave a collection error, and with all pairs 18 passed. Rev1 was proven on the rev1 oracle and again on the final base (section 16). Batch 1 is S1 + S2 + S3: one PR (`Refs #1560`), one broad gate. S3 must not merge alone. Decision: consult `4bb6d748` (on #1560, comment 7064966284), corrected here in D2 and D8. No Captain condition.

**Rev1 changes (2026-11-21):**
- X10 now anchors on `class SecretHandle:` and its docstring line. The old anchor, the end of `_map_strings`, was rewritten by S1's section 17 repair (RB3). Both helpers keep their text.
- N3 is extended to pin the label cap (16, the rest counted) and the call-id cap (128 characters).
- N7 is extended with a strict-profile run. It pins the loop's own `final` call: `strict=strict` and `correlation=trace_correlation`.
- Section 10 gains T12 to T18, and T11's killer is corrected to N2.
- Section 16 is the orchestrator's.
- Counts are unchanged: 16 cases, 18 items.

**Base:** `origin/main` (`5d8a5eb4`) plus S1 (with its section 17 and section 18 repairs) and S2 rev1, as committed on the build branch, ending at `089895c1`.
- From S1, S3 uses `SecretMasker.mask_text`, `.mask_result`, `MASKING_FAILED_TEXT` and `secret_forms`.
- From S2, it uses `ToolExecutor(secret_masker=)`, `ToolExecutor.secret_masker`, `_runtime_secret_masker`, `EventType.SECRET_MASKED`, `SECRET_MASKED_MAX_NAMES` and `_calls_building_a_tool_executor`.

**Line endings:**
- Every edited file that exists on `main` is `i/lf w/crlf` (`git ls-files --eol`).
- `src/probos/security/secret_masking.py` (S1's) is LF.
- The SEARCH blocks are LF; match and write each file with its own endings.
- The new files are LF and ASCII only.

**Milestones** (one Builder delegation each; the Builder applies the pairs and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then 7.2 (new module), then X1 to X10 and F1 (7.3 to 7.9) | HIGH, security control | One full review by the GPT Diff Reviewer with section 14's properties. The mutation campaign of record (section 10) stands in for a second reviewer. If round 1 finds a Critical or High defect, the repair gets a full re-review, not a delta. |
| M2 | TR1 to TR4, then the ledger (7.10 to 7.13) | LOW | Delta |

- Commit subjects:
  - M1: `Mask what the agentic loop hands a model and the routes past the executor`
  - M2: `Record the render seam in the status, decisions and research entries`
- About 35 Builder tool calls for M1 and 12 for M2.

## 0. Premises (this tree)

| P | Premise | Evidence |
|---|---|---|
| P1 | Every model-bound tool result is produced in `AgenticLoop._execute_one_tool`, except the parallel batch's conversion | `agentic_loop.py:2575-2579` (parallel), `:2644` (BF-965 refusal, constant), `:2856`, `:2872`, `:2880`, `:2940-2949`, `:2960-2966`; `return tcr` `:3000` |
| P2 | The model reads `delivery.presentation` for a delivered result and the bounded `tcr.output` otherwise | `format_tool_result_content`, `agentic_loop.py:875-890` |
| P3 | `effect_correlation` is a per-instance attribute set after the result is built, so `replace(tcr, ...)` drops it | `tool_call.py:693` (ClassVar), `agentic_loop.py:2967-2973` |
| P4 | `legacy_result` re-renders an oversized dict, list or tuple from the raw value, not from the captured text | `tool_call.py:842-848`, `:444-446` |
| P5 | `AgenticLoop` has 13 methods, at its cap; its line count is grandfathered debt | `test_ad1324_srp_layout.py:32`, `:60-61`; `architecture-baseline.yaml:650-653` |
| P6 | The AD-1152 golden pins every `AgenticLoop` constructor's keywords by sha256 | `test_ad1152_agentic_correlation.py:173-182`, `:549-570`; golden `:435-466` |
| P7 | Two constructions, no alias, no subclass in `src` | `agentic_dispatch.py:4174`, `native_builder.py:140` |
| P8 | The dispatch loop's executor is S2's `DispatchToolExecutor(secret_masker=_runtime_secret_masker(runtime))`; the harness's is the runtime executor from finalize | `agentic_dispatch.py:3029-3033`; `finalize.py:5912` |
| P9 | The digests stay like with like: `SourceRef.raw_sha256` is the file's; the workspace payload's sha256 is the capture's and is checked against the stored payload | `result_offload.py:646-653`, `:709-740`; `workspace_results.py:133-139`; `workspace_result_store.py:887` |
| P10 | `_source_frame` and `_workspace_frame` quote no captured text (outline, path, digest, worked call) | `result_offload.py:522-554` |
| P11 | The tier-1 browser result becomes the action's `result` and the episode's `outcomes[0]["result"]` | `reply_pipeline.py:1189-1194`, `:1222` |
| P12 | The loop's emitter is `runtime.emit_event` (synchronous) at both constructions | `agentic_dispatch.py:4177`, `native_builder.py:145`, `runtime.py:2034` |
| P13 | Under the strict profile the parallel branch re-raises a failure instead of converting it, so its `final` only ever runs non-strict | `agentic_loop.py:2557-2560` |
| P14 | A strict call whose result carries `operation_id`, `attempt_id`, a known `effect_outcome` and a `reason_code` gets a trusted `trace_correlation`, which the completed event validates | `agentic_loop.py:2780-2805`, `:2974-2999`; `effect_adapters.py:375-404`, `:669-708` |

## 1. Problem

S2 masks every `ToolResult` a registry returns. The model still receives text that never passed that seam:
- a raised exception's text (`agentic_loop.py:2945`, `:2577`);
- the `str()` of an output the producer seam leaves as it is (a custom object, `bytes`, a container past the walk bounds, P4);
- AD-1240's captured text, which becomes the offloaded payload and its recovery slices.

`reply_pipeline`'s inline browser call skips the executor, and its output is written to an episode that later prompts recall (P11).

## 2. Overview

| Part | Change |
|---|---|
| New `cognitive/swe_harness/render_masking.py` | `SecretMaskerSlot` (the loop's masker) and `RenderMask`: `capture` before `prepare_result`, `final` on each result the loop returns, and at most one `SECRET_MASKED` (`seam: "render"`) per tool result |
| `cognitive/swe_harness/agentic_loop.py` | The slot; one `RenderMask` per call; the capture and final passes; the parallel conversion |
| `cognitive/agentic_dispatch.py`, `swe_harness/native_builder.py` | Each loop takes its executor's masker after construction; `_runtime_secret_masker` uses the shared filter |
| `cognitive/dm/reply_pipeline.py` | The tier-1 browser result is masked before `mark_executed` and the episode |
| `security/secret_masking.py` | `secret_masker_of`, `mask_route_result` (placed above `class SecretHandle`) |
| `tests/test_ad1195_durable_producers.py` | The render module joins `SECRET_MASKED`'s producer row; no count changes |
| `cognitive/crew_verifier.py` (section 17) | The session correction's runtime projection carries the runtime's masker |
| `tests/test_ad1320_agentic_budget_awareness.py` (section 17) | The `native_builder.py` blob pin moves to S3's blob |

**Heavier designs rejected:**
- A constructor keyword: it would change the AD-1152 golden (P6).
- An `AgenticLoop` method: the class is at its cap (P5).
- Masking in `format_tool_result_content`: it runs after the bound truncates (a cut value no longer matches), and it misses the trace, the AgenticResult and the payload.
- A thread for the pass: S2 D2 still holds. Only the captured and the final text can be long, and each costs at most S1's measured 22 ms (1 MiB, 50 values); the frame and the call id are short (D6).
- Sealing the slot when the run starts: only the two constructions assign it, and N13 pins that.

## 3. Consumers checked

| Changed | Consumer | Result |
|---|---|---|
| A slot, not a keyword | AD-1152 golden (P6); every loop double (`**kwargs` or plain attribute assignment: `test_ad1007:299`, `test_ad1142:376`, `test_ad1209:264`, `test_bf731:235`, subclasses `test_ad1190:2086`, `test_ad1240:3867`) | Unchanged |
| No new method | `test_ad1324_srp_layout.py:60-61` | 13 methods (section 16) |
| `RenderMask` with no masker or no match returns its argument | AD-1240 golden `_capture_baseline` (`test_ad1240:212-279`), strict baseline, AD-1147, AD-545 | Unchanged; N11 re-runs the golden with a masker that matches nothing |
| `SECRET_MASKED` from a second file | AD-1195 PROD-1 (`test_ad1195_durable_producers.py:126-188`) | F1 adds the file; `emit_fn(EventType.SECRET_MASKED, ...)` is the shape it looks for |
| A render event in a dispatch run with a producer hit | S2's N5 (`[payload] = events.masked()`) | The loop sees `<secret:github>` and finds no hit, so no second event |
| `secret_masker_of(executor)` on a MagicMock executor | `test_ad546_native_builder_harness.py:37` | None, so no `TypeError` |
| reply_pipeline step_4e | AD-745 tests (runtime without a masker), AD-1343 `DIRECT_TOOL_INVOKES` and `SOURCE_ORDER` (`ad1343_seam_registry.py:92-97`, `:110`), AD-1346 shadow | Unchanged: there is no new `*tool.invoke(` call and the stop check still comes first |
| `_runtime_secret_masker` body (X6) | S2 rev1's N4 (`test_ad1337_executor_seam.py:225-229`: a real masker, a bare namespace, a `MagicMock`) and N19 (`:533-539`: the keyword source `_runtime_secret_masker(runtime)` at the construction) | Unchanged: `secret_masker_of` is the same `isinstance` filter, and X6 does not touch the call site |
| `secret_masking.py` gains two module functions above `SecretHandle` | S1's census of `masked_credential_values` (`test_ad1337_secret_masking.py:516-520`) | Unchanged: neither function names it |
| Owned-steps view / `WorkPullReceipt` hit | `agentic_dispatch.py:4150-4154` (an acknowledgement needs `presentation.output == rendered`); `result_offload.py:603-608` | Fail closed: a masked view is not acknowledged; a receipt longer than the bound becomes a delivery failure |
| `self_query` after a producer hit | `agentic_loop.py:2846-2877` | Fail closed: the model is told `self_query: presentation check failed.` (N8) |
| `native_builder.py`'s five lines (X8) | AD-1320's blob pin (`test_ad1320_agentic_budget_awareness.py:625`) | Missed by rev1; re-pinned by section 17 (no `budget_awareness`, unchanged) |
| `_SessionCorrectionRuntime` gains a defaulted field | `test_ad1126:1773`, `test_ad1241:2529`, `test_ad1190:1507-1560`, `test_ad1205:1695`, `test_ad1346_admission_shadow_crew:244` | Unchanged: none compares the field list; `secret_masker_of` gives None for their doubles |
| A withheld delivered result has no delivery | `_delivery_stop`, BF-946, `DeliveryRun.promised` | A failed delivery keeps its extension, so the stop is unchanged; a dropped delivery leaves its masked payload, reservation and reader offer, as an admitted one does |

**Not checked:** a live run, or the vessel.

## 4. Decisions

- **D1 (positions, (a)).**

  | Branch | Masked by | Why |
  |---|---|---|
  | BF-965 refusal `:2644` | none | The constant `UNOFFERED_TOOL_REFUSAL` |
  | `InvocationRefusal` `:2682` | none | A code, not text |
  | `from_tool_result` `:2856`, `:2880` | `final` | Covers custom `str()` and the P4 re-render |
  | `self_query` failure `:2872` | `final` (no hit) | Fixed text |
  | Exception `:2940-2949` | `final`; when armed, `capture` too (`delivery_source` `:2953`) | The text never passed a `ToolResult` |
  | Armed delivery `:2960-2966` | `capture` before `prepare_result`, then `final` | The payload, its sha256, the frames, the recovery slices and the recorded result all hold the placeholder |
  | Parallel conversion `:2575-2579` | its own `RenderMask(...).final`, `strict=False` | Built outside `_execute_one_tool`; unreachable under the strict profile (P13) |

  `final` runs before the effect correlation is attached (P3) and before the message bound truncates.

- **D2 (wiring, (d)).** `secret_masker = SecretMaskerSlot()` is a class attribute. It accepts a `SecretMasker` or None, and raises `TypeError` for anything else. Each construction assigns `loop.secret_masker = secret_masker_of(<its tool_executor>)` right after construction (P6, P7, P8). The render seam therefore uses the producer seam's masker: the runtime's in production, None for a test executor.
- **D3 (exceptions, (b)).**
  - The non-strict text `Tool X failed: {exc}` is masked by `final`. The strict text is `failure.error_code`, a fixed code that `project_refusal` then replaces (`:2943-2944`, `:2968-2972`).
  - `ToolLockedDenied.result` is registry lock text (`registry.py:475-480`). Non-strict, the registry returns it as a `ToolResult`, so the producer seam masks it. Strict, the loop never renders it.
  - The loop's WARNING tracebacks (`:2931-2939`, `:2567-2574`) are logs, not model text: residual R4.
- **D4 (`self_query` and AD-1240, (c)).**
  - `self_query` after a producer hit fails closed (consult Q4). With only the loop masking, the retained presentation is masked by `final`.
  - Masking the capture changes no digest comparison (P9, P10). A large `read_file` of a file that holds a secret is still delivered as a source frame, its recovery is re-read through the executor and masked again, and `raw_sha256` stays the file's.
  - Fail closed:
    - a placeholder longer than its value can push a line past `_source_frame`'s allowance (`source_line_too_large`), or a receipt past `_admit`; either becomes a typed delivery failure;
    - a capture pass that fails is replaced by a withheld result's capture;
    - a final pass that fails, or a delivered frame that holds a known value, gives a withheld result with no delivered frame; a frame is never rewritten (section 17).
- **D5 (event, (f)).**
  - `SECRET_MASKED` with S2's eight keys:
    - `seam: "render"`;
    - `tool_id`: `tool_record_identity(name)`, None when strict;
    - `invocation_id`: the model's tool-call id (`ToolCallResult.id`, at most 128 characters, holding no known value), None when strict;
    - `operation_id` and `attempt_id` from the strict `EffectCorrelation`;
    - `names` (at most 16), `names_omitted` and `failed`.
  - At most one per tool result: both passes share one `RenderMask`.
  - One WARNING with labels only.
  - The event is emitted through the loop's `self._emit`, and awaited if the emitter returns an awaitable.
  - AD-1195: F1 only. No new member and no count changes.
- **D6 (cost).** The passes run inline: S2 D2 still holds. `capture` and `final` are the two API stages, not the number of masking calls (measured in review round 2). `capture` masks the captured text; `final` masks the returned text, then a delivered result's frame, then, for a non-strict event, the call id. An unarmed call makes at most two `mask_text` calls; an armed delivered call makes three with no hit and four when it emits a non-strict event (three at most under the strict profile). Only the captured and the final text can be long (S1: 22 ms for 1 MiB with 50 values); a frame is bounded by the delivery frame size and a call id by 128 characters. Each call takes one credential snapshot, so with the producer pass a delivered call takes four or five. No redesign (section 18).
- **D7 (routes and census, (e), (g)).** `reply_pipeline` masks with `mask_route_result` before `mark_executed`. N15 pins each route past the executor:

  | Route | Reason |
  |---|---|
  | `ToolExecutor._invoke_once` `check_and_invoke` | The executor itself: the producer seam |
  | `_SessionProjectedToolRegistry.check_and_invoke` (two calls) | A registry subclass delegating; its caller is an executor |
  | `AgentWorkRunner.claim` | Reads `result.error is None` only (`agent_work_runner.py:496`) |
  | `ToolContext.invoke` | No caller in `src` (asserted) |
  | `FederationMCPServer._handle_tools_call` `call_tool` | Internal app tools only (`include_external=False`, asserted), all from `mcp_apps/game_app.py`; the answer goes to the MCP client |
  | `MCPAppRegistry` external handler | Unreached: the one caller passes `include_external=False` |
  | `MCPBridge.invoke` `call_tool` | The bridge's transport; its callers are the bridge rows |
  | `ToolRegistry.check_and_invoke` `tool.invoke` | The tool sink |
  | `step_4e_action_dispatch` `browser_tool.invoke` | Masked (S3) |
  | `ack_action` `browser_tool.invoke` | The Captain's ACK: dispatcher record and HXI answer only; nothing reads `DispatchedAction.result` afterwards (`action_dispatcher.py:180` is its only writer) |
  | `_McpTool.invoke` bridge calls | A registered tool's body: the producer seam |
  | `MCPToolAdapter.invoke` | Never constructed in `src` (asserted) |
  | `submit_mcp_invoke_with_consensus` | Reaches a model through `_McpTool` (producer seam) or a DAG's reflect (S5) |
  | `AgenticLoop._execute_one_tool` `self._executor.invoke` (section 17) | The loop's executor: the producer seam, then the render seam |
  | `DispatchToolExecutor.invoke` `super().invoke` (section 17) | The executor itself |
  | `_EffectDispatchMixin.dispatch` `invoke(context)` (section 17) | The broker's callback, `ToolExecutor`'s `invoke_reserved` |
  | `verify_repair` `executor.invoke` (section 17) | The runtime's `ToolExecutor`; reads `error` only |
  | `BrowserTool.open_captain_session` `self.invoke` (section 17) | The Captain's session open: HXI answer only |

- **D8 (S5, scope).** `Decomposer.reflect` writes DAG node results (mesh `stdout`, `decomposer.py:710-714`) into a model prompt and logs it at DEBUG (`:491`). No seam covers it. That is a separate route class, so it is AD-1337 S5, in batch 2 with S4, and #1560 closes after both.

## 5. Tests: new file `tests/test_ad1337_render_seam.py` (16 cases, 18 items; 18 cases, 23 items after section 17; 19 cases, 24 items after section 18)

| N | Case |
|---|---|
| N1 | The slot: default None, a real masker kept, non-maskers refused, no constructor keyword |
| N2 | No masker, or no match: `capture` and `final` return their argument; no event |
| N3 | Two passes, one event, merged labels, the exact payload, a labels-only WARNING, no form of a value in logs or payload; 17 labels give the first 16 and `names_omitted == 1`; a 128-character call id is kept and a 129-character one is left out |
| N4 | A failed pass withholds both ways; a strict payload has no tool id and no call id; an awaitable emitter is awaited; a raising emitter never unmasks |
| N5 | Loop: an exception's text is masked; one render event |
| N6 | Loop: the parallel conversion is masked |
| N7 | Loop: a custom object's `str()` is masked at the render seam, which the producer seam leaves alone; under the strict profile the loop's event carries the call's correlation and no tool or call id |
| N8 | `self_query`: fails closed after a producer hit; masked when only the loop masks (x2) |
| N9 | Armed: the offloaded payload, its sha256, the frame, the readbacks and the recorded result hold only the placeholder; with no match, the same object and the raw sha256 (x2) |
| N10 | Armed: a large file holding a secret is framed and recovered masked; `raw_sha256` is the file's; no copy is written |
| N11 | A masker that matches nothing keeps AD-1240's pre-edit golden |
| N12 | reply_pipeline: the tier-1 result is masked in the episode; a non-`ToolResult` is withheld |
| N13 | Census: each loop takes its own executor's masker, tied to S2's census |
| N14 | Census: every result the loop hands the model passes the render seam |
| N15 | Census: every route past the executor is masked or has a reason |
| N16 | `secret_masker_of` and `mask_route_result` |
| N17 | A session correction's projected dispatch masks; every dispatch run is handed its caller's runtime or that projection (section 17) |
| N18 | A delivered frame that holds a known value, or whose pass fails, or whose output pass fails, is withheld and never rewritten; a clean frame is delivered (x4, section 17) |
| N19 | Without the strict profile the render event carries no operation or attempt id, directly and through the loop with a tool whose exception carries a correlation; a strict call keeps them (section 18). N4 also pins `source_chars` through the trace |

- **Base (`089895c1`):** collection error `ModuleNotFoundError: No module named 'probos.cognitive.swe_harness.render_masking'`.
- **After M1:** 18 passed.

## 6. What S4 and S5 need from S3

- **S4:** nothing new. It registers in `runtime.secret_registry`.
- **S5:** `secret_masker_of(self.runtime)` and `mask_text` on the reflect prompt before it is truncated or logged. S5 adds the DAG route to N15's table. A `SECRET_MASKED` it emits takes an id only from a source the runtime issued (section 18, F1).

## 7. The contract

### 7.1 New file `tests/test_ad1337_render_seam.py` (M1, written first)

```python
"""AD-1337 S3 (#1560): the render seam and the routes. The text the agentic loop hands a model, and every tool result
a route takes past the tool executor, is masked; SECRET_MASKED (seam "render") records which labels, never a value.

Contract: prompts/ad-1337-s3-render-seam.md. The owner (SecretMasker) is S1's; the producer seam is S2's.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import probos
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    ToolCallResult,
    capture_tool_result,
    result_delivery,
    tool_registration_to_llm_definition,
)
from probos.events import EventType
from probos.security import secret_masking
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    SecretMasker,
    mask_route_result,
    secret_forms,
    secret_masker_of,
)
from probos.tools.executor import ToolExecutor, tool_record_identity
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from tests import test_ad1240_tool_result_delivery as delivery_tests
from tests import test_ad745_episode_anchor as action_tests
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures.ad1343_seam_registry import DIRECT_TOOL_INVOKES
from tests.offered_tools import offer
from tests.test_ad1147_parallel_tools import _RecordingEmit
from tests.test_ad1240_tool_result_delivery import (
    _FakeLLM,
    _RawTool,
    _ReadbackLLM,
    _done,
    _environment,
    _last_result,
    _started,
    _turn,
)
from tests.test_ad1337_executor_seam import _calls_building_a_tool_executor
from tests.test_ad1337_secret_masking import _masker, _no_builtin_env, _store  # noqa: F401 -- _no_builtin_env is autouse

TOKEN = "tok-S3r8Wm2Qz6Lp4Nx9"
OTHER = "oth-S3c5Hv1Jd7Ty3Bk8"
PLACEHOLDER = "<secret:github>"
_SRC = Path(probos.__file__).resolve().parent
_LOOP = "src/probos/cognitive/swe_harness/agentic_loop.py"
_PRODUCING = frozenset({"ToolCallResult", "from_tool_result", "prepare_result", "capture_tool_result"})


def _real_masker(directory: Path, **values: str) -> SecretMasker:
    """S1's masker over a store holding ``values`` (default: TOKEN named ``github``) and an empty environment."""
    return _masker(_store(directory / "store", values or {"github": TOKEN}))


def _masked(emit: _RecordingEmit) -> list[dict[str, Any]]:
    return [payload for name, payload in emit.events if name == "SECRET_MASKED"]


def _raise_values(_credential_store: Any) -> tuple[tuple[str, str], ...]:
    raise RuntimeError(TOKEN)


def _loop(llm: Any, executor: Any, masker: SecretMasker | None, emit: _RecordingEmit, **kwargs: Any) -> AgenticLoop:
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, event_emit_fn=emit,
        structured_tool_messages=True, **kwargs,
    )
    loop.secret_masker = masker
    return loop


def _registered(tool: Any) -> tuple[ToolRegistry, dict[str, Any]]:
    registry = ToolRegistry()
    registration = registry.register(tool, default_permissions={"ensign": "read"})
    return registry, tool_registration_to_llm_definition(registration)


async def _run(loop: AgenticLoop, tools: list[dict[str, Any]], context: dict[str, Any] | None = None) -> Any:
    return await loop.run(
        system_prompt="fixture", user_message="fixture task", tools=tools,
        context=context if context is not None else {"agent_id": "fixture-agent"},
    )


def _requests_text(llm: Any) -> str:
    return json.dumps([asdict(request) for request in llm.requests], default=str)


def _callee(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


class _RaisingTool(_RawTool):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"bad credential {TOKEN}")


class _Secretive:
    """An output the producer seam leaves as it is: only its str() holds the value."""

    def __repr__(self) -> str:
        return f"<Secretive holding {TOKEN}>"


class _StrictProfileExecutor:
    """BF-965's strict-profile executor shape (test_bf965_unoffered_tool_refusal.py:111): its result carries a
    trusted effect correlation, and its output is a custom object that only the render seam masks."""

    protected_effects_enabled = True

    async def match_operation_handle(self, **kwargs: Any) -> None:
        return None

    async def invoke(self, **kwargs: Any) -> ToolResult:
        return ToolResult(output=_Secretive(), metadata={
            "operation_id": "op-s3", "attempt_id": "at-s3", "effect_outcome": "result", "reason_code": "tool_completed",
        })


class _SelfQueryProbe:
    """A self_query stand-in that admits its presentation as the real tool does (self_query_tool.py:73)."""

    tool_id = "self_query"
    name = "self_query"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "AD-1337 S3 self_query probe"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {}

    def __init__(self) -> None:
        self.admitted: list[Any] = []

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        output = {"agent_id": "fixture-agent", "rendered": f"note {TOKEN}"}
        self.admitted.append((context or {})["_tool_result_presentation"].render_complete(output))
        return ToolResult(output=output)


class _EscapingLoop(AgenticLoop):
    """AD-1147's escape (test_ad1147_parallel_tools.py:468): a failure outside _execute_one_tool's conversion."""

    async def _execute_one_tool(self, use: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"escaped {TOKEN}")


class _TokenBrowser(action_tests._FakeBT):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output={"text": f"page {TOKEN}"})


class _RouteCalls(seam_census.Visitor):
    """AD-1343's census visitor, recording the registry and MCP calls that hand back tool output."""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("check_and_invoke", "call_tool"):
            self.calls.append(seam_census.Call(
                self._rel, ".".join(self._scope) or "<module>", func.attr, ast.unparse(func.value), "",
            ))
        self.generic_visit(node)


# -- N1 to N4: the slot and RenderMask ------------------------------------------------------------------------------


def test_the_loop_takes_its_masker_through_a_type_checked_slot_not_a_keyword(tmp_path: Path) -> None:
    assert isinstance(AgenticLoop.secret_masker, SecretMaskerSlot)
    assert "secret_masker" not in inspect.signature(AgenticLoop).parameters  # the AD-1152 golden pins the keywords
    loop = AgenticLoop(llm_client=_FakeLLM([]), tool_executor=ToolExecutor(registry=ToolRegistry()))
    assert loop.secret_masker is None
    masker = _real_masker(tmp_path)
    loop.secret_masker = masker
    assert loop.secret_masker is masker
    for bad in (MagicMock(), object(), "masker"):
        with pytest.raises(TypeError):
            loop.secret_masker = bad
    loop.secret_masker = None
    assert loop.secret_masker is None


async def test_render_mask_returns_its_argument_without_a_masker_or_a_match(tmp_path: Path) -> None:
    captured = capture_tool_result("call-1", ToolResult(output=f"plain {TOKEN}"), 1.0, max_chars=0)
    result = ToolCallResult(id="call-1", output=f"plain {TOKEN}")
    emit = _RecordingEmit()
    for render in (RenderMask(None), RenderMask(_real_masker(tmp_path, github=OTHER))):
        assert render.capture(captured) is captured
        assert await render.final(result, emit_fn=emit, tool_name="t", strict=False, correlation=None) is result
    assert emit.events == []


async def test_both_passes_share_one_event_that_names_labels_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    emit = _RecordingEmit()
    render = RenderMask(_real_masker(tmp_path, github=TOKEN, other=OTHER))

    captured = render.capture(capture_tool_result("call-1", ToolResult(output=f"a {TOKEN}"), 1.0, max_chars=0))
    result = await render.final(
        ToolCallResult(id="call-1", output=f"b {OTHER}"),
        emit_fn=emit, tool_name="fixture_result", strict=False, correlation=None,
    )

    assert captured.text == f"a {PLACEHOLDER}"
    assert result.output == "b <secret:other>" and type(result) is ToolCallResult
    assert emit.events == [("SECRET_MASKED", {
        "seam": "render", "tool_id": tool_record_identity("fixture_result"), "invocation_id": "call-1",
        "operation_id": None, "attempt_id": None, "names": ["github", "other"], "names_omitted": 0, "failed": False,
    })]
    assert "AD-1337: render seam masked names=['github', 'other']" in caplog.text
    shown = caplog.text + json.dumps(emit.events)
    assert [form for form in secret_forms(TOKEN) | secret_forms(OTHER) if form in shown] == []

    # The caps (literal on purpose): 17 labels give the first 16 and a count of 1; a call id of 128 characters is
    # kept and one of 129 is left out.
    many = {f"k{index:02d}": f"val-S3m{index:02d}Qz6Lp4Nx9" for index in range(17)}
    crowded = _real_masker(tmp_path / "many", **many)
    capped = _RecordingEmit()
    for call_id in ("i" * 128, "i" * 129):
        await RenderMask(crowded).final(
            ToolCallResult(id=call_id, output=" ".join(many.values())),
            emit_fn=capped, tool_name="fixture_result", strict=False, correlation=None,
        )
    assert [(p["invocation_id"], p["names"], p["names_omitted"]) for p in _masked(capped)] == [
        ("i" * 128, sorted(many)[:16], 1), (None, sorted(many)[:16], 1),
    ]


async def test_a_failed_pass_withholds_and_a_strict_event_names_no_tool_or_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)
    render = RenderMask(masker)

    captured = render.capture(capture_tool_result("call-1", ToolResult(output={"k": TOKEN}), 1.0, max_chars=0))
    assert type(captured.producer) is ToolResult and captured.producer.error == MASKING_FAILED_TEXT
    assert captured.text == MASKING_FAILED_TEXT

    pairs: list[tuple[Any, dict[str, Any]]] = []

    async def _async_emit(event: Any, payload: dict[str, Any]) -> None:
        pairs.append((event, payload))

    result = await render.final(
        ToolCallResult(id="call-1", output=f"x {TOKEN}"), emit_fn=_async_emit, tool_name="t", strict=True,
        correlation=SimpleNamespace(operation_id="op-1", attempt_id="at-1"),
    )
    assert (result.output, result.is_error) == (MASKING_FAILED_TEXT, True)
    assert pairs == [(EventType.SECRET_MASKED, {
        "seam": "render", "tool_id": None, "invocation_id": None, "operation_id": "op-1", "attempt_id": "at-1",
        "names": [], "names_omitted": 0, "failed": True,
    })]

    def _broken(*_args: Any) -> None:
        raise RuntimeError("bus down")

    again = await RenderMask(masker).final(
        ToolCallResult(id="c", output=f"y {TOKEN}"), emit_fn=_broken, tool_name="t", strict=False, correlation=None,
    )
    assert again.output == MASKING_FAILED_TEXT
    assert "SECRET_MASKED could not be emitted at the render seam" in caplog.text and TOKEN not in caplog.text


# -- N5 to N8: what the loop hands the model ------------------------------------------------------------------------


async def test_an_exception_message_is_masked_before_the_model_sees_it(tmp_path: Path) -> None:
    registry, definition = _registered(_RaisingTool(ToolResult()))
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])

    result = await _run(_loop(llm, ToolExecutor(registry=registry), _real_masker(tmp_path), emit), [definition])

    shown = _last_result(llm.requests[1])
    assert shown == f"Tool fixture_result failed: bad credential {PLACEHOLDER}"
    assert result.tool_results[0].output == shown and result.tool_results[0].is_error
    assert TOKEN not in _requests_text(llm)
    assert _masked(emit) == [{
        "seam": "render", "tool_id": tool_record_identity("fixture_result"), "invocation_id": "fixture-call",
        "operation_id": None, "attempt_id": None, "names": ["github"], "names_omitted": 0, "failed": False,
    }]
    assert TOKEN not in json.dumps(emit.events, default=repr)


async def test_the_parallel_batch_conversion_is_masked(tmp_path: Path) -> None:
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn("read_page"), _done()])
    loop = _EscapingLoop(
        llm_client=llm, tool_executor=ToolExecutor(registry=ToolRegistry()), max_iterations=3, event_emit_fn=emit,
        structured_tool_messages=True, parallel_tool_calls_enabled=True,
    )
    loop.secret_masker = _real_masker(tmp_path)

    await _run(loop, offer("read_page"))

    assert _last_result(llm.requests[1]) == f"Tool read_page failed: escaped {PLACEHOLDER}"
    [payload] = _masked(emit)
    assert (payload["seam"], payload["invocation_id"], payload["names"]) == ("render", "fixture-call", ["github"])


async def test_a_custom_object_output_is_masked_at_the_render_seam_only(tmp_path: Path) -> None:
    masker = _real_masker(tmp_path)
    raw = ToolResult(output=_Secretive())
    registry, definition = _registered(_RawTool(raw))
    executor = ToolExecutor(registry=registry, secret_masker=masker)
    seen: list[ToolResult] = []
    executor.add_post_hook(lambda _ctx, result: seen.append(result))
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])

    await _run(_loop(llm, executor, masker, emit), [definition])

    assert len(seen) == 1 and seen[0] is raw  # the producer seam leaves a custom object as it is
    assert _last_result(llm.requests[1]) == f"<Secretive holding {PLACEHOLDER}>"
    assert TOKEN not in _requests_text(llm)
    assert [(payload["seam"], payload["names"]) for payload in _masked(emit)] == [("render", ["github"])]

    # The strict profile: the loop's own call hands final its strict flag and the call's effect correlation.
    strict_emit = _RecordingEmit()
    strict_llm = _FakeLLM([_turn(), _done()])
    await _run(_loop(strict_llm, _StrictProfileExecutor(), masker, strict_emit), [definition])
    assert _last_result(strict_llm.requests[1]) == f"<Secretive holding {PLACEHOLDER}>"
    assert _masked(strict_emit) == [{
        "seam": "render", "tool_id": None, "invocation_id": None, "operation_id": "op-s3", "attempt_id": "at-s3",
        "names": ["github"], "names_omitted": 0, "failed": False,
    }]


@pytest.mark.parametrize("producer", [True, False])
async def test_self_query_fails_closed_after_a_producer_hit_and_is_masked_when_only_the_loop_masks(
    tmp_path: Path, producer: bool,
) -> None:
    masker = _real_masker(tmp_path)
    tool = _SelfQueryProbe()
    registry, definition = _registered(tool)
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn("self_query", domains=["wellness"]), _done()])
    executor = ToolExecutor(registry=registry, secret_masker=masker if producer else None)

    result = await _run(_loop(llm, executor, masker, emit), [definition])

    assert tool.admitted and tool.admitted[0] is not None  # premise: the loop retained the presentation
    shown = _last_result(llm.requests[1])
    assert TOKEN not in _requests_text(llm)
    if producer:
        # The producer seam copied the output, so the loop's identity check fails: fail closed (consult Q4).
        assert shown == "self_query: presentation check failed." and result.tool_results[0].is_error
        assert _masked(emit) == []
    else:
        assert shown == str({"agent_id": "fixture-agent", "rendered": f"note {PLACEHOLDER}"})
        assert [payload["seam"] for payload in _masked(emit)] == ["render"]


# -- N9 to N11: AD-1240's offloaded copy, and byte identity ---------------------------------------------------------


@pytest.mark.parametrize("known", [True, False])
async def test_an_offloaded_output_is_stored_framed_and_read_back_masked(tmp_path: Path, known: bool) -> None:
    runtime, executor, context = _environment(tmp_path)
    text = "HEAD " + TOKEN + "\n" + "y" * 20000
    canonical = text.replace(TOKEN, PLACEHOLDER) if known else text
    registration = runtime.tool_registry.register(_RawTool(ToolResult(output=text)))
    emit = _RecordingEmit()
    llm = _ReadbackLLM(_turn(), canonical)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = _real_masker(tmp_path / "masker", github=TOKEN if known else OTHER)

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="recover exactly",
            tools=[tool_registration_to_llm_definition(registration)], context=context,
        )
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        [payload_file] = list(runtime.workspace_results.root.rglob("payload.jsonl"))
        stored = payload_file.read_bytes()

    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "workspace"
    assert delivery.reference.sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if known:
        assert PLACEHOLDER in llm.readbacks[0] and PLACEHOLDER.encode("utf-8") in stored
        assert result.tool_results[0].output == canonical
        shown = _last_result(llm.requests[1]) + "".join(llm.readbacks) + stored.decode("utf-8") + _requests_text(llm)
        assert [form for form in secret_forms(TOKEN) if form in shown] == []
        [payload] = _masked(emit)
        assert (payload["seam"], payload["invocation_id"], payload["names"]) == ("render", "fixture-call", ["github"])
    else:
        assert result.tool_results[0].output is text
        assert _masked(emit) == []


async def test_a_large_source_file_holding_a_secret_is_framed_and_recovered_masked(tmp_path: Path) -> None:
    runtime, _, context = _environment(tmp_path)
    executor = ToolExecutor(registry=runtime.tool_registry, secret_masker=_real_masker(tmp_path / "masker"))
    path = tmp_path / "secret_source.txt"
    text = f"0000 token {TOKEN}\n" + "".join(f"{index:04d} " + "x" * 100 + "\n" for index in range(1, 200))
    path.write_bytes(text.encode("utf-8"))
    emit = _RecordingEmit()
    llm = _ReadbackLLM(_turn("read_file", path=str(path)), text.replace(TOKEN, PLACEHOLDER), source=True)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = executor.secret_masker

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="read source", tools=offer("read_file"), context=context,
        )
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2

    delivery = result_delivery(result.tool_results[0])
    assert delivery.status == "source"
    assert delivery.reference.raw_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()  # the file, not the capture
    assert PLACEHOLDER in llm.readbacks[0]
    shown = _requests_text(llm) + "".join(llm.readbacks)
    assert [form for form in secret_forms(TOKEN) if form in shown] == []
    assert _masked(emit) == []  # the producer seam masked it; the render seam found nothing left
    assert not runtime.workspace_results.root.exists()  # a source is never copied


async def test_a_masker_that_matches_nothing_keeps_the_ad1240_pre_edit_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    masker = _real_masker(tmp_path / "masker")

    class _MaskingLoop(AgenticLoop):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.secret_masker = masker

    monkeypatch.setattr(delivery_tests, "AgenticLoop", _MaskingLoop)
    actual = await delivery_tests._capture_baseline(tmp_path / "owned", monkeypatch)
    assert actual == json.loads(delivery_tests._GOLDEN.read_text(encoding="utf-8"))


# -- N12: the DM route ------------------------------------------------------------------------------------------------


async def test_the_dm_tier1_browser_result_is_masked_before_its_record_and_episode(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    runtime = action_tests._runtime()
    runtime.secret_masker = masker
    runtime.browser_tool = _TokenBrowser()
    await action_tests._pipeline(runtime, '[ACTION: {"verb":"extract_text","args":{}}]').step_4e_action_dispatch()

    outcome = runtime.episodic_memory.stored[-1].outcomes[0]
    assert outcome["tier_classified"] == 1  # premise: the inline tier-1 path ran
    assert outcome["result"] == {"text": f"page {PLACEHOLDER}"}
    assert "AD-1337: route=dm_tier1_browser masked names=['github']" in caplog.text and TOKEN not in caplog.text

    odd = action_tests._runtime()  # its browser answers with an object that is not a ToolResult
    odd.secret_masker = masker
    await action_tests._pipeline(odd, '[ACTION: {"verb":"extract_text","args":{}}]').step_4e_action_dispatch()
    assert odd.episodic_memory.stored[-1].outcomes[0]["result"] is None


# -- N13 to N16: the censuses and the route helpers ----------------------------------------------------------------


def _loop_constructions() -> dict[tuple[str, int], tuple[str, str, list[str]]]:
    found: dict[tuple[str, int], tuple[str, str, list[str]]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Assign) and _callee(node.value) == "AgenticLoop"):
                    continue
                if (rel, node.lineno) in found:
                    continue
                [target] = [ast.unparse(t) for t in node.targets]
                executor = next(ast.unparse(k.value) for k in node.value.keywords if k.arg == "tool_executor")
                maskers = [
                    ast.unparse(a.value) for a in ast.walk(fn)
                    if isinstance(a, ast.Assign) and [ast.unparse(t) for t in a.targets] == [f"{target}.secret_masker"]
                ]
                found[(rel, node.lineno)] = (target, executor, maskers)
    return found


def test_every_agentic_loop_masks_with_its_own_executors_masker() -> None:
    found = _loop_constructions()
    calls = sum(
        1 for path in _SRC.rglob("*.py") for node in ast.walk(ast.parse(path.read_bytes()))
        if _callee(node) == "AgenticLoop" and isinstance(node.func, ast.Name)
    )
    assert calls == len(found) == 2
    assert sorted((rel, *row) for (rel, _), row in found.items()) == [
        ("cognitive/agentic_dispatch.py", "loop", "executor", ["secret_masker_of(executor)"]),
        ("cognitive/swe_harness/native_builder.py", "loop", "self._executor", ["secret_masker_of(self._executor)"]),
    ]
    run = seam_census.function("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor._run_reserved")
    built = [
        node.value for node in ast.walk(run)
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["executor"]
        and isinstance(node.value, ast.Call)
    ]
    assert [ast.unparse(call.func) for call in built] == ["DispatchToolExecutor"]
    # S2's census checks that construction's masker; this ties the dispatch loop to it.
    assert ("cognitive/agentic_dispatch.py", built[0].lineno) in {
        (rel, call.lineno) for rel, call in _calls_building_a_tool_executor()
    }
    startup = seam_census.function("src/probos/startup/finalize.py", "finalize_startup")
    [handed] = [node for node in ast.walk(startup) if _callee(node) == "_wire_native_swe_harness"]
    assert [ast.unparse(k.value) for k in handed.keywords if k.arg == "tool_executor"] == ["tool_executor"]


def test_every_result_the_loop_hands_the_model_passes_the_render_seam() -> None:
    module = ast.parse((seam_census.ROOT / _LOOP).read_bytes())
    assert sum(_callee(node) in _PRODUCING for node in ast.walk(module)) == 8
    one = seam_census.function(_LOOP, "AgenticLoop._execute_one_tool")
    producing = [node for node in ast.walk(one) if _callee(node) in _PRODUCING]
    [refusal] = [
        node for node in producing
        if any(k.arg == "output" and ast.unparse(k.value) == "UNOFFERED_TOOL_REFUSAL" for k in node.keywords)
    ]
    guarded = [node for node in producing if node is not refusal]
    [render] = [node for node in ast.walk(one) if _callee(node) == "RenderMask"]
    [capture] = [node for node in ast.walk(one) if _callee(node) == "capture"]
    [final] = [node for node in ast.walk(one) if _callee(node) == "final"]
    assert len(guarded) == 6
    assert [ast.unparse(arg) for arg in render.args] == ["self.secret_masker"]
    assert render.lineno < min(node.lineno for node in guarded)
    assert max(node.lineno for node in guarded) < final.lineno and ast.unparse(final.func.value) == "render"
    assert _callee(capture.args[0]) == "capture_tool_result"
    assert capture.lineno < next(node.lineno for node in guarded if _callee(node) == "prepare_result")
    attach = seam_census.first_line(
        one, lambda node: isinstance(node, ast.Call) and ast.unparse(node.func) == "object.__setattr__",
    )
    assert final.lineno < attach  # before the effect correlation, which replace() would drop
    uses = seam_census.function(_LOOP, "AgenticLoop._execute_tool_uses")
    built = [node for node in ast.walk(uses) if _callee(node) == "ToolCallResult"]
    wrapped = [
        node.args[0] for node in ast.walk(uses)
        if _callee(node) == "final" and ast.unparse(node.func.value) == "RenderMask(self.secret_masker)"
    ]
    assert len(built) == len(wrapped) == 1 and built[0] is wrapped[0]


ROUTES: dict[tuple[str, str, str, str], str] = {
    ("src/probos/tools/executor.py", "ToolExecutor._invoke_once", "check_and_invoke", "self._registry"):
        "the executor itself: the producer seam masks what it returns",
    ("src/probos/cognitive/crew_verifier.py", "_SessionProjectedToolRegistry.check_and_invoke", "check_and_invoke",
     "self._source_registry"): "a registry subclass delegating; its caller is a ToolExecutor",
    ("src/probos/cognitive/crew_verifier.py", "_SessionProjectedToolRegistry.check_and_invoke", "check_and_invoke",
     "super()"): "a registry subclass delegating; its caller is a ToolExecutor",
    ("src/probos/agent_work_runner.py", "AgentWorkRunner.claim", "check_and_invoke", "self._tools"):
        "the claim reads only whether result.error is None; no text reaches a model or a record",
    ("src/probos/tools/context.py", "ToolContext.invoke", "check_and_invoke", "registry"):
        "no caller in src (asserted below)",
    ("src/probos/federation/mcp_server.py", "FederationMCPServer._handle_tools_call", "call_tool", "registry"):
        "internal app tools only (include_external=False, asserted below), all from mcp_apps/game_app.py",
    ("src/probos/mcp_apps/registry.py", "MCPAppRegistry.register_external_app._external_handler", "call_tool",
     "mcp_client"): "unreached: MCPAppRegistry.call_tool's one caller passes include_external=False",
    ("src/probos/integrations/mcp_bridge/bridge.py", "MCPBridge.invoke", "call_tool", "client"):
        "the bridge's transport; its callers are the bridge rows below",
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "invoke", "tool"):
        "the tool sink; its callers are the check_and_invoke rows above",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "invoke", "browser_tool"):
        "masked by mask_route_result before mark_executed and the episode (asserted below)",
    ("src/probos/routers/agent_actions.py", "ack_action", "invoke", "browser_tool"):
        "the Captain's ACK: the dispatcher record and the HXI answer only; nothing reads it after",
    ("src/probos/cognitive/agentic_dispatch.py", "_McpTool.invoke", "invoke", "self._bridge"):
        "a registered tool's body: the producer seam masks its ToolResult",
    ("src/probos/integrations/mcp_bridge/adapter.py", "MCPToolAdapter.invoke", "invoke", "self._bridge"):
        "never constructed in src (asserted below)",
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect (AD-1337 S5)",
}


def test_every_route_past_the_tool_executor_is_masked_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str, str]] = set()
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        visitor = _RouteCalls(path.relative_to(seam_census.ROOT).as_posix())
        visitor.visit(ast.parse(path.read_bytes()))
        found |= {(c.file, c.function, c.callee, c.receiver) for c in visitor.calls}
    found |= {
        (c.file, c.function, c.callee, c.receiver) for c in seam_census.census()
        if c.callee == "invoke" and c.receiver.split(".")[-1].endswith(("tool", "bridge"))
    }
    assert found == set(ROUTES), sorted(found ^ set(ROUTES))
    assert {(k[0], k[1], k[3]) for k in ROUTES if k[2] == "invoke" and k[3].endswith("tool")} == set(DIRECT_TOOL_INVOKES)
    assert not [
        c for c in seam_census.census() if c.callee == "invoke" and c.receiver.split(".")[-1] == "tool_context"
    ]
    assert not [n for p in _SRC.rglob("*.py") for n in ast.walk(ast.parse(p.read_bytes())) if _callee(n) == "MCPToolAdapter"]
    server = seam_census.function("src/probos/federation/mcp_server.py", "FederationMCPServer._handle_tools_call")
    [app_call] = [node for node in ast.walk(server) if _callee(node) == "call_tool"]
    assert [ast.unparse(k.value) for k in app_call.keywords if k.arg == "include_external"] == ["False"]
    step = seam_census.function("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch")
    assert (
        seam_census.first_line(step, seam_census.calls("invoke"))
        < seam_census.first_line(step, seam_census.calls("mask_route_result"))
        < seam_census.first_line(step, seam_census.calls("mark_executed"))
    )


def test_the_route_helpers_mask_a_tool_result_and_withhold_anything_else(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    assert secret_masker_of(SimpleNamespace(secret_masker=masker)) is masker
    assert secret_masker_of(SimpleNamespace()) is None and secret_masker_of(MagicMock()) is None
    plain = ToolResult(output="nothing here")
    assert mask_route_result(None, plain, route="r") is plain
    assert mask_route_result(masker, plain, route="r") is plain
    odd = SimpleNamespace(output=TOKEN)
    assert mask_route_result(None, odd, route="r") is odd
    withheld = mask_route_result(masker, odd, route="r")
    assert type(withheld) is ToolResult and (withheld.output, withheld.error) == (None, MASKING_FAILED_TEXT)
    assert mask_route_result(masker, ToolResult(output={"text": TOKEN}), route="r").output == {"text": PLACEHOLDER}
    assert "AD-1337: route=r masked names=['github']" in caplog.text and TOKEN not in caplog.text
```

### 7.2 New file `src/probos/cognitive/swe_harness/render_masking.py` (M1)

```python
"""AD-1337 S3 (#1560): the render seam. The text the agentic loop hands a model is masked before the model sees it.

The producer seam (AD-1337 S2, ``ToolExecutor._invoke_once``) masks every ``ToolResult`` a registry returns. Some
text reaches the model without passing it, and this seam masks it:

- a raised exception's text (``Tool X failed: ...``), in the loop's own conversion and in the parallel batch's;
- the ``str()`` of an output the producer seam leaves as it is (a custom object, ``bytes``, a container past its walk
  bounds), and BF-728's re-render of a container from the raw value;
- AD-1240's captured text, which becomes the offloaded payload, the recovery slices read from it and the result the
  run records.

``RenderMask`` holds one tool result's two passes, ``capture`` before ``prepare_result`` and ``final`` on the result
the loop returns, and emits at most one ``SECRET_MASKED`` (``seam: "render"``) for both. After the producer seam a hit
here means text the producer seam did not see, so it is also logged at WARNING, with labels only.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from probos.cognitive.swe_harness.tool_call import CapturedConversion, ToolCallResult, capture_tool_result
from probos.tools.executor import SECRET_MASKED_MAX_NAMES, tool_record_identity
from probos.tools.protocol import ToolResult

if TYPE_CHECKING:
    from probos.execution.effect_types import EffectCorrelation
    from probos.security.secret_masking import SecretMasker

logger = logging.getLogger(__name__)

#: The longest tool-call id a SECRET_MASKED payload carries. The id is the model's (its JSON is unchecked), so a
#: longer one is left out rather than stored.
CALL_ID_MAX_CHARS = 128


class SecretMaskerSlot:
    """``AgenticLoop.secret_masker`` as a data descriptor: a ``SecretMasker``, or None (the default: nothing is masked).

    Anything else raises ``TypeError``, so a wiring bug cannot pass silently. It is not a constructor keyword because
    the AD-1152 golden pins the loop's constructor keywords; both constructions assign it right after construction, as
    AD-1240 assigns ``workspace_results``.
    """

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = f"_{name}"

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return instance.__dict__.get(self._name)

    def __set__(self, instance: object, value: object) -> None:
        from probos.security.secret_masking import SecretMasker

        if value is not None and not isinstance(value, SecretMasker):
            raise TypeError("secret_masker must be a SecretMasker or None")
        instance.__dict__[self._name] = value


class RenderMask:
    """One tool result's render-seam passes and the one ``SECRET_MASKED`` they share.

    Without a masker both passes return their argument itself. With one and no match, the same: ``mask_text`` returns
    the same string, so the loop's text, the offloaded payload and its sha256 are byte-identical to a run without one.
    """

    def __init__(self, masker: SecretMasker | None) -> None:
        self._masker = masker
        self._names: set[str] = set()
        self._failed = False

    def capture(self, captured: CapturedConversion) -> CapturedConversion:
        """Mask AD-1240's captured text before ``prepare_result`` stores, frames or returns any of it.

        A failed pass replaces the capture with a withheld result's (``MASKING_FAILED_TEXT`` as its error), so nothing
        of the original text or its raw value is delivered, offloaded or re-rendered.
        """
        if self._masker is None or captured.text is None:
            return captured
        outcome = self._masker.mask_text(captured.text)
        if outcome.failed:
            from probos.security.secret_masking import MASKING_FAILED_TEXT

            self._failed = True
            return capture_tool_result(
                captured.request_id, ToolResult(error=MASKING_FAILED_TEXT), captured.duration_ms,
                max_chars=captured.max_chars,
            )
        if outcome.text is captured.text:
            return captured
        self._names |= outcome.names
        return replace(captured, text=outcome.text)

    async def final(
        self,
        result: ToolCallResult,
        *,
        emit_fn: Callable[..., Any] | None,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> ToolCallResult:
        """Mask the text this call hands the model, then emit ``SECRET_MASKED`` once if either pass masked or failed.

        A failed pass withholds: the output becomes ``MASKING_FAILED_TEXT`` and the result an error.
        """
        if self._masker is not None and isinstance(result.output, str):
            outcome = self._masker.mask_text(result.output)
            if outcome.failed:
                from probos.security.secret_masking import MASKING_FAILED_TEXT

                self._failed = True
                result = replace(result, output=MASKING_FAILED_TEXT, is_error=True)
            elif outcome.text is not result.output:
                self._names |= outcome.names
                result = replace(result, output=outcome.text)
        if self._names or self._failed:
            await self._emit(emit_fn, result, tool_name=tool_name, strict=strict, correlation=correlation)
        return result

    async def _emit(
        self,
        emit_fn: Callable[..., Any] | None,
        result: ToolCallResult,
        *,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> None:
        from probos.events import EventType

        names = sorted(self._names)
        call_id = result.id if type(result.id) is str and len(result.id) <= CALL_ID_MAX_CHARS else None
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else call_id,
            "operation_id": correlation.operation_id if correlation is not None else None,
            "attempt_id": correlation.attempt_id if correlation is not None else None,
            "names": names[:SECRET_MASKED_MAX_NAMES],
            "names_omitted": max(0, len(names) - SECRET_MASKED_MAX_NAMES),
            "failed": self._failed,
        }
        logger.warning(
            "AD-1337: render seam masked names=%s tool=%s failed=%s",
            payload["names"], payload["tool_id"], self._failed,
        )
        if emit_fn is None:
            return
        try:
            emitted = emit_fn(EventType.SECRET_MASKED, payload)
            if inspect.isawaitable(emitted):
                await emitted
        except Exception:
            logger.warning(
                "AD-1337: SECRET_MASKED could not be emitted at the render seam for tool=%s; the text stays masked",
                payload["tool_id"],
            )
```

### 7.3 `src/probos/cognitive/swe_harness/agentic_loop.py` (M1)

**X1.** SEARCH (`:44-46`):
```
    safe_delivery_error,
    seal_workspace_results,
)
```
REPLACE:
```
    safe_delivery_error,
    seal_workspace_results,
)
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
```

**X2.** SEARCH (`:1366-1368`):
```
    workspace_results = WorkspaceResultsSlot()

    def __init__(
```
REPLACE:
```
    workspace_results = WorkspaceResultsSlot()
    # AD-1337 S3 (#1560): the render seam's masker, the one this loop's executor masks with. A data descriptor like
    # ``workspace_results`` and for the same reason: assigned after construction, so the constructor keywords the
    # AD-1152 golden pins are unchanged. None (the default) masks nothing.
    secret_masker = SecretMaskerSlot()

    def __init__(
```

**X3.** SEARCH (`:2575-2579`):
```
                    by_index[index] = ToolCallResult(
                        id=call.id,
                        output=f"Tool {call.name} failed: {outcome}",
                        is_error=True,
                    )
```
REPLACE:
```
                    # AD-1337 S3 (#1560): this text never passed a ToolResult, so the render seam masks it here.
                    by_index[index] = await RenderMask(self.secret_masker).final(
                        ToolCallResult(
                            id=call.id,
                            output=f"Tool {call.name} failed: {outcome}",
                            is_error=True,
                        ),
                        emit_fn=self._emit, tool_name=call.name, strict=False, correlation=None,
                    )
```

**X4.** SEARCH (`:2664-2666`):
```
        strict = getattr(self._executor, "protected_effects_enabled", False)
        privacy = StrictEffectPrivacyProjector()
        read_context = None
```
REPLACE:
```
        strict = getattr(self._executor, "protected_effects_enabled", False)
        privacy = StrictEffectPrivacyProjector()
        # AD-1337 S3 (#1560): this call's render-seam passes; inert without a masker.
        render = RenderMask(self.secret_masker)
        read_context = None
```

**X5.** SEARCH (`:2960-2967`):
```
            captured = capture_tool_result(
                use.tool_call.id, delivery_source, duration_ms,
                max_chars=delivery_run.settings.max_chars,
            )
            tcr = await prepare_result(
                captured, DeliveryContext(delivery_run, delivery_remaining, use.tool_call.name),
            )
        if trace_correlation is not None:
```
REPLACE:
```
            # AD-1337 S3 (#1560): masked before prepare_result offloads, frames or returns any of it.
            captured = render.capture(capture_tool_result(
                use.tool_call.id, delivery_source, duration_ms,
                max_chars=delivery_run.settings.max_chars,
            ))
            tcr = await prepare_result(
                captured, DeliveryContext(delivery_run, delivery_remaining, use.tool_call.name),
            )
        # AD-1337 S3 (#1560): the render seam's final mask on the result this call hands the model, before the effect
        # correlation is attached below (replace() would drop it) and before the message bound truncates the text, so
        # whole forms still match. At most one SECRET_MASKED for this call, with the capture pass above.
        tcr = await render.final(
            tcr, emit_fn=self._emit, tool_name=use.tool_call.name, strict=strict, correlation=trace_correlation,
        )
        if trace_correlation is not None:
```

### 7.4 `src/probos/cognitive/agentic_dispatch.py` (M1)

**X6.** SEARCH (S2's `_runtime_secret_masker` body, `:1541-1544`):
```
    from probos.security.secret_masking import SecretMasker

    masker = getattr(runtime, "secret_masker", None)
    return masker if isinstance(masker, SecretMasker) else None
```
REPLACE:
```
    from probos.security.secret_masking import secret_masker_of

    return secret_masker_of(runtime)  # AD-1337 S3: the one filter every seam that takes a masker shares
```

**X7.** SEARCH (`:4184-4186`):
```
            **_loop_kwargs,
        )
        # AD-1240: the owner is assigned after construction (never as a constructor
```
REPLACE:
```
            **_loop_kwargs,
        )
        # AD-1337 S3 (#1560): the render seam masks with this run's executor's masker, assigned after construction for
        # the reason AD-1240 gives below (the AD-1152 golden pins the constructor keywords).
        from probos.security.secret_masking import secret_masker_of

        loop.secret_masker = secret_masker_of(executor)
        # AD-1240: the owner is assigned after construction (never as a constructor
```

### 7.5 `src/probos/cognitive/swe_harness/native_builder.py` (M1)

**X8.** SEARCH (`:160-163`):
```
        # AD-1240: assigned after construction, never as a keyword. The run context
        # carries the SAME authorized registry view this harness's executor serves,
        # only when a real owner was injected.
        loop.workspace_results = resolve_workspace_results(self._runtime)
```
REPLACE:
```
        # AD-1337 S3 (#1560): the render seam masks with this harness's executor's masker (the runtime's, from
        # finalize), assigned after construction like the AD-1240 owner below; a test double's executor gives None.
        from probos.security.secret_masking import secret_masker_of

        loop.secret_masker = secret_masker_of(self._executor)
        # AD-1240: assigned after construction, never as a keyword. The run context
        # carries the SAME authorized registry view this harness's executor serves,
        # only when a real owner was injected.
        loop.workspace_results = resolve_workspace_results(self._runtime)
```

### 7.6 `src/probos/cognitive/dm/reply_pipeline.py` (M1)

**X9.** SEARCH (`:1189-1194`):
```
                    result = await browser_tool.invoke(
                        params, context={"agent_id": self.ctx.agent_id},
                    )
                    dispatcher.mark_executed(
                        action_id, result=getattr(result, "output", None),
                    )
```
REPLACE:
```
                    result = await browser_tool.invoke(
                        params, context={"agent_id": self.ctx.agent_id},
                    )
                    # AD-1337 S3 (#1560): this inline call skips the tool executor, and its output becomes the
                    # action's record and the episode below, which later prompts recall, so it is masked here.
                    from probos.security.secret_masking import mask_route_result, secret_masker_of

                    result = mask_route_result(
                        secret_masker_of(self.ctx.runtime), result, route="dm_tier1_browser",
                    )
                    dispatcher.mark_executed(
                        action_id, result=getattr(result, "output", None),
                    )
```

### 7.7 `src/probos/security/secret_masking.py` (M1)

**X10.** SEARCH (`:188-189` on `089895c1`; the class line and its docstring, which S1's repair rounds have not touched. The two helpers go above the class. They name `SecretMasker` only when called, so defining them before it is safe):
```
class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```
REPLACE:
```
def secret_masker_of(holder: object) -> SecretMasker | None:
    """AD-1337 S3: ``holder.secret_masker`` when it is a real ``SecretMasker``, else None.

    For a seam that takes its masker from what it is given (a runtime, a tool executor): a holder without one, or a
    test double whose attribute is a ``MagicMock``, masks nothing rather than handing on something that is no masker.
    """
    masker = getattr(holder, "secret_masker", None)
    return masker if isinstance(masker, SecretMasker) else None


def mask_route_result(masker: SecretMasker | None, result: Any, *, route: str) -> Any:
    """AD-1337 S3: mask a tool result a route takes past the tool executor, before the route records it.

    ``result`` itself without a masker. With one, a ``ToolResult`` is masked as the producer seam masks it and a hit is
    logged at WARNING with its labels; anything else is withheld (``ToolResult(error=MASKING_FAILED_TEXT)``), because
    a route that cannot be masked must not pass its text on.
    """
    if masker is None:
        return result
    if not isinstance(result, ToolResult):
        logger.error("AD-1337: route=%s got %s, not a ToolResult; the output is withheld", route, type(result).__name__)
        return ToolResult(error=MASKING_FAILED_TEXT)
    masked = masker.mask_result(result)
    if masked.names:
        logger.warning("AD-1337: route=%s masked names=%s", route, sorted(masked.names))
    return masked.result


class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```

### 7.8 `tests/test_ad1195_durable_producers.py` (M1)

**F1.** SEARCH (S2's row, `:69`):
```
    "SECRET_MASKED": ("tools/executor.py",),
```
REPLACE:
```
    "SECRET_MASKED": ("tools/executor.py", "cognitive/swe_harness/render_masking.py"),
```

### 7.9 `src/probos/cognitive/swe_harness/tool_call.py` (none)

No edit. Listed so no Builder adds one: S3 reads `CapturedConversion`, `capture_tool_result` and `ToolCallResult` as they are.

### 7.10 `PROGRESS.md` (M2)

**TR1.** SEARCH (the whole line `:1`; it occurs once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1337 S3 (2026-11-21), #1560 -- the render seam and the routes: the text the agentic loop hands a model is masked, and every route past the tool executor is masked or has a recorded reason.** New `cognitive/swe_harness/render_masking.py`: `RenderMask` masks AD-1240's captured text before `prepare_result`, so the offloaded payload, its sha256, the frame and every recovery slice hold `<secret:NAME>`. It then masks each `ToolCallResult` the loop returns: a raised exception's text, the parallel batch's conversion and a custom object's `str()`. At most one `SECRET_MASKED` (`seam: "render"`) per tool result, with a WARNING; at most 16 labels (the rest counted), a call id of at most 128 characters, and under the strict profile no tool or call id. `AgenticLoop.secret_masker` is a type-checked slot that both constructions fill from their own executor (`secret_masker_of`); it is not a constructor keyword, so the AD-1152 golden is unchanged. `reply_pipeline`'s inline tier-1 browser call is masked before its action record and episode (`mask_route_result`). Measured by `tests/test_ad1337_render_seam.py` (16 cases, 18 items): an exception, a custom object and the parallel conversion reach the model as `<secret:github>`; an offloaded payload and a large source file are framed and read back masked, and `raw_sha256` stays the file's; a masker that matches nothing leaves AD-1240's pre-edit golden byte-identical; `self_query` fails closed after a producer-seam hit; three censuses pin the loop's mask positions, each loop's masker source and the 14 routes past the executor. Not measured: a live run. Next: S4 (per-run values) and S5 (a decomposed DAG's reflect prompt), batch 2. Contract `prompts/ad-1337-s3-render-seam.md`.
```

### 7.11 `DECISIONS.md` (M2)

**TR2.** SEARCH: the whole line S2's TR2 added (`DECISIONS.md:1674` on the rev1 oracle; S2 rev1 did not change it). It occurs once on `089895c1` and is ASCII:
```
- *Event (S2).* `SECRET_MASKED`, a routed DURABLE member, at most one per call and only when something was masked or withheld: labels (at most 16, the rest counted), `invocation_id` or `operation_id` to join the call's `TOOL_INVOKED` row, no agent id, and no tool id for a strict call. Not an owner row with `parent_event_id` (consult 4bb6d748): the router already records security-control events, and the correlation id joins the AD-1224 chain.
```
REPLACE:
```markdown
- *Event (S2).* `SECRET_MASKED`, a routed DURABLE member, at most one per call and only when something was masked or withheld: labels (at most 16, the rest counted), `invocation_id` or `operation_id` to join the call's `TOOL_INVOKED` row, no agent id, and no tool id for a strict call. Not an owner row with `parent_event_id` (consult 4bb6d748): the router already records security-control events, and the correlation id joins the AD-1224 chain.
- *Render seam (S3).* `RenderMask` (`cognitive/swe_harness/render_masking.py`) masks AD-1240's captured text before `prepare_result`, then the `ToolCallResult` the loop returns. The final pass runs before the effect correlation is attached and before the message bound truncates, so whole forms match. It covers text that never passes a `ToolResult` (a raised exception, the parallel batch's conversion) and text the producer seam leaves alone (a custom object's `str()`, a container past the walk bounds, BF-728's re-render from the raw value). At most one `SECRET_MASKED` (`seam: "render"`) per tool result: `invocation_id` is the model's tool-call id (at most 128 characters), and a strict call carries neither it nor a tool id. A failed pass withholds.
- *Loop wiring (S3).* `AgenticLoop.secret_masker` is a type-checked data descriptor, assigned after construction from the loop's own executor (`secret_masker_of`). It is not the constructor keyword consult 4bb6d748 named: the AD-1152 golden pins the constructor keywords, which is why AD-1240 assigns `workspace_results` the same way, and the class is at its 13-method cap. The render seam therefore masks with the producer seam's masker.
- *Offload (S3).* Every digest comparison stays like with like. `SourceRef.raw_sha256` hashes the file, and recovery re-reads the file through the executor. A workspace payload's sha256 is the masked capture's, and the store re-checks it against the masked payload. `self_query` after a producer-seam hit, and an owned-steps view whose presentation changed, fail closed.
- *Routes (S3).* `reply_pipeline`'s tier-1 browser call is masked before its action record and episode. A census pins every other route past the executor with its reason: the claim (error only), `ToolContext.invoke` (no caller), the Captain's ACK (HXI only), the internal MCP app tools (game state), and the MCP bridge with its callers. A decomposed DAG's results reach the reflect model through neither seam (`decomposer.py:468-498`); that route is AD-1337 S5, in batch 2 with S4.
```

**TR3.** Same file. SEARCH (the whole line; it occurs once):
```
- *Residual.* #1820 items ad-1337 R1 to R3. *Reversal.* Revert the AD-1337 commits.
```
REPLACE:
```
- *Residual.* #1820 items ad-1337 R1 to R6. *Reversal.* Revert the AD-1337 commits.
```

### 7.12 `docs/research/openhands-absorption.md` (M2)

**TR4.** SEARCH (the whole line `:33`):
```
| 3 | **Secret masking in tool output** (`<secret-hidden>`). | BF-890 strips credential-shaped names from child environments (`execution/command_env.py`), and `PIIRedactor.redact_tokens` masks token *patterns* in logs and traces. Nothing masks known credential *values* in tool output before it reaches a model. | AD-1337/#1560. |
```
REPLACE:
```
| 3 | **Secret masking in tool output** (`<secret-hidden>`). | BF-890 strips credential-shaped names from child environments (`execution/command_env.py`), and `PIIRedactor.redact_tokens` masks token *patterns* in logs and traces. Nothing masks known credential *values* in tool output before it reaches a model. | AD-1337/#1560: built. S1 is the owner (`security/secret_masking.py`, `<secret:NAME>`), S2 masks where a tool registry returns, and S3 masks what the agentic loop hands a model, its offloaded copy and the routes past the executor. Per-run values (S4) and a decomposed DAG's reflect prompt (S5) follow. |
```

### 7.13 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit any regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. Add no `roadmap.md` row (this is an AD).

## 8. Issue texts (post after batch 1 merges)

**8.1 #1560, decision 2 amended** (replaces S1's 8.1):
> **Decision 2, amended (AD-1337; consult 4bb6d748; PR #...).** Tool output is masked by one owner, `SecretMasker` (`probos/security/secret_masking.py`), at two seams:
> - the producer seam in `ToolExecutor._invoke_once`, right after the registry returns, which covers the direct, broker and `DispatchToolExecutor` paths and every post-hook;
> - the render seam in `AgenticLoop` (`RenderMask`), which masks AD-1240's captured text before it is offloaded or framed, and every result the loop hands the model, so exception text, custom reprs and the offloaded copy are covered. The loop masks with its own executor's masker.
>
> `ToolExecutor.invoke` alone was not enough: `DispatchToolExecutor.invoke` skips it on its non-protected path, and an exception's text never passes a `ToolResult`. `reply_pipeline`'s direct browser call is masked before its action record and episode are written, and a census fails on any new route past the executor that has no recorded reason. A decomposed DAG's results reach the reflect model through neither seam; AD-1337 S5 masks that route, in batch 2 with S4, and this issue closes after both. `run_python` and `run_command` are registry tools, so both seams cover them. BF-896's session tools run inside the Copilot SDK and are confined by its permission policy. AD-1337 does not mask them; AD-1335 must pass its shell output through `mask_text` before handing it to the SDK.

**8.2 #1557 (AD-1335):** S1's 8.2, unchanged.

**8.3 #1820:** S1's items ad-1337 R1 to R3, unchanged, plus:
- **ad-1337 R4** (Low).
  - *Reach:* a tool exception whose message holds a value: the loop logs its traceback at WARNING (`agentic_loop.py:2931-2939` unarmed, `:2567-2574` parallel).
  - *Evidence:* S3 N5 (the model text is masked; the traceback is the loop's existing log).
  - *Gap:* the log line is not masked; `PIIRedactor` catches token patterns only.
- **ad-1337 R5** (Low).
  - *Reach:* extension fields that are not tool output text: repository instruction files appended to the system prompt (`InstructionObservation`) and delegation evidence frames (`DelegatedToolResult.evidence`, `format_tool_result_content`).
  - *Evidence:* consult Q4.
  - *Gap:* not masked.
- **ad-1337 R6** (Low).
  - *Reach:* a value cut short before a seam sees it: a leaf past the producer walk's bounds that BF-728's shape renderer truncates (`tool_call.py:444-470`).
  - *Gap:* the seams match whole forms only.
- **ad-1337 R8** (Low; R7 is S1's round-3 finding, recorded in the same splice).
  - *Reach:* a session correction whose tool output holds a value.
  - *Evidence:* S3 N17 (masked).
  - *Gap:* no `SECRET_MASKED` is recorded, because the correction projection is event-neutral by design (AD-1126); only the WARNING log records it.

## 9. What this does NOT change

- `ToolExecutor`, the effect broker, the registry, `result_offload.py`, `tool_call.py`, `workspace_results.py`, `decomposer.py` (S5), `runtime.py`, `routers/agent_actions.py`, `finalize.py`.
- `EventType`, `event_persistence.py`, the AD-1195 counts, AD-1224's schemas, `StrictEffectPrivacyProjector`.
- `architecture-baseline.yaml`, `AgenticLoop`'s method count and its constructor signature, the AD-1152 and AD-1240 goldens, config and profiles, HXI.
- S1's code in `security/secret_masking.py`: X10 only inserts two module functions above `class SecretHandle`.

## 10. Mutation rows (one campaign on the M1 candidate; restore between rows)

| Row | Mutant (lines changed) | Killed by |
|---|---|---|
| M9 | `RenderMask.capture` returns `captured` as its first statement (1) | N3, N9 |
| M10 | `RenderMask._mask_final` (section 17): `if isinstance(result.output, str):` becomes `if False:` (1) | N3, N5, N6, N7, N8 (render) |
| M17 | Delete the `result = mask_route_result(...)` statement in `reply_pipeline` (3) | N12, N15 |
| M19 | Dispatch: `loop.secret_masker = None` (1) | N13 |
| T1 | Native builder: `loop.secret_masker = None` (1) | N13 |
| T2 | `SecretMaskerSlot.__set__` without its type check (1) | N1 |
| T3 | Delete the `tcr = await render.final(...)` statement (3) | N5, N7, N14 |
| T4 | Parallel: `by_index[index] = ToolCallResult(...)` without the `final` wrapper (5) | N6, N14 |
| T5 | `capture`: a failed pass returns `captured` (1) | N4 |
| T6 | `"invocation_id": self._carried_call_id(masker, result.id),` in strict mode too (section 17) (1) | N7 (N4's masker fails, so its id is left out either way) |
| T7 | `_emit` drops `await emitted` (1) | N4 |
| T8 | `secret_masker_of` returns the raw attribute (1) | N16 |
| T9 | `mask_route_result` returns a non-`ToolResult` as it is (1) | N12, N16 |
| T10 | `final` emits when nothing was masked (`if True:`) (1) | N2 |
| T11 | `capture` drops its identity return (always `replace`) (1) | N2 (the no-match masker's `capture(...) is captured`); rev1 corrects the draft's N9, which cannot see it because `mask_text` returns the same string |
| T12 | `_emit`: `"names_omitted": 0,` (1) (campaign row X4) | N3 (17 labels must give a count of 1) |
| T13 | `_emit`: `"names": names,` without the slice (1) | N3 (17 labels must give 16) |
| T14 | `CALL_ID_MAX_CHARS = 100000` (1) (campaign row X12) | N3 (a 129-character id must be None; the test uses literals, not the constant) |
| T15 | `_carried_call_id` (section 17): `len(call_id) >= CALL_ID_MAX_CHARS` (1) | N3 (a 128-character id must be kept) |
| T16 | Loop: `strict=strict` becomes `strict=False` in X5's `render.final(...)` (1) (campaign row X17) | N7 (the strict payload must have `tool_id` and `invocation_id` None) |
| T17 | Parallel: `strict=False` becomes `strict=True` in X3 (1) | N6 (`invocation_id == "fixture-call"`) |
| T18 | Loop: `correlation=trace_correlation` becomes `correlation=None` in X5 (1) | N7 (`operation_id == "op-s3"`, `attempt_id == "at-s3"`) |

- **Equivalent:** the campaign's E1, as predicted in the draft; no row.
- **Calls that pass `strict` to `RenderMask.final`:** two. X3 passes the literal False, which is right because the strict profile re-raises before it (P13); T17 pins it. X5 passes `strict=strict`; T16 pins it.
- **Campaign of record:** the draft's campaign ran on the draft oracle, where `secret_masking.py` was S1 before its repair. Rev1 changes these source lines only: X10's position, the extended N3 and N7, and the new `_StrictProfileExecutor`. Rerun on the rev1 oracle:
  - T8 and T9 (their functions moved);
  - T11 (its killer was corrected);
  - T12 to T18 (new).
- **Why the other rows stand:**
  - no line they mutate changed;
  - no assertion that killed them was removed;
  - S1's repair changes only the label of a form two values share, the `unnamed` label and the node budget, and no S3 case reaches any of them: every label is a distinct plain name, no two values share a form, and no output nears 10,000 nodes.
- **sha256 rule:** record each edited file's sha256 on the rev1 oracle. If any file the Builder produces differs, rerun every row that mutates that file and every row killed by a case in `tests/test_ad1337_render_seam.py`.

## 11. Verified Against Codebase (2026-11-21, rev1 on `ob11k`: `5d8a5eb4` + S1 with section 17's repair + S2 rev1)

```
read security/secret_masking.py:40-99, 111-143, 180-400 (ob11k; blob a00840e3, 400 lines)
  188: class SecretHandle:                    (once in src)
  189:     """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
  374-400: _map_strings (rewritten by section 17 RB3; the draft's X10 anchor is gone)
  37-38: imports CredentialStore, masked_credential_values, ToolResult; 40: logger; 50: MASKING_FAILED_TEXT
read agentic_loop.py:40-47, 1364-1368, 2549-2584, 2660-2667, 2676-2715, 2740-2805, 2842-2972, 2967-3000, 3011-3080 (ob11k)
  44-46, 1366-1368, 2575-2579, 2664-2666, 2960-2967: X1 to X5 SEARCH text, unchanged from the draft
  2557-2560: the parallel branch re-raises under protected_effects_enabled
  2780-2805: a strict result's metadata gives trace_correlation; 2974-2999: completed event under strict
rg -n "strict=" agentic_loop.py   1256 1285 1635 1747 2248 2290 2702 2997 (no RenderMask call yet)
read effect_adapters.py:375-404 (_OUTCOMES, _reason: [a-z0-9_]{1,64}), 669-708 (project_event)
read effect_types.py:66-71 (EffectCorrelation: no validation)
rg -n "def protected_effects_enabled" src   tools/executor.py:976 (returns self._effect_broker is not None)
read tests/test_bf965_unoffered_tool_refusal.py:100-123, 355-366 (the strict executor double runs a whole loop)
read agentic_dispatch.py:1535-1546, 4170-4189 (ob11k)   1541-1544 X6, 4184-4186 X7 (each once)
rg -n "AD-1240: assigned after construction, never as a keyword" native_builder.py   160 (once)
read reply_pipeline.py:1185-1196; rg -c "result = await browser_tool.invoke\(" reply_pipeline.py   1
rg -n '"SECRET_MASKED"' tests/test_ad1195_durable_producers.py   69
rg -c "# ProbOS Progress" PROGRESS.md   1; PROGRESS.md:3 holds S2 rev1's "21 cases"
read DECISIONS.md:1666-1676   1674 TR2 SEARCH (unchanged by S2 rev1), 1676 TR3 SEARCH (each once)
rg -n "Secret masking in tool output" docs/research/openhands-absorption.md   33
rg -n "_runtime_secret_masker" tests   test_ad1337_executor_seam.py:227-229 (N4), :536 (N19)
rg -c "^(async )?def test_" tests/test_ad1337_executor_seam.py   21
read credential_store.py:451-484 (every JSON-store entry is a (name, value) pair)
read tests/test_ad1337_secret_masking.py:59-99, 516-520; test_ad1147_parallel_tools.py:106-113
read tests/test_ad1240_tool_result_delivery.py:181-191, 1876-1880
Draft evidence (5d8a5eb4, ob11f), unchanged lines: tool_call.py:390-446, 669-873, 876-911; result_offload.py:148-193,
  430-449, 522-554, 575-677, 709-740; workspace_results.py:109-139; workspace_result_store.py:887; swe_harness/tools.py:265-297;
  agentic_dispatch.py:3029-3033, 4083-4196; native_builder.py:95-179; routers/agent_actions.py:55-99; action_dispatcher.py:180;
  agent_work_runner.py:483-504; tools/context.py:107-140; federation/mcp_server.py:463-519; mcp_apps/registry.py:95-124, 244-268;
  mcp_bridge/bridge.py:259-274, adapter.py:11-48; runtime.py:2034, 5023-5153, 5438-5491; decomposer.py:460-512, 691-730, 955-1004;
  crew_verifier.py:464, 578-618; tools/registry.py:77-82, 468-499; tools/executor.py:312-324, 738-773; the AD-1152, AD-1324,
  AD-1195, AD-1343, AD-1240, AD-745 and AD-1147 tests named in section 3; tools/browser/actions.py:1368-1402;
  self_query_tool.py:55-84, 195-215; test_layer_boundaries.py:14-53
git ls-files --eol (the eight edited files on main)   i/lf w/crlf
```

## Absence Verified (2026-11-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No S3 name exists yet | `rg -l "render_masking\|RenderMask\|SecretMaskerSlot\|secret_masker_of\|mask_route_result\|CALL_ID_MAX_CHARS" -g "*.py"` (ob11k) | none | yes |
| `secret_masking.py` has no `__all__` to extend | `rg "__all__" src/probos/security/` (ob11k) | none | yes |
| The loop has no masker | `rg "secret" src/probos/cognitive/swe_harness/agentic_loop.py` | none | yes |
| No `render` name in the loop module | `rg "\brender\b" agentic_loop.py` | docstrings only (`:419`, `:496`, `:834`, `:917`) | yes |
| Two loop constructions, no alias or subclass | `rg "AgenticLoop\("`, `rg "class \w+\([^)]*AgenticLoop\|= AgenticLoop\b\|AgenticLoop as "` in src | `agentic_dispatch.py:4174`, `native_builder.py:140` | yes |
| Only two `final` calls pass `strict` after S3 | `rg "strict=" agentic_loop.py` (ob11k) plus X3 and X5 | the eight existing lines (none a `RenderMask` call), plus X3 and X5 | yes |
| No test reads `_runtime_secret_masker`'s body | `rg "_runtime_secret_masker" tests` (ob11k) | N4's calls and N19's keyword-source string only | yes |
| The route scans | `rg "\.check_and_invoke\(\|\.call_tool\(" src`; `rg "[a-z_]*tool[a-z_]*\.invoke\(" src`; `rg "await [A-Za-z_.]+\.invoke\(" src` | the 14 rows of N15 (plus executors' own `executor.invoke`) | checked by N15 (section 16) |
| `ToolContext.invoke` has no caller | `rg "tool_context" src` | `agent_onboarding.py:573-592`, `cognitive_agent.py:1462`, `events.py:304`; no `.invoke(` | yes |
| `MCPToolAdapter` is never built | `rg "MCPToolAdapter\(" src` | none | yes |
| Internal app tools are only the game's | `rg "register_app_tool\(" src` | `mcp_apps/game_app.py` only | yes |
| Nothing reads an action's result after an ACK | `rg "action_dispatcher\|ActionDispatcher" src`; `rg "\.result\b" action_dispatcher.py` | three files; `:180` (the write) | yes |
| No test scans the edited loop lines as source | `rg` for the replaced lines and for `getsource\|agentic_loop.py.\.read_` in tests | `test_ad1125:1325` and `test_ad1240:5324` are each test's own calls; the AD-1152 golden's `base_source_blobs` are historical and not compared | yes |
| No new event member or count | F1 only | n/a | yes |

## 12. Deterministic checks

- **Focused gate, `-n 0`:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on:
  - `tests/test_ad1337_render_seam.py`, `tests/test_ad1337_executor_seam.py`, `tests/test_ad1337_secret_masking.py`
  - `tests/test_ad545_agentic_loop.py`, `tests/test_ad1146_multiturn_messages.py`, `tests/test_ad1147_parallel_tools.py`, `tests/test_ad1148_tool_result_bounds.py`, `tests/test_ad1151_durable_tool_outputs.py`, `tests/test_bf965_unoffered_tool_refusal.py`, `tests/test_bf946_read_only_delivery_failures.py`
  - `tests/test_ad1240_tool_result_delivery.py`, `tests/test_ad1240_workspace_result_lifecycle.py`, `tests/test_ad1152_agentic_correlation.py`, `tests/test_ad1153_browser_agentic_loop.py`, `tests/test_ad856_agentic_dispatch.py`, `tests/test_ad1189_deferred_tool_schemas.py`, `tests/test_ad1192_owned_steps_dm.py`, `tests/test_ad1187_agent_work_pull.py`, `tests/test_ad1261_authority_domain.py`, `tests/test_ad1316_governed_effect_broker.py`
  - `tests/test_ad546_native_builder_harness.py`, `tests/test_ad1200_repository_instruction_wire.py`, `tests/test_ad1205_fault_paths.py`
  - `tests/test_ad745_episode_anchor.py`, `tests/test_ad1343_stop_seam_inventory.py`, `tests/test_ad1343_seam_registry.py`, `tests/test_ad1343_agent_stop_runs.py`, `tests/test_ad1346_admission_shadow_routing.py`, `tests/test_ad1156_plan_mode_reply_tags.py`
  - `tests/test_ad1195_durable_producers.py`, `tests/test_layer_boundaries.py`, `tests/test_ad1324_srp_layout.py`, `tests/test_ad1270b_architecture_fitness.py`, `tests/test_ad1184_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` exits 0.
- `rg -l masked_credential_values src` finds only `credential_store.py` and `security/secret_masking.py`.
- `git diff 089895c1 -- src/probos/tools/ src/probos/events.py src/probos/event_persistence.py src/probos/startup/ src/probos/runtime.py src/probos/cognitive/swe_harness/result_offload.py src/probos/cognitive/swe_harness/tool_call.py docs/development/architecture-baseline.yaml tests/fixtures/` is empty.
- `git diff 089895c1 -- src/probos/security/secret_masking.py` shows insertions only, all above `class SecretHandle:`.
- The new files are ASCII only.
- Broad gate, once for batch 1: `scripts/run_test_gate.py --label ad-1337-1560 --receipt logs/gates/ad-1337-1560.receipt.json`.

## 13. Prior art and blind spots

- **Internal:**
  - consult `4bb6d748` Q1, Q4, Q5, Q7 and Q8;
  - AD-1240's `WorkspaceResultsSlot` (the slot pattern);
  - AD-1343's census and `DIRECT_TOOL_INVOKES` (reused, not copied);
  - AD-1195 PROD-1;
  - BF-965's strict-profile executor double (the shape N7's strict half reuses).
- **External:** no new search; this is ProbOS plumbing of S1's researched design.
  - The GitHub Actions runner masks again at each output it writes, which is the same shape as a render seam after a producer seam.
  - Reference projects checked 2026-11-21: OpenHands was last reviewed 2026-10-15 with a 90-day interval, so it is not overdue and no row changes.
- **Blind spots named:**
  - the DAG reflect route (D8, S5);
  - log tracebacks (R4);
  - extension fields (R5);
  - truncated leaves (R6);
  - a placeholder longer than its value can push a frame or receipt past its bound (fail closed, D4);
  - a PEM value collapsed to one placeholder shortens the source frame's worked call (benign: the recovery reads a valid, masked window);
  - HXI shows placeholders wherever it shows the same result object.

## 14. Diff Reviewer: properties to verify

1. Every `ToolCallResult` that `_execute_one_tool` returns, other than the constant BF-965 refusal and an `InvocationRefusal`, passes `RenderMask.final` before the effect correlation is attached. That `final` receives the call's own `strict` flag and `trace_correlation`. The parallel conversion passes its own `final` with `strict=False`, which is correct because that branch re-raises under the strict profile (`agentic_loop.py:2557-2560`). Every AD-1240 capture passes `RenderMask.capture` before `prepare_result`.
2. Without a masker, or with no match, every object is returned as it is (the same text, capture and result) and no event is emitted. The AD-1152 and AD-1240 goldens are unchanged.
3. No value, form or position reaches a log line, an event payload or an exception message. The render payload has exactly S2's eight keys, at most 16 labels with the rest counted, and a call id of at most 128 characters. A strict call carries no tool id and no call id.
4. A failed pass withholds (the capture is replaced by a withheld result's; the final text is `MASKING_FAILED_TEXT`, and a withheld result carries no delivered frame except a failed delivery's fixed code). A delivered frame is checked as the model reads it; one that holds a known value is withheld, never rewritten. The call id is carried only when it holds no known value. Nothing raises out of the seam, and an emitter failure never unmasks.
5. Both `AgenticLoop` constructions assign `secret_masker_of(<their tool_executor>)` right after construction. The slot refuses a non-masker. There is no constructor keyword and no new `AgenticLoop` method.
6. The tier-1 browser result is masked before `mark_executed` and the episode. A non-`ToolResult` is withheld only when a masker exists.
7. Every N15 row's reason is true of the code it names. S2's census strings and AD-1343's inventory are unchanged.
8. The only AD-1195 change is the producer row.
9. `secret_masking.py` changes by insertion only: two module functions above `class SecretHandle`, and no S1 line is altered.

## 15. Acceptance

- [ ] Section 5's prediction holds: a collection error on `089895c1`, then 18 passed after M1. The focused gate is green.
- [ ] Section 17.8's prediction holds: 6 failed and 17 passed with the test pairs alone on `25944b39`, then 23 passed; rows U1 to U12 are killed by their named cases.
- [ ] Mutation rows M9, M10, M17, M19 and T1 to T18 are killed by the named cases (section 10's rerun set on the rev1 oracle).
- [ ] Section 12's `rg` and diff checks hold, and `check_architecture_principles.py --check` passes.
- [ ] TR1 to TR4 are applied, and the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-21, scratch trees detached at `70763ad6`: S1 as repaired by sections 17 and 18, S2's contract and its first milestone, with S2's two tracker pairs applied, then this contract's pairs; rev1 was proved first on a tree at `3e8248b0` with S1's section-17 repair and S2 rev1)

Every pair of section 7 was applied to scratch worktrees by `audit\contract_tools.py` (ASCII only: no `--utf8` was needed). Each test run went through `run_pytest_homeguard.ps1` (a redirected, empty home). A bare `pytest` was not used: it imports the main checkout's `src` and fails for the wrong reason. Results:

| O | Result |
|---|---|
| O1 | All 17 operations (the two new files, X1 to X10, F1, TR1 to TR4) are found by `contract_tools.py list`; every SEARCH of 7.3 to 7.8 and of TR1 to TR4 occurs exactly once on that base, S2's two tracker pairs having been applied first (S3's `TR2` anchors on text S2's `TR2` adds). Blobs after the pairs: the new test file `7a19392f`, `render_masking.py` `ca5235e5`, `agentic_loop.py` `775b6374`, `agentic_dispatch.py` `60c6761a`, `native_builder.py` `5f0fac6f`, `reply_pipeline.py` `9fd6c4ec`, `secret_masking.py` `95086015` (S1's second repair and X10), `tests/test_ad1195_durable_producers.py` `22403e85`, `docs/research/openhands-absorption.md` `0158aad8`. `PROGRESS.md` and `DECISIONS.md` carry the earlier slices' edits too, so the Builder's checkpoint table (computed on the committed head) names their blobs; the ledger pair is regenerated by M2. |
| O2 | The new test file alone on that base: **a collection error**, `ModuleNotFoundError: No module named 'probos.cognitive.swe_harness.render_masking'` (the right reason). |
| O3 | After the pairs: **18 passed** (16 cases, 18 items) in 41 s. |
| O4 | `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`). An AST count: `AgenticLoop` has **13** methods and 1,738 lines, `RenderMask` 4 methods and 99 lines, `SecretMaskerSlot` 3 methods and 22 lines. |
| O5 | N15's `found` equals `ROUTES`: the case passes as written, so no key-spelling fix and no new route was needed. |
| O6 | N7's strict half passes as written: the strict-profile double reaches `from_tool_result` at `:2880`, so no member was added to `_StrictProfileExecutor`, and the campaign's X17 (`strict=False` at X5's call) is killed by N7. |
| O7 | **Section 12's `rg` and diff checks.** `rg -l masked_credential_values src` finds only `credential_store.py` and `security/secret_masking.py`. `git diff 70763ad6` over `src/probos/tools/`, `events.py`, `event_persistence.py`, `startup/`, `runtime.py`, `result_offload.py`, `tool_call.py`, the architecture baseline and `tests/fixtures/` is empty. `secret_masking.py` gains 28 lines in one hunk, all above `class SecretHandle:` and none removed (a diff against the same tree without X10). The two new files hold no non-ASCII character. |
| O8 | **The mutation campaign** (`audit\rows_ad1337s3.py`: section 10's rows, with the draft's X4, X12, X17 and X17b standing for T12, T14, T16 and T18, plus my extra rows X1 to X3, X5 to X11, X13 to X16 and X18 to X23, and E1): **killed 42, differs 0, survived 1, invalid 0** (43 rows over the unmutated baseline of 39 passing cases: S3's 18 and S2's 21; run on `3e8248b0` plus S1's repair, S2 and S3 as then written). The survivor is E1, `_emit`'s `if emit_fn is None:` to `if False:`, which section 10 names as equivalent: a render mask with no emitter never reaches the guard with anything to emit. Every row names killers that failed; X23 has no named killer and is killed by one case. Section 18 changes `secret_masking.py` above the lines S3's rows mutate, so the five rows that mutate that file (T8, T9, X20, X21, X22) were rerun on the final base (the tree of O1, 39 passing cases unmutated): **killed 5, differs 0, survived 0, invalid 0**, each by its named cases. |
| O9 | **The 34 files of section 12**, four workers each, on `53696f68` (S1 as repaired by section 17) with S2's and S3's pairs and the regenerated ledger: **2,589 passed, 14 skipped** under the default embeddings (505 s) and **2,589 passed, 14 skipped** under `PROBOS_EMBEDDINGS=local` (469 s). The 14 skips are AD-1240's POSIX-only cases (unprivileged symlinks, FIFOs, directory renames). Section 18 adds four cases to one file of that list; the consolidated check on the committed head is the figure of record. |
| O10 | **All three new files and the closest consumers on the final base** (`70763ad6` plus section 18, S2's tracker pairs, S3 and the regenerated ledger; S1's 97 cases, S2's 21, S3's 18, the four AD-1195 files, the ledger, layer-boundary, SRP-layout and fitness tests, 11 files): **818 passed** in 133 s; `check_config_facade.py --check` and `gen_ad_ledger.py --check` pass. |

**What the orchestrator changed in the Architect's rev1:** nothing in the pairs, the tests or the rows; this section replaces the placeholder, and the `Answers to (a)-(j)` tail of the answer is not part of the contract.

**What these checks do not show.**
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`, and the DAG reflect route (S5) and the per-run vault registrations (S4) are not in this slice.
- A render seam driven by a real model: the cases use the loop's own doubles, which is what section 5 names.
- The full suite: it runs once for the batch, after this slice.

---

## 17. Repair after review round 1 (2026-11-21)

**Base:** `25944b39` (batch 1 head), with the S2 repair already applied to S2's files.

**Milestones:**

| M | Content | Tier | Review |
|---|---|---|---|
| M3 | 17.2 (tests first), then 17.3, 17.4, 17.5 | HIGH, security control | **Full** review (round 1 found High defects, and `RenderMask.final`'s return shape changes) |
| M4 | 17.6, 17.7, then `gen_ad_ledger.py` and its `--check` | LOW | Delta |

**Commit subjects:**
- M3: `Withhold a frame the render seam cannot mask and carry the masker into a correction`
- M4: `Record the render seam repair in the status and decisions entries`

### 17.1 Classification and decisions

| F | Fix | Where |
|---|---|---|
| F1 | `_SessionCorrectionRuntime.secret_masker`, filled from `secret_masker_of(runtime)` | RV1 to RV4 |
| F2 | `final` checks the delivered frame and withholds one that changes; it never rewrites one | RM2 |
| F3 | `_carried_call_id`: the id is kept only when the mask pass returns it unchanged | RM2 |
| F4 | Every withhold goes through `_withheld`, which drops a non-failed delivery | RM2 |
| F5 | N15 reads every `invoke` call; five new `ROUTES` rows; two new assertions | RT5 to RT7 |
| Wide run | AD-1320 blob re-pin | RP1 |

**Heavier designs rejected:**
- A `without_result_delivery` helper in `tool_call.py`. It would be the owner's natural home, but it edits AD-1240's module and breaks section 12's empty-diff check, for one caller.
- Rewriting the frame with placeholders. A masked worked path points the recovery at a file that does not exist.
- An emitter in the projection. It would widen the event-neutral projection (AD-1126, `test_ad1126:1812`), so it is recorded as R8 instead (renumbered by the orchestrator: R7 is S1's round-3 finding F7).

**Conditional for the Builder:** if the S2 repair changed how S2's `test_a_dispatch_run_shows_the_model_the_placeholder_and_emits_secret_masked` readies its masker, apply the same step in N17, with the same lines, and record it in the report.

### 17.2 `tests/test_ad1337_render_seam.py` (M3, written first)

**RT1.** SEARCH:
```
import probos
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    ToolCallResult,
    capture_tool_result,
    result_delivery,
    tool_registration_to_llm_definition,
)
from probos.events import EventType
from probos.security import secret_masking
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
```
REPLACE:
```
import probos
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_verifier import _session_correction_runtime
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallResult,
    capture_tool_result,
    result_delivery,
    tool_registration_to_llm_definition,
    with_result_delivery,
)
from probos.events import EventType
from probos.execution.workspace_results import ResultDelivery
from probos.repository_instructions import InstructionObservation
from probos.security import secret_masking
from probos.security.secret_masking import (
    MASKING_FAILED_TEXT,
    MaskOutcome,
```

**RT2.** SEARCH:
```
from tests import test_ad1240_tool_result_delivery as delivery_tests
from tests import test_ad745_episode_anchor as action_tests
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures.ad1343_seam_registry import DIRECT_TOOL_INVOKES
from tests.offered_tools import offer
from tests.test_ad1147_parallel_tools import _RecordingEmit
from tests.test_ad1240_tool_result_delivery import (
```
REPLACE:
```
from tests import test_ad1240_tool_result_delivery as delivery_tests
from tests import test_ad1337_executor_seam as executor_tests
from tests import test_ad745_episode_anchor as action_tests
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures.ad1343_seam_registry import DIRECT_TOOL_INVOKES
from tests.offered_tools import offer
from tests.test_ad1147_parallel_tools import _RecordingEmit
from tests.test_ad1224_durable_tool_start import _dispatch_runtime, _offering_store
from tests.test_ad1240_tool_result_delivery import (
```

**RT3.** Extends N3. SEARCH:
```
    assert [(p["invocation_id"], p["names"], p["names_omitted"]) for p in _masked(capped)] == [
        ("i" * 128, sorted(many)[:16], 1), (None, sorted(many)[:16], 1),
    ]
```
REPLACE:
```
    assert [(p["invocation_id"], p["names"], p["names_omitted"]) for p in _masked(capped)] == [
        ("i" * 128, sorted(many)[:16], 1), (None, sorted(many)[:16], 1),
    ]

    # The call id is the model's: one that holds a known value is left out of the event while the text is masked.
    leaky = _RecordingEmit()
    shown = await RenderMask(_real_masker(tmp_path / "leaky")).final(
        ToolCallResult(id=f"call_{TOKEN}", output=f"c {TOKEN}"),
        emit_fn=leaky, tool_name="fixture_result", strict=False, correlation=None,
    )
    assert shown.output == f"c {PLACEHOLDER}"
    assert [(p["invocation_id"], p["names"]) for p in _masked(leaky)] == [(None, ["github"])]
    assert [form for form in secret_forms(TOKEN) if form in json.dumps(leaky.events)] == []
```

**RT4.** Extends N4. SEARCH:
```
    assert again.output == MASKING_FAILED_TEXT
    assert "SECRET_MASKED could not be emitted at the render seam" in caplog.text and TOKEN not in caplog.text
```
REPLACE:
```
    assert again.output == MASKING_FAILED_TEXT
    assert "SECRET_MASKED could not be emitted at the render seam" in caplog.text and TOKEN not in caplog.text

    # A withheld delivered result keeps no frame the model would read instead, but keeps an instruction or delegation
    # extension; a failed delivery keeps its own fixed frame, so the run still stops on it (BF-946).
    observation, evidence = InstructionObservation(), DelegationEvidence(status="completed")
    for plain, kind in (
        (ToolCallResult(id="d", output="z"), ToolCallResult),
        (
            InstructionToolCallResult(id="d", output="z", repository_instructions=observation),
            InstructionToolCallResult,
        ),
        (DelegatedToolCallResult(id="d", output="z", evidence=evidence), DelegatedToolCallResult),
    ):
        held = await RenderMask(masker).final(
            with_result_delivery(plain, ResultDelivery("workspace", "Outline: a frame")),
            emit_fn=None, tool_name="t", strict=False, correlation=None,
        )
        assert type(held) is kind and result_delivery(held) is None
        assert (held.id, held.output, held.is_error) == ("d", MASKING_FAILED_TEXT, True)
        assert getattr(held, "repository_instructions", observation) is observation
        assert getattr(held, "evidence", evidence) is evidence
    stopped = with_result_delivery(
        ToolCallResult(id="d", output="z"), ResultDelivery("failed", "!", code="capture_limit"),
    )
    kept = await RenderMask(masker).final(stopped, emit_fn=None, tool_name="t", strict=False, correlation=None)
    assert result_delivery(kept) is result_delivery(stopped)
    assert (kept.output, kept.is_error) == (MASKING_FAILED_TEXT, True)
```

**RT5.** Adds five `ROUTES` rows. SEARCH:
```
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect (AD-1337 S5)",
}
```
REPLACE:
```
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect (AD-1337 S5)",
    ("src/probos/cognitive/swe_harness/agentic_loop.py", "AgenticLoop._execute_one_tool", "invoke", "self._executor"):
        "the loop's executor: the producer seam, then the render seam (N14)",
    ("src/probos/cognitive/agentic_dispatch.py", "DispatchToolExecutor.invoke", "invoke", "super()"):
        "the executor itself (ToolExecutor.invoke): the producer seam masks what it returns",
    ("src/probos/execution/effect_broker.py", "_EffectDispatchMixin.dispatch", "invoke", ""):
        "the broker's callback: its one caller hands it ToolExecutor's invoke_reserved (asserted below)",
    ("src/probos/cognitive/repair_verification.py", "verify_repair", "invoke", "executor"):
        "the runtime's ToolExecutor (the producer seam); the retry reads only result.error, for its signature",
    ("src/probos/tools/browser/tool.py", "BrowserTool.open_captain_session", "invoke", "self"):
        "the Captain's own session open: its one caller, the browser router, returns the answer to the Captain "
        "(asserted below); no model or record reads it",
}
```

**RT6.** The head of N15. SEARCH:
```
def test_every_route_past_the_tool_executor_is_masked_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str, str]] = set()
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        visitor = _RouteCalls(path.relative_to(seam_census.ROOT).as_posix())
        visitor.visit(ast.parse(path.read_bytes()))
        found |= {(c.file, c.function, c.callee, c.receiver) for c in visitor.calls}
    found |= {
        (c.file, c.function, c.callee, c.receiver) for c in seam_census.census()
        if c.callee == "invoke" and c.receiver.split(".")[-1].endswith(("tool", "bridge"))
    }
    assert found == set(ROUTES), sorted(found ^ set(ROUTES))
```
REPLACE:
```
def test_every_route_past_the_tool_executor_is_masked_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str, str]] = set()
    captain_opens: list[str] = []
    broker_dispatches: list[tuple[str, list[str]]] = []
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        rel = path.relative_to(seam_census.ROOT).as_posix()
        tree = ast.parse(path.read_bytes())
        visitor = _RouteCalls(rel)
        visitor.visit(tree)
        found |= {(c.file, c.function, c.callee, c.receiver) for c in visitor.calls}
        for node in ast.walk(tree):
            if _callee(node) == "open_captain_session":
                captain_opens.append(rel)
            elif _callee(node) == "dispatch" and ast.unparse(node.func).endswith("broker.dispatch"):
                broker_dispatches.append((rel, [ast.unparse(arg) for arg in node.args]))
    # Every invoke call, whatever its receiver: a filter on the receiver's name hid five (review round 1).
    found |= {(c.file, c.function, c.callee, c.receiver) for c in seam_census.census() if c.callee == "invoke"}
    assert found == set(ROUTES), sorted(found ^ set(ROUTES))
```

**RT7.** The tail of N15. SEARCH:
```
        < seam_census.first_line(step, seam_census.calls("mask_route_result"))
        < seam_census.first_line(step, seam_census.calls("mark_executed"))
    )


def test_the_route_helpers_mask_a_tool_result_and_withhold_anything_else(
```
REPLACE:
```
        < seam_census.first_line(step, seam_census.calls("mask_route_result"))
        < seam_census.first_line(step, seam_census.calls("mark_executed"))
    )
    assert captain_opens == ["src/probos/routers/browser_stream.py"]
    opened = seam_census.function("src/probos/routers/browser_stream.py", "open_browser_session")
    assert "await browser_tool.open_captain_session(body.url)" in {
        ast.unparse(node.value) for node in ast.walk(opened) if isinstance(node, ast.Return) and node.value is not None
    }
    assert broker_dispatches == [("src/probos/tools/executor.py", ["request", "invoke_reserved"])]


def test_the_route_helpers_mask_a_tool_result_and_withhold_anything_else(
```

**RT8.** Adds N17 and N18 at the end of the file. SEARCH:
```
    assert mask_route_result(masker, ToolResult(output={"text": TOKEN}), route="r").output == {"text": PLACEHOLDER}
    assert "AD-1337: route=r masked names=['github']" in caplog.text and TOKEN not in caplog.text
```
REPLACE:
```
    assert mask_route_result(masker, ToolResult(output={"text": TOKEN}), route="r").output == {"text": PLACEHOLDER}
    assert "AD-1337: route=r masked names=['github']" in caplog.text and TOKEN not in caplog.text


# -- N17 and N18: the repair after review round 1 (section 17) ------------------------------------------------------


async def test_a_session_correction_masks_what_its_tools_return(tmp_path: Path) -> None:
    masker = _real_masker(tmp_path)
    for projected in (False, True):
        tool = executor_tests._EchoTool("echo_dispatch", f"correction result {TOKEN}")
        runtime = _dispatch_runtime(
            registry=executor_tests._registry(tool), event_log=None,
            perm_store=await _offering_store("agent-s2", "echo_dispatch"),
        )
        runtime.secret_masker = masker
        runtime.emit_event = executor_tests._Events()
        target = (
            _session_correction_runtime(runtime, agent_id="agent-s2", department="engineering", rank="lieutenant")
            if projected else runtime
        )
        llm = executor_tests._CapturingLLM("echo_dispatch")

        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-s2", instructions="Test instructions.", task_text="use the probe", runtime=target,
        )

        assert tool.calls == 1, projected  # premise: the tool ran, through the projection too
        shown = repr(llm.requests[1])
        assert PLACEHOLDER in shown and TOKEN not in shown, projected
    assert target.secret_masker is masker  # the projection carries the runtime's masker

    # Every dispatch run is handed the runtime its caller was given, or this one projection: a new projection would
    # add a spelling here, and needs a case like the one above.
    handed: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            keywords = {k.arg: k.value for k in node.keywords} if isinstance(node, ast.Call) else {}
            if "task_text" in keywords and "runtime" in keywords:
                value = keywords["runtime"]
                handed.add(f"{_callee(value)}()" if isinstance(value, ast.Call) else ast.unparse(value))
    assert handed == {"runtime", "self._runtime", "_session_correction_runtime()"}


@pytest.mark.parametrize("case", ["clean", "known_root", "frame_fails", "output_fails"])
async def test_a_delivered_frame_that_cannot_be_masked_is_withheld_not_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    owned = tmp_path / "rig" / (f"own-{TOKEN}" if case == "known_root" else "own")
    owned.mkdir(parents=True)
    runtime, executor, context = _environment(owned)
    assert (TOKEN in str(runtime.workspace_results.root)) == (case == "known_root")  # premise
    registration = runtime.tool_registry.register(_RawTool(ToolResult(output="HEAD\n" + "y" * 20000)))
    masker = _real_masker(tmp_path / "masker")
    real, passes = masker.mask_text, []

    def _injected(text: str) -> MaskOutcome:
        # The injected faults: the pass over the frame fails, or every pass after the capture fails.
        passes.append(text)
        if (case == "frame_fails" and "Outline:" in text) or (case == "output_fails" and len(passes) > 1):
            return MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
        return real(text)

    monkeypatch.setattr(masker, "mask_text", _injected)
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=3, tool_result_max_chars=6000,
        structured_tool_messages=True, workspace_results=runtime.workspace_results, event_emit_fn=emit,
    )
    loop.secret_masker = masker

    async with _started(runtime):
        result = await loop.run(
            system_prompt="fixture", user_message="recover",
            tools=[tool_registration_to_llm_definition(registration)], context=context,
        )

    shown = _last_result(llm.requests[1])
    recorded = result.tool_results[0]
    assert [form for form in secret_forms(TOKEN) if form in _requests_text(llm)] == []
    if case == "clean":
        assert "Outline:" in shown and result_delivery(recorded).status == "workspace"
        assert _masked(emit) == []
        return
    # The model is shown the withheld text, never the frame, and the recorded result carries no delivery.
    assert shown == MASKING_FAILED_TEXT
    assert type(recorded) is ToolCallResult and result_delivery(recorded) is None
    assert (recorded.output, recorded.is_error) == (MASKING_FAILED_TEXT, True)
    [payload] = _masked(emit)
    assert (payload["names"], payload["failed"], payload["invocation_id"]) == (
        ["github"] if case == "known_root" else [], True, None if case == "output_fails" else "fixture-call",
    )
```

**RT9.** (Added by the orchestrator: RT4 builds a real `DelegationEvidence`, because `DelegatedToolCallResult.__post_init__` refuses any other object.) SEARCH:
```
from probos.tools.executor import ToolExecutor, tool_record_identity
```
REPLACE:
```
from probos.tools.delegation_evidence import DelegationEvidence
from probos.tools.executor import ToolExecutor, tool_record_identity
```

**Stop condition for the Builder.** Stop and report, without adapting the test, if any of these happens after the code pairs:
- N15's assertion message names a key outside the 19;
- N17's `handed` set holds a spelling outside the three;
- N18 finds a form of the token anywhere in the requests other than the tool message.

Each would be a new route or leak, not a fixture to update.

### 17.3 `src/probos/cognitive/swe_harness/render_masking.py` (M3)

**RM1.** SEARCH:
```
from probos.cognitive.swe_harness.tool_call import CapturedConversion, ToolCallResult, capture_tool_result
```
REPLACE:
```
from probos.cognitive.swe_harness.tool_call import (
    CapturedConversion,
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallResult,
    capture_tool_result,
    result_delivery,
)
```

**RM2.** SEARCH (`render_masking.py:98-141` on `25944b39`):
```
    async def final(
        self,
        result: ToolCallResult,
        *,
        emit_fn: Callable[..., Any] | None,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> ToolCallResult:
        """Mask the text this call hands the model, then emit ``SECRET_MASKED`` once if either pass masked or failed.

        A failed pass withholds: the output becomes ``MASKING_FAILED_TEXT`` and the result an error.
        """
        if self._masker is not None and isinstance(result.output, str):
            outcome = self._masker.mask_text(result.output)
            if outcome.failed:
                from probos.security.secret_masking import MASKING_FAILED_TEXT

                self._failed = True
                result = replace(result, output=MASKING_FAILED_TEXT, is_error=True)
            elif outcome.text is not result.output:
                self._names |= outcome.names
                result = replace(result, output=outcome.text)
        if self._names or self._failed:
            await self._emit(emit_fn, result, tool_name=tool_name, strict=strict, correlation=correlation)
        return result

    async def _emit(
        self,
        emit_fn: Callable[..., Any] | None,
        result: ToolCallResult,
        *,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> None:
        from probos.events import EventType

        names = sorted(self._names)
        call_id = result.id if type(result.id) is str and len(result.id) <= CALL_ID_MAX_CHARS else None
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else call_id,
```
REPLACE:
```
    async def final(
        self,
        result: ToolCallResult,
        *,
        emit_fn: Callable[..., Any] | None,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> ToolCallResult:
        """Mask the text this call hands the model, then emit ``SECRET_MASKED`` once if either pass masked or withheld.

        The model reads a delivered result's frame instead of its output (``format_tool_result_content``), so the frame
        is checked too. A failed pass, or a frame that holds a known value, withholds (``_withheld``).
        """
        masker = self._masker
        if masker is None:
            return result
        result = self._mask_final(masker, result)
        if self._names or self._failed:
            await self._emit(masker, emit_fn, result, tool_name=tool_name, strict=strict, correlation=correlation)
        return result

    def _mask_final(self, masker: SecretMasker, result: ToolCallResult) -> ToolCallResult:
        if isinstance(result.output, str):
            outcome = masker.mask_text(result.output)
            if outcome.failed:
                return self._withheld(result)
            if outcome.text is not result.output:
                self._names |= outcome.names
                result = replace(result, output=outcome.text)
        delivery = result_delivery(result)
        if delivery is not None:
            # A frame is never rewritten: a masked worked path would send the recovery to a file that does not exist.
            # One that holds a known value (a workspace root or a source path that contains one) is withheld, and so
            # is one whose pass failed (its text is then MASKING_FAILED_TEXT, which differs too).
            framed = masker.mask_text(delivery.presentation)
            if framed.text is not delivery.presentation:
                self._names |= framed.names
                return self._withheld(result)
        return result

    def _withheld(self, result: ToolCallResult) -> ToolCallResult:
        """``result`` as an error whose output is ``MASKING_FAILED_TEXT``, with no frame the model would read instead.

        A failed delivery keeps its extension: its frame is a fixed code, and the run still stops on it (BF-946). Any
        other delivery is dropped; an instruction or delegation extension is kept as it was.
        """
        from probos.security.secret_masking import MASKING_FAILED_TEXT

        self._failed = True
        delivery = result_delivery(result)
        if delivery is None or delivery.status == "failed":
            return replace(result, output=MASKING_FAILED_TEXT, is_error=True)
        kept = {"id": result.id, "output": MASKING_FAILED_TEXT, "is_error": True, "duration_ms": result.duration_ms}
        if isinstance(result, DelegatedToolCallResult):
            return DelegatedToolCallResult(**kept, evidence=result.evidence)
        if isinstance(result, InstructionToolCallResult):
            return InstructionToolCallResult(**kept, repository_instructions=result.repository_instructions)
        return ToolCallResult(**kept)

    @staticmethod
    def _carried_call_id(masker: SecretMasker, call_id: object) -> str | None:
        """The model's tool-call id for the payload, or None: not a str, longer than ``CALL_ID_MAX_CHARS``, or holding
        a known value. The id is the model's (its JSON is unchecked), so it is checked like the text and never masked
        into the record; a failed pass returns ``MASKING_FAILED_TEXT``, which leaves it out too."""
        if type(call_id) is not str or len(call_id) > CALL_ID_MAX_CHARS:
            return None
        return call_id if masker.mask_text(call_id).text is call_id else None

    async def _emit(
        self,
        masker: SecretMasker,
        emit_fn: Callable[..., Any] | None,
        result: ToolCallResult,
        *,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> None:
        from probos.events import EventType

        names = sorted(self._names)
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else self._carried_call_id(masker, result.id),
```

### 17.4 `src/probos/cognitive/crew_verifier.py` (M3)

**RV1.** SEARCH:
```
    from probos.cognitive.verifier_independence import VerifierJudgePolicy
    from probos.consensus.trust import TrustNetwork
    from probos.substrate.registry import AgentRegistry
```
REPLACE:
```
    from probos.cognitive.verifier_independence import VerifierJudgePolicy
    from probos.consensus.trust import TrustNetwork
    from probos.security.secret_masking import SecretMasker
    from probos.substrate.registry import AgentRegistry
```

**RV2.** SEARCH:
```
    emit_event: None = None
    event_emit_fn: None = None
    fault_observer: ToolFaultObservationPort | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedSessionCorrectionOutcome:
```
REPLACE:
```
    emit_event: None = None
    event_emit_fn: None = None
    fault_observer: ToolFaultObservationPort | None = None
    # AD-1337 S3 (#1560): the runtime's masker, so the correction's dispatch executor and loop mask what its tools
    # return (agentic_dispatch reads it through secret_masker_of). A filter over tool output, not runtime authority.
    secret_masker: SecretMasker | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedSessionCorrectionOutcome:
```

**RV3.** SEARCH:
```
    """Build one event-neutral governed capability projection for correction."""
    from probos.cognitive.agentic_dispatch import register_mesh_intent_tools
```
REPLACE:
```
    """Build one event-neutral governed capability projection for correction."""
    from probos.cognitive.agentic_dispatch import register_mesh_intent_tools
    from probos.security.secret_masking import secret_masker_of
```

**RV4.** SEARCH:
```
        fault_observer=(
            ToolFaultObservationPort(observer.observe_tool_run)
            if observer is not None else None
        ),
    )
```
REPLACE:
```
        fault_observer=(
            ToolFaultObservationPort(observer.observe_tool_run)
            if observer is not None else None
        ),
        secret_masker=secret_masker_of(runtime),
    )
```

### 17.5 `tests/test_ad1320_agentic_budget_awareness.py` (M3)

**RP1.** SEARCH:
```
    # The blob before #1796 was 24179141cc441e31e176227fc767b39b950ac976.
    rel, blob = "cognitive/swe_harness/native_builder.py", "6641aa6aa67c91244efc6189d7044397bd46eaf1"
```
REPLACE:
```
    # The blob before #1796 was 24179141cc441e31e176227fc767b39b950ac976.
    # AD-1337 S3 (#1560): native_builder.py now assigns the render seam's masker slot from its executor (a two-line
    # comment, one import, one blank line, one assignment); the protected property (no budget_awareness in this
    # file) is unchanged.
    # The blob before AD-1337 S3 was 6641aa6aa67c91244efc6189d7044397bd46eaf1.
    rel, blob = "cognitive/swe_harness/native_builder.py", "5f0fac6ffc9ef52e0c4f04068f65df9832f24877"
```

### 17.6 `PROGRESS.md` (M4)

**TP1.** SEARCH (occurs once): `` Measured by `tests/test_ad1337_render_seam.py` (16 cases, 18 items) ``

REPLACE: `` Measured by `tests/test_ad1337_render_seam.py` (18 cases, 23 items) ``

**TP2.** SEARCH (occurs once):
```
three censuses pin the loop's mask positions, each loop's masker source and the 14 routes past the executor. Not measured: a live run.
```
REPLACE:
```
four censuses pin the loop's mask positions, each loop's masker source, the runtime each dispatch run is handed and the 19 routes past the executor. Review round 1's repair: a session correction's runtime projection carries the masker (it masked nothing before); a delivered frame that holds a known value, or whose pass fails, is withheld rather than rewritten, because the model reads the frame and not the output; a call id that holds a known value is left out of the event. Not measured: a live run.
```

### 17.7 `DECISIONS.md` (M4)

**TD1.** SEARCH (occurs once):
```
and a strict call carries neither it nor a tool id. A failed pass withholds.
```
REPLACE:
```
and a strict call carries neither it nor a tool id; an id that holds a known value is left out, not masked (review round 1). A failed pass withholds. The model reads a delivered result's frame, not its output, so the final pass checks the frame too and withholds one that holds a known value (a workspace root or source path containing one) rather than rewrite it: a masked worked path would send the recovery to a file that does not exist. A withheld result keeps no delivered frame, except a failed delivery's fixed code, on which the run still stops (BF-946).
```

**TD2.** SEARCH (occurs once):
```
the Captain's ACK (HXI only), the internal MCP app tools (game state), and the MCP bridge with its callers.
```
REPLACE:
```
the Captain's ACK and session open (HXI only), the internal MCP app tools (game state), the MCP bridge with its callers, and the executor paths (the loop's, the dispatch executor's, the broker's callback, the repair retry). The census reads every `invoke` call whatever its receiver: review round 1 found that a filter on the receiver's name had hidden five. A session correction's runtime projection carries the runtime's masker (a filter over tool output, not authority); the projection stays event-neutral, so a correction masks but emits no `SECRET_MASKED` (#1820 ad-1337 R8). A census pins the runtime each dispatch run is handed.
```

There is no change to the `*Residual.*` line. The residual numbering is the orchestrator's: R7 is S1's round-3 finding F7, so this item is R8 (TD2 and correction C14 say R8), and the priming-window seam of S2's repair is R9; the #1820 splice records R7 to R9.

### 17.8 Counts and the focused gate

**S3's file:**

| Run | Prediction |
|---|---|
| On `25944b39`: S3's file now holds 18 cases, 23 items; the test pairs alone | **6 failed, 17 passed** |
| After every pair | **23 passed** |

The 6 that fail on the tests alone:
- N3: the call id holds the token;
- N4: the extension block, because the delivery is kept;
- N17: the projected model saw the token;
- N18, three items: `known_root`, `frame_fails` and `output_fails`. On the old code each delivers the frame.

N15 passes on the tests alone, because F5's repair is test-only.

**AD-1320:** `test_native_builder_and_continue_or_ask_are_untouched_negative_pins` fails on `25944b39` and passes after RP1.

**Focused gate, `-n 0`:**
- Section 12's 34 files;
- `tests/test_ad1320_agentic_budget_awareness.py`;
- `tests/test_ad1126_verified_finalization.py`, `tests/test_ad1241_mcp_offer_budget.py`, `tests/test_ad1190_delegation_tree_budget.py`, `tests/test_ad1346_admission_shadow_crew.py`, `tests/test_ad860_crew_verifier.py`.

Then `check_architecture_principles.py --check`, and `gen_ad_ledger.py --check`. Commit a regenerated ledger in M4 if `--check` asks for one.

### 17.9 Mutation rows (one change each; restore between rows)

| Row | Mutant | Killed by |
|---|---|---|
| U1 | `_mask_final`: `if delivery is not None:` becomes `if False:` | N18[known_root], N18[frame_fails] |
| U2 | `_mask_final`: the frame branch's `return self._withheld(result)` becomes `return result` | N18[known_root], N18[frame_fails] |
| U3 | `_mask_final`: delete `self._names \|= framed.names` | N18[known_root] |
| U4 | `_mask_final`: the output branch's `return self._withheld(result)` becomes `return replace(result, output=outcome.text, is_error=True)` | N4, N18[output_fails] |
| U5 | `_withheld`: `if delivery is None or delivery.status == "failed":` becomes `if True:` | N4, N18[known_root, frame_fails, output_fails] |
| U6 | `_withheld`: the same line becomes `if delivery is None:` | N4 (the failed delivery must be kept) |
| U7 | `_withheld`: `if isinstance(result, DelegatedToolCallResult):` becomes `if False:` | N4 |
| U8 | `_withheld`: `if isinstance(result, InstructionToolCallResult):` becomes `if False:` | N4 |
| U9 | `_withheld`: delete `self._failed = True` | N18[known_root, frame_fails, output_fails] |
| U10 | `_carried_call_id`: the return becomes `return call_id` | N3, N18[output_fails] |
| U11 | `final`: `if masker is None:` becomes `if False:` | N2 |
| U12 | `crew_verifier.py`: `secret_masker=secret_masker_of(runtime),` becomes `secret_masker=None,` | N17 |

Section 10's M10, T6 and T15 are restated by C10 to C12 below. All other rows stand as written.

**Campaign of record:** `render_masking.py`'s `final` and `_emit` and S3's test file both change, so the section 10 sha256 rule makes this a whole rerun on the M3 candidate: M9, M10, M17, M19, T1 to T18 (as amended), U1 to U12 and E1. Record each edited file's sha256. E1 stays equivalent.

### 17.10 Round-2 review: properties to verify (full review, delta `25944b39..`)

1. A session correction's dispatch masks:
   - run N17;
   - revert RV4 alone and confirm N17 fails;
   - confirm the projection gains only `secret_masker` and stays event-neutral (`test_ad1126:1773` passes).
2. No delivered frame that holds a known value reaches the model, and no frame is rewritten:
   - run N18;
   - revert RM2's frame block alone and confirm `known_root` and `frame_fails` fail.
3. Every withheld result carries no delivered frame, except a failed delivery, which keeps its fixed code so `_delivery_stop` and BF-946 behave as before. Instruction and delegation extensions survive (N4).
4. The payload keeps S2's eight keys:
   - `invocation_id` is the model's id only when the mask pass returned it unchanged (N3, N18[output_fails]);
   - `tool_id` is `tool_record_identity` with no catalog (`executor.py:312-326`);
   - `operation_id` and `attempt_id` come only from the trusted correlation.
5. N15 enumerates every `invoke` call, and each of the five new reasons is true of its code:
   - `executor.py:895` is the broker's only dispatch;
   - `browser_stream.py:186` returns the answer to the router;
   - `repair_verification.py:231-247` reads only `error`.
6. Without a masker, or with no match, every object comes back as it is, and the AD-1240 golden is unchanged (N2, N11).
7. RP1's blob equals `git rev-parse <candidate>:src/probos/cognitive/swe_harness/native_builder.py`.
8. The diff touches only the files of 17.2 to 17.7 and the ledger. No `AgenticLoop` method or constructor keyword is added. `tool_call.py`, `result_offload.py`, `tools/` and `startup/` are unchanged from `25944b39`.

### 17.11 Verified Against Codebase (2026-11-21, `ob11` at `25944b39`)

```
read render_masking.py:1-163        98-141 RM2 SEARCH; 25 RM1 SEARCH; 31 SecretMasker under TYPE_CHECKING
read tool_call.py:680-693, 736-749, 876-911   DeliveryToolCallResult family; result_delivery; with_result_delivery
read workspace_results.py:350-367   ResultDelivery(status, presentation, reference=None, code=None); failed validates code
read result_offload.py:287-295, 405-418, 438-448, 575-677   admit -> promised; offer; delivery_failure; frames at 651, 673
read agentic_loop.py:870-891 (frame is what the model reads), 1263-1296 (_delivery_stop), 1757-1773, 2951-2991
read crew_verifier.py:85-92, 621-635, 1013-1024, 1266-1291   RV1-RV4 SEARCH text, each once
rg "import TrustNetwork|emit_event: None = None|fault_observer: ToolFaultObservationPort|if observer is not None else None" crew_verifier.py
  90, 632, 634, 1289 (each once)
read secret_masking.py:43-84, 193-229, 297-336   MaskOutcome; MASKING_FAILED_TEXT; secret_masker_of; no __slots__
read executor.py:312-326 (tool_record_identity), 880-904 (broker.dispatch(request, invoke_reserved, ...))
read browser/tool.py:1317-1387; routers/browser_stream.py:172-186; repair_verification.py:167-248
read effect_broker.py:454-548 (dispatch; bare invoke(context) at 548, no nested def)
read tests/fixtures/ad1343_seam_census.py:1-204 (Visitor records Name and Attribute callees, receiver unparse)
read tests/test_ad1337_render_seam.py:1-645; test_ad1337_executor_seam.py:83-252; test_ad1240:151-191, 677-719, 1876-1925
read tests/test_ad1320_agentic_budget_awareness.py:616-628
git rev-parse 25944b39:...native_builder.py 5d8a5eb4:...native_builder.py   5f0fac6f..., 6641aa6a...
rg -c on PROGRESS.md / DECISIONS.md for TP1, TP2, TD1, TD2 SEARCH text   1 each
read tests/test_layer_boundaries.py:14-53   security is not a checked layer
read swe_harness/tools.py:494-497   read_file's description is static (no path)
read probe_b11s3_r1.py (the orchestrator's): F1 rig agent-s2/engineering/lieutenant; F2 root "own-"+TOKEN
```

**Absence Verified (2026-11-21):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other call is passed as `runtime=` | `rg -n "\bruntime=[A-Za-z_][A-Za-z_0-9.]*\(" src/probos` | `crew_verifier.py:2155` only | yes |
| `runtime=` beside `task_text=` is spelled three ways | `rg "task_text=" src/probos`, then `rg "^\s+runtime=" src/probos`; `rg "runtime=" crew_executor.py crew_finalizer.py` | `runtime` (agentic_dispatch 4365; cognitive_agent 2361, 2546, 5210, 5816), `self._runtime` (agent_work_runner 646, crew_verifier 1670, delegate_task_tool 498), the projection; crew_executor and crew_finalizer have no `runtime=` | yes |
| No test compares the projection's fields | `rg "__slots__\|dataclass_fields\|fields\(\|asdict\(proj\|vars\(proj"` in the six files that use it | `test_ad1190:824, :1540` and `test_ad1205:761` (other classes); `test_ad1346:245` (`vars(projection.tool_registry)`) | yes |
| The `invoke` calls in src | `rg -n "\.invoke\(" src/probos`; `rg -n "(^\|[^.\w])invoke\(" src/probos` | the 9 old rows plus `agentic_dispatch:1562` (`super()`), `effect_broker:548` (bare), `repair_verification:222`, `browser/tool:1361`, `agentic_loop:2764`; everything else is a def, a comment or a docstring | yes, subject to N15 |
| `open_captain_session` has one caller | `rg open_captain_session src/probos` | `browser_stream.py:186` | yes |
| `broker.dispatch` has one caller | `rg "broker\.dispatch\(" src` | `executor.py:895` | yes |
| No doc names the pinned blob | `rg "6641aa6a\|5f0fac6f"` | this test plus two historical prompts | yes |
| No test reads `RenderMask` internals | `rg "_emit\(\|_failed\|_names\|CALL_ID_MAX_CHARS" tests/test_ad1337*.py` | none of `RenderMask`'s | yes |
| `_session_correction_runtime` builds one object | `rg "_SessionCorrectionRuntime\(" src` | `crew_verifier.py:1267` | yes |

### 17.12 The orchestrator's first-hand checks

The 20 operations of this section (RT1 to RT9, RM1, RM2, RV1 to RV4, RP1, TP1, TP2, TD1, TD2) were applied to a scratch worktree detached at `25944b39` (the committed S3 head) after S2's repair of its own section 17 (the order the real tree gets them in), by `audit\contract_tools.py apply --prefix 17.` (ASCII only), and every check below was run before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (an empty redirected home; BF-919) and each probe through `run_probe_homeguard.ps1`; a bare `pytest` was not used: it imports `D:\ProbOS\src` and fails for the wrong reason.

| R | Result |
|---|---|
| R1 | All 20 operations are found by `contract_tools.py list --prefix 17.`; every SEARCH occurs exactly once on `25944b39` after S2's 18 operations (the code, the test and the tracker pairs alike). The six files change by +245 -24 lines: `render_masking.py` 63 and 14 (162 to 211 lines), `crew_verifier.py` 6 and 0, `tests/test_ad1337_render_seam.py` 168 and 6 (644 to 806 lines; 18 cases, 23 items), `tests/test_ad1320_agentic_budget_awareness.py` 5 and 1, `PROGRESS.md` one line and `DECISIONS.md` two lines replaced in place. Blobs after all 20 operations: `render_masking.py` `a3ee21b9`, `crew_verifier.py` `a9cefe62`, the render seam test file `a09d60e1`, the AD-1320 test file `b45b228a`, and, with S2's repair applied as well, `PROGRESS.md` `6d596ba2` and `DECISIONS.md` `590906df`. No added line is non-ASCII. |
| R2 | **The tests alone** (RT1 to RT9 applied, the code pairs not; RT4 and RT9 as the last paragraph says): **6 failed, 17 passed** in 48 s, exactly the prediction of 17.8, each for its stated reason: N3 on its id assertion (the event carries the model's call id `call_tok-...` where `None` is expected); N4 on the extension block (the result is still a `DeliveryToolCallResult` where a plain `ToolCallResult` is expected); N17 on its `projected` case (the model's request does not hold the placeholder); N18 on three items: `known_root` on its list of known values left in the frame the model reads (`['tok-...']` where `[]` is expected), and `frame_fails` and `output_fails` on the model's frame (the workspace frame where the withheld text is expected). N15 passes on the tests alone (F5's repair is test-only). |
| R3 | After all 20 operations: S3's file alone **23 passed** (18 cases, 23 items), and S2's file, S3's file and `tests/test_ad1320_agentic_budget_awareness.py` together **121 passed** in 59 s. The AD-1320 case `test_native_builder_and_continue_or_ask_are_untouched_negative_pins` fails on `25944b39` (the blob of `native_builder.py` is `5f0fac6f...`, the pin says `6641aa6a...`) and passes after RP1. |
| R4 | **The reproductions of review round 1, before and after** (`probe_b11s3_r1.py`, one case per finding, each beside a control that is clean on both trees; before in `evidence-b11s3r1-probe.txt`, after in `evidence-b11s3r1-probe-cand.txt`). F1: before the repair, the projected runtime of a session correction carries no masker and the model saw the raw token; after it the projected runtime masks (`target_carries_a_masker` True). F2: before, the delivered frame, which holds a path component with a known value, reaches the model (`model_frame_chars` 734, 0 render events); after it the delivery is withheld (`delivery_status` null, the model's frame is 43 characters, the withheld text), the recorded output is clean and one render event was emitted. F3: before, the event's `invocation_id` held the known value (`call_tok-...`); after it is `None`. F4: before, after a failed final pass the model was given the workspace frame; after it the model gets the withheld text. F5: before, `BrowserTool.open_captain_session` was in neither `ROUTES` nor `DIRECT_TOOL_INVOKES` (the census saw its `invoke(self)` and its filter dropped it); after it is in `ROUTES`. |
| R5 | **The campaign** (`audit\mutants_gen.py`, `rows_ad1337s3r1.py`): the rows of section 17.9 (U1 to U12) and the rows of section 10 that this section changes or restates (M9, M10, M17, M19 and T1 to T17 as amended), rerun on the candidate with S3's and S2's test files (47 baseline cases, all passing), plus my extra rows X1 to X23; 55 rows in all: **killed 54, differed 0, survived 1, invalid 0**. Every named killer failed in every row. The survivor is E1, the equivalent mutant the contract expects: with the `if emit_fn is None: return` in `_emit` removed, a missing emitter raises a `TypeError` that the `except Exception` below it catches, so the only difference is one more WARNING line, which no case reads. The home was empty after each run. |
| R6 | **Static checks.** `check_architecture_principles.py --check` passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`). `AgenticLoop` is unchanged at 1738 lines and 13 methods; `RenderMask` has 141 lines and 7 methods, `SecretMaskerSlot` 22 lines and 3, `_SessionCorrectionRuntime` 16 lines and no method (an AST count). `native_builder.py`'s blob on `25944b39` is `5f0fac6ffc9e...`, the value RP1 pins (it was `6641aa6a...` on `5d8a5eb4`). `rg -l "RenderMask\|SecretMaskerSlot" src` finds exactly `render_masking.py` and `agentic_loop.py`; `crew_verifier.py` names `secret_masker_of` on one import and one assignment. `git diff 25944b39 --stat` lists only the files of 17.2 to 17.7 and S2's seven files. `gen_ad_ledger.py --check` is not run here: the trackers change, and M4 regenerates the ledger. |
| R7 | **The wide consumer run on `25944b39`** (263 test files touching the loop, the dispatch, the render seam, the crew verifier, the projection and the executor; `evidence-b11wide-def.txt`): 5 failed, 11042 passed, 14 skipped. Triage, each rerun alone on the candidate and on the main baseline `5d8a5eb4`: the AD-1320 pin is S3's (RP1 repairs it, R3); two `tests/ablation/test_sigma_harness_structural.py` cases fail identically on `5d8a5eb4` (the file is in the gate's release exclusions); two `test_ad1324_terminal_context` cases pass alone on both trees and fail only under load (flakes). No other consumer fails. |
| R8 | **The consolidated focused set on the candidate** (the 34 files of section 12, `tests/test_ad1320_agentic_budget_awareness.py`, the projection consumers and `tests/test_ad860_crew_verifier.py`: 46 files, `-n 0`, default embedding mode, a tree with S2's 18 operations and these 20 applied): **3565 passed, 14 skipped** in 1039 s (the skips are AD-1240's POSIX-only cases). The run repeats on the committed head, in both embedding modes. |
| R9 | **S3 on the repaired S2**: S2's section 17 applied first, then these 20 operations: every SEARCH occurs exactly once in that order, the trackers included (S2's repair and S3's repair edit different lines of `PROGRESS.md` and `DECISIONS.md`). |

**What the orchestrator changed in the Architect's section 17:** RT4's evidence fixture and a new pair RT9 (RT4 built the delegated result with `evidence=object()`, which raises `TypeError: delegated call result requires typed evidence` on `tool_call.py:752`; it now builds `DelegationEvidence(status="completed")`, and RT9 adds the import `from probos.tools.delegation_evidence import DelegationEvidence` before the `probos.tools.executor` import); the residual numbering (R7 is S1's round-3 finding F7, so the session-correction event gap is R8 and S2's priming-window route seam is R9). The test pairs were rerun red and green after the change: R2 and R3 are the results after it. TD1 and TD2 carry the new numbering and were edited after the oracle runs of R2 to R8, which ran with their earlier text (the `DECISIONS.md` blob above is the final one); no test reads them, and the check of every SEARCH in R9 was repeated on the real tree. Nothing else in the pairs, the tests or the rows.

**What these checks do not show.**
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.
- A session correction's masking event: the projection stays event-neutral, so no `SECRET_MASKED` event is emitted for a masked correction (R8 of the follow-up list); N17 pins that the text is masked.
- The route seam of the priming window (R9 of the follow-up list).

---

## 18. Repair after review round 2 (2026-11-22)

**Base:** `693c685c`, the batch 1 head. S3's code, tests and contract there are as review round 2 read them at `1a1a4782`; the three commits after it touch S2's files and S2's tracker lines only.

**Milestones:**

| M | Content | Tier | Review |
|---|---|---|---|
| M5 | 18.2 (tests first), then 18.3 | HIGH, security control | Delta re-review (round 3) over `693c685c..`. No shared contract changes (18.1). |
| M6 | 18.4, 18.5, then `gen_ad_ledger.py` and its `--check` | LOW | Delta |

**Commit subjects:**
- M5: `Keep the tool's length on a withheld result and leave an unissued correlation out of the render event`
- M6: `Record the render seam's second repair in the status and decisions entries`

About 15 Builder tool calls for M5 and 8 for M6. Line endings are as section 0 says: the SEARCH blocks are LF; match and write each file with its own endings.

### 18.1 Classification and decisions

| F | Fix | Where |
|---|---|---|
| F1 | The render event takes `operation_id` and `attempt_id` only from a strict call's correlation. Without the strict profile, the loop's correlation can only come from a tool's own exception (`agentic_loop.py:2906-2929`). | RQ7; N19 (RQ2, RQ3, RQ5) |
| F2 | `_withheld` keeps `source_chars` (BF-760), so the durable trace still reports the tool's own length. | RQ6; N4 (RQ1, RQ3, RQ4) |
| F3 | Recorded as #1820 ad-1337 R11: under the strict profile, a render withhold reaches the model as the broker's reason code. | RQ11 names it |
| F4 | The contract's cost sentences (lines 84 and 147) count `mask_text` calls, not the two API stages. | Corrections applied by the orchestrator, outside this section |

**Heavier designs rejected:**
- Checking each id like the call id (option B): two more `mask_text` calls per event, to check ids the broker already issued or checked.
- Fixing F3 now: it changes the strict privacy surface, needs a new fixed code (`MASKING_FAILED_TEXT` fails `StrictEffectPrivacyProjector._reason`) and edits `agentic_loop.py`, which this repair does not touch.

**Not changed:** `agentic_loop.py`, `tool_call.py`, `result_offload.py`, `execution/`, `tools/` and `startup/`.

### 18.2 `tests/test_ad1337_render_seam.py` (M5, written first)

**RQ1.** SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallResult,
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, build_tool_trace_payload
from probos.cognitive.swe_harness.render_masking import RenderMask, SecretMaskerSlot
from probos.cognitive.swe_harness.tool_call import (
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallRequest,
    ToolCallResult,
```

**RQ2.** SEARCH:
```
from probos.events import EventType
from probos.execution.workspace_results import ResultDelivery
```
REPLACE:
```
from probos.events import EventType
from probos.execution.effect_types import EffectCorrelation
from probos.execution.workspace_results import ResultDelivery
```

**RQ3.** Adds the correlated raising tool and the trace helper. SEARCH:
```
class _RaisingTool(_RawTool):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"bad credential {TOKEN}")
```
REPLACE:
```
class _RaisingTool(_RawTool):
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"bad credential {TOKEN}")


class _CorrelatedRaising(_RawTool):
    """An ordinary tool whose exception carries an effect correlation, as the broker's do (effect_broker.py:727), with
    ids that hold the value. Without the strict profile no broker issued it, so the render event leaves it out."""

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        correlation = EffectCorrelation(f"op-{TOKEN}", f"at-{TOKEN}", "failed", "tool_failed")
        exc = RuntimeError(f"bad credential {TOKEN}")
        exc.effect_correlation = correlation  # type: ignore[attr-defined]
        raise exc


def _traced(result: ToolCallResult) -> tuple[Any, Any]:
    """The durable trace's view of one result (BF-760): the length it received and the tool's own length, if any."""
    [entry], _blob = build_tool_trace_payload(
        [ToolCallRequest(name="t", arguments={}, id=result.id)], [result],
        output_max_chars=8192, blob_max_bytes=1_000_000,
    )
    return entry["output_chars"], entry.get("source_chars")
```

**RQ4.** Extends N4 so each withheld result keeps the tool's length through the trace consumer. SEARCH:
```
    # A withheld delivered result keeps no frame the model would read instead, but keeps an instruction or delegation
    # extension; a failed delivery keeps its own fixed frame, so the run still stops on it (BF-946).
    observation, evidence = InstructionObservation(), DelegationEvidence(status="completed")
    for plain, kind in (
        (ToolCallResult(id="d", output="z"), ToolCallResult),
        (
            InstructionToolCallResult(id="d", output="z", repository_instructions=observation),
            InstructionToolCallResult,
        ),
        (DelegatedToolCallResult(id="d", output="z", evidence=evidence), DelegatedToolCallResult),
    ):
        held = await RenderMask(masker).final(
            with_result_delivery(plain, ResultDelivery("workspace", "Outline: a frame")),
            emit_fn=None, tool_name="t", strict=False, correlation=None,
        )
        assert type(held) is kind and result_delivery(held) is None
        assert (held.id, held.output, held.is_error) == ("d", MASKING_FAILED_TEXT, True)
        assert getattr(held, "repository_instructions", observation) is observation
        assert getattr(held, "evidence", evidence) is evidence
    stopped = with_result_delivery(
        ToolCallResult(id="d", output="z"), ResultDelivery("failed", "!", code="capture_limit"),
    )
    kept = await RenderMask(masker).final(stopped, emit_fn=None, tool_name="t", strict=False, correlation=None)
    assert result_delivery(kept) is result_delivery(stopped)
    assert (kept.output, kept.is_error) == (MASKING_FAILED_TEXT, True)
```
REPLACE:
```
    # A withheld delivered result keeps no frame the model would read instead, but keeps an instruction or delegation
    # extension; a failed delivery keeps its own fixed frame, so the run still stops on it (BF-946). Each keeps the
    # tool's own length (BF-760), which the durable trace reports beside the withheld text (section 18).
    observation, evidence = InstructionObservation(), DelegationEvidence(status="completed")
    for plain, kind in (
        (ToolCallResult(id="d", output="z", source_chars=20005), ToolCallResult),
        (
            InstructionToolCallResult(id="d", output="z", source_chars=20005, repository_instructions=observation),
            InstructionToolCallResult,
        ),
        (DelegatedToolCallResult(id="d", output="z", source_chars=20005, evidence=evidence), DelegatedToolCallResult),
    ):
        held = await RenderMask(masker).final(
            with_result_delivery(plain, ResultDelivery("workspace", "Outline: a frame")),
            emit_fn=None, tool_name="t", strict=False, correlation=None,
        )
        assert type(held) is kind and result_delivery(held) is None
        assert (held.id, held.output, held.is_error, held.source_chars) == ("d", MASKING_FAILED_TEXT, True, 20005)
        assert _traced(held) == (len(MASKING_FAILED_TEXT), 20005)
        assert getattr(held, "repository_instructions", observation) is observation
        assert getattr(held, "evidence", evidence) is evidence
    stopped = with_result_delivery(
        ToolCallResult(id="d", output="z", source_chars=20005), ResultDelivery("failed", "!", code="capture_limit"),
    )
    kept = await RenderMask(masker).final(stopped, emit_fn=None, tool_name="t", strict=False, correlation=None)
    assert result_delivery(kept) is result_delivery(stopped)
    assert (kept.output, kept.is_error, kept.source_chars) == (MASKING_FAILED_TEXT, True, 20005)
    assert _traced(kept) == (len(MASKING_FAILED_TEXT), 20005)
```

**RQ5.** Adds N19 at the end of the file. SEARCH:
```
    [payload] = _masked(emit)
    assert (payload["names"], payload["failed"], payload["invocation_id"]) == (
        ["github"] if case == "known_root" else [], True, None if case == "output_fails" else "fixture-call",
    )
```
REPLACE:
```
    [payload] = _masked(emit)
    assert (payload["names"], payload["failed"], payload["invocation_id"]) == (
        ["github"] if case == "known_root" else [], True, None if case == "output_fails" else "fixture-call",
    )


# -- N19: the repair after review round 2 (section 18) --------------------------------------------------------------


async def test_a_correlation_without_the_strict_profile_never_reaches_the_render_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    masker = _real_masker(tmp_path)
    loose, issued = _RecordingEmit(), _RecordingEmit()
    await RenderMask(masker).final(
        ToolCallResult(id="c", output=f"x {TOKEN}"), emit_fn=loose, tool_name="t", strict=False,
        correlation=EffectCorrelation(f"op-{TOKEN}", f"at-{TOKEN}", "failed", "tool_failed"),
    )
    await RenderMask(masker).final(
        ToolCallResult(id="c", output=f"x {TOKEN}"), emit_fn=issued, tool_name="t", strict=True,
        correlation=EffectCorrelation("op-1", "at-1", "result", "tool_completed"),
    )
    assert [(p["operation_id"], p["attempt_id"]) for p in _masked(loose) + _masked(issued)] == [
        (None, None), ("op-1", "at-1"),
    ]

    # Through the loop: an ordinary tool's exception carries the correlation, and the loop's exception branch hands
    # it to the render seam. Only the render event is this test's contract: the loop's live completed event still
    # carries the tool's ids (#1820 ad-1337 R12).
    registry, definition = _registered(_CorrelatedRaising(ToolResult()))
    emit = _RecordingEmit()
    llm = _FakeLLM([_turn(), _done()])

    await _run(_loop(llm, ToolExecutor(registry=registry), masker, emit), [definition])

    assert _last_result(llm.requests[1]) == f"Tool fixture_result failed: bad credential {PLACEHOLDER}"
    assert _masked(emit) == [{
        "seam": "render", "tool_id": tool_record_identity("fixture_result"), "invocation_id": "fixture-call",
        "operation_id": None, "attempt_id": None, "names": ["github"], "names_omitted": 0, "failed": False,
    }]
    render_lines = "\n".join(r.getMessage() for r in caplog.records if r.name == RenderMask.__module__)
    assert "render seam masked" in render_lines
    shown = json.dumps(_masked(loose) + _masked(emit)) + _requests_text(llm) + render_lines
    assert [form for form in secret_forms(TOKEN) if form in shown] == []
```

### 18.3 `src/probos/cognitive/swe_harness/render_masking.py` (M5)

**RQ6.** SEARCH:
```
        A failed delivery keeps its extension: its frame is a fixed code, and the run still stops on it (BF-946). Any
        other delivery is dropped; an instruction or delegation extension is kept as it was.
        """
        from probos.security.secret_masking import MASKING_FAILED_TEXT

        self._failed = True
        delivery = result_delivery(result)
        if delivery is None or delivery.status == "failed":
            return replace(result, output=MASKING_FAILED_TEXT, is_error=True)
        kept = {"id": result.id, "output": MASKING_FAILED_TEXT, "is_error": True, "duration_ms": result.duration_ms}
```
REPLACE:
```
        A failed delivery keeps its extension: its frame is a fixed code, and the run still stops on it (BF-946). Any
        other delivery is dropped; an instruction or delegation extension is kept as it was. Every withheld result
        keeps the tool's own length (``source_chars``, BF-760), which the durable trace reports.
        """
        from probos.security.secret_masking import MASKING_FAILED_TEXT

        self._failed = True
        delivery = result_delivery(result)
        if delivery is None or delivery.status == "failed":
            return replace(result, output=MASKING_FAILED_TEXT, is_error=True)
        kept = {
            "id": result.id, "output": MASKING_FAILED_TEXT, "is_error": True, "duration_ms": result.duration_ms,
            "source_chars": result.source_chars,
        }
```

**RQ7.** SEARCH:
```
        names = sorted(self._names)
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else self._carried_call_id(masker, result.id),
            "operation_id": correlation.operation_id if correlation is not None else None,
            "attempt_id": correlation.attempt_id if correlation is not None else None,
```
REPLACE:
```
        names = sorted(self._names)
        # Only the broker issues a correlation, and only under the strict profile. Without it the loop's correlation
        # can come from a tool's own exception (``effect_correlation``), whose ids are the tool's and unchecked.
        trusted = correlation if strict else None
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else self._carried_call_id(masker, result.id),
            "operation_id": trusted.operation_id if trusted is not None else None,
            "attempt_id": trusted.attempt_id if trusted is not None else None,
```

### 18.4 `PROGRESS.md` (M6)

**RQ8.** SEARCH:
```
Measured by `tests/test_ad1337_render_seam.py` (18 cases, 23 items)
```
REPLACE:
```
Measured by `tests/test_ad1337_render_seam.py` (19 cases, 24 items)
```

**RQ9.** SEARCH:
```
a call id that holds a known value is left out of the event. Not measured: a live run.
```
REPLACE:
```
a call id that holds a known value is left out of the event. Review round 2's repair: without the strict profile the event carries no operation or attempt id (a correlation then comes from a tool's own exception, not the broker); a withheld result keeps the tool's own length for the durable trace. Not measured: a live run.
```

### 18.5 `DECISIONS.md` (M6)

**RQ10.** SEARCH:
```
an id that holds a known value is left out, not masked (review round 1). A failed pass withholds.
```
REPLACE:
```
an id that holds a known value is left out, not masked (review round 1). `operation_id` and `attempt_id` come only from a strict call's correlation, which the broker issues: without the strict profile a correlation can only come from a tool's own exception, so the event leaves both out (review round 2). A failed pass withholds.
```

**RQ11.** SEARCH:
```
A withheld result keeps no delivered frame, except a failed delivery's fixed code, on which the run still stops (BF-946).
```
REPLACE:
```
A withheld result keeps no delivered frame, except a failed delivery's fixed code, on which the run still stops (BF-946). It keeps the tool's own length (`source_chars`, BF-760), so the durable trace still reports what the tool returned. Under the strict profile the model is told the broker's reason code for a withheld result, not that it was withheld (#1820 ad-1337 R11).
```

The `*Residual.*` line does not change: the residual numbering is the orchestrator's.

### 18.6 Counts and the focused gate

| Run on `693c685c` | Prediction |
|---|---|
| RQ1 to RQ5 applied, code pairs not (19 cases, 24 items) | **2 failed, 22 passed** |
| After every pair | **24 passed** |

The 2 that fail on the tests alone:
- N4, on `held.source_chars`: it is `None` where 20005 is expected.
- N19, on its first assertion: `("op-tok-...", "at-tok-...")` where `(None, None)` is expected.

The failed-delivery `kept` case passes on both trees, because `replace` keeps `source_chars`.

**Focused gate, `-n 0`:**
- `tests/test_ad1337_render_seam.py`, `tests/test_ad1337_executor_seam.py`;
- `tests/test_bf760_trace_records_the_tools_length.py`, `tests/test_ad1240_tool_result_delivery.py`;
- `tests/test_ad1152_agentic_correlation.py`, `tests/test_ad1195_durable_producers.py`;
- `tests/test_bf965_unoffered_tool_refusal.py`, `tests/test_ad1224_durable_tool_start.py`, `tests/test_ad1324_srp_layout.py`.

Then `check_architecture_principles.py --check`, and in M6 `gen_ad_ledger.py --check`. Commit a regenerated ledger if `--check` asks for one. `render_masking.py` grows from 211 to 218 lines; `AgenticLoop` is untouched.

### 18.7 Mutation rows (one change each; restore between rows)

| Row | Mutant | Killed by |
|---|---|---|
| W1 | `_emit`: `trusted = correlation if strict else None` becomes `trusted = correlation` | N19 (both halves) |
| W2 | `_emit`: the same line becomes `trusted = None` | N4, N7, N19 |
| W3 | `_withheld`: delete `"source_chars": result.source_chars,` | N4 |
| W4 | `_emit`: the `operation_id` line becomes `"operation_id": correlation.operation_id if correlation is not None else None,` | N19 |
| W5 | `_emit`: the `attempt_id` line becomes `"attempt_id": correlation.attempt_id if correlation is not None else None,` | N19 |

**Campaign of record:** `render_masking.py` and S3's test file both change, so section 10's sha256 rule makes this a whole rerun on the M5 candidate: M9, M10, M17, M19, T1 to T18 (as amended), U1 to U12, W1 to W5 and E1. Record each edited file's sha256. E1 stays equivalent.

### 18.8 Round-3 review: properties to verify (delta review from 693c685c)

1. **No unissued correlation reaches the render event.**
   - Run N19, then apply W1 alone and confirm N19 fails.
   - Confirm N4 and N7 still carry the strict ids.
   - Enumerate the loop's `final` calls (`agentic_loop.py:2581-2588`: `strict=False, correlation=None`; `:2982-2984`: `strict=strict, correlation=trace_correlation`). Confirm the only place a non-strict call gets a correlation is the exception branch (`:2906-2929`).
2. **A withheld result keeps `source_chars`.**
   - Run N4, then apply W3 and confirm N4 fails.
   - `kept` now matches `with_result_delivery`'s fields minus the delivery (`tool_call.py:902-906`).
   - `build_tool_trace_payload` reports `source_chars` for all four variants.
3. **No shared contract changes.**
   - The payload keeps its eight keys and every strict value.
   - `rg SECRET_MASKED src` finds producers and declarations only.
   - No test reads a non-strict render `operation_id` other than the null-valued cases.
4. **Contract corrections RC3 and RC4 match the measured counts.** Instrument `mask_text` and check: at most 2 calls for an unarmed call; for an armed delivered call, 3 with no hit and 4 when a non-strict event is emitted; 3 at most under strict.
5. **R11 and R12 reach statements are true.**
   - The strict projection is at `agentic_loop.py:2985-2990`.
   - `AGENTIC_TOOL_CALL_COMPLETED` is OPERATIONAL (`event_persistence.py:94`, `:28-29`).
   - The ordinary trace ignores `effect_correlations`: only the strict branch reads them (`agentic_loop.py:526-543`).
6. **Scope.** The delta touches only `render_masking.py`, S3's test file, S3's `PROGRESS.md` line, `DECISIONS.md:1676`, the ledger pair and the contract. `agentic_loop.py` is unchanged; it keeps 13 methods and the same constructor keywords.
7. **Execute** 18.6's focused set: S3's file gives 24 passed.

### 18.9 Verified Against Codebase (2026-11-22, `ob11s3q` at `693c685c`)

```
git diff --stat 1a1a4782 693c685c            S2's files only (executor.py, S2 test, S2 contract, trackers, ledger pair)
read render_masking.py:1-211                 RQ6 SEARCH 149-158, RQ7 SEARCH 186-192, each once
read test_ad1337_render_seam.py:20-399, 715-806   RQ1 24-29, RQ2 35-36, RQ3 126-129, RQ4 307-331, RQ5 803-806
read agentic_loop.py:2673, 2782-2816, 2900-3018   strict flag; strict-only correlation; exception branch; projection
read agentic_loop.py:408-419, 580-627        build_tool_trace_payload signature; output_chars/source_chars (BF-760)
read tool_call.py:680-693, 738-748, 876-911  source_chars field; kw_only extensions; with_result_delivery copies it
read effect_adapters.py:372-441, 710-711     _reason [a-z0-9_]{1,64}; project_refusal returns reason_code
read effect_broker.py:596-634, 696-737       strict exception correlations are broker-set or identity-checked
read effect_types.py:17, 66-71               EffectOutcome Literal; EffectCorrelation(op, at, outcome, reason)
read secret_masking.py:55                    MASKING_FAILED_TEXT = "tool output withheld: secret masking failed"
read test_ad1240_tool_result_delivery.py:162-181, 1876  _RawTool tool_id fixture_result; _turn call id; _last_result
read test_bf760_trace_records_the_tools_length.py:33-60  ToolCallRequest(name=, arguments=, id=) call shape
read PROGRESS.md:3; DECISIONS.md:1674-1681   RQ8-RQ11 SEARCH text, each once (rg -o)
git show 5d8a5eb4:...agentic_loop.py | grep effect_operation_id   2785, 2905, 2914, **effect_correlation 2994 (R12 on main)
```

**Absence Verified (2026-11-22):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| Nothing in `src` reads `SECRET_MASKED` | `rg SECRET_MASKED src/probos` | `events.py:329`, `event_persistence.py:72`, producers `executor.py:1616` and `render_masking.py:204`, comments | yes |
| No test reads a non-strict render id | `rg operation_id tests/test_ad1337*.py tests/test_ad1195*.py` | render: N3 and N5 (None), N4 and N7 (strict); the rest are S2 producer or AD-1195 permit cases | yes |
| The ordinary trace ignores `effect_correlations` | `rg "effect_correlations\|effect_operation_id" agentic_loop.py` | 416 (parameter), 532 (strict branch), 2796, 2916, 2925 | yes |
| No other S3 text states a call count | `rg "two passes\|at most two\|22 ms\|both passes"` over the contract, `swe_harness/*.py`, `PROGRESS.md` and `DECISIONS.md` | contract 84, 143, 147, 869, 924; `render_masking.py:12`, `:74`; tracker hits are S1/S2 or other ADs | yes; 143, 869, 924, 12 and 74 describe stages |
| The `RQ` and `W` labels are free | `rg "\b(RQ\|RS\|RW\|C)\d+\b"`, `rg "\b[VW]\d+\b"` in the contract | `C10`-`C12` mentioned in 17.9 only | yes |

**Prior art:** skipped. This repairs S3's own defects and has no outside analogue.

### 18.10 The orchestrator's first-hand checks

The 11 operations of this section (RQ1 to RQ11) were applied to a scratch worktree detached at `693c685c` (the branch head, which the Builder starts from; S3's files there equal `1a1a4782`) by `audit\contract_tools.py apply --prefix 18.` (ASCII only), and every check below was run before the Builder started. Each test run went through `run_pytest_homeguard.ps1` (HOME and USERPROFILE redirected to an empty directory; the listing after the run was empty every time), serial unless a worker count is named.

| R | Result |
|---|---|
| R1 | All 11 operations are found by `contract_tools.py list --prefix 18.`; every SEARCH occurs exactly once on `693c685c` (the code, the test and the tracker pairs alike; dry run). Four files change by +87 -14 lines: `render_masking.py` 11 and 4, the test file 74 and 8, `PROGRESS.md` and `DECISIONS.md` 1 and 1 each. Blobs after the operations: `render_masking.py` `1dcc62cd29964d3b4aded3fd1b8a28922fc07cad` (218 lines, as 18.6 predicts), `tests/test_ad1337_render_seam.py` `1c4302db2113072572a2e4b7bbe46537227b1a7f`, `PROGRESS.md` `9ab714f579218026c8a2857e1f014093cb734587`, `DECISIONS.md` `f2ba37d2e7a045d077018bda031e27757fdcf991`. |
| R2 | **The tests alone** (RQ1 to RQ5 applied, the code pairs not): **2 failed, 22 passed** in 51 s, exactly the prediction of 18.6: N4 fails at `held.source_chars` (`None != 20005`, index 3), and N19 at its first assertion (`('op-tok-S3r8Wm2Qz6Lp4Nx9', 'at-tok-S3r8Wm2Qz6Lp4Nx9') != (None, None)`). |
| R3 | **All pairs:** `tests/test_ad1337_render_seam.py` **24 passed** in 46 s; the same file under `-W error`: **24 passed** in 54 s (N19 and N4 leave no pending task and raise no warning). |
| R4 | **The findings' reproduction, before and after** (`probe_b11s3r2.py`, which imports the test file's own harness; evidence `evidence-b11s3r2-findings.txt` on `1a1a4782` and `evidence-b11s3r2-findings-after.txt` on the scratch tree). F1: before, the render event of a non-strict call carried `operation_id` `op-<token>` and `attempt_id` `at-<token>` from a tool's exception (the model saw only the masked text); after, both are `null` and the token is in neither the payload nor the model's requests. F2: before, a withheld delivered result had `source_chars` 20005 -> `None` and the trace payload read `{'output_chars': 43, 'output_truncated': False}`; after, 20005 survives and the payload carries `'source_chars': 20005`. F3 is unchanged on purpose (the model reads `tool_completed`; recorded as R11). F4: three `mask_text` calls for a clean frame and four for a frame that holds a value, before and after (documentation only). |
| R5 | **RC4's counts** (`probe_b11s3r2_counts.py`, a counting wrapper on `SecretMasker.mask_text`; evidence `evidence-b11s3r2-counts.txt`): an unarmed call 1 (no hit) or 2 (a hit that emits a non-strict event); an armed delivered call 3 with a clean frame and no hit, 4 when the frame holds a value or the text hit emits a non-strict event; 3 under the strict profile in both hit cases. RC4's sentence holds. |
| R6 | **The focused gate of 18.6** (the three AD-1337 test files, `test_bf760_trace_records_the_tools_length`, `test_ad1240_tool_result_delivery`, `test_ad1152_agentic_correlation`, `test_ad1195_durable_producers`, `test_bf965_unoffered_tool_refusal`, `test_ad1224_durable_tool_start` and `test_ad1324_srp_layout`: 10 files) with 3 workers: **1033 passed, 2 skipped** (the two skips are AD-1240's POSIX-only symlink cases) in 153 s. |
| R7 | **Static checks.** `check_architecture_principles.py --check` passes (srp-size 92, layer-import 0, db-connect 30, unowned-task 13); `render_masking.py` is 218 lines; `agentic_loop.py` is unchanged (13 methods, the same constructor keywords); `rg -n "ensure_future"` over the three AD-1337 test files and `render_masking.py` finds nothing; the added lines hold no non-ASCII character. |
| R8 | **The campaign of record** (`audit\mutants_gen.py`, `rows_ad1337s3r2.py`: the 55 rows of section 17's campaign with X6 and X7 restated on the `trusted` lines, plus W1 to W5: 60 rows; 49 baseline cases, S3's 24 and S2's 25, all passing) runs on three scratch trees that hold this section's operations, 20 rows each, while this section is committed; the `lf-sha256` of `render_masking.py` is `bea1bd57590f15f4e0d4ddbd791e1e1e8f0a46407f955e47f686a274e74c0385` and of the test file `f42831404beb20d2777191da03414dcda00c0acdfc37caad26ab76aea1cc872f`. Its result (killed, differed, survived, invalid; E1 is expected to survive) is recorded in the PR description and in `evidence-b11s3r2-camp1.txt` to `-camp3.txt`; any other survivor reopens 18.7. |

**What the orchestrator changed in the Architect's section 18:** nothing in the pairs, the test, the rows or the corrections.

**What these checks do not show.**
- A live vessel: nothing here ran against `%LOCALAPPDATA%\ProbOS\data`.
- The wider consumer set (the full gate) and `PROBOS_EMBEDDINGS=local`: the committed head gets the 46-file consolidated set in both embedding modes after M6.
- F3: the strict projection is unchanged, so the strict-profile result of a failed render pass is still the broker's reason code (R11).
