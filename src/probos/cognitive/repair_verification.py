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


def find_failing_arguments(
    entries: Any, *, tool_id: str, signature: str, observed_as: str = "",
) -> dict | None:
    """Recover the arguments of the call that produced this fault.

    Scans a persisted AD-1151 trace for the last entry whose tool and error
    signature match. The LAST rather than the first, because an agent that
    retried a refused call has the same arguments each time and the final
    attempt is the one it settled on.

    AD-1269: the trace stores ``asdict(ToolCallRequest)``, whose ``name`` is the
    name the MODEL used -- an alias for any tool id the provider's name regex
    rejects. The fault row's ``tool_id`` is the canonical registered id, so
    matching on it alone would never find an MCP tool's call. ``observed_as``
    carries the alias when there is one and is empty otherwise, which is why
    the match falls back to ``tool_id``. The SIGNATURE is still computed over
    the canonical id, because that is what the row was keyed on.

    AD-1279: an error entry now CARRIES that identity, computed by the writer
    over the untruncated output, so the match reads it rather than deriving it.
    Recomputation is the LEGACY path -- kept, not replaced, and taken on a
    missing key *and* on a mismatch. Reading the field alone would make it
    authoritative even when the writer and the detector had been handed
    different resolvers; recomputing cannot produce a false positive against a
    specific 256-bit target except by collision, so keeping it is strictly more
    permissive and costs nothing. It is what made BF-855 possible: the writer
    bounds each output before persisting it, and ``normalise_error`` collapses
    before it truncates, so a long error whose head collapses to less than that
    bound derived a different digest from its own trace and could never be
    matched back to it.
    """
    if not isinstance(entries, list):
        return None
    traced_name = observed_as or tool_id
    named = 0
    signed = 0
    mismatches = 0
    found: dict | None = None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("is_error") is not True:
            continue
        if str(entry.get("name") or entry.get("tool") or "") != traced_name:
            continue
        named += 1
        carried = entry.get("error_signature")
        if not (isinstance(carried, str) and carried == signature):
            # Absent, or written by a writer that canonicalised differently.
            # Either way the pre-AD-1279 derivation still decides.
            raw = entry.get("output", "")
            raw_text = raw if isinstance(raw, str) else str(raw)
            if error_signature(tool_id=tool_id, error_text=raw_text) != signature:
                continue
            if isinstance(carried, str):
                # AD-1279: recomputation rescued a match the carried identity
                # disagreed with. That is the writer/detector skew this AD set
                # out to remove, and the fallback would otherwise hide it
                # perfectly -- recovery succeeds and nothing says the trace's
                # own identity was wrong. Not an error: the repair proceeds.
                mismatches += 1
                logger.warning(
                    "AD-1279: trace entry for %r carries error signature %s "
                    "but recomputation matched %s; recovery proceeded on the "
                    "recomputed value. The writer and the detector "
                    "canonicalised this tool differently",
                    traced_name, carried[:12], signature[:12],
                )
        signed += 1
        args = entry.get("arguments")
        if isinstance(args, dict):
            found = args
    if found is None and signed:
        # Counted separately because the two causes are different repairs. An
        # entry that matched the signature and still yielded nothing has a
        # missing or non-dict ``arguments``; saying "none carries the
        # signature" here asserts something this branch did not check, and
        # review measured exactly that message on an exact name-and-signature
        # match with a non-dict ``arguments``.
        logger.debug(
            "AD-1173: %d trace entries name %r and carry error signature %s, "
            "but none has a recoverable argument dictionary; verification will "
            "report 'inconclusive'",
            signed, traced_name, signature[:12],
        )
    elif found is None and named:
        # Before AD-1279 this was the one place the AD-1269 truncation
        # asymmetry became observable, and it was unavoidable. Now that an
        # error entry carries the identity the detector derived, reaching here
        # means either a trace written before that key existed whose bounded
        # output no longer derives the same digest, or a genuinely different
        # failure of the same tool.
        logger.debug(
            "AD-1173: %d trace entries name %r but none carries error "
            "signature %s -- a pre-AD-1279 trace, or a different failure of "
            "the same tool; verification will report 'inconclusive'",
            named, traced_name, signature[:12],
        )
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
                observed_as=str(getattr(fault, "observed_as", "") or ""),
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
