"""AD-1140 ``publish_finding`` — the write half of Σ.

Real ``ToolRegistry`` / ``ToolPermissionStore`` / ``RecordsStore`` throughout
(BF-287) — no mock stands in at the registry or the store boundary, because the
department gate, the AD-550 dedup layers and the frontmatter round trip are
exactly the things a mock would paper over.

The headline is a genuine round trip: agent A publishes, then a **freshly
constructed** ``SemanticKnowledgeLayer`` + ``OracleService`` over the same
on-disk paths (standing in for a later session) serve the claim to agent B.
Proven on both retrieval paths, because the capability must not be contingent
on ChromaDB being healthy.
"""

from __future__ import annotations

import sys
import yaml
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    _GATED_TOOL_IDS,
    WorkItemAgenticExecutor,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.oracle_service import (
    OracleService,
    _RECORDS_QUERY_SCOPE,
    make_reader_identity_resolver,
)
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.config import AgenticToolsConfig, RecordsConfig, SystemConfig
from probos.knowledge.records_store import (
    _CLASSIFICATION_LEVELS,
    _RESERVED_FRONTMATTER_KEYS,
    RecordsStore,
)
from probos.knowledge.semantic import (
    SemanticKnowledgeLayer,
    build_records_scope_filter,
)
from probos.startup.communication import _register_publish_finding_tool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.publish_finding_tool import (
    CLAIM_VERSION,
    FINDING_TAG,
    _ALLOWED_KEYS,
    _CALLSIGN_RE,
    _DUPLICATE_DISPOSITION,
    _FLEET_DISPOSITION,
    _HEADER,
    _MAX_BASIS_CHARS,
    _MAX_TAGS,
    _MAX_TAG_CHARS,
    _MAX_TITLE_CHARS,
    _MAX_TRACKED_AUTHORS,
    _RATE_LIMITED_DISPOSITION,
    _SUCCESS_DISPOSITION,
    _TOOL_DESCRIPTION,
    PublishFindingTool,
    compute_claim_id,
)
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

_ALL_DEPARTMENTS = (
    "engineering",
    "science",
    "medical",
    "security",
    "operations",
    "bridge",
)

# Subjects with disjoint vocabulary, so a sequence of publishes by ONE author
# stays under the AD-550 Jaccard threshold and the DD-7 rate limit is what the
# test actually exercises. (Near-identical bodies are covered separately.)
_DISTINCT_SUBJECTS = (
    "coolant", "gyroscope", "transponder", "airlock", "hydroponics",
    "shielding", "manifold", "telescope", "ballast", "antenna",
    "cryostat", "flywheel", "periscope",
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    """Real store. ``auto_commit=False`` matches ``test_ad1138``'s fixture so
    ``initialize()``'s unconditional ``git init`` is the only git cost."""
    store = RecordsStore(
        RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False)
    )
    await store.initialize()
    return store


