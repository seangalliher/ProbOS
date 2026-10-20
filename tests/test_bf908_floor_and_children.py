"""BF-908 (#1605): the config files join the read floor, content search re-checks every match, and what a child process can and cannot read (slice C1b).

What each test proves, and what it does not (contract section 10). No test here touches the Captain's OS keyring, config
files or data directory: ``tests/conftest.py`` forces the fail keyring backend and a temporary data directory, the autouse
fixture below points ``Path.home()`` at a folder under ``tmp_path``, and every config file, data directory and search root is
under ``tmp_path``. Every token is synthetic (``tests/fixtures/crew_scope_keyring.py`` and ``ENV_PROBE`` below). The J tests
drive the floor, the readers an agent can reach and the content-search agent. The K tests start real children (a shell ``set``
or ``env`` dump, a PowerShell dump, ``run_python``'s sandbox, a shell ``type`` or ``cat``): they run the commands in
``_CHILD_COMMANDS`` and nothing else (``_child`` refuses any other), and none of them imports the keyring module (K5), because a
child built through ``build_command_env`` does not inherit ``PYTHON_KEYRING_BACKEND`` (a credential-shaped name), so a child
that imported it would reach the Captain's real keyring. A child's output and ``os.environ`` are never placed in an ``assert``,
a message or a print: a test derives LABELS, booleans or an exit code into a local first and asserts on that local alone. No
``assert`` calls a function on a child's output or names a result object that holds it: when an assertion fails, pytest's
rewriting prints a call's arguments and the repr of an attribute's owner (review round 1 of C1b found two such guards).

J1  the loaded config file is on the floor
    Proves: the file the vessel loaded (``runtime.config_path``, under a name no default uses) is refused by
    ``resolve_for_runtime``, a sibling in the same directory is not, and ``protected_config_files`` names the file.
    Does not prove: that a copy or a hard link of the file under another path is refused (residual R3), or that a shell
    command cannot read it (K4).
J2  both default config files are on the floor with no runtime
    Proves: ``file_access._REPO_DEFAULT_CONFIG`` is the file ``probos.__main__._repo_default_config_path()`` names (neither is
    patched), a reader with no runtime still gets that file and ``~/.probos/config.yaml``, and the platform data directory
    still leads ``protected_read_roots``.
    Does not prove: that either file exists here. The floor names paths, present or not.
J3  an unusable runtime adds no config file
    Proves: a ``MagicMock`` runtime, and a runtime whose ``config_path`` is empty, holds a NUL or is not a string, adds
    nothing and never raises: the two defaults remain. A host with no home directory keeps the checkout's file alone.
    Does not prove: what a real runtime holds after startup (J1).
J4  every floor reader refuses the config file
    Proves: the mesh-reachable ``FileReaderAgent`` refuses the config file and still reads its sibling; the read tools'
    resolvers (``ReadFileTool``, ``CodebaseReadSourceTool``) raise ``FileAccessDenied``; listing the directory still works and
    returns names only.
    Does not prove: readers that do not call the floor: a shell command and ``run_python`` (residual R2, pinned by K4).
J5  content search drops matches in a protected file (``python`` and ``rg``)
    Proves: through ``decide`` and ``act``, with the engine named in the result, a root that holds the loaded config file
    returns the matches of its other files and none of that file's, though the engine itself read it (the raw engine output is
    the control). The ``rg`` variant skips when no ``rg`` binary is found.
    Does not prove: that a root which is not admitted is refused (BF-758's tests do), or that a dropped match is reported: a
    match in a protected file is dropped whole, and the result does not name it.
J6  a search above the data directory drops the vault
    Proves: a root that holds the runtime's data directory returns the matches outside it and none of the vault's, nor of
    another file in the data directory, on the Python engine. The search sets ``include_ignored``: the walk prunes a directory
    named ``data`` by default, so without it the engine never reaches the vault and the test could not fail.
    Does not prove: the rg engine here (J5), or the default search, which never reaches the data directory on the Python engine.
J7  a search that drops nothing returns the engine's result unchanged
    Proves: with no protected file under the root, ``act`` returns exactly what the Python engine returned: the same records
    and the same ``count``.
    Does not prove: the same for the rg engine.
J8  a loaded config file that is a default is listed once
    Proves: when ``runtime.config_path`` names the checkout's or the home default (spelled with a ``..`` hop),
    ``protected_config_files`` lists each file once, loaded first, and the data directory still leads ``protected_read_roots``.
    Does not prove: anything about two different files that are hard links of one another (residual R3).
J9  a protected first match does not use up the quota (``python`` and ``rg``)
    Proves: with ``max_results=1`` and the loaded config file met first (the unfloored Python engine returns it; the fake rg
    prints it first), ``act`` returns the public match, from the engine named.
    Does not prove: real rg's order (D28: it is not fixed; J5 runs the real binary).
J10 a search that no public match was cut from is not truncated (``python`` and ``rg``)
    Proves: a protected match does not count toward the cap: one public match under a cap of two is ``truncated`` False.
    Does not prove: that ``truncated`` means "more matches exist" (D27, R13: it means "the cap was reached").
J11 a search the cap really cut is truncated (``python`` and ``rg``)
    Proves: three public matches under a cap of two return the first two, ``count`` 2, ``truncated`` True; the protected
    match ahead of them takes no slot.
    Does not prove: the same for matches inside one file under real rg (rg's per-file ``--max-count``).
J12 ``handle_intent`` returns the public match behind a protected one
    Proves: at the boundary the DM pipeline consumes, a search with ``max_results=1`` whose first match is protected returns
    the public match, not ``[]``.
    Does not prove: the DM pipeline's rendering (it renders the list it is given).
J13 ``act`` drops a protected match an engine returned (``python`` and ``rg``)
    Proves: defence in depth: with each engine replaced by one that ignores the floor, ``act`` still returns only the public
    match. Runs without an ``rg`` binary.
    Does not prove: that today's engines ever return one (J9-J11 show they do not).
J14 the floor decides each file once per search
    Proves: for one public file with thirty matching lines, a search builds the floor's roots three times (the root check,
    the engines' floor, the final check's fresh floor) and makes four decisions (the root; the config file and the public
    file, each at its first match; the public file again, in the final check), never one per line.
    Detector premise: ``_ReadFloor`` looks the floor's functions up on ``probos.security.file_access`` at call time (the
    module's lazy-import convention); if it bound them at import, the counts would fall and the test would fail, not pass.
    Does not prove: wall-clock cost.
J15 rg output whose every line the floor refused is an empty rg result
    Proves: lines that parsed and were refused are not BF-895's "rg and the parser disagree" case: the result is rg's, empty,
    not a fallback to the Python engine.
    Does not prove: BF-895's own fallback (its tests do).
J16 the search's floor decides as ``resolve_for_runtime`` does
    Proves: on a confined vessel (``read_roots`` set), for a public file, the loaded config, a data-directory file, a workspace
    file and a file outside every readable root, ``_ReadFloor.permits`` gives ``resolve_for_runtime``'s answers, which are
    True, False, False, True, False.
    Does not prove: a symlink's target (BF-758's tests cover resolution).
J17 the final check decides with a fresh floor (``python`` and ``rg``)
    Proves: when the floor the engines ask allows the loaded config file (a double, standing for a decision taken before a
    link under the root was retargeted), ``act`` builds a second, real ``_ReadFloor`` after the engine ran and drops that
    file's match: the engines' cached allows are not the final authorization (review round 2 of C1b). Runs without ``rg``.
    Detector premise: ``act`` looks ``_ReadFloor`` up on the module at call time, so the double sees every floor a search
    builds; were it bound elsewhere, ``built`` would be empty and the test would fail, not pass.
    Does not prove: a real link retargeted mid-search (none is created here: creating one needs privileges on Windows), or
    a link changed back before the final check runs (residual R15).
J18 ``handle_intent`` returns no match only the fresh floor refuses
    Proves: the same at the boundary the DM pipeline consumes, on the Python engine (the reviewer's reproduction path).
    Does not prove: the pipeline's rendering (it renders the list it is given).
J19 a walk with no match asks the floor about no file
    Proves: on the Python engine, twenty-one walked files with no match cost the root check's decision and no other: the
    engines' floor is asked at a file's first match, not before every open (A3 asked once per walked file).
    Does not prove: wall-clock cost, or that a refused file is not read (it is, up to its first match: residual R14).
J20 an ``OSError`` inside the floor propagates from the search (``python`` and ``rg``)
    Proves: when the floor's decision raises an ``OSError`` for the loaded config file (a defect in the floor, not a
    path-resolution failure, which ``resolve_read_path`` turns into a denial), ``act`` raises that same exception object:
    the Python engine's file-I/O handler does not take it for an unreadable file (review round 3 of C1b; A4 returned the
    public match and dropped the error). The rg variant is the control: its floor call was never under a handler.
    Detector premise: ``_ReadFloor.permits`` looks ``resolve_read_path`` up on ``probos.security.file_access`` at call time
    (J14's premise); were it bound at import, nothing would raise and the test would fail, not pass.
    Does not prove: what the mesh does with the exception.
J21 ``handle_intent`` propagates an ``OSError`` inside the floor
    Proves: the same at the boundary the DM pipeline consumes, on the Python engine.
    Does not prove: the pipeline's handling of an agent that raises.
J22 a file that cannot be opened or read still degrades
    Proves: on the Python engine, a file whose text-mode open raises ``OSError`` contributes nothing, a file whose read fails
    after one matching line keeps that line, and the walk goes on to the next file: the handler still covers the file's own
    open and read. Only text-mode opens of those two names fail; the walker's binary sniff (``"rb"``) reads them as they are.
    Does not prove: a real disk or permission error (both are injected).
K1  no agent command's child sees the token
    Proves: with the keyring's token held by the vessel and ``PROBOS_CREW_SCOPE_TOKEN`` set to ``ENV_PROBE`` in its environment
    (a child that inherits the environment sees the probe), the children ``run_command`` and the shell agent start print an
    environment that holds neither the probe nor the keyring's token.
    Does not prove: that they cannot read the keyring or a file. They run as the same user (residuals R1, R2).
K2  a ``run_python`` child sees no token in its environment
    Proves: the same for the sandbox's child: it prints its environment (``PATH`` is among the names) and neither value is in it.
    Does not prove: the same limit as K1.
K3  an environment variable would reach every trusted launch
    Proves: a variable in the vessel's environment is in ``trusted_command_env()`` (why D6 refuses an environment variable as a
    source) and in neither agent-command environment (``build_command_env()`` and the builder's pytest shape); the keyring's token
    is in none of the three.
    Does not prove: what any trusted launch does with its environment.
K4  a shell command can still read a token left in the config file
    Proves, as a pinned limitation (residual R2): a shell command reads a config file that holds a token, though the floor refuses
    the same file to every reader that calls it.
    Does not prove: that this is acceptable. It fails only when OS-level isolation (AD-995) closes the route, and then it goes.
K5  no child script imports the keyring module
    Proves: no command or script in ``_CHILD_COMMANDS``, the only ones a child here runs, names the keyring.
    Does not prove: anything about a child started outside this file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import probos.__main__ as main_module
from probos.agents import code_search
from probos.agents.code_search import CodeSearchAgent
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import CodebaseReadSourceTool, ReadFileTool, RunCommandTool
from probos.config import SystemConfig
from probos.credential_store import crew_scope_token
from probos.execution.command_env import build_command_env, trusted_command_env
from probos.execution.isolation import ExecutionRequest, SubprocessSandbox
from probos.execution.workspace import _platform_data_dir
from probos.security import file_access
from probos.security.file_access import (
    FileAccessDenied,
    protected_config_files,
    protected_read_roots,
    resolve_for_runtime,
)
from probos.types import IntentMessage
from tests.fixtures.crew_scope_keyring import FILE_TOKEN, KEYRING_TOKEN, MemoryKeyring, loaded_store

#: Synthetic; planted in this process's environment under a token-shaped name (D6: no environment-variable source).
ENV_PROBE = "bf908-env-probe-value-c19"
_PLANTED_NAME = "PROBOS_CREW_SCOPE_TOKEN"
_PLANTS: dict[str, str] = {"ENV_PROBE": ENV_PROBE, "KEYRING_TOKEN": KEYRING_TOKEN}

_IS_WINDOWS = sys.platform == "win32"

# Every command or script a child process of this file runs, and nothing else: ``_child`` refuses any other. None mentions the
# keyring (K5). ``{path}`` is filled by ``_child``.
_WINDOWS_ENV_DUMP = "set"
_POWERSHELL_ENV_DUMP = "Get-ChildItem Env: | ForEach-Object { $_.Name + '=' + $_.Value }"
_POSIX_ENV_DUMP = "env"
_PYTHON_ENV_DUMP = "import json, os\nprint(json.dumps(sorted(os.environ.items())))"
_WINDOWS_TYPE_FILE = 'type "{path}"'
_POSIX_CAT_FILE = "cat '{path}'"
_CHILD_COMMANDS: tuple[str, ...] = (
    _WINDOWS_ENV_DUMP,
    _POWERSHELL_ENV_DUMP,
    _POSIX_ENV_DUMP,
    _PYTHON_ENV_DUMP,
    _WINDOWS_TYPE_FILE,
    _POSIX_CAT_FILE,
)

_VARIANTS = [
    pytest.param(
        "windows",
        marks=pytest.mark.skipif(
            not _IS_WINDOWS,
            reason="cmd.exe's set and PowerShell's Env: provider exist only on Windows",
        ),
    ),
    pytest.param(
        "posix",
        marks=pytest.mark.skipif(
            _IS_WINDOWS,
            reason="the /bin/sh env variant needs a POSIX host; this host is Windows",
        ),
    ),
]


class _FakeRuntime:
    """RunCommandTool keeps its runtime but never reads it to run a shell command."""


@pytest.fixture(autouse=True)
def _synthetic_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``Path.home()`` is a folder under ``tmp_path``: no test here names the Captain's own ``~/.probos``."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _child(template: str, **fields: str) -> str:
    """The command a child runs: *template* must be listed in ``_CHILD_COMMANDS``; *fields* fill its ``{path}``."""
    assert template in _CHILD_COMMANDS
    return template.format(**fields) if fields else template


def _labels_seen_in(text: str, planted: dict[str, str]) -> list[str]:
    """The LABELS whose synthetic value occurs in *text*: all a test may assert on, never the text itself."""
    return sorted(label for label, value in planted.items() if value in text)


def _prints_an_environment(stdout: str) -> bool:
    """True when *stdout* holds a ``PATH=...`` line: the child printed its environment, not nothing."""
    return any(line.strip().upper().startswith("PATH=") for line in stdout.splitlines())


def _runtime(tmp_path: Path, config_path: Path) -> SimpleNamespace:
    """The vessel as the floor sees it: a data directory, a loaded config file and an unconfined read policy."""
    data = tmp_path / "data"
    return SimpleNamespace(
        data_dir=data,
        config_path=str(config_path),
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(data / "execution" / "workspaces")),
            security_infra=SimpleNamespace(read_roots=[]),
        ),
    )


def _project(tmp_path: Path, config_name: str = "vessel-settings.yaml") -> tuple[Path, Path, Path]:
    """A folder holding a config file that holds a token (under *config_name*) and an ordinary sibling."""
    project = tmp_path / "project"
    project.mkdir()
    cfg = project / config_name
    cfg.write_text(f"auth:\n  crew_scope_token: {FILE_TOKEN}\n", encoding="utf-8")
    notes = project / "notes.txt"
    notes.write_text(f"remember {FILE_TOKEN}\n", encoding="utf-8")
    return project, cfg, notes


def _paths(result: dict) -> list[Path]:
    return [Path(match["path"]).resolve() for match in result["data"]]


async def _vessel_holding_the_keyring_token() -> SimpleNamespace:
    """A runtime whose real CredentialStore has read the keyring's token once, as startup does (no ``get`` is called)."""
    config = SystemConfig()
    return SimpleNamespace(
        config=config, credential_store=await loaded_store(config, MemoryKeyring(token=KEYRING_TOKEN)),
    )


