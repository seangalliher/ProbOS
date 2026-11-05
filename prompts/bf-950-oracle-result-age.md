# BF-950 (#1742): an oracle_query result is aged by its own write time, not by its retrieval

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-04
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-05, before the build: the two tracker heads of section 8 carry 2026-11-05, the local date of M5's commit, as section 8's Date rule requires; and the base of this build is `58235059` (BF-948 and BF-953's merge, PR #1753), which changes none of the nine files this contract anchors in (`git diff --stat 728e1fc2 58235059 -- <the nine files>` is empty, and so is the same diff over the thirteen test files and the two scripts the gates call), and whose only changes to the tracker files are the BF-948 and BF-953 entries the re-anchoring rule of section 8 expects (P5-1 and P5-2 each match exactly once there).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 1 (review round 1, F1 and F2) adds milestones M6 to M9, tests T11 and T12, mutation rows NBM-10 to NBM-12 and OAM-21 to OAM-22, limits L15 to L17 and §16 items 13 to 17; it is appended at the end of this file.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 2 (review round 2, F3 and F4) adds milestones M10 to M12, tests T13 and T14, mutation rows NBM-13 to NBM-16, limits L18 and L19 and §16 items 18 to 21. It amends L15, NBM-12's killer and §16 item 13, and corrects the store-written claims of A1.1 and A1.12. It is appended at the end of this file.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 3 (review round 3, F5) adds milestones M13 to M15, tests T15 and T16, mutation rows NBM-17 to NBM-19, limit L20 and §16 items 22 to 24. It corrects L19, the third claim of A2.11 and the docstring P11-1 added. It is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2` (tree of BF-948 Amendment 1). For every file this contract touches, `git diff --stat ca0ca20b 728e1fc2 -- <files>` is empty, so `origin/main` `ca0ca20b` gives the same anchors. **Dependencies:** none. It does not touch BF-948/BF-953 work (`list_files`, `security/file_access.py`, `tools/protocol.py`). **Tier:** M1 STANDARD; M2, M3 and M4 STANDARD with a shared contract each (§4); M5 STANDARD. **Estimated tests:** 1 new file, `tests/test_bf950_oracle_result_age.py`: 11 functions and 39 cases, a count derived by reading the file, not by running it. Edits: `tests/test_ad677_context_provenance.py` (5 functions), `tests/test_ad1139_oracle_query_tool.py` (the regex and 1 function), `tests/test_ad1341_s4_lessons.py` and `tests/test_ad1341_s6_nature_description.py` (one constant each), and `tests/fixtures/ad1179_tool_definition_golden.json` (one description).
**BF number:** BF-950, held by the title of #1742 (OPEN). `git log --all -i --grep BF-950` finds `cb6d61ef` (BF-951) and `079f4761` (docs). Both mention the number and neither fixes it. Nothing is allocated.

**Which text describes the head.** Line numbers are those of `728e1fc2`. Before building, run `git diff --stat 728e1fc2 HEAD -- src/probos/cognitive/provenance.py src/probos/tools/oracle_query_tool.py src/probos/proactive.py src/probos/cognitive/cognitive_agent.py tests/test_ad677_context_provenance.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s6_nature_description.py tests/fixtures/ad1179_tool_definition_golden.json`. A SEARCH that no longer matches goes back to the Architect; do not rebase it by hand. Where prose and a block differ, the block wins.

## 1. Problem

1. `ProvenanceEnvelope.from_oracle_result` stamps `retrieval_timestamp=time.time()` (`cognitive/provenance.py:89`).
2. `ProvenanceTag.age_seconds` is `time.time() - self.retrieval_timestamp` (`:35`). `is_stale` is `age_seconds > 300` (`:40`), and `format_inline` prints that age (`:42-59`).
3. `oracle_query` builds the envelopes (`tools/oracle_query_tool.py:317-325`) and renders them in the same call (`:148`). So every marker reads `age:0s` and `STALE` never appears.
4. The preamble promises "an age" and says to "weigh a weakly-matching or STALE entry lightly" (`_ORACLE_DISPOSITION`, `:89-97`). The tool description, which agents see on the wire and the AD-1179 golden pins (`tests/fixtures/ad1179_tool_definition_golden.json:38`), says each entry is tagged with "an age" (`:194-195`).
5. **The real write times exist, per tier** (enumeration in §13):

| Tier | Write time in `OracleResult.metadata` | Source |
|---|---|---|
| records (keyword and semantic) | `frontmatter.updated`, else `.created` | `oracle_service.py:1079-1082`, `:1127-1132`; set at `records_store.py:305-323` |
| archive | `archived_at` (epoch) | `oracle_service.py:1187` |
| operational | `timestamp` (epoch) | `:1154` |
| episodic | `timestamp` | `:963`, `:981` |
| semantic | `indexed_at` (spread from the Chroma metadata) | `oracle_service.py:1236-1240`; `semantic.py:260,284,309,334,360,439` |
| graph | none (the edge has `created_at`/`updated_at`, `edges.py:93-94`, but the Oracle does not carry them) | `oracle_service.py:1380-1392`, `:1549-1561` |
| health | none (live readings, no timestamp) | `:1619-1683` |

   Three shapes reach `updated`:
   - An ISO string, as the store writes it.
   - A `datetime.date`, when someone writes `updated: 2026-05-03` by hand: YAML `safe_load` reads an unquoted date as a date (`records_store.py:1271`).
   - `str(datetime)`, with a space separator, from the semantic sidecar (`semantic.py:410`, `default=str`).

   Test doubles also pass a float (`tests/test_self_monitoring.py:406`).
6. **Adjacent: the proactive notebook read-back.** `<notebook topic="...">` carries no date (`cognitive_agent.py:9417`, `:11326`), although the index line beside it shows `updated` (`:9407`, `:11314`). The two producers already hold the frontmatter (`proactive.py:2846-2849` from `search`, which returns `frontmatter` at `records_store.py:1170`; `:2865-2868` from `read_entry`, which returns it at `:999`). They drop it.

## 2. Solution

The marker's age becomes the content's own: the time its tier records the entry was written. A tier with no recorded write time shows no age. `STALE` means the content is older than 30 days. The preamble and the description say exactly that. The `<notebook>` read-back tag carries `updated` and `revision` when they parse. Ranking, retrieval and `oracle_service.py` are untouched.

## 3. Decisions

**OA1, what the marker may say (ranked):**
1. **Chosen: the content's own age where the tier records a write time; no age otherwise.** The `age:` key keeps its name because it is now truthful. Graph and health get no invented time.
2. Render the absolute date (`written:2026-05-03`). Rejected: it adds about 19 characters to every archive marker, and AD-1341 sized its exit notes against the marker (§9 L12). The relative age is what an agent weighs.
3. Rename the field to the retrieval's age (`retrieved:0s`). Rejected: it is true but useless, and it keeps a signal that carries no information.
4. Drop the age entirely. Rejected: acceptance 1 requires a true age or the date.

**OA2, STALE:**
- STALE means the content is older than `STALE_AFTER_SECONDS = 30 days`, a module constant in `provenance.py`, as the tool's `SIGMA_TIERS` and DD-4 bounds are.
- Rejected: 300 s on the content's age, which would mark almost every record; `RecordsConfig.notebook_staleness_hours` (72 h), which is AD-550's refresh window for dedup (`config_models/knowledge.py:328`, `notebook_quality.py:211-239`), not a reader's warning; a config field now (deferred, L6).
- No age means no STALE. A write time in the future reads as `0s`.

**OA3, parser:** total. A value that does not parse gives no age and never an exception. `query_with_provenance` catches everything and returns `[]` (`provenance.py:116-122`), so one malformed frontmatter would otherwise empty the whole result. Valid values are positive, finite and no later than the end of 9999. Dates are formatted by arithmetic from the epoch, because `datetime.fromtimestamp` on Windows is bounded by the C library.

**OA4, consumers.** `age_seconds`, `is_stale` and `format_inline` on `ProvenanceTag` are read only by `ProvenanceEnvelope.render` (`provenance.py:80`) and by tests (Absence A1). `age_seconds` becomes `float | None`. `memory_transparency.MemoryProvenance` is a separate class with its own `age_seconds` and is unchanged. Tests that pin the old text are updated, never deleted, each with an inline BF-950 note:
- `test_ad677`: `test_provenance_tag_age`, `test_provenance_tag_staleness`, `test_provenance_tag_format_inline`, `test_provenance_tag_stale_marker`, `test_provenance_envelope_render`.
- `test_ad1139`: `_PROVENANCE_MARKER_RE` (`:55`); the `age:0s` literals (`:394-395`, which pin the defect).
- AD-1341: `_WORST_MARKER` (`s4:511`, `s6:74`; `s5` imports it from s4).

**OA5, M4 scope: kept.** It is acceptance 3. One renderer helper replaces both blocks, so they cannot drift. Producer `proactive._notebook_read_back`:
- `updated` is ISO-8601 UTC to the second, from `updated`, else `created`, else `""`.
- `revision` is a positive int, else `None`. A first write has no `revision` key and the block does not guess one.

**OA6, the issue's adjacent items:**
- `provenance.py:71` ("Used by TieredKnowledgeLoader"): fixed in M2. It is false (Absence A2) and the file is being edited anyway.
- The module docstring (`:3-5`, "every piece of context"): fixed in M2.
- `provenance.py:25` "AD-1294 (#1090)": **not changed; the premise is refuted.** Commit `a6516a8a` says "Closes #1090", so the citation names the issue AD-1294 fixed.
- `memory_transparency.py:5`: deferred (L9). The module is dormant with no production caller (Absence A3), and whether to wire it or retire it is its own decision.

## 4. Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only | N1-1, P1-1, P1-2 | G1 |
| M2 | STANDARD | **yes**: the public `ProvenanceTag.age_seconds` type and the `format_inline` text, consumed by agents and by AD-1341's budget tests | P2-1 to P2-12 | G2 |
| M3 | STANDARD | **yes**: the wire tool description (the AD-1179 golden) and agent-visible preamble | P3-1 to P3-7 | G3 |
| M4 | STANDARD | **yes**: the `notebook_content` dict shape, produced in `proactive.py` and consumed in `cognitive_agent.py` | P4-1 to P4-8 | G4 |
| M5 | STANDARD | trackers | P5-1, P5-2, ledger | G5 |

For M2 to M4 the Diff Reviewer covers each whole contract (§16), not only the delta.

- **M0:** on the base, record the collected count of every existing file named in G1 to G4.
- **G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf950_oracle_result_age.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s5_after_action_format.py tests/test_ad1341_s6_nature_description.py -q -n 0`.
  - Expected in the new file: **4 passed (T7, T10a×3), 35 xfailed**. The AD-1341 files: 0 failed.
  - **Hard stop:** a failure on a `worst <= _MAX_ENTRY_CHARS` assertion means AD-1341's budget lacks the 9 characters of headroom. That goes back to the Architect; do not shrink the marker or the bounds. Any other count, or a failure on a `# premise` line, is also a hard stop.
- **G2:** `... -m pytest tests/test_bf950_oracle_result_age.py tests/test_ad677_context_provenance.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s5_after_action_format.py tests/test_ad1341_s6_nature_description.py tests/test_ad1140_publish_finding.py tests/test_ad1141_crew_loop_sigma.py tests/test_bf679_oracle_records_reader_identity.py tests/test_ad696_agentic_oracle_retrieval.py -q -n 0`, then `... -P scripts/check_architecture_principles.py --check`.
  - Expected in the new file: **33 passed, 6 xfailed**. Others: 0 failed, counts equal to M0.
- **G3:** `... -m pytest tests/test_bf950_oracle_result_age.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1179_tool_schema_golden.py tests/test_ad1152_agentic_correlation.py tests/test_ad1140_publish_finding.py -q -n 0`.
  - Expected in the new file: **34 passed, 5 xfailed**. Others: 0 failed.
- **G4:** `... -m pytest tests/test_bf950_oracle_result_age.py tests/test_self_monitoring.py tests/test_bf949_notebook_reader_identity.py tests/test_ad550_notebook_dedup.py tests/test_ad552_notebook_self_repetition.py tests/test_proactive_quality.py -q -n 0`, then `check_architecture_principles.py --check`.
  - Expected in the new file: **39 passed**. Others: 0 failed.
- **G5:** `... -P scripts/gen_ad_ledger.py`; `... -P scripts/gen_ad_ledger.py --check`; `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- The broad gate runs once, in the main session with `--receipt`, after the review repairs.

## 5. Commit messages

- M1: `BF-950 M1: reproductions of oracle_query results marked age:0s and of the undated notebook read-back`
- M2: `BF-950 M2: an Oracle result's age is its content's own write time, STALE past thirty days`
- M3: `BF-950 M3: the oracle_query preamble and description state what the marker carries`
- M4: `BF-950 M4: the notebook read-back carries the entry's updated date and revision`
- M5: `BF-950 M5: trackers and ledger`

## 6. Tests (`tests/test_bf950_oracle_result_age.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_an_old_record_reaches_the_agent_with_its_own_age_and_marked_stale` | 2 | Acceptance 1, real store → Oracle → tool | M2 |
| T2 | `test_each_tier_is_aged_by_its_own_write_time` | 7 | OA1 table | M2 |
| T3 | `test_a_tier_that_records_no_write_time_shows_no_age` | 2 | graph, health | M2 |
| T4 | `test_stale_marks_only_content_older_than_thirty_days` | 4 | OA2, future clamp | M2 |
| T5 | `test_a_write_time_that_does_not_parse_shows_no_age` | 13 | OA3 | M2 |
| T6 | `test_one_bad_write_time_does_not_empty_the_result` | 1 | OA3 through the tool | M2 |
| T7 | `test_the_oracle_order_and_relevance_are_unchanged` | 1 | Acceptance 4 | none |
| T8 | `test_the_preamble_and_the_description_say_what_the_marker_carries` | 1 | Acceptance 2, DD-3 | M3 |
| T9 | `test_the_notebook_read_back_carries_the_entrys_date_and_revision` | 2 | Acceptance 3, real store → pull → both renderers | M4 |
| T10a | `test_a_read_back_with_nothing_that_parses_keeps_the_bare_tag` | 3 | compatibility | none |
| T10b | `test_a_read_back_keeps_what_parses_and_drops_what_does_not` | 3 | OA5 normalisation | M4 |

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_bf950_oracle_result_age.py` (new)

```python
"""BF-950 (#1742): an oracle_query result is aged by its own write time, not by its retrieval.

On the base every marker read ``age:0s``: ``ProvenanceEnvelope.from_oracle_result`` stamped the
retrieval time and the tool rendered the marker in the same call, so ``STALE`` could never appear.
Real fixtures where the chain matters: a real ``RecordsStore`` on ``tmp_path`` read through the real
``OracleService`` and ``OracleQueryTool`` (T1), and the real self-monitoring pull read back through
both ``<notebook>`` renderers (T9). Names the fix adds are reached inside tests, never imported at
module level, so the file collects on the base.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

import probos.cognitive.provenance as provenance
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.oracle_service import OracleResult, OracleService, make_reader_identity_resolver
from probos.cognitive.provenance import ProvenanceEnvelope, ProvenanceTag, query_with_provenance
from probos.config import RecordsConfig
from probos.crew_profile import Rank
from probos.knowledge.records_store import RecordsStore
from probos.proactive import ProactiveCognitiveLoop
from probos.tools.oracle_query_tool import _ORACLE_DISPOSITION, OracleQueryTool

_UNTIL_M2 = pytest.mark.xfail(strict=True, reason="BF-950 M2: the marker's age is the retrieval's, always 0s")
_UNTIL_M3 = pytest.mark.xfail(strict=True, reason="BF-950 M3: the preamble promises an age on every entry")
_UNTIL_M4 = pytest.mark.xfail(strict=True, reason="BF-950 M4: the notebook read-back carries no date")

_DAY = 86400.0
_FORTY_DAYS_AGO = 40 * _DAY + 3600.0


def _result(
    tier: str, metadata: Any, *, score: float = 0.5, content: str = "entry body",
) -> OracleResult:
    return OracleResult(source_tier=tier, content=content, score=score, metadata=metadata, provenance=f"[{tier}]")


def _marker(result: OracleResult) -> str:
    return ProvenanceEnvelope.from_oracle_result(result).tag.format_inline()


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _entry_marker(output: str, needle: str) -> str:
    """The provenance marker of the one rendered entry whose body holds ``needle``."""
    entries = [chunk for chunk in output.split("\n[source:")[1:] if needle in chunk]
    assert len(entries) == 1, output  # premise: the entry was rendered once
    return "[source:" + entries[0].splitlines()[0]


class _ScriptedOracle:
    def __init__(self, results: list[OracleResult]) -> None:
        self._results = list(results)

    async def query(self, query_text: str = "", **_kwargs: Any) -> list[OracleResult]:
        return list(self._results)


async def _records(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _rewrite_frontmatter(store: RecordsStore, path: str, **fields: Any) -> dict[str, Any]:
    """Set ``fields`` in a written entry's frontmatter, in the store's own YAML form; returns what loads back."""
    file = store.repo_path / path
    _, header, body = file.read_text(encoding="utf-8").split("---", 2)
    frontmatter = yaml.safe_load(header)
    frontmatter.update(fields)
    file.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)}---{body}", encoding="utf-8",
    )
    _, reread, _ = file.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(reread)


async def _self_monitoring(store: Any, callsign: str, *, pending: str | None = None) -> dict[str, Any]:
    """BF-949's harness (``tests/test_bf949_notebook_reader_identity.py``): trust 0.75, no posts, no episodes."""
    agent = SimpleNamespace(
        id=f"id-{callsign}", agent_type="engineering_agent", callsign=callsign,
        rank=Rank.COMMANDER, department="engineering", sovereign_id=f"id-{callsign}",
    )
    trust = MagicMock()
    trust.get_score = MagicMock(return_value=0.75)
    ward_room = MagicMock()
    ward_room.get_posts_by_author = AsyncMock(return_value=[])
    runtime = SimpleNamespace(
        ward_room=ward_room, episodic_memory=None, _records_store=store, trust_network=trust,
        _lifecycle_state="warm_boot", _start_time_wall=time.time() - 7200,
    )
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    if pending is not None:
        loop._pending_notebook_reads[agent.id] = pending
    return await loop._build_self_monitoring_context(agent, callsign, runtime)


def _sensorium_render(self_monitoring: dict[str, Any]) -> str:
    agent = CognitiveAgent.__new__(CognitiveAgent)
    return agent._sensorium_ext_self_monitoring({"_context_parts": {"self_monitoring": self_monitoring}})


async def _proactive_render(self_monitoring: dict[str, Any]) -> str:
    """The proactive prompt, built as ``tests/test_self_monitoring.py`` builds it."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._recent_post_count = 0
    agent._temporal_context = None
    agent._build_temporal_context = lambda: ""
    agent._format_memory_section = lambda memories: ["(memories)"]
    observation = {
        "intent": "proactive_think",
        "params": {
            "context_parts": {"self_monitoring": self_monitoring},
            "trust_score": 0.65,
            "agency_level": "suggestive",
            "rank": "lieutenant",
            "duty": None,
        },
    }
    return await agent._build_user_message(observation)


def _notebook_tags(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("<notebook ")]


def _mock_records(entry: dict[str, Any]) -> MagicMock:
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[])
    records.read_entry = AsyncMock(return_value=entry)
    return records


# ── M2: the age is the content's own ──────────────────────────────────


@_UNTIL_M2
@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["hand-written-date", "store-written-iso"])
async def test_an_old_record_reaches_the_agent_with_its_own_age_and_marked_stale(tmp_path: Path, shape: str) -> None:
    """Acceptance 1 through the real store, Oracle and tool. ``updated`` is 185 days back: a YAML date (an
    operator's hand edit) or the ISO text ``RecordsStore.write_entry`` writes."""
    store = await _records(tmp_path)
    path = "notebooks/Anvil/deck12-inspection.md"
    await store.write_notebook(
        "Anvil", "deck12-inspection", "zxqdecktwelve inspection closed without findings",
        department="engineering", classification="ship",
    )
    old = datetime.now(timezone.utc) - timedelta(days=185)
    updated: Any = old.date() if shape == "hand-written-date" else old.isoformat(timespec="seconds")
    loaded = _rewrite_frontmatter(store, path, updated=updated, revision=4)
    assert loaded["updated"] == updated  # premise: the YAML round trip keeps the shape
    written = (
        datetime(old.year, old.month, old.day, tzinfo=timezone.utc).timestamp()
        if shape == "hand-written-date"
        else datetime.fromisoformat(updated).timestamp()
    )
    oracle = OracleService(records_store=store)
    oracle.attach_reader_identity_resolver(make_reader_identity_resolver(
        registry=SimpleNamespace(
            get=lambda aid: SimpleNamespace(agent_type="engineer", callsign="WRENCH", sovereign_id="")
            if aid == "agent-b" else None,
            all=lambda: [],
        ),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "engineering"),
    ))

    result = await OracleQueryTool(oracle=oracle).invoke(
        {"query": "zxqdecktwelve", "kind": "records"}, {"agent_id": "agent-b"},
    )

    assert result.error is None  # premise
    marker = _entry_marker(result.output, "zxqdecktwelve inspection closed")
    match = re.fullmatch(r"\[source:records relevance:\d\.\d{2} age:(\d+)d STALE\]", marker)
    assert match is not None, marker
    expected = int((time.time() - written) // _DAY)
    assert expected - 1 <= int(match.group(1)) <= expected + 1


_TIMESTAMPED = [
    pytest.param("records", lambda ts: {"path": "p.md", "frontmatter": {"updated": _iso(ts)}}, id="records-updated"),
    pytest.param("records", lambda ts: {"path": "p.md", "frontmatter": {"created": _iso(ts)}}, id="records-created-only"),
    pytest.param(
        "records", lambda ts: {"path": "p.md", "frontmatter": {"updated": "not a date", "created": _iso(ts)}},
        id="records-bad-updated-uses-created",
    ),
    pytest.param("archive", lambda ts: {"archive_id": "a1", "archived_at": ts}, id="archive"),
    pytest.param("operational", lambda ts: {"timestamp": ts}, id="operational"),
    pytest.param("semantic", lambda ts: {"id": "skill_x", "type": "skill", "indexed_at": ts}, id="semantic"),
    pytest.param("episodic", lambda ts: {"episode_id": "ep-1", "timestamp": ts}, id="episodic"),
]


@_UNTIL_M2
@pytest.mark.parametrize(("tier", "metadata"), _TIMESTAMPED)
def test_each_tier_is_aged_by_its_own_write_time(tier: str, metadata: Any) -> None:
    written = time.time() - _FORTY_DAYS_AGO
    assert _marker(_result(tier, metadata(written))) == f"[source:{tier} relevance:0.50 age:40d STALE]"


@_UNTIL_M2
@pytest.mark.parametrize(("tier", "metadata"), [
    pytest.param("graph", {"edge_id": "e1", "relation": "reports_to", "weight": 1.0}, id="graph"),
    pytest.param("health", {"metric": "pool", "pool": "builders", "current_size": 2}, id="health"),
])
def test_a_tier_that_records_no_write_time_shows_no_age(tier: str, metadata: dict[str, Any]) -> None:
    envelope = ProvenanceEnvelope.from_oracle_result(_result(tier, metadata))
    assert envelope.render().splitlines()[0] == f"[source:{tier} relevance:0.50]"
    assert envelope.tag.age_seconds is None and envelope.tag.is_stale is False


@_UNTIL_M2
@pytest.mark.parametrize(("ago", "age", "stale"), [
    pytest.param(-3600.0, "0s", False, id="written-in-the-future"),
    pytest.param(5.0, "5s", False, id="seconds"),
    pytest.param(29 * _DAY + 3600.0, "29d", False, id="twenty-nine-days"),
    pytest.param(31 * _DAY, "31d", True, id="thirty-one-days"),
])
def test_stale_marks_only_content_older_than_thirty_days(ago: float, age: str, stale: bool) -> None:
    assert provenance.STALE_AFTER_SECONDS == 30 * _DAY
    tag = ProvenanceTag(
        source_tier="records", retrieval_timestamp=time.time(), relevance=0.5, content_hash="abcdef12",
        content_timestamp=time.time() - ago,
    )
    assert tag.format_inline() == f"[source:records relevance:0.50 age:{age}{' STALE' if stale else ''}]"
    assert tag.is_stale is stale
    assert tag.age_seconds >= 0


_UNPARSEABLE = [
    pytest.param({"updated": "yesterday"}, id="words"),
    pytest.param({"updated": ""}, id="empty-text"),
    pytest.param({"updated": None}, id="none"),
    pytest.param({"updated": True}, id="a-bool"),
    pytest.param({"updated": 0}, id="zero"),
    pytest.param({"updated": -5}, id="negative"),
    pytest.param({"updated": math.nan}, id="nan"),
    pytest.param({"updated": math.inf}, id="infinity"),
    pytest.param({"updated": 10**400}, id="too-large-for-a-float"),
    pytest.param({"updated": 1e13}, id="after-the-year-9999"),
    pytest.param({"updated": date(1960, 1, 1)}, id="before-1970"),
    pytest.param({"updated": ["2026-05-03"]}, id="a-list"),
    pytest.param("updated: 2026-05-03", id="frontmatter-not-a-mapping"),
]


@_UNTIL_M2
@pytest.mark.parametrize("frontmatter", _UNPARSEABLE)
def test_a_write_time_that_does_not_parse_shows_no_age(frontmatter: Any) -> None:
    tag = ProvenanceEnvelope.from_oracle_result(
        _result("records", {"path": "p.md", "frontmatter": frontmatter}),
    ).tag
    assert tag.format_inline() == "[source:records relevance:0.50]"
    assert tag.age_seconds is None and tag.is_stale is False


@_UNTIL_M2
@pytest.mark.asyncio
async def test_one_bad_write_time_does_not_empty_the_result() -> None:
    """``query_with_provenance`` answers any exception with ``[]``, so a parser that raised would drop every entry."""
    written = time.time() - _FORTY_DAYS_AGO
    oracle = _ScriptedOracle([
        _result("records", {"path": "p.md", "frontmatter": {"updated": 10**400}}, score=0.9, content="RECORD body"),
        _result("archive", {"archive_id": "a1", "archived_at": written}, score=0.8, content="ARCHIVE body"),
    ])

    result = await OracleQueryTool(oracle=oracle).invoke({"query": "anything"})

    assert result.error is None and result.metadata["returned_count"] == 2
    assert _entry_marker(result.output, "RECORD body") == "[source:records relevance:0.90]"
    assert _entry_marker(result.output, "ARCHIVE body") == "[source:archive relevance:0.80 age:40d STALE]"


@pytest.mark.asyncio
async def test_the_oracle_order_and_relevance_are_unchanged() -> None:
    """Acceptance 4: provenance renders only. Passes on the base and after."""
    results = [
        _result("records", {"path": "a.md", "frontmatter": {}}, score=0.9, content="first"),
        _result("graph", {"edge_id": "e1"}, score=0.4, content="second"),
        _result("archive", {"archive_id": "a1", "archived_at": 1.0e9}, score=0.7, content="third"),
    ]

    envelopes = await query_with_provenance(
        _ScriptedOracle(results), query_text="q", tiers=["records", "graph", "archive"],
    )

    assert [e.content for e in envelopes] == ["first", "second", "third"]
    assert [e.tag.relevance for e in envelopes] == [0.9, 0.4, 0.7]
    assert [e.tag.source_tier for e in envelopes] == ["records", "graph", "archive"]
    assert all(e.tag.metadata is r.metadata for e, r in zip(envelopes, results))


# ── M3: the preamble and the description ──────────────────────────────


@_UNTIL_M3
def test_the_preamble_and_the_description_say_what_the_marker_carries() -> None:
    assert "where its store records when the entry was written" in _ORACLE_DISPOSITION
    assert "marked STALE past thirty days" in _ORACLE_DISPOSITION
    assert "an entry with no age has no recorded write time" in _ORACLE_DISPOSITION
    assert getattr(provenance, "STALE_AFTER_SECONDS", None) == 30 * _DAY  # the words and the constant agree
    description = OracleQueryTool(oracle=None).description
    assert "a retrieval relevance score and, where its store records when it was written, its age." in description
    assert "and an age" not in description
    for text in (_ORACLE_DISPOSITION, description):
        assert _CAPABILITY_GAP_RE.search(text) is None


# ── M4: the notebook read-back ────────────────────────────────────────


@_UNTIL_M4
@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["semantic-pull", "pending-read"])
async def test_the_notebook_read_back_carries_the_entrys_date_and_revision(tmp_path: Path, path: str) -> None:
    """Acceptance 3: a real store, the real pull, and both renderers of the block."""
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    _rewrite_frontmatter(store, "notebooks/Zephyr/own-topic.md", updated="2026-05-03T10:00:00+00:00", revision=4)

    result = await _self_monitoring(store, "Zephyr", pending="own-topic" if path == "pending-read" else None)

    content = result["notebook_content"]
    assert content["topic"] == "own-topic" and "engineering notes of my own" in content["snippet"]  # premise
    expected = '<notebook topic="own-topic" updated="2026-05-03T10:00:00+00:00" revision="4">'
    assert _notebook_tags(_sensorium_render(result)) == [expected]
    proactive_tags = _notebook_tags(await _proactive_render(result))
    assert proactive_tags and set(proactive_tags) == {expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [
    pytest.param({"content": "Notebook body"}, id="no-frontmatter"),
    pytest.param(
        {"content": "Notebook body", "frontmatter": {"updated": "yesterday", "revision": "4"}}, id="nothing-parses",
    ),
    pytest.param(
        {"content": "Notebook body", "frontmatter": {"updated": None, "revision": True}}, id="none-and-a-bool",
    ),
])
async def test_a_read_back_with_nothing_that_parses_keeps_the_bare_tag(entry: dict[str, Any]) -> None:
    """Compatibility: passes on the base and after."""
    result = await _self_monitoring(_mock_records(entry), "Bones", pending="my-topic")
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise: the pending read ran
    assert _notebook_tags(_sensorium_render(result)) == ['<notebook topic="my-topic">']


@_UNTIL_M4
@pytest.mark.asyncio
@pytest.mark.parametrize(("frontmatter", "expected"), [
    pytest.param(
        {"updated": date(2026, 5, 3), "revision": True},
        '<notebook topic="my-topic" updated="2026-05-03T00:00:00+00:00">', id="a-yaml-date-and-a-bool-revision",
    ),
    pytest.param(
        {"updated": "2026-05-03T10:00:00", "revision": 0},
        '<notebook topic="my-topic" updated="2026-05-03T10:00:00+00:00">', id="naive-text-and-revision-zero",
    ),
    pytest.param(
        {"created": "2026-04-01T08:00:00+00:00", "revision": 7},
        '<notebook topic="my-topic" updated="2026-04-01T08:00:00+00:00" revision="7">', id="created-only",
    ),
])
async def test_a_read_back_keeps_what_parses_and_drops_what_does_not(
    frontmatter: dict[str, Any], expected: str,
) -> None:
    result = await _self_monitoring(
        _mock_records({"content": "Notebook body", "frontmatter": frontmatter}), "Bones", pending="my-topic",
    )
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise
    assert _notebook_tags(_sensorium_render(result)) == [expected]
```

**P1-1** `tests/test_ad1341_s4_lessons.py`

SEARCH:
```python
#: The longest inheritance label S2 writes (a six-digit generation) and the longest provenance marker the Oracle tool
#: puts before an archive entry it has just retrieved (relevance at most 1.00, retrieved under a minute ago).
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"
```
REPLACE:
```python
#: The longest inheritance label S2 writes (a six-digit generation) and the longest provenance marker the Oracle tool
#: puts before an archive entry: relevance at most 1.00 and, from BF-950, the entry's own age (five digits of days
#: covers every write time after 1970 until 2243) marked STALE. Before BF-950 it was "age:59s", the retrieval's age,
#: which the tool measured in the same call that rendered it.
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:99999d STALE]"
```

**P1-2** `tests/test_ad1341_s6_nature_description.py`

SEARCH:
```python
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
_WORST_MARKER = "[source:archive relevance:1.00 age:59s]"
```
REPLACE:
```python
_WORST_LABEL = "[Inherited from the crew of generation 999999: not your own memory]"
# BF-950: the entry's own age (at most five digits of days) and STALE; it was "age:59s", the retrieval's age.
_WORST_MARKER = "[source:archive relevance:1.00 age:99999d STALE]"
```

### 7.2 M2

**P2-1** `src/probos/cognitive/provenance.py`

SEARCH:
```python
"""Context Provenance Metadata (AD-677).

Tags every piece of context injected into agent prompts with
source tier, retrieval timestamp, retrieval relevance, and
staleness indicator.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
```
REPLACE:
```python
"""Context Provenance Metadata (AD-677).

