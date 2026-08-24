"""AD-994: CodeRunnerAgent — Tier-1 isolated Python execution for crew agents.

Gives crew agents the GitHub Copilot / Claude Code capability — *create and run a
Python script, installing libraries as needed* — under constraints that include,
but are not limited to:

* **NOT consensus-gated, despite the descriptors.** Both intents set
  ``requires_consensus=True``, and that does not authorize anything: the runtime
  broadcasts (this agent executes, below) and evaluates quorum on the results
  afterwards, with no rollback. The intents that DO get a real gate have a
  proposal/commit pair behind a dedicated runtime method -- ``write_file`` via
  ``submit_write_with_consensus`` / ``FileWriterAgent.commit_write``, and
  similarly MCP invocation and device actuation. This agent has no commit phase.
  ``run_command`` does not either, so the "exactly like ``run_command``" this
  line used to claim was accidentally true. See BF-779.
* **No dedicated execution audit on THIS path.** The agentic
  ``CodeExecutionTool`` ATTEMPTS a per-execution ``code_execution`` record when
  ``security_infra.audit_enabled`` is on (AD-1247). This mesh path attempts
  nothing. What it writes is generic event-log rows via ``runtime`` --
  ``intent_broadcast`` and ``intent_resolved`` on the decomposed-plan route,
  ``quorum_evaluated`` only when the plan's model-chosen ``use_consensus`` was
  true (it defaults false, BF-779), and nothing at all on the federation MCP
  route, which broadcasts straight to the bus. None of those rows carries the
  submitted source or its execution output. BF-787 tracks giving this path the
  same record.
* **Default OFF.** Inert unless ``config.execution.enabled`` is set by the
  operator. Package install is separately gated (``allow_package_install``).
* **Isolated (Tier 1).** Runs through the AD-993 ``SubprocessSandbox``:
  subprocess isolation, a timeout trigger that does not guarantee the call
  returns by the deadline, output caps, and memory bounds that are POSIX-only
  and best-effort. Tier 1 is process-isolation + confinement-by-convention --
  not kernel containment (that is the Tier-2 AD-995 escalation).

  ``allow_network=False`` is **not** a network block. It sets a discard-port
  proxy, which deters libraries that honour ``*_proxy`` (requests, urllib) and
  which a raw socket walks straight past -- verified by execution. Hard network
  isolation is Tier 2.

  The working folder is **not** ephemeral by default: ``persistent_workspaces``
  defaults True and ``_resolve_workdir`` keeps a per-owner folder across runs,
  ``.venv`` included. Only the ephemeral branch reaps.

Two intents:

* ``run_python`` -- write + execute Python source. Optional ``packages`` are
  installed into the owner's workspace venv first ("install libraries as
  needed"), then the script runs in it. That venv is REUSED across runs under
  the default ``persistent_workspaces``, so installed packages persist; only the
  ephemeral branch gives a fresh one. No packages -> runs in the host
  interpreter, no venv.
* ``install_package`` -- validate that a package set installs cleanly (a
  standalone availability probe). Same machinery, no script run.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from probos.execution.isolation import (
    ExecutionRequest,
    SubprocessSandbox,
    remove_workdir_off_loop,
)
from probos.execution.workspace import WorkspaceManager
from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


def _venv_python(venv_dir: Path) -> Path:
    """Path to the interpreter inside a created venv (platform-specific)."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


