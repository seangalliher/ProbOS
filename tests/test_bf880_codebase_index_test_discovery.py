"""BF-880 (#1444): ``CodebaseIndex.find_tests_for()`` finds the project's tests.

The production index is built over ``src/probos`` (``startup/agent_fleet.py``)
while the suite lives in ``tests/`` beside ``src``. The index lists that suite
by name, ranks and bounds the matches, reads what it returns, keeps the suite
out of every other query, and each consumer receives it end to end.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive import codebase_index as _index_module
from probos.cognitive.architect import ArchitectAgent
from probos.cognitive.codebase_index import CodebaseIndex
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.swe_harness.tools import CodebaseFindTestsTool
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage

_LOGGER = "probos.cognitive.codebase_index"
_FLEET = Path(importlib.util.find_spec("probos.startup.agent_fleet").origin).resolve()
_PROJECT_ROOT = _FLEET.parent.parent.parent.parent


@pytest.fixture(scope="module")
def production_index() -> CodebaseIndex:
    """Built as ``agent_fleet`` builds it, through the real build rather than the test memo."""
    construction = "CodebaseIndex(source_root=Path(__file__).resolve().parent.parent)"
    assert construction in _FLEET.read_text(encoding="utf-8"), "premise: agent_fleet's index topology changed"
    index = CodebaseIndex(source_root=_FLEET.parent.parent)
    inspect.unwrap(CodebaseIndex.build)(index)
    return index


def _project(
    tmp_path: Path,
    suite: dict[str, str],
    sources: dict[str, str] | None = None,
    suite_dirs: tuple[str, ...] = (),
) -> CodebaseIndex:
    source_root = tmp_path / "src" / "probos"
    for rel, text in (sources or {"alpha.py": '"""Alpha."""\n'}).items():
        (source_root / rel).parent.mkdir(parents=True, exist_ok=True)
        (source_root / rel).write_text(text, encoding="utf-8")
    for rel in suite_dirs:
        (tmp_path / "tests" / rel).mkdir(parents=True)
    for rel, text in suite.items():
        (tmp_path / "tests" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "tests" / rel).write_text(text, encoding="utf-8")
    index = CodebaseIndex(source_root=source_root)
    index.build()
    return index


def _named(*names: str) -> dict[str, str]:
    return {name: f'"""{name}"""\n' for name in names}


def _invocation(**arguments: object) -> MagicMock:
    invocation = MagicMock()
    invocation.arguments = arguments
    return invocation


def test_the_production_index_finds_and_reads_real_tests(production_index: CodebaseIndex) -> None:
    on_disk = _PROJECT_ROOT / "tests" / "test_codebase_index.py"
    assert on_disk.is_file() and (_PROJECT_ROOT / "tests" / "test_experience_panels.py").is_file(), "premise"

    found = production_index.find_tests_for("cognitive/codebase_index.py")
    header = production_index.read_source(found[0], start_line=1, end_line=5)

    assert found[0] == "tests/test_codebase_index.py"
    assert "tests/test_experience_panels.py" in production_index.find_tests_for("experience/panels.py")
    assert header.strip() and header == "".join(on_disk.read_text(encoding="utf-8").splitlines(keepends=True)[:5])
    assert not any(key.startswith("tests/") for key in production_index._file_tree), (
        "a source subpackage named tests would make the bare tests/ paths ambiguous"
    )


def test_matches_rank_exact_then_prefixed_then_whole_word(tmp_path: Path) -> None:
    # NTFS lists test_ab_alpha before test_a_alpha; codepoint order is the reverse.
    index = _project(tmp_path, _named(
        "test_ab_alpha.py", "test_a_alpha.py", "test_alpha_extra.py", "test_alpha.py",
        "test_alphabet.py", "test_xalpha.py", "test_beta.py",
    ))

    assert index.find_tests_for("pkg/alpha.py") == [
        "tests/test_alpha.py", "tests/test_alpha_extra.py", "tests/test_a_alpha.py", "tests/test_ab_alpha.py",
    ]


def test_at_most_five_best_ranked_matches_are_returned(tmp_path: Path) -> None:
    index = _project(tmp_path, _named("test_alpha.py", *(f"test_alpha_{n}.py" for n in "abcdef")))

    assert index.find_tests_for("alpha.py") == ["tests/test_alpha.py"] + [f"tests/test_alpha_{n}.py" for n in "abcd"]


def test_returned_paths_round_trip_through_read_source(tmp_path: Path) -> None:
    index = _project(tmp_path, {"test_alpha.py": '"""Alpha tests."""\n\nimport pytest\n'})

    (path,) = index.find_tests_for("alpha.py")

    assert path == "tests/test_alpha.py"
    assert index.read_source(path) == '"""Alpha tests."""\n\nimport pytest\n'
    assert index.read_source(path.replace("/", "\\"), start_line=1, end_line=1) == '"""Alpha tests."""\n'


def test_only_top_level_test_modules_are_indexed(tmp_path: Path) -> None:
    index = _project(
        tmp_path,
        _named("test_alpha.py", "conftest.py", "helper_alpha.py", "__init__.py", "test_alpha.json", "fixtures/test_alpha_nested.py"),
        suite_dirs=("test_alpha_dir.py",),
    )

    assert index._test_files == ("tests/test_alpha.py",)
    assert index.find_tests_for("alpha.py") == ["tests/test_alpha.py"]


def test_read_source_reads_only_indexed_test_files_inside_tests(tmp_path: Path) -> None:
    index = _project(tmp_path, {"test_alpha.py": "x = 1\n", "conftest.py": "SECRET = 1\n", "fixtures/test_alpha_nested.py": "SECRET = 2\n"})
    (tmp_path / "outside.py").write_text("SECRET = 3\n", encoding="utf-8")

    for refused in (
        "tests/conftest.py",
        "tests/fixtures/test_alpha_nested.py",
        "tests/../outside.py",
        "../../outside.py",
        str(tmp_path / "tests" / "test_alpha.py"),
    ):
        assert index.read_source(refused) == "", refused
    index._test_files = ("tests/../outside.py",)  # a listed name that escapes the tests root
    assert index.read_source("tests/../outside.py") == ""


def test_a_file_without_tests_and_non_module_paths_get_nothing(tmp_path: Path) -> None:
    index = _project(tmp_path, _named("test_alpha.py", "test_.py"))

    for path in ("gamma.py", "pkg/__init__.py", "alpha.md", "docs:ALPHA.md", "alpha", "", ".py"):
        assert index.find_tests_for(path) == [], path
    assert index.find_tests_for("PKG\\Alpha.PY") == ["tests/test_alpha.py"]


def test_test_files_stay_out_of_every_other_query(tmp_path: Path) -> None:
    sources = {
        "alpha.py": '"""Alpha service."""\n\nclass TrustNetwork:\n    def run(self) -> None:\n        pass\n',
        "beta.py": '"""Beta."""\n\nfrom probos.alpha import TrustNetwork\n',
    }
    suite = (
        '"""Alpha tests."""\n\nfrom probos.alpha import TrustNetwork\nfrom probos.substrate.agent import BaseAgent\n\n\n'
        "class TrustNetwork:\n    def leaked(self) -> None:\n        TrustNetwork().run()\n\n\n"
        'class AlphaProbeAgent(BaseAgent):\n    agent_type = "alpha_probe"\n'
    )
    index = _project(tmp_path, {"test_alpha.py": suite}, sources=sources)
    assert index.find_tests_for("alpha.py") == ["tests/test_alpha.py"], "premise: the suite file is indexed"

    assert sorted(index._file_tree) == ["alpha.py", "beta.py"]
    assert [m["path"] for m in index.query("alpha")["matching_files"]] == ["alpha.py"]
    assert [c["path"] for c in index.find_callers("run")] == ["alpha.py"]
    assert index.get_layer_map() == {"root": ["alpha.py", "beta.py"]}
    assert index.find_importers("alpha.py") == ["beta.py"]
    assert index.get_agent_map() == []
    assert [m["method"] for m in index.get_api_surface("TrustNetwork")] == ["run"]


def test_an_install_without_a_suite_indexes_no_tests_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source_root = tmp_path / "src" / "probos"
    source_root.mkdir(parents=True)
    (source_root / "alpha.py").write_text('"""Alpha."""\n', encoding="utf-8")
    (tmp_path / "test_alpha.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # BF-880 A-1: with no suite, nothing else -- not the working directory -- is listed
    index = CodebaseIndex(source_root=source_root)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert index._built and "alpha.py" in index._file_tree
    assert index._test_files == () and index.find_tests_for("alpha.py") == []
    assert not [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING], caplog.text


def test_an_unlistable_suite_disables_discovery_without_failing_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source_root = tmp_path / "src" / "probos"
    source_root.mkdir(parents=True)
    (source_root / "alpha.py").write_text('"""Alpha."""\n', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alpha.py").write_text("x = 1\n", encoding="utf-8")
    blocked = (tmp_path / "tests").resolve()
    real_scandir = os.scandir
    refused: list[object] = []

    def refusing(path: object = ".") -> object:
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == blocked:
            refused.append(path)
            raise PermissionError(13, "simulated: permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", refusing)
    index = CodebaseIndex(source_root=source_root)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert refused, "the refusal was never exercised"
    assert index._built and "alpha.py" in index._file_tree
    assert index._test_files == () and index.find_tests_for("alpha.py") == []
    assert "could not be listed" in caplog.text


@pytest.mark.asyncio
async def test_the_architect_context_carries_discovered_test_headers(production_index: CodebaseIndex) -> None:
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.codebase_index = production_index
    llm = AsyncMock(spec=BaseLLMClient)
    llm.complete.return_value = MagicMock(content="experience/panels.py")
    agent = ArchitectAgent(agent_id="bf880-architect", llm_client=llm, runtime=runtime)

    obs = await agent.perceive(
        IntentMessage(intent="design_feature", params={"feature": "panel rendering", "phase": ""})
    )

    header = production_index.read_source("tests/test_experience_panels.py", start_line=1, end_line=5)
    assert header.strip(), "premise: the header is readable"
    assert "## Associated Test Files" in obs["codebase_context"]
    assert f"### tests/test_experience_panels.py\n```python\n{header}\n```" in obs["codebase_context"]


@pytest.mark.asyncio
async def test_the_copilot_adapter_reads_what_its_find_tests_tool_returns(production_index: CodebaseIndex) -> None:
    adapter = CopilotBuilderAdapter(codebase_index=production_index)

    found = await adapter._handle_find_tests(_invocation(file_path="experience/panels.py"))
    paths = json.loads(found.text_result_for_llm)
    read = await adapter._handle_read_source(_invocation(file_path=paths[0], start_line=1, end_line=5))

    assert paths[0] == "tests/test_experience_panels.py"
    assert read.text_result_for_llm == production_index.read_source(paths[0], start_line=1, end_line=5)
    assert read.text_result_for_llm.strip()


@pytest.mark.asyncio
async def test_the_swe_harness_tool_returns_the_ranked_tests(production_index: CodebaseIndex) -> None:
    tool = CodebaseFindTestsTool(SimpleNamespace(codebase_index=production_index))

    result = await tool.invoke({"file_path": "cognitive/codebase_index.py"})

    assert result.error is None
    assert result.output == production_index.find_tests_for("cognitive/codebase_index.py")
    assert result.output[0] == "tests/test_codebase_index.py"


# BF-880 A-1: the suite and its files are read only as the project's own, unredirected tests directory.
_A1_SECRET = 'SECRET = "EXTERNAL_PRIVATE_FILE"\n'


def _a1_project(tmp_path: Path, suite: dict[str, str] | None = None) -> Path:
    """A project at ``tmp_path/project``, so ``tmp_path/outside`` lies outside it but inside ``tmp_path``."""
    project = tmp_path / "project"
    (project / "src" / "probos").mkdir(parents=True)
    (project / "src" / "probos" / "alpha.py").write_text('"""Alpha."""\n', encoding="utf-8")
    for name, text in (suite or {}).items():
        (project / "tests").mkdir(exist_ok=True)
        (project / "tests" / name).write_text(text, encoding="utf-8")
    return project


def _a1_outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_alpha.py").write_text(_A1_SECRET, encoding="utf-8")
    return outside


def _a1_redirect(link: Path, target: Path) -> None:
    """Point ``link`` at the directory ``target``: a junction on Windows, which needs no privilege; a symlink elsewhere."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"the OS refused to create a directory link: {exc}")
    assert os.path.isjunction(link) or os.path.islink(link), "premise: the directory link was created"


