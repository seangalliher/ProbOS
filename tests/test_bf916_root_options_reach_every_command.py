"""BF-916 (#1624): a root option given before the command reaches ``serve``, ``rebuild-episodic`` and
``backup-reclaim``.

The root parser declares ``--config``, ``--fresh`` and ``--data-dir``. argparse copies every subcommand default
over the value the root parser already holds, so a subcommand that redeclared one with a ``None`` or ``False``
default discarded the option given before the command: ``probos --data-dir D serve`` booted the platform's ship,
and ``probos --data-dir D backup-reclaim --force`` looked for a running vessel in the platform data directory before
it deleted. Each test runs the real ``main`` on a real argv; selecting the platform data directory or loading a
configuration fails the test. Only the command's handler is replaced by a capture, except in B5 and B7, which run
the real handler. The model is ``tests/test_ad1341_s1_reset_and_erase.py`` (R14, R15).
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from subprocess import Popen as _Popen
from typing import Any

import pytest

from probos import __main__ as cli
from probos.pidfile_guard import is_pid_alive

_EITHER_POSITION = pytest.mark.parametrize("leading", [True, False], ids=["options-first", "options-last"])


# --- helpers -----------------------------------------------------------------------------------------------------


def _placed(options: list[str], command: list[str], leading: bool) -> list[str]:
    """The argv with ``options`` before the command words, or after them."""
    return [*options, *command] if leading else [*command, *options]


def _prepare_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    """Set up the real ``main`` for ``argv``. The platform data directory and any configuration load fail the test,
    so a discarded option can never reach ``~/.probos`` or a real vessel."""

    def _no_platform_directory() -> Path:
        pytest.fail("the platform data directory was selected")  # Failed: no except Exception swallows it

    def _no_configuration_load(path: Any) -> Any:
        pytest.fail(f"a configuration was loaded ({path!r}); no command in this file loads one")

    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # no repository .env into the worker
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: None)  # main sets one on Windows
    monkeypatch.setattr(cli, "_default_data_dir", _no_platform_directory)
    monkeypatch.setattr(cli, "_load_config_with_fallback", _no_configuration_load)
    monkeypatch.setattr("sys.argv", ["probos", *argv])


def _exit_code(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> Any:
    """Run the real ``main`` on ``argv``; return its exit code."""
    _prepare_main(monkeypatch, argv)
    with pytest.raises(SystemExit) as exited:
        cli.main()
    return exited.value.code


def _serve_receives(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict[str, Any]:
    """Run the real ``main`` with ``_serve`` replaced by a capture; return the keywords ``_serve`` was given."""
    received: dict[str, Any] = {}

    async def _capture_serve(**kwargs: Any) -> None:
        received.update(kwargs)

    monkeypatch.setattr(cli, "_serve", _capture_serve)
    _prepare_main(monkeypatch, argv)
    cli.main()  # serve returns when its server stops; it does not exit
    assert received, "main did not reach _serve"
    return received


def _command_receives(
    monkeypatch: pytest.MonkeyPatch, handler: str, argv: list[str],
) -> tuple[Any, dict[str, Any]]:
    """Run the real ``main`` with the command's handler replaced by a capture; return the exit code and the parsed
    options the handler was given."""
    received: dict[str, Any] = {}

    def _capture_args(args: Any) -> int:
        received.update(vars(args))
        return 0

    monkeypatch.setattr(cli, handler, _capture_args)
    return _exit_code(monkeypatch, argv), received


def _parser_from_main(monkeypatch: pytest.MonkeyPatch) -> argparse.ArgumentParser:
    """The root parser the real ``main`` builds, taken at its ``parse_args`` call; nothing is parsed or run."""
    built: list[argparse.ArgumentParser] = []

    def _take_parser(self: argparse.ArgumentParser, *args: Any, **kwargs: Any) -> Any:
        built.append(self)
        raise SystemExit

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", _take_parser)
    _exit_code(monkeypatch, [])
    (parser,) = built
    return parser


def _subcommands(parser: argparse.ArgumentParser, prefix: str = "") -> list[tuple[str, argparse.ArgumentParser]]:
    """Every subcommand parser under ``parser``, nested ones included, named by its command words."""
    found: list[tuple[str, argparse.ArgumentParser]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                words = f"{prefix}{name}"
                found += [(words, sub), *_subcommands(sub, f"{words} ")]
    return found


def _live_owner() -> _Popen[bytes]:
    """A running process for the pidfile to name. It imports nothing from probos, so it needs no PYTHONPATH. The
    test reads only that the pid it was given is alive, never that it is the interpreter's own: on this Windows host
    a venv python is a launcher, whose pid stays alive while its child waits (AD-1341 S1 A5)."""
    return _Popen([sys.executable, "-I", "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)


def _end_owner(owner: _Popen[bytes]) -> None:
    """End the owner: its read returns at end of file. Kill it if it has not exited within 30 seconds."""
    if owner.stdin is not None:
        owner.stdin.close()
    try:
        owner.wait(timeout=30)
    except subprocess.TimeoutExpired:
        owner.kill()
        owner.wait(timeout=30)


# --- B1 to B3: serve ---------------------------------------------------------------------------------------------


@_EITHER_POSITION
def test_serve_receives_the_configuration_cold_start_and_data_directory_in_either_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """B1. Before BF-916 all three, given before ``serve``, were replaced by serve's own defaults (None, False,
    None): the platform's ship, warm-booted on the fallback configuration."""
    named, data_dir = tmp_path / "named.yaml", tmp_path / "data"
    options = ["--config", str(named), "--fresh", "--data-dir", str(data_dir)]

    received = _serve_receives(monkeypatch, _placed(options, ["serve"], leading))

    assert (received["config_path"], received["fresh"], received["data_dir"]) == (named, True, data_dir)


