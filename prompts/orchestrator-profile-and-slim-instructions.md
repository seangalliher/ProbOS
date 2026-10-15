# Build contract: the ProbOS Orchestrator profile and a slimmer injected instruction file (v2)

**Drafted by:** claude-architect (read-only consult; saved verbatim by the orchestrator)
**Revised by:** claude-architect (Claude Code, Opus 5.5), 2026-10-15, read-only refresh against `579b5530`
**Revision note (2026-10-15, build):** the M3 Builder's hard stop on T3 showed v2 had conflated AD-1200's per-file cap (`INSTRUCTION_FILE_BYTES = 8192`) with the whole-addendum cap (32,768); claude-architect ranked the options (A: pin the prefix), supplied the replacement T3 and mutants M15 to M17, and corrected Verdict 1, H4, table (d), the guardrail row, the blind spot, the Diff Reviewer brief and acceptance 3 (applied by the orchestrator; follow-ups F8 to F10). V2 (the Copilot CLI injection experiment) also showed that the CLI refuses every explicit model name (even `gpt-6-luna`, which `auto` resolved to), so the profile's `model` could not be verified there; the contract's own fallback `"Claude Sonnet 5.5 (copilot)"` (the VS Code qualified display name, as in `diff-reviewer.agent.md`) is pinned instead of `claude-sonnet-5.5`, and the Captain confirms it in the picker at kickoff.
**Status:** build-ready. The sequencing condition is gone: the wall-clock PR is in `579b5530` (merge `7301f647`), so hidden pin H1 is resolved.
**Base measured:** `579b5530`. The anchors are headings and text fragments, not line numbers. The line numbers below are for orientation only.
**AD/BF:** none allocated. This is standing-order and docs work, and Delegated authority item 5 allocates a number only when the work needs one. `ad_ceiling.py` was not run.
**Estimated tests:** 1 new file with about 15 tests, plus 1 updated file (`test_ad1231`).

## What changed from v1

1. **Base moved from `12183fb5` to `579b5530`.**
   - `3a0d22d0` has the same content as `12183fb5` (both are "repair review round 1", with identical stats), so it changes nothing here.
   - `7301f647` brings in `1dcc9b20`. Net change to the injected file: Burn-Down Reporting (L115) gains the "decided by the Architect" and "needs the Captain" lines, and Delegated AD gains the paragraph **"Route decisions through the Architect, not the Captain (Captain, 2026-10-14)"** (L140).
   - Every line from L140 on moved down by 2. The section map now uses current line numbers.
2. **The routing paragraph and the parking and reframing rules move to O, word for word, inside Delegated AD Execution Mode** (L140 and L151). No new manifest entry is needed, because they move with their section.
   - v1's Absence row 3 ("not verbatim text") is now false. It is replaced by a presence check, and T9 pins the paragraph.
3. **New E7 edit.** `claude-architect.md:51` (the new "Decision Requests from the Orchestrator" section) cites the Delegated AD envelope in C. It is retargeted to O.
   - The BF bullet moved from `:161` to `:171`, and the acceptance line from `:237` to `:247`.
4. **T12 had a false positive.** Its bare substring `probos-architect` matches `claude-architect.md:301` (`/memories/probos-architect-learnings.md`). It now uses bounded patterns, and the new test T12a pins them.
   - v1 missed this because a ripgrep search from the repository root skips the tracked `.claude/` files (`.gitignore` excludes `.claude/`). New hidden pin H15.
5. **Two existing citations v1 missed.** Both are left unchanged, and the reasons are recorded under E8.
   - `tests/test_ad1203_trace_routes.py:9`: a docstring citing the API-test rule.
   - `.github/agents/diff-reviewer.agent.md:102`: "never read `.github/copilot-instructions.md` whole".
6. **Sizes.** Before is now 79,625 bytes. The profile estimate rises to about 25,950 bytes. The saving per call stays about 9.7K tokens, about 2.3% of the 426K median.
7. **V2 location.** `injection_check.py` lives only in `D:\ProbOS-worktrees\proc-20261014-a28fa315\logs\architect\`. Copy it into the build worktree's `logs/architect/`.
8. **Tests and mutants.** T9 gains three anchors and T12a is new. Mutants M13 and M14 are added.
9. **Settled questions stand.** Nothing in the three commits invalidates Q1–Q13. Q7 (the caller's side in O, the callee's side in `claude-architect.md`) now also covers the new pair: L140 is the caller's rule, and `claude-architect.md` "Decision Requests from the Orchestrator" is the callee's.

## Verdict

**Build it as one PR with two slices.**
- **Slice A:** create the profile, slim the injected file, create the moved docs, update every reference, add the guard tests.
- **Slice B:** retire the Supervised Worker profiles.

Two findings still change the scope (unchanged from v1):

1. **Slimming changes what ProbOS's own builder sees, but not how much.** AD-1200 reads at most `INSTRUCTION_FILE_BYTES` (8,192) of each instruction file (`file_access.py:231`) and renders it as a typed `truncated`/`prefix` frame. `MAX_RENDERED_BYTES` (32,768) caps the whole addendum, not one file. At the base, the 8,192-byte prefix of the 79 KB file covered Repository Context, How You Should Operate, Current State, the Evidence Standard and the start of Adversarial Review. After the split, the 8,192-byte prefix of C (about 14.6 KB) covers the title, the routing lines, the same sections and the start of Adversarial Review; Engineering Principles and everything after it are cut. The mechanism and the delivered sections do not change. T3 pins the prefix and the sections inside it. (Corrected after the M3 Builder's hard stop: v2 had conflated the two caps and said the whole slim file is delivered; see Revision note.)
2. **The acceptance line must keep resolving.** About 800 prompts, `repair_brief.py:245-246` and 6 docs say "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`". So C keeps a heading named `## Building: Engineering Principles (Standing Order)`, with an index and a link to the full text. No prompt, `src/` file or fixture changes.

**Honest expectation on cost.** For an orchestrator the injected text falls from 79,625 to about 40,950 bytes. That is about 9.7K tokens per call, roughly 2.3% of the 426K median. The large lever remains a fresh session per item, which this profile makes practical.

---

## Verified Against Codebase (2026-10-15, HEAD `579b5530`)

