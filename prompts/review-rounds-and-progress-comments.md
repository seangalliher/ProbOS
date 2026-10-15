**Drafted by:** `claude-architect` (Claude Code, Opus 5.5; read-only consult through `scripts/claude_architect.py`, saved verbatim by the orchestrator), 2026-10-15
**Status:** built; the five edit blocks below were installed by script from this file (every anchor verified once against the committed text), the tests were added as written, and the mutation table was run by the orchestrator.
**Provenance note:** this is the Architect's answer to the Captain's two queued rules (a round-three review brake and a two-hour progress comment) with its decisions D1 to D6, edit blocks, tests, mutation table and tracker wording.
**Review round 1 note (orchestrator, after the Diff Reviewer):** three changes to what this answer says, all in the built text: (1) the brake also covers a fourth round that follows a failed gate or CI (D2 limited it to a round three that leaves a finding; the Captain's words are "do not start a fourth on your own"); (2) the brake request names where the candidate is frozen and the exact diff command, not only `git diff --stat`: a head commit id and `git diff <base> <head>` for a committed candidate, the worktree path, the `git write-tree` id and `git diff --cached <base>` for a staged one (round 2 found that the commit-pair form alone is empty for an uncommitted candidate, the normal state at review); (3) D5's claim that the new test "closes F-79 for this pair" is withdrawn: the test pins the brake's three options, not the "Still requires the Captain" heading F-79 asks for.
**Review round 3 note (orchestrator, after the round-three brake):** round 3 found that a candidate that exists only in the working tree has no frozen form (`git write-tree` names the base tree and `git diff --cached <base>` is empty). This was the item's third round, so the brake fired on the item that adds it, and the Architect (read-only) decided to continue with that finding only: the clause now allows two forms and no other (committed; staged in full, new files included, never `git add -N`), requires a working-tree candidate to be staged before the call, and names an unreviewed repair by `git diff` (staged candidate) or `git diff <head>` (committed), with the path of every file it adds. One premise of that decision is refuted by probe and is not in the text: `git add -N` on a repair's file changes neither `git diff --cached <base>` nor `git write-tree`.

# Consult: review-round brake and progress comments in the ProbOS Orchestrator profile

**Verdict:** Ready to build as one docs and test change. Both rules go in O under one new section. C, `CLAUDE.md` and `claude-architect.md` get pointers only. **Decisions that need the Captain: none.** Two after-the-fact notes for him are at the end.

## 1. Decisions

| # | Decision | Criteria / reason |
|---|---|---|
| **D1** | Add a new section to O, `## Review Rounds and Progress (Standing Order)`, between the end of **Delegation and Waiting** (O, the "Prompts from the Claude Architect" bullet) and `## Backlog Burn-Down Mode`. It has four bold-lead paragraphs: Convergence, Round definition, Round-three brake, Progress comments. Add pointers in C (the "Act on the findings" paragraph and the Where Each Rule Lives row), in `CLAUDE.md` workflow step 3 and in `claude-architect.md` (one callee bullet). | Both rules apply in every mode, not only in Burn-Down, so neither fits under **Reporting** or **Gate, Batch and Push**. Delegation and Waiting is already about 9 KB. A `##` heading can sit in `OWNERS`. C's "Act on the findings" already sends unfixed findings to O, so retargeting that pointer keeps one owner. |
| **D2** | **A round** is one *completed* Diff Reviewer pass over a frozen candidate. The first review counts, and so does every repair re-review, whether it covers the delta or the whole candidate. Reviewers run in parallel on one candidate count once. A relaunch after a reviewer failed to start or was refused does not count, so it does not penalise C's retry rule. Each item or slice in a batch keeps its own count. **The brake applies only when round three leaves a finding that the convergence rule says to fix.** If round three is READY, or leaves only findings that can be recorded, there is no round four and so no brake. "Continue" allows exactly one more round, and so does a split's review of its reduced candidate. Any later round needs a new decision. | A completed pass is what cost the 189 review minutes. A failed launch costs none. Allowing one round per decision stops one "continue" from becoming open-ended again. |
| **D3** | **The clock starts** at the item's first Architect bridge call or first Builder delegation, whichever comes first. An overlapped `--read-only` consult does not start it: it is preparation and does not count toward WIP either. **Cadence:** post 2 h after the start, then 2 h after the *last progress comment*. After the first post, GitHub's own comment timestamp is the durable clock, so a fresh session can always compute the next mark. **When the start is lost:** take the earliest time the worktree can prove (its first `logs/architect/<stamp>-<session>.json` file, from `scripts/claude_architect.py:543-545`, or the branch's `git reflog`). If none exists, post at once; the worst case is one early comment. **Posting:** check the clock before each delegation or gate and on every wake (watchdog, agent completion, any turn). No timers. A sync delegation can delay the post by up to its own length, which is accepted. | The cadence then needs no new state file. The Captain also forbade automation. |
| **D4** | Post on the owning issue. A slice without its own issue posts on its parent issue. An item with no issue posts on its PR once one is open. If there is neither, say so in the session report. The PR is not opened early just to have somewhere to post, because pushing before a green gate is forbidden (O, Gate, Batch and Push). Template: at most five lines (below). Skip the post if phase, work left and blocker are all unchanged; this is the Captain's "no repeats" rule, applied literally. | The order follows where a reader looks first. |
| **D5** | **The request is a fresh `--read-only` bridge call carrying:**<br>• every finding from rounds 1–3, each with severity, reach, regression flag and status (fixed, open or recorded)<br>• the candidate's `git diff --stat` against its base, plus the stat of any unreviewed repair already in hand<br>• minutes spent per phase: build, each round, each repair<br>**The answer gives:** the option, its scope (findings and files) and the reason.<br>**The options:**<br>• **continue**: round four, with that scope.<br>• **rescope**: land what has converged and move the remaining findings to the follow-up. This never moves a P1, a regression, or a finding that would break the next run.<br>• **split**: land the converged part. The rest becomes a new slice of the same issue, which stays open, or is filed under the filing policy.<br>**Callee side:** yes, one bullet in `claude-architect.md` that points to O and names the three options. A new test pins that both sides name the same options, which closes F-79 for this pair. | **The rescope limit is needed.** The brake only fires when a must-fix finding is still open. If rescope could move only findings that are recordable anyway, it would never apply. So rescope is a bounded exception to the convergence rule. The bound comes from C's existing blocker rule ("would break the next run", C Adversarial Review) and from O's Definition of Done (no unresolved Critical/High). Every option that would leave Critical/High unresolved is already a "Still requires the Captain" condition. |
| **D6** | **Yes, codify it**, in the same section, and record it as a codification in DECISIONS. One wording choice to flag: you stated the rule for an "injected-only P2". I wrote **"P2 or lower"**, because a P3 can hardly need more than a P2 does. The orchestrator may strike "or lower" if the kickoff text meant P2 only. | The brake's "findings of all three rounds" and the rescope limit both depend on this rule. Without it, two rules would rest on text that exists only in review briefs. |

## 2. Edit blocks (text fragments; the tree is CRLF, so match on the text)

**O, `.github/agents/orchestrator.agent.md`** (adds about 2.8 KB; the measurement line and the template are most of it):

```
<<<<<<< SEARCH
and send Builder hard stops to `claude-architect` through `scripts/claude_architect.py` (see **Delegation and Waiting**).

## Backlog Burn-Down Mode (Standing Order)
=======
and send Builder hard stops to `claude-architect` through `scripts/claude_architect.py` (see **Delegation and Waiting**).

## Review Rounds and Progress (Standing Order)

**Convergence (codified 2026-10-15).** Fix every P1, every finding with ordinary reach and every regression a repair introduced. Record a P2 or lower that only injected faults reach, and that is not a regression, as a follow-up with its reach, under the filing policy in **Backlog Burn-Down Mode**. Every reviewer brief asks for each finding's severity, reach (ordinary or injected-only) and regression flag.

**A round** is one completed Diff Reviewer pass over a frozen candidate: the first review and each repair re-review, delta or whole. Reviewers run in parallel on one candidate count once; a relaunch after a reviewer failed to start or was refused does not count. Each item or slice in a batch keeps its own count.

**Round-three brake (Captain, 2026-10-15).** When round three leaves a finding that convergence says to fix, do not start round four on your own. Make a fresh `--read-only` bridge call with every finding of rounds one to three (severity, reach, regression flag, and fixed, open or recorded), the candidate's `git diff --stat` against its base and that of any unreviewed repair in hand, and the minutes spent building, in each round and in each repair. Ask for one decision, answered as the option, its scope (findings and files) and the reason: **continue** (round four, with that scope), **rescope** (land what has converged and move the remaining findings to the follow-up; never a P1, a regression or a finding that would break the next run) or **split** (land the converged part; the rest becomes a new slice of the same issue, left open, or is filed under the filing policy). Record the decision in the owning issue and follow it. A continue, or a split's review of its reduced candidate, allows one more round; any later round needs a new decision. Measured: BF-892/893 took five rounds and 189 review minutes against 44 build minutes; one round ran 76 minutes.

**Progress comments (Captain, 2026-10-15).** An item's clock starts at its first Architect bridge call or Builder delegation; an overlapped read-only consult does not start it. Check the clock before each delegation or gate and on every wake; set no timer and schedule no post. Two hours after the start, and two hours after each later progress comment, post one on the owning issue (a slice without one: its parent issue; no issue: its PR once open; neither: say so in your report). Skip it when the phase, the work left and the blocker are unchanged since your last one. A session without the start time takes the earliest the worktree proves (its first `logs/architect/` file, its branch's `git reflog`), or posts at once. At most five lines, no findings detail:

```text
Progress <UTC time>, <hours> h since start
Phase: draft | build | review round N | gate | CI
Left: <remaining steps>
Blocker: <none, or one line>
```

## Backlog Burn-Down Mode (Standing Order)
>>>>>>> REPLACE
```

**C, `.github/copilot-instructions.md`** (pointers only; adds about 150 bytes, so C stays far below the 18,000-byte cap):

```
<<<<<<< SEARCH
For findings you are not fixing here, follow the filing policy in **Backlog Burn-Down Mode** (`.github/agents/orchestrator.agent.md`) rather than opening an issue per finding.
=======
Which findings you fix here, which you record, and when to stop after round three: **Review Rounds and Progress** in `.github/agents/orchestrator.agent.md`; file what you record under its **Backlog Burn-Down Mode** filing policy rather than opening an issue per finding.
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
| Orchestration: delegation, waiting, Backlog Burn-Down,
=======
| Orchestration: delegation, waiting, review rounds and progress comments, Backlog Burn-Down,
>>>>>>> REPLACE
```

**`CLAUDE.md`** (step 3):

```
<<<<<<< SEARCH
A repair round re-reviews the delta unless it changes a shared contract (Adversarial Review Before Every Commit).
=======
A repair round re-reviews the delta unless it changes a shared contract (Adversarial Review Before Every Commit). Which findings to fix and the stop after round three: **Review Rounds and Progress** (`.github/agents/orchestrator.agent.md`).
>>>>>>> REPLACE
```

**`.claude/agents/claude-architect.md`** (callee side; the file is force-tracked, so stage it with `git add -f`):

```
<<<<<<< SEARCH
- **Stay within authority.** You may not widen any authority ceiling, waive a gate, weaken a control, or change approval rules, even if asked.
=======
- **Stay within authority.** You may not widen any authority ceiling, waive a gate, weaken a control, or change approval rules, even if asked.
- **Round-three brake.** A brake request (**Review Rounds and Progress**, `.github/agents/orchestrator.agent.md`) gets exactly one of **continue**, **rescope** or **split**, with its scope and reason, inside the limits that section sets on rescope. If every option leaves an unresolved Critical or High defect, that is a Captain condition.
>>>>>>> REPLACE
```

## 3. Tests, in `tests/test_standing_orders_layout.py`

```python
# OWNERS: add
    "Review Rounds and Progress (Standing Order)": ORCHESTRATOR,

# PROCEDURE: append
    "**Convergence (codified 2026-10-15).**",
    "**Round-three brake (Captain, 2026-10-15).**",
    "**Progress comments (Captain, 2026-10-15).**",
    "Phase: draft | build | review round N | gate | CI",

# new constants, after SHARED_RULES
ARCHITECT_PROFILE = _REPO_ROOT / ".claude" / "agents" / "claude-architect.md"
REVIEW_ROUNDS = "Review Rounds and Progress"
BRAKE_OPTIONS = ("**continue**", "**rescope**", "**split**")


def test_review_rounds_pointers_and_brake_options_agree() -> None:
    """C, CLAUDE.md and claude-architect.md point to the review-rounds section by name
    instead of restating it, and both sides of the round-three brake name the same options."""
    pointers = (CONSTITUTION, CLAUDE_MD, ARCHITECT_PROFILE)
    absent = [_rel(path) for path in (ORCHESTRATOR, *pointers) if not path.is_file()]
    assert not absent, f"files are missing: {absent}"
    assert f"{REVIEW_ROUNDS} (Standing Order)" in _headings(ORCHESTRATOR), "the section heading moved"

    unpointed = [_rel(path) for path in pointers if f"**{REVIEW_ROUNDS}**" not in _text(path)]
    assert not unpointed, f"no pointer to **{REVIEW_ROUNDS}** in: {unpointed}"

    orchestrator, architect = _text(ORCHESTRATOR), _text(ARCHITECT_PROFILE)
    missing = {_rel(ORCHESTRATOR): [o for o in BRAKE_OPTIONS if o not in orchestrator],
               _rel(ARCHITECT_PROFILE): [o for o in BRAKE_OPTIONS if o not in architect]}
    assert not any(missing.values()), f"brake options the two sides do not share: {missing}"
```

The premises come first: the files exist and the heading is present. Two more premises are carried by the existing tests: `test_each_section_has_exactly_one_owner` and the ≥200-sentence count in `test_no_sentence_is_duplicated_across_instruction_files`.

**Mutation table** (each row is a single-line edit; the run must fail):

| # | Mutation | Failing test |
|---|---|---|
| M1 | Delete O's `## Review Rounds and Progress (Standing Order)` line | `test_each_section_has_exactly_one_owner`, `test_review_rounds_pointers_and_brake_options_agree` |
| M2 | Paste that heading line into C | `test_each_section_has_exactly_one_owner` |
| M3 | Remove `**Round-three brake (Captain, 2026-10-15).**` from O | `test_orchestrator_profile_carries_the_procedure` |
| M4 | Paste `**Progress comments (Captain, 2026-10-15).**` into C | `test_orchestrator_profile_carries_the_procedure` (repeated) |
| M5 | Change `Phase: draft \| build \| review round N \| gate \| CI` to drop `CI` | `test_orchestrator_profile_carries_the_procedure` |
| M6 | Remove `**Convergence (codified 2026-10-15).**` from O | `test_orchestrator_profile_carries_the_procedure` |
| M7 | Revert C's pointer sentence to the base text | `test_review_rounds_pointers_and_brake_options_agree` |
| M8 | Delete the pointer sentence added to `CLAUDE.md` | `test_review_rounds_pointers_and_brake_options_agree` |
| M9 | Change `**rescope**` to `rescope` in the `claude-architect.md` bullet | `test_review_rounds_pointers_and_brake_options_agree` |
| M10 | Copy O's "Fix every P1, …" sentence into `CLAUDE.md` | `test_no_sentence_is_duplicated_across_instruction_files` |

Focused command: `pytest tests/test_standing_orders_layout.py -v -n 0`.

## 4. Trackers, pins, and what goes to the Captain

**PROGRESS line:**
> **Review rounds and progress comments (2026-10-15) -- the orchestrator stops after three Diff Reviewer rounds and asks the Architect, and posts a short progress comment every two hours; no AD or BF number.** New section `Review Rounds and Progress (Standing Order)` in `.github/agents/orchestrator.agent.md`. It writes down the convergence rule the review briefs already used (fix every P1, every ordinary-reach finding and every regression of a repair; record an injected-only finding that is not a regression as a follow-up). It defines a round. It adds the Captain's round-three brake (a fresh read-only Architect decision: continue, rescope or split; one more round per decision) and his two-hour progress comment (on the owning issue, its parent, or its PR; skipped when nothing changed; no timers). C, `CLAUDE.md` and `claude-architect.md` point to the section. `tests/test_standing_orders_layout.py` pins the owner, the procedure needles and the agreement of the two sides on the three options. Measured: BF-892/893 took five rounds and 189 review minutes against 44 build minutes.

**DECISIONS entry:** `### Review-round brake and progress comments; convergence rule codified (2026-10-15)`
- *Scope.* Standing-order text and its layout test only. Nothing under `src/` or `scripts/`, no automation.
- *Convergence is a codification, not a new rule.* It was used in kickoff text and review briefs but was not written in C or O. Written as "P2 or lower" for injected-only findings.
- *Rescope is a bounded exception to convergence.* The brake fires only when a must-fix finding is still open, so a rescope that could move only recordable findings would never apply. The bound reuses existing limits: never a P1, a regression or a finding that would break the next run (C, Act on the findings), and no unresolved Critical/High (O, Definition of done).
- *Clock and cadence.* The clock starts at the first bridge call or Builder delegation. After the first post, the last comment's timestamp is the clock. A session that has lost the start falls back to the worktree's evidence, or posts at once.
- *Caller and callee.* `claude-architect.md` names the same three options, and a test pins the agreement.

**Hidden pins (checked):**
- Only `tests/test_standing_orders_layout.py` reads O. A search of `*.py` for `orchestrator.agent.md` finds only that file.
- `test_pointer_paths_exist`: the new text adds no backticked `.md` or `.py` path under `.github/`, `.claude/`, `docs/` or `scripts/` that does not resolve; `logs/architect/` does not match `_POINTER`.
- `test_constitution_prefix_delivered_to_the_native_builder`: the C edit comes after the Adversarial Review heading, so the 8,192-byte prefix is unchanged where it matters.
- `test_constitution_stays_slim`: C is about 14.6K + 0.15K, under 18,000.
- The duplicate detector: the pointer sentences in C and `CLAUDE.md` are worded differently from each other and from O.

**Absence verified (2026-10-15):**
- CLAIM: the convergence rule, the brake and progress comments are not yet in the governed files.
- RUN: Grep for `Round-three|Phase: draft|Convergence \(|Progress comments|progress comment|ordinary reach|injected` (case-insensitive) over C, `.github/agents/*.md`, `CLAUDE.md` and the three docs.
- FOUND: one hit, `architecture-reference.md:200` ("injected as SYSTEM CONTEXT"), which is unrelated.
- RUN: Grep of `.claude/agents/claude-architect.md` by direct path (ripgrep's gitignore handling would skip `.claude/`) for `**continue|rescope|split**|Review Rounds|round`.
- FOUND: lines 162 and 209 only ("review rounds" in narrative text).
- HOLDS: yes.

**Not verified:** the BF-892/893 measurement (5 rounds, 189 against 44 minutes, one round of 76) is the Captain's figure as you relayed it. I quote it but did not re-measure it.

**Decisions that need the Captain: none.** Two notes for him after the fact:
1. Convergence is codified, with "P2 or lower" as a clarifying reading of the original wording.
2. Rescope is bounded by the existing blocker and Definition of Done limits. The bound narrows his option, it does not widen it, and without it the option would never apply.

I wrote no memory note.
