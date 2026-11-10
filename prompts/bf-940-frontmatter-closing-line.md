# BF-940 (#1686): A document's frontmatter ends at the first later line made only of hyphens, so a frontmatter value holding "---" is no longer cut short (slice 1 of the issue)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out, preflight exit 2), 2026-11-09
**Status:** ready to build on `origin/main` `b82f96d9` (BF-943's merge, #1779; reading tree `D:\ProbOS-worktrees\bf940-build`; `HEAD` equals `origin/main`, status empty). **Oracle:** no pytest and no timing script (a read-only consult). An in-memory script applied the 21 pairs of M2, the marker pair and the 3 pairs of M3 to the LF blobs (each SEARCH once, every result parses), wrote the 3 new files, overlaid them on a copy of the tree in the OS temp folder (outside every repository) and drove the test functions by hand with a driver that calls each function with `tmp_path` and `monkeypatch`, not the pytest runner (section 11). On the head the 13 guards pass and the 20 class cases fail, each at an `assert` of its own body; on M2's head with A1 all 40 pass, the unit file's 22 pass, `test_bf952_records_keyword_search.py` goes from 80 cases to 76 and all pass, `test_records_store.py` (31), `test_ad550_notebook_dedup.py` (26), `test_ad1341_s4_lessons.py` (133), `test_ad1341_s4_stand_down.py` (67), `test_layer_boundaries.py` (3) and eight skill modules pass, each with the count it has on the head; the twelve mutants of section 9 and the ten of A1 (Q-1 to Q-10) fail the cases listed there. **Not run:** G1 to G3, the broad gate, the ledger generator, the census of 7.4 on a real tree, a timing run (L1, L7, L9).
**Base blobs (`b82f96d9`):** `records_store.py` `8c9e0f7d2d36d04afff38e2aa8fb8fea64bf0bc1`, `skill_catalog.py` `ae4ebcaad7223d706efea656bbd5f8a442a75027`, `lessons.py` `148c59574652cb8e3ad6136aa51be2233084528a`, `tests/test_bf952_records_keyword_search.py` `3c58724c32f405ac43b7e04590c5bdcefb10e1ed`, `tests/test_ad1341_s4_lessons.py` `4bf54dab3daebe9aa73c731609897a70ca1a60f1`, `tests/test_ad1341_s4_stand_down.py` `5454c540624c4df67ca8a063afd868b767b0eccc`, `docs/development/deterministic-ship.md` `ef04968585e386a85b3bc4d01cf8590ca9fac82d`, `PROGRESS.md` `c96539740dc4534afd3cc3fb0995d3b2069f919c`, `DECISIONS.md` `c81c82c276f9e952a9c52507a9f32330cfff1020`.
**Dependencies:** none (BF-952 and BF-943 are merged). **Tier:** M1 STANDARD (tests); M2 HIGH (it changes what every Ship's Records reader sees for a document, and the skill catalog's read and rewrite of SKILL.md); M3 STANDARD. **Estimated tests:** two new files (33 cases: 13 pass and 20 xfail at M1; 15 cases); `test_bf952_records_keyword_search.py` loses 4 cases and narrows one. **BF number:** BF-940, held by #1686 (open, `bug`); nothing new is allocated (section 11).
**What this contract closes of #1686:** the framing (L25), the opener with no closing marker (L18) and the skill catalog's three splits (L20). **The issue keeps** the parse-failure policy (L19), Python-tagged YAML (L24), the numeric tag (L27) and the route's serialization (F7-1), and stays open: the pull request says `Refs #1686`, not `Closes` (D0).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` for the nine paths prints the blobs above, `git diff --stat b82f96d9 HEAD -- src/probos/knowledge src/probos/cognitive/skill_catalog.py src/probos/utils tests/test_bf952_records_keyword_search.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s4_stand_down.py docs/development/deterministic-ship.md PROGRESS.md DECISIONS.md` is empty, and neither new test file nor `src/probos/utils/frontmatter.py` exists. If one fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The framing.** Five places frame a document with `split("---", 2)` or its copy: `RecordsStore._parse_document` (`records_store.py:1712-1722`, split at `:1715`); its copy for the search, `_split_document` (`:264-277`, split at `:274`; BF-952 A6: "the base's split, copied"); and the skill catalog's `parse_skill_file` (`skill_catalog.py:92`, split `:105`), `get_skill_body` (`:169`, `:179`) and `_rewrite_frontmatter` (`:784`, split `:790`, write `:814`). The second `---` anywhere ends the frontmatter, inside a value too. Every other `---` framing in `src` is a different format (section 11).
2. **The readers.** `_parse_document` has nine call sites, all in `records_store.py`: update-in-place `:724`, the similarity check `:1067`, `:1140`, `:1158`, the convergence scan `:1248`, `:1269`, `read_entry` `:1408`, `list_entries` `:1473`, `publish` `:1533`. The search reaches the copy through `_search_read_document` (`:330`, called at `:430`). Fifteen other files call the store's `read_entry`, `list_entries` or `search` and take what those return: the semantic backfill (`semantic.py:708`, `:738`), `routers/records.py`, `proactive.py`, `oracle_service.py`, `archive_promotion.py` and `stand_down.py` among them.
3. **What the cut does,** run on the base over a temporary store with `~` moved, and on a SKILL.md in the same way (section 11):

| Caller | On the base | After M2 |
|---|---|---|
| `read_entry`, `list_entries`, search | A private note whose author is `Ezri---Prime` reads as `{author: "Ezri"}`: its classification was after the cut, so another reader was shown it (measured through `read_entry`; `list_entries` and the search take the same parse). A value whose cut prefix is a bad timestamp (`2026-13-05---nominal`) makes `read_entry` raise `ValueError` and `list_entries` omit the record | read whole; private |
| update-in-place `:724` | `created` and `revision` lost (`revision` read `None` after a second write) | carried forward |
| `publish` `:1533` | A Captain's `publish` rewrote the file with `author`, `status` and `updated` only; `classification`, `topic` and `created` now stood at the head of the body | the whole frontmatter rewritten |
| similarity, convergence | compare a body that begins with the rest of the frontmatter; `department` and `topic` may be lost | the body is the body |
| semantic backfill `semantic.py:738` | indexes what `read_entry` returned (classification `ship`; author or tags cut) | whole (L4) |
| skill catalog | a plain description is cut (`'Use when a task needs it'`, `license` lost); a quoted one makes `parse_skill_file` return None (`Invalid YAML`); `get_skill_body` starts inside the frontmatter; `enrich_skill`'s rewrite wrote the cut frontmatter and then `--- or a peer asks` and the old `license` line: the file is corrupted | read whole; rewritten whole |

4. **Why a store-written document has two delimiter lines.** `write_entry`, `publish` and `append_captains_log` write `---\n{yaml.dump(...)}---\n\n{body}` (`:760`, `:1542`, `:884`), and `yaml.dump` indents the continuation lines of a value, so it wrote no line of only hyphens inside a frontmatter in 300,000 random frontmatters and 88 targeted values (a probe outside the repository; section 11). T2 pins it through the real store for 36 values. A rule that ends the frontmatter at the first later delimiter line therefore reads every store-written document whole.
5. **Reach.** Any writer that puts `---` in an author, topic, tag, department or envelope value. Latent on the vessel when the issue was filed (its own census; see the issue); this contract repeats no census (L1), and 7.4 is the one to run.

## 2. Solution

New `utils/frontmatter.py`: `split_frontmatter(text) -> (block | None, rest)`, framing only. A text has frontmatter when it begins with `---`; the block ends at the first later line of only hyphens (three or more, trailing blanks allowed); a text with no such line is framed as the base framed it (the first later `---` wherever it stands, and none when there is none). `RecordsStore._parse_document`, `_search_read_document` (its `_split_document` copy is deleted), `parse_skill_file`, `get_skill_body` and `_rewrite_frontmatter` call it and load the YAML in their own frames, so PyYAML's recursion frontier is where BF-952 pinned it. Comments that said the store cuts a value at `---` are corrected. `is_exit_note_text`, L19 (but for A1's one read-side fallback, D7), L24, L27 and F7-1 are untouched.

## 3. Decisions

**D0. Scope** (ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; Delegated AD Execution Mode: the top is taken).

| # | Option | Judgement |
|---|---|---|
| 1 | The rule, L18 and the skill catalog's three splits (L20) here; L19, L24, L27 and F7-1 a second slice of #1686 (chosen) | One rule at every split in `src` (the copy of the split is how L25 reached the search, A6). The skill catalog's rewrite corrupts a SKILL.md on the same shape (measured), so leaving it leaves a data-loss path. Its call sites (P2-7 to P2-11) and cases (T4, T10, T11) are separable: dropping them is option 2 |
| 2 | The rule and L18 alone; L20 in the second slice | The smallest review; leaves the corrupting rewrite for another round. L18 cannot be left out: the function must say what a text with no closing line reads as |
| 3 | Everything in one contract | Four risk classes in one review: a read-side reframe (compatibility), write-side refusals (L24, L27: new errors for callers), a policy for nine callers and the backfill (L19: a visibility decision) and a route boundary (F7-1). BF-952 took seven review rounds on two of them |

What each box of #1686 shares with the parser, and where it goes:

| Box | Shares the parser's code or tests? | This contract |
|---|---|---|
| Framing of a value holding `---` (L25) | is the parser; T5 to T9 | **closed** (M2) |
| An opener with no closing marker (L18) | the no-closing-line branch of the same function; rows of T3 and U1 | **closed by decision**: read as the base read it, pinned (D1, L2); the Captain-only option is ranked below it |
| The skill catalog's three splits (L20) | the same function, three call sites; its own module and callers; 27 test files reach it | **closed** (P2-7 to P2-11; T4, T10, T11) |
| A frontmatter that does not parse (L19) | `_parse_document`'s `except yaml.YAMLError` (unchanged); the policy is per caller | **kept** by the issue (D3) |
| Python-tagged YAML from `write_entry` (L24) | `write_entry`'s `yaml.dump`; no parser code | **kept** (D3) |
| A numeric tag never reaches the semantic index (L27) | `semantic.py:406` and `write_entry`; no parser code; the issue ties it to L24's policy | **kept** (D3) |
| The records route returns 500 for a deeply nested record (F7-1) | `routers/records.py:87-102`; no parser code | **kept** (D3) |

#1686 closes only when every box is built or shown invalid with evidence. Three are built or decided here; four are not, and stay in slices of the same issue. The pull request says `Refs #1686`, M3's commit body ends `Refs #1686.`, and nothing is moved to another issue.

