"""AD-1145: W3C PROV-O provenance projection.

Covers the pinned decisions: vocabulary validity against an explicit allowlist
(DD-1), honest omission over invention (DD-4), the BF-680 token exclusion
(DD-5), opaque full-width IRIs (DD-6), the default-OFF endpoint parameter
(DD-7), and the DD-3 purity invariant that makes the module vendorable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.knowledge.provo import (
    PROV_CONTEXT,
    PROV_NAMESPACE,
    PROV_TERMS,
    project_crew_execution,
    project_record_frontmatter,
)
from probos.routers.records import read_record

_PROVO_SOURCE = Path(__file__).resolve().parents[1] / "src" / "probos" / "knowledge" / "provo.py"

# A full SHA-256 digest (64 lowercase hex chars), the shape both
# ``tool_trace_ref`` and ``artifact_refs[].content_hash`` are validated to.
_TRACE_SHA = "a" * 64
_ARTIFACT_SHA = "b" * 64
_OTHER_SHA = "c" * 64

# Microsecond-exact so the ISO-8601 round-trip is bit-for-bit, not approximate.
_STARTED_AT = 1_752_000_000.5
_FINISHED_AT = 1_752_000_123.25


def _artifact_ref(content_hash: str = _ARTIFACT_SHA) -> dict[str, Any]:
    """One artifact ref with exactly the 7 keys ``crew_executor`` enforces."""
    return {
        "artifact_id": "art-1",
        "content_hash": content_hash,
        "thread_id": "thread-1",
        "name": "report.md",
        "mime": "text/markdown",
        "size_bytes": 128,
        "version": 1,
    }


def _crew_execution(**overrides: Any) -> dict[str, Any]:
    """A complete, valid ``crew_execution`` record -- the frozen 14-key set."""
    record: dict[str, Any] = {
        "version": 1,
        "parent_id": "WI-parent",
        "work_item_id": "WI-child",
        "thread_id": "thread-1",
        "assigned_to": "scotty",
        "status": "done",
        "stopped_reason": "complete",
        "output_summary": "did the thing",
        "tool_trace_ref": _TRACE_SHA,
        "artifact_refs": [_artifact_ref()],
        "tokens_used": 4321,
        "started_at": _STARTED_AT,
        "finished_at": _FINISHED_AT,
        "blocked_dependency_ids": [],
    }
    record.update(overrides)
    return record


def _nodes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["@id"]: node for node in document["@graph"]}


def _prov_strings(value: Any) -> set[str]:
    """Every ``prov:``-prefixed string anywhere in the document, key or value."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.startswith("prov:"):
                found.add(key)
            found |= _prov_strings(child)
    elif isinstance(value, list):
        for child in value:
            found |= _prov_strings(child)
    elif isinstance(value, str) and value.startswith("prov:"):
        found.add(value)
    return found


