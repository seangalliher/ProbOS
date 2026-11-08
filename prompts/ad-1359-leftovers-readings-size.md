# AD-1359: Own leftovers, written readings and a size check, for the dev agents and the crew

Three agent rules (adapted from multica-ai/andrej-karpathy-skills via copilot-forever fa17a51) reach the agents that build ProbOS (#1765) and ProbOS's own engineering crew (#1766). Text only, plus one test and one golden refresh.

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07
**Status:** Ready to build
**Issues:** #1765 (dev agents), #1766 (crew), one batch
**Dependencies:** none
**Estimated tests:** 1 new file (3 cases); 1 fixture refresh
**AD number:** AD-1359. Ceiling AD-1358, agreed by all three sources of `scripts/ad_ceiling.py` (git log subjects, GitHub issue titles all states, `prompts/ad-*.md`), run 2026-11-07 in this worktree.

---

## Problem

The repository already enforces scope (Builder Scope Constraints, each prompt's **What This Does NOT Change**) and proof (verify-first, tests that fail without the change, mutation testing). Three rules have no counterpart (searched by #1765 for orphan, dead code, made unused, simplest, speculative, over-engineer, assumption):

1. **Own leftovers only.** Nothing tells an agent to remove what its change made unused, or to leave other dead code alone and mention it.
2. **Written readings.** The Builder stops and asks on ambiguity (`.claude/agents/claude-builder.md:32,35`; `config/standing_orders/builder.md:9`), but small readings taken where no design choice is involved go unrecorded.
3. **A size check.** Neither Diff Reviewer profile has a size item (`.github/agents/diff-reviewer.agent.md:45-79`, `.claude/agents/claude-diff-reviewer.md:52-86`); the crew's Code Review Checklist has only "Scope discipline" (`config/standing_orders/engineering.md:82`). Today **Convergence** (`.github/agents/orchestrator.agent.md:44`) would repair and re-review every size finding, since each has ordinary reach.

Crew route: AD-1200's instruction discovery skips the installed ProbOS repository (`src/probos/repository_instructions.py:315`), so the crew reads none of the dev files. Its only route is `config/standing_orders/`, composed per billet by `compose_instructions` (`src/probos/cognitive/standing_orders.py:445`): `builder` and `code_reviewer` both map to `engineering` (`standing_orders.py:42-43`), `architect` to `science` (`:52`), and the personal file is `<agent_type>.md` (`:503`). The Visiting Builder composes as `agent_type="builder"` (`src/probos/cognitive/copilot_adapter.py:490-492`).

CodeReviewAgent placement: `_parse_review` (`src/probos/cognitive/code_reviewer.py:140-163`) copies the model's `issues` and `suggestions` lists as given; the model decides the placement from its system prompt, which `review()` composes from the standing orders (`code_reviewer.py:85-88`). So a standing-order line that says "size goes in `suggestions`" is the whole change: **no code change**. A parse-side reclassification is rejected: the parser cannot tell a size finding from any other string.

## Solution

Short additions to nine tracked files and one untracked local file; no source code.

| Rule | Dev agents (#1765) | Crew (#1766) |
|---|---|---|
| 1 leftovers | `.github/copilot-instructions.md`, `claude-builder.md` Scope Constraints | `config/standing_orders/builder.md` |
| 2 readings | `.github/copilot-instructions.md`, `claude-builder.md` report step | `config/standing_orders/builder.md` |
| 3 size | both Diff Reviewer profiles (**Size**, **Assumptions**); orchestrator **Size findings** paragraph; `claude-architect.md` item 4 | `engineering.md` checklist item 13; `architect.md` |

The Engineering Principles caveat (Protocols, storage interfaces, boundary validation, exception tiers are never a size finding) sits in every reviewer-facing and architect-facing rule.

Rejected heavier designs:
- Editing the hardcoded `instructions` of `BuilderAgent` (`builder.py:2095`), `CodeReviewAgent` (`code_reviewer.py:38`) or `_VISITING_BUILDER_INSTRUCTIONS` (`copilot_adapter.py:127`): none contradicts the rules, and the standing orders already reach all three (#1766 "Out of scope").
- A `size` field in `ReviewResult` or a `readings` field in the build output: the issues ask for placement and report text, not a schema.
- A separate AD for #1765: one AD covers the batch; the crew change is the product change.

---

### Section 1: Shared standing order (`.github/copilot-instructions.md`)

SEARCH:
```
| Configuration Standards | Pydantic models, defaults, parse-time validation |

---

## AD and BF Numbering — Hard Rule
```
REPLACE:
```
| Configuration Standards | Pydantic models, defaults, parse-time validation |

**Leftovers and readings (AD-1359, #1765).** Remove the imports, variables, functions and files your change made unused, and only those: leave dead code the change did not create and name it in your report. Where a prompt or issue leaves a detail implicit and no design choice is involved, take the reading that changes least and list it in your report; an ambiguity that needs a design choice still stops for a decision.

---

## AD and BF Numbering — Hard Rule
```

Constraints: `tests/test_standing_orders_layout.py` caps this file at 18,000 bytes (`:61`, 15,520 with CRLF before this change) and forbids any sentence of 60+ characters appearing in two governed files (`:379`). The text above appears in no other governed file; keep it that way in Section 4.

### Section 2: Claude Builder (`.claude/agents/claude-builder.md`)

Tracked by force (`git ls-files .claude/agents` lists it); stage it by name like any tracked file.

2a. SEARCH:
```
6. **Update trackers** as specified in the prompt's Tracking section.
7. **Report test count** at each step.
```
REPLACE:
```
6. **Update trackers** as specified in the prompt's Tracking section.
7. **Report test count** at each step.
8. **Report readings and leftovers.** Your final report lists, one line each, every reading you took where the prompt left a detail implicit and no design choice was involved (the reading, and the one you rejected), and the dead code you noticed and left alone. A gap that needs a design choice is not a reading: stop and ask.
```

2b. SEARCH:
```
- Do NOT refactor adjacent code for "improvement." Stay within the boundary of the prompt.
- If the prompt is ambiguous, **stop and ask** — do not guess.
```
REPLACE:
```
- Do NOT refactor adjacent code for "improvement." Stay within the boundary of the prompt.
- Remove what your own change made unused (imports, variables, functions, files), and nothing else. Leave dead code you did not create and list it in your report.
- If the prompt is ambiguous, **stop and ask** — do not guess.
```

### Section 3: Both Diff Reviewers (`.github/agents/diff-reviewer.agent.md`, `.claude/agents/claude-diff-reviewer.md`)

Apply the same edit to both files (their Reach blocks are identical).

SEARCH:
```
- If the change is gated by a flag or config, does the documented combination of
  flags actually work?

## Output
```
REPLACE:
```
- If the change is gated by a flag or config, does the documented combination of
  flags actually work?

**Size**
- Is there code the issue and prompt do not need: an option or setting nobody
  asked for, a helper with one caller, handling for a case that cannot occur, a
  change to neighbouring code, or something this change made unused and left
  behind? Name the lines to delete and label the finding **size**. It is not a P1
  unless the extra code itself breaks something.
- Structure the Engineering Principles require (Protocol interfaces, abstract
  storage interfaces, validation at every boundary, the exception-handling tiers)
  is never a size finding.

**Assumptions**
- Does each reading in the Builder's report fit the prompt and the code? A
  reading that changes what the prompt asks for, or settles a design choice, is a
  finding.

## Output
```

### Section 4: Orchestrator review loop (`.github/agents/orchestrator.agent.md`, **Review Rounds and Progress**)

Insert one paragraph between **A round** (line 46) and **Round-three brake** (line 48).

SEARCH:
```
Reviewers run in parallel on one candidate count once; a relaunch after a reviewer failed to start or was refused does not count. Each item or slice in a batch keeps its own count.

**Round-three brake (Captain, 2026-10-15).**
```
REPLACE:
```
Reviewers run in parallel on one candidate count once; a relaunch after a reviewer failed to start or was refused does not count. Each item or slice in a batch keeps its own count.

**Size findings (AD-1359, #1765).** A finding the Diff Reviewer labels size follows this rule instead of the ordinary-reach rule in **Convergence**, unless the extra code breaks something. Leftovers the change itself made unused are deleted in any round. Other size findings are deleted in round 1, in the same Builder delegation as that round's other repairs; from round 2 on they go to the follow-up under the filing policy. When a deletion is the round's only repair and removes only code this change added that nothing references, run the focused tests and start no further review round. Any other size repair, such as reverting a change to neighbouring code, gets a delta review, which counts as a round. The round-three brake below is unchanged.

**Round-three brake (Captain, 2026-10-15).**
```

The SEARCH's last line is a prefix of line 48; the REPLACE keeps that line byte-identical, so the brake paragraph and its `PROCEDURE` needles (`test_standing_orders_layout.py:100-128`) are untouched.

### Section 5: Claude Architect (`.claude/agents/claude-architect.md`, Prompt Drafting Standards)

SEARCH:
```
4. **Solution** — overview before implementation.
```
REPLACE:
```
4. **Solution** — overview before implementation. Choose the smallest design that settles the issue, and list each heavier design you rejected in one line (what it would add, why the issue does not need it). Structure the Engineering Principles require is not weight to cut.
```

### Section 6: Crew Software Engineer (`config/standing_orders/builder.md`)

Line 9 (ask rather than guess) stays byte-identical. *Superseded by Amendment 1.*

SEARCH:
```
- Every file you write must have a clear purpose. No scaffolding, no boilerplate for its own sake.
```
REPLACE:
```
- Every file you write must have a clear purpose. No scaffolding, no boilerplate for its own sake.
- Remove the imports, variables, functions and files your own change made unused. Leave dead code you did not create and mention it in your report; a file outside your spec's footprint is reported, not removed.
- Where the spec leaves a small detail implicit and no design choice is involved, take the reading that changes least and list it in your report. Anything that needs a design choice is still an ambiguity: ask.
```

The footprint clause keeps rule 1 consistent with "You do NOT modify files outside your build spec's file footprint" (`builder.md:47`) and `BuilderAgent`'s "Do NOT modify files that aren't listed in target_files" (`builder.py:2110`).

### Section 7: Crew Code Review Checklist (`config/standing_orders/engineering.md`)

SEARCH:
```
12. Principles compliance — verify against the ProbOS Principles Stack
```
REPLACE:
```
12. Principles compliance — verify against the ProbOS Principles Stack
13. Size — no code the spec does not need: an unrequested option, a single-use helper, handling for a case that cannot occur, a change to neighbouring code, or a leftover the change made unused. Structure the Principles Stack requires (Protocol interfaces, abstract storage interfaces, boundary validation, the log-and-degrade tiers) is never a size finding. Report size in `suggestions`, never in blocking `issues`, unless the extra code breaks something.
```

Item 13 ends the file's checklist; keep the file's trailing newline as it is.

### Section 8: Crew Architect (`config/standing_orders/architect.md`)

SEARCH:
```
- Prefer extension over modification. New modules over changed core files.
```
REPLACE:
```
- Prefer extension over modification. New modules over changed core files.
- Specify the smallest design that settles the spec. Name each heavier design you rejected in one line and why it is not needed; structure the Engineering Principles require is not weight to cut.
```

### Section 9: Tests

New file `tests/test_ad1359_agent_size_rules.py`, exactly one parametrized test over the three billets. It asserts the **composed** text, not the file:

```python
"""AD-1359 (#1766): the composed instructions of the Builder, Code Review and Architect billets carry the new rules."""

from __future__ import annotations

import pytest

from probos.cognitive.builder import BuilderAgent
from probos.cognitive.code_reviewer import CodeReviewAgent
from probos.cognitive.standing_orders import clear_cache, compose_instructions


@pytest.mark.parametrize(
    ("agent_type", "hardcoded", "required"),
    [
        (
            "builder",
            BuilderAgent.instructions,
            (
                "your own change made unused",
                "take the reading that changes least and list it in your report",
                "If something is ambiguous, ask for clarification rather than guessing.",
            ),
        ),
        (
            "code_reviewer",
            CodeReviewAgent.instructions,
            (
                "13. Size — no code the spec does not need",
                "is never a size finding",
                "Report size in `suggestions`, never in blocking `issues`",
            ),
        ),
        (
            "architect",
            "",
            ("Specify the smallest design that settles the spec.",),
        ),
    ],
)
def test_composed_billet_instructions_carry_the_rules(
    agent_type: str, hardcoded: str, required: tuple[str, ...],
) -> None:
    clear_cache()
    composed = compose_instructions(agent_type=agent_type, hardcoded_instructions=hardcoded)
    missing = [text for text in required if text not in composed]
    assert not missing, f"{agent_type}: composed instructions lack {missing}"
```

The builder case also pins the unchanged (*superseded by Amendment 1*) ambiguity rule (#1766 acceptance 1). Each case fails on the base (the new text is absent); confirm once by stashing Sections 6 to 8 and running it.

Check before writing it: `BuilderAgent` and `CodeReviewAgent` expose `instructions` as class attributes (`builder.py:2095`, `code_reviewer.py:38`) and `clear_cache` is public (`standing_orders.py:312`). If composing raises on a real crew profile or a template brace, stop and report; do not catch it.

### Section 10: Refresh the AD-1152 golden (`tests/fixtures/ad1152_agentic_off_golden.json`)

`test_default_off_matches_pinned_base` (`tests/test_ad1152_agentic_correlation.py:523-533`) pins the native builder's composed system prompt, which embeds `engineering.md` and `builder.md` verbatim (once each; checked 2026-11-07). Sections 6 and 7 change both, so the golden's text and its `observation_sha256` must be refreshed, as AD-1270 slice 4c did for `default_config_sha256` (commit 9d71e934). `architect.md` is not in it.

Use a throwaway script in the session scratchpad (never committed) that:
1. Loads the golden with `json.loads`.
2. For each of `config/standing_orders/builder.md` and `engineering.md`: `old = git show HEAD:<path>` and `new = Path(<path>).read_text(encoding="utf-8")`, each with `\r\n` → `\n` and `.strip()` (what `_load_file` returns, `standing_orders.py:156`).
3. Replaces `old` with `new` in every string value of the tree, asserting the total count of replacements is exactly 1 per file.
4. Sets `golden["observation_sha256"] = sha256(json.dumps(golden["observation"], ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()` (the test's `_json_bytes`, `:59-60`).
5. Writes `json.dumps(golden, indent=2, ensure_ascii=True) + "\n"` with `newline="\n"` (this reproduces the current file byte for byte after LF normalisation; checked 2026-11-07).

Then `git diff --stat` on the golden must show only line 760 and line 15 changed. Leave `base_commit`, `base_source_blobs` and `default_config_sha256` alone.

---

## Amendments after review

**Amendment 1 (review rounds 1-2, 2026-11-07).** The candidate departs from Sections 1-9 and the DECISIONS draft above as follows; the staged files are authoritative.
- *Ambiguity (round 1, B1).* "Stop and ask" contradicted the readings rule. Its trigger is now a gap that needs a design choice: `claude-builder.md` Scope Constraints reads "If the prompt is ambiguous where a design choice is needed, **stop and ask** — do not guess. A small implicit detail with no design choice takes the reading that changes least, listed in your report (step 8)."; crew `builder.md:9` reads "If something is ambiguous where a design choice is needed, ask for clarification rather than guessing."; the Section 9 test string follows it. Crew `builder.md`'s readings bullet adds "A spec reference the live code contradicts is not a reading: flag it." (round 2, F3).
- *Review loop (round 1, S1-S4; round 2, F2, F4).* Every reviewer brief asks for a **size** tag and passes the Builder's readings; both reviewer Output sections ask for the tag; a finding is size only if every reviewer reporting it tags it so. The no-review path covers only deleted imports or call-free bindings the change added that nothing references (diff `+` lines, repo-wide `git grep`), in review rounds only; a deleted `def`, class, decorator or call is reviewed, and gate or CI repairs follow the brake. `.github/copilot-instructions.md`'s repair-round paragraph names the exception.
- *Crew residual (round 1, S5).* Nothing reads crew `suggestions` or the crew Builder's prose yet; recorded in DECISIONS and PROGRESS as a follow-up source change.

## Focused test command

The shared venv imports `D:\ProbOS\src`, not the worktree (checked: `probos.__file__` → `D:\ProbOS\src\probos\__init__.py`). Point it at the worktree's source:

```
cd D:/ProbOS-worktrees/agent-rules-1765-1766
PYTHONPATH=D:/ProbOS-worktrees/agent-rules-1765-1766/src d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1359_agent_size_rules.py tests/test_ad1152_agentic_correlation.py tests/test_standing_orders_layout.py tests/test_standing_orders.py tests/test_code_reviewer.py tests/test_bf910_standing_orders_lookup.py -q -n 0
```

Base (2026-11-07, without the new file and without `test_bf910`): 82 passed. Without `PYTHONPATH` the AD-1152 golden fails with `KeyError: 'agent_work_routine_decider'` (stale main-checkout source); that is environmental, not this change.

## Post-merge local step (main session, not the Builder)

`.claude/agents/builder.md` (the Copilot Builder) is gitignored and untracked (`UNTRACKED_LOCAL`, `test_standing_orders_layout.py:147`). The Builder must not create, edit or force-add it in the worktree. After the PR merges, the main session applies Section 2's two edits, plus review round 1's narrowing of the ambiguity line (copy the final step 8 and Scope Constraints text of `claude-builder.md`), to `D:/ProbOS/.claude/agents/builder.md`; its anchors match (`builder.md:19-20` steps 6-7, `:28-29` the last two Scope Constraints, read 2026-11-07). Then it comments on #1765: "Applied AD-1359 Section 2a and 2b to the local Copilot `.claude/agents/builder.md` on <date>", with the `git diff --no-index` of the two lines or a quoted excerpt.

## What This Does NOT Change

- No source code: `code_reviewer.py` (`_parse_review` and the hardcoded `instructions`), `builder.py`'s `BuilderAgent.instructions`, `copilot_adapter.py`'s `_VISITING_BUILDER_INSTRUCTIONS`, `standing_orders.py`, `repository_instructions.py`.
- `docs/development/engineering-principles.md` and the Principles Stack section of `engineering.md`.
- **Convergence**'s text, the **Round-three brake**, the gate, the review approve/block logic.
- The Copilot Architect profile (`.claude/agents/architect.md`, untracked) and any other untracked profile besides the post-merge step above.
- `docs/development/architect-standards.md` (#1765 places the drafting rule in `claude-architect.md`).
- `config/system.yaml` (dirty in the main checkout; not in this worktree's change).

## Tracking

- `PROGRESS.md`: new paragraph at the top (above line 3):
  `**AD-1359 (2026-11-07), #1765 #1766 -- agents clean up only their own leftovers, write down small readings, and reviewers check size.** The dev agents (shared standing order, Claude Builder, both Diff Reviewers, the orchestrator's review loop, the Claude Architect) and the crew's standing orders (Software Engineer, Code Review Checklist item 13, Architect) gain three rules adapted from multica-ai/andrej-karpathy-skills: remove only what the change made unused; list small readings in the report while ambiguity still stops; flag code the spec does not need, never the structure the Engineering Principles require. Size findings are deleted in round 1 (leftovers in any round) and deferred after; a deletion-only repair of the change's own unreferenced code needs no review round. The Code Review Agent puts size in `suggestions` by its standing order, with no code change. New test: tests/test_ad1359_agent_size_rules.py; AD-1152 golden refreshed for the two crew files.`
- `DECISIONS.md`: insert after the AD-1358 S1 entry (after line 1490, before `### AD-1346 M3e4d9`):

```
### AD-1359 -- Agents clean up only their own leftovers, write down small readings, and reviewers check size (2026-11-07, #1765, #1766)

- *Scope.* `.github/copilot-instructions.md`, `.github/agents/orchestrator.agent.md` (**Size findings**), `.github/agents/diff-reviewer.agent.md`, `.claude/agents/claude-builder.md`, `.claude/agents/claude-diff-reviewer.md`, `.claude/agents/claude-architect.md`; `config/standing_orders/builder.md`, `engineering.md` (checklist item 13), `architect.md`; `tests/test_ad1359_agent_size_rules.py`; the AD-1152 golden. Contract `prompts/ad-1359-leftovers-readings-size.md`.
- *Source.* Andrej Karpathy's observations on LLM coding mistakes as written up in multica-ai/andrej-karpathy-skills, adapted through copilot-forever fa17a51. Of its four principles, staying in scope and proving the result were already covered; leftovers, readings and size were not.
- *SR1 (exception).* Structure the Engineering Principles require (Protocol interfaces, storage interfaces, boundary validation, the exception tiers) is never a size finding. Rejected: a plain copy of "no abstractions, no error handling for impossible cases", which contradicts them.
- *SR2 (review loop).* Leftovers the change made unused are deleted in any round; other size findings in round 1 only, then the follow-up. A deletion-only repair of the change's own unreferenced code runs the focused tests with no review round; any other size repair is a delta review and counts as a round. The round-three brake is unchanged.
- *SR3 (crew route).* Standing orders only: AD-1200's discovery skips the installed ProbOS repository. The Code Review Agent places size in `suggestions` because its composed standing orders say so; `_parse_review` already copies the model's lists. Rejected: hardcoded instruction edits (none contradicts the rules); a parse-side reclassification.
- *Ambiguity.* "Stop and ask" is unchanged (*superseded by Amendment 1*) for the dev Builder and the crew; a written reading covers only a detail where no design choice is involved.
- *Local step.* The untracked Copilot `.claude/agents/builder.md` gets the same edits after merge, recorded on #1765.
- *Reversal.* Revert the AD-1359 commit and re-apply the previous golden.
```

- `docs/development/roadmap.md`: none (no BF).
- Closure: the PR closes #1766. It references #1765 without closing it; the main session closes #1765 after the post-merge local step's comment and the measurement comment (review rounds per item and lines changed per commit over the next three batches against the previous three), per #1765's last two acceptance boxes.

## Acceptance Criteria

- [ ] Sections 1-8 applied verbatim; ambiguity lines as amended by Amendment 1.
- [ ] Both Diff Reviewer profiles and `engineering.md` item 13 say Engineering-Principles structure is never a size finding.
- [ ] The orchestrator's **Size findings** paragraph adds no review round for a deletion-only repair of the change's own unreferenced code.
- [ ] `test_ad1359_agent_size_rules.py` passes and fails on the base; the AD-1152 golden passes after Section 10; the layout tests pass (byte cap, no duplicated sentence).
- [ ] DECISIONS and PROGRESS entries added.
- [ ] Staged by name only: the eight edited files, the new test, the golden, the two tracker files and this prompt. Never `git add -A`; never stage `.claude/agents/builder.md`.
- [ ] Builder report lists its readings and any dead code noticed (Section 2a applies to this build too).
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-11-07)

Worktree `D:/ProbOS-worktrees/agent-rules-1765-1766`, base `origin/main` 46950c39.

```
grep -n "Configuration Standards" .github/copilot-instructions.md
  80: | Configuration Standards | Pydantic models, defaults, parse-time validation |
  84: ## AD and BF Numbering — Hard Rule
wc -c .github/copilot-instructions.md            15520
grep -n "CONSTITUTION_CAP_BYTES = \|def test_no_sentence_is_duplicated\|UNTRACKED_LOCAL = " tests/test_standing_orders_layout.py
  61, 379, 147
grep -n "Report test count\|If the prompt is ambiguous\|refactor adjacent" .claude/agents/claude-builder.md
  26: 7. **Report test count** at each step.   34: Do NOT refactor adjacent ...   35: If the prompt is ambiguous ...
grep -n "flags actually work\|^## Output" .github/agents/diff-reviewer.agent.md .claude/agents/claude-diff-reviewer.md
  diff-reviewer.agent.md:79,81   claude-diff-reviewer.md:86,88
grep -n "Convergence (codified\|^\*\*A round\*\*\|Round-three brake (Captain" .github/agents/orchestrator.agent.md
  44, 46, 48
grep -n "4. \*\*Solution\*\*" .claude/agents/claude-architect.md      241
git ls-files .claude/agents      claude-architect.md, claude-builder.md, claude-diff-reviewer.md
grep -n "ambiguous\|Every file you write\|outside your build spec" config/standing_orders/builder.md   9, 11, 47
grep -n "Scope discipline\|Principles compliance" config/standing_orders/engineering.md   82, 88
grep -n "Prefer extension over modification" config/standing_orders/architect.md          9
grep -n "\"builder\"\|\"code_reviewer\"\|\"architect\"" src/probos/cognitive/standing_orders.py   42, 43, 52
grep -n "def compose_instructions\|def clear_cache\|agent_text = _load_file\|text = path.read_text" src/probos/cognitive/standing_orders.py   445, 312, 503, 156
grep -n "instructions = \|compose_instructions(\|result.issues = \|result.suggestions = " src/probos/cognitive/code_reviewer.py   38, 85, 149, 150
grep -n "instructions = \"\"\"You are the Builder\|aren't listed in target_files" src/probos/cognitive/builder.py   2095, 2110
grep -n "_VISITING_BUILDER_INSTRUCTIONS = \|agent_type=\"builder\"" src/probos/cognitive/copilot_adapter.py   127, 491
sed -n 315p src/probos/repository_instructions.py   (_installed_repository skip, per #1765 correction comment)
grep -n "def _json_bytes\|def test_default_off_matches_pinned_base" tests/test_ad1152_agentic_correlation.py   59, 523
golden: "Code Review Checklist", "Scope discipline", "Quality Gates" each occur once; "Prefer extension" 0
golden re-serialises byte-identical as json.dumps(indent=2, ensure_ascii=True)+"\n" after CRLF->LF
D:/ProbOS/.claude/agents/builder.md   20: 7. **Report test count**   28-29: same two Scope Constraint lines as claude-builder.md
```

## Absence Verified (2026-11-07)

```
CLAIM: no other test or fixture pins the text of builder.md, engineering.md or architect.md
RUN:   Grep "Design for what exists|Understand the spec before you build|Pattern adherence" outside prompts/ and config/
FOUND: tests/fixtures/ad1152_agentic_off_golden.json only
HOLDS: yes (Section 10 refreshes it); other tests name these files only as paths or write tmp copies
       (test_ad1344:162, test_bf894:32, test_bf910 reads the live file dynamically at 803, 1287)

CLAIM: no test pins the content of the claude-* profiles or diff-reviewer.agent.md beyond the layout tests
RUN:   Grep "claude-architect\.md|claude-builder\.md|claude-diff-reviewer\.md|diff-reviewer\.agent\.md" tests/
FOUND: test_claude_architect_bridge.py:44,213 (writes its own tmp copy), test_standing_orders_layout.py:141,153,437,470,520
HOLDS: yes; layout tests read front matter, the review-rounds pointer and brake options, all unchanged

CLAIM: no code_reviewer.md personal standing order exists
RUN:   Glob config/standing_orders/code_reviewer.md
FOUND: nothing; the Code Review billet reads engineering.md as its department tier
```

## Prior Art and Blind Spots

- **multica-ai/andrej-karpathy-skills** (fetched 2026-11-07): four principles (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution). Adapted: Surgical Changes' "remove only the orphans your own changes create" (rule 1), Think Before Coding's stated assumptions (rule 2, narrowed so ProbOS's stop-and-ask stays), Simplicity First (rule 3). Rejected: its unconditional "no abstractions for single-use code" and "no error handling for impossible scenarios", which collide with the Principles Stack; hence the exception in every size rule. Goal-Driven Execution is already covered by tests-that-fail-first.
- **copilot-forever fa17a51**: wording reference. Adapted its review-rounds size rule, including the two fixes its history records (a deletion-only round must have a reachable outcome; the no-review path must exclude reverts of neighbouring code). Not adopted: its "simplest code" Scope bullet for the Builder (ProbOS builds from exact prompts, so the leverage is the Architect's item 4) and its plan-level Assumptions section (no PLAN.md here).
- **Reference projects** (`docs/research/reference-projects.md`, judged 2026-11-07): relevant harness rows Claude Code (2026-10-16), Aider (2026-10-18), SWE-agent (2026-11-02) are within their 90-day interval; none overdue, none examined. No row updates.
- **Blind spots.** (a) The AD-1152 golden embeds the crew files: handled in Section 10. (b) The shared venv imports the main checkout: handled in the focused command. (c) The crew BuilderAgent emits file changes, not a prose report, so rule 2's "report" lands wherever its build narrative goes; a schema field is deferred unless measurement shows readings are lost. (d) A leftover deletion of pre-existing code in round 3 needs a delta review and so meets the brake; deliberately unchanged per #1765. (e) Every added standing-order line is paid per crew call: about 1 KB across three crew files, kept to one line per rule.
