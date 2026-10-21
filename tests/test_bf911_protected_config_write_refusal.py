"""BF-911 (#1613): agents cannot rewrite the running vessel's config files or the credential vault's files.

``security.file_access.protected_write_refusal`` is the write side of BF-908's config floor. These
tests drive it directly (the forms, identity, failing closed), then through each writer that calls
it: the SWE-harness ``write_file`` and ``edit_file``, ``FileWriterAgent`` (the proposal, the write,
the consensus commit and the bundled agents' direct write) and the office document writers. The
writer tests run on a temporary layout that mirrors production: ``swe_tools._PROJECT_ROOT`` is
``<checkout>/src``, ``file_access._REPO_DEFAULT_CONFIG`` is ``<checkout>/config/system.yaml``, the
loaded ``--config`` file lies outside the checkout, and the home directory is a temporary folder
without ``.probos/config.yaml``. Each refusal is paired with a neighbour the same writer still
writes, and a copy of the config in another tree stays writable. An autouse guard snapshots the
repository's own ``config/system.yaml`` and the real ``~/.probos/config.yaml`` and compares them
after each test. The census tests are name and keyword inventories: they pin the callers, pair them
with AD-1344's and pin that each ``commit_write`` call passes ``runtime=``; the behaviour tests pin
that the guards run. T41-T44 drive a plan through the DAG executor and the production gate table.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility import organizer_agents, productivity_agents
from probos.cognitive import builder_paths
from probos.cognitive.decomposer import DAGExecutor
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.security import file_access
from probos.security.file_access import PROTECTED_LEAF_NAMES, protected_write_refusal
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.types import ConsensusOutcome, IntentMessage, IntentResult, TaskDAG, TaskNode
from tests.test_ad1344_constitution_write_refusal import (
    _CHANNEL_SUFFIXES,
    _ShiftingPath,
    _build,
    _callee,
    _calls,
    _dir_link,
    _source,
    _tracked,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_CONFIG = _REPO_ROOT / "config" / "system.yaml"
_REAL_HOME_CONFIG = Path.home() / ".probos" / "config.yaml"  # read at import, before a test moves the home directory
_BF = "BF-911"
_LIVE = "auth:\n  crew_scope_token: ''\n"
_CUSTOM = "auth:\n  crew_scope_token: ''\nsystem:\n  name: custom\n"
_CHOSEN = "auth:\n  crew_scope_token: chosen-by-the-writer\n"


# ── Fixtures and helpers ──────────────────────────────────────────────────


def _snapshot(path: Path) -> tuple[bytes, int] | None:
    try:
        return path.read_bytes(), os.stat(path).st_mode
    except FileNotFoundError:
        return None


@pytest.fixture(autouse=True)
def _real_config_files_untouched():
    """The repository's ``config/system.yaml`` and the real ``~/.probos/config.yaml`` are unchanged by each test.

    A snapshot, not a frozen hash, so the Captain's local edits are fine. The paths are literals fixed
    at import: a defect in the rule fails its own tests, not this setup.
    """
    before = (_snapshot(_REAL_CONFIG), _snapshot(_REAL_HOME_CONFIG))
    yield
    assert (_snapshot(_REAL_CONFIG), _snapshot(_REAL_HOME_CONFIG)) == before, "a real config file changed"


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Production's shape under tmp_path: the SWE root is <checkout>/src, the live config <checkout>/config/system.yaml."""
    checkout = tmp_path / "checkout"
    for sub in ("src", "config", "docs", "data"):
        (checkout / sub).mkdir(parents=True)
    live = checkout / "config" / "system.yaml"
    live.write_text(_LIVE, encoding="utf-8")
    (checkout / "config" / "other.yaml").write_text("other: 1\n", encoding="utf-8")
    custom = tmp_path / "elsewhere" / "custom.yaml"
    custom.parent.mkdir()
    custom.write_text(_CUSTOM, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    worktree = tmp_path / "worktree"
    (worktree / "config").mkdir(parents=True)
    shutil.copyfile(live, worktree / "config" / "system.yaml")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(file_access, "_REPO_DEFAULT_CONFIG", live.resolve())
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", checkout / "src")
    assert Path.home() == home, "premise: the home directory is the temporary one"
    return SimpleNamespace(
        checkout=checkout, src=checkout / "src", live=live, custom=custom, home=home,
        home_config=home / ".probos" / "config.yaml", worktree=worktree,
        runtime=SimpleNamespace(config_path=str(custom)),
    )


def _unchanged(layout: SimpleNamespace) -> bool:
    return (
        layout.live.read_text(encoding="utf-8") == _LIVE
        and layout.custom.read_text(encoding="utf-8") == _CUSTOM
        and not layout.home_config.exists()
    )


def _link(source: Path, alias: Path) -> Path:
    try:
        os.link(source, alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, source), "premise: the alias is the same file"
    return alias


def _refused(text: str | None) -> bool:
    return text is not None and _BF in text and "\n" not in text


def _logged(caplog: pytest.LogCaptureFixture, *loggers: str) -> str:
    """The messages the named module loggers recorded; another logger may report the refusal, which names the path."""
    return "\n".join(record.getMessage() for record in caplog.records if record.name in loggers)


# ── The forms ─────────────────────────────────────────────────────────────

# Relative to the SWE root (<checkout>/src); each names <checkout>/config/system.yaml, which exists.
_LIVE_FORMS = {
    "dot-dot": "../config/system.yaml",
    "case": "../CONFIG/SYSTEM.YAML",
    "backslashes": "..\\config\\system.yaml",
    "dot-prefix": "./../config/system.yaml",
    "dot-component": "../config/./system.yaml",
    "empty-component": "..//config//system.yaml",
    "dots-only-component": "../config/.../system.yaml",
    "inner-dot-dot": "../config/sub/../system.yaml",
    "trailing-dot": "../config/system.yaml.",
    "trailing-space": "../config/system.yaml ",
    "default-stream": "../config/system.yaml::$DATA",
    "named-stream": "../config/system.yaml:hidden",
    "short-name-file": "../config/SYSTEM~1.YAM",
    "short-name-directory": "../CONFIG~1/system.yaml",
    "hfs-ignorable": "../config/sys\u200ctem.yaml",
}
# Absolute, for ~/.probos/config.yaml, which does not exist: only the name comparison can refuse.
_HOME_FORMS = {
    "exact": "{home}/.probos/config.yaml",
    "case": "{home}/.PROBOS/CONFIG.YAML",
    "backslashes": "{home}\\.probos\\config.yaml",
    "dot-dot": "{home}/.probos/notes/../config.yaml",
    "dots-only-component": "{home}/.probos/.../config.yaml",
    "trailing-dot": "{home}/.probos/config.yaml.",
    "trailing-space": "{home}/.probos/config.yaml ",
    "named-stream": "{home}/.probos/config.yaml:hidden",
    "short-name-file": "{home}/.probos/CONFIG~1.YAM",
    "hfs-ignorable": "{home}/.probos/con\u200cfig.yaml",
}
_LIVE_NEIGHBOURS = [
    "../config/other.yaml",
    "../config/system.yaml.bak",
    "../config/system.yml",
    "../config/sub/system.yaml",
    "../config",
    "config/system.yaml",
    "../docs/system.yaml",
    "../data/credential_vault.json.bak",
]
_VAULT_FORMS = [
    "../data/credential_vault.json",
    "../docs/CREDENTIAL_VAULT.JSON",
    "credential_keyring_index.json",
    "../data/credential_keyring_index.json:hidden",
    "../data/credential_vault.json.",
]
# Pure strings: judged the same on every platform, and no host is contacted.
_SAME_KEY = {
    "extended-length": ("\\\\?\\C:\\V\\config\\system.yaml", "C:/v/CONFIG/system.yaml"),
    "device-lowercase-drive": ("\\\\.\\C:\\V\\config\\system.yaml", "c:\\v\\config\\system.yaml"),
    "unc-extended": ("\\\\?\\UNC\\server\\share\\cfg\\system.yaml", "//SERVER/share/cfg/./system.yaml"),
    "unc": ("\\\\server\\share\\cfg\\system.yaml", "//server/SHARE/cfg/system.yaml"),
    "posix-dot-dot": ("/home/x/.probos/config.yaml", "/home/x/.probos/notes/../config.yaml"),
}
_OTHER_KEY = {
    "another-drive": ("C:/v/config/system.yaml", "D:/v/config/system.yaml"),
    "unc-vs-posix": ("//server/share/cfg/system.yaml", "/server/share/cfg/system.yaml"),
    "drive-vs-posix": ("C:/v/config/system.yaml", "/v/config/system.yaml"),
    "another-name": ("C:/v/config/system.yaml", "C:/v/config/system.yaml.bak"),
}


# ── 1. The rule ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
def test_rule_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T1: relative to the SWE root, as write_file receives them."""
    path = _LIVE_FORMS[form]
    refusal = protected_write_refusal(path, root=layout.src)
    assert _refused(refusal) and repr(path) in refusal


@pytest.mark.parametrize("form", list(_HOME_FORMS))
def test_rule_refuses_every_form_of_an_absent_home_config(layout: SimpleNamespace, form: str) -> None:
    """T2: no file to compare identity with, so the name comparison alone refuses."""
    assert not layout.home_config.exists(), "premise: ~/.probos/config.yaml is absent"
    path = _HOME_FORMS[form].format(home=layout.home)
    assert _refused(protected_write_refusal(path))
    assert _refused(protected_write_refusal(".probos/config.yaml", root=layout.home))  # relative: the resolved form decides


@pytest.mark.parametrize("path", _LIVE_NEIGHBOURS)
def test_rule_allows_the_neighbours(layout: SimpleNamespace, path: str) -> None:
    """T3."""
    assert protected_write_refusal(path, root=layout.src, runtime=layout.runtime) is None


@pytest.mark.parametrize("path", _VAULT_FORMS)
def test_rule_refuses_the_vault_file_names_anywhere(layout: SimpleNamespace, path: str) -> None:
    """T4."""
    assert PROTECTED_LEAF_NAMES == frozenset({"credential_vault.json", "credential_keyring_index.json"})
    refusal = protected_write_refusal(path, root=layout.src)
    assert _refused(refusal) and "credential vault" in refusal


def test_rule_refuses_the_loaded_config_through_the_runtime(layout: SimpleNamespace) -> None:
    """T5."""
    assert layout.custom.resolve() in file_access.protected_config_files(layout.runtime)
    assert layout.custom.resolve() not in file_access.protected_config_files(None), "premise: only the runtime names it"
    for path, root in ((str(layout.custom), None), ("custom.yaml", layout.custom.parent),
                       (str(layout.custom.parent / "CUSTOM.YAML"), None)):
        assert _refused(protected_write_refusal(path, root=root, runtime=layout.runtime)), path


def test_rule_allows_a_copy_of_the_config_in_another_tree(layout: SimpleNamespace) -> None:
    """T6."""
    copy = layout.worktree / "config" / "system.yaml"
    assert copy.read_bytes() == layout.live.read_bytes(), "premise: the same content in another file"
    assert protected_write_refusal(str(copy), runtime=layout.runtime) is None
    assert protected_write_refusal("config/system.yaml", root=layout.worktree, runtime=layout.runtime) is None


@pytest.mark.parametrize("pair", list(_SAME_KEY))
def test_rule_key_judges_lexical_forms_the_same_on_every_platform(pair: str) -> None:
    """T7."""
    left, right = _SAME_KEY[pair]
    assert file_access._write_key(left) == file_access._write_key(right)


@pytest.mark.parametrize("pair", list(_OTHER_KEY))
def test_rule_key_keeps_drives_and_names_apart(pair: str) -> None:
    """T8."""
    left, right = _OTHER_KEY[pair]
    assert not file_access._same_key(file_access._write_key(left), file_access._write_key(right))


def test_rule_refuses_a_value_that_is_not_an_exact_str_without_running_its_code(layout: SimpleNamespace) -> None:
    """T9."""
    ran: list[str] = []

    class Spy(str):
        def replace(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("replace")
            return str.replace(self, *args, **kwargs)

        def __fspath__(self) -> str:
            ran.append("__fspath__")
            return str.__str__(self)

        def __str__(self) -> str:
            ran.append("__str__")
            return str.__str__(self)

        def __repr__(self) -> str:
            ran.append("__repr__")
            return str.__repr__(self)

    neighbour = Spy("../config/other.yaml")
    refusal = protected_write_refusal(neighbour, root=layout.src)
    assert _refused(refusal) and "exact str" in refusal
    assert ran == [], f"the rule ran code of the caller's value: {ran}"
    assert protected_write_refusal(str.__str__(neighbour), root=layout.src) is None  # control: the same text, exact str


def test_rule_refuses_a_hard_link_to_the_live_config_by_identity(layout: SimpleNamespace) -> None:
    """T10."""
    alias = _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    assert _refused(protected_write_refusal("../docs/alias.yaml", root=layout.src))
    assert _refused(protected_write_refusal(str(alias)))
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    assert protected_write_refusal("../docs/other.yaml", root=layout.src) is None  # an existing unrelated file
    assert protected_write_refusal("../docs/new.yaml", root=layout.src) is None  # not on disk


def test_rule_refuses_a_hard_link_to_the_loaded_config_through_the_runtime(layout: SimpleNamespace) -> None:
    """T11."""
    alias = _link(layout.custom, layout.checkout / "docs" / "custom-alias.yaml")
    assert _refused(protected_write_refusal(str(alias), runtime=layout.runtime))


def test_rule_checks_the_next_config_file_when_the_loaded_one_is_missing(layout: SimpleNamespace) -> None:
    """T12: the first protected file is not on disk; the hard link to the second is still found."""
    alias = _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    runtime = SimpleNamespace(config_path=str(layout.checkout / "missing.yaml"))
    assert _refused(protected_write_refusal(str(alias), runtime=runtime))


def test_rule_refuses_a_directory_link_to_the_config_directory(layout: SimpleNamespace) -> None:
    """T13: through the resolved name, with the file present and with it missing."""
    _dir_link(layout.checkout / "docs" / "cfg", layout.checkout / "config")
    assert _refused(protected_write_refusal("../docs/cfg/system.yaml", root=layout.src))
    assert protected_write_refusal("../docs/cfg/other.yaml", root=layout.src) is None
    layout.live.unlink()
    assert _refused(protected_write_refusal("../docs/cfg/system.yaml", root=layout.src))


def test_rule_refuses_when_a_config_file_cannot_be_examined(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T14."""
    assert protected_write_refusal("../docs/new.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "system.yaml":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/new.yaml", root=layout.src)
    assert _refused(refusal) and "(config: PermissionError)" in refusal


def test_rule_refuses_when_the_target_cannot_be_examined(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T15."""
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    assert protected_write_refusal("../docs/other.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.yaml":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
    assert _refused(refusal) and "(target: PermissionError)" in refusal


def test_rule_names_a_failure_under_another_metaclass_exception(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T16: the reason reads no attribute of a class whose metaclass is not exactly ``type``."""
    ran: list[str] = []

    class Meta(type):
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            ran.append("__name__")
            return "Spoofed"

    class Denied(PermissionError, metaclass=Meta):
        pass

    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.yaml":
            raise Denied(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
    assert _refused(refusal) and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"


def test_rule_refuses_a_path_that_cannot_be_resolved(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T17."""
    assert protected_write_refusal("../docs/probe.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "probe.yaml":
            raise ValueError("unresolvable")
        return real_resolve(self, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "resolve", resolve)
        refusal = protected_write_refusal("../docs/probe.yaml", root=layout.src)
    assert _refused(refusal) and "(resolved: ValueError)" in refusal


def test_rule_refuses_when_a_config_file_cannot_be_resolved(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T42 (A2, review F2): a protected config whose resolution raises refuses the write; the read floor still leaves it out."""
    alias = _link(layout.custom, layout.checkout / "docs" / "custom-alias.yaml")
    assert _refused(protected_write_refusal(str(alias), runtime=layout.runtime)), "premise: the alias is refused"
    assert protected_write_refusal("../docs/new.yaml", root=layout.src, runtime=layout.runtime) is None, "premise: accepted"
    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == layout.custom.name:
            raise PermissionError(13, "denied")
        return real_resolve(self, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "resolve", resolve)
        try:
            read_side: list[Path] | None = file_access.protected_config_files(layout.runtime)
        except PermissionError:
            read_side = None
        through_alias = protected_write_refusal(str(alias), runtime=layout.runtime)
        new_file = protected_write_refusal("../docs/new.yaml", root=layout.src, runtime=layout.runtime)
    assert read_side is not None and layout.custom.resolve() not in read_side and len(read_side) == 2, (
        "the read floor's default: a file it cannot resolve is left out, as on the base"
    )
    for refusal in (through_alias, new_file):
        assert _refused(refusal) and "(config resolved: PermissionError)" in refusal, refusal


def test_rule_refusal_changes_nothing_on_disk_and_a_direct_write_still_works(layout: SimpleNamespace) -> None:
    """T18: no friction. The rule does not lock, chmod or mark the file; the Captain's own write is untouched."""
    before = (layout.live.read_bytes(), os.stat(layout.live).st_mode)
    assert _refused(protected_write_refusal(str(layout.live)))
    assert (layout.live.read_bytes(), os.stat(layout.live).st_mode) == before
    layout.live.write_text("auth:\n  crew_scope_token: captain\n", encoding="utf-8")
    assert layout.live.read_text(encoding="utf-8") == "auth:\n  crew_scope_token: captain\n"


@pytest.mark.parametrize("name", [".GiT", ".git. ", "fede\u200cration.md", "System.YAML", "CONFIG~1", "a b "])
def test_rule_canonical_form_is_bf894s(name: str) -> None:
    """T19: the mirrored helpers agree with builder_paths (D10)."""
    assert file_access._canonical_name(name) == builder_paths._canonical(name)
    assert file_access._SHORT_NAME.pattern == builder_paths._SHORT_NAME.pattern
    assert file_access._HFS_IGNORABLE.pattern == builder_paths._HFS_IGNORABLE.pattern


def test_rule_names_a_failure_whose_class_name_is_not_an_exact_identifier_exception(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T36 (A1, D17): a class name with a line break, or held as a ``str`` subclass, is reported as ``Exception``.

    The reason has no line break and none of the name's code runs; ``builder_paths._exception_name`` gives
    the same name for each exception (D10 parity).
    """
    ran: list[str] = []

    class Name(str):
        def __format__(self, spec: str) -> str:
            ran.append("__format__")
            return str.__format__(self, spec)

    class TwoLines(PermissionError):
        pass

    class Formatted(PermissionError):
        pass

    TwoLines.__name__ = "Two\nLines"
    Formatted.__name__ = Name("Formatted")
    assert type(TwoLines) is type and type(Formatted.__name__) is Name, "premise: metaclass type, names as set"
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    real_stat = os.stat
    for cls in (TwoLines, Formatted):

        def _stat(path, *args, _cls=cls, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "other.yaml":
                raise _cls(13, "denied")
            return real_stat(path, *args, **kwargs)

        with monkeypatch.context() as patched:
            patched.setattr(file_access.os, "stat", _stat)
            refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
        assert _refused(refusal) and "(target: Exception)" in refusal, cls
    for exc in (TwoLines(13, "denied"), Formatted(13, "denied"), PermissionError(13, "denied")):
        assert file_access._exception_class_name(exc) == builder_paths._exception_name(exc), type(exc)
    assert ran == [], "the class name's own code ran"


# ── 2. SWE harness ────────────────────────────────────────────────────────


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
async def test_write_file_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T20."""
    result = await WriteFileTool(layout.runtime).invoke({"path": _LIVE_FORMS[form], "content": _CHOSEN})
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


async def test_write_file_refuses_each_config_by_absolute_path_and_still_writes_the_neighbours(
    layout: SimpleNamespace,
) -> None:
    """T21."""
    tool = WriteFileTool(layout.runtime)
    vault = layout.checkout / "data" / "credential_vault.json"
    for target in (layout.live, layout.custom, layout.home_config, vault):
        result = await tool.invoke({"path": str(target), "content": _CHOSEN})
        assert not result.success and _BF in (result.error or ""), target
    assert _unchanged(layout) and not vault.exists()
    worktree_config = layout.worktree / "config" / "system.yaml"
    for path, text in (("../config/other.yaml", "other: 2\n"), ("config/system.yaml", "under src\n"),
                       (str(worktree_config), _CHOSEN), (str(layout.home / ".probos" / "notes" / "n.md"), "a note\n")):
        result = await tool.invoke({"path": path, "content": text})
        assert result.success, f"{path}: {result.error}"
    assert (layout.src / "config" / "system.yaml").read_text(encoding="utf-8") == "under src\n"
    assert worktree_config.read_text(encoding="utf-8") == _CHOSEN
    assert _unchanged(layout)


async def test_write_file_refuses_a_hard_link_and_a_directory_link(layout: SimpleNamespace) -> None:
    """T22."""
    tool = WriteFileTool(layout.runtime)
    _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    linked = await tool.invoke({"path": "../docs/alias.yaml", "content": _CHOSEN})
    assert not linked.success and _BF in (linked.error or "")
    _dir_link(layout.checkout / "docs" / "cfg", layout.checkout / "config")
    through = await tool.invoke({"path": "../docs/cfg/system.yaml", "content": _CHOSEN})
    assert not through.success and _BF in (through.error or "")
    assert _unchanged(layout)


async def test_write_file_refuses_under_the_effect_broker_context(layout: SimpleNamespace) -> None:
    """T23: the refusal comes before the strict-native lock and the plain write alike."""
    context = {
        "_effect_dispatch_context": object(),
        "_strict_native_target": str(layout.live),
        "_strict_native_root": str(layout.checkout),
    }
    result = await WriteFileTool(layout.runtime).invoke({"path": "../config/system.yaml", "content": _CHOSEN}, context)
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
async def test_edit_file_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T24."""
    result = await EditFileTool(layout.runtime).invoke(
        {"path": _LIVE_FORMS[form], "old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"})
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


async def test_edit_file_refuses_the_loaded_config_and_a_hard_link_and_still_edits_the_neighbours(
    layout: SimpleNamespace,
) -> None:
    """T25."""
    tool = EditFileTool(layout.runtime)
    edit = {"old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"}
    loaded = await tool.invoke({"path": str(layout.custom), **edit})
    assert not loaded.success and _BF in (loaded.error or "")
    worktree_config = layout.worktree / "config" / "system.yaml"
    for path, old, new in (("../config/other.yaml", "other: 1", "other: 2"),
                           (str(worktree_config), "crew_scope_token: ''", "crew_scope_token: worktree")):
        result = await tool.invoke({"path": path, "old_text": old, "new_text": new})
        assert result.success and result.output["replacements"] == 1, f"{path}: {result.error}"
    _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    linked = await tool.invoke({"path": "../docs/alias.yaml", **edit})
    assert not linked.success and _BF in (linked.error or "")
    assert _unchanged(layout)


async def test_the_swe_tools_log_a_protected_refusal_without_the_callers_path(
    layout: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """T37 (A1, D16): the BF-911 log line carries the operation and the reason code, not the caller's path.

    Driven with the strict effect context and without it, as AD-1344's T37; the returned error still names the path.
    """
    caplog.set_level("WARNING", logger=swe_tools.__name__)
    sentinel = "../config/SENTINEL_PRIVATE_DIR/../system.yaml"
    edit = {"old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"}
    for context in ({"_effect_dispatch_context": object()}, None):
        written = await WriteFileTool(layout.runtime).invoke({"path": sentinel, "content": _CHOSEN}, context)
        edited = await EditFileTool(layout.runtime).invoke({"path": sentinel, **edit}, context)
        for result in (written, edited):
            assert not result.success and _BF in (result.error or ""), context
            assert "SENTINEL_PRIVATE_DIR" in (result.error or ""), "the returned error keeps the path"
    logged = _logged(caplog, swe_tools.__name__)
    assert "SENTINEL_PRIVATE_DIR" not in logged
    assert "operation=write_file reason_code=protected_write_refused" in logged
    assert "operation=edit_file reason_code=protected_write_refused" in logged
    assert _unchanged(layout)


async def test_the_swe_tools_judge_the_one_conversion_of_the_callers_path(layout: SimpleNamespace) -> None:
    """T38 (A1, D15): BF-911 judges ``path_text``, the text the tool resolves, writes and returns.

    The caller's ``__str__`` gives a neighbour first and the live config afterwards (AD-1344's ``_ShiftingPath``).
    """
    neighbour, live = "../config/other.yaml", "../config/system.yaml"
    written = _ShiftingPath(neighbour, live)
    result = await WriteFileTool(layout.runtime).invoke({"path": written, "content": "other: 2\n"})
    assert result.success, result.error
    assert written.conversions == 1 and result.output["path"] == neighbour
    edited = _ShiftingPath(neighbour, live)
    result = await EditFileTool(layout.runtime).invoke({"path": edited, "old_text": "other: 2", "new_text": "other: 3"})
    assert result.success, result.error
    assert edited.conversions == 1 and result.output == {"replacements": 1, "path": neighbour}
    assert (layout.checkout / "config" / "other.yaml").read_text(encoding="utf-8") == "other: 3\n"
    assert _unchanged(layout)


async def test_an_exception_from_the_rule_enters_the_swe_tools_existing_handlers(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T39 (A1, D16): the call is a statement of each tool's existing ``try``.

    A ``LookupError`` is not a ``FileNotFoundError`` (``edit_file``'s first arm), so each tool takes its
    ``except Exception``: an error result without the effect dispatch context, the exception itself with it.
    Nothing is written.
    """

    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise LookupError("the rule failed")

    monkeypatch.setattr(swe_tools, "protected_write_refusal", _raise)
    write = {"path": "../config/other.yaml", "content": "other: 2\n"}
    edit = {"path": "../config/other.yaml", "old_text": "other: 1", "new_text": "other: 2"}
    written = await WriteFileTool(layout.runtime).invoke(write)
    edited = await EditFileTool(layout.runtime).invoke(edit)
    assert (written.error or "").startswith("write_file failed: "), written.error
    assert (edited.error or "").startswith("edit_file failed: "), edited.error
    for tool, params in ((WriteFileTool(layout.runtime), write), (EditFileTool(layout.runtime), edit)):
        with pytest.raises(LookupError):
            await tool.invoke(params, {"_effect_dispatch_context": object()})
    assert (layout.checkout / "config" / "other.yaml").read_text(encoding="utf-8") == "other: 1\n"
    assert _unchanged(layout)


class _VesselWhoseConfigPathRaises:
    """A runtime whose ``config_path`` attribute raises ``FileNotFoundError`` (review round 2, F6)."""

    @property
    def config_path(self) -> str:
        raise FileNotFoundError(2, "the loaded config moved")


async def test_a_config_path_attribute_that_raises_is_refused_not_reported_missing(layout: SimpleNamespace) -> None:
    """T45 (A3, review round 2 F6): the rule's config step includes reading ``runtime.config_path``.

    The ``FileNotFoundError`` that attribute raises is refused as ``(config resolved: FileNotFoundError)``,
    so ``edit_file`` returns the refusal, with and without the effect dispatch context, instead of
    taking its ``except FileNotFoundError`` (R11). Nothing is written.
    """
    vessel = _VesselWhoseConfigPathRaises()
    with pytest.raises(FileNotFoundError):
        _ = vessel.config_path  # premise: the attribute raises
    neighbour = "../config/other.yaml"
    assert protected_write_refusal(neighbour, root=layout.src, runtime=layout.runtime) is None, "premise: accepted"
    try:
        refusal = protected_write_refusal(neighbour, root=layout.src, runtime=vessel)
    except Exception as exc:  # r1's route: the exception left the rule
        refusal = f"raised {type(exc).__name__}"
    assert _refused(refusal) and "(config resolved: FileNotFoundError)" in refusal, refusal
    edit = {"path": neighbour, "old_text": "other: 1", "new_text": "other: 2"}
    outcomes: list[str | None] = []
    for context in (None, {"_effect_dispatch_context": object()}):
        try:
            outcomes.append((await EditFileTool(vessel).invoke(edit, context)).error)
        except Exception as exc:  # r1's route under the dispatch context: NoEffectFailure("file_not_found")
            outcomes.append(f"raised {type(exc).__name__}")
    assert outcomes == [refusal, refusal], outcomes
    assert (layout.checkout / "config" / "other.yaml").read_text(encoding="utf-8") == "other: 1\n"
    assert _unchanged(layout)


# ── 3. FileWriterAgent and its callers ────────────────────────────────────


async def test_file_writer_refuses_the_proposal_and_the_commit(layout: SimpleNamespace) -> None:
    """T26."""
    agent = FileWriterAgent(pool="filesystem", runtime=layout.runtime)
    await agent.start()
    for target in (layout.live, layout.custom):
        proposal = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": str(target), "content": _CHOSEN}))
        assert proposal is not None and proposal.success is False and _BF in (proposal.error or ""), target
    other = layout.checkout / "config" / "other.yaml"
    control = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": str(other), "content": "other: 2\n"}))
    assert control is not None and control.success is True and control.result["requires_consensus"] is True
    for target, runtime in ((layout.live, None), (layout.home_config, None), (layout.custom, layout.runtime)):
        committed = await FileWriterAgent.commit_write(str(target), _CHOSEN, runtime=runtime)
        assert committed["success"] is False and _BF in committed["error"], target
    assert (await FileWriterAgent.commit_write(str(other), "other: 2\n", runtime=layout.runtime))["success"] is True
    assert _unchanged(layout)


class _ConsensusVessel:
    """What ``submit_write_with_consensus`` reads from its runtime, with an approving quorum; the production method runs."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = str(config_path)
        self.event_log = SimpleNamespace(log=AsyncMock(return_value="row-1"))

    async def submit_intent_with_consensus(self, intent, params=None, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"intent": None, "results": [], "verifications": [],
                "consensus": SimpleNamespace(outcome=ConsensusOutcome.APPROVED)}


async def test_the_consensus_commit_passes_the_vessel(layout: SimpleNamespace) -> None:
    """T27: intent -> approved -> commit_write(runtime=self) -> refused; only the runtime names this file."""
    vessel = _ConsensusVessel(layout.custom)
    refused = await ProbOSRuntime.submit_write_with_consensus(vessel, str(layout.custom), _CHOSEN)
    assert refused["committed"] is False
    assert vessel.event_log.log.await_args.kwargs["event"] == "write_failed"
    assert _unchanged(layout)
    other = layout.checkout / "config" / "other.yaml"
    allowed = await ProbOSRuntime.submit_write_with_consensus(vessel, str(other), "other: 2\n")
    assert allowed["committed"] is True and other.read_text(encoding="utf-8") == "other: 2\n"


async def test_the_bundled_agents_direct_write_cannot_reach_a_config_file(layout: SimpleNamespace) -> None:
    """T28: the notes agent joins a model-chosen filename to ~/.probos/notes; both helpers pass their runtime."""
    notes = layout.home / ".probos" / "notes"
    notes.mkdir(parents=True)
    assert not await organizer_agents._mesh_write_file(None, f"{notes}/../config.yaml", _CHOSEN)
    for module in (organizer_agents, productivity_agents):
        assert not await module._mesh_write_file(layout.runtime, str(layout.custom), _CHOSEN), module.__name__
    assert _unchanged(layout)
    assert await organizer_agents._mesh_write_file(layout.runtime, f"{notes}/note.md", "a note\n")
    assert (notes / "note.md").read_text(encoding="utf-8") == "a note\n"


class _GatedVessel(_ConsensusVessel):
    """The DAG executor's view of the vessel: the production gate table, adapters and consensus commits run; the quorum approves."""

    def __init__(self, config_path: Path) -> None:
        super().__init__(config_path)
        self.mcp_bridge = None  # no bridge wired: an approved invoke cannot run
        self.dependent_calls: list[str] = []
        self.episodes: list[dict] = []

    def gated_commit_for(self, intent):  # type: ignore[no-untyped-def]
        return ProbOSRuntime.gated_commit_for(self, intent)

    async def _gated_commit_write(self, params, *, timeout=None):  # type: ignore[no-untyped-def]
        return await ProbOSRuntime._gated_commit_write(self, params, timeout=timeout)

    async def _gated_commit_mcp_invoke(self, params, *, timeout=None):  # type: ignore[no-untyped-def]
        return await ProbOSRuntime._gated_commit_mcp_invoke(self, params, timeout=timeout)

    async def submit_write_with_consensus(self, path, content, timeout=None, policy=None):  # type: ignore[no-untyped-def]
        return await ProbOSRuntime.submit_write_with_consensus(self, path, content, timeout=timeout, policy=policy)

    async def submit_mcp_invoke_with_consensus(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await ProbOSRuntime.submit_mcp_invoke_with_consensus(self, *args, **kwargs)

    async def _store_mcp_invoke_episode(self, **kwargs):  # type: ignore[no-untyped-def]
        self.episodes.append(kwargs)

    async def submit_intent(self, intent, params, timeout=None):  # type: ignore[no-untyped-def]
        self.dependent_calls.append(intent)
        return [IntentResult(intent_id="i2", agent_id="a2", success=True, result={"ran": True}, confidence=0.9)]


async def _run_plan(vessel: _GatedVessel, first: TaskNode) -> tuple[TaskDAG, dict, list, SimpleNamespace]:
    """*first*, then a node that depends on it, through the production executor with an escalation manager that records."""
    escalation = SimpleNamespace(user_wait_seconds=0.0, escalate=AsyncMock())
    events: list[tuple[object, str]] = []

    async def _on_event(event, data):  # type: ignore[no-untyped-def]
        events.append((event, data["node"].id))

    dag = TaskDAG(nodes=[first, TaskNode(id="after", intent="observe_after", depends_on=[first.id])])
    outcome = await DAGExecutor(vessel, escalation_manager=escalation).execute(dag, on_event=_on_event)  # type: ignore[arg-type]
    return dag, outcome, events, escalation


async def test_a_refused_consensus_write_fails_its_plan_node_and_holds_its_dependent(layout: SimpleNamespace) -> None:
    """T41 (A2, review F1): plan -> gate table -> consensus commit -> commit_write refused; the node fails, its dependent does not run, nothing escalates."""
    other = layout.checkout / "config" / "other.yaml"
    vessel = _GatedVessel(layout.custom)
    dag, _, _, _ = await _run_plan(vessel, TaskNode(
        id="write", intent="write_file", params={"path": str(other), "content": "other: 2\n"}, use_consensus=True))
    assert [node.status for node in dag.nodes] == ["completed", "completed"], "premise: an allowed write completes and releases its dependent"
    assert vessel.dependent_calls == ["observe_after"] and other.read_text(encoding="utf-8") == "other: 2\n"

    vessel = _GatedVessel(layout.custom)
    dag, outcome, events, escalation = await _run_plan(vessel, TaskNode(
        id="write", intent="write_file", params={"path": str(layout.custom), "content": _CHOSEN}, use_consensus=True))
    write, after = dag.nodes
    assert outcome["results"]["write"]["committed"] is False, "premise: the vote approved and the commit was refused"
    assert vessel.event_log.log.await_args.kwargs["event"] == "write_failed", "premise: the production commit ran"
    assert write.status == "failed", write.status
    assert (EventType.NODE_FAILED, "write") in events and (EventType.NODE_COMPLETE, "write") not in events, events
    assert vessel.dependent_calls == [], "the dependent ran on a write that never happened"
    assert after.status == "failed" and outcome["results"]["after"] == {"error": "Dependency deadlock"}
    assert escalation.escalate.await_count == 0, "an approved commit that did not happen is not escalated"
    assert (outcome["completed_count"], outcome["failed_count"]) == (0, 2)
    assert _unchanged(layout)


async def test_a_gated_path_that_does_not_report_committed_is_judged_by_its_vote() -> None:
    """T43 (A2): without a ``committed`` key an approved gated node completes, as on the base; both production gated paths set the key."""
    async def _gate(params, *, timeout=None):  # type: ignore[no-untyped-def]
        return {"results": [], "consensus": SimpleNamespace(outcome=ConsensusOutcome.APPROVED)}

    node = TaskNode(id="t1", intent="write_file", params={}, use_consensus=True)
    dag = TaskDAG(nodes=[node])
    await DAGExecutor(SimpleNamespace(gated_commit_for=lambda intent: _gate)).execute(dag)  # type: ignore[arg-type]
    assert node.status == "completed", node.status


async def test_an_approved_mcp_invoke_that_did_not_run_fails_its_plan_node(layout: SimpleNamespace) -> None:
    """T44 (A2): the gate table's other path; with no bridge wired the approved invoke does not run, so the node fails and its dependent waits."""
    vessel = _GatedVessel(layout.custom)
    dag, outcome, events, escalation = await _run_plan(vessel, TaskNode(
        id="invoke", intent="mcp_invoke", params={"server_url": "srv", "tool": "do_thing", "arguments": {}}, use_consensus=True))
    invoke, after = dag.nodes
    assert outcome["results"]["invoke"]["committed"] is False, "premise: approved, not invoked"
    assert vessel.event_log.log.await_args.kwargs["event"] == "mcp_invoke_failed", "premise: the production consensus path ran"
    assert invoke.status == "failed", invoke.status
    assert (EventType.NODE_FAILED, "invoke") in events and (EventType.NODE_COMPLETE, "invoke") not in events, events
    assert vessel.dependent_calls == [] and after.status == "failed"
    assert escalation.escalate.await_count == 0


# ── 4. Office document writers ────────────────────────────────────────────


async def test_office_create_refuses_the_loaded_config_and_the_home_config(layout: SimpleNamespace) -> None:
    """T29."""
    docx = DocxAgent(pool="office", runtime=layout.runtime)
    pptx = PptxAgent(pool="office", runtime=layout.runtime)
    for target in (layout.custom, layout.home_config):
        with pytest.raises(PermissionError, match=_BF):
            await docx.handle_intent(IntentMessage(intent="docx_create", params={
                "title": "Settings", "content": ["x"], "output_path": str(target)}))
        with pytest.raises(PermissionError, match=_BF):
            await pptx.handle_intent(IntentMessage(intent="pptx_create", params={
                "title": "Settings", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(target)}))
    assert _unchanged(layout)
    notes = layout.checkout / "docs" / "notes.docx"
    control = await docx.handle_intent(IntentMessage(intent="docx_create", params={
        "title": "Notes", "content": ["x"], "output_path": str(notes)}))
    assert control is not None and control.success is True and notes.is_file()


async def test_office_revise_and_update_refuse_a_link_to_the_loaded_config(layout: SimpleNamespace) -> None:
    """T30."""
    docx_alias = _link(layout.custom, layout.checkout / "docs" / "settings.docx")
    xlsx_alias = _link(layout.custom, layout.checkout / "docs" / "settings.xlsx")
    with pytest.raises(PermissionError, match=_BF):
        await DocxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="docx_revise", params={
            "file_path": str(docx_alias), "instructions": "amend"}))
    with pytest.raises(PermissionError, match=_BF):
        await XlsxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="xlsx_update", params={
            "file_path": str(xlsx_alias), "sheet": "Sheet", "updates": {"A1": "x"}}))
    assert _unchanged(layout)
    notes = layout.checkout / "docs" / "notes.docx"
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
    revised = await DocxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="docx_revise", params={
        "file_path": str(notes), "instructions": "tidy"}))
    assert revised is not None and revised.success is True


