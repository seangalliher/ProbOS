"""AD-1157: agent-selected notebook classification, and the ontology default.

Two defects are closed here, and they are separable.

**The default was wrong.** ``config/ontology/records.yaml`` declares the
``notebook`` document class as ``classification_default: private`` with the
rule "Private by default — agent can explicitly publish entries".
``write_notebook`` shipped ``department``. Nothing compared them, so the
divergence survived the entire life of the corpus.

**The choice was unreachable.** The ``[NOTEBOOK]`` action tag captured a topic
slug and nothing else, and neither proactive write site passed a
classification. The default was therefore not a default at all — it was the
only value any notebook could ever receive. On the reference vessel that
produced 2,453 notebook entries at ``department``, none at ``private`` and none
at ``ship``. Guidance telling crew to choose a scope had no channel to carry
the choice, which is why earlier prompt-level corrections could not have
worked.

The tests below therefore cover both halves: the parser now carries a scope,
and the ontology and the code are pinned to each other so this class of
silent divergence fails loudly next time.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge.records_store import (
    NOTEBOOK_DEFAULT_CLASSIFICATION,
    _CLASSIFICATION_LEVELS,
    RecordsStore,
)
from probos.proactive import (
    _NOTEBOOK_CLASSIFICATIONS,
    _NOTEBOOK_PATTERN,
    _resolve_notebook_classification,
)
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent

_ONTOLOGY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "ontology" / "records.yaml"
)


# ---------------------------------------------------------------------------
# The ontology is the authority for the default
# ---------------------------------------------------------------------------

def _notebook_document_class() -> dict[str, Any]:
    doc = yaml.safe_load(_ONTOLOGY_PATH.read_text(encoding="utf-8"))
    classes = {c["id"]: c for c in doc["document_classes"]}
    return classes["notebook"]


def test_code_default_matches_the_records_ontology() -> None:
    """The anti-drift guard.

    A comment claiming the ontology as the source of truth is the same
    unenforced promise that produced the original divergence; this parses the
    YAML and compares.
    """
    assert (
        _notebook_document_class()["classification_default"]
        == NOTEBOOK_DEFAULT_CLASSIFICATION
    )


def test_the_default_the_ontology_asks_for_is_private() -> None:
    """Guards the guard: pins the expected value, so a matched-but-wrong pair
    (both flipped to ``department``) still fails."""
    assert NOTEBOOK_DEFAULT_CLASSIFICATION == "private"


def test_write_notebook_signature_takes_a_no_preference_sentinel() -> None:
    """AD-1157a: ``None`` has to mean *unspecified*, distinct from a caller
    passing the default explicitly — the two need different behaviour on
    update, so a plain string default cannot express the contract."""
    default = inspect.signature(RecordsStore.write_notebook).parameters[
        "classification"
    ].default
    assert default is None


# ---------------------------------------------------------------------------
# The tag now carries the choice
# ---------------------------------------------------------------------------

def test_bare_tag_still_parses_and_selects_no_scope() -> None:
    """Backward compatibility: every entry ever written used this shape."""
    assert _NOTEBOOK_PATTERN.findall("[NOTEBOOK my-slug]body[/NOTEBOOK]") == [
        ("my-slug", "", "body")
    ]


@pytest.mark.parametrize("scope", sorted(_NOTEBOOK_CLASSIFICATIONS))
def test_each_offered_scope_parses_off_the_tag(scope: str) -> None:
    assert _NOTEBOOK_PATTERN.findall(
        f"[NOTEBOOK my-slug {scope}]body[/NOTEBOOK]"
    ) == [("my-slug", scope, "body")]


def test_multiline_body_and_several_blocks_survive_the_scope_group() -> None:
    text = (
        "[NOTEBOOK first ship]line one\nline two[/NOTEBOOK]\n"
        "chatter\n"
        "[NOTEBOOK second]plain[/NOTEBOOK]"
    )
    assert _NOTEBOOK_PATTERN.findall(text) == [
        ("first", "ship", "line one\nline two"),
        ("second", "", "plain"),
    ]


def test_stripping_removes_blocks_with_and_without_a_scope() -> None:
    """The strip site shares the pattern; a scoped block left behind would leak
    a raw tag into the Captain-visible reply."""
    text = "a[NOTEBOOK one ship]x[/NOTEBOOK]b[NOTEBOOK two]y[/NOTEBOOK]c"
    assert _NOTEBOOK_PATTERN.sub("", text) == "abc"


def test_an_unrecognised_token_keeps_the_entry() -> None:
    """The reason group 2 is ``[\\w-]+`` and not an alternation.

    Under an alternation the tag would fail to match at all, so a misspelled
    scope would discard the agent's analysis along with it. Here the body still
    parses and only the scope is lost.
    """
    assert _NOTEBOOK_PATTERN.findall(
        "[NOTEBOOK my-slug fleeet]body[/NOTEBOOK]"
    ) == [("my-slug", "fleeet", "body")]


def test_fleet_is_not_offered_on_the_tag() -> None:
    """``fleet`` outranks the ``ship`` scope every query on this node uses, so
    a fleet notebook would be durable and reachable by nobody, its author
    included. AD-1140 records fleet intent in an envelope; a tag has none."""
    assert "fleet" not in _NOTEBOOK_CLASSIFICATIONS
    assert _NOTEBOOK_CLASSIFICATIONS <= set(_CLASSIFICATION_LEVELS)


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scope", sorted(_NOTEBOOK_CLASSIFICATIONS))
def test_resolver_passes_through_every_offered_scope(scope: str) -> None:
    assert (
        _resolve_notebook_classification(scope, callsign="SCOUT", topic_slug="t")
        == scope
    )


@pytest.mark.parametrize("token", ["", None, "fleeet", "FLEET", "public", "fleet"])
def test_resolver_reports_no_preference(token: str | None) -> None:
    """Absent, misspelled, miscased and out-of-vocabulary all resolve to *no
    preference* rather than raising — the write must not be lost, and an
    unreadable intent is not grounds to re-scope an existing note."""
    assert (
        _resolve_notebook_classification(
            token, callsign="SCOUT", topic_slug="t",
        )
        is None
    )


def test_resolver_names_the_offending_token_in_the_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An operator reading the log needs the bad value, not just that one
    occurred, or the misspelling is unfindable across a 2,000-entry corpus."""
    with caplog.at_level("WARNING"):
        _resolve_notebook_classification(
            "fleeet", callsign="SCOUT", topic_slug="coolant-harmonics",
        )
    assert "fleeet" in caplog.text
    assert "SCOUT" in caplog.text
    assert "coolant-harmonics" in caplog.text


