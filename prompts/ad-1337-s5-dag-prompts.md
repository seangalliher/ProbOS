# AD-1337 S5 (#1560): the prompts a decomposed DAG sends a model are masked

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-22

**Status:** draft. Batch 2 is S4 + S5: one PR (`Refs #1560`), one broad gate. S5 is the last slice; #1560 can close after the merge. Decision: S3 D8 and section 6 (contract `prompts/ad-1337-s3-render-seam.md`), corrected here in D1 (the per-part cut) and D4 (the Tier 2 arbitration prompt, a second DAG prompt S3 did not name). No Captain condition.

**Base:** `8abbf58d9a77` (the head after S4). Line numbers are those of `108a7fff` (`5d8a5eb4` plus batch 1; the tip that merged, `a86a2895`, has the same `src`), before S4's pairs; `33826d30`, which section 0 and the notes below name, differs from it only in `finalize.py` (six lines added at 735-748) and `tests/test_ad1337_executor_seam.py` (nine lines added before line 498), whose references are given for `108a7fff`. From batch 1, S5 uses `SecretMasker.mask_text`, `MASKING_FAILED_TEXT`, `secret_forms`, `secret_masker_of` (S1/S3) and `_wire_secret_masker` (S2). From S4 it uses nothing; it assumes S4's pairs as drafted:
- A1 inserts above `class SecretHandle:` and ends with that line and its docstring line;
- TR1 puts S4's entry under `# ProbOS Progress`;
- TR2 inserts S4's bullets above `- *Related.* BF-890 ...` and keeps that line;
- TR3 ends the research row with `A decomposed DAG's reflect prompt (S5) follows. |`.
If S4's repairs change TR3's sentence, KT3's SEARCH fails loudly: anchor on S4's final sentence.

**Line endings:** every edited file is `i/lf w/crlf` (`git ls-files --eol`). The SEARCH blocks are LF; match and write each file with its own endings. The new test file is LF and ASCII only.

**Milestones** (one Builder delegation each; the Builder applies the pairs and runs no test; no `AD-` or `BF-` token in a commit subject):

| M | Content | Tier | Review |
|---|---|---|---|
| M1 | 7.1 (new tests) first, then K1 to K14 (7.2 to 7.6) | HIGH, security control | One full review by the GPT Diff Reviewer with section 14's properties. The mutation campaign of record (section 10) stands in for a second reviewer. A Critical or High in round 1 gets a full re-review. |
| M2 | KT1 to KT3, then the ledger (7.7 to 7.10) | LOW | Delta |

- Commit subjects:
  - M1: `Mask the prompts a decomposed task graph sends a model`
  - M2: `Record the task graph prompts in the status, decisions and research entries`
- About 25 Builder tool calls for M1 and 8 for M2.

## 0. Premises (on `33826d30`)

| P | Premise | Evidence |
|---|---|---|
| P1 | `reflect` joins every node's summary into one prompt, cuts it at `REFLECT_PAYLOAD_BUDGET` (12000), logs it at DEBUG and sends it (`tier="standard"`) | `decomposer.py:456-512` |
| P2 | `_summarize_node_result` cuts 8 parts before the prompt exists (`:699`, `:714`, `:716`, `:726`, `:732`, `:747`, `:754`, `:771`); grounded context, errors and paths are not cut (`:739`, `:750`, `:758`, `:769`) | `decomposer.py:691-771` |
| P3 | Node results come from mesh intents, not tool calls: a shell agent returns at most 64 KiB per stream; the MCP mesh intent calls the bridge directly | `shell_command.py:69`, `:330-345`; `test_ad1337_render_seam.py:671-672` |
| P4 | One decomposer, built in `ProbOSRuntime.__init__` before the masker exists, never replaced; the masker is built at `finalize.py:5898` | `runtime.py:1059`; `finalize.py:715-748`, `:5896-5898` |
| P5 | `IntentDecomposer` has 15 methods (the cap) and spans 402 lines; `EscalationManager` spans exactly 500 lines (the cap); neither is in the baseline | `decomposer.py:247-648`; `escalation.py:51-550`; `check_architecture_principles.py:187-188` |
| P6 | Tier 2 arbitration sends `node.params`, a node's error text and the context to a model, for every escalation that reaches it (a consensus rejection skips only Tier 1); `EscalationManager` holds the runtime | `escalation.py:135-171`, `:271-290`, `:68`; `runtime.py:1073-1077`; `decomposer.py:1094`, `:1181` |
| P7 | The callers treat `""` as the timeout branch does: the runtime skips `_verify_response`; replies fall back to the node results; the shell panels show no reflection line | `runtime.py:6130-6153`; `renderer.py:465-478`; `commands_plan.py:164-178`; `response_formatter.py:31-50`; `panels.py:752-755` |
| P8 | `secret_masker_of` keeps only a real `SecretMasker`; `mask_text` raises only `TypeError` for a non-`str` and logs a failure as its type name | `secret_masking.py:198-210`, `:362-372` |
| P9 | Neither class can emit: the escalation is "event-silent"; the decomposer holds no emitter | `escalation.py:52-56`; `decomposer.py:254-277` |

## 1. Problem

S2 masks what a tool registry returns, and S3 masks what the agentic loop hands a model. A decomposed DAG's nodes run as mesh intents (P3), so their output never reaches either seam:
- `reflect` writes every node's output, errors and parameters into a model prompt and a DEBUG log (P1);
- the summariser cuts each part first (P2), so a value crossing a cut leaves a prefix that no later pass matches;
- Tier 2 arbitration sends a node's error text to a model (P6).

## 2. Overview

| Part | Change |
|---|---|
| `security/secret_masking.py` | `RouteTextMask(masker, *, route)`: call it to mask a text; `clip(text, limit)` masks then cuts; `settle()` logs once and says whether to send. Placed above `class SecretHandle`. |
| `cognitive/decomposer.py` | `secret_masker` attribute (None); `reflect` masks each part through `_summarize_node_result(clip=)` and then the whole prompt, before the cap, the log and the model; a failure returns `""` |
| `startup/finalize.py` | `runtime.decomposer.secret_masker = secret_masker` after `_wire_secret_masker` |
| `consensus/escalation.py` | `_arbitration_prompt(runtime, node, error, context)`, masked; on a failure Tier 2 sends nothing |
| `tests/test_ad1337_render_seam.py` | N15's `submit_mcp_invoke_with_consensus` row reason names S5 |

**Heavier designs rejected:**
- S3's `SecretMaskerSlot`: importing `render_masking` would bring the SWE tool layer (`swe_harness/tools.py:24-69`) into the decomposer's imports for one type check.
- A setter or property: `IntentDecomposer` is at its 15-method cap (P5).
- A constructor keyword: the decomposer is built before the masker exists (P4).
- A `SECRET_MASKED` event: neither class holds an emitter (P9); one would need another slot and an AD-1195 producer row (R20).
- Masking the decompose prompt: it is the Captain's own request and conversation; masking would rewrite a value the Captain typed on purpose (R19).
- A thread: D7.

## 3. Consumers checked