# --------------------------------------------------------------------------- #
# J -- the config files are on the floor, and content search re-checks every match
# --------------------------------------------------------------------------- #


def test_the_loaded_config_file_is_on_the_floor(tmp_path: Path) -> None:
    _project_dir, cfg, notes = _project(tmp_path)
    rt = _runtime(tmp_path, cfg)

    with pytest.raises(FileAccessDenied):
        resolve_for_runtime(str(cfg), rt)
    assert resolve_for_runtime(str(notes), rt) == notes.resolve()
    assert cfg.resolve() in protected_config_files(rt)


def test_both_default_config_files_are_on_the_floor_without_a_runtime() -> None:
    assert file_access._REPO_DEFAULT_CONFIG == main_module._repo_default_config_path()
    files = protected_config_files(None)
    assert file_access._REPO_DEFAULT_CONFIG.resolve() in files
    assert (Path.home() / ".probos" / "config.yaml").resolve() in files
    assert protected_read_roots(None)[0] == _platform_data_dir().resolve()


@pytest.mark.parametrize(
    "runtime",
    [
        pytest.param(MagicMock(), id="mock"),
        pytest.param(SimpleNamespace(config_path=""), id="config_path_empty"),
        pytest.param(SimpleNamespace(config_path="bad\x00name.yaml"), id="config_path_nul"),
        pytest.param(SimpleNamespace(config_path=12345), id="config_path_number"),
    ],
)
def test_a_mock_runtime_adds_no_config_file(runtime: object) -> None:
    files = protected_config_files(runtime)

    assert files == [
        file_access._REPO_DEFAULT_CONFIG.resolve(),
        (Path.home() / ".probos" / "config.yaml").resolve(),
    ]


