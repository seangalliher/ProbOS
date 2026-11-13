"""AD-1359 follow-up (#1769): the code review's suggestions reach the build result, the failure report and the success event.

``CodeReviewAgent`` returns ``suggestions`` (the crew's size findings among them) and nothing read them. The executor
now carries them as ``BuildResult.review_suggestions`` whether or not the review approved, the failure report copies
them, and the approval route's success event carries them and counts them in its message. Real git in repositories
under ``tmp_path`` (helpers copied from the BF-904a and BF-904b tests), the real executor, the real ``CodeReviewAgent``
over a fake model client and the real ``_execute_build``. The cases marked ``built`` fail on the base at their own
assert and pass once M2 is applied; ``--runxfail`` runs them as plain cases. Synthetic text only.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import (
    BuildFailureReport,
    BuildResult,
    BuildSpec,
    classify_build_failure,
    execute_approved_build,
)
from probos.events import EventType

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
BAD = "src/probos/bad.py"
BROKEN = "def broken(:\n"
SUGGESTIONS = ["Delete the unused helper; the spec does not need it", "Name the size of the change in the summary"]

# The real runner, captured at import: the tests' own git calls go through it.
_REAL_RUN = subprocess.run

built = pytest.mark.xfail(raises=AssertionError, strict=True)


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``GIT_*`` name from the process environment for the test's duration."""
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "ad1359@example.invalid"),
        ("config", "user.name", "AD1359 Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    target = path / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x = 1\n")
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _spec() -> BuildSpec:
    return BuildSpec(title="ad1359 probe", description="")


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _reply(*, approved: bool, issues: list[str], suggestions: object, summary: str) -> str:
    """The review's JSON as the code review agent asks the model to write it."""
    return json.dumps({"approved": approved, "issues": issues, "suggestions": suggestions, "summary": summary})


class _FakeModel:
    """A model client whose every answer is *reply*: the code review is the only call a build without tests makes."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=SimpleNamespace(content=reply))


class _Runtime:
    """What the approval route reads from a runtime: ``emit_event`` and ``llm_client``. It has no config, so the
    sealed-core observation is off."""

    def __init__(self, llm_client: object | None = None) -> None:
        self.emit_event = MagicMock()
        self.llm_client = llm_client


def _route_modules() -> tuple[Any, Any]:
    """``(probos.api, probos.routers.build)``: the second takes its failure cache from the first, so it loads first."""
    import probos.api as api_module
    from probos.routers import build as build_router

    return api_module, build_router


def _events(rt: _Runtime, event_type: EventType) -> list[dict[str, Any]]:
    return [call.args[1] for call in rt.emit_event.call_args_list if call.args[0] == event_type]


def _one(items: list[Any], what: str) -> Any:
    assert len(items) == 1, f"expected exactly one {what}, found {len(items)}"
    return items[0]


def _committed() -> BuildResult:
    """What the executor returns for a build that committed, with no suggestions."""
    return BuildResult(
        success=True, spec=_spec(), branch_name="builder/probe", commit_hash="abc1234",
        files_written=[TARGET], tests_passed=True,
    )


async def _approve(build_router: Any, rt: _Runtime, repo: Path, changes: list[dict[str, Any]], build_id: str) -> None:
    """Run the approval route's background build over *repo*, bounded."""
    await asyncio.wait_for(
        build_router._execute_build(build_id, changes, _spec(), str(repo), rt, run_tests=False), timeout=120,
    )


# --- the seams, with real git ---------------------------------------------------------------------------------------


@needs_git
@built
async def test_a_reviews_suggestions_reach_the_success_event_through_the_real_executor(tmp_path: Path) -> None:
    _, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo")
    reply = _reply(approved=True, issues=[], suggestions=SUGGESTIONS, summary="Looks fine")
    rt = _Runtime(_FakeModel(reply))
    await _approve(build_router, rt, repo, [_modify(TARGET, "x = 1", "x = 2")], "t1")
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload["commit"], "premise: the build committed"
    assert payload["review"] == "Looks fine"
    assert payload["review_issues"] == []
    assert payload.get("review_suggestions") == SUGGESTIONS
    assert payload["message"].endswith(", Review suggestions: 2")


