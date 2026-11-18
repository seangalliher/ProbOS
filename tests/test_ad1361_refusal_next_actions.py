"""AD-1361 (#1743 item 2): every refusal in ``cognitive/swe_harness/tools.py`` names the nearest action the agent has.

The contract's census (section 3) classifies the file's 49 error returns on 9f43697f. The nine refusals that named no
next action now end with one sentence; refusals that already named one, input errors, failures and AD-1240 delivery
codes are unchanged. A ToolResult error added to or removed from a tool class fails the census until it is classified
under this convention.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import llm_function_name
from probos.cognitive.swe_harness.tools import EditFileTool, ReadFileTool, WriteFileTool, register_native_swe_tools
from probos.tools.protocol import is_caller_input_error
from probos.tools.registry import ToolRegistry
from tests.test_bf948_list_files_read_policy import SECRET_NAME, _list, _runtime, _scene

_READ_NEXT = (
    "Do not repeat this call with the same path: read another file, and use list_files to see which files you can read."
)
_LIST_NEXT = "Do not repeat this call with the same path: list another directory."
_WRITE_NEXT = (
    "Do not repeat this call: leave this file as it is, go on with the rest of your task, "
    "and say in your reply what change you wanted."
)
_STANDING_ORDERS_NEXT = "Do not repeat this call for it: say in your reply which file you needed."
_RULE = "RULE-TEXT-1361"
_RULES = ("constitution_write_refusal", "captain_document_write_refusal", "protected_write_refusal")

# Each sentence and the tools whose refusal ends with it.
_REFUSED_BY = {
    _READ_NEXT: ("read_file",),
    _LIST_NEXT: ("list_files",),
    _WRITE_NEXT: ("write_file", "edit_file"),
    _STANDING_ORDERS_NEXT: ("standing_orders_lookup",),
}

# The census (contract section 3): ToolResult and RecoveryFailureToolResult calls with an ``error`` keyword, per tool
# class, on 9f43697f. AD-1361 changes texts, never the number of returns.
_ERROR_RETURNS = {
    "ReadFileTool": 5, "ListFilesTool": 5, "CodebaseQueryTool": 3, "CodebaseFindCallersTool": 3,
    "CodebaseFindTestsTool": 3, "CodebaseGetImportsTool": 3, "CodebaseReadSourceTool": 4,
    "StandingOrdersLookupTool": 5, "SystemSelfModelTool": 1, "WriteFileTool": 6, "EditFileTool": 7,
    "RunCommandTool": 4,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", ["read_file", "list_files"])
async def test_read_and_list_refusals_name_the_next_action(tmp_path: Path, tool_id: str) -> None:
    """The policy's refusal keeps BF-948's mark and its reason, then names the next action."""
    scene = _scene(tmp_path)
    if tool_id == "read_file":
        result = await ReadFileTool(_runtime(scene, read_roots=[scene.allowed])).invoke(
            {"path": str(scene.outside / SECRET_NAME)},
        )
        base, sentence = "read_file refused: path is outside every readable root", _READ_NEXT
    else:
        result = await _list(scene, [scene.allowed], "*", str(scene.outside))
        base, sentence = "list_files refused: path is outside every readable root", _LIST_NEXT
    assert result.output is None and (result.error or "").startswith(base)  # premise: the policy refused
    assert result.error == f"{base}. {sentence}"
    assert is_caller_input_error(tool_id, result.error)  # the mark is kept, so both fault detectors still skip it


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", _RULES)
@pytest.mark.parametrize("tool_id", ["write_file", "edit_file"])
async def test_write_refusals_name_the_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_id: str, rule: str,
) -> None:
    """Each write rule as the tool returns it: the rule's text (marked for the Captain-document rule, as BF-975 left
    it), then the next action. The target is a temporary file, so nothing outside ``tmp_path`` could be written even
    if a refusal were lost."""
    for name in _RULES:
        monkeypatch.setattr(swe_tools, name, (lambda *_a, **_k: _RULE) if name == rule else (lambda *_a, **_k: None))
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    tool = WriteFileTool(SimpleNamespace()) if tool_id == "write_file" else EditFileTool(SimpleNamespace())
    params = (
        {"path": str(target), "content": "new"} if tool_id == "write_file"
        else {"path": str(target), "old_text": "old", "new_text": "new"}
    )
    result = await tool.invoke(params)
    base = f"{tool_id} refused: {_RULE}" if rule == "captain_document_write_refusal" else _RULE
    assert (result.error or "").startswith(base)  # premise: that rule refused
    assert result.error == f"{base}. {_WRITE_NEXT}"
    assert target.read_text(encoding="utf-8") == "old"


def test_the_standing_orders_denial_and_the_sentences_are_pinned() -> None:
    """BF-910's tests prove the tool returns ``_STANDING_ORDERS_DENIED`` for a refused read; this pins its text and the
    three sentences the other refusals append."""
    assert swe_tools._STANDING_ORDERS_DENIED == (
        "standing_orders_lookup: that standing-orders file is not readable on this vessel. " + _STANDING_ORDERS_NEXT
    )
    assert (swe_tools._READ_REFUSAL_NEXT, swe_tools._LIST_REFUSAL_NEXT, swe_tools._WRITE_REFUSAL_NEXT) == (
        _READ_NEXT, _LIST_NEXT, _WRITE_NEXT,
    )


def test_each_next_action_reads_as_no_gap_and_names_only_tools_the_refused_agent_has() -> None:
    """No sentence reads as a capability gap; a tool a sentence names is registered with the refused tool's own
    permission matrix and spelled as the model sees it."""
    registry = ToolRegistry()
    assert register_native_swe_tools(registry, SimpleNamespace()) == 12
    named_any = False
    for sentence, refused_by in _REFUSED_BY.items():
        assert _CAPABILITY_GAP_RE.search(sentence) is None, sentence
        for name in sorted(set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", sentence))):
            named_any = True
            registration = registry.get(name)
            assert registration is not None, f"{name} is not a registered tool"
            assert llm_function_name(name) == name
            for tool_id in refused_by:
                assert registration.default_permissions == registry.get(tool_id).default_permissions, (name, tool_id)
    assert named_any, "premise: at least one sentence names a tool"


def test_every_error_return_in_the_native_tools_is_counted() -> None:
    """The census: an error return added to or removed from a native tool class is classified under AD-1361's
    convention (a refusal names the nearest action this agent has) before this table changes."""
    tree = ast.parse(Path(swe_tools.__file__).read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        found = sum(
            1 for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id in ("ToolResult", "RecoveryFailureToolResult")
            and any(keyword.arg == "error" for keyword in call.keywords)
        )
        if found:
            counts[node.name] = found
    assert sum(counts.values()) > 0, "premise: the census found the native tools' error returns"
    assert counts == _ERROR_RETURNS, "classify the added or removed error return under AD-1361, then update the table"