def _a1_link_file(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"the OS refused to create a symbolic link: {exc}")
    assert os.path.islink(link), "premise: the test file is a link"


def _a1_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_a1_suite_root_junction_outside_the_project_is_neither_listed_nor_read(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path)
    _a1_redirect(project / "tests", _a1_outside(tmp_path))
    assert (project / "tests" / "test_alpha.py").read_text(encoding="utf-8") == _A1_SECRET, (
        "premise: the junction exposes the outside file"
    )
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()
        assert index.read_source("docs:../outside/test_alpha.py") == "", "premise: a docs: read refuses it"
        copilot = await CopilotBuilderAdapter(codebase_index=index)._handle_read_source(
            _invocation(file_path="tests/test_alpha.py")
        )
        observed = {
            "listed": index.find_tests_for("alpha.py"),
            "read": index.read_source("tests/test_alpha.py"),
            "copilot": copilot.text_result_for_llm,
        }

    assert observed == {"listed": [], "read": "", "copilot": "(empty or not found)"}
    warnings = _a1_warnings(caplog)
    assert len(warnings) == 1 and "symbolic link or junction" in warnings[0], warnings
    assert "EXTERNAL_PRIVATE_FILE" not in caplog.text


def test_a1_suite_root_swapped_for_a_junction_after_build_is_not_read(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "REAL = 1\n"})
    outside = _a1_outside(tmp_path)
    index = CodebaseIndex(source_root=project / "src" / "probos")
    index.build()
    assert index.read_source("tests/test_alpha.py") == "REAL = 1\n", "premise: the real suite file reads"

    shutil.rmtree(project / "tests")
    _a1_redirect(project / "tests", outside)
    assert (project / "tests" / "test_alpha.py").read_text(encoding="utf-8") == _A1_SECRET, (
        "premise: the swapped-in junction serves the outside copy under the listed name"
    )

    assert index.find_tests_for("alpha.py") == ["tests/test_alpha.py"], "premise: still listed from the build"
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert index.read_source("tests/test_alpha.py") == ""
    assert _a1_warnings(caplog) == [], "the refusal warns once, at build, never per read"


