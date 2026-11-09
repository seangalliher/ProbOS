"""BF-943 (#1707): agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout.

The rule is ``builder_paths.captain_document_write_refusal``; the writers are ``write_file``, ``edit_file``, ``FileWriterAgent`` and the four
office writers, run on a temporary layout in production's shape: the running checkout is ``<tmp>/checkout`` (``_DEFAULT_ORDERS_DIR`` points
into it), ``swe_tools._PROJECT_ROOT`` is ``<checkout>/src``, the working directory is the checkout, the home directory is a temporary one.
The class holds the cases the unfixed tree fails; the functions before it pass on both. No BF-943 name is imported: the rule is looked up
once and, on the tree without it, refuses nothing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool, register_native_swe_tools
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from tests.test_ad1344_constitution_write_refusal import _CHANNEL_SUFFIXES, _build, _callee, _calls, _dir_link, _source, _tracked

_REPO = Path(__file__).resolve().parents[1]
_REAL = [_REPO / "CLAUDE.md", _REPO / "pyproject.toml", _REPO / "config" / "standing_orders" / "ship.md",
         _REPO / ".github" / "copilot-instructions.md"]
_BF, _BP = "BF-943", "src/probos/cognitive/builder_paths.py"
_RULE, _AD_RULE = "captain_document_write_refusal", "constitution_write_refusal"
_rule = getattr(builder_paths, _RULE, lambda path, root=None: None)  # without BF-943 nothing is refused
# One file per entry that exists today (a directory entry: one member), each holding "x v1"; and entries that exist nowhere today.
_FILES = ("config/standing_orders/ship.md", "config/standing_orders/crew_profiles/_default.yaml", "config/ontology/organization.yaml",
          "config/command_policy/starter.yaml", "config/sealed_modules.yaml", "CLAUDE.md", ".claude/agents/claude-builder.md",
          ".github/workflows/ci.yml", "pyproject.toml", "uv.lock", "ui/package.json", "ui/package-lock.json", "requirements-dev.txt")
_ABSENT = ("AGENTS.md", ".agents/skills/x.md", ".codex/config.toml", "requirements-extra.txt", "CODEOWNERS", ".github/CODEOWNERS",
           "docs/CODEOWNERS")
_NEIGHBOURS = ("docs/notes.md", "config/other.yaml", "config/standing_orders_notes.md", "pyproject.toml.bak", "requirements/dev.txt",
               "docs/CODEOWNERS.md", ".githubx/x.md")
_SPELLINGS = {"relative": lambda m: m, "dot-dot": lambda m: f"docs/../{m}", "case": str.upper, "trailing-dot": lambda m: m + ".",
              "trailing-space": lambda m: m + " ", "stream": lambda m: m + ":hidden"}
_SHORT = ("config/STANDI~9/ship.md", "PYPROJ~9.TOM", "GITHUB~9/workflows/ci.yml", "REQUIR~9.TXT")  # no such alias exists: lexical only
_WRITERS = ("write_file", "edit_file", "commit", "propose", "docx_create", "pptx_create")  # each reaches any entry
_OFFICE = ("docx_revise", "xlsx_update")  # each reaches a .docx or .xlsx under a directory entry
_LOG = {"write_file": ("WriteFileTool", "write_file"), "edit_file": ("EditFileTool", "edit_file"),
        "commit": ("FileWriterAgent", "commit_write"), "propose": ("FileWriterAgent", "propose_write"),
        "docx_create": ("DocxAgent", "docx_create"), "pptx_create": ("PptxAgent", "pptx_create"),
        "docx_revise": ("DocxAgent", "docx_revise"), "xlsx_update": ("XlsxAgent", "xlsx_update")}
_DIRECTORIES = ("config/standing_orders", "config/ontology", "config/command_policy", ".claude", ".agents", ".codex", ".github")
_EXPECTED_CALLERS = {("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
                     ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
                     ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
                     ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
                     ("src/probos/skill_framework.py", "DocxAgent.create_docx"), ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
                     ("src/probos/skill_framework.py", "PptxAgent.create_pptx"), ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx")}


@pytest.fixture(autouse=True)
def _real_documents_untouched():
    before = [(p.read_bytes(), os.stat(p).st_mode) for p in _REAL]
    yield
    assert [(p.read_bytes(), os.stat(p).st_mode) for p in _REAL] == before, "a real Captain document changed"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout"
    for rel in (*_FILES, "docs/notes.md", "config/other.yaml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x v1\n", encoding="utf-8")
    (root / "src").mkdir()
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", root / "config" / "standing_orders")
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", root / "src")
    monkeypatch.chdir(root)
    assert Path.cwd() == root.resolve() and standing_orders.standing_orders_dir().parent.parent == root, "premise: the layout"
    return root


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _link(source: Path, alias: Path) -> Path:
    alias.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, source), "premise: the alias is the same file"
    return alias


def _refused(reason: str | None) -> bool:
    return reason is not None and _BF in reason


def _office_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".docx":
        from docx import Document

        Document().save(str(path))
    else:
        from openpyxl import Workbook

        Workbook().save(str(path))
    return path


async def _call(writer: str, path: str) -> tuple[bool, str]:
    """(written, error) of one writer for a path; each keeps its own error shape (a result, a dict, a raise)."""
    if writer == "write_file":
        result = await WriteFileTool(SimpleNamespace()).invoke({"path": path, "content": "AMENDED\n"})
        return result.success, result.error or ""
    if writer == "edit_file":
        result = await EditFileTool(SimpleNamespace()).invoke({"path": path, "old_text": "v1", "new_text": "AMENDED"})
        return result.success, result.error or ""
    if writer == "commit":
        done = await FileWriterAgent.commit_write(path, "AMENDED\n")
        return done["success"], done.get("error", "")
    agent, intent, params = {
        "propose": (FileWriterAgent(pool="filesystem"), "write_file", {"path": path, "content": "AMENDED\n"}),
        "docx_create": (DocxAgent(pool="office"), "docx_create", {"title": "t", "content": ["x"], "output_path": path}),
        "pptx_create": (PptxAgent(pool="office"), "pptx_create",
                        {"title": "t", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": path}),
        "docx_revise": (DocxAgent(pool="office"), "docx_revise", {"file_path": path, "instructions": "amend"}),
        "xlsx_update": (XlsxAgent(pool="office"), "xlsx_update", {"file_path": path, "sheet": "Sheet", "updates": {"A1": "amended"}}),
    }[writer]
    if writer == "propose":
        await agent.start()
    try:
        result = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    except PermissionError as exc:
        return False, str(exc)
    return (result.success, result.error or "") if result else (False, "no result")


def _callers(*names: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for rel in _tracked("src/probos"):
        if rel.endswith(".py"):
            found |= {(rel, scope) for scope, call in _calls(_source(rel)) if _callee(call) in names}
    return found


# ── Guards and controls: these pass on both trees ─────────────────────────


def test_the_swe_root_is_the_src_directory_and_the_checkout_is_derived_from_the_orders() -> None:
    """T0, D2's premise: in production ``_PROJECT_ROOT`` is ``<checkout>/src``, and the orders directory lies two levels below the checkout."""
    root = Path(swe_tools.__file__).resolve().parents[3]
    assert swe_tools._PROJECT_ROOT == root and root.name == "src"
    assert standing_orders.standing_orders_dir() == root.parent / "config" / "standing_orders"