Tags each result the ``oracle_query`` tool hands an agent with its source tier,
its retrieval relevance and, where the tier's store records when the entry was
written, the entry's own age and a staleness flag.

BF-950: the age was measured from the retrieval, which happens in the same call
that renders the marker, so every marker read ``age:0s`` and ``STALE`` never
appeared. The age is now the content's, read from the write time its tier
records (:func:`entry_write_time`); a tier that records none shows no age.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

logger = logging.getLogger(__name__)

#: BF-950: content older than this is marked ``STALE``. Thirty days: the tiers
#: that record a write time hold standing reference material (records, the
#: archive, the semantic index, past episodes), so a threshold in minutes would
#: mark nearly every entry and the flag would say nothing. A module constant, as
#: the Oracle tool's tier list and bounds are; ``_ORACLE_DISPOSITION`` states it
#: to agents in words, and a test holds the two together.
STALE_AFTER_SECONDS: Final = 30 * 86400.0

#: BF-950: the metadata key under which each tier records its entry's write
#: time. ``records`` keeps it in the entry's frontmatter (:func:`record_write_time`).
#: ``graph`` and ``health`` record none in their results, so they show no age.
_TIER_WRITE_TIME_KEYS: Final[dict[str, str]] = {
    "episodic": "timestamp",
    "operational": "timestamp",
    "archive": "archived_at",
    "semantic": "indexed_at",
}

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=timezone.utc)
#: The last second of 9999-12-31 UTC: a later write time is not a date.
_MAX_POSIX_SECONDS: Final = 253402300799.0


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _posix_seconds(value: Any) -> float | None:
    """BF-950: ``value`` as positive, finite POSIX seconds no later than 9999, or ``None``.

    A number, a ``datetime``, a ``date`` (midnight UTC) or ISO-8601 text. A naive
    datetime, or text without an offset, is read as UTC: the store writes aware
    UTC times, and a hand-written entry names no zone. A bool, any other type,
    and text that is not ISO-8601 give ``None``. Nothing here raises, so one
    malformed entry cannot empty a result.
    """
    try:
        if type(value) is bool:
            return None
        if isinstance(value, (int, float)):
            seconds = float(value)
        elif isinstance(value, datetime):
            seconds = _as_utc(value).timestamp()
        elif isinstance(value, date):
            seconds = datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
        elif isinstance(value, str):
            seconds = _as_utc(datetime.fromisoformat(value.strip())).timestamp()
        else:
            return None
    except (OverflowError, ValueError, TypeError):
        return None
    if not math.isfinite(seconds) or seconds <= 0 or seconds > _MAX_POSIX_SECONDS:
        return None
    return seconds


def record_write_time(frontmatter: Any) -> float | None:
    """BF-950: when a Ship's Records entry was last written, as POSIX seconds, or ``None``.

    Its frontmatter's ``updated``, else its ``created``: ``RecordsStore.write_entry``
    sets both on a first write and ``updated`` on every revision.
    """
    if type(frontmatter) is not dict:
        return None
    updated = _posix_seconds(frontmatter.get("updated"))
    return updated if updated is not None else _posix_seconds(frontmatter.get("created"))


def entry_write_time(source_tier: str, metadata: Any) -> float | None:
    """BF-950: when an Oracle result's content was written to its tier, or ``None``.

    Read from the key :data:`_TIER_WRITE_TIME_KEYS` names, or for ``records``
    from the frontmatter. A tier not named there, and a value that does not
    parse, give ``None``.
    """
    if type(metadata) is not dict:
        return None
    if source_tier == "records":
        return record_write_time(metadata.get("frontmatter"))
    key = _TIER_WRITE_TIME_KEYS.get(source_tier)
    return None if key is None else _posix_seconds(metadata.get(key))


