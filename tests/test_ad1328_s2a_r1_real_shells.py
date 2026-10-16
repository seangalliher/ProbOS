"""AD-1328 S2a repair r1, R1-M3 (B20-B22): the cmd lookup and the PowerShell resolver against the real shells.

Windows only: real ``cmd.exe`` and Windows PowerShell (and ``pwsh`` when it is installed), real ``os.path.isfile``. Every
file is written under ``tmp_path``; every subprocess this file starts has ``timeout=60``. The contract is
``prompts/ad-1328-s2a-repair-r1.md`` ("Tests", Part B, R1-M3).

B20 asks the question the gate's cmd lookup answers: for a bare name, which file does ``cmd.exe /c`` run? The marker a layout
prints is compared with the marker of the file ``make_program_resolver(dialect="cmd", ...)`` names, so a lookup that names
another file than the shell runs fails here and not in front of a pinned ``allow``. B21 shows why PowerShell has no lookup: it
runs a file no lookup names. B22 crosses the whole chain, gate to real spawn, for the tool and for the shell agent.
"""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_gate import _MAX_REASON_CHARS, CommandPolicyGate, make_program_resolver

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe and Windows PowerShell")

PATHEXT = ".COM;.EXE;.BAT;.CMD"
_TIMEOUT_S = 60
_POLICY_PATH = re.compile(r"[A-Za-z0-9_.+\\: -]+")  # the characters S1 reads in a written program path (cmd and PowerShell)
_MAX_FILE_PATH = 240  # below the 260 characters a cmd.exe working directory and its file names may take


def _work_root(tmp_path: Path, nest: str) -> Path:
    """``tmp_path`` (``plain``), or a directory under it with a blank whose path is at least 200 characters
    (``long_spaced``): the refusals then exceed the gate's 300-character cause bound. Skips when the host's temp
    path leaves no room, or holds a character the policy does not read in a written program path."""
    root = tmp_path
    if nest == "long_spaced":
        root = tmp_path / "with space"
        root = root / ("L" * max(1, 200 - len(str(root)) - 1))
    if len(str(root / "empty" / "tool.CMD")) > _MAX_FILE_PATH:
        pytest.skip(f"the temp path ({len(str(root))} characters) leaves no room under cmd.exe's path limit")
    if _POLICY_PATH.fullmatch(str(root)) is None:
        pytest.skip("the temp path holds a character the policy refuses in a written program path")
    root.mkdir(parents=True, exist_ok=True)
    return root

# --------------------------------------------------------------------------------------
# Fixtures files and the shells
# --------------------------------------------------------------------------------------

_BODIES = {
    ".bat": "@echo off\r\necho BAT\r\necho ran> \"%~dp0ran_bat\"\r\n",
    ".cmd": "@echo off\r\necho CMD\r\necho ran> \"%~dp0ran_cmd\"\r\n",
    ".ps1": "Set-Content -Path (Join-Path $PSScriptRoot 'ran_ps1') -Value ran\r\nWrite-Output 'PS1'\r\n",
}


def _system32() -> str:
    return ntpath.join(os.environ["SYSTEMROOT"], "System32")


def _windows_powershell() -> str:
    return ntpath.join(_system32(), "WindowsPowerShell", "v1.0", "powershell.exe")


def _hostname_marker() -> str:
    done = subprocess.run(
        [ntpath.join(_system32(), "hostname.exe")], capture_output=True, text=True, timeout=_TIMEOUT_S,
    )
    marker = done.stdout.strip()
    assert marker, "premise: hostname.exe prints the computer name"
    return marker


