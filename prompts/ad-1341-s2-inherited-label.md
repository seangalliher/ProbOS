# AD-1341 S2: a later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24

**Status:** build-ready. Slice 2 of 6 of #1569; it does not close the issue. **Tier HIGH:** it changes what every agent reads from the Oracle's archive tier, and a wrong label is the defect the Westworld and minority-report principles exist to prevent (inherited knowledge taken as one's own memory). No new AD or BF number. **Base:** `origin/main` `026a682f`, tree `cad2c0ee25686a5683fd0ba3be35463796b5cf35`, with S1 merged (`prompts/ad-1341-s1-archive-provenance-promotion.md`). **Captain:** nothing in this slice requires the Captain (D10).

**Milestones:** M1 (code and tests, §7.1 to §7.4) and M2 (trackers, §8). Each is one Builder delegation and one local commit. The broad gate is the orchestrator's single canonical run, once, after M2 (`scripts/run_test_gate.py --label ad1341-s2 --receipt logs/gates/ad1341-s2.receipt.json`); the Builder runs only the focused gates in §4.

**Tests:** new `tests/test_ad1341_s2_inherited_label.py`: 11 functions, 27 cases. No existing test changes: every existing archive assertion is a substring or metadata check that the label keeps (Absence S2-AV6).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| The Oracle returns every archive row to every reader, as `[category] title` then content, with no origin label | present | `oracle_service.py:1134-1157` |
| `_query_archive` is the only path from the archive to anything an agent reads | present | Absence S2-AV1, S2-AV2 |
| `generations` holds one row per close at tier 2 or above, in AUTOINCREMENT order; a skip may have an empty timeline | present | `archive_store.py:201-214`, `:179-182`; `test_ad1341_s1_archive_store.py:359-372` |
| The reset promotes, then records the close; a failed close leaves promoted entries under a timeline that keeps living | present | `__main__.py:3306-3312`, `:3265-3271` |
| The reset and the ontology read the same `ontology/instance_id`, both stripped | present | `__main__.py:3185-3188`; `ontology/loader.py:95-98` |
| The ontology is built after the Oracle; the runtime late-binds Oracle collaborators once it exists | present | `startup/cognitive_services.py:699-707`; `startup/communication.py:787-797`; `runtime.py:3357-3381` |
| Agent-facing renderers keep the head of an Oracle result's content and cut its tail | present | §5, rows 1 to 6 |
| `cognitive` may import `knowledge` | present | `tests/test_layer_boundaries.py:51` |
| The live archive's row and close counts | not verified here | §Not verified, item 1 |

## 1. Problem

#1569 Decision item 5: "A later crew retrieves archived knowledge through the Oracle tier, and it arrives marked as inherited: 'from the crew of generation N', not 'your experience'." Its acceptance line: "After a reset, a new crew's Oracle query returns an archived entry labelled as inherited from the earlier generation, never as the agent's own episode."