class _StaticResolver:
    """``agent_id -> (callsign, department)`` with a recorded call list."""

    def __init__(self, mapping: dict[str, tuple[str, str]]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def __call__(self, agent_id: str) -> tuple[str, str]:
        self.calls.append(agent_id)
        return self._mapping.get(agent_id, ("", ""))


class _RaisingResolver:
    def __call__(self, agent_id: str) -> tuple[str, str]:
        raise RuntimeError("identity service is down")


class _RecordingQuality:
    def __init__(self) -> None:
        self.events: list[str] = []

    def record_event(self, event_type: str, **_kw: Any) -> None:
        self.events.append(event_type)


class _RecordingEpisodic:
    """DD-8: any touch of the sovereign shard is a test failure."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def store(self, *_a: Any, **_kw: Any) -> None:
        self.calls.append("store")

    async def recall(self, *_a: Any, **_kw: Any) -> list[Any]:
        self.calls.append("recall")
        return []

    async def recall_for_agent_scored(self, *_a: Any, **_kw: Any) -> list[Any]:
        self.calls.append("recall_for_agent_scored")
        return []


def _tool(
    records_store: Any,
    *,
    mapping: dict[str, tuple[str, str]] | None = None,
    resolver: Any = None,
    max_per_hour: int = 12,
    max_content_chars: int = 4000,
    quality_engine: Any = None,
    source_node: str = "node-1",
    **kw: Any,
) -> PublishFindingTool:
    return PublishFindingTool(
        records_store=records_store,
        callsign_resolver=resolver
        or _StaticResolver(mapping or {"agent-a": ("SCOUT", "science")}),
        source_node=source_node,
        max_per_hour=max_per_hour,
        max_content_chars=max_content_chars,
        quality_engine=quality_engine,
        **kw,
    )


def _params(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Coolant loop harmonics",
        "claim": "The port coolant loop resonates at 4.2 kHz under sustained load.",
        "basis": "Observed across nine sensor sweeps during the deck-twelve survey.",
    }
    base.update(over)
    return base


def _ctx(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"agent_id": "agent-a"}
    base.update(over)
    return base


def _notebook_files(store: RecordsStore) -> list[Path]:
    return sorted((store.repo_path / "notebooks").rglob("*.md"))


async def _read_written(store: RecordsStore, path: str) -> dict[str, Any]:
    entry = await store.read_entry(path, reader_id="captain")
    assert entry is not None
    return entry


# ---------------------------------------------------------------------------
# DD-2 — framing, and the gap regex
# ---------------------------------------------------------------------------

def test_every_module_authored_string_is_clean_under_the_real_gap_regex() -> None:
    """The regex is imported, never re-typed — a copy would drift silently."""
    module = sys.modules["probos.tools.publish_finding_tool"]
    authored = {
        name: value
        for name, value in vars(module).items()
        if type(value) is str and not name.startswith("__")
    }
    # Sanity: the scan actually reaches the strings it claims to.
    assert {"_SUCCESS_DISPOSITION", "_FLEET_DISPOSITION", "_HEADER"} <= set(authored)
    offenders = {
        name: _CAPABILITY_GAP_RE.search(value).group(0)  # type: ignore[union-attr]
        for name, value in authored.items()
        if _CAPABILITY_GAP_RE.search(value)
    }
    assert offenders == {}


def test_the_gap_regex_really_would_catch_the_phrasings_this_module_avoids() -> None:
    """Guards the guard: prove the regex is live, not a no-op import.

    ``lack`` is a bare substring, so ordinary prose about a missing transport
    trips it — including inside ``black hole``, which is the phrase the DD-4
    rationale uses in prose and which therefore must never reach an agent.
    """
    for phrase in ("cannot", "unable to", "no mechanism", "black hole", "lacks"):
        assert _CAPABILITY_GAP_RE.search(phrase) is not None


def test_tool_description_is_framed_and_names_the_durable_outcome() -> None:
    assert _CAPABILITY_GAP_RE.search(_TOOL_DESCRIPTION) is None
    assert "Ship's Records" in _TOOL_DESCRIPTION
    assert "later session" in _TOOL_DESCRIPTION


@pytest.mark.asyncio
async def test_success_output_carries_the_disposition_framing(records) -> None:
    result = await _tool(records).invoke(_params(), _ctx())

    assert result.error is None
    assert _HEADER in result.output
    assert _SUCCESS_DISPOSITION.format(classification="ship") in result.output
    assert "later session" in result.output
    assert _CAPABILITY_GAP_RE.search(result.output) is None


@pytest.mark.asyncio
async def test_every_rendered_output_shape_is_gap_regex_clean(records) -> None:
    """Success / duplicate / rate-limited / fleet / refusal, all rendered."""
    tool = _tool(records, max_per_hour=1)
    rendered: list[str] = []

    rendered.append((await tool.invoke(_params(), _ctx())).output)
    rendered.append((await tool.invoke(_params(), _ctx())).output)  # rate-limited

    fleet_tool = _tool(records, max_per_hour=9)
    rendered.append(
        (
            await fleet_tool.invoke(
                _params(title="Fleet doctrine", classification="fleet"), _ctx()
            )
        ).output
    )
    dup = await fleet_tool.invoke(_params(title="Fleet doctrine",
                                          classification="fleet"), _ctx())
    rendered.append(dup.output)

    assert all(text for text in rendered)
    for text in rendered:
        assert _CAPABILITY_GAP_RE.search(text) is None


# ---------------------------------------------------------------------------
# DD-3 — the envelope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_envelope_round_trips_losslessly_through_yaml(records) -> None:
    result = await _tool(records).invoke(
        _params(confidence=0.85, tags=["coolant", "deck-twelve"]),
        _ctx(_crew_session_id="sess-7", _crew_work_item_id="wi-9"),
    )
    entry = await _read_written(records, result.metadata["path"])
    fm = entry["frontmatter"]

    assert fm["author"] == "SCOUT"
    assert fm["department"] == "science"
    assert fm["classification"] == "ship"
    assert fm["claim_id"] == result.metadata["claim_id"]
    assert fm["claim_version"] == CLAIM_VERSION
    assert fm["confidence"] == 0.85
    assert fm["basis"].startswith("Observed across nine")
    assert fm["requested_scope"] == "ship"
    assert fm["source_node"] == "node-1"
    assert fm["session_id"] == "sess-7"
    assert fm["work_item_id"] == "wi-9"
    assert fm["contest_state"] == "uncontested"
    assert fm["half_life_days"] == 0
    assert FINDING_TAG in fm["tags"]
    assert set(fm["tags"]) == {FINDING_TAG, "coolant", "deck-twelve"}

    # Every value survives a real dump/load cycle as a plain scalar.
    reloaded = yaml.safe_load(yaml.dump(fm, sort_keys=False))
    assert reloaded == fm
    for key, value in fm.items():
        assert type(value) in (str, int, float, bool, list), (key, type(value))


@pytest.mark.asyncio
async def test_body_is_the_claim_text_so_every_retrieval_path_sees_it(records) -> None:
    result = await _tool(records).invoke(_params(), _ctx())
    entry = await _read_written(records, result.metadata["path"])

    assert "resonates at 4.2 kHz" in entry["content"]
    assert "Coolant loop harmonics" in entry["content"]
    assert "Observed across nine sensor sweeps" in entry["content"]


def test_claim_id_is_stable_for_the_same_triple_and_moves_for_any_change() -> None:
    base = compute_claim_id("t", "c", "b")

    assert base == compute_claim_id("t", "c", "b")
    assert len(base) == 64
    assert base != compute_claim_id("T", "c", "b")
    assert base != compute_claim_id("t", "C", "b")
    assert base != compute_claim_id("t", "c", "B")


@pytest.mark.asyncio
async def test_system_owned_fields_are_rejected_not_dropped(records) -> None:
    """DD-3 anti-spoof. Rejection, and *nothing written* — a dropped ``author``
    would let the agent believe it stamped provenance it did not."""
    tool = _tool(records)
    for spoof in (
        "author", "claim_id", "source_node", "session_id", "created",
        "revision", "department", "work_item_id", "requested_scope",
    ):
        result = await tool.invoke(_params(**{spoof: "forged"}), _ctx())
        assert result.error == "publish_finding_invalid:parameter", spoof
        assert _notebook_files(records) == [], spoof


def test_allowed_key_set_is_exactly_the_agent_supplied_schema() -> None:
    assert _ALLOWED_KEYS == frozenset(
        {"title", "claim", "basis", "confidence", "classification", "tags"}
    )


@pytest.mark.asyncio
async def test_department_comes_from_context_when_the_resolver_has_none(
    records,
) -> None:
    tool = _tool(records, mapping={"agent-a": ("SCOUT", "")})
    result = await tool.invoke(_params(), _ctx(department="medical"))
    entry = await _read_written(records, result.metadata["path"])

    assert entry["frontmatter"]["department"] == "medical"


@pytest.mark.asyncio
async def test_missing_session_linkage_is_written_empty_never_fabricated(
    records,
) -> None:
    result = await _tool(records).invoke(_params(), _ctx())
    fm = (await _read_written(records, result.metadata["path"]))["frontmatter"]

    assert fm["session_id"] == ""
    assert fm["work_item_id"] == ""


# ---------------------------------------------------------------------------
# DD-4 — fleet
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fleet_is_written_at_ship_scope_and_stamped_as_requested(
    records,
) -> None:
    result = await _tool(records).invoke(
        _params(classification="fleet"), _ctx()
    )
    fm = (await _read_written(records, result.metadata["path"]))["frontmatter"]

    assert fm["classification"] == "ship"
    assert fm["requested_scope"] == "fleet"
    assert result.metadata["classification"] == "ship"
    assert result.metadata["requested_scope"] == "fleet"


@pytest.mark.asyncio
async def test_fleet_confirmation_is_truthful_about_what_actually_happened(
    records,
) -> None:
    result = await _tool(records).invoke(
        _params(classification="fleet"), _ctx()
    )
    assert _FLEET_DISPOSITION in result.output
    assert "ship scope" in result.output
    assert "marked for fleet distribution" in result.output
    assert _CAPABILITY_GAP_RE.search(result.output) is None


@pytest.mark.asyncio
async def test_a_fleet_request_stays_retrievable_through_tier_2(records) -> None:
    """The whole point of DD-4: the claim must be reachable, not merely durable."""
    await _tool(records).invoke(
        _params(title="Fleet doctrine", claim="Convoy spacing holds at nine km.",
                classification="fleet"),
        _ctx(),
    )
    hits = await records.search(
        "convoy spacing", scope=_RECORDS_QUERY_SCOPE,
        reader_id="SCOUT", reader_department="science",
    )
    assert [h["path"] for h in hits]


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["private", "department", "ship"])
async def test_non_fleet_classifications_round_trip_unchanged(records, level) -> None:
    result = await _tool(records).invoke(
        _params(title=f"Finding {level}", classification=level), _ctx()
    )
    fm = (await _read_written(records, result.metadata["path"]))["frontmatter"]

    assert fm["classification"] == level
    assert fm["requested_scope"] == level


@pytest.mark.asyncio
async def test_unknown_classification_is_refused_with_no_write(records) -> None:
    result = await _tool(records).invoke(
        _params(classification="galactic"), _ctx()
    )
    assert result.error == "publish_finding_invalid:classification"
    assert _notebook_files(records) == []


@pytest.mark.asyncio
async def test_tier_2_really_does_exclude_a_fleet_record_today(records) -> None:
    """Regression guard: this is *why* DD-4 exists.

    BF-679 added reader identity to both records paths; it did **not** change
    the classification ordering, so ``fleet`` (level 3) still sits above the
    ``ship`` (level 2) scope both Tier 2 paths query at — for every reader,
    including the Captain. If a future fix makes ``fleet`` reachable, this test
    goes red and forces DD-4 to be revisited rather than silently leaving the
    tool writing a narrower scope than the agent asked for.
    """
    await records.write_entry(
        author="dave", path="reports/fleet-doctrine.md",
        content="convoy spacing doctrine shared across the fleet",
        message="fleet", classification="fleet",
    )
    assert _CLASSIFICATION_LEVELS["fleet"] > _CLASSIFICATION_LEVELS["ship"]

    for reader in (None, "", "captain", "dave"):
        hits = await records.search(
            "convoy spacing", scope=_RECORDS_QUERY_SCOPE, reader_id=reader,
        )
        assert hits == [], reader
        permitted = build_records_scope_filter(
            _RECORDS_QUERY_SCOPE, reader_id=reader,
        )
        assert "fleet" not in str(permitted), reader


def test_no_federation_module_is_imported_by_the_tool() -> None:
    module = sys.modules["probos.tools.publish_finding_tool"]
    for name, value in vars(module).items():
        origin = getattr(value, "__module__", "") or ""
        assert "federation" not in str(origin).lower(), name

    # Belt-and-braces over the *statements*, so a deferred in-function import
    # is caught too. The prose docstring names the package deliberately.
    import ast

    tree = ast.parse(
        Path(module.__file__).read_text(encoding="utf-8"),  # type: ignore[arg-type]
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported
    assert not any("federation" in name for name in imported), imported
    assert not any("episodic" in name for name in imported), imported


# ---------------------------------------------------------------------------
# DD-6 — idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publishing_identical_content_twice_writes_exactly_one_file(
    records,
) -> None:
    tool = _tool(records)
    first = await tool.invoke(_params(), _ctx())
    second = await tool.invoke(_params(), _ctx())

    assert first.metadata["published"] is True
    assert second.metadata["published"] is False
    assert second.metadata["reason"] == "duplicate"
    assert first.metadata["path"] in second.output
    assert (
        _DUPLICATE_DISPOSITION.format(path=first.metadata["path"])
        in second.output
    )
    assert len(_notebook_files(records)) == 1


@pytest.mark.asyncio
async def test_near_identical_content_is_suppressed_by_the_cross_topic_layer(
    records,
) -> None:
    """Different title ⇒ different claim_id ⇒ different slug, so Layer 2 misses
    and Layer 3's cross-topic Jaccard scan is what catches it."""
    tool = _tool(records)
    body = (
        "The port coolant loop resonates at 4.2 kHz under sustained load and "
        "the resonance grows with deck temperature across every observed sweep."
    )
    first = await tool.invoke(_params(title="Harmonics one", claim=body), _ctx())
    second = await tool.invoke(_params(title="Harmonics two", claim=body), _ctx())

    assert first.metadata["published"] is True
    assert second.metadata["published"] is False
    assert second.metadata["reason"] == "duplicate"
    assert len(_notebook_files(records)) == 1


@pytest.mark.asyncio
async def test_genuinely_different_findings_both_land(records) -> None:
    tool = _tool(records)
    a = await tool.invoke(_params(), _ctx())
    b = await tool.invoke(
        _params(
            title="Sensor drift",
            claim="Lateral sensor array drifts two degrees per watch cycle.",
            basis="Compared against the navigational fix log for six watches.",
        ),
        _ctx(),
    )

    assert a.metadata["published"] is True
    assert b.metadata["published"] is True
    assert a.metadata["path"] != b.metadata["path"]
    assert len(_notebook_files(records)) == 2


@pytest.mark.asyncio
async def test_a_raising_dedup_gate_degrades_to_write(records, caplog) -> None:
    """Matches ``proactive.py``: a broken guard must not discard a finding."""

    async def _boom(**_kw: Any) -> dict[str, Any]:
        raise RuntimeError("dedup index corrupted")

    records.check_notebook_similarity = _boom  # type: ignore[method-assign]
    with caplog.at_level("WARNING"):
        result = await _tool(records).invoke(_params(), _ctx())

    assert result.metadata["published"] is True
    assert len(_notebook_files(records)) == 1
    assert any("AD-1140" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_slug_is_content_addressed_and_path_safe(records) -> None:
    result = await _tool(records).invoke(_params(), _ctx())
    path = result.metadata["path"]

    assert path.startswith("notebooks/SCOUT/")
    assert path.endswith(".md")
    assert result.metadata["claim_id"][:8] in path


@pytest.mark.asyncio
async def test_a_title_that_slugifies_to_nothing_is_refused(records) -> None:
    result = await _tool(records).invoke(_params(title="!!! ???"), _ctx())

    assert result.error == "publish_finding_invalid:title"
    assert _notebook_files(records) == []


# ---------------------------------------------------------------------------
# DD-7 — abuse bounds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_thirteenth_publish_in_an_hour_is_refused_without_a_write(
    records,
) -> None:
    tool = _tool(records, max_per_hour=12)
    for n, subject in enumerate(_DISTINCT_SUBJECTS[:12]):
        result = await tool.invoke(
            _params(
                title=f"Finding {n} {subject}",
                claim=f"The {subject} reading held steady through watch {n}.",
                basis=f"Cross-checked the {subject} log against the duty roster.",
            ),
            _ctx(),
        )
        assert result.metadata["published"] is True, (n, subject)

    before = len(_notebook_files(records))
    assert before == 12
    refused = await tool.invoke(
        _params(
            title="Finding 13 turbolift",
            claim="The turbolift governor trips above deck nineteen.",
            basis="Traced the governor fault log across two shifts.",
        ),
        _ctx(),
    )

    assert refused.error is None  # framed output, never an error (no retry loop)
    assert refused.metadata == {"published": False, "reason": "rate_limited"}
    assert _RATE_LIMITED_DISPOSITION in refused.output
    assert "publication budget" in refused.output
    assert len(_notebook_files(records)) == before


@pytest.mark.asyncio
async def test_the_rate_limit_is_per_author(records) -> None:
    tool = _tool(
        records,
        mapping={"agent-a": ("SCOUT", "science"), "agent-b": ("PROBE", "engineering")},
        max_per_hour=1,
    )
    await tool.invoke(_params(), _ctx())
    blocked = await tool.invoke(_params(title="Second"), _ctx())
    other = await tool.invoke(
        _params(title="Other author claim"), _ctx(agent_id="agent-b")
    )

    assert blocked.metadata["reason"] == "rate_limited"
    assert other.metadata["published"] is True


@pytest.mark.asyncio
async def test_the_rate_limiter_does_not_grow_without_bound_under_a_burst(
    records,
) -> None:
    mapping = {f"agent-{n}": (f"CREW{n}", "science") for n in range(400)}
    tool = _tool(records, mapping=mapping, max_per_hour=2)

    for n in range(400):
        await tool.invoke(
            _params(title=f"Finding {n}", claim=f"Distinct claim number {n}."),
            _ctx(agent_id=f"agent-{n}"),
        )

    tracked = tool._publications
    assert len(tracked) <= _MAX_TRACKED_AUTHORS
    for window in tracked.values():
        assert len(window) <= 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "x" * (_MAX_TITLE_CHARS + 1)),
        ("title", ""),
        ("title", 7),
        ("claim", "x" * 4001),
        ("claim", "   "),
        ("claim", None),
        ("basis", "x" * (_MAX_BASIS_CHARS + 1)),
        ("basis", ""),
        ("confidence", 1.01),
        ("confidence", -0.01),
        ("confidence", "high"),
        ("confidence", True),
        ("tags", ["t"] * _MAX_TAGS),
        ("tags", ["Uppercase"]),
        ("tags", ["-leading"]),
        ("tags", ["x" * (_MAX_TAG_CHARS + 1)]),
        ("tags", [7]),
        ("tags", "not-a-list"),
    ],
)
async def test_out_of_bounds_fields_are_refused_with_nothing_written(
    records, field, value,
) -> None:
    result = await _tool(records).invoke(_params(**{field: value}), _ctx())

    assert result.error == f"publish_finding_invalid:{field}"
    assert _notebook_files(records) == []