def test_serve_without_the_options_receives_the_root_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2. SUPPRESS leaves each attribute to the root parser, whose defaults still reach ``_serve``. main reads
    ``args.config``, ``args.fresh`` and ``args.data_dir`` directly, so a missing attribute would raise here."""
    received = _serve_receives(monkeypatch, ["serve"])

    assert (received["config_path"], received["fresh"], received["data_dir"]) == (None, False, None)


def test_an_option_given_on_both_sides_of_serve_takes_the_one_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3. argparse applies the subcommand's value last, so the one after the command wins, as before BF-916."""
    before, after = tmp_path / "before", tmp_path / "after"

    received = _serve_receives(monkeypatch, ["--data-dir", str(before), "serve", "--data-dir", str(after)])

    assert received["data_dir"] == after


# --- B4 and B5: rebuild-episodic ---------------------------------------------------------------------------------


@_EITHER_POSITION
def test_rebuild_episodic_receives_the_configuration_and_data_directory_in_either_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """B4. Before BF-916 both, given before the command, were replaced by its own ``None`` defaults."""
    named, data_dir = tmp_path / "named.yaml", tmp_path / "data"
    options = ["--config", str(named), "--data-dir", str(data_dir)]

    code, received = _command_receives(
        monkeypatch, "_cmd_rebuild_episodic", _placed(options, ["rebuild-episodic", "--dry-run"], leading),
    )

    assert (code, received["config"], received["data_dir"]) == (0, named, data_dir)


def test_rebuild_episodic_reads_the_data_directory_named_before_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """B5, the real handler. The named directory holds no ward_room.db, so the command exits 3 naming that file.
    Before BF-916 the option was discarded and the handler selected the platform data directory, which fails here."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    code = _exit_code(monkeypatch, ["--data-dir", str(data_dir), "rebuild-episodic", "--dry-run"])

    said = "".join(capsys.readouterr().out.split())  # rich may wrap a long path
    assert code == 3
    assert "".join(str(data_dir.resolve() / "ward_room.db").split()) in said


# --- B6 and B7: backup-reclaim -----------------------------------------------------------------------------------


@_EITHER_POSITION
def test_backup_reclaim_receives_the_data_directory_in_either_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """B6. Before BF-916 a ``--data-dir`` before the command was replaced by its own ``None`` default."""
    data_dir, backup_root = tmp_path / "data", tmp_path / "backups"
    command = ["backup-reclaim", "--backup-root", str(backup_root), "--force"]

    code, received = _command_receives(
        monkeypatch, "_cmd_backup_reclaim", _placed(["--data-dir", str(data_dir)], command, leading),
    )

    assert (code, received["data_dir"]) == (0, data_dir)


@_EITHER_POSITION
def test_backup_reclaim_force_refuses_while_a_live_process_owns_the_named_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leading: bool,
) -> None:
    """B7, the real handler on the deleting path. The vessel check reads the directory the Captain named, so a live
    owner there refuses the deletion (exit 2) and the working directory stays. Before BF-916 a ``--data-dir`` before
    the command was discarded and the check read the platform data directory, which fails here."""
    data_dir, backup_root = tmp_path / "data", tmp_path / "backups"
    working = backup_root / "20261022-120000.1-0123abcd.incomplete"
    working.mkdir(parents=True)
    data_dir.mkdir()
    command = ["backup-reclaim", "--backup-root", str(backup_root), "--force"]
    owner = _live_owner()
    try:
        assert is_pid_alive(owner.pid)  # premise: the pidfile names a running process
        (data_dir / "probos.pid").write_text(str(owner.pid), encoding="utf-8")
        code = _exit_code(monkeypatch, _placed(["--data-dir", str(data_dir)], command, leading))
    finally:
        _end_owner(owner)

    assert code == 2
    assert working.is_dir()


# --- B8: the class of defect -------------------------------------------------------------------------------------


def test_every_subcommand_that_redeclares_a_root_option_keeps_the_value_given_before_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B8. A subcommand option with a root option's destination must default to SUPPRESS, or argparse replaces the
    root parser's value with its default. AD-1135 (setup), AD-1137 (doctor), BF-908 (crew-token), AD-1341 S1
    (reset, archive erase) and BF-916 each repaired commands one at a time; this walks every subcommand, nested ones
    included, of the parser main builds."""
    parser = _parser_from_main(monkeypatch)
    root_options = {action.dest for action in parser._actions if action.option_strings and action.dest != "help"}
    redeclared = {
        (words, action.dest): action.default
        for words, sub in _subcommands(parser)
        for action in sub._actions
        if action.dest in root_options
    }

    assert root_options == {"config", "fresh", "data_dir"}  # premise: the root options this guards
    assert {("serve", "fresh"), ("backup-reclaim", "data_dir"), ("archive erase", "config")} <= redeclared.keys()
    assert sorted(key for key, default in redeclared.items() if default != argparse.SUPPRESS) == []