def test_a_host_without_a_home_directory_keeps_the_checkout_config_on_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_home(cls: type[Path]) -> Path:
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(Path, "home", classmethod(_no_home))

    assert protected_config_files(None) == [file_access._REPO_DEFAULT_CONFIG.resolve()]


@pytest.mark.parametrize("loaded", ["checkout_default", "home_default"])
def test_a_loaded_default_config_file_is_listed_once(tmp_path: Path, loaded: str) -> None:
    checkout = file_access._REPO_DEFAULT_CONFIG.resolve()
    home = (Path.home() / ".probos" / "config.yaml").resolve()
    # Spelled with a ``..`` hop: the floor compares resolved paths, not spellings.
    spelled = {
        "checkout_default": file_access._REPO_DEFAULT_CONFIG.parent / ".." / "config" / "system.yaml",
        "home_default": Path.home() / ".probos" / ".." / ".probos" / "config.yaml",
    }[loaded]
    rt = _runtime(tmp_path, spelled)

    files = protected_config_files(rt)
    roots = protected_read_roots(rt)

    assert files == ([checkout, home] if loaded == "checkout_default" else [home, checkout])
    assert roots == [(tmp_path / "data").resolve(), *files]


async def test_every_floor_reader_refuses_the_config_file(tmp_path: Path) -> None:
    project, cfg, notes = _project(tmp_path)
    rt = _runtime(tmp_path, cfg)

    refused = await FileReaderAgent(agent_id="fr-1", runtime=rt)._read_file(str(cfg))
    sibling = await FileReaderAgent(agent_id="fr-1", runtime=rt)._read_file(str(notes))
    refusal_holds_token = FILE_TOKEN in str(refused)
    assert refused["success"] is False
    assert refusal_holds_token is False
    assert sibling["success"] is True  # control: the agent reads, so the refusal above is the floor's

    with pytest.raises(FileAccessDenied):
        ReadFileTool(rt).resolve_source_path(str(cfg))
    with pytest.raises(FileAccessDenied):
        CodebaseReadSourceTool(rt).resolve_source_path(str(cfg))

    listing = await DirectoryListAgent(agent_id="dl-1", runtime=rt)._list_directory(str(project))
    assert listing["success"] is True
    listing_holds_token = FILE_TOKEN in str(listing)
    assert sorted(entry["name"] for entry in listing["data"]) == sorted([cfg.name, notes.name])
    assert listing_holds_token is False


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_content_search_drops_matches_in_a_protected_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    rg = code_search._resolve_rg_binary()
    if engine == "python":
        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
    elif rg is None:
        pytest.skip("no rg binary on PATH or under tools/: the rg engine cannot run on this host")
    project, cfg, notes = _project(tmp_path, config_name="system.yaml")
    rt = _runtime(tmp_path, cfg)
    agent = CodeSearchAgent(agent_id="cs-5", runtime=rt)
    plan = await agent.decide({"params": {"path": str(project), "pattern": FILE_TOKEN}})

    # Control: the engine itself reads both files, so the floor is what drops the config file's match.
    raw = agent._search_python(plan, project.resolve()) if engine == "python" else await agent._search_rg(
        rg, plan, project.resolve(),
    )
    assert raw is not None and raw["success"] is True
    assert sorted(_paths(raw)) == sorted([cfg.resolve(), notes.resolve()])

    result = await agent.act(plan)

    assert result["success"] is True
    assert result["engine"] == engine
    assert _paths(result) == [notes.resolve()]
    assert result["count"] == 1


