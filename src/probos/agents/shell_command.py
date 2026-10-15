"""Shell command agent — executes shell commands, gated by consensus."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from probos.execution.command_env import build_command_env
from probos.execution.process_tree import ProcessTree, ProcessTreeSlot, process_tree_popen_kwargs
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)

# Regex to detect and strip redundant `powershell -Command "..."` wrappers.
# The agent already invokes powershell on Windows, so the inner call is
# unnecessary and can cause quoting issues.
_PS_WRAPPER_RE = re.compile(
    r"^powershell(?:\.exe)?\s+(?:-\w+\s+)*-(?:Command|c)\s+",
    re.IGNORECASE,
)

# Regex to detect bare `python` / `python3` at the start of a command.
_BARE_PYTHON_RE = re.compile(
    r"^(python3?(?:\.exe)?)\s",
    re.IGNORECASE,
)


class ShellCommandAgent(BaseAgent):
    """Concrete agent that executes shell commands.

    HIGH-RISK: All commands go through consensus (enforced at
    the DAG level via use_consensus=true).

    Capabilities: run_command.
    """

    agent_type: str = "shell_command"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="run_command",
            detail="Execute a shell command and return output (general-purpose: dates, math, system info, etc.)",
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="run_command", params={"command": "<shell_command>"}, description="Execute an OS shell command (dates, system info, process management, package install). NOT for scripting workarounds.", requires_consensus=True, requires_reflect=True),
    ]

    _handled_intents = {"run_command"}

    # Security constants
    DEFAULT_TIMEOUT: float = 30.0
    MAX_OUTPUT_BYTES: int = 64 * 1024  # 64KB cap on stdout/stderr
    # BF-893 (#1544): how long past the deadline the worker has to end the command's tree and return its
    # own timeout result; the caller's wait is only a backstop for a worker that never starts or wedges.
    WORKER_TEARDOWN_GRACE: float = 5.0

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # through the shell pool's spawn kwargs.
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        super().__init__(pool, **kwargs)

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
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
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Plan what to do based on the perceived intent."""
        params = observation["params"]
        command = params.get("command", "")

        if not command or not command.strip():
            return {"action": "error", "error": "No command specified"}

        # Validate the primary command exists before executing
        primary_cmd = command.split()[0].strip('"').strip("'")
        if not self._command_exists(primary_cmd):
            return {
                "action": "error",
                "error": (
                    f"Command '{primary_cmd}' not found on this system. "
                    "This task may need a dedicated agent — try asking ProbOS to build one."
                ),
            }

        return {"action": "run", "command": command}

    @staticmethod
    def _command_exists(cmd: str) -> bool:
        """Check whether *cmd* is a shell builtin, PowerShell cmdlet, or on PATH."""
        # PowerShell cmdlets contain a hyphen (e.g. Get-Date)
        if '-' in cmd:
            return True
        _BUILTINS = {
            'echo', 'cd', 'set', 'dir', 'type', 'copy', 'move', 'del',
            'mkdir', 'rmdir', 'cls', 'exit', 'where', 'if', 'for',
            'powershell', 'cmd', 'python', 'pip', 'git', 'node', 'npm',
            'curl', 'wget', 'tar', 'ssh', 'scp',
        }
        if cmd.lower() in _BUILTINS:
            return True
        return shutil.which(cmd) is not None

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "run":
            return await self._run_command(plan["command"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _run_command(self, command: str) -> dict[str, Any]:
        """Execute a shell command with timeout and output capping.

        Uses subprocess.Popen in a thread executor so it works with any
        asyncio event-loop policy (including WindowsSelectorEventLoop
        which does not support asyncio.create_subprocess_*).
        """
        if sys.platform == "win32":
            # Strip redundant powershell wrapper — the agent already
            # runs commands under powershell via Popen.
            command = self._strip_ps_wrapper(command)

        command = self._rewrite_python_interpreter(command)

        loop = asyncio.get_running_loop()
        # BF-893 (#1544): one deadline, measured from submission, is shared with the worker. Its own
        # budget used to start when a pool thread picked the job up, so with the shared executor busy the
        # caller reported a timeout while the command it had started was still running.
        deadline = time.monotonic() + self.DEFAULT_TIMEOUT
        slot = ProcessTreeSlot()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_sync, command, deadline, slot),
                timeout=self.DEFAULT_TIMEOUT + self.WORKER_TEARDOWN_GRACE,
            )
            return result
        except asyncio.CancelledError:
            slot.cancel()  # BF-893: an enclosing timeout or cancellation must not leave the tree running
            raise
        except asyncio.TimeoutError:
            slot.cancel()
            return {
                "success": False,
                "error": f"Command timed out after {self.DEFAULT_TIMEOUT}s",
            }
        except Exception as e:
            return {"success": False, "error": repr(e)}

    @staticmethod
    def _strip_ps_wrapper(command: str) -> str:
        """Remove a redundant ``powershell -Command "..."`` wrapper.

        If the whole command is wrapped in an outer ``powershell -Command``
        invocation, unwrap it so we don't nest powershell → powershell.
        Handles optional surrounding quotes on the inner body.
        """
        m = _PS_WRAPPER_RE.match(command)
        if m:
            inner = command[m.end():]
            # Strip one layer of surrounding double-quotes if present
            if inner.startswith('"') and inner.endswith('"'):
                inner = inner[1:-1]
            return inner
        return command

    @staticmethod
    def _rewrite_python_interpreter(command: str) -> str:
        """Replace bare ``python``/``python3`` with the current interpreter.

        When the LLM generates ``python -c "..."``, the bare name may not
        be on PATH.  Replace it with ``sys.executable`` which is guaranteed
        to be the running interpreter (inside the venv).
        """
        m = _BARE_PYTHON_RE.match(command)
        if m:
            prefix = '& ' if sys.platform == 'win32' else ''
            return f'{prefix}"{sys.executable}"' + command[m.end(1):]
        return command

    def _run_sync(
        self, command: str, deadline: float | None = None, slot: ProcessTreeSlot | None = None,
    ) -> dict[str, Any]:
        """Blocking subprocess execution (called via run_in_executor).

        ``deadline`` is the ``time.monotonic()`` instant the caller's budget ends (BF-893): a worker
        that starts past it runs nothing, and one that starts inside it ends its command's tree at the
        deadline, or when ``slot`` is cancelled (the caller gave up). It can outlive the deadline only
        while that teardown is in progress, or if a process cannot be ended (``ProcessTree.kill`` logs
        when it cannot signal the tree). Omitted, the budget starts now.
        """
        if deadline is None:
            deadline = time.monotonic() + self.DEFAULT_TIMEOUT
        timed_out = {"success": False, "error": f"Command timed out after {self.DEFAULT_TIMEOUT}s"}
        if time.monotonic() >= deadline or (slot is not None and slot.cancelled()):
            return timed_out
        try:
            # BF-890 (#1529): an allowlisted environment, not the runtime's.
            env = build_command_env(self._command_env_passthrough)
            if sys.platform == "win32":
                args = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    **process_tree_popen_kwargs(),
                )
            else:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    **process_tree_popen_kwargs(),
                )

            with ProcessTree.attach(proc) as tree:
                if slot is not None and not slot.hold(tree):
                    proc.wait()
                    return timed_out
                try:
                    stdout_bytes, stderr_bytes = proc.communicate(
                        timeout=max(deadline - time.monotonic(), 0.0),
                    )
                except subprocess.TimeoutExpired:
                    # BF-893 (#1544): end the command's whole tree, not only the shell.
                    tree.kill()
                    proc.wait()
                    return timed_out
                finally:
                    if slot is not None:
                        slot.release()  # before close(): cancel() never sees a closed job

            stdout = stdout_bytes[:self.MAX_OUTPUT_BYTES].decode(
                "utf-8", errors="replace"
            )
            stderr = stderr_bytes[:self.MAX_OUTPUT_BYTES].decode(
                "utf-8", errors="replace"
            )

            return {
                "success": True,
                "data": {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode,
                    "command": command,
                },
            }
        except Exception as e:
            return {"success": False, "error": repr(e)}
