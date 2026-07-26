"""AD-1145: W3C PROV-O projection of ProbOS provenance -- pure stdlib.

A read-only projection of provenance ProbOS **already persists** onto the W3C
PROV-O vocabulary (https://www.w3.org/TR/prov-o/) as JSON-LD, so stock RDF
tooling can read it. Two sources, both complete, both carrying PROV-O's
Agent/Activity/Entity triad:

* **Crew execution evidence** -- the frozen 14-key ``crew_execution`` record.
  ``work_item_id`` is the Activity, ``assigned_to`` the Agent, ``parent_id``
  the informing Activity, ``artifact_refs`` the generated Entities.
* **Ship's Records frontmatter** -- ``author`` / ``created`` / ``revision``.

DD-3 purity invariant: this module imports NOTHING outside the standard
library -- in particular nothing from ``probos``. That non-import is what lets
a third-party agentic harness vendor this file verbatim, and it is what makes
the projection provably incapable of writing, emitting an event, or touching
the frozen contracts it reads. Input is a plain ``dict``, output is a plain
``dict``. Not called => zero cost, byte-identical behaviour. This mirrors the
AD-1144 ``federation/ard/jcs.py`` precedent.

Two invariants worth stating because they are easy to erode:

* **Honest omission over invention (DD-4).** A field that is absent, empty or
  ill-typed yields *no triple* -- never a placeholder. A consumer must be able
  to distinguish "unattributed" from "attributed to unknown". Consequently
  nothing here raises: a malformed record projects to a smaller document, and
  a record whose *identity* is unknowable projects to an empty graph.
* **No token counts (DD-5 / BF-680).** ``tokens_used`` is deliberately NOT
  projected. PROV-O has no term for it, and ``crew_execution`` carries the
  integer without the ``token_source`` label that says whether it was measured
  or estimated -- ``WorkItemAgenticOutcome.token_source`` is dropped before
  persistence. Projecting it would present a possible BF-680 estimate as a
  measured fact, so the honest answer is silence.

Public surface: :data:`PROV_CONTEXT`, :data:`PROV_TERMS`,
:func:`project_crew_execution`, :func:`project_record_frontmatter`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "PROV_CONTEXT",
    "PROV_NAMESPACE",
    "PROV_TERMS",
    "project_crew_execution",
    "project_record_frontmatter",
]

PROV_NAMESPACE = "http://www.w3.org/ns/prov#"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"

#: The JSON-LD ``@context`` every projected document carries.
PROV_CONTEXT: dict[str, str] = {
    "prov": PROV_NAMESPACE,
    "xsd": XSD_NAMESPACE,
}

#: The complete, explicit allowlist of PROV-O terms this module may emit --
#: both ``@type`` values and predicate keys. It is public so a test can assert
#: that the terms actually emitted are a SUBSET of it, and that the allowlist
#: itself has not been widened to admit an invented ``prov:`` term.
PROV_TERMS: frozenset[str] = frozenset(
    {
        "prov:Activity",
        "prov:Agent",
        "prov:Entity",
        "prov:SoftwareAgent",
        "prov:endedAtTime",
        "prov:generatedAtTime",
        "prov:startedAtTime",
        "prov:used",
        "prov:wasAssociatedWith",
        "prov:wasAttributedTo",
        "prov:wasGeneratedBy",
        "prov:wasInformedBy",
        "prov:wasRevisionOf",
    }
)

# Deliberately duplicated from ``crew_executor`` rather than imported: DD-3
# requires zero ``probos`` imports. Drift is safe in one direction only, and
# this is that direction -- a stricter pattern here can only OMIT a triple
# from a read-only projection, never admit a bad write there.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_MAX_PATH_CHARS = 4096
_MAX_TIMESTAMP_CHARS = 64
_MAX_REVISION = 2**31 - 1


def _safe_id(value: Any) -> str | None:
    """Return ``value`` when it is a bounded identifier safe to put in a URN."""
    # Exact-type checks throughout: a ``str``/``dict``/``list`` SUBCLASS can
    # override the very operations used below and raise, which would break the
    # never-raises contract.
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        return None
    return value


def _safe_sha256(value: Any) -> str | None:
    """Return ``value`` when it is a full lowercase SHA-256 hex digest."""
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        return None
    return value


def _activity_iri(work_item_id: str) -> str:
    return f"urn:probos:activity:{work_item_id}"


def _agent_iri(agent_id: str) -> str:
    return f"urn:probos:agent:{agent_id}"


def _entity_iri(sha256_hex: str) -> str:
    return f"urn:probos:entity:{sha256_hex}"


def _record_entity_iri(path: str, revision: int) -> str:
    """Opaque IRI for revision ``revision`` of the record at ``path``.

    DD-6 forbids a filesystem path inside an IRI, so the identity string is
    hashed rather than embedded. The pre-image is exactly
    ``record:{path}@{revision}`` -- documented in
    ``docs/development/prov-o-mapping.md`` so any consumer can reproduce it.
    A full SHA-256 is used; ``compute_content_hash`` is deliberately NOT used
    because it truncates to 32 bits.
    """
    identity = f"record:{path}@{revision}"
    return _entity_iri(hashlib.sha256(identity.encode("utf-8")).hexdigest())


def _typed_datetime(iso_8601: str) -> dict[str, str]:
    return {"@value": iso_8601, "@type": "xsd:dateTime"}


def _iso_from_epoch(value: Any) -> str | None:
    """Render a POSIX timestamp as an ISO-8601 UTC instant, or ``None``."""
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        # NaN, infinity and out-of-range epochs have no ISO-8601 rendering.
        return None


def _iso_from_text(value: Any) -> str | None:
    """Return ``value`` verbatim when it already parses as ISO-8601."""
    if type(value) is not str or len(value) > _MAX_TIMESTAMP_CHARS:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _document(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"@context": dict(PROV_CONTEXT), "@graph": nodes}


def project_crew_execution(record: dict[str, Any]) -> dict[str, Any]:
    """Project one ``crew_execution`` evidence record onto PROV-O JSON-LD.

    Args:
        record: A ``crew_execution`` record (the frozen 14-key set). Read only;
            never mutated. Any other value projects to an empty graph.

    Returns:
        ``{"@context": ..., "@graph": [...]}``. Never raises. ``tokens_used``
        is deliberately absent (DD-5).
    """
    if type(record) is not dict:
        return _document([])

    work_item_id = _safe_id(record.get("work_item_id"))
    if work_item_id is None:
        # Without an Activity identity there is nothing to hang a triple on,
        # and inventing one would be the opposite of provenance.
        return _document([])

    activity_iri = _activity_iri(work_item_id)
    activity: dict[str, Any] = {"@id": activity_iri, "@type": "prov:Activity"}
    nodes: dict[str, dict[str, Any]] = {activity_iri: activity}

    assigned_to = _safe_id(record.get("assigned_to"))
    if assigned_to is not None:
        agent_iri = _agent_iri(assigned_to)
        activity["prov:wasAssociatedWith"] = {"@id": agent_iri}
        nodes.setdefault(
            agent_iri,
            {"@id": agent_iri, "@type": ["prov:Agent", "prov:SoftwareAgent"]},
        )

    parent_id = _safe_id(record.get("parent_id"))
    if parent_id is not None:
        parent_iri = _activity_iri(parent_id)
        activity["prov:wasInformedBy"] = {"@id": parent_iri}
        nodes.setdefault(parent_iri, {"@id": parent_iri, "@type": "prov:Activity"})

    tool_trace_ref = _safe_sha256(record.get("tool_trace_ref"))
    if tool_trace_ref is not None:
        trace_iri = _entity_iri(tool_trace_ref)
        activity["prov:used"] = {"@id": trace_iri}
        nodes.setdefault(trace_iri, {"@id": trace_iri, "@type": "prov:Entity"})

    artifact_refs = record.get("artifact_refs")
    if type(artifact_refs) is list:
        for ref in artifact_refs:
            if type(ref) is not dict:
                continue
            content_hash = _safe_sha256(ref.get("content_hash"))
            if content_hash is None:
                continue
            entity_iri = _entity_iri(content_hash)
            node = nodes.setdefault(
                entity_iri, {"@id": entity_iri, "@type": "prov:Entity"}
            )
            node["prov:wasGeneratedBy"] = {"@id": activity_iri}

    started_at = _iso_from_epoch(record.get("started_at"))
    if started_at is not None:
        activity["prov:startedAtTime"] = _typed_datetime(started_at)

    finished_at = _iso_from_epoch(record.get("finished_at"))
    if finished_at is not None:
        activity["prov:endedAtTime"] = _typed_datetime(finished_at)

    return _document(list(nodes.values()))


def project_record_frontmatter(
    path: str, frontmatter: dict[str, Any]
) -> dict[str, Any]:
    """Project one Ship's Records document's frontmatter onto PROV-O JSON-LD.

    Args:
        path: The repository-relative record path. Hashed into the entity IRI
            rather than embedded (DD-6).
        frontmatter: The parsed frontmatter mapping. Read only; never mutated.

    Returns:
        ``{"@context": ..., "@graph": [...]}``. Never raises.

    ``revision`` is absent on a first write and set by the store from
    revision 2 onward, so an absent key means revision 1 -- that is the store's
    own semantics, not a default invented here. A ``revision`` that is present
    but not a usable integer makes the entity's identity unknowable, so the
    projection asserts nothing at all rather than guessing a version.
    """
    if (
        type(path) is not str
        or not path
        or len(path) > _MAX_PATH_CHARS
        or type(frontmatter) is not dict
    ):
        return _document([])

    revision = frontmatter.get("revision", 1)
    # ``type(...) is int`` also excludes ``bool``, whose truth values would
    # silently become revisions 0 and 1.
    if type(revision) is not int or not 1 <= revision <= _MAX_REVISION:
        return _document([])

    entity_iri = _record_entity_iri(path, revision)
    entity: dict[str, Any] = {"@id": entity_iri, "@type": "prov:Entity"}
    nodes: dict[str, dict[str, Any]] = {entity_iri: entity}

    author = _safe_id(frontmatter.get("author"))
    if author is not None:
        agent_iri = _agent_iri(author)
        entity["prov:wasAttributedTo"] = {"@id": agent_iri}
        # ``prov:Agent`` only, never ``prov:SoftwareAgent``: a record author
        # may be the human Captain, and narrowing the type would assert
        # something this surface cannot know.
        nodes.setdefault(agent_iri, {"@id": agent_iri, "@type": "prov:Agent"})

    created = _iso_from_text(frontmatter.get("created"))
    if created is not None:
        entity["prov:generatedAtTime"] = _typed_datetime(created)

    if revision >= 2:
        previous_iri = _record_entity_iri(path, revision - 1)
        entity["prov:wasRevisionOf"] = {"@id": previous_iri}
        nodes.setdefault(previous_iri, {"@id": previous_iri, "@type": "prov:Entity"})

    return _document(list(nodes.values()))