async def test_a_search_above_the_data_directory_drops_the_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
    data = tmp_path / "data"
    data.mkdir()
    vault = data / "credential_vault.json"
    vault.write_text(f'{{"token": "{FILE_TOKEN}"}}\n', encoding="utf-8")
    # A name the floor does not know: only the data-directory rule refuses it, not the vault's leaf name.
    other = data / "ward_room_notes.txt"
    other.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    notes = tmp_path / "notes.txt"
    notes.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    rt = _runtime(tmp_path, tmp_path / "elsewhere" / "system.yaml")
    agent = CodeSearchAgent(agent_id="cs-6", runtime=rt)
    plan = await agent.decide({"params": {"path": str(tmp_path), "pattern": FILE_TOKEN, "include_ignored": True}})

    # Control: the engine reaches the vault, so the floor is what drops it.
    raw = agent._search_python(plan, tmp_path.resolve())
    assert sorted(_paths(raw)) == sorted([vault.resolve(), other.resolve(), notes.resolve()])

    result = await agent.act(plan)

    assert result["success"] is True
    assert result["engine"] == "python"
    assert _paths(result) == [notes.resolve()]


async def test_a_search_that_drops_nothing_returns_the_engine_s_result_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
    project = tmp_path / "project"
    project.mkdir()
    (project / "notes.txt").write_text(f"one {FILE_TOKEN}\ntwo\n{FILE_TOKEN} three\n", encoding="utf-8")
    (project / "more.txt").write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    rt = _runtime(tmp_path, tmp_path / "elsewhere" / "system.yaml")
    agent = CodeSearchAgent(agent_id="cs-7", runtime=rt)
    plan = await agent.decide({"params": {"path": str(project), "pattern": FILE_TOKEN}})
    engine_result = agent._search_python(plan, project.resolve())
    assert engine_result["success"] is True and engine_result["count"] == 3  # control: there is something to keep

    result = await agent.act(plan)

    assert result == engine_result
    assert result["count"] == engine_result["count"]


