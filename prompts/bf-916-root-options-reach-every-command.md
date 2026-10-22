# BF-916: a root option given before the command reaches serve, rebuild-episodic and backup-reclaim

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** build-ready after AD-1341 S1 (#1569) merges. One milestone (M1) and a docs-only validation commit. **Tier HIGH**: data integrity. A deleting command checks the wrong directory, and a boot picks the wrong ship. Closes #1624. The number BF-916 is the issue's own; no new number is allocated. **Base:** the S1 rehearsal tree `a6174659` (tree `30a965fd`) on `origin/main` `80456da2`. Every SEARCH anchors on text: the three `__main__.py` pairs and the test pair rely on no S1 text (identical on `80456da2`, lines 3309–3365), and the tracker pairs rely on no S1 text either; S1 merging first only fixes where the entries land.

**Tests:** new `tests/test_bf916_root_options_reach_every_command.py`: 8 functions, 12 cases. Updated: `tests/test_ad1135_setup_cli.py`, one assertion that pinned the defect.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. The new file is written LF.

---

## 0. Premise: what is present on this tree

The root parser declares `--config`/`-c` (`default=None`), `--fresh` (`store_true`) and `--data-dir` (`default=None`) at `__main__.py:3417-3433`. Python is 3.12.13 (`d:/ProbOS/.venv/pyvenv.cfg`). In argparse, the subcommand action parses into a fresh namespace and copies every attribute, defaults included, over the root namespace. A redeclared option with a non-SUPPRESS default therefore replaces the root value given before the command. CPython's attempt to change that (bpo-45235) was reverted. The orchestrator reproduced the defect by execution on the frozen M3 tree, with `doctor` (SUPPRESS) as the control.

## 1. Problem

`serve` (`__main__.py:3676`, `:3679`, `:3680`), `rebuild-episodic` (`:3643`, `:3646`) and `backup-reclaim` (`:3633`) redeclare root options with `None`/`False` defaults:

- `probos --data-dir D serve` boots the platform's ship, `probos --config X serve` reads the fallback configuration, and `probos --fresh serve` warm-boots.
- `probos --data-dir D rebuild-episodic` rebuilds the platform's ChromaDB.
- `probos --data-dir D backup-reclaim --force` runs `assert_no_other_instance` on the platform data directory (`:2112`) and then deletes the listed working directories (`:2171-2178`).

An option placed after the command works. The live vessel starts as `probos serve --interactive` (no leading option), so nothing reaches the live ship today.

## 2. Solution overview

The six redeclarations get `default=argparse.SUPPRESS`, as `setup`, `doctor`, `crew-token`, `reset` and `archive erase` already have. Absent after the command, the subparser sets nothing and the root's value or default stays. Present after the command, it wins, as now. One test (B8) walks every subcommand of the parser `main` builds and fails on any root option redeclared without SUPPRESS.

## 3. Decisions

| # | Decision | Options, ranked (chosen first) |
|---|---|---|
| D1 | Scope: the six lines in §7.1, plus B8 guarding the class | (1) chosen; (2) the six lines only, rejected because this is the fifth per-command repair; (3) drop the redeclarations, rejected because it breaks `probos serve --config X`, the Dockerfile `CMD` and the commands setup prints; (4) a shared parent parser, rejected because it adds options to `verify-snapshot`, which refuses them on purpose (`:3612`) |
| D2 | Form: `default=argparse.SUPPRESS` | (1) chosen; (2) per-command destinations merged in the handler, rejected as two sources of truth; (3) a post-parse overlay, rejected because it reimplements argparse precedence |
| D3 | `backup-reclaim` gets no `--config` | It loads no configuration (`_cmd_backup_reclaim` reads only `backup_root`, `force` and `data_dir`) |
| D4 | Precedence unchanged: an option after the command wins over one before it | B3 pins it |
| D5 | Tier HIGH | data integrity; not lowered |

Enumeration of every root-option redeclaration (13 sites, 8 commands): setup `:1246`, doctor `:3453` and `:3457`, crew-token `:3551`, reset `:3703` and `:3704`, archive erase `:3723` already use SUPPRESS; backup-reclaim `:3633`, rebuild-episodic `:3643` and `:3646`, serve `:3676`, `:3679` and `:3680` are fixed here. No subparser sets `dest=` to a root destination (Absence AV1).

## 4. Milestones

| Milestone | Files (§7) | Focused gate (`-n 0`) |
|---|---|---|
| **M1** (opens at §7.1) | 7.1 `src/probos/__main__.py`; 7.2 `tests/test_ad1135_setup_cli.py`; 7.3 new `tests/test_bf916_root_options_reach_every_command.py`; §8 trackers and the regenerated ledger | `tests/test_bf916_root_options_reach_every_command.py tests/test_ad1135_setup_cli.py tests/test_ad1026_boot_verbosity.py tests/test_ad1137_doctor.py tests/test_ad1341_s1_reset_and_erase.py tests/test_dotenv.py tests/test_ad819_rebuild_episodic.py tests/test_ad1296_working_dir_ownership.py tests/test_ad465_containerized_deployment.py tests/test_ad1340_s1_restore_reset.py tests/test_bf781_isolation_claims.py tests/test_bf877_unapproved_design_is_refused.py tests/test_bf892_spawn_env_guard.py tests/test_ad1184_ad_ledger.py`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

After M1, a docs-only commit adds the Validation of record (§8). Stage explicit paths only. If a test outside §7 fails because it pinned a discarded leading option, update it with an inline `BF-916 (#1624)` reason and never delete it. Stop and report any other failure.

## 5. Consumers of every value this changes

| Value | Consumer | With the option on neither side | Holds because |
|---|---|---|---|
| `args.config` (serve) | `main` → `_serve(config_path=args.config, ...)` `:3791`, direct read | `None` (root default) | the root parser always sets it |
| `args.fresh` (serve) | `:3792`, direct read | `False` | root `store_true` default |
| `args.data_dir` (serve) | `:3793`, direct read | `None` → `_serve` uses `_default_data_dir()` (`:750`) | root default |
| `args.data_dir` (rebuild) | `_cmd_rebuild_episodic` `:2206` via `getattr` | `None` → platform dir | unchanged |
| `args.config` (rebuild) | `:2266` via `getattr` → `_load_config_with_fallback` | `None` → fallback | unchanged |
| `args.data_dir` (backup) | `_cmd_backup_reclaim` `:2112` via `getattr`, under `--force` only | `None` → platform dir | unchanged |
| default shell | `:3807` reads the root namespace | unchanged | no subcommand parsed |
| `--help` | argparse help | the options still listed | SUPPRESS is on `default`, not `help` |

## 6. Tests

**Milestone openings:** M1 opens at `### 7.1`. There is no other milestone.

New file (7.3), every case through the real `main`. `_prepare_main` replaces `_default_data_dir` and `_load_config_with_fallback` with `pytest.fail`, so selecting the platform directory or any configuration fails the test.

| ID | Test | Fails today |
|---|---|---|
| B1 | serve receives `--config`, `--fresh`, `--data-dir` in either position (capture of `_serve`) | options-first |
| B2 | serve with none receives `(None, False, None)` | no (control) |
| B3 | `--data-dir A serve --data-dir B` → B | no (precedence pin) |
| B4 | rebuild-episodic receives `--config`, `--data-dir` in either position (handler capture) | options-first |
| B5 | real `_cmd_rebuild_episodic`, leading `--data-dir D`: exit 3 naming `D/ward_room.db` | yes |
| B6 | backup-reclaim receives `--data-dir` in either position (handler capture) | options-first |
| B7 | real `_cmd_backup_reclaim --force`, a live owner's pid in `D/probos.pid`: exit 2, working dir kept | options-first |
| B8 | every subcommand, nested ones included, redeclares root options only with SUPPRESS | yes (6 offenders) |

Updated (7.2): `test_main_config_parsing_for_serve_and_the_shell_is_unchanged` now expects `("serve", explicit)` for the leading form; it fails today.

Unchanged readers checked: `test_ad1026_boot_verbosity.py:223-238` (serve capture, trailing flags), `test_ad1137_doctor.py:227` (doctor root-flag control), `test_ad1341_s1_reset_and_erase.py:551-588` (R14, R15), `test_dotenv.py:19,38` (`--help`), `test_ad465_containerized_deployment.py:23` (Dockerfile trailing form), `test_ad1340_s1_restore_reset.py:325` (counts `EpisodicMemory` constructions; none added), `test_bf781_isolation_claims.py:376` (`wait_for` regex; untouched), `test_bf877_unapproved_design_is_refused.py:457` (ProbOSShell sites; untouched), `test_bf892_spawn_env_guard.py:479` (scans `src` only; the new child process is in `tests`).

## 7. The contract

### 7.1 `src/probos/__main__.py` (M1: three pairs, in file order)

Pair 1 (backup-reclaim). The trailing comment keeps the changed line distinct from rebuild's, which shares its prefix.

SEARCH:
```python
    backup_reclaim_parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Data directory checked for a running vessel; only used with --force",
    )
```
REPLACE:
```python
    backup_reclaim_parser.add_argument(
        "--data-dir", type=Path, default=argparse.SUPPRESS,  # BF-916: a --data-dir before the command is kept
        help="Data directory checked for a running vessel; only used with --force",
    )
```

Pair 2 (rebuild-episodic). The trailing comma after `help=...` keeps the config line distinct from reset's and archive erase's.

SEARCH:
```python
    rebuild_parser.add_argument(
        "--data-dir", type=Path, default=None, help="Data directory (default: platform path)"
    )
    rebuild_parser.add_argument(
        "--config", "-c", type=Path, default=None, help="Path to config YAML"
    )
```
REPLACE:
```python
    # BF-916, SUPPRESS as for doctor: a --data-dir or --config before `rebuild-episodic` (the root parser's) is kept.
    rebuild_parser.add_argument(
        "--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory (default: platform path)"
    )
    rebuild_parser.add_argument(
        "--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",
    )
```

Pair 3 (serve). The four-line `--config` call becomes one line.

SEARCH:
```python
    serve_parser = subparsers.add_parser("serve", help="Start HTTP + WebSocket API server")
    serve_parser.add_argument(
        "--config", "-c", type=Path, default=None,
        help="Path to config YAML",
    )
    serve_parser.add_argument("--fresh", action="store_true", help="Cold start")
    serve_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")
```
REPLACE:
```python
    serve_parser = subparsers.add_parser("serve", help="Start HTTP + WebSocket API server")
    # BF-916, SUPPRESS as for doctor: a --config, --fresh or --data-dir before `serve` (the root parser's) is kept.
    serve_parser.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
    serve_parser.add_argument("--fresh", action="store_true", default=argparse.SUPPRESS, help="Cold start")
    serve_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
```

### 7.2 `tests/test_ad1135_setup_cli.py` (M1: the assertion pinned serve's defect)

SEARCH:
```python
    # Measured before B6: serve's own --config default replaces one given before `serve`. Only setup's
    # parser changed, so this stays; the two commands setup prints (serve --config X, --config X) name X.
    assert seen == [("serve", None), ("serve", explicit), ("shell", explicit)]
```
REPLACE:
```python
    # Measured before B6: serve's own --config default replaced one given before `serve`, and this pinned it.
    # BF-916 (#1624) gives serve's --config SUPPRESS, as setup's has, so X now reaches serve in either position;
    # the two commands setup prints (serve --config X, --config X) still name X.
    assert seen == [("serve", explicit), ("serve", explicit), ("shell", explicit)]
```

### 7.3 New file: `tests/test_bf916_root_options_reach_every_command.py` (M1)

```python
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
```

## 8. Tracking (tracker pairs; in M1's commit)

Each pair anchors on one line that occurs once in its file and that no wave item changes, so it applies whichever entries land first. S1 merges first, so BF-916's entries land above S1's in `PROGRESS.md` and after S1's in `DECISIONS.md`. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title line):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-916 (2026-10-22), closes #1624 -- a root option given before the command reaches serve, rebuild-episodic and backup-reclaim.** argparse copies every subcommand default over the root parser's value, so the `None` and `False` defaults of these three commands' own `--config`, `--fresh` and `--data-dir` discarded the same option given before the command: `probos --data-dir D serve` booted the platform's ship, `probos --fresh serve` warm-booted, `rebuild-episodic` rebuilt the platform's ChromaDB, and `backup-reclaim --force` looked for a running vessel in the platform data directory before deleting. The six redeclarations now use `default=argparse.SUPPRESS`, as `setup`, `doctor`, `crew-token`, `reset` and `archive erase` already did; an option after the command still wins. New: `tests/test_bf916_root_options_reach_every_command.py` (the real `main` in both positions; the real handlers of `rebuild-episodic` and of `backup-reclaim --force` beside a live owner; a walk of every subcommand, nested ones included, that fails on any root option redeclared without SUPPRESS). Updated: `tests/test_ad1135_setup_cli.py`, which pinned serve's defect. The contract is `prompts/bf-916-root-options-reach-every-command.md`.
```

**`DECISIONS.md`** (inserted before the heading below; S1's entry already precedes it):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-916 -- A root option given before the command reaches serve, rebuild-episodic and backup-reclaim (2026-10-22, #1624)

- *Scope.* `__main__.py`: the `serve` (`--config`, `--fresh`, `--data-dir`), `rebuild-episodic` (`--data-dir`, `--config`) and `backup-reclaim` (`--data-dir`) subparsers. Tests: new `tests/test_bf916_root_options_reach_every_command.py`; `tests/test_ad1135_setup_cli.py` updated where it pinned serve's defect. Contract: `prompts/bf-916-root-options-reach-every-command.md`. Found by AD-1341 S1's M3 review (register RA4-1).
- *D2 (the form).* `default=argparse.SUPPRESS`: the subcommand sets the attribute only when the option follows the command, so a value given before it, or the root default (`None`, `False`), stays. When both are given, the one after the command wins, as before. argparse's own change to this precedence (bpo-45235) was reverted, so every redeclaration needs it. Rejected: per-command destinations merged in each handler (two sources of truth), and removing the redeclarations (breaks the trailing form the Dockerfile and setup's printed commands use).
- *D1 (scope).* Every redeclaration of a root option was enumerated: 13 across eight commands; seven already used SUPPRESS and these six now do. `backup-reclaim` gains no `--config` (it loads none). A test walks every subcommand of the parser `main` builds, so a new redeclaration without SUPPRESS fails the suite.
- *Disclosed effects.* `probos --data-dir D serve`, `probos --config X serve` and `probos --fresh serve` now boot D, read X and cold-start, where they booted the platform's ship, read the fallback configuration and warm-booted. The live vessel's `probos serve --interactive` is unchanged.
- *Reversal.* Revert the BF-916 commit. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M1's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after M1:** add a *Validation of record* bullet before BF-916's *Reversal* line: the mutation campaign of record, its base tree, the sha256 of `src/probos/__main__.py` and of the new test file, and each row's first failing test. Regenerate the ledger.

**`docs/development/roadmap.md`:** no row (the Bug Tracker has no `BF-9xx` rows; BF-911's D13 precedent).

## 9. What this does NOT change

- Every other subparser option, the root parser, and the dispatch in `main`.
- `_serve`, `_cmd_rebuild_episodic` and `_cmd_backup_reclaim` bodies; `assert_no_other_instance`, `is_pid_alive` and the AD-816 pidfile.
- `_cmd_pairing`, which ignores `--data-dir` entirely (`:1921`): a different defect (register RB1).
- `_check_nats`'s JetStream store under the platform directory (`:455`): register RB2.
- `verify-snapshot` still takes neither option (`:3612`).
- The Dockerfile, `config/`, `.github/` and `scripts/`.

## 10. Mutation rows

Tier HIGH: every changed production line has a row. Run each against `tests/test_bf916_root_options_reach_every_command.py tests/test_ad1135_setup_cli.py` on the contract-applied tree, after an unmutated baseline run that passes. Restore the file before the next row. Each Line cell occurs exactly once in `src/probos/__main__.py` after §7, as a substring as well as a whole line.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| N1 | `src/probos/__main__.py` | `serve_parser.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")` | `serve_parser.add_argument("--config", "-c", type=Path, default=None, help="Path to config YAML")` | B1 `[options-first]`; B8; `test_ad1135_setup_cli.py::test_main_config_parsing_for_serve_and_the_shell_is_unchanged` |
| N2 | `src/probos/__main__.py` | `serve_parser.add_argument("--fresh", action="store_true", default=argparse.SUPPRESS, help="Cold start")` | `serve_parser.add_argument("--fresh", action="store_true", help="Cold start")` | B1 `[options-first]`; B8 |
| N3 | `src/probos/__main__.py` | `serve_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")` | `serve_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")` | B1 `[options-first]`; B8 |
| N4 | `src/probos/__main__.py` | `serve_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")` | `serve_parser.add_argument("--datadir", type=Path, default=argparse.SUPPRESS, help="Data directory")` | B1 `[options-last]` and B3 (unrecognised argument, exit 2). `--data-dir` is not a prefix of `--datadir`, so `allow_abbrev` cannot save the mutant |
| N5 | `src/probos/__main__.py` | `"--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory (default: platform path)"` | `"--data-dir", type=Path, default=None, help="Data directory (default: platform path)"` | B4 `[options-first]`; B5; B8 |
| N6 | `src/probos/__main__.py` | `"--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",` | `"--config", "-c", type=Path, default=None, help="Path to config YAML",` | B4 `[options-first]`; B8 |
| N7 | `src/probos/__main__.py` | `"--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",` | `"--cfg", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML",` | B4 `[options-last]` (exit 2, not 0) |
| N8 | `src/probos/__main__.py` | `"--data-dir", type=Path, default=argparse.SUPPRESS,  # BF-916: a --data-dir before the command is kept` | `"--data-dir", type=Path, default=None,` | B6 `[options-first]`; B7 `[options-first]` (the platform directory is selected); B8 |
| N9 | `src/probos/__main__.py` | `"--data-dir", type=Path, default=argparse.SUPPRESS,  # BF-916: a --data-dir before the command is kept` | `"--datadir", type=Path, default=argparse.SUPPRESS,` | B6 `[options-last]` (exit 2, not 0). B7 `[options-last]` does not kill it: argparse's exit 2 equals the refusal's |

## 11. Verified Against Codebase (2026-10-22, HEAD `a6174659`, tree `30a965fd`)

```
Grep "add_argument\(|add_parser\(|args\.(config|data_dir|fresh)|getattr\(args" src/probos/__main__.py
  3417-3433: parser.add_argument("--config", "-c", ... default=None ...); "--fresh" action="store_true"; "--data-dir" default=None
  1246: "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS, help="Edit or create this config file",
  3453: "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS,      (doctor)
  3457: "--data-dir", type=Path, metavar="DIR", default=argparse.SUPPRESS,          (doctor)
  3551: "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS,      (crew-token)
  3633: "--data-dir", type=Path, default=None,                                        (backup-reclaim)
  3634: help="Data directory checked for a running vessel; only used with --force",
  3643: "--data-dir", type=Path, default=None, help="Data directory (default: platform path)"
  3646: "--config", "-c", type=Path, default=None, help="Path to config YAML"
  3674: serve_parser = subparsers.add_parser("serve", help="Start HTTP + WebSocket API server")
  3676: "--config", "-c", type=Path, default=None,
  3679: serve_parser.add_argument("--fresh", action="store_true", help="Cold start")
  3680: serve_parser.add_argument("--data-dir", type=Path, default=None, help="Data directory")
  3703: reset_parser.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
  3704: reset_parser.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS, help="Data directory")
  3723: archive_erase.add_argument("--config", "-c", type=Path, default=argparse.SUPPRESS, help="Path to config YAML")
  3612: # Deliberately no --data-dir / --config: the check reads the snapshot
  3766-3772: sys.exit(_cmd_backup_reclaim(args)); sys.exit(_cmd_rebuild_episodic(args))
  3791-3793: config_path=args.config, fresh=args.fresh, data_dir=args.data_dir,
  3807: asyncio.run(_boot_and_run(config_path=args.config, fresh=args.fresh, data_dir=args.data_dir, verbose=False))
  2112: data_dir = (getattr(args, "data_dir", None) or _default_data_dir()).resolve()     (backup-reclaim, under --force)
  2206: data_dir = (getattr(args, "data_dir", None) or _default_data_dir()).resolve()     (rebuild-episodic)
  2266: cfg, _cfg_path = _load_config_with_fallback(getattr(args, "config", None))
Read src/probos/__main__.py:2104-2122  --force: assert_no_other_instance(data_dir); refusal returns 2
Read src/probos/__main__.py:2221-2227  ward_room.db not found at {wardroom_db} ... return 3
Read src/probos/__main__.py:726-736   async def _serve(config_path: Path | None = None, fresh: bool = False, data_dir: Path | None = None, ...)
Read src/probos/__main__.py:1200      def _add_setup_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
Read src/probos/pidfile_guard.py:239-254  assert_no_other_instance: reads probos.pid; skips os.getpid(); raises if is_pid_alive
Read src/probos/pidfile_guard.py:87-94    _read_pid_from: strip(), isdigit(), int
Grep "^INCOMPLETE_SUFFIX" src/probos/infrastructure  snapshot_manifest.py:64: INCOMPLETE_SUFFIX = ".incomplete"
Read tests/test_ad1135_setup_cli.py:1555-1570  ("--config", str(explicit), "serve") ... assert seen == [("serve", None), ...]
Read tests/test_ad1026_boot_verbosity.py:223-238  _run_main_serve: argv ["probos", "serve", *extra_argv]
Read tests/test_ad1341_s1_reset_and_erase.py:196-222, 551-588  _only_what_the_captain_named, _main, R14, R15
Grep tests/test_ad1137_doctor.py:227  ("--data-dir", "{}", "doctor"), ("doctor", "--data-dir", "{}") ids root-flag/doctor-flag
Read d:/ProbOS/.venv/pyvenv.cfg  version_info = 3.12.13
git show 80456da2:src/probos/__main__.py | grep  3309-3365: the same backup/rebuild/serve parser text (S1 did not change it)
git diff 04badba4 HEAD --stat -- tests/test_ad1135_setup_cli.py  (empty: S1 did not change it)
Grep "^### Explicit delegation models, plain-id profile models|^# ProbOS Progress"  DECISIONS.md:588, PROGRESS.md:1 (one each)
Glob scripts/gen_ad_ledger.py, tests/test_ad1184_ad_ledger.py  present
```

**SEARCH uniqueness (how checked):** Grep with line numbers. `Data directory checked for a running vessel` 1 hit (3634); `Data directory (default: platform path)` 1 (3643); `serve_parser = subparsers.add_parser("serve"` 1 (3674); `help="Cold start"` 1 (3679); `default=None, help="Data directory")` 1 (3680); in `test_ad1135_setup_cli.py`, `Measured before B6`, `parser changed, so this stays` and `("serve", None)` 1 each. Each pair's first line occurs in a block that occurs once.

## Absence Verified (2026-10-22)

```
AV1 CLAIM: no subparser redeclares a root option except the 13 sites in §3, and none uses dest= to reach one
    RUN:   Grep '"--config", "-c", type=Path|"--data-dir", type=Path|"--fresh"' and 'dest=|"config"|"data_dir"|"fresh"' on src/probos/__main__.py
    FOUND: 1246, 3453, 3457, 3551, 3633, 3643, 3646, 3676, 3679, 3680, 3703, 3704, 3723; dest= only on add_subparsers (command, pairing_cmd, channel_*_cmd, crew_token_cmd, migrate_source, qa_cmd, archive_cmd)
    HOLDS: yes
AV2 CLAIM: only two tests drive main() with serve, rebuild-episodic or backup-reclaim argv; none reads those parser lines as source
    RUN:   Grep '"serve"|'serve'|"rebuild-episodic"|'rebuild-episodic'|"backup-reclaim"|'backup-reclaim'|serve_parser|rebuild_parser|backup_reclaim_parser' tests/
    FOUND: test_ad1026_boot_verbosity.py:232 (trailing flags only); test_ad1135_setup_cli.py:1560,1564,1570 (the pin, §7.2);
           test_ad1278 _ModalSink(mode="serve") (unrelated); test_ad1296:381,471 (log text); test_ad465:23 (Dockerfile, trailing form)
    HOLDS: yes
AV3 CLAIM: no source reader of __main__.py depends on the changed lines
    RUN:   Grep '"__main__\.py"|__main__\.py"\)|probos/__main__' tests/
    FOUND: test_ad1135_provider_setup:703 and test_ad1137_doctor:1437 (import sets; no import added); test_ad1340_s1:46/325 (EpisodicMemory count);
           test_ad1341_s1:481 (callee naming); test_bf781:376 (wait_for regex); test_bf877:457 (ProbOSShell sites); test_bf892:83-85 (src launches)
    HOLDS: yes
AV4 CLAIM: the new helper names are in no AD-1343 census set
    RUN:   Read tests/fixtures/ad1343_seam_census.py:25-39
    FOUND: STOP_CALLEES {active_stop, tool_refusal, refusal, refuse_new_run}; GUARD_CALLEES + {standing_stop, _stopped}; RECORDED adds invoke, issue_stop, ..., complete, finalize, run_crew_task
    HOLDS: yes (_placed, _prepare_main, _exit_code, _serve_receives, _command_receives, _parser_from_main, _subcommands, _live_owner, _end_owner, _capture_serve, _capture_args, _take_parser)
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 3 (`Name(`) | The test aliases `subprocess.Popen` as `_Popen`; `SystemExit` appears only in `pytest.raises(SystemExit)` and a bare `raise SystemExit`; no `Namespace`, `Console` or exception class is called. The production lines call no capitalised name |
| Pattern 2 (`Name.attr`) | Capitalised names appear only as receivers that are stdlib aliases or are followed by `,`, `]` or `)` (`argparse.ArgumentParser`, `subprocess.TimeoutExpired`); `argparse._SubParsersAction` begins with an underscore (production precedent `__main__.py:1200`) |
| Pattern B (kwarg lines) | No line binds a name to a class call: `owner` comes from `_live_owner`, `parser` from `_parser_from_main`; nothing calls `unlink` |
| AD-1343 census | AV4 |
| Subprocess census (`test_bf892`) | scans `src` only; no launch added to `src` |
| Store registry and `.db` literals | none added in `src` |
| Config | no new field |
| Size | `__main__.py` net -1 line; the new test about 230 lines |
| Ledger | M1 |
| Child process | `_live_owner` imports nothing from probos (no PYTHONPATH needed) and the test asserts only `is_pid_alive(owner.pid)`, never pid identity; it is ended in `finally` |

## 13. Prior Art and Blind Spots

- This is ProbOS plumbing on a stdlib behaviour. One bounded search: CPython changed subparser-default precedence for bpo-45235 and reverted it as a regression ([revert commit](https://android.googlesource.com/platform/external/python/cpython3/+/807f839bbf); [original report](https://bugs.python.org/msg111324)). Adopted: SUPPRESS on the subcommand, the documented workaround and this repo's own five precedents. I did not review `docs/research/reference-projects.md` because this is a bug fix (standing rule).
- Blind spot absorbed: the defect recurs one command at a time (AD-1135, AD-1137, BF-908, AD-1341 S1, BF-916), so B8 guards the class.
- Blind spot absorbed: `allow_abbrev` would let a rename mutant survive. N4, N7 and N9 use names the original option is not a prefix of.
- Blind spot recorded, not fixed: `pairing` accepts a leading `--data-dir` and ignores it (RB1).
- Considered, deferred: extracting `_build_parser` so B8 needs no `parse_args` interception. It is a refactor of `main` outside this BF.

## 14. Diff Reviewer: properties to verify

1. Exactly six option declarations change, and each change is `default=argparse.SUPPRESS` (on `default`, never on `help`). Every other subparser option is byte-identical.
2. With the option on neither side, `_serve` receives `(None, False, None)`, and the two handlers' `getattr` calls see `None` (the root defaults).
3. An option after the command still overrides one before it.
4. `backup-reclaim` gains no `--config`.
5. Every test runs the real `main`. `_default_data_dir` and `_load_config_with_fallback` are replaced with `pytest.fail`, which raises Failed, not an Exception subclass. No path reaches the platform data directory or `~/.probos`.
6. B7's child is ended on every exit. Nothing assumes the child's own pid equals `Popen.pid`.
7. The updated ad1135 assertion records why inline; no test is deleted.
8. The consumer that must accept the change: `main`'s serve dispatch reads `args.config`, `args.fresh` and `args.data_dir` directly (`:3791-3793`). Confirm the root parser still sets all three when the subcommand does not.

## 15. Acceptance criteria

- §7.1 to §7.3 and §8 applied; the M1 focused gate passes at `-n 0`; `gen_ad_ledger.py --check` reports current.
- B1 `[options-first]`, B4 `[options-first]`, B5, B6 `[options-first]`, B7 `[options-first]`, B8 and the updated ad1135 test fail on the pre-change tree and pass after it.
- All nine §10 rows are killed by the named tests. The campaign of record is recorded in the docs-only commit.
- The broad gate runs once for the batch, by the orchestrator, with `--receipt`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