def _iris(document: dict[str, Any], prefix: str) -> set[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and value.startswith(prefix):
            found.add(value)

    walk(document)
    return found


# --------------------------------------------------------------------------- #
# The test fixture itself must track the frozen contract
# --------------------------------------------------------------------------- #


def test_crew_execution_fixture_matches_the_frozen_14_key_set() -> None:
    assert set(_crew_execution()) == {
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
    }
    assert len(_crew_execution()) == 14


# --------------------------------------------------------------------------- #
# Vocabulary validity (allowlist)
# --------------------------------------------------------------------------- #


def test_allowlist_is_exactly_the_thirteen_real_prov_o_terms() -> None:
    # Pinning the allowlist itself is what stops an invented ``prov:`` term
    # from shipping by simply being added to both the code and the subset test.
    assert PROV_TERMS == {
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


def test_crew_execution_emits_only_allowlisted_terms() -> None:
    emitted = _prov_strings(project_crew_execution(_crew_execution()))
    assert emitted
    assert emitted <= PROV_TERMS


def test_record_frontmatter_emits_only_allowlisted_terms() -> None:
    document = project_record_frontmatter(
        "notebooks/chapel/n1.md",
        {"author": "chapel", "created": "2026-07-26T10:00:00+00:00", "revision": 3},
    )
    emitted = _prov_strings(document)
    assert emitted
    assert emitted <= PROV_TERMS


def test_context_binds_the_real_prov_o_namespace() -> None:
    assert PROV_CONTEXT["prov"] == "http://www.w3.org/ns/prov#"
    assert PROV_NAMESPACE == "http://www.w3.org/ns/prov#"
    assert project_crew_execution(_crew_execution())["@context"] == PROV_CONTEXT


def test_context_is_copied_not_shared_so_a_caller_cannot_poison_it() -> None:
    document = project_crew_execution(_crew_execution())
    document["@context"]["prov"] = "http://evil.example/"
    assert PROV_CONTEXT["prov"] == "http://www.w3.org/ns/prov#"


# --------------------------------------------------------------------------- #
# Round-trip without loss
# --------------------------------------------------------------------------- #


def test_crew_execution_round_trips_every_projected_field() -> None:
    document = project_crew_execution(_crew_execution())
    nodes = _nodes(document)

    activity = nodes["urn:probos:activity:WI-child"]
    assert activity["@type"] == "prov:Activity"
    assert activity["prov:wasAssociatedWith"] == {"@id": "urn:probos:agent:scotty"}
    assert activity["prov:wasInformedBy"] == {"@id": "urn:probos:activity:WI-parent"}
    assert activity["prov:used"] == {"@id": f"urn:probos:entity:{_TRACE_SHA}"}

    assert nodes["urn:probos:agent:scotty"]["@type"] == [
        "prov:Agent",
        "prov:SoftwareAgent",
    ]
    assert nodes[f"urn:probos:entity:{_ARTIFACT_SHA}"]["prov:wasGeneratedBy"] == {
        "@id": "urn:probos:activity:WI-child"
    }


def test_timestamps_round_trip_through_iso_8601_to_the_same_float() -> None:
    from datetime import datetime

    activity = _nodes(project_crew_execution(_crew_execution()))[
        "urn:probos:activity:WI-child"
    ]
    started = activity["prov:startedAtTime"]
    ended = activity["prov:endedAtTime"]

    assert started["@type"] == "xsd:dateTime"
    assert ended["@type"] == "xsd:dateTime"
    assert datetime.fromisoformat(started["@value"]).timestamp() == _STARTED_AT
    assert datetime.fromisoformat(ended["@value"]).timestamp() == _FINISHED_AT


def test_every_artifact_ref_becomes_a_generated_entity() -> None:
    record = _crew_execution(
        artifact_refs=[_artifact_ref(_ARTIFACT_SHA), _artifact_ref(_OTHER_SHA)]
    )
    nodes = _nodes(project_crew_execution(record))
    for sha in (_ARTIFACT_SHA, _OTHER_SHA):
        assert nodes[f"urn:probos:entity:{sha}"]["prov:wasGeneratedBy"] == {
            "@id": "urn:probos:activity:WI-child"
        }


def test_repeated_artifact_hash_merges_into_one_node() -> None:
    record = _crew_execution(
        artifact_refs=[_artifact_ref(_ARTIFACT_SHA), _artifact_ref(_ARTIFACT_SHA)]
    )
    document = project_crew_execution(record)
    ids = [node["@id"] for node in document["@graph"]]
    assert len(ids) == len(set(ids))


def test_trace_ref_that_equals_an_artifact_hash_merges_into_one_node() -> None:
    record = _crew_execution(
        tool_trace_ref=_ARTIFACT_SHA, artifact_refs=[_artifact_ref(_ARTIFACT_SHA)]
    )
    document = project_crew_execution(record)
    ids = [node["@id"] for node in document["@graph"]]
    assert len(ids) == len(set(ids))
    node = _nodes(document)[f"urn:probos:entity:{_ARTIFACT_SHA}"]
    assert node["@type"] == "prov:Entity"
    assert node["prov:wasGeneratedBy"] == {"@id": "urn:probos:activity:WI-child"}


def test_projection_does_not_mutate_the_source_record() -> None:
    record = _crew_execution()
    before = json.dumps(record, sort_keys=True)
    project_crew_execution(record)
    assert json.dumps(record, sort_keys=True) == before


def test_record_frontmatter_round_trips_author_created_and_revision() -> None:
    created = "2026-07-26T10:00:00+00:00"
    document = project_record_frontmatter(
        "notebooks/chapel/n1.md",
        {"author": "chapel", "created": created, "revision": 3},
    )
    nodes = _nodes(document)
    entity = next(n for n in nodes.values() if "prov:wasAttributedTo" in n)

    assert entity["@type"] == "prov:Entity"
    assert entity["prov:wasAttributedTo"] == {"@id": "urn:probos:agent:chapel"}
    assert entity["prov:generatedAtTime"] == {
        "@value": created,
        "@type": "xsd:dateTime",
    }
    assert entity["prov:wasRevisionOf"]["@id"] in nodes


def test_revision_chain_links_n_to_n_minus_one() -> None:
    frontmatter = {"author": "chapel", "revision": 4}
    path = "notebooks/chapel/n1.md"
    at_4 = project_record_frontmatter(path, frontmatter)
    at_3 = project_record_frontmatter(path, {**frontmatter, "revision": 3})

    entity_4 = next(n for n in at_4["@graph"] if "prov:wasRevisionOf" in n)
    entity_3 = next(n for n in at_3["@graph"] if "prov:wasRevisionOf" in n)
    # Revision 4's predecessor IRI is exactly revision 3's own IRI.
    assert entity_4["prov:wasRevisionOf"]["@id"] == entity_3["@id"]


def test_record_author_is_a_plain_agent_not_a_software_agent() -> None:
    # A record author may be the human Captain; narrowing to SoftwareAgent
    # would assert something this surface cannot know.
    document = project_record_frontmatter("captains-log/c1.md", {"author": "captain"})
    agent = _nodes(document)["urn:probos:agent:captain"]
    assert agent["@type"] == "prov:Agent"


# --------------------------------------------------------------------------- #
# DD-5 / BF-680 -- no token counts, ever
# --------------------------------------------------------------------------- #


def test_tokens_used_and_token_source_appear_nowhere_in_projected_output() -> None:
    record = _crew_execution(tokens_used=987654321)
    record["token_source"] = "estimated"  # even if a caller smuggles it in
    serialized = json.dumps(project_crew_execution(record))

    assert "tokens_used" not in serialized
    assert "token_source" not in serialized
    assert "987654321" not in serialized
    assert "estimated" not in serialized


def test_token_terms_absent_from_record_frontmatter_projection() -> None:
    serialized = json.dumps(
        project_record_frontmatter(
            "n1.md",
            {"author": "chapel", "tokens_used": 5, "token_source": "measured"},
        )
    )
    assert "tokens_used" not in serialized
    assert "token_source" not in serialized


# --------------------------------------------------------------------------- #
# DD-4 -- honest omission over invention
# --------------------------------------------------------------------------- #


def test_unassigned_execution_emits_no_agent_and_no_association() -> None:
    document = project_crew_execution(_crew_execution(assigned_to=None))
    serialized = json.dumps(document)

    assert "prov:wasAssociatedWith" not in serialized
    assert "urn:probos:agent:" not in serialized
    assert "prov:Agent" not in serialized
    # The activity itself still projects -- only the unknown agent is omitted.
    assert "urn:probos:activity:WI-child" in _nodes(document)


def test_empty_artifact_refs_emits_no_generated_entities() -> None:
    document = project_crew_execution(_crew_execution(artifact_refs=[]))
    assert "prov:wasGeneratedBy" not in json.dumps(document)


def test_absent_parent_emits_no_was_informed_by() -> None:
    document = project_crew_execution(_crew_execution(parent_id=None))
    assert "prov:wasInformedBy" not in json.dumps(document)


def test_absent_tool_trace_ref_emits_no_used_edge() -> None:
    document = project_crew_execution(_crew_execution(tool_trace_ref=None))
    assert "prov:used" not in json.dumps(document)


def test_first_revision_emits_no_was_revision_of() -> None:
    for frontmatter in ({"author": "chapel"}, {"author": "chapel", "revision": 1}):
        document = project_record_frontmatter("n1.md", frontmatter)
        assert "prov:wasRevisionOf" not in json.dumps(document)


def test_absent_author_emits_no_attribution() -> None:
    document = project_record_frontmatter("n1.md", {"created": "2026-07-26T10:00:00+00:00"})
    serialized = json.dumps(document)
    assert "prov:wasAttributedTo" not in serialized
    assert "urn:probos:agent:" not in serialized


def test_malformed_created_emits_no_generation_time() -> None:
    document = project_record_frontmatter("n1.md", {"author": "chapel", "created": "not-a-date"})
    assert "prov:generatedAtTime" not in json.dumps(document)


def test_unknowable_revision_asserts_nothing_rather_than_guessing() -> None:
    # A present-but-unusable revision makes the entity's identity unknowable,
    # so no IRI is invented for it.
    for bad in ("3", 0, -1, None, 2.0, True):
        document = project_record_frontmatter("n1.md", {"author": "chapel", "revision": bad})
        assert document["@graph"] == []


# --------------------------------------------------------------------------- #
# DD-6 -- opaque, full-width, namespaced IRIs
# --------------------------------------------------------------------------- #


def test_entity_iris_carry_a_full_sha256_never_a_truncated_hash() -> None:
    documents = [
        project_crew_execution(_crew_execution()),
        project_record_frontmatter("notebooks/chapel/n1.md", {"author": "chapel", "revision": 2}),
    ]
    entity_iris = set()
    for document in documents:
        entity_iris |= _iris(document, "urn:probos:entity:")
    assert entity_iris
    for iri in entity_iris:
        digest = iri.rsplit(":", 1)[1]
        # 64 hex chars -- ``compute_content_hash``'s 32-bit truncation would
        # produce 8 and is unusable as a global identifier.
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


def test_record_iri_does_not_leak_the_filesystem_path() -> None:
    path = "notebooks/chapel/secret-topic.md"
    serialized = json.dumps(project_record_frontmatter(path, {"author": "chapel"}))
    assert path not in serialized
    assert "secret-topic" not in serialized
    assert "notebooks" not in serialized


def test_record_iri_is_deterministic_and_path_sensitive() -> None:
    a1 = project_record_frontmatter("a.md", {"author": "chapel"})
    a2 = project_record_frontmatter("a.md", {"author": "chapel"})
    b = project_record_frontmatter("b.md", {"author": "chapel"})
    assert a1 == a2
    assert a1 != b


def test_every_iri_is_namespaced_under_urn_probos() -> None:
    document = project_crew_execution(_crew_execution())
    for node in document["@graph"]:
        assert node["@id"].startswith("urn:probos:")


# --------------------------------------------------------------------------- #
# Never raises
# --------------------------------------------------------------------------- #


class _HostileDict(dict):
    """A dict subclass whose accessors raise -- must never be walked."""

    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("hostile get")

    def items(self) -> Any:
        raise RuntimeError("hostile items")


class _HostileStr(str):
    """A str subclass whose comparison machinery raises."""

    def __eq__(self, other: Any) -> bool:
        raise RuntimeError("hostile eq")

    def __hash__(self) -> int:
        raise RuntimeError("hostile hash")


@pytest.mark.parametrize(
    "record",
    [
        {},
        None,
        [],
        "not-a-record",
        42,
        _HostileDict({"work_item_id": "WI-1"}),
        {"work_item_id": None},
        {"work_item_id": ""},
        {"work_item_id": "a" * 200},
        {"work_item_id": "has spaces"},
        {"work_item_id": "WI-1", "assigned_to": 17},
        {"work_item_id": "WI-1", "parent_id": ["nope"]},
        {"work_item_id": "WI-1", "tool_trace_ref": "short"},
        {"work_item_id": "WI-1", "tool_trace_ref": "A" * 64},
        {"work_item_id": "WI-1", "artifact_refs": "not-a-list"},
        {"work_item_id": "WI-1", "artifact_refs": [None, 3, "x", {}]},
        {"work_item_id": "WI-1", "artifact_refs": [_HostileDict()]},
        {"work_item_id": "WI-1", "started_at": float("nan")},
        {"work_item_id": "WI-1", "started_at": float("inf")},
        {"work_item_id": "WI-1", "started_at": 1e300},
        {"work_item_id": "WI-1", "finished_at": "yesterday"},
        {"work_item_id": "WI-1", "started_at": True},
    ],
)
def test_crew_execution_never_raises_and_always_returns_a_document(record: Any) -> None:
    document = project_crew_execution(record)
    assert set(document) == {"@context", "@graph"}
    assert isinstance(document["@graph"], list)
    json.dumps(document)  # always serializable


@pytest.mark.parametrize(
    ("path", "frontmatter"),
    [
        ("n1.md", {}),
        ("", {"author": "chapel"}),
        (None, {"author": "chapel"}),
        (17, {"author": "chapel"}),
        ("a" * 5000, {"author": "chapel"}),
        ("n1.md", None),
        ("n1.md", "not-a-dict"),
        ("n1.md", _HostileDict()),
        ("n1.md", {"author": 42}),
        ("n1.md", {"author": "has spaces"}),
        ("n1.md", {"author": "a" * 200}),
        ("n1.md", {"created": 12345}),
        ("n1.md", {"created": "x" * 500}),
        ("n1.md", {"revision": "many"}),
        ("n1.md", {"revision": 2**62}),
        (_HostileStr("n1.md"), {"author": "chapel"}),
    ],
)
def test_record_frontmatter_never_raises_and_always_returns_a_document(
    path: Any, frontmatter: Any
) -> None:
    document = project_record_frontmatter(path, frontmatter)
    assert set(document) == {"@context", "@graph"}
    assert isinstance(document["@graph"], list)
    json.dumps(document)


def test_unidentifiable_activity_projects_an_empty_graph() -> None:
    assert project_crew_execution({"assigned_to": "scotty"})["@graph"] == []


# --------------------------------------------------------------------------- #
# DD-3 purity invariant -- the module must be vendorable verbatim
# --------------------------------------------------------------------------- #


def test_provo_module_has_zero_project_imports() -> None:
    source = _PROVO_SOURCE.read_text(encoding="utf-8")
    assert "import probos" not in source
    assert "from probos" not in source


def test_provo_module_imports_only_the_standard_library() -> None:
    import ast

    tree = ast.parse(_PROVO_SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "hashlib", "re", "datetime", "typing"}


# --------------------------------------------------------------------------- #
# DD-7 -- the endpoint parameter is additive and default-OFF
# --------------------------------------------------------------------------- #


class _FakeStore:
    def __init__(self, entry: Any) -> None:
        self._entry = entry
        self.calls: list[tuple[str, str]] = []

    async def read_entry(self, path: str, reader_id: str = "captain") -> Any:
        self.calls.append((path, reader_id))
        return self._entry


def _runtime(store: Any) -> MagicMock:
    rt = MagicMock()
    rt._records_store = store
    return rt


def _entry() -> dict[str, Any]:
    return {
        "frontmatter": {
            "author": "chapel",
            "created": "2026-07-26T10:00:00+00:00",
            "revision": 2,
        },
        "content": "# Notes\n",
        "path": "notebooks/chapel/n1.md",
    }


@pytest.mark.asyncio
async def test_read_record_without_format_is_byte_identical_to_the_store_entry() -> None:
    entry = _entry()
    expected = json.dumps(entry, sort_keys=True)
    result = await read_record("notebooks/chapel/n1.md", runtime=_runtime(_FakeStore(entry)))
    # Identity, not just equality: the projection is never in the path.
    assert result is entry
    assert json.dumps(result, sort_keys=True) == expected


@pytest.mark.asyncio
async def test_read_record_with_explicitly_empty_format_is_still_inert() -> None:
    entry = _entry()
    result = await read_record(
        "notebooks/chapel/n1.md", format="", runtime=_runtime(_FakeStore(entry))
    )
    assert result is entry


@pytest.mark.asyncio
async def test_read_record_with_prov_jsonld_returns_the_projection() -> None:
    result = await read_record(
        "notebooks/chapel/n1.md",
        format="prov-jsonld",
        runtime=_runtime(_FakeStore(_entry())),
    )
    assert set(result) == {"@context", "@graph"}
    assert result["@context"]["prov"] == PROV_NAMESPACE
    assert _prov_strings(result) <= PROV_TERMS
    assert "# Notes" not in json.dumps(result)


@pytest.mark.asyncio
async def test_read_record_rejects_an_unsupported_format() -> None:
    store = _FakeStore(_entry())
    result = await read_record(
        "notebooks/chapel/n1.md", format="rdf-xml", runtime=_runtime(store)
    )
    assert getattr(result, "status_code", 200) == 400
    assert store.calls == []  # rejected before any read


@pytest.mark.asyncio
async def test_read_record_still_503s_without_a_store_even_when_format_is_set() -> None:
    rt = MagicMock()
    rt._records_store = None
    result = await read_record("n1.md", format="prov-jsonld", runtime=rt)
    assert getattr(result, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_read_record_still_404s_when_projection_is_requested_for_a_missing_doc() -> None:
    result = await read_record(
        "missing.md", format="prov-jsonld", runtime=_runtime(_FakeStore(None))
    )
    assert getattr(result, "status_code", 200) == 404


@pytest.mark.asyncio
async def test_read_record_preserves_the_reader_argument() -> None:
    store = _FakeStore(_entry())
    await read_record("n1.md", reader="chapel", runtime=_runtime(store))
    assert store.calls == [("n1.md", "chapel")]
