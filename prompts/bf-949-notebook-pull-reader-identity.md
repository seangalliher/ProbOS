# BF-949 (#1741): the self-monitoring notebook pull reads only the agent's own notebook, as the agent

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-03
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-03, before the build: NRM-1's Line cell names the occurrence in `search` (`list_entries` holds the same line); NR7 no longer says what rendering the repetition warning would change. After review rounds 2 and 3: the last sentence of L10, which promised an error for a root retargeted between the two resolutions, and the first sentence of NR8's first bullet, which cited it, are deleted.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-03, after review round 1: R1 (§7.5) and the text it changes.
**Status:** M1 to M4 built (`701cabcd`); R1, review round 1's repair, ready to build. **Base:** drafted on `317fcdc0` (tree `4ca36294`); R1 written on `701cabcd`. **Dependencies:** none. **Tier:** M1 STANDARD, M2 HIGH, M3 HIGH, M4 STANDARD, R1 HIGH. **Estimated tests:** 1 new file, `tests/test_bf949_notebook_reader_identity.py` (13 test functions, 27 cases); M2 edits `tests/test_self_monitoring.py` and `tests/test_bf679_oracle_records_reader_identity.py`.
**BF number:** BF-949, held by the title of #1741 (`gh issue list --state all --search "BF-949 in:title"`: #1741 only; `git log --all -i --grep BF-949`: `079f4761`, a docs commit, no fix). Nothing allocated.
**Priority:** the Captain's first item (2026-11-03): a crew member's private note can reach another agent's prompt on every proactive cycle.

**Which text describes the head.** §1 to §3 describe `317fcdc0`; line numbers are that commit's, except where a line names `701cabcd`. §7.5 (R1) is written against `701cabcd`; before building it, run `git diff --stat 701cabcd HEAD -- src/probos/knowledge/records_store.py tests/test_bf949_notebook_reader_identity.py PROGRESS.md DECISIONS.md`. Before building M1 to M4, run `git diff --stat 317fcdc0 HEAD -- src/probos/knowledge/records_store.py src/probos/knowledge/semantic.py src/probos/proactive.py src/probos/routers/records.py src/probos/cognitive/dm_targeted_lookup.py tests/test_self_monitoring.py tests/test_bf679_oracle_records_reader_identity.py`. A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. P2-9 to P2-15 and P3-4 to P3-5 quote N1-1. Where prose differs from a REPLACE or new-file block, the block wins. "Head text" means every docstring, comment, log message, error string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

1. **The pull.** Self-monitoring's notebook block runs at AUTONOMOUS and UNRESTRICTED agency (`proactive.py:2610-2616`, `:2739`). When the agent has entries of its own (`list_entries(f"notebooks/{callsign}", author=callsign)`, `:2742-2746`), it calls `rt._records_store.search(dept, scope=f"notebooks/{callsign}")` (`:2832-2836`). It takes the top hit's path-derived topic and snippet as `notebook_content` (`:2837-2842`), and the prompt renders it as `<notebook topic="...">` (`cognitive/cognitive_agent.py:9415-9419`, `:11324-11328`). The snippet is `content_text[:200]` (`records_store.py:1155`), so the `[:300]` at `proactive.py:2841` cuts nothing.
2. **Why the filter does not hold.**
   - `scope` is a classification label (`records_store.py:48-53`). `notebooks/Anvil` is unknown and is read as level 2 (`:140`).
   - `reader_id=None` skips the identity layer (`:143`).
   - The walk is every `.md` file in the repository (`:1128`), not the agent's directory.
   - The query is one word, so every match scores 1.0 (`:1154`). The sort is stable (`:1158`), so on a tie path order picks the top hit.
   - So the top hit can be another agent's `private` note, or another department's `department` note that mentions the word.
   - `record_is_readable`'s own docstring names this caller and `/records/search` as the callers kept level-only (`:113-116`).