**D1. The delimiter rule.** What each option does to each shape (the options are the issue's (a), (b) and (c), with (a) in two forms; the shapes were run through the base, both forms of (a) and a prototype of (c) outside the repository):

| Shape | Base | (a') chosen: first later line of only hyphens; none, or a block that does not load where the base's cut does: as the base (A1) | (a) the same, none: no frontmatter | (b) writer refuses or escapes `---` | (c) YAML's own document stream |
|---|---|---|---|---|---|
| A `---` inside a value, a closing line follows | cut there | whole | whole | cut (reads unchanged) | whole |
| Closing line `---` (the store shape) | ends there | same | same | same | same |
| Closing line `----` | ends; body starts with `-` | ends; clean body | as (a') | as base | error: not a marker |
| `---` plus trailing blanks | ends | same | same | same | same |
| CRLF (`read_text` turns a file's CRLF into LF first, L6) | ends | same | same | same | same |
| A BOM before the opener | no frontmatter | same | same | same | same |
| Empty frontmatter | `{}` | same | same | same | `{}` |
| A body holding `---` rules | kept | kept | kept | kept | kept |
| `---` ends the text | ends | same | same | same | same |
| Opener, no later `---` (L18) | none; the text is the body | same | same | same | scans the body as YAML: error |
| Opener, a `---` only inside a line, no closing line | ends at it | as the base | none: a private note reads as unclassified | as base | error |
| Hand-made: a `---` inside a line, then a later closing line, and the whole block loads | ends at the inline one | ends at the closing line (L3) | same | as base | the closing line |
| A `---` inside a line, then a later closing line, and the whole block does not load (a Python tag after the `---`, F1; prose after a key) | ends at the inline one; the cut loads: a private note stays private | reads as the base read it (A1) | `{}`: `ship`, shown to every reader (M2's F1) | as base | error |

Every `_parse_document` site and the search take the one function, so each reads these shapes alike (T9 runs both readers over BF-952's 3,747 shapes). Against the base, (a') frames 2,388 of them otherwise and no other (confinement, T9's premise), and returns a different reading, both readers, an error compared by its name, for 2,110 of those (T9 asserts both numbers; the other 278 read as the base reads them, 90 of them by A1's fallback); (a) returns a different reading for 2,884 of the 3,747, the shapes with no closing line included; (b) changes no reader; (c) turns three of these shapes, and an opener with text, into errors.

| # | Option | Judgement |
|---|---|---|
| 1 | (a') (chosen) | The change is confined to documents that have a closing line after an earlier `---`. A text with no closing line reads as before, so BF-952's first round-2 case (a hand-made `classification: private --- inline` note) stays private, which BF-952 A1 broke and A3 withdrew. Costs a second branch, pinned by T3 and U1 (L18 is answered by it), and a third for a block that does not load (A1, D7) |
| 2 | (a) the issue's rule, no fallback | Simplest to say; turns that note from private to readable by every reader (an unrecognised classification is level 0 and not identity-gated, `record_is_readable`), BF-952's RK9 and RK10 |
| 3 | (c) YAML's stream | Cannot tell where YAML ends and Markdown begins when the closing marker is missing; rejects `----`; adds a YAML scan to every document of the search's walk; changes every reader's recursion frontier |
| 4 | (b) writer-side | Leaves every stored and hand-edited document misread, those this defect already damaged included; refuses ordinary values (a topic `Review --- nominal`). AD-1341 S4 took it for exit notes, where the writer is the only source |

The first line is the opener as on the base (`startswith("---")`), so a first line holding more than hyphens (`--- x`) frames as before. python-frontmatter, the issue's reference for (a), is not installed and was not read: the rule here is this contract's own.

**D2. One function, one place.**

| # | Option | Judgement |
|---|---|---|
| 1 | `probos/utils/frontmatter.py`, `split_frontmatter(text) -> tuple[str | None, str]`: the block, and the text after its closing hyphens, not stripped; framing only (chosen) | `utils` is the layer any layer may import and that imports nothing (`tests/test_layer_boundaries.py:42` `UNIVERSALLY_IMPORTABLE_LAYERS`, `:55` `utils: set()`; `_get_imported_layer` returns None for it), with precedent (`agents/utility/web_agents.py:26`, `cognitive/causal_reasoning.py:32`); `utils/__init__.py` imports nothing. The fitness check ranks only substrate, mesh, consensus, cognitive and experience (`check_architecture_principles.py:80-84`; baseline `layers`), so `knowledge` and `utils` are neither source nor target there; `--check` run: exit 0, `layer-import=0`. No allowlist row, no cycle. The load stays in each caller's frame (T-frontier of BF-952 stays valid) |
| 2 | `knowledge/frontmatter.py` | Allowed (`cognitive` may import `knowledge`, `:51`), but `knowledge/__init__.py` imports five modules and the catalog imports nothing of ProbOS at module scope; a skill file's format is not a knowledge concern |
| 3 | Keep it in `records_store.py`; the catalog imports it | The catalog would import a module that imports `cognitive.provenance` (an allowlisted exception, `:92`): a cycle risk and a heavy import |
| 4 | Two copies kept in step | How L25 reached the search |

**D3. The parse-failure policy and the writer-side items** (what is in, with the function and the test each is coupled to).

| Item | In? | Coupling | Ranked options for its slice |
|---|---|---|---|
| L19: a frontmatter that does not parse reads `{}` | out | `_parse_document`'s `except yaml.YAMLError: fm = {}` (unchanged); nine callers, each rewriting or indexing differently (a Captain's `publish` writes `status` and `updated` only; update-in-place restarts `revision`; the backfill indexes at `ship`). Acceptance: T17 as at `cf61c683` (`test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone`, absent at HEAD). After this contract a store-written quoted value holding `---` and `: ` parses (T5, `a-quoted-topic-holding-a-key`), which is why RK10 was withdrawn; a hand-made unparseable record is L19's | carry the failure across `read_entry` as a typed result so each caller decides; then Captain-only for every reader (T17); a sentinel (rewritten as `{}` by `publish`, BF-952 A2) |
| L24: `!!python/` tags | out | `write_entry`'s `yaml.dump` (`:759`); AD-1140's fail-fast tier; tests of `write_entry` | reject before writing; normalize |
| L27: `tags: [717]` | out | `semantic.py:406`'s `', '.join(tags)`; the issue ties it to L24's policy | the same slice as L24 |
| F7-1: 500 for a deeply nested record | out | `routers/records.py:87-102` (serialization after the `try`); a route test | contain the refusal at the boundary |

**D4. The census** ("a documents-parse comparison over a copy of a real Ship's Records tree"). I have no live system, so 7.4 is a script for the orchestrator to run on a read-only copy of the vessel's `ship-records`, the path taken from the live process (`%LOCALAPPDATA%\ProbOS\data`, never `d:\ProbOS\data`).

| # | Option | Judgement |
|---|---|---|
| 1 | One script: the shipped `split_frontmatter` against the base's split embedded verbatim, each file read the way `read_text` hands it to the readers, every difference listed with a class, and a positive control run through the same `census` function (chosen) | Reads only; no store instance (`initialize` runs `git init`); the control cannot pass unless the comparison sees a difference |
| 2 | Drive `RecordsStore` over the copy | `initialize()` writes into the repository directory |
| 3 | Count files holding `---` | Does not compare readings |

What a difference means (7.4 prints the class): **D1**, a `---` inside a line before the first closing line, the defect's own shape (the classification column shows `(absent) -> private` for a private record the base read as unclassified); **D2**, a closing line of four or more hyphens, body only; **D3**, anything else: stop and return to the Architect. A hand-made document of L3's shape is D1 with a classification that changes. No difference on a tree means the change is inert on it. The counts of openers with no closing line (L18), Python tags (L24) and non-text tags (L27) are for the second slice.

**D5. Tests.** The real `RecordsStore` and skill functions over `tmp_path` with `~` moved (chosen): a control round (T1) and a premise (T2) before the class; a value holding `---` at each position through `write_entry`, `read_entry`, `list_entries`, search, update-in-place and `publish` (T5); every closing-line form (T6, T7); BF-952's T22 over its 3,747 shapes against an independent oracle (T9); the guards named in section 6; a unit file for the function (U1, U2). Rejected: a source-text test (it cannot tell a required line from the shipped one, BF-720); reader mocks.

**D6. Trackers, documents and `is_exit_note_text`.** PROGRESS.md, DECISIONS.md (after BF-943's entry) and the regenerated ledger (G3), as BF-943's M3; the roadmap is not edited (`git grep BF-940 -- docs/development/roadmap.md` finds nothing). Documents that state the delimiter, by `git grep -n -E "frontmatter" -- docs src` narrowed to those naming `---`: `docs/development/deterministic-ship.md:49` (P3-3); `records_store.py:267-270` (deleted with `_split_document`), `:670-672` (P2-5); `lessons.py:85-87`, `:225`, `:229` (P2-12 to P2-14); the two AD-1341 S4 test comments (P2-20, P2-21). Left as they are, with the reason: `records_store.py:1573` states L19's policy, which still holds; `skill_catalog.py:100` ("between --- delimiters") is true; `config/ontology/records.yaml:80` and `docs/architecture/memory.md:127` state no delimiter; BF-952's contract and DECISIONS RK9, RK10 and RK15 are history. **`is_exit_note_text` keeps refusing `---`** (AD-1341 S4's decision; its P4 test and `stand_down` cases pin it). Ranked: keep it > relax it now (a decision for that rule's owner, with its own tests) > delete it. Only its comments change.

**D7. Review round 1 (A1): F1's repair, case B, L3 and F4** (decided by the Architect under Delegated AD Execution Mode; ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the top is taken).

**F1 (P1, a regression of M2).** `write_notebook("alice", "review---nominal", body, metrics={"sample": (1, 2)})` writes a private note whose topic holds `---` and whose `metrics` hold `!!python/tuple`, a tag `safe_load` refuses. The base cut the block at the topic's `---`, after `classification`, so the tag was never loaded and the note stayed alice's. The rule reads the whole block, so `_parse_document` returned `{}`, which is classified `ship`: every reader was shown the note, and alice's own `publish` raised `PermissionError`. Measured through the real store, `~` moved:

| Case | Base | M2 | With A1 |
|---|---|---|---|
| A: topic holds `---`, tuple metric | private; bob none; publish ok | `{}`; bob reads it; `PermissionError` | private; bob none; publish ok |
| B: no `---`, tuple metric (L10) | `{}`; bob reads it; `PermissionError` | the same | the same |
| C: topic holds `---`, list metric | private; bob none; publish ok (metrics cut) | the same (metrics kept) | the same |

| Rank | Option (the review request's number) | Judgement |
|---|---|---|
| 1 | (1) A read-side fallback: a block that reads as nothing is read as the base read the text, where the base's cut reads as something (chosen) | Gives the base's reading back to exactly the documents M2 regressed and changes no other (on BF-952's 3,747 shapes it moves 90 back and no other); no writer, schema or visibility policy changes; reversible by deleting the branch. Cost: one decision made in three readers, each loading in its own frame so the recursion frontier stays (`_parse_document`, `_search_read_document`, and `_base_reading_admits`, which must apply it or the search shows a reader what `read_entry` withholds: T14); for a block that reads as nothing only, one more split and one more load (not timed). Pinned by T12 to T14, U3, U4 |
| 2 | (3) Both: 1 and `yaml.safe_dump` in the three writers | The writer half stops new Python-tagged documents but changes what every `write_entry` caller may pass (an object raises `RepresenterError`, a tuple becomes a list): L24's slice, with its own callers and tests; it adds nothing to F1 for the documents already on disk |
| 3 | (2) `yaml.safe_dump` alone | Fixes future writes only; leaves the regression and every stored document as they are |
| 4 | (5) Fail closed on a parse failure (L19) | Fixes case B too, but it is L19's visibility policy for nine callers and the backfill (D3), and an author's own note that does not parse becomes unreadable to its author |
| 5 | (4) Monotone-restrictive reconciliation | BF-952 A1 and A2's family, withdrawn in A3 for misreading others: it reads a document at a classification nobody wrote and cannot order two authors (T8's fourth shape) |

**The rule (A1).** Where the rule's block reads as nothing (`safe_load` returns a falsy value or raises `YAMLError`, the base's own catch) and the base's cut of the same text (`base_split_frontmatter`) loads to something, the text reads as the base read it: the cut's frontmatter, and the text after the second `---`, stripped. A cut that loads to a list or a scalar is taken too, as the base took it (the search then withholds it: a mapping is required). A constructor error or a `RecursionError` is not a parse failure and propagates, as on the base (L13). `_base_reading_admits` holds only the block, and takes the cut as the block up to its first `---`, which is `base_split_frontmatter`'s block for every text the rule framed (U4).

**Case B (pre-existing, L10).** A private document that holds a Python-tagged value and no `---` before it reads `{}` for every reader, on the base and after this contract: shown to everyone, and its author's `publish` raises `PermissionError`. The issue's L24 box says only "reads as `{}`"; it is a privacy defect. Decided: it stays the issue's L24 box, not a new issue (the filing policy's first clause would allow one for a reproducible security defect, but #1686's open checklist already holds this defect as its L24 box), retitled "privacy defect (P1)" with the table above, and slice 2 starts with L24, then L19. Exposure: crew to crew inside one vessel, from a writer that passes a tuple or an object; no payload read so far holds one (L16).

**L3 and the Captain-only boundary.** Classified: not Captain-only. The envelope asks that a decision preserve or strengthen privacy controls; the controls here are `record_is_readable`, the classification vocabulary and the writers, and A1 changes none of them. What changes is how a hand-made document's own YAML is read: after A1 T8's second shape (prose after a key) reads as the base read it, and shapes 1, 3 and 4 read what the YAML says (an unrecognised or repeated classification, level 0 and not identity-gated, or another author). The base's private reading of them came from cutting a value in the middle, the defect itself (RK15: BF-940 designs the framing). Reframing check, as the standing order asks: the requirement protects a private note's classification from other readers on the vessel; after the existing controls, the three document writers write a closing line and a mapping that loads back whole (T2; a Python-tagged value is case B, L10), and no production writer makes these shapes, a raw-file writer already controls the text and can write `classification: ship` outright, and a writer-made note is better protected than on M2. Ranked, if the Captain overrules: 1, as built (chosen); 2, a classification floor (read the stricter classification of the two framings), which is BF-952 A2's family, a hybrid reading nobody wrote and no answer for shape 4's author. Guard: 7.4's census is a hard stop for it: a document that moves from a gated classification to a non-gated one goes to the Captain before the merge.

**F2, F3, F4.** F2 (P2): T20's real-search assertions are restored in T8, for alice and bob. F3 (P3): "changes the reading of 2,388" counted framings; the rule frames 2,388 of BF-952's 3,747 shapes otherwise than the base and, with A1, returns a different reading for 2,110 (2,200 before A1; the strict rule, 2,884); T9 asserts both numbers. F4 (P3, pre-existing, equal on both trees): `_rewrite_frontmatter` does not keep the body's line endings (`read_text` turns CRLF into LF, `write_text` turns LF into CRLF on Windows). Not fixed here: no content is lost, and the natural fix replaces the `.write_text` call that the AD-1344 and AD-1346 write inventories key on (`(file, scope, call)`), a governance edit outside this issue; recorded as L15 and as an item of the issue's follow-up. This contract says "the text after the closing hyphens", not bytes.

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-21, then N2-1 and N2-2 (the marker) | G2 |
| M3 | P3-1 to P3-3, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf940_frontmatter_framing.py -q -n 0 -p no:randomly`. **Expected: 13 passed** (T1 to T4), **20 xfailed** (T5 to T11). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `$f = git grep -l -E '_parse_document|_split_document|_search_read_document|parse_skill_file|get_skill_body|_rewrite_frontmatter\(|enrich_skill|import_skill\(|SKILL\.md|Chapel---Two|normal---value' -- 'tests/test_*.py'` (33 files on the head: the three files naming the readers, the skill files, the two AD-1341 S4 files); then `PY -m pytest $f tests/test_bf940_frontmatter_framing.py tests/test_bf940_split_frontmatter.py tests/test_layer_boundaries.py tests/test_ad1346_admission_file_write_census.py -q -n 0 -p no:randomly`. (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new files 40 and 22 passed; `test_bf952_records_keyword_search.py` 76 collected (M0's less 4) and 0 failed; every other file 0 failed with collected counts equal to M0; the check clean (exit 0 on the head: `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`).
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Census (not a Builder step).** Run 7.4 on the vessel's copy before the pull request merges; a difference of class D3, or any D1 outside L3's shape, goes back to the Architect; a D1 document whose classification moves from a gated level to a non-gated one (L3) goes to the Captain before the merge.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new files at G2, or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-940 M1: tests for a frontmatter value holding "---" read whole by the store and the skill catalog, xfail until built (#1686)`
- **M2:** `BF-940 M2: a document's frontmatter ends at the first later line made only of hyphens, in the store and the skill catalog (#1686)`
- **M3:** `BF-940 M3: trackers, ledger and the invariants document (#1686)`; its body ends with the line `Refs #1686.`

## 6. Tests

`tests/test_bf940_frontmatter_framing.py` (M1; the functions pass on both trees, the class is xfail until M2) and `tests/test_bf940_split_frontmatter.py` (M2). Function names in full are in 7.1 and 7.2.

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 2 | Control of T5: the same record chain with values holding no `---`, and with a body holding a rule (`test_a_record_the_rule_does_not_reframe_goes_through_the_same_round_trip`) | none |
| T2 | 1 | Premise: `yaml.dump` through `write_entry` writes only its two delimiter lines for 12 hostile values as author, topic and tag (`test_the_writer_puts_no_line_of_only_hyphens_inside_the_frontmatter`) | none |
| T3 | 9 | Guards: store shape, CRLF, trailing blanks, the closing line ending the text, a body holding rules, a BOM, an opener with no later hyphens (L18), a `---` inside a line with no closing line (L2), frontmatter that does not parse (L19), through `_parse_document` and the search's reader (`test_a_document_the_rule_does_not_reframe_reads_as_before`) | none |
| T4 | 1 | Guard: a SKILL.md with a body holding rules reads and rewrites as before | none |
| T5 | 8 | Class: a value holding `---` as the first key, a trailing `---`, a quoted topic holding a key (T17's premise), a multi-line topic, a tag, the last key, a topic holding `---` with list metrics (F1's safe twin, A1), a bad-timestamp prefix, each through write, read, list, search, update-in-place and `publish`; BF-952's T16 is its first four | M2 |
| T6 | 5 | Class: each closing line (`---`, `----`, `---  `, CRLF, at the end of the text) after a value holding `---` | M2 |
| T7 | 1 | Class: a four-hyphen closing line leaves nothing of itself in the body | M2 |
| T8 | 4 | Class: the four hand-made shapes BF-952's T20 and round 3 held with a closing line after an inline marker, at their new readings and readers (L3; the second reads as the base read it, A1), each through `_parse_document`, `read_entry` and the search for alice and bob (F2) | M2 |
| T9 | 1 | Class: BF-952's T22 over 3,747 shapes, both readers against an independent oracle that includes A1's fallback; premise: 2,388 shapes are reframed; claim, asserted last: 2,110 are returned otherwise than the base returns them (F3) | M2 |
| T10 | 1 | Class: a SKILL.md whose description holds `---`: entry, body, rewrite | M2 |
| T11 | 1 | Class: a SKILL.md whose quoted description holds `---` and `: ` parses | M2 |
| T12 | 1 | Guard (A1, F1): a private note whose topic holds `---` and whose metrics hold a tuple stays private through `read_entry`, the search and `publish`; passes on the base, fails on the candidate before A1 | none |
| T13 | 4 | Class (A1): a block that does not load reads as the base read the text where the cut loads: F1's note as a document; a cut that is a list; a cut that does not load either; a constructor error, which is not a parse failure (L13). The first two rows pass on the base | M2 |
| T14 | 1 | Guard (A1): where libyaml reads the whole block and PyYAML does not (RK8), the search shows a reader no note that `read_entry` withholds from them, because its second reading applies the fallback; passes on the base, fails on the candidate before A1 | none |
| U1 | 14 | The function, row by row: `(block, rest)` for each shape of D1 | none (M2 file) |
| U2 | 1 | 4,000 random documents against a loop over the lines | none (M2 file) |
| U3 | 6 | The base's framing, `base_split_frontmatter`, row by row | none (M2 file) |
| U4 | 1 | 4,000 random documents: wherever the rule frames a block the base frames one, and it is the rule's block up to its first `---` (the search's second reading relies on it) | none (M2 file) |

**How each xfail case fails on the base.** T5's first four at the assert that `read_entry` returns `classification == "private"` and the author (it returns the cut frontmatter); `a-tag-...` and `the-last-key-...` at the assert that each value reads back whole; the bad-timestamp case at the `AssertionError` raised from `ValueError` out of `read_entry`. T6 and T7 at their one `assert` on `_parse_document`; T8 at the assert on `_parse_document`; T9 at `assert differ == []`; T10 at the assert that the description reads whole; T11 at the assert that the entry exists. Each passes its premise assert first (the control round T1, the two-delimiter premise inside the chain, T9's grid premise). A1's: T5's list-metrics case fails at the assert that `metrics` reads back whole, T13's last two rows at the assert on `_parse_document` (its first two rows say "as the base read it" and pass), and T9's claim of 2,110 is asserted after the oracle comparison. **Guards that pass on both trees:** T1 to T4, and A1's T12 and T14 (they fail on the candidate before A1: F1); on the unfixed base 18 of N1-1's 40 cases pass (the 15 guards, T8's second shape, T13's first two rows) and 22 fail. T3 asserts, before each case, that the rule does not reframe it (`reframed`, an independent line loop).

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf940_frontmatter_framing.py`:

```python
"""BF-940 (#1686): a document's frontmatter ends at a line of its own, so a value holding ``---`` is not cut short.

The real RecordsStore over ``tmp_path`` (its git repository too; no network) with HOME moved there, and the real skill catalog's
functions over SKILL.md files in ``tmp_path``. The functions before the class pass on both trees; the class holds the cases the
unfixed tree fails. No BF-940 name is imported.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.skill_catalog import CognitiveSkillCatalog, get_skill_body, parse_skill_file
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore

_BODY = "PRIVATE_BODY_PROOF the coolant"
_VALUES = ("---", "----", "--- x", "x ---", "---x", "x --- y", "a\n---\nb", "a\r\n---\r\nb", "- - -", "---\n---", "x: ---", "'---'")


async def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordsStore:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _bare(tmp_path: Path) -> RecordsStore:
    return RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))


def _hyphens(line: str) -> int:
    """The hyphens of a line of only hyphens (three or more) and trailing blanks, else 0: the test's own rule."""
    bare = line.rstrip(" \t\r")
    return len(bare) if len(bare) >= 3 and set(bare) == {"-"} else 0


def _closing(raw: str) -> tuple[int, int] | None:
    """(offset, hyphens) of the first line after the first that is only hyphens, for a text that begins with ``---``."""
    if not raw.startswith("---") or "\n" not in raw:
        return None
    offset = raw.index("\n") + 1
    for line in raw[offset:].split("\n"):
        if _hyphens(line):
            return offset, _hyphens(line)
        offset += len(line) + 1
    return None


def reframed(raw: str) -> bool:
    """Whether the rule frames ``raw`` otherwise than the base: a ``---`` inside a line before the first closing line, or a
    closing line of more than three hyphens (the base left the rest of them at the start of the body)."""
    found = _closing(raw)
    return found is not None and ("---" in raw[3:found[0]] or found[1] > 3)


def _oracle(raw: str) -> tuple[Any, str]:
    """The rule as a loop over the lines, not a pattern: what every reader's reading is compared with."""
    block = rest = None
    if raw.startswith("---"):
        found = _closing(raw)
        if found is not None:
            block, rest = raw[3:found[0]], raw[found[0] + found[1]:]
        elif len(parts := raw.split("---", 2)) >= 3:  # no closing line: the base's reading (L18)
            block, rest = parts[1], parts[2]
    if block is None:
        return {}, raw
    try:
        return yaml.safe_load(block) or {}, rest.strip()
    except yaml.YAMLError:
        return {}, rest.strip()


def _read_or_error(read: Any, raw: str) -> Any:
    try:
        return read(raw)
    except Exception as exc:  # noqa: BLE001 -- compared, never swallowed: a constructor error must be the same error
        return type(exc).__name__


def _search_read(raw: str) -> tuple[Any, str]:
    return records_store_module._search_read_document(raw)[:2]


def grid() -> list[str]:
    """BF-952's T22 corpus, 3,747 documents: (12 + 144) line sequences x 3 closing lines x 4 bodies x 2 line endings, + 3."""
    lines = (
        "author: alice", "author: alice --- legacy", "author: Ezri---Prime", "classification: private", "classification: ship",
        "classification: private --- legacy", "department: medical", "topic: Review --- nominal", "topic: 2026-13-05---nominal",
        "topic: 'Inspection --- status: nominal'", "broken: [unclosed", "updated: 2026-13-05",
    )
    shapes = [
        "---\n" + "".join(f"{line}\n" for line in seq) + close + body
        for count in (1, 2) for seq in itertools.product(lines, repeat=count)
        for close in ("---\n", "----\n", "") for body in ("", "warp notes\n", "classification: ship\nauthor: bob\n", "---\nmore notes\n")
    ]
    shapes += [shape.replace("\n", "\r\n") for shape in shapes]
    return shapes + ["no frontmatter", "-- two hyphens\n---\nbody", "\n---\nauthor: alice\n---\nbody"]


async def _round_trip(store: RecordsStore, author: str, values: dict[str, Any], body: str = _BODY) -> None:
    """One private record through write_entry, read_entry, list_entries, search, update-in-place and publish."""
    path = "notebooks/Ezri/inspection.md"
    call = {"author": author, "path": path, "content": body, "message": "probe", "classification": "private", **values}
    await store.write_entry(**call)
    raw = (store.repo_path / path).read_text(encoding="utf-8")
    assert raw.endswith(body) and sum(1 for line in raw[: len(raw) - len(body)].split("\n") if _hyphens(line)) == 2, "premise: two delimiters"
    expected = {k: v for k, v in values.items() if k != "extra_frontmatter"} | values.get("extra_frontmatter", {})
    try:
        own = await store.read_entry(path, reader_id=author)
    except Exception as exc:  # the base raises for a bad timestamp before its cut: a failure of the case
        raise AssertionError(f"read_entry raised {type(exc).__name__}") from exc
    assert own is not None and own["frontmatter"].get("classification") == "private" and own["frontmatter"].get("author") == author
    assert {key: own["frontmatter"].get(key) for key in expected} == expected and own["content"] == body
    assert await store.read_entry(path, reader_id="alice") is None
    assert [e["frontmatter"].get("classification") for e in await store.list_entries("notebooks") if e["path"] == path] == ["private"]
    assert await store.search("coolant", reader_id="alice") == []
    hits = await store.search("coolant", reader_id=author)
    assert [hit["path"] for hit in hits] == [path] and hits[0]["snippet"] == body[:200]
    await store.write_entry(**call)  # update-in-place carries ``created`` forward and counts the revision
    again = await store.read_entry(path, reader_id=author)
    assert again is not None and again["frontmatter"].get("revision") == 2 and again["frontmatter"].get("created") == own["frontmatter"].get("created")
    await store.publish(path, author)
    done = await store.read_entry(path, reader_id=author)
    assert done is not None and done["frontmatter"].get("status") == "published" and done["content"] == body
    assert done["frontmatter"].get("classification") == "private" and {key: done["frontmatter"].get(key) for key in expected} == expected


@pytest.mark.parametrize(("values", "body"), [
    pytest.param({"topic": "Inspection nominal", "tags": ["warp core"]}, _BODY, id="no-three-hyphens-in-the-values"),
    pytest.param({}, "above the coolant\n\n---\n\nbelow", id="a-body-holding-a-rule"),
])
async def test_a_record_the_rule_does_not_reframe_goes_through_the_same_round_trip(tmp_path, monkeypatch, values, body):
    """The control of the class below, and a body holding a rule: the chain passes on both trees."""
    await _round_trip(await _store(tmp_path, monkeypatch), "Ezri", values, body)


async def test_the_writer_puts_no_line_of_only_hyphens_inside_the_frontmatter(tmp_path, monkeypatch):
    """The premise of the class: for each of ``_VALUES`` as author, topic and tag, the file holds its two delimiter lines only."""
    store = await _store(tmp_path, monkeypatch)
    for index, value in enumerate(_VALUES):
        for position, call in enumerate(({"author": value}, {"topic": value}, {"tags": [value]})):
            path = f"notebooks/Ezri/p{index}-{position}.md"
            await store.write_entry(**{"author": "Ezri", "path": path, "content": "body", "message": "probe", **call})
            assert sum(1 for line in (store.repo_path / path).read_text(encoding="utf-8").split("\n") if _hyphens(line)) == 2, (value, position)


@pytest.mark.parametrize(("raw", "frontmatter", "body"), [
    pytest.param("---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n", {"author": "bones", "classification": "ship"}, "Warp report.", id="the-store-shape"),
    pytest.param("---\r\nauthor: bones\r\n---\r\n\r\nbody\r\n", {"author": "bones"}, "body", id="crlf-endings"),
    pytest.param("---\nauthor: bones\n---   \n\nbody", {"author": "bones"}, "body", id="a-closing-line-with-trailing-blanks"),
    pytest.param("---\nauthor: bones\n---", {"author": "bones"}, "", id="the-closing-line-ends-the-file"),
    pytest.param("---\nauthor: bones\n---\nabove\n\n---\n\nbelow", {"author": "bones"}, "above\n\n---\n\nbelow", id="a-body-holding-rules"),
    pytest.param("\ufeff---\nauthor: bones\n---\nbody", {}, "\ufeff---\nauthor: bones\n---\nbody", id="a-byte-order-mark-opens-no-frontmatter"),
    pytest.param("---\nauthor: alice\nwarp notes\n", {}, "---\nauthor: alice\nwarp notes\n", id="an-opener-and-no-later-hyphens-L18"),
    pytest.param(
        "---\nauthor: alice\nclassification: private --- inline\nbody", {"author": "alice", "classification": "private"}, "inline\nbody",
        id="hyphens-inside-a-line-and-no-closing-line-read-as-before",
    ),
    pytest.param("---\nkey: [unclosed\n---\nbody", {}, "body", id="frontmatter-that-does-not-parse-reads-as-empty-L19"),
])
def test_a_document_the_rule_does_not_reframe_reads_as_before(tmp_path, raw, frontmatter, body):
    """Guards: ``_parse_document`` and the search's reader read each shape as the base did."""
    assert not reframed(raw), "premise: the rule frames this shape as the base did"
    assert _bare(tmp_path)._parse_document(raw) == (frontmatter, body) and _search_read(raw) == (frontmatter, body)


_SKILL = "---\nname: demo-skill\ndescription: Use when a task needs it --- or a peer asks\nlicense: MIT\n---\n\n# Demo\n\nSteps.\n\n---\n\nFooter.\n"
_SKILL_BODY = "# Demo\n\nSteps.\n\n---\n\nFooter."


def _skill(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "demo-skill" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def _rewritten(path: Path) -> Any:
    entry = parse_skill_file(path)
    entry.department = "operations"
    CognitiveSkillCatalog._rewrite_frontmatter(path, entry)
    return parse_skill_file(path)


def test_a_skill_file_without_three_hyphens_in_its_frontmatter_reads_and_rewrites_as_before(tmp_path):
    """Guard: its body holds rules, as a store document's may."""
    path = _skill(tmp_path, _SKILL.replace(" --- or", ", or"))
    entry = parse_skill_file(path)
    assert entry is not None and entry.description == "Use when a task needs it, or a peer asks" and get_skill_body(path) == _SKILL_BODY
    assert _rewritten(path).department == "operations" and get_skill_body(path) == _SKILL_BODY


class TestAValueHoldingThreeHyphensIsNotCutShort:
    # BF-940 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-940 M2 builds it")

    @pytest.mark.parametrize(("author", "values"), [
        pytest.param("Ezri---Prime", {}, id="an-author-holding-three-hyphens"),
        pytest.param("Ezri---", {}, id="an-author-ending-in-three-hyphens"),
        pytest.param("Ezri", {"topic": "Inspection --- status: nominal"}, id="a-quoted-topic-holding-a-key"),
        pytest.param("Ezri", {"topic": "first line\n---\nlast line"}, id="a-multi-line-topic-holding-a-rule"),
        pytest.param("Ezri", {"tags": ["warp --- core"]}, id="a-tag-holding-three-hyphens"),
        pytest.param("Ezri", {"extra_frontmatter": {"zz_note": "end --- of the envelope"}}, id="the-last-key-holding-three-hyphens"),
        pytest.param("Ezri", {"extra_frontmatter": {"due": "2026-13-05---nominal"}}, id="a-value-whose-cut-prefix-is-a-bad-timestamp"),
    ])
    async def test_a_record_holding_it_is_read_whole_listed_found_updated_and_published(self, tmp_path, monkeypatch, author, values):
        """BF-952's T16 (its four cases first), and the premise of its T17: the quoted topic parses. The last case's cut prefix,
        ``2026-13-05``, is a constructor error on the base: ``read_entry`` raised."""
        await _round_trip(await _store(tmp_path, monkeypatch), author, values)

    @pytest.mark.parametrize(("raw", "body"), [
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---\n\nbody", "body", id="lf"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n----\n\nbody", "body", id="four-hyphens"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---  \n\nbody", "body", id="trailing-blanks"),
        pytest.param("---\r\nauthor: Normal---Name\r\nclassification: private\r\n---\r\n\r\nbody", "body", id="crlf"),
        pytest.param("---\nauthor: Normal---Name\nclassification: private\n---", "", id="the-end-of-the-file"),
    ])
    def test_each_closing_line_ends_the_frontmatter_after_a_value_holding_three_hyphens(self, tmp_path, raw, body):
        want = ({"author": "Normal---Name", "classification": "private"}, body)
        assert _bare(tmp_path)._parse_document(raw) == want and _search_read(raw) == want

    def test_a_four_hyphen_closing_line_leaves_nothing_of_itself_in_the_body(self, tmp_path):
        assert _bare(tmp_path)._parse_document("---\nauthor: bones\n----\n\nbody") == ({"author": "bones"}, "body")

    @pytest.mark.parametrize(("raw", "frontmatter", "body", "readers"), [
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nstatus: nominal\n---\nwarp notes\n",
            {"author": "alice", "classification": "private --- inline", "status": "nominal"}, "warp notes", {"alice", "bob"},
            id="then-a-key-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nWarp notes, in prose.\n---\nmore warp notes\n",
            {}, "more warp notes", {"alice", "bob"}, id="then-prose-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nclassification: ship\n---\nwarp notes\n",
            {"author": "alice", "classification": "ship"}, "warp notes", {"alice", "bob"}, id="then-a-repeated-key-and-a-rule",
        ),
        pytest.param(
            "---\nauthor: alice\nclassification: private --- inline\nclassification: private\nauthor: bob\n---\nwarp notes\n",
            {"author": "bob", "classification": "private"}, "warp notes", {"bob"}, id="then-keys-naming-another-author-and-a-rule",
        ),
    ])
    async def test_a_hand_made_document_closed_inside_a_line_reads_to_its_closing_line(
        self, tmp_path, monkeypatch, raw, frontmatter, body, readers,
    ):
        """The four BF-952 T20 / round-3 shapes that have a closing line after the inline marker. The base read each as alice's
        private note; the inline marker now ends nothing, so each reads to its closing line, as here, and ``read_entry`` admits
        the readers listed. No writer in the repository makes such a document (L3)."""
        store = await _store(tmp_path, monkeypatch)
        (store.repo_path / "notebooks" / "alice").mkdir(parents=True)
        (store.repo_path / "notebooks" / "alice" / "framing.md").write_text(raw, encoding="utf-8")
        assert store._parse_document(raw) == (frontmatter, body)
        assert {who for who in ("alice", "bob") if await store.read_entry("notebooks/alice/framing.md", reader_id=who)} == readers

    def test_every_document_of_the_grid_reads_by_the_rule(self, tmp_path):
        """BF-952's T22 over its 3,747 shapes, rewritten: both readers read each as ``_oracle`` does, a constructor error
        included. Premise: ``reframed`` names 2,388 of them, and the base differs from the rule on those and no others."""
        store, shapes = _bare(tmp_path), grid()
        assert len(shapes) == 3747 and sum(map(reframed, shapes)) == 2388, "premise: the grid and its reframed shapes"
        differ = [s for s in shapes if _read_or_error(store._parse_document, s) != _read_or_error(_oracle, s) or _read_or_error(_search_read, s) != _read_or_error(_oracle, s)]
        assert differ == [], (len(differ), differ[:3])

    def test_a_skill_file_whose_frontmatter_holds_three_hyphens_is_read_whole_and_rewritten_whole(self, tmp_path):
        path = _skill(tmp_path, _SKILL)
        entry = parse_skill_file(path)
        assert entry is not None and entry.description == "Use when a task needs it --- or a peer asks" and entry.license == "MIT"
        assert get_skill_body(path) == _SKILL_BODY
        again = _rewritten(path)
        assert again is not None and again.description == entry.description and again.department == "operations"
        assert path.read_text(encoding="utf-8").endswith("---\n\n# Demo\n\nSteps.\n\n---\n\nFooter.\n")

    def test_a_skill_file_whose_quoted_description_holds_three_hyphens_and_a_colon_parses(self, tmp_path):
        path = _skill(tmp_path, '---\nname: demo-skill\ndescription: "Use --- when: needed"\n---\n\nBody.\n')
        entry = parse_skill_file(path)
        assert entry is not None and entry.description == "Use --- when: needed" and get_skill_body(path) == "Body."
```

### 7.2 M2

**P2-1.** New file `src/probos/utils/frontmatter.py`:

```python
"""BF-940 (#1686): where the frontmatter of a Markdown document ends.

Ship's Records documents and SKILL.md files open with ``---``, hold YAML, and close with a line of their own. The base cut
each at the first two ``---`` it found, inside a YAML value too, so a value holding ``---`` was cut short and the keys after
it left the frontmatter. This module only frames a document; it loads nothing. Each caller loads the block in its own frame,
so PyYAML's recursion frontier stays where it was (BF-952 A6, L30). It imports nothing of ProbOS (``utils`` holds pure
helpers any layer may import).
"""

from __future__ import annotations

import re

#: A line of three or more hyphens and nothing else but trailing blanks. Group 1 is the hyphens: whatever follows them (the
#: blanks, the line break) belongs to the text after the marker, as what followed the second ``---`` did on the base.
_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Frame ``text`` as ``(block, rest)``: its frontmatter block and the text after it. ``block`` is None with none.

    A text has frontmatter when it begins with ``---``. The block runs from those three hyphens to the first later line
    made only of hyphens (three or more, trailing blanks allowed), line break included; ``rest`` is everything after that
    line's hyphens, not stripped, so a caller that rewrites the document keeps its whitespace. A ``---`` inside a line ends
    nothing. Where no such line follows, the text is framed as the base framed every document: the block ends at the first
    later ``---`` wherever it stands (L18), and ``(None, text)`` returns when there is none.
    """
    if not text.startswith("---"):
        return None, text
    first_break = text.find("\n")
    if first_break != -1:
        closing = _CLOSING_LINE.search(text, first_break + 1)
        if closing is not None:
            return text[3:closing.start()], text[closing.end(1):]
    parts = text.split("---", 2)  # the base's framing, kept for a text with no closing line
    if len(parts) >= 3:
        return parts[1], parts[2]
    return None, text
```

**P2-2.** `src/probos/knowledge/records_store.py` (the import; the SEARCH occurs once).
SEARCH:
```
from probos.cognitive.provenance import record_write_time
from probos.execution.command_env import trusted_command_env
```
REPLACE:
```
from probos.cognitive.provenance import record_write_time
from probos.execution.command_env import trusted_command_env
from probos.utils.frontmatter import split_frontmatter
```

**P2-3.** `src/probos/knowledge/records_store.py` (`_split_document`, the search's copy of the split, is deleted; the SEARCH occurs once).
SEARCH:
```
def _split_document(raw: str) -> tuple[str | None, str]:
    """BF-952 A3, A5: a Ship's Records document framed exactly as the base framed it: frontmatter block and body.

    A document that starts with ``---`` has frontmatter up to the next ``---`` wherever it stands, inside a value
    too, and its body is what follows, stripped; one with no later ``---`` has no frontmatter (``None``) and its
    body is the whole document (L18). That framing cuts a value holding ``---``; BF-940 (#1686) owns changing it,
    for every reader at once (L25). Only the search calls it: ``RecordsStore._parse_document`` keeps the base's own
    copy, so PyYAML's recursion frontier stays the base's for every other reader (A6, round 6; L30).
    """
    if raw.startswith("---"):
        parts = raw.split("---", 2)  # A6: the base's split, copied; _parse_document keeps its own
        if len(parts) >= 3:  # A6: the base's test, copied
            return parts[1], parts[2].strip()
    return None, raw


def _load_frontmatter(block: str) -> Any:
```
REPLACE:
```
def _load_frontmatter(block: str) -> Any:
```

**P2-4.** `src/probos/knowledge/records_store.py` (the search's reader frames through the shared function; the SEARCH occurs once).
SEARCH:
```
    The base's framing (:func:`_split_document`) and the search's load (:func:`_search_load_frontmatter`). The
    block (``None`` for a document with no frontmatter) lets the search check a record it would return against
    the base's reading (:func:`_base_reading_admits`).
    """
    block, body = _split_document(raw)
    return ({} if block is None else _search_load_frontmatter(block)), body, block
```
REPLACE:
```
    The framing every reader shares (BF-940: :func:`probos.utils.frontmatter.split_frontmatter`) and the search's load
    (:func:`_search_load_frontmatter`). The block (``None`` for a document with no frontmatter) lets the search check
    a record it would return against the base's reading (:func:`_base_reading_admits`).
    """
    block, rest = split_frontmatter(raw)
    if block is None:
        return {}, raw, None
    return _search_load_frontmatter(block), rest.strip(), block
```

**P2-5.** `src/probos/knowledge/records_store.py` (the `write_entry` docstring no longer says a value holding `---` is cut; the SEARCH occurs once).
SEARCH:
```
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them) and
        holds no ``---``, which the reader's framing cuts (BF-940, #1686).
        ``yaml.dump`` writes a tuple or another Python object with a
```
REPLACE:
```
        ``_parse_document`` when every value is one YAML's safe loader builds
        (a string, number, boolean, date, or a list or mapping of them), a
        value holding ``---`` included: the frontmatter ends at a line of its
        own (BF-940, #1686). ``yaml.dump`` writes a tuple or another Python
        object with a
```

**P2-6.** `src/probos/knowledge/records_store.py` (`_parse_document`; the SEARCH occurs once).
SEARCH:
```
    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document."""
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    fm = {}
                return fm, parts[2].strip()
        return {}, raw
```
REPLACE:
```
    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document.

        BF-940 (#1686): the frontmatter ends at the first later line of only hyphens, so a value holding ``---``
        stays whole (:func:`probos.utils.frontmatter.split_frontmatter`). The YAML is loaded here, in this frame,
        so PyYAML's recursion frontier is the one the base had (BF-952 A6, L30).
        """
        block, rest = split_frontmatter(raw)
        if block is None:
            return {}, raw
        try:
            fm = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            fm = {}
        return fm, rest.strip()
```

**P2-7.** `src/probos/cognitive/skill_catalog.py` (the import; the SEARCH occurs once).
SEARCH:
```
import yaml

if TYPE_CHECKING:
```
REPLACE:
```
import yaml

from probos.utils.frontmatter import split_frontmatter

if TYPE_CHECKING:
```

**P2-8.** `src/probos/cognitive/skill_catalog.py` (`parse_skill_file`; the SEARCH occurs once).
SEARCH:
```
    parts = content.split("---", 2)
    if len(parts) < 3:
        logger.warning("AD-596a: Incomplete frontmatter delimiters in %s", path)
        return None

    yaml_text = parts[1]
    try:
```
REPLACE:
```
    yaml_text, _ = split_frontmatter(content)  # BF-940: the frontmatter ends at a line of its own
    if yaml_text is None:
        logger.warning("AD-596a: Incomplete frontmatter delimiters in %s", path)
        return None

    try:
```

**P2-9.** `src/probos/cognitive/skill_catalog.py` (`get_skill_body`; the SEARCH occurs once).
SEARCH:
```
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    return parts[2].strip()
```
REPLACE:
```
    block, rest = split_frontmatter(content)  # BF-940: the frontmatter ends at a line of its own
    if block is None:
        return None

    return rest.strip()
```

**P2-10.** `src/probos/cognitive/skill_catalog.py` (`_rewrite_frontmatter`, the framing; the SEARCH occurs once).
SEARCH:
```
        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) < 3:
            return

        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return
```
REPLACE:
```
        block, rest = split_frontmatter(content)  # BF-940: the frontmatter ends at a line of its own
        if block is None:
            return

        try:
            fm = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            return
```

**P2-11.** `src/probos/cognitive/skill_catalog.py` (`_rewrite_frontmatter`, the write keeps the text after the closing hyphens as it was; the SEARCH occurs once).
SEARCH:
```
        skill_md.write_text(f"---\n{new_yaml}---{parts[2]}", encoding="utf-8")
```
REPLACE:
```
        skill_md.write_text(f"---\n{new_yaml}---{rest}", encoding="utf-8")
```

**P2-12.** `src/probos/knowledge/lessons.py` (comment only; the SEARCH occurs once).
SEARCH:
```
# A4 (R2-F3): Ship's Records splits a document's frontmatter at the first two "---" it finds, inside a value too
# (records_store._parse_document, register R25), so an envelope value holding one would come back cut short.
_FRONTMATTER_DELIMITER = "---"
```
REPLACE:
```
# A4 (R2-F3): Ship's Records split a document's frontmatter at the first two "---" it found, inside a value too
# (register R25), so an envelope value holding one came back cut short. BF-940 (#1686) ends the frontmatter at a line
# of its own, so that no longer happens; this rule still refuses "---" (AD-1341 S4's decision, left as it was).
_FRONTMATTER_DELIMITER = "---"
```

**P2-13.** `src/probos/knowledge/lessons.py` (docstring only; the SEARCH occurs once).
SEARCH:
```
    keyword search; a line break in a callsign would put another heading into the origin line. A4 (R2-F3): and no
    ``---``, which Ship's Records would take for the end of the frontmatter, so the value would come back cut short.
```
REPLACE:
```
    keyword search; a line break in a callsign would put another heading into the origin line. A4 (R2-F3): and no
    ``---``, which Ship's Records once took for the end of the frontmatter (BF-940, #1686, ended that); the rule stays.
```

**P2-14.** `src/probos/knowledge/lessons.py` (comment only; the SEARCH occurs once).
SEARCH:
```
        and _FRONTMATTER_DELIMITER not in value  # A4 (R2-F3): Ship's Records cuts a frontmatter value at "---"
```
REPLACE:
```
        and _FRONTMATTER_DELIMITER not in value  # A4 (R2-F3): kept since BF-940 (#1686); the store no longer cuts at "---"
```

**P2-15.** `tests/test_bf952_records_keyword_search.py` (BF-952's T22 narrows to the shapes the rule does not reframe: the import; the SEARCH occurs once).
SEARCH:
```
from tests.test_bf949_notebook_reader_identity import _self_monitoring
```
REPLACE:
```
from tests.test_bf940_frontmatter_framing import reframed
from tests.test_bf949_notebook_reader_identity import _self_monitoring
```

**P2-16.** `tests/test_bf952_records_keyword_search.py` (BF-952's T20: the four shapes with a closing line after the inline marker move to BF-940's file (T8); the SEARCH occurs once).
SEARCH:
```
    pytest.param(
        _INLINE_CLOSE + "status: nominal\n---\nwarp core notes\n", True, id="closed-inside-a-line-then-a-key-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "Warp core notes, in prose.\n---\nmore warp notes\n", True,
        id="closed-inside-a-line-then-prose-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "classification: ship\n---\nwarp core notes\n", True,
        id="closed-inside-a-line-then-a-repeated-key-and-a-rule",
    ),
    pytest.param(
        "---\nauthor: alice\nclassification: private --- legacy\nclassification: private\nauthor: bob\n---\n"
        "warp core notes\n",
        True, id="closed-inside-a-line-then-keys-naming-another-author-and-a-rule",
    ),
```
REPLACE:
```
    # BF-940 (#1686): the four hand-made shapes with a closing line after the inline marker read to that line now. They moved
    # to tests/test_bf940_frontmatter_framing.py, which pins each at its new reading (L3 of BF-940's contract).
```

**P2-17.** `tests/test_bf952_records_keyword_search.py` (BF-952's T20: its docstring; the SEARCH occurs once).
SEARCH:
```
    """A2 (round 2, finding 1), through ``read_entry`` and ``search``. A1 ended a frontmatter only at a line
    beginning ``---``, so a hand-made or legacy file closed inside a line read as ``{}`` (the first case) or took
    its body as YAML: the second case then read an unknown classification, the third did not parse (its author
    lost it) and the fourth read the repeated ``ship``. Each read as ``private`` on the base, and does again. In the
    fifth (round 3, finding 2) A1 and A2 read the repeated keys and gave the record to ``bob``; it is ``alice``'s, as
    on the base (A3: the base's framing for every reader). The sixth is the store's own shape. The last has no
    closing marker and reads as on the base, with no frontmatter (L18); BF-940 (#1686) owns any change to it and
    updates this case."""
```
REPLACE:
```
    """A2 (round 2, finding 1), through ``read_entry`` and ``search``. A hand-made or legacy file closed inside a line, with no
    closing line after it, read as ``private`` on the base and still does: BF-940's rule frames a text with no closing line
    as the base did. The four cases that had a closing line after the inline marker (rounds 2 and 3) moved to BF-940's file
    (#1686), where each is pinned at the reading the rule gives it. The next is the store's own shape. The last has no
    closing marker and reads as on the base, with no frontmatter (L18, kept by BF-940)."""
```

**P2-18.** `tests/test_bf952_records_keyword_search.py` (BF-952's T22: its docstring; the SEARCH occurs once).
SEARCH:
```
    """A3 (round 3, findings 1 to 3): BF-952 changes no reader's reading of a document. Each reconciliation of the
    base's framing with a line framing (A1, A2) misread some shape: as ``{}``, as an unclassified prefix, as another
    author's, or as a constructor error for a valid store-written value. Every shape here, over the three rounds'
    lines, closing markers, bodies and both line endings, reads under ``_parse_document`` (the base's own text, A6)
    exactly as the base read it, a constructor error included, and the search reads it so too (A5): no line holds a
    tab, so libyaml and PyYAML read each alike. The tab shapes, RK8's and round 4's, are T23's."""
```
REPLACE:
```
    """A3 (round 3, findings 1 to 3): BF-952 changes no reader's reading of a document. BF-940 (#1686) reframes 2,388 of the
    3,747 shapes (a ``---`` inside a line before the first closing line, or a closing line of more than three hyphens);
    those are its T9's. The other 1,359 are this test's: over the three rounds' lines, closing markers, bodies and both
    line endings, each reads under ``_parse_document`` exactly as the base read it, a constructor error included, and the
    search reads it so too (A5): no line holds a tab, so libyaml and PyYAML read each alike. The tab shapes, RK8's and
    round 4's, are T23's."""
```

**P2-19.** `tests/test_bf952_records_keyword_search.py` (BF-952's T22: the shapes the rule reframes are BF-940's (T9); the SEARCH occurs once).
SEARCH:
```
    assert len(shapes) == 3747  # premise: (12 + 144) line sequences x 3 closes x 4 bodies x 2 line endings, + 3
```
REPLACE:
```
    assert len(shapes) == 3747  # premise: (12 + 144) line sequences x 3 closes x 4 bodies x 2 line endings, + 3
    shapes = [shape for shape in shapes if not reframed(shape)]  # BF-940: the shapes it reframes are its own
    assert len(shapes) == 1359  # premise: 3,747 less the 2,388 that BF-940's rule frames otherwise
```

**P2-20.** `tests/test_ad1341_s4_lessons.py` (docstring only; the SEARCH occurs once).
SEARCH:
```
    """A4 (R2-F3): Ship's Records cuts a document's frontmatter at the first two ``---`` it finds, wherever they stand
    (register R25), so a callsign such as ``normal---value`` came back as ``normal``: the stand-down reported the
```
REPLACE:
```
    """A4 (R2-F3): Ship's Records cut a document's frontmatter at the first two ``---`` it found, wherever they stood
    (register R25; BF-940, #1686, ended that and the rule stays), so a callsign such as ``normal---value`` came back
    as ``normal``: the stand-down reported the
```

**P2-21.** `tests/test_ad1341_s4_stand_down.py` (comment only; the SEARCH occurs once).
SEARCH:
```
        ("callsign", "Chapel---Two"),  # A4 (R2-F3): Ship's Records would read it back as "Chapel"
```
REPLACE:
```
        ("callsign", "Chapel---Two"),  # A4 (R2-F3): read back as "Chapel" until BF-940 (#1686); the rule still refuses it
```

**N2-1.** New file `tests/test_bf940_split_frontmatter.py`:

```python
"""BF-940 (#1686): the framing function's contract, row by row. Each reader's own cases are in test_bf940_frontmatter_framing.py."""

from __future__ import annotations

import random

import pytest

from probos.utils.frontmatter import split_frontmatter


@pytest.mark.parametrize(("text", "framed"), [
    pytest.param("---\na: 1\n---\n\nbody\n", ("\na: 1\n", "\n\nbody\n"), id="the-store-shape"),
    pytest.param("---\na: x---y\n---\nbody", ("\na: x---y\n", "\nbody"), id="hyphens-inside-a-line-end-nothing"),
    pytest.param("---\na: 1\n----\nbody", ("\na: 1\n", "\nbody"), id="a-closing-line-of-four-hyphens"),
    pytest.param("---\na: 1\n---  \nbody", ("\na: 1\n", "  \nbody"), id="trailing-blanks-stay-in-the-rest"),
    pytest.param("---\r\na: 1\r\n---\r\nbody", ("\r\na: 1\r\n", "\r\nbody"), id="crlf"),
    pytest.param("---\na: 1\n---", ("\na: 1\n", ""), id="the-closing-line-ends-the-text"),
    pytest.param("---\n---\nbody", ("\n", "\nbody"), id="an-empty-block"),
    pytest.param("---\na: 1 --- b\nbody", ("\na: 1 ", " b\nbody"), id="no-closing-line-the-base-framing-L18"),
    pytest.param("---\ra: 1\r---\rbody", ("\ra: 1\r", "\rbody"), id="no-line-feed-at-all-the-base-framing"),
    pytest.param("---\na: 1\nbody", (None, "---\na: 1\nbody"), id="no-later-hyphens-L18"),
    pytest.param("---", (None, "---"), id="an-opener-alone"),
    pytest.param("", (None, ""), id="empty"),
    pytest.param("\ufeff---\na: 1\n---\n", (None, "\ufeff---\na: 1\n---\n"), id="a-byte-order-mark"),
    pytest.param("a: 1\n---\nbody", (None, "a: 1\n---\nbody"), id="no-opener"),
])
def test_each_shape_is_framed_as_its_row_says(text, framed):
    assert split_frontmatter(text) == framed


def _loop(text: str) -> tuple[str | None, str]:
    """The same rule as a loop over the lines: the reference for random documents."""
    if text.startswith("---"):
        offset = text.find("\n") + 1
        for line in text[offset:].split("\n") if offset else ():
            bare = line.rstrip(" \t\r")
            if len(bare) >= 3 and set(bare) == {"-"}:
                return text[3:offset], text[offset + len(bare):]
            offset += len(line) + 1
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[1], parts[2]
    return None, text


def test_random_documents_are_framed_as_a_loop_over_the_lines_frames_them():
    rng, pieces = random.Random(940), ["---", "----", "--", "-", "\n", "\r\n", "\r", " ", "\t", "a", ": ", "x---y", "---\n", "\n---\n"]
    for _ in range(4000):
        text = "---" * rng.randint(0, 1) + "".join(rng.choice(pieces) for _ in range(rng.randint(0, 16)))
        assert split_frontmatter(text) == _loop(text), repr(text)
```

**N2-2.** `tests/test_bf940_frontmatter_framing.py` (N1-1; the marker comes off, once; the SEARCH occurs once).
SEARCH:
```
class TestAValueHoldingThreeHyphensIsNotCutShort:
    # BF-940 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-940 M2 builds it")

```
REPLACE:
```
class TestAValueHoldingThreeHyphensIsNotCutShort:
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-940 (DATE), #1686 -- a document's frontmatter ends at the first later line made only of hyphens, so a frontmatter value holding "---" is no longer cut short (slice 1 of the issue).**
- **Base.** `RecordsStore._parse_document`, the search's copy of its split and the skill catalog's three parsers framed a document with `split("---", 2)`: the second `---` anywhere ended the frontmatter, inside a value too. On the real store a private note whose author held `---` read back as `{author: "Ezri"}` and to another reader, lost `created` and `revision` on its next write, and after a Captain's `publish` kept only `author`, `status` and `updated` in its frontmatter, the rest of it now in the body; a value whose cut prefix was `2026-13-05` made `read_entry` raise. In a SKILL.md the same split cut a description and made `enrich`'s rewrite corrupt the file.
- **Fix.** New `utils/frontmatter.py`: `split_frontmatter(text)` returns `(block, rest)`; the block ends at the first later line of only hyphens (three or more, trailing blanks allowed), and a text with no such line is framed as before (L18, kept). `_parse_document`, the search's reader and the skill catalog's three parsers call it and load the YAML in their own frame; the search's `_split_document` copy is gone. Contract `prompts/bf-940-frontmatter-closing-line.md`. Refs #1686: this closes its framing (L25), opener-without-closer (L18) and skill-catalog (L20) boxes; the issue stays open for L19, L24, L27 and F7-1.

```

**P3-2.** `DECISIONS.md`. Append after BF-943's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L15 of the contract. *Reversal.* Revert the BF-943 commits.
```
REPLACE:
```
- *Residual.* L1 to L15 of the contract. *Reversal.* Revert the BF-943 commits.

### BF-940 -- A document's frontmatter ends at the first later line made only of hyphens (DATE, #1686)

- *Scope.* `utils/frontmatter.py` (new), `RecordsStore._parse_document` and the search's reader, the skill catalog's three parsers, comments of `knowledge/lessons.py` and of two AD-1341 S4 tests, tests. Contract `prompts/bf-940-frontmatter-closing-line.md`. Slice 1 of #1686.
- *G0 (scope).* The rule, L18 and L20 in one contract; L19, L24, L27 and F7-1 stay in #1686, which stays open (`Refs`). Rejected: the rule alone (the skill catalog's rewrite corrupts files on the same shape); everything in one contract.
- *G1 (the rule).* A closing line is three or more hyphens and blanks only; a `---` inside a line ends nothing; a text with no closing line is framed as the base framed it (L18: no visibility change). Rejected: a writer-side refusal; YAML's document stream; the strict line rule with no fallback (3,072 of the 3,747 shapes of BF-952's T22 differ from the base, against 2,388).
- *G2 (one function).* `probos.utils.frontmatter`, pure, framing only: each caller loads in its own frame (BF-952's recursion frontier). Rejected: a function in `records_store`; one in `knowledge/`; two copies.
- *G3 (what changes).* A hand-made document closed by a `---` inside a line that holds a later closing line now reads to that line (L3 of the contract). `is_exit_note_text` keeps refusing `---`.
- *Residual.* L1 to L9 of the contract. *Reversal.* Revert the BF-940 commits.
```

**P3-3.** `docs/development/deterministic-ship.md` (the sentence occurs once, in the Persistence row; the cut is gone, the parse-failure gap of L19 is what the row still has to say).
SEARCH:
```
Ship's Records cuts a document short when a frontmatter value contains `---` (BF-940, #1686). |
```
REPLACE:
```
Ship's Records reads a document whose frontmatter does not parse as one with none (`{}`, so at the default classification) (#1686). |
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.4 The acceptance census (an orchestrator step; no repository file)

Run on a read-only copy of the vessel's `ship-records` (the path from the live process, `%LOCALAPPDATA%\ProbOS\data`), and again with `--skills` on a copy of its skills directory, with M2's tree first on `PYTHONPATH`: `$env:PYTHONPATH = '<build tree>\src'; PY -B -P census_bf940.py <copy> [--skills]`. Exit 0: no difference. 1: differences, all D1 or D2 (read each; D1's classification column is the one that matters). 3: a D3 difference (stop). 2: the control was not flagged (the comparison is not to be trusted). It reads each file as `read_text` hands it to the readers (CRLF and CR become LF; a BOM stays), compares the base's split, embedded verbatim, with the shipped `split_frontmatter`, and prints paths, key names and counts, never a value. The positive control is three documents in a temporary folder walked by the same `census` function, two of which must be flagged. Run on the Architect's synthetic trees (a store-written tree of 33 files, and the same with a store-written `Normal---Name` note and a four-hyphen file): exit 0 with 33 compared; exit 1 with D1 `(absent) -> private` and D2 flagged; the four in-repo SKILL.md: exit 0.

```python
"""BF-940 acceptance census. Run by the orchestrator on a READ-ONLY COPY; it only reads files, and is no repository file.

usage:  PYTHONPATH=<build tree>/src  python census_bf940.py ROOT [--skills]
ROOT: a copy of the vessel's ship-records (path taken from the live process, %LOCALAPPDATA%\\ProbOS\\data), or with --skills a
copy of a skills directory (every SKILL.md). Each file is framed by the base's split (embedded) and by the shipped
``split_frontmatter``; the two readings (loaded frontmatter, body) are compared. Exit 0: no difference; 1: differences, all
D1 or D2; 3: a difference of another class; 2: the control was not flagged. Prints paths and key names, never a value.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from probos.utils.frontmatter import split_frontmatter


def base_split(raw: str):
    """The base's framing, verbatim (``_parse_document`` and the skill catalog's parsers at b82f96d9)."""
    parts = raw.split("---", 2) if raw.startswith("---") else []
    return (parts[1], parts[2]) if len(parts) >= 3 else (None, raw)


def read(split, raw: str):
    block, rest = split(raw)
    if block is None:
        return "no frontmatter", raw
    try:
        return yaml.safe_load(block) or {}, rest.strip()
    except yaml.YAMLError:
        return {}, rest.strip()
    except Exception as exc:  # noqa: BLE001 -- a constructor error is compared by name
        return f"raises {type(exc).__name__}", rest.strip()


def closing(raw: str):
    """(offset, hyphens) of the first line after the first that is only hyphens (three or more) and blanks; None."""
    offset = raw.find("\n") + 1
    for line in raw[offset:].split("\n") if offset and raw.startswith("---") else ():
        bare = line.rstrip(" \t\r")
        if len(bare) >= 3 and set(bare) == {"-"}:
            return offset, len(bare)
        offset += len(line) + 1
    return None


def kind(raw: str) -> str:
    """D1: a '---' inside a line before the first closing line (the defect). D2: a closing line of four or more hyphens (body only)."""
    found = closing(raw)
    return "D3" if found is None else ("D1" if "---" in raw[3:found[0]] else ("D2" if found[1] > 3 else "D3"))


def level(loaded) -> str:
    value = loaded.get("classification") if isinstance(loaded, dict) else None
    return value if value in ("private", "department", "ship", "fleet") else ("(absent)" if value is None else "(other)")


def census(root: Path, name: str):
    count, report = Counter(), []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for file in sorted(files):
            if not (file == name or (name == "*.md" and file.endswith(".md"))):
                continue
            path, rel = Path(folder) / file, (Path(folder) / file).relative_to(root).as_posix()
            try:
                data = path.read_bytes()
                raw = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")  # what read_text hands the readers
            except (OSError, UnicodeDecodeError):
                count["unreadable"] += 1
                continue
            before, after = read(base_split, raw), read(split_frontmatter, raw)
            tags = after[0].get("tags") if isinstance(after[0], dict) else None
            count["compared"] += 1
            count["crlf on disk"] += b"\r\n" in data
            count["byte-order mark"] += raw.startswith("\ufeff")
            count["opener, no closing line (L18)"] += raw.startswith("---") and closing(raw) is None
            count["python tag (L24)"] += "!!python/" in raw
            count["non-text tag (L27)"] += isinstance(tags, list) and any(not isinstance(t, str) for t in tags)
            if before != after:
                count["differs " + kind(raw)] += 1
                part = [w for w, same in (("frontmatter", before[0] == after[0]), ("body", before[1] == after[1])) if not same]
                keys = [sorted(map(str, b[0])) if isinstance(b[0], dict) else b[0] for b in (before, after)]
                report.append(f"{kind(raw)} {rel}: {' + '.join(part)}; keys base={keys[0]} new={keys[1]}; classification {level(before[0])} -> {level(after[0])}")
    return count, report


def control() -> bool:
    """The positive control, through the same ``census``: three documents in a temporary folder, two of which must be flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in (("defect.md", "---\nauthor: Normal---Name\nclassification: private\n---\n\nbody\n"),
                           ("four.md", "---\nauthor: bones\n----\n\nbody\n"), ("plain.md", "---\nauthor: bones\n---\n\nbody\n")):
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        count, report = census(Path(tmp), "*.md")
        return (count["compared"], count["differs D1"], count["differs D2"], len(report)) == (3, 1, 1, 2)


def main() -> int:
    root = Path(sys.argv[1])
    if not control():
        print("CONTROL NOT FLAGGED: the comparison cannot see a difference")
        return 2
    count, report = census(root, "SKILL.md" if "--skills" in sys.argv else "*.md")
    print(f"control flagged (2 of 3 documents); root {root}")
    print("\n".join(f"{key}: {count[key]}" for key in sorted(count)))
    print("\n".join(report))
    return 3 if count["differs D3"] else (1 if report else 0)


if __name__ == "__main__":
    sys.exit(main())
```

## 8. What this does NOT change

`write_entry`'s serialization (`yaml.dump`), `append_captains_log`, `publish`'s rewrite shape, `record_is_readable` and `read_entry`'s gate; the search's ranking, its libyaml load (`_search_load_frontmatter`, `_load_frontmatter`) and its second reading (`_base_reading_admits`) except for A1's fallback (D7); the semantic indexer and its backfill (`semantic.py`); `routers/records.py`; `archive_promotion.py`; `is_exit_note_text`'s code and its tests; the skill catalog's other methods (`enrich_skill`, scan, validation); the AD-1344, AD-1346 and BF-892 inventories (their rows are keyed by file or by (file, scope, call), and the one write in `_rewrite_frontmatter` stays in its scope); BF-952's contract and DECISIONS RK9, RK10, RK15 (history); the roadmap; config. OSS only; no dependency (python-frontmatter is not added).

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/utils/frontmatter.py | `_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)` | `_CLOSING_LINE = re.compile(r"^(-{3})[ \t\r]*$", re.MULTILINE)` | T6[four-hyphens], T7, T9, U1[a-closing-line-of-four-hyphens], U2 |
| 2 | M2 | src/probos/utils/frontmatter.py | `_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)` | `_CLOSING_LINE = re.compile(r"^(-{3,})[ \t]*$", re.MULTILINE)` | T6[crlf], T9, U2 |
| 3 | M2 | src/probos/utils/frontmatter.py | `_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$", re.MULTILINE)` | `_CLOSING_LINE = re.compile(r"^(-{3,})[ \t\r]*$")` | T5 to T11, T13[a-cut-that-does-not-load-either-reads-as-the-rule-reads-it, a-constructor-error-after-three-hyphens-is-not-a-parse-failure-L13], U1[hyphens-inside-a-line-end-nothing, a-closing-line-of-four-hyphens], U2 (25 cases; A1) |
| 4 | M2 | src/probos/utils/frontmatter.py | `closing = _CLOSING_LINE.search(text, first_break + 1)` | `closing = _CLOSING_LINE.search(text, 0)` | T3[an-opener-and-no-later-hyphens-L18, frontmatter-that-does-not-parse-reads-as-empty-L19], T4 to T11, T13[a-cut-that-does-not-load-either-reads-as-the-rule-reads-it, a-constructor-error-after-three-hyphens-is-not-a-parse-failure-L13], U1 (9 of 14), U2, U4 (36 of the 62 cases; with A1 the fallback reads a store-shaped document as the base read it, so T1 no longer fails here; T2 asserts what the writer wrote and never calls the function) |
| 5 | M2 | src/probos/utils/frontmatter.py | `if first_break != -1:` | `if True:` | U1[an-opener-alone], U2, U4 |
| 6 | M2 | src/probos/utils/frontmatter.py | `if len(parts) >= 3:` | `if False:` | T3[hyphens-inside-a-line-and-no-closing-line-read-as-before, frontmatter-that-does-not-parse-reads-as-empty-L19], T8[then-prose-and-a-rule-reads-as-the-base-read-it], T9, T12, T13[a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it, a-cut-that-is-a-list-is-taken-as-the-base-took-it, a-cut-that-does-not-load-either-reads-as-the-rule-reads-it], T14, U1[no-closing-line-the-base-framing-L18, no-line-feed-at-all-the-base-framing], U2, U3[the-first-two-runs, a-run-inside-a-line-is-the-second, six-hyphens], U4 (16 cases; A1: the line is now in `base_split_frontmatter`, which the fallback also uses) |
| 7 | M2 | src/probos/utils/frontmatter.py | `return text[3:closing.start()], text[closing.end(1):]` | `return text[3:closing.start()], text[closing.end():]` | U1[trailing-blanks-stay-in-the-rest, crlf], U2 |
| 8 | M2 | src/probos/cognitive/skill_catalog.py | `yaml_text, _ = split_frontmatter(content)  # BF-940: the frontmatter ends at a line of its own` | `yaml_text = content.split("---", 2)[1] if content.count("---") >= 2 else None` | T10, T11 |
| 9 | M2 | src/probos/knowledge/records_store.py | `return fm, rest.strip()` | `return fm, rest` | T1, T3, T5 to T9, T13[a-cut-that-does-not-load-either-reads-as-the-rule-reads-it] (26 cases; A1) |
| 10 | M2 | src/probos/knowledge/records_store.py | `return frontmatter, rest.strip(), block` | `return frontmatter, rest, block` | T1, T3, T5, T6, T9, T13[a-cut-that-does-not-load-either-reads-as-the-rule-reads-it] (22 cases; A1 moved the line: it was `return _search_load_frontmatter(block), rest.strip(), block`) |
| 11 | M2 | src/probos/cognitive/skill_catalog.py | `return rest.strip()` | `return rest` | T4, T10, T11 |
| 12 | M2 | src/probos/cognitive/skill_catalog.py | `skill_md.write_text(f"---\n{new_yaml}---{rest}", encoding="utf-8")` | `skill_md.write_text(f"---\n{new_yaml}---\n{rest}", encoding="utf-8")` | T10 |

Run by hand against M2's head (no pytest), one mutant at a time with the two new files driven (baseline 48 passed): each fails the cases it names, and the cases listed are the failing ones, rows 3, 4, 9 and 10 counted. Rows 5 and 7 are killed only by the unit file, which is why N2-1 exists. Campaign of record: the orchestrator ran the 12 mutants by tool on M2's head, with the two new files alone (baseline 48 passed, 2026-11-10): 12 of 12 killed by their claimed cases. The tool's first pass named T2 in row 4 (it passes there; corrected above) and could not take row 12's mutant as written, because it reads a literal backslash-n as a newline, so row 12 was run as `skill_md.write_text(f"---{chr(10)}{new_yaml}---{chr(10)}{rest}", encoding="utf-8")`, the same text. Not tabulated, for the cap: the `block is None` guard of `_search_read_document` (T3 and T9 read both readers), the three `lessons.py` text edits, the BF-952 repairs.

**Rows added by A1** (each Line occurs once, stripped, in its file with A1 applied):

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| Q-1 | M2 | src/probos/utils/frontmatter.py | `return base_split_frontmatter(text)  # a text with no closing line is framed as the base framed it (L18)` | `return None, text` | T3[hyphens-inside-a-line-and-no-closing-line-read-as-before], T9, U1[no-closing-line-the-base-framing-L18, no-line-feed-at-all-the-base-framing], U2, U4 |
| Q-2 | M2 | src/probos/utils/frontmatter.py | `parts = text.split("---", 2) if text.startswith("---") else []` | `parts = text.split("---", 2)` | U3[no-opener], U4 |
| Q-3 | M2 | src/probos/knowledge/records_store.py | `if not fm:  # A1: the base's cut may read where the whole block does not (a tag safe_load refuses, after a ---)` | `if False:` | T8[then-prose-and-a-rule-reads-as-the-base-read-it], T9, T12, T13[a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it, a-cut-that-is-a-list-is-taken-as-the-base-took-it], T14 |
| Q-4 | M2 | src/probos/knowledge/records_store.py | `if base_fm:` | `if type(base_fm) is dict and base_fm:` | T13[a-cut-that-is-a-list-is-taken-as-the-base-took-it] |
| Q-5 | M2 | src/probos/knowledge/records_store.py | `return base_fm, base_rest.strip()` | `return base_fm, rest.strip()` | T8[then-prose-and-a-rule-reads-as-the-base-read-it], T9, T13[a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it, a-cut-that-is-a-list-is-taken-as-the-base-took-it] |
| Q-6 | M2 | src/probos/knowledge/records_store.py | `base_fm = {}` | `raise` | T3[frontmatter-that-does-not-parse-reads-as-empty-L19], T9, T13[a-cut-that-does-not-load-either-reads-as-the-rule-reads-it] |
| Q-7 | M2 | src/probos/knowledge/records_store.py | `base_frontmatter = _search_load_frontmatter(base_block)` | `base_frontmatter = {}` | T9, T13[a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it, a-cut-that-is-a-list-is-taken-as-the-base-took-it] |
| Q-8 | M2 | src/probos/knowledge/records_store.py | `return base_frontmatter, base_rest.strip(), block` | `return base_frontmatter, rest.strip(), block` | T9, T13[a-tag-safe-load-refuses-after-three-hyphens-reads-as-the-base-read-it, a-cut-that-is-a-list-is-taken-as-the-base-took-it] |
| Q-9 | M2 | src/probos/knowledge/records_store.py | `frontmatter = _load_frontmatter(block.partition("---")[0]) or frontmatter` | `frontmatter = frontmatter` | T14 (with libyaml installed, L17) |
| Q-10 | M2 | src/probos/knowledge/records_store.py | `frontmatter = _load_frontmatter(block.partition("---")[0]) or frontmatter` | `frontmatter = _load_frontmatter(block.partition("---")[2]) or frontmatter` | T14 (with libyaml installed, L17), T8[then-prose-and-a-rule-reads-as-the-base-read-it] |

Run by hand by the Architect (2026-11-10; no pytest, no timing script), one mutant at a time, on an overlay of the base tree `4c5d1e80` with the staged blobs (index tree `2981c112`) and A1-1 to A1-15 applied, the two new files driven (baseline 62 passed: 40 and 22): rows 1 to 12 and Q-1 to Q-10 each fail the cases they name. The "Killed by" cells of rows 3, 4, 5, 6, 9 and 10 are this campaign's; the paragraph above the A1 rows is the campaign on M2's head before A1 (baseline 48). Not tabulated, for the cap: widening `_parse_document`'s catch on the rule's load from `yaml.YAMLError` to `Exception` (two lines, so no row) fails T9 and T13[a-constructor-error-after-three-hyphens-is-not-a-parse-failure-L13]. **Campaign of record for A1** (the base tree and files above; sha256 of the LF text): `src/probos/utils/frontmatter.py` 858078c73bd1b6f4d9e6f6bfd8ab3163f3a83e58cb8306c2043198b4ca9773b1; `src/probos/knowledge/records_store.py` 093653da07e574b557b9215c3c88d5d033f2e02fb5531edbc51087fc3140d6c2; `src/probos/cognitive/skill_catalog.py` 50f114182adc46d857662fad52d496e3e539dfce175975d68b13b8873bd7e6ae (unchanged by A1); `tests/test_bf940_frontmatter_framing.py` d083ed2a518662acd79500c14b40906a202da66c1ba09df9ad8575dbe5d79815; `tests/test_bf940_split_frontmatter.py` ada1776ff2a45aae88f68f9d26fd9ddefd88edc34d43dfbc26389f505a52fa9e. A Builder whose files hash the same does not repeat it; if one differs, rerun the rows that name it: `frontmatter.py`, rows 1 to 7, Q-1 and Q-2; `records_store.py`, rows 9, 10 and Q-3 to Q-10; `skill_catalog.py`, rows 8, 11 and 12; a test file, every row.

## 10. Recorded limits

- **L1.** Nothing here is a live-system claim: no vessel, no real `ship-records` and no real skills directory was read. The 2026-10-26 census is the issue's; 7.4 is the census to run (with `--skills` for installed skills). Until it is run, that no live document differs is unverified. **Run since (the orchestrator, 2026-11-10, read-only, the vessel not running; M2's code):** 7.4 was run on a read-only copy of a vessel's `ship-records` and, with `--skills`, on the repository's own `config/skills`; the acceptance criterion of section 14 for it was met, and the data directory was identical before and after. The census prints paths and key names, never a value, and it covers the documents present when it was run, so a document written later is not covered. **Counts and every other result of a run on a vessel's data are not recorded in this repository.**
- **L2.** A text with no closing line reads as on the base: the first later `---` wherever it stands, and none means no frontmatter. So a truncated store-written document (its closing line lost) with a `---` in a value before the cut still reads cut, and a hand-made `classification: private --- inline` note with no closing line still reads private (T3). The issue's L18 question, whether an opener with no closing marker should be the Captain's alone, is answered no, ranked: keep (no change of visibility) > Captain-only (hides raw `.md` files that open with a rule: `write_workspace_file` and `append_workspace_file` have ten call sites in `consultation/workspace.py` and one in `consultation/delivery.py:983`; and `publish` and update-in-place would rewrite a sentinel into the file, BF-952 A2) > no frontmatter for every such text (the strict rule, D1). A later owner may change the order; that is a new decision, not this box.
- **L3.** A hand-made document whose frontmatter a `---` inside a line closed, whose whole block loads and which holds a later line of only hyphens, now reads to that line (a block that does not load reads as the base read it, A1). Its classification and author can change in either direction: of T8's shapes the 1st and 3rd become readable by every reader (an unrecognised classification is level 0 and not identity-gated, `record_is_readable`) and the 4th reads as bob's; the 2nd (prose after a key) reads as before. On BF-952's 3,747 shapes, for a reader with no claim on them (bob), the rule makes 252 readable that the base withheld, and withholds 90 and fails 90 that the base showed (counted with `record_is_readable`; every shape is hand-made and hostile by construction). No writer in `src` produces one (the three document writers write a closing line and a whole mapping; section 11), and the rule that would keep the old reading for such documents ("provable agreement", BF-952 A2; a classification floor, D7) was withdrawn in A3 for misreading others. Classified by the Architect as inside the Delegated AD Execution envelope, not a weakening of a control (D7). 7.4 lists each such document with its classification before and after, and a document that moves from a gated classification to a non-gated one goes to the Captain before the merge.
- **L4.** Records already indexed are not re-indexed. `write_entry` indexes the caller's dict, so a record it wrote was indexed whole; the backfill reads from disk (`semantic.py:738`) and skips a path already indexed (`_indexed_record_paths`), so a record it indexed from a cut reading keeps that metadata until its next write. Not measured against a real index.
- **L5.** L19, L24, L27 and F7-1 are not built (D3). A frontmatter that does not parse still reads `{}` for every reader, except that a block that does not parse while the base's cut of the same text does reads as the base read it (A1; `deterministic-ship.md` says so after P3-3); T17 as at `cf61c683` is L19's acceptance; `!!python/` tags and a numeric tag behave as on the base; the route still returns 500 for a record nested about 450 levels.
- **L6.** A line ends at LF (a CRLF's CR counts as a trailing blank); a bare CR, NEL or LS ends none. `read_text` turns a file's CRLF and CR into LF before any reader sees it (run), so CRLF matters for a text passed directly (the tests; a reader of bytes). A BOM before the opener opens no frontmatter, as on the base. The opener is `startswith("---")` as on the base, so a first line holding more than hyphens (`--- x`) frames as before.
- **L7.** No timing was run (the request forbids it). Each parse adds one regex search that stops at the first closing line; a text with no closing line is scanned to its end and then split as before. BF-952's B1 and B2 bounds were not re-measured: an orchestrator step if that benchmark is still run. Not run: G1 to G3, the broad gate and the ledger generator (it writes); M3 changes the ledger's inputs by the two tracker pairs only.
- **L8.** `_load_frontmatter`, `_base_reading_admits` and the search's comments still say "the base's reading" for PyYAML's `safe_load` of the block (BF-952's words); text only, not changed.
- **L9.** The four in-repo SKILL.md files read identically on both trees and eight skill modules driven gave equal counts, but the 15 class-based cases of `test_ad634_notebook_quality.py` (`setup_class`) could not be driven by the hand driver and are unverified here (G2 runs them). Skills a vessel has installed are 7.4 with `--skills`. python-frontmatter, the issue's reference for option (a), is not installed and was not read.
- **L10.** Case B (F1's twin, pre-existing; the issue's L24). A private document whose frontmatter holds a value `yaml.dump` writes with a `!!python/` tag (a tuple or an object in `metrics` or `extra_frontmatter`) and no `---` before it does not load for any reader: it reads `{}`, so at the default `ship` classification, shown to every reader, and its author's `publish` raises `PermissionError`. The base, M2 and A1 alike (A1 gives the base's reading back where a `---` precedes the tag, F1's case A). A privacy defect, not only "reads as `{}`" (the issue's L24 text). Recorded on #1686's L24 box; slice 2 starts with L24, then L19 (D7). Exposure: crew to crew inside one vessel, from a writer that passes such a value; the payloads read so far hold none (L16).
- **L11.** A document read by A1's fallback is read as the base read it, so it is rewritten as the base rewrote it: `publish` and update-in-place write the cut frontmatter, and what the cut left out (`created`, `metrics`, the keys after the `---`) is lost from the file. It no longer reads as `{}`; the rewrite is the base's, and L24's slice owns it.
- **L12.** The skill catalog has no fallback. A SKILL.md whose whole frontmatter does not load while its cut prefix did (a tag, or an unquoted `: `, after a `---` inside a description) now fails `parse_skill_file` (`Invalid YAML`) where the base loaded it, cut. No privacy control is involved. The four in-repo files read identically on both trees and the vessel holds none (L1).
- **L13.** A1's trigger is the base's own catch (`yaml.YAMLError`) and nothing wider. A block that raises a constructor error (a timestamp YAML cannot build, `updated: 2026-13-05`) or a `RecursionError` after a `---` that the base's cut stopped before raises where the base read the cut: `read_entry` raises, `list_entries` drops the record, the search skips it (withheld, not exposed). On BF-952's 3,747 shapes 108 do, all holding `2026-13-05`; T13's last row pins it. Widening the trigger is L19's policy.
- **L14.** 7.4 compares framings and loads each block alone; it does not apply A1's fallback, so a document it lists as D1 whose block does not load reads as the base read it (no change). Its list is a superset of the documents whose reading changes; run before A1, it listed none (L1).
- **L15.** F4 (P3, pre-existing, equal on both trees): `_rewrite_frontmatter` does not keep the body's line endings: `read_text` turns CRLF and CR into LF and `write_text` turns LF into CRLF on Windows (`os.linesep`). No content is lost, only line-ending bytes; reach: every `enrich_skill` rewrite on a host whose line separator is not LF. Not fixed: the natural fix replaces the `.write_text` call that the AD-1344 and AD-1346 write inventories key on (`(file, scope, call)`), a governance edit outside this issue. This contract and DECISIONS say "the text after the closing hyphens", not bytes. An item of the issue's follow-up.
- **L16.** Whether a production caller passes a tuple or an object to `write_entry` or `write_notebook` was enumerated in part: the notebook metrics (`collect_notebook_metrics`, `proactive.py:332`: numbers and strings) and the envelopes of the after-action and stand-down writers (`after_action.py:353-362`, `stand_down.py:390-397`: strings, lists of strings, and `review.as_envelope()`, not read) hold none; the payloads of `publish_finding_tool.py:693`, `dreaming.py` (1012, 1145, 1372), `procedure_store.py` (719, 1729), `recreation/service.py:377`, `peer_perception.py:350`, `commands_gap.py:244`, `routers/gaps.py:186` and `creative/output_writer.py:105` were not read. The records route takes JSON, which has no tuple.
- **L17.** T14's assertion that the search's second reading applies the fallback (Q-9, Q-10) is exercised only where libyaml is installed: without it the first reading is PyYAML's and the fallback in `_search_read_document` withholds the note alone, with the same answer. This venv has libyaml (PyYAML 6.0.3); whether the Linux CI image has it is unmeasured.

## 11. Verified Against Codebase (2026-11-09, reading tree `D:\ProbOS-worktrees\bf940-build` at `b82f96d9`)

**Run by the Architect, read-only (CPython 3.12.13, win32; PyYAML 6.0.3 with libyaml; scripts, copies and scenes in the OS temp folder, outside every repository, `-B`; no pytest runner and no timing script):**

```
git rev-parse HEAD and origin/main -> both b82f96d9a1bfd78afb541b99ed5701ad1a5fd4c7; git status of the reading tree empty after every run
git archive HEAD (src tests config scripts and two docs files) into two temp overlays, base and patched; each script asserts that probos imports from its overlay
this contract's pairs applied in label order to the LF blobs: every SEARCH once (21 of M2, N2-2 on the M1 file, 3 of M3); every .py result parses; the 3 new files written
hand driver (calls each function with tmp_path, monkeypatch and the module's own fixtures; not the pytest runner): on the head N1-1 gives 13 passed and 20 failed, each at an assert of its own body, none at a premise; on M2's head (marker removed) 33 passed; N2-1 15 passed
existing modules driven on both trees: test_bf952_records_keyword_search 80 cases -> 76 (the four params of P2-16 removed), all pass; before P2-15 to P2-19 the same file failed exactly four T20 cases and T22; test_records_store 31, test_ad550_notebook_dedup 26, test_ad1341_s4_lessons 133, test_ad1341_s4_stand_down 67, test_layer_boundaries 3: equal and passing; test_cognitive_skill_catalog 27, test_ad596d 23, test_ad626 55, test_ad630 28, test_ad643a 41, test_ad728d 6 (+1 skipped), test_ad596e 34 (+1 skipped), test_ad1069 13: equal on both trees
the twelve mutants of section 9, one at a time on M2's head, against N1-1 and N2-1 (baseline 48 passed): each fails the cases listed
the real store over a temp directory, ~ moved (base, then M2's head): author "Ezri---Prime", private: read_entry by alice -> {author: "Ezri"} / None; after a second write revision None / 2; a Captain's publish -> author, status and updated only, the rest at the head of the body / the whole frontmatter; due "2026-13-05---nominal": read_entry raises ValueError and list_entries omits the record / reads and lists it
SKILL.md "description: Use when a task needs it --- or a peer asks" then "license: MIT": base description 'Use when a task needs it', license '', body starts 'or a peer asks', the rewrite wrote "--- or a peer asks\nlicense: MIT\n---" after the cut frontmatter; a quoted description holding --- and ": " -> None (Invalid YAML) / M2's head: whole in each
the four in-repo SKILL.md files (config/skills): entry and body hashes equal on both trees
BF-952's T22 corpus rebuilt (3,747 shapes): the rule frames 2,388 otherwise than the base, exactly the shapes with a --- inside a line before the first closing line or a closing line of more than three hyphens (0 outside); the base's returned reading differs from (a') as built before A1 for 2,200 of them (both readers, an error compared by its name; 188 of the 2,388 read alike on both trees) and from the strict rule (a) for 2,884 of the 3,747 (the earlier figures, 2,388 and 3,072, counted framings and bodies, not returned readings)
yaml.dump fuzz (seeded): 300,000 random frontmatters (author, topic, tags, a caller key; hyphen-heavy alphabet) and 88 targeted values: 0 lines of only hyphens and blanks
Path.read_text(encoding="utf-8") on b'---\r\na: 1\r\n---\r\nb\r\n' -> '---\na: 1\n---\nb\n'; a BOM is kept ('\ufeff---')
scripts/check_architecture_principles.py --check (writes nothing): exit 0, srp-size=92, layer-import=0, db-connect=30, unowned-task=13
YAML-stream prototype of option (c) over 16 shapes: errors on "----", on an opener with text, on an opener with no closing line and on one with a --- only inside a line
census 7.4 on two synthetic trees and the in-repo skills directory: as 7.4 states
A1 (2026-11-10; the Architect, no pytest; an overlay of the base tree 4c5d1e80 with the staged blobs of index tree 2981c112 and A1-1 to A1-15 applied; every SEARCH once, every .py result parses): hand driver: N1-1 40 passed, N2-1 22 passed; on the unfixed base the amended N1-1 gives 18 passed and 22 failed, each failing case at an assert of its own body (the 15 guards, T8's second shape and T13's first two rows pass); on the candidate before A1 the amended N1-1 fails exactly 6 of 40 (T12, T14, T8's second shape, T9's claim, T13's first two rows) and the unit file fails at import
A1: the existing modules driven on the amended overlay, counts equal to the head's and all passing: test_bf952_records_keyword_search 76, test_records_store 31, test_ad550_notebook_dedup 26, test_ad1341_s4_lessons 133, test_ad1341_s4_stand_down 67, test_layer_boundaries 3, test_cognitive_skill_catalog 27, test_ad596d 23, test_ad626 55, test_ad630 28, test_ad643a 41, test_ad728d 6 (+1 skipped), test_ad596e 34 (+1 skipped), test_ad1069 13; scripts/check_architecture_principles.py --check: exit 0, srp-size=92, layer-import=0, db-connect=30, unowned-task=13
A1: the real store over a temp directory, ~ moved (the orchestrator's probe), base / M2 / A1: case A (topic holding ---, tuple metric) private, bob none, publish ok / {}, bob reads it, PermissionError / as the base; case B (no ---, tuple metric) {}, bob reads it, PermissionError on all three; case C (list metric) private, bob none, publish ok on all three, metrics kept from M2
A1: BF-952's T22 corpus (3,747 shapes), both readers: the returned reading differs from the base's for 2,110 (M2: 2,200; the strict rule (a): 2,884): 1,732 read to read, 270 error to read, 108 read to error (all 108 hold 2026-13-05: L13); none outside the 2,388 reframed shapes; the two readers never differ from each other; for a reader with no claim (bob) 252 shapes become readable that the base withheld, 90 become withheld and 90 become errors (L3)
A1: the 23 mutants (rows 1 to 12, Q-1 to Q-10, and the widened catch) each fail the cases named in section 9; the twelve old rows were re-run on the amended files
```

**Absence Verified (2026-11-09)**

```
CLAIM: no BF-940 other than #1686; nothing new is allocated
RUN:   git log --all --format=%s, searched for BF-940; prompts/bf-940* in each of the 119 worktrees of git worktree list; gh issue list --state all --search "BF-940 in:title"; git grep BF-940 -- docs/development/roadmap.md docs/development/roadmap-completed.md docs/development/open-ads-report.md
FOUND: 0 subjects (BF-941's body names it); 0 files; #1686 only (OPEN, bug); 0 hits
HOLDS: yes

CLAIM: _parse_document is called only inside records_store.py (nine sites) and by three test files; _split_document only by _search_read_document
RUN:   git grep -n -E "_parse_document|_split_document|_search_read_document" -- src tests scripts docs
FOUND: records_store.py :724, :1067, :1140, :1158, :1248, :1269, :1408, :1473, :1533, the definition :1712, _split_document :264, _search_read_document :330, :337, :430; comments at tools/publish_finding_tool.py:32 and lessons.py:86; tests: test_ad550_notebook_dedup.py, test_bf952_records_keyword_search.py, test_records_store.py
HOLDS: yes

CLAIM: every other --- framing of a document in src is another format
RUN:   Grep over src/probos/**/*.py for (split|rsplit|partition|rpartition|find|index|count|startswith|endswith)\(r?["'](\\n)?-{3,} and for re.(split|match|search|compile|sub|findall|finditer|fullmatch) with a hyphen run; the same for scripts/*.py and ui/src; pyproject.toml for "frontmatter"
FOUND: records_store.py :273-274, :1714-1715; skill_catalog.py :101/105, :176/179, :787/790; avatars/asset_manifest.py:103 (a Markdown table's separator row); cognitive/step_instruction_router.py:146 (re.split of tier blocks of an instruction text); none in scripts or ui/src; no frontmatter dependency
HOLDS: yes

CLAIM: the three document writers and the skill rewrite write a closing line; the raw writers write any text
RUN:   Grep f"---\\n\{ over src; Grep write_workspace_file|append_workspace_file over src
FOUND: records_store.py :760 (write_entry), :884 (append_captains_log), :1542 (publish); skill_catalog.py:814; raw writers records_store.py :1661, :1694, called ten times in consultation/workspace.py and once at consultation/delivery.py:983
HOLDS: yes

CLAIM: fifteen other files call the store's read_entry, list_entries or search, and none parses a frontmatter itself
RUN:   Grep over src/probos for \.list_entries\(|\.read_entry\(|records_store\.search\(|\.check_notebook_similarity\(|\.publish\( (61 matches in 27 files; the skill catalog's own list_entries, the mesh's publish and other publish calls excluded by reading each receiver)
FOUND: __main__.py, experience/commands/commands_gap.py, proactive.py, knowledge/semantic.py, notebook_quality.py, backlinks.py, archive_promotion.py, knowledge_linter.py, recreation/history.py, routers/gaps.py, routers/records.py, stand_down.py, cognitive/dreaming.py, oracle_service.py, diagnostic_context.py; tools/publish_finding_tool.py calls check_notebook_similarity; the three-hyphen search of the previous claim found no other framing
HOLDS: yes

CLAIM: the new names are free; nothing is named for the framing
RUN:   git grep -n -E "split_frontmatter|_CLOSING_LINE|utils\.frontmatter|def reframed|test_bf940|bf-940-frontmatter" -- src tests scripts docs; git ls-files, searched for frontmatter
FOUND: 0; 0
HOLDS: yes

CLAIM: no test pins the comments and docstrings the pairs edit, and none names _split_document
RUN:   git grep -n -E "Ship's Records cuts a frontmatter value|would take for the end of the frontmatter|splits a document's frontmatter|reader's framing cuts|the base's split, copied|_split_document" -- tests
FOUND: 0
HOLDS: yes (P2-20 and P2-21 edit two AD-1341 S4 test texts that do not pin them)

CLAIM: T17 of cf61c683 is not at HEAD; T16 and T17 are at cf61c683; T22 and T20 are at HEAD
RUN:   git grep -n "shown_to_the_captain_alone" -- tests at HEAD and at cf61c683; git show cf61c683:tests/test_bf952_records_keyword_search.py
FOUND: 0 at HEAD; cf61c683 :375 (T16), :404 (T17); HEAD :438 (T20), :524 (T22)
HOLDS: yes

CLAIM: no AD-1344, AD-1346 or BF-892 inventory keys a line of an edited file
RUN:   Grep tests/test_ad1344_constitution_write_refusal.py, tests/fixtures/ad1346_file_write_census.py, tests/fixtures/ad1346_effect_census.py and tests/test_bf892_spawn_env_guard.py for records_store, skill_catalog, lessons
FOUND: rows keyed by (file, scope, call) or by file: skill_catalog.py "CognitiveSkillCatalog._rewrite_frontmatter" ".write_text" (test_ad1344:769); records_store.py "RecordsStore.write_entry" and "RecordsStore._git_sync"; none by line
HOLDS: yes

CLAIM: the documents that state the delimiter are those of D6
RUN:   git grep -c -i -E "frontmatter" -- docs config (12 files); Grep over docs and src for frontmatter within 160 characters of ---, delimit, hyphen, fence or closing marker
FOUND: docs/development/deterministic-ship.md:49 only in docs; src: records_store.py :267-270, :670-672, :1573; lessons.py :85-87, :225, :229; skill_catalog.py :100-107; config/ontology/records.yaml:80, docs/architecture/memory.md:127 and docs/development/prov-o-mapping.md:30-33 name the format and no delimiter
HOLDS: yes
```

**Read, not run:** `records_store.py:106-175` (`record_is_readable`: an unrecognised classification is level 0 and not identity-gated), `:264-357`, `:647-800`, `:858-890`, `:1023-1285`, `:1393-1495`, `:1526-1612`, `:1661-1722`; `semantic.py:392-425`, `:700-760`; `routers/records.py:55-102`; `skill_catalog.py:88-200`, `:729-815`; `lessons.py:76-96`, `:205-245`; `tests/test_layer_boundaries.py:1-260` (the matrix, the allowlist, `_get_imported_layer`); `check_architecture_principles.py:74-100`; BF-952's contract (L18 to L30, A1.1, A2.1, A3.1, the T16, T17, T20 and T22 text) and DECISIONS RK9 to RK15. **Not measured:** a live vessel; the Linux CI; timing; python-frontmatter.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** BF-952's A6 and L30 (the YAML load stays in each caller's frame: `split_frontmatter` frames and loads nothing, so BF-952's frontier tests are unaffected and pass), RK15 (every reader reads alike unless a design for every reader says otherwise: this contract is that design), A2 and A3 (no reconciliation with the base for hand-made documents beyond A1's fallback for a block that does not load, D7: one rule, its changes enumerated and pinned in T8, T9 and T13), T16, T17, T20 and T22 as acceptance; the `utils` precedent (`web_agents.py:26`, `causal_reasoning.py:32`); BF-961's form. **Rejected:** "provable agreement" (BF-952 A2, withdrawn in A3); python-frontmatter as a dependency (not in `pyproject.toml`). **External:** python-frontmatter's pattern, as the issue cites it: not read.
- **Blind spots handled.** CRLF (files reach the readers with LF; strings keep it); a BOM; a closing line at the end of the text; four hyphens; trailing blanks; a body holding rules; an opener with no closing line, with and without a `---` inside a line; a value ending or starting in `---`; a multi-line value (its continuation lines are indented); a bad-timestamp prefix; update-in-place and `publish`, which rewrite from the parse; the search's second reading (it takes the same block); SKILL.md read, body and rewrite; the recursion frontier.
- **What discards a correct result.** After a successful parse: the body's `strip()` is each caller's own step, pinned by rows 9 to 11 of section 9; the skill rewrite keeps `rest` unstripped (row 12); the search hands the same block to `_base_reading_admits`, so a record is returned only where `read_entry` admits the reader too (T5 asserts alice gets nothing). Records already indexed from a cut reading keep their metadata (L4). **Recorded:** L1 to L17.

## 13. Diff Reviewer: properties to verify

1. `split_frontmatter`: for a text that begins with `---` and has a later line of only hyphens (three or more, trailing blanks allowed), `block` is `text[3:start of that line]` and `rest` is the text after its hyphens, unstripped; otherwise the result is the base's `split("---", 2)` (`parts[1], parts[2]` with three parts, else `(None, text)`); a text not beginning with `---` is `(None, text)`. It loads nothing and imports only `re`.
2. `_parse_document` calls `yaml.safe_load(block)` itself (no helper between it and the load), returns `fm, rest.strip()` (or A1's fallback reading, property 10), and `({}, raw)` for `None`; BF-952's frontier tests still hold.
3. `_search_read_document` returns `({}, raw, None)` for no frontmatter and `(_search_load_frontmatter(block), rest.strip(), block)` otherwise, except for A1's fallback (property 10); nothing references `_split_document` (`git grep _split_document -- src tests` is empty).
4. The skill catalog: `parse_skill_file` keeps its "No frontmatter delimiters" warning (the `startswith` test before the new call is untouched) and its "Incomplete frontmatter delimiters" for `None`; `get_skill_body` returns `rest.strip()`; `_rewrite_frontmatter` writes `---\n{new_yaml}---{rest}`, as it wrote `parts[2]`.
5. `lessons.py`: three text-only edits; `is_exit_note_text` behaves as before; the two AD-1341 S4 tests change a docstring and a comment only.
6. BF-952's file: T20 keeps three cases and T22 keeps 1,359 shapes; the four moved shapes and the other 2,388 are N1-1's T8 and T9; collected count 80 to 76.
7. M1: the file collects on the unfixed tree, imports no BF-940 name, and the 20 class cases fail at their own `assert`, never at a premise line; N2-2 removes the marker only; `reframed` in N1-1 is public because BF-952's T22 imports it.
8. M3: the PROGRESS entry and the DECISIONS entry say `Refs #1686` and name what the issue keeps; P3-3 states the L19 gap and no longer the cut.
9. A1: `base_split_frontmatter(text)` is `(parts[1], parts[2])` of `text.split("---", 2)` for a text that begins with `---` and splits into three, else `(None, text)`; `split_frontmatter` returns it for a text with no closing line; wherever `split_frontmatter` returns a block this returns one, and it is that block up to its first `---` (U4).
10. A1: `_parse_document` and `_search_read_document` fall back only where the rule's block reads as nothing; each loads the cut in its own frame (`yaml.safe_load`; `_search_load_frontmatter`; no helper between), returns the cut's frontmatter and its text after the second `---`, stripped, only where the cut reads as something, and otherwise returns what it returned before; the catch is `yaml.YAMLError` and nothing wider (L13); `_search_read_document` still returns the rule's block as its third element; `_base_reading_admits` makes the same decision with the cut taken as `block.partition("---")[0]`, inside its existing `try`.
11. A1: a private note whose topic holds `---` and whose metrics hold a tuple reads private through `read_entry`, the search and `publish` (T12); T8 asserts each shape through the search for alice and bob; T9 asserts 2,388 and 2,110; `skill_catalog.py` is not changed.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, the census of 7.4 is run on the vessel's copy (a D3 difference stops the merge), and the batch's broad gate is green with a receipt.
- **A value holding `---`** (as author, tag, topic, a multi-line value, the last key, or with a bad-timestamp prefix) is read whole, listed, found, updated (`created` and `revision` kept) and published, and a private record stays private (T5); each closing-line form ends the frontmatter (T6, T7); BF-952's 3,747 shapes read by the rule (T9); a SKILL.md is read, bodied and rewritten whole (T10, T11).
- **What reads as before:** the shapes of T3, a text with no closing line, BF-952's 1,359 unchanged shapes, a body holding rules, and the existing store and skill tests.
- **F1 (A1):** a writer-made private note whose topic holds `---` and whose metrics hold a tuple stays private through `read_entry`, the search and `publish` (T12, T14), and a block that does not load reads as the base read it where the base's cut loads (T13); case B is recorded on #1686 (L10), not fixed here.
- **The issue:** the pull request says `Refs #1686`; its checklist shows L25, L18 and L20 done and L19, L24, L27 and F7-1 open; the issue is not closed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (review round 1: F1 to F4)

The diff reviewer's round 1 on M2 and M3 was NOT READY: F1 (P1, regression), F2 (P2), F3 (P3), F4 (P3, pre-existing). A1 is a set of pairs (A1-1 to A1-53) applied to the staged candidate: the decisions are D7, the limits L10 to L17, the rows Q-1 to Q-10, the cases T12 to T14, U3 and U4. The pairs are the amendment's own text; the code and tests they produce are in the tree.

| Finding | Disposition | Where |
|---|---|---|
| F1 (P1): M2 made a writer-made private note (topic holding `---`, tuple metric) readable by every reader | Repaired: a block that reads as nothing reads as the base read the text where the base's cut reads | D7; `base_split_frontmatter`; `_parse_document`, `_search_read_document`, `_base_reading_admits`; T12 to T14, U3, U4; Q-1 to Q-10 |
| Case B (pre-existing, the issue's L24): a tuple with no `---` reads `{}`, shown to every reader | Recorded as a privacy defect (P1) on #1686's L24 box; slice 2 starts with it; not fixed here | D7; L10 |
| L3 and the Captain-only boundary | In-envelope, not a weakening of a control; the census is a hard stop for it | D7; L3 |
| F2 (P2): T20's real-search assertions were dropped | T8 asserts the search for alice and bob | T8 |
| F3 (P3): "changes the reading of 2,388" counted framings | The claim is "frames 2,388, returns a different reading for 2,110"; T9 asserts both | D1; T9; section 11; DECISIONS G1 |
| F4 (P3, pre-existing): a skill rewrite does not keep the body's line endings | Not fixed here; recorded | L15 |