# --------------------------------------------------------------------------- #
# J9-J16 -- a protected file never uses up the result quota (amendment A3)
# --------------------------------------------------------------------------- #


def _quota_root(tmp_path: Path, public_matches: int) -> tuple[Path, SimpleNamespace, Path, list[Path]]:
    """A search root whose FIRST file in walk order is the loaded config (one match), then *public_matches* ordinary files.

    ``iter_files`` yields a directory's files sorted by name, so ``aa-vessel.yaml`` is read before ``note-0.txt``.
    """
    root = tmp_path / "project"
    root.mkdir()
    cfg = root / "aa-vessel.yaml"
    cfg.write_text(f"auth:\n  crew_scope_token: {FILE_TOKEN}\n", encoding="utf-8")
    public = [root / f"note-{index}.txt" for index in range(public_matches)]
    for path in public:
        path.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    return root, _runtime(tmp_path, cfg), cfg, public


class _FakeRg:
    """An ``rg`` child that prints one ``path<NUL>1:text`` record per path, in the order given, and exits 0.

    Real rg searches in parallel, so its output order is not fixed (D28); this one prints the protected file first every time.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.returncode = 0
        self._stdout = "".join(f"{path}\x001:{FILE_TOKEN}\n" for path in paths).encode("utf-8")

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""


def _use_engine(monkeypatch: pytest.MonkeyPatch, engine: str, rg_prints: list[Path]) -> None:
    """Pin the engine ``act`` takes: the Python engine (no rg), or the real rg engine reading ``_FakeRg``'s output."""
    if engine == "python":
        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
        return
    fake = _FakeRg(rg_prints)

    async def _spawn(*_args: object, **_kwargs: object) -> _FakeRg:
        return fake

    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg-stub")
    monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", _spawn)


async def _search(agent: CodeSearchAgent, root: Path, max_results: int) -> dict:
    plan = await agent.decide({"params": {"path": str(root), "pattern": FILE_TOKEN, "max_results": max_results}})
    return await agent.act(plan)


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_protected_first_match_does_not_use_up_the_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    agent = CodeSearchAgent(agent_id="cs-9", runtime=rt)
    if engine == "python":
        # Premise: the unfloored engine meets the protected file first, so it would fill a quota of one with it.
        plan = await agent.decide({"params": {"path": str(root), "pattern": FILE_TOKEN, "max_results": 1}})
        assert _paths(agent._search_python(plan, root.resolve())) == [cfg.resolve()]

    result = await _search(agent, root, max_results=1)

    assert result["success"] is True
    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_search_no_public_match_was_cut_from_is_not_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])

    result = await _search(CodeSearchAgent(agent_id="cs-10", runtime=rt), root, max_results=2)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1
    assert result["truncated"] is False


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_search_the_cap_really_cut_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=3)
    _use_engine(monkeypatch, engine, [cfg, *public])

    result = await _search(CodeSearchAgent(agent_id="cs-11", runtime=rt), root, max_results=2)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve(), public[1].resolve()]
    assert result["count"] == 2
    assert result["truncated"] is True