@needs_git
@built
@pytest.mark.parametrize(
    ("suggestions", "expected"),
    [
        pytest.param(["Delete the unused helper"], ["Delete the unused helper"], id="list"),
        pytest.param(None, [], id="null"),
    ],
)
async def test_a_rejected_review_keeps_its_issues_and_carries_its_suggestions(
    tmp_path: Path, suggestions: object, expected: list[str],
) -> None:
    repo = _init_repo(tmp_path / "repo")
    model = _FakeModel(_reply(approved=False, issues=["Bad import"], suggestions=suggestions, summary="Rejected"))
    result = await asyncio.wait_for(
        execute_approved_build(
            [_modify(TARGET, "x = 1", "x = 2")], _spec(), str(repo), run_tests=False, llm_client=model,
        ),
        timeout=120,
    )
    assert result.success is True, f"premise: the review is a soft gate and the build commits: {result.error}"
    assert result.review_issues == ["Bad import"]
    assert result.review_result == "Rejected"
    assert getattr(result, "review_suggestions", None) == expected


@needs_git
@built
async def test_a_failed_builds_report_carries_the_suggestions_through_the_real_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, build_router = _route_modules()
    cache: dict[str, Any] = {}
    monkeypatch.setattr(build_router, "_pending_failures", cache)  # keep the entry out of the shared cache
    repo = _init_repo(tmp_path / "repo")
    reply = _reply(approved=True, issues=[], suggestions=SUGGESTIONS, summary="Looks fine")
    rt = _Runtime(_FakeModel(reply))
    await _approve(build_router, rt, repo, [_create(BAD, BROKEN)], "t3")
    failure = _one(_events(rt, EventType.BUILD_FAILURE), "BUILD_FAILURE event")
    assert "report" in failure, "premise: the executor reported a failure and the route classified it"
    assert failure["report"].get("review_suggestions") == SUGGESTIONS
    assert getattr(cache["t3"]["report"], "review_suggestions", None) == SUGGESTIONS


# --- the route and the report, without git --------------------------------------------------------------------------


async def test_the_success_message_and_payload_are_unchanged_without_suggestions() -> None:
    _, build_router = _route_modules()
    rt = _Runtime()
    with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=_committed()):
        await build_router._execute_build("t4", [], _spec(), "unused", rt)
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload["message"] == "\u2b22 Build complete! Branch: builder/probe, Commit: abc1234, Files: 1, Tests: passed"
    old_keys = {
        "build_id", "branch", "commit", "files_written", "tests_passed", "test_result", "review", "review_issues",
        "message",
    }
    assert old_keys <= set(payload)


@built
async def test_the_success_event_carries_the_suggestions_and_their_count() -> None:
    _, build_router = _route_modules()
    rt = _Runtime()
    result = _committed()
    result.review_suggestions = ["first", "second", "third"]
    with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=result):
        await build_router._execute_build("t5", [], _spec(), "unused", rt)
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload.get("review_suggestions") == ["first", "second", "third"]
    assert payload["message"].endswith(", Review suggestions: 3")


@built
def test_a_build_result_starts_with_no_suggestions_of_its_own() -> None:
    first = BuildResult(success=True, spec=_spec())
    second = BuildResult(success=True, spec=_spec())
    assert getattr(first, "review_suggestions", None) == []
    assert getattr(second, "review_suggestions", None) == []
    first.review_suggestions.append("only the first")
    assert second.review_suggestions == [], "two results must not share one list"


@built
def test_a_failure_report_copies_the_results_suggestions() -> None:
    spec = _spec()
    result = BuildResult(success=False, spec=spec, error="Tests failed after 2 fix attempt(s).")
    result.review_suggestions = ["a", "b"]
    report = classify_build_failure(result, spec)
    assert getattr(report, "review_suggestions", None) == ["a", "b"]
    result.review_suggestions.append("later")
    assert report.review_suggestions == ["a", "b"], "the report holds a copy"


@built
def test_a_failure_reports_dict_carries_the_suggestions() -> None:
    report = BuildFailureReport()
    assert report.to_dict().get("review_suggestions") == []
    report.review_suggestions = ["a"]
    assert report.to_dict().get("review_suggestions") == ["a"]


@built
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, [], id="null"),
        pytest.param("a lone suggestion", ["a lone suggestion"], id="bare-string"),
        pytest.param([], [], id="empty-list"),
        pytest.param(["keep", "", "   ", None, 3, {"k": "v"}], ["keep", "3", "{'k': 'v'}"], id="mixed-items"),
        pytest.param(("x", "y"), ["x", "y"], id="tuple"),
        pytest.param({"k": "v"}, [], id="mapping"),
        pytest.param(5, [], id="number"),
    ],
)
def test_the_reviews_suggestions_are_coerced_to_non_blank_strings(raw: object, expected: list[str]) -> None:
    helper = getattr(builder_module, "_review_suggestions", None)
    assert helper is not None, "the helper does not exist yet"
    assert helper(raw) == expected
