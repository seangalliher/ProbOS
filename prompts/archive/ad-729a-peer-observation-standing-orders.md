# AD-729a — Standing Orders extension for peer observation conduct

**Wave:** 162
**Closes:** #588
**Status:** ready to build
**Dependencies:** AD-489 (Code of Conduct — existing); AD-586 (task-contextual Standing Orders — DECISIONS.md:132). AD-729 (capability AD — does NOT advance until this ships).
**Estimated tests:** +6 pytest (one per Standing Orders section).
**Scope tag:** **Documentation + YAML/Markdown only.** No new pip/npm deps. Apache 2.0. Authors the rules; AD-729 capability and AD-729b training are siblings (out of scope).

---

## Problem

[Issue #588](https://github.com/seangalliher/ProbOS/issues/588) — Captain ruling 2026-05-10: peer observation is a class of crew action governed by the same Code of Conduct (AD-489) as all crew action. The AD-729 capability AD does not advance to build until Standing Orders are extended to cover it.

The issue body specifies five Standing Orders sections (Operational observation, Personal commentary, Prohibited behavior, Permission-to-speak-freely protocol, Captain/chain-of-command exceptions). This AD authors and ratifies them, wired through the existing AD-586/AD-489 prompt-assembly path.

---

## Solution overview

1. New Markdown file `config/standing_orders/peer_observation.md` containing the five sections verbatim from the issue body (already authored by Captain in the issue — Builder copies them in faithfully, no paraphrasing).
2. Cross-reference from `config/standing_orders/ship.md` (or wherever AD-489's Code of Conduct rendering anchors) so the new file is picked up by the existing prompt-assembly path. NO new wiring code — uses the AD-586 framework that's already there.
3. Cross-reference from the Counselor standing orders (`config/standing_orders/counselor.md`) — the Counselor reviews pattern-level drift per Section 2/4 of this AD.
4. Boundary tests: 6 pytest tests, one per Standing Orders section, verifying the rendered prompt block contains the section's key sentences.
5. Counselor + Captain ratification recorded via the existing ratification mechanism (Builder: read AD-586 / existing standing-orders to find how ratification is currently noted — typically a metadata header or a `ratified_by:` field).

### What this does NOT change

- The AD-489 Code of Conduct (this AD EXTENDS, doesn't modify).
- The prompt-assembly wiring (AD-586 framework consumes the new file automatically).
- AD-729 capability code (not built until this AD ships).
- AD-729b training (out of scope, sibling AD).
- AD-729c Counselor monitoring (out of scope, sibling AD).
- Any agent code paths — this is pure documentation + prompt-context.

---

## Section 1 — Author `config/standing_orders/peer_observation.md`

NEW FILE. Contents are the 5 sections from the issue body, verbatim. Builder must NOT paraphrase — the Captain authored the text. Use the issue body's text exactly, formatted as Markdown with `## Section N: <title>` headings.

Header block:
```markdown
# Peer Observation — Standing Orders

**Status:** Ratified Wave 162 (AD-729a).
**Parent Code of Conduct:** AD-489.
**Ratified by:** Counselor, Captain.
**Scope:** All crew. Applies to operational and social channels.

These orders extend the Code of Conduct (AD-489) to cover peer observation — a class of crew action introduced by AD-729's capability surface.

---
```

Then the 5 sections (Operational observation / Personal commentary / Prohibited behavior / Permission-to-speak-freely protocol / Captain and chain-of-command exceptions) — copied verbatim from the issue body.

---

## Section 2 — Cross-reference from `config/standing_orders/ship.md`

`config/standing_orders/ship.md` is the ship-wide Code-of-Conduct rendering anchor. Append a one-line cross-reference at the end of its Code-of-Conduct section:

```markdown
**Peer observation conduct:** see `peer_observation.md` (AD-729a extension).
```

Builder: read `config/standing_orders/ship.md` first; if it doesn't contain a Code-of-Conduct section yet, append the cross-reference at the bottom. Single `replace_string_in_file` (BF-274).

---

## Section 3 — Cross-reference from `config/standing_orders/counselor.md`

The Counselor's standing orders should reference the pattern-level review duty introduced by this AD. Append to `config/standing_orders/counselor.md`:

```markdown
## Peer Observation Pattern Review (AD-729a)

You are responsible for reviewing pattern-level conduct concerns arising from peer observation. Specifically:

- Cascade observations (Section 3 of peer_observation.md).
- Aesthetic conformity pressure (Section 3).
- Static impressions (Section 3).
- Repeated permission-request despite denial (Section 4).
- Cross-rank personal commentary that lacks operational rationale (Section 2).

Pattern-level review means reviewing aggregated observations over time — single events are not actionable unless they meet the "Prohibited behavior" thresholds in Section 3.
```

---

## Section 4 — Permission-to-speak-freely DSL anchors

The DSL tokens `[PERMISSION_REQUEST observed_agent: <id>, register: personal]` / `[PERMISSION_GRANTED]` / `[PERMISSION_DENIED <reason>]` are defined by AD-729 (capability AD). This AD's Section 4 of `peer_observation.md` AUTHORS the social grammar; AD-729 will provide the parser.

This AD does NOT add a parser — only the prose. If AD-729 has shipped before this AD, this AD's Section 4 prose references the existing parser. If AD-729 has not shipped, the prose stands alone as the protocol specification, and AD-729 builds the parser to match.

---

## Section 5 — Tests

`tests/test_ad729a_peer_observation_standing_orders.py` — 6 tests:

1. `test_peer_observation_md_exists_and_loads` — `config/standing_orders/peer_observation.md` exists and parses.
2. `test_section_1_operational_observation_phrases_present` — required sentence "Crew may make observations of fellow crew's presentation when operationally relevant" present.
3. `test_section_2_personal_commentary_phrases_present` — required sentence "Personal commentary about a fellow crew member's presentation is a privilege, not a right" present.
4. `test_section_3_prohibited_behavior_phrases_present` — required sentence "Cascade observation — repeating an observation made by another officer without independent corroboration — is prohibited" present.
5. `test_section_4_permission_protocol_phrases_present` — `PERMISSION_REQUEST` / `PERMISSION_GRANTED` / `PERMISSION_DENIED` tokens present.
6. `test_section_5_captain_exception_phrases_present` — required sentence "The Captain may make either register of observation at any time without requesting permission" present.

All tests parse the markdown file at the path `config/standing_orders/peer_observation.md`, scan for the required phrases, and assert presence. No production code paths exercised.

Optional 7th test (recommended, not required): `test_ship_md_cross_references_peer_observation` — `ship.md` contains the cross-reference line.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-729a row to SHIPPED Wave 162; confirm AD-729 capability AD is now buildable.
- `DECISIONS.md` — append AD-729a entry summarizing the five sections and the AD-489 cross-reference.
- `config/standing_orders/peer_observation.md` — the file itself is the deliverable.

---

## Acceptance criteria

- `config/standing_orders/peer_observation.md` exists with 5 sections verbatim from the issue body.
- Counselor + Captain ratification noted in the file header (the existing ratification mechanism — Builder reads how other files note ratification).
- Cross-reference from `ship.md` added.
- Counselor cross-reference added.
- 6 (or 7) new pytest tests green at `-n 0` and parallel.
- No new pip/npm deps.
- No code changes outside `config/standing_orders/` and `tests/`.
- AD-489 unchanged (this AD EXTENDS).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `config/standing_orders/` directory exists with 41+ files (per repository listing).
- `config/standing_orders/counselor.md` exists, line 1 confirms "# Counselor — Personal Standing Orders".
- `config/standing_orders/ship.md` exists in the standing_orders directory.
- `DECISIONS.md:132` — AD-586 (Task-Contextual Standing Orders) confirmed; framework is in place for picking up new files.
- AD-489 Code of Conduct referenced as parent; existing references confirmed in `src/probos/holodeck/chamber.py:283` and `src/probos/holodeck/gates.py:50` (`code_of_conduct_acknowledged` gate).
- Issue body 5 sections are pre-authored Captain text; Builder copies verbatim.
- AD-729 capability AD not yet present in DECISIONS.md (forward marker only); this AD's ship status precondition will allow AD-729 to advance.