def test_resolver_stays_silent_on_the_ordinary_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An absent token is the common case, not a fault."""
    with caplog.at_level("WARNING"):
        _resolve_notebook_classification("", callsign="SCOUT", topic_slug="t")
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# End to end through the real store
# ---------------------------------------------------------------------------

@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(
        RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False)
    )
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_notebook_write_lands_private_when_nothing_is_asked_for(
    records: RecordsStore,
) -> None:
    path = await records.write_notebook(
        callsign="SCOUT", topic_slug="coolant", content="body",
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == "private"


@pytest.mark.parametrize("scope", sorted(_NOTEBOOK_CLASSIFICATIONS))
@pytest.mark.asyncio
async def test_a_selected_scope_reaches_the_stored_frontmatter(
    records: RecordsStore, scope: str,
) -> None:
    """The end the agent actually cares about: the scope it typed is the scope
    on disk, through dedup, frontmatter assembly and the YAML round trip."""
    path = await records.write_notebook(
        callsign="SCOUT",
        topic_slug=f"topic-{scope}",
        content="body",
        classification=scope,
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == scope


@pytest.mark.asyncio
async def test_a_private_notebook_is_withheld_from_another_agent(
    records: RecordsStore,
) -> None:
    """What choosing ``private`` actually buys, enforced by BF-679."""
    path = await records.write_notebook(
        callsign="SCOUT", topic_slug="coolant", content="body",
    )
    assert await records.read_entry(path, "SCOUT") is not None
    assert await records.read_entry(path, "ANVIL") is None


# ---------------------------------------------------------------------------
# AD-1157a: a revision must not silently reclassify
# ---------------------------------------------------------------------------
#
# Observed live: a notebook created under the old ``department`` default was
# revised once by its author and came back ``private``. Update-in-place
# re-stamps frontmatter from the caller's default, and the write path is the
# same for a first draft and a revision, so a routine AD-550 update applied a
# default to a document authored before that default existed.

@pytest.mark.parametrize("original", sorted(_NOTEBOOK_CLASSIFICATIONS))
@pytest.mark.asyncio
async def test_revision_keeps_the_classification_it_had(
    records: RecordsStore, original: str,
) -> None:
    path = await records.write_notebook(
        callsign="SCOUT",
        topic_slug="coolant",
        content="first draft",
        classification=original,
    )
    await records.write_notebook(
        callsign="SCOUT", topic_slug="coolant", content="revised",
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == original
    assert entry["frontmatter"]["revision"] == 2


@pytest.mark.parametrize("chosen", sorted(_NOTEBOOK_CLASSIFICATIONS))
@pytest.mark.asyncio
async def test_the_author_may_rescope_an_existing_note(
    records: RecordsStore, chosen: str,
) -> None:
    """The Captain's ruling: an explicit tag is the author's own decision and
    wins on update, in either direction — including pulling a ``department``
    note back to ``private``."""
    path = await records.write_notebook(
        callsign="SCOUT",
        topic_slug="coolant",
        content="first draft",
        classification="department",
    )
    await records.write_notebook(
        callsign="SCOUT",
        topic_slug="coolant",
        content="revised",
        classification=chosen,
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == chosen


@pytest.mark.asyncio
async def test_preservation_does_not_leak_into_creation(
    records: RecordsStore,
) -> None:
    """There is nothing to preserve on a first write, so the default stands."""
    path = await records.write_notebook(
        callsign="SCOUT", topic_slug="brand-new", content="body",
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == "private"
    assert "revision" not in entry["frontmatter"]


@pytest.mark.asyncio
async def test_an_unreadable_stored_classification_falls_back(
    records: RecordsStore,
) -> None:
    """A corrupted stored value must not be carried forward: it would fail the
    validation that already ran on entry, turning a routine revision into a
    hard error on a document the agent cannot repair."""
    path = await records.write_notebook(
        callsign="SCOUT", topic_slug="coolant", content="first",
    )
    full = records._safe_path(path)
    full.write_text(
        full.read_text(encoding="utf-8").replace(
            "classification: private", "classification: bogus",
        ),
        encoding="utf-8",
    )

    await records.write_notebook(
        callsign="SCOUT", topic_slug="coolant", content="revised",
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == "private"


@pytest.mark.asyncio
async def test_write_entry_keeps_re_stamping_by_default(
    records: RecordsStore,
) -> None:
    """The carve-out is opt-in. Every other ``write_entry`` caller keeps the
    behaviour it had, so this cannot change duty logs or reports."""
    await records.write_entry(
        author="SCOUT", path="reports/x.md", content="first",
        message="m", classification="department",
    )
    await records.write_entry(
        author="SCOUT", path="reports/x.md", content="second",
        message="m", classification="ship",
    )
    entry = await records.read_entry("reports/x.md", "captain")
    assert entry["frontmatter"]["classification"] == "ship"


@pytest.mark.asyncio
async def test_curation_still_sees_a_private_entry(records: RecordsStore) -> None:
    """The load-bearing check on the default flip.

    AD-550 dedup and AD-554 convergence read notebook files off disk rather
    than through the classification gate. Had they gone through ``read_entry``,
    defaulting to ``private`` would have blinded the crew's curation and
    convergence loops to every new entry at once.
    """
    await records.write_notebook(
        callsign="SCOUT",
        topic_slug="coolant",
        content="The port coolant loop resonates at 4.2 kHz under load.",
    )
    dedup = await records.check_notebook_similarity(
        callsign="SCOUT",
        topic_slug="coolant",
        new_content="The port coolant loop resonates at 4.2 kHz under load.",
    )
    assert dedup["action"] != "write"

    convergence = await records.check_cross_agent_convergence(
        anchor_callsign="ANVIL",
        anchor_department="engineering",
        anchor_topic_slug="coolant",
        anchor_content="The port coolant loop resonates at 4.2 kHz under load.",
    )
    assert convergence["convergence_matches"] or not convergence[
        "convergence_detected"
    ]


@pytest.mark.asyncio
async def test_publish_finding_is_unaffected_by_the_notebook_default(
    records: RecordsStore,
) -> None:
    """AD-1140 passes ``classification`` explicitly, so the commons verb keeps
    reaching the whole ship regardless of what a notebook defaults to."""
    path = await records.write_notebook(
        callsign="SCOUT",
        topic_slug="finding-abc12345",
        content="body",
        classification="ship",
    )
    entry = await records.read_entry(path, "captain")
    assert entry["frontmatter"]["classification"] == "ship"
    assert await records.read_entry(path, "ANVIL") is not None


# ---------------------------------------------------------------------------
# The seam that was actually broken: tag -> write call
# ---------------------------------------------------------------------------
#
# The parser and the store were each individually correct before this AD. What
# was missing was the wiring between them, and a test of either half alone
# would have passed throughout the entire period no notebook could be
# classified. These assert on the kwarg as it arrives at ``write_notebook``.

def _mock_runtime() -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt._records_store = AsyncMock()
    rt._records_store.write_notebook = AsyncMock(
        return_value="notebooks/bones/analysis.md",
    )
    # Pin the AD-550 gate to a real dict. A bare AsyncMock returns a coroutine
    # that the gate never awaits, which both emits a RuntimeWarning and leaves
    # the write/suppress decision resting on MagicMock truthiness rather than
    # on the branch under test.
    rt._records_store.check_notebook_similarity = AsyncMock(
        return_value={
            "action": "write",
            "reason": "no_existing_entry",
            "existing_path": None,
            "existing_content": None,
            "similarity": 0.0,
            "revision": 0,
            "created_iso": None,
            "updated_iso": None,
            "existing_metrics": {},
        },
    )
    rt._ontology = None
    rt.ontology = None
    rt.ward_room = MagicMock()
    rt.ward_room.get_endorsements_for = AsyncMock(return_value=[])
    rt.trust_network = MagicMock()
    rt.trust_network.get_score = MagicMock(return_value=0.9)
    rt.ward_room_router = MagicMock()
    rt.ward_room_router.extract_endorsements = MagicMock(return_value=(None, []))
    return rt


def _mock_agent() -> Any:
    agent = MagicMock(spec=BaseAgent)
    agent.id = "test-agent"
    agent.callsign = "Bones"
    agent.agent_type = "medical"
    return agent


def _loop(rt: Any) -> Any:
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=60)
    loop._runtime = rt
    return loop


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("[NOTEBOOK t]", None),
        ("[NOTEBOOK t private]", "private"),
        ("[NOTEBOOK t department]", "department"),
        ("[NOTEBOOK t ship]", "ship"),
        ("[NOTEBOOK t fleeet]", None),
    ],
)
@pytest.mark.asyncio
async def test_proactive_path_carries_the_tag_scope_to_the_write(
    tag: str, expected: str | None,
) -> None:
    rt = _mock_runtime()
    text = f"Observation.\n{tag}Extended analysis body.[/NOTEBOOK]"

    await _loop(rt)._extract_and_execute_actions(_mock_agent(), text)

    rt._records_store.write_notebook.assert_called_once()
    kwargs = rt._records_store.write_notebook.call_args.kwargs
    assert kwargs["classification"] == expected


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("[NOTEBOOK t]", None),
        ("[NOTEBOOK t department]", "department"),
        ("[NOTEBOOK t ship]", "ship"),
    ],
)
@pytest.mark.asyncio
async def test_dm_path_carries_the_tag_scope_to_the_write(
    tag: str, expected: str | None,
) -> None:
    """AD-911/912's 1:1 path shares the pattern; before this AD it carried its
    own copy of the regex literal and could have drifted from the proactive
    one without anything failing."""
    rt = _mock_runtime()
    text = f"Saved for you.\n{tag}Note body.[/NOTEBOOK]"

    cleaned, actions = await _loop(rt).extract_and_execute_notebooks(
        _mock_agent(), text,
    )

    rt._records_store.write_notebook.assert_called_once()
    kwargs = rt._records_store.write_notebook.call_args.kwargs
    assert kwargs["classification"] == expected
    assert "[NOTEBOOK" not in cleaned
    assert actions and actions[0]["type"] == "notebook_write"