@pytest.mark.asyncio
async def test_content_cap_is_configurable_and_enforced_at_the_boundary(
    records,
) -> None:
    tool = _tool(records, max_content_chars=200)
    at_cap = await tool.invoke(_params(claim="c" * 200), _ctx())
    over_cap = await tool.invoke(
        _params(title="Second", claim="c" * 201), _ctx()
    )

    assert at_cap.metadata["published"] is True
    assert over_cap.error == "publish_finding_invalid:claim"


@pytest.mark.asyncio
@pytest.mark.parametrize("callsign", ["", "a/b", "..", "../escape", "a b", "x" * 65])
async def test_an_unsafe_callsign_is_refused_with_nothing_written(
    records, callsign,
) -> None:
    """The callsign becomes a directory name. ``_safe_path`` blocks traversal
    but not nesting, and a nested dir falls out of both curation guards' flat
    globs — so this fails closed before any write."""
    tool = _tool(records, mapping={"agent-a": (callsign, "science")})
    result = await tool.invoke(_params(), _ctx())

    assert result.error == "publish_finding_invalid:author"
    assert _notebook_files(records) == []
    assert _CALLSIGN_RE.fullmatch(callsign) is None


@pytest.mark.asyncio
async def test_a_missing_agent_id_is_refused(records) -> None:
    tool = _tool(records)

    assert (await tool.invoke(_params(), {})).error == (
        "publish_finding_invalid:author"
    )
    assert (await tool.invoke(_params(), None)).error == (
        "publish_finding_invalid:author"
    )
    assert _notebook_files(records) == []


