"""AD-1073 (#1009): approval-gated dependency install in the AD-1066 run_python
loop tool.

A missing third-party import is detected, routed through the existing
approval-gated ``runtime.ensure_dependency`` machinery (AD-838c), and the outcome
is surfaced in the tool result. Default-OFF is byte-identical to AD-1066; a
declined / unavailable approval honest-degrades (the script runs and reports the
import error). The resolver + ensure_dependency are FAKED so no real pip runs and
the detect/approve outcome is deterministic.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from probos.cognitive.dependency_resolver import DependencyResult
from probos.config import DependencyConfig, ExecutionConfig
from probos.tools.code_execution_tool import CodeExecutionTool


class _FakeResolver:
    def __init__(self, missing: list[str]) -> None:
        self._missing = missing
        self.detect_calls = 0

    def detect_missing(self, code: str) -> list[str]:
        self.detect_calls += 1
        return list(self._missing)


def _runtime(
    tmp_path: Path,
    *,
    dep_enabled: bool,
    missing: list[str],
    result: DependencyResult | None = None,
    raises: bool = False,
    with_resolver: bool = True,
):
    resolver = _FakeResolver(missing) if with_resolver else None
    rt = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=True, scratch_dir=str(tmp_path / "scratch")),
            dependency=DependencyConfig(dynamic_install_enabled=dep_enabled),
        ),
        dependency_resolver=resolver,
        artifact_store=None,
        attachment_store=None,
    )
    rt.ensure_calls = []

    async def _ensure(names, **_kwargs):
        # AD-1220 added `requested_by`. Absorbed with **kwargs rather than
        # pinned: this stub asserts on the NAMES passed through, so the
        # keyword set is incidental and pinning it would only make the stub
        # break again on the next additive option (the BF-678 class).
        rt.ensure_calls.append(list(names))
        if raises:
            raise RuntimeError("boom")
        return result

    rt.ensure_dependency = _ensure
    return rt


def _ctx():
    return {"thread_id": "thread-1", "agent_id": "ezri"}


_CODE = "print('ran')\n"


async def test_default_off_is_byte_identical(tmp_path) -> None:
    rt = _runtime(tmp_path, dep_enabled=False, missing=["reportlab"])
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    assert result.error is None
    # No detection, no install, no extra output key — exactly the AD-1066 shape.
    assert "dependencies" not in result.output
    assert rt.dependency_resolver.detect_calls == 0
    assert rt.ensure_calls == []


async def test_missing_detected_and_installed_on_approval(tmp_path) -> None:
    rt = _runtime(
        tmp_path, dep_enabled=True, missing=["reportlab"],
        result=DependencyResult(success=True, installed=["reportlab"]),
    )
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    assert result.error is None
    dep = result.output["dependencies"]
    assert dep["missing"] == ["reportlab"]
    assert dep["installed"] == ["reportlab"]
    assert dep["declined"] == []
    assert rt.ensure_calls == [["reportlab"]]


async def test_declined_honest_degrades(tmp_path) -> None:
    rt = _runtime(
        tmp_path, dep_enabled=True, missing=["reportlab"],
        result=DependencyResult(
            success=False, declined=["reportlab"], error="approval callback unavailable",
        ),
    )
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    # The run itself still completes — the agent reports the gap honestly.
    assert result.error is None
    dep = result.output["dependencies"]
    assert dep["installed"] == []
    assert dep["declined"] == ["reportlab"]
    assert dep["error"] == "approval callback unavailable"


async def test_failed_install_reported_as_declined(tmp_path) -> None:
    rt = _runtime(
        tmp_path, dep_enabled=True, missing=["reportlab"],
        result=DependencyResult(success=False, failed=["reportlab"], error="pip failed"),
    )
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    dep = result.output["dependencies"]
    assert dep["installed"] == []
    assert dep["declined"] == ["reportlab"]  # failed folds into declined for the summary


async def test_nothing_missing_adds_no_key(tmp_path) -> None:
    rt = _runtime(tmp_path, dep_enabled=True, missing=[])
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    assert result.error is None
    assert "dependencies" not in result.output
    assert rt.dependency_resolver.detect_calls == 1  # detection ran, found nothing
    assert rt.ensure_calls == []


async def test_ensure_dependency_raising_honest_degrades(tmp_path) -> None:
    rt = _runtime(tmp_path, dep_enabled=True, missing=["reportlab"], raises=True)
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    assert result.error is None
    dep = result.output["dependencies"]
    assert dep["error"] == "install attempt failed"
    assert dep["installed"] == []
    assert dep["declined"] == []


async def test_no_resolver_adds_no_key(tmp_path) -> None:
    rt = _runtime(tmp_path, dep_enabled=True, missing=["reportlab"], with_resolver=False)
    tool = CodeExecutionTool(runtime=rt)
    result = await tool.invoke({"code": _CODE}, _ctx())

    assert result.error is None
    assert "dependencies" not in result.output
    assert rt.ensure_calls == []
