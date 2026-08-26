"""AD-1172: a repair brief, and a target you choose.

`ArchitectAgent` and `BuilderAgent` are fully built and work well — and are
reachable only by the Captain typing ``/design``. There is no path from any
system signal to the repair crew. The ship has engineers who only respond when
the Captain walks down to engineering personally.

This closes that path. But the deliverable is deliberately **not** "dispatch to
the Architect", because that would bake in the assumption the Captain rejected:

    "I could decide to have a different harness do the work. I could decide to
     use GitHub Copilot for example. So I want to be able to have that choice
     on what harness I want to dispatch to."

So the artifact is a **harness-neutral brief**. The internal Architect consumes
it; an external harness receives the same thing rendered as Markdown for a human
to carry across. Neither is the fallback — the brief is the interface, and that
is what keeps an external target first-class rather than a degraded mode.

This maps onto the HXI's own tiering: ``architect`` is the agentic tier, an
external harness is the airlock, and the brief is exactly what crosses the
boundary.

**Two gates, both the Captain's** (their choice, of the two offered):

1. Approve the dispatch AND pick the target. An Architect run spends deep-tier
   tokens, and a flapping tool must not be able to spend them on its own.
2. Approve the resulting change. Nothing reaches a branch without this.

The brief is pure and renderable with no runtime attached, so what the Architect
sees and what a human pastes into Copilot are provably the same text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# The internal harness. Named rather than special-cased so it sits in the same
# list as every external one and gets no privileged path.
TARGET_ARCHITECT: str = "architect"

_TITLE_MAX = 120
_EVIDENCE_MAX = 4000

# AD-1267: the target list reaches the approval payload, whose canonical JSON is
# capped at _ACTION_PAYLOAD_MAX_CHARS (4000). resolve_targets was unbounded, so a
# long or long-named target list made an ordinary fault permanently unproposable.
_TARGETS_MAX = 8
_TARGET_NAME_MAX = 64


@dataclass(frozen=True)
class RepairBrief:
    """Everything a harness needs to diagnose one fault, and nothing else.

    Frozen and free of runtime references on purpose: a brief can be rendered,
    logged, persisted, shown in the HXI, or pasted into a chat window without
    dragging a live system behind it.
    """

    fault_id: str = ""
    tool_id: str = ""
    signature: str = ""
    error_text: str = ""
    occurrences: int = 0
    attempted: str = ""
    agent_id: str = ""
    thread_id: str = ""
    trace_summary: str = ""
    tool_trace_ref: str = ""
    suspected_files: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        summary = " ".join(str(self.error_text or "").split())
        head = f"{self.tool_id or 'tool'} fault: {summary}"
        return head[: _TITLE_MAX - 1] + "\u2026" if len(head) > _TITLE_MAX else head

    def render_markdown(self) -> str:
        """The portable artifact.

        Written to be useful to a person and to a model, and to survive being
        pasted into a harness that knows nothing about ProbOS. It leads with
        what is broken and how it is known, not with provenance.
        """
        return self._render(include_occurrences=True, include_trace=True)

    def render_for_payload(self) -> str:
        """The same brief, projected to what is invariant across recurrences.

        AD-1267: this value travels in an approval request's ``params``, and
        ``action_dedup_key`` hashes ``params`` WHOLE. So any field that changes
        between two occurrences of ONE fault makes that fault raise one Captain
        approval per change. Two families of field do:

        - **the occurrence count**, volatile by definition — occurrence 2 and
          occurrence 3 of one fault would hash differently;
        - **every trace-derived field**, because the coalesce branch adopts a
          ``tool_trace_ref`` (and the ``observed_as`` that belongs to it)
          absent -> present. A fault whose first occurrence carried no trace and
          whose third does would otherwise render a different brief for the same
          fault, and raise a second approval even with the count removed.

        The Captain loses neither. The live count rides in the request's
        ``rationale``, which is not key material, and ``params["fault_id"]``
        resolves the full report — and therefore its current ``tool_trace_ref``
        — in one :meth:`FaultReportStore.get` lookup.
        """
        return self._render(include_occurrences=False, include_trace=False)

    def _render(self, *, include_occurrences: bool, include_trace: bool) -> str:
        """The one renderer both public forms delegate to.

        Shared rather than forked so a field added later cannot reach the
        portable artifact while silently rejoining the dedup key, or the
        reverse. A new volatile field is excluded here, in one place.
        """
        if include_occurrences:
            observed = (
                f"The `{self.tool_id}` tool returned the same error "
                f"{self.occurrences} time(s):"
            )
        else:
            observed = (
                f"The `{self.tool_id}` tool returned the same error on more "
                "than one occasion:"
            )
        lines: list[str] = [
            f"# Repair brief: {self.tool_id or 'unknown tool'}",
            "",
            "## What is wrong",
            "",
            observed,
            "",
            "```",
            " ".join(str(self.error_text or "").split())[:_EVIDENCE_MAX],
            "```",
            "",
        ]
        if self.attempted:
            lines += ["## What was being attempted", "", self.attempted, ""]
        if include_trace and self.trace_summary:
            lines += [
                "## Evidence from the run",
                "",
                "This is the agent's tool trace, not its narration. Where the "
                "two disagree, the trace is what happened.",
                "",
                self.trace_summary,
                "",
            ]
        if self.suspected_files:
            lines += ["## Where to look first", ""]
            lines += [f"- `{path}`" for path in self.suspected_files]
            lines.append("")
        if self.acceptance:
            lines += ["## Done means", ""]
            lines += [f"- {item}" for item in self.acceptance]
            lines.append("")
        lines += [
            "## Provenance",
            "",
            f"- Fault report: `{self.fault_id}`",
            f"- Error signature: `{self.signature[:16]}`",
        ]
        if include_trace and self.tool_trace_ref:
            lines.append(f"- Tool trace: `{self.tool_trace_ref[:16]}`")
        if self.agent_id:
            lines.append(f"- Reported by: `{self.agent_id}`")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "tool_id": self.tool_id,
            "signature": self.signature,
            "error_text": self.error_text,
            "occurrences": self.occurrences,
            "attempted": self.attempted,
            "agent_id": self.agent_id,
            "thread_id": self.thread_id,
            "trace_summary": self.trace_summary,
            "tool_trace_ref": self.tool_trace_ref,
            "suspected_files": list(self.suspected_files),
            "acceptance": list(self.acceptance),
        }


def _acceptance_for(tool_id: str, error_text: str) -> tuple[str, ...]:
    """What "repaired" means for this fault, stated before any work starts.

    Deliberately concrete and checkable: AD-1173 verifies a repair by re-running
    the failing operation and confirming the signature is gone, so the criteria
    have to be the kind of thing that can be checked rather than judged.
    """
    return (
        f"The `{tool_id}` tool no longer returns: "
        f"{' '.join(str(error_text or '').split())[:200]}",
        "The original failing operation succeeds when retried.",
        "A regression test fails against the current code and passes after the fix.",
        "Verify compliance with the Engineering Principles in "
        "`.github/copilot-instructions.md`.",
    )


def build_repair_brief(
    fault: Any,
    *,
    trace_summary: str = "",
    suspected_files: tuple[str, ...] = (),
) -> RepairBrief:
    """Assemble a brief from an AD-1169 fault and an AD-1171 trace summary.

    Pure and defensive: a malformed fault yields a brief with empty fields
    rather than raising, because a half-known fault is still worth showing the
    Captain.
    """
    return RepairBrief(
        fault_id=str(getattr(fault, "id", "") or ""),
        tool_id=str(getattr(fault, "tool_id", "") or ""),
        signature=str(getattr(fault, "signature", "") or ""),
        error_text=str(getattr(fault, "error_text", "") or ""),
        occurrences=int(getattr(fault, "occurrences", 0) or 0),
        attempted=str(getattr(fault, "attempted", "") or ""),
        agent_id=str(getattr(fault, "agent_id", "") or ""),
        thread_id=str(getattr(fault, "thread_id", "") or ""),
        trace_summary=str(trace_summary or ""),
        tool_trace_ref=str(getattr(fault, "tool_trace_ref", "") or ""),
        suspected_files=tuple(suspected_files),
        acceptance=_acceptance_for(
            str(getattr(fault, "tool_id", "") or ""),
            str(getattr(fault, "error_text", "") or ""),
        ),
    )


def resolve_targets(config: Any) -> tuple[str, ...]:
    """The dispatch targets this instance offers, in declared order.

    Config-declared rather than code-registered: an external harness needs no
    code, because dispatching to one means rendering the brief and telling the
    Captain. Adding "copilot" to a list is the whole integration.
    """
    raw = getattr(config, "targets", None)
    if not isinstance(raw, (list, tuple)) or not raw:
        return (TARGET_ARCHITECT,)
    # AD-1267: each name is clipped BEFORE the dedup, so two names differing only
    # past the bound collapse to the one form the payload would carry, and the
    # list cap then counts distinct targets rather than duplicates.
    seen: list[str] = []
    clipped = 0
    for item in raw:
        full = str(item or "").strip()
        name = full[:_TARGET_NAME_MAX]
        if len(full) > _TARGET_NAME_MAX:
            clipped += 1
        if name and name not in seen:
            seen.append(name)
    dropped = max(len(seen) - _TARGETS_MAX, 0)
    if dropped or clipped:
        logger.warning(
            "AD-1267: bounded the repair dispatch targets — dropped %d beyond "
            "the first %d and clipped %d name(s) to %d chars, because the whole "
            "list is carried in an approval payload capped at 4000 characters; "
            "an oversized list would make every fault unproposable. Offering "
            "%s.",
            dropped, _TARGETS_MAX, clipped, _TARGET_NAME_MAX,
            ", ".join(seen[:_TARGETS_MAX]),
        )
    seen = seen[:_TARGETS_MAX]
    return tuple(seen) if seen else (TARGET_ARCHITECT,)


def is_internal_target(target: str) -> bool:
    """True for the one target ProbOS can run itself."""
    return str(target or "").strip().lower() == TARGET_ARCHITECT