@pytest.mark.asyncio
async def test_a_raising_identity_resolver_refuses_rather_than_guessing(
    records, caplog,
) -> None:
    tool = _tool(records, resolver=_RaisingResolver())
    with caplog.at_level("WARNING"):
        result = await tool.invoke(_params(), _ctx())

    assert result.error == "publish_finding_invalid:author"
    assert _notebook_files(records) == []
    assert any("AD-1140" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_a_failed_records_write_is_reported_not_swallowed(records) -> None:
    async def _boom(**_kw: Any) -> str:
        raise RuntimeError("disk full")

    records.write_notebook = _boom  # type: ignore[method-assign]
    result = await _tool(records).invoke(_params(), _ctx())

    assert result.error == "publish_finding_invalid:write_failed"


# ---------------------------------------------------------------------------
# DD-8 — sovereignty
# ---------------------------------------------------------------------------

def test_the_module_imports_no_episodic_symbol() -> None:
    """Asserted over the module's *resolved* imports, not a text grep."""
    module = sys.modules["probos.tools.publish_finding_tool"]
    for name, value in vars(module).items():
        origin = getattr(value, "__module__", "") or ""
        assert "episodic" not in origin.lower(), name
        assert "episodic" not in name.lower(), name
        assert "MemoryAccessPolicy" != name


@pytest.mark.asyncio
async def test_a_publish_makes_zero_episodic_calls(records) -> None:
    """The double is deliberately made *reachable* — hung off the store and off
    a runtime-shaped attribute — so this proves the tool does not go looking for
    a memory surface, not merely that it was never handed one."""
    episodic = _RecordingEpisodic()
    records.episodic_memory = episodic  # type: ignore[attr-defined]
    records._episodic = episodic  # type: ignore[attr-defined]
    records.runtime = SimpleNamespace(episodic_memory=episodic)  # type: ignore[attr-defined]

    tool = _tool(records)
    published = await tool.invoke(_params(), _ctx())
    duplicate = await tool.invoke(_params(), _ctx())
    refused = await tool.invoke(_params(title="!!!"), _ctx())

    assert published.metadata["published"] is True
    assert duplicate.metadata["published"] is False
    assert refused.error is not None
    assert episodic.calls == []
    assert not hasattr(tool, "_episodic")
    assert not hasattr(tool, "_episodic_memory")


def test_the_constructor_accepts_no_memory_surface() -> None:
    import inspect

    params = set(inspect.signature(PublishFindingTool.__init__).parameters)
    assert params == {
        "self", "records_store", "callsign_resolver", "source_node",
        "max_per_hour", "max_content_chars", "quality_engine",
        "similarity_threshold", "staleness_hours", "max_scan_entries",
    }


# ---------------------------------------------------------------------------
# DD-5 / indexing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_write_lands_under_the_curation_guards_notebook_path(
    records,
) -> None:
    result = await _tool(records).invoke(_params(), _ctx())
    path = result.metadata["path"]

    # Flat, one level below the callsign dir — what AD-550's glob and AD-554's
    # one-level iterdir both require.
    assert path.startswith("notebooks/SCOUT/")
    assert path.count("/") == 2
    listed = await records.list_entries("notebooks")
    assert [e["path"] for e in listed] == [path]


