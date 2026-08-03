"""AD-1178 (#1110): a missing library becomes a request, not a bare traceback.

When a crew agent's script imports a library the venv does not have, the run
previously surfaced only ``ModuleNotFoundError`` in ``stderr``. AD-1180 tells
every agentic path to "say plainly what is needed and why" — this gives the
model the structured signal to say it from.

The load-bearing test here is
``test_detect_unimportable_is_not_detect_missing``: it records the empirical
reason a new detector exists rather than a call to
``DependencyResolver.detect_missing``. Without it, someone will "simplify" this
back to the resolver and silently reintroduce the bug.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.dependency_resolver import DependencyResolver, DependencyResult
from probos.config import DependencyConfig, ExecutionConfig, SelfModConfig
from probos.tools import code_execution_tool
from probos.tools.code_execution_tool import (
    _DEPENDENCY_GUIDANCE,
    CodeExecutionTool,
    detect_unimportable,
)

# Real libraries a crew script would plausibly reach for. Which of these is
# absent is resolved AT TEST TIME via find_spec rather than hardcoded, so
# installing any of them later moves the test to the next candidate instead of
# breaking it. If every candidate is somehow present, the synthetic fallback is
# a name that can never appear on PyPI, so the test still has a genuine absence.
_CANDIDATE_MODULES = ("reportlab", "matplotlib", "pyarrow", "tensorflow", "torch")
_SYNTHETIC_ABSENT = "probos_ad1178_absent_probe"


def _absent_module() -> str:
    """A root module name this interpreter genuinely cannot resolve."""
    for name in _CANDIDATE_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                return name
        except Exception:
            return name
    return _SYNTHETIC_ABSENT


def _present_module() -> str:
    """A third-party (non-stdlib) module known to be installed."""
    assert importlib.util.find_spec("pydantic") is not None
    return "pydantic"


def _runtime(
    tmp_path: Path,
    *,
    dep_enabled: bool = False,
    resolver: object | None = None,
    ensure_result: DependencyResult | None = None,
):
    rt = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"),
            ),
            dependency=DependencyConfig(dynamic_install_enabled=dep_enabled),
        ),
        dependency_resolver=resolver,
        artifact_store=None,
        attachment_store=None,
    )
    rt.ensure_calls = []

    async def _ensure(names):
        rt.ensure_calls.append(list(names))
        return ensure_result

    rt.ensure_dependency = _ensure
    return rt


def _ctx():
    return {"thread_id": "thread-1", "agent_id": "ezri"}


class _FakeResolver:
    """Stands in for a whitelist-mode resolver: sees the code, reports nothing."""

    def __init__(self, missing: list[str]) -> None:
        self._missing = missing
        self.detect_calls = 0

    def detect_missing(self, code: str) -> list[str]:
        self.detect_calls += 1
        return list(self._missing)


# ── 1. the detector ───────────────────────────────────────────────


def test_detect_unimportable_reports_a_genuinely_absent_module() -> None:
    absent = _absent_module()
    assert detect_unimportable(f"import {absent}\nprint('hi')\n") == [absent]


def test_detect_unimportable_ignores_stdlib_and_installed_packages() -> None:
    code = (
        "import json\n"
        "import pathlib\n"
        f"from {_present_module()} import BaseModel\n"
    )
    assert detect_unimportable(code) == []


def test_detect_unimportable_returns_empty_on_syntax_error() -> None:
    # The run reports the SyntaxError itself; nothing to add.
    assert detect_unimportable("def broken(:\n    pass\n") == []


def test_detect_unimportable_skips_relative_imports() -> None:
    # Relative imports resolve against the workdir, not site-packages.
    code = "from . import sibling\nfrom ..pkg import thing\n"
    assert detect_unimportable(code) == []


def test_detect_unimportable_treats_find_spec_raising_as_unimportable(
    monkeypatch,
) -> None:
    # find_spec raises ModuleNotFoundError for a missing parent package and
    # ValueError for some malformed names — either way the import fails.
    def _boom(name):
        raise ModuleNotFoundError(f"No module named {name!r}")

    monkeypatch.setattr(code_execution_tool.importlib.util, "find_spec", _boom)
    assert detect_unimportable("import json\n") == ["json"]


def test_detect_unimportable_is_sorted_and_deduplicated() -> None:
    absent = _absent_module()
    code = (
        f"import {absent}\n"
        f"import {absent}.sub\n"
        f"from {absent}.other import thing\n"
        "import json\n"
    )
    assert detect_unimportable(code) == [absent]


def test_detect_unimportable_collects_both_import_forms() -> None:
    absent = _absent_module()
    other = _SYNTHETIC_ABSENT if absent != _SYNTHETIC_ABSENT else "probos_ad1178_other"
    code = f"from {other} import a\nimport {absent}\n"
    assert detect_unimportable(code) == sorted([absent, other])


def test_detect_unimportable_is_not_detect_missing() -> None:
    """WHY THIS HELPER EXISTS — do not collapse it into the resolver.

    ``DependencyResolver.__init__`` defaults ``policy="whitelist"`` and
    ``startup/cognitive_services.py`` builds it WITHOUT a policy when dynamic
    install is off. In whitelist mode ``detect_missing`` ``continue``s past any
    import that is not on ``self_mod.allowed_imports`` BEFORE it checks
    availability, so a genuinely absent non-allowlisted module is invisible to
    it. It answers "which allowlisted packages are missing"; this AD needs
    "which imports in this script will fail".
    """
    absent = _absent_module()
    allowed = SelfModConfig().allowed_imports
    assert absent not in allowed, "candidate must be off the allowlist"

    source = f"import {absent}\nimport json\n"
    # Constructed exactly as cognitive_services.py does it — no policy argument.
    resolver = DependencyResolver(allowed_imports=allowed)

    assert resolver.detect_missing(source) == []
    assert detect_unimportable(source) == [absent]


# ── 2. the guidance string ────────────────────────────────────────


def test_guidance_is_not_a_capability_gap() -> None:
    """Through the real ``is_capability_gap``, never a re-implemented pattern.

    The subject matter is absence, so the gap regex is easy to trip; a match
    would misread a routine "this needs a library" report as a capability gap
    and trip self-mod.
    """
    assert is_capability_gap(_DEPENDENCY_GUIDANCE) is False
    for names in ("reportlab", "matplotlib, reportlab"):
        assert is_capability_gap(_DEPENDENCY_GUIDANCE.format(names=names)) is False


# ── 3. the tool output ────────────────────────────────────────────


async def test_invoke_attaches_dependencies_when_a_module_is_absent(tmp_path) -> None:
    absent = _absent_module()
    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    result = await tool.invoke({"code": f"import {absent}\n"}, _ctx())

    dep = result.output["dependencies"]
    assert dep["missing"] == [absent]
    assert dep["install_enabled"] is False
    assert absent in dep["guidance"]
    assert is_capability_gap(dep["guidance"]) is False


async def test_invoke_preserves_run_output_alongside_the_new_key(tmp_path) -> None:
    # This augments; it never replaces the run's own output.
    absent = _absent_module()
    code = f"print('before import')\nimport {absent}\n"
    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    result = await tool.invoke({"code": code}, _ctx())

    assert "before import" in result.output["stdout"]
    assert "ModuleNotFoundError" in result.output["stderr"]
    assert result.output["exit_code"] != 0
    assert result.output["success"] is False
    assert result.output["artifacts"] == []
    assert result.output["dependencies"]["missing"] == [absent]


async def test_invoke_is_byte_identical_when_nothing_is_missing(tmp_path) -> None:
    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    result = await tool.invoke({"code": "import json\nprint('ok')\n"}, _ctx())

    assert result.error is None
    assert result.output["success"] is True
    assert "dependencies" not in result.output


async def test_invoke_works_with_dependency_resolver_none(tmp_path) -> None:
    # Both self_mod and dynamic install off => runtime.dependency_resolver is
    # None. The detector must not touch it.
    absent = _absent_module()
    rt = _runtime(tmp_path, resolver=None)
    assert rt.dependency_resolver is None
    result = await CodeExecutionTool(runtime=rt).invoke(
        {"code": f"import {absent}\n"}, _ctx(),
    )
    assert result.output["dependencies"]["missing"] == [absent]


async def test_ad1073_enabled_path_is_untouched(tmp_path) -> None:
    # dynamic_install_enabled=True => _maybe_install_missing returns a dict, so
    # the AD-1178 branch never runs and the AD-1073 shape is preserved intact.
    absent = _absent_module()
    resolver = _FakeResolver([absent])
    rt = _runtime(
        tmp_path, dep_enabled=True, resolver=resolver,
        ensure_result=DependencyResult(success=True, installed=[absent]),
    )
    result = await CodeExecutionTool(runtime=rt).invoke(
        {"code": f"import {absent}\n"}, _ctx(),
    )

    dep = result.output["dependencies"]
    assert dep == {
        "missing": [absent], "installed": [absent], "declined": [], "error": None,
    }
    assert "guidance" not in dep
    assert "install_enabled" not in dep
    assert rt.ensure_calls == [[absent]]


async def test_install_enabled_reports_the_operator_setting(tmp_path) -> None:
    # The one case where this branch runs with the flag ON: the flag is set but
    # the resolver's whitelist filtered the import out, so _maybe_install_missing
    # returned None. Report the operator's real setting, not a false False.
    absent = _absent_module()
    resolver = _FakeResolver([])  # whitelist mode saw nothing offerable
    rt = _runtime(tmp_path, dep_enabled=True, resolver=resolver)
    result = await CodeExecutionTool(runtime=rt).invoke(
        {"code": f"import {absent}\n"}, _ctx(),
    )

    assert resolver.detect_calls == 1
    assert rt.ensure_calls == []
    dep = result.output["dependencies"]
    assert dep["missing"] == [absent]
    assert dep["install_enabled"] is True