def _write_tool(directory: Path, extension: str) -> Path:
    """``tool<extension>`` in ``directory``: a script that prints its marker and leaves ``ran_<kind>`` beside itself, or
    (``.exe``) a copy of hostname.exe, whose marker is the computer name."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"tool{extension}"
    if extension == ".exe":
        shutil.copyfile(ntpath.join(_system32(), "hostname.exe"), target)
    else:
        target.write_bytes(_BODIES[extension].encode("ascii"))
    return target


def _marker_of(extension: str) -> str:
    return _hostname_marker() if extension.lower() == ".exe" else extension.lstrip(".").upper()


def _env(path: str, pathext: str = PATHEXT) -> dict[str, str]:
    return {"SYSTEMROOT": os.environ["SYSTEMROOT"], "PATH": path, "PATHEXT": pathext}


def _run_cmd(path: str, cwd: Path, command: str = "tool", pathext: str = PATHEXT) -> str:
    """What ``cmd.exe /c <command>`` prints, as ``asyncio.create_subprocess_shell`` starts it (``shell=True``)."""
    done = subprocess.run(
        command, shell=True, cwd=str(cwd), env=_env(path, pathext), capture_output=True, text=True, timeout=_TIMEOUT_S,
    )
    return done.stdout.strip()


def _run_powershell(executable: str, path: str, cwd: Path, command: str = "tool") -> str:
    done = subprocess.run(
        [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=str(cwd), env=_env(path), capture_output=True, text=True, timeout=_TIMEOUT_S,
    )
    return done.stdout.strip()


# --------------------------------------------------------------------------------------
# B20. The cmd lookup names the file cmd runs
# --------------------------------------------------------------------------------------

# layout id -> (files as (directory, extension; "" is an extensionless file), PATH as directory names with "" the empty entry,
# the directory this process runs in: "cwd" means no chdir; cmd's own working directory is always "cwd")
_LAYOUTS: dict[str, tuple[list[tuple[str, str]], list[str], str]] = {
    "cmd_only": ([("d1", ".cmd")], ["d1"], "cwd"),
    "bat_and_cmd": ([("d1", ".bat"), ("d1", ".cmd")], ["d1"], "cwd"),
    "exe_and_cmd": ([("d1", ".exe"), ("d1", ".cmd")], ["d1"], "cwd"),
    "cmd_and_ps1": ([("d1", ".cmd"), ("d1", ".ps1")], ["d1"], "cwd"),
    "d1_ps1_d2_cmd": ([("d1", ".ps1"), ("d2", ".cmd")], ["d1", "d2"], "cwd"),
    "cwd_bat_d1_cmd": ([("cwd", ".bat"), ("d1", ".cmd")], ["d1"], "cwd"),
    "d1_empty_d2_cmd": ([("d2", ".cmd")], ["d1", "", "d2"], "cwd"),
    "extensionless_d1_cmd_d2": ([("d1", ""), ("d2", ".cmd")], ["d1", "d2"], "cwd"),
    "proc_cwd_bat_d1_cmd": ([("proc", ".bat"), ("d1", ".cmd")], ["d1"], "proc"),
}
# what the lookup must name (directory, file) in the two r2 layouts. Only proc_cwd_bat_d1_cmd separates cmd from a
# ``which``-style lookup (see the B20 docstring); extensionless_d1_cmd_d2 is a control, since ``which`` names the same file
_NAMED_BY_LAYOUT = {"extensionless_d1_cmd_d2": ("d2", "tool.CMD"), "proc_cwd_bat_d1_cmd": ("d1", "tool.CMD")}


@pytest.mark.parametrize("layout", list(_LAYOUTS))
def test_r1_cmd_lookup_names_the_file_cmd_runs(layout: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B20. The marker ``cmd.exe /c tool`` prints is the marker of the file the cmd lookup names. A mismatch is a lookup
    that would prove the wrong file for a pinned ``allow``. ``proc_cwd_bat_d1_cmd`` (r2) separates cmd from a ``shutil.which``
    lookup: a file in this process's own directory, which ``which`` reads first unless ``NoDefaultCurrentDirectoryInExePath``
    is set (measured with it unset: ``which`` names the ``.bat`` there, cmd runs the ``.cmd`` on PATH). ``cwd_bat_d1_cmd`` (r1)
    and ``extensionless_d1_cmd_d2`` (r2) are controls: a ``shutil.which`` lookup over cmd's working directory and then PATH
    passes both, so the second rules out only a lookup that treats an extensionless file as runnable."""
    files, path_entries, process_directory = _LAYOUTS[layout]
    directories = {name: tmp_path / "layout" / name for name in ("cwd", "d1", "d2", "proc")}
    for directory in directories.values():
        directory.mkdir(parents=True)
    for directory_name, extension in files:
        if extension == "":
            (directories[directory_name] / "tool").write_bytes(b"@echo EXTLESS\r\n")  # not a file cmd runs; no alone control
        else:
            _write_tool(directories[directory_name], extension)
    path = ";".join(str(directories[name]) if name else "" for name in path_entries)
    cwd = directories["cwd"]

    # premise: each file alone, in a directory of its own and a working directory of its own, prints its own marker; a .ps1
    # is not a file cmd runs, so it prints nothing and does not run
    clean_cwd = tmp_path / "clean_cwd"
    clean_cwd.mkdir()
    for number, (_, extension) in enumerate((f for f in files if f[1] != ""), start=0):
        alone = tmp_path / "alone" / str(number)
        _write_tool(alone, extension)
        if extension == ".ps1":
            assert _run_cmd(str(alone), clean_cwd) == "" and not (alone / "ran_ps1").exists(), (layout, extension)
        else:
            assert _run_cmd(str(alone), clean_cwd) == _marker_of(extension), (layout, extension)

    if process_directory != "cwd":
        # this process's directory, which ``shutil.which`` reads first unless NoDefaultCurrentDirectoryInExePath is set
        monkeypatch.chdir(directories[process_directory])
    named = make_program_resolver(dialect="cmd", search_path=path, cwd=str(cwd), pathext=PATHEXT)("tool")

    printed = _run_cmd(path, cwd)
    assert named is not None, (layout, printed)
    assert os.path.isfile(named)
    assert printed == _marker_of(ntpath.splitext(named)[1]), (layout, named, printed)
    if layout in _NAMED_BY_LAYOUT:
        directory_name, file_name = _NAMED_BY_LAYOUT[layout]
        assert named == ntpath.join(str(directories[directory_name]), file_name), (layout, named, printed)