@pytest.mark.asyncio
async def test_one_publish_produces_one_indexed_record_with_the_full_envelope(
    records, tmp_path,
) -> None:
    import json

    layer = SemanticKnowledgeLayer(
        db_path=tmp_path / "semantic", episodic_memory=None,
    )
    await layer.start()
    try:
        records.set_semantic_indexer(layer)
        result = await _tool(records).invoke(
            _params(tags=["coolant"]), _ctx(_crew_session_id="sess-7")
        )
        col = layer._collections["records"]
        assert col.count() == 1

        got = col.get(ids=[f"record_{result.metadata['path']}"])
        meta = got["metadatas"][0]
        assert meta["classification"] == "ship"
        assert meta["author"] == "SCOUT"
        assert meta["department"] == "science"

        envelope = json.loads(meta["frontmatter_json"])
        assert envelope["claim_id"] == result.metadata["claim_id"]
        assert envelope["session_id"] == "sess-7"
        assert envelope["requested_scope"] == "ship"
        assert envelope["contest_state"] == "uncontested"
    finally:
        await layer.stop()


@pytest.mark.asyncio
async def test_quality_events_are_recorded_for_writes_and_suppressions(
    records,
) -> None:
    quality = _RecordingQuality()
    tool = _tool(records, quality_engine=quality)
    await tool.invoke(_params(), _ctx())
    await tool.invoke(_params(), _ctx())

    assert quality.events == ["dedup_write", "dedup_suppression"]


