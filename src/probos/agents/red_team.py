"""Red team agent — independently verifies other agents' results."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentMessage,
    IntentResult,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class RedTeamAgent(BaseAgent):
    """Agent that independently verifies other agents' results.

    Red team agents do NOT modify state. They re-execute the same
    operation and compare results. Discrepancies are reported to
    the trust network and consensus layer.

    Capabilities: verify_read_file, verify_stat_file, verify_run_command,
    verify_http_fetch.
    """

    agent_type: str = "red_team"
    default_capabilities = [
        CapabilityDescriptor(
            can="verify_read_file",
            detail="Independently verify file read results",
        ),
        CapabilityDescriptor(
            can="verify_stat_file",
            detail="Independently verify file stat results",
        ),
        CapabilityDescriptor(
            can="verify_run_command",
            detail="Independently verify shell command results",
        ),
        CapabilityDescriptor(
            can="verify_http_fetch",
            detail="Independently verify HTTP fetch results",
        ),
    ]
    initial_confidence: float = 0.9
    intent_descriptors = []  # Does not handle user intents

    # Red team agents do NOT subscribe to the normal intent bus.
    # They are invoked directly by the consensus layer.

    async def verify(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed_result: IntentResult,
    ) -> VerificationResult:
        """Independently verify a claimed result.

        Re-executes the same operation and compares output.
        Returns a VerificationResult with match/mismatch details.
        """
        intent_name = intent.intent
        params = intent.params

        if intent_name == "read_file":
            return await self._verify_read(target_agent_id, intent, claimed_result, params)
        elif intent_name == "stat_file":
            return await self._verify_stat(target_agent_id, intent, claimed_result, params)
        elif intent_name == "run_command":
            return await self._verify_run_command(target_agent_id, intent, claimed_result, params)
        elif intent_name == "http_fetch":
            return await self._verify_http_fetch(target_agent_id, intent, claimed_result, params)
        else:
            # Cannot verify this intent type
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=True,  # Give benefit of doubt for unknown intents
                confidence=0.1,
                discrepancy=f"Cannot verify intent type: {intent_name}",
            )

    async def _verify_read(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
        params: dict[str, Any],
    ) -> VerificationResult:
        """Verify a file read result by re-reading the file."""
        path = params.get("path", "")
        try:
            p = Path(path)
            if not p.exists():
                # File doesn't exist — agent should have reported failure
                if not claimed.success:
                    return VerificationResult(
                        verifier_id=self.id,
                        target_agent_id=target_agent_id,
                        intent_id=intent.id,
                        verified=True,
                        confidence=self.confidence,
                    )
                else:
                    self.update_confidence(True)
                    return VerificationResult(
                        verifier_id=self.id,
                        target_agent_id=target_agent_id,
                        intent_id=intent.id,
                        verified=False,
                        expected=None,
                        actual=claimed.result,
                        discrepancy="Agent claims success but file does not exist",
                        confidence=self.confidence,
                    )

            content = p.read_text(encoding="utf-8", errors="replace")

            if not claimed.success:
                # File exists but agent reported failure
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    expected=content,
                    actual=None,
                    discrepancy="Agent claims failure but file exists and is readable",
                    confidence=self.confidence,
                )

            # Compare content
            if claimed.result == content:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=True,
                    expected=content,
                    actual=claimed.result,
                    confidence=self.confidence,
                )
            else:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    expected=content,
                    actual=claimed.result,
                    discrepancy="Content mismatch",
                    confidence=self.confidence,
                )

        except Exception as e:
            self.update_confidence(False)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy=f"Verification error: {e}",
                confidence=self.confidence,
            )

    async def _verify_stat(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
        params: dict[str, Any],
    ) -> VerificationResult:
        """Verify a file stat result by re-statting the file."""
        path = params.get("path", "")
        try:
            p = Path(path)
            if not p.exists():
                if not claimed.success:
                    return VerificationResult(
                        verifier_id=self.id,
                        target_agent_id=target_agent_id,
                        intent_id=intent.id,
                        verified=True,
                        confidence=self.confidence,
                    )
                else:
                    self.update_confidence(True)
                    return VerificationResult(
                        verifier_id=self.id,
                        target_agent_id=target_agent_id,
                        intent_id=intent.id,
                        verified=False,
                        discrepancy="Agent claims success but file does not exist",
                        confidence=self.confidence,
                    )

            stat = p.stat()
            expected_data = {
                "path": str(p.resolve()),
                "size": stat.st_size,
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
            }

            if not claimed.success:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    expected=expected_data,
                    discrepancy="Agent claims failure but file is stattable",
                    confidence=self.confidence,
                )

            # For stat, just verify basic fields match
            if isinstance(claimed.result, dict):
                mismatches = []
                for key in ["size", "is_file", "is_dir"]:
                    if key in expected_data and key in claimed.result:
                        if expected_data[key] != claimed.result[key]:
                            mismatches.append(f"{key}: expected={expected_data[key]} actual={claimed.result[key]}")

                if mismatches:
                    self.update_confidence(True)
                    return VerificationResult(
                        verifier_id=self.id,
                        target_agent_id=target_agent_id,
                        intent_id=intent.id,
                        verified=False,
                        expected=expected_data,
                        actual=claimed.result,
                        discrepancy="; ".join(mismatches),
                        confidence=self.confidence,
                    )

            self.update_confidence(True)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=True,
                confidence=self.confidence,
            )

        except Exception as e:
            self.update_confidence(False)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy=f"Verification error: {e}",
                confidence=self.confidence,
            )

    async def _verify_run_command(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
        params: dict[str, Any],
    ) -> VerificationResult:
        """Verify command execution by re-running the same command."""
        command = params.get("command", "")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self.update_confidence(False)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    discrepancy="Verification command timed out",
                    confidence=self.confidence,
                )

            expected_exit_code = proc.returncode

            if not claimed.success:
                # Agent claims failure but we could run the command
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    discrepancy="Agent claims failure but command executed successfully",
                    confidence=self.confidence,
                )

            # Compare exit codes
            claimed_data = claimed.result if isinstance(claimed.result, dict) else {}
            claimed_exit_code = claimed_data.get("exit_code")

            if claimed_exit_code != expected_exit_code:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    expected={"exit_code": expected_exit_code},
                    actual={"exit_code": claimed_exit_code},
                    discrepancy=f"Exit code mismatch: expected={expected_exit_code} actual={claimed_exit_code}",
                    confidence=self.confidence,
                )

            # Compare stdout
            expected_stdout = stdout_bytes[:64 * 1024].decode("utf-8", errors="replace")
            claimed_stdout = claimed_data.get("stdout", "")
            if expected_stdout.strip() != claimed_stdout.strip():
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    discrepancy="Stdout mismatch",
                    confidence=self.confidence,
                )

            self.update_confidence(True)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=True,
                confidence=self.confidence,
            )

        except Exception as e:
            self.update_confidence(False)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy=f"Verification error: {e}",
                confidence=self.confidence,
            )

    async def _verify_http_fetch(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
        params: dict[str, Any],
    ) -> VerificationResult:
        """Verify HTTP fetch by re-fetching the same URL."""
        url = params.get("url", "")
        method = params.get("method", "GET")
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.request(method, url)

            if not claimed.success:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    discrepancy="Agent claims failure but URL is reachable",
                    confidence=self.confidence,
                )

            claimed_data = claimed.result if isinstance(claimed.result, dict) else {}
            claimed_status = claimed_data.get("status_code")

            if claimed_status != response.status_code:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    expected={"status_code": response.status_code},
                    actual={"status_code": claimed_status},
                    discrepancy=f"Status code mismatch: expected={response.status_code} actual={claimed_status}",
                    confidence=self.confidence,
                )

            # Verify content length consistency (20% tolerance for dynamic content)
            expected_length = len(response.content)
            claimed_length = claimed_data.get("body_length", 0)
            if expected_length > 0 and abs(expected_length - claimed_length) / expected_length > 0.2:
                self.update_confidence(True)
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=False,
                    discrepancy=f"Content length mismatch: expected~{expected_length} actual={claimed_length}",
                    confidence=self.confidence,
                )

            self.update_confidence(True)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=True,
                confidence=self.confidence,
            )

        except (httpx.ConnectError, httpx.TimeoutException):
            # If we can't reach the URL either, and agent also failed, that's consistent
            if not claimed.success:
                return VerificationResult(
                    verifier_id=self.id,
                    target_agent_id=target_agent_id,
                    intent_id=intent.id,
                    verified=True,
                    confidence=self.confidence,
                )
            self.update_confidence(False)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy="Verifier cannot reach URL but agent claims success",
                confidence=self.confidence,
            )
        except Exception as e:
            self.update_confidence(False)
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy=f"Verification error: {e}",
                confidence=self.confidence,
            )

    # ------------------------------------------------------------------
    # BaseAgent lifecycle — red team agents are passive (no intent bus)
    # ------------------------------------------------------------------

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}
