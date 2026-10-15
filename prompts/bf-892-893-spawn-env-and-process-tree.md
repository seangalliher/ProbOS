# Build contract: BF-892 (#1543) and BF-893 (#1544), one batch

**Corrections (orchestrator, after slice 893 review round 1, 2026-10-15; the sentences below are corrected in place):** (1) a Windows descendant that asks for `CREATE_BREAKAWAY_FROM_JOB` is neither refused nor does it escape the job: it starts and a timeout still ends it (reproduced with a real grandchild, twice); (2) the POSIX claim that the kill "runs before any `wait`, so the pid cannot be reused" is false for the asyncio path (3.12's child watcher reaps independently while the caller can still be awaiting the pipes), so it is not claimed; the CI tests show group ownership, an already-exited command and a grandchild, and process-group-id reuse is recorded as a follow-up; (3) the caller's `wait_for` and the worker thread's own `communicate` timeout were two budgets that started at different times, so under executor contention a caller was told "timed out" while the command was still running: one submission deadline is now shared with the worker (the review's P1); (4) Section 3.3's "SEARCH (delete the old outer handler)" was an annotated label the installer skipped; the orchestrator applied it.

**Verdict: ready to build as 3 slices (892a, 892b, 893), one gate and one PR.** Three of the orchestrator's facts were wrong, and the contract corrects them:

1. **The AST scan undercounts.** There are **39 launches, not 38**. The scan missed `swe_harness/tools.py:1150`, which calls `_asyncio.create_subprocess_shell` through `import asyncio as _asyncio` (:1136). It already passes `env=`, so the true split is **13 with `env=`, 26 without**.
2. **Two of the "12 with `env=`" still hand over the whole environment.**
   - `mcp_bridge/transport.py:271` builds `env = {**os.environ, **self._env} if self._env else None`. With no extra variables it passes `None`, so the server inherits everything.
   - `execution/authority.py:780` builds `git_environment = os.environ.copy()`.
   - A guard that only checks for a non-`None` `env=` would pass both.
3. **BF-893 needs a race-free Windows design.** If the shell is assigned to a job only after it starts, `run_command`'s `await` leaves a gap that grows with event-loop load. The design is: start the shell suspended, assign it to a job, then resume it.

I ran no mutants and no tests (read-only consult). The Builder runs the mutation campaign once.

---

## Verified Against Codebase (2026-10-14, HEAD `7301f647`)

```
git log --oneline -5                       -> 7301f647 Merge origin/main ...; git status clean
Grep 'subprocess\.(run|Popen|call|check_call|check_output|getoutput|getstatusoutput)\b|create_subprocess_(exec|shell)|os\.(system|popen|exec..|spawn..|posix_spawnp?|startfile)\b|pty\.spawn' src/probos
  -> 39 launches: the 38 in spawn-scan.json plus swe_harness/tools.py:1150 (_asyncio.create_subprocess_shell)
Grep import aliases '^\s*(import (subprocess|asyncio|os)\s+as ...|from (subprocess|asyncio|os) import ...)' src/probos
  -> tools.py:1136 'import asyncio as _asyncio' (the launch alias); the others (_aio, _asyncio, _os) launch nothing
src/probos/execution/command_env.py:98-122  build_command_env(declared=(), *, source=None, platform=None) -> dict:
  the allowlist plus declared names that pass env_name_refusal; refused names are logged and skipped
  (credential words, PROBOS_ prefix, bad shape). SSH_AUTH_SOCK/XDG_RUNTIME_DIR are deliberately absent (:43-44).
  No PROXY, PIP_*, GH_*, DOCKER_*, OLLAMA_*, RIPGREP_*, VIRTUAL_ENV.
cognitive/builder.py:2433-2442  _run_tests: env = os.environ.copy() + PYTHONPATH; subprocess.run(..., env=env)
cognitive/builder.py:2511-2520  _run_targeted_tests: same shape
cognitive/builder.py:97-98     _FORBIDDEN_PATHS = (".git/", ...)  (the model cannot write git hooks)
security/container_sandbox.py:168  env = {**os.environ, **request.env}; :173 subprocess.run(... env=env)
security/container_sandbox.py:53  'import os'; its only use is :168
security/container_sandbox.py:255  DockerContainerSandbox.run: subprocess.run(args, ...) with no env
cognitive/dependency_resolver.py:219,236,250  subprocess.run([...pip|uv...]) with no env; module has no 'import os'
integrations/mcp_bridge/transport.py:271  env = {**os.environ, **self._env} if self._env else None; :26 import os is its only use
execution/authority.py:780  git_environment = os.environ.copy(); :807/:814/:821 env=git_environment
execution/isolation.py:854-863  env = self._build_env(request) (SANDBOX_ENV_PASSTHROUGH); Popen(..., env=env, **popen_kwargs)
execution/isolation.py:1079  "_kill still ends only this child on Windows, not its tree (#1417)"; #1417 is CLOSED
agents/red_team.py:302-307  wait_for(run_in_executor(_run_verify_sync, command, build_command_env(...)), timeout=5.0)
agents/red_team.py:385-406  _run_verify_sync(command, env): Popen(..., env=env); communicate(timeout=5);
                            except TimeoutExpired: proc.kill(); return None
agents/shell_command.py:216-266  _run_sync: Popen powershell (win) / shell=True (posix), env=env;
                            communicate(timeout=DEFAULT_TIMEOUT); except TimeoutExpired: proc.kill(); proc.wait(); return {"success": False, "error": ...}
cognitive/swe_harness/tools.py:1150-1167  create_subprocess_shell(..., env=build_command_env(...));
                            wait_for(communicate(), timeout); except TimeoutError: proc.kill() in try/except; return ToolResult(error=...)
credential_store.py:89-95  built-in spec cli_command=["gh","auth","token"]
pyproject.toml:9,106,190    requires-python >=3.12; pytest-timeout>=2.3; timeout = 180
.github/workflows/ci.yml:17  ubuntu-latest only; no mypy or ruff step
Glob psutil* in d:/ProbOS/.venv/Lib/site-packages -> none; Grep psutil in pyproject/src -> two comments only
```

### Absence Verified

| Claim | Run | Found | Holds |
|---|---|---|---|
| No launch shape beyond the 39 | the launch Grep above, plus Grep `subprocess_exec\b\|subprocess_shell\b\|multiprocessing\|startfile\|webbrowser\.open\|ProcessPoolExecutor\|\bpty\b` | the 39, plus `__main__.py:892 webbrowser.open` (not a subprocess API) | yes; webbrowser is listed under the guard's limits |
| None of the three BF-893 sites passes `creationflags` or `start_new_session` | Grep `start_new_session\|creationflags\|killpg\|CREATE_` in src | `__main__.py:255,463` (CREATE_NO_WINDOW) and `isolation.py:1080-1084` only | yes |
| No test asserts a launch's exact kwargs | Grep `assert_called_(once_)?with\(\|call_args(\.kwargs\|\[1\])\s*==\|kwargs\s*==\s*\{` in the 15 patching test files | `test_ad1211:979,1097,1165` (`invoke`/`enable`), `test_dependency_resolver:263,336` (`install_fn`), `test_scout:269` (`call_args[1]=="api"`, positional) | yes; every patched fake takes `**kwargs` (Grep of fake defs: all `**kwargs` or `**_kwargs`) |
| A "scrubbed-environment launcher" exists in the repo | Grep `(?i)scrub\|launcher` in `scripts/` and `logs/architect/*.md` | only `check_config_facade.py:760 scrubbed_env` (internal) and the issue text | **not found.** The tests below are safe by construction (synthetic plants; children print only booleans or markers; assertions use derived values). Run them under your launcher if it lives outside the repo |

---

## Hidden pins (update these or they break)

| Pin | Why | Slice | Action |
|---|---|---|---|
| `tests/test_expansion_agents.py` tests at :203/:208, :220/:226, :646/:648, :703/:705, ~:751 | They patch `probos.agents.shell_command.subprocess.Popen`, which is the global `subprocess.Popen`, so red_team's Popen is patched too. Both return a MagicMock. On Windows, `ProcessTree.attach` opens the mock's `pid` through ctypes, gets `ArgumentError`, and the agent returns its error shape. | 893 | Add the `direct_kill_process_tree` fixture (Section 3.5) and `@pytest.mark.usefixtures` on those five |
| `tests/test_bf890_run_command_env.py:70-81` `_wait_out_the_orphan` | Its docstring says RunCommandTool "kills the shell, not the command". After BF-893 that is false, and the loop waits the full 5 s for a marker that never comes. | 893 | Section 3.6 (docstring, default 0.5 s) |
| `tests/test_bf890_command_env.py:468-486` (raw-source detector over tools, shell_command, red_team) | It counts a call with `**` and no `env` keyword as missing (:483, :132-137). | 893 | No change needed: every edited launch keeps an explicit `env=` before `**process_tree_popen_kwargs()`. The Diff Reviewer must confirm. |
| `tests/test_quality_hardening.py:44-71` (`getsource` checks on `KnowledgeStore._git_run`, `DependencyResolver._install_package`, `_cmd_reset`) | They assert `encoding` is present and `text=True` is absent. | 892a/b | Do not add `text=True`. Adding `env=` is safe. |
| `tests/test_ad1025_path_anchoring.py:206,232` (global Popen patch on the piper path) | Its fake is `_factory(args, *_pos, **_kwargs)`. | 892b | Safe |
| `tests/test_ad1014_stdio_mcp_transport.py` (`env={}` everywhere) | Before: `{}` led to `None`, which inherits. After: `dict(os.environ)`, with the same contents. | 892b | Safe; no test asserts `env is None` (Grep `\benv\b` in that file) |

---

## Ranked options

**(a) How the 26 launches state their environment**

| Rank | Option | Verdict |
|---|---|---|
| 1 | **The allowlist where the command or code is model-reachable (6 launches); `trusted_command_env()` for argv ProbOS fixes (25 launches, plus authority's 3 and transport's 1 rewritten). Every trusted use is listed with its reason in the guard's `TRUSTED_ENV_SITES`.** | **Chosen.** No behaviour change for trusted launches, as the issue requires. Exposure is not reintroduced, because (i) the helper is the *only* route the guard accepts to the full environment (`os.environ`, `.copy()`, `dict(os.environ)`, `**os.environ`, `None` and a `None` branch all fail); (ii) a new use fails the guard until someone edits the inventory with a reason, which is a reviewed diff; (iii) the inventory is checked both ways, so a stale entry also fails. |
| 2 | The allowlist everywhere | Rejected. It breaks `gh` (GH_TOKEN), git push/SSH, `docker` (DOCKER_HOST), `ollama serve` (OLLAMA_*), `rg` (RIPGREP_CONFIG_PATH) and ProbOS's own probe (PROBOS_*). That is a behaviour change on trusted argv. |
| 3 | A hand-written dict at each site | Rejected. It is 25 small allowlists, which breaks DRY and "no second allowlist". |