@pytest.mark.asyncio
async def test_a_raising_quality_engine_does_not_fail_the_publication(
    records,
) -> None:
    class _Boom:
        def record_event(self, *_a: Any, **_kw: Any) -> None:
            raise RuntimeError("metrics sink down")

    result = await _tool(records, quality_engine=_Boom()).invoke(
        _params(), _ctx()
    )
    assert result.metadata["published"] is True


# ---------------------------------------------------------------------------
# records_store: additive extra_frontmatter (DD-10 byte identity)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extra_frontmatter_none_is_byte_identical_to_the_literal_shape(
    records,
) -> None:
    """Asserted against a recomputation of the documented frontmatter, not a
    golden file — a golden file would drift silently."""
    path = await records.write_entry(
        author="alice", path="reports/plain.md", content="body text",
        message="m", classification="ship", extra_frontmatter=None,
    )
    raw = (records.repo_path / path).read_text(encoding="utf-8")
    fm, body = raw.split("---", 2)[1], raw.split("---", 2)[2]
    parsed = yaml.safe_load(fm)

    assert set(parsed) == {"author", "classification", "status", "created", "updated"}
    expected = yaml.dump(
        {
            "author": "alice",
            "classification": "ship",
            "status": "draft",
            "created": parsed["created"],
            "updated": parsed["updated"],
        },
        default_flow_style=False,
        sort_keys=False,
    )
    assert raw == f"---\n{expected}---\n\nbody text"
    assert body.strip() == "body text"


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", sorted(_RESERVED_FRONTMATTER_KEYS))
async def test_extra_frontmatter_rejects_every_store_owned_key(
    records, reserved,
) -> None:
    with pytest.raises(ValueError, match="store-owned keys"):
        await records.write_entry(
            author="alice", path="reports/spoof.md", content="c", message="m",
            extra_frontmatter={reserved: "forged"},
        )
    assert not (records.repo_path / "reports" / "spoof.md").exists()


@pytest.mark.asyncio
async def test_extra_frontmatter_merges_caller_keys_before_the_yaml_dump(
    records,
) -> None:
    path = await records.write_entry(
        author="alice", path="reports/env.md", content="c", message="m",
        extra_frontmatter={"claim_id": "abc", "confidence": 0.25},
    )
    entry = await _read_written(records, path)

    assert entry["frontmatter"]["claim_id"] == "abc"
    assert entry["frontmatter"]["confidence"] == 0.25
    assert entry["frontmatter"]["author"] == "alice"