@pytest.mark.parametrize("writer", [*_WRITERS, *_OFFICE])
async def test_every_writer_writes_a_neighbour(checkout: Path, writer: str) -> None:
    """T1, the control round: the neighbour a refusal test pairs with is written by the same writer."""
    target = checkout / "docs" / ("n.docx" if writer == "docx_revise" else "n.xlsx" if writer == "xlsx_update" else "notes.md")
    if writer in _OFFICE:
        _office_file(target)
    before = target.read_bytes() if target.exists() else None
    written, error = await _call(writer, str(target))
    assert written, error
    assert writer == "propose" or before is None or target.read_bytes() != before  # a proposal writes nothing until the vote


@pytest.mark.parametrize("neighbour", _NEIGHBOURS)
def test_the_rule_allows_a_neighbour_and_a_document_in_another_tree(checkout: Path, tmp_path: Path, neighbour: str) -> None:
    """T2: a name that only looks like an entry, and documents in a tree that is neither root."""
    assert _rule(neighbour, checkout) is None and _rule(str(checkout / neighbour), checkout) is None
    for member in ("CLAUDE.md", "config/standing_orders/ship.md", ".github/workflows/ci.yml"):
        assert _rule(str(tmp_path / "other" / member), checkout) is None, member
    alias = _link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")
    assert _rule(str(alias), checkout) is None, "a file with another name that is no document's"


@pytest.mark.parametrize("member", ["config/standing_orders/ship.md", "config/ontology/organization.yaml", "CLAUDE.md"])
async def test_a_native_build_still_modifies_a_document_in_its_worktree(checkout: Path, member: str) -> None:
    """T3, acceptance 3: the build lane writes through ``builder_write_refusal``, not through this rule."""
    result, commit = await _build(checkout, [{"path": member, "mode": "modify", "replacements": [{"search": "v1", "replace": "v2"}]}])
    assert not result.error, result.error
    assert (checkout / member).read_text(encoding="utf-8") == "x v2\n" and member in commit.await_args.args[0]


