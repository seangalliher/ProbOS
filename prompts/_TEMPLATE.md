<!--
prompts/_TEMPLATE.md — the ProbOS build-prompt skeleton + pre-dispatch spec-completeness checklist.

Copy this file to prompts/ad-XXXX-<slug>.md and fill it in. Delete the guidance
comments (<!-- ... -->) as you go. The Architect writes this; the Builder executes it.

The "Spec-completeness checklist" at the bottom is the absorbed spec-kit
`/speckit.checklist` idea ("unit tests for English") adapted to ProbOS: the
Architect ticks every box BEFORE dispatching the Builder. It complements
verify-first (spec-vs-reality) by catching under-specification (spec-vs-itself).
-->

# AD-XXXX — <concise title> (<area>)

<!-- One line: epic/issue refs · the single AD or small AD group · which repo. -->
**Epic #NNN · issue #NNN · depends on AD-XXXX (state status).**
**Repo: OSS (`d:\ProbOS`) or the private commercial overlay. AD ceiling at drafting: AD-XXXX (state the verified highest; this AD = the next free number).**

<!-- One or two sentences: what this delivers and, crucially, what it does NOT (defer to a later AD). -->
<one-line scope statement>

---

## Why / context
<!-- Optional but recommended for non-trivial work. The problem, the trigger
(a live test, a review finding, a Nooplex gap), and the grounding (existing
pattern this mirrors). Keep it tight. -->

## Pinned design decisions
<!-- For any AD that required an Architect design pass. Each decision is settled
against the LIVE code (cite file:line). Number them DD-1, DD-2, … so the Builder
and reviewer can reference them. Lead with the highest-risk / most-load-bearing
decision. If a sub-question must be resolved AT build, FLAG it explicitly with
your recommended option — do not guess. -->

### DD-1 — <headline decision>
<the decision, the existing pattern it mirrors (file:line), and the guardrail/trap it avoids>

### DD-2 — <decision>
…

## Build
<!-- Numbered, each item: implement [specific thing] in [specific file]; it
should [behavior]; wire it from [caller]; add tests in [test file]. Reference
verified seams (file:line). Follow the perceive→decide→act→report lifecycle for
new agents; instructions-first for CognitiveAgents. -->
1. **<thing>** — implement in [file](path) … wire from [caller](path).
2. …

## Acceptance
<!-- Every build item maps to ≥1 criterion here. Include: test expectations
(named tests + counts), default-OFF byte-identity, BF-287 real-fixture rule,
real-DB (tmp_path) test for any new SQLite store, a gate/consensus test for any
new tier/destructive intent, and the compliance line. -->
- <criterion with named test(s)>
- Default-OFF (`config.<flag>=False`) ⇒ byte-identical; existing tests unchanged.
- Real-fixture tests per BF-287 (no MagicMock at substrate/store/bridge boundaries); real-DB `tmp_path` test for any new store (cache-only `db_path=""` masks the real path).
- Verify compliance with `.github/copilot-instructions.md` (async hygiene, layer discipline, IntentBus fan-out, type annotations, logging context).

## Do NOT build here
<!-- Name SPECIFIC adjacent features that are tempting to add, by name. This is
the #1 scope-creep guard. Also: ❌ no new top-level AD number, ❌ don't change
sealed protocols (BaseAgent/IntentMessage/IntentResult), ❌ don't alter prior-AD
behavior, ❌ (OSS repo) no pricing/revenue/competitive-analysis leak. -->
❌ <adjacent feature> (AD-YYYY). ❌ … ❌ A new top-level AD number — this is AD-XXXX.

## Files (verify each at build)
<!-- List every file you'll touch, NEW or modified, with a one-line purpose.
The Builder verifies each exists (or is genuinely new) before editing. -->
- `path/to/file.py` — <what changes / mirror which pattern>.
- `tests/test_adXXXX_*.py` (NEW) — <coverage>.

## Done-when
All acceptance green; gate `-k "<selectors>"` green (prior-AD count unchanged + new); default-OFF byte-identical; full type annotations on new public methods; async hygiene verified; **verify compliance with `.github/copilot-instructions.md`.**

---

<!-- ===================================================================== -->
<!-- SPEC-COMPLETENESS CHECKLIST — Architect ticks ALL before dispatch.     -->
<!-- The absorbed spec-kit `/speckit.checklist` concept: validate the spec  -->
<!-- against ITSELF (completeness) the way verify-first validates it        -->
<!-- against REALITY (no phantom APIs). Delete this block before commit, or -->
<!-- keep it ticked as an audit trail.                                      -->
<!-- ===================================================================== -->

## Pre-dispatch checklist (do not dispatch the Builder until every box is checked)

**Numbering & boundary**
- [ ] AD number is the next free one — grepped `DECISIONS.md` (+ era files), stated the verified highest, assigned sequentially. Never guessed/reused.
- [ ] Correct repo for the change (OSS = how it works · Commercial = how it makes money). No commercial leak in an OSS prompt.

**Verify-first (spec vs reality)**
- [ ] Every API / class / method / signature / config field the spec asserts was grepped against the LIVE codebase (not memory). Import paths, constructor params, enum vs string, public vs `_private` all confirmed.
- [ ] Every cited `file:line` / "mirror X" pattern was opened and confirmed to be the shape claimed.
- [ ] For any AD that CONSUMES a prior AD's output: confirmed the prior AD actually PERSISTED the data this AD reads (an in-memory return value is not queryable later), and the cited cross-AD seam is PUBLIC.

**Completeness (spec vs itself)**
- [ ] Every Build item maps to ≥1 Acceptance criterion (and vice-versa — no orphan criteria).
- [ ] Every new public method has a stated test: happy path + error/edge + empty/None where applicable.
- [ ] Every new SQLite store has a real-DB (`tmp_path`) round-trip test requirement (not only `db_path=""`).
- [ ] Every new tier / gate / destructive intent has a gate test; destructive ops set `requires_consensus=True` (or route through the existing quorum) — and a test asserts the gate actually blocks.
- [ ] Default-OFF transitional flag specified, defaulting False, with a byte-identical assertion.
- [ ] Any unsettled design sub-question is FLAGGED with a recommended option (not silently left to the Builder).

**Discipline**
- [ ] "Do NOT build" names specific adjacent features by name (not just "stay in scope").
- [ ] Async hygiene considered (task refs held, cancellation re-raised, `create_task` not `ensure_future`).
- [ ] Layer discipline respected (lower layers don't import higher; cross-cutting via runtime API).
- [ ] Hard-stop conditions for the Builder are explicit and narrow (phantom API in impl · sealed-protocol change · unresolved design fork).
- [ ] The compliance line (`verify compliance with .github/copilot-instructions.md`) is in the Acceptance criteria.
