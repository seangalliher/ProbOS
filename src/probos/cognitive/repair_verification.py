"""AD-1173: verify a repair before it goes back into service.

`SystemQAAgent` and `RedTeamAgent` are implemented, registered as spawner
templates, and have never been spawned in production. `QAAgentPool` exists with
no call sites. The ship has a QA department that has never been called to a job.

This is the "test it, then put it back into use" half of the repair loop, and
for a tool fault the verification is unusually direct: **re-run the operation
that failed and confirm the error signature is gone.** No judgement, no model
call, no interpretation — the same evidence-over-narration discipline the rest
of this epic runs on.

Three outcomes, and the distinction matters:

* ``repaired`` — the retry succeeded, or failed differently. The fault closes.
* ``unrepaired`` — the retry produced the SAME signature. The fault stays open
  and the repair did not hold.
* ``inconclusive`` — the retry could not be run at all. This must never be
  mistaken for success: closing a fault because it could not be checked is
  exactly how a broken tool returns to service.

Arguments for the retry come from the persisted trace (AD-1171), so a fault can
be verified without having recorded them separately at filing time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from probos.fault_report import error_signature

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerificationResult:
    """What happened when the failing operation was tried again."""

    outcome: str = "inconclusive"  # repaired | unrepaired | inconclusive
    tool_id: str = ""
    detail: str = ""
    retried: bool = False

    @property
    def repaired(self) -> bool:
        return self.outcome == "repaired"

    def render(self) -> str:
        if self.outcome == "repaired":
            return (
                f"Verified: the {self.tool_id} tool no longer returns the "
                f"reported error. {self.detail}".strip()
            )
        if self.outcome == "unrepaired":
            return (
                f"Not verified: the {self.tool_id} tool still returns the same "
                f"error. {self.detail}".strip()
            )
        return (
            f"Could not verify the {self.tool_id} repair. {self.detail} The "
            "fault stays open, because a repair that was not checked is not a "
            "repair."
        ).strip()


def find_failing_arguments(entries: Any, *, tool_id: str, signature: str) -> dict | None:
    """Recover the arguments of the call that produced this fault.

    Scans a persisted AD-1151 trace for the last entry whose tool and error
    signature match. The LAST rather than the first, because an agent that
    retried a refused call has the same arguments each time and the final
    attempt is the one it settled on.
    """
    if not isinstance(entries, list):
        return None
    found: dict | None = None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("is_error") is not True:
            continue
        if str(entry.get("name") or entry.get("tool") or "") != tool_id:
            continue
        raw = entry.get("output", "")
        raw_text = raw if isinstance(raw, str) else str(raw)
        if error_signature(tool_id=tool_id, error_text=raw_text) != signature:
            continue
        args = entry.get("arguments")
        if isinstance(args, dict):
            found = args
    return found


async def verify_repair(
    *,
    runtime: Any,
    fault: Any,
    tool_executor: Any = None,
) -> VerificationResult:
    """Re-run the failing operation and report whether the fault is gone.

    Never raises. An exception during verification is ``inconclusive``, never
    ``repaired`` — the whole point of this gate is that an unchecked repair does
    not return to service.
    """
    tool_id = str(getattr(fault, "tool_id", "") or "")
    signature = str(getattr(fault, "signature", "") or "")
    if not tool_id or not signature:
        return VerificationResult(
            outcome="inconclusive", tool_id=tool_id,
            detail="The fault does not name a tool and an error signature.",
        )

    executor = tool_executor or getattr(runtime, "_tool_executor", None)
    if executor is None or not hasattr(executor, "invoke"):
        return VerificationResult(
            outcome="inconclusive", tool_id=tool_id,
            detail="No tool executor is available to retry the operation.",
        )

    trace_ref = str(getattr(fault, "tool_trace_ref", "") or "")
    args: dict | None = None
    if trace_ref:
        try:
            from probos.cognitive.trace_analysis import load_trace

            entries = await load_trace(
                getattr(runtime, "attachment_store", None), trace_ref,
            )
            args = find_failing_arguments(
                entries, tool_id=tool_id, signature=signature,
            )
        except Exception:
            logger.debug(
                "AD-1173: could not recover arguments from trace %s",
                trace_ref[:16], exc_info=True,
            )
    if args is None:
        return VerificationResult(
            outcome="inconclusive", tool_id=tool_id,
            detail=(
                "The arguments of the failing call could not be recovered, so "
                "there is nothing to retry."
            ),
        )

    try:
        result = await executor.invoke(
            agent_id="system-qa", tool_id=tool_id, params=args,
        )
    except Exception as exc:
        return VerificationResult(
            outcome="inconclusive", tool_id=tool_id, retried=True,
            detail=f"Retrying raised {type(exc).__name__}.",
        )

    error = getattr(result, "error", None)
    if error is None:
        return VerificationResult(
            outcome="repaired", tool_id=tool_id, retried=True,
            detail="The retried call succeeded.",
        )
    if error_signature(tool_id=tool_id, error_text=str(error)) == signature:
        return VerificationResult(
            outcome="unrepaired", tool_id=tool_id, retried=True,
            detail="The retried call produced the same error.",
        )
    return VerificationResult(
        outcome="repaired", tool_id=tool_id, retried=True,
        detail=(
            "The retried call failed differently, so the reported fault is "
            "gone even though the operation did not succeed."
        ),
    )


async def verify_and_close(
    *,
    runtime: Any,
    fault: Any,
    tool_executor: Any = None,
) -> VerificationResult:
    """Verify, and close the fault only when it is actually repaired."""
    result = await verify_repair(
        runtime=runtime, fault=fault, tool_executor=tool_executor,
    )
    store = getattr(runtime, "fault_report_store", None)
    if store is None:
        return result
    try:
        if result.repaired:
            await store.resolve(
                str(getattr(fault, "id", "")),
                status="repaired",
                resolution=result.render(),
            )
            logger.info(
                "AD-1173: fault %s verified repaired and returned to service",
                str(getattr(fault, "id", ""))[:12],
            )
        else:
            logger.warning(
                "AD-1173: fault %s was NOT verified (%s); it stays open. %s",
                str(getattr(fault, "id", ""))[:12], result.outcome, result.detail,
            )
    except Exception:
        logger.warning(
            "AD-1173: could not record the verification outcome for fault %s",
            str(getattr(fault, "id", ""))[:12], exc_info=True,
        )
    return result