async def test_handle_intent_returns_the_public_match_behind_a_protected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])

    result = await CodeSearchAgent(agent_id="cs-12", runtime=rt).handle_intent(
        IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 1})
    )

    assert result is not None
    assert result.success is True
    assert [Path(match["path"]).resolve() for match in result.result] == [public[0].resolve()]


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_act_drops_a_protected_match_an_engine_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    unfloored = {
        "success": True,
        "data": [
            {"path": str(cfg), "line": 2, "text": FILE_TOKEN},
            {"path": str(public[0]), "line": 1, "text": FILE_TOKEN},
        ],
        "count": 2,
        "engine": engine,
        "truncated": False,
    }

    def _python(self: CodeSearchAgent, plan: dict, _root: Path, *, floor: object = None) -> dict:
        return dict(unfloored)

    async def _rg(self: CodeSearchAgent, rg: str, plan: dict, _root: Path, *, floor: object = None) -> dict:
        return dict(unfloored)

    monkeypatch.setattr(code_search, "_resolve_rg_binary", (lambda: None) if engine == "python" else (lambda: "rg-stub"))
    monkeypatch.setattr(CodeSearchAgent, "_search_python", _python)
    monkeypatch.setattr(CodeSearchAgent, "_search_rg", _rg)

    result = await _search(CodeSearchAgent(agent_id="cs-13", runtime=rt), root, max_results=5)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


