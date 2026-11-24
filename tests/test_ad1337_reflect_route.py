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