Helper: `trusted_command_env() -> dict[str, str]` in `execution/command_env.py`, returning `dict(os.environ)` (a copy, so a caller's additions never reach `os.environ`).

**Classification of all 39 launches**

"Data" below means model text passed as a bound argument value, never run as code.

| Site | Argv | Model-reachable? | Needs from the environment | Decision |
|---|---|---|---|---|
| builder `_run_tests` / `_run_targeted_tests` | pytest over **model-written tests** | **code** | PATH, SYSTEMROOT, TEMP, PYTHONPATH | allowlist + PYTHONPATH (892a) |
| container_sandbox `InProcessContainerSandbox.run` | **model command** | **code** | allowlist + `request.env` | allowlist + `request.env` (892a) |
| dependency_resolver ×3 | pip/uv install of a **model-named package** (runs the package's build step) | **code** | PATH, APPDATA/HOME (pip config), VIRTUAL_ENV (uv) | allowlist + `VIRTUAL_ENV` (892a) |
| tools `RunCommandTool.invoke`, shell_command ×2 | model command | code | already the allowlist (BF-890) | unchanged |
| red_team ×2 | model command (re-run) | code | `env` parameter; its one caller passes the allowlist (:305) | INDIRECT inventory |
| isolation `SubprocessSandbox._run_sync_inner` | run_python | code | `_build_env`, which is the sandbox base set | INDIRECT inventory |
| `__main__` `_ensure_ollama` | `ollama serve` | fixed | OLLAMA_*, CUDA_* | trusted |
| `__main__` `_check_nats` | nats-server | fixed | PATH | trusted |
| `__main__` `_cmd_reset` ×2 | git add/commit (Captain's CLI) | fixed | HOME/USERPROFILE, GIT_* | trusted |
| code_search `_search_rg` | rg; model text only after `--regexp`/`--glob` | data | RIPGREP_CONFIG_PATH | trusted |
| piper `synthesize._run_sync` | piper; text on stdin | data | ESPEAK_* | trusted |
| blender `render` | blender with ProbOS's own script | fixed | BLENDER_* | trusted |
| rhubarb ×3 (`_convert_to_wav`, `probe_version`, `_run_rhubarb`) | ffmpeg/rhubarb | fixed | PATH | trusted |
| builder `_run_git._sync_run` | git branch/checkout/add/commit (`.git/` not writable by the model, :97-98) | data | git identity, GIT_SSH* | trusted |
| builder `_is_dirty_working_tree` ×2 | git rev-parse/status | fixed | HOME | trusted |
| artifact_extractor `_to_docx_libreoffice` | soffice converting **model-authored content** | data (document) | profile dirs | trusted (follow-up 6) |
| referent_gate `GitObjectResolver._resolve_sync` | `git cat-file -e -- <token>` | data | HOME | trusted |
| scout `ScoutAgent._search_github` (by reference) | gh api | data | GH_TOKEN/gh config | trusted |
| credential_store `CredentialStore._resolve` | `gh auth token` (built-in spec) | fixed | gh config/keyring | trusted |
| sandbox_check `_docker_info_sync` | docker info | fixed | DOCKER_HOST | trusted |
| episodic_health `check_episodic_health` | `python -m probos._episodic_probe` | fixed | PROBOS_* | trusted |
| authority `_ManifestPreparer._repository_binding` ×3 | git with config stripped | fixed | as today | trusted (rewritten) |
| transport `StdioTransport.start` | operator-approved MCP server | third-party | as today | trusted (rewritten; follow-up 5) |
| records_store `RecordsStore._git_sync`, store `KnowledgeStore._git_run` | git | fixed | HOME | trusted |
| container_sandbox `DockerContainerSandbox.run` | `docker run` (the container gets only `-e`) | fixed CLI | DOCKER_* | trusted |
| worktree_manager `WorktreeManager._run_git` | git | fixed | HOME | trusted |

**(b) What the guard accepts**

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Only `env` values traced to the owners**: a direct owner call; a dict display whose first element is `**owner(...)`; a local name every binding of which is one of those (item assignment is allowed); an IfExp only if no branch fails. A parameter or another function's result is INDIRECT and must be listed. Any whole use of `os.environ` fails (single-variable `.get`/`[...]` reads are allowed). | **Chosen.** `env=os.environ.copy()` cannot pass. Reports `path:line callee (shape, scope) -> verdict`. |
| 2 | Any non-`None` `env=` | Rejected. It passes `os.environ.copy()` and the transport's runtime `None`. |
| 3 | Option 1 without name resolution (owners inline only) | Rejected. It would force rewrites of shell_command, authority and container. |

**(c) Slicing**

**Chosen: 892a** (the three exposed sites, their tests, their mutants), then **892b** (`trusted_command_env`, the remaining launches, authority/transport, the guard), then **893**. Each slice has its own Builder milestone, Diff Review and commit; the gate runs once.

**(d) Windows and POSIX kill mechanism**

| Rank | Option | Verdict |
|---|---|---|
| 1 | **POSIX: `start_new_session=True` + `os.killpg(pid, SIGKILL)`. Windows: `CREATE_SUSPENDED`, then a job object, `AssignProcessToJobObject`, `NtResumeProcess`, and `TerminateJobObject` on timeout. No kill-on-close.** | **Chosen.** Race-free by construction: no instruction of the shell runs before it is in the job. It reaches a descendant whose parent already exited. A command that finishes in time keeps its background descendants, as today and on POSIX. `NtResumeProcess` is undocumented but is what psutil (since 5.6.0) and Sysinternals use; on a fresh suspended process it has one thread to resume. Nested jobs are fine on Windows 10+. If the job cannot be made: log a warning and fall back to killing the shell only, the pre-BF-893 behaviour. If the child cannot be resumed: kill it and raise `OSError`, which each site already maps to its error shape. |
| 2 | A job assigned after spawn, without suspending | Rejected. In `run_command`, `await create_subprocess_shell` returns after event-loop round-trips, so `cmd.exe` can start the command first, and under load it will. |
| 3 | `taskkill /T /F /PID` | Rejected. It finds descendants by parent id at kill time, so it misses descendants whose intermediate parent has exited (a shell whose backgrounded command holds the pipe). It also spawns an external binary, which must use an absolute path to avoid a CWD hijack and would itself need guard coverage. |
| — | `PROC_THREAD_ATTRIBUTE_JOB_LIST` | Unreachable: `subprocess.STARTUPINFO.lpAttributeList` supports only `handle_list`. |

**(e) One shared helper**

The helper is `src/probos/execution/process_tree.py`:
- `process_tree_popen_kwargs(platform=None) -> dict`
- `ProcessTree.attach(proc)`, `.kill()` (never raises; idempotent; an exited process is not an error), `.close()` and a context manager.
- `SpawnedProcess` Protocol (`pid`, `kill()`), which `Popen` and `asyncio.subprocess.Process` both satisfy.

None of the three sites passes `creationflags` or `start_new_session` today (Absence table), so nothing collides.

Known limit: a descendant that detaches on purpose (`setsid`, a double fork, work handed to a service) escapes on both platforms.

Windows: a grandchild that asks for `CREATE_BREAKAWAY_FROM_JOB` is neither refused nor does it escape: it starts and a timeout still ends it (reproduced by probe in review round 1). The job sets no breakaway-OK limit.

**(f) Unchanged**

Timeouts (the caller's value, the agent's `DEFAULT_TIMEOUT`, the red team's 5 s), output caps and the shapes `ToolResult(error=...)`, `{"success": False, "error": ...}` and `None` all stay as they are.

---

## Slice 892a — the three exposed sites

### Section 1 -- `src/probos/cognitive/builder.py`

SEARCH:
```python
from probos.events import EventType
from probos.execution.isolation import remove_workdir_off_loop
```
REPLACE:
```python
from probos.events import EventType
from probos.execution.command_env import build_command_env
from probos.execution.isolation import remove_workdir_off_loop
```

SEARCH:
```python
async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            env = os.environ.copy()
            src_dir = str(Path(work_dir) / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{work_dir}{os.pathsep}{src_dir}" + (f"{os.pathsep}{existing}" if existing else "")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"],
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=env,
            )
```
REPLACE:
```python
def _pytest_pythonpath(work_dir: str) -> str:
    """The work tree and its ``src``, then the runtime's own ``PYTHONPATH`` (the pre-BF-892 order)."""
    src_dir = str(Path(work_dir) / "src")
    existing = os.environ.get("PYTHONPATH", "")
    return f"{work_dir}{os.pathsep}{src_dir}" + (f"{os.pathsep}{existing}" if existing else "")


async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            # BF-892 (#1543): the tests are model-authored; they get the command
            # allowlist plus PYTHONPATH, never the runtime's environment.
            run_env = {**build_command_env(), "PYTHONPATH": _pytest_pythonpath(work_dir)}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"],
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=run_env,
            )
```

SEARCH:
```python
    def _sync_run() -> tuple[int, str]:
        try:
            env = os.environ.copy()
            src_dir = str(Path(work_dir) / "src")
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{work_dir}{os.pathsep}{src_dir}" + (f"{os.pathsep}{existing}" if existing else "")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"] + test_files,
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=env,
            )
```
REPLACE:
```python
    def _sync_run() -> tuple[int, str]:
        try:
            # BF-892 (#1543): model-authored tests; allowlist plus PYTHONPATH only.
            targeted_env = {**build_command_env(), "PYTHONPATH": _pytest_pythonpath(work_dir)}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"] + test_files,
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=targeted_env,
            )
```

### Section 2 -- `src/probos/security/container_sandbox.py`

SEARCH:
```python
import logging
import os
import shutil
```
REPLACE (`os` has no other use; :168 was the only one):
```python
import logging
import shutil
```

SEARCH:
```python
from typing import Literal, Protocol, runtime_checkable
```
REPLACE:
```python
from typing import Literal, Protocol, runtime_checkable

from probos.execution.command_env import build_command_env
```

SEARCH:
```python
        cwd = str(request.workspace_root) if request.workspace_root else None
        env = {**os.environ, **request.env}
        t0 = time.monotonic()
```
REPLACE:
```python
        cwd = str(request.workspace_root) if request.workspace_root else None
        # BF-892 (#1543): the command allowlist, then request.env as the caller's
        # explicit extension -- never the runtime's environment.
        env = {**build_command_env(), **request.env}
        t0 = time.monotonic()
```

### Section 3 -- `src/probos/cognitive/dependency_resolver.py`

SEARCH:
```python
from collections.abc import Awaitable, Callable
from typing import Any, Literal
```
REPLACE:
```python
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from probos.execution.command_env import build_command_env
```

SEARCH:
```python
        loop = asyncio.get_running_loop()

        # Method 1: pip via the running Python (most reliable)
```
REPLACE:
```python
        loop = asyncio.get_running_loop()
        # BF-892 (#1543): a package's build step runs third-party code. It gets the
        # command allowlist plus VIRTUAL_ENV (so uv targets the same venv), never
        # the runtime's environment. A proxy or index set only in the runtime's
        # environment is not passed; pip's own config file (APPDATA/HOME) still is.
        install_env = build_command_env(("VIRTUAL_ENV",))

        # Method 1: pip via the running Python (most reliable)
```

Make these three one-line edits, keeping the rest of each call unchanged:
- `[sys.executable, "-m", "pip", "install", package_name],` becomes `[sys.executable, "-m", "pip", "install", package_name], env=install_env,`
- `[uv_path, "pip", "install", package_name],` becomes `[uv_path, "pip", "install", package_name], env=install_env,`
- `[uv_path, "add", package_name],` becomes `[uv_path, "add", package_name], env=install_env,`

### Tests -- `tests/test_bf892_spawn_env.py` (new)

```python
"""BF-892 (#1543): model-authored code outside the run_python sandbox no longer inherits the runtime's environment.

Each test plants a synthetic credential-shaped variable, first proves a child that INHERITS
this process's environment sees it (the premise), then proves the site's child does not.
Children print or write only booleans, never an environment value or listing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from probos.cognitive import dependency_resolver as dependency_resolver_module
from probos.cognitive.builder import _run_targeted_tests, _run_tests
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.security.container_sandbox import ContainerExec, InProcessContainerSandbox, SandboxLimits

PLANT_NAME = "BF892_PROBE_API_KEY"
PLANT_VALUE = "bf892-planted-secret-4c1"
_SEES_PLANT = f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r})"


@pytest.fixture
def plant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PLANT_NAME, PLANT_VALUE)


def _inheriting_child_sees_plant() -> bool:
    done = subprocess.run([sys.executable, "-c", _SEES_PLANT], env=None, capture_output=True, text=True, timeout=60)
    return done.stdout.strip() == "True"


def _write_model_test(work: Path) -> Path:
    tests = work / "tests"
    tests.mkdir()
    (tests / "test_probe_env.py").write_text(
        "import json, os\n\n"
        "def test_records_what_the_child_sees():\n"
        f"    seen = {{'plant': os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r},\n"
        f"            'pythonpath': {str(work)!r} in os.environ.get('PYTHONPATH', '').split(os.pathsep)}}\n"
        "    open('seen.json', 'w').write(json.dumps(seen))\n",
        encoding="utf-8",
    )
    return work / "seen.json"
```

The test cases (premise first in each; `@pytest.mark.timeout(150)` on the pytest-running ones):

1. **`test_premise_an_inheriting_child_sees_the_plant`** (uses `plant`): `assert _inheriting_child_sees_plant()`.
2. **`test_run_tests_hides_the_plant_and_keeps_pythonpath`** (`plant`, `tmp_path`):
   - Premise: the inheriting child sees the plant.
   - Write the model test, then `passed, _ = await _run_tests(str(tmp_path), timeout=120)`.
   - Premise: `passed and seen.exists()`.
   - Assert the JSON equals `{"plant": False, "pythonpath": True}`.
   - Kills M1.
3. **`test_run_targeted_tests_hides_the_plant`**:
   - Run `_run_targeted_tests(str(tmp_path), ["tests/test_probe_env.py"], timeout=120)`.
   - Premise: the returned `test_files == [str(tmp_path / "tests" / "test_probe_env.py")]` (the targeted path ran, not the fallback).
   - Assert `{"plant": False, "pythonpath": True}`.
   - Kills M2.
4. **`test_inprocess_container_hides_the_plant_and_keeps_request_env`**:
   - Command: `[sys.executable, "-c", f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r}, os.environ.get('BF892_EXTENSION') == 'kept')"]`.
   - Request: `egress_policy="bridge"`, `env={"BF892_EXTENSION": "kept"}`, `limits=SandboxLimits(wall_timeout_seconds=30)`.
   - Premise: `out.success`.
   - Assert `out.stdout.split() == ["False", "True"]`.
   - Kills M3.
5. **`test_dependency_install_hides_the_plant_on_every_method`** (`plant`, `monkeypatch`):
   - Capture `real_run = subprocess.run` *before* patching. The premise uses `real_run` with `env=None`.
   - Patch `dependency_resolver_module.subprocess.run` with `_probe_run(argv, **kw)`. It runs `real_run([sys.executable, "-c", _SEES_PLANT], env=kw.get("env"), capture_output=True, text=True, timeout=60)`, records `(" ".join(map(str, argv[1:3])), stdout == "True")`, and returns `subprocess.CompletedProcess(argv, 1, "", "")`.
   - Patch `dependency_resolver_module.shutil.which` with `lambda name: "uv-bf892-fake"`.
   - Run `ok, _ = await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")`.
   - Assert `ok is False`.
   - Assert the labels equal `["-m pip", "pip install", "add bf892-not-a-package"]`.
   - Assert the seen flags equal `[False, False, False]`.
   - Kills M4, M5 and M6.
6. **`test_dependency_install_keeps_virtual_env`**: `monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))`. A recorder captures `kw.get("env")` across all three calls. Assert there are 3 envs, each not `None` and each with `env["VIRTUAL_ENV"] == str(tmp_path)`. Kills M7.
7. **`test_dependency_install_omits_unset_virtual_env`**: `monkeypatch.delenv("VIRTUAL_ENV", raising=False)`, then assert `"VIRTUAL_ENV" not in env` for all three (boundary case).

**Focused check (892a):**

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf892_spawn_env.py tests/test_builder_agent.py tests/test_builder_guardrails.py tests/test_ad798_container_sandbox.py tests/test_dependency_resolver.py tests/test_quality_hardening.py -q -n 0 -p no:randomly
```

---

## Slice 892b — every launch states its environment; the guard

### Section 4 -- `src/probos/execution/command_env.py` (append after `build_command_env`)

```python
def trusted_command_env() -> dict[str, str]:
    """BF-892 (#1543): the runtime's whole environment, for a command ProbOS builds itself.

    For a launch whose program and argument shape ProbOS fixes -- ``git`` on its own
    repositories, ``gh``, ``docker``, ``ollama``, ``nats-server``, ``rg``, ``blender``,
    ``rhubarb``, ``piper``, ``soffice``, a credential helper, ProbOS's own probe, an
    operator-approved MCP server -- that may need the operator's toolchain variables
    (credentials, proxies, config paths). Never for a command or code the model or an
    agent wrote: those use :func:`build_command_env`.

    Returns a copy, so a caller's additions never reach ``os.environ``. Every caller is
    listed with its reason in ``tests/test_bf892_spawn_env_guard.py``
    (``TRUSTED_ENV_SITES``); a new caller fails that guard until it is listed, so choosing
    this environment is always a reviewed decision.
    """
    return dict(os.environ)
```

### Section 5 -- the remaining launches (one mechanical edit each)

In each file:
- Add `from probos.execution.command_env import trusted_command_env` to its first-party import block. Where the file already imports `build_command_env` (container_sandbox from 892a), extend that import instead.
- **Insert the line `<indent>env=trusted_command_env(),`** immediately after the anchor line, inside the launch call. Each anchor is unique within its function.

The guard test is the completeness check: a missed site fails it.

| # | File | Scope | Anchor (stripped) | Indent |
|---|---|---|---|---|
| 1 | `__main__.py` | `_ensure_ollama` | `[ollama_bin, "serve"],` | 16 |
| 2 | `__main__.py` | `_check_nats` | `cmd,` (the line right after `subprocess.Popen(`) | 12 |
| 3 | `__main__.py` | `_cmd_reset` | `["git", "-C", str(repo_path), "add", "-A"],` | 16 |
| 4 | `__main__.py` | `_cmd_reset` | `f"probos reset: Tier {tier} — {RESET_TIERS[tier]['name']}"],` | 16 |
| 5 | `agents/code_search.py` | `CodeSearchAgent._search_rg` | `*args,` | 16 |
| 6 | `audio/tts/piper_backend.py` | `PiperBackend.synthesize._run_sync` | `stdin=subprocess.PIPE,` | 24 |
| 7 | `avatars/blender_renderer.py` | `BlenderRenderer.render` | `*cmd,` | 16 |
| 8 | `avatars/rhubarb_backend.py` | `_convert_to_wav._run_sync` | `args,` (line after `proc = subprocess.Popen(`) | 12 |
| 9 | `avatars/rhubarb_backend.py` | `probe_version._probe_sync` | `[str(binary_path), "--version"],` | 16 |
| 10 | `avatars/rhubarb_backend.py` | `_run_rhubarb._run_sync` | `stdout=subprocess.PIPE,` | 16 |
| 11 | `cognitive/builder.py` | `_run_git._sync_run` | `["git", *args],` | 12 |
| 12 | `cognitive/builder.py` | `_is_dirty_working_tree` | `"git", "rev-parse", "--git-dir",` | 12 |
| 13 | `cognitive/builder.py` | `_is_dirty_working_tree` | `"git", "status", "--porcelain",` | 12 |
| 14 | `cognitive/dm/artifact_extractor.py` | `_to_docx_libreoffice` | `[soffice, "--headless", "--convert-to", "docx", "--outdir", d, src],` | 16 |
| 15 | `cognitive/referent_gate.py` | `GitObjectResolver._resolve_sync` | `["git", "cat-file", "-e", "--", f"{token}^{{object}}"],` | 20 |
| 16 | `cognitive/scout.py` | `ScoutAgent._search_github` | `"-f", "per_page=30"],` (`to_thread` forwards it) | 16 |
| 17 | `credential_store.py` | `CredentialStore._resolve` | `spec.cli_command,` | 20 |
| 18 | `doctor/checks/sandbox_check.py` | `_docker_info_sync` | `["docker", "info", "--format", "{{.ServerVersion}}"],` | 12 |
| 19 | `episodic_health.py` | `check_episodic_health` | `[sys.executable, "-m", "probos._episodic_probe", str(data_dir)],` | 16 |
| 20 | `knowledge/records_store.py` | `RecordsStore._git_sync` | `["git"] + list(args),` | 12 |
| 21 | `knowledge/store.py` | `KnowledgeStore._git_run` | `["git", "-C", str(self._repo_path), *args],` | 16 |
| 22 | `security/container_sandbox.py` | `DockerContainerSandbox.run` | `args,` (line after `lambda: subprocess.run(  # noqa: S603` in this class) | 20 |
| 23 | `worktree_manager.py` | `WorktreeManager._run_git` | `*args,` | 12 |

### Section 6 -- `src/probos/execution/authority.py`

SEARCH: `        git_environment = os.environ.copy()`
REPLACE: `        git_environment = trusted_command_env()`

Keep `import os`: `os.devnull` is still used at :787/:797.

### Section 7 -- `src/probos/integrations/mcp_bridge/transport.py`

SEARCH: `        env = {**os.environ, **self._env} if self._env else None`

REPLACE:
```python
        # BF-892 (#1543): stated, not inherited by omission. An operator-approved
        # server gets the runtime's environment plus its own declared variables,
        # exactly as before (None used to inherit the same environment).
        env = {**trusted_command_env(), **self._env}
```

Then delete `import os` (:26): its only use was :271 (Grep `\bos\.` count was 1).

### Section 8 -- `tests/test_bf892_spawn_env_guard.py` (new, complete scanner)

```python
"""BF-892 (#1543): every subprocess launch under src/ states its environment on purpose.

A launch passes ``env=`` from an owner in ``probos.execution.command_env``:
``build_command_env(...)`` (the allowlist; for commands or code the model or an agent
wrote) or ``trusted_command_env()`` (the runtime's environment; for argv ProbOS fixes,
each listed in TRUSTED_ENV_SITES with its reason). A dict display may extend an owner
(``{**build_command_env(), "PYTHONPATH": p}``) and a local name may carry one. An
environment that arrives from elsewhere (a parameter, another function) is INDIRECT and
listed in INDIRECT_ENV_SITES. Anything else fails: no env, env=None, a None branch,
``**kwargs`` without env, os.environ used whole by any route, a launch API bound by
reference, or a launch API that cannot take an environment.

Limits (a static scan cannot see these, so they cannot pass silently through it either,
but nor are they checked): getattr(subprocess, "run"), importlib-loaded modules, and
launches inside third-party libraries (Playwright's driver, webbrowser).
"""

from __future__ import annotations

import ast
import os
import textwrap
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from probos.execution.command_env import trusted_command_env

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_OWNER = "probos.execution.command_env"
_ALLOWLIST_OWNER = f"{_OWNER}.build_command_env"
_TRUSTED_OWNER = f"{_OWNER}.trusted_command_env"
ALLOWLIST, TRUSTED, INDIRECT = "allowlist", "trusted", "indirect"
_FAIL_WHOLE_ENV = "fail: the runtime environment by another route; use trusted_command_env()"

_ENV_LAUNCHERS = frozenset({
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
    "asyncio.subprocess.create_subprocess_exec", "asyncio.subprocess.create_subprocess_shell",
})
_LOOP_LAUNCH_ATTRS = frozenset({"subprocess_exec", "subprocess_shell"})
_NO_ENV_LAUNCHERS = frozenset({
    "os.system", "os.popen", "os.startfile", "os.posix_spawn", "os.posix_spawnp",
    "subprocess.getoutput", "subprocess.getstatusoutput", "pty.spawn",
    "multiprocessing.Process", "multiprocessing.Pool", "concurrent.futures.ProcessPoolExecutor",
})
_NO_ENV_PREFIXES = ("os.exec", "os.spawn")
#: Launches found at 7301f647 (2026-10-14). The scan must reach at least these.
_KNOWN_LAUNCH_FLOOR = 39

TRUSTED_ENV_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("src/probos/__main__.py", "_ensure_ollama"): (1, "ollama serve: OLLAMA_* and GPU variables"),
    ("src/probos/__main__.py", "_check_nats"): (1, "nats-server, fixed argv"),
    ("src/probos/__main__.py", "_cmd_reset"): (2, "git add/commit in the Captain's repo during reset"),
    ("src/probos/agents/code_search.py", "CodeSearchAgent._search_rg"): (1, "rg; model text only as a bound --regexp/--glob value; RIPGREP_CONFIG_PATH"),
    ("src/probos/audio/tts/piper_backend.py", "PiperBackend.synthesize._run_sync"): (1, "piper; text on stdin"),
    ("src/probos/avatars/blender_renderer.py", "BlenderRenderer.render"): (1, "blender running ProbOS's own script"),
    ("src/probos/avatars/rhubarb_backend.py", "_convert_to_wav._run_sync"): (1, "ffmpeg, fixed argv"),
    ("src/probos/avatars/rhubarb_backend.py", "probe_version._probe_sync"): (1, "rhubarb --version"),
    ("src/probos/avatars/rhubarb_backend.py", "_run_rhubarb._run_sync"): (1, "rhubarb, fixed argv"),
    ("src/probos/cognitive/builder.py", "_run_git._sync_run"): (1, "git verbs ProbOS chooses; .git/ is not model-writable (_FORBIDDEN_PATHS)"),
    ("src/probos/cognitive/builder.py", "_is_dirty_working_tree"): (2, "git rev-parse/status"),
    ("src/probos/cognitive/dm/artifact_extractor.py", "_to_docx_libreoffice"): (1, "soffice convert; content is data (follow-up: narrow)"),
    ("src/probos/cognitive/referent_gate.py", "GitObjectResolver._resolve_sync"): (1, "git cat-file -e -- <token>"),
    ("src/probos/cognitive/scout.py", "ScoutAgent._search_github"): (1, "gh api needs GH_TOKEN or gh config"),
    ("src/probos/credential_store.py", "CredentialStore._resolve"): (1, "credential helper (gh auth token)"),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, "docker info: DOCKER_HOST"),
    ("src/probos/episodic_health.py", "check_episodic_health"): (1, "ProbOS's own probe module: PROBOS_* config"),
    ("src/probos/execution/authority.py", "_ManifestPreparer._repository_binding"): (3, "git with system/global config stripped"),
    ("src/probos/integrations/mcp_bridge/transport.py", "StdioTransport.start"): (1, "operator-approved MCP server (follow-up: narrow)"),
    ("src/probos/knowledge/records_store.py", "RecordsStore._git_sync"): (1, "git on the records repo"),
    ("src/probos/knowledge/store.py", "KnowledgeStore._git_run"): (1, "git on the knowledge repo"),
    ("src/probos/security/container_sandbox.py", "DockerContainerSandbox.run"): (1, "docker CLI on the host; the container gets only -e"),
    ("src/probos/worktree_manager.py", "WorktreeManager._run_git"): (1, "git worktree verbs"),
}
INDIRECT_ENV_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("src/probos/agents/red_team.py", "RedTeamAgent._run_verify_sync"): (2, "env parameter; its one caller passes build_command_env"),
    ("src/probos/execution/isolation.py", "SubprocessSandbox._run_sync_inner"): (1, "run_python sandbox: _build_env starts from SANDBOX_ENV_PASSTHROUGH"),
}


@dataclass(frozen=True)
class Launch:
    path: str
    line: int
    callee: str
    shape: str  # "direct" | "by-reference" | "bound"
    scope: str
    verdict: str

    def render(self) -> str:
        return f"{self.path}:{self.line} {self.callee} ({self.shape}, {self.scope}) -> {self.verdict}"


def _module_parts(rel_path: str) -> tuple[list[str], bool]:
    parts = list(Path(rel_path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    is_package = bool(parts) and parts[-1] == "__init__"
    return (parts[:-1] if is_package else parts), is_package


def _aliases(tree: ast.Module, rel_path: str) -> dict[str, str]:
    module, is_package = _module_parts(rel_path)
    package = module if is_package else module[:-1]
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    names[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                origin = ".".join([*base, node.module] if node.module else base)
            else:
                origin = node.module or ""
            for alias in node.names:
                names[alias.asname or alias.name] = f"{origin}.{alias.name}"
    return names


def _dotted(node: ast.AST, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def _launcher(node: ast.AST, aliases: dict[str, str]) -> tuple[str, bool] | None:
    """(callee, takes_env) when *node* names a launch API."""
    dotted = _dotted(node, aliases)
    if dotted is not None:
        if dotted in _ENV_LAUNCHERS:
            return dotted, True
        if dotted in _NO_ENV_LAUNCHERS or dotted.startswith(_NO_ENV_PREFIXES):
            return dotted, False
    if isinstance(node, ast.Attribute) and node.attr in _LOOP_LAUNCH_ATTRS:
        return f"<loop>.{node.attr}", True
    return None


def _reads_whole_environment(expr: ast.AST, aliases: dict[str, str]) -> bool:
    """True when *expr* uses os.environ whole (copy, spread, pass), not one .get()/[...] read."""
    parents = {id(child): node for node in ast.walk(expr) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(expr):
        if _dotted(node, aliases) != "os.environ":
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.Subscript) and parent.value is node:
            continue
        if isinstance(parent, ast.Attribute) and parent.attr == "get":
            continue
        return True
    return False


def _bindings(function: ast.AST, name: str) -> tuple[list[ast.AST | None], list[ast.AST]]:
    """(values bound to *name* in *function*'s own body, augmented values); None = unreadable binding."""
    values: list[ast.AST | None] = []
    augmented: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
                elif not isinstance(target, (ast.Subscript, ast.Attribute)) and any(
                    isinstance(n, ast.Name) and n.id == name for n in ast.walk(target)
                ):
                    values.append(None)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            if node.value is not None:
                values.append(node.value)
        elif isinstance(node, ast.NamedExpr) and node.target.id == name:
            values.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            augmented.append(node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and any(
            isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.target)
        ):
            values.append(None)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None and any(
            isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.optional_vars)
        ):
            values.append(None)
        stack.extend(ast.iter_child_nodes(node))
    return values, augmented


def _widest(verdicts: list[str]) -> str:
    if TRUSTED in verdicts:
        return TRUSTED
    return INDIRECT if INDIRECT in verdicts else ALLOWLIST


class _Scanner(ast.NodeVisitor):
    def __init__(self, tree: ast.Module, rel_path: str) -> None:
        self.path = rel_path
        self.aliases = _aliases(tree, rel_path)
        self.scope: list[str] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.launches: list[Launch] = []
        self._consumed: set[int] = set()

    def _enter(self, node: ast.AST, name: str, is_function: bool) -> None:
        self.scope.append(name)
        if is_function:
            self.functions.append(node)  # type: ignore[arg-type]
        self.generic_visit(node)
        if is_function:
            self.functions.pop()
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name, False)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name, True)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name, True)

    def visit_Call(self, node: ast.Call) -> None:
        direct = _launcher(node.func, self.aliases)
        if direct is not None:
            self._consumed.add(id(node.func))
            self._record(node, direct, "direct")
        else:
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                ref = _launcher(arg, self.aliases)
                if ref is not None:
                    self._consumed.add(id(arg))
                    self._record(node, ref, "by-reference")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._bound(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._bound(node)

    def _bound(self, node: ast.AST) -> None:
        if id(node) in self._consumed:
            return
        ref = _launcher(node, self.aliases)
        if ref is not None:
            self.launches.append(Launch(self.path, node.lineno, ref[0], "bound", ".".join(self.scope) or "<module>",
                                        "fail: a launch API bound by reference; call it with env="))

    def _record(self, call: ast.Call, launcher: tuple[str, bool], shape: str) -> None:
        callee, takes_env = launcher
        verdict = self._verdict(call) if takes_env else "fail: this launch API cannot be given an environment"
        self.launches.append(Launch(self.path, call.lineno, callee, shape, ".".join(self.scope) or "<module>", verdict))

    def _verdict(self, call: ast.Call) -> str:
        env = [kw.value for kw in call.keywords if kw.arg == "env"]
        if not env:
            if any(kw.arg is None for kw in call.keywords):
                return "fail: **kwargs without an explicit env="
            return "fail: no env="
        return self._classify(env[0], 0)

    def _classify(self, expr: ast.AST, depth: int) -> str:
        if depth > 6:
            return "fail: environment not resolvable"
        if isinstance(expr, ast.Constant) and expr.value is None:
            return "fail: env=None"
        if _reads_whole_environment(expr, self.aliases):
            return _FAIL_WHOLE_ENV
        if isinstance(expr, ast.Call):
            owner = _dotted(expr.func, self.aliases)
            if owner == _ALLOWLIST_OWNER:
                return ALLOWLIST
            if owner == _TRUSTED_OWNER:
                return TRUSTED
            return INDIRECT
        if isinstance(expr, ast.Dict):
            if not expr.keys or expr.keys[0] is not None:
                return "fail: a dict environment must start with **build_command_env(...) or **trusted_command_env()"
            base = self._classify(expr.values[0], depth + 1)
            if base in (ALLOWLIST, TRUSTED) or base.startswith("fail"):
                return base
            return "fail: a dict environment must start from a sanctioned owner"
        if isinstance(expr, ast.IfExp):
            branches = [self._classify(expr.body, depth + 1), self._classify(expr.orelse, depth + 1)]
            failed = [b for b in branches if b.startswith("fail")]
            return failed[0] if failed else _widest(branches)
        if isinstance(expr, ast.Name):
            return self._classify_name(expr.id, depth)
        return INDIRECT

    def _classify_name(self, name: str, depth: int) -> str:
        for function in reversed(self.functions):
            args = function.args
            params = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            params |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
            values, augmented = _bindings(function, name)
            if any(_reads_whole_environment(v, self.aliases) for v in augmented):
                return _FAIL_WHOLE_ENV
            if values:
                verdicts = [
                    self._classify(v, depth + 1) if v is not None else "fail: environment bound in a way the guard cannot read"
                    for v in values
                ]
                failed = [v for v in verdicts if v.startswith("fail")]
                return failed[0] if failed else _widest(verdicts)
            if name in params:
                return INDIRECT
        return INDIRECT


def _scan_source(source: str, rel_path: str) -> list[Launch]:
    tree = ast.parse(source)
    scanner = _Scanner(tree, rel_path)
    scanner.visit(tree)
    return scanner.launches


@cache
def _scan_tree() -> tuple[Launch, ...]:
    launches: list[Launch] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        launches.extend(_scan_source(path.read_text(encoding="utf-8-sig"), rel))
    return tuple(launches)
```

The test cases:

- **`test_every_launch_under_src_states_its_environment`**: `assert [l.render() for l in _scan_tree() if l.verdict.startswith("fail")] == []`
- **`test_inventory_matches_the_code[trusted|indirect]`** (parametrized over `(TRUSTED, TRUSTED_ENV_SITES)` and `(INDIRECT, INDIRECT_ENV_SITES)`): `dict(Counter((l.path, l.scope) for l in _scan_tree() if l.verdict == verdict)) == {site: count for site, (count, _) in inventory.items()}`
- **`test_scan_reaches_the_known_launches`**:
  - Premise: `len(_scan_tree()) >= _KNOWN_LAUNCH_FLOOR`.
  - The set of `(path, scope, shape, verdict)` contains `("src/probos/cognitive/swe_harness/tools.py", "RunCommandTool.invoke", "direct", ALLOWLIST)` (the aliased `_asyncio`) and `("src/probos/cognitive/scout.py", "ScoutAgent._search_github", "by-reference", TRUSTED)`.
- **`test_trusted_command_env_is_a_copy_of_the_runtime_environment`** (`monkeypatch.setenv("BF892_TRUSTED_PLAIN", "bf892-plain")`):
  - `env = trusted_command_env()`; assert `env.get(...) == "bf892-plain"`.
  - Set `env[...] = "changed"`; assert `os.environ[...] == "bf892-plain"`.
  - **Never** compare the whole dict, so a failure cannot print the environment.
- **`test_scanner_classifies_shape[<id>]`** (parametrized). Each case asserts `len(launches) == 1` (premise: the scanner sees exactly the planted launch), then the shape, then `verdict.startswith(expected)`:

| id | source (`textwrap.dedent`) | shape | expected |
|---|---|---|---|
| no-env | `import subprocess` / `subprocess.run(['x'])` | direct | `fail: no env=` |
| env-none | `… subprocess.run(['x'], env=None)` | direct | `fail: env=None` |
| kwargs-splat | `import subprocess` / `def f(**kw):` / `    subprocess.Popen(['x'], **kw)` | direct | `fail: **kwargs` |
| aliased-module | `import subprocess as sp` / `sp.Popen(['x'])` | direct | `fail: no env=` |
| from-import | `from subprocess import run` / `run(['x'])` | direct | `fail: no env=` |
| from-import-alias | `from subprocess import Popen as P` / `P(['x'])` | direct | `fail: no env=` |
| aliased-asyncio | `import asyncio as _a` / `async def f():` / `    await _a.create_subprocess_shell('x')` | direct | `fail: no env=` |
| asyncio-subprocess | `import asyncio` / `async def f():` / `    await asyncio.subprocess.create_subprocess_exec('x')` | direct | `fail: no env=` |
| loop-method | `async def f(loop, p):` / `    await loop.subprocess_exec(p, 'x')` | direct | `fail: no env=` |
| to-thread | `import asyncio, subprocess` / `async def f():` / `    await asyncio.to_thread(subprocess.run, ['x'])` | by-reference | `fail: no env=` |
| run-in-executor | `import subprocess` / `async def f(loop):` / `    await loop.run_in_executor(None, subprocess.run, ['x'])` | by-reference | `fail: no env=` |
| partial | `import functools, subprocess` / `functools.partial(subprocess.run, ['x'])` | by-reference | `fail: no env=` |
| bound | `import subprocess` / `launch = subprocess.run` | bound | `fail: a launch API bound` |
| os-system / os-popen / os-execv / os-spawnl / getoutput / multiprocessing | one call each | direct | `fail: this launch API cannot` |
| environ-copy | `env=os.environ.copy()` | direct | `fail: the runtime environment` |
| environ-dict | `env=dict(os.environ)` | direct | same |
| environ-spread | `env={**os.environ, 'A': 'b'}` | direct | same |
| environ-via-name | `def f():` / `    env = os.environ.copy()` / `    subprocess.run(['x'], env=env)` | direct | same |
| from-os-environ | `from os import environ` … `env=dict(environ)` | direct | same |
| none-branch | owner import; `def f(a):` / `    subprocess.run(['x'], env=build_command_env() if a else None)` | direct | `fail: env=None` |
| dict-without-owner | `env={'PATH': '/bin'}` | direct | `fail: a dict environment` |
| allowlist-inline | `from probos.execution.command_env import build_command_env` … `env=build_command_env()` | direct | `allowlist` |
| allowlist-extended | `env={**build_command_env(), 'PYTHONPATH': p}` | direct | `allowlist` |
| allowlist-name-item | `def f():` / `    env = build_command_env()` / `    env['X'] = os.environ.get('X', '')` / `    subprocess.run(['x'], env=env)` | direct | `allowlist` |
| trusted-by-reference | owner import; `async def f():` / `    await asyncio.to_thread(subprocess.run, ['x'], env=trusted_command_env())` | by-reference | `trusted` |
| relative-owner (rel_path `src/probos/execution/snippet.py`) | `from .command_env import build_command_env` … | direct | `allowlist` |
| parameter | `def f(env):` / `    subprocess.run(['x'], env=env)` | direct | `indirect` |
| lookalike-owner | `def build_command_env():` / `    return {}` / `subprocess.run(['x'], env=build_command_env())` | direct | `indirect` |

**Focused check (892b):**

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf892_spawn_env_guard.py tests/test_bf892_spawn_env.py tests/test_bf890_command_env.py tests/test_scout.py tests/test_credential_store.py tests/test_quality_hardening.py tests/test_ad1014_stdio_mcp_transport.py tests/test_bf745_mcp_credentials_survive_restart.py tests/test_ad1211_approval_fulfils_every_kind.py tests/test_ad1315_protected_execution_authority.py tests/test_ad1119_referent_gate.py tests/test_ad721b_1a_ffmpeg_conversion.py tests/test_ad721i_renderer.py tests/test_ad738_piper_tts.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_ad1025_path_anchoring.py tests/test_ad798_container_sandbox.py -q -n 0 -p no:randomly
```

---

## Slice 893 — end the whole tree on timeout

### Section 3.1 -- `src/probos/execution/process_tree.py` (new)

```python
"""BF-893 (#1544): the one owner of ending a spawned command's whole process tree.

A command started through a shell -- ``run_command`` in the native SWE harness,
``ShellCommandAgent``, the red team's re-run -- runs as the shell's child. Killing only
the shell on a timeout left the command running, so a caller told "timed out" could
still see its effects (a push, a write, a build).

POSIX: the shell starts a new session (``start_new_session=True``), so it and everything
it starts share one process group, and :meth:`ProcessTree.kill` sends ``SIGKILL`` to it.
Windows: the shell starts suspended (``CREATE_SUSPENDED``); :meth:`ProcessTree.attach`
puts it in a new job object and only then resumes it, so every process it starts is in
the job from its first instruction, and :meth:`ProcessTree.kill` ends the job
(``TerminateJobObject``), reaching even a descendant whose parent has exited.

Not covered: a descendant that leaves on purpose (``setsid`` or a double fork on POSIX;
work handed to a scheduler, service or COM server on either platform) outlives the
timeout, as before. Only a timeout kills: a command that finishes in time leaves its
background descendants running, as before (the job is not kill-on-close).
The job sets no breakaway-OK limit; a Windows descendant that asks to break away from it
(``CREATE_BREAKAWAY_FROM_JOB``) was observed to start normally and still be ended by a timeout.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import os
import signal
import sys
import types
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: ``CREATE_SUSPENDED`` from winbase.h; ``subprocess`` does not export it.
CREATE_SUSPENDED = 0x00000004
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SUSPEND_RESUME = 0x0800
#: The exit code ``subprocess.Popen.kill`` gives a process on Windows.
_KILLED_EXIT_CODE = 1


class SpawnedProcess(Protocol):
    """What :class:`ProcessTree` needs; ``subprocess.Popen`` and ``asyncio.subprocess.Process`` both fit."""

    @property
    def pid(self) -> int: ...

    def kill(self) -> None: ...


def process_tree_popen_kwargs(platform: str | None = None) -> dict[str, Any]:
    """Spawn keywords that make the child the root of a tree :class:`ProcessTree` can end.

    Pass them to ``subprocess.Popen`` or ``asyncio.create_subprocess_*`` and call
    :meth:`ProcessTree.attach` on the result at once: on Windows the child stays
    suspended until then.
    """
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        return {"creationflags": CREATE_SUSPENDED}
    return {"start_new_session": True}


def _kill_direct(proc: SpawnedProcess) -> None:
    try:
        proc.kill()
    except OSError:
        pass  # already gone (ProcessLookupError is an OSError)


@functools.lru_cache(maxsize=1)
def _win32() -> Any:
    """kernel32/ntdll entry points with explicit signatures (a 64-bit HANDLE must not truncate)."""
    if sys.platform != "win32":
        raise OSError("BF-893: job objects exist only on Windows")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS
    return types.SimpleNamespace(
        create_job=kernel32.CreateJobObjectW,
        open_process=kernel32.OpenProcess,
        assign=kernel32.AssignProcessToJobObject,
        terminate_job=kernel32.TerminateJobObject,
        close=kernel32.CloseHandle,
        resume=ntdll.NtResumeProcess,
    )


def _contain_suspended(proc: SpawnedProcess) -> int | None:
    """Put a suspended child in a new job, then resume it. The job handle, or None when no job could hold it."""
    api = _win32()
    handle = api.open_process(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, proc.pid)
    if not handle:
        error = ctypes.get_last_error()
        _kill_direct(proc)
        raise OSError(error, f"BF-893: could not open the spawned command (pid {proc.pid}) to start it; it was killed")
    try:
        job = api.create_job(None, None)
        if not job:
            logger.warning(
                "BF-893: no job object for pid %s (error %s); a timeout will end only the shell, not the command under it",
                proc.pid, ctypes.get_last_error(),
            )
        elif not api.assign(job, handle):
            logger.warning(
                "BF-893: could not place pid %s in a job object (error %s); a timeout will end only the shell, "
                "not the command under it", proc.pid, ctypes.get_last_error(),
            )
            api.close(job)
            job = None
        status = api.resume(handle)
        if status != 0:
            if job:
                api.terminate_job(job, _KILLED_EXIT_CODE)
                api.close(job)
            _kill_direct(proc)
            raise OSError(
                f"BF-893: could not start the spawned command (pid {proc.pid}, "
                f"NTSTATUS {status & 0xFFFFFFFF:#010x}); it was killed"
            )
        return int(job) if job else None
    finally:
        api.close(handle)


class ProcessTree:
    """Ends a spawned command and every process it started.

    Build it with :meth:`attach`. Built directly with neither a job nor a group it can
    end only the process itself -- the pre-BF-893 behaviour, used when the platform
    could not give a tree.
    """

    def __init__(self, proc: SpawnedProcess, *, job: int | None = None, group: int | None = None) -> None:
        self._proc = proc
        self._job = job
        self._group = group

    @classmethod
    def attach(cls, proc: SpawnedProcess) -> ProcessTree:
        """Own *proc*'s tree. Call it right after spawning with :func:`process_tree_popen_kwargs`.

        Raises ``OSError`` only on Windows, after killing the child, when the suspended
        child cannot be opened or resumed.
        """
        if sys.platform == "win32":
            return cls(proc, job=_contain_suspended(proc))
        return cls(proc, group=proc.pid)

    def kill(self) -> None:
        """End the whole tree. Never raises; a command that already exited is not an error."""
        if sys.platform == "win32":
            if self._job is not None:
                if _win32().terminate_job(self._job, _KILLED_EXIT_CODE):
                    return
                logger.warning(
                    "BF-893: could not end the job of pid %s (error %s); ending only the shell",
                    self._proc.pid, ctypes.get_last_error(),
                )
        elif self._group is not None:
            if self._group == os.getpgrp():
                logger.error(
                    "BF-893: refusing to signal the runtime's own process group %s; ending only pid %s",
                    self._group, self._proc.pid,
                )
            else:
                try:
                    os.killpg(self._group, signal.SIGKILL)
                    return
                except ProcessLookupError:
                    pass  # the group is gone: nothing of the tree is left
                except OSError as exc:
                    logger.warning(
                        "BF-893: could not signal process group %s (%s); ending only the shell", self._group, exc,
                    )
        _kill_direct(self._proc)

    def close(self) -> None:
        """Release the job handle. Ends nothing: only :meth:`kill` does."""
        if sys.platform == "win32" and self._job is not None:
            _win32().close(self._job)
        self._job = None

    def __enter__(self) -> ProcessTree:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: types.TracebackType | None) -> None:
        self.close()
```

### Section 3.2 -- `src/probos/cognitive/swe_harness/tools.py`

Import: after `from probos.execution.command_env import build_command_env` (:23), add `from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs`.

SEARCH:
```python
                # BF-890 (#1529): an allowlisted environment, not the runtime's.
                env=build_command_env(self._command_env_passthrough),
            )
            try:
                stdout_b, stderr_b = await _asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except _asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return ToolResult(error=f"run_command timed out after {timeout}s")
```
REPLACE:
```python
                # BF-890 (#1529): an allowlisted environment, not the runtime's.
                env=build_command_env(self._command_env_passthrough),
                # BF-893 (#1544): the command's whole tree can be ended on a timeout.
                **process_tree_popen_kwargs(),
            )
            tree = ProcessTree.attach(proc)
            try:
                stdout_b, stderr_b = await _asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except _asyncio.TimeoutError:
                tree.kill()
                return ToolResult(error=f"run_command timed out after {timeout}s")
            finally:
                tree.close()
```

### Section 3.3 -- `src/probos/agents/shell_command.py`

Import after :13: `from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs`.

Add `**process_tree_popen_kwargs(),` as the last keyword (after `env=env,`) of both `subprocess.Popen` calls (:223, :230).

SEARCH:
```python
            stdout_bytes, stderr_bytes = proc.communicate(
                timeout=self.DEFAULT_TIMEOUT,
            )
```
REPLACE:
```python
            with ProcessTree.attach(proc) as tree:
                try:
                    stdout_bytes, stderr_bytes = proc.communicate(
                        timeout=self.DEFAULT_TIMEOUT,
                    )
                except subprocess.TimeoutExpired:
                    # BF-893 (#1544): end the command's whole tree, not only the shell.
                    tree.kill()
                    proc.wait()
                    return {
                        "success": False,
                        "error": f"Command timed out after {self.DEFAULT_TIMEOUT}s",
                    }
```

SEARCH (delete the old outer handler):
```python
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return {
                "success": False,
                "error": f"Command timed out after {self.DEFAULT_TIMEOUT}s",
            }
        except Exception as e:
            return {"success": False, "error": repr(e)}
```
REPLACE:
```python
        except Exception as e:
            return {"success": False, "error": repr(e)}
```

### Section 3.4 -- `src/probos/agents/red_team.py`

Import after :15: the same `process_tree` import.

Add `**process_tree_popen_kwargs(),` to both Popen calls (:390, :394), after the existing keywords.

SEARCH:
```python
            stdout_bytes, _ = proc.communicate(timeout=5)
            stdout = stdout_bytes[:64 * 1024].decode("utf-8", errors="replace")
            return (proc.returncode, stdout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None
        except Exception:
```
REPLACE:
```python
            with ProcessTree.attach(proc) as tree:
                try:
                    stdout_bytes, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    # BF-893 (#1544): end the re-run's whole tree, not only the shell.
                    tree.kill()
                    return None
            stdout = stdout_bytes[:64 * 1024].decode("utf-8", errors="replace")
            return (proc.returncode, stdout)
        except Exception:
```

### Section 3.5 -- `tests/test_expansion_agents.py` (hidden pin)

Add `from probos.execution.process_tree import ProcessTree` and this fixture:

```python
@pytest.fixture
def direct_kill_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """BF-893: these tests hand the agents a MagicMock process, not a real child; a real
    ProcessTree would open the mock's pid on Windows. A tree with no job or group is the
    shape ProcessTree takes when the platform gives no tree."""
    monkeypatch.setattr(ProcessTree, "attach", classmethod(lambda cls, proc: cls(proc)))
```

Add `@pytest.mark.usefixtures("direct_kill_process_tree")` to `test_echo_hello`, `test_failing_command`, `test_nl_run_command`, `test_submit_run_command_with_consensus`, and the test whose mock starts at ~:751. Grep `patch("probos.agents.shell_command.subprocess.Popen"` to confirm there are exactly five.

### Section 3.6 -- `tests/test_bf890_run_command_env.py` (hidden pin)

SEARCH:
```python
async def _wait_out_the_orphan(marker: Path, *, seconds: float = 5.0) -> None:
    """Let the child a timed-out call left behind finish, while the event loop still runs.

    ``RunCommandTool`` kills the shell on a timeout, not the command under it, so
    the command keeps the output pipes open until it exits. Waiting for it here
    lets the pipes reach EOF and asyncio close the transport normally, instead of
    leaving it for a finalizer that runs after the loop is closed.
    """
```
REPLACE:
```python
async def _wait_out_the_orphan(marker: Path, *, seconds: float = 0.5) -> None:
    """Let the event loop see a timed-out call's pipes close before the test ends.

    BF-893 (#1544): ``RunCommandTool`` now ends the command's whole tree on a timeout,
    so no orphan holds the pipes open and the marker should never appear; this short
    wait only lets asyncio finish the transport inside the loop rather than in a
    finalizer after the loop closes. (Before BF-893 it waited up to 5 s for the orphan.)
    """
```

### Tests -- `tests/test_bf893_process_tree.py` (new)

Fixtures:
- `spawner(tmp_path)` writes `spawner.py`:
  ```python
  import pathlib, subprocess, sys
  marker, seconds = sys.argv[1], float(sys.argv[2])
  code = f"import pathlib, time; time.sleep({seconds}); pathlib.Path({marker!r}).write_text('done')"
  child = subprocess.Popen([sys.executable, "-c", code])
  pathlib.Path(marker + ".started").write_text(str(child.pid))
  child.wait()
  ```
- Command line: `f'"{sys.executable}" "{spawner}" "{marker}" {seconds}'`, prefixed with `& ` when the shell is PowerShell. PowerShell is the shell for ShellCommandAgent and the red team on win32; `run_command` uses cmd.exe on win32; all three use `/bin/sh` on POSIX.
- `_appears(path, within)` polls every 0.1 s.
- Every test has `@pytest.mark.timeout(90)` as its watchdog. Children write only markers.

The test cases:

1. **`test_premise_killing_only_the_shell_leaves_the_grandchild`**:
   - Spawn the platform shell (`powershell -NoProfile -Command` on win32, `shell=True` on POSIX) with `env=build_command_env()` and **no** tree kwargs.
   - Premise: `.started` appears within 20 s.
   - `proc.kill()`; then assert the marker **does** appear within S+8 (S=3).
   - This proves the defect is observable on this platform, so the "never appears" checks below are not vacuous. On ubuntu it must hold even when dash execs the spawner, because the grandchild is then orphaned to init.
2. **`test_process_tree_kill_ends_the_grandchild`**:
   - Same spawn with `**process_tree_popen_kwargs()`, then `tree = ProcessTree.attach(proc)`.
   - Wait for `.started`, then `tree.kill()`, `proc.wait(10)`.
   - Assert the marker does not appear within S+3; `tree.close()`.
3. **`test_kill_after_the_command_exited_is_not_an_error`**: `Popen([sys.executable, "-c", "pass"], **kwargs)`, then `with ProcessTree.attach(proc) as tree: proc.wait(30); tree.kill(); tree.kill()`. Assert `proc.returncode == 0` and that nothing raised.
4. **`test_direct_tree_kills_only_the_process`**:
   - A fake process with `pid=4242` and `kill()` counting calls: `ProcessTree(fake).kill()` gives count 1.
   - A fake whose `kill()` raises `ProcessLookupError` is swallowed.
5. **`test_windows_child_does_not_run_before_attach`** (skip unless win32):
   - Control: `Popen([py, "-c", write marker])` without kwargs, and the marker appears within 10 s.
   - Test: with kwargs, after 1.5 s there is no marker; then `attach`, and the marker appears within 10 s.
   - Kills M18.
6. **`test_posix_child_leads_its_own_group`** (skip on win32):
   - With kwargs: `os.getpgid(proc.pid) == proc.pid`.
   - Control without kwargs: `os.getpgid(proc.pid) == os.getpgrp()`.
   - Kill and reap both.
   - Kills M17.
7. **`test_kill_never_signals_the_runtimes_own_group`** (skip on win32):
   - `monkeypatch.setattr("probos.execution.process_tree.os.killpg", recorder)`.
   - `ProcessTree(fake, group=os.getpgrp()).kill()`.
   - Assert the recorder was never called and `fake.kill` was called.
   - Kills M20.
8. **`test_run_command_timeout_ends_the_grandchild`**:
   - Control: `invoke({"command": cmd(S=1), "timeout": 60})` succeeds with `exit_code == 0` and the marker appears within 3 s.
   - Test: `invoke(cmd(S=7), timeout 4.0)`. Assert `result.error == "run_command timed out after 4.0s"`.
   - Premise: `.started` exists (the grandchild existed when the timeout fired).
   - Assert the marker is absent now and does not appear within 10 s.
   - Kills M14.
9. **`test_shell_agent_timeout_ends_the_grandchild`**:
   - `agent = ShellCommandAgent(pool="shell")`; `agent.DEFAULT_TIMEOUT = 4.0` for the test (control: 60).
   - Use `await agent._run_command(cmd)` (this bypasses `decide()`, which refuses a leading `&`).
   - Assert `{"success": False, "error": "Command timed out after 4.0s"}`, the `.started` premise, and no marker within 10 s. The thread's own `communicate` timeout fires right after the outer `wait_for`, so poll for the full window.
   - Kills M15.
10. **`test_red_team_rerun_timeout_ends_the_grandchild`**:
    - `await asyncio.to_thread(RedTeamAgent._run_verify_sync, cmd, build_command_env())`.
    - Control S=1 returns `(0, <str>)` and the marker appears.
    - Test S=8 returns `None`; check the `.started` premise; the marker does not appear within 11 s.
    - Kills M16.
11. **`test_in_time_results_are_unchanged`**:
    - `run_command` printing `bf893-ok` returns `set(result.output) == {"stdout", "stderr", "exit_code"}` with exit 0.
    - Shell agent: `set(r) == {"success", "data"}` and `set(r["data"]) == {"stdout", "stderr", "exit_code", "command"}`.
    - Red team returns `(0, str)`.
    - Kills M19 (a never-resumed child times out instead).

**What must hold on ubuntu CI (POSIX was not measured):**
- `setsid` succeeds in runners.
- The premise in test 1 holds whether or not dash execs.
- `killpg` reaches the spawner and its grandchild.
- asyncio's child watcher (3.12) can reap the shell independently of `kill()` while a caller is still awaiting the pipes, so "the kill runs before any `wait`, so the pid cannot be reused" is not claimed. What CI must show: the group is owned (`getpgid(proc.pid) == proc.pid`), an already-exited command is not an error, and a grandchild is ended. Reuse of the process-group id after the group is empty is a follow-up (the group id is kept as a bare number).
- The timing margins (`.started` premise, S−timeout ≥ 3 s) tolerate a slow runner. A premise failure is a loud fail, never a vacuous pass.

**Focused check (893):**

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf893_process_tree.py tests/test_bf890_run_command_env.py tests/test_bf890_shell_agent_env.py tests/test_bf890_command_env.py tests/test_expansion_agents.py tests/test_ad544_native_tools.py tests/test_bf892_spawn_env_guard.py -q -n 0 -p no:randomly
```

---

## Mutation table (single-line anchors; run each slice's rows on its frozen candidate; one campaign)

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| M1 | cognitive/builder.py | `env=run_env,` | `env=None,` | test_run_tests_hides_the_plant_and_keeps_pythonpath |
| M2 | cognitive/builder.py | `env=targeted_env,` | `env=None,` | test_run_targeted_tests_hides_the_plant |
| M3 | security/container_sandbox.py | `env = {**build_command_env(), **request.env}` | `env = None` | test_inprocess_container_hides_the_plant_and_keeps_request_env |
| M4 | cognitive/dependency_resolver.py | `[sys.executable, "-m", "pip", "install", package_name], env=install_env,` | `[sys.executable, "-m", "pip", "install", package_name],` | test_dependency_install_hides_the_plant_on_every_method |
| M5 | cognitive/dependency_resolver.py | `[uv_path, "pip", "install", package_name], env=install_env,` | `[uv_path, "pip", "install", package_name],` | same |
| M6 | cognitive/dependency_resolver.py | `[uv_path, "add", package_name], env=install_env,` | `[uv_path, "add", package_name],` | same |
| M7 | cognitive/dependency_resolver.py | `install_env = build_command_env(("VIRTUAL_ENV",))` | `install_env = build_command_env()` | test_dependency_install_keeps_virtual_env |
| M8 | worktree_manager.py | `env=trusted_command_env(),` | `env=None,` | test_every_launch_under_src_states_its_environment |
| M9 | integrations/mcp_bridge/transport.py | `env = {**trusted_command_env(), **self._env}` | `env = {**os.environ, **self._env}` | same (static; the module would NameError at runtime) |
| M10 | execution/authority.py | `git_environment = trusted_command_env()` | `git_environment = os.environ.copy()` | same |
| M11 | execution/command_env.py | `return dict(os.environ)` | `return os.environ` | test_trusted_command_env_is_a_copy_of_the_runtime_environment |
| M12 | tests/test_bf892_spawn_env_guard.py | `names[alias.asname] = alias.name` | `pass` | test_scanner_classifies_shape[aliased-module], test_scan_reaches_the_known_launches |
| M13 | tests/test_bf892_spawn_env_guard.py | `ref = _launcher(arg, self.aliases)` | `ref = None` | [to-thread], [run-in-executor], [partial], test_scan_reaches_the_known_launches |
| M14 | cognitive/swe_harness/tools.py | `tree.kill()` | `proc.kill()` | test_run_command_timeout_ends_the_grandchild |
| M15 | agents/shell_command.py | `tree.kill()` | `proc.kill()` | test_shell_agent_timeout_ends_the_grandchild |
| M16 | agents/red_team.py | `tree.kill()` | `proc.kill()` | test_red_team_rerun_timeout_ends_the_grandchild |
| M17 | execution/process_tree.py | `return {"start_new_session": True}` | `return {}` | test_posix_child_leads_its_own_group (**POSIX/CI only; INERT on Windows**) |
| M18 | execution/process_tree.py | `return {"creationflags": CREATE_SUSPENDED}` | `return {}` | test_windows_child_does_not_run_before_attach (**Windows only**) |
| M19 | execution/process_tree.py | `status = api.resume(handle)` | `status = 0` | test_in_time_results_are_unchanged (**Windows**) |
| M20 | execution/process_tree.py | `if self._group == os.getpgrp():` | `if False:` | test_kill_never_signals_the_runtimes_own_group (**POSIX**) |
| M21 | execution/process_tree.py | `elif not api.assign(job, handle):` | `elif False:` | test_process_tree_kill_ends_the_grandchild (**Windows**) |

Run the unmutated baseline first. A platform-only mutant counts as INERT on the other platform, not as killed. M17 and M20 are settled on CI and recorded as such.

---

## Builder briefs (3 milestones; each slice gets a focused check, Diff Review and local commit)

- **Milestone 1, 892a** (`fix(security): BF-892 slice a -- model-authored children start from the command allowlist`): Sections 1-3 plus `tests/test_bf892_spawn_env.py`. Do not touch any other launch. Remove `import os` from container_sandbox.
- **Milestone 2, 892b** (`fix(security): BF-892 slice b -- every launch states its environment; spawn-env guard`): Sections 4-8.
  - Copy the scanner verbatim.
  - If the guard reports a scope string that differs from the inventory (for example a nested-def name), fix the inventory key, not the scanner, and say so in the report.
  - Remove `import os` from transport.
- **Milestone 3, 893** (`fix(execution): BF-893 -- a timeout ends the command's whole process tree`): Sections 3.1-3.6 plus `tests/test_bf893_process_tree.py`. Run on Windows. Report CI as pending for the POSIX-only tests.

Tracker updates (in milestone 3's commit or a docs commit inside the batch):
- `PROGRESS.md` and the `docs/development/roadmap.md` Bug Tracker rows for BF-892 and BF-893: closed, with commits.
- `DECISIONS.md`: one short entry. On Windows a command is started suspended, put in a job object, then resumed (`NtResumeProcess`). On POSIX it starts a new session and is ended with `killpg`. The full environment goes only through `trusted_command_env()`, with every caller listed in the guard's inventory.

## Diff Reviewer brief hint (one per slice; properties to verify, not attacks)

> **892a.** Claim: pytest runs over model tests (`_run_tests`, `_run_targeted_tests`), `InProcessContainerSandbox.run` and the three dependency installs start from `build_command_env`. PYTHONPATH (same order as before) and `request.env` are explicit extensions, plus VIRTUAL_ENV for installs. Verify that no `os.environ` copy or spread remains at these sites. Verify that `request.env` is still applied last and that what `InProcessContainerSandbox` refuses is unchanged. Verify that the `getsource` checks in `test_quality_hardening` (no `text=True`) still hold. Consumers that must accept the change: `SoftwareEngineerAgent.execute_approved_build` (the result tuple is unchanged), `test_builder_agent` (its `subprocess.run` mocks take any kwargs), `test_ad798_container_sandbox`, `test_dependency_resolver`.
> **892b.** Claim: all 39 launches pass `env=` from `build_command_env`/`trusted_command_env`, or are inventoried INDIRECT (red_team parameter, isolation `_build_env`). Behaviour is identical for trusted sites: `trusted_command_env()` equals the old inherited environment, including transport's old `None`. Verify that each inserted keyword sits inside the right call and not in a sibling call; that `asyncio.to_thread` forwards `env` in scout; that no `import os` is left unused (transport) or wrongly removed (authority still uses `os.devnull`); that the inventory counts match; and that the scanner's snippet premises each find exactly one launch. Consumers: the MCP stdio servers (`test_ad1014`, `test_bf745`, `test_ad1211`), `test_ad1315` (authority git), `test_scout`, `test_credential_store`, the avatar/tts tests, and `test_ad1025`.
> **893.** Claim: on timeout the three sites end the whole tree (job object on Windows, process group on POSIX). In-time results, timeouts and error strings are unchanged. Verify the following:
> - Every edited Popen or `create_subprocess_shell` keeps an explicit `env=` before `**process_tree_popen_kwargs()` (the BF-890 detector `test_bf890_command_env.py:468` depends on it).
> - `ProcessTree.attach` runs immediately after spawn on every path.
> - `close()` runs on every path (a `finally` or `with`).
> - `kill()` cannot raise.
> - A failed resume kills the child and maps to the site's existing error shape.
> - No kill-on-close flag is set.
> - The POSIX branch can never signal `os.getpgrp()`.
>
> Consumers: `test_bf890_run_command_env` (with the updated `_wait_out_the_orphan`), `test_bf890_shell_agent_env`, `test_expansion_agents` (with the new fixture), `test_ad544_native_tools`, `RedTeamAgent._verify_run_command` (it still returns "timed out" or "Verification error"). This is a security change: also run the Copilot GPT Diff Reviewer.

## Acceptance criteria

- **BF-892 (#1543):**
  - A planted variable is invisible to `_run_tests` and `_run_targeted_tests` model tests, to the in-process container child, and to all three dependency-install methods. Each test first proves an inheriting child sees it (slice 892a).
  - The guard exists. It fails on a launch with no `env=`, on `env=None`, on a `None` branch, on `**kwargs` alone, on any whole use of `os.environ`, on a bound reference and on a launch API that cannot take an environment. It names file and line, passes on the batch tree, and both inventories match exactly (slice 892b).
  - Mutants M1-M7 are killed (the three sites), and M8-M13 are killed.
- **BF-893 (#1544):**
  - After a reported timeout at each of the three sites, a real grandchild's marker never appears, and each test first shows its control writes the marker.
  - In-time results are unchanged.
  - Killing an exited command is not an error.
  - POSIX tests run on ubuntu CI.
  - M14-M16 are killed, and M17-M21 are killed on their platform.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do not build

- No command policy (AD-1328, #1530).
- No OS sandboxing or resource limits.
- No new allowlist, and no `execution.command_env_passthrough` plumbing into the builder, container or resolver.
- No change to `DockerContainerSandbox` behaviour; it only states `env=`.
- No change to what `InProcessContainerSandbox` refuses.
- No change to run_python's sandbox or `isolation._kill`.
- No change to timeouts, output caps or result shapes.
- No kill-on-close and no `BREAKAWAY_OK`.
- No `psutil` and no `taskkill`.
- No cancellation-path kill.

## Orchestrator regeneration commands

```
git rev-parse HEAD                                   # consult was against 7301f647
d:/ProbOS/.venv/Scripts/python.exe logs/architect/probe_f44.py   # with PYTHONPATH set to the worktree's src; after 892a expect "REPRODUCED at: none" (exit 1)
d:/ProbOS/.venv/Scripts/python.exe logs/architect/probe_f45.py   # after 893 expect "marker appeared afterwards: False" at all three sites
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf892_spawn_env_guard.py -q -n 0 -p no:randomly   # supersedes scan_spawns.py, which misses import aliases
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf892-893
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf892-893 --receipt logs/gates/bf892-893.receipt.json
```

## Prior art and blind spots

**Considered:**
- **Starting suspended, adding to a job, then resuming** is the documented way to close the job-assignment race. Rust's `windows-spawn` and `processkit` describe exactly this race ([processkit](https://docs.rs/crate/processkit/2.2.1), [windows-spawn](https://docs.rs/windows-spawn), [conpty-oxide job.rs](https://docs.rs/crate/conpty-oxide/0.1.1/source/src/core/job.rs)). Adopted.
- **`NtResumeProcess`** is what psutil has used since 5.6.0 ([psutil 5.6.0](https://psutil.readthedocs.io/latest/blog/2019/announcing-560.html), [NtDoc](https://ntdoc.m417z.com/ntresumeprocess)). NtDoc's race warning is about processes with many threads; a fresh suspended child has one. Adopted.
- **`PROC_THREAD_ATTRIBUTE_JOB_LIST`** is the cleaner API but cannot be reached through `subprocess.STARTUPINFO`. Rejected.
- **`taskkill /T`** and **psutil**. Rejected; reasons are in (d) and (5).
- **In-repo precedent:** `isolation._platform_kwargs` and `_kill` (:1076-1120) already use the POSIX session and `killpg`. The new helper follows them.

**Follow-ups** (not in scope). Reach is "ordinary" when normal use triggers it, "injected" when it needs attacker-supplied content.

1. Pass `execution.command_env_passthrough` to the builder, the container sandbox and the dependency resolver. Today a proxy, index or CA set only in the runtime's environment no longer reaches pip, uv or model tests. *Ordinary.*
2. Timeouts that still kill only the direct child: `subprocess.run(timeout=)` in `_run_tests`, `InProcessContainerSandbox`, piper, rhubarb, referent_gate and episodic_health. Model tests that use xdist workers would orphan them. They could adopt `ProcessTree`. *Ordinary.*
3. run_python's Windows `_kill`, which still ends only the child (#1417 is closed, the code comment remains). Could adopt `ProcessTree`. *Ordinary.*
4. A cancelled `run_command` turn (`CancelledError`) leaves the tree running. *Ordinary.*
5. MCP stdio servers, which are third-party code, still get the full environment; it is now explicit. *Ordinary.*
6. soffice converts model-authored documents with the full environment. *Injected:* needs a macro or exploit path.
7. Docker `-e k=v` exposes `request.env` values in the host process listing. *Ordinary, local.*
8. Launches inside libraries (the Playwright driver, `webbrowser`) inherit the environment and are outside a static guard. *Ordinary.*
9. `logs/architect/scan_spawns.py` misses import aliases; it is superseded by the guard and should not be cited again.

Sources:
- [processkit 2.2.1](https://docs.rs/crate/processkit/2.2.1)
- [windows-spawn](https://docs.rs/windows-spawn)
- [conpty-oxide job.rs](https://docs.rs/crate/conpty-oxide/0.1.1/source/src/core/job.rs)
- [psutil 5.6.0 announcement](https://psutil.readthedocs.io/latest/blog/2019/announcing-560.html)
- [NtResumeProcess (NtDoc)](https://ntdoc.m417z.com/ntresumeprocess)

No agent-memory note was written.