| Changed | Consumer | Result |
|---|---|---|
| `_summarize_node_result` gains keyword-only `clip` (default: today's cut) | `test_ad152_regressions.py:404-445`, `test_decomposer.py:1488-1510` (one-argument calls) | Unchanged |
| `IntentDecomposer.secret_masker` (None) | 30 constructions in 11 test files; `test_public_apis.py:330-336`; no signature golden (Absence) | Unchanged: nothing is masked |
| `reflect` without a masker | `test_decomposer.py:331-383` (the cap), `test_escalation.py:885-909` | Byte-identical (Z1) |
| finalize's new assignment | `finalize_startup` tests run on `MagicMock` runtimes (`test_new_crew_auto_welcome.py:186`, `test_ad641d_deliberation.py:276`, `test_bf235_stale_identity_cache.py:93`, `test_ad1270a_startup_receipts.py:418`); S2's census matches only the target `secret_masker` (`test_ad1337_executor_seam.py:612-616`) | Unchanged |
| `_tier2_arbitrate` | `test_escalation.py` (`MagicMock` or bare runtimes) | `secret_masker_of` gives None: today's prompt |
| `EscalationManager` 500 -> 499 lines; `IntentDecomposer` still 15 methods, about 410 lines | `check_architecture_principles.py:187-188` | Under both caps |
| `consensus` imports `probos.security` | `test_layer_boundaries.py:156-169` (an unmapped package is allowed) | No exception needed |
| N15 row reason | N15 compares keys only (`test_ad1337_render_seam.py:704`) | Text only |
| Reflect returns `""` on a failure | P7 | As on a timeout |

**Not checked:** a request served before `finalize_startup` assigns the masker (it would also find no runtime `ToolExecutor`, `finalize.py:5906`); a live run.

## 4. Decisions

- **D1 (what is masked and where, (a)).** In `reflect`, every part is masked before its cut (`clip`), then the whole joined prompt once, before the cap, the DEBUG log and `LLMRequest`. The whole-prompt pass covers the parts that are not cut (P2), the request and `node.params`, and a value spanning the 12000 cap. A placeholder cut by a slice (`<secr`) shows nothing. **Correction to S3 section 6:** S3 said the whole prompt; the per-part cut (P2) makes that insufficient.
- **D2 (reaching the masker, (b)).**
  - `self.secret_masker: SecretMasker | None = None` in `__init__`, read through `secret_masker_of(self)`, so a non-masker (a `MagicMock`) masks nothing, as S3's executor filter does.
  - finalize assigns it from `_wire_secret_masker`'s return value, the masker the runtime's `ToolExecutor` gets.
  - A decomposer with no runtime (every test, the benchmark) keeps None: byte-identical prompts.
  - The arbitration reads `secret_masker_of(self.runtime)` at call time.
- **D3 (failure, (c)).**
  - After the first failed pass, later passes return `MASKING_FAILED_TEXT` without calling the masker, so the call logs S1's one ERROR (the type name) and `settle` one WARNING.
  - `reflect` then returns `""` before the cap, the log and the model; the callers show the results alone (P7).
  - Tier 2 returns an unresolved `EscalationResult` with reason `MASKING_FAILED_TEXT`, and the cascade goes on to Tier 3, the Captain.
- **D4 (logs and the line, (d)).**

  | Site | Model-facing? | Disposition |
  |---|---|---|
  | `reflect` prompt and its DEBUG log `:491` | yes | masked (S5) |
  | Tier 2 arbitration `escalation.py:275-290` | yes | masked (S5) |
  | decompose prompt `:409`, its conversation history `:383-389` (client-supplied, `routers/chat.py:906`, `channels/base.py:387`) | yes, Captain's input | not masked (R19) |
  | working memory `detail` (`runtime.py:6117-6122`) | no: `to_text` renders intent and success only (`working_memory.py:73-79`) | none |
  | episode outcomes (`dream_adapter.py:370-387`) | no: intent, success, status | none |
  | `panels.render_dag_result`, `response_formatter`, channel replies, `/plan` | the Captain's view | out of scope (Do Not Build) |
  | `decomposer.py:1087`, `escalation.py:257`, `:385` (logs); `ESCALATION_START` `error` (`decomposer.py:1090-1093`, `:1177-1180`) | logs and an event | R21 (the classes of R4 and R14) |

- **D5 (event, (e)).** None. One WARNING per prompt, labels only (`AD-1337: route=dag_reflect masked names=[...]`; route `dag_arbitration` for Tier 2). No id is involved. AD-1195 is unchanged.
- **D6 (census, (f)).** Z8 pins every model request in `decomposer.py` and `escalation.py`, each with a reason, plus:
  - the decomposer's one construction and the finalize assignment;
  - the three `reflect` callers;
  - the order mask -> settle -> cap -> log -> request;
  - no direct slice left in `_summarize_node_result`.
  N15 keeps failing on a new unlisted route; K14 changes only its row's reason.
- **D7 (cost).** Inline, as S2 D2. Each pass is S1's: 0.026 ms for a short text, 22 ms for 1 MiB with 50 values (DECISIONS, AD-1337 *Producer seam*). `reflect` makes one pass per part (for a shell node, at most 64 KiB per stream) plus one over the joined prompt, once per reflected request, which already waited on a decomposition call.
- **D8 (trackers, (h)).** PROGRESS above S4's entry; DECISIONS bullets above `*Related.*` (after S4's) with the residual range brought up to date; the research row says #1560 is complete; the ledger is regenerated last.

## 5. Tests: new file `tests/test_ad1337_reflect_route.py` (8 cases, 10 items)

| Z | Case |
|---|---|
| Z1 | No masker, or a non-masker: today's reflect prompt, byte for byte (golden), and the model's synthesis (x2) |
| Z2 | Raw, base64 and URL forms in stdout, stderr, a doc snippet and a result reach the model as `<secret:github>`; the DEBUG log holds the masked prompt; one WARNING; no form in any log record |
| Z3 | A value the 500-character cut would split is masked whole; without a masker the cut leaves its prefix |
| Z4 | A value the 12000 cap would split is masked whole; without a masker the cap leaves its prefix |
| Z5 | A failed pass: `""`, no model call, one ERROR, one WARNING, no DEBUG prompt, no form in logs |
| Z6 | The arbitration prompt is masked; without a masker it is today's (golden) (x2) |
| Z7 | A failed pass sends no arbitration prompt; the cascade reaches Tier 3 |
| Z8 | Census (D6) |