@pytest.mark.asyncio
async def test_extra_frontmatter_must_be_a_dict(records) -> None:
    with pytest.raises(ValueError, match="must be a dict"):
        await records.write_entry(
            author="alice", path="reports/bad.md", content="c", message="m",
            extra_frontmatter=["not", "a", "dict"],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# DD-1 / DD-10 — governance, registration, default-OFF
# ---------------------------------------------------------------------------

def _registry(records_store: Any, *, enabled: bool = True,
              permission_store: Any = None) -> ToolRegistry:
    registry = ToolRegistry()
    if permission_store is not None:
        registry.set_permission_store(permission_store)
    _register_publish_finding_tool(
        tool_registry=registry,
        enabled=enabled,
        records_store=records_store,
        registry=SimpleNamespace(
            get=lambda aid: SimpleNamespace(
                agent_type="scout", callsign="SCOUT", sovereign_id="",
            ) if aid == "agent-a" else None,
            all=lambda: [],
        ),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
        source_node="node-1",
        max_per_hour=12,
        max_content_chars=4000,
    )
    return registry


def test_registered_with_all_six_departments_and_write_at_every_rank(
    records,
) -> None:
    registry = _registry(records)
    reg = registry.get("publish_finding")

    assert reg is not None
    assert set(reg.allowed_departments) == set(_ALL_DEPARTMENTS)
    assert reg.default_permissions == {
        "ensign": "write", "lieutenant": "write",
        "commander": "write", "senior_officer": "write",
    }
    assert reg.provider == "records"
    assert "publish_finding" in reg.tags


@pytest.mark.parametrize("department", _ALL_DEPARTMENTS)
def test_every_department_holds_write(records, department) -> None:
    registry = _registry(records)
    assert registry.check_permission(
        "agent-a", "publish_finding", ToolPermission.WRITE,
        agent_department=department, agent_rank="ensign",
    )


def test_an_unlisted_department_does_not_hold_the_tool(records) -> None:
    registry = _registry(records)
    assert not registry.check_permission(
        "agent-a", "publish_finding", ToolPermission.WRITE,
        agent_department="civilian", agent_rank="commander",
    )


def test_publish_finding_is_gated_against_raw_captain_grants() -> None:
    assert "publish_finding" in _GATED_TOOL_IDS
    assert {"event_log_query", "oracle_query"} <= _GATED_TOOL_IDS


def test_registration_is_skipped_when_the_flag_is_off(records) -> None:
    assert _registry(records, enabled=False).get("publish_finding") is None


def test_registration_is_skipped_without_a_store_or_an_ontology() -> None:
    registry = ToolRegistry()
    _register_publish_finding_tool(
        tool_registry=registry, enabled=True, records_store=None,
        registry=SimpleNamespace(get=lambda _a: None, all=lambda: []),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
        source_node="", max_per_hour=12, max_content_chars=4000,
    )
    assert registry.get("publish_finding") is None

    registry2 = ToolRegistry()
    _register_publish_finding_tool(
        tool_registry=registry2, enabled=True, records_store=object(),
        registry=SimpleNamespace(get=lambda _a: None, all=lambda: []),
        ontology=None, source_node="", max_per_hour=12, max_content_chars=4000,
    )
    assert registry2.get("publish_finding") is None


def test_default_config_leaves_the_flag_off_with_its_documented_bounds() -> None:
    cfg = AgenticToolsConfig()
    assert cfg.publish_finding_enabled is False
    assert cfg.publish_finding_max_per_hour == 12
    assert cfg.publish_finding_max_content_chars == 4000


def test_the_registration_resolver_is_the_bf679_reader_identity_resolver(
    records,
) -> None:
    """Reused, not duplicated — so an agent authors under exactly the identity
    Oracle Tier 2 later resolves it back to."""
    resolver = make_reader_identity_resolver(
        registry=SimpleNamespace(
            get=lambda aid: SimpleNamespace(
                agent_type="scout", callsign="SCOUT", sovereign_id="",
            ) if aid == "agent-a" else None,
            all=lambda: [],
        ),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
    )
    assert resolver("agent-a") == ("SCOUT", "science")
    assert resolver("nobody") == ("", "")


# ---------------------------------------------------------------------------
# DD-10 — tool_ids byte identity through the real dispatch
# ---------------------------------------------------------------------------

class _ToolIdCapturingLLM:
    def __init__(self) -> None:
        self.tool_names: list[list[str]] = []

    async def complete(self, request: Any, **_kw: object) -> LLMResponse:
        self.tool_names.append([
            (t.get("function") or {}).get("name")
            for t in (getattr(request, "tools", None) or [])
        ])
        return LLMResponse(
            content="done", tokens_used=1, content_blocks=[TextBlock(text="done")],
        )


def _agentic_runtime(registry: ToolRegistry, store: ToolPermissionStore) -> Any:
    return SimpleNamespace(
        tool_registry=registry, tool_permission_store=store, intent_bus=None,
        intent_grant_store=None, mcp_workbench=None, cognitive_skill_catalog=None,
        attachment_store=None, emit_event=None, registry=None, ontology=None,
        trust_network=None,
        config=SimpleNamespace(
            execution=SimpleNamespace(enabled=False),
            mcp=SimpleNamespace(agent_tools_enabled=False),
            agentic_tools=SimpleNamespace(
                tool_search_enabled=False, delegation_enabled=False,
            ),
        ),
    )


async def _offered(records_store: Any, *, enabled: bool,
                   department: str = "science") -> list[str]:
    store = ToolPermissionStore(db_path=":memory:")
    await store.start()
    try:
        registry = _registry(records_store, enabled=enabled,
                             permission_store=store)
        llm = _ToolIdCapturingLLM()
        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-a", instructions="", task_text="go",
            runtime=_agentic_runtime(registry, store),
            department=department, rank="ensign",
        )
        return llm.tool_names[0]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_flag_off_leaves_the_offered_tool_set_byte_identical(records) -> None:
    off = await _offered(records, enabled=False)
    on = await _offered(records, enabled=True)

    assert "publish_finding" not in off
    assert on == [*off, "publish_finding"]


@pytest.mark.asyncio
async def test_an_out_of_department_agent_is_not_offered_the_tool(records) -> None:
    offered = await _offered(records, enabled=True, department="civilian")
    assert "publish_finding" not in offered


@pytest.mark.asyncio
async def test_a_raw_captain_grant_does_not_surface_it_out_of_department(
    records,
) -> None:
    """``_GATED_TOOL_IDS`` drops the grant from ``granted_ids``, so the
    department layer stays authoritative."""
    store = ToolPermissionStore(db_path=":memory:")
    await store.start()
    try:
        await store.issue_grant(
            "agent-a", "publish_finding", ToolPermission.WRITE,
            issued_by="captain", reason="raw grant",
        )
        registry = _registry(records, enabled=True, permission_store=store)
        llm = _ToolIdCapturingLLM()
        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-a", instructions="", task_text="go",
            runtime=_agentic_runtime(registry, store),
            department="civilian", rank="commander",
        )
        assert "publish_finding" not in llm.tool_names[0]
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# Ablation flag set (AD-1143)
# ---------------------------------------------------------------------------

def test_the_ablation_arms_carry_the_publish_flag_on_both_sides() -> None:
    from tests.ablation.sigma_flags import SIGMA_OFF, SIGMA_ON, resolve_flag

    path = "agentic_tools.publish_finding_enabled"
    assert SIGMA_OFF[path] is False
    assert SIGMA_ON[path] is True
    assert set(SIGMA_ON) == set(SIGMA_OFF)
    assert type(resolve_flag(SystemConfig(), path)) is bool


# ---------------------------------------------------------------------------
# HEADLINE — the Σ round trip
# ---------------------------------------------------------------------------