# --------------------------------------------------------------------------------------
# B21. PowerShell runs a file no lookup names
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("shell", ["powershell", "pwsh"])
def test_r1_powershell_runs_a_file_no_lookup_names(shell: str, tmp_path: Path) -> None:
    """B21. With ``tool.cmd`` and ``tool.ps1`` in one PATH directory PowerShell runs ``tool.ps1``, which neither the cmd
    lookup (it names ``tool.CMD``) nor the PowerShell resolver (it names nothing) says; ``where`` is an alias there."""
    executable = _windows_powershell() if shell == "powershell" else shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 (pwsh) is not installed on this host")
    d1 = tmp_path / "d1"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    _write_tool(d1, ".cmd")
    _write_tool(d1, ".ps1")

    printed = _run_powershell(executable, str(d1), cwd)

    assert printed == "PS1"
    assert (d1 / "ran_ps1").exists() and not (d1 / "ran_cmd").exists()
    by_cmd = make_program_resolver(dialect="cmd", search_path=str(d1), cwd=str(cwd), pathext=PATHEXT)("tool")
    assert by_cmd == ntpath.join(str(d1), "tool.CMD")  # the cmd lookup names the file PowerShell did not run
    by_powershell = make_program_resolver(dialect="powershell", search_path=str(d1), cwd=str(cwd), pathext=PATHEXT)("tool")
    assert by_powershell is None
    assert _run_powershell(executable, str(d1), cwd, "(Get-Command where).CommandType") == "Alias"