- **On `8abbf58d9a77`:** 3 passed (Z1 x2, Z6 "no masker": the goldens are today's), 7 failed.
- **After M1:** 10 passed; `tests/test_ad1337_render_seam.py` still 24 passed.

## 6. What S5 leaves

Nothing. #1560's slices S1 to S5 are built; follow-ups are #1820 ad-1337 R1 to R27 (R10 and R15 are not used).

## 7. The contract

### 7.1 New file `tests/test_ad1337_reflect_route.py` (M1, written first)

```python
"""AD-1337 S5 (#1560): the prompts a decomposed DAG sends a model are masked.

A DAG's nodes run as mesh intents (a shell agent's stdout, a doc snippet, another agent's result), not tool calls, so
neither the producer seam (S2) nor the render seam (S3) sees what they return. Two prompts carry it to a model:
``IntentDecomposer.reflect`` (every node's result) and the escalation's Tier 2 arbitration (a node's error text).

Proves, with a real IntentDecomposer and EscalationManager, the MockLLMClient (which records every request) and S1's
real masker over a store holding the value as ``github``:
- Z1: a decomposer with no masker, or with something that is no masker, sends today's prompt (x2);
- Z2: raw, base64 and URL-encoded forms in a node's stdout, stderr, doc snippet and result are replaced before the
  model sees the prompt; the DEBUG log holds the masked prompt; one WARNING with labels;
- Z3, Z4: a value that _summarize_node_result's 500-character cut, or the 12,000-character cap, would split is
  replaced whole (without a masker the cut leaves a prefix of it);
- Z5: a failed pass makes no model call and returns "", with one ERROR (the type name) and one WARNING;
- Z6: the arbitration prompt is masked, and without a masker it is today's (x2);
- Z7: a failed pass sends no arbitration prompt, and the cascade goes on to Tier 3;
- Z8: census: every model request in the two DAG files, the decomposer's one construction and its wiring, the reflect
  callers, and no cut in _summarize_node_result that bypasses its clip.
Z2, Z5, Z6 and Z7 assert that no form of the value reaches a log record (DEBUG).
Does not prove: a live shell agent through the mesh, a live run.
"""

from __future__ import annotations

import ast
import base64
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest

from probos.cognitive.decomposer import IntentDecomposer
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.consensus.escalation import EscalationManager
from probos.security import secret_masking
from probos.security.secret_masking import secret_forms
from probos.types import EscalationTier, IntentResult, TaskDAG, TaskNode
from tests.fixtures import ad1343_seam_census as seam_census
from tests.test_ad1337_render_seam import _raise_values, _real_masker
from tests.test_ad1337_secret_masking import _no_builtin_env  # noqa: F401 -- _no_builtin_env is autouse

VALUE = "dgv-S5q8/Hw3+Kz7=Rt2"
B64 = base64.b64encode(VALUE.encode("utf-8")).decode("ascii")
URL = quote(VALUE, safe="")
PLACEHOLDER = "<secret:github>"
REQUEST = "show the env"
TAIL = "\n\n[... results truncated ...]"
BUDGET = IntentDecomposer.REFLECT_PAYLOAD_BUDGET
GOLDEN = (
    "Original request: show the env\n"
    "\n"
    "Agent results:\n"
    "- [completed] run_command({'command': 'cat .env'}): success=True; output=API_TOKEN=" + VALUE
)
_DECOMPOSER = "src/probos/cognitive/decomposer.py"
_ESCALATION = "src/probos/consensus/escalation.py"


def _clean(text: str) -> None:
    """No form of VALUE (raw, escaped, URL- or base64-encoded) appears in ``text``."""
    assert not [form for form in secret_forms(VALUE) if form in text]


def _decomposer(masker: Any = None) -> tuple[IntentDecomposer, MockLLMClient]:
    llm = MockLLMClient()
    decomposer = IntentDecomposer(llm_client=llm, working_memory=WorkingMemoryManager())
    if masker is not None:
        decomposer.secret_masker = masker  # as finalize assigns it
    return decomposer, llm


def _agent(data: Any) -> dict[str, Any]:
    """One node's result as DAGExecutor holds it: the agents' IntentResults under ``results``."""
    result = IntentResult(intent_id="i1", agent_id="a1", success=True, result=data)
    return {"success": True, "result_count": 1, "results": [result]}


def _shell(stdout: str, stderr: str = "") -> dict[str, Any]:
    """A run_command node's result: the shell agent's data (shell_command.py:337-345)."""
    return _agent({"stdout": stdout, "stderr": stderr, "exit_code": 0, "command": "cat .env"})


def _execution(*node_results: Any, status: str = "completed") -> dict[str, Any]:
    """One run_command node per result, as DAGExecutor.execute returns them."""
    nodes = [
        TaskNode(id=f"t{index}", intent="run_command", params={"command": "cat .env"}, status=status)
        for index in range(len(node_results))
    ]
    return {"dag": TaskDAG(nodes=nodes), "results": {f"t{index}": r for index, r in enumerate(node_results)}}


def _routed(caplog: pytest.LogCaptureFixture, route: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if f"route={route} " in record.getMessage()]


# -- Z1 to Z5: the reflect prompt -------------------------------------------------------------------------------------


@pytest.mark.parametrize("masker", [None, MagicMock()], ids=["no masker", "not a masker"])
async def test_a_decomposer_without_a_masker_sends_todays_reflect_prompt(masker: Any) -> None:
    decomposer, llm = _decomposer(masker)

    reflection = await decomposer.reflect(REQUEST, _execution(_shell(f"API_TOKEN={VALUE}\n")))

    assert llm.last_request.prompt == GOLDEN
    assert reflection == "Based on the agent results: The operation completed successfully."


async def test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
    execution = _execution(
        _shell(f"API_TOKEN={VALUE}\n", stderr=f"warning: {VALUE} is set"),
        _agent({"hits": 1, "doc_snippets": [{"path": "notes.md", "source": f"key: {B64}"}]}),
        _agent({"url": f"https://s5.example/cb?k={URL}"}),
    )

    reflection = await decomposer.reflect(REQUEST, execution)

    prompt = llm.last_request.prompt
    assert f"output=API_TOKEN={PLACEHOLDER} (stderr: warning: {PLACEHOLDER} is set)" in prompt
    assert f"[doc: notes.md]\nkey: {PLACEHOLDER}" in prompt
    assert f"?k={PLACEHOLDER}'" in prompt
    _clean(prompt)
    assert reflection  # the model's synthesis, as without a masker
    [logged] = [record for record in caplog.records if record.getMessage().startswith("Reflect prompt")]
    assert PLACEHOLDER in logged.getMessage()
    [warning] = _routed(caplog, "dag_reflect")
    assert (warning.levelno, warning.getMessage()) == (
        logging.WARNING, "AD-1337: route=dag_reflect masked names=['github']",
    )
    _clean(caplog.text)


async def test_a_value_the_part_cut_would_split_is_masked_whole(tmp_path: Path) -> None:
    execution = _execution(_shell("x" * 495 + VALUE))
    plain, plain_llm = _decomposer()
    masked, llm = _decomposer(_real_masker(tmp_path, github=VALUE))

    await plain.reflect(REQUEST, execution)
    await masked.reflect(REQUEST, execution)

    assert plain_llm.last_request.prompt.endswith("x" * 495 + VALUE[:5])  # today: the cut leaves the value's prefix
    assert llm.last_request.prompt.endswith("x" * 495 + PLACEHOLDER[:5])
    assert VALUE[:5] not in llm.last_request.prompt


async def test_a_value_the_payload_cap_would_split_is_masked_whole(tmp_path: Path) -> None:
    head = (
        "Original request: " + REQUEST + "\n\nAgent results:\n"
        "- [failed] run_command({'command': 'cat .env'}): error="
    )
    filler = "e" * (BUDGET - 5 - len(head))
    execution = _execution({"error": filler + VALUE}, status="failed")
    plain, plain_llm = _decomposer()
    masked, llm = _decomposer(_real_masker(tmp_path, github=VALUE))

    await plain.reflect(REQUEST, execution)
    await masked.reflect(REQUEST, execution)

    assert plain_llm.last_request.prompt == head + filler + VALUE[:5] + TAIL  # today: the cap leaves the prefix
    assert llm.last_request.prompt == head + filler + PLACEHOLDER[:5] + TAIL


async def test_a_failed_pass_makes_no_reflect_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    decomposer, llm = _decomposer(_real_masker(tmp_path, github=VALUE))
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)

    reflection = await decomposer.reflect(
        REQUEST, _execution(_shell(f"API_TOKEN={VALUE}", stderr=f"warning: {VALUE}")),
    )

    assert reflection == ""
    assert llm.call_count == 0
    errors = [r for r in caplog.records if r.name == secret_masking.__name__ and r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["AD-1337: secret masking failed (RuntimeError); the output is withheld"]
    [warning] = _routed(caplog, "dag_reflect")
    assert warning.levelno == logging.WARNING and "failed" in warning.getMessage()
    assert not [r for r in caplog.records if r.getMessage().startswith("Reflect prompt")]
    _clean(caplog.text)


# -- Z6 and Z7: the Tier 2 arbitration prompt ------------------------------------------------------------------------


def _node() -> TaskNode:
    return TaskNode(id="t1", intent="run_command", params={"command": "cat .env"}, use_consensus=True)


def _context() -> dict[str, Any]:
    """What DAGExecutor._handle_rejection hands the escalation (decomposer.py:1186-1190)."""
    return {"intent": "run_command", "params": {"command": "cat .env"}, "category": "consensus"}


def _arbitration(shown: str) -> str:
    """The Tier 2 prompt (escalation.py:275-280) for _node() and _context()."""
    return (
        "Intent: run_command\n"
        'Params: {"command": "cat .env"}\n'
        f"Error: exit 1: API_TOKEN={shown}\n"
        'Context: {"intent": "run_command", "params": {"command": "cat .env"}, "category": "consensus"}\n'
    )


@pytest.mark.parametrize("masked", [True, False], ids=["masked", "no masker"])
async def test_the_arbitration_prompt_is_masked(masked: bool, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    masker = _real_masker(tmp_path, github=VALUE) if masked else None
    llm = MockLLMClient()
    manager = EscalationManager(runtime=SimpleNamespace(secret_masker=masker), llm_client=llm)

    result = await manager.escalate(_node(), f"exit 1: API_TOKEN={VALUE}", _context())

    assert llm.last_request.prompt == _arbitration(PLACEHOLDER if masked else VALUE)
    assert EscalationTier.ARBITRATION in result.tiers_attempted
    assert len(_routed(caplog, "dag_arbitration")) == (1 if masked else 0)
    if masked:
        _clean(caplog.text)


async def test_a_failed_pass_sends_no_arbitration_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    masker = _real_masker(tmp_path, github=VALUE)
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise_values)
    llm = MockLLMClient()
    manager = EscalationManager(runtime=SimpleNamespace(secret_masker=masker), llm_client=llm)

    result = await manager.escalate(_node(), f"exit 1: API_TOKEN={VALUE}", _context())

    assert llm.call_count == 0
    assert result.tier == EscalationTier.USER and EscalationTier.ARBITRATION in result.tiers_attempted
    [warning] = _routed(caplog, "dag_arbitration")
    assert warning.levelno == logging.WARNING and "failed" in warning.getMessage()
    _clean(caplog.text)


# -- Z8: the census --------------------------------------------------------------------------------------------------

_DAG_FILES = frozenset({_DECOMPOSER, _ESCALATION})
_PINNED = frozenset({"LLMRequest", "reflect", "IntentDecomposer", "_summarize_node_result", "_arbitration_prompt"})

DAG_CALLS: dict[tuple[str, str, str, str], str] = {
    (_DECOMPOSER, "IntentDecomposer.decompose", "LLMRequest", ""):
        "the decompose prompt: the Captain's request and conversation, not node results (#1820 ad-1337 R19)",
    (_DECOMPOSER, "IntentDecomposer.reflect", "LLMRequest", ""): "masked by RouteTextMask (asserted below; Z2 to Z5)",
    (_DECOMPOSER, "IntentDecomposer.reflect", "_summarize_node_result", ""): "every part cut by the mask's clip",
    (_ESCALATION, "EscalationManager._tier2_arbitrate", "LLMRequest", ""): "built from _arbitration_prompt",
    (_ESCALATION, "EscalationManager._tier2_arbitrate", "_arbitration_prompt", ""): "masked by RouteTextMask (Z6, Z7)",
    ("src/probos/runtime.py", "ProbOSRuntime.__init__", "IntentDecomposer", ""):
        "the one decomposer; finalize assigns its masker (asserted below)",
    ("src/probos/runtime.py", "ProbOSRuntime._execute_dag", "reflect", "self.decomposer"): "the runtime's decomposer",
    ("src/probos/experience/renderer.py", "ExecutionRenderer.process_with_feedback", "reflect",
     "self.runtime.decomposer"): "the runtime's decomposer",
    ("src/probos/experience/commands/commands_plan.py", "cmd_approve", "reflect", "runtime.decomposer"):
        "the runtime's decomposer",
}


class _DagCalls(seam_census.Visitor):
    """AD-1343's scope-tracking census visitor, recording each call this census pins (a model request only in the two
    DAG files)."""

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in _PINNED and (name != "LLMRequest" or self._rel in _DAG_FILES):
            receiver = ast.unparse(func.value) if isinstance(func, ast.Attribute) else ""
            self.calls.append(seam_census.Call(self._rel, ".".join(self._scope) or "<module>", name, receiver, ""))
        self.generic_visit(node)


def test_every_dag_prompt_is_masked_or_has_a_recorded_reason() -> None:
    found: set[tuple[str, str, str, str]] = set()
    stores: list[str] = []
    for path in sorted(seam_census.PACKAGE.rglob("*.py")):
        rel = path.relative_to(seam_census.ROOT).as_posix()
        tree = ast.parse(path.read_bytes())
        visitor = _DagCalls(rel)
        visitor.visit(tree)
        found |= {(call.file, call.function, call.callee, call.receiver) for call in visitor.calls}
        stores += [
            rel for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Attribute) and target.attr == "decomposer"
        ]
    assert found == set(DAG_CALLS), sorted(found ^ set(DAG_CALLS))
    assert stores == ["src/probos/runtime.py"]  # runtime.decomposer is built once and never replaced

    reflect = seam_census.function(_DECOMPOSER, "IntentDecomposer.reflect")
    [mask] = [node for node in ast.walk(reflect) if seam_census.calls("RouteTextMask")(node)]
    assert ast.unparse(mask) == "RouteTextMask(secret_masker_of(self), route='dag_reflect')"
    [summary] = [node for node in ast.walk(reflect) if seam_census.calls("_summarize_node_result")(node)]
    assert [f"{k.arg}={ast.unparse(k.value)}" for k in summary.keywords] == ["clip=mask.clip"]
    [joined] = [
        node for node in ast.walk(reflect)
        if isinstance(node, ast.Assign) and ast.unparse(node.value).startswith("mask(")
    ]
    assert [ast.unparse(target) for target in joined.targets] == ["prompt_text"]
    settle = seam_census.first_line(reflect, seam_census.calls("settle"))
    cap = seam_census.first_line(
        reflect, lambda node: isinstance(node, ast.Attribute) and node.attr == "REFLECT_PAYLOAD_BUDGET",
    )
    logged = seam_census.first_line(reflect, seam_census.calls("debug"))
    request = seam_census.first_line(reflect, seam_census.calls("LLMRequest"))
    assert mask.lineno < summary.lineno < joined.lineno < settle < cap < logged < request
    summarize = seam_census.function(_DECOMPOSER, "_summarize_node_result")
    assert not [node for node in ast.walk(summarize) if isinstance(node, ast.Slice)]  # every cut goes through clip

    startup = seam_census.function("src/probos/startup/finalize.py", "finalize_startup")
    wired = sorted(
        (
            node for node in ast.walk(startup)
            if isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets] in (["secret_masker"], ["runtime.decomposer.secret_masker"])
        ),
        key=lambda node: node.lineno,
    )
    assert [ast.unparse(node) for node in wired] == [
        "secret_masker = _wire_secret_masker(runtime=runtime)", "runtime.decomposer.secret_masker = secret_masker",
    ]

    tier2 = seam_census.function(_ESCALATION, "EscalationManager._tier2_arbitrate")
    [built] = [node for node in ast.walk(tier2) if seam_census.calls("_arbitration_prompt")(node)]
    assert [ast.unparse(arg) for arg in built.args] == ["self.runtime", "node", "error", "context"]
    assert built.lineno < seam_census.first_line(tier2, seam_census.calls("LLMRequest"))
    arbitration = seam_census.function(_ESCALATION, "_arbitration_prompt")
    [route] = [node for node in ast.walk(arbitration) if seam_census.calls("RouteTextMask")(node)]
    assert ast.unparse(route) == "RouteTextMask(secret_masker_of(runtime), route='dag_arbitration')"
```

### 7.2 `src/probos/security/secret_masking.py` (M1)

**K1.** SEARCH (after S4's A1 it occurs once):
```
class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```
REPLACE:
```
class RouteTextMask:
    """AD-1337 S5: the masking passes over one model prompt that a route builds from text no seam masked.

    A decomposed DAG's node results come from mesh intents, not tool calls, so neither the producer nor the render seam
    sees them. Calling the mask masks a text; ``clip`` masks a part before cutting it, so a value the cut would split
    is still replaced whole. Without a masker both return their argument as it is, so the prompt is byte-identical.
    After a failed pass every later pass returns ``MASKING_FAILED_TEXT`` without masking again. ``settle`` logs once,
    with labels only, and says whether the prompt may be sent.
    """

    def __init__(self, masker: SecretMasker | None, *, route: str) -> None:
        self._masker = masker
        self._route = route
        self._names: set[str] = set()
        self._failed = False

    def __call__(self, text: str) -> str:
        """``text`` masked. With a masker, ``TypeError`` for anything but a ``str``, as ``mask_text``."""
        if self._masker is None:
            return text
        if self._failed:
            return MASKING_FAILED_TEXT
        outcome = self._masker.mask_text(text)
        self._names |= outcome.names
        self._failed = outcome.failed
        return outcome.text

    def clip(self, text: Any, limit: int) -> Any:
        """``text[:limit]``; with a masker, the first ``limit`` characters of ``str(text)`` after masking it whole."""
        if self._masker is None:
            return text[:limit]
        return self(text if isinstance(text, str) else str(text))[:limit]

    def settle(self) -> bool:
        """True when the prompt may be sent. One WARNING: the labels masked, or that a pass failed."""
        if self._failed:
            logger.warning("AD-1337: route=%s secret masking failed; nothing is sent to the model", self._route)
            return False
        if self._names:
            logger.warning("AD-1337: route=%s masked names=%s", self._route, sorted(self._names))
        return True


class SecretHandle:
    """One registration in a ``SecretRegistry``; ``release`` ends it and may be called again."""
```

### 7.3 `src/probos/cognitive/decomposer.py` (M1)

**K2.** SEARCH:
```
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.events import EventType
from probos.types import ConsensusOutcome, IntentDescriptor, LLMRequest, TaskDAG, TaskNode, Episode, AttentionEntry
```
REPLACE:
```
from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot
from probos.events import EventType
from probos.security.secret_masking import RouteTextMask, SecretMasker, secret_masker_of
from probos.types import ConsensusOutcome, IntentDescriptor, LLMRequest, TaskDAG, TaskNode, Episode, AttentionEntry
```

**K3.** SEARCH:
```
        self.last_raw_response: str = ""  # Last raw LLM response for debugging
        self.last_tier: str = ""  # Tier used for last LLM call
        self.last_model: str = ""  # Model used for last LLM call
```
REPLACE:
```
        self.last_raw_response: str = ""  # Last raw LLM response for debugging
        self.last_tier: str = ""  # Tier used for last LLM call
        self.last_model: str = ""  # Model used for last LLM call
        # AD-1337 S5: the runtime's secret masker for the reflect prompt. Not a constructor argument: the runtime builds
        # this decomposer before the masker exists, and finalize assigns it. None masks nothing.
        self.secret_masker: SecretMasker | None = None
```

**K4.** SEARCH:
```
        # Serialize results into a readable format
        result_parts = [f"Original request: {original_request}", "", "Agent results:"]
        dag = execution_result.get("dag")
        results = execution_result.get("results", {})

        if dag and hasattr(dag, "nodes"):
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                summary = _summarize_node_result(node_result)
                status = getattr(node, "status", "unknown")
                result_parts.append(
                    f"- [{status}] {node.intent}({node.params}): {summary}"
                )

        prompt_text = "\n".join(result_parts)
```
REPLACE:
```
        # Serialize results into a readable format
        # AD-1337 S5: the node results come from mesh intents, which neither masking seam sees. Each part is masked
        # before it is cut, so a value a cut would split is replaced whole, then the whole prompt before the cap, the
        # log and the model.
        mask = RouteTextMask(secret_masker_of(self), route="dag_reflect")
        result_parts = [f"Original request: {original_request}", "", "Agent results:"]
        dag = execution_result.get("dag")
        results = execution_result.get("results", {})

        if dag and hasattr(dag, "nodes"):
            for node in dag.nodes:
                node_result = results.get(node.id, {})
                summary = _summarize_node_result(node_result, clip=mask.clip)
                status = getattr(node, "status", "unknown")
                result_parts.append(
                    f"- [{status}] {node.intent}({node.params}): {summary}"
                )

        prompt_text = mask("\n".join(result_parts))
        if not mask.settle():
            return ""  # AD-1337 S5: fail closed, as on a timeout below; the callers show the results alone
```

**K5.** SEARCH:
```
def _summarize_node_result(node_result: Any) -> str:
    """Extract meaningful output from a node result for reflection.

    Pulls actual agent output (stdout, file content, etc.) from the
    nested IntentResult objects rather than dumping raw metadata.
    Deduplicates identical outputs from multiple agents.
    """
    if not isinstance(node_result, dict):
        return str(node_result)[:500]
```
REPLACE:
```
def _cut_part(text: Any, limit: int) -> Any:
    """``text[:limit]``: how ``_summarize_node_result`` cuts a part unless it is given a ``clip``."""
    return text[:limit]


def _summarize_node_result(node_result: Any, *, clip: Callable[[Any, int], Any] = _cut_part) -> str:
    """Extract meaningful output from a node result for reflection.

    Pulls actual agent output (stdout, file content, etc.) from the
    nested IntentResult objects rather than dumping raw metadata.
    Deduplicates identical outputs from multiple agents.

    AD-1337 S5: every part is cut by ``clip``. ``IntentDecomposer.reflect`` passes its ``RouteTextMask``'s, which
    masks a part before cutting it, so a known value the cut would split is still replaced whole.
    """
    if not isinstance(node_result, dict):
        return clip(str(node_result), 500)
```

**K6.** SEARCH:
```
                    stdout = data["stdout"].strip()
                    stderr = data.get("stderr", "").strip()
                    exit_code = data.get("exit_code")
                    entry = stdout[:500] if stdout else ""
                    if stderr:
                        entry += f" (stderr: {stderr[:200]})"
```
REPLACE:
```
                    stdout = data["stdout"].strip()
                    stderr = data.get("stderr", "").strip()
                    exit_code = data.get("exit_code")
                    entry = clip(stdout, 500) if stdout else ""
                    if stderr:
                        entry += f" (stderr: {clip(stderr, 200)})"
```

**K7.** SEARCH:
```
                    base = {k: v for k, v in data.items()
                            if k not in ("doc_snippets", "grounded_context")}
                    entry = str(base)[:400]
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    for snip in data["doc_snippets"]:
                        doc_entry = (
                            f"[doc: {snip.get('path', '?')}]\n"
                            f"{snip.get('source', '')[:1500]}"
                        )
```
REPLACE:
```
                    base = {k: v for k, v in data.items()
                            if k not in ("doc_snippets", "grounded_context")}
                    entry = clip(str(base), 400)
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    for snip in data["doc_snippets"]:
                        doc_entry = (
                            f"[doc: {snip.get('path', '?')}]\n"
                            f"{clip(snip.get('source', ''), 1500)}"
                        )
```

**K8.** SEARCH:
```
                    base = {k: v for k, v in data.items()
                            if k != "grounded_context"}
                    entry = str(base)[:500]
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    gc_entry = f"\nGROUNDED SYSTEM FACTS:\n{gc}"
                    if gc_entry not in seen_outputs:
                        seen_outputs.append(gc_entry)
                else:
                    entry = str(data)[:500]
```
REPLACE:
```
                    base = {k: v for k, v in data.items()
                            if k != "grounded_context"}
                    entry = clip(str(base), 500)
                    if entry not in seen_outputs:
                        seen_outputs.append(entry)
                    gc_entry = f"\nGROUNDED SYSTEM FACTS:\n{gc}"
                    if gc_entry not in seen_outputs:
                        seen_outputs.append(gc_entry)
                else:
                    entry = clip(str(data), 500)
```

**K9.** SEARCH:
```
    # Error result
    if "error" in node_result:
        return f"error={node_result['error']}"

    return str(node_result)[:500]
```
REPLACE:
```
    # Error result
    if "error" in node_result:
        return f"error={node_result['error']}"

    return clip(str(node_result), 500)
```

### 7.4 `src/probos/startup/finalize.py` (M1)

**K10.** SEARCH:
```
    # AD-1337 S2: the secret masker, after the credential store's path is set (AD-456 above), so its first read loads
    # the right store. Every tool executor masks with it: this one below, and each dispatch's from runtime.secret_masker.
    secret_masker = _wire_secret_masker(runtime=runtime)
```
REPLACE:
```
    # AD-1337 S2: the secret masker, after the credential store's path is set (AD-456 above), so its first read loads
    # the right store. Every tool executor masks with it: this one below, and each dispatch's from runtime.secret_masker.
    secret_masker = _wire_secret_masker(runtime=runtime)
    # AD-1337 S5: a decomposed DAG's reflect prompt is masked with it too; the runtime built the decomposer before it.
    runtime.decomposer.secret_masker = secret_masker
```

### 7.5 `src/probos/consensus/escalation.py` (M1)

**K11.** SEARCH:
```
from probos.types import (
    ConsensusOutcome,
    EscalationResult,
    EscalationTier,
    LLMRequest,
)
```
REPLACE:
```
from probos.security.secret_masking import MASKING_FAILED_TEXT, RouteTextMask, secret_masker_of
from probos.types import (
    ConsensusOutcome,
    EscalationResult,
    EscalationTier,
    LLMRequest,
)
```

**K12.** SEARCH:
```
class EscalationManager:
    """Orchestrates the 3-tier escalation cascade.
```
REPLACE:
```
def _arbitration_prompt(runtime: Any, node: Any, error: str, context: dict) -> str | None:
    """AD-1337 S5: the Tier 2 prompt, masked with the runtime's secret masker; None when the pass fails.

    ``error`` is a node's exception or rejection text, which no masking seam saw: a decomposed DAG's mesh intents never
    pass the tool executor. Without a masker the prompt is the same text as before. A module function because
    ``EscalationManager`` is at the 500-line class bound.
    """
    mask = RouteTextMask(secret_masker_of(runtime), route="dag_arbitration")
    prompt = mask(
        f"Intent: {node.intent}\n"
        f"Params: {json.dumps(node.params, default=str)}\n"
        f"Error: {error}\n"
        f"Context: {json.dumps(context, default=str)}\n"
    )
    return prompt if mask.settle() else None


class EscalationManager:
    """Orchestrates the 3-tier escalation cascade.
```

**K13.** SEARCH:
```
        """Ask the LLM to judge the failure."""
        prompt = (
            f"Intent: {node.intent}\n"
            f"Params: {json.dumps(node.params, default=str)}\n"
            f"Error: {error}\n"
            f"Context: {json.dumps(context, default=str)}\n"
        )
```
REPLACE:
```
        """Ask the LLM to judge the failure."""
        prompt = _arbitration_prompt(self.runtime, node, error, context)
        if prompt is None:  # AD-1337 S5: the masking pass failed: nothing is sent, and the cascade goes on to Tier 3
            return EscalationResult(
                tier=EscalationTier.ARBITRATION, resolved=False, original_error=error, reason=MASKING_FAILED_TEXT,
            )
```

### 7.6 `tests/test_ad1337_render_seam.py` (M1)

**K14.** SEARCH:
```
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect (AD-1337 S5)",
```
REPLACE:
```
    ("src/probos/runtime.py", "ProbOSRuntime.submit_mcp_invoke_with_consensus", "invoke", "self.mcp_bridge"):
        "reaches a model through _McpTool.invoke (producer seam) or a decomposed DAG's reflect or arbitration prompt, "
        "which RouteTextMask masks (AD-1337 S5, test_ad1337_reflect_route.py)",
```

### 7.7 `PROGRESS.md` (M2)

**KT1.** SEARCH (the whole line `:1`; it occurs once): `# ProbOS Progress`. REPLACE:
```markdown
# ProbOS Progress

**AD-1337 S5 (2026-11-22), #1560 -- a decomposed DAG's model prompts are masked; #1560 is complete.** A DAG's nodes run as mesh intents (a shell agent's stdout, a doc snippet, another agent's result), which neither the producer seam nor the render seam sees. `RouteTextMask` (`security/secret_masking.py`) masks the two prompts that carry them to a model. `IntentDecomposer.reflect` masks each node-result part before `_summarize_node_result` cuts it, so a value a cut would split is replaced whole, then the whole prompt before the 12,000-character cap, the DEBUG log and the model. The escalation's Tier 2 arbitration prompt, which carries a node's error text, is masked the same way. A failed pass sends nothing: reflect returns "" (its callers then show the node results without a synthesis, as on a timeout), and arbitration goes on to Tier 3, the Captain. One WARNING with labels and no `SECRET_MASKED`, as for S3's DM route. Finalize assigns `IntentDecomposer.secret_masker` after the masker exists, because the runtime builds the decomposer first; without one both prompts are byte-identical. Measured by `tests/test_ad1337_reflect_route.py` (8 cases, 10 items): raw, base64 and URL-encoded forms in stdout, stderr, a doc snippet and a result reach the model and the DEBUG log as `<secret:github>`; a value spanning the 500-character cut or the cap is masked whole; a failed pass makes no model call; with no masker both prompts match today's goldens; a census pins every model request in the two DAG files, the decomposer's one construction and its wiring, and the reflect callers. Not measured: a live shell agent through the mesh, a live run. #1560's slices S1 to S5 are built; follow-ups are #1820 ad-1337 R1 to R27 (R10 and R15 are not used). Contract `prompts/ad-1337-s5-dag-prompts.md`.
```

### 7.8 `DECISIONS.md` (M2)

**KT2.** SEARCH (two whole lines, S1's text; after S4's TR2 they occur once, in this order):
```
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
- *Residual.* #1820 items ad-1337 R1 to R6. *Reversal.* Revert the AD-1337 commits.
```
REPLACE:
```markdown
- *DAG prompts (S5).* A decomposed DAG's nodes run as mesh intents, not tool calls, so neither seam sees their results. `RouteTextMask` (`security/secret_masking.py`) holds the passes over one model prompt a route builds from such text. `IntentDecomposer.reflect` masks each node-result part before `_summarize_node_result` cuts it: a cut leaves a prefix of a value that no later pass matches, and a `.env` line crossing the 500-character cut is the ordinary case. It then masks the whole prompt before the 12,000-character cap, the DEBUG log and the model. The escalation's Tier 2 arbitration prompt carries a node's error text and is masked the same way (`_arbitration_prompt`, a module function because `EscalationManager` is at the 500-line class bound). The decompose prompt is not masked: it is the Captain's request and conversation (#1820 ad-1337 R19). A census pins every model request in the two files.
- *Wiring and failure (S5).* `IntentDecomposer.secret_masker` is a plain attribute (None), assigned by finalize from `_wire_secret_masker` and read through `secret_masker_of`. It is not a constructor argument, because the runtime builds the decomposer before the masker exists; not a method, because the class is at its 15-method cap; and not S3's slot, whose module would bring the SWE tool layer into the decomposer's imports. The arbitration reads the runtime's masker, which `EscalationManager` holds. A failed pass sends nothing: reflect returns "" as on a timeout, so its callers show the results without a synthesis, and arbitration goes on to Tier 3. One WARNING with labels and no `SECRET_MASKED`, as S3's DM route: neither class holds an emitter (#1820 ad-1337 R20). Inline: each pass is S1's (22 ms per MiB with 50 values), and a shell stream is at most 64 KiB.
- *Residual (S5).* #1820 items ad-1337 R19 to R21.
- *Related.* BF-890 (child environments), `PIIRedactor.redact_tokens` (patterns; stays as a second layer), `provider_setup.redact` (one provider key in the operator's own setup and doctor text).
- *Residual.* #1820 items ad-1337 R1 to R27 (R10 and R15 are not used). *Reversal.* Revert the AD-1337 commits.
```

If S4's final residuals do not end at R18, number S5's three from the next free number in KT1, KT2, 8.3 and the census reason (R19).

### 7.9 `docs/research/openhands-absorption.md` (M2)

**KT3.** SEARCH (S4's TR3 text; it occurs once):
```
A decomposed DAG's reflect prompt (S5) follows. |
```
REPLACE:
```
S5 masks a decomposed DAG's reflect and arbitration prompts, which completes the issue. |
```

### 7.10 Ledger (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then the same command with `--check`, then `tests/test_ad1184_ad_ledger.py`. Commit any regenerated `docs/development/open-ads-report.md` and `ad-ledger-snapshot.json` in M2. No `roadmap.md` row (an AD).

## 8. Issue texts (post after batch 2 merges)

**8.1 #1560, landing comment** (S4's paragraph from S4's 8.1, then):
> **AD-1337 S5 (a decomposed DAG's prompts; PR #...).** A DAG's nodes run as mesh intents, which neither seam sees. `RouteTextMask` masks the two prompts that carry their output to a model: the reflect prompt (each part before it is cut, then the whole prompt before the cap, the DEBUG log and the model) and the escalation's Tier 2 arbitration prompt (a node's error text). A failed pass sends nothing: reflect returns "", and arbitration goes on to the Captain. Without a masker both prompts are unchanged. A census pins every model request in the DAG files.
>
> **What remains in #1560: nothing.** S1 to S5 are built. The follow-ups are #1820 ad-1337 R1 to R27 (R10 and R15 are not used).

**8.2 #1560, decision 2 (final amendment):**
> *Decision 2, as built.* Masking has two seams, not one. The producer seam (`ToolExecutor._invoke_once`, S2) masks every result a registry returns. The render seam (`RenderMask` in the agentic loop, S3) masks what the loop hands a model, including exception text, custom `str()` and AD-1240's offloaded copy. Every route past the executor is masked or has a recorded reason (S3's census). The DM tier-1 browser call is masked (`mask_route_result`). A browser session that holds a per-run value masks its own results (S4). A decomposed DAG's reflect and arbitration prompts are masked (`RouteTextMask`, S5). Per-run vault values are registered while their session or client lives (S4).

**8.3 #1820:** S4's items are R13, R14, R16 to R18, R22 and R24 to R27 (its draft's R9 to R14, renumbered: R9->R13, R10->R14, R12->R16, R13->R17, R14->R18; the draft's R11 is not filed, because S4's D9 fixes it; R22 and R24 to R27 are S4's reviews', numbered after S5's). R23 (S2's, found in review) is filed with this batch. Add:
- **ad-1337 R19** (Low).
  - *Reach:* a raw node result the Captain is shown (reflect off, or empty after a failed pass) returns as the HXI client's or a channel's conversation history and enters the next decompose prompt, 200 characters per message (`routers/chat.py:906`, `channels/base.py:387`, `decomposer.py:383-389`).
  - *Evidence:* S5 D4.
  - *Gap:* the decompose prompt is the Captain's own input and is not masked; masking it would rewrite a value the Captain typed on purpose.
- **ad-1337 R20** (Low).
  - *Reach:* a hit on the DAG reflect or arbitration prompt.
  - *Evidence:* S5 D5.
  - *Gap:* logged at WARNING with labels, with no `SECRET_MASKED` (as S3's DM route and R13's `browser_session`).
- **ad-1337 R21** (Low).
  - *Reach:* a node's exception text in the DAG executor's and the escalation's logs (`decomposer.py:1087`, `escalation.py:257`, `:385`) and in `ESCALATION_START`'s `error` (`decomposer.py:1090-1093`, `:1177-1180`).
  - *Evidence:* S5 D4.
  - *Gap:* logs and event payloads are not masked: the classes of R4 and R14.

**8.4 #1557 (AD-1335):** nothing from S5.

## 9. What this does NOT change

- `ToolExecutor`, `render_masking.py`, the agentic loop, `reply_pipeline`, S4's files and its registry, `EventType`, the AD-1195 counts.
- The decompose prompt, `DAGExecutor` (its logs and events), working memory, episodes, the Captain's displays (`panels.py`, `response_formatter.py`, channels, `/plan`).
- `architecture-baseline.yaml`, config, profiles, HXI.
- S1's code: K1 only inserts a class above `class SecretHandle`.

## 10. Mutation rows (one campaign on the M1 candidate; restore between rows)

| Row | Mutant (one line) | Killed by |
|---|---|---|
| Y1 | `RouteTextMask.__call__`: `return outcome.text` becomes `return text` | Z2, Z6 |
| Y2 | `__call__`: `if self._failed:` becomes `if False:` | Z5 (three ERROR records) |
| Y3 | `clip`: the masked return becomes `return text[:limit]` | Z3 |
| Y4 | `settle`: `return False` becomes `return True` | Z5, Z7 |
| Y5 | `settle`: `if self._names:` becomes `if False:` | Z2, Z6 |
| Y6 | reflect: `_summarize_node_result(node_result, clip=mask.clip)` becomes `_summarize_node_result(node_result)` | Z3, Z8 |
| Y7 | reflect: `prompt_text = mask("\n".join(result_parts))` becomes `prompt_text = "\n".join(result_parts)` | Z4, Z8 |
| Y8 | reflect: the failure branch's `return ""` becomes `pass` | Z5 |
| Y9 | reflect: `RouteTextMask(secret_masker_of(self), ...)` becomes `RouteTextMask(None, ...)` | Z2, Z3, Z4, Z8 |
| Y10 | `_summarize_node_result`: `clip(stdout, 500)` becomes `stdout[:500]` | Z3, Z8 |
| Y11 | `_summarize_node_result`: `clip(snip.get('source', ''), 1500)` becomes `snip.get('source', '')[:1500]` | Z8 |
| Y12 | finalize: delete `runtime.decomposer.secret_masker = secret_masker` | Z8 |
| Y13 | `_arbitration_prompt`: `secret_masker_of(runtime)` becomes `None` | Z6, Z8 |
| Y14 | `_tier2_arbitrate`: `if prompt is None:` becomes `if False:` | Z7 |
| Y15 | `_arbitration_prompt`: `return prompt if mask.settle() else None` becomes `return prompt` | Z7 |
| Y16 | `__init__`: delete `self.secret_masker: SecretMasker | None = None` | predicted equivalent (`secret_masker_of` reads with a default); report if killed |

- **sha256 rule:** record each edited file's sha256 on the candidate. If any file the Builder produces differs, rerun every row that mutates that file and every row killed by a case in `tests/test_ad1337_reflect_route.py`.

## 11. Verified Against Codebase (2026-11-22, `ob11brake` at `33826d30`)

```
read cognitive/decomposer.py:1-50, 240-330, 380-512, 640-796, 1080-1104, 1160-1191
  16-18 K2; 271-273 K3; 468-482 K4; 691-699 K5; 711-716 K6; 724-733 K7; 745-754 K8; 767-771 K9 (each once)
  rg "^    (async )?def " -> 15 methods in IntentDecomposer (254-640); class 247-648
  rg "LLMRequest\(|\.complete\(" decomposer.py escalation.py -> decomposer 409, 493, 502; escalation 282, 290
read consensus/escalation.py:1-80, 95-195, 225-397, 484-551   17-22 K11; 51-52 K12; 274-280 K13 (each once); class 51-550
read startup/finalize.py:700-742, 5884-5904   5890-5892 K10 (once); S4's C1 edits 724-726 only
read security/secret_masking.py:1-450   55 MASKING_FAILED_TEXT; 80-86 MaskOutcome; 198-228; 231-232 K1 anchor; 362-372 mask_text
read runtime.py:1050-1079, 5903-5927, 6093-6158; renderer.py:455-489; commands_plan.py:155-182
read utils/response_formatter.py:18-57; experience/panels.py:748-761; dream_adapter.py:348-390; agents/introspect.py:233-270
read cognitive/working_memory.py:60-81, 225-255; agents/shell_command.py:69, 326-347; cognitive/llm_client.py:2920-2979, 3094-3100
read tests/test_ad1337_render_seam.py:20-90, 600-725 (671-672 K14, once); tests/test_ad1337_secret_masking.py:56-100
read tests/fixtures/ad1343_seam_census.py:44-150; tests/test_decomposer.py:300-383; tests/test_escalation.py:880-909
read tests/test_ad1337_executor_seam.py:585-615; tests/test_layer_boundaries.py:14-61, 146-169
read scripts/check_architecture_principles.py:187-188, 556-574; PROGRESS.md:1-3; DECISIONS.md:1661-1681
rg "IntentDecomposer\(" tests -> 30 in 11 files; rg "finalize_startup\(" tests -> 5 files (MagicMock runtimes)
rg "\.get\([\"']reflection[\"']" src -> the consumers in P7
git ls-files --eol (the 8 edited files) -> i/lf w/crlf
```

## Absence Verified (2026-11-22)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No S5 name exists | `rg "RouteTextMask\|_arbitration_prompt\|dag_reflect\|dag_arbitration\|decomposer\.secret_masker" -g "*.py"`; the same over S4's draft | none; S4 names `decomposer.py` only in its section 9 | yes |
| No S5 test file | glob `tests/test_ad1337_*.py` | three batch-1 files | yes |
| No decomposer signature golden | `rg "signature\(IntentDecomposer\|IntentDecomposer\.__init__\|vars\(IntentDecomposer" tests` | none | yes |
| One decomposer, never replaced | `rg "IntentDecomposer\(" src`; `rg "\.decomposer\s*=[^=]" src` | `runtime.py:1059` each | yes (Z8) |
| Three reflect callers | `rg "\.reflect\(" src`; `rg "[^.\w]reflect\(" src` | renderer 468, commands_plan 167, runtime 6131; the def at 460 | yes (Z8) |
| The summariser has one caller | `rg "_summarize_node_result" src` | `decomposer.py:476`, def 691 | yes |
| Neither class is in the baseline | `rg "EscalationManager\|IntentDecomposer\|DAGExecutor" architecture-baseline.yaml` | none | yes: a breach would be a new finding |
| Working memory's `detail` reaches no prompt | `rg "recent_results" src/probos`; `rg "\.get\([\"']detail[\"']\)" src/probos/cognitive` | `working_memory.py` only (to_text 73-79); none | yes |
| No blob pin on the edited files | `rg "(decomposer\|escalation\|finalize)\.py.{0,80}(sha\|blob\|[0-9a-f]{40})" tests` | the AD-1152 golden's `base_source_blobs` (a past base commit's blobs) | yes |

## 12. Deterministic checks

- **Focused gate, `-n 0`:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest -n 0 -q` on:
  - `tests/test_ad1337_reflect_route.py`, `tests/test_ad1337_render_seam.py`, `tests/test_ad1337_secret_masking.py`, `tests/test_ad1337_executor_seam.py`, `tests/test_ad1337_per_run.py`
  - `tests/test_decomposer.py`, `tests/test_ad152_regressions.py`, `tests/test_escalation.py`, `tests/test_bf860_consensus_floor.py`, `tests/test_workflow_cache.py`, `tests/test_prompt_builder.py`, `tests/test_public_apis.py`, `tests/test_introspect.py`, `tests/test_bf875_mcp_inbound_auth.py`, `tests/test_agent_evals.py`
  - `tests/test_ad1270a_startup_receipts.py`, `tests/test_new_crew_auto_welcome.py`, `tests/test_ad641d_deliberation.py`, `tests/test_bf235_stale_identity_cache.py`, `tests/test_ad1248_slice_a_gaps.py`, `tests/test_ad1273_agent_rehydration.py`, `tests/test_ad1278_audit_durability.py`, `tests/test_ad1296_working_dir_ownership.py`, `tests/test_ad654d_internal_emitters.py`
  - `tests/test_layer_boundaries.py`, `tests/test_ad1324_srp_layout.py`, `tests/test_ad1270b_architecture_fitness.py`, `tests/test_ad1195_durable_producers.py`, `tests/test_ad1184_ad_ledger.py`
- `d:/ProbOS/.venv/Scripts/python.exe -P -c "import probos.captain_card.card, probos.experience.renderer, probos.consensus.escalation"` exits 0 (no import cycle).
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` exits 0.
- `rg -l "RouteTextMask\(" src` finds only `cognitive/decomposer.py` and `consensus/escalation.py` (the class is declared `class RouteTextMask:` in `security/secret_masking.py`, which this pattern does not match; measured 2026-11-24 on the oracle).
- `git diff 8abbf58d9a77 -- src/probos/security/secret_masking.py` shows insertions only, all above `class SecretHandle:`.
- `git diff 8abbf58d9a77 --stat` lists exactly: the four source files, the two test files, the three trackers and any regenerated ledger files.
- The new file is ASCII only.
- Broad gate, once for batch 2: `scripts/run_test_gate.py --label ad-1337-1560-b2 --receipt logs/gates/ad-1337-1560-b2.receipt.json`.

## 13. Prior art and blind spots

- **Internal:** S1's owner and fail-closed rule; S3's rejection of masking after a truncation (the same defect as P2's cut) and its route WARNING (`mask_route_result`); S3's `secret_masker_of` holder filter; AD-1343's census visitor (reused, not copied); S2's measured cost.
- **External:** none searched. This is ProbOS-specific prompt assembly, and the masking design's prior art (GitHub Actions `add-mask`, OpenHands' per-conversation secrets) was absorbed in S1 and S4. Reference projects checked on 2026-11-22: OpenHands (last reviewed 2026-10-15) was found not overdue by S4 on the same date; no other row is relevant. No row update.
- **Blind spots named:**
  - the per-part cut (D1, fixed);
  - the second DAG prompt (D4, fixed);
  - the conversation-history echo (R19);
  - no event (R20);
  - logs and events (R21);
  - an arbiter shown a masked parameter may answer "modify" with the placeholder, and that retry then fails rather than leaks (only for a parameter that already holds a known value);
  - a value holding a quote, a backslash or a control character appears in a `str(dict)` part in Python's repr escaping, which matches a JSON-escaped form only where the two agree (the same class as S3's `str()` of a container).

## 14. Diff Reviewer: properties to verify

1. Every DAG prompt holding node output or a node's error text passes `RouteTextMask` before the model and before any log of it. Reflect masks each part before its cut, then the whole prompt before the cap, the DEBUG log and `LLMRequest`; Tier 2 masks its prompt. The decompose prompt's recorded reason is true.
2. With no masker (None, a non-`SecretMasker`, a runtime without one), both prompts and `_summarize_node_result`'s default cuts are byte-identical to the base.
3. Fail closed: a failed pass sends nothing to the model; reflect returns `""`, and Tier 2 returns unresolved; the call logs one value-free WARNING plus S1's one ERROR, and later passes do not re-run the masker.
4. No value, form or position reaches a log record, an exception, an event or a returned result; labels come from S1 only; no `SECRET_MASKED` and no id is introduced.
5. Finalize assigns the runtime's masker to the one decomposer right after `_wire_secret_masker`, and nothing else replaces `runtime.decomposer`.
6. `_summarize_node_result` has no direct slice left; `secret_masking.py` changes by insertion only, above `class SecretHandle`; `EscalationManager` stays within 500 lines and `IntentDecomposer` within 15 methods.

## 15. Acceptance

- [ ] Section 5's prediction holds: 3 passed and 7 failed on `8abbf58d9a77`, 10 passed after M1; the focused gate is green.
- [ ] Mutation rows Y1 to Y15 are killed by the named cases; Y16 is equivalent as predicted.
- [ ] Section 12's checks hold, including the import check and `check_architecture_principles.py --check`.
- [ ] KT1 to KT3 are applied; the ledger is regenerated and checked.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. The orchestrator's first-hand checks (2026-11-24, scratch worktrees detached at `8abbf58d`, S4's final head, after its two review rounds)

The 18 operations of section 7 (the new test file, K1 to K14 and KT1 to KT3) were applied by `audit\contract_tools.py apply` (ASCII only) to scratch copies of the tree at S4's final head (S4's 18 operations, the 24 of its repair and the two tracker texts of its second review, as committed, so `secret_masking.py`, `finalize.py` and the three trackers are S4's), so no run touched another's files: `ob11s5e` (all 18 operations, then the regenerated ledger) and `ob11s5f` (the new test file and K14 alone). The red run used the tree at S4's final head with only those two test edits added. Results:

| R | Result |
|---|---|
| R1 | **The pairs.** `contract_tools.py list` finds the 18 operations, and a dry run on the real tree at S4's head (`8abbf58d`; nothing written) finds every SEARCH exactly once at its turn: K1 116 to 2,159 characters; K2 239 to 328; K3 209 to 482; K4 666 to 1,163; K5 400 to 839; K6 317 to 327; K7 525 to 535; K8 496 to 506; K9 131 to 136; K10 296 to 468; K11 108 to 204; K12 75 to 897; K13 272 to 404; K14 219 to 309; KT1 17 to 1,820; KT2 278 to 2,143; KT3 49 to 89. `audit\ws_ambiguity.py`, which models the edit tool's matching (a multi-line SEARCH equals a block that differs only in leading whitespace), finds no pair that matches twice at its turn (0 hazards in 17). The four source files change by **+97 -17** lines (`secret_masking.py` +43 -0, `decomposer.py` +29 -11, `finalize.py` +2 -0, `escalation.py` +23 -6), the render-seam test by +2 -1, the new test file has 340 lines, and the three trackers by +7 -2. The blob after each operation is in the `contract_tools.py checkpoints` table that the Builder briefs carry; the oracle's nine files equal its final blobs (9 of 9): `secret_masking.py` `596476cf`, `decomposer.py` `5b0ffc3f`, `finalize.py` `f1c32d35`, `escalation.py` `087d4be6`, `test_ad1337_render_seam.py` `8240c38c`, the new test file `d5ed72b1`, `PROGRESS.md` `5b40851d`, `DECISIONS.md` `2dac54b1` and `openhands-absorption.md` `a36967b3`. |
| R2 | **Red.** The new test file and K14 alone on the tree at S4's head (no S5 source pair): **7 failed, 3 passed** in 15.6 s, as section 5 predicts. The three passes are the cases that take today's path without a masker (Z1's two and Z6's "no masker" case). The seven failures are Z2 (`test_every_form_in_a_node_result_is_masked_before_the_model_and_the_log`), Z3, Z4, Z5, Z6's masked case, Z7 and the census Z8; the first failure shows the node output in the prompt unmasked. |
| R3 | **Green.** With K1 to K14: **10 passed** in 15.8 s; under `-W error`: 10 passed in 11.5 s. |
| R4 | **The campaign** (`audit\mutants_gen.py`, `audit\rows_ad1337s5.py`; the new test file alone; each row changes one line and restores the file before the next): the unmutated candidate ran 10 cases, all passed. **16 rows (Y1 to Y16): killed 15, differs 0, survived 1, invalid 0.** The survivor is Y16, which section 10 predicts equivalent (`secret_masker_of` reads the attribute with a default, so deleting its declaration changes no behaviour). Every named killer failed in every killed row; the extra failures beyond the named killers were Y1 2, Y9 1, Y13 1 and Y15 1. The edited files' LF sha256 on the candidate: `secret_masking.py` `a07e43a0...`, `decomposer.py` `a62b96fb...`, `finalize.py` `e63fd38b...`, `escalation.py` `5ef33ac1...`, the new test file `00d05b7c...` and `test_ad1337_render_seam.py` `5e76d307...` (the full values are in `evidence-b11s5r2-campaign.txt`). The campaign ran on `ob11s5c`, the same operations on the tree at `e53f70f6`, S4's head before the documents of its second review; the six edited files there are blob-identical to the final oracle's (6 of 6), and the trackers take no part in it. If a file the Builder produces differs in blob from R1's, rerun every row that mutates that file and every row killed by a case in the new test file (section 10's rule). |
| R5 | **The focused gate of section 12** (32 files, `-n 0`, through the home-guard wrapper with an empty redirected home; S4's `test_ad1337_per_run.py`, 38 items, is one of them): **1470 passed, 1 skipped** with the default embedding mode (510 s), and **1470 passed, 1 skipped** with `PROBOS_EMBEDDINGS=local`, CI's mode (446 s). The skip is the `skip` marker at `tests/test_ad641d_deliberation.py:250` ("BF-657: fragile full-finalize_startup-on-a-MagicMock integration test"), in that test's own source, so it does not depend on this contract. |
| R6 | **The static checks of section 12** on the oracle: `rg -l "RouteTextMask\("` finds exactly `cognitive/decomposer.py` and `consensus/escalation.py`; `git diff 8abbf58d -- src/probos/security/secret_masking.py` shows **43 insertions and 0 deletions**, one hunk at line 267, all above `class SecretHandle:` (which is then at line 310); the new test file has 340 lines and no byte above 127; `python -P -c "import probos.captain_card.card, probos.experience.renderer, probos.consensus.escalation"` exits 0; `check_architecture_principles.py --check` passes with `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, the same counts as the tree at S4's head. `EscalationManager` spans exactly 500 lines before the pairs and 499 after them (K12's helper function and K11's imports sit above the class, so it starts at line 69, not 51), and `IntentDecomposer` has 15 methods before and after. |
| R7 | **M2.** KT1, KT2 and KT3 apply (one occurrence each). `gen_ad_ledger.py` wrote the ledger pair, `--check` reports "AD/BF ledger is current", and relative to the ledger at S4's head the snapshot differs by three replaced lines (`captured_at`, `head`, `subject_count`) and the report by three (the git-log row and the two `PROGRESS.md` line numbers that moved down by KT1's two added lines). The tests that read the trackers, the ledger or the research doc (the eight files named in S4's R7 with `test_ad758_program_gate.py`) and the two new test files of batch 2 (`test_ad1337_per_run.py`, `test_ad1337_reflect_route.py`): **280 passed in 107 s (the 266 of the first measurement and the 14 items that S4's repair added to its test file)**. |
| R8 | **The premises and absences, read again on the tree at S4's head.** S5's prose cites the line numbers of `108a7fff`, before S4's pairs. S4 changes three files this contract reads or edits: `secret_masking.py` (+36 above `class SecretHandle:`, where K1 inserts too: the class is at line 267 before K1), `finalize.py` (+5 -2 inside `_wire_secret_masker`, which moves K10's anchor from `:5898` to `:5901`) and `runtime.py` (+6, which S5 only cites: the decomposer's build is now at `:1065` and the `reflect` call at `:6137`). Its repair changes `client.py`, `registration.py`, its own tests and the trackers, which S5 reads only through KT1 to KT3. The absence rows of section 11 were run again on that tree (`git grep` at `8abbf58d`): no S5 name in any `*.py` (exit 1); the glob `tests/test_ad1337_*.py` finds four files, batch 1's three and S4's `test_ad1337_per_run.py`; no decomposer signature golden (exit 1); one decomposer, built at `runtime.py:1065`, and no other store of `.decomposer`; three `reflect` callers (`renderer.py:468`, `commands_plan.py:167`, `runtime.py:6137`) and the def at `decomposer.py:460`; the summariser's one caller at `decomposer.py:476` and its def at `:691`; neither class in `docs/development/architecture-baseline.yaml` (exit 1; the row names the file without its folder); `recent_results` only in `working_memory.py` and no `.get("detail")` in `cognitive/`; the blob-pin pattern finds `tests/fixtures/ad1152_agentic_off_golden.json` (a past base commit's blobs) and a comment at `tests/test_ad477_naval.py:351`, the same two as on `33826d30`. |
| R9 | **The pins discriminate.** Each of rows Y1 to Y15 is killed by the cases section 10 names, and R4 shows that every named killer failed in every killed row. So D1 (each part is masked before its cut, and the whole prompt before the cap) is held by Z3 and Z4 (rows Y3, Y6, Y7, Y10, Y11); D3 (a failed pass sends nothing) by Z5 and Z7 (rows Y2, Y4, Y8, Y14, Y15); D4's second prompt, the arbitration, by Z6 (rows Y1, Y5, Y13); and the wiring and the one construction of the decomposer (D2, D6) by the census Z8 (rows Y12 and, with Z2 to Z4, Y9). |
| R10 | **Linux.** The Windows gate cannot see platform differences (batch 1's first CI run failed on one), so the new test file was searched for the constructs that differ: a process spawn, `os.environ`, `HOME`, file modes, path separators, `read_text` without an encoding, signals, `sys.platform`, case-sensitive names, `subprocess` and sleeps. It has none: it builds its real masker over `tmp_path` through S3's `_real_masker`, uses `MockLLMClient` and `SimpleNamespace` runtimes, patches one module function with `monkeypatch`, and its census reads source with `Path.read_bytes()` and compares `as_posix()` paths, as AD-1343's census does. That is a reading, not a Linux run: the pull request's CI is the only one. |

**What the orchestrator changed in the Architect's sections 7, 10 and 14:** nothing in the pairs, the test file, the rows or the properties. Two remarks on the surrounding text. (1) The header's base sentence says that the tip of batch 1 that merged (`a86a2895`) has the same `src` as `108a7fff`, whose line numbers the prose cites. (2) The `rg` line of section 12 names the two files the pattern finds, because `RouteTextMask\(` does not match the class declaration; measured on the oracle.

**What these checks do not show.**
- A live shell agent through the mesh, a live DAG run, a real model and the HXI: the file uses a mock model and doubles for the runtime.
- Linux (R10) and the broad gate of batch 2 (not run yet).