async def test_the_other_writers_log_a_protected_refusal_without_the_callers_path(
    layout: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """T40 (A1, D16): FileWriterAgent's and the office writers' BF-911 log lines carry the operation and the reason code.

    Each target is its writer's loaded config file (its runtime's ``config_path``) in a directory named
    SENTINEL_PRIVATE_DIR, so the name comparison refuses it with no link; the returned or raised refusal names the path.
    """
    loggers = (FileWriterAgent.__module__, DocxAgent.__module__)
    for name in loggers:
        caplog.set_level("WARNING", logger=name)
    private = layout.checkout / "SENTINEL_PRIVATE_DIR"
    private.mkdir()
    targets = {suffix: private / f"settings{suffix}" for suffix in (".yaml", ".docx", ".xlsx")}
    for target in targets.values():
        target.write_bytes(b"settings")
    vessels = {suffix: SimpleNamespace(config_path=str(target)) for suffix, target in targets.items()}
    writer = FileWriterAgent(pool="filesystem", runtime=vessels[".yaml"])
    await writer.start()
    proposal = await writer.handle_intent(IntentMessage(intent="write_file", params={"path": str(targets[".yaml"]), "content": _CHOSEN}))
    assert proposal is not None and proposal.success is False and "SENTINEL_PRIVATE_DIR" in (proposal.error or "")
    committed = await FileWriterAgent.commit_write(str(targets[".yaml"]), _CHOSEN, runtime=vessels[".yaml"])
    assert committed["success"] is False and "SENTINEL_PRIVATE_DIR" in committed["error"]
    docx = DocxAgent(pool="office", runtime=vessels[".docx"])
    calls = (
        (docx, "docx_create", {"title": "Settings", "content": ["x"], "output_path": str(targets[".docx"])}),
        (PptxAgent(pool="office", runtime=vessels[".yaml"]), "pptx_create", {
            "title": "Settings", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(targets[".yaml"])}),
        (docx, "docx_revise", {"file_path": str(targets[".docx"]), "instructions": "amend"}),
        (XlsxAgent(pool="office", runtime=vessels[".xlsx"]), "xlsx_update", {
            "file_path": str(targets[".xlsx"]), "sheet": "Sheet", "updates": {"A1": "x"}}),
    )
    for agent, intent, params in calls:
        with pytest.raises(PermissionError, match=_BF) as raised:
            await agent.handle_intent(IntentMessage(intent=intent, params=params))
        assert "SENTINEL_PRIVATE_DIR" in str(raised.value), intent
    logged = _logged(caplog, *loggers)
    assert "SENTINEL_PRIVATE_DIR" not in logged
    for operation in ("propose_write", "commit_write", "docx_create", "pptx_create", "docx_revise", "xlsx_update"):
        assert f"operation={operation} reason_code=protected_write_refused" in logged, operation
    assert all(target.read_bytes() == b"settings" for target in targets.values())
    assert _unchanged(layout)


# ── 5. The builder is unchanged ───────────────────────────────────────────


async def test_a_build_still_edits_a_worktrees_config(layout: SimpleNamespace) -> None:
    """T31: BF-897 keeps a build out of the running checkout, so its config/system.yaml is another file."""
    assert _refused(protected_write_refusal(str(layout.live))), "premise: the live config is protected in this layout"
    change = {"path": "config/system.yaml", "mode": "modify",
              "replacements": [{"search": "crew_scope_token: ''", "replace": "crew_scope_token: build"}]}
    result, commit = await _build(layout.worktree, [change])
    assert not result.error, result.error
    assert (layout.worktree / "config" / "system.yaml").read_text(encoding="utf-8") == "auth:\n  crew_scope_token: build\n"
    assert "config/system.yaml" in commit.await_args.args[0]
    assert _unchanged(layout)


# ── 6. The inventory (AST censuses over tracked files) ────────────────────

_RULE = "protected_write_refusal"
_RULE_HELPERS = frozenset({"_write_key", "_same_key"})
_CENSUS_NAMES = frozenset({_RULE, "constitution_write_refusal", "commit_write", *_RULE_HELPERS})
_EXPECTED_CALLERS = {
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
    ("src/probos/skill_framework.py", "DocxAgent.create_docx"),
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx"),
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx"),
}
# The one caller of AD-1344's rule that does not call this one, and why (D6).
_BUILDER_ONLY = {
    ("src/probos/cognitive/builder_paths.py", "builder_write_refusal"):
        "a build runs in a linked worktree (BF-897 operator_checkout_refusal), whose config/system.yaml is another file",
}
_COMMIT_WRITE_CALLERS = {
    ("src/probos/runtime.py", "ProbOSRuntime.submit_write_with_consensus"),
    ("src/probos/agents/utility/organizer_agents.py", "_mesh_write_file"),
    ("src/probos/agents/utility/productivity_agents.py", "_mesh_write_file"),
}


@lru_cache(maxsize=1)
def _call_sites() -> dict[str, frozenset[tuple[str, str, bool]]]:
    """(file, function, passes runtime=) for each call of a census name in the tracked source."""
    sites: dict[str, set[tuple[str, str, bool]]] = {}
    for rel in _tracked("src/probos"):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            name = _callee(call)
            if name in _CENSUS_NAMES:
                passes_runtime = any(keyword.arg == "runtime" for keyword in call.keywords)
                sites.setdefault(name, set()).add((rel, scope, passes_runtime))
    return {name: frozenset(found) for name, found in sites.items()}


def _functions(name: str) -> set[tuple[str, str]]:
    return {(rel, scope) for rel, scope, _ in _call_sites().get(name, frozenset())}


def test_census_callers_are_the_inventoried_writers_and_the_helpers_stay_private() -> None:
    """T32."""
    assert _functions(_RULE) == _EXPECTED_CALLERS
    helper_files = {rel for name in _RULE_HELPERS for rel, _ in _functions(name)}
    assert helper_files == {"src/probos/security/file_access.py"}


def test_census_every_caller_of_ad1344s_rule_but_the_builder_calls_this_one() -> None:
    """T33: a writer that gains AD-1344's guard (its census B asks for one) must gain this one too."""
    constitution = _functions("constitution_write_refusal")
    assert set(_BUILDER_ONLY) <= constitution, "premise: the builder boundary calls AD-1344's rule"
    assert constitution - set(_BUILDER_ONLY) == _functions(_RULE)


def test_census_every_commit_write_call_passes_the_vessel() -> None:
    """T34."""
    sites = _call_sites().get("commit_write", frozenset())
    found = {(rel, scope) for rel, scope, _ in sites}
    assert found == _COMMIT_WRITE_CALLERS, (
        f"commit_write callers changed: new {sorted(found - _COMMIT_WRITE_CALLERS)}, gone "
        f"{sorted(_COMMIT_WRITE_CALLERS - found)}. Pass runtime=<the vessel> at a new call, add it to "
        "_COMMIT_WRITE_CALLERS and report the inventory change to the Architect (a name census, not a reachability proof)"
    )
    assert all(passes for _, _, passes in sites), (
        f"a commit_write call does not pass runtime=: {sorted(site for site in sites if not site[2])}"
    )


def test_census_the_captains_channels_do_not_consult_the_rule() -> None:
    """T35: no tracked script, hook or workflow with a suffix in ``_CHANNEL_SUFFIXES`` names the rule (no friction)."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml")
                if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        assert _RULE not in (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace"), rel