# --------------------------------------------------------------------------------------
# B22. Gate to real spawn, at the tool and at the agent
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("nest", ["plain", "long_spaced"])
@pytest.mark.asyncio
async def test_r1_tool_and_agent_end_to_end(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, nest: str) -> None:
    """B22. A real gate with real probes, a rule pinned to ``<d1>\\tool.CMD``, and real spawns; ``long_spaced`` runs it all
    in a directory of at least 200 characters holding a blank, so no assumption about a path's length or characters holds."""
    root = _work_root(tmp_path, nest)
    d1 = root / "d1"
    empty = root / "empty"
    empty.mkdir()
    if nest == "long_spaced":
        assert " " in str(root) and len(str(root)) >= 200  # premise: the layout this row exists for
    _write_tool(d1, ".cmd")
    # the PowerShell directory is on the PATH too: the agent starts ``powershell`` by name, and this process's PATH is the child's
    monkeypatch.setenv("PATH", f"{d1};{_system32()};{ntpath.dirname(_windows_powershell())}")
    monkeypatch.setenv("PATHEXT", PATHEXT)
    pin = ntpath.join(str(d1), "tool.CMD")
    config = CommandPolicyConfig.model_validate({
        "rules": [{
            "name": "pinned-tool", "pattern": ["tool"], "decision": "allow", "justification": "pinned-tool because",
            "host_executable": [pin],
        }],
        "unmatched_decision": "escalate",
    })
    gate = CommandPolicyGate(config, platform="win32")
    tool = RunCommandTool(SimpleNamespace(), command_policy_gate=gate)

    # (a) cmd runs the pinned file: allowed, and the shell printed that file's marker
    allowed = await tool.invoke({"command": "tool", "working_directory": str(empty)})
    assert allowed.error is None, allowed.error
    assert allowed.output["stdout"].strip() == "CMD"
    assert allowed.metadata["command_policy"]["decision"] == "allow"
    assert (d1 / "ran_cmd").exists()  # premise: (a) ran the pinned file, which left its marker; cleared so (b) can show it did not run again
    (d1 / "ran_cmd").unlink()

    # (b) a file in the working directory is found first: cmd would run it, so the call is refused and nothing ran
    planted = _write_tool(empty, ".bat")
    refused = await tool.invoke({"command": "tool", "working_directory": str(empty)})
    assert refused.error is not None
    named = ntpath.join(str(empty), "tool.BAT")
    cause = f"rule 'pinned-tool' allows tool only at {pin}; {named!r} is not one of them"
    assert planted.name.lower() == "tool.bat"
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert cause[:_MAX_REASON_CHARS].lower() in refused.error.lower()  # the gate shows at most this much of a cause
    assert not (empty / "ran_bat").exists() and not (d1 / "ran_cmd").exists()

    # (c) the agent starts PowerShell, where a bare name proves nothing: refused naming the pin, and tool.ps1 did not run
    _write_tool(d1, ".ps1")
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    bare = await agent._run_command("tool")
    assert bare["success"] is False
    assert f"run the pinned executable: {pin}"[:_MAX_REASON_CHARS].lower() in bare["error"].lower()
    assert not (d1 / "ran_ps1").exists()
    command = f"& '{pin}'"  # a path with blanks is written quoted, whatever its length
    assert gate.judge(command, site="shell_command_agent", search_path=os.environ["PATH"]).decision == "allow"
    written = await agent._run_command(command)
    assert written["success"] is True, written
    assert written["data"]["stdout"].strip() == "CMD"


# --------------------------------------------------------------------------------------
# B34 (S2a repair r2). cmd keeps a blank in PATHEXT: the gate does not trim it
# --------------------------------------------------------------------------------------

_BLANK_PATHEXT = {"lead_blank": ".EXE; .CMD;.BAT", "trail_blank": ".EXE;.CMD ;.BAT"}


def _tool_gate_and_tool(d1: Path, pin: str) -> tuple[CommandPolicyGate, RunCommandTool]:
    config = CommandPolicyConfig.model_validate({
        "rules": [{
            "name": "pinned-tool", "pattern": ["tool"], "decision": "allow", "justification": "pinned-tool because",
            "host_executable": [pin],
        }],
        "unmatched_decision": "escalate",
    })
    gate = CommandPolicyGate(config, platform="win32")
    return gate, RunCommandTool(SimpleNamespace(), command_policy_gate=gate)