class CodeRunnerAgent(BaseAgent):
    """Execute Python (and install its libraries) under Tier-1 isolation.

    HIGH-RISK: arbitrary code execution. Default-OFF + sandboxed, and NOT
    quorum-approved despite ``requires_consensus=True`` -- see the module
    docstring and BF-779. The workspace is persistent by default, so neither
    the folder nor its venv is ephemeral. Capabilities: run_python,
    install_package.
    """

    agent_type: str = "code_runner"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="run_python",
            detail="Create and run a Python script (optionally installing libraries) to perform a task",
        ),
        CapabilityDescriptor(
            can="install_package",
            detail="Validate that Python packages install cleanly (availability probe)",
        ),
    ]
    initial_confidence: float = 0.7
    intent_descriptors = [
        IntentDescriptor(
            name="run_python",
            params={
                "code": "<python_source>",
                "packages": "<optional list[str] of pip packages>",
                "timeout": "<optional seconds>",
            },
            description="Create and run a Python script in an isolated working folder; optionally pip-install libraries first. For real computation/automation, NOT shell workarounds.",
            # No usage_hint: this is a consensus/WRITE intent, so it must NOT
            # appear in the read-only [MESH ...] do-and-report affordance block
            # ("these reads change nothing"). The decomposer learns it from
            # `description` and routes it through the plan -> consensus path.
            requires_consensus=True,
            requires_reflect=True,
        ),
        IntentDescriptor(
            name="install_package",
            params={"packages": "<list[str] of pip packages>"},
            description="Validate that Python packages install cleanly into an isolated venv.",
            requires_consensus=True,
            requires_reflect=True,
        ),
    ]

    _handled_intents = {"run_python", "install_package"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None
        plan = await self.decide(observation)
        if plan is None:
            return None
        result = await self.act(plan)
        report = await self.report(result)
        success = report.get("success", False)
        self.update_confidence(success)
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent", "") not in self._handled_intents:
            return None
        return {"intent": intent.get("intent", ""), "params": intent.get("params", {})}

    async def decide(self, observation: Any) -> Any:
        cfg = self._execution_config()
        if cfg is None or not getattr(cfg, "enabled", False):
            return {"action": "disabled"}
        intent = observation["intent"]
        params = observation["params"]
        if intent == "run_python":
            code = params.get("code")
            if not code or not str(code).strip():
                return {"action": "error", "error": "No code provided"}
            return {
                "action": "run_python",
                "code": str(code),
                "packages": self._clean_packages(params.get("packages")),
                "timeout": params.get("timeout"),
                "owner": self._resolve_owner(params),
            }
        if intent == "install_package":
            packages = self._clean_packages(params.get("packages"))
            if not packages:
                return {"action": "error", "error": "No packages specified"}
            return {"action": "install_package", "packages": packages, "owner": self._resolve_owner(params)}
        return {"action": "error", "error": f"Unhandled intent: {intent}"}

    async def act(self, plan: Any) -> Any:
        action = plan.get("action")
        if action == "disabled":
            return {
                "success": False,
                "error": "Code execution is disabled (set config.execution.enabled).",
            }
        if action == "error":
            return {"success": False, "error": plan["error"]}
        if action == "run_python":
            return await self._run_python(plan)
        if action == "install_package":
            return await self._install_package(plan["packages"], plan["owner"])
        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------

    async def _run_python(self, plan: dict) -> dict[str, Any]:
        cfg = self._execution_config()
        sandbox = SubprocessSandbox(scratch_root=cfg.scratch_dir)
        owner = plan["owner"]
        workdir, persistent = self._resolve_workdir(cfg, owner)
        packages = plan["packages"]
        timeout = self._resolve_timeout(plan.get("timeout"), cfg.timeout_seconds)
        py_exe: str | None = None
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            if packages:
                if not getattr(cfg, "allow_package_install", False):
                    return {
                        "success": False,
                        "error": "Package install disabled (set config.execution.allow_package_install).",
                    }
                prep = await self._prepare_venv(sandbox, self._venv_dir(cfg, owner, workdir, persistent), packages, cfg)
                if not prep["success"]:
                    return prep
                py_exe = prep["python"]

            res = await sandbox.run(ExecutionRequest(
                code=plan["code"],
                workdir=workdir,
                timeout_seconds=timeout,
                max_output_bytes=cfg.max_output_bytes,
                max_memory_mb=cfg.max_memory_mb,
                allow_network=False,
                python_executable=py_exe,
            ))
            return {
                "success": res.success,
                "data": {
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "exit_code": res.exit_code,
                    "timed_out": res.timed_out,
                    "duration_ms": res.duration_ms,
                    "tier": res.tier,
                    "installed": packages,
                    "workspace": str(workdir),
                    "owner": owner,
                    "persistent": persistent,
                },
                "error": res.error or None,
            }
        finally:
            if not persistent:
                await self._reap(workdir)

    async def _install_package(self, packages: list[str], owner: str) -> dict[str, Any]:
        cfg = self._execution_config()
        if not getattr(cfg, "allow_package_install", False):
            return {
                "success": False,
                "error": "Package install disabled (set config.execution.allow_package_install).",
            }
        sandbox = SubprocessSandbox(scratch_root=cfg.scratch_dir)
        workdir, persistent = self._resolve_workdir(cfg, owner)
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            prep = await self._prepare_venv(sandbox, self._venv_dir(cfg, owner, workdir, persistent), packages, cfg)
            if not prep["success"]:
                return prep
            return {
                "success": True,
                "data": {
                    "installed": packages,
                    "stdout": prep.get("stdout", ""),
                    "workspace": str(workdir),
                    "owner": owner,
                    "persistent": persistent,
                },
            }
        finally:
            if not persistent:
                await self._reap(workdir)

    async def _prepare_venv(
        self, sandbox: SubprocessSandbox, venv_dir: Path, packages: list[str], cfg: Any,
    ) -> dict[str, Any]:
        """Ensure a venv exists at ``venv_dir`` and pip-install ``packages``.

        Both steps run through the Tier-1 sandbox (bounded + governed). The venv
        is **reused** when it already exists (persistent workspace) — pip install
        is idempotent, so already-satisfied packages are fast no-ops, and the
        crew don't re-download numpy every run. Returns ``{success, python}`` on
        success, or ``{success: False, error}``.
        """
        py = _venv_python(venv_dir)
        # 1. Create the venv if it isn't already there (no network needed).
        if not py.exists():
            create = await sandbox.run(ExecutionRequest(
                argv=[sys.executable, "-m", "venv", str(venv_dir)],
                workdir=venv_dir.parent,
                timeout_seconds=cfg.install_timeout_seconds,
                max_output_bytes=cfg.max_output_bytes,
                allow_network=False,
            ))
            if not create.success:
                return {"success": False, "error": f"venv creation failed: {create.stderr or create.error}"}
        # 2. pip install (network ON, scoped index url). Tier 1 cannot scope the
        #    network to PyPI only -- that is a Tier-2 guarantee. The package
        #    names are surfaced in the intent, but nothing votes on them before
        #    this runs: the quorum this comment used to invoke is evaluated
        #    after the fact (BF-779).
        install = await sandbox.run(ExecutionRequest(
            argv=[
                str(py), "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input",
                "--index-url", cfg.pip_index_url, *packages,
            ],
            workdir=venv_dir.parent,
            timeout_seconds=cfg.install_timeout_seconds,
            max_output_bytes=cfg.max_output_bytes,
            allow_network=True,
        ))
        if not install.success:
            return {"success": False, "error": f"pip install failed: {install.stderr or install.error}"}
        return {"success": True, "python": str(py), "stdout": install.stdout}

    # ------------------------------------------------------------------

    def _execution_config(self) -> Any:
        return getattr(getattr(self._runtime, "config", None), "execution", None)

    def _resolve_owner(self, params: dict) -> str:
        """The workspace owner key for this execution.

        An explicit ``workspace_owner`` in params (a delegating crew agent's
        key) wins; otherwise the code-runner's own key. Sanitized so it is
        always a safe single folder name (the WorkspaceManager guarantees this).
        """
        mgr = self._workspace_manager()
        explicit = params.get("workspace_owner")
        if explicit:
            return mgr.sanitize(str(explicit))
        return mgr.key_for_agent(self)

    def _workspace_manager(self) -> WorkspaceManager:
        cfg = self._execution_config()
        root = getattr(cfg, "workspace_root", "data/execution/workspaces")
        return WorkspaceManager(root)

    def _resolve_workdir(self, cfg: Any, owner: str) -> tuple[Path, bool]:
        """Return ``(workdir, persistent)`` for an execution.

        Persistent (default): the owner's stable folder under workspace_root —
        work products survive + are visible. Ephemeral: a fresh uuid scratch
        under scratch_dir that the caller reaps (the original AD-993 behavior).
        """
        if getattr(cfg, "persistent_workspaces", True):
            return self._workspace_manager().resolve(owner, create=True), True
        return Path(cfg.scratch_dir) / uuid.uuid4().hex, False

    def _venv_dir(self, cfg: Any, owner: str, workdir: Path, persistent: bool) -> Path:
        """Where the per-execution venv lives: reused ``<workspace>/.venv`` when
        persistent, throwaway ``<scratch>/venv`` when ephemeral."""
        if persistent:
            return self._workspace_manager().venv_dir(owner)
        return workdir / "venv"

    @staticmethod
    def _clean_packages(raw: Any) -> list[str]:
        """Sanitize the package list: strings only, no option-injection (a token
        starting with ``-`` could smuggle a pip flag like ``--index-url``)."""
        if not isinstance(raw, (list, tuple)):
            return []
        out: list[str] = []
        for item in raw:
            s = str(item).strip()
            if s and not s.startswith("-") and len(s) <= 200:
                out.append(s)
        return out

    @staticmethod
    def _resolve_timeout(requested: Any, default: float) -> float:
        try:
            t = float(requested) if requested is not None else float(default)
        except (TypeError, ValueError):
            t = float(default)
        return max(1.0, min(t, 300.0))

    @staticmethod
    async def _reap(path: Path) -> None:
        """Remove a run's scratch dir, retrying while something still holds it.

        BF-840: this was a one-shot ``shutil.rmtree(path, ignore_errors=True)``,
        which on Windows cannot remove a directory a live child still holds and
        reports nothing when it fails. Measured: with a child holding a file
        under ``path``, the one-shot form left the directory on disk and raised
        no exception -- and it was STILL there after the child exited, because
        nothing retried. That is the BF-788 signature, at a caller BF-788 did
        not reach.

        Async because the callers clean up in a ``finally`` on the event loop
        and the retry budget runs to ~9s; see `remove_workdir_off_loop` for why
        the work is submitted before it is awaited.
        """
        await remove_workdir_off_loop(path)