def test_a1_a_linked_test_file_is_skipped(tmp_path: Path) -> None:
    project = _a1_project(tmp_path, {"test_real.py": "REAL = 1\n"})
    outside = _a1_outside(tmp_path)
    _a1_link_file(project / "tests" / "test_alpha.py", outside / "test_alpha.py")
    assert (project / "tests" / "test_alpha.py").read_text(encoding="utf-8") == _A1_SECRET, (
        "premise: the link exposes the outside file"
    )
    index = CodebaseIndex(source_root=project / "src" / "probos")

    index.build()

    assert index._test_files == ("tests/test_real.py",)
    assert index.find_tests_for("alpha.py") == [] and index.read_source("tests/test_alpha.py") == ""


def test_a1_a_test_file_swapped_for_a_link_after_build_is_not_read(tmp_path: Path) -> None:
    # The link stays inside tests/, so the bounds alone would pass it: only the read-time link check refuses.
    project = _a1_project(tmp_path, {"test_alpha.py": "REAL = 1\n", "conftest.py": "UNLISTED = 1\n"})
    index = CodebaseIndex(source_root=project / "src" / "probos")
    index.build()
    assert index.read_source("tests/test_alpha.py") == "REAL = 1\n", "premise: the listed file reads"

    (project / "tests" / "test_alpha.py").unlink()
    _a1_link_file(project / "tests" / "test_alpha.py", project / "tests" / "conftest.py")
    assert (project / "tests" / "test_alpha.py").read_text(encoding="utf-8") == "UNLISTED = 1\n", (
        "premise: the link serves a file the listing never names"
    )

    assert index.read_source("tests/test_alpha.py") == ""