async def _round_trip(
    tmp_path: Path, *, semantic: bool,
) -> tuple[list[Any], str]:
    """Agent A publishes; new service objects over the same paths serve agent B.

    The Oracle and the semantic layer are both constructed *after* the write and
    from disk, so nothing in-process carries the claim across — that is what
    makes this a later-session round trip rather than a shared handle.
    """
    repo = tmp_path / "ship-records"
    sem_path = tmp_path / "semantic"

    write_store = RecordsStore(
        RecordsConfig(repo_path=str(repo), auto_commit=False)
    )
    await write_store.initialize()

    write_layer: SemanticKnowledgeLayer | None = None
    if semantic:
        write_layer = SemanticKnowledgeLayer(
            db_path=sem_path, episodic_memory=None,
        )
        await write_layer.start()
        write_store.set_semantic_indexer(write_layer)

    tool = PublishFindingTool(
        records_store=write_store,
        callsign_resolver=_StaticResolver({"agent-a": ("SCOUT", "science")}),
        source_node="node-1",
    )
    published = await tool.invoke(
        {
            "title": "Deck twelve coolant harmonics",
            "claim": (
                "The port coolant loop resonates at 4.2 kHz under sustained "
                "load on deck twelve."
            ),
            "basis": "Nine sensor sweeps across three watches.",
            "tags": ["coolant"],
        },
        {"agent_id": "agent-a", "department": "science"},
    )
    assert published.metadata["published"] is True
    if write_layer is not None:
        await write_layer.stop()

    # ---- later session: fresh objects, same on-disk paths ----
    read_store = RecordsStore(
        RecordsConfig(repo_path=str(repo), auto_commit=False)
    )
    await read_store.initialize()
    read_layer: SemanticKnowledgeLayer | None = None
    if semantic:
        read_layer = SemanticKnowledgeLayer(db_path=sem_path, episodic_memory=None)
        await read_layer.start()

    oracle = OracleService(
        records_store=read_store,
        semantic_layer=read_layer,
        records_semantic_enabled=semantic,
    )
    oracle.attach_reader_identity_resolver(
        make_reader_identity_resolver(
            registry=SimpleNamespace(
                get=lambda aid: SimpleNamespace(
                    agent_type="engineer", callsign="WRENCH", sovereign_id="",
                ) if aid == "agent-b" else None,
                all=lambda: [],
            ),
            ontology=SimpleNamespace(
                get_agent_department=lambda _t: "engineering"
            ),
        )
    )
    try:
        results = await oracle.query(
            query_text="deck twelve coolant harmonics",
            agent_id="agent-b",
            k_per_tier=5,
            tiers=["records"],
        )
    finally:
        if read_layer is not None:
            await read_layer.stop()
    return results, published.metadata["path"]


@pytest.mark.asyncio
async def test_headline_keyword_path_round_trip(tmp_path) -> None:
    """A different agent, in a different session, reaches the claim — with no
    ChromaDB in the loop at all. This is the variant that proves the capability
    is not contingent on the semantic index being healthy."""
    results, path = await _round_trip(tmp_path, semantic=False)

    assert results, "agent B received nothing from the commons"
    assert any(r.source_tier == "records" for r in results)
    assert any(
        (r.metadata or {}).get("path") == path for r in results
    ), [r.metadata for r in results]


@pytest.mark.asyncio
async def test_headline_semantic_path_round_trip(tmp_path) -> None:
    """Same round trip with the real AD-1138 index in front of the keyword path."""
    results, path = await _round_trip(tmp_path, semantic=True)

    assert results, "agent B received nothing from the commons"
    assert any(r.source_tier == "records" for r in results)
    assert any((r.metadata or {}).get("path") == path for r in results)


@pytest.mark.asyncio
async def test_the_round_trip_reaches_agent_b_through_the_oracle_query_tool(
    tmp_path,
) -> None:
    """End-to-end through the AD-1139 read tool, so the pair is proven as one
    surface: agent A's ``publish_finding`` output is what agent B's
    ``oracle_query`` renders, carrying the disposition and a provenance marker."""
    from probos.tools.oracle_query_tool import _ORACLE_DISPOSITION, OracleQueryTool

    repo = tmp_path / "ship-records"
    store = RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))
    await store.initialize()
    await PublishFindingTool(
        records_store=store,
        callsign_resolver=_StaticResolver({"agent-a": ("SCOUT", "science")}),
        source_node="node-1",
    ).invoke(
        {
            "title": "Deck twelve coolant harmonics",
            "claim": "The port coolant loop resonates at 4.2 kHz on deck twelve.",
            "basis": "Nine sensor sweeps across three watches.",
        },
        {"agent_id": "agent-a", "department": "science"},
    )

    reader_store = RecordsStore(
        RecordsConfig(repo_path=str(repo), auto_commit=False)
    )
    await reader_store.initialize()
    oracle = OracleService(records_store=reader_store)
    oracle.attach_reader_identity_resolver(
        make_reader_identity_resolver(
            registry=SimpleNamespace(
                get=lambda aid: SimpleNamespace(
                    agent_type="engineer", callsign="WRENCH", sovereign_id="",
                ) if aid == "agent-b" else None,
                all=lambda: [],
            ),
            ontology=SimpleNamespace(
                get_agent_department=lambda _t: "engineering"
            ),
        )
    )
    result = await OracleQueryTool(oracle=oracle).invoke(
        {"query": "deck twelve coolant harmonics", "kind": "records"},
        {"agent_id": "agent-b"},
    )

    assert result.error is None
    assert _ORACLE_DISPOSITION in result.output
    assert "[source:records" in result.output
    assert "coolant" in result.output.lower()