@pytest.mark.parametrize("nest", ["plain", "long_spaced"])
@pytest.mark.parametrize("variant", list(_BLANK_PATHEXT))
@pytest.mark.asyncio
async def test_r2_cmd_keeps_a_blank_in_pathext(
    variant: str, nest: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """B34. With a blank in PATHEXT cmd.exe does not read ``.CMD`` there, so it runs ``tool.bat`` where a lookup that trimmed
    the blank would name ``tool.CMD``: the gate refuses the PATHEXT, so the pinned call is refused and nothing ran. Kills G39."""
    value = _BLANK_PATHEXT[variant]
    root = _work_root(tmp_path, nest)
    d1 = root / "d1"
    empty = root / "empty"
    empty.mkdir()
    _write_tool(d1, ".cmd")
    _write_tool(d1, ".bat")
    path = f"{d1};{_system32()}"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("PATHEXT", value)
    pin = ntpath.join(str(d1), "tool.CMD")
    _, tool = _tool_gate_and_tool(d1, pin)

    # premise, the class measured: cmd runs tool.bat under this PATHEXT
    assert _run_cmd(path, empty, pathext=value) == "BAT", (variant, value)
    (d1 / "ran_bat").unlink()  # the premise ran it; the refusal below must leave none
    assert make_program_resolver(dialect="cmd", search_path=path, cwd=str(empty), pathext=value)("tool") is None

    refused = await tool.invoke({"command": "tool", "working_directory": str(empty)})
    assert refused.error is not None
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert not (d1 / "ran_bat").exists() and not (d1 / "ran_cmd").exists()

    # control: the same layout with a PATHEXT that holds no blank is allowed, and cmd runs the pinned file
    monkeypatch.setenv("PATHEXT", ".EXE;.CMD;.BAT")
    allowed = await tool.invoke({"command": "tool", "working_directory": str(empty)})
    assert allowed.error is None, allowed.error
    assert allowed.metadata["command_policy"]["decision"] == "allow"
    assert allowed.output["stdout"].strip() == "CMD"


# --------------------------------------------------------------------------------------
# B35 (S2a repair r2). cmd runs its internal command, not a file of the same name
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("nest", ["plain", "long_spaced"])
@pytest.mark.asyncio
async def test_r2_cmd_runs_its_internal_command_not_the_pinned_file(
    nest: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """B35. ``echo`` under cmd is the internal command even with an ``echo.cmd`` on the PATH, so a rule pinned to that
    file does not allow the bare name; the file written out as a quoted path is what it allows. Kills G44."""
    root = _work_root(tmp_path, nest)
    d1 = root / "d1"
    empty = root / "empty"
    empty.mkdir()
    d1.mkdir()
    (d1 / "echo.cmd").write_bytes(_BODIES[".cmd"].encode("ascii"))
    path = f"{d1};{_system32()}"
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("PATHEXT", PATHEXT)
    pin = ntpath.join(str(d1), "echo.CMD")
    config = CommandPolicyConfig.model_validate({
        "rules": [{
            "name": "echo-pinned", "pattern": ["echo"], "decision": "allow", "justification": "echo-pinned because",
            "host_executable": [pin],
        }],
        "unmatched_decision": "escalate",
    })
    gate = CommandPolicyGate(config, platform="win32")
    tool = RunCommandTool(SimpleNamespace(), command_policy_gate=gate)

    # premise: cmd runs its internal echo (whose text is locale dependent), not the file
    printed = _run_cmd(path, empty, command="echo")
    assert printed != "CMD" and not (d1 / "ran_cmd").exists(), printed
    assert make_program_resolver(dialect="cmd", search_path=path, cwd=str(empty), pathext=PATHEXT)("echo") is None

    refused = await tool.invoke({"command": "echo", "working_directory": str(empty)})
    assert refused.error is not None
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert f"run the pinned executable: {pin}"[:_MAX_REASON_CHARS].lower() in refused.error.lower()
    assert not (d1 / "ran_cmd").exists()

    command = f'"{pin}"'
    assert gate.judge(command, site="run_command_tool", search_path=path).decision == "allow"  # premise: the written pin
    allowed = await tool.invoke({"command": command, "working_directory": str(empty)})
    assert allowed.error is None, allowed.error
    assert allowed.metadata["command_policy"]["decision"] == "allow"
    assert allowed.output["stdout"].strip() == "CMD"
    assert (d1 / "ran_cmd").exists()