def test_a1_a_redirect_the_link_checks_miss_is_refused_by_where_it_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Stands in for a redirect os.path cannot classify; resolution still follows it.
    project = _a1_project(tmp_path)
    _a1_redirect(project / "tests", _a1_outside(tmp_path))
    monkeypatch.setattr(os.path, "islink", lambda path: False)
    monkeypatch.setattr(os.path, "isjunction", lambda path: False)
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert index.find_tests_for("alpha.py") == [] and index.read_source("tests/test_alpha.py") == ""
    warnings = _a1_warnings(caplog)
    assert len(warnings) == 1 and "resolves outside" in warnings[0], warnings


@pytest.mark.parametrize("through_link", [False, True], ids=["direct", "project-reached-through-a-link"])
def test_a1_a_real_suite_lists_and_reads_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, through_link: bool
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "A = 1\n", "test_alpha_more.py": "B = 2\n", "conftest.py": "C = 3\n"})
    if through_link:  # only the project root is reached through the link; its tests child stays its own
        _a1_redirect(tmp_path / "alias", project)
        project = tmp_path / "alias"
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()
        observed = (
            index._test_files,
            index.find_tests_for("alpha.py"),
            index.read_source("tests/test_alpha.py"),
            index.read_source("tests\\test_alpha_more.py", start_line=1, end_line=1),
        )

    assert observed == (
        ("tests/test_alpha.py", "tests/test_alpha_more.py"),
        ["tests/test_alpha.py", "tests/test_alpha_more.py"],
        "A = 1\n",
        "B = 2\n",
    )
    assert _a1_warnings(caplog) == []