3. **Measured on `317fcdc0`** with the orchestrator's probe (real store, real `_build_self_monitoring_context`; `logs/bf949/probe-evidence-head-317fcdc0.txt`, gitignored; its premise held):
   - The control refuses Anvil and allows Bravo on Bravo's `private` entry.
   - Fixture S-issue (Anvil's own note lacks the word) leaks the entry. S-after (the agent sorts after Bravo) leaks it. S-before does not, only because of path order.
   - `search(scope="notebooks/Anvil")` and `search(scope="nonsense")` both return Bravo's entry.
   - The AD-725 DM knowledge lookup leaks it, and `GET /api/records/search` returns it.
4. **The class.** Four `src` calls reach `RecordsStore.search` (Absence A1):
   - `proactive.py:2834`, the defect.
   - `cognitive/dm_targeted_lookup.py:236`, `rs.search(query)` with no reader. Its text reaches the addressed agent's prompt (`routers/agents.py:3146-3159`). It is off in the committed `config/system.yaml:1668-1669`; the live config was not read.
   - `routers/records.py:173`, with `scope` taken straight from the query string and no reader.
   - `cognitive/oracle_service.py:1066`, already scope `"ship"` with a reader (BF-679).
5. **A root not spelled as it resolves (review round 1, `logs/bf949/review-r1-report.md`).** `RecordsStore.__init__` keeps `Path(config.repo_path)` as configured (`records_store.py:216`). Startup derives only an empty `records.repo_path` and passes any other value through (`startup/cognitive_services.py:607-609`). `_safe_path` returns a resolved path (`:1265`). `list_entries` walks `_safe_path(directory)` and takes each path `relative_to` the configured root (`:1025`, `:1031`), as `list_bills` does under `_safe_path("bills")` (`:603`, `:609`). So for a relative root (`records.repo_path: ship-records`), or an absolute one through `..` (and, by reading, a link or a Windows short name), the first file such a walk finds raises `ValueError`. The pull calls `list_entries(f"notebooks/{callsign}", ...)` first and catches the error, so it gave the agent no notebook context (`logs/bf949/probe-evidence-relroot-base.txt`). M2 copied the pattern into `search(directory=...)` (`701cabcd` `:1136`, `:1140`; `probe-evidence-relroot-head.txt`).

## 2. Solution

- **M1:** a real-store test file, written first. Cases that change are `xfail(strict=True)`, so each must fail on the base. The census premise and the Captain's view of the route pass on the base.
- **M2:**
  - `RecordsStore.search` gains `directory` (the walk is confined to it, validated as `list_entries` validates it) and raises `ValueError` for a scope that is not one of the four labels.
  - The pull searches `notebooks/{callsign}` at `ship`, as the agent and its department.
  - `GET /api/records/search` reads as `captain` and answers an unknown scope with 400.
  - Docstrings and comments that would become false are deleted or corrected.
- **M3:** the DM knowledge lookup reads as the addressed agent, resolved by `make_reader_identity_resolver`. Every unresolved path reads as the anonymous `""`.
- **M4:** trackers and ledger.
- **R1** (review round 1): a directory walk in `list_entries`, `search` and `list_bills` takes its paths against the resolved root, the form `_safe_path` returns. A whole-repository walk is unchanged.

## 3. Decisions

Criteria order: correctness, safety, compatibility, architectural fit, reversibility, validation cost.

- **NR1, the pull (D1), chosen (b): a `directory` keyword on `search`, with identity passed and scope `ship`.**
  - (b) confines the walk, so the 20-hit cap (`records_store.py:1159`) is applied to the agent's own entries only. It removes the per-cycle full-repository read for this caller and mirrors `list_entries(directory=...)` (`:1001-1031`).
  - Cost: one additive keyword-only argument with default `""`, so every existing caller is unchanged (A3, A4).
  - Rejected (a), the issue's M2 (identity, then a `notebooks/{callsign}/` filter on the results). It is wrong on a populated corpus: 20 readable hits that sort first crowd out the agent's own entry before the filter runs (T3). Rejected (c), matching over `list_entries` in `proactive.py`: it duplicates `search`'s scoring and re-reads every entry.
  - Identity is kept with (b) as defence in depth: an entry by another author placed inside the agent's directory is still identity-gated.
  - Scope `ship` keeps the level the base applied (`:140`), so the agent's own `fleet` entries stay out, as before (L3).
- **NR2, unknown scope (D2), chosen: `search` raises `ValueError("Unknown records scope; expected one of: private, department, ship, fleet")` before reading any file.**
  - `record_is_readable` and `build_records_scope_filter` keep their level-2 default. They are pure, and in production they are reached only through `search` and through `SemanticKnowledgeLayer.search` with the Oracle's constant `"ship"` (A2). The clause "exactly as `RecordsStore.search` has always done" (`records_store.py:105`) and the comment at `semantic.py:34-35` would become false, so P2-1 deletes the first and P2-4 corrects the second.
  - Consumers that can pass a scope: the route (from its query string; P2-6 catches the error and returns 400, never 500), the pull (P2-5 passes `ship`; its block already catches exceptions, `proactive.py:2843-2844`), the DM lookup (default `ship`) and the Oracle (`_RECORDS_QUERY_SCOPE`, `oracle_service.py:69`).
  - Rejected: returning `[]` (that hides the class of bug BF-949 is); logging and widening (fails acceptance 3); failing closed inside the two pure helpers (rewrites the BF-679 parity tests for a path no production caller reaches).
- **NR3, closing the class (D3), chosen: keep `reader_id=None` and add a census test.**
  - The census pins every `.search(` call under `src/probos` whose receiver, or a local name bound to it, mentions `records`, by file and function. Each must pass `reader_id` or be named in `_DELIBERATELY_ANONYMOUS` with its reason (empty after M3).
  - The census and the list live in the test file. The census fails on a caller that is added, moved or renamed, and on a list entry with no live call.
  - Rejected: making `reader_id` required. It breaks seven test calls in five files (A3) for no production gain once all four callers pass it.
- **NR4, the DM lookup (D4), chosen: fix it in this batch as M3.**
  - Its text reaches the addressed agent's prompt, so it reads as that agent: `make_reader_identity_resolver(registry=runtime.registry, ontology=runtime.ontology)`, the resolver the Oracle uses (`runtime.py:3516-3526`).
  - A missing registry or ontology, an empty or non-string id, an unknown agent, or a raising resolver all read as `("", "")`, BF-679's anonymous reader. It never reads as `captain`, even though a Captain's DM triggers it.
- **NR5, the route (D5), chosen: a fixed `reader_id="captain"`.**
  - The route serves the Captain's notebooks browser (AD-523b; `ui/src/store/useStore.ts:2073` sends `scope=ship`). Its sibling `GET /documents/{path}` defaults `reader` to `captain` (`routers/records.py:58-61`).
  - For the four labels the results are the base's, since the captain reader skips identity (`records_store.py:143`).
  - Who can reach it today: the API binds `127.0.0.1` by default (`__main__.py:4461`) with no auth middleware (CORS only, `api.py:203-210`), so the HXI and any local process can. Agents' `http_fetch` refuses private addresses (`agents/http_fetch.py:399`); the browser tool was not traced.
  - Not a Captain condition: no control is weakened, no supported use breaks, and an unknown scope narrows to 400.
  - Rejected: a `reader` query parameter (surface no caller uses); anonymous `""` (breaks the Captain's browser); unchanged and listed (names a Captain surface "identity not specified").
- **NR6, tests (D6).**
  - The new file: three whole-path fixtures, a premise that the identity layer can refuse the reader, and T2, T3 and T10 (the census).
  - The four stubbed siblings (`test_self_monitoring.py:391`, `:411`, `:532`, `:549`) and `test_ad550_notebook_dedup.py:493`, `:521`, `:547` are kept: they test index, limit and tier, and `AsyncMock` accepts the new keywords.
  - `test_notebook_semantic_pull` gains an assertion on the call's arguments (P2-7); the real-store test beside it is T1.
  - BF-679's `test_default_call_is_unchanged_by_bf679` keeps its assertion (a `None` reader still applies the level only); its docstring, which names the two callers, is corrected (P2-8).
  - Unchanged, and still true: `test_unknown_scope_defaults_to_ship_level` (`:641`) and `_ALL_SCOPES` (`:39`), both about the pure helpers; BF-679's module docstring (`:14`), the Oracle's anonymous-reader decision; `test_ad725_dm_targeted_lookup.py`; `test_memory_architecture.py:138`.
- **NR7, the AD-552 repetition warning (D7):** out. It is not privacy-bearing.
- **NR8, the walk root (review round 1), chosen O1: `root = self._repo_path.resolve() if directory else self._repo_path` in `list_entries` and `search`, and `root = self._repo_path.resolve()` in `list_bills` (it always walks `_safe_path("bills")`); every path is taken `relative_to(root)`.**
  - For a root configured as it resolves, `root` is that path and every result is the head's (T13). A whole-repository walk keeps the configured root, as on the head.
  - The returned `path` is the tail below the resolved root, so on Windows a directory argument in another case comes back in the stored case, as the head already returns it for an absolute root (by reading); `_archived/` is matched on that tail, as before.
  - No signature, return shape, persisted format, config field, class or method changes (§14).
  - Rejected O2, resolving `self._repo_path` once in `__init__`. It changes the spelling of the public `repo_path` (`consultation/workspace.py`, `consultation/dispatch.py`, `after_action.py`, `stand_down.py`), of `status()["repo_path"]` (`records_store.py:1194`, `runtime.py:6474`), of the log lines and of git's `cwd` for every such root. It also pins a relative root to the working directory at construction.
  - Rejected O3, fixing `search` only: the pull calls `list_entries` first (`proactive.py:2742`), so T12 still fails.
  - Rejected O4, walking `self._repo_path / _safe_path(directory).relative_to(self._repo_path.resolve())`: the same paths, with a second join.
- **Config:** none. **EventType:** none. **No class and no method** is added to `RecordsStore`, `ProactiveCognitiveLoop` or `LookupDispatcher`.

## 4. Milestones and gates

| M | Tier | Why | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only, no `src`; its strength is held by the strict xfails failing on the base, the premise asserts, and §10 | N1-1 | G1 |
| M2 | HIGH | the admissibility path of a shared store method, a public signature, an HTTP response, and the privacy-bearing pull | P2-1 to P2-15 | G2 |
| M3 | HIGH | identity resolution whose every failure must fail closed | P3-1 to P3-5 | G3 |
| M4 | STANDARD | trackers | P4-1, P4-2, the ledger | G4 |
| R1 | HIGH | the result of `list_entries`, a shared store method that the stand-down and the erasure's citation check read strictly | R1a: R1-1 to R1-3; R1b: R1-4 to R1-12 | GR1a, GR1b |

- **G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf949_notebook_reader_identity.py -q -n 0`. Expected: 3 passed, 16 xfailed (19 cases).
- **G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf949_notebook_reader_identity.py tests/test_bf679_oracle_records_reader_identity.py tests/test_self_monitoring.py tests/test_records_store.py tests/test_ad550_notebook_dedup.py tests/test_ad1138_records_semantic_index.py tests/test_ad1140_publish_finding.py tests/test_graduated_zones.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`. Expected in the new file: 14 passed, 5 xfailed (T6, T10).
- **G3:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf949_notebook_reader_identity.py tests/test_ad725_dm_targeted_lookup.py tests/test_bf679_oracle_records_reader_identity.py tests/test_layer_boundaries.py -q -n 0`, then the architecture check. Expected: the new file 19 passed, no xfail left.
- **G4:**
  - `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`
  - `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`
  - `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`

- **GR1a** (after R1a, `src` as at `701cabcd`): `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf949_notebook_reader_identity.py -q -n 0 -rxX`. Expected: 20 passed, 7 xfailed (27 cases). T11's six cases fail on `ValueError` and T12 on `AssertionError`; strict `raises=` reports any other exception as a failure.
- **GR1b** (after R1b): `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf949_notebook_reader_identity.py tests/test_records_store.py tests/test_path_traversal.py tests/test_ad618a_bill_schema.py tests/test_self_monitoring.py tests/test_ad550_notebook_dedup.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad562_records_browse_endpoint.py tests/test_ad563_knowledge_linting.py tests/test_ad1184_ad_ledger.py -q -n 0`. Then the architecture check, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; if it fails, run it without `--check` and stage the two files it writes. Expected: the new file 27 passed, no xfail left.

The broad gate runs once for the batch (main session, `--receipt`).

## 5. Commit messages

- M1: `BF-949 M1: real-store reproductions of the notebook pull and the records search callers`
- M2: `BF-949 M2: the notebook pull reads only the agent's own notebook, as the agent; an unknown records scope is refused`
- M3: `BF-949 M3: the DM knowledge lookup reads Ship's Records as the addressed agent`
- M4: `BF-949 M4: trackers and ledger`
- Contract amendment: `BF-949 (#1741): contract amendment R1, the walk root (review round 1)`
- R1a: `BF-949 R1a: directory walks under a root not spelled as it resolves, as strict xfails`
- R1b: `BF-949 R1b: a directory walk takes its paths against the resolved root`

## 6. Tests (`tests/test_bf949_notebook_reader_identity.py`)

| Id | Test | Covers | xfail until |
|---|---|---|---|
| T1 | `test_another_agents_private_note_never_reaches_the_pull` (3 fixtures) | Acceptance 1, whole path | M2 (two cases; the third passes on the base by path order) |
| T2 | `test_a_department_colleagues_note_is_not_shown_as_the_agents_own` | NR1: identity alone admits it | M2 |
| T3 | `test_the_agents_own_entry_is_found_behind_twenty_readable_matches` | NR1 against (a) | M2 |
| T4 | `test_search_refuses_an_unknown_scope` (5 scopes) | Acceptance 3 | M2 |
| T5 | `test_search_walks_only_the_directory_it_is_given` | NR1's keyword | M2 |
| T6 | `test_the_dm_knowledge_lookup_reads_as_the_addressed_agent` (4 cases) | NR4 | M3 |
| T7 | `test_the_records_search_route_still_returns_what_the_captain_may_read` | NR5 compatibility | none |
| T8 | `test_the_records_search_route_answers_an_unknown_scope_with_400` | NR2 at the HTTP boundary | M2 |
| T9 | `test_the_census_finds_the_four_records_search_callers` | Acceptance 2's premise | none |
| T10 | `test_every_records_search_caller_in_src_passes_a_reader` | Acceptance 2 | M3 |
| T11 | `test_a_root_spelled_otherwise_walks_a_directory` (3 walks × 2 spellings) | NR8: `list_entries`, `search`, `list_bills` | R1 |
| T12 | `test_a_relative_root_keeps_the_notebook_pull` | NR8, whole path | R1 |
| T13 | `test_a_root_spelled_as_it_resolves_walks_as_before` | NR8 compatibility (control) | none |

## 7. The contract

### 7.1 M1

**N1-1** `tests/test_bf949_notebook_reader_identity.py` (new)

```python
"""BF-949 (#1741): the self-monitoring notebook pull reads only the agent's own notebook, as the agent.

Real fixtures throughout: a real ``RecordsStore`` on ``tmp_path``, the real
``ProactiveCognitiveLoop._build_self_monitoring_context``, the real ``LookupDispatcher`` and the
``search_records`` route function. Nothing here replaces ``RecordsStore.search``.
"""

from __future__ import annotations

import ast
import functools
import json
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse

from probos.cognitive.dm_targeted_lookup import LookupDispatcher
from probos.config import DmTargetedLookupConfig, RecordsConfig
from probos.crew_profile import Rank
from probos.knowledge.records_store import RecordsStore
from probos.proactive import ProactiveCognitiveLoop
from probos.routers.records import search_records
from tests.test_bf679_oracle_records_reader_identity import _FakeAgent, _FakeOntology, _FakeRegistry

_SECRET = "BRAVO-PRIVATE-SECRET-7731"
_BRAVO = "notebooks/Bravo/reactor-notes.md"
_ZEPHYR = "notebooks/Zephyr/own-topic.md"
_SCOPE_ERROR = "Unknown records scope; expected one of: private, department, ship, fleet"
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_M2 = "BF-949 M2: on the base the pull searches the whole repository with no reader"
_M3 = "BF-949 M3: on the base the DM knowledge lookup searches with no reader"

# BF-949: every RecordsStore.search call under src/probos, by file and enclosing function.
_RECORDS_SEARCH_CALLERS = frozenset({
    ("cognitive/dm_targeted_lookup.py", "_dispatch"),
    ("cognitive/oracle_service.py", "_query_records_keyword"),
    ("proactive.py", "_build_self_monitoring_context"),
    ("routers/records.py", "search_records"),
})
# BF-949: RecordsStore.search callers that deliberately pass no reader, each with its reason. None today.
_DELIBERATELY_ANONYMOUS: dict[tuple[str, str], str] = {}


async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


async def _write_bravo_secret(store: RecordsStore) -> None:
    """Bravo's note: the department word and the secret, at the notebook default (``private``)."""
    await store.write_notebook(
        "Bravo", "reactor-notes", f"engineering {_SECRET} written for my eyes only", department="engineering",
    )


async def _self_monitoring(store: RecordsStore, callsign: str) -> dict[str, Any]:
    """``callsign``'s self-monitoring context at trust 0.75, with no Ward Room posts and no episodic memory."""
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
    return await loop._build_self_monitoring_context(agent, callsign, runtime)


_PULL_FIXTURES = [
    pytest.param(
        "Anvil", "my own calibration log, nothing else", "", None,
        id="own-note-lacks-the-word", marks=pytest.mark.xfail(strict=True, reason=_M2),
    ),
    pytest.param(
        "Zephyr", "engineering notes of my own", "engineering", "own-topic",
        id="agent-sorts-after-bravo", marks=pytest.mark.xfail(strict=True, reason=_M2),
    ),
    pytest.param(
        "Anvil", "engineering notes of my own", "engineering", "own-topic", id="agent-sorts-before-bravo",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("callsign", "own_body", "own_department", "expected_topic"), _PULL_FIXTURES)
async def test_another_agents_private_note_never_reaches_the_pull(
    tmp_path: Path, callsign: str, own_body: str, own_department: str, expected_topic: str | None,
) -> None:
    """Acceptance 1. The query is one word, so every match ties and path order picks the top hit."""
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook(callsign, "own-topic", own_body, department=own_department)
    # Premise: the identity layer refuses this reader Bravo's entry, and the secret is in it.
    assert await store.read_entry(_BRAVO, reader_id=callsign, reader_department="engineering") is None
    bravo = await store.read_entry(_BRAVO, reader_id="Bravo", reader_department="engineering")
    assert bravo["frontmatter"]["classification"] == "private" and _SECRET in bravo["content"]
    result = await _self_monitoring(store, callsign)
    assert "notebook_index" in result  # premise: the notebook block ran
    assert _SECRET not in repr(result)
    if expected_topic is None:
        assert "notebook_content" not in result
    else:
        assert result["notebook_content"]["topic"] == expected_topic
        assert own_body in result["notebook_content"]["snippet"]


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_a_department_colleagues_note_is_not_shown_as_the_agents_own(tmp_path: Path) -> None:
    """Bravo's ``department`` note is readable by an engineering reader; it is still not Zephyr's notebook."""
    store = await _store(tmp_path)
    await store.write_notebook(
        "Bravo", "shared-notes", "engineering shift handover for the department",
        department="engineering", classification="department",
    )
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    # Premise: the identity layer admits Bravo's note to Zephyr, so only the directory keeps it out.
    assert await store.read_entry(
        "notebooks/Bravo/shared-notes.md", reader_id="Zephyr", reader_department="engineering",
    ) is not None
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "own-topic"


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_the_agents_own_entry_is_found_behind_twenty_readable_matches(tmp_path: Path) -> None:
    """``search`` keeps 20 hits, so a filter applied to its result would lose an entry that sorts 22nd."""
    store = await _store(tmp_path)
    for index in range(21):
        await store.write_notebook(
            f"Able{index:02d}", "status", "engineering status for the ship",
            department="engineering", classification="ship",
        )
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    # Premise: a whole-repository search as Zephyr returns twenty hits, none of them Zephyr's.
    hits = await store.search("engineering", scope="ship", reader_id="Zephyr", reader_department="engineering")
    assert len(hits) == 20 and not any(hit["path"].startswith("notebooks/Zephyr/") for hit in hits)
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "own-topic"


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [
    pytest.param("notebooks/Anvil", id="a-path"),
    pytest.param("nonsense", id="unknown-label"),
    pytest.param("", id="empty"),
    pytest.param("Ship", id="wrong-case"),
    pytest.param(None, id="not-a-string"),
])
async def test_search_refuses_an_unknown_scope(tmp_path: Path, scope: Any) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    with pytest.raises(ValueError, match="Unknown records scope"):
        await store.search("engineering", scope=scope)


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_search_walks_only_the_directory_it_is_given(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    everything = await store.search("engineering", scope="ship", reader_id="captain")
    assert {hit["path"] for hit in everything} == {_BRAVO, _ZEPHYR}  # premise: "" walks the whole repository
    confined = await store.search("engineering", scope="ship", reader_id="captain", directory="notebooks/Zephyr")
    assert [hit["path"] for hit in confined] == [_ZEPHYR]
    assert await store.search("engineering", scope="ship", reader_id="captain", directory="notebooks/Nobody") == []
    with pytest.raises(ValueError, match="Path traversal denied"):
        await store.search("engineering", scope="ship", reader_id="captain", directory="../outside")


class _RaisingRegistry:
    def get(self, agent_id: str) -> Any:
        raise RuntimeError("registry unavailable")

    def all(self) -> list[Any]:
        raise RuntimeError("registry unavailable")


def _dm_runtime(store: RecordsStore, registry: str) -> SimpleNamespace:
    """The surface the knowledge lookup reads: the store and, unless ``registry`` is "none", a registry and an ontology."""
    if registry == "none":
        return SimpleNamespace(records_store=store)
    crew = _FakeRegistry([_FakeAgent("id-Anvil", callsign="Anvil", agent_type="engineering_agent")])
    return SimpleNamespace(
        records_store=store,
        registry=crew if registry == "crew" else _RaisingRegistry(),
        ontology=_FakeOntology({"engineering_agent": "engineering"}),
    )


@pytest.mark.xfail(strict=True, reason=_M3)
@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_id", "registry", "sees_own"), [
    pytest.param("id-Anvil", "crew", True, id="addressed-agent-resolves"),
    pytest.param("id-ghost", "crew", False, id="unresolved-agent-is-anonymous"),
    pytest.param("id-Anvil", "none", False, id="no-registry-is-anonymous"),
    pytest.param("id-Anvil", "raising", False, id="raising-registry-is-anonymous"),
])
async def test_the_dm_knowledge_lookup_reads_as_the_addressed_agent(
    tmp_path: Path, agent_id: str, registry: str, sees_own: bool,
) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook("Anvil", "own-topic", "engineering ANVIL-OWN-NOTE", department="engineering")
    await store.write_entry(
        author="Carol", path="reports/ship-briefing.md", content="engineering briefing for the whole ship",
        message="ship", classification="ship",
    )
    config = DmTargetedLookupConfig(
        enabled=True, enable_knowledge=True, timeout_ms=10_000, max_lookup_chars=100_000,
    )
    dispatcher = LookupDispatcher(runtime=_dm_runtime(store, registry), config=config)
    result = await dispatcher.maybe_lookup("what do the ship's records say about engineering", agent_id=agent_id)
    assert result is not None and result.lookup_type == "knowledge"
    assert "reports/ship-briefing.md" in result.content  # premise: the lookup ran and read the commons
    assert _SECRET not in result.content
    assert ("ANVIL-OWN-NOTE" in result.content) is sees_own


@pytest.mark.asyncio
async def test_the_records_search_route_still_returns_what_the_captain_may_read(tmp_path: Path) -> None:
    """The route serves the Captain's notebooks browser (AD-523b): a private note is in its results, as on the base."""
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    body = await search_records(q="engineering", scope="ship", runtime=SimpleNamespace(_records_store=store))
    assert [hit["path"] for hit in body["results"]] == [_BRAVO] and body["count"] == 1


@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_the_records_search_route_answers_an_unknown_scope_with_400(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    response = await search_records(
        q="engineering", scope="notebooks/Bravo", runtime=SimpleNamespace(_records_store=store),
    )
    assert isinstance(response, JSONResponse) and response.status_code == 400
    assert json.loads(response.body) == {"error": _SCOPE_ERROR}


def _own_nodes(func: ast.AST) -> Iterator[ast.AST]:
    """Every node inside ``func`` that is not inside a nested function or lambda."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


@functools.cache
def _records_search_calls() -> dict[tuple[str, str], tuple[ast.Call, ...]]:
    """``.search(...)`` calls whose receiver names Ship's Records, directly or through a local bound to it."""
    found: dict[tuple[str, str], list[ast.Call]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(_own_nodes(func))
            aliases = {
                target.id
                for node in nodes if isinstance(node, ast.Assign) and "records" in ast.unparse(node.value)
                for target in node.targets if isinstance(target, ast.Name)
            }
            for node in nodes:
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                receiver = node.func.value
                named = "records" in ast.unparse(receiver)
                aliased = isinstance(receiver, ast.Name) and receiver.id in aliases
                if node.func.attr == "search" and (named or aliased):
                    found.setdefault((path.relative_to(_SRC).as_posix(), func.name), []).append(node)
    return {caller: tuple(calls) for caller, calls in found.items()}


def test_the_census_finds_the_four_records_search_callers() -> None:
    """Acceptance 2's premise: the census sees the four callers and nothing else."""
    found = _records_search_calls()
    assert set(found) == _RECORDS_SEARCH_CALLERS, (
        "a RecordsStore.search caller was added, moved or renamed: give it a reader_id, then name it in "
        "_RECORDS_SEARCH_CALLERS, or in _DELIBERATELY_ANONYMOUS with its reason"
    )
    assert set(_DELIBERATELY_ANONYMOUS) <= set(found)  # no entry outlives its call


@pytest.mark.xfail(strict=True, reason=_M3)
def test_every_records_search_caller_in_src_passes_a_reader() -> None:
    """Acceptance 2: each caller passes ``reader_id`` or is named, with its reason, as deliberately anonymous."""
    for caller, calls in _records_search_calls().items():
        for call in calls:
            passes_reader = any(keyword.arg == "reader_id" for keyword in call.keywords)
            assert passes_reader or caller in _DELIBERATELY_ANONYMOUS, f"{caller} searches with no reader"
```

### 7.2 M2

**P2-1** `src/probos/knowledge/records_store.py`

SEARCH:
```python
    * **Scope level** (always applied) — a record is admissible when
      ``level(classification) <= level(scope)``. An unrecognised record
      classification defaults to level ``0`` and an unrecognised ``scope`` to
      level ``2``, exactly as :meth:`RecordsStore.search` has always done.
```
REPLACE:
```python
    * **Scope level** (always applied) — a record is admissible when
      ``level(classification) <= level(scope)``. An unrecognised record
      classification defaults to level ``0`` and an unrecognised ``scope`` to
      level ``2``.
```

**P2-2** `src/probos/knowledge/records_store.py`

SEARCH:
```python
    * ``None`` — **identity not specified**. Scope level only; the pre-BF-679
      behaviour, kept so existing callers of :meth:`RecordsStore.search` (the
      ``/records/search`` endpoint, self-monitoring's notebook pull) are
      byte-identical.
```
REPLACE:
```python
    * ``None`` — **identity not specified**. Scope level only; the pre-BF-679
      behaviour.
```

**P2-3** `src/probos/knowledge/records_store.py`

SEARCH:
```python
    async def search(
        self,
        query: str,
        scope: str = "ship",
        *,
        reader_id: str | None = None,
        reader_department: str = "",
    ) -> list[dict]:
        """Keyword search across records.

        Simple word-matching against frontmatter fields and content.

        BF-679: ``reader_id`` / ``reader_department`` add the identity layer
        :meth:`read_entry` applies, so a caller that knows who is asking no
        longer receives another crew member's ``private`` or out-of-department
        records. The default ``reader_id=None`` means *identity not specified*
        and leaves the scope-level-only behaviour byte-identical; see
        :func:`record_is_readable` for the full tri-state contract.
        """
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(self._repo_path.rglob("*.md")):
```
REPLACE:
```python
    async def search(
        self,
        query: str,
        scope: str = "ship",
        *,
        reader_id: str | None = None,
        reader_department: str = "",
        directory: str = "",
    ) -> list[dict]:
        """Keyword search across records.

        Simple word-matching against frontmatter fields and content.

        BF-679: ``reader_id`` / ``reader_department`` add the identity layer
        :meth:`read_entry` applies, so a caller that knows who is asking no
        longer receives another crew member's ``private`` or out-of-department
        records. The default ``reader_id=None`` means *identity not specified*
        and applies the scope level only; see :func:`record_is_readable` for the
        full tri-state contract.

        BF-949: ``scope`` is one of the four classification labels; any other
        value raises ``ValueError``. ``directory`` confines the walk to that
        directory of the repository, validated as :meth:`list_entries` validates
        it (a path that leaves the repository raises ``ValueError``); ``""`` walks
        the whole repository.
        """
        if type(scope) is not str or scope not in _CLASSIFICATION_LEVELS:
            raise ValueError(
                "Unknown records scope; expected one of: "
                + ", ".join(_CLASSIFICATION_LEVELS)
            )
        search_path = self._safe_path(directory) if directory else self._repo_path
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(search_path.rglob("*.md")):
```

**P2-4** `src/probos/knowledge/semantic.py`

SEARCH:
```python
# AD-1138: level assumed when a scope label is unknown. Matches the
# ``_CLASSIFICATION_LEVELS.get(scope, 2)`` default in RecordsStore.search.
_DEFAULT_SCOPE = "ship"
```
REPLACE:
```python
# AD-1138: level assumed when a scope label is unknown. Matches the
# ``_CLASSIFICATION_LEVELS.get(scope, 2)`` default in ``record_is_readable``.
_DEFAULT_SCOPE = "ship"
```

**P2-5** `src/probos/proactive.py`

SEARCH:
```python
                    # Semantic pull: search notebooks for content relevant to current think
                    dept = getattr(agent, 'department', '')
                    if dept and entries:
                        search_results = await rt._records_store.search(
                            dept, scope=f"notebooks/{callsign}",
                        )
```
REPLACE:
```python
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
```

**P2-6** `src/probos/routers/records.py`

SEARCH:
```python
@router.get("/search")
async def search_records(q: str = "", scope: str = "ship", runtime: Any = Depends(get_runtime)) -> Any:
    """Search Ship's Records by keyword."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    results = await runtime._records_store.search(q, scope=scope)
    return {"query": q, "results": results, "count": len(results)}
```
REPLACE:
```python
@router.get("/search")
async def search_records(q: str = "", scope: str = "ship", runtime: Any = Depends(get_runtime)) -> Any:
    """Search Ship's Records by keyword.

    BF-949: the search reads as the Captain, the reader ``GET /documents/{path}``
    defaults to, so the scope level alone bounds the results. A ``scope`` that is
    not a classification label is HTTP 400.
    """
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    try:
        results = await runtime._records_store.search(q, scope=scope, reader_id="captain")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"query": q, "results": results, "count": len(results)}
```

**P2-7** `tests/test_self_monitoring.py`

SEARCH:
```python
        agent = _make_agent(rank=Rank.COMMANDER, department="medical")
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "notebook_content" in result
        assert "analysis" in result["notebook_content"]["snippet"]
```
REPLACE:
```python
        agent = _make_agent(rank=Rank.COMMANDER, department="medical")
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "notebook_content" in result
        assert "analysis" in result["notebook_content"]["snippet"]
        # BF-949: the pull reads only the agent's own notebook, as the agent; the real-store
        # test is tests/test_bf949_notebook_reader_identity.py.
        records.search.assert_awaited_once_with(
            "medical", scope="ship", reader_id="Bones", reader_department="medical",
            directory="notebooks/Bones",
        )
```

**P2-8** `tests/test_bf679_oracle_records_reader_identity.py`

SEARCH:
```python
    async def test_default_call_is_unchanged_by_bf679(self, records) -> None:
        """``/records/search`` and self-monitoring pass no reader; they keep
        the level-only behaviour they have always had."""
```
REPLACE:
```python
    async def test_default_call_is_unchanged_by_bf679(self, records) -> None:
        """An unspecified reader (``reader_id=None``) keeps the level-only behaviour."""
```

**P2-9** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
        id="own-note-lacks-the-word", marks=pytest.mark.xfail(strict=True, reason=_M2),
```
REPLACE:
```python
        id="own-note-lacks-the-word",
```

**P2-10** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
        id="agent-sorts-after-bravo", marks=pytest.mark.xfail(strict=True, reason=_M2),
```
REPLACE:
```python
        id="agent-sorts-after-bravo",
```

**P2-11** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_a_department_colleagues_note_is_not_shown_as_the_agents_own(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_a_department_colleagues_note_is_not_shown_as_the_agents_own(tmp_path: Path) -> None:
```

**P2-12** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_the_agents_own_entry_is_found_behind_twenty_readable_matches(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_the_agents_own_entry_is_found_behind_twenty_readable_matches(tmp_path: Path) -> None:
```

**P2-13** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [
```

**P2-14** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_search_walks_only_the_directory_it_is_given(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_search_walks_only_the_directory_it_is_given(tmp_path: Path) -> None:
```

**P2-15** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M2)
@pytest.mark.asyncio
async def test_the_records_search_route_answers_an_unknown_scope_with_400(tmp_path: Path) -> None:
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_the_records_search_route_answers_an_unknown_scope_with_400(tmp_path: Path) -> None:
```

### 7.3 M3

**P3-1** `src/probos/cognitive/dm_targeted_lookup.py`

SEARCH:
```python
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
```
REPLACE:
```python
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from probos.cognitive.oracle_service import make_reader_identity_resolver

if TYPE_CHECKING:
```

**P3-2** `src/probos/cognitive/dm_targeted_lookup.py`

SEARCH:
```python
class LookupDispatcher:
    """Runs the classifier, dispatches at most one read-only lookup."""
```
REPLACE:
```python
def _knowledge_lookup_reader(runtime: Any, agent_id: str) -> tuple[str, str]:
    """BF-949: the Ship's Records reader the knowledge lookup reads as.

    The agent the DM is addressed to, resolved as the Oracle resolves its callers
    (``make_reader_identity_resolver``): its callsign and its ontology department.
    A runtime without a registry or an ontology, an agent id that is empty or not
    a string, an agent the resolver does not find, and a resolver that raises all
    give ``("", "")``, BF-679's anonymous reader (``record_is_readable``).
    """
    registry = getattr(runtime, "registry", None)
    ontology = getattr(runtime, "ontology", None)
    if registry is None or ontology is None or type(agent_id) is not str or not agent_id:
        return "", ""
    try:
        return make_reader_identity_resolver(registry=registry, ontology=ontology)(agent_id)
    except Exception:
        logger.warning(
            "BF-949: records reader resolution failed for agent=%s; the knowledge "
            "lookup reads as the anonymous reader",
            agent_id, exc_info=True,
        )
        return "", ""


class LookupDispatcher:
    """Runs the classifier, dispatches at most one read-only lookup."""
```

**P3-3** `src/probos/cognitive/dm_targeted_lookup.py`

SEARCH:
```python
            res = rs.search(query)
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        return ""
```
REPLACE:
```python
            # BF-949: the lookup's text reaches the addressed agent's prompt, so the
            # records are read as that agent.
            reader_id, reader_department = _knowledge_lookup_reader(self._runtime, agent_id)
            res = rs.search(
                query, reader_id=reader_id, reader_department=reader_department,
            )
            if asyncio.iscoroutine(res):
                res = await res
            return self._stringify(res)
        return ""
```

**P3-4** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M3)
@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_id", "registry", "sees_own"), [
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_id", "registry", "sees_own"), [
```

**P3-5** `tests/test_bf949_notebook_reader_identity.py`

SEARCH:
```python
@pytest.mark.xfail(strict=True, reason=_M3)
def test_every_records_search_caller_in_src_passes_a_reader() -> None:
```
REPLACE:
```python
def test_every_records_search_caller_in_src_passes_a_reader() -> None:
```

### 7.4 M4

M4 changes no `src` or `tests` file. Its pairs are P4-1 and P4-2 (§8), plus the ledger.

### 7.5 R1

R1 repairs review round 1's P2 (`logs/bf949/review-r1-report.md`). Its pairs are written against `701cabcd`; line numbers are that commit's. R1a (R1-1 to R1-3) changes only the test file and is committed after GR1a. R1b (R1-4 to R1-12) is the fix, the marker deletions and the trackers.

**R1-1** `tests/test_bf949_notebook_reader_identity.py` (R1a)

SEARCH:
```python
_M3 = "BF-949 M3: on the base the DM knowledge lookup searches with no reader"
```
REPLACE:
```python
_M3 = "BF-949 M3: on the base the DM knowledge lookup searches with no reader"
_R1 = "BF-949 R1: on the head a directory walk takes its resolved paths against the root as configured"
```

**R1-2** `tests/test_bf949_notebook_reader_identity.py` (R1a)

SEARCH:
```python
async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store
```
REPLACE:
```python
async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


async def _store_spelled(root: Path, monkeypatch: pytest.MonkeyPatch, spelling: str) -> RecordsStore:
    """A store whose configured root is not its resolved path: ``ship-records`` against the working directory, or an
    absolute path through ``..``. Startup passes a non-empty ``records.repo_path`` to the store unchanged."""
    monkeypatch.chdir(root)
    if spelling == "relative":
        configured = "ship-records"
    else:
        (root / "elsewhere").mkdir()
        configured = str(root / "elsewhere" / ".." / "ship-records")
    store = RecordsStore(RecordsConfig(repo_path=configured, auto_commit=False))
    await store.initialize()
    assert store.repo_path != store.repo_path.resolve()  # premise: the configured spelling is not the resolved one
    return store
```

**R1-3** `tests/test_bf949_notebook_reader_identity.py` (R1a)

SEARCH:
```python
    with pytest.raises(ValueError, match="Path traversal denied"):
        await store.search("engineering", scope="ship", reader_id="captain", directory="../outside")


class _RaisingRegistry:
```
REPLACE:
```python
    with pytest.raises(ValueError, match="Path traversal denied"):
        await store.search("engineering", scope="ship", reader_id="captain", directory="../outside")


@pytest.mark.xfail(strict=True, raises=ValueError, reason=_R1)
@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["relative", "through-dotdot"])
@pytest.mark.parametrize("walk", ["list_entries", "search", "list_bills"])
async def test_a_root_spelled_otherwise_walks_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, walk: str, spelling: str,
) -> None:
    """A directory walk returns repository paths when the configured root is relative or runs through ``..``."""
    store = await _store_spelled(tmp_path, monkeypatch, spelling)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    (store.repo_path / "bills" / "drill.bill.yaml").write_text("bill: drill\n", encoding="utf-8")
    if walk == "list_bills":
        assert await store.list_bills() == [{"path": "bills/drill.bill.yaml", "bill_id": "drill"}]
        return
    if walk == "list_entries":
        whole = await store.list_entries()
        walked = await store.list_entries("notebooks/Zephyr")
    else:
        reader: dict[str, Any] = {"scope": "ship", "reader_id": "Zephyr", "reader_department": "engineering"}
        whole = await store.search("engineering", **reader)
        walked = await store.search("engineering", **reader, directory="notebooks/Zephyr")
    assert [item["path"] for item in whole] == [_ZEPHYR]  # premise: the whole-repository walk works with this root
    assert walked == whole


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=_R1)
@pytest.mark.asyncio
async def test_a_relative_root_keeps_the_notebook_pull(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``records.repo_path: ship-records``: the pull shows the agent its own note, and never Bravo's."""
    store = await _store_spelled(tmp_path, monkeypatch, "relative")
    await _write_bravo_secret(store)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    result = await _self_monitoring(store, "Zephyr")
    assert "notebook_index" in result  # premise: the notebook block ran
    assert result["notebook_content"]["topic"] == "own-topic"
    assert _SECRET not in repr(result)


@pytest.mark.asyncio
async def test_a_root_spelled_as_it_resolves_walks_as_before(tmp_path: Path) -> None:
    """The control: for a root configured as it resolves, a directory walk returns what the whole walk returns."""
    store = await _store(tmp_path)
    assert store.repo_path == store.repo_path.resolve()  # premise: the configured spelling is the resolved one
    await _write_bravo_secret(store)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    (store.repo_path / "_archived" / "old.md").write_text("engineering, archived\n", encoding="utf-8")
    (store.repo_path / "bills" / "drill.bill.yaml").write_text("bill: drill\n", encoding="utf-8")
    whole = await store.list_entries()
    assert [entry["path"] for entry in whole] == [_BRAVO, _ZEPHYR]
    assert await store.list_entries("notebooks") == whole
    assert await store.list_entries("_archived") == []
    hits = await store.search("engineering", scope="ship", reader_id="captain")
    assert [hit["path"] for hit in hits] == [_BRAVO, _ZEPHYR]
    assert await store.search("engineering", scope="ship", reader_id="captain", directory="notebooks") == hits
    assert await store.list_bills() == [{"path": "bills/drill.bill.yaml", "bill_id": "drill"}]


class _RaisingRegistry:
```

**R1-4** `src/probos/knowledge/records_store.py` (`list_bills`, `:605-607`; R1b)

SEARCH:
```python
        results = []
        for yaml_file in sorted(bills_dir.rglob("*.bill.yaml")):
            rel_path = str(yaml_file.relative_to(self._repo_path)).replace("\\", "/")
```
REPLACE:
```python
        results = []
        # BF-949 R1: bills_dir comes from _safe_path, which resolves, so its paths are taken against the resolved root
        root = self._repo_path.resolve()
        for yaml_file in sorted(bills_dir.rglob("*.bill.yaml")):
            rel_path = str(yaml_file.relative_to(root)).replace("\\", "/")
```

**R1-5** `src/probos/knowledge/records_store.py` (`list_entries`, `:1023-1029`; R1b)

SEARCH:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        results = []
        # AD-1341 S4 (A4): rglob passes over a directory it cannot list; the strict walk raises its OSError instead
        found = _markdown_files_or_raise(search_path) if strict else search_path.rglob("*.md")

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(self._repo_path)).replace("\\", "/")
```
REPLACE:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        results = []
        # AD-1341 S4 (A4): rglob passes over a directory it cannot list; the strict walk raises its OSError instead
        found = _markdown_files_or_raise(search_path) if strict else search_path.rglob("*.md")

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```

**R1-6** `src/probos/knowledge/records_store.py` (`search`, `:1136-1140`; R1b)

SEARCH:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(search_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(self._repo_path)).replace("\\", "/")
```
REPLACE:
```python
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(search_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```

**R1-7** `tests/test_bf949_notebook_reader_identity.py` (R1b). This deletes `_R1`, and also `_M2` and `_M3`, which nothing has referenced since M3.

SEARCH:
```python
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_M2 = "BF-949 M2: on the base the pull searches the whole repository with no reader"
_M3 = "BF-949 M3: on the base the DM knowledge lookup searches with no reader"
_R1 = "BF-949 R1: on the head a directory walk takes its resolved paths against the root as configured"
```
REPLACE:
```python
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
```

**R1-8** `tests/test_bf949_notebook_reader_identity.py` (R1b)

SEARCH:
```python
@pytest.mark.xfail(strict=True, raises=ValueError, reason=_R1)
@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["relative", "through-dotdot"])
```
REPLACE:
```python
@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["relative", "through-dotdot"])
```

**R1-9** `tests/test_bf949_notebook_reader_identity.py` (R1b)

SEARCH:
```python
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=_R1)
@pytest.mark.asyncio
async def test_a_relative_root_keeps_the_notebook_pull(
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_a_relative_root_keeps_the_notebook_pull(
```

**R1-10** `PROGRESS.md` (R1b)

SEARCH:
```
to passing a reader. Exposure on the live vessel was not measured. No config field.
```
REPLACE:
```
to passing a reader. A directory walk in `list_entries`, `search` and `list_bills` now takes its paths against the resolved root, so a relative `records.repo_path`, or one through `..`, no longer raises `ValueError` on the first file found; on the base that left the pull with no notebook context. Exposure on the live vessel was not measured. No config field.
```

**R1-11** `DECISIONS.md` (R1b)

SEARCH:
```
(`RecordsStore.search`: `directory`, the scope check; `record_is_readable` docstring),
```
REPLACE:
```
(`RecordsStore.search`: `directory`, the scope check; `record_is_readable` docstring; R1: the walk root in `list_entries`, `search` and `list_bills`),
```

**R1-12** `DECISIONS.md` (R1b)

SEARCH:
```
- *NR5 (the route).* Reads as `captain`, as its sibling `GET /documents/{path}` does by default. Rejected: a `reader` query parameter; the anonymous reader.
- *Residual.* Recorded limits L1 to L9 of the contract.
```
REPLACE:
```
- *NR5 (the route).* Reads as `captain`, as its sibling `GET /documents/{path}` does by default. Rejected: a `reader` query parameter; the anonymous reader.
- *R1 (the walk root, review round 1).* `list_entries` and `search` with a `directory`, and `list_bills`, take their paths against `self._repo_path.resolve()`, the form `_safe_path` returns; a whole-repository walk keeps the configured root. Rejected: resolving the root once in `__init__` (it changes the public `repo_path`, the status output and the log lines for every root not spelled as it resolves).
- *Residual.* Recorded limits L1 to L10 of the contract.
```

## 8. Tracking (M4's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters.
**Date rule:** both heads carry 2026-11-03. If M4 is committed later (`git log -1 --format=%cs`), use that date in both heads.
**Staging:** explicit paths only; `PROGRESS.md` and `DECISIONS.md` may hold unrelated work.

**P4-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-949 (2026-11-03), #1741 -- the self-monitoring notebook pull reads only the agent's own notebook, as the agent.** On the base, the pull of an AUTONOMOUS or UNRESTRICTED agent with notebook entries of its own called `RecordsStore.search(dept, scope=f"notebooks/{callsign}")`. `scope` is a classification label, so the path was read as `ship`; no reader was passed; and the walk covered the whole repository. So the top hit for the department word could be another crew member's `private` note, and up to 200 characters of it reached the agent's prompt as `<notebook>`. Now `search` takes `directory` (the walk is confined to it, validated as `list_entries` validates it) and refuses a scope that is not one of the four labels with `ValueError`. The pull searches `notebooks/{callsign}` at `ship` as the agent and its department. `GET /api/records/search` reads as the Captain, with the results the base gave for the four labels, and answers any other scope with HTTP 400. The AD-725 DM knowledge lookup (off in the committed config) reads as the addressed agent, resolved by `make_reader_identity_resolver`, or as the anonymous reader. A census test holds every `RecordsStore.search` caller in `src` to passing a reader. Exposure on the live vessel was not measured. No config field. The contract is `prompts/bf-949-notebook-pull-reader-identity.md`.

```

**P4-2** `DECISIONS.md`

SEARCH:
```
### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```
REPLACE:
```
### BF-949 -- The self-monitoring notebook pull reads only the agent's own notebook, as the agent (2026-11-03, #1741)

- *Scope.* `knowledge/records_store.py` (`RecordsStore.search`: `directory`, the scope check; `record_is_readable` docstring), `knowledge/semantic.py` (a comment), `proactive.py` (the pull), `routers/records.py` (`search_records`), `cognitive/dm_targeted_lookup.py` (`_knowledge_lookup_reader`, the knowledge branch), tests. Contract `prompts/bf-949-notebook-pull-reader-identity.md`.
- *NR1 (the pull).* `directory=f"notebooks/{callsign}"`, `scope="ship"`, `reader_id=callsign`, `reader_department=dept`. Rejected: a filter applied to the result (the 20-hit cap drops the agent's own entry behind 20 readable matches); matching over `list_entries` in the proactive layer.
- *NR2 (unknown scope).* `search` raises `ValueError`; the route answers 400. `record_is_readable` and `build_records_scope_filter` keep their level-2 default; no production caller reaches them with an unknown scope. Rejected: returning nothing; logging and widening; failing closed inside the two helpers.
- *NR3 (the class).* `reader_id=None` stays "identity not specified"; a census test pins every `RecordsStore.search` caller in `src`, each passing `reader_id` or named as deliberately anonymous (none). Rejected: a required `reader_id`.
- *NR4 (DM lookup).* Reads as the addressed agent, or as `("", "")` on every path that does not resolve.
- *NR5 (the route).* Reads as `captain`, as its sibling `GET /documents/{path}` does by default. Rejected: a `reader` query parameter; the anonymous reader.
- *Residual.* Recorded limits L1 to L9 of the contract.
- *Reversal.* Revert the BF-949 commits.

### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```

If another entry was inserted directly above BF-946's heading before M4, BF-949's entry still goes directly above that heading. That is the only re-anchoring the Builder may do.

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (its Bug Tracker lists BFs filed and not fixed).

## 9. What this does NOT change

- `record_is_readable`'s and `build_records_scope_filter`'s behaviour, the BF-679 parity matrix, `read_entry`, and the Oracle's two retrieval paths.
- What `list_entries`, `search` and `list_bills` return for a root configured as it resolves (T13), and every whole-repository walk (`directory=""`) for every root.
- The pending `[READ_NOTEBOOK]` path (`proactive.py:2846-2863`, already read as the agent), and the prompt rendering (`cognitive_agent.py:9415-9419`, `:11324-11328`).
- `GET /api/records/documents` and `GET /api/records/notebooks/{callsign}`, which list frontmatter with no reader (Captain surfaces; L7).
- AD-552's repetition warnings (NR7), config, `EventType`, the AD-725 config defaults, and `docs/research/clark-extended-mind-absorption.md` (a dated note whose Owner line hands the leak to BF-949).

## 10. Mutation rows (campaign of record on M3's head; NRM-12 to NRM-16 on R1b's head)

Line cells hold the source line without its leading indentation. Prefix `NRM` (absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`).

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| NRM-1 | `src/probos/knowledge/records_store.py` | `search_path = self._safe_path(directory) if directory else self._repo_path` (the one in `search`) | `search_path = self._repo_path` | `test_search_walks_only_the_directory_it_is_given` |
| NRM-2 | `src/probos/knowledge/records_store.py` | `if type(scope) is not str or scope not in _CLASSIFICATION_LEVELS:` | `if type(scope) is not str:` | `test_search_refuses_an_unknown_scope` |
| NRM-3 | `src/probos/proactive.py` | `directory=f"notebooks/{callsign}",` | delete the line | `test_a_department_colleagues_note_is_not_shown_as_the_agents_own` |
| NRM-4 | `src/probos/proactive.py` | `reader_id=callsign,` (in the pull) | delete the line | `test_every_records_search_caller_in_src_passes_a_reader` |
| NRM-5 | `src/probos/proactive.py` | `scope="ship",` (in the pull) | `scope=f"notebooks/{callsign}",` | `test_another_agents_private_note_never_reaches_the_pull` |
| NRM-6 | `src/probos/routers/records.py` | `results = await runtime._records_store.search(q, scope=scope, reader_id="captain")` | `results = await runtime._records_store.search(q, scope=scope)` | `test_every_records_search_caller_in_src_passes_a_reader` |
| NRM-7 | `src/probos/routers/records.py` | `except ValueError as e:` (in `search_records`) | `except KeyError as e:` | `test_the_records_search_route_answers_an_unknown_scope_with_400` |
| NRM-8 | `src/probos/cognitive/dm_targeted_lookup.py` | `query, reader_id=reader_id, reader_department=reader_department,` | `query,` | `test_the_dm_knowledge_lookup_reads_as_the_addressed_agent` |
| NRM-9 | `src/probos/cognitive/dm_targeted_lookup.py` | `return make_reader_identity_resolver(registry=registry, ontology=ontology)(agent_id)` | `return "", ""` | `test_the_dm_knowledge_lookup_reads_as_the_addressed_agent` |
| NRM-10 | `src/probos/cognitive/dm_targeted_lookup.py` | `return "", ""` (the first, after the guard) | `return "captain", ""` | `test_the_dm_knowledge_lookup_reads_as_the_addressed_agent` |
| NRM-11 | `src/probos/cognitive/dm_targeted_lookup.py` | `return "", ""` (the second, in `except`) | `return "captain", ""` | `test_the_dm_knowledge_lookup_reads_as_the_addressed_agent` |
| NRM-12 | `src/probos/knowledge/records_store.py` | `root = self._repo_path.resolve() if directory else self._repo_path` (the one in `list_entries`) | `root = self._repo_path` | `test_a_root_spelled_otherwise_walks_a_directory` (list_entries cases), `test_a_relative_root_keeps_the_notebook_pull` |
| NRM-13 | `src/probos/knowledge/records_store.py` | `root = self._repo_path.resolve() if directory else self._repo_path` (the one in `search`) | `root = self._repo_path` | `test_a_root_spelled_otherwise_walks_a_directory` (search cases), `test_a_relative_root_keeps_the_notebook_pull` |
| NRM-14 | `src/probos/knowledge/records_store.py` | `root = self._repo_path.resolve() if directory else self._repo_path` (the one in `list_entries`) | `root = self._repo_path.resolve()` | `test_a_root_spelled_otherwise_walks_a_directory` (list_entries cases: the whole-walk premise raises) |
| NRM-15 | `src/probos/knowledge/records_store.py` | `root = self._repo_path.resolve() if directory else self._repo_path` (the one in `search`) | `root = self._repo_path.resolve()` | `test_a_root_spelled_otherwise_walks_a_directory` (search cases: the whole-walk premise raises) |
| NRM-16 | `src/probos/knowledge/records_store.py` | `root = self._repo_path.resolve()` (the one in `list_bills`) | `root = self._repo_path` | `test_a_root_spelled_otherwise_walks_a_directory` (list_bills cases) |

**Campaign of record.** Run an unmutated baseline of the new file first, then each row against the file that holds its killer. Record the base tree and the sha256 of every mutated `src` file. NRM-12 to NRM-16 are a second campaign, run on R1b's head against `tests/test_bf949_notebook_reader_identity.py`.

## 11. Recorded limits

- **L1.** The census recognises a store by a receiver whose text, or whose local binding, contains `records`. A store reached under another name escapes it.
- **L2.** `SemanticKnowledgeLayer.search(records_scope=...)` still reads an unknown scope at level 2. Its only production caller passes `"ship"` (`oracle_service.py:1114`).
- **L3.** The pull's scope `ship` leaves the agent's own `fleet` entries out, as the base's level 2 did.
- **L4.** A `ship` entry another author placed under `notebooks/{callsign}/` would be pulled (identity admits `ship`).
- **L5.** The whole-path tests stop at `notebook_content`; the prompt rendering is unchanged and not run here.
- **L6.** The route, the DM lookup and the Oracle still walk the whole repository on each call.
- **L7.** `GET /api/records/documents` and `/notebooks/{callsign}` list any notebook's frontmatter with no reader.
- **L8.** AD-552's repetition warnings are still not rendered (NR7).
- **L9.** Exposure before the fix is not measured (§12, the Captain's).
- **L10.** R1 is run for a relative root and for an absolute root through `..` (T11, T12). A root through a link or junction, a Windows short name, and a root differing only in case were not run. By reading, `resolve()` gives each its final path, as `_safe_path` does; for the last, the head already returned the same tail.

## 12. The Captain's read-only tasks (the live vessel stays his)

- **Exposure, measured on a copy.**
  1. Copy `%LOCALAPPDATA%\ProbOS\data\ship-records` to a scratch directory. `RecordsStore.initialize` may write, so never point it at the live one.
  2. For each `notebooks/<callsign>/` holding an entry authored by `<callsign>`, take that crew member's department `D` (its entries' `department` frontmatter) and run the base call, `await store.search(D, scope="ship")`. It behaves the same before and after the merge.
  3. The entry was exposed when the list is non-empty and `hits[0]["path"]` does not start with `notebooks/<callsign>/`. Record the callsign, the path, `classification` and `author`. Only crew at COMMANDER rank or above (AUTONOMOUS, UNRESTRICTED) ran the pull.
  4. This measures today's corpus, not the corpus at each past cycle.
  5. Persistence: grep the exposed agents' episodes, Ward Room posts and notebook writes for distinctive phrases from each exposed entry's first 200 characters. By reading, the journal stores only hashes and counts (`journal.py:21-47`), and proactive episodes store the agent's own thought summary (`proactive.py:1671`).
- **Live check after merge.**
  - On the copy: run `search(D, scope="ship", reader_id=<callsign>, reader_department=D, directory=f"notebooks/{<callsign>}")` and confirm every hit is under `notebooks/<callsign>/`.
  - On the running vessel: an AUTONOMOUS agent's next proactive prompt shows `<notebook topic="X">` only where `X.md` is in `notebooks/<its callsign>/`. Use whatever surface shows the composed prompt; this contract did not identify one.

## 13. Verified Against Codebase (2026-11-03, on `317fcdc0`)

```
git rev-parse HEAD HEAD^{tree} -> 317fcdc0..., 4ca36294...
Read src/probos/knowledge/records_store.py :40-164, :490-549, :970-1069, :1095-1169, :1245-1284
  48-53 levels; 72 notebook default private; 84-155 record_is_readable (103-105, 113-116, 140, 143);
  529, 532 notebook path/author; 988-996 read_entry gates; 1025 _safe_path(directory); 1031 relative_to;
  1107-1159 search (1128 rglob, 1144, 1154 score, 1155 snippet[:200], 1159 [:20]); 1260-1271 _safe_path
Read src/probos/proactive.py :2590-2629, :2725-2875; grep Episode( -> 1410-1411, 1670-1671; 2508-2510 context
Read src/probos/cognitive/cognitive_agent.py :9413-9420, :11322-11328
Read src/probos/cognitive/dm_targeted_lookup.py :1-263 (14-21 imports, 71-74, 101-113, 156, 173-240)
Read src/probos/routers/agents.py :3135-3166 (3146-3159 dispatcher, agent_id, recall block)
Read src/probos/config_models/agentic.py :167-199; config/system.yaml :1668-1676 (enabled: false)
Read src/probos/cognitive/oracle_service.py :60-149, :470-509, :1050-1079 (69, 76, 85-134, 1066-1071)
Read src/probos/runtime.py :2220-2229 (records_store property), :3510-3534 (resolver attach)
Read src/probos/routers/records.py :1-185 (9 JSONResponse, 58-61, 88, 128-137, 166-174)
Read src/probos/api.py :150-319 (203-210 CORS only); grep __main__.py --host -> 4461 default 127.0.0.1
grep src/probos/agents/http_fetch.py SSRF -> 399
Read src/probos/knowledge/semantic.py :28-97, :495-519 (34-36, 504-505, 517-518)
Read src/probos/cognitive/journal.py :20-59
Read tests/test_bf679_oracle_records_reader_identity.py :1-178, :234-253, :636-697; grep test names
Read tests/test_self_monitoring.py :340-557; grep _make_agent -> 177-191
Read tests/test_ad725_dm_targeted_lookup.py :1-149
grep docs/development/architecture-baseline.yaml -> 751-758 RecordsStore, 862-869 ProactiveCognitiveLoop, 760
Read scripts/check_architecture_principles.py :44-68, :925-946 (srp-size compares triggers)
grep scripts/gen_ad_ledger.py -> 126-139; Read PROGRESS.md :1-4; Read DECISIONS.md :1-12, :1318-1388
grep ui/src/store/useStore.ts -> 2073 scope=ship; pyproject.toml :9 >=3.12, :181 asyncio_mode auto
logs/bf949/probe-evidence-head-317fcdc0.txt (premise held, exit 0); logs/bf949/search-callers-ast-317fcdc0.txt
```

## Absence Verified (2026-11-03, on `317fcdc0`)

```
A1 CLAIM: in src/probos, the .search( calls on a RecordsStore are exactly proactive.py:2834,
          cognitive/dm_targeted_lookup.py:236, cognitive/oracle_service.py:1066 and routers/records.py:173.
   RUN:   Grep "\.search\(" over src/probos (content, all hits shown); Grep "(getattr|hasattr)\([^)]*["']search["']"
          over src/probos; Grep "^\s*(layer|store)\s*=" over introspect.py, commands_knowledge.py, oracle_service.py,
          routers/work.py; logs/bf949/search-callers-ast-317fcdc0.txt (124 calls, 24 after the regex filter)
   FOUND: the four; every other hit is a compiled pattern or re.search, a SemanticKnowledgeLayer (introspect.py:867
          from :840, commands_knowledge.py:105 from :61, oracle_service.py:1109, :1222 from :1217), the archive store
          (oracle_service.py:1171), the work store (routers/work.py:88 from :83), or a comment (organizer_agents.py:145,
          oracle_service.py:1204); hasattr: dm_targeted_lookup.py:231 only
   HOLDS: yes for calls spelled .search( (L1)
A2 CLAIM: record_is_readable is called in src only by RecordsStore.search; build_records_scope_filter only by
          SemanticKnowledgeLayer.search; only oracle_service.py passes records_scope=.
   RUN:   Grep "record_is_readable|build_records_scope_filter|records_scope=|_CLASSIFICATION_LEVELS" over src/probos
   FOUND: records_store.py:84 (def), :1144 (call), :94, :128, :1124 (docstrings); semantic.py:39 (def), :517 (call);
          records_scope=: oracle_service.py:1114; oracle_service.py:467-468 (docstring)
   HOLDS: yes
A3 CLAIM: every test call to a real RecordsStore.search passes one of the four labels or no scope.
   RUN:   Grep "(records|store|rs|_records_store|records_store)\.search\(" over tests; -A2 on test_ad1140
   FOUND: ad1138:263 "ship"; ad1141:1121 "ship"; ad1140:500, :547 _RECORDS_QUERY_SCOPE; bf679:98-99, :660, :667,
          :674, :684, :691 "ship"; records_store:335 (none), :348 "department"; semantic_store:127-128 (none);
          ad1341_s1/s2 and ad524 hits use limit/category keywords (the archive store)
   HOLDS: yes for those receivers
A4 CLAIM: no test fake of search on the pull's path refuses a directory keyword.
   RUN:   Grep "def search\(self" over tests; Read test_self_monitoring.py :381-557; Grep search in test_ad550
   FOUND: fakes take **kw (ad1138:552, :569; ad1294:79; ad988:91), or are the archive store (ad1341_s2:315,
          ad524:196) or Gmail (bf803:140); the pull's tests use AsyncMock (self_monitoring :391 :411 :427 :532 :549;
          ad550 :493 :521 :547)
   HOLDS: yes
A5 CLAIM: no Python test calls the /api/records/search route.
   RUN:   Grep "search_records|records/search|\"/search\"" over tests
   FOUND: bf679:656 (docstring); test_semantic_knowledge.py:628, :701 (the shell's /search command)
   HOLDS: yes
A6 CLAIM: no source-scan test quotes a line this contract edits.
   RUN:   Grep "notebooks/\{callsign\}\"|rglob\(\\?\"\*\.md|exactly as :meth|search_records|_records_store\.search"
          over tests; Grep "(proactive|records_store|dm_targeted_lookup|routers/records|semantic)\.py[\"']" over tests
   FOUND: rglob in ad1140:193, ad1341_s1:393, ad1341_s4:941 (their own trees); scans of proactive.py in ad590:281,
          ad591:407, ad614:23, :29, bf156:21, bf163:19-44, bf164:72, :86, bf257:24-192, bf925_event_log_window:24,
          combo_a:19, ad1025b:65, bf874:566; ad1343/ad1346 fixtures name _run_cycle, _think_for_agent, _save_state,
          _git_sync, write_entry
   HOLDS: yes for the quoted lines; the proactive.py scans were not read one by one (the broad gate runs them)
A7 CLAIM: no file outside logs/ names _knowledge_lookup_reader, test_bf949 or bf-949; "Unknown records scope" is in no .py.
   RUN:   Grep "_knowledge_lookup_reader|test_bf949|bf-949" (files, logs/ excluded);
          Grep "_records_reader\b|Unknown records scope|test_bf949" (*.py); Glob prompts/bf-949*
   FOUND: none; only _resolve_records_reader (oracle_service.py, test_bf679), a different name; none
   HOLDS: yes
A8 CLAIM: in src, notebook_content is read only to render the prompt.
   RUN:   Grep "notebook_content" over src/probos
   FOUND: set at proactive.py:2839, :2858; read at cognitive_agent.py:9415, :11324; proactive.py:3145-3329 and
          :4287-4362 are the [NOTEBOOK] write action's local variable
   HOLDS: yes
```

**Not verified (the orchestrator measures):**
- G1's counts.
- That T10's census finds exactly the four callers on the base (T9 must pass in G1), and how long the census takes to parse `src`.
- That `rglob` on a missing directory yields nothing on Python 3.12+ (`list_entries` relies on the same).
- `relative_to` on a short-name temp path (the same as `list_entries`).
- Whether the proactive intent's `context` is recorded anywhere (event log, NATS).
- The live `dm_targeted_lookup.enabled`.
- Whether the browser tool can reach the loopback API.
- That `layer-import` raises no finding for `cognitive.dm_targeted_lookup -> cognitive.oracle_service` (G3 runs the check).

## R1: Verified Against Codebase and Absence Verified (2026-11-03, on `701cabcd`)

```
git log --oneline -6 -> 701cabcd M4, 59ad881c M3, 5cef6342 M2, 2e9497cf M1, 23747cda contract, 317fcdc0 base
Read src/probos/knowledge/records_store.py :205-249 (214 Path(config.repo_path); 222-224 repo_path), :590-619
  (601 bills_dir = _safe_path("bills"); 607 relative_to), :990-1057 (1023 walk base; 1026 strict walk; 1029
  relative_to; 1031 _archived), :1105-1164 (1136, 1139 rglob, 1140, 1141), :1262-1282 (1276-1282 _safe_path
  resolves); grep -> 167-197 _markdown_files_or_raise yields Path(directory, entry.name); 1194 status repo_path
git show 317fcdc0:src/probos/knowledge/records_store.py | grep -> 216, 603, 609, 1025, 1031, 1129 (whole walk), 1265
Read src/probos/startup/cognitive_services.py :600-613; src/probos/config.py :2658-2666; config/system.yaml 774-776 ('')
Read src/probos/proactive.py :2736-2755, grep 2834-2851 (2742 list_entries first; 2837-2843 search; 2850 except)
Read tests/test_bf949_notebook_reader_identity.py :1-302; grep tests monkeypatch.chdir -> test_ad1025_path_anchoring.py
  and others (precedent)
grep docs/development/architecture-baseline.yaml -> 750-758 RecordsStore [lines, methods]; Read
  scripts/check_architecture_principles.py :922-946
logs/bf949/probe-evidence-relroot-base.txt, probe-evidence-relroot-head.txt (list_entries raises on both)
```

```
A9  CLAIM: in src, RecordsStore.list_entries is called with a non-empty directory at exactly dreaming.py:932,
           commands_gap.py:51, knowledge_linter.py:58, notebook_quality.py:217, archive_promotion.py:310 (strict),
           proactive.py:2742, routers/gaps.py:23, routers/records.py:50, :123, :134, :220, stand_down.py:281
           (strict); search with directory= only at proactive.py:2837; list_bills nowhere.
    RUN:   Grep "\.list_entries\(|\.list_bills\(" over src (-A1); Grep "_records_store\.search\(|records\.search\(|
           store\.search\(" over src/probos (-A3); Grep "rs\.search\(" dm_targeted_lookup.py (-A2); Read
           oracle_service.py :1066-1071
    FOUND: those twelve; no directory at diagnostic_context.py:375, __main__.py:3575, backlinks.py:263,
           semantic.py:708, archive_promotion.py:368; the skill catalog's list_entries (commands_skill.py:120,
           runtime.py:6607, jit_bridge.py:203, use_skill_tool.py:114, :174, routers/skills.py:194, routers/tools.py:118,
           skill_bridge.py:55, :108, skill_catalog.py:383, :420), another class; search: only proactive.py:2842
           passes directory; list_bills: records_store.py:592 (def) only
    HOLDS: yes for calls spelled .list_entries( and .search( (L1)
A10 CLAIM: records_store.py takes relative_to(self._repo_path) at exactly :607, :1029, :1140, and calls .resolve( only
           in _safe_path.
    RUN:   Grep "relative_to|_repo_path|\.resolve\(" records_store.py
    FOUND: 607, 1029, 1140; .resolve( at 1276, 1277
    HOLDS: yes; after R1 no relative_to(self._repo_path) remains
A11 CLAIM: no production caller relies on the ValueError a root not spelled as it resolves raised, and no test asserts it.
    RUN:   Read each A9 caller's handler; Grep "subpath|is not in the" over tests
    FOUND: proactive.py:2850, dreaming.py:1228, knowledge_linter.py:59, notebook_quality.py:218, commands_gap.py:74,
           gaps.py:48 catch Exception and skip; routers/records.py:53-54, :135-136 answer 400 with the message, :225-226
           400 fixed; :123 has no handler (500); stand_down.py:282 refuses; archive_promotion.py:310 propagates to
           routers/security.py:120 before any erase; tests: no pathlib-message hit
    HOLDS: yes: each takes the error as a failure, none as an answer
A12 CLAIM: no source-scan test quotes a line R1 edits.
    RUN:   Grep "relative_to\(self\._repo_path|_safe_path\(directory\) if directory|_safe_path\(\"bills\"\)|
           records_store\.py" over tests
    FOUND: census fixtures naming _git_sync / write_entry (ad1346_effect_census.py:143, ad1346_file_write_census.py:146,
           :159, test_ad1346_admission_file_write_census.py:61, test_bf892_spawn_env_guard.py:100), an import
           (test_layer_boundaries.py:88), a duplicate-method check (test_records_store.py:423), file_durations.json:1448
    HOLDS: yes
```

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** `RecordsStore` and `ProactiveCognitiveLoop` are frozen with triggers `[lines, methods]`, and the check compares triggers only; no method is added to either. `_knowledge_lookup_reader` is a module function. The new import is cognitive to cognitive. No `create_task`, no database connect.
- **`check_dormant_classes.py`:** no `src` class added.
- **Config:** none. **EventType:** none.
- **`gen_ad_ledger.py --check`:** passes once M4 regenerates; the heads carry no status keyword in their first 120 characters.
- **Collection:** one new test file. M1's strict xfails keep G1 green on the base; R1a's keep GR1a green on `701cabcd`. R1 adds lines and no method to `RecordsStore`, so its triggers stay `[lines, methods]`.

## 15. Prior Art and Blind Spots

- **Internal:**
  - BF-679: the tri-state reader is kept; `""` stays the fail-closed reader.
  - AD-1157: notebooks became `private` by default, which is why the leak now reaches private text.
  - AD-1138: the records collection is dropped when no scope is given.
  - AD-523b: the Captain's notebooks browser is the route's consumer.
  - AD-725: the DM lookup's read-only contract is unchanged.
  - AD-550 and AD-552: the block's other reads, already identity-gated.
- **External:** skipped. This is a bug fix in ProbOS-specific plumbing with no outside analogue, and `docs/research/reference-projects.md` rows were not reviewed. Considered, deferred: all overdue rows (not relevant to a BF).
- **Blind spots found:**
  1. The issue's M2 (a filter after the search) loses the agent's own entry behind the 20-hit cap (T3).
  2. A `department` colleague's note passes identity and would still be shown as the agent's own (T2).
  3. The leak depends on path order: the third fixture does not leak on the base.
  4. The snippet is 200 characters, not 300 (`records_store.py:1155`).
  5. The DM lookup is off in the committed config; the live config was not read.
  6. The list routes expose frontmatter (L7).
  7. Limits L1 to L10.
  8. Found by review round 1, missed by this drafting: a configured root not spelled as it resolves made a directory walk raise on the first file it found (on the base in `list_entries` and `list_bills`; M2 copied it into `search`). Every fixture used a resolved `tmp_path` root; T11 and T12 use a relative one and one through `..`.

## 16. Diff Reviewer: properties to verify

1. `RecordsStore.search` raises `ValueError` for every scope that is not one of the four labels, including a non-string, before reading any file. For the four labels with `directory=""`, its result for every reader equals the base's.
2. With `directory` set, every returned path lies under that directory, and a directory that leaves the repository raises `ValueError`, as `list_entries` does.
3. The pull passes the agent's callsign, its department, scope `ship` and `notebooks/{callsign}`. No other read in `_build_self_monitoring_context` changed.
4. `GET /api/records/search` returns the base's results for the four labels. Any other scope gives HTTP 400 with the fixed message, never 500.
5. Every path through `_knowledge_lookup_reader` that does not resolve returns `("", "")`, never `"captain"` and never `None`. The resolver is `make_reader_identity_resolver`.
6. No config field, `EventType`, persisted key, `src` class or class method is added. `record_is_readable` and `build_records_scope_filter` behave as on the base.
7. Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order.
8. Each test whose xfail mark M2 or M3 removes failed on the base for the reason its marker names. T7 and T9 pass on the base.
9. R1: with `directory` set, `list_entries` and `search` take every path `relative_to` the resolved root, and `list_bills` always does; with `directory=""` both keep the configured root. For a root configured as it resolves every result equals the head's (T13). T11 and T12 failed on `701cabcd` with the exception their marker names.

## 17. Acceptance criteria

1. T1 (whole path, three fixtures, with the identity-layer premise): another agent's `private` entry never appears in `notebook_content`, and the agent's own matching entry does. T2 and T3 also pass.
2. T9 and T10: every `RecordsStore.search` caller in `src` passes `reader_id` (the anonymous list is empty).
3. T4 and T8: an unknown scope raises in the store and is HTTP 400 at the route. T7: the Captain's search results are unchanged.
4. `test_notebook_semantic_pull` asserts the call's arguments, and T1 is the real-store test beside it.
5. T6: the DM knowledge lookup reads as the addressed agent, or as the anonymous reader.
6. T11 and T12 (R1): a directory walk under a relative root, or one through `..`, returns repository paths, and the pull under a relative root shows the agent its own note and never Bravo's. T13 holds on the head and after R1.
7. Every §10 mutant is killed. G1 to G4, GR1a, GR1b and the §14 checks pass, and the broad gate's receipt is green.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