async def test_a_lieutenants_unoffered_write_file_call_reaches_the_tool_on_the_dm_route(
    checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4, acceptance 1 and the severity: the DM route's executor runs a registered tool the model was never offered.

    The route builds ``DispatchToolExecutor(registry=)`` with no confinement and offers only the Captain's grants; the loop's call passes no
    ``required``, so ``check_and_invoke`` asks for READ, and the rank matrix gives a lieutenant WRITE. A pass on both trees (it is about the
    route, not the rule); if it fails the route is closed and P3-1 says Medium.
    """
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    reached: list[str] = []
    real = WriteFileTool.invoke

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    target = str(checkout / "docs" / "dm.md")
    result = await DispatchToolExecutor(registry=registry).invoke(
        agent_id="lt-1", tool_id="write_file", params={"path": target, "content": "x"},
        agent_department="engineering", agent_rank="lieutenant", context={})
    assert reached == [target] and result.success, result.error


def test_census_the_captains_channels_do_not_consult_the_rule() -> None:
    """T5, acceptance 5 (AD-1344's T36): no tracked script, hook or workflow names the rule or the set."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml") if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        text = (_REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert _RULE not in text and "CAPTAIN_DOCUMENT_PATHS" not in text, rel


# ── The cases the unfixed tree fails ──────────────────────────────────────


class TestWhatTheBaseDoesNotRefuse:
    @pytest.mark.parametrize("spelling", [*_SPELLINGS, "absolute", "absolute without a root"])
    @pytest.mark.parametrize("member", (*_FILES, *_ABSENT))
    def test_the_rule_refuses_every_entry_in_every_spelling(self, checkout: Path, member: str, spelling: str) -> None:
        """T10: relative, absolute (with and without a root), with ``..``, a case variant, a trailing dot or space, a stream."""
        if spelling.startswith("absolute"):
            refusal = _rule(str(checkout / member), None if spelling.endswith("root") else checkout)
        else:
            refusal = _rule(_SPELLINGS[spelling](member), checkout)
        assert _refused(refusal), refusal

    @pytest.mark.parametrize("form", _SHORT)
    def test_the_rule_refuses_an_8_3_short_form(self, checkout: Path, form: str) -> None:
        """T11: the lexical form, a ``~digit`` component with the first two characters of an entry's."""
        assert _refused(_rule(form, checkout)), form

    def test_the_rule_judges_the_checkout_and_the_writers_root(self, checkout: Path, tmp_path: Path) -> None:
        """T12, D2: the writer's root; the checkout reached from ``src`` by ``..`` or from another root by an absolute path."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        assert _refused(_rule("config/standing_orders/x.md", elsewhere)), "below the writer's root"
        assert _refused(_rule("../CLAUDE.md", checkout / "src")), "the checkout, from the SWE root"
        assert _refused(_rule(str(checkout / ".github" / "x.yml"), elsewhere)), "the checkout, from another root"
        assert _rule("../docs/n.md", checkout / "src") is None and _rule(str(elsewhere / "docs" / "n.md"), checkout) is None

    @pytest.mark.parametrize("where", ["docs/alias.md", "../outside/alias.md"])
    @pytest.mark.parametrize("member", _FILES)
    def test_a_hard_link_to_a_document_is_refused(self, checkout: Path, where: str, member: str) -> None:
        """T13: an existing file with another name that is a document's, under either root or outside both."""
        assert _refused(_rule(str(_link(checkout / member, (checkout / where).resolve())), checkout)), where

    def test_a_directory_link_is_refused_both_ways(self, checkout: Path) -> None:
        """T14: through a junction (a symlink off Windows) into a document directory; and for a document directory that is itself a link."""
        _dir_link(checkout / "docs" / "orders", checkout / "config" / "standing_orders")
        assert _refused(_rule("docs/orders/new.md", checkout)), "through a link"
        (checkout.parent / "codex-target").mkdir()
        _dir_link(checkout / ".codex", checkout.parent / "codex-target")
        assert _refused(_rule(".codex/config.toml", checkout)), "the written form of a document directory that is a link"

    def test_the_other_name_of_a_document_directory_that_is_a_link_is_refused(self, checkout: Path, tmp_path: Path) -> None:
        """T14b (A1, F1): a document directory that is itself a link is also its target's name, under the checkout's root and a writer's."""
        orders = tmp_path / "orders-real"
        shutil.move(str(checkout / "config" / "standing_orders"), str(orders))
        _dir_link(checkout / "config" / "standing_orders", orders)
        assert (checkout / "config" / "standing_orders").resolve() == orders.resolve() and (orders / "ship.md").is_file(), "premise: a link"
        for name in ("ship.md", "new.md", "crew_profiles/_default.yaml"):
            assert _refused(_rule(str(orders / name), checkout)), name
        assert _refused(_rule(str(orders / "ship.md"), checkout / "src")), "from the SWE root"
        assert _rule(str(tmp_path / "orders-real.md"), checkout) is None, "a neighbour of the target"
        workflows, elsewhere = tmp_path / "gh-real", tmp_path / "elsewhere"
        workflows.mkdir()
        elsewhere.mkdir()
        _dir_link(elsewhere / ".github", workflows)
        assert (elsewhere / ".github").resolve() == workflows.resolve(), "premise: the writer's own entry is a link"
        assert _refused(_rule(str(workflows / "ci.yml"), elsewhere)), "under the writer's root"

    def test_a_link_inside_a_document_directory_is_not_followed(self, checkout: Path) -> None:
        """T14c (A1, F3): a link to a directory inside an entry is not entered: a loop does not stop a neighbour, and a workflow's alias is found."""
        _dir_link(checkout / ".github" / "loop", checkout / ".github")
        assert (checkout / ".github" / "loop").resolve() == (checkout / ".github").resolve(), "premise: the link leads to its own parent"
        assert _rule(str(_link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")), checkout) is None
        assert _refused(_rule(str(_link(checkout / ".github" / "workflows" / "ci.yml", checkout / "docs" / "ci.md")), checkout))

    @pytest.mark.skipif(os.name != "nt", reason="the denied query is the Windows final-path query")
    def test_a_link_whose_final_path_cannot_be_queried_is_refused_not_taken_as_resolved(
        self, checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T14d (A2, R2-1): where a deny ACE on a link refuses the query of its final path (winerror 5), ``Path.resolve(strict=False)`` answers with
        the link's own name; the rule refuses a write through the target of an entry that is such a link, and through a path that goes through one."""
        import ntpath

        github, orders, up = tmp_path / "gh-real", checkout / "config" / "standing_orders", checkout / "docs" / "up"
        github.mkdir()
        (github / "member.txt").write_text("x\n", encoding="utf-8")
        shutil.rmtree(checkout / ".github")
        _dir_link(checkout / ".github", github)
        _dir_link(up, orders)
        assert (checkout / ".github").resolve() == github.resolve() and up.resolve() == orders.resolve(), "premise: two links"
        assert _refused(_rule(str(github / "member.txt"), checkout)) and _refused(_rule("docs/up/new.md", checkout)), "premise: refused while they resolve"
        denied = {os.path.normcase(str(checkout / ".github")), os.path.normcase(str(up))}

        def denying(real):  # type: ignore[no-untyped-def]
            def query(path):  # type: ignore[no-untyped-def]
                if os.path.normcase(os.fspath(path)).removeprefix("\\\\?\\") in denied:
                    raise OSError(13, "denied by the test", None, 5)
                return real(path)

            return query

        with monkeypatch.context() as patch:
            patch.setattr(ntpath, "_getfinalpathname", denying(ntpath._getfinalpathname))
            patch.setattr(ntpath, "_nt_readlink", denying(ntpath._nt_readlink))
            assert os.path.normcase(os.path.realpath(str(up))) == os.path.normcase(str(up)), "premise: the non-strict answer is the link's own name"
            through_entry = _rule(str(github / "member.txt"), checkout)
            through_path = _rule("docs/up/new.md", checkout)
        assert _refused(through_entry) and "(entries: PermissionError)" in through_entry, through_entry
        assert _refused(through_path) and "(resolved: PermissionError)" in through_path, through_path

    def test_a_link_whose_target_is_gone_is_followed_as_far_as_it_goes(self, checkout: Path, tmp_path: Path) -> None:
        """T14e (A2): an entry that is a link to a directory that is gone has that directory's name too: making the directory would make it live."""
        gone = tmp_path / "codex-gone"
        gone.mkdir()
        _dir_link(checkout / ".codex", gone)
        gone.rmdir()
        assert os.path.lexists(checkout / ".codex") and not gone.exists(), "premise: a link to a directory that is gone"
        assert _refused(_rule(str(gone / "config.toml"), checkout)), "through the name of the missing target"
        assert _rule(str(tmp_path / "codex-gone-notes.md"), checkout) is None, "a neighbour of the target"

    def test_a_name_that_is_not_there_yet_is_kept_after_a_link_to_the_checkout(self, checkout: Path) -> None:
        """T14f (A2): the part of a path that does not exist is judged after the part that does: a link to the checkout, then a name no entry has yet."""
        _dir_link(checkout / "docs" / "up", checkout)
        assert (checkout / "docs" / "up").resolve() == checkout.resolve(), "premise: a link to the checkout"
        for name in ("AGENTS.md", ".agents/skills/x.md", "CODEOWNERS", "docs/CODEOWNERS"):
            assert _refused(_rule("docs/up/" + name, checkout)), name
        assert _rule("docs/up/docs/notes2.md", checkout) is None, "a neighbour through the same link"

    @pytest.mark.skipif(os.name != "nt", reason="a drive that is not there is a Windows case")
    def test_a_path_on_a_drive_that_is_not_there_is_judged_as_written(self, checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T14h (A2, A3): where not even the root of a path exists, no link is on it: it is judged by its names, and the writer's own error follows.
        The drive is a letter that is not in use; the host is simulated (its final-path query, ``lstat`` and ``stat`` are answered here, so the filesystem
        is never asked about the name and no network is used)."""
        import ntpath

        letter = next((c for c in "ZYXWVUTSRQPONM" if not os.path.exists(c + ":\\")), None)
        if letter is None:
            pytest.skip("every probe drive letter is in use")
        assert _rule(f"{letter}:\\no-such-drive\\x.md", checkout) is None, "a neighbour, not a refusal for what cannot be resolved"
        asked = []

        def absent(real):  # type: ignore[no-untyped-def]
            def query(path, *args, **kwargs):  # type: ignore[no-untyped-def]
                if os.fspath(path).startswith("\\\\no-such-host-bf943"):
                    asked.append(os.fspath(path))
                    raise FileNotFoundError(2, "no such host (simulated)", None, 53)
                return real(path, *args, **kwargs)

            return query

        with monkeypatch.context() as patch:
            patch.setattr(ntpath, "_getfinalpathname", absent(ntpath._getfinalpathname))
            patch.setattr(builder_paths.os, "lstat", absent(os.lstat))
            patch.setattr(builder_paths.os, "stat", absent(os.stat))
            host = _rule("\\\\no-such-host-bf943\\share\\x.md", checkout)
        assert asked and host is None, "the same for a host that is not there (the answer came from the simulated absence)"

    def test_a_link_whose_missing_target_is_reached_through_another_link_is_followed_to_its_real_place(
        self, checkout: Path, tmp_path: Path,
    ) -> None:
        """T14i (A3, F1): an entry that is a link to a directory that is gone, by a path that goes through another link, has the real place of that
        path too: following the link only as far as it goes left the second link unfollowed."""
        real, hop = tmp_path / "agents-real", tmp_path / "agents-hop"
        (real / "gone").mkdir(parents=True)
        _dir_link(hop, real)
        _dir_link(checkout / ".agents", hop / "gone")
        (real / "gone").rmdir()
        assert os.path.lexists(checkout / ".agents") and not (real / "gone").exists() and hop.resolve() == real.resolve(), "premise: the layout"
        assert _refused(_rule(str(real / "gone" / "skill.md"), checkout)), "the real place of the missing target"
        assert _refused(_rule(str(hop / "gone" / "skill.md"), checkout)), "the stored place of the missing target"
        assert _rule(str(real / "other.md"), checkout) is None, "a neighbour"

    def test_a_dangling_link_whose_stored_target_cannot_be_read_refuses_the_write(
        self, checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T14j (A3, F1): ``os.readlink`` is how a link whose target is gone is followed; a denied read refuses (``entries``) and is not answered
        with the link's own name."""
        gone, asked = tmp_path / "scratch-gone", []
        gone.mkdir()
        _dir_link(checkout / ".codex", gone)
        gone.rmdir()
        real = os.readlink

        def readlink(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == ".codex":
                asked.append(True)
                raise PermissionError(13, "denied")
            return real(path, *args, **kwargs)

        assert _rule(str(tmp_path / "other.md"), checkout) is None, "premise: allowed while the link can be read"
        with monkeypatch.context() as patch:
            patch.setattr(builder_paths.os, "readlink", readlink)
            refusal = _rule(str(tmp_path / "other.md"), checkout)
        assert asked and _refused(refusal) and "(entries: PermissionError)" in refusal, refusal

    def test_a_name_that_exists_but_is_called_absent_and_is_no_link_is_refused(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T14k (A3): where resolution says that a name is not there but it is, and it is no link to follow, the rule does not guess: it refuses."""
        real = Path.resolve

        def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self.name == "notes.md" and kwargs.get("strict"):
                raise FileNotFoundError(2, "not found (simulated)")
            return real(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", resolve)
            refusal = _rule("docs/notes.md", checkout)
        assert _refused(refusal) and "(resolved: FileNotFoundError)" in refusal, refusal

    def test_a_stored_target_that_is_relative_is_read_from_the_links_own_directory(
        self, checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T14l (A3): a symlink stores a relative target, and it is read from the directory the link is in, not from the working directory (a
        junction stores an absolute one, so the stored value is replaced here)."""
        shutil.rmtree(checkout / "config" / "ontology")
        gone, asked = tmp_path / "ontology-gone", []
        gone.mkdir()
        _dir_link(checkout / "config" / "ontology", gone)
        gone.rmdir()
        real = os.readlink

        def readlink(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "ontology":
                asked.append(True)
                return os.path.join("..", "..", "relative-target")  # from checkout/config: tmp_path/relative-target
            return real(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(builder_paths.os, "readlink", readlink)
            refused = _rule(str(tmp_path / "relative-target" / "x.md"), checkout)
            neighbour = _rule(str(tmp_path / "relative-neighbour.md"), checkout)
        assert asked and _refused(refused), "the relative target, read from checkout/config"
        assert neighbour is None, "a neighbour of it"

    @pytest.mark.skipif(os.name != "nt", reason="the denied query is the Windows final-path query")
    def test_an_entry_that_is_no_link_is_not_resolved_so_an_unreadable_one_refuses_nothing_else(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T14g (A2): a document that cannot be queried but is no link (a read-denied ``CLAUDE.md``) stays where it is: refused by name, and no
        ordinary write is refused for it."""
        import ntpath

        entry, real = os.path.normcase(str(checkout / "CLAUDE.md")), ntpath._getfinalpathname

        def query(path):  # type: ignore[no-untyped-def]
            if os.path.normcase(os.fspath(path)).removeprefix("\\\\?\\") == entry:
                raise OSError(13, "denied by the test", None, 5)
            return real(path)

        with monkeypatch.context() as patch:
            patch.setattr(ntpath, "_getfinalpathname", query)
            assert _rule("docs/notes.md", checkout) is None, "an ordinary write"
            assert _refused(_rule("CLAUDE.md", checkout)), "the document itself, by name"

    @pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Windows form")
    def test_a_real_8_3_alias_is_refused(self, checkout: Path) -> None:
        """T15a (A1, F6): Windows only (this host, not the Linux CI), and only on a volume that makes short names (C: here, not G:)."""
        import ctypes

        orders = checkout / "config" / "standing_orders"
        buffer = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(orders), buffer, 1024) or buffer.value.lower() == str(orders).lower():
            pytest.skip("this volume does not make 8.3 names")
        assert "~" in Path(buffer.value).name and os.path.samefile(buffer.value, orders), "premise: a real alias of the directory"
        assert _refused(_rule(str(Path(buffer.value) / "new.md"), checkout)), buffer.value

    @pytest.mark.skipif(os.name != "nt", reason="extended-length paths are a Windows form")
    def test_an_extended_length_path_is_refused(self, checkout: Path) -> None:
        """T15b: Windows only: the extended-length prefix is dropped, and the extended UNC form names the same share."""
        assert _refused(_rule("\\\\?\\" + str(checkout / "CLAUDE.md"), checkout))
        parts = builder_paths._document_parts  # a pure function
        assert parts(Path("\\\\?\\UNC\\host\\share\\a\\CLAUDE.md")) == parts(Path("\\\\host\\share\\a\\CLAUDE.md"))

    def test_a_path_that_cannot_be_resolved_or_examined_is_refused(self, checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T16: failing closed at the resolution, the target and the documents (premise lines first)."""
        _link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")
        for name in ("probe.md", "notes.md", "again.md"):
            assert _rule(f"docs/{name}", checkout) is None, "premise: accepted before the patches"
        real_resolve, real_stat = Path.resolve, os.stat

        def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self.name == "probe.md":
                raise ValueError("unresolvable")
            return real_resolve(self, *args, **kwargs)

        def stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name in ("notes.md", "CLAUDE.md"):
                raise PermissionError(13, "denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        resolved = _rule("docs/probe.md", checkout)
        monkeypatch.undo()
        monkeypatch.setattr(builder_paths.os, "stat", stat)
        target, documents = _rule("docs/notes.md", checkout), _rule("docs/again.md", checkout)
        monkeypatch.undo()
        assert _refused(resolved) and "(resolved: ValueError)" in resolved
        assert _refused(target) and "(target: PermissionError)" in target
        assert _refused(documents) and "(documents: PermissionError)" in documents

    @pytest.mark.parametrize(
        ("unlistable", "stage"), [(".", "entries"), (".github", "documents"), ("config/standing_orders", "documents")],
    )
    def test_a_directory_that_cannot_be_listed_refuses_the_write_instead_of_being_skipped(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch, unlistable: str, stage: str,
    ) -> None:
        """T16b (A1, F2; A2): a root is listed, for ``requirements*.txt``, by every call that neither its written nor its resolved name refuses
        (stage ``entries``); a document directory is scanned only for a write to a file with another name (stage ``documents``); a listing that fails
        refuses, at its own stage."""
        alias = _link(checkout / "requirements-dev.txt", checkout / "docs" / "alias.md")
        assert _refused(_rule(str(alias), checkout)), "premise: the alias is refused while everything lists"
        real, denied = os.scandir, (checkout / unlistable).resolve()

        def scandir(path="."):  # type: ignore[no-untyped-def]
            if Path(path).resolve() == denied:
                raise PermissionError(13, "denied")
            return real(path)

        with monkeypatch.context() as patch:
            patch.setattr(builder_paths.os, "scandir", scandir)
            refusal = _rule(str(alias), checkout)
            ordinary = _rule("docs/notes.md", checkout)
        assert _refused(refusal) and f"({stage}: PermissionError)" in refusal, refusal
        assert (ordinary is None) == (stage == "documents"), "a root that cannot be listed refuses an ordinary write; a document directory does not"

    @pytest.mark.parametrize("stage", ["resolved", "entries", "target", "scan"])
    @pytest.mark.parametrize(
        "error", [PermissionError(13, "denied"), RuntimeError("loop"), ValueError("embedded null")], ids=lambda e: type(e).__name__,
    )
    def test_an_oserror_a_runtimeerror_and_a_valueerror_are_each_refused_at_each_stage(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch, stage: str, error: Exception,
    ) -> None:
        """T16c (A1, F4; A2, R2-2): the docstring's three classes are each refused by the handler of the resolution, of the entries' places, of the
        target's ``os.stat`` and of the identity scan, and the reason names the stage; each injection is shown to have fired, at its own stage."""
        _link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")
        raised, armed = [], []
        real_resolve, real_stat, real_locations = Path.resolve, os.stat, builder_paths._document_locations

        def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
            raised.append(stage)
            raise error

        def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return fail() if self.name == "probe.md" else real_resolve(self, *args, **kwargs)

        def locations(*args, **kwargs):  # type: ignore[no-untyped-def]
            armed.append(True)  # the resolution is over: only the target's own stat comes next
            return real_locations(*args, **kwargs)

        def stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            return fail() if armed and Path(path).name == "notes.md" else real_stat(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            if stage == "resolved":
                patch.setattr(Path, "resolve", resolve)
            elif stage == "entries":
                patch.setattr(builder_paths, "_document_locations", fail)
            elif stage == "target":
                patch.setattr(builder_paths, "_document_locations", locations)
                patch.setattr(builder_paths.os, "stat", stat)
            else:
                patch.setattr(builder_paths, "_is_a_second_name_of_a_document", fail)
            refusal = _rule("docs/" + {"resolved": "probe.md", "scan": "again.md"}.get(stage, "notes.md"), checkout)
        assert raised == [stage], "premise: the injection fired once, at its own stage"
        named = {"entries": "entries", "scan": "documents"}.get(stage, stage)
        assert _refused(refusal) and f"({named}: {type(error).__name__})" in refusal, refusal

    def test_an_entry_that_cannot_be_examined_refuses_every_write(self, checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T16d (A1, F2): an entry whose existence cannot be told is not taken to be absent."""
        assert _rule("docs/notes.md", checkout) is None, "premise: allowed while every entry can be examined"
        real = os.lstat

        def lstat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "CLAUDE.md":
                raise PermissionError(13, "denied")
            return real(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(builder_paths.os, "lstat", lstat)
            refusal = _rule("docs/notes.md", checkout)
        assert _refused(refusal) and "(entries: PermissionError)" in refusal, refusal

    def test_any_other_exception_propagates(self, checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T16e (A1): the rule refuses on the three classes and swallows nothing else."""

        def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise KeyError("not a refusal")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", resolve)
            with pytest.raises(KeyError):
                _rule("docs/notes.md", checkout)

    def test_a_value_that_is_not_an_exact_str_is_refused(self, checkout: Path) -> None:
        """T17: the type is compared first (AD-1344's D14)."""

        class Text(str):
            pass

        refusal = _rule(Text("docs/notes.md"), checkout)
        assert _refused(refusal) and "exact str" in refusal
        assert _rule("docs/notes.md", checkout) is None  # control: the same text, an exact str

    @pytest.mark.parametrize("form", ["relative", "absolute"])
    @pytest.mark.parametrize("member", (*_FILES, *_ABSENT))
    @pytest.mark.parametrize("writer", _WRITERS)
    async def test_each_writer_refuses_every_entry_and_still_writes_a_neighbour(
        self, checkout: Path, writer: str, member: str, form: str,
    ) -> None:
        """T20, acceptance 2: each general writer, each entry, rooted as that writer roots a relative path; nothing is written."""
        before = _tree(checkout)
        written, error = await _call(writer, member if form == "relative" else str(checkout / member))
        assert not written and _BF in error, error
        assert _tree(checkout) == before
        written, error = await _call(writer, str(checkout / "docs" / "notes.md"))
        assert written, error

    @pytest.mark.parametrize("writer", _OFFICE)
    @pytest.mark.parametrize("directory", _DIRECTORIES)
    async def test_the_office_revise_and_update_refuse_a_file_under_a_document_directory(
        self, checkout: Path, writer: str, directory: str,
    ) -> None:
        """T21: an existing .docx or .xlsx under a directory entry, then the neighbour."""
        suffix = ".docx" if writer == "docx_revise" else ".xlsx"
        target = _office_file(checkout / directory / ("x" + suffix))
        before = target.read_bytes()
        written, error = await _call(writer, str(target))
        assert not written and _BF in error, error
        assert target.read_bytes() == before
        written, error = await _call(writer, str(_office_file(checkout / "docs" / ("n" + suffix))))
        assert written, error

    @pytest.mark.parametrize("writer", ["write_file", "edit_file", "commit", "docx_create"])
    async def test_a_hard_link_to_a_document_is_refused_by_the_writers(self, checkout: Path, writer: str) -> None:
        """T22, acceptance 2: through the alias the writer is given, the document is unchanged."""
        written, error = await _call(writer, str(_link(checkout / "CLAUDE.md", checkout / "docs" / "alias.md")))
        assert not written and _BF in error, error
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "x v1\n"

    async def test_write_file_refuses_under_the_effect_broker_context(self, checkout: Path) -> None:
        """T23: the refusal comes before the strict-native lock (the unfixed tree goes on into it and raises)."""
        context = {"_effect_dispatch_context": object(), "_strict_native_target": str(checkout / "CLAUDE.md"),
                   "_strict_native_root": str(checkout)}
        try:
            result = await WriteFileTool(SimpleNamespace()).invoke({"path": str(checkout / "CLAUDE.md"), "content": "AMENDED\n"}, context)
        except Exception:
            result = None
        assert result is not None and not result.success and _BF in (result.error or "")
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "x v1\n"

    @pytest.mark.parametrize("writer", list(_LOG))
    async def test_a_refusal_logs_a_constant_line_without_the_callers_path(
        self, checkout: Path, writer: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T24, D4 (AD-1344's D20, BF-911's D15 to D17): the operation and the reason code, not the path."""
        caplog.set_level("WARNING")
        if writer in _OFFICE:
            document = _office_file(checkout / ".github" / "SENTINEL_PRIVATE_DIR" / ("x.docx" if writer == "docx_revise" else "x.xlsx"))
        else:
            document = checkout / "SENTINEL_PRIVATE_DIR" / ".." / "CLAUDE.md"
        written, error = await _call(writer, str(document))
        assert not written and "SENTINEL_PRIVATE_DIR" in error and _BF in error, error
        owner, operation = _LOG[writer]
        assert f"BF-943 {owner} refused operation={operation} reason_code=captain_document_refused" in caplog.text
        assert "SENTINEL_PRIVATE_DIR" not in caplog.text

    def test_census_the_rule_is_called_by_the_inventoried_writers(self) -> None:
        """T30, census A: the callers are the eight writers; the build lane's modules are not among them."""
        assert _callers(_RULE) == _EXPECTED_CALLERS

    def test_census_every_caller_of_ad1344s_rule_but_the_builder_calls_this_one(self) -> None:
        """T31, census B and acceptance 4: a writer that calls AD-1344's rule and not this one fails."""
        constitution = _callers(_AD_RULE)
        assert (_BP, "builder_write_refusal") in constitution, "premise"
        assert constitution - {(_BP, "builder_write_refusal")} == _callers(_RULE)