Today `_query_archive` (`oracle_service.py:1134-1157`) renders an entry as `[convergence_report] <title>\n<content>` with the provenance `Archive/convergence_report (timeline 1a2b3c4d...)`. Nothing tells the reading agent which crew the entry came from, or that it is not its own memory. Five renderers hand that content to agents (§5), and two of them (`format_refs`, the `oracle_query` tool's envelope) never show the provenance at all. S1's `generations` table already records each crew's close (S1 D9: "the generation order S2 will label"), but nothing reads it.

## 2. Solution overview

- **The store numbers the crews.** Every read (`search`, `get_recent`, `entry_by_id`) fills a new defaulted field, `ArchiveEntry.generation`: the place of the entry's timeline's first close among the closes `generations` attributes to a timeline. A timeline with no recorded close has `None`.
- **One label rule, in the store module.** `inheritance_label(entry, *, current_timeline)` returns one of three fixed labels: `[Archived by this crew: a record, not a memory]` for the reading crew's own timeline; `[Inherited from the crew of generation N: not your own memory]`; `[Inherited from an earlier crew: not your own memory]` when no close is recorded.
- **One attachment point.** `_query_archive` makes the label the first line of every archive result's content and adds `generation` and `inherited` to its metadata. Every renderer keeps the head of the content, so the label reaches the agent first on every path.
- **The Oracle learns this crew's timeline.** `OracleService.attach_current_timeline` (the BF-679 late-bind pattern) is called once by the runtime with the ontology's instance id. Until then, and if it fails, every entry reads as inherited: the safe direction.

No flag, no schema change, no change to the archive's contents, its score or the Oracle's tier order.

## 3. Decisions

- **D1 (premises).** §0. S1's decisions stand; S2 only reads `generations`.
- **D2 (where the label is attached).**
  - **(A) chosen:** the rule and the data in the store module (`inheritance_label`, `ArchiveEntry.generation`: the archive's contract, in its lowest owning layer, as S1 D5 put the record types there); attached once, in `OracleService._query_archive`, the one path from the archive to any agent (Absence S2-AV1, S2-AV2).
  - (B) attach in the store (`search` returns labelled content): rejected. The stored content is what was archived and what `content_sha256` hashes (S1 D3), the Captain's erase prompt shows it, and whether an entry is "this crew's" is a runtime fact the store does not know.
  - (C) attach in each renderer (`query_formatted`, the tool, `format_refs`, the crew consult, the DM lookup): rejected. Five owners, and a sixth renderer would be unlabelled by default: fail-open.
  - (D) label only the `provenance`: rejected. `format_refs` (`oracle_service.py:843`) and the tool's envelope (`provenance.py:78-80`, `oracle_query_tool.py:148`) never render provenance.
- **D3 (how generation N is computed).**
  - **(A) chosen:** N is the 1-based place of the timeline's **first** close among the distinct timelines with a non-blank `timeline_id` in `generations`, ordered by that first close's id (`_GENERATION_ORDER_SQL`). AUTOINCREMENT ids only grow, so the order is the order of the closes. A skip with no instance id numbers no generation (it names no crew). A second close of the same timeline (a reset that recorded its close, then failed in the tier loop and was run again) does not renumber it. Both outcomes (`promoted`, `skipped`) count: a skipped promotion still ended a crew.
  - (B) count every row: rejected. A blank-timeline skip and a re-close would each add a generation, and one crew could carry two numbers.
  - (C) order by `recorded_at`: rejected. Wall-clock time can go backwards; the id cannot.
  - (D) store the number in a new column at write: rejected. A schema change (v2) for a derivable value, computed under a race between two writers.

  Numbering starts at the first close the archive recorded (S1, 2026-10-22): crews before it are not numbered, so "generation 1" is the first crew whose close the archive holds (disclosed effect 3). An entry is attributed to the timeline that first promoted it (S1 D3, disclosed effect 6 there).
- **D4 (the label text and structure).**
  - **(A) chosen:** three fixed, bracketed labels, each saying first where the entry came from and then that it is not the reader's memory: `[Inherited from the crew of generation N: not your own memory]`, `[Inherited from an earlier crew: not your own memory]` (no recorded close, including any AD-524 v0 row), `[Archived by this crew: a record, not a memory]`. The label is the first line of the result's `content`; the metadata carries `generation` (int or None) and `inherited` (bool) for code. It is structural in four ways: one attachment point that no renderer can bypass; the head of the content, which every cap keeps (§5); `source_tier` stays `"archive"`, which no filter maps to episodic; and typed metadata beside the text. The longest label, with a seven-digit generation behind the widest `format_refs` prefix (a 13-digit id), ends by character 114 of that renderer's 119 (T7).
  - (B) prose framing in each consumer's preamble: rejected; the preambles already say "not your personal experiences" (`cognitive_agent.py:10546-10548`, `oracle_query_tool.py:89-97`) for the whole block, and they cannot say which crew each entry came from.
  - (C) the earlier crew's callsign in the label ("from Chapel of generation 2"): rejected. A later crew member may carry the same callsign (RS2-3), and the label must never read as the reader's own byline. The author stays in `metadata["author"]`, as before.
  - (D) datamarking or encoding the archived text (spotlighting's stronger forms): rejected. It rewrites the knowledge on every token, and the risk here is our own model misattributing a source, not an injection.
- **D5 (this crew's own entries).** An entry whose timeline is the reading crew's own (the reset refused after promotion committed, `__main__.py:3306-3312`; and every entry once S5's continuous promotion lands) is labelled `[Archived by this crew: a record, not a memory]`, not "inherited", whatever its generation: a false "inherited from generation N" would misstate what the crew is (Westworld). The Oracle learns the timeline through `attach_current_timeline`, called by the runtime once the ontology exists (`runtime.py:3357`). Not attached, or failed: every entry reads as inherited. That is the safe direction of the two possible errors: the minority-report principle forbids presenting inherited knowledge as one's own, and the reverse error only understates the crew's authorship.
  - Rejected: read `ontology/instance_id` from the Oracle (a cognitive service reaching into the data directory, outside the ontology that owns it); pass it at construction (the ontology does not exist yet at `cognitive_services.py:699-707`).
- **D6 (flag and default).**
  - **(A) chosen:** no flag; always on.
  - (B) a flag defaulting on: rejected. Its off position presents inherited knowledge unlabelled, which is a switch for violating the two principles, and nothing here needs calibrating.
  - (C) a flag defaulting off: rejected; the acceptance line fails by default.

  **Scope proof in place of a byte-identity proof:** only archive-tier results change (one function builds them, Absence S2-AV2), and an archive with no matching row returns nothing, as before. Every other tier's output is byte-identical: no other line of `query`, `query_formatted`, `query_refs` or `format_refs` changes.
- **D7 (score and tier order).**
  - **(A) chosen:** the archive's score and the Oracle's tier order are unchanged. The archive admits a row only when the whole query text is a substring of its title or content (`archive_store.py:482-484`), so a hit is a strong match; the label, not the rank, is what keeps an inherited entry from being taken as the agent's own; no consumer turns a score into "own evidence" (AD-1294 already renders it as relevance, `provenance.py:25-28`).
  - (B) a constant discount for inherited entries: rejected. An uncalibrated cross-tier constant, the shape BF-684 warns against (`oracle_service.py:162-177`).
  - (C) a keyword-overlap relevance like Tier 3: rejected for this slice; it changes ranking for every archive hit and is a separate question (RS2-5).
- **D8 (the principles).** Westworld (agents know what they are: `docs/research/metacognitive-architecture.md:115-117`, "LLM + KnowledgeStore ≠ personal memory"): every label states the entry's true origin, including "this crew" (D5). Minority report (inherited knowledge is never presented as an agent's own memory): every label ends with "not your own memory" or "not a memory"; `source_tier` stays `"archive"`; AD-607e's shard filter and the tool's sovereign-tier filter are unchanged and keep the archive in the commons (`oracle_service.py:850-878`, `oracle_query_tool.py:337-342`). This is culture in the Captain's nature/culture/nurture amendment (#1569, 2026-10-16): labelled as inherited from generation N.
- **D9 (tests that pinned the old shape).** None changes. The archive assertions in `test_ad524_ships_archive.py:118-121, 147`, `test_ad1341_s1_archive_store.py:407-411`, `test_ad1341_s1_promotion.py:382-384` and `test_ad1341_s1_reset_and_erase.py:613-615` are substring, tier and metadata checks the label keeps; `_FakeArchiveStore` (`test_ad524_ships_archive.py:191-198`) returns real `ArchiveEntry` objects, which default `generation` to None (Absence S2-AV6).
- **D10 (the Captain).** Nothing here meets a "Still requires the Captain" condition: it implements a principle the Captain set (#1569 item 5) without weakening any control. The label wording is in the envelope; the Captain may overrule it after the fact.
- **D11 (tier).** HIGH (see the status line).

**Disclosed effects.**
1. Every archive result an agent reads opens with its label line, and its metadata gains `generation` and `inherited`. `GET /oracle` (the Captain's surface, `routers/system.py:711-730`) shows the same.
2. Each archive read issues one more small query (the `generations` order).
3. Generations are numbered from the first close the archive recorded; earlier crews are not numbered.
4. Several vessels sharing one archive file (S1 disclosed effect 7) share one generation count, and each reads the other's entries as inherited from "generation N" of that shared count (RS2-1).
5. AD-688's graph expansion takes up to six of an archive parent's 16 tokens from its label (`oracle_service.py:1474`; `_extract_entity_tokens` caps at 16, `:264`): at most six more `find_edges` lookups per archive parent, and an archive parent's tokens beyond its tenth content token are not tried (RS2-4).

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Files (§7, §8) | Focused gate |
|---|---|---|
| **M1** the label | 7.1 `src/probos/knowledge/archive_store.py`; 7.2 `src/probos/cognitive/oracle_service.py`; 7.3 `src/probos/runtime.py`; 7.4 new `tests/test_ad1341_s2_inherited_label.py` | `tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad524_ships_archive.py tests/test_bf919_archive_isolation.py tests/test_bf679_oracle_records_reader_identity.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1141_crew_loop_sigma.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad688_oracle_graph_integration.py tests/test_ad686_oracle_semantic_tier.py tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad695_ship_health_oracle.py tests/test_layer_boundaries.py tests/test_ad680_public_runtime_api.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py`, then `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-1341-s2-inherited-label.md` (§12) |
| **M2** trackers | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

Write the new test file first and run it on the base: it must fail at import (`inheritance_label`), then each test must fail at the assertion §6 names once the names exist. If a test outside §7 fails only because an archive result's content now opens with the label, stop and report it (Absence S2-AV6 says none does); never delete or loosen a test.

## 5. Consumers of every value this changes

| # | Value | Consumer (renderer an agent reads) | What it keeps | Effect |
|---|---|---|---|---|
| 1 | archive `OracleResult.content` | `query_formatted` (`oracle_service.py:694-753`): the ORACLE recall tier (`cognitive_agent.py:11579-11586`, framed at `:10545-10552`) and the `oracle_lookup` sub-task (`sub_tasks/query.py:274-280`) | `content[:300]` (`:736`), after `provenance` and the score | label first |
| 2 | same | the `oracle_query` tool (`oracle_query_tool.py:260-263`) through `ProvenanceEnvelope.render` (`provenance.py:78-80`) | marker line, then content; `_cap_entry` keeps the head (`:119-129`) | label first |
| 3 | same | `format_refs(query_refs(...))` (`sub_tasks/query.py:346-362`; `oracle_service.py:788, 843-845`) | `[tier] ref_id (score) ` then `snippet[:200]`, the line cut at 119 characters plus "…" | label first and whole (T7) |
| 4 | same | the AD-1141 crew consult (`crew_executor.py:697-745, 1808-1822`) | provenance marker, then content with whitespace collapsed (`:740`), cut at 400 (`:742-745`) | label first |
| 5 | same | the AD-725 DM lookup (`dm_targeted_lookup.py:196-206, 242-262`) | `repr` of each result | label first in `content=` |
| 6 | same | AD-688 graph expansion (`oracle_service.py:1473-1525`) | tokens of `parent.content` | label words are tried as tokens (disclosed effect 5) |
| 7 | archive `metadata` gains `generation`, `inherited` | `routers/system.py:729-730` (Captain's `GET /oracle`); `query_refs` keeps only its whitelist (`oracle_service.py:790-794`) | | new keys; refs unchanged |
| 8 | `ArchiveEntry.generation` (defaulted) | `_query_archive`; `__main__.py:3393` (the erase prompt prints title, kind, ref, timeline only); `_FakeArchiveStore` | | none for the CLI; fakes default to None |
| 9 | `_row_to_entry(row, generations)` | the store's three reads only (Absence S2-AV4) | | internal |
| 10 | `OracleService.attach_current_timeline` | `runtime.py` once (T9) | | new |
| — | not consumers: `introspect.py:846-848`, `organizer_agents.py:151-153`, `commands_knowledge.py:91-93` query only `semantic` (and `episodic`); the archive is not in their tiers | | | none |

## 6. Tests

All in `tests/test_ad1341_s2_inherited_label.py`. On the base every test fails at import (`ImportError: cannot import name 'LABEL_EARLIER_CREW'`); the "First assertion to fail" column names the assertion that fails once the names exist but the behaviour is the base's.

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| T1 | `test_each_entry_carries_its_crews_generation_from_every_read` | D3 on the real store: closes `""` (skip), alpha, beta (skip), alpha again, gamma give alpha 1, beta 2, gamma 3, an unclosed timeline None, through `search`, `get_recent` and `entry_by_id`; the store's content is unlabelled | `{entry.timeline_id: entry.generation ...} == _EXPECTED` (no attribute `generation`) |
| T2 | `test_an_entry_whose_crew_has_no_recorded_close_has_no_generation[empty-generations, v0-row]` | no close, or an AD-524 v0 row: None, and the earlier-crew label | `entry.generation is None` (no attribute) |
| T3 | `test_the_label_says_where_an_entry_came_from[generation, no-current, unrecorded, zero, bool, str, this-crew-closed, this-crew-open, both-empty]` | D4, D5 on the pure rule, with exact types (a `bool` or `str` generation is no generation; an empty current timeline matches nothing) | `label == expected` |
| T3b | `test_the_fixed_labels_read_as_decided` | the two fixed texts | `LABEL_THIS_CREW == ...` |
| T4 | `test_the_oracle_puts_the_label_first_in_each_archive_result` | `_query_archive`: content is exactly `label\n[category] title\ncontent`; `generation` and `inherited` in metadata; tier `archive`; provenance unchanged | `result.content.split("\n", 1)[0] == label` (base: `[convergence_report] t-alpha`) |
| T5 | `test_an_entry_this_crew_archived_is_its_own_record_never_inherited` | D5: attached (with a trailing newline, stripped) the own timeline reads `LABEL_THIS_CREW`, `inherited` False; unattached, nothing does | `labels == {...}` |
| T5b | `test_the_oracle_takes_its_timeline_only_as_text[none, int, bytes]` | `TypeError` | `pytest.raises(TypeError)` (base: `AttributeError`, no method) |
| T6 | `test_every_path_from_the_archive_to_an_agent_carries_the_label_before_the_content[query-formatted, oracle-tool, memory-refs, crew-consult, dm-lookup]` | each real renderer, on 2,400-character entries so every cap cuts: every entry header is preceded by its label, and all three labels appear | `_every_entry_is_labelled_first(text) == 3` (base: the header follows the score or marker, not a label) |
| T7 | `test_the_label_survives_the_tightest_cap_any_consumer_applies` | `format_refs` with a 13-digit id and generation 1,000,000: the whole label survives the 120-character line | `"[Inherited from the crew of generation 1000000: not your own memory]" in refs_text` |
| T8 | `test_after_two_resets_a_later_crew_reads_each_generations_knowledge_labelled_as_inherited[default, full]` | **the real seam:** the real `probos reset` closes crew 1, crew 2 boots under a new instance id, publishes a finding and is reset; crew 3's real `OracleService` (attached to its own timeline) and the real `oracle_query` tool and `query_formatted` give crew 1's entries "generation 1" and crew 2's "generation 2", each before its content; nothing reads as crew 3's own; every result's tier is `archive` | `generations == {(_SHIP, 1), (_SECOND, 2)}` |
| T9 | `test_only_the_runtime_tells_the_oracle_its_timeline_and_it_reads_the_ontologys_instance_id` | census: `attach_current_timeline` is called once in `src`, in `runtime.py`, with the ontology's instance id | `calls == [...]` (base: `[]`) |

## 7. The contract

### 7.1 `src/probos/knowledge/archive_store.py`

Pair 1 (the module docstring):

SEARCH:
```python
Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.
```
REPLACE:
```python
Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.

AD-1341 S2: ``generations`` also numbers the crews. A timeline's generation is
its first close's place among the closes attributed to a timeline, and every read
fills an entry's ``generation`` from it. ``inheritance_label`` is what an agent
reads first about an archived entry: inherited from the crew of generation N, or
from an earlier crew, or archived by this crew; never its own memory. The Oracle's
archive tier (``OracleService._query_archive``) is the one place that attaches it.
```

Pair 2 (the entry's generation):

SEARCH:
```python
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
```
REPLACE:
```python
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()
    # AD-1341 S2 (D3): the crew generation that archived it: 1 for the first crew whose close ``generations``
    # records. None when its timeline has no recorded close (an AD-524 entry, or a close that failed).
    generation: int | None = None


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
```

Pair 3 (the generation order and the label rule):

SEARCH:
```python
_SQLITE_MAX_ROWID = 2**63 - 1


def _valid_reason(reason: object) -> str:
```
REPLACE:
```python
_SQLITE_MAX_ROWID = 2**63 - 1

# AD-1341 S2 (D3): the generation order. A timeline's generation is its first close's place among the closes
# attributed to a timeline: a skip with no instance id numbers none, and a second close of one timeline does not
# renumber it. AUTOINCREMENT ids only grow, so the first close's id orders the crews.
_GENERATION_ORDER_SQL = (
    "SELECT timeline_id FROM generations WHERE trim(timeline_id) != '' "
    "GROUP BY timeline_id ORDER BY min(id)"
)

#: AD-1341 S2 (D4, D5): what an agent reads first about an entry its own crew archived.
LABEL_THIS_CREW = "[Archived by this crew: a record, not a memory]"

#: AD-1341 S2 (D4): what an agent reads first about an inherited entry whose crew generation is not recorded.
LABEL_EARLIER_CREW = "[Inherited from an earlier crew: not your own memory]"


def inheritance_label(entry: ArchiveEntry, *, current_timeline: str) -> str:
    """AD-1341 S2 (#1569): the label an agent reads before an archived entry (D4).

    The Westworld Principle (agents know what they are) and the minority-report principle (inherited knowledge is
    never presented as an agent's own memory): every label says where the entry came from and that it is not the
    reader's memory. An entry of ``current_timeline`` (the reading crew's own instance id) was archived by this
    crew, whatever its generation (D5); any other entry is inherited, from the crew of its generation when one is
    recorded and from an earlier crew otherwise. An empty ``current_timeline`` matches nothing.
    """
    if current_timeline and entry.timeline_id == current_timeline:
        return LABEL_THIS_CREW
    if type(entry.generation) is int and entry.generation >= 1:
        return f"[Inherited from the crew of generation {entry.generation}: not your own memory]"
    return LABEL_EARLIER_CREW


def _valid_reason(reason: object) -> str:
```

Pair 4 (`entry_by_id`):

SEARCH:
```python
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None
```
REPLACE:
```python
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_entry(row, await self._generation_numbers())
```

Pair 5 (`search`):

SEARCH:
```python
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]
```
REPLACE:
```python
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2

        return [self._row_to_entry(row, generations) for row in rows]
```

Pair 6 (`get_recent`):

SEARCH:
```python
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]
```
REPLACE:
```python
            (limit,),
        )
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2
        return [self._row_to_entry(row, generations) for row in rows]
```

Pair 7 (the order read and the row mapping's signature):

SEARCH:
```python
    @staticmethod
    def _row_to_entry(row: Any) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
```
REPLACE:
```python
    async def _generation_numbers(self) -> dict[str, int]:
        """AD-1341 S2: each timeline's generation, from ``generations`` (D3). A read, so it takes no lock (D16)."""
        cursor = await self._db.execute(_GENERATION_ORDER_SQL)
        rows = await cursor.fetchall()
        return {row[0]: number for number, row in enumerate(rows, start=1)}

    @staticmethod
    def _row_to_entry(row: Any, generations: dict[str, int]) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
```

Pair 8 (the row mapping fills it):

SEARCH:
```python
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
        )
```
REPLACE:
```python
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
            generation=generations.get(row[1]),
        )
```

### 7.2 `src/probos/cognitive/oracle_service.py`

Pair 1 (import):

SEARCH:
```python
from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684
from probos.types import (  # AD-462f (types.py has no reverse dep on oracle_service)
```
REPLACE:
```python
from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684
from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
from probos.types import (  # AD-462f (types.py has no reverse dep on oracle_service)
```

Pair 2 (the attribute):

SEARCH:
```python
        self._reader_identity_resolver = reader_identity_resolver
        self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
```
REPLACE:
```python
        self._reader_identity_resolver = reader_identity_resolver
        self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
        # AD-1341 S2 (D5): this crew's timeline (the ship's instance id), so an archive entry this crew archived is
        # labelled as its own record and every other entry as inherited. "" until the runtime attaches it.
        self._current_timeline = ""
```

Pair 3 (the late bind):

SEARCH:
```python
        self._reader_identity_resolver = resolver

    def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
```
REPLACE:
```python
        self._reader_identity_resolver = resolver

    def attach_current_timeline(self, timeline_id: str) -> None:
        """AD-1341 S2: Late-bind this crew's timeline, the ship's instance id (``ontology/instance_id``).

        Used by the runtime because the ontology, which loads the instance id, is built after the cognitive phase
        that builds OracleService. Idempotent — last write wins. Until it is attached no archive entry is labelled
        as this crew's own: every entry reads as inherited, the safe direction (D5).
        """
        if type(timeline_id) is not str:
            raise TypeError("AD-1341 S2: the current timeline is the ship's instance id, a string")
        self._current_timeline = timeline_id.strip()

    def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
```

Pair 4 (`_query_archive`):

SEARCH:
```python
        """Query the Ship's Archive for cross-reset knowledge."""
        entries = await self._archive_store.search(query_text, limit=k)
        results: list[OracleResult] = []
        for entry in entries:
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))

            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```
REPLACE:
```python
        """Query the Ship's Archive for cross-reset knowledge (AD-524).

        AD-1341 S2 (#1569): every result's content opens with its inheritance label (``inheritance_label``), so
        each renderer of an Oracle result, and every cap that keeps the head of the text, hands the agent the label
        before the archived knowledge. This is the one path from the archive to an agent (D2). The score and the
        provenance are unchanged (D7).
        """
        entries = await self._archive_store.search(query_text, limit=k)
        results: list[OracleResult] = []
        for entry in entries:
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))
            label = inheritance_label(entry, current_timeline=self._current_timeline)

            results.append(OracleResult(
                source_tier="archive",
                content=f"{label}\n[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                    "generation": entry.generation,
                    "inherited": label != LABEL_THIS_CREW,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```

### 7.3 `src/probos/runtime.py`

SEARCH:
```python
                logger.warning(
                    "BF-679: failed to attach the reader-identity resolver to "
                    "OracleService; Tier 2 stays anonymous, so agents keep the "
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
```
REPLACE:
```python
                logger.warning(
                    "BF-679: failed to attach the reader-identity resolver to "
                    "OracleService; Tier 2 stays anonymous, so agents keep the "
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-1341 S2 (#1569): the Oracle labels a Ship's Archive entry this crew archived as its own record and every
        # other entry as inherited, so it needs this crew's timeline: the instance id the ontology loaded. A failure
        # degrades to "every entry inherited", never to an inherited entry labelled as this crew's (D5).
        if self._oracle_service is not None and self.ontology is not None:
            try:
                self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)
            except Exception:
                logger.warning(
                    "AD-1341 S2: failed to attach this crew's timeline to OracleService; every Ship's Archive "
                    "entry reads as inherited, including any this crew archived",
                    exc_info=True,
                )

        # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
```

### 7.4 New file: `tests/test_ad1341_s2_inherited_label.py`

```python
"""AD-1341 S2 (#1569): a later crew reads the Ship's Archive as inherited knowledge, never as its own memory.

The real ``ArchiveStore`` on a temporary file (BF-919 keeps every test archive under the suite's temporary roots),
the real ``OracleService``, and the real renderers through which an Oracle result reaches an agent:
``query_formatted`` (the ORACLE recall tier and the ``oracle_lookup`` sub-task), the AD-1139 ``oracle_query`` tool,
AD-462f memory refs, the AD-1141 crew consult and the AD-725 DM lookup. The seam test runs the real ``probos reset``
twice, with S1's helpers.
"""

from __future__ import annotations

import ast
import asyncio
import re
import time
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.cognitive.crew_executor import _render_commons_block
from probos.cognitive.dm_targeted_lookup import LookupDispatcher
from probos.cognitive.oracle_service import OracleService
from probos.knowledge.archive_store import (
    LABEL_EARLIER_CREW,
    LABEL_THIS_CREW,
    ArchiveEntry,
    ArchiveStore,
    GenerationOutcome,
    GenerationRecord,
    PromotionRecord,
    SourceKind,
    inheritance_label,
)
from probos.storage.sqlite_factory import default_factory
from probos.tools.oracle_query_tool import OracleQueryTool
from tests.test_ad1341_s1_archive_store import _plant_v0
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset, _write_records

_SRC = Path(probos.__file__).resolve().parent
_BODY = "Three officers independently traced the coolant drift."
_SECOND = "ship-did-second-0002"
_THIRD = "ship-did-third-0003"
_SECOND_REPORT = "reports/convergence/convergence-20261023-000000.md"
_HEADER = re.compile(r"\[(?:convergence_report|published_report|captains_log|notebook_finding)\] ")
_LABEL_ENDS = ("not your own memory]", "a record, not a memory]")

# Closes in id order: a skip with no instance id, alpha, beta (skipped), alpha again, gamma. t-open has no close.
_TIMELINES = ("t-alpha", "t-beta", "t-gamma", "t-open")
_EXPECTED = {"t-alpha": 1, "t-beta": 2, "t-gamma": 3, "t-open": None}


def _generation_label(generation: int) -> str:
    return f"[Inherited from the crew of generation {generation}: not your own memory]"


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _new_oracle(store: Any) -> OracleService:
    return OracleService(archive_store=store)


def _oracle(store: Any, current_timeline: str = "") -> OracleService:
    oracle = _new_oracle(store)
    oracle.attach_current_timeline(current_timeline)
    return oracle


def _content(timeline: str) -> str:
    """Long enough that every renderer's cap cuts it."""
    return f"{_BODY} ({timeline}) " + "Detail. " * 300


def _record(timeline: str) -> PromotionRecord:
    fields: dict[str, Any] = {
        "timeline_id": timeline, "source_kind": SourceKind.CONVERGENCE_REPORT,
        "source_ref": f"reports/convergence/{timeline}.md", "title": timeline, "content": _content(timeline),
        "classification": "ship", "author_callsign": "system",
    }
    return PromotionRecord(**fields)


def _closed(timeline: str, *, skipped: bool = False) -> GenerationRecord:
    fields: dict[str, Any] = {"timeline_id": timeline, "reset_tier": 2}
    if skipped:
        fields.update(outcome=GenerationOutcome.SKIPPED, reason="Captain: a recorded skip")
    else:
        fields.update(outcome=GenerationOutcome.PROMOTED, created=1)
    return GenerationRecord(**fields)


def _entry(timeline: str, generation: Any) -> ArchiveEntry:
    fields: dict[str, Any] = {
        "id": 7, "timeline_id": timeline, "category": "convergence_report", "title": "t", "content": _BODY,
        "author_agent_type": "", "author_callsign": "system", "archived_at": 1.0, "generation": generation,
    }
    return ArchiveEntry(**fields)


async def _plant(store: ArchiveStore, timelines: tuple[str, ...] = _TIMELINES) -> None:
    for closure in (
        _closed("", skipped=True), _closed("t-alpha"), _closed("t-beta", skipped=True), _closed("t-alpha"),
        _closed("t-gamma"),
    ):
        await store.record_generation(closure)
    for timeline in timelines:
        await store.promote_entry(_record(timeline))


def _every_entry_is_labelled_first(text: str) -> int:
    """Each archive entry's header (``[<kind>] <title>``) is preceded by an inheritance label, with only whitespace,
    or a ``repr``'s escaped newline, between them. Returns how many headers it checked."""
    checked = 0
    for header in _HEADER.finditer(text):
        before = text[: header.start()].rstrip().removesuffix("\\n").rstrip()
        assert before.endswith(_LABEL_ENDS), text[max(0, header.start() - 160): header.start() + 40]
        checked += 1
    return checked


# --- T1, T2: the store numbers the crews (D3) -----------------------------------------------------------------


async def test_each_entry_carries_its_crews_generation_from_every_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        searched = await store.search("coolant drift")
        recent = await store.get_recent()
        by_id = [await store.entry_by_id(entry.id) for entry in recent]
    finally:
        await store.close()
    for read in (searched, recent, by_id):
        assert {entry.timeline_id: entry.generation for entry in read} == _EXPECTED
    assert sorted(entry.content for entry in recent) == sorted(_content(t) for t in _TIMELINES)  # unlabelled


@pytest.mark.parametrize("v0", [False, True], ids=["empty-generations", "v0-row"])
async def test_an_entry_whose_crew_has_no_recorded_close_has_no_generation(tmp_path: Path, v0: bool) -> None:
    if v0:
        _plant_v0(tmp_path / "archive.db")  # AD-524's two rows, timeline "timeline-zero", never closed
    store = _store(tmp_path)
    await store.initialize()
    try:
        if v0:
            await store.record_generation(_closed("t-alpha"))
            entries = await store.search("Legacy")
        else:
            await store.promote_entry(_record("t-alpha"))
            entries = await store.search("coolant drift")
    finally:
        await store.close()
    assert entries, "premise: the read returns the entry"
    assert all(entry.generation is None for entry in entries)
    assert {inheritance_label(entry, current_timeline="t-now") for entry in entries} == {LABEL_EARLIER_CREW}


# --- T3, T3b: the rule (D4, D5) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeline", "generation", "current", "expected"),
    [
        ("t-alpha", 3, "t-now", _generation_label(3)),
        ("t-alpha", 1, "", _generation_label(1)),
        ("t-alpha", None, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", 0, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", True, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", "2", "t-now", LABEL_EARLIER_CREW),
        ("t-now", 2, "t-now", LABEL_THIS_CREW),
        ("t-now", None, "t-now", LABEL_THIS_CREW),
        ("", None, "", LABEL_EARLIER_CREW),
    ],
    ids=["generation", "no-current", "unrecorded", "zero", "bool", "str", "this-crew-closed", "this-crew-open",
         "both-empty"],
)
def test_the_label_says_where_an_entry_came_from(timeline: str, generation: Any, current: str, expected: str) -> None:
    label = inheritance_label(_entry(timeline, generation), current_timeline=current)
    assert label == expected
    assert label.startswith("[") and label.endswith(_LABEL_ENDS)


def test_the_fixed_labels_read_as_decided() -> None:
    assert LABEL_THIS_CREW == "[Archived by this crew: a record, not a memory]"
    assert LABEL_EARLIER_CREW == "[Inherited from an earlier crew: not your own memory]"


# --- T4, T5, T5b: the one attachment point (D2, D5) -----------------------------------------------------------


async def test_the_oracle_puts_the_label_first_in_each_archive_result(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        results = await _oracle(store, "t-now").query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    assert sorted(result.metadata["timeline_id"] for result in results) == sorted(_TIMELINES)
    for result in results:
        timeline = result.metadata["timeline_id"]
        generation = _EXPECTED[timeline]
        label = _generation_label(generation) if generation else LABEL_EARLIER_CREW
        assert result.content.split("\n", 1)[0] == label
        assert result.content == f"{label}\n[convergence_report] {timeline}\n{_content(timeline)}"
        assert (result.source_tier, result.metadata["generation"], result.metadata["inherited"]) == (
            "archive", generation, True,
        )
        assert result.provenance == f"Archive/convergence_report (timeline {timeline[:8]}...)"


async def test_an_entry_this_crew_archived_is_its_own_record_never_inherited(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        attached = await _oracle(store, "t-alpha\n").query("coolant drift", tiers=["archive"])
        unattached = await _new_oracle(store).query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    labels = {r.metadata["timeline_id"]: (r.content.split("\n", 1)[0], r.metadata["inherited"]) for r in attached}
    assert labels == {
        "t-alpha": (LABEL_THIS_CREW, False),
        "t-beta": (_generation_label(2), True),
        "t-gamma": (_generation_label(3), True),
        "t-open": (LABEL_EARLIER_CREW, True),
    }
    # Until the runtime attaches the timeline nothing reads as this crew's own: the safe direction (D5).
    assert all(result.metadata["inherited"] is True for result in unattached)
    assert LABEL_THIS_CREW not in "".join(result.content for result in unattached)


@pytest.mark.parametrize("value", [None, 7, b"t-alpha"], ids=["none", "int", "bytes"])
def test_the_oracle_takes_its_timeline_only_as_text(value: Any) -> None:
    oracle = _new_oracle(None)
    with pytest.raises(TypeError):
        oracle.attach_current_timeline(value)


# --- T6, T7: every renderer an agent reads (§5) ---------------------------------------------------------------


async def _agent_text(oracle: OracleService, path: str, query: str) -> str:
    """The text an agent receives from the Oracle through ``path``, by the renderer that path uses."""
    if path == "query-formatted":  # the ORACLE recall tier and the oracle_lookup sub-task
        return await oracle.query_formatted(query, k_per_tier=3, max_chars=2000)
    if path == "oracle-tool":  # AD-1139
        return (await OracleQueryTool(oracle=oracle).invoke({"query": query, "kind": "archive"})).output
    if path == "memory-refs":  # AD-462f, the oracle_refs sub-task
        return OracleService.format_refs(await oracle.query_refs(query, k_per_tier=3))
    if path == "crew-consult":  # AD-1141
        consult = await oracle.query(query, k_per_tier=3, tiers=["archive"])
        return _render_commons_block(consult, max_chars=4000, max_entries=5, min_score=0.0)
    return LookupDispatcher._stringify(await oracle.query(query))  # AD-725: every tier, stringified


@pytest.mark.parametrize("path", ["query-formatted", "oracle-tool", "memory-refs", "crew-consult", "dm-lookup"])
async def test_every_path_from_the_archive_to_an_agent_carries_the_label_before_the_content(
    tmp_path: Path, path: str,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), path, "coolant drift")
    finally:
        await store.close()
    assert _every_entry_is_labelled_first(text) == 3
    for label in (_generation_label(1), _generation_label(2), LABEL_EARLIER_CREW):
        assert label in text


class _FarArchive:
    """An archive whose one entry has an id and a generation far beyond any live value: the widest label."""

    async def search(self, query: str, *, limit: int = 10) -> list[ArchiveEntry]:
        fields: dict[str, Any] = {
            "id": 10**12, "timeline_id": "t-far", "category": "convergence_report", "title": "x" * 200,
            "content": "y" * 2000, "author_agent_type": "", "author_callsign": "system",
            "archived_at": time.time(), "generation": 10**6,
        }
        return [ArchiveEntry(**fields)][:limit]


async def test_the_label_survives_the_tightest_cap_any_consumer_applies() -> None:
    refs_text = OracleService.format_refs(await _oracle(_FarArchive(), "t-now").query_refs("anything"))
    assert "[archive] archive:1000000000000 (score: 0.99) " in refs_text  # premise: the widest prefix
    assert "[Inherited from the crew of generation 1000000: not your own memory]" in refs_text


# --- T8: the real seam: two resets, then a later crew's Oracle and the text it hands an agent ------------------


async def _publish_second_finding(data_dir: Path) -> None:
    await _records(data_dir).write_entry(
        author="system", path=_SECOND_REPORT,
        content="## Convergence Report\n\nThe second watch traced the coolant drift to a cracked manifold.",
        message="AD-551: Convergence report (manifold)", classification="ship", tags=["convergence", "ad-551"],
    )


async def _third_crew_reads(tmp_path: Path, query: str) -> tuple[list[Any], str, str]:
    later = _store(tmp_path)  # the third crew's boot opens the archive the resets wrote
    await later.initialize()
    try:
        oracle = _oracle(later, _THIRD)
        results = await oracle.query(query, tiers=["archive"])
        tool = await _agent_text(oracle, "oracle-tool", query)
        formatted = await _agent_text(oracle, "query-formatted", query)
    finally:
        await later.close()
    return results, tool, formatted


@pytest.mark.parametrize("full", [False, True], ids=["default", "full"])
def test_after_two_resets_a_later_crew_reads_each_generations_knowledge_labelled_as_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool,
) -> None:
    data_dir = _data_dir(tmp_path)  # the first crew, under _SHIP
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    # The second crew boots under a new instance id, as the ontology loader writes it, and publishes a finding.
    (data_dir / "ontology").mkdir(parents=True, exist_ok=True)
    (data_dir / "ontology" / "instance_id").write_text(_SECOND, encoding="utf-8")
    asyncio.run(_publish_second_finding(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    results, tool, formatted = asyncio.run(_third_crew_reads(tmp_path, "coolant drift"))
    generations = {(result.metadata["timeline_id"], result.metadata["generation"]) for result in results}
    assert generations == {(_SHIP, 1), (_SECOND, 2)}
    for result in results:
        assert result.source_tier == "archive"
        assert result.content.split("\n", 1)[0] == _generation_label(result.metadata["generation"])
        assert result.metadata["inherited"] is True
    for text in (tool, formatted):
        assert _every_entry_is_labelled_first(text) == len(results)
        assert _generation_label(1) in text and _generation_label(2) in text
        assert LABEL_THIS_CREW not in text
    assert "cracked manifold" in tool  # premise: the second crew's finding reached the third crew


# --- T9: the runtime is the one caller ------------------------------------------------------------------------


def test_only_the_runtime_tells_the_oracle_its_timeline_and_it_reads_the_ontologys_instance_id() -> None:
    calls: list[tuple[str, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "attach_current_timeline"
            ):
                calls.append((path.relative_to(_SRC).as_posix(), ast.unparse(node)))
    assert calls == [(
        "runtime.py",
        "self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)",
    )]
```

## 8. Tracking (tracker pairs; M2's commit)

Written against `026a682f`; re-anchored by the orchestrator at build time on the post-BF-925 heads (this paragraph's own instruction). If another entry has merged first, re-anchor both pairs on the newest head line and the newest DECISIONS entry's last bullet and the heading after it, as S1's orchestrator did; change no wording. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title, the blank line and the bold lead of BF-919's head entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-925 (2026-10-25), #1655 -- silent-fallback guards name APIs that exist.**
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S2 (2026-10-26), #1569 slice 2 of 6 -- a later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory.** Every Ship's Archive read now fills `ArchiveEntry.generation`: the place of the entry's timeline's first close among the closes `generations` attributes to a timeline (a skip with no instance id numbers no crew; a second close does not renumber one). `inheritance_label` (in `knowledge/archive_store.py`) gives one of three labels: `[Inherited from the crew of generation N: not your own memory]`, `[Inherited from an earlier crew: not your own memory]` when no close is recorded, and `[Archived by this crew: a record, not a memory]` for the reading crew's own timeline. The Oracle's archive tier, the one path from the archive to an agent, makes the label the first line of every result and adds `generation` and `inherited` to its metadata, so `query_formatted`, the `oracle_query` tool, memory refs, the crew consult and the DM lookup all hand an agent the label before the knowledge. The runtime tells the Oracle this crew's timeline (the ontology's instance id) through `OracleService.attach_current_timeline`; until then, or if that fails, every entry reads as inherited. No flag, no schema change; the archive's contents, its score and the Oracle's tier order are unchanged. New: `tests/test_ad1341_s2_inherited_label.py` (the real store, Oracle, renderers and two real resets). The contract is `prompts/ad-1341-s2-inherited-label.md`.

**BF-925 (2026-10-25), #1655 -- silent-fallback guards name APIs that exist.**
```

**`DECISIONS.md`** (after BF-919's entry, anchored on its *Reversal* bullet, the blank line and the next heading; the docs-only commit adds a *Validation of record* bullet before AD-1341 S2's own *Reversal* line):

SEARCH:
```markdown
- *Reversal.* Revert the commits; the report, mention links, Chiefs' stats and window return to empty, and the guard test goes.

### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
```
REPLACE:
```markdown
- *Reversal.* Revert the commits; the report, mention links, Chiefs' stats and window return to empty, and the guard test goes.

### AD-1341 S2 -- A later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory (2026-10-26, #1569 slice 2 of 6)

- *Scope.* Slice 2 of #1569 (Decision item 5 and its acceptance line), one code commit and one tracker commit. Files: `knowledge/archive_store.py` (`ArchiveEntry.generation`, `inheritance_label`, the two labels, the generation order), `cognitive/oracle_service.py` (`_query_archive`, `attach_current_timeline`), `runtime.py` (one late bind) and a new test. Contract: `prompts/ad-1341-s2-inherited-label.md`.
- *D2 (where).* The rule and the data live in the store module; the label is attached once, in the Oracle's archive tier, the one path from the archive to an agent, as the first line of the result's content. Not in the store's content (it is what was archived and hashed), not in each renderer (a new renderer would be unlabelled), not in the provenance alone (two renderers never show it).
- *D3 (generation N).* The place of the timeline's first close among the distinct non-blank timelines in `generations`, by id. A blank-timeline skip numbers nothing; a re-close does not renumber; a skipped close still ended a crew. Numbering starts at the first close the archive recorded.
- *D4-D5 (the label).* Three fixed bracketed labels, each naming the origin first and then "not your own memory" (or "not a memory"); `generation` and `inherited` in the metadata. An entry of the reading crew's own timeline is "archived by this crew", never "inherited" (Westworld). Not attached, or failed, every entry reads as inherited: the error the minority-report principle tolerates. No callsign in the label, so a later crew member with an earlier crew's callsign never reads it as its own byline.
- *D6-D7.* No flag (its off position would present inherited knowledge unlabelled). The archive's score and the tier order are unchanged; the label, not the rank, keeps inherited knowledge from reading as one's own.
- *Disclosed effects.* Archive results open with the label line and carry two new metadata keys, also on the Captain's `GET /oracle`. One more small query per archive read. Vessels sharing one archive file share one generation count. AD-688's graph expansion tries up to six label words as tokens for an archive parent.
- *Reversal.* Revert the S2 commits. Nothing persisted changes: the archive and `generations` are read, never written, by this slice.

### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M2's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the gate:** add a *Validation of record* bullet before AD-1341 S2's *Reversal* line (the campaign of record, its base tree, the sha256 of each §10 file and of the new test file, and each row's first failing test), and the same as a closing §16 of this contract; then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there.

## 9. What this does NOT change

- The archive's schema, contents, writes, erasure and `generations` rows (S1); `promote_entry`, `record_generation`, `erase_entry` and their lock. No review queue or veto (S3), no exit notes or stand-down (S4), no continuous promotion (S5), no `--full` snapshot or clean slate (S6).
- The archive's score, its LIKE search, the Oracle's tier list, order, merge and `max_results`; the archive result's `provenance` and existing metadata keys; `_derive_ref_id`; `query_refs`' metadata whitelist.
- Every other tier's output, and the renderers themselves: `query_formatted`, `format_refs`, `ProvenanceEnvelope`, `OracleQueryTool`, `_render_commons_block`, `LookupDispatcher`, and the framing preambles in `cognitive_agent.py` and `sub_tasks/analyze.py`/`compose.py`.
- AD-607e's shard filter, the tool's sovereign-tier filter, BF-679's records reader rule.
- Ship's Records that survive tier 2 and reach a later crew through Tier 2 (RS2-6); episodic memory and its write path (RS2-2); the ontology and its instance id.
- `introspect`, the organizer and `/search`, which do not query the archive.

## 10. Mutation rows (17 rows; whole stripped lines, each occurring once in its file after §7)

Tier HIGH: every changed production file has rows. Run each row against `tests/test_ad1341_s2_inherited_label.py` on the contract-applied tree, after an unmutated baseline run that passes. Restore each file before the next row.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| S-K1 | `src/probos/knowledge/archive_store.py` | `"SELECT timeline_id FROM generations WHERE trim(timeline_id) != '' "` | `"SELECT timeline_id FROM generations "` | T1 (the blank-timeline skip numbers first, so alpha is 2). "A skip with no crew counts" |
| S-K2 | `src/probos/knowledge/archive_store.py` | `"GROUP BY timeline_id ORDER BY min(id)"` | `"GROUP BY timeline_id ORDER BY max(id)"` | T1 (alpha's re-close moves it after beta). "A re-close renumbers" |
| S-K3 | `src/probos/knowledge/archive_store.py` | `return {row[0]: number for number, row in enumerate(rows, start=1)}` | `return {row[0]: number for number, row in enumerate(rows, start=0)}` | T1 (alpha 0) |
| S-K4 | `src/probos/knowledge/archive_store.py` | `generation=generations.get(row[1]),` | `generation=None,` | T1 |
| S-K5 | `src/probos/knowledge/archive_store.py` | `if current_timeline and entry.timeline_id == current_timeline:` | `if entry.timeline_id == current_timeline:` | T3 `[both-empty]` |
| S-K6 | `src/probos/knowledge/archive_store.py` | `if current_timeline and entry.timeline_id == current_timeline:` (after S-K5 is restored) | `if False:` | T3 `[this-crew-closed]`; T5 |
| S-K7 | `src/probos/knowledge/archive_store.py` | `if type(entry.generation) is int and entry.generation >= 1:` | `if entry.generation:` | T3 `[bool]` and `[str]` |
| S-K8 | `src/probos/knowledge/archive_store.py` | `if type(entry.generation) is int and entry.generation >= 1:` (after S-K7 is restored) | `if type(entry.generation) is int and entry.generation >= 0:` | T3 `[zero]` |
| S-K9 | `src/probos/knowledge/archive_store.py` | `return f"[Inherited from the crew of generation {entry.generation}: not your own memory]"` | `return f"[From the crew of generation {entry.generation}]"` | T3 `[generation]`; T4 |
| S-K10 | `src/probos/knowledge/archive_store.py` | `LABEL_EARLIER_CREW = "[Inherited from an earlier crew: not your own memory]"` | `LABEL_EARLIER_CREW = "[From an earlier crew]"` | T3b |
| S-K11 | `src/probos/knowledge/archive_store.py` | `LABEL_THIS_CREW = "[Archived by this crew: a record, not a memory]"` | `LABEL_THIS_CREW = "[Your memory]"` | T3b |
| O-1 | `src/probos/cognitive/oracle_service.py` | `label = inheritance_label(entry, current_timeline=self._current_timeline)` | `label = ""` | T4 |
| O-2 | `src/probos/cognitive/oracle_service.py` | `content=f"{label}\n[{entry.category}] {entry.title}\n{entry.content}",` | `content=f"[{entry.category}] {entry.title}\n{entry.content}\n{label}",` | T4 (first line); T6 `[memory-refs]` (the cap drops a trailing label). "The label as prose at the end" |
| O-3 | `src/probos/cognitive/oracle_service.py` | `"inherited": label != LABEL_THIS_CREW,` | `"inherited": True,` | T5 |
| O-4 | `src/probos/cognitive/oracle_service.py` | `"generation": entry.generation,` | `"generation": None,` | T4 |
| O-5 | `src/probos/cognitive/oracle_service.py` | `self._current_timeline = timeline_id.strip()` | `self._current_timeline = ""` | T5 |
| R-1 | `src/probos/runtime.py` | `self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)` | `pass` | T9 |

`if type(timeline_id) is not str:` (oracle_service) has no row of its own: mutated to `if False:`, `None` and `7` raise `AttributeError` and `b"t-alpha"` is accepted, so T5b kills it; record it as row O-6 if the campaign has room.

## 11. Verified Against Codebase (2026-10-24, HEAD `026a682f`, tree `cad2c0ee25686a5683fd0ba3be35463796b5cf35`)

Read with the Grep and Read tools on this checkout (the bridge allows no `rg` pipelines).

```
src/probos/knowledge/archive_store.py
  13-15: "``generations`` records each crew generation's close ... promotion the Captain skipped and why."   (7.1 pair 1)
  43-61: class ArchiveEntry ... source_episode_ids: tuple[str, ...] = ()   (frozen dataclass; every field after metadata defaulted)
  64: #: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
  179-182: PROMOTED needs a timeline; SKIPPED needs a reason (a blank timeline is allowed)
  201-214: CREATE TABLE IF NOT EXISTS generations (id INTEGER PRIMARY KEY AUTOINCREMENT, timeline_id TEXT NOT NULL, ...)
  280: _SQLITE_MAX_ROWID = 2**63 - 1
  283: def _valid_reason(reason: object) -> str:
  312-317: "Reads and ``initialize`` take no lock ... No method holding the lock calls another store method"
  462-466: entry_by_id: cursor ...; row = await cursor.fetchone(); return self._row_to_entry(row) if row else None
  482-484: LIKE '%query%' on title or content
  497-500: cursor = await self._db.execute(sql, params); rows = ...; (blank); return [self._row_to_entry(row) for row in rows]
  507-512: get_recent: ... (limit,), ) rows = ...; return [self._row_to_entry(row) for row in rows]
  522-540: @staticmethod def _row_to_entry(row: Any) -> ArchiveEntry: return ArchiveEntry(id=row[0], ... author_did=row[13], source_episode_ids=...)
src/probos/cognitive/oracle_service.py
  21-22: from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684 / from probos.types import (  # AD-462f ...
  35-47: class OracleResult (source_tier, content, score, metadata, provenance, match_reason)
  162-177: BF-684: the axes' scores "were never calibrated against each other"
  264: _extract_entity_tokens stops at 16 tokens
  309-310: _derive_ref_id: tier == "archive": key = md.get("archive_id") ...
  371-372: self._reader_identity_resolver = reader_identity_resolver / self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
  422-436: def attach_reader_identity_resolver ... self._reader_identity_resolver = resolver / (blank) / def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
  631-637: Tier 4: if self._archive_store and "archive" in active_tiers: ... self._query_archive(query_text, k=k_per_tier)
  683-692: merge: sort by score; max_results = k_per_tier * len(active_tiers); AD-607e filter
  736-745: content_preview = r.content[:300]; line = f"{r.provenance} (score: ...)" ... f") {content_preview}"
  788-794: snippet = (r.content or "")[:_MEMORY_REF_SNIPPET_CHARS]; ref_metadata whitelist includes "archive_id"
  843-845: line = f"[{ref.tier}] {ref.ref_id} (score: {ref.score:.2f}) {ref.snippet}"; cap at _FORMAT_REFS_LINE_CHAR_CAP (120)
  876-878: AD-607e: non-episodic results pass through
  1134-1157: async def _query_archive ... content=f"[{entry.category}] {entry.title}\n{entry.content}" ... provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)"
  1145: source_tier="archive"   (the only one in src: Absence S2-AV2)
  1473-1474, 1525: expansion tokens from parent.content; provenance=f"[graph expansion: {parent.provenance}]"
src/probos/runtime.py
  3357: self.ontology = comm.ontology
  3364-3381: BF-679 attach block ending in the logger.warning(... exc_info=True, ) and a blank line
  3383: # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
src/probos/ontology/loader.py
  95-98: _load_or_generate_instance_id_sync: return id_file.read_text(encoding="utf-8").strip()
  143-150: self.vessel_identity = VesselIdentity(... instance_id=instance_id, ...)
src/probos/ontology/service.py
  86-92: def get_vessel_identity(self) -> VesselIdentity: (a default with instance_id="unknown" when none is loaded)
src/probos/startup/communication.py
  787-797: ontology = VesselOntologyService(ontology_dir, data_dir=data_dir); await ontology.initialize()
src/probos/startup/cognitive_services.py
  669-707: ArchiveStore built and initialised, then OracleService(..., archive_store=archive_store, ...) (before the ontology)
src/probos/__main__.py
  3185-3188: _read_instance_id: (data_dir / "ontology" / "instance_id").read_text(...).strip()
  3306-3312: promote_ship_records(...) then archive.record_generation(closed)
  3393: entry = await archive.entry_by_id(entry_id)   (the Captain's erase prompt)
src/probos/cognitive/provenance.py
  25-28: relevance, "not how strongly its author holds it"
  78-80: render(): f"{self.tag.format_inline()}\n{self.content}"
src/probos/tools/oracle_query_tool.py
  55-62: SIGMA_TIERS includes "archive"; 89-97: the disposition; 119-129: _cap_entry keeps the head; 172: __init__(self, *, oracle); 260-263: _render(envelopes) -> ToolResult(output=...)
src/probos/cognitive/crew_executor.py
  119: _MAX_ENTRY_CHARS = 400; 697-745: _render_commons_entry (740 collapses whitespace; 742-745 keeps the head); 748-754: _render_commons_block(results, *, max_chars, max_entries, min_score)
src/probos/cognitive/dm_targeted_lookup.py
  101: class LookupDispatcher; 203: res = oracle.query(query, agent_id=agent_id); 242-262: @staticmethod _stringify (repr for objects)
src/probos/cognitive/cognitive_agent.py
  10545-10552: "These are NOT your personal experiences ..."; 11579-11586: oracle.query_formatted(...) -> observation["_oracle_context"]
src/probos/cognitive/sub_tasks/query.py
  274-280: oracle.query_formatted(...); 346-362: oracle.query_refs(...); oracle.format_refs(refs)
src/probos/routers/system.py
  711-730: GET /oracle: oracle.query(...); {"source_tier", "content": r.content[:500], "score", "provenance", "metadata"}
tests/test_layer_boundaries.py
  51: "cognitive": {"knowledge", "substrate", "mesh"},
tests/test_ad1341_s1_archive_store.py
  77-90: def _plant_v0(path, *, extra_column=False) (timeline "timeline-zero", titles "Legacy one"/"Legacy two")
  242-252: the store's public surface (no new public method here: _generation_numbers is private; inheritance_label is module level)
tests/test_ad1341_s1_reset_and_erase.py
  49: _SHIP = "ship-did-alpha-0001"; 162: def _config; 169: def _data_dir; 181: def _records; 185: async def _write_records; 212: def _reset
  557-558: a second reset after writing the next instance id (the pattern T8 follows)
docs/research/metacognitive-architecture.md
  115-117: The Westworld Principle: "what they know (LLM + KnowledgeStore ≠ personal memory)"
```

## Absence Verified (2026-10-24)

**S2-AV1.** CLAIM: no `src` code other than `OracleService._query_archive` reads archive entries for anything an agent receives.
RUN: Grep `_archive_store\b|\.archive_store\b` in `src`; Grep `\barchive\.(search|get_recent|entry_by_id|count|promote_entry|erase_entry|record_generation|initialize|close)\(` in `src`.
FOUND: holders `runtime.py:586, 1345, 2971` (assignment), `startup/shutdown.py:2064-2074` (close only), `startup/cognitive_services.py:670-707` (construction), `startup/results.py:140` (field), `oracle_service.py:354, 632, 1138` (the one `search`); calls `__main__.py:3298-3314` (initialize, record_generation, close), `:3391-3407` (initialize, `entry_by_id`, `erase_entry`, close: the Captain's CLI), `knowledge/archive_promotion.py:163` (`promote_entry`).
HOLDS: yes. The CLI prints to the Captain, not to an agent.

**S2-AV2.** CLAIM: only `_query_archive` builds an archive-tier `OracleResult`.
RUN: Grep `source_tier="archive"` in `src`.
FOUND: `oracle_service.py:1145`.
HOLDS: yes.

**S2-AV3.** CLAIM: §5 lists every consumer of Oracle results in `src`.
RUN: Grep `\.query_formatted\(|oracle[a-z_]*\.query\(|\.query_refs\(|\.resolve_ref\(|format_refs\(`; Grep `query_with_provenance\(|_oracle_service\.|\.oracle\.|oracle_service\.query|\boracle\.query`; Grep `from_oracle_result|OracleResult\b` (outside `oracle_service.py`).
FOUND: `introspect.py:846`, `organizer_agents.py:151`, `cognitive_agent.py:11579, 11607` (the second is `tiers=["graph"]`), `crew_executor.py:1808`, `commands_knowledge.py:91`, `dm_targeted_lookup.py:203`, `provenance.py:108, 115` (for `oracle_query_tool.py:319`), `routers/system.py:724`, `sub_tasks/query.py:274, 346, 362`; `resolve_ref` has no caller outside its definition and a docstring (`types.py:630`); `runtime.py` calls only `attach_*`, `write_semantic` and `semantic_stats`.
HOLDS: yes.

**S2-AV4.** CLAIM: `ArchiveStore._row_to_entry` is called only by the store's three reads.
RUN: Grep `_row_to_entry` in `src` and `tests`.
FOUND: `archive_store.py:466, 500, 512` (and the definition at `:523`); `cognitive/skill_catalog.py:270, 848` is that class's own method; none in `tests`.
HOLDS: yes.

**S2-AV5.** CLAIM: `ArchiveEntry` is constructed only by keyword, so a defaulted field at the end breaks no caller.
RUN: Grep `ArchiveEntry\(` in `src` and `tests`.
FOUND: `archive_store.py:524` (keywords); `tests/test_ad524_ships_archive.py:130` (keywords).
HOLDS: yes.

**S2-AV6.** CLAIM: no existing test pins an archive result's first content line, its exact content, its metadata key set or its provenance text.
RUN: Grep `\.content ==|\.content\.startswith|\.metadata ==|content\.split\(|provenance ==` in `tests/test_ad524*.py`, `tests/test_ad1341*.py`, `tests/test_ad1139*.py`, `tests/test_ad1141*.py`, `tests/test_ad696*.py`; Grep `Archive/|_query_archive|archive_store=|tiers=\["archive` in `tests`.
FOUND: one unrelated hit (`test_ad1141_crew_loop_sigma.py:1078`, a publish refusal's metadata); the archive queries at `test_ad524_ships_archive.py:114-121, 142-147`, `test_ad1341_s1_archive_store.py:404-411`, `test_ad1341_s1_promotion.py:379-384`, `test_ad1341_s1_reset_and_erase.py:239, 612-615` assert substrings, the tier and existing metadata keys only.
HOLDS: yes.

**S2-AV7.** CLAIM: nothing in `src` imports `oracle_service` at module level, so the new module-level import of `knowledge.archive_store` cannot close an import cycle through it.
RUN: Grep `^from probos\.cognitive\.oracle_service|^import probos\.cognitive\.oracle_service` in `src`; Grep the imports of `knowledge/archive_store.py` (`:26-37`: stdlib and `probos.protocols`) and `protocols.py` (`:23` `probos.types`; the rest under `TYPE_CHECKING`, `:31`, `:51`).
FOUND: no module-level importer of `oracle_service`; `archive_store` imports nothing from `cognitive`.
HOLDS: yes. The `probos.knowledge` package `__init__` (`edges`, `backfill`, `store`, `rejection_cache`) is already imported at module level by other `cognitive` modules (`nl_graph_query.py:25`, `relationship_inference.py:25`).

## Not verified (the orchestrator verifies by running)

1. **The live archive** (`%LOCALAPPDATA%\ProbOS\archive\archive.db`, read-only, the vessel stays up): `PRAGMA user_version`, `SELECT count(*) FROM archive`, `SELECT id, timeline_id, outcome FROM generations ORDER BY id`. The bridge allows no `sqlite3`. With no rows, nothing an agent reads changes until the first promotion; with rows, the running crew sees labels after its next boot.
2. **The phantom precheck** on this contract: I traced its three regex patterns and the AST helper against every python block (§12) but could not run `pwsh` here.
3. **T8's wall time**: two real resets per case, as S1's R10 runs; expected a few seconds.
4. **Callsign reuse (RS2-3):** whether a later crew can carry an earlier crew's callsign (`naming.py:92`, `AgentNamingPolicy`, validates self-chosen callsigns). It does not affect this slice (the label names no callsign, D4 C), but it decides whether RS2-3 is a real defect.

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 1 (runtime attributes) | The only match is the file name `runtime.py` (the census test's expected path, and prose), which resolves `py`: it occurs as `py =` or `py:` across `src` (144 hits). No line accesses a runtime attribute |
| Pattern 2 (class attributes) | `OracleService.format_refs` and `OracleService._query_archive` exist; `LookupDispatcher._stringify` exists; enum members are upper case; no constant is a receiver (the label is an f-string, not a format call on a constant) |
| Pattern 3 (capitalised calls) | Every capitalised call in the contract is a ProbOS or stdlib class that exists: `ArchiveStore`, `OracleService`, `OracleQueryTool`, `ArchiveEntry`, `PromotionRecord`, `GenerationRecord`, `OracleResult`, `ToolResult`, `VesselIdentity`, `VesselOntologyService`, `TypeError`, `Path`. `_FarArchive` starts with an underscore. SQL functions are lower case (`trim`, `min`), and no upper-case SQL function call appears anywhere in the text |
| AST helper (kwargs, fields, methods) | `ArchiveEntry`, `PromotionRecord` and `GenerationRecord` are built from `**fields`, so `generation=` is never a literal keyword; 7.1 pairs 7 and 8 put `generation=` only in an unbalanced fragment. No `x = OracleService(...)` binding precedes `attach_current_timeline`: oracles come from the `_new_oracle` and `_oracle` helpers. `write_entry`'s keywords match S1's use (`test_ad1341_s1_reset_and_erase.py:188-192`) |
| Layer | `oracle_service.py` (cognitive) imports `knowledge.archive_store`, allowed (`test_layer_boundaries.py:51`) |
| Store registry, `.db` literals, config facade | no table, no `.db` literal, no config field |
| AD-1343 census, subprocess census | no new name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED`; no `.complete(`, `.finalize(` or `.report(`; no subprocess |
| BF-919 isolation | every archive in the new test is under `tmp_path` |
| Public surface (S1 A7) | `ArchiveStore` gains no public method (`_generation_numbers` is private) |
| Size | `archive_store.py` +45 lines; `oracle_service.py` +25; `runtime.py` +12; the new test about 340 |

## 13. Prior Art and Blind Spots

**Date used for overdue rows:** 2026-10-24. Interval for memory systems and research lines: 180 days.

**Internal work used:**
- S1 D9 (`generations` as the order S2 labels) and D3 (first-promoter attribution). Used as given.
- The Westworld Principle (`docs/research/metacognitive-architecture.md:115-125`): "don't hide the seams"; knowledge is not personal memory. Adopted as D5's truthfulness rule.
- The nature/culture/nurture amendment on #1569 (2026-10-16): culture is labelled as inherited from generation N. Implemented.
- AD-677 provenance envelopes, AD-1139's disposition, AD-1294's relevance-not-confidence: the label rides on these renderers, unchanged.
- BF-675 (an episode surfaced under the wrong tier label bypassed AD-607e): the same failure shape, so `source_tier` stays `archive`.
- BF-679's late bind (`attach_reader_identity_resolver`): adopted for `attach_current_timeline`, including its fail-safe direction.
- BF-684 (uncalibrated cross-tier scores): the reason D7 adds no discount.

**External prior art:**
- Spotlighting (Hines et al., Microsoft, arXiv 2403.14720): transforming an input gives the model "a reliable and continuous signal of its provenance". Adopted in its lightest form, a fixed in-band marker at the head of each entry; datamarking and encoding rejected (D4 D). <https://arxiv.org/abs/2403.14720v1>
- Source-monitoring framework (Johnson, Hashtroudi and Lindsay, *Psychological Bulletin* 114(1), 1993): source errors arise when activated information is ambiguous about its origin and attribution relies on heuristics. Adopted as the rationale for an explicit origin cue rather than leaving the reader to infer it. <https://www.doi.org/10.3758/BF03198562>, <https://pmc.ncbi.nlm.nih.gov/articles/PMC1692093>
- MemIR, "provenance-role collapse" (arXiv 2605.25869): flat-text memory induces source-monitoring errors; typed units fix it. Adapted: typed `generation`/`inherited` metadata beside the text; typed memory atoms rejected as out of scope. <https://arxiv.org/abs/2605.25869>
- Memory provenance laundering (arXiv 2607.29167): consolidation can rewrite an external observation as apparent user history, keeping its power and dropping its low-trust mark. Considered, deferred: the same path exists here (an agent repeats inherited knowledge, its episode records the repetition, and recall later returns it as `[episodic memory]`). Register RS2-2. <https://arxiv.org/abs/2607.29167>
- AI Meets Brain memory survey (arXiv 2512.23343; **overdue**, last reviewed 2026-04-12): examined at abstract level; its memory-security section adds nothing specific to inheritance labelling. Row update below. <https://arxiv.org/html/2512.23343v1>
- Memvid (**overdue** in the file, last reviewed 2026-04-05; S1 examined it on 2026-10-22 without updating the row): considered, deferred; S1 found nothing new and it has no labelling model.

**`docs/research/reference-projects.md` row updates** (this run edits only the contract; the orchestrator applies them): AI Meets Brain: *Last reviewed* 2026-10-24, *Where recorded* add "AD-1341 S2 (#1569) Prior Art, `prompts/ad-1341-s2-inherited-label.md` (abstract only; nothing on inheritance labelling)". Memvid: *Last reviewed* 2026-10-22, *Where recorded* add "AD-1341 S1 (#1569) Prior Art (append-only frames match the content-hash key; nothing new)".

**Blind spots found:**
1. An entry the reading crew archived itself (a reset refused after promotion committed; every entry once S5 lands). Fixed by D5.
2. A blank-timeline skip and a re-close of one timeline. Fixed by D3.
3. An empty `generations` table, or an AD-524 v0 row with no close. "Earlier crew" (T2).
4. Two renderers never show `provenance`. Fixed by D2 (content head).
5. Caps cut the tail of every entry. Fixed by placing the label first; the tightest cap is held by T7.
6. Vessels sharing one archive file share one generation count, and a ship's instance id changes every generation, so the archive cannot tell lineages apart. Disclosed effect 4; register RS2-1 (needs a lineage id that survives resets).
7. Provenance laundering through episodes (above). Register RS2-2.
8. A later crew member with an earlier crew member's callsign: BF-679's records reader rule (`author == callsign`) and AD-1294's byline would treat the earlier crew's surviving Ship's Records as that agent's own. Outside S2 (Tier 2, not the archive); the label names no callsign (D4 C). Register RS2-3, Not verified item 4.
9. Graph expansion reads label words as tokens. Disclosed effect 5; register RS2-4.
10. The archive's score is age decay, not relevance. Kept (D7); register RS2-5.
11. Ship's Records that survive tier 2 reach a later crew through Tier 2 as `[ship's records]`, unlabelled by generation, beside the same document labelled in Tier 4. Register RS2-6 (#1569's item 5 names the Oracle's archive tier; a records-tier label is a separate decision).
12. The label cannot stop a model from restating inherited knowledge as its own in its output; it is the strongest in-band cue available, beside the existing "not your personal experiences" framing.

## 14. Diff Reviewer: properties to verify

1. `_query_archive` is the only place in `src` that builds an archive-tier `OracleResult`, and every result it builds has `content` beginning with `inheritance_label(entry, current_timeline=self._current_timeline)` followed by a newline; nothing is placed before the label. List each renderer in §5 and confirm it keeps the head of `content` (or, for `format_refs`, the first 119 characters of the line) so the whole label reaches the agent.
2. `inheritance_label` returns exactly one of the three texts. `LABEL_THIS_CREW` only when `current_timeline` is non-empty and equals `entry.timeline_id`; the generation label only for an `int` (not `bool`) of at least 1; otherwise `LABEL_EARLIER_CREW`. Each label names the origin and says it is not the reader's memory.
3. `generation` is the 1-based place of the timeline's first close among distinct timelines with a non-blank `timeline_id`, ordered by that first close's id. A blank-timeline row numbers nothing; a second close does not renumber; `promoted` and `skipped` both count. All three reads (`search`, `get_recent`, `entry_by_id`) fill it; `count` is unchanged; no read takes `_write_lock`; no method holding the lock calls `_generation_numbers`.
4. The store's returned `content`, `title` and every existing field are what was archived; the label exists only in the Oracle's result. The archive file is never written by this slice.
5. `attach_current_timeline` raises `TypeError` for a non-`str` and stores the stripped value; `__init__` starts it at `""`. The runtime calls it once, after `self.ontology` is assigned, with `self.ontology.get_vessel_identity().instance_id`, inside a `try` whose `except` logs a warning and continues. Trace the failure and the not-yet-attached state: both make every entry read as inherited, never an inherited entry as this crew's.
6. The archive score, `provenance`, `source_tier`, the existing metadata keys, the tier list and order, the merge and `max_results` are byte-identical; the metadata gains exactly `generation` and `inherited`. No other tier's output changes.
7. No existing test is edited. T1 to T9 use the real store, Oracle and renderers; T8 runs the real `probos reset` twice and reads through the real tool and `query_formatted`; T9 is the only source census. Every test file archive lies under `tmp_path`.
8. `oracle_service.py` imports `probos.knowledge.archive_store` at module level and nothing in `src` imports `oracle_service` at module level (S2-AV7); confirm a fresh interpreter imports `probos.cognitive.oracle_service` and `probos.runtime` without a cycle.

## 15. Acceptance criteria

1. Each archived entry an Oracle query returns carries its crew's generation from `generations` (D3), with `None` when no close is recorded (T1, T2; S-K1 to S-K4).
2. A later crew's Oracle query returns an archived entry labelled as inherited from the earlier generation, never as its own memory; an entry its own crew archived is labelled as this crew's record (D4, D5; T3 to T5b; S-K5 to S-K11, O-1 to O-5).
3. Every path from the archive to an agent carries the label before the knowledge, under every cap (T6, T7; O-2).
4. After two real resets, a third crew's Oracle, its `oracle_query` tool and `query_formatted` give each generation's knowledge its own label (T8).
5. The runtime tells the Oracle this crew's timeline, once, from the ontology (T9; R-1).
6. Every test in §6 fails on the base, and every mutation row in §10 is killed by the named test. One broad gate and one PR for M1 and M2; a cross-family review of M1 (tier HIGH).
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
