"""AD-994: CodeRunnerAgent — governed ephemeral Python execution for crew agents.

Gives crew agents the GitHub Copilot / Claude Code capability — *create and run a
Python script, installing libraries as needed* — done the ProbOS way:

* **Consensus-gated.** Both intents set ``requires_consensus=True``; every
  execution is quorum-authorized, exactly like ``run_command``.
* **Default OFF.** Inert unless ``config.execution.enabled`` is set by the
  operator. Package install is separately gated (``allow_package_install``).
* **Isolated (Tier 1).** Runs through the AD-993 ``SubprocessSandbox``: a fresh
  ephemeral working folder per task, subprocess isolation, resource + time bounds,
  output caps, network-off-by-default. Tier 1 is process-isolation +
  confinement-by-convention governed by consensus — not kernel containment (that
  is the Tier-2 AD-995 escalation). The whole scratch tree, including any
  per-task venv, is reaped after the run.

Two intents:

* ``run_python`` — write + execute Python source. Optional ``packages`` are
  installed into a throwaway per-task venv first ("install libraries as needed"),
  then the script runs in that venv. No packages → runs in the host interpreter,
  no venv.
* ``install_package`` — validate that a package set installs cleanly into a
  throwaway venv (a standalone availability probe). Same machinery, no script run.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from probos.execution.isolation import ExecutionRequest, SubprocessSandbox
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
    """Execute ephemeral Python (and install its libraries) under Tier-1 isolation.

    HIGH-RISK: arbitrary code execution. Consensus-gated + default-OFF +
    sandboxed. Capabilities: run_python, install_package.
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
            usage_hint="[MESH run_python code=<src>] (run an isolated Python script to perform a task)",
            requires_consensus=True,
            requires_reflect=True,
        ),
        IntentDescriptor(
            name="install_package",
            params={"packages": "<list[str] of pip packages>"},
            description="Validate that Python packages install cleanly into an isolated throwaway venv.",
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
            }
        if intent == "install_package":
            packages = self._clean_packages(params.get("packages"))
            if not packages:
                return {"action": "error", "error": "No packages specified"}
            return {"action": "install_package", "packages": packages}
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
            return await self._install_package(plan["packages"])
        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------

    async def _run_python(self, plan: dict) -> dict[str, Any]:
        cfg = self._execution_config()
        sandbox = SubprocessSandbox(scratch_root=cfg.scratch_dir)
        scratch = Path(cfg.scratch_dir) / uuid.uuid4().hex
        packages = plan["packages"]
        timeout = self._resolve_timeout(plan.get("timeout"), cfg.timeout_seconds)
        py_exe: str | None = None
        try:
            scratch.mkdir(parents=True, exist_ok=True)
            if packages:
                if not getattr(cfg, "allow_package_install", False):
                    return {
                        "success": False,
                        "error": "Package install disabled (set config.execution.allow_package_install).",
                    }
                prep = await self._prepare_venv(sandbox, scratch, packages, cfg)
                if not prep["success"]:
                    return prep
                py_exe = prep["python"]

            res = await sandbox.run(ExecutionRequest(
                code=plan["code"],
                workdir=scratch,
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
                },
                "error": res.error or None,
            }
        finally:
            self._reap(scratch)

    async def _install_package(self, packages: list[str]) -> dict[str, Any]:
        cfg = self._execution_config()
        if not getattr(cfg, "allow_package_install", False):
            return {
                "success": False,
                "error": "Package install disabled (set config.execution.allow_package_install).",
            }
        sandbox = SubprocessSandbox(scratch_root=cfg.scratch_dir)
        scratch = Path(cfg.scratch_dir) / uuid.uuid4().hex
        try:
            scratch.mkdir(parents=True, exist_ok=True)
            prep = await self._prepare_venv(sandbox, scratch, packages, cfg)
            if not prep["success"]:
                return prep
            return {
                "success": True,
                "data": {"installed": packages, "stdout": prep.get("stdout", "")},
            }
        finally:
            self._reap(scratch)

    async def _prepare_venv(
        self, sandbox: SubprocessSandbox, scratch: Path, packages: list[str], cfg: Any,
    ) -> dict[str, Any]:
        """Create a throwaway venv in ``scratch`` and pip-install ``packages``.

        Both steps run through the Tier-1 sandbox (bounded + governed). Returns
        ``{success, python}`` on success, or ``{success: False, error}``.
        """
        venv_dir = scratch / "venv"
        # 1. Create the venv (no network needed).
        create = await sandbox.run(ExecutionRequest(
            argv=[sys.executable, "-m", "venv", str(venv_dir)],
            workdir=scratch,
            timeout_seconds=cfg.install_timeout_seconds,
            max_output_bytes=cfg.max_output_bytes,
            allow_network=False,
        ))
        if not create.success:
            return {"success": False, "error": f"venv creation failed: {create.stderr or create.error}"}
        py = _venv_python(venv_dir)
        # 2. pip install (network ON, scoped index url). Tier 1 cannot scope the
        #    network to PyPI only — that is a Tier-2 guarantee — so this is
        #    consensus-gated and the package names are surfaced in the intent.
        install = await sandbox.run(ExecutionRequest(
            argv=[
                str(py), "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input",
                "--index-url", cfg.pip_index_url, *packages,
            ],
            workdir=scratch,
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
    def _reap(path: Path) -> None:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