def _count_floor_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count the floor's root-list builds (``protected_read_roots``) and decisions (``resolve_read_path``) from now on.

    Detector premise: ``_ReadFloor`` and ``resolve_for_runtime`` look both up on ``probos.security.file_access`` at call
    time (the module's lazy-import convention); if either bound them at import, the counts would fall and a test would fail.
    """
    calls = {"roots_built": 0, "decisions": 0}
    real_roots, real_resolve = file_access.protected_read_roots, file_access.resolve_read_path

    def _roots(runtime: object) -> list[Path]:
        calls["roots_built"] += 1
        return real_roots(runtime)

    def _resolve(raw: str, **kwargs: object) -> Path:
        calls["decisions"] += 1
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "protected_read_roots", _roots)
    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)
    return calls


async def test_the_floor_decides_each_file_once_per_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    public[0].write_text("".join(f"{FILE_TOKEN} {index}\n" for index in range(30)), encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    calls = _count_floor_calls(monkeypatch)

    result = await _search(CodeSearchAgent(agent_id="cs-14", runtime=rt), root, max_results=200)

    assert result["count"] == 30  # control: one public file, thirty matching lines
    # The root check builds the roots and decides once; the engines' floor builds them and decides once per FILE with a
    # match (the config file, the public file); the final check builds a fresh floor and decides once per distinct RESULT
    # path (the public file). Never once per matching line.
    assert calls == {"roots_built": 3, "decisions": 4}


async def test_rg_output_whose_every_line_the_floor_refused_is_an_empty_rg_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, _public = _quota_root(tmp_path, public_matches=0)
    _use_engine(monkeypatch, "rg", [cfg])

    result = await _search(CodeSearchAgent(agent_id="cs-15", runtime=rt), root, max_results=5)

    # Not a fallback to the Python engine: rg's lines parsed; the floor refused them.
    assert result == {"success": True, "data": [], "count": 0, "engine": "rg", "truncated": False}


def test_the_search_floor_decides_as_resolve_for_runtime_does(tmp_path: Path) -> None:
    base = tmp_path.resolve()  # the workspace root is used as given, so compare canonical paths
    project, cfg, notes = _project(base)
    data = base / "data"
    paths = [
        notes,
        cfg,
        data / "ward_room_notes.txt",
        data / "execution" / "workspaces" / "agent-1" / "draft.txt",
        base / "outside" / "elsewhere.txt",
    ]
    rt = _runtime(base, cfg)
    rt.config.security_infra.read_roots = [str(project)]  # confined: the project and, always, the workspace

    def _admitted(path: Path) -> bool:
        try:
            resolve_for_runtime(str(path), rt)
        except FileAccessDenied:
            return False
        return True

    floor = code_search._ReadFloor(rt)
    decided = [floor.permits(str(path)) for path in paths]

    assert decided == [_admitted(path) for path in paths]
    assert decided == [True, False, False, True, False]


class _AllowAll:
    """A floor double: the engines' floor as it answered before a link under the root was retargeted (it allows every path)."""

    def __init__(self, _runtime: object) -> None:
        self.asked: list[Path] = []

    def permits(self, path: str) -> bool:
        self.asked.append(Path(path).resolve())
        return True


def _first_floor_allows_all(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The first ``_ReadFloor`` a search builds is ``_AllowAll``; every later one is the real floor. Returns the floors built."""
    real = code_search._ReadFloor
    built: list[object] = []

    def _floor(runtime: object) -> object:
        floor = _AllowAll(runtime) if not built else real(runtime)
        built.append(floor)
        return floor

    monkeypatch.setattr(code_search, "_ReadFloor", _floor)
    return built


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_the_final_check_decides_with_a_fresh_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    built = _first_floor_allows_all(monkeypatch)

    result = await _search(CodeSearchAgent(agent_id="cs-17", runtime=rt), root, max_results=5)

    assert [type(floor).__name__ for floor in built] == ["_AllowAll", "_ReadFloor"]
    # Premise: the engines' floor was asked about the config file and allowed it, so the engine kept its match.
    assert cfg.resolve() in built[0].asked
    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


async def test_handle_intent_returns_no_match_only_the_fresh_floor_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])
    built = _first_floor_allows_all(monkeypatch)

    result = await CodeSearchAgent(agent_id="cs-18", runtime=rt).handle_intent(
        IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 5})
    )

    assert [type(floor).__name__ for floor in built] == ["_AllowAll", "_ReadFloor"]
    assert cfg.resolve() in built[0].asked
    assert result is not None
    assert result.success is True
    assert [Path(match["path"]).resolve() for match in result.result] == [public[0].resolve()]


async def test_a_walk_with_no_match_asks_the_floor_about_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, _public = _quota_root(tmp_path, public_matches=20)
    _use_engine(monkeypatch, "python", [])
    assert len(list(code_search.iter_files(root.resolve()))) == 21  # premise: the config file and twenty others are walked
    agent = CodeSearchAgent(agent_id="cs-19", runtime=rt)
    plan = await agent.decide({"params": {"path": str(root), "pattern": "bf908-no-file-holds-this"}})
    calls = _count_floor_calls(monkeypatch)

    result = await agent.act(plan)

    assert result["engine"] == "python"
    assert result["count"] == 0
    # Only the root check decides; the engines' floor and the final check's floor are built and asked about nothing.
    assert calls == {"roots_built": 3, "decisions": 1}


def _floor_raises_oserror_on(monkeypatch: pytest.MonkeyPatch, target: Path) -> OSError:
    """From now on the floor's decision raises a sentinel ``OSError`` for *target*'s name and decides every other path as before.

    R16's defect: an error inside the floor that is not a path-resolution failure (``resolve_read_path`` turns those into a
    denial). ``_ReadFloor.permits`` looks ``resolve_read_path`` up on ``probos.security.file_access`` at call time (J14's
    premise), so the sentinel reaches every floor a search builds; the root check's path delegates to the real function.
    """
    injected = OSError("bf908-injected floor defect")
    real_resolve = file_access.resolve_read_path

    def _resolve(raw: str, **kwargs: object) -> Path:
        if Path(raw).name == target.name:
            raise injected
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)
    return injected


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_an_oserror_inside_the_floor_propagates_from_the_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    injected = _floor_raises_oserror_on(monkeypatch, cfg)

    with pytest.raises(OSError) as raised:
        await _search(CodeSearchAgent(agent_id="cs-20", runtime=rt), root, max_results=5)

    # The floor's own exception, unchanged: not taken for an unreadable file (A4 returned the public match instead).
    assert raised.value is injected


async def test_handle_intent_propagates_an_oserror_inside_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, _public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])
    injected = _floor_raises_oserror_on(monkeypatch, cfg)

    with pytest.raises(OSError) as raised:
        await CodeSearchAgent(agent_id="cs-21", runtime=rt).handle_intent(
            IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 5})
        )

    assert raised.value is injected


class _ReadFailsAfterOneLine:
    """A text file handle that yields one matching line and then fails, as a read error part-way through a file would."""

    def __enter__(self) -> _ReadFailsAfterOneLine:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def __iter__(self) -> Iterator[str]:
        yield f"{FILE_TOKEN}\n"
        raise OSError("bf908-injected read failure")


async def test_a_file_that_cannot_be_opened_or_read_still_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=2)
    unopenable = root / "ab-unopenable.txt"  # walked after the config file, before note-0.txt
    breaks = root / "note-0a-breaks.txt"  # walked between note-0.txt and note-1.txt
    for path in (unopenable, breaks):
        path.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    real_open = Path.open

    def _open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        # Text-mode opens of the two names only: the walker's binary sniff ("rb") reads every file as it is.
        if mode == "r" and self.name == unopenable.name:
            raise OSError("bf908-injected open failure")
        if mode == "r" and self.name == breaks.name:
            return _ReadFailsAfterOneLine()
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _open)

    result = await _search(CodeSearchAgent(agent_id="cs-22", runtime=rt), root, max_results=10)

    assert result["success"] is True
    assert result["engine"] == "python"
    # The unopenable file contributes nothing; the failed read keeps the line read before it; the walk goes on.
    assert _paths(result) == [public[0].resolve(), breaks.resolve(), public[1].resolve()]
    assert result["count"] == 3


# --------------------------------------------------------------------------- #
# K -- real children: what they can and cannot obtain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("variant", _VARIANTS)
async def test_no_agent_command_child_sees_the_token(monkeypatch: pytest.MonkeyPatch, variant: str) -> None:
    runtime = await _vessel_holding_the_keyring_token()
    held = crew_scope_token(runtime) == KEYRING_TOKEN
    in_environment = KEYRING_TOKEN in os.environ.values()
    assert held is True  # premise: this process holds the keyring's token
    assert in_environment is False  # premise: and it is not in the environment
    monkeypatch.setenv(_PLANTED_NAME, ENV_PROBE)
    tool_command = _child(_WINDOWS_ENV_DUMP if variant == "windows" else _POSIX_ENV_DUMP)
    agent_command = _child(_POWERSHELL_ENV_DUMP if variant == "windows" else _POSIX_ENV_DUMP)

    # Premise: a child that INHERITS this process's environment sees the probe. Without it, the absence below could mean only
    # that the dump cannot see what it says is hidden. No env argument: inheriting is the point.
    inheriting = subprocess.run(
        tool_command, shell=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
    )
    inherited = _labels_seen_in(inheriting.stdout.decode("utf-8", errors="replace"), {"ENV_PROBE": ENV_PROBE})
    assert inherited == ["ENV_PROBE"]

    # Each check on a child's output is derived into a local first; only the locals are asserted (header: the safety rule).
    # RunCommandTool's ``error`` is a refusal, timeout or exception text, never child output, so it may be shown.
    tool_result = await RunCommandTool(_FakeRuntime()).invoke({"command": tool_command, "timeout": 30})
    tool_ran = tool_result.success is True
    tool_stdout = tool_result.output["stdout"] if tool_ran else ""
    tool_checks = {
        "ran": tool_ran,
        "error": tool_result.error,
        "exit_code": tool_result.output["exit_code"] if tool_ran else None,
        "prints_an_environment": _prints_an_environment(tool_stdout),
        "labels_seen": _labels_seen_in(tool_stdout, _PLANTS),
    }
    assert tool_checks == {"ran": True, "error": None, "exit_code": 0, "prints_an_environment": True, "labels_seen": []}

    agent_result = await ShellCommandAgent().handle_intent(
        IntentMessage(intent="run_command", params={"command": agent_command})
    )
    assert agent_result is not None
    # The shell agent's ``error`` may hold the child's stderr: withheld.
    agent_ran = agent_result.success is True
    agent_stdout = agent_result.result["stdout"] if agent_ran else ""
    agent_checks = {
        "ran": agent_ran,
        "exit_code": agent_result.result["exit_code"] if agent_ran else None,
        "prints_an_environment": _prints_an_environment(agent_stdout),
        "labels_seen": _labels_seen_in(agent_stdout, _PLANTS),
    }
    assert agent_checks == {"ran": True, "exit_code": 0, "prints_an_environment": True, "labels_seen": []}


async def test_a_run_python_child_sees_no_token_in_its_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await _vessel_holding_the_keyring_token()
    held = crew_scope_token(runtime) == KEYRING_TOKEN
    monkeypatch.setenv(_PLANTED_NAME, ENV_PROBE)
    planted = os.environ.get(_PLANTED_NAME) == ENV_PROBE
    assert held is True  # premise: this process holds the keyring's token
    assert planted is True  # premise: and the probe is in its environment

    result = await SubprocessSandbox(scratch_root=str(tmp_path / "scratch")).run(
        ExecutionRequest(code=_child(_PYTHON_ENV_DUMP))
    )

    # The sandbox's ``error`` may hold the child's stderr: withheld. Only derived values are asserted.
    ran = result.success is True
    names = [pair[0] for pair in json.loads(result.stdout)] if ran else []
    checks = {
        "ran": ran,
        "prints_an_environment": "PATH" in names,  # premise: the child printed its environment
        "labels_seen": _labels_seen_in(result.stdout if ran else "", _PLANTS),
    }
    assert checks == {"ran": True, "prints_an_environment": True, "labels_seen": []}


async def test_an_environment_variable_would_reach_every_trusted_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = await _vessel_holding_the_keyring_token()
    held = crew_scope_token(runtime) == KEYRING_TOKEN
    assert held is True  # premise: this process holds the keyring's token
    monkeypatch.setenv(_PLANTED_NAME, ENV_PROBE)

    environments = {
        "trusted_command_env": trusted_command_env(),
        "build_command_env": build_command_env(),
        # The shape the builder's pytest runs get (cognitive/builder.py:2827).
        "builder_pytest_env": {**build_command_env(), "PYTHONPATH": "x"},
    }
    reached = {
        name: {label: value in env.values() for label, value in _PLANTS.items()} for name, env in environments.items()
    }

    assert reached == {
        "trusted_command_env": {"ENV_PROBE": True, "KEYRING_TOKEN": False},
        "build_command_env": {"ENV_PROBE": False, "KEYRING_TOKEN": False},
        "builder_pytest_env": {"ENV_PROBE": False, "KEYRING_TOKEN": False},
    }


async def test_a_shell_command_can_still_read_a_token_left_in_the_config_file(tmp_path: Path) -> None:
    """Residual R2, pinned as a LIMITATION rather than silently unknown.

    The floor refuses the config file to every reader that calls it (J1, J4). A shell command is not such a reader: it runs as
    the vessel's own OS user, so a token left in the file is readable by it. This asserts the CURRENT behaviour, as
    ``tests/test_bf758_file_read_confinement.py::test_a_hard_link_into_the_floor_is_a_known_limitation`` does for the hard link.
    If it starts failing, OS-level isolation (AD-995) has closed the route and this docstring should go with it.
    """
    _project_dir, cfg, _notes = _project(tmp_path, config_name="system.yaml")
    with pytest.raises(FileAccessDenied):
        resolve_for_runtime(str(cfg), _runtime(tmp_path, cfg))  # premise: the floor refuses this very file
    command = _child(_WINDOWS_TYPE_FILE if _IS_WINDOWS else _POSIX_CAT_FILE, path=str(cfg))

    result = await RunCommandTool(_FakeRuntime()).invoke({"command": command, "timeout": 30})

    ran = result.success is True
    checks = {
        "ran": ran,
        "error": result.error,  # RunCommandTool's: never child output
        "exit_code": result.output["exit_code"] if ran else None,
        "read_the_token": ran and FILE_TOKEN in result.output["stdout"],
    }
    assert checks == {"ran": True, "error": None, "exit_code": 0, "read_the_token": True}


def test_no_child_script_here_imports_keyring() -> None:
    assert _CHILD_COMMANDS  # a tuple that lists nothing proves nothing
    assert all("keyring" not in command for command in _CHILD_COMMANDS)