def iso_utc(seconds: float) -> str:
    """BF-950: POSIX ``seconds`` as ISO-8601 UTC to the second, e.g. ``2026-05-03T10:00:00+00:00``.

    By arithmetic from the epoch, so every value :func:`record_write_time`
    returns renders on every platform (``datetime.fromtimestamp`` is bounded by
    the C library, on Windows at the year 3000).
    """
    return (_EPOCH + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _is_stale(age: float | None) -> bool:
    return age is not None and age > STALE_AFTER_SECONDS


def _format_age(seconds: float) -> str:
    """``45s``, ``12m``, ``5h`` or ``184d``, each rounded down."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"
```

**P2-2** `src/probos/cognitive/provenance.py`

SEARCH: `provenance.py:19-59` exactly as on the head, from `@dataclass(frozen=True)` / `class ProvenanceTag:` through the closing `        )` of `format_inline`. The block opens with:
```python
@dataclass(frozen=True)
class ProvenanceTag:
    """Metadata tag for a single piece of injected context."""

    source_tier: str
    retrieval_timestamp: float
```
and it ends with:
```python
        stale_marker = " STALE" if self.is_stale else ""
        return (
            f"[source:{self.source_tier} relevance:{self.relevance:.2f} "
            f"age:{age_str}{stale_marker}]"
        )
```
REPLACE:
```python
@dataclass(frozen=True)
class ProvenanceTag:
    """Metadata tag for a single piece of injected context."""

    source_tier: str
    #: When the entry was retrieved. Not rendered (BF-950): the retrieval is the
    #: call that renders the marker, so its age says nothing about the entry.
    retrieval_timestamp: float
    #: AD-1294 (#1090): how well the entry MATCHED THE QUERY, not how strongly
    #: its author holds it. Named ``confidence`` until it was found rendering
    #: ``OracleResult.score`` under that label straight into agent context.
    relevance: float
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)
    #: BF-950: when the content was written to its tier, as POSIX seconds, or
    #: ``None`` when the tier records no write time (:func:`entry_write_time`).
    content_timestamp: float | None = None

    @property
    def age_seconds(self) -> float | None:
        """BF-950: how old the content is, or ``None`` with no recorded write time.

        A write time in the future (a skewed clock) reads as 0.
        """
        if self.content_timestamp is None:
            return None
        return max(0.0, time.time() - self.content_timestamp)

    @property
    def is_stale(self) -> bool:
        """BF-950: whether the content is older than :data:`STALE_AFTER_SECONDS`; False with no age."""
        return _is_stale(self.age_seconds)

    def format_inline(self) -> str:
        """Format as an inline provenance marker for prompt injection.

        Examples: ``[source:records relevance:0.82 age:184d STALE]``, and for a
        tier that records no write time ``[source:graph relevance:0.70]``.
        """
        marker = f"[source:{self.source_tier} relevance:{self.relevance:.2f}"
        age = self.age_seconds
        if age is not None:
            marker += f" age:{_format_age(age)}"
            if _is_stale(age):
                marker += " STALE"
        return marker + "]"
```

**P2-3** `src/probos/cognitive/provenance.py`

SEARCH:
```python
    """Wraps content with its provenance tag (AD-677).

    Used by TieredKnowledgeLoader to pass provenance through
    the context injection pipeline.
    """
```
REPLACE:
```python
    """Wraps content with its provenance tag (AD-677).

    Built by :func:`query_with_provenance`, whose one production caller is the
    ``oracle_query`` tool (``tools/oracle_query_tool.py``).
    """
```

**P2-4** `src/probos/cognitive/provenance.py`

SEARCH:
```python
        """Create from an OracleResult (oracle_service.py:22-30)."""
        return cls(
            content=result.content,
            tag=ProvenanceTag(
                source_tier=result.source_tier,
                retrieval_timestamp=time.time(),
                relevance=result.score,
                content_hash=compute_content_hash(result.content),
                metadata=result.metadata,
            ),
        )
```
REPLACE:
```python
        """Create from an ``oracle_service.OracleResult``.

        BF-950: the tag carries the content's own write time, read from the
        result's tier metadata (:func:`entry_write_time`); the retrieval time is
        kept and not rendered.
        """
        return cls(
            content=result.content,
            tag=ProvenanceTag(
                source_tier=result.source_tier,
                retrieval_timestamp=time.time(),
                relevance=result.score,
                content_hash=compute_content_hash(result.content),
                metadata=result.metadata,
                content_timestamp=entry_write_time(result.source_tier, result.metadata),
            ),
        )
```

**P2-5** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
    ProvenanceTag,
    compute_content_hash,
```
REPLACE:
```python
    ProvenanceTag,
    STALE_AFTER_SECONDS,
    compute_content_hash,
```

**P2-6** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
def test_provenance_tag_age() -> None:
    tag = ProvenanceTag(
        source_tier="records",
        retrieval_timestamp=time.time() - 1,
        relevance=0.7,
        content_hash="abcdef12",
    )

    assert tag.age_seconds > 0
```
REPLACE:
```python
def test_provenance_tag_age() -> None:
    # BF-950: built from ``retrieval_timestamp`` and asserted its age, which was
    # the defect: the retrieval is the call that renders the marker, so that age
    # was always about zero. The age is the content's own write time now, and
    # absent when the tier records none.
    tag = ProvenanceTag(
        source_tier="records",
        retrieval_timestamp=time.time(),
        relevance=0.7,
        content_hash="abcdef12",
        content_timestamp=time.time() - 90,
    )
    untimed = ProvenanceTag(
        source_tier="graph",
        retrieval_timestamp=time.time() - 600,
        relevance=0.7,
        content_hash="abcdef12",
    )

    assert tag.age_seconds >= 90
    assert untimed.age_seconds is None
```

**P2-7** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
def test_provenance_tag_staleness() -> None:
    tag = ProvenanceTag(
        source_tier="operational",
        retrieval_timestamp=time.time() - 600,
        relevance=0.7,
        content_hash="abcdef12",
    )
```
REPLACE:
```python
def test_provenance_tag_staleness() -> None:
    # BF-950: was STALE from a retrieval 600 s back (the 300 s threshold on the
    # retrieval's clock). Staleness is the content's age past STALE_AFTER_SECONDS.
    tag = ProvenanceTag(
        source_tier="operational",
        retrieval_timestamp=time.time() - 600,
        relevance=0.7,
        content_hash="abcdef12",
        content_timestamp=time.time() - STALE_AFTER_SECONDS - 60,
    )
```

**P2-8** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
def test_provenance_tag_format_inline() -> None:
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time(),
        relevance=0.82,
        content_hash="abcdef12",
    )
```
REPLACE:
```python
def test_provenance_tag_format_inline() -> None:
    # BF-950: the age comes from ``content_timestamp``; without one the marker has no age.
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time(),
        relevance=0.82,
        content_hash="abcdef12",
        content_timestamp=time.time(),
    )
```

**P2-9** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
def test_provenance_tag_stale_marker() -> None:
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time() - 600,
        relevance=0.82,
        content_hash="abcdef12",
    )
```
REPLACE:
```python
def test_provenance_tag_stale_marker() -> None:
    # BF-950: was STALE from a retrieval 600 s back; STALE is the content's age past STALE_AFTER_SECONDS.
    tag = ProvenanceTag(
        source_tier="episodic",
        retrieval_timestamp=time.time() - 600,
        relevance=0.82,
        content_hash="abcdef12",
        content_timestamp=time.time() - STALE_AFTER_SECONDS - 60,
    )
```

**P2-10** `tests/test_ad677_context_provenance.py`

SEARCH:
```python
            source_tier="records",
            retrieval_timestamp=time.time(),
            relevance=0.91,
            content_hash="abcdef12",
        ),
```
REPLACE:
```python
            source_tier="records",
            retrieval_timestamp=time.time(),
            relevance=0.91,
            content_hash="abcdef12",
            # BF-950: the rendered age is the content's; without a write time there is none.
            content_timestamp=time.time(),
        ),
```

**P2-11** `tests/test_ad1139_oracle_query_tool.py` (two edits, each SEARCH unique)

SEARCH:
```python
_PROVENANCE_MARKER_RE = re.compile(
    r"^\[source:(\w+) relevance:\d\.\d{2} age:\d+[smh]( STALE)?\]$",
    re.MULTILINE,
)
```
REPLACE:
```python
# BF-950: the age is the content's own, so it appears only where the tier records a
# write time, and in days for old content; the regex required ``age:`` on every entry.
_PROVENANCE_MARKER_RE = re.compile(
    r"^\[source:(\w+) relevance:\d\.\d{2}(?: age:\d+[smhd]( STALE)?)?\]$",
    re.MULTILINE,
)
```
SEARCH:
```python
    assert "[source:records relevance:0.82 age:0s]" in output
    assert "[source:graph relevance:0.70 age:0s]" in output
```
REPLACE:
```python
    # BF-950: asserted ``age:0s`` on both, the defect itself (an age measured from the
    # retrieval in the same call). These results record no write time, so no age.
    assert "[source:records relevance:0.82]" in output
    assert "[source:graph relevance:0.70]" in output
```

**P2-12** `tests/test_bf950_oracle_result_age.py`:
- Delete every line `@_UNTIL_M2` (an Edit with `replace_all: true`, old `@_UNTIL_M2\n`, new empty).
- Then delete the line `_UNTIL_M2 = pytest.mark.xfail(strict=True, reason="BF-950 M2: the marker's age is the retrieval's, always 0s")`.

### 7.3 M3

**P3-1** `src/probos/tools/oracle_query_tool.py`

SEARCH:
```python
``ProvenanceEnvelope.render()`` markers (AD-677) carrying source tier,
relevance and age.
```
REPLACE:
```python
``ProvenanceEnvelope.render()`` markers (AD-677) carrying source tier,
relevance and, where the tier records when the entry was written, its age
(BF-950).
```

**P3-2** `src/probos/tools/oracle_query_tool.py`

SEARCH:
```python
# phrasing so it never trips ``_CAPABILITY_GAP_RE``.
_ORACLE_DISPOSITION: str = (
    "(These entries come from the ship's shared knowledge stores, not from your "
    "own memory — treat them as reference material rather than as something you "
    "lived through. Each entry is prefixed with its source tier, a retrieval "
    "relevance score and an age, so weigh a weakly-matching or STALE entry "
    "lightly. Relevance is how well the entry matched your query, not how "
    "strongly its author holds it. Cite an "
    "entry when you actually rely on it; otherwise do not narrate this lookup.)"
)
```
REPLACE:
```python
# phrasing so it never trips ``_CAPABILITY_GAP_RE``. BF-950: it promised an age on
# every entry and a STALE that could never fire; it now states what the marker
# carries. "thirty days" is ``provenance.STALE_AFTER_SECONDS`` in words, and a test
# holds the two together.
_ORACLE_DISPOSITION: str = (
    "(These entries come from the ship's shared knowledge stores, not from your "
    "own memory — treat them as reference material rather than as something you "
    "lived through. Each entry is prefixed with its source tier, a retrieval "
    "relevance score and, where its store records when the entry was written, "
    "the entry's age, marked STALE past thirty days; an entry with no age has "
    "no recorded write time. So weigh a weakly-matching or STALE entry "
    "lightly. Relevance is how well the entry matched your query, not how "
    "strongly its author holds it. Cite an "
    "entry when you actually rely on it; otherwise do not narrate this lookup.)"
)
```

**P3-3** `src/probos/tools/oracle_query_tool.py`

SEARCH:
```python
    larger, so trimming the tail only ever removes content — the source tier,
    relevance and age an agent needs to weigh the entry always survive.
```
REPLACE:
```python
    larger, so trimming the tail only ever removes content — the source tier,
    relevance and any age an agent needs to weigh the entry always survive.
```

**P3-4** `src/probos/tools/oracle_query_tool.py`

SEARCH:
```python
            "telemetry. Read-only. Every entry comes back tagged with its "
            "source tier, a retrieval relevance score and an age. Each agent's personal "
```
REPLACE:
```python
            "telemetry. Read-only. Every entry comes back tagged with its "
            "source tier, a retrieval relevance score and, where its store "
            "records when it was written, its age. Each agent's personal "
```

**P3-5** `tests/fixtures/ad1179_tool_definition_golden.json` (the text at `:38`; plain substring)

SEARCH: `source tier, a retrieval relevance score and an age. Each agent's personal`
REPLACE: `source tier, a retrieval relevance score and, where its store records when it was written, its age. Each agent's personal`

**P3-6** `tests/fixtures/ad1179_tool_definition_golden.json` (`:2`, the end of `_header`)

SEARCH: `so a key reorder is a failure, not a normalisation.",`
REPLACE: `so a key reorder is a failure, not a normalisation. BF-950 (#1742) changed only oracle_query's function.description, which now states an age only where the store records a write time; that definition's bytes were edited in place to the producer's output on BF-950 M3, as AD-1241 recaptured find_mcp_tool.",`

`_captured_at_commit` is unchanged. G3's `test_ad1179_tool_schema_golden.py` is the check that P3-5 equals the producer's bytes.

**P3-7** `tests/test_bf950_oracle_result_age.py`:
- Delete every line `@_UNTIL_M3` (`replace_all`).
- Then delete the `_UNTIL_M3 = ...` line.

### 7.4 M4

**P4-1** `src/probos/proactive.py`

SEARCH:
```python
from probos.cognitive.orientation import OrientationContext, count_agent_episodes, derive_watch_section
from probos.types import AnchorFrame, IntentMessage, Priority
```
REPLACE:
```python
from probos.cognitive.orientation import OrientationContext, count_agent_episodes, derive_watch_section
from probos.cognitive.provenance import iso_utc, record_write_time
from probos.types import AnchorFrame, IntentMessage, Priority
```

**P4-2** `src/probos/proactive.py`

SEARCH:
```python
def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse HH:MM into (hour, minute) for schedule threshold checks."""
```
REPLACE:
```python
def _notebook_read_back(topic: str, snippet: str, frontmatter: Any) -> dict[str, Any]:
    """BF-950: the notebook entry self-monitoring reads back, with the entry's own date.

    ``updated`` is when the entry was last written, as ISO-8601 UTC to the second
    (its frontmatter's ``updated``, else ``created``; ``record_write_time``), or
    ``""`` when neither parses. ``revision`` is the frontmatter's ``revision`` when
    that is a positive int, else ``None``: a first write carries no ``revision``
    key, and the read-back does not guess one.
    """
    fields = frontmatter if type(frontmatter) is dict else {}
    written = record_write_time(fields)
    revision = fields.get("revision")
    return {
        "topic": topic,
        "snippet": snippet,
        "updated": iso_utc(written) if written is not None else "",
        "revision": revision if type(revision) is int and revision >= 1 else None,
    }


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse HH:MM into (hour, minute) for schedule threshold checks."""
```

**P4-3** `src/probos/proactive.py`

SEARCH:
```python
                        if search_results:
                            top = search_results[0]
                            result["notebook_content"] = {
                                "topic": top.get("path", "").split("/")[-1].replace(".md", ""),
                                "snippet": top.get("snippet", "")[:300],
                            }
```
REPLACE:
```python
                        if search_results:
                            top = search_results[0]
                            # BF-950: dated, as the index line beside it is.
                            result["notebook_content"] = _notebook_read_back(
                                top.get("path", "").split("/")[-1].replace(".md", ""),
                                top.get("snippet", "")[:300],
                                top.get("frontmatter"),
                            )
```

**P4-4** `src/probos/proactive.py`

SEARCH:
```python
                        if entry:
                            result["notebook_content"] = {
                                "topic": topic_slug,
                                "snippet": entry.get("content", "")[:500],
                            }
```
REPLACE:
```python
                        if entry:
                            result["notebook_content"] = _notebook_read_back(
                                topic_slug,
                                entry.get("content", "")[:500],
                                entry.get("frontmatter"),
                            )
```

**P4-5** `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```python
        "thread_id" in observation,
    )
    return resolved


class CognitiveAgent(BaseAgent):
```
REPLACE:
```python
        "thread_id" in observation,
    )
    return resolved


def _notebook_block_lines(nb_content: Mapping[str, Any]) -> list[str]:
    """BF-950: the ``<notebook>`` block a self-monitoring context reads back.

    The opening tag carries the entry's ``updated`` and ``revision`` when the
    pull supplied them (``proactive._notebook_read_back`` normalises both), so
    the read-back is dated as the index line beside it is. Both renderers of the
    block use this, so the two prompts cannot drift apart.
    """
    attributes = f'topic="{nb_content["topic"]}"'
    updated = nb_content.get("updated")
    if updated:
        attributes += f' updated="{updated}"'
    revision = nb_content.get("revision")
    if revision is not None:
        attributes += f' revision="{revision}"'
    return [f"<notebook {attributes}>", nb_content["snippet"], "</notebook>"]


class CognitiveAgent(BaseAgent):
```

**P4-6** `src/probos/cognitive/cognitive_agent.py` (`:9415-9419`)

SEARCH:
```python
        nb_content = self_mon.get("notebook_content")
        if nb_content:
            sm_parts.append(f'<notebook topic="{nb_content["topic"]}">')
            sm_parts.append(nb_content["snippet"])
            sm_parts.append("</notebook>")
```
REPLACE:
```python
        nb_content = self_mon.get("notebook_content")
        if nb_content:
            sm_parts.extend(_notebook_block_lines(nb_content))
```

**P4-7** `src/probos/cognitive/cognitive_agent.py` (`:11324-11328`)

SEARCH:
```python
                nb_content = self_mon.get("notebook_content")
                if nb_content:
                    pt_parts.append(f'<notebook topic="{nb_content["topic"]}">')
                    pt_parts.append(nb_content["snippet"])
                    pt_parts.append("</notebook>")
```
REPLACE:
```python
                nb_content = self_mon.get("notebook_content")
                if nb_content:
                    pt_parts.extend(_notebook_block_lines(nb_content))
```

**P4-8** `tests/test_bf950_oracle_result_age.py`:
- Delete every line `@_UNTIL_M4` (`replace_all`).
- Then delete the `_UNTIL_M4 = ...` line.

## 8. Tracking (M5's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-05, the local date of M5's commit. If M5 is committed on another local date (`git log -1 --format=%cs`), use that date.
**Staging:** explicit paths only.
**Re-anchoring:** BF-948 and BF-953 will have inserted their entries first. BF-950's PROGRESS entry goes directly under `# ProbOS Progress`. Its DECISIONS entry goes directly above the `### BF-949 --` heading; BF-953 inserts below that heading, so it does not move. That is the only re-anchoring allowed, and the orchestrator re-checks both on the real base.

**P5-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-950 (2026-11-05), #1742 -- an oracle_query result is aged by its own write time, not by its retrieval.** On the base `ProvenanceEnvelope.from_oracle_result` stamped the retrieval time and `oracle_query` rendered the marker in the same call, so every entry read `age:0s` and the preamble's "weigh a STALE entry lightly" could never apply. Now the marker's age is the content's: records frontmatter `updated` (else `created`), archive `archived_at`, operational and episodic `timestamp`, semantic `indexed_at`. Graph and health record no write time and show no age. `STALE` marks content older than 30 days (`provenance.STALE_AFTER_SECONDS`). A value that does not parse gives no age and never an exception. The preamble and the tool description state exactly that (the AD-1179 golden's oracle_query description is updated in place). The self-monitoring `<notebook>` read-back now carries the entry's `updated` and `revision`, from one helper for both renderers. Ranking and retrieval are unchanged. No config field. The contract is `prompts/bf-950-oracle-result-age.md`.

```

**P5-2** `DECISIONS.md`

SEARCH:
```
### BF-949 -- The self-monitoring notebook pull reads only the agent's own notebook, as the agent (2026-11-03, #1741)
```
REPLACE:
```
### BF-950 -- An oracle_query result is aged by its own write time, not by its retrieval (2026-11-05, #1742)

- *Scope.* `cognitive/provenance.py` (`ProvenanceTag.content_timestamp`, `age_seconds`, `is_stale`, `format_inline`; `STALE_AFTER_SECONDS`, `entry_write_time`, `record_write_time`, `iso_utc`; docstrings), `tools/oracle_query_tool.py` (`_ORACLE_DISPOSITION`, the description, docstrings), `proactive.py` (`_notebook_read_back`), `cognitive/cognitive_agent.py` (`_notebook_block_lines`, both `<notebook>` renderers), the AD-1179 golden, tests. Contract `prompts/bf-950-oracle-result-age.md`.
- *OA1 (the age).* The content's write time as its tier records it; graph and health record none and show none. Rejected: an absolute date in the marker (AD-1341's entry budget); a retrieval age under another name; dropping the age.
- *OA2 (STALE).* Older than 30 days, a module constant. Rejected: 300 s on the content's age; AD-550's 72 h refresh window; a config field now.
- *OA3 (the parser).* Total: a value that does not parse is no age, so one entry cannot empty the result.
- *OA4 (the text).* The preamble and the description state an age only where the store records a write time; pinned tests updated with inline notes, none deleted.
- *OA5 (the read-back).* `<notebook>` carries `updated` (ISO-8601 UTC) and `revision` when they parse.
- *Not changed.* `oracle_service.py`, ranking and retrieval; `memory_transparency.py`; the "AD-1294 (#1090)" citation, which is correct (`a6516a8a` closes #1090).
- *Residual.* Recorded limits L1 to L14 of the contract.
- *Reversal.* Revert the BF-950 commits.

### BF-949 -- The self-monitoring notebook pull reads only the agent's own notebook, as the agent (2026-11-03, #1741)
```

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as written. **Not updated:** `docs/development/roadmap.md`.

## 9. What this does NOT change

- `oracle_service.py` (tier queries, metadata, scores, fusion, `query_formatted`, `query_refs`), `records_store.py`, `semantic.py`, `edges.py`.
- `query_with_provenance`'s signature and catch-all; the tool's tiers, bounds, schemas, id and name.
- `memory_transparency.py`; the notebook index line (still the raw `updated`); config; `EventType`; persisted shapes; no new class.

## 10. Mutation rows (campaign of record on M4's head)

- Prefix `OAM`/`NBM`; both are absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`. The same search finds `LFM-`.
- Run an unmutated baseline of the new file first, then each row against it.
- Record the base tree and the sha256 of `provenance.py`, `oracle_query_tool.py`, `proactive.py` and `cognitive_agent.py`.
- OAM-16 is valid only on a host whose local zone is not UTC. Record the offset, or "n/a (UTC host)".

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| OAM-1 | provenance.py | `content_timestamp=entry_write_time(result.source_tier, result.metadata),` | delete the line | T1, T2, T6 |
| OAM-2 | provenance.py | `return updated if updated is not None else _posix_seconds(frontmatter.get("created"))` | `return updated` | T2 `records-created-only`, `records-bad-updated-uses-created` |
| OAM-3 | provenance.py | `"archive": "archived_at",` | `"archive": "timestamp",` | T2 `archive`, T6 |
| OAM-4 | provenance.py | `"semantic": "indexed_at",` | `"semantic": "timestamp",` | T2 `semantic` |
| OAM-5 | provenance.py | `if type(value) is bool:` | `if False:` | T5 `a-bool` |
| OAM-6 | provenance.py | `if not math.isfinite(seconds) or seconds <= 0 or seconds > _MAX_POSIX_SECONDS:` | `if seconds <= 0 or seconds > _MAX_POSIX_SECONDS:` | T5 `nan` |
| OAM-7 | provenance.py | the same line | `if not math.isfinite(seconds) or seconds > _MAX_POSIX_SECONDS:` | T5 `zero`, `negative`, `before-1970` |
| OAM-8 | provenance.py | the same line | `if not math.isfinite(seconds) or seconds <= 0:` | T5 `after-the-year-9999` |
| OAM-9 | provenance.py | `except (OverflowError, ValueError, TypeError):` | `except (ValueError, TypeError):` | T5 `too-large-for-a-float`, T6 |
| OAM-10 | provenance.py | the same line | `except (OverflowError, TypeError):` | T5 `words`, `empty-text` |
| OAM-11 | provenance.py | `elif isinstance(value, date):` | `elif False:` | T1 `hand-written-date`, T10b `a-yaml-date-and-a-bool-revision` |
| OAM-12 | provenance.py | `STALE_AFTER_SECONDS: Final = 30 * 86400.0` | `STALE_AFTER_SECONDS: Final = 300.0` | T4, T8 |
| OAM-13 | provenance.py | `return max(0.0, time.time() - self.content_timestamp)` | `return time.time() - self.content_timestamp` | T4 `written-in-the-future` |
| OAM-14 | provenance.py | `return f"{int(seconds // 86400)}d"` | `return f"{int(seconds // 3600)}h"` | T2, T4 |
| OAM-15 | provenance.py | `if source_tier == "records":` | `if False:` | T1, T2 records cases |
| OAM-16 | provenance.py | `seconds = _as_utc(datetime.fromisoformat(value.strip())).timestamp()` | `seconds = datetime.fromisoformat(value.strip()).timestamp()` | T10b `naive-text-and-revision-zero` (non-UTC host) |
| OAM-17 | provenance.py | `if _is_stale(age):` | `if True:` | T4 `seconds`, `twenty-nine-days` |
| OAM-18 | provenance.py | `if age is not None:` | `if True:` | T3, T5 |
| OAM-19 | oracle_query_tool.py | `"relevance score and, where its store records when the entry was written, "` | `"relevance score and "` | T8 |
| OAM-20 | oracle_query_tool.py | `"records when it was written, its age. Each agent's personal "` | `"records when it was written, an age. Each agent's personal "` | T8, `test_ad1179_tool_schema_golden.py` |
| NBM-1 | proactive.py | `top.get("frontmatter"),` | `None,` | T9 `semantic-pull` |
| NBM-2 | proactive.py | `entry.get("frontmatter"),` | `None,` | T9 `pending-read`, T10b |
| NBM-3 | proactive.py | `"revision": revision if type(revision) is int and revision >= 1 else None,` | `"revision": revision if type(revision) is int else None,` | T10b `naive-text-and-revision-zero` |
| NBM-4 | proactive.py | the same line | `"revision": revision if revision >= 1 else None,` | T10a, T10b |
| NBM-5 | proactive.py | `"updated": iso_utc(written) if written is not None else "",` | `"updated": "",` | T9, T10b |
| NBM-6 | cognitive_agent.py | `if updated:` | `if True:` | T10a `no-frontmatter` |
| NBM-7 | cognitive_agent.py | `if revision is not None:` | `if False:` | T9, T10b `created-only` |
| NBM-8 | cognitive_agent.py | `sm_parts.extend(_notebook_block_lines(nb_content))` | `sm_parts.append(f'<notebook topic="{nb_content["topic"]}">')` | T9 (sensorium) |
| NBM-9 | cognitive_agent.py | `pt_parts.extend(_notebook_block_lines(nb_content))` | `pt_parts.append(f'<notebook topic="{nb_content["topic"]}">')` | T9 (proactive) |

## 11. Recorded limits

- **L1.** Graph edges store `created_at`/`updated_at` (`edges.py:93-94`), but the Oracle does not carry them into metadata, so graph shows no age. Health readings are live but carry no timestamp. Changing `oracle_service.py` is out of scope (acceptance 4); considered, deferred.
- **L2.** Semantic `indexed_at` is when the index row was last written. For a row re-indexed at boot, the age counts from that write, not from when the underlying definition changed.
- **L3.** Archive `archived_at` is when the entry entered the archive, not when its source record was first written.
- **L4.** `query_refs` sets `MemoryRef.timestamp` from `metadata["timestamp"]` only (`oracle_service.py:816`). `query_formatted` ages entries by the same key (`:747-748`). So records, archive and semantic carry no time on those paths. Considered, deferred.
- **L5.** A naive time is read as UTC. OAM-16 is killed only on a host that is not on UTC.
- **L6.** One 30-day threshold for every tier, as a constant, not config.
- **L7.** The marker carries no date, revision or author (OA1, AD-1341's budget). The notebook read-back carries the date and the revision.
- **L8.** A first-write notebook entry shows no `revision`, although AD-552's index treats a missing revision as 1.
- **L9.** The `memory_transparency.py:5` docstring is not changed: the module is dormant, and whether to wire or retire it is its own decision.
- **L10.** The issue's "AD-1294 (#1090)" item is refuted (`a6516a8a` closes #1090); no change.
- **L11.** The age is computed when the marker is rendered. An agent that reads a result many turns later sees the age as of the render.
- **L12.** The worst archive marker grows from 39 to 48 characters. M1 re-checks AD-1341's budgets (s4, s5, s6) before any `src` change.
- **L13.** A write time in the future reads as `0s` and not STALE.
- **L14.** The index line keeps the raw `updated` text, so the index and the block may spell the same moment differently.

## 12. The Captain's items

- **None to decide.** The changed agent-visible text (marker, preamble, tool description, `<notebook>` tag) corrects a signal that was false. It weakens no control.
- **Optional live check after merge (reads only):** in a vessel session, an agent's `oracle_query` for a known older record shows `age:<n>d`, with `STALE` when it is past 30 days.

## 13. Verified Against Codebase (2026-11-04, on `728e1fc2`)

```
git rev-parse HEAD -> 728e1fc2d2f49fd04584adf2a41d1dfa68befcb5
git diff --stat ca0ca20b 728e1fc2 -- <the nine touched files> -> (empty)
provenance.py:19-59   ProvenanceTag; :35 `return time.time() - self.retrieval_timestamp`; :40 `return self.age_seconds > 300`
provenance.py:71      "Used by TieredKnowledgeLoader to pass provenance through"
provenance.py:83-94   from_oracle_result; :89 `retrieval_timestamp=time.time(),`
provenance.py:116-122 query_with_provenance catches Exception, returns []
oracle_query_tool.py:89-97 _ORACLE_DISPOSITION "...relevance score and an age, so weigh a weakly-matching or STALE entry"
oracle_query_tool.py:148 `candidate = f"{out}\n{_cap_entry(envelope.render())}\n"`
oracle_query_tool.py:194-195 description "...retrieval relevance score and an age. Each agent's personal "
oracle_query_tool.py:317-325 lazy import + query_with_provenance(...)
oracle_service.py:36-48 OracleResult; :1079-1082 keyword records {"path","frontmatter"}; :1127-1132 semantic records frontmatter
oracle_service.py:1154 operational {"timestamp"}; :1187 archive "archived_at"; :963/:981 episodic "timestamp"
oracle_service.py:1236-1240 semantic `**metadata`; :1380-1392, :1549-1561 graph (no time); :1619-1683 health (no time)
oracle_service.py:298-305 _format_age; :745-760 query_formatted; :816 query_refs timestamp; :1174-1175 archive score decays by age
oracle_service.py:347-357 __init__(records_store=, archive_store=, semantic_layer=); :69 _RECORDS_QUERY_SCOPE = "ship"
semantic.py:260,284,309,334,360,439 "indexed_at": time.time(); :410 json.dumps(frontmatter, default=str); :504-505 records dropped without scope
records_store.py:305-323 created/updated/revision; :1271 yaml.safe_load; :1168-1172 search returns frontmatter; :999 read_entry returns frontmatter
records_store.py:488-544 write_notebook; :1109-1117 search(query, scope, *, reader_id, reader_department, directory)
edges.py:93-94 created_at/updated_at
config_models/knowledge.py:328 notebook_staleness_hours: float = 72.0; notebook_quality.py:211-239 its use
proactive.py:44-45 imports; :278 def _parse_hhmm; :2799-2805 index carries "updated","revision"; :2844-2849, :2864-2868 producers
cognitive_agent.py:16 `from collections.abc import Mapping`; :1028-1032 before `class CognitiveAgent(BaseAgent):`
cognitive_agent.py:9349 _sensorium_ext_self_monitoring; :9407 index "(updated ...)"; :9415-9419 block; :11314 index; :11324-11328 block
tests/test_ad677_context_provenance.py:9-14 imports; :34-108 the five pinned tests
tests/test_ad1139_oracle_query_tool.py:54-57 _PROVENANCE_MARKER_RE; :386-390 framing asserts; :394-395 "age:0s" literals
tests/test_ad1341_s4_lessons.py:508-511 _WORST_MARKER; s5:39 imports it; s6:73-74
tests/fixtures/ad1179_tool_definition_golden.json:2 _header; :3 _captured_at_commit; :38 the description
tests/test_self_monitoring.py:573-593 _build_proactive_prompt; tests/test_bf949_notebook_reader_identity.py:48-91 harness
tests/test_ad1140_publish_finding.py:1413-1434 real store + OracleService + resolver precedent
decomposer.py:51-58 _CAPABILITY_GAP_RE; gen_ad_ledger.py:126-132 _STATUS_PATTERNS
git show a6516a8a -> "Closes #1200. Closes #1090." ; gh issue view 1090 -> "BF-689: ..." CLOSED
```

## Absence Verified (2026-11-04, on `728e1fc2`)

```
A1 CLAIM: ProvenanceTag/Envelope/format_inline have no consumer beyond render, the tool and tests
   RUN:   rg "ProvenanceTag|ProvenanceEnvelope|format_inline|query_with_provenance|from_oracle_result|retrieval_timestamp|cognitive\.provenance" -g "*.py"
   FOUND: provenance.py; oracle_query_tool.py:26,300,317,319; memory_transparency.py:5,46,78 (its own class);
          tests/test_ad677_*; tests/test_ad1139_*:829
   HOLDS: yes
A2 CLAIM: TieredKnowledgeLoader does not use provenance
   RUN:   the A1 search; rg TieredKnowledgeLoader src
   FOUND: no tiered_knowledge.py hit in A1; provenance.py:71 is the only provenance mention
   HOLDS: yes
A3 CLAIM: memory_transparency has no production caller
   RUN:   rg -l "memory_transparency|MemoryTransparencyService|TransparentMemory|MemoryProvenance"
   FOUND: src only memory_transparency.py itself; tests/test_ad678_*; prompts/docs
   HOLDS: yes
A4 CLAIM: notebook_content has two producers and two renderers
   RUN:   rg notebook_content src ; rg "notebook topic=|<notebook " -g "*.py"
   FOUND: producers proactive.py:2846, :2865; renderers cognitive_agent.py:9417, :11326
   HOLDS: yes
A5 CLAIM: no other test pins the marker text
   RUN:   rg "\[source:|relevance:\d|age:\d|age:0s" tests ; rg "_WORST_MARKER|_WORST_LABEL" tests
   FOUND: test_ad1139 :55,:355,:394,:395,:466,:545,:761; test_ad1140:1438; test_ad1341_s4:511,:540; s5:39,:263; s6:74,:234;
          test_ad677:66,:107; test_ad678:76 (its own class)
   HOLDS: yes (prefix-only asserts are unaffected)
A6 CLAIM: only the AD-1179 golden pins the description
   RUN:   rg -o ".{0,60}retrieval relevance score.{0,40}" tests/fixtures ; rg oracle_query tests/fixtures/ad1152_agentic_off_golden.json
   FOUND: ad1179_tool_definition_golden.json:38 only; ad1152 none
   HOLDS: yes
A7 CLAIM: no standing order or config describes the marker to agents
   RUN:   rg -l "\[source:|STALE entr|age:\d+[smh]" -g "!**/*.py"
   FOUND: prompts/ (7), docs/research/clark-extended-mind-absorption.md
   HOLDS: yes
A8 CLAIM: mutation prefixes OAM and NBM are free
   RUN:   rg -l "\b(OAM|NBM)-\d" prompts DECISIONS.md PROGRESS.md ; control rg -l "\bLFM-\d" (same scope)
   FOUND: none ; control finds prompts/bf-948-list-files-read-policy.md
   HOLDS: yes
A9 CLAIM: no source-scan test reads the lines M4 changes
   RUN:   rg "notebook topic|snippet\"\)\[:300\]|_ORACLE_DISPOSITION|from_oracle_result" tests
   FOUND: only value-level uses (test_ad1139, test_ad1140, test_ad677)
   HOLDS: yes
```

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:**
  - No class grows past its triggers: `CognitiveAgent` and the proactive loop shrink or stay level, and `ProvenanceTag` grows by about 15 lines.
  - The one new import, `probos.proactive` → `probos.cognitive.provenance`, comes from an unranked module.
  - Only public names cross a module.
- **`check_dormant_classes.py`:** no class added.
- **Goldens:** AD-1179 changes by P3-5/P3-6 only; AD-1152 does not contain the text.
- **Config:** none. **EventType:** none.
- **Collection:** names the fix adds are not imported at module level, so M1 collects on the base. The strict xfails keep G1 green.

## 15. Prior Art and Blind Spots

- **Internal:**
  - AD-677: the original tag.
  - AD-1294 (`a6516a8a`): the same class of mislabel. Its review even reproduced `age:0s`, and it updated pinned tests with inline notes.
  - `oracle_service.query_formatted`, which already ages entries by the content's `timestamp` (`:747-748`): **adopted**, generalised per tier.
  - AD-550/AD-555's 72 h staleness: **rejected** as the threshold (a refresh window).
  - AD-1341's entry budget: **respected** (OA1).
  - Found by `docs/research/clark-extended-mind-absorption.md` (PR #1740).
- **External** (from a search summary, not full-text reads):
  - The HoH benchmark puts each document's last-modified time and the current date in the prompt ([arXiv 2503.04800](https://arxiv.org/pdf/2503.04800)). **Adopted:** the content's own time. **Adapted:** a relative age, because the agent's prompt already carries temporal context and the marker must stay short.
  - "It's About Time" notes that retrieval-augmented models ignore temporal metadata ([arXiv 2401.13222](https://arxiv.org/pdf/2401.13222)).
  - Recency re-ranking ([arXiv 2509.19376](https://arxiv.org/html/2509.19376v1)): **rejected**, since acceptance 4 keeps ranking unchanged and the archive score already decays.
  - `reference-projects.md`, judged on 2026-11-04: the memory rows (RAGFlow, LoCoMo, 2026-05-08) are at exactly 180 days, so not yet overdue. No row is updated.
- **Blind spots found:**
  1. AD-1341's budget constants pin the retrieval age as the worst case (`age:59s`).
  2. A raising parser would empty every result through `query_with_provenance`'s catch-all.
  3. Three shapes of `updated` (YAML date, ISO text, `str(datetime)`) plus float test doubles.
  4. Windows bounds `fromtimestamp`.
  5. A 300 s threshold on the content's age would mark everything STALE.
  6. The wire tool description, pinned by a golden, also promised "an age".
  7. Graph and health must not be given an invented time.
  8. The two `<notebook>` renderers would drift unless one helper renders both.

## 16. Diff Reviewer: properties to verify

M2 to M4 are shared contracts: review each whole contract, not the delta.

1. Rendering only. `oracle_service.py`, `records_store.py` and `semantic.py` are byte-identical. Envelope order, relevance, content and the metadata object equal the `OracleResult`'s (T7).
2. The marker grammar is exactly `[source:<tier> relevance:<2dp>`, then optionally ` age:<n><s|m|h|d>`, then ` STALE` only after an age, then `]`. An age appears if and only if the tier's recorded write time parses (§1 table). STALE appears if and only if the age exceeds `STALE_AFTER_SECONDS`.
3. `_posix_seconds`, `record_write_time` and `entry_write_time` raise for no input. The accepted range is 0 < s ≤ 253402300799, finite, and a bool is never accepted.
4. `age_seconds` is `None` if and only if `content_timestamp` is `None`, and it is never negative. `retrieval_timestamp` is still set and is not rendered.
5. Every `src` reader of `age_seconds`, `is_stale` and `format_inline` on `ProvenanceTag` is `render` (Absence A1).
6. The preamble and the description state an age only where a write time is recorded, and "thirty days" equals the constant (T8). The DD-3 regex stays clean. The preamble still contains "relevance", lowercase "weigh", "not how strongly its author holds it", "Cite an entry" and "do not narrate this lookup", and never "confidence".
7. The golden differs from the base only in oracle_query's description substring and the `_header` sentence, and `test_ad1179_tool_schema_golden.py` passes.
8. Both `<notebook>` renderers call `_notebook_block_lines`. `updated` is ISO-8601 UTC to the second, from `updated`, else `created`. `revision` is a positive non-bool int or absent. A read-back with no parseable frontmatter renders the base's bare tag.
9. Every pinned-defect assertion is updated with an inline BF-950 note and none is deleted. `_WORST_MARKER` is the true worst-case marker.
10. No config field, `EventType`, persisted key or class is added. `content_timestamp` is defaulted and is the last field.
11. Every new docstring, comment and test docstring is true of the head.
12. Each xfail mark is removed only at its milestone, and each such test failed on the base for the reason its marker names. T7 and T10a pass on the base.

## 17. Acceptance criteria

1. An `oracle_query` result for a Records entry last updated months ago reads `age:<n>d STALE`, never `age:0s` (T1, T2). An entry with no recorded write time shows no age (T3).
2. The preamble and the description match the marker (T8).
3. The proactive `<notebook>` read-back carries the entry's `updated` date, and `revision` when it parses (T9, T10b).
4. Ranking and retrieval are unchanged (T7, §16 item 1).
5. Every §10 mutant is killed (OAM-16 where the host is not on UTC). G1 to G5 and the §14 checks pass, and the broad gate's receipt is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## For the Captain

None. The changed agent-visible text corrects a false signal, which is within the Delegated AD Execution envelope, and it weakens no control. The orchestrator should check one risk at M1: G1's AD-1341 budget re-check needs 9 characters of headroom in the exit-note budget. If it fails, M1 stops and returns to the Architect before any source change.

Sources:
- [HoH: A Dynamic Benchmark for Evaluating the Impact of Outdated Information on RAG (arXiv 2503.04800)](https://arxiv.org/pdf/2503.04800)
- [It's About Time: Incorporating Temporality in Retrieval Augmented Language Models (arXiv 2401.13222)](https://arxiv.org/pdf/2401.13222)
- [Solving Freshness in RAG: A Simple Recency Prior (arXiv 2509.19376)](https://arxiv.org/html/2509.19376v1)

## Amendment 1 (review round 1: F1 and F2)

**Ordering:** apply P6-0 to the contract first, then append this whole section verbatim to the end of `prompts/bf-950-oracle-result-age.md`, both in M6's commit. Every `src` and tracker SEARCH is anchored on `eed3a3ee`, because M6 is test-only. P7-5 and P8-2 remove markers that P6-1 and P6-2 add, so they are anchored on M6's tree; that is the only exception.

**P6-0** `prompts/bf-950-oracle-result-age.md`

SEARCH:
```
**Status:** ready to build. **Base:** drafted on `728e1fc2`
```
REPLACE:
```
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 1 (review round 1, F1 and F2) adds milestones M6 to M9, tests T11 and T12, mutation rows NBM-10 to NBM-12 and OAM-21 to OAM-22, limits L15 to L17 and §16 items 13 to 17; it is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2`
```

### A1.1 Findings and decisions

- **F1 (P2, ordinary reach through an operator-edited file; not a regression).** In `_build_self_monitoring_context` the AD-550 index sorted the raw `updated`, the AD-552 repetition check compared the raw `revision`, and the topic count hashed the raw `topic`. All three sat inside the `try` that also held the BF-949/BF-950 semantic pull. So one hand-edited notebook entry (a YAML date beside the store's text, a text revision, a list topic) ended the read-back for the cycle. Store-written files never produce the first two (`records_store.py:305`, `:323`, `:354`). The store rewrites `updated` as text. A text revision raises at `:323`, is caught at `:333`, and that update is written without one. A list topic can be store-written only through the records API, which passes a JSON `topic` through (`routers/records.py:146-153`; Amendment 2, L19). This contract's §1.5 names the hand-written date as a supported shape. **Fix (M7):** the pull gets its own error boundary; the index orders by `record_write_time`; the repetition check counts only an int revision.
- **F2 (P2, ordinary reach with `crew_sigma_context_enabled=True`; not a regression).** `crew_executor._COMMONS_DISPOSITION` promised every entry "an age" and told agents to weigh a "STALE" entry lightly. `_render_commons_entry` shows an age only for a numeric `metadata["timestamp"]` and never writes STALE. **Fix (M8):** text only, "sometimes an age", "old" instead of "STALE", +8 characters. The renderer is unchanged (L16).
- **§9 note.** The index line still shows the raw `updated` (L14 holds). Its order is now that of the parsed write time, which equals the raw order for every store-written entry.

### A1.2 Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M6 | STANDARD | test only (plus this contract) | P6-0, P6-1, P6-2 | G6 |
| M7 | STANDARD | no (the dict's keys and shape are unchanged; only when `notebook_content` is produced changes) | P7-1 to P7-5 | G7 |
| M8 | STANDARD | no (agent-visible text; no pinned test changes) | P8-1, P8-2 | G8 |
| M9 | STANDARD | trackers | P9-1, P9-2, P9-3, ledger | G9 |

Count notes: the new-file counts below come from reading the file (39 cases at HEAD, plus T11's 3 and T12's 1). Every count marked **measure** has to be measured on the oracle tree.

- **G6:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf950_oracle_result_age.py -q -n 0`.
  - Expected: **39 passed, 4 xfailed**.
  - Then `... -m pytest tests/test_bf950_oracle_result_age.py -q -n 0 --runxfail -k "hand_edited or crew_consult"`. Expected: **4 failed**:
    - three T11 cases with `KeyError: 'notebook_content'`;
    - T12 at the line `assert ("STALE" in _COMMONS_DISPOSITION) == ("STALE" in rendered)`.
  - Any failure on a `# premise` line is a hard stop.
- **G7:** `... -m pytest tests/test_bf950_oracle_result_age.py tests/test_self_monitoring.py tests/test_bf949_notebook_reader_identity.py tests/test_ad550_notebook_dedup.py tests/test_ad552_notebook_self_repetition.py tests/test_proactive_quality.py -q -n 0`, then `... -P scripts/check_architecture_principles.py --check`.
  - New file: **42 passed, 1 xfailed**.
  - Others: 0 failed, counts equal to G4's (**measure**).
- **G8:** `... -m pytest tests/test_bf950_oracle_result_age.py tests/test_ad1141_crew_loop_sigma.py tests/test_ad1294_read_provenance_rendering.py -q -n 0`, then `check_architecture_principles.py --check`.
  - New file: **43 passed**.
  - Others: 0 failed, counts equal to M5's head (**measure**). `test_char_budget_is_enforced_and_reports_the_elision` must pass; it fails if the +8 characters exceed the budget margin.
- **G9:** `... -P scripts/gen_ad_ledger.py`; `... -P scripts/gen_ad_ledger.py --check` (exit 0); `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
  - Expected: the same count as G5 (33).
  - Stage the two ledger files as written (whether they change at all is **measure**).
- **Mutation campaign of record, on M8's head.**
  - Run an unmutated baseline of the new file first.
  - Record the sha256 of `proactive.py` and `crew_executor.py`.
  - Run NBM-10 to NBM-12 and OAM-21 to OAM-22.
  - Rerun NBM-1 to NBM-5, because `proactive.py` differs from M4's campaign file (their lines are unchanged).
- **Broad gate:** once, after round 2, as §4 says.

### A1.3 Commit messages

- M6: `BF-950 M6: reproductions of the notebook read-back lost to one hand-edited entry and of the crew-consult STALE promise`
- M7: `BF-950 M7: one hand-edited notebook entry no longer ends the self-monitoring read-back`
- M8: `BF-950 M8: the crew-consult preamble promises only what its entries carry`
- M9: `BF-950 M9: trackers and ledger for Amendment 1`

### A1.4 Tests

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T11 | `test_one_hand_edited_entry_does_not_cost_the_read_back` | 3 | F1, real store → pull → sensorium renderer | M7 |
| T12 | `test_the_crew_consult_preamble_promises_only_what_its_entries_carry` | 1 | F2, preamble × renderer crossing | M8 |

**P6-1** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
        assert _CAPABILITY_GAP_RE.search(text) is None
```
REPLACE:
```python
        assert _CAPABILITY_GAP_RE.search(text) is None


_UNTIL_M8 = pytest.mark.xfail(
    strict=True, reason="BF-950 M8: the crew-consult preamble promises a STALE flag its entries never carry",
)


@_UNTIL_M8
def test_the_crew_consult_preamble_promises_only_what_its_entries_carry() -> None:
    """Review round 1 (F2): the crew consult's own preamble promised every entry an age and a STALE flag.

    ``crew_executor._render_commons_entry`` dates an entry only from a numeric ``metadata["timestamp"]`` and
    never writes ``STALE``, so a forty-day-old entry is rendered with an age and no flag. The preamble and the
    renderer are held together here, as AD-1294's crossing test holds the other fields.
    """
    from probos.cognitive.crew_executor import _COMMONS_DISPOSITION, _render_commons_entry

    rendered = _render_commons_entry(
        _result("operational", {"timestamp": time.time() - _FORTY_DAYS_AGO}, score=0.71),
    )
    assert "40d ago" in rendered  # premise: an old entry with a numeric timestamp is dated
    assert ("STALE" in _COMMONS_DISPOSITION) == ("STALE" in rendered)
    assert "and sometimes an age, so weigh a weakly-matching or old entry lightly." in _COMMONS_DISPOSITION
    assert _CAPABILITY_GAP_RE.search(_COMMONS_DISPOSITION) is None
```

**P6-2** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
    result = await _self_monitoring(
        _mock_records({"content": "Notebook body", "frontmatter": frontmatter}), "Bones", pending="my-topic",
    )
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise
    assert _notebook_tags(_sensorium_render(result)) == [expected]
```
REPLACE:
```python
    result = await _self_monitoring(
        _mock_records({"content": "Notebook body", "frontmatter": frontmatter}), "Bones", pending="my-topic",
    )
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise
    assert _notebook_tags(_sensorium_render(result)) == [expected]


_UNTIL_M7 = pytest.mark.xfail(
    strict=True, reason="BF-950 M7: one hand-edited notebook entry ends the self-monitoring notebook block",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["a-yaml-date-beside-text", "a-text-revision", "a-list-topic"])
@_UNTIL_M7
async def test_one_hand_edited_entry_does_not_cost_the_read_back(tmp_path: Path, shape: str) -> None:
    """Review round 1 (F1): one notebook entry edited outside the store ended the whole block for the cycle.

    The index sorted the raw ``updated`` (a YAML date beside the store's text raised), the repetition check
    compared the raw ``revision`` (text raised), and the topic count hashed the raw ``topic``; each sat inside
    the error boundary of the read-back, so the agent lost the read-back with the index. A real store, its
    files edited as a person would edit them.
    """
    store = await _records(tmp_path)
    now = time.time()
    await store.write_notebook("Zephyr", "first-topic", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "second-topic", "engineering notes, second", department="engineering")
    first, second = "notebooks/Zephyr/first-topic.md", "notebooks/Zephyr/second-topic.md"
    if shape == "a-yaml-date-beside-text":
        assert type(_rewrite_frontmatter(store, first, updated=date(2026, 5, 3))["updated"]) is date  # premise
        assert type(_rewrite_frontmatter(store, second)["updated"]) is str  # premise: the store writes text
    elif shape == "a-text-revision":
        assert type(_rewrite_frontmatter(store, first, updated=_iso(now), revision="4")["revision"]) is str  # premise
        _rewrite_frontmatter(store, second, updated=_iso(now - 3600), revision=5)
    else:
        assert type(_rewrite_frontmatter(store, first, topic=["engines", "warp"])["topic"]) is list  # premise

    result = await _self_monitoring(store, "Zephyr")

    content = result["notebook_content"]
    assert content["topic"] in {"first-topic", "second-topic"} and "engineering notes" in content["snippet"]
    tags = _notebook_tags(_sensorium_render(result))
    assert len(tags) == 1 and tags[0].startswith(f'<notebook topic="{content["topic"]}" updated="'), tags
    if shape == "a-yaml-date-beside-text":
        assert [entry["topic"] for entry in result["notebook_index"]] == ["second-topic", "first-topic"]
    elif shape == "a-text-revision":
        warnings = result.get("notebook_repetition_warnings", [])
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings
```

### A1.5 M7

**P7-1** `src/probos/proactive.py`

SEARCH:
```python
        if tier["notebooks"]:
            try:
                if hasattr(rt, '_records_store') and rt._records_store:
                    entries = await rt._records_store.list_entries(
```
REPLACE:
```python
        if tier["notebooks"]:
            # BF-950 Amendment 1: bound before the listing, so the read-back below
            # still runs when the index or repetition enrichment raises.
            entries: list[dict] = []
            try:
                if hasattr(rt, '_records_store') and rt._records_store:
                    entries = await rt._records_store.list_entries(
```

**P7-2** `src/probos/proactive.py`

SEARCH:
```python
                        # AD-550: Enhanced index with content previews + recency
                        sorted_entries = sorted(
                            entries,
                            key=lambda e: e.get("frontmatter", {}).get("updated", ""),
                            reverse=True,
                        )
```
REPLACE:
```python
                        # AD-550: Enhanced index with content previews + recency
                        # BF-950 Amendment 1: ordered by record_write_time, which reads every
                        # shape of ``updated`` (the store's text, a hand-written YAML date) as
                        # one type; the raw sort raised on a date beside text. An entry with no
                        # parseable write time sorts last, as an empty ``updated`` did.
                        sorted_entries = sorted(
                            entries,
                            key=lambda e: record_write_time(e.get("frontmatter")) or 0.0,
                            reverse=True,
                        )
```

**P7-3** `src/probos/proactive.py`

SEARCH:
```python
                        for ei in enriched_index:
                            rev = ei.get("revision", 1)
                            if rev >= _rep_thresh and ei.get("updated"):
```
REPLACE:
```python
                        for ei in enriched_index:
                            rev = ei.get("revision", 1)
                            # BF-950 Amendment 1: only an int revision is counted (the store
                            # writes nothing else); a hand-written text revision raised here.
                            if type(rev) is int and rev >= _rep_thresh and ei.get("updated"):
```

> **Amendment 2 note.** The comment P7-3 adds says the store writes only an int revision. That is false: the store carries an existing revision forward as `existing_rev + 1` (`records_store.py:322-323`), so an operator's 3.5 becomes 4.5. P11-4 corrects the source. P7-3 stays as M7 applied it.

**P7-4** `src/probos/proactive.py`

SEARCH:
```python
                        if warnings:
                            result["notebook_repetition_warnings"] = warnings

                    # Semantic pull: the agent's own notebook entries that contain its
                    # department name (frontmatter included). BF-949: the walk is confined
                    # to the agent's notebook directory and reads as the agent, so it sees
                    # only entries under that directory, and of those only what it may read.
                    dept = getattr(agent, 'department', '')
                    if dept and entries:
                        search_results = await rt._records_store.search(
                            dept,
                            scope="ship",
                            reader_id=callsign,
                            reader_department=dept,
                            directory=f"notebooks/{callsign}",
                        )
                        if search_results:
                            top = search_results[0]
                            # BF-950: dated, as the index line beside it is.
                            result["notebook_content"] = _notebook_read_back(
                                top.get("path", "").split("/")[-1].replace(".md", ""),
                                top.get("snippet", "")[:300],
                                top.get("frontmatter"),
                            )
            except Exception:
                logger.debug("Self-monitoring: notebook query failed for %s", callsign, exc_info=True)
```
REPLACE:
```python
                        if warnings:
                            result["notebook_repetition_warnings"] = warnings
            except Exception:
                logger.debug("Self-monitoring: notebook query failed for %s", callsign, exc_info=True)

            # Semantic pull: the agent's own notebook entries that contain its
            # department name (frontmatter included). BF-949: the walk is confined
            # to the agent's notebook directory and reads as the agent, so it sees
            # only entries under that directory, and of those only what it may read.
            # BF-950 Amendment 1: its own error boundary, so an index or repetition
            # failure on one entry no longer skips the read-back. It still runs only
            # when the listing above returned entries.
            try:
                dept = getattr(agent, 'department', '')
                if dept and entries:
                    search_results = await rt._records_store.search(
                        dept,
                        scope="ship",
                        reader_id=callsign,
                        reader_department=dept,
                        directory=f"notebooks/{callsign}",
                    )
                    if search_results:
                        top = search_results[0]
                        # BF-950: dated, as the index line beside it is.
                        result["notebook_content"] = _notebook_read_back(
                            top.get("path", "").split("/")[-1].replace(".md", ""),
                            top.get("snippet", "")[:300],
                            top.get("frontmatter"),
                        )
            except Exception:
                logger.debug("Self-monitoring: notebook read-back failed for %s", callsign, exc_info=True)
```

**P7-5** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
_UNTIL_M7 = pytest.mark.xfail(
    strict=True, reason="BF-950 M7: one hand-edited notebook entry ends the self-monitoring notebook block",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["a-yaml-date-beside-text", "a-text-revision", "a-list-topic"])
@_UNTIL_M7
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["a-yaml-date-beside-text", "a-text-revision", "a-list-topic"])
```

### A1.6 M8

**P8-1** `src/probos/cognitive/crew_executor.py`

SEARCH:
```python
_COMMONS_DISPOSITION: str = (
```
REPLACE:
```python
# BF-950 Amendment 1: name only what ``_render_commons_entry`` emits. It shows an
# age only for a result whose ``metadata["timestamp"]`` is a number, and it never
# writes STALE; a BF-950 test holds the two together.
_COMMONS_DISPOSITION: str = (
```

SEARCH:
```python
    "tier, a retrieval relevance score, an author where one was recorded, and "
    "an age, so weigh a weakly-matching or STALE entry lightly. Relevance is "
```
REPLACE:
```python
    "tier, a retrieval relevance score, an author where one was recorded, and "
    "sometimes an age, so weigh a weakly-matching or old entry lightly. "
    "Relevance is "
```

**P8-2** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
_UNTIL_M8 = pytest.mark.xfail(
    strict=True, reason="BF-950 M8: the crew-consult preamble promises a STALE flag its entries never carry",
)


@_UNTIL_M8
def test_the_crew_consult_preamble_promises_only_what_its_entries_carry() -> None:
```
REPLACE:
```python
def test_the_crew_consult_preamble_promises_only_what_its_entries_carry() -> None:
```

### A1.7 M9 (trackers)

These amend the already-committed P5-1 and P5-2 entries in place: the entry heads and their dates are unchanged, so §8's head constraint and date rule still hold. Stage explicit paths only.

**P9-1** `PROGRESS.md`

SEARCH:
```
Ranking and retrieval are unchanged. No config field. The contract is `prompts/bf-950-oracle-result-age.md`.
```
REPLACE:
```
Ranking and retrieval are unchanged. No config field. Review round 1 (Amendment 1): the read-back no longer depends on the notebook index and repetition check succeeding, which one hand-edited entry (a YAML date beside the store's text, a text revision) made raise; the index orders entries by their parsed write time; and the crew-consult preamble (`crew_executor._COMMONS_DISPOSITION`) no longer promises every entry an age and a STALE flag its renderer never emits. The contract is `prompts/bf-950-oracle-result-age.md`.
```

**P9-2** `DECISIONS.md`

SEARCH:
```
`proactive.py` (`_notebook_read_back`), `cognitive/cognitive_agent.py`
```
REPLACE:
```
`proactive.py` (`_notebook_read_back`; Amendment 1: the notebook index's sort key, the repetition check's revision read and the read-back's own error boundary), `cognitive/crew_executor.py` (`_COMMONS_DISPOSITION`, Amendment 1), `cognitive/cognitive_agent.py`
```

**P9-3** `DECISIONS.md`

SEARCH:
```
- *Residual.* Recorded limits L1 to L14 of the contract.
```
REPLACE:
```
- *Amendment 1 (review round 1).* The read-back has its own error boundary, and the index orders by parsed write time and counts only an int revision, so one hand-edited notebook entry no longer ends the read-back. The crew-consult preamble promises an age only "sometimes" and no STALE flag, as its renderer emits. Rejected: moving the crew renderer onto `entry_write_time` (a second agent-visible marker change; recorded on #1754).
- *Residual.* Recorded limits L1 to L17 of the contract.
```

Then regenerate the ledger as G9 says.

### A1.8 Mutation rows

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| NBM-10 | proactive.py | `key=lambda e: record_write_time(e.get("frontmatter")) or 0.0,` | `key=lambda e: e.get("frontmatter", {}).get("updated", ""),` | T11 `a-yaml-date-beside-text` |
| NBM-11 | proactive.py | `if type(rev) is int and rev >= _rep_thresh and ei.get("updated"):` | `if rev >= _rep_thresh and ei.get("updated"):` | T11 `a-text-revision` |
| NBM-12 | proactive.py | `if dept and entries:` | `if dept and entries and "notebook_summary" in result:` | T11 `a-list-topic` (campaign on M8's head); from M10 on, T14 (Amendment 2: after M11 no real-store shape ends the enrichment before the summary) |
| OAM-21 | crew_executor.py | `"sometimes an age, so weigh a weakly-matching or old entry lightly. "` | `"sometimes an age, so weigh a weakly-matching or STALE entry lightly. "` | T12 |
| OAM-22 | crew_executor.py | the same line | `"an age, so weigh a weakly-matching or old entry lightly. "` | T12 |

### A1.9 Limits (added; L1 to L14 unchanged; L14 still holds, see A1.1)

- **L15.** (Amended by Amendment 2.) Since M11, no frontmatter shape a real store lists is known to make the index or repetition enrichment raise (A2.11), with one exception. A naive text `updated` that local time cannot convert (for example `1900-01-01T00:00:00` on Windows) can make `.timestamp()` raise `OSError` or `OverflowError` past the `except (ValueError, TypeError)` at the index's recency and at the repetition check. This was found by reading and is not yet measured. Such a failure costs the index for that cycle, never the read-back (T14). The repetition check still skips an entry whose `updated` is a YAML date (it parses with `datetime.fromisoformat`). Recorded on #1754.
- **L16.** The crew-consult renderer still dates an entry only from a numeric `metadata["timestamp"]` and never writes STALE, so records, archive and semantic entries show no age there. The preamble now says "sometimes an age". Moving the renderer onto `entry_write_time` is recorded on #1754.
- **L17.** An entry with no parseable `updated` but a parseable `created` now sorts in the index by `created`. The store always writes `updated`, so no store-written entry is affected.

### A1.10 Diff Reviewer properties (added to §16)

13. (Amended by Amendment 2.) A notebook whose every write came through the store with a text topic renders exactly as at M5's head: the index order, the index fields (raw `updated`; `revision` defaulting to 1), the repetition warnings and the read-back. The sort key orders every store-written `updated` as the raw text did. The store creates every revision as an int, and the guard counts only an int. A fractional revision an operator wrote stays fractional when the store carries it forward (`existing_rev + 1`, `records_store.py:322-323`). Such a history gives no repetition warning where M5's head gave one; nothing renders the warnings (L18).
14. The semantic pull runs whenever `list_entries` returned entries, whatever the index or repetition enrichment raised. It does not run when the listing raised or was empty, or when the agent has no department. Its exception is logged at debug with the callsign and ends only the pull.
15. The pending-read path, its order after the pull (it still overwrites `notebook_content`), and the set of keys `_build_self_monitoring_context` can return are unchanged.
16. `_COMMONS_DISPOSITION` promises only what `_render_commons_entry` emits and contains no "STALE". It still contains "tier", "relevance", "author" and "age", and never "confidence". The DD-4 gap regex finds nothing in it. It grew by 8 characters, and `test_char_budget_is_enforced_and_reports_the_elision` still renders exactly one entry.
17. In `crew_executor.py` only the constant and its comment change; `_render_commons_entry` and `_format_consult_age` are byte-identical. §16 item 12 extends to T11 and T12: each marker is removed only at its milestone, after G6 showed the named failure.

### A1.11 Verified against codebase (2026-11-05, on `eed3a3ee`)

```
proactive.py:45      from probos.cognitive.provenance import iso_utc, record_write_time
proactive.py:2760-63 if tier["notebooks"]: / try: / if hasattr(rt, '_records_store') ... / entries = await ...list_entries(
proactive.py:2768-73 sorted(entries, key=lambda e: e.get("frontmatter", {}).get("updated", ""), reverse=True)
proactive.py:2779    set(e.get("frontmatter", {}).get("topic", ...) for e in entries)
proactive.py:2837-39 for ei in enriched_index: / rev = ei.get("revision", 1) / if rev >= _rep_thresh and ei.get("updated"):
proactive.py:2849-74 warnings ... semantic pull ... except Exception: logger.debug("Self-monitoring: notebook query failed ...")
proactive.py:2876-94 pending read, its own try, overwrites notebook_content
provenance.py:81-90  record_write_time(frontmatter) -> float | None (positive or None)
records_store.py:305,:323,:354  updated = now isoformat; revision = existing_rev + 1; yaml.dump
records_store.py:1143-1176  search: keyword match over raw text, returns path/frontmatter/score/snippet
crew_executor.py:132-141  _COMMONS_DISPOSITION ("an age, so weigh a weakly-matching or STALE entry lightly")
crew_executor.py:678-694, :722-735  _format_consult_age(int|float only); marker never writes STALE
crew_executor.py:785-804  block budget includes the disposition; _BUDGET_NOTE at :157-160
tests/test_ad1294_read_provenance_rendering.py:141-164  words tier/relevance/author/age; no confidence
tests/test_ad1141_crew_loop_sigma.py:805-812  max_chars=1200 renders exactly one 400-char entry
tests/test_bf950_oracle_result_age.py:70-142  _records, _rewrite_frontmatter, _self_monitoring, _sensorium_render, _notebook_tags, _mock_records
```

### A1.12 Absence verified (2026-11-05)

```
CLAIM: no store-reachable writer puts a date-typed `updated` or a non-int `revision` in a notebook
RUN:   Grep "records_store\.(write_entry|write_notebook|publish|write_workspace_file)" src/; Grep write_workspace_file\( src/
FOUND: routers/records.py:151 (write_notebook); write_workspace_file only from consultation/workspace.py and consultation/delivery.py:983 (workspace YAML)
HOLDS: in part (corrected by Amendment 2, review round 2 F4). No writer creates a date-typed `updated` or a non-int `revision`. But `write_entry` carries an existing revision forward as `existing_rev + 1` (`records_store.py:322-323`), so an operator-written float stays a float (3.5, then 4.5). A bool becomes an int (True + 1 = 2). A text, null or list revision raises there, is caught at `:333`, and that update is written without `revision`. Every non-int revision still starts with an edit outside the store.

CLAIM: notebook_repetition_warnings and notebook_summary are never consumed in src
RUN:   Grep "repetition_warnings|notebook_summary" src/ and tests/
FOUND: src: proactive.py:2777, :2850 (producers only); tests: test_ad550_notebook_dedup.py:555-557 (notebook_summary)
HOLDS: yes (recorded on #1754)

CLAIM: no test pins the moved notebook-block source text
RUN:   Grep "notebook query failed|Semantic pull|get\(\"updated\", \"\"\)|rev >= _rep_thresh" tests/
FOUND: nothing
HOLDS: yes
```

### A1.13 For the Captain

None. Both repairs correct a false or lost signal inside the BF-950 envelope and weaken no control.

## Amendment 2 (review round 2: F3 and F4)

**Ordering (M10):** on the contract as it stands at `158418fc`, apply P10-0 to P10-6. Each of their SEARCH strings occurs exactly once there, before the append. Then append this whole section verbatim to the end of `prompts/bf-950-oracle-result-age.md`, then apply P10-7. All of this goes in M10's commit. Every `src` SEARCH is anchored on `158418fc`, because M10 changes no `src`. P11-5 and P11-6 remove the marker P10-7 adds, so they are anchored on M10's tree; that is the only exception. P12 is anchored on `158418fc`'s trackers.

**P10-0** `prompts/bf-950-oracle-result-age.md` (the header; the SEARCH ends partway through line 6)

SEARCH:
```
it is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2` (tree of BF-948 Amendment 1).
```
REPLACE:
```
it is appended at the end of this file.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 2 (review round 2, F3 and F4) adds milestones M10 to M12, tests T13 and T14, mutation rows NBM-13 to NBM-16, limits L18 and L19 and §16 items 18 to 21. It amends L15, NBM-12's killer and §16 item 13, and corrects the store-written claims of A1.1 and A1.12. It is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2` (tree of BF-948 Amendment 1).
```

**P10-1** `prompts/bf-950-oracle-result-age.md` (A1.1, F1 bullet)

SEARCH:
```
Store-written files never produce these shapes (`records_store.py:305`, `:323`, `:354`).
```
REPLACE:
```
Store-written files never produce the first two (`records_store.py:305`, `:323`, `:354`). The store rewrites `updated` as text. A text revision raises at `:323`, is caught at `:333`, and that update is written without one. A list topic can be store-written only through the records API, which passes a JSON `topic` through (`routers/records.py:146-153`; Amendment 2, L19).
```

**P10-2** `prompts/bf-950-oracle-result-age.md` (A1.5, before P7-4)

SEARCH:
```
**P7-4** `src/probos/proactive.py`
```
REPLACE:
```
> **Amendment 2 note.** The comment P7-3 adds says the store writes only an int revision. That is false: the store carries an existing revision forward as `existing_rev + 1` (`records_store.py:322-323`), so an operator's 3.5 becomes 4.5. P11-4 corrects the source. P7-3 stays as M7 applied it.

**P7-4** `src/probos/proactive.py`
```

**P10-3** `prompts/bf-950-oracle-result-age.md` (A1.8)

SEARCH:
```
| NBM-12 | proactive.py | `if dept and entries:` | `if dept and entries and "notebook_summary" in result:` | T11 `a-list-topic` |
```
REPLACE:
```
| NBM-12 | proactive.py | `if dept and entries:` | `if dept and entries and "notebook_summary" in result:` | T11 `a-list-topic` (campaign on M8's head); from M10 on, T14 (Amendment 2: after M11 no real-store shape ends the enrichment before the summary) |
```

**P10-4** `prompts/bf-950-oracle-result-age.md` (A1.9)

SEARCH:
```
- **L15.** Index and repetition enrichment can still fail for a cycle on other frontmatter written outside the store's path (for example a list `topic`, which `set()` cannot hash). Since Amendment 1 that no longer suppresses the read-back. The repetition check still skips an entry whose `updated` is a YAML date (it parses with `datetime.fromisoformat`). Recorded on #1754.
```
REPLACE:
```
- **L15.** (Amended by Amendment 2.) Since M11, no frontmatter shape a real store lists is known to make the index or repetition enrichment raise (A2.11), with one exception. A naive text `updated` that local time cannot convert (for example `1900-01-01T00:00:00` on Windows) can make `.timestamp()` raise `OSError` or `OverflowError` past the `except (ValueError, TypeError)` at the index's recency and at the repetition check. This was found by reading and is not yet measured. Such a failure costs the index for that cycle, never the read-back (T14). The repetition check still skips an entry whose `updated` is a YAML date (it parses with `datetime.fromisoformat`). Recorded on #1754.
```

**P10-5** `prompts/bf-950-oracle-result-age.md` (A1.10)

SEARCH:
```
13. A store-written notebook renders exactly as at M5's head: the index order, the index fields (raw `updated`; `revision` defaulting to 1), the repetition warnings and the read-back. The sort key orders every store-written `updated` as the raw text did, and the revision guard admits every revision the store writes.
```
REPLACE:
```
13. (Amended by Amendment 2.) A notebook whose every write came through the store with a text topic renders exactly as at M5's head: the index order, the index fields (raw `updated`; `revision` defaulting to 1), the repetition warnings and the read-back. The sort key orders every store-written `updated` as the raw text did. The store creates every revision as an int, and the guard counts only an int. A fractional revision an operator wrote stays fractional when the store carries it forward (`existing_rev + 1`, `records_store.py:322-323`). Such a history gives no repetition warning where M5's head gave one; nothing renders the warnings (L18).
```

**P10-6** `prompts/bf-950-oracle-result-age.md` (A1.12)

SEARCH:
```
HOLDS: yes; reaching the defect needs an edit outside the store
```
REPLACE:
```
HOLDS: in part (corrected by Amendment 2, review round 2 F4). No writer creates a date-typed `updated` or a non-int `revision`. But `write_entry` carries an existing revision forward as `existing_rev + 1` (`records_store.py:322-323`), so an operator-written float stays a float (3.5, then 4.5). A bool becomes an int (True + 1 = 2). A text, null or list revision raises there, is caught at `:333`, and that update is written without `revision`. Every non-int revision still starts with an edit outside the store.
```

### A2.1 Findings and decisions

- **F3 (P2, ordinary reach through an operator-edited file; a regression that widened an older defect).**
  - **The defect.** When an index entry's `updated` is empty, both renderers join its raw `topic` into one line (`cognitive_agent.py:9424-9426`, `:11329-11331`). A number or null topic raises `TypeError` there, and the sensorium dispatcher drops the whole self-monitoring extension, read-back included.
  - **Before Amendment 1.** At `eed3a3ee` this was reachable when the edited entry's `updated` was missing or `""`; the raw sort compares `""` with text. That is AD-550's defect.
  - **What M7 widened.** M7's total sort key let a null, false or non-text `updated` through as well.
  - **Neighbouring shapes.** A list topic made the topic count raise and cost the index (old L15). A blank topic rendered as an empty item.
  - **Fix (M11).** A new `_notebook_index_topic` returns the frontmatter's `topic` when it is non-empty text, otherwise the file's slug. The index and the topic count both use it. The renderers do not change.
  - **Rejected:** casting in the two renderers. It would leave the topic count and the warnings on the raw value, and it would edit duplicated code twice.
- **F4 (P3, ordinary reach: an update after an operator edit; a regression in the claims and in an output nothing reads).** The guard stays int-only. A fractional "times" count means nothing, and nothing renders `notebook_repetition_warnings`. The comment, A1.1, A1.12 and property 13 are corrected (P10-1, P10-5, P10-6, P11-4). P9-1 and P9-3 make no store claim and stay as written.

### A2.2 Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M10 | STANDARD | test only (plus this contract) | P10-0 to P10-7 | G10 |
| M11 | STANDARD | no (index keys and shape unchanged; `topic` narrows to the `str` both renderers already assume) | P11-1 to P11-6 | G11 |
| M12 | STANDARD | trackers | P12-1 to P12-3, ledger | G12 |

The new-file counts below come from reading the file: 43 cases at M9's head, plus T13's 4 and T14's 1. Every count marked **measure** has to be measured on the oracle tree.

- **G10:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf950_oracle_result_age.py -q -n 0`.
  - Expected: **44 passed, 4 xfailed**. T14 passes on M10.
  - Then `... -q -n 0 --runxfail -k "index_topic"`. Expected: **4 failed**:
    - `a-number-topic`: `TypeError: sequence item …: expected str instance, int found`;
    - `a-null-topic`: the same, with `NoneType found`;
    - `a-list-topic`: `AssertionError` at `assert lines and len(set(lines)) == 1`;
    - `a-blank-topic`: `AssertionError` at the item-set assertion.
  - Any failure on a `# premise` line is a hard stop.
- **G11:** G7's command, with the same six test files, then `... -P scripts/check_architecture_principles.py --check`.
  - New file: **48 passed**.
  - Others: 0 failed, counts equal to G7's (**measure**).
- **G12:** `... -P scripts/gen_ad_ledger.py`; `... -P scripts/gen_ad_ledger.py --check` (exit 0); `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
  - Expected: **33**, as G9.
  - Stage the two ledger files as written.
- **The 36-file focus run:** **1878 passed, 1 skipped** if the new file is among the 36 (**measure**).
- **Mutation campaign of record, on M11's head.**
  - Run an unmutated baseline of the new file first.
  - Record the sha256 of `proactive.py`.
  - Run NBM-13 to NBM-16 and NBM-12 (new killer T14).
  - Rerun NBM-1 to NBM-5, NBM-10 and NBM-11, because `proactive.py` differs from M8's campaign file (their lines are unchanged).
  - Expected inventory: **38 of 38 killed** (**measure**).
- **Optional measurement for L15:** `python -I -c "from datetime import datetime; datetime.fromisoformat('1900-01-01T00:00:00').timestamp()"`. Record whether it raises in the #1754 line. It changes nothing in this candidate.
- **Broad gate:** once, after round 3, as §4 says.

### A2.3 Commit messages

- M10: `BF-950 M10: reproduction of an index topic that is not text ending the self-monitoring block, and the corrected store-written claims`
- M11: `BF-950 M11: an index topic that is not text is named by its file`
- M12: `BF-950 M12: trackers and ledger for Amendment 2`

### A2.4 Tests

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T13 | `test_an_index_topic_that_is_not_text_does_not_end_the_block` | 4 | F3, real store → pull → both renderers | M11 |
| T14 | `test_a_failed_index_does_not_cost_the_read_back` | 1 | §16 item 14 under mutation (NBM-12) | none: passes on M10 |

**P10-7** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
    elif shape == "a-text-revision":
        warnings = result.get("notebook_repetition_warnings", [])
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings
```
REPLACE:
```python
    elif shape == "a-text-revision":
        warnings = result.get("notebook_repetition_warnings", [])
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings


_UNTIL_M11 = pytest.mark.xfail(
    strict=True, reason="BF-950 M11: an index topic that is not text ends the self-monitoring notebook block",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "updated"), [
    pytest.param(17, None, id="a-number-topic"),
    pytest.param(None, False, id="a-null-topic"),
    pytest.param(["engines", "warp"], None, id="a-list-topic"),
    pytest.param("", None, id="a-blank-topic"),
])
@_UNTIL_M11
async def test_an_index_topic_that_is_not_text_does_not_end_the_block(
    tmp_path: Path, topic: Any, updated: Any,
) -> None:
    """Review round 2 (F3): an index entry with an empty ``updated`` is rendered by its bare topic.

    So a topic edited outside the store into a number or a null raised in ``", ".join`` in both renderers,
    and the sensorium dispatcher dropped the whole self-monitoring extension, read-back included. A list
    topic ended the index at the topic count, and a blank one rendered as an empty item. The index now names
    such an entry by its file. A real store, its file edited as a person would edit it.
    """
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "first-topic", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "second-topic", "engineering notes, second", department="engineering")
    first, second = "notebooks/Zephyr/first-topic.md", "notebooks/Zephyr/second-topic.md"
    edited = _rewrite_frontmatter(store, first, topic=topic, updated=updated)
    assert edited["topic"] == topic and edited["updated"] is updated  # premise
    second_updated = _rewrite_frontmatter(store, second)["updated"]
    assert type(second_updated) is str  # premise: the store writes text

    result = await _self_monitoring(store, "Zephyr")

    expected_items = {"first-topic", f"second-topic (updated {second_updated})"}
    for text in (_sensorium_render(result), await _proactive_render(result)):
        lines = [line for line in text.splitlines() if line.startswith("Your notebooks: [")]
        assert lines and len(set(lines)) == 1, text
        assert set(lines[0][len("Your notebooks: ["):-1].split(", ")) == expected_items, lines[0]
        assert any(tag.startswith('<notebook topic="') for tag in _notebook_tags(text)), text
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
async def test_a_failed_index_does_not_cost_the_read_back() -> None:
    """§16 item 14 under mutation (NBM-12): the read-back runs whenever the listing returned entries.

    Since Amendment 2 no frontmatter a real store lists is known to end the index (L15), so the failure is
    injected: a listing entry without the ``path`` that ``RecordsStore.list_entries`` always sets.
    Passes on M10 and after.
    """
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[{"frontmatter": {"author": "Bones"}}])
    records.search = AsyncMock(return_value=[{
        "path": "notebooks/Bones/own-topic.md", "snippet": "engineering notes of my own",
        "frontmatter": {"updated": "2026-05-03T10:00:00+00:00"},
    }])

    result = await _self_monitoring(records, "Bones")

    assert "notebook_summary" not in result and "notebook_index" not in result  # premise: the enrichment raised
    assert result["notebook_content"]["topic"] == "own-topic"
    assert _notebook_tags(_sensorium_render(result)) == [
        '<notebook topic="own-topic" updated="2026-05-03T10:00:00+00:00">',
    ]
```

### A2.5 M11

**P11-1** `src/probos/proactive.py`

SEARCH:
```python
        "revision": revision if type(revision) is int and revision >= 1 else None,
    }


def _parse_hhmm(value: str) -> tuple[int, int]:
```
REPLACE:
```python
        "revision": revision if type(revision) is int and revision >= 1 else None,
    }


def _notebook_index_topic(entry: dict[str, Any]) -> str:
    """BF-950 Amendment 2: the topic an AD-550 index entry shows, always text.

    The frontmatter's ``topic`` when that is non-empty text, else the file's slug.
    The store writes ``topic`` only from a non-empty argument (``write_entry``) and
    every agent writer passes the slug as text, so their index is unchanged. The
    records API can store a non-text topic, but names the file by its text, so the
    slug reads the same. A topic edited into a number, a null, a list or a blank is
    named by its file: both renderers join the topic into one line, and the topic
    count hashes it.
    """
    frontmatter = entry.get("frontmatter")
    topic = frontmatter.get("topic") if type(frontmatter) is dict else None
    if isinstance(topic, str) and topic:
        return topic
    return entry["path"].split("/")[-1].replace(".md", "")


def _parse_hhmm(value: str) -> tuple[int, int]:
```

> **Amendment 3 note.** The fallback P11-1 adds, `.replace(".md", "")`, removes every `.md`, not only the final one: `notes.md.md` showed as `notes`, and `.md.md` as an empty item. Its docstring's claim "so the slug reads the same" was false for a topic text containing `.md`. P14-1 corrects both. P11-1 stays as M11 applied it.

**P11-2** `src/probos/proactive.py`

SEARCH:
```python
                            "total_topics": len(set(
                                e.get("frontmatter", {}).get("topic", e["path"].split("/")[-1].replace(".md", ""))
                                for e in entries
                            )),
```
REPLACE:
```python
                            # BF-950 Amendment 2: counted by the topic the index shows.
                            "total_topics": len(set(_notebook_index_topic(e) for e in entries)),
```

**P11-3** `src/probos/proactive.py`

SEARCH:
```python
                            fm = e.get("frontmatter", {})
                            topic = fm.get("topic", e["path"].split("/")[-1].replace(".md", ""))
                            updated_str = fm.get("updated", "")
```
REPLACE:
```python
                            fm = e.get("frontmatter", {})
                            topic = _notebook_index_topic(e)
                            updated_str = fm.get("updated", "")
```

**P11-4** `src/probos/proactive.py`

SEARCH:
```python
                            # BF-950 Amendment 1: only an int revision is counted (the store
                            # writes nothing else); a hand-written text revision raised here.
```
REPLACE:
```python
                            # BF-950 Amendment 1: only an int revision is counted; a hand-written
                            # text revision raised here. Amendment 2: the store creates every
                            # revision as an int but carries an existing one forward as +1, so a
                            # fractional history an operator started (3.5, 4.5) is not counted (L18).
```

**P11-5** `tests/test_bf950_oracle_result_age.py` (anchored on M10's tree)

SEARCH:
```python
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings


_UNTIL_M11 = pytest.mark.xfail(
    strict=True, reason="BF-950 M11: an index topic that is not text ends the self-monitoring notebook block",
)


```
REPLACE:
```python
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings


```

**P11-6** `tests/test_bf950_oracle_result_age.py` (anchored on M10's tree)

SEARCH:
```python
    pytest.param("", None, id="a-blank-topic"),
])
@_UNTIL_M11
async def test_an_index_topic_that_is_not_text_does_not_end_the_block(
```
REPLACE:
```python
    pytest.param("", None, id="a-blank-topic"),
])
async def test_an_index_topic_that_is_not_text_does_not_end_the_block(
```

### A2.6 M12 (trackers)

These amend the entries already committed in place. Entry heads and dates are unchanged. Stage explicit paths only.

**P12-1** `PROGRESS.md`

SEARCH:
```
a STALE flag its renderer never emits. The contract is `prompts/bf-950-oracle-result-age.md`.
```
REPLACE:
```
a STALE flag its renderer never emits. Review round 2 (Amendment 2): an index entry whose topic is not text (a number, a null, a list or a blank, edited into the file) is named by its file. It no longer ends the self-monitoring block in either renderer. The contract is `prompts/bf-950-oracle-result-age.md`.
```

**P12-2** `DECISIONS.md`

SEARCH:
```
the repetition check's revision read and the read-back's own error boundary)
```
REPLACE:
```
the repetition check's revision read and the read-back's own error boundary; Amendment 2: `_notebook_index_topic`, the index's topic)
```

**P12-3** `DECISIONS.md`

SEARCH:
```
- *Residual.* Recorded limits L1 to L17 of the contract.
```
REPLACE:
```
- *Amendment 2 (review round 2).* An index entry is named by its topic only when that is non-empty text, otherwise by its file. So a topic edited into a number, a null, a list or a blank no longer ends the self-monitoring block in either renderer. The repetition check still counts only an int revision. A fractional history the store carries forward after an operator edit is not counted (L18). Rejected: casting the topic in the two renderers, which would leave the topic count and the warnings on the raw value.
- *Residual.* Recorded limits L1 to L19 of the contract.
```

Then regenerate the ledger as G12 says.

### A2.7 Mutation rows

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| NBM-13 | proactive.py | `if isinstance(topic, str) and topic:` | `if topic is not None:` | T13 `a-number-topic` |
| NBM-14 | proactive.py | the same line | `if isinstance(topic, str):` | T13 `a-blank-topic` |
| NBM-15 | proactive.py | `topic = _notebook_index_topic(e)` | `topic = fm.get("topic", e["path"].split("/")[-1].replace(".md", ""))` | T13 `a-number-topic` |
| NBM-16 | proactive.py | `"total_topics": len(set(_notebook_index_topic(e) for e in entries)),` | `"total_topics": len(set(e.get("frontmatter", {}).get("topic", e["path"].split("/")[-1].replace(".md", "")) for e in entries)),` | T13 `a-list-topic` |
| NBM-12 | (row amended by P10-3) | | | T14 |

### A2.8 Limits (L15 amended by P10-4; L18 and L19 added)

- **L18.** The store creates every revision as an int and carries an existing one forward as `existing_rev + 1` (`records_store.py:322-323`), so a fractional revision an operator wrote stays fractional (3.5, then 4.5). The repetition check does not count such a history; M5's head counted it, but nothing renders the warnings. The read-back also shows no `revision` for it, since it shows only a positive int (§3). The store's next write drops a text, null or list revision (`:323` raises, `:333` catches).
- **L19.** The records API passes a JSON `topic` to `write_notebook` unchecked (`routers/records.py:146-153`), so a non-text topic can be store-written. Its file is named `f"{topic}.md"` (`records_store.py:527`). Since Amendment 3 the index's fallback removes only that final `.md`, so the slug shows the topic's text, unless the text contains a `/` (the file then lies in a subdirectory, and the slug is its last component). Before Amendment 3 the fallback removed every `.md`, so a topic text containing `.md` lost it, and `notes.md` and `notes.md.md` both showed as `notes` (review round 3, F5). Validating the topic is recorded on #1754.

### A2.9 Diff Reviewer properties (added to §16; item 13 amended by P10-5)

18. Every `notebook_index` entry's `topic` is a non-empty `str`: the frontmatter's `topic` when that is non-empty text, otherwise the file's slug (`_notebook_index_topic`). Both renderers render every entry, whatever its `updated`, and `cognitive_agent.py` is byte-identical.
19. A notebook with text topics, as every agent write path produces, gives the same index, `notebook_summary`, repetition warnings and read-back as at M9's head. Only a hand-edited number, null, list or blank topic, or a non-text one the API wrote, changes: it is named by its file, and the topic count counts that name.
20. The guard line `if type(rev) is int and rev >= _rep_thresh and ei.get("updated"):` is byte-identical. Only its comment and the contract prose change, to state what the store writes as A2.1 does.
21. T13 crosses real store → pull → both renderers. T14 passes on M10 and after. §16 item 12 extends to T13: its marker is removed only at M11, after G10 showed the four named failures.

### A2.10 Verified against codebase (2026-11-05, on `158418fc`)

```
proactive.py:279-296   _notebook_read_back: revision shown only when type(revision) is int and >= 1
proactive.py:299       def _parse_hhmm (P11-1 anchor)
proactive.py:2776-2780 sorted(..., key=lambda e: record_write_time(e.get("frontmatter")) or 0.0, reverse=True)
proactive.py:2784-2790 notebook_summary: len(set(e.get("frontmatter", {}).get("topic", <slug>) for e in entries))
proactive.py:2795-2797 fm = e.get("frontmatter", {}); topic = fm.get("topic", <slug>); updated_str = fm.get("updated", "")
proactive.py:2801-2812 recency: datetime.fromisoformat(updated_str).timestamp() under except (ValueError, TypeError)
proactive.py:2827-2835 enriched_index {topic, updated, recency, preview, revision}; result["notebook_index"]
proactive.py:2846-2848 the Amendment 1 comment; if type(rev) is int and rev >= _rep_thresh and ei.get("updated")
proactive.py:2850-2857 warnings: .timestamp() under except (ValueError, TypeError); f"...{ei['topic']} {rev} times..."
proactive.py:2870-2889 semantic pull, its own try, `if dept and entries:`
cognitive_agent.py:9422-9432, :11327-11337  ", ".join(f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"] ...)
provenance.py:52-90    _posix_seconds / record_write_time: "Nothing here raises"; non-dict frontmatter -> None
records_store.py:311   "updated": now on every write; :320-323 created kept, revision = existing_rev + 1; :333 except; :338-339 topic only if truthy
records_store.py:296-302 extra_frontmatter may not set store-owned keys (updated, revision, topic: :39-42)
records_store.py:525-545 write_notebook: path f"notebooks/{callsign}/{topic_slug}.md", topic=topic_slug
records_store.py:1050  list_entries: author filter fm.get("author"); every result is {"path", "frontmatter"}
routers/records.py:146,151-153  topic = body.get("topic", "untitled") passed as topic_slug
tests/test_bf950_oracle_result_age.py:70-135  _records, _rewrite_frontmatter, _self_monitoring, _sensorium_render, _proactive_render, _notebook_tags
tests/test_bf950_oracle_result_age.py:394-428  T11 (its last three lines are P10-7's anchor)
tests/test_ad550_notebook_dedup.py:535-557  total_topics == 3 over three text topics (unchanged by M11)
```

### A2.11 Absence verified (2026-11-05)

```
CLAIM: in src, notebook_index entries are read only by the two renderers, which read only `topic` and `updated`
RUN:   Grep "notebook_index|notebook_summary|notebook_repetition_warnings" src/; Grep "\[.(recency|preview).\]|get\(.(recency|preview)." src/
FOUND: cognitive_agent.py:9422, :11327 (consumers); proactive.py:2621 (docstring), :2784, :2835, :2859 (producers);
       recency/preview only in unrelated factor dicts (chat_facilitator.py:302, episodic.py:3384, :4782, thread_priority/scorer.py:79)
HOLDS: yes; `updated` is only truth-tested and f-string formatted, which cannot raise for any YAML type

CLAIM: no test or source scan pins the lines M11 replaces
RUN:   Grep "total_topics|e\[\"path\"\]\.split|_notebook_index_topic|writes nothing else" tests/
FOUND: test_ad550_notebook_dedup.py:557 (total_topics == 3 over text topics)
HOLDS: yes; that assertion holds after M11

CLAIM: notebook topics come from text slugs on every agent path; only the records API can store a non-text one
RUN:   Grep "\.write_notebook\(" src/ -A3; read records_store.py:338-339, routers/records.py:141-153
FOUND: proactive.py:3341, :4405, tools/publish_finding_tool.py:693 (slug text); routers/records.py:151 (raw JSON topic)
HOLDS: in part (corrected by Amendment 3, review round 3 F5). The API names the file `f"{topic}.md"`, but M11's fallback `.replace(".md", "")` removed every `.md`, so the slug read the same only for a text without `.md` or `/`. Since M14 it removes only the final `.md` (L19)

CLAIM: after M11, nothing in the index or repetition enrichment raises on frontmatter a real store lists, except naive out-of-range `.timestamp()`
RUN:   read proactive.py:2776-2859 expression by expression
FOUND: record_write_time is total; _notebook_index_topic is total given list_entries' `path`; `fm` is a dict (the author filter at
       records_store.py:1050 raises on any other type, so such a file never lists); fromisoformat(...) raises only ValueError/TypeError
       (caught); the revision guard is a type check; the warning f-string formats any object; read_entry sits under its own except
HOLDS: yes, with the L15 exception (by reading; not measured)
```

### A2.12 For the Captain

None. Both repairs restore a lost signal or correct a false claim inside the BF-950 envelope and weaken no control.

## Amendment 3 (review round 3: F5)

**Ordering (M13):** take the contract as it stands at `d969ecd4` and apply P13-0 to P13-3. Each of their SEARCH strings occurs exactly once there before the append. Then append this whole section verbatim to the end of `prompts/bf-950-oracle-result-age.md`, then apply P13-4. All of this goes in M13's commit.
- Every `src` SEARCH is anchored on `d969ecd4`, because M13 changes no `src`.
- P14-2 to P14-4 remove the markers P13-4 adds, so they are anchored on M13's tree. That is the only exception.
- P15 is anchored on `d969ecd4`'s trackers.

**P13-0** `prompts/bf-950-oracle-result-age.md` (the header; the SEARCH ends partway through line 7)

SEARCH:
```
and A1.12. It is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2` (tree of BF-948 Amendment 1). For every file
```
REPLACE:
```
and A1.12. It is appended at the end of this file.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-05: Amendment 3 (review round 3, F5) adds milestones M13 to M15, tests T15 and T16, mutation rows NBM-17 to NBM-19, limit L20 and §16 items 22 to 24. It corrects L19, the third claim of A2.11 and the docstring P11-1 added. It is appended at the end of this file.
**Status:** ready to build. **Base:** drafted on `728e1fc2` (tree of BF-948 Amendment 1). For every file
```

**P13-1** `prompts/bf-950-oracle-result-age.md` (A2.8, L19)

SEARCH:
```
so a non-text topic can be store-written. Its file is named by the topic's text, so the index's slug shows that same text. Validating it is recorded on #1754.
```
REPLACE:
```
so a non-text topic can be store-written. Its file is named `f"{topic}.md"` (`records_store.py:527`). Since Amendment 3 the index's fallback removes only that final `.md`, so the slug shows the topic's text, unless the text contains a `/` (the file then lies in a subdirectory, and the slug is its last component). Before Amendment 3 the fallback removed every `.md`, so a topic text containing `.md` lost it, and `notes.md` and `notes.md.md` both showed as `notes` (review round 3, F5). Validating the topic is recorded on #1754.
```

**P13-2** `prompts/bf-950-oracle-result-age.md` (A2.11, third claim)

SEARCH:
```
HOLDS: yes (L19); the API's file is named by the topic's text, so the slug reads the same
```
REPLACE:
```
HOLDS: in part (corrected by Amendment 3, review round 3 F5). The API names the file `f"{topic}.md"`, but M11's fallback `.replace(".md", "")` removed every `.md`, so the slug read the same only for a text without `.md` or `/`. Since M14 it removes only the final `.md` (L19)
```

**P13-3** `prompts/bf-950-oracle-result-age.md` (A2.5, before P11-2)

SEARCH:
```
**P11-2** `src/probos/proactive.py`
```
REPLACE:
```
> **Amendment 3 note.** The fallback P11-1 adds, `.replace(".md", "")`, removes every `.md`, not only the final one: `notes.md.md` showed as `notes`, and `.md.md` as an empty item. Its docstring's claim "so the slug reads the same" was false for a topic text containing `.md`. P14-1 corrects both. P11-1 stays as M11 applied it.

**P11-2** `src/probos/proactive.py`
```

### A3.1 Findings and decisions

- **F5 (P3; reach is ordinary through a file name written by an operator or by the API, never by an agent; a regression: Amendment 2 routed non-text topics through an inherited idiom).**
  - **The defect.** `_notebook_index_topic` falls back to `entry["path"].split("/")[-1].replace(".md", "")` (`proactive.py:314`), which strips every `.md`. Take two files, `notes.md` and `notes.md.md`, whose topics an operator edited into numbers. At base they showed as `17 (updated …)` and `27 (updated …)`. Since M11 they show as `notes` and `notes`, and `total_topics` falls from 2 to 1. A file `.md.md` shows as an empty item. The read-back survives.
  - **Reach.** An agent's `[NOTEBOOK slug]` is `[\w-]+`, so an agent cannot write a dot. The API can: a text topic `""` gives the file `.md`, and a topic containing `.md` gives an embedded one.
  - **Fix (M14).** Remove only the final `.md` (`str.removesuffix`). When that leaves nothing, show the whole file name. The count and the index keep the one helper.
  - **Rejected:**
    - `Path(name).stem`: it also strips a final `.yaml` or `.txt` that `rglob("*.md")` never lists, and it diverges from the store's `f"{slug}.md"` naming.
    - Making names unique with a suffix: no consumer keys on uniqueness (search above).
    - Converting the read-back topic (`:2902`) and `notebook_quality.py` too: both were already like this at base and are outside the index (L20).

### A3.2 Milestones and gates

| M | Tier | Shared contract? | Pairs | Gate |
|---|---|---|---|---|
| M13 | STANDARD | test only (plus this contract) | P13-0 to P13-4 | G13 |
| M14 | STANDARD | no (still a non-empty `str`; keys unchanged) | P14-1 to P14-4 | G14 |
| M15 | STANDARD | trackers | P15-1 to P15-3, ledger | G15 |

The new-file counts below come from reading the file: 48 cases at M12's head (A2.2), plus T15's 1 and T16's 4. Every count marked **measure** has to be measured on the oracle tree.

- **G13:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf950_oracle_result_age.py -q -n 0`.
  - Expected: **49 passed, 4 xfailed**. T16 `a-plain-file` passes on M13.
  - Then `... -q -n 0 --runxfail -k "stay_two_items or keeps_all_but_its_final_md"`. Expected: **4 failed, 1 passed**:
    - T15: `AssertionError` at `sorted(...) == ["notes", "notes.md"]`, showing `['notes', 'notes']`, in the first renderer;
    - `an-embedded-md`: `AssertionError`, `['notes'] == ['notes.md']`;
    - `a-doubled-bare-md` and `a-bare-md`: `AssertionError`, `[''] == ['.md']`.
  - Any failure on a `# premise` line is a hard stop.
- **G14:** G11's command, with the same six test files, then `... -P scripts/check_architecture_principles.py --check`.
  - New file: **53 passed**.
  - Others: 0 failed, counts equal to G11's (**measure**).
- **G15:** `... -P scripts/gen_ad_ledger.py`; `... -P scripts/gen_ad_ledger.py --check` (exit 0); `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
  - Expected: **33**, as G12.
  - Stage the two ledger files as written.
- **The 36-file focus run:** **1883 passed, 1 skipped** (1878 + 5, **measure**).
- **Mutation campaign of record, on M14's head.**
  - Run an unmutated baseline of the new file first.
  - Record the sha256 of `proactive.py`.
  - Run NBM-17 to NBM-19.
  - Because `proactive.py` differs from M11's campaign file, rerun every `proactive.py` row: NBM-1 to NBM-5 and NBM-10 to NBM-16. NBM-15 and NBM-16 are still killed by T13 `a-number-topic` and `a-list-topic`.
  - Expected inventory: **41 of 41 killed** (**measure**).
- **Broad gate:** once, after round 4, as §4 says.

### A3.3 Commit messages

- Contract: `BF-950 (#1742): Amendment 3 to the build contract after review round 3 (M13 to M15: an index name taken from the file loses only its final .md)`
- M13: `BF-950 M13: reproduction of two notebook files collapsing into one index item, and the corrected file-name claims`
- M14: `BF-950 M14: an index name taken from the file loses only its final .md`
- M15: `BF-950 M15: trackers and ledger for Amendment 3`

### A3.4 Tests

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T15 | `test_two_files_named_by_their_files_stay_two_items` | 1 | F5, real store → pull → both renderers → summary | M14 |
| T16 | `test_an_index_name_from_the_file_keeps_all_but_its_final_md` | 4 | the fallback's boundaries: an embedded `.md`, `.md.md`, the bare `.md`, a plain file (unchanged; no marker) | M14 (3 of 4) |

**P13-4** `tests/test_bf950_oracle_result_age.py`

SEARCH:
```python
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
async def test_a_failed_index_does_not_cost_the_read_back() -> None:
```
REPLACE:
```python
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


_UNTIL_M14 = pytest.mark.xfail(
    strict=True, reason="BF-950 M14: the index's file-name fallback removes every .md, not only the final one",
)


@pytest.mark.asyncio
@_UNTIL_M14
async def test_two_files_named_by_their_files_stay_two_items(tmp_path: Path) -> None:
    """Review round 3 (F5): an index entry named by its file kept nothing of an embedded ``.md``.

    Amendment 2 names an entry whose topic is not text by its file, and that fallback removed every ``.md``.
    So ``notes.md`` and ``notes.md.md`` (the store names a file ``f"{slug}.md"``) both showed as ``notes``,
    and the topic count fell from 2 to 1. A real store, both files edited as a person would edit them.
    """
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "notes", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "notes.md", "engineering notes, second", department="engineering")
    for path, topic in (("notebooks/Zephyr/notes.md", 17), ("notebooks/Zephyr/notes.md.md", 27)):
        edited = _rewrite_frontmatter(store, path, topic=topic, updated=None)
        assert edited["topic"] == topic and edited["updated"] is None  # premise

    result = await _self_monitoring(store, "Zephyr")

    for text in (_sensorium_render(result), await _proactive_render(result)):
        lines = [line for line in text.splitlines() if line.startswith("Your notebooks: [")]
        assert lines and len(set(lines)) == 1, text
        assert sorted(lines[0][len("Your notebooks: ["):-1].split(", ")) == ["notes", "notes.md"], lines[0]
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "frontmatter", "shown"), [
    pytest.param("notebooks/Zephyr/notes.md.md", {"topic": 27}, "notes.md", id="an-embedded-md", marks=_UNTIL_M14),
    pytest.param("notebooks/Zephyr/.md.md", {}, ".md", id="a-doubled-bare-md", marks=_UNTIL_M14),
    pytest.param("notebooks/Zephyr/.md", {"topic": None}, ".md", id="a-bare-md", marks=_UNTIL_M14),
    pytest.param("notebooks/Zephyr/notes.md", {"topic": 27}, "notes", id="a-plain-file"),
])
async def test_an_index_name_from_the_file_keeps_all_but_its_final_md(
    path: str, frontmatter: dict[str, Any], shown: str,
) -> None:
    """Review round 3 (F5): the fallback removes only the final ``.md``, and shows the whole name when nothing is left.

    The records API names a file ``f"{topic}.md"`` from any JSON topic, so ``""`` gives ``.md`` and ``.md`` gives
    ``.md.md``; every-``.md`` removal showed both as an empty item. A listing as ``list_entries`` returns it, so no
    dot-file listing rule is assumed. ``a-plain-file`` is the unchanged case and passes on M13.
    """
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[{"path": path, "frontmatter": frontmatter}])
    records.read_entry = AsyncMock(return_value=None)
    records.search = AsyncMock(return_value=[])

    result = await _self_monitoring(records, "Zephyr")

    assert [entry["topic"] for entry in result["notebook_index"]] == [shown]
    assert result["notebook_summary"] == {"total_entries": 1, "total_topics": 1}
    for text in (_sensorium_render(result), await _proactive_render(result)):
        assert f"Your notebooks: [{shown}]" in text.splitlines(), text


@pytest.mark.asyncio
async def test_a_failed_index_does_not_cost_the_read_back() -> None:
```

### A3.5 M14

**P14-1** `src/probos/proactive.py` (anchored on `d969ecd4`)

SEARCH:
```python
    The frontmatter's ``topic`` when that is non-empty text, else the file's slug.
    The store writes ``topic`` only from a non-empty argument (``write_entry``) and
    every agent writer passes the slug as text, so their index is unchanged. The
    records API can store a non-text topic, but names the file by its text, so the
    slug reads the same. A topic edited into a number, a null, a list or a blank is
    named by its file: both renderers join the topic into one line, and the topic
    count hashes it.
    """
    frontmatter = entry.get("frontmatter")
    topic = frontmatter.get("topic") if type(frontmatter) is dict else None
    if isinstance(topic, str) and topic:
        return topic
    return entry["path"].split("/")[-1].replace(".md", "")
```
REPLACE:
```python
    The frontmatter's ``topic`` when that is non-empty text, else the file's name
    without its final ``.md``, or the whole name when that leaves nothing. The store
    writes ``topic`` only from a non-empty argument (``write_entry``) and every agent
    writer passes the slug as text, so their index is unchanged. The records API can
    store a non-text topic and names the file ``f"{topic}.md"``, so removing only the
    final ``.md`` gives that text back (L19). A topic edited into a number, a null, a
    list or a blank is named by its file: both renderers join the topic into one
    line, and the topic count hashes it. Amendment 3: removing every ``.md`` showed
    ``notes.md`` and ``notes.md.md`` as one name, and ``.md.md`` as an empty one.
    """
    frontmatter = entry.get("frontmatter")
    topic = frontmatter.get("topic") if type(frontmatter) is dict else None
    if isinstance(topic, str) and topic:
        return topic
    name = entry["path"].split("/")[-1]
    slug = name.removesuffix(".md")
    return slug or name
```

**P14-2** `tests/test_bf950_oracle_result_age.py` (anchored on M13's tree)

SEARCH:
```python
_UNTIL_M14 = pytest.mark.xfail(
    strict=True, reason="BF-950 M14: the index's file-name fallback removes every .md, not only the final one",
)


@pytest.mark.asyncio
@_UNTIL_M14
async def test_two_files_named_by_their_files_stay_two_items(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_two_files_named_by_their_files_stay_two_items(tmp_path: Path) -> None:
```

**P14-3** `tests/test_bf950_oracle_result_age.py` (anchored on M13's tree)

SEARCH:
```python
    pytest.param("notebooks/Zephyr/notes.md.md", {"topic": 27}, "notes.md", id="an-embedded-md", marks=_UNTIL_M14),
    pytest.param("notebooks/Zephyr/.md.md", {}, ".md", id="a-doubled-bare-md", marks=_UNTIL_M14),
    pytest.param("notebooks/Zephyr/.md", {"topic": None}, ".md", id="a-bare-md", marks=_UNTIL_M14),
```
REPLACE:
```python
    pytest.param("notebooks/Zephyr/notes.md.md", {"topic": 27}, "notes.md", id="an-embedded-md"),
    pytest.param("notebooks/Zephyr/.md.md", {}, ".md", id="a-doubled-bare-md"),
    pytest.param("notebooks/Zephyr/.md", {"topic": None}, ".md", id="a-bare-md"),
```

**P14-4** `tests/test_bf950_oracle_result_age.py` (anchored on M13's tree; the T16 docstring's M13 sentence)

SEARCH:
```python
    dot-file listing rule is assumed. ``a-plain-file`` is the unchanged case and passes on M13.
```
REPLACE:
```python
    dot-file listing rule is assumed. ``a-plain-file`` is the unchanged case; it passed on M13, before the fix.
```

### A3.6 M15 (trackers)

These amend the entries already committed, in place. Entry heads and dates are unchanged. Stage explicit paths only.

**P15-1** `PROGRESS.md`

SEARCH:
```
It no longer ends the self-monitoring block in either renderer. The contract is `prompts/bf-950-oracle-result-age.md`.
```
REPLACE:
```
It no longer ends the self-monitoring block in either renderer. Review round 3 (Amendment 3): a name taken from the file loses only its final `.md`, so `notes.md` and `notes.md.md` stay two items. The contract is `prompts/bf-950-oracle-result-age.md`.
```

**P15-2** `DECISIONS.md`

SEARCH:
```
Amendment 2: `_notebook_index_topic`, the index's topic)
```
REPLACE:
```
Amendment 2: `_notebook_index_topic`, the index's topic; Amendment 3: its file-name fallback)
```

**P15-3** `DECISIONS.md`

SEARCH:
```
the warnings on the raw value.
- *Residual.* Recorded limits L1 to L19 of the contract.
```
REPLACE:
```
the warnings on the raw value.
- *Amendment 3 (review round 3).* An index name taken from the file removes only the final `.md`, and shows the whole name when nothing is left. So `notes.md` and `notes.md.md` no longer collapse into one item and one topic, and the file `.md.md` is no longer shown as an empty item. Rejected: `Path.stem`, which diverges from the store's `f"{slug}.md"` naming; and converting the read-back topic and AD-551's quality scan, which were already like this at base and are outside the index (L20).
- *Residual.* Recorded limits L1 to L20 of the contract.
```

Then regenerate the ledger as G15 says.

### A3.7 Mutation rows

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| NBM-17 | proactive.py | `slug = name.removesuffix(".md")` | `slug = name.replace(".md", "")` | T15; T16 `an-embedded-md` |
| NBM-18 | proactive.py | `return slug or name` | `return slug` | T16 `a-bare-md` |
| NBM-19 | proactive.py | the same line | `return name` | T16 `a-plain-file`; T13 (every case) |

### A3.8 Limits (L19 amended by P13-1; L20 added)

- **L20.** Three places outside the index still remove every `.md`, as they did at base: the read-back topic (`proactive.py:2902`) and AD-551's quality scan (`notebook_quality.py:98`, `:230`). Only a file name an operator or the API wrote can contain an embedded `.md`. Recorded on #1754.

### A3.9 Diff Reviewer properties (added to §16)

22. `_notebook_index_topic` returns the frontmatter's `topic` when that is non-empty text. Otherwise it returns the file name without only its final `.md`, or the whole name when that leaves nothing. So for every path `list_entries` yields, it returns a non-empty `str`. `total_topics` and the index use this one helper.
23. Two kinds of entry render exactly as at `d969ecd4` in the index, `notebook_summary`, the warnings and the read-back: an entry named by a text topic, and an entry named by a file with no embedded `.md` and not bare `.md`. Lines `proactive.py:2805` and `:2812`, the read-back line `:2902` (L20) and `cognitive_agent.py` are byte-identical.
24. T15 crosses the real store, the pull, both renderers and the summary. The markers are removed only at M14, after G13 showed the four named failures. No test is deleted.

### A3.10 Verified against codebase (2026-11-05, on `d969ecd4`)

```
proactive.py:299-314   _notebook_index_topic; :314 return entry["path"].split("/")[-1].replace(".md", "")
proactive.py:2802-2806 notebook_summary {"total_entries", "total_topics": len(set(_notebook_index_topic(e) ...))}
proactive.py:2812      topic = _notebook_index_topic(e)
proactive.py:2843-2851 enriched_index {topic, updated, recency, preview, revision}; result["notebook_index"]
proactive.py:2871      f"You've written about {ei['topic']} {rev} times recently. "
proactive.py:2902      read-back topic: top.get("path", "").split("/")[-1].replace(".md", "")   (L20)
proactive.py:3508      read_nb_pattern = r'\[READ_NOTEBOOK\s+([\w-]+)\]'
cognitive_agent.py:9422-9432, :11327-11337  ", ".join(f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"] ...)
notebook_quality.py:98, :230  fm.get("topic", entry.get("path", "unknown").split("/")[-1].replace(".md", ""))   (L20)
records_store.py:527-528  path = f"notebooks/{callsign}/{topic_slug}.md"; self._safe_path(path) (traversal check only, :1277-1288)
records_store.py:1030  list_entries walks rglob("*.md")
tests/test_bf950_oracle_result_age.py:70-106  _records, _rewrite_frontmatter, _self_monitoring
tests/test_bf950_oracle_result_age.py:465-470  end of T13 and start of T14 (P13-4's anchor)
builder.py:1641        str.removesuffix already used in src (Python >= 3.9)
```

### A3.11 Absence verified (2026-11-05)

```
CLAIM: nothing in src reads notebook_summary or notebook_repetition_warnings
RUN:   Grep "notebook_repetition_warnings|notebook_summary" src
FOUND: proactive.py:2802, :2877 (both producers)
HOLDS: yes; the collapsed count reached no consumer, but property 22 keeps the count and the index on one helper

CLAIM: no consumer of the index topic needs it unique
RUN:   Grep "notebook_index|_notebook_index_topic" (all files except prompts/); Grep "READ_NOTEBOOK\s" src/probos
FOUND: cognitive_agent.py:9422, :11327 (display join); proactive.py:3508 ([\w-]+, so a dotted name cannot be requested back)
HOLDS: yes; display identity only

CLAIM: no test pins the line M14 replaces
RUN:   Grep 'replace\(\\?"\.md|removesuffix|_notebook_index_topic|slug reads the same' tests
FOUND: test_ad1227_recent_outputs.py:416 (an unrelated string); others are removesuffix in unrelated tests
HOLDS: yes
```

### A3.12 For the Captain

None. The repair restores a lost distinction inside the BF-950 envelope and weakens no control.
