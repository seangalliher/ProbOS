"""Shared crew-identification utility used by multiple extracted modules."""

from __future__ import annotations

from typing import Any

#: The persisted ``crew_execution`` record's exact shape -- the ONE definition.
#:
#: It lives in this dependency-free leaf module because THREE modules validate
#: against it (``crew_session``, ``crew_finalizer``, ``crew_executor``) and the
#: executor imports ``crew_session`` only under ``TYPE_CHECKING`` -- so putting
#: the contract there would need a runtime import the executor deliberately
#: avoids.
#:
#: **Why one definition matters here more than usual.** Five exact-key guards
#: compare a persisted record against this set and raise on any mismatch, so a
#: field added to the writer fails RESUME -- and the executor's rejection
#: becomes ``child_execution_integrity``, which blocks the whole crew session
#: rather than failing one child. Adding a field therefore has to land in every
#: copy in one commit or restart breaks.
#:
#: The shape was restated NINE times before this: byte-identical named copies
#: in ``crew_session`` and ``crew_finalizer``; an INLINE literal in the
#: executor's resume path that no search for a constant name could find; and
#: six more in the suite, under two different private names
#: (``_CREW_EXECUTION_KEYS``, ``_EVIDENCE_KEYS``) plus one literal written
#: inline in a test body. A name-based search found three of those six. The
#: AST census in ``tests/test_ad1248_slice_c_one_shape.py`` found the rest,
#: which is why that census exists rather than a grep.
#:
#: One literal restatement is kept on purpose, in
#: ``tests/test_bf680_token_usage_fallback.py``, so the suite still pins the
#: shape independently instead of asserting the record matches whatever this
#: constant happens to say.
#:
#: AD-1248 slice C has to add ``tool_failures`` here, so the shape is
#: consolidated first, as a separate behaviour-preserving change.
CREW_EXECUTION_KEYS = frozenset({
    "version",
    "parent_id",
    "work_item_id",
    "thread_id",
    "assigned_to",
    "status",
    "stopped_reason",
    "output_summary",
    "tool_trace_ref",
    "artifact_refs",
    "tokens_used",
    "started_at",
    "finished_at",
    "blocked_dependency_ids",
})

# Legacy fallback — remove when ontology is mandatory.
# Core crew eligible for Ward Room participation.
# Ontology equivalent: VesselOntologyService.get_crew_agent_types()
_WARD_ROOM_CREW = {
    "architect", "scout", "counselor",
    "security_officer", "operations_officer", "engineering_officer",
    "training_officer",  # AD-628 Tucker
    "diagnostician",  # Bones — CMO / Medical Chief
    "surgeon", "pathologist", "pharmacist",  # Medical crew
    "builder",  # Scotty — SWE officer, uses build pipeline as tool
    "data_analyst", "systems_analyst", "research_specialist",  # Science crew (AD-560)
}


def is_crew_agent(agent: Any, ontology: Any | None = None) -> bool:
    """Check if an agent is core crew eligible for Ward Room participation."""
    if not hasattr(agent, 'agent_type'):
        return False
    # AD-429e: Prefer ontology, fall back to legacy set
    if ontology:
        return agent.agent_type in ontology.get_crew_agent_types()
    return agent.agent_type in _WARD_ROOM_CREW