# BF-880 A-2: a listed file that is swapped or cannot be read reads empty, never raising, and the listing is re-validated.
_A2_RECHECK = "changed while it was listed"


def _a2_is_link(path: Path) -> bool:
    return os.path.isjunction(path) or os.path.islink(path)


def _a2_unlink(link: Path) -> None:
    """Remove a directory link itself, never its target (on Windows a junction is removed as a directory)."""
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)


def _a2_file_junction(link: Path, target: Path) -> None:
    """Point ``link`` at the FILE ``target`` through a junction; elsewhere a link is a symlink, which A-1 refuses first."""
    if os.name != "nt":
        pytest.skip("a junction to a file is a Windows construct; other hosts make symlinks, refused before resolving")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:
        pytest.skip(f"the OS refused to create a junction to a file: {exc}")
    assert os.path.isjunction(link), "premise: the listed name is now a junction"


def _a2_swap_suite_for_link(project: Path, outside: Path) -> None:
    """Move the real suite aside, where it keeps its identity, and put a link to ``outside`` in its place."""
    os.rename(project / "tests", project / "tests_aside")
    _a1_redirect(project / "tests", outside)


def _a2_record_listing(
    monkeypatch: pytest.MonkeyPatch,
    suite: Path,
    *,
    on_open: Callable[[], None] | None = None,
    on_close: Callable[[], None] | None = None,
) -> list[str]:
    """Route the index module's ``os.scandir`` of ``suite`` through a recorder; returns the names the listing yields.

    ``on_open`` runs once, just before the real ``scandir`` opens the path; ``on_close`` runs once the listing is
    closed, before anything after it. Every other path is listed untouched.
    """
    real_scandir = _index_module.os.scandir
    seen: list[str] = []
    opened: list[bool] = []

    class _Recorded:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __enter__(self) -> _Recorded:
            return self

        def __exit__(self, *exc_info: object) -> None:
            self._inner.close()
            if on_close is not None:
                on_close()

        def __iter__(self) -> Iterator[os.DirEntry[str]]:
            for entry in self._inner:
                seen.append(entry.name)
                yield entry

    def scandir(path: object = ".") -> object:
        if isinstance(path, (str, os.PathLike)) and Path(path) == suite and not opened:
            opened.append(True)
            if on_open is not None:
                on_open()
            return _Recorded(real_scandir(path))
        return real_scandir(path)

    monkeypatch.setattr(_index_module.os, "scandir", scandir)
    return seen


def _a2_assert_discarded(index: CodebaseIndex, caplog: pytest.LogCaptureFixture, reason: str) -> None:
    assert index._test_files == () and index.find_tests_for("alpha.py") == []
    assert index.read_source("tests/test_alpha.py") == ""
    assert "test_alpha" not in caplog.text and "EXTERNAL_PRIVATE_FILE" not in caplog.text, caplog.text
    warnings = _a1_warnings(caplog)
    assert len(warnings) == 1 and _A2_RECHECK in warnings[0] and reason in warnings[0], warnings


@pytest.mark.asyncio
async def test_a2_a_listed_file_swapped_for_a_file_junction_reads_empty_and_never_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "REAL = 1\n"})
    outside_file = _a1_outside(tmp_path) / "test_alpha.py"
    index = CodebaseIndex(source_root=project / "src" / "probos")
    index.build()
    assert index.read_source("tests/test_alpha.py") == "REAL = 1\n", "premise: the listed file reads"

    listed = project / "tests" / "test_alpha.py"
    listed.unlink()
    _a2_file_junction(listed, outside_file)
    with pytest.raises(OSError):  # premise: resolving the swapped name raises, which the unguarded read let escape
        listed.resolve()

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        read = index.read_source("tests/test_alpha.py")
        copilot = await CopilotBuilderAdapter(codebase_index=index)._handle_read_source(
            _invocation(file_path="tests/test_alpha.py")
        )

    assert (read, copilot.text_result_for_llm) == ("", "(empty or not found)")
    assert _a1_warnings(caplog) == [], "a read never warns"