| Claim | Command | Result |
|---|---|---|
| Changes on the profile surface since the base | `git log --oneline 12183fb5..579b5530 -- .github CLAUDE.md .claude`; `git show --stat` | `7301f647` (merge), `3a0d22d0` (same stats as `12183fb5`, also a child of `9372f70d`), `1dcc9b20` |
| Net change in the injected file | `git diff -U1 12183fb5 579b5530 -- .github/copilot-instructions.md .claude/agents/claude-architect.md` | C: L115 Reporting extended; L140 routing paragraph added (+2 lines). `claude-architect.md`: +10 lines at `:46-55` ("Decision Requests from the Orchestrator") |
| `CLAUDE.md`, the other profiles, `src/`, cited docs and `mkdocs.yml` unchanged | `git diff --stat 12183fb5 579b5530 -- …` | Only DECISIONS, PROGRESS, `ad-ledger-snapshot.json` and `open-ads-report.md` changed; none of them is cited |
| Section anchors | Grep `^#{1,3} ` in C | 1 Title · 5 Operate · 13 Current State · 23 Evidence · 39 Adversarial · 61 Delegation · 85 Burn-Down (89/99/113/117) · 123 Delegated AD · 155 Engineering Principles (159 SOLID … 190 Testing Standards … 258 Configuration) · 266 Review Checklist · 283 Common Review Flags · 312 Prompt Drafting · 327 AD Numbering · 333 Strategy · 342 Repository Boundary · 360 Architecture Reference · 381 Design Principles · 413 HXI · 582 duplicate AD Numbering |
| Separators | Grep `^---` | 21, 37, 59, 83, 121, 153, 264, 358 |
| File sizes | `wc -l -c` | C 590 lines / 79,625 bytes; `CLAUDE.md` 52 / 7,522; `claude-architect.md` 321 / 26,292; `claude-builder.md` 177 / 11,053; `claude-diff-reviewer.md` 107 / 5,800 |
| Changed section sizes | `head -n 152 … \| tail -n 30 \| wc -c`; `head -n 122 … \| tail -n 38 \| wc -c` | Delegated AD (L123–152) 5,757; Burn-Down (L85–122) 4,086. Together +1,350 of the +1,357 file delta. |
| CRLF | `git ls-files --eol` | C, `CLAUDE.md`, `diff-reviewer.agent.md`, `claude-architect.md`: `i/lf w/crlf` |
| Every manifest anchor matches exactly one line | Grep with `-o` (anchors) | `**Building mode** -- When asked` 9 · `This file contains **durable architectural knowledge**` 15 · `**Act on the findings before committing.**` 53 · `**Brief template (both roles).**` 73 · `**Reading rule (every role, the orchestrator included).**` 74 · `Work in progress is limited to **one issue**` 91 · `- **Test gates**: The Builder runs focused tests` 193 · `- **Batched execution (Captain, 2026-08-25` 195 · `- **HXI emoji violation**` 300 · `## ProbOS Architecture Reference` 360 · `All changes are tracked by AD number` 584 · `Each AD should be a single, testable change.` 590 |
| Every rewrite fragment sits in its anchor line | Grep with `-o` (fragments) | `design principles below,` 9 · `that changes rarely.` 15 · `in **Backlog Burn-Down Mode** below` 53 · brief-template fragment 73 · both reading-rule fragments 74 · `(see **Batched execution** under Testing Standards)` 91 · `o not re-run each milestone's tests yourself.` and ` with the focused command below ` 193 · `(defined under **Adversarial Review Before Every Commit**)` 195 · `per HXI Design Principle #3.` 300 · ` Before proposing ANY new AD:` 584 · `**Never guess. Never assume. Never reuse.** ` 329 and 590. For R12 it is unique within anchor line 590, which is what the verifier checks. |
| The focused command lives in Testing Standards | Read L204 | `- **Run focused tests with**: \`d:/ProbOS/.venv/Scripts/pytest.exe <test-files-or-node-ids> -q -n 0 -p no:randomly\`` (moves to EP, so R7's EP line "below" still holds) |
| AD rule text | Read L327–331, L582–590 | L329 "Before proposing ANY new AD, read PROGRESS.md…"; L331 "**Do not take the number from…**"; L585–588 are the four steps |
| L325 bullet | Grep `Prompts from the Claude Architect` | 325, ending "(see **Delegation and Waiting**)" |
| Routing and parking text | Read L140, L142, L151 | L140 `**Route decisions through the Architect, not the Captain (Captain, 2026-10-14).**` · L142 `**Still requires the Captain.**` · L151 "Before parking, ask whether the blocking requirement itself can be narrowed or reframed … (#1239 lesson, 2026-10-11)." |
| T9 and T10 anchors | Grep with `-o` | `scripts/claude_architect.py --task-file` 63 · `Start-Sleep -Seconds 270` 79 · `Discovery budget` 111 · `decided by the Architect` 115, 140 · `**Still requires the Captain.**` 142 · `Freeze the batch, then run ONE full repository gate` 195 · `scripts/run_test_gate.py --label <issue-or-wave> --receipt` 196 · `Claims that something does NOT exist…` 25 · ``run the `Diff Reviewer` subagent on the staged diff`` 41 · `scripts/ad_ceiling.py` 135 (→ O) and 331 (stays in C) · `How the product makes money` 348 |
| Product injection unchanged | Grep `copilot-instructions` in `src` | `repository_instructions.py:251` (`names.append(".github/copilot-instructions.md")`). File unchanged since the base, so the `MAX_RENDERED_BYTES = 32768`, `_content_prefix` and `delivery` anchors from v1 still hold. Per-file read cap: `file_access.py:231` `INSTRUCTION_FILE_BYTES = 8192`; `:697` `payload = data[:INSTRUCTION_FILE_BYTES]`. Probe `probe_ad1200_delivery`, 2026-10-15: base 79,035 bytes and slim C 14,639 bytes both render as `truncated`/`prefix`, 8,192 bytes delivered. |
| Acceptance line in product code | Grep in `src` | `repair_brief.py:245` "compliance with the Engineering Principles", `:246` the path |
| Tests that read or cite the file | Grep `copilot-instructions` in `tests` (now includes `test_bf891`–`bf894`, `test_expansion_agents` and the others added since the base) | Reads the real file: only `test_ad1231…:40` (`_INSTRUCTIONS`), `:121` (`"1. **Agent-native OS"`). Synthetic tmp files: `test_ad1200_repository_instructions.py:153,184,227,229,266,289`; `…_wire.py:462`. Synthetic events: `test_measure_agent_token_usage.py:65,66,156,267,268,272`. Docstring only: `test_ad1203_trace_routes.py:9` (new to this list; it was already present at the base). |
| Tests citing moved headings | Grep section names in `tests`, `scripts`, `src`, `.github/agents`, `.github/workflows`, `prompts/BUILDER-EXECUTION-PLAN.md`, `CLAUDE.md` | `CLAUDE.md:21` (Adversarial Review, stays in C), `CLAUDE.md:46` (Delegation), `BUILDER-EXECUTION-PLAN.md:235` (Burn-Down). None in `tests`, `scripts` or `src`. |
| Claude-side citations | Grep explicit `path: .claude/agents` | `claude-architect.md:13` (reading list, "about 70K"), `:28` (envelope), `:51` (**new**: "Still requires the Captain" in C), `:171` (BF bullet), `:247` (acceptance line). `claude-builder.md:12`. `claude-builder.md:171` and `claude-architect.md:32` name their own sections, not citations. |
| `CLAUDE.md` citations | Grep | `:3`, `:20` (Testing Standards), `:23` (`Testing Standards, Batched execution`), `:33`, `:46` (Delegation and Waiting), `:52` |
| `.github` and scripts citations | Grep `copilot-instructions` | `diff-reviewer.agent.md:102` (reading rule, newly noted); the 3 `probos-*` profiles (`:16`, `:17`, `:25`); `BUILDER-EXECUTION-PLAN.md:28,235`; `wave-orchestrator.ps1:574`; `measure_agent_token_usage.py:16,52` |
| Supervised Worker references | Grep at the root, plus an explicit `.claude/agents` grep | Live: `supervised-worker.json:26-28,40`, the 3 profiles, `.gitignore:76`. History: DECISIONS, `roadmap.md`, `supervised-worker-host-program.md`, `self-maintenance-architecture.md:111,522,546`, `prompts/ad-1259…:214`, `prompts/wallclock-standing-orders.md:64`, `prompts/archive/*`. False-positive trap: `claude-architect.md:301` (`probos-architect-learnings.md`), `prompts/Reviews/README.md:56` (same filename). |
| Tracked `.github` and `.claude` files | `git ls-files .github .claude` | 3 `claude-*.md`; `diff-reviewer.agent.md` and 3 `probos-*.agent.md`; C; `supervised-worker.json`; `ci.yml`, `docs.yml` |
| No test or script reads the agent profiles | Grep `\.github/agents\|agent\.md\|supervised-worker` in `tests`; `(?i)\.github/agents\|supervised` in `scripts` | tests: none; scripts: `run_test_gate.py:260` (the word "supervised" only) |
| The injection probe exists | Glob `**/injection_check.py` under `D:\ProbOS-worktrees` | Only `proc-20261014-a28fa315\logs\architect\injection_check.py` |

### Absence Verified

| Claim | Run | Found | Holds |
|---|---|---|---|
| No kickoff template is tracked | Grep `(?i)kick-?off template\|orchestrator kickoff` outside `prompts/archive` and `logs` | no files | yes |
| No test or script reads agent profiles or `supervised-worker.json` | See the table above | none | yes |
| Nothing under `src`, `scripts`, `tests` or `CLAUDE.md` names a `probos-*` profile | Root grep `probos-(architect\|builder\|diff-reviewer)` over those globs, then an explicit `.claude/agents` grep | Root: none. `.claude/agents`: `claude-architect.md:301` only, which is the `-learnings.md` memory filename, not a profile. | yes, but a bare-substring T12 would fail on it (H15) |
| No other C text depends on the two changed lines | Grep `decided by the Architect` | 115 and 140 only, both moving to O | yes |
| The injected file has no BF rule | Grep `does not cover BF` in C | none; it lives only in `claude-architect.md:171` | yes |
| ~~"Route decisions through the Architect, not the Captain" is not verbatim text~~ | Grep | **Now present at C:140.** v1's row is withdrawn. | no longer holds; the paragraph moves to O unchanged |

**Not gathered:** `ls` on the old worktree's `logs/architect/` was denied; a Glob confirmed `injection_check.py` exists there. The experiment output (`injection-experiment.txt`) and `local-profiles/` were not re-read; v1's readings of them stand, since the bridge did not change them. The merge state of PR #1545 rests on `git log` (merge `7301f647` is an ancestor of `579b5530`), not on `gh pr view`.

---

## Hidden pins

- **H1. ~~The base is still moving.~~ Resolved.** The wall-clock PR is in `579b5530`.
  - Merge `origin/main` before the gate, as the Testing Standards require.
  - Rerun the verifier against the final merge base if main moves.
  - Any anchor matching zero lines or several lines stops the verifier.
- **H2. `test_ad1231` reads Design Principle 1 from C.** Point it at AR, and assert that `"No central scheduler."` is absent from both files.
- **H3. The acceptance line must keep resolving.** Keep `## Building: Engineering Principles (Standing Order)` in C, with a link. Do not edit `repair_brief.py`, the e2e fixture or any prompt.
- **H4. The product builder still gets a prefix.** AD-1200 delivers C as `status=truncated`, `delivery=prefix`, at most 8,192 bytes, with the routing lines and the whole Evidence Standard inside. T3 pins it. Delivering C whole would need C ≤ 8,192 bytes or a change to the cap in `src/`; both are out of scope (F8, F9).
- **H5. CRLF.** The verifier compares lines from `.splitlines()`, `rstrip()`-ed. Rewrites are single-line fragments. New files are written with `newline="\r\n"`.
- **H6. The CLI refuses an array `model:`** (`diff-reviewer.agent.md:4`). O uses a string. The array is a T8 exception (F1).
- **H7. A `tools:` list shrinks the system message.** O omits `tools`; V2 verifies it.
- **H8. Reading rule.** Delegation's reading rule (C:74) is retargeted to EP and AR (R5). `diff-reviewer.agent.md:102` ("never read `.github/copilot-instructions.md` whole") stays: it remains true for the reviewer and does not conflict with O's preamble, which binds only the orchestrator.
- **H9. Brief template.** Retargeted (R4).
- **H10. Two "Batched execution under Testing Standards" pointers** (C:91, `CLAUDE.md:23`). Both are retargeted.
- **H11. The Trial paragraph moves with Delegation.** No change of meaning.
- **H12. Do not edit `wave-orchestrator.ps1`** (`:574` "Read first" stays valid; tests copy and run the script).
- **H13. Measurement script.** It counts reads of `copilot-instructions.md` only (F4).
- **H14. Compaction.** Handled by R0b and V4.
- **H15 (new). Grep scope and the T12 patterns.**
  - ripgrep from the repository root skips the tracked `.claude/` files, because `.gitignore` excludes `.claude/`. The Builder's enumerations must add an explicit `.claude/agents` search (or use `git ls-files`).
  - T12 must use bounded patterns, because `claude-architect.md:301` contains `probos-architect-learnings.md`.
- **H16 (new). The routing, parking and reframing rules move as part of Delegated AD Execution Mode (C:123–151) into O, unchanged.**
  - The callee's side stays in `claude-architect.md` "Decision Requests from the Orchestrator". It is retargeted at `:51` (E7) and not merged (Q7).
  - Reporting (C:115) moves with Burn-Down.

---

## (a) Section map (base `579b5530` → new location)

New files: **C** = `.github/copilot-instructions.md` (constitution) · **O** = `.github/agents/orchestrator.agent.md` · **EP** = `docs/development/engineering-principles.md` · **AS** = `docs/development/architect-standards.md` · **AR** = `docs/development/architecture-reference.md`

| # | Old (line) | New | Status |
|---|---|---|---|
| 1 | Title + description (L1, L3) | C | unchanged |
| 2 | (none) | C, lines 3–4: Captain's routing line + compaction line | **added** (R0) |
| 3 | How You Should Operate (L5–11) | C | reworded R1 (pointer "below" → AR path) |
| 4 | Current State (L13–19) | C | reworded R2 (describes the file; no rule) |
| 5 | Evidence Standard (L23–35) | C | unchanged |
| 6 | Adversarial Review (L39–57) | C | reworded R3 (pointer to the Burn-Down filing policy names O) |
| 7 | Delegation and Waiting (L61–81, with the Trial paragraph) | O | reworded R4 (brief template targets), R5 (reading-rule target) |
| 8 | Prompt Drafting bullet "Prompts from the Claude Architect" (L325) | O, end of Delegation | unchanged (moved) |
| 9 | Backlog Burn-Down (L85–119, with Reporting L115 as amended by `1dcc9b20`) | O | reworded R6 (Batched execution location); L115 unchanged |
| 10 | Delegated AD Execution (L123–151: Activation, Overrides, Delegated authority, envelope, **Route decisions through the Architect (L140)**, Still requires the Captain, park and reframe (L151)) | O | unchanged |
| 11 | Engineering Principles heading + "All code MUST…" (L155–157) | C (index section) | unchanged; index and link **added** |
| 12 | SOLID … Configuration Standards (L159–263), apart from rows 13–14 | EP | unchanged |
| 13 | Testing Standards "Test gates" (L193) | split: the Builder clause → EP; the rest → O "Gate, Batch and Push" | reworded R7 (split at the sentence boundary; pointer to the focused command at L204) |
| 14 | Broad-gate currency, Batched execution, canonical wrapper (L194–196) | O "Gate, Batch and Push" | unchanged; R8 in L195 |
| 15 | Review Checklist + Common Review Flags (L266–310) | AS | unchanged; R9 (location of HXI Principle #3) |
| 16 | Prompt Drafting (L312–324) | AS | unchanged |
| 17 | AD Numbering (L327–331) | C, "AD and BF Numbering — Hard Rule" | **merged** (heading renamed) |
| 18 | Strategy (L333–339) | AS | unchanged |
| 19 | Repository Boundary (L342–357) | C | unchanged |
| 20 | Architecture Reference (L360–580) | AR | unchanged; R10 (`##` → `#`) |
| 21 | Duplicate AD Numbering (L582–590) | merged into row 17 | First sentence of L584 and second sentence of L590 kept. The L582 heading and the steps L585–588 are dropped as restatements of L329/L331. |
| 22 | `claude-architect.md:171` BF bullet | C, numbering section | **moved in**; `claude-architect.md` keeps a pointer |
| 23 | (none) | C "Where Each Rule Lives" | **added** (pointers only) |
| 24 | (none) | O front matter + preamble | **added** |
| 25 | `---` separators between moved sections | (none) | dropped (formatting) |

**Duplicated rules resolved.**
- **AD numbering:** two copies (rows 17 and 21) become one owner, C.
- **BF numbering:** moves from `claude-architect.md` to C.
- **Not resolved here:** the paraphrased copies in `claude-builder.md`, `claude-architect.md` and the local `builder.md` (F3).
- **Not a duplicate:** the caller's routing rule (O) and the callee's decision rule (`claude-architect.md:46-55`) are the two sides of one exchange, kept apart under Q7.

## (b) Design questions, ranked

Q1–Q13 stand as settled in v1. None of the three commits invalidates an answer. Q7 is confirmed and extended to the new pair. The recommended options are restated for the Builder:

- **Q1. The adversarial-review rule** stays whole in C.
- **Q2. Gate, batch and push.** The orchestrator part of "Test gates" and L194–196 go to O; the Builder clause stays in EP.
- **Q3. Engineering Principles.** The full text goes to EP; C keeps the heading and an index.
- **Q4. The orchestrator's model** is Claude Sonnet 5.5, pinned as `"Claude Sonnet 5.5 (copilot)"` (see the Revision note), to keep the #1518 baseline like for like. Opus 5.5 is a later, separate experiment. Front matter cannot set effort, so the kickoff sets it.
- **Q5. Other roles' model pins** stay with their rules: the bridge pin in O, the reviewer pin in C.
- **Q6. Numbering.** C owns the merged AD rule plus the moved BF bullet.
- **Q7. Caller and callee.** O holds the orchestrator's side: the L63 bridge paragraph, and now also the L140 routing paragraph. `claude-architect.md` keeps "Headless calls" and "Decision Requests from the Orchestrator"; its `:13`, `:28` and `:51` are retargeted to O.
- **Q8. Enforcement** is the committed `tests/test_standing_orders_layout.py`, plus a one-shot verifier in `logs/`.
- **Q9. The move itself.** A script produces the files from heading-anchored ranges, and a line-multiset verifier checks them against the manifest.
- **Q10. Front matter** as in E2, pinned by T7 and T8.
- **Q11. Residual injection risk.** The profile is self-sufficient for the procedure, with R0a, R0b and V4.
- **Q12. The kickoff template** goes in the PR body (F6 tracks it later).
- **Q13. Slicing:** see (f).

## Exact edits

**E1. Producer and verifier (one-shot, in `logs/architect/`, gitignored, not committed).**

The producer `split_standing_orders.py` (Builder-written):
- reads the base with `git show <base>:.github/copilot-instructions.md`;
- slices by exact heading lines into C, O, EP, AS and AR in the order below;
- applies the manifest's fragment rewrites and splits;
- writes CRLF.

It must never retype moved text.

The verifier is mandatory. Use it as written:

```python
"""One-shot verifier for the standing-orders split. usage: python verify_standing_orders_split.py <base-rev> <manifest.json>"""
from __future__ import annotations
import collections, json, subprocess, sys
from pathlib import Path

NEW = (".github/copilot-instructions.md", ".github/agents/orchestrator.agent.md",
       "docs/development/engineering-principles.md", "docs/development/architect-standards.md",
       "docs/development/architecture-reference.md")

def lines(text: str) -> list[str]:
    return [l.rstrip() for l in text.splitlines() if l.strip()]

def main() -> int:
    rev, manifest = sys.argv[1], json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    base = lines(subprocess.run(["git", "show", f"{rev}:.github/copilot-instructions.md"],
                                capture_output=True, check=True).stdout.decode("utf-8"))
    files = {n: collections.Counter(lines(Path(n).read_text(encoding="utf-8"))) for n in NEW}
    errors: list[str] = []
    def one(anchor: str) -> str:
        hits = [l for l in base if anchor in l]
        if len(hits) != 1:
            errors.append(f"anchor matches {len(hits)} base lines: {anchor[:70]}")
            return ""
        return hits[0]
    def need(name: str, line: str) -> None:
        if files[name][line] == 0:
            errors.append(f"missing in {name}: {line[:90]}")
    expected = collections.Counter(base)
    for d in manifest["dropped"]:
        expected[d["line"]] -= d["count"]
    for r in manifest["rewrites"]:
        old = one(r["anchor"]); new = old
        for frag_old, frag_new in r["replace"]:
            if new.count(frag_old) != 1:
                errors.append(f"fragment not unique: {frag_old[:60]}")
            new = new.replace(frag_old, frag_new, 1)
        expected[old] -= 1; expected[new] += 1; need(r["file"], new)
    for s in manifest["splits"]:
        expected[one(s["anchor"])] -= 1
        for part in s["parts"]:
            expected[part["line"]] += 1; need(part["file"], part["line"])
    for name, added in manifest["added"].items():
        for line in added:
            expected[line] += 1; need(name, line)
    for m in manifest["moved_in"]:
        expected[m["line"]] += 1; need(m["file"], m["line"])
        if m["anchor"] in Path(m["source"]).read_text(encoding="utf-8"):
            errors.append(f"moved line still in {m['source']}")
    if any(v < 0 for v in expected.values()):
        errors.append("a dropped or rewritten line was counted below zero")
    actual = sum(files.values(), collections.Counter())
    for line in (+expected).keys() | actual.keys():
        if expected[line] != actual[line]:
            errors.append(f"count {actual[line]} != expected {expected[line]}: {line[:100]}")
    for n in NEW:
        print(f"{n}: {len(Path(n).read_text(encoding='utf-8')):,} chars")
    print("\n".join(errors) or "OK: every base line is placed exactly once, apart from declared changes")
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
```

The manifest (`logs/architect/standing-orders-split.json`) declares the following. File keys: C/O/EP/AS/AR as above. All anchors and fragments were re-verified at `579b5530` (see Verified).

**Rewrites** (`anchor` → `replace` pairs → `file`):

- **R1** (C)
  - anchor: `**Building mode** -- When asked`
  - replace: `design principles below,` → ``design principles in `docs/development/architecture-reference.md`,``
- **R2** (C)
  - anchor: `This file contains **durable architectural knowledge**`
  - replace: `This file contains **durable architectural knowledge** that changes rarely.` → `This file contains the **shared standing orders**, which change rarely; role procedures and reference material live in the files listed under **Where Each Rule Lives**.`
- **R3** (C)
  - anchor: `**Act on the findings before committing.**`
  - replace: `in **Backlog Burn-Down Mode** below` → ``in **Backlog Burn-Down Mode** (`.github/agents/orchestrator.agent.md`)``
- **R4** (O)
  - anchor: `**Brief template (both roles).**`
  - replace: ``Builder, `Building: Engineering Principles` and its `Testing Standards`; Diff Reviewer, `Adversarial Review Before Every Commit` and `Evidence Standard`.`` → ``Builder, `docs/development/engineering-principles.md` and its `Testing Standards`; Diff Reviewer, `Adversarial Review Before Every Commit` and `Evidence Standard` in `.github/copilot-instructions.md`.``
- **R5** (O)
  - anchor: `**Reading rule (every role, the orchestrator included).**`
  - replace 1: ``or read `.github/copilot-instructions.md` whole.`` → ``or read `docs/development/architecture-reference.md` or `docs/development/engineering-principles.md` whole.``
  - replace 2: `and this file read 46 times by Builders (350K chars).` → ``and `.github/copilot-instructions.md` read 46 times by Builders (350K chars, before the 2026-10 split).``
- **R6** (O)
  - anchor: `Work in progress is limited to **one issue**`
  - replace: `(see **Batched execution** under Testing Standards)` → `(see **Batched execution** under **Gate, Batch and Push**)`
- **R8** (O)
  - anchor: `- **Batched execution (Captain, 2026-08-25`
  - replace: `(defined under **Adversarial Review Before Every Commit**)` → ``(defined under **Adversarial Review Before Every Commit** in `.github/copilot-instructions.md`)``
- **R9** (AS)
  - anchor: `- **HXI emoji violation**`
  - replace: `per HXI Design Principle #3.` → ``per HXI Design Principle #3 in `docs/development/architecture-reference.md`.``
- **R10** (AR)
  - anchor: `## ProbOS Architecture Reference`
  - replace: `## ProbOS Architecture Reference` → `# ProbOS Architecture Reference`
- **R11** (C), merge
  - anchor: `All changes are tracked by AD number`
  - replace: ` Before proposing ANY new AD:` → `` (empty)
- **R12** (C), merge
  - anchor: `Each AD should be a single, testable change.`
  - replace: `**Never guess. Never assume. Never reuse.** ` → `` (empty)

No rewrite touches L115 or L140: they move unchanged with their sections.

**Split R7** (anchor `- **Test gates**: The Builder runs focused tests`):
- **EP line:** ``- **Test gates**: The Builder runs focused tests for the changed slice and its immediate consumers after each milestone, with the focused command below; the orchestrator's gates are in `.github/agents/orchestrator.agent.md` (**Gate, Batch and Push**).``
- **O line:** `- **Test gates**: D` followed by the base line from `o not re-run each milestone's tests yourself.` to its end, with ` with the focused command below ` replaced by `` with the focused command in Testing Standards (`docs/development/engineering-principles.md`) ``. The Builder computes the exact text and pastes it into the manifest.

**Dropped:**
- the `### AD (Architecture Decision) Numbering — Hard Rule` heading;
- the four step lines `1. Read PROGRESS.md` through `4. Assign the next sequential number`;
- the `### AD Numbering — Hard Rule` heading (replaced by an added `## AD and BF Numbering — Hard Rule`);
- the `---` lines that are not reused, with their count.

**Added:** every line in E2–E5 marked ADDED, the front-matter lines, and the new headings.

**moved_in:**
```json
{"source": ".claude/agents/claude-architect.md",
 "anchor": "**BF:** `ad_ceiling.py` does not cover BF numbers",
 "file": ".github/copilot-instructions.md",
 "line": "**BF numbers.** `ad_ceiling.py` does not cover BF numbers. Enumerate the same three sources yourself — `git log --all --format='%s'` subjects, GitHub issue titles in all states, and `prompts/bf-*.md` filenames — plus the Bug Tracker in `docs/development/roadmap.md`, and paste what you ran."}
```

**E2. `.github/agents/orchestrator.agent.md`** (new, about 25.9K)

```yaml
---
name: "ProbOS Orchestrator"
description: "Runs the ProbOS issue queue: Architect bridge, Builder and Diff Reviewer delegation, waiting with watchdogs, Backlog Burn-Down and Delegated AD Execution, the single receipted gate, push and verified closure."
model: "Claude Sonnet 5.5 (copilot)"
user-invocable: true
disable-model-invocation: true
argument-hint: "Name the queue scope or starting issue, and whether Backlog Burn-Down or Delegated AD Execution Mode is active"
---
```

ADDED body opening:

```
# ProbOS Orchestrator

You orchestrate the ProbOS issue queue. This profile carries the orchestration procedure. The shared standing orders (Evidence Standard, Adversarial Review Before Every Commit, the Engineering Principles index, the repository boundary, AD and BF numbering) are in `.github/copilot-instructions.md`, which Copilot normally injects alongside this profile; if its line "Orchestrating the queue? You must be the ProbOS Orchestrator agent" is not in your context, read that file once before your first step. Full texts, read by section: `docs/development/engineering-principles.md`, `docs/development/architect-standards.md`, `docs/development/architecture-reference.md`.
```

Then, in order:
1. `## Delegation and Waiting (Standing Order)`: the base section with R4 and R5 applied, then the moved L325 bullet.
2. `## Backlog Burn-Down Mode (Standing Order)`, with R6. Reporting (L115) is carried as amended by `1dcc9b20`.
3. `## Delegated AD Execution Mode (Standing Order)`: the whole section, L125–151, unchanged. It includes **Route decisions through the Architect, not the Captain (Captain, 2026-10-14)**, **Still requires the Captain** and the park-and-reframe paragraph.
4. ADDED heading `## Gate, Batch and Push (Standing Order)`, followed by the O line of R7 and base L194, L195 (with R8) and L196.

The id form `claude-sonnet-5.5` was the first choice; V2 showed the CLI refuses every explicit model name, so the fallback `"Claude Sonnet 5.5 (copilot)"` (the VS Code qualified display name) is pinned.

**E3. `.github/copilot-instructions.md`** (rewritten, about 15.0K), in this order:

- Title, blank line, then two ADDED lines:
  - **R0a (Captain, verbatim):** `Orchestrating the queue? You must be the ProbOS Orchestrator agent; if you are not, read .github/agents/orchestrator.agent.md before doing anything else.`
  - **R0b (new, strengthens):** `If that profile's sections are no longer in your context (for example after a context compaction), read it again before your next step.`
- Description; How You Should Operate (R1); Current State (R2); `---`; Evidence Standard; `---`; Adversarial Review (R3); `---`.
- `## Building: Engineering Principles (Standing Order)`, the base "All code MUST…" line, then ADDED:

  ```
  The full text is `docs/development/engineering-principles.md`; the standing acceptance line "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`" refers to it through this section. Read it by section:

  | Section | Governs |
  |---|---|
  | SOLID Principles | class responsibility, extension through public APIs, protocols, constructor injection |
  | Additional Engineering Principles | Law of Demeter, exception-handling tiers, defense in depth, DRY, cloud-ready storage |
  | Coding Standards | existing patterns, agent lifecycle, consensus on destructive intents, raw trust parameters, warm-boot validation |
  | Testing Standards | focused tests, mutation testing, coverage, structure, isolation, API and UI test requirements |
  | Type Annotation Standards | public API annotations, protocol compliance, modern typing |
  | Logging Standards | structured context, levels, no print, no sensitive data |
  | Async Discipline | running loop, task references, cancellation, async cleanup |
  | Import & Module Standards | layer discipline, circular imports, import order, wildcards |
  | Configuration Standards | Pydantic models, defaults, parse-time validation |
  ```

- `---`
- ADDED `## AD and BF Numbering — Hard Rule`, then R11's line, base L329, base L331, the moved BF line, then R12's line.
- `## Repository Boundary — OSS vs Commercial`, unchanged.
- `---`
- ADDED `## Where Each Rule Lives`, with this table:

  | Material | File |
  |---|---|
  | Orchestration: delegation, waiting, Backlog Burn-Down, Delegated AD Execution (including routing decisions through the Architect), gate, batch, push, closure, reporting | `.github/agents/orchestrator.agent.md` |
  | Engineering Principles, full text | `docs/development/engineering-principles.md` |
  | Architect review checklist, Common Review Flags, prompt drafting, strategy | `docs/development/architect-standards.md` |
  | ProbOS Architecture Reference | `docs/development/architecture-reference.md` |
  | Copilot Diff Reviewer | `.github/agents/diff-reviewer.agent.md` |
  | Claude Code roles and the split workflow | `CLAUDE.md`, `.claude/agents/claude-*.md` |
  | Copilot Builder and Architect | local `.claude/agents/builder.md`, `architect.md` (untracked) |

**E4. `docs/development/engineering-principles.md`** (new, about 10.0K)

ADDED `# Engineering Principles (Standing Order)`, then ADDED `Index and authority: \`.github/copilot-instructions.md\`, section Building: Engineering Principles.`, then base `### SOLID Principles` through Configuration Standards, with R7's EP line in place of Test gates and L194–196 removed.

**E5. `docs/development/architect-standards.md`** (new, about 9.9K)

ADDED `# Architect Standards`, then the base Review Checklist and Common Review Flags (R9), Prompt Drafting (without L325), and Strategy.

**E6. `docs/development/architecture-reference.md`** (new, about 24.0K)

R10, then base L362–580.

**E7. Claude-side and pointer files:**

- `CLAUDE.md:3` → "The repository's shared standing orders live in `.github/copilot-instructions.md`; the orchestration procedure (delegation, waiting, Backlog Burn-Down, Delegated AD Execution, the gate, push and closure) lives in `.github/agents/orchestrator.agent.md`. Read the first at the start of every session, and the second too when this session orchestrates the queue; both apply to Claude Code exactly as they do to Copilot. This file only adds what Claude Code needs on top of them: the subagent workflow and the Claude Code equivalents of Copilot-only mechanics. Where they disagree on anything else, those two files win."
- `CLAUDE.md:20` `(Testing Standards)` → ``(**Gate, Batch and Push**, `.github/agents/orchestrator.agent.md`)``
- `CLAUDE.md:21`: unchanged (Adversarial Review stays in C).
- `CLAUDE.md:23` `Testing Standards, Batched execution` → ``**Batched execution**, `.github/agents/orchestrator.agent.md` ``
- `CLAUDE.md:33` ``per `.github/copilot-instructions.md`.`` → ``per `.github/agents/orchestrator.agent.md`, selected as **ProbOS Orchestrator** in the agent picker.``
- `CLAUDE.md:46` `(Delegation and Waiting)` → ``(Delegation and Waiting, `.github/agents/orchestrator.agent.md`)``
- `CLAUDE.md:52` ``The test commands in `.github/copilot-instructions.md` use`` → ``The test commands in `.github/agents/orchestrator.agent.md` and `docs/development/engineering-principles.md` use``
- `claude-architect.md:13`, keeping the first sentence's provenance → "…read `config/standing_orders/architect.md` whole (about 5K characters). Read the rest by section (grep `^## `/`^### ` headings, then read only what the task needs): usually the Evidence Standard and AD and BF Numbering in `.github/copilot-instructions.md`, Delegated AD Execution Mode in `.github/agents/orchestrator.agent.md`, `docs/development/engineering-principles.md`, and Architect: Claude Code Prompt Drafting in `docs/development/architect-standards.md`."
- `claude-architect.md:28` ``envelope in `.github/copilot-instructions.md` `` → ``envelope in `.github/agents/orchestrator.agent.md` ``
- **`claude-architect.md:51` (new)** ``condition in `.github/copilot-instructions.md` (Delegated AD Execution Mode)`` → ``condition in `.github/agents/orchestrator.agent.md` (Delegated AD Execution Mode)``
- `claude-architect.md:171` → `   - **BF:** see **AD and BF Numbering — Hard Rule** in \`.github/copilot-instructions.md\`.`
- `claude-architect.md:247` and `:301`: unchanged.
- `claude-builder.md:12` → "Repository standing orders live in `.github/copilot-instructions.md`; the full Engineering Principles and Testing Standards are in `docs/development/engineering-principles.md`. Read those sections before starting; they apply to you in Claude Code exactly as they do in Copilot."
- In `diff-reviewer.agent.md` after `## Checklist`, and in `claude-diff-reviewer.md` after `## Checklist`, insert: "Project standards behind these checks: Engineering Principles in `docs/development/engineering-principles.md`; Common Review Flags in `docs/development/architect-standards.md`; Evidence Standard and Adversarial Review in `.github/copilot-instructions.md`. Read them by section."
  - `diff-reviewer.agent.md:102` and its model array stay unchanged.
- `prompts/BUILDER-EXECUTION-PLAN.md:28` → ``1. `.github/copilot-instructions.md` and `docs/development/engineering-principles.md` — engineering principles, …``
- `prompts/BUILDER-EXECUTION-PLAN.md:235` ``(see `.github/copilot-instructions.md`)`` → ``(see `.github/agents/orchestrator.agent.md`)``

**E8. Docs.**

Retarget (the files are unchanged since v1, so the lines stand):
- `composable-cognition.md:320` → `docs/development/architecture-reference.md`
- `hxi-live-ux-review-2026-09-07.md:38` and `hxi-spatial-collaboration-program.md:55`: link → `(architecture-reference.md)`
- `platform-maturity-program.md:736` → `.github/agents/orchestrator.agent.md`
- `test-suite-optimization-plan.md:42` → `docs/development/engineering-principles.md`

Leave unchanged, because they still resolve:
- the acceptance lines in `codebase-review-follow-through.md:214`, `nooplex-roadmap-follow-through.md:266`, `self-maintenance-architecture.md:512` and `hxi-spatial…:462`;
- `platform-maturity-program.md:32`;
- `commercial-boundary-audit-guide.md:9,78`;
- `repository-instructions.md:79`;
- history files, PROGRESS and DECISIONS;
- `src/` comments (`divergence_detector.py:508`, `build_pipeline.py:44`, `episodic_health.py:20`, `clinical_notes_store.py:18`, `chamber.py:254`, `ground_truth.py:395`, `finalize.py:2684`) and `desktop/src/main/logger.ts:5`;
- **`tests/test_ad1203_trace_routes.py:9`** (a docstring; it reaches the API-test rule through the index).

**Prompts:** none of the ~800 prompts changes.

**E9. Slice B (retirement).** `git rm` the following:
- `.github/agents/probos-architect.agent.md`
- `.github/agents/probos-builder.agent.md`
- `.github/agents/probos-diff-reviewer.agent.md`
- `.github/supervised-worker.json` (its only consumer was the withdrawn external host)

**Keep:**
- `.gitignore:76 .supervised-worker/`;
- the history files listed in Verified.

**E10. Trackers.**
- `PROGRESS.md`: one line.
- `DECISIONS.md`: one entry, no AD number: "Standing orders split into constitution, orchestrator profile and reference docs; one owner per rule; layout pinned by `tests/test_standing_orders_layout.py`".

## Tests

New file `tests/test_standing_orders_layout.py`. Governed set: C, O, EP, AS, AR, `CLAUDE.md`.

| # | Name | Premise asserted first | Asserts |
|---|---|---|---|
| T1 | `test_constitution_opens_with_orchestrator_routing_line` | the file exists | The first non-blank line after the title is R0a, byte-exact; the next is R0b |
| T2 | `test_constitution_stays_slim` | the file is non-empty | LF-normalised UTF-8 ≤ 18,000 bytes. The docstring says raising the cap is a deliberate decision. |
| T3 | `test_constitution_prefix_delivered_to_the_native_builder` | `INSTRUCTION_FILE_BYTES == 8192`; C is larger than the cap; exactly one frame | Real discover and render paths on a `tmp_path` repo. `status == "truncated"`, `delivery == "prefix"`, content ≤ cap and a prefix of C, and R0A, R0B, the Evidence Standard heading and the Adversarial Review heading are inside it. |
| T4 | `test_engineering_principles_acceptance_line_still_resolves` | (none) | C contains `## Building: Engineering Principles (Standing Order)` and `docs/development/engineering-principles.md`; EP has `### SOLID Principles` and `### Testing Standards` |
| T5 | `test_each_section_has_exactly_one_owner` | all governed files exist | `OWNERS`: Evidence, Adversarial, AD and BF Numbering, Repository Boundary, Building: Engineering Principles → C. Delegation, Burn-Down, Delegated AD, Gate Batch and Push → O. SOLID, Testing Standards → EP. Review Checklist, Common Review Flags, Prompt Drafting, Strategy → AS. Design Principles, HXI Design Principles → AR. Each heading line occurs exactly once across the set, in its owner. |
| T6 | `test_no_sentence_is_duplicated_across_instruction_files` | ≥ 200 units in total, and T6a passes | Normalised sentences (strip `**`, list markers, collapse whitespace, lowercase; ≥ 60 chars; YAML front matter excluded) occur once across the set. A duplicate in `CLAUDE.md` is replaced by a pointer. |
| T6a | `test_duplicate_detector_finds_a_planted_duplicate` | (none) | The detector, run on two synthetic texts that share one long sentence, reports exactly that sentence |
| T7 | `test_orchestrator_profile_frontmatter_has_cli_shape` | parses with `yaml.safe_load` | `name == "ProbOS Orchestrator"`; `model` is a non-empty `str`; `description` is a `str`; `user-invocable is True`; `disable-model-invocation is True`; no `tools` key; the keys are a subset of {name, description, model, tools, user-invocable, disable-model-invocation, argument-hint, target, agents, handoffs, mcp-servers, hooks} |
| T8 | `test_agent_profile_models_are_strings` | at least 2 profiles found | Every `.github/agents/*.agent.md` with a `model` has a `str`, apart from `KNOWN_ARRAY = {"diff-reviewer.agent.md"}` |
| T8a | `test_known_array_model_exceptions_are_still_arrays` | (none) | Each exception still has a list |
| T9 | `test_orchestrator_profile_carries_the_procedure` | (none) | O contains `scripts/claude_architect.py --task-file`, `Start-Sleep -Seconds 270`, `scripts/run_test_gate.py --label <issue-or-wave> --receipt`, `**Still requires the Captain.**`, `Discovery budget` and `Freeze the batch, then run ONE full repository gate`; **and (new)** `**Route decisions through the Architect, not the Captain (Captain, 2026-10-14).**`, `**decided by the Architect**` and `Before parking, ask whether the blocking requirement itself can be narrowed or reframed`. None of these occurs in C. |
| T10 | `test_constitution_keeps_the_shared_rules` | (none) | C contains `Claims that something does NOT exist require an enumeration you actually ran`, ``run the `Diff Reviewer` subagent on the staged diff``, `scripts/ad_ceiling.py`, `` `ad_ceiling.py` does not cover BF numbers`` and `How the product makes money` |
| T11 | `test_pointer_paths_exist` | at least 5 paths found | Every backticked `(\.github\|\.claude\|docs\|scripts)/…\.(md\|py)` path in C and O exists, apart from `UNTRACKED_LOCAL = {".claude/agents/builder.md", ".claude/agents/architect.md"}` |
| T12 | `test_retired_supervised_worker_profiles_are_gone` | the scan visited at least 50 files, **and `.claude/agents/claude-architect.md` was among them** | The 4 retired files are absent. No file under `.github/`, `.claude/agents/claude-*.md`, `CLAUDE.md`, `scripts/`, `src/` or `tests/` (this file excluded) matches `RETIRED = re.compile(r"probos-(?:architect\|builder\|diff-reviewer)(?![-\w])\|ProbOS Supervised\|supervised-worker\.json")`. Walk the paths with `pathlib`, not with a gitignore-aware tool. |
| T12a | `test_retired_profile_pattern_is_bounded` | (none) | `RETIRED` matches `probos-builder.agent.md`, `"probos-diff-reviewer"` and `ProbOS Supervised Architect`; it does **not** match `/memories/probos-architect-learnings.md` (the text at `claude-architect.md:301`) |

**Updated test.** `tests/test_ad1231_hybrid_coordination_principle.py`:
- `_INSTRUCTIONS` → `_REPO_ROOT / "docs" / "development" / "architecture-reference.md"`;
- add `_CONSTITUTION` (the old path);
- `test_principle_one_no_longer_claims_there_is_no_central_scheduler` asserts the string is absent from both;
- add one docstring line recording the move.

No assertion is removed.

### Mutation table (targeted)

Not executed: this consult is read-only. The Builder runs it in place, with `.mutbak` siblings and single-line anchors, after an unmutated green baseline.

| Mutant | Expected killer |
|---|---|
| M1: delete R0a from C | T1 |
| M2: append AR's text to C | T2, T5, T6 |
| M3: O `model:` set to a list | T7 |
| M4: add `tools: [read]` to O | T7 |
| M5: remove the `## Gate, Batch and Push` heading from O | T5, T9 |
| M6: paste the Evidence Standard's first sentence into EP | T6 |
| M7: rename C's Engineering Principles heading | T4, T5 |
| M8: restore `probos-builder.agent.md` from git | T12 |
| M9: AR Principle 1 set to `No central scheduler.` | `test_ad1231` |
| M10: make the T6 normaliser return `""` | T6a |
| M11: change the `diff-reviewer.agent.md` model to a string without updating `KNOWN_ARRAY` | T8a |
| M12: delete the BF line from C | T10 |
| **M13: delete the "Route decisions through the Architect" paragraph from O** | T9 (and the verifier, once) |
| **M14: drop `(?![-\w])` from `RETIRED`** | T12a (and T12, through `claude-architect.md:301`) |
| **M15 (T3 revision):** in C, change the line `## Current State` so it is preceded on the same line by 8,192 `x` characters (the Evidence Standard and Adversarial Review headings leave the 8,192-byte prefix) | T3; also T2 |
| **M16 (T3 revision):** in C, change `## Evidence Standard (Standing Order, both modes)` to `## Evidence Standard` | T3, T5 |
| **M17 (T3 revision):** temporary overlay of `src/probos/security/file_access.py:231`, `INSTRUCTION_FILE_BYTES = 8192` → `16384`; revert immediately, never commit | T3 (premise: the cap changed); proves a cap change fails loudly |

## (c) Kickoff template

It is not tracked anywhere (Absence Verified). Put this text in the PR body:

> Select **ProbOS Orchestrator** in the agent picker before sending (it pins Claude Sonnet 5.5; set reasoning effort **max**). Task: [Delegated AD Execution Mode | Backlog Burn-Down Mode] over the open queue of seangalliher/ProbOS, starting at [#NNNN | a fresh snapshot]. Prefer one item, or one coupled batch, per session; take questions that come up to the Architect as the profile directs. At the end, run `scripts/measure_agent_token_usage.py` on this session's `events.jsonl` and report orchestrator tokens per call (first-call prompt size and median) against the #1518 baseline (median 426K over 943 calls), plus any instruction you had to look up that the profile should have carried.

## (d) Size, before and after

CRLF working-tree bytes; "after" is an estimate. The Builder reports exact LF character counts from the verifier.

| | Before (`579b5530`) | After |
|---|---|---|
| Injected for a default agent and AD-1200 | 79,625 | ~15,000 (−81%) |
| Orchestrator profile | — | ~25,950 |
| **Orchestrator total injected** (CLI: C + profile) | 79,625 | **~40,950 (−49%; about −38.7K bytes ≈ −9.7K tokens per call ≈ −2.3% of the 426K median)** |
| `engineering-principles.md` / `architect-standards.md` / `architecture-reference.md` | — | ~10,000 / ~9,900 / ~24,000 |
| Native builder (AD-1200) delivery | prefix, 8,192 of 79,035 bytes (per-file cap) | prefix, 8,192 of ~14,639 bytes (per-file cap); same sections inside, plus the routing lines |

Before, by part:

| Part | Bytes |
|---|---|
| Header + Operate + State | 1,608 |
| Evidence | 2,560 |
| Adversarial | 4,534 |
| Delegation | 10,029 |
| **Burn-Down** | **~4,086** (was 3,832) |
| **Delegated AD** | **~5,757** (was 4,661) |
| Engineering Principles (of which gate bullets: 3,913) | 13,625 |
| Review | 6,822 |
| Drafting (of which the L325 bullet: 470) | 2,793 |
| AD | 1,228 |
| Strategy | 523 |
| Boundary | 1,604 |
| Architecture Reference | 23,867 |
| Duplicate AD | 582 |

The total, 79,625, is measured. The two bold parts were measured with `head|tail|wc -c`, and their ranges include trailing separators.

## (e) Guardrails check

| Change | What could now be missed | What catches it |
|---|---|---|
| 1. Profile | A session not started as ProbOS Orchestrator lacks the procedure | R0a in C and T1; the kickoff; V4 |
| 1. Profile | The profile body is lost after a VS Code compaction | R0b; V4 |
| 1. Profile | The orchestrator escalates to the Captain instead of the Architect | L140 carried verbatim in O; T9 (M13) |
| 2. Slim C | The Copilot Builder or the Architect fallback no longer sees the filing policy or the envelope | R3; Where Each Rule Lives; `claude-architect.md:13/:28/:51`; T5, T11 |
| 2. Slim C | A rule the native builder needs moves out of its 8,192-byte prefix | T3 |
| 3. Move reference | Briefs point at moved headings | R4, R5; T5 |
| 3. Move reference | The acceptance line stops resolving | T4 |
| 3. Move reference | Design Principle 1 coherence | `test_ad1231` |
| 3. Move reference | A rule is duplicated or lost in the move | Verifier E1 and T6 |
| 4. Retire profiles | Something still launches `probos-*`, or the guard false-fires | T12 + T12a; V2 |
| 5. CLAUDE.md | A Claude Code main session that orchestrates skips the procedure | `CLAUDE.md:3`; R0a |

## (f) Batching, build order and the focused check

One PR, two slices, **one gate**. Wall-clock rules apply:
- the Builder runs focused tests per milestone;
- the orchestrator runs **one consolidated focused check** on each frozen candidate: before the Diff Reviewer's first round, and again before commit only if a repair changed the tree;
- a repair round is re-reviewed on its delta, unless it changes a shared contract;
- **this PR changes C, which is a shared contract**, so a repair that touches C or O gets a full re-review;
- one receipted broad gate for the batch.

Build order:

- **M1 (Slice A).** Copy `injection_check.py` from `D:\ProbOS-worktrees\proc-20261014-a28fa315\logs\architect\` into this worktree's `logs/architect/`. Write E1's producer, verifier and manifest. Produce C, O, EP, AS and AR. The verifier exits 0 against `579b5530`, or against the current merge base if main has moved.
  - Builder focused test: `test_ad1231` (expected red until M3).
- **M2 (Slice A).** Edits E7, E8 and E10. Rerun the verifier.
  - Builder focused test: the E7/E8 path greps.
- **M3 (Slice A).** Write `tests/test_standing_orders_layout.py`, update `test_ad1231`, and run the mutation table, M1–M14.
- **M4 (Slice B).** E9, then rerun T12 and T12a.
- **Orchestrator, once on the frozen candidate (focused check):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_standing_orders_layout.py tests/test_ad1231_hybrid_coordination_principle.py tests/test_ad1200_repository_instructions.py tests/test_ad1200_repository_instruction_wire.py tests/test_measure_agent_token_usage.py -q -n 0 -p no:randomly`, plus V1 and V2.
- Then: Diff Reviewer → repairs → preflight → commit Slice A and Slice B separately → V3, the single broad gate → push.

## Builder brief (by file)

- **Contract:** this answer.
- **Standing orders:** `Building: Engineering Principles` → `Testing Standards`. Copy in the reading rule.
- **Never retype moved text:** produce it with the script; the verifier is the gate.
- **Enumerations** must include an explicit `.claude/agents` search (H15).
- **Files:** C, O, EP, AS, AR (E1–E6); `CLAUDE.md`, `claude-architect.md` (`:13`, `:28`, `:51`, `:171`), `claude-builder.md`, `claude-diff-reviewer.md`, `diff-reviewer.agent.md` (insertion only), `BUILDER-EXECUTION-PLAN.md` (E7); the five docs (E8); the tests; the Slice B removals.
- **Hard stops:**
  - any anchor matching zero lines or several lines;
  - any rule text that would need rewording beyond the manifest;
  - T6 duplicates outside `CLAUDE.md`;
  - V2 showing a missing shell or subagent tool.

## Diff Reviewer brief (≤ 4 KB)

> **Claim.** The standing orders were split with no change in meaning: `.github/copilot-instructions.md` is now a constitution, the orchestration procedure moved to `.github/agents/orchestrator.agent.md`, and the full reference texts moved to three files in `docs/development/`. The procedure includes Delegated AD Execution with its "Route decisions through the Architect, not the Captain" paragraph and its park-and-reframe rule. The Supervised Worker profiles are retired.
>
> **Consumers that must accept it:**
> - Copilot loads the profile: string `model`, no `tools`.
> - AD-1200 (`src/probos/repository_instructions.py:251`; per-file cap `INSTRUCTION_FILE_BYTES = 8192` at `src/probos/security/file_access.py:231`) delivers an 8,192-byte typed prefix of the constitution. The prefix must contain the routing lines and the whole Evidence Standard. It was a prefix before the split as well.
> - The acceptance line in `repair_brief.py:245-246` and the prompts still resolves to an Engineering Principles section.
> - Builders following the brief template find their sections.
> - `test_ad1231` reads Design Principle 1.
> - `claude-architect.md` (`:13`, `:28`, `:51`, `:171`) points at where the envelope and the numbering rules now live.
>
> **Properties to verify:**
> 1. Every base line is placed exactly once, apart from the manifest's declared rewrites, splits, drops and additions. Rerun `logs/architect/verify_standing_orders_split.py`.
> 2. Each rewrite changes only a pointer or the file a rule names, never what the rule requires.
> 3. No rule exists in two files.
> 4. Every pointer path exists.
> 5. No test assertion is weaker, and T12's pattern does not match `probos-architect-learnings.md`.
> 6. Nothing outside the listed files changed.
> 7. Nothing tracked still references the retired profiles, outside the files kept as history.
> 8. T3 asserts `prefix` against the real cap. Check that it does not assert `complete` and does not hard-code a byte offset into C.
>
> **Start from:** `Adversarial Review Before Every Commit` and `Evidence Standard` in `.github/copilot-instructions.md`.

## Acceptance criteria

1. The verifier exits 0 against the merge base used for the gate and prints character counts.
2. The focused check in (f) passes.
3. All 17 mutants are killed or explained.
4. V1–V3 are recorded in the PR body, with the section map, the size table and the Captain's manual steps.
5. The single receipted broad gate is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do not build

- No rule rewording beyond the manifest. In particular, L115 and L140 move byte-identical.
- No edits to:
  - `src/` (including its comments) or `desktop/`;
  - `ui/e2e` fixtures;
  - `scripts/measure_agent_token_usage.py`, `scripts/wave-orchestrator.ps1`, `scripts/claude_architect.py`;
  - prompts other than `BUILDER-EXECUTION-PLAN.md`;
  - existing tracker entries;
  - `.gitignore:76`;
  - `tests/test_ad1203_trace_routes.py`.
- Do not change `diff-reviewer.agent.md`'s model array or its `:102` reading rule.
- Do not merge the "Decision Requests from the Orchestrator" section of `claude-architect.md` into O.
- Do not edit the untracked local profiles.
- Do not dedupe the existing paraphrased copies in the role profiles.
- Do not change Strategy's "Competitive positioning" line.
- Do not commit the producer, verifier, manifest or `injection_check.py`.
- Do not track the kickoff template.

## Orchestrator commands

- **V0.** `git merge origin/main`, then `git log --oneline -1`. Build against that base, and rerun V1 if main moves before the gate.
- **V1.** `d:/ProbOS/.venv/Scripts/python.exe logs/architect/verify_standing_orders_split.py <base> logs/architect/standing-orders-split.json`
- **Focused check:** see (f).
- **V2.** From the build worktree, rerun the Copilot CLI injection experiment with `logs/architect/injection_check.py` (copied in M1). Update its markers:
  - REPO = `Orchestrating the queue? You must be the ProbOS Orchestrator agent`;
  - PROFILE = `You orchestrate the ProbOS issue queue.`;
  - MOVED = `## Delegation and Waiting (Standing Order)`, which must appear exactly once;
  - **ROUTE = `Route decisions through the Architect, not the Captain`**, which must appear exactly once, and only with PROFILE.

  Expected results:

  | Case | REPO | PROFILE |
  |---|---|---|
  | default | yes | no |
  | `--agent orchestrator` | yes | yes |
  | `--no-custom-instructions` | no | no |
  | `--agent orchestrator --no-custom-instructions` | no | yes |

  Also confirm that the model is Sonnet 5.5 and that a shell tool and the subagent tool are present. Record the command lines and the injected sizes per case in the PR body; that is how requirement 5 is verified.
- **V3.** Preflight, commit both slices, then the broad gate: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label orchestrator-profile --receipt logs/gates/orchestrator-profile.receipt.json`
- **V4 (after merge).** Start the first VS Code session as ProbOS Orchestrator.
  - Run `injection_check.py` on its session folder: REPO and PROFILE both present, before and after the first compaction.
  - For each of the next three items, run `measure_agent_token_usage.py <events.jsonl> --since <item start>`. Report the first-call prompt size and the median against 426K.

## Captain, by hand

1. **Local profiles.** Below the H1 of `D:\ProbOS\.claude\agents\builder.md` and of `architect.md`, add:

   "Repository standing orders: `.github/copilot-instructions.md` (shared). Engineering Principles in full: `docs/development/engineering-principles.md`. Architect standards: `docs/development/architect-standards.md`. Architecture reference: `docs/development/architecture-reference.md`. Orchestration procedure, including the Delegated AD Execution envelope, routing decisions through the Architect, and the Burn-Down filing policy: `.github/agents/orchestrator.agent.md`."
2. **Kickoff.** Use the new template: select ProbOS Orchestrator, set effort to max, and confirm the picker shows Sonnet 5.5.
3. **R0b.** A new rule that adds a safeguard, flagged for your visibility. It is not a decision.

**Decisions that need the Captain:** none.

## Prior Art and Blind Spots

- **Prior art** (unchanged from v1; not re-searched, because nothing in the three commits touches it):
  - VS Code custom agents: the body is prepended to the prompt; `model` may be a string or an array, though this CLI refuses an array; effort cannot be set.
  - GitHub's lessons from about 2,500 `agents.md` files favour short, role-specific files.
  - Adopted: role profile plus a slim constitution. Rejected: copying the constitution into the profile.
- **Blind spots:**
  - per-call savings are modest, about 2%;
  - compaction (R0b, V4);
  - ProbOS's own builder sees only the first 8,192 bytes of C (T3; F8, F9);
  - moved docs publish on probos.dev through `docs.yml`;
  - GitHub-hosted Copilot review reads only the slim file;
  - **(new)** gitignore-aware search hides the tracked `.claude/` files (H15);
  - **(new)** the caller's routing rule and the callee's decision rule can drift apart, because they live in two files by design. T9 pins the caller's side; a cross-file consistency check is a follow-up (F7).

**Follow-ups** (one consolidated issue):
- **F1.** The array `model` in `diff-reviewer.agent.md`.
- **F2.** The Strategy line "Competitive positioning vs …" conflicts with the OSS boundary; the Captain's call.
- **F3.** Paraphrased Engineering Principles and AD-rule copies in the role profiles.
- **F4.** Extend the measurement script's instruction-read count to the new files.
- **F5.** Stale "license whitelist" citations (`avatar-assets.md:10`, `tts-backends-evaluation.md:9`, `skeletal-animations-license.md:6`) and `episodic_health.py:20`.
- **F6.** Track the kickoff template.
- **F7 (new).** A light test that O's routing paragraph and `claude-architect.md` "Decision Requests from the Orchestrator" name the same escalation section ("Still requires the Captain").
- **F8 (T3 revision).** Order C for the product builder: move the Engineering Principles index above Adversarial Review, or shorten the sections before byte 8,192, so the index falls inside the prefix (it needs about 1 KB; the cut lands at 9,166). In the envelope; do it only if a product-builder session is shown to miss Engineering Principles, and T3 then gains that heading.
- **F9 (T3 revision).** The per-file read of AD-1200 is 8,192 bytes while the addendum budget is 32,768, so for a repository with a large `copilot-instructions.md` three quarters of the budget can go unused by that file. Raising the per-file cap, or reading the file by section, is an AD-1200 decision: it changes a security read bound and needs an Architect review and the Captain's knowledge.
- **F10 (T3 revision).** Correct the record: v2 conflated the two caps (Verdict 1, H4, table (d)); corrected here, and the PR body says so.


Sources:
- [VS Code custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [VS Code custom instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions)
- [GitHub blog: How to write a great agents.md](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/)