def test_a2_a_listed_file_that_cannot_be_read_reads_empty_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "REAL = 1\n"})
    index = CodebaseIndex(source_root=project / "src" / "probos")
    index.build()
    locked = (project / "tests" / "test_alpha.py").resolve()
    real_read_text = Path.read_text
    refused: list[Path] = []

    def refusing(self: Path, *args: object, **kwargs: object) -> str:
        if self == locked:
            refused.append(self)
            raise PermissionError(13, "simulated: held open exclusively by another process", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refusing)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        read = index.read_source("tests/test_alpha.py")

    assert refused, "premise: the read itself raised"
    assert read == ""
    assert _a1_warnings(caplog) == [], "a read never warns"


@pytest.mark.parametrize("swap", ["removed", "a-directory"])
def test_a2_a_listed_file_removed_or_replaced_by_a_directory_reads_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, swap: str
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "REAL = 1\n"})
    index = CodebaseIndex(source_root=project / "src" / "probos")
    index.build()
    listed = project / "tests" / "test_alpha.py"
    listed.unlink()
    if swap == "a-directory":
        listed.mkdir()

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        read = index.read_source("tests/test_alpha.py")

    assert index.find_tests_for("alpha.py") == ["tests/test_alpha.py"], "premise: still listed from the build"
    assert read == ""
    assert _a1_warnings(caplog) == [], "a read never warns"


def test_a2_a_suite_root_swapped_during_the_listing_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path, {"test_real.py": "REAL = 1\n"})
    outside = _a1_outside(tmp_path)
    seen = _a2_record_listing(monkeypatch, project / "tests", on_open=lambda: _a2_swap_suite_for_link(project, outside))
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert seen == ["test_alpha.py"] and _a2_is_link(project / "tests"), (
        "premise: the listing ran over the outside directory swapped in after the suite root was validated"
    )
    _a2_assert_discarded(index, caplog, "no longer the project's own tests directory")


def test_a2_a_suite_root_swapped_right_after_its_validation_is_caught_by_the_re_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Swapped before the listing takes the suite root's identity: the identities agree, the re-validation does not.
    project = _a1_project(tmp_path, {"test_real.py": "REAL = 1\n"})
    outside = _a1_outside(tmp_path)
    suite = project / "tests"
    real_resolve = Path.resolve
    swapped: list[bool] = []

    def resolve_then_swap(self: Path, strict: bool = False) -> Path:
        resolved = real_resolve(self, strict=strict)
        if self == suite and not swapped:  # the build's validation of the suite root has just resolved it
            swapped.append(True)
            _a2_swap_suite_for_link(project, outside)
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve_then_swap)
    seen = _a2_record_listing(monkeypatch, suite)
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert swapped and seen == ["test_alpha.py"], "premise: the suite root was swapped after its validation"
    _a2_assert_discarded(index, caplog, "no longer the project's own tests directory")


def test_a2_a_suite_root_replaced_during_the_listing_is_caught_by_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Listed through a link that is then replaced by a new real directory: re-validation passes, identity does not.
    project = _a1_project(tmp_path, {"test_real.py": "REAL = 1\n"})
    outside = _a1_outside(tmp_path)
    suite = project / "tests"

    def replace_the_link_with_a_new_directory() -> None:
        _a2_unlink(suite)
        suite.mkdir()

    seen = _a2_record_listing(
        monkeypatch,
        suite,
        on_open=lambda: _a2_swap_suite_for_link(project, outside),
        on_close=replace_the_link_with_a_new_directory,
    )
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()

    assert seen == ["test_alpha.py"] and suite.is_dir() and not _a2_is_link(suite), "premise: listed through a link"
    assert _index_module._suite_root(project) == suite, "premise: the final suite root passes re-validation"
    _a2_assert_discarded(index, caplog, "was replaced")


def test_a2_a_real_suite_lists_as_before_through_the_post_listing_re_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    project = _a1_project(tmp_path, {"test_alpha.py": "A = 1\n", "test_alpha_more.py": "B = 2\n", "conftest.py": "C = 3\n"})
    seen = _a2_record_listing(monkeypatch, project / "tests")  # recorded, nothing swapped
    index = CodebaseIndex(source_root=project / "src" / "probos")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        index.build()
        observed = (index._test_files, index.find_tests_for("alpha.py"), index.read_source("tests/test_alpha.py"))

    assert sorted(seen) == ["conftest.py", "test_alpha.py", "test_alpha_more.py"], "premise: listed through the recorder"
    assert observed == (
        ("tests/test_alpha.py", "tests/test_alpha_more.py"),
        ["tests/test_alpha.py", "tests/test_alpha_more.py"],
        "A = 1\n",
    )
    assert _a1_warnings(caplog) == []
