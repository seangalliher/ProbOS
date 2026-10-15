# Build contract: encoding the wall-clock changes in the standing orders

**Drafted by:** claude-architect (read-only consult, session id from the bridge header; saved verbatim by the orchestrator), 2026-10-14
**Bridge session:** `b69fb255-6f4d-449a-9a7d-30a30fed3034` (`--read-only`, effort high, exit 0, no tool denials, models claude-haiku-5-5 and claude-opus-5-5)

**Verdict: ✅ Build-ready, docs only.** All five of the Captain's changes fit into existing sentences. `copilot-instructions.md` grows by **4 physical lines and about 3.4K characters**; `CLAUDE.md` grows by **2 lines**. No AD or BF number is allocated, because this is a process change to the standing orders and no code changes. I edited no repository file and wrote no agent memory.

**Answers to the orchestrator's three facts:**

1. **Batching.** The rule failed in two ways.
   - **It did not cover slices.** `#1526` is "AD-1299 S2a (#1352)". `#1527`, `#1528` and `#1539` are AD-1287 S2a, S2b and S3 under parent `#1334`; `gh issue view` on each number returned a merged PR. None of them is an issue, but the rule at line 187 talks only about "three bounded **issues**".
   - **It was optional.** "A single issue may still take its own gate" means gating every slice separately was compliant.
   - **A third conflict.** Delegated AD Execution Mode, line 130, has a parent-backed slice "bank the reviewed commit, durable canonical receipt", which reads as one receipt per slice. Sections 7 and 9 below fix all three.
2. **Watchdog.** Confirmed. Line 73 requires the watchdog but says nothing about how to read it. Section 5 makes "waiting" mean "end the turn with the watchdog armed", so the two sentences can no longer be read as contradicting each other.
3. **#1518's rules.** They are in Delegation and Waiting, lines 65–69:
   - fresh delegation per phase: line 66;
   - briefs by path, about 4 KB: lines 67 and 45;
   - the reading rule: line 68.
   
   "Failure-only test output" is **not encoded anywhere**. Grepping for `failure-only|failures only|only the failures` returned nothing in `.github/**`, and grepping for `failure-only` returned nothing in `CLAUDE.md`, `.claude/agents/claude-*.md` or `config/standing_orders/`. The closest rules are the `-q` focused command (line 196) and the ban on live output filters for gates (line 188). New text refers back to lines 67 and 68 rather than repeating them.

---

## 1. Change → baseline → encoding

| # | Captain's change | Baseline it targets (Captain's figures) | Encoded in |
|---|---|---|---|
| 1 | Stop missing subagent completions | Idle 38 min over 7 cases; resumed 2.1–8.0 min after each completion; `read_powershell` reads of up to 10 min | §5 (line 73 rewrite), §16 (CLAUDE.md line 44) |
| 2 | Batch coupled slices | Broad gate ~15 min per slice; CI and PR ~12 min per slice; 1 gate per slice | §7 (line 187), §8 (line 85), §9 (line 130), §10, §13–§15 (CLAUDE.md) |
| 3 | Overlap waiting with read-only work | Architect bridge ~20 min per slice, taken off the critical path | §2 (line 61), §3 (new paragraph after line 63), §8, §16 |
| 4 | Verify once | Own focused pytest ~20 min per slice (162 calls, ~87 min); own reasoning ~50 min (649 views, 235 greps) | §6 (line 185), §4 (line 68), §11 |
| 5 | Scoped re-reviews | Diff Reviewer ~30 min per slice (5 runs of 20–35 min) | §1 (new paragraph after line 49), §12 |

On change 5: 5 Reviewer runs across 4 slices is about 1.25 rounds per slice. The projected saving is therefore at most one partial run across the window, the smallest of the five.

## 2. Verified Against Codebase (2026-10-14)

**Text each edit replaces** (`.github/copilot-instructions.md`, working tree CRLF, index LF, per `git ls-files --eol`; the same holds for `CLAUDE.md`):

| Line | Current text (quoted, or the start of it) | Section |
|---|---|---|
| 49 | "…When the blast radius crosses layers, follow it; stopping at the immediate caller because the boundary looked tidy is how the seam defects in this repo survive." | §1 |
| 61 | "…runs `d:/ProbOS/.venv/Scripts/python.exe scripts/claude_architect.py --task-file <request.md>` from the worktree root, synchronously, like any sync delegation." | §2 |
| 63 | "…split longer work, such as a full Architect contract, into bounded milestones, or run it in the background with a watchdog." | §3 |
| 67 | "Keep reviewer briefs near 4 KB." (kept; §1 does not repeat it) | none |
| 68 | "- **Reading rule.** Search first, then read the range." | §4 |
| 73 | "**Never end a turn waiting on a background or `write_agent` agent without a watchdog.** Start an async shell: … The shell's completion notification wakes an idle caller (observed 26 times, after up to 38 idle minutes)." | §5 |
| 85 | "- Work in progress is limited to **one issue**, or at most **three tightly coupled issues** in a bounded wave." | §8 |
| 130 | "…bank the reviewed commit, durable canonical receipt, and parent checklist/evidence update…" | §9 |
| 185 | "- **Test gates**: Run focused tests for the changed slice and its immediate consumers after each implementation slice." | §6 |
| 187 | "- **Batched execution (Captain, 2026-08-25)**: … A single issue may still take its own gate; …" | §7 |
| CLAUDE.md 17, 20–24, 44 | Workflow heading, steps 2–6, Watchdog paragraph | §10–§16 |

**Uniqueness of the anchors.** One count of the four line-61/68/85/130 phrases returned exactly 4 hits. Each of those anchors was also seen once in the ranged reads. The same count found no "Merge the base" or "base branch" in `copilot-instructions.md`, so §7 deliberately adds no base-merge rule there; that rule stays only in CLAUDE.md step 5.

**Hidden pins** (things that read these files or quote the sentences being changed):

| Pin | Found by | Handling |
|---|---|---|
| `tests/test_ad1231_hybrid_coordination_principle.py:40` reads the real `copilot-instructions.md` and pins Design Principle 1 (around line 373) | `Grep copilot-instructions tests` | Not touched. Run it in the focused check. |
| `tests/test_ad1200_repository_instructions*.py` (lines 153–289, 462) | same | They write synthetic `copilot-instructions.md` files under a tmp root and never read the real file. Not pinned. |
| `scripts/measure_agent_token_usage.py:350` classifies `powershell`/`read_powershell` calls containing `Start-Sleep` as "watchdog sleep"; `tests/test_measure_agent_token_usage.py:80,145,259` pins that | `Grep "Start-Sleep\|watchdog" tests scripts` | Kept: §5 keeps the `Start-Sleep` commands. This script is the measurement tool for §6 of this contract. Run its test in the focused check. |
| `scripts/wave-orchestrator.ps1:574` lists the file path only | `Grep copilot-instructions scripts` | No sentence pinned. |
| `.github/supervised-worker.json:31` focused command | `Grep "-q -n 0"` | Command unchanged. |
| `.github/agents/diff-reviewer.agent.md:40` and `.claude/agents/claude-diff-reviewer.md:46`: "Do not rerun the Builder's focused test matrix" | `Grep focused .github/agents .claude/agents` | Consistent: the consolidated check is the orchestrator's job, not the Reviewer's. |
| `.claude/agents/claude-builder.md:161`: "once per issue (or per batch of up to three issues)" | same | Consistent: the Builder runs the gate only when asked. No edit (see the Do-not-build list). |
| `tests/fixtures/ad1152_agentic_off_golden.json:760` contains a "## Testing Standards" heading | `Grep "Testing Standards" tests` | It comes from `config/standing_orders` text, not this file. Not pinned. |
| No test or script mentions `CLAUDE.md`, "Delegation and Waiting", "Batched execution" or "Never end a turn" | `Grep "CLAUDE\.md\|Delegation and Waiting\|…" tests scripts .github/workflows .github/*.json` | Only the fixture above matched. |

**Event types** the measurement relies on, confirmed as consumed by `scripts/measure_agent_token_usage.py`:

- line 57: `subagent.started`, `subagent.completed`, `subagent.failed`, `user.message`;
- line 201: `assistant.turn_start`;
- line 236: `assistant.message`, which counts only when `apiCallId` is set;
- lines 245 and 257: `tool.execution_start` and `tool.execution_complete`;
- line 214: field `executionMode`;
- line 226: field `durationMs`;
- line 31: the `--group` option.

## 3. Ranked options

**(a) Where the scoped re-review rule lives**

| Rank | Option | Correctness | Safety | Compatibility | Cost |
|---|---|---|---|---|---|
| **1 ✔** | **Adversarial Review Before Every Commit**, directly after the scope paragraph (line 49) | Review scope is defined here, so the exception sits next to the rule it narrows. | The Reviewer's brief template (line 67) sends it to this section, so the Reviewer itself sees where the narrowing stops. | Fits the "Scoping is … not permission to stop short" sentence. | +2 lines |
| 2 | Delegation and Waiting, context-economy bullets | Workable | Weaker: Reviewers are not pointed there, and it reads as a cost rule, which invites narrowing for cost reasons. | OK | +1 line |
| 3 | Both, cross-referenced | Duplicated | Two texts drift apart | — | +3 lines |

**(b) Making "tightly coupled" and "shared contract" testable**

| Rank | Option | Notes |
|---|---|---|
| **1 ✔** | Enumerate them and define each once. **Shared contract** (in Adversarial Review) is any of: a public signature or return shape used outside its module; a persisted schema or on-disk format; a config field; an event type or payload; an API or wire shape; a test another component relies on, including `?raw` source-scan tests; a gate, CI or tooling script. **Tightly coupled** (in Batched execution) means: slices of the same AD or parent issue; or one issue depends on another's change; or they change the same production file or the same shared contract. | Each item can be decided from a diff or the issue graph. Testing Standards refers to the shared-contract definition instead of repeating it. |
| 2 | Same AD or parent issue only | Easiest to test, but drops the coupled-issue batching that has existed since 2026-08-25. |
| 3 | Leave it to judgment (status quo) | Cannot be tested, and it is what produced fact 1. |

**(c) The lag target**

| Rank | Option | Notes |
|---|---|---|
| **1 ✔** | A trial target, one clause in the watchdog paragraph, measured like the 270 s interval trial | Visible to every agent, carries a measurement, and is the same pattern as line 75. |
| 2 | Reporting metric only, in the PR | Invisible at the point where the wait happens. |
| 3 | A hard "must" target | Cannot be enforced mid-turn, and pushes toward tighter polling, which costs tokens. |

**(d) The poll-slice wording**

| Rank | Option | Notes |
|---|---|---|
| **1 ✔** | Ending the turn is the default. Reading the watchdog in-turn is allowed only when you must stay in the turn, in slices of 60 s or less, with `read_agent` between slices. | Ending the turn gives zero lag at the lowest cost. |
| 2 | Always poll in slices of 60 s or less | About 60 model calls an hour over a context of roughly 426K tokens (line 75's median). |
| 3 | Never read the watchdog | Removes the in-turn option the Captain explicitly allowed. |

**(e) How the overlap works** (a design choice the request did not list, but it is real)

| Rank | Option | Notes |
|---|---|---|
| **1 ✔** | Start the read-only consult as an **async shell** before the wait, then keep the critical-path wait (the sync Reviewer, the CI watch) in the foreground. | The current item is never queued behind the consult, the Reviewer stays sync (keeping the line 63 failure property), and the consult's exit code is still read. |
| 2 | Run the Reviewer in the background and the consult in sync | A sync bridge run of about 20 min hides the Reviewer's completion. That brings back the lag change 1 removes and loses sync failure handling. |
| 3 | No overlap | Safe; gives up roughly 20 min per item. |

## 4. Guardrail check

| Change | Could a defect now get further than it does today? | What still catches it | Adjustment made |
|---|---|---|---|
| 1. Watchdog reads | No. Timing only. | The watchdog stays mandatory; the failure notice still comes from the shell; `read_agent` still runs on every wake. | None. |
| 2. Batching | A slice's defect is found at the batch gate instead of a per-slice gate, before push either way. The gate runs on the exact tree that is pushed. | Per-slice review and focused check, the full gate on the frozen tree, and the 4 CI checks. The "Broad-gate currency" rule for an early gate on high-risk changes is kept and referenced. | Capped at 3 items. A red batch gate is traced to the slice that caused it (each slice is committed separately), and the whole batch is re-gated. |
| 3. Overlap | The risk is a stale consult, not a defect reaching review. | The WIP limit on building is unchanged. | **Added:** re-verify the consult's citations if the current item is parked rather than merged, or if a later repair touches a file the consult cites. |
| 4. "Do not re-run each milestone's tests yourself" | **Yes, as worded by the Captain.** A false green claim from a Builder could reach review, because the Captain's single check runs only "before commit". | The consolidated check. | **Tightened:** it runs on each frozen candidate *before the Reviewer's first round*, and again before commit if a repair changed the tree. Still about two runs per slice against roughly 40 today. |
| 5. Scoped re-reviews | Possibly: the previous round's unchecked areas, or a repair that changes a contract. | Escalation to a full review on any shared-contract change or any behaviour the findings did not ask for; the gate; CI. | **Added:** the brief must carry "anything the previous round said it did not check". |

Nothing was refused.

## 5. Exact edits

### Section 1 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
When the blast radius crosses layers, follow it; stopping at the immediate caller because the boundary looked tidy is how the seam defects in this repo survive.
=======
When the blast radius crosses layers, follow it; stopping at the immediate caller because the boundary looked tidy is how the seam defects in this repo survive.

**A repair round re-reviews the delta, not the whole candidate (Captain, 2026-10-14).** Brief it with the previous round's findings, the files and line ranges the repair changed, and anything the previous round said it did not check; it confirms each finding is resolved and traces the delta through every consumer the delta touches, as above. Review the whole candidate again when the delta changes a **shared contract** — a public signature or return shape used outside its module, a persisted schema or on-disk format, a config field, an event type or payload, an API or wire shape, a test another component relies on (including `?raw` source-scan tests), or a gate, CI or tooling script — or adds behaviour the findings did not ask for.
>>>>>>> REPLACE
```

### Section 2 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
from the worktree root, synchronously, like any sync delegation.
=======
from the worktree root, synchronously, like any sync delegation (the one exception is an overlapped `--read-only` consult; see **Overlap waiting with read-only preparation**).
>>>>>>> REPLACE
```

### Section 3 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
split longer work, such as a full Architect contract, into bounded milestones, or run it in the background with a watchdog.
=======
split longer work, such as a full Architect contract, into bounded milestones, or run it in the background with a watchdog.

**Overlap waiting with read-only preparation (Captain, 2026-10-14).** While the current item's Diff Reviewer or CI runs, you may prepare the next queue item read-only: its `--read-only` Architect consult and its Builder brief. Start the consult as an async shell before entering the wait, keep the current item's wait in the foreground (the sync review, the CI watch), and read the consult's output and exit code when that wait returns, so the critical path never queues behind the consult. Make no repository change for anything outside the current item or batch until it is merged or parked; the WIP limit governs building, not read-only preparation. If the current item is parked rather than merged, or a later repair touches a file the consult cites, re-verify those citations before building on them.
>>>>>>> REPLACE
```

### Section 4 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
- **Reading rule.** Search first, then read the range.
=======
- **Reading rule (every role, the orchestrator included).** Search first, then read the range.
>>>>>>> REPLACE
```

### Section 5 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
**Never end a turn waiting on a background or `write_agent` agent without a watchdog.** Start an async shell: `Start-Sleep -Seconds 270` for up to 20 wakes, then `Start-Sleep -Seconds 900`. The shell's completion notification wakes an idle caller (observed 26 times, after up to 38 idle minutes).
=======
**Never end a turn waiting on a background or `write_agent` agent without a watchdog, and never block the turn on the watchdog.** Start an async shell: `Start-Sleep -Seconds 270` for up to 20 wakes, then `Start-Sleep -Seconds 900`, then end the turn — waiting means ending the turn with the watchdog armed. Whichever comes first wakes an idle caller: the agent's completion notification or the shell's (the shell's was observed 26 times, after up to 38 idle minutes). Do not read the watchdog shell (`read_powershell`) for more than 60 seconds at a time: a blocking read is not interrupted by a completion, and on 2026-10-14 reads of up to 10 minutes left seven finished agents waiting 2.1 to 8.0 minutes each (38 minutes in all). If you must stay in the turn, read in slices of 60 seconds or less and `read_agent` between slices. Target, a trial measured like the interval below: under one minute from `subagent.completed` to your next model call.
>>>>>>> REPLACE
```

### Section 6 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
- **Test gates**: Run focused tests for the changed slice and its immediate consumers after each implementation slice.
=======
- **Test gates**: The Builder runs focused tests for the changed slice and its immediate consumers after each milestone; do not re-run each milestone's tests yourself. Instead run **one consolidated focused check** — the Builder's tests plus the immediate consumers, with the focused command below — on each frozen candidate: before the Diff Reviewer's first round, and again before commit if a repair changed the tree. A subagent's test claim stays a hypothesis until that check passes.
>>>>>>> REPLACE
```

### Section 7 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
- **Batched execution (Captain, 2026-08-25)**: Process up to **three bounded issues sequentially**, each with focused tests and a scoped adversarial review. Accumulate their reviewed local commits, **freeze the batch, then run ONE full repository gate** for the whole batch. Push and verify every closure only after that gate is green. A single issue may still take its own gate; the batch exists to stop paying ~15 minutes per issue for the same tree.
=======
- **Batched execution (Captain, 2026-08-25; slices 2026-10-14)**: Batch up to **three tightly coupled items**: slices of the same AD or parent issue, or issues where one depends on another's change, or that change the same production file or the same shared contract (defined under **Adversarial Review Before Every Commit**). Process them sequentially; each keeps its own Builder milestone, consolidated focused check, Diff Reviewer pass and local commit. **Freeze the batch, then run ONE full repository gate** on it, push it as one PR so one CI run covers the gated tree, and verify every closure (or parent-checklist update) only after that gate is green. Gate an item alone only when no coupled item is next in the queue or its blast radius warrants an earlier gate (**Broad-gate currency**). Never batch unrelated items, and never hold a batch open for an item whose review is not ready: freeze what is reviewed. Triage a red batch gate to the slice that caused it, repair and re-review that slice, then re-gate the whole batch. The batch exists to stop paying ~15 minutes per item for the same tree.
>>>>>>> REPLACE
```

### Section 8 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
- Work in progress is limited to **one issue**, or at most **three tightly coupled issues** in a bounded wave.
=======
- Work in progress is limited to **one issue**, or at most **three tightly coupled issues or slices** in a bounded wave (see **Batched execution** under Testing Standards). The limit counts building; read-only preparation of the next item does not (**Delegation and Waiting**).
>>>>>>> REPLACE
```

### Section 9 -- `.github/copilot-instructions.md`
```
<<<<<<< SEARCH
bank the reviewed commit, durable canonical receipt, and parent checklist/evidence update
=======
bank the reviewed commit, the durable canonical receipt (one batch receipt covers every slice in the batch), and the parent checklist/evidence update
>>>>>>> REPLACE
```

### Section 10 -- `CLAUDE.md`
```
<<<<<<< SEARCH
## Workflow (one issue, or a batch of up to three)
=======
## Workflow (one issue or slice, or a batch of up to three coupled ones)
>>>>>>> REPLACE
```

### Section 11 -- `CLAUDE.md`
```
<<<<<<< SEARCH
running only the **focused tests** for each changed slice and its immediate consumers. No full suite.
=======
running only the **focused tests** for each changed slice and its immediate consumers. No full suite. The main session does not re-run each milestone's tests; it runs one consolidated focused check on each frozen candidate (Testing Standards).
>>>>>>> REPLACE
```

### Section 12 -- `CLAUDE.md`
```
<<<<<<< SEARCH
Repair its findings before committing; anything that would break the next run is a blocker.
=======
Repair its findings before committing; anything that would break the next run is a blocker. A repair round re-reviews the delta unless it changes a shared contract (Adversarial Review Before Every Commit).
>>>>>>> REPLACE
```

### Section 13 -- `CLAUDE.md`
```
<<<<<<< SEARCH
4. **Commit locally** — after the pre-commit deletion check
=======
4. **Commit locally** — each slice or issue separately, after the pre-commit deletion check
>>>>>>> REPLACE
```

### Section 14 -- `CLAUDE.md`
```
<<<<<<< SEARCH
5. **Broad gate, once** for the issue or batch:
=======
5. **Broad gate, once** for the issue or batch (slices of one AD, or up to three coupled issues: Testing Standards, Batched execution):
>>>>>>> REPLACE
```

### Section 15 -- `CLAUDE.md`
```
<<<<<<< SEARCH
6. **Push and verify closure** only after a green gate.
=======
6. **Push and verify closure** only after a green gate: one PR for the batch, then every issue or parent checklist it closes.
>>>>>>> REPLACE
```

### Section 16 -- `CLAUDE.md`
```
<<<<<<< SEARCH
Start a background Bash command such as `sleep 900` (`run_in_background: true`); its exit wakes the idle session. On wake, check the agent: if it failed, recover at once; if it is still running, start another `sleep`. Report a failure by when it happened, not by elapsed time since launch.
=======
Start a background Bash command such as `sleep 900` (`run_in_background: true`), then end the turn: the agent's completion notification or the sleep's exit, whichever comes first, wakes the idle session. Never wait in the foreground for more than 60 seconds; a blocking wait delays the resume past the completion. On wake, check the agent: if it failed, recover at once; if it is still running, start another `sleep`. Report a failure by when it happened, not by elapsed time since launch.

**Overlap with read-only preparation** (Delegation and Waiting): launch the next item's `claude-architect` consult with `run_in_background: true` before the current item's foreground wait (a sync Diff Reviewer, a CI watch), and read it when that wait returns. Change nothing for that item until the current one is merged or parked.
>>>>>>> REPLACE
```

**Installer notes:**
- Every SEARCH is inside a single line, so CRLF in the working tree is safe.
- Write any inserted newlines with the file's existing line ending. Git normalizes them to LF in the index.

**Growth:**
- `copilot-instructions.md`: +4 lines (§1, §3), about +3.4K characters, roughly 5% of the file.
- `CLAUDE.md`: +2 lines.

## 6. PR body: Baseline and measurement plan

**Baseline** (Captain, 2026-10-14). Source: `C:\Users\seang\.copilot\session-state\5ad6e802-695c-426d-a88f-868997638877\events.jsonl`, window 15:40–01:07 UTC. Four slices shipped (#1526, #1527, #1528, #1539), about 2 hours each. Per slice:
- own reasoning between steps: ~50 min (1,065 turns, 649 file views, 235 greps);
- Builder: ~35 min (11 runs of 8–17 min);
- Diff Reviewer: ~30 min (5 runs of 20–35 min);
- own focused pytest: ~20 min (162 calls, ~87 min total);
- Architect bridge: ~20 min;
- broad gate: ~15 min;
- CI and PR: ~12 min;
- idle after a subagent had already finished: 38 min over 7 cases, with resume lag of 2.1–8.0 min.

*Caveat:* the components add up to about 182 min per slice against about 142 min of wall time (567 min ÷ 4), so they overlap. Measure the follow-up with the same definitions. Defects found by review, gate or CI in the baseline window still have to be counted by the orchestrator from the same log.

**Follow-up**, after the next three slices or batches. Grouping is per slice, using `measure_agent_token_usage.py --group NAME=REGEX` on delegation display names. Event and field names marked *(exp)* are expectations to verify against the new log.

| Metric | Definition |
|---|---|
| Time per slice | (a) Same method as the baseline: session window ÷ slices shipped. (b) Per batch: from the first orchestrator `tool.execution_start` whose command contains `claude_architect.py` for the batch, to the `tool.execution_complete` of the closure-verification `gh` command, divided by the number of slices. |
| Completion-to-resume lag | For each `subagent.completed` or `subagent.failed` whose `subagent.started.executionMode` is not sync *(exp: value names)*: the first orchestrator `assistant.turn_start`, or `assistant.message` with `apiCallId`, after it, minus the completion timestamp. Report it two ways: **idle** (no orchestrator tool call open at completion) and **busy** (a call open; name its tool, and treat a `read_powershell` over a `Start-Sleep` shell as a defect against change 1). Target: idle lag under 60 s. |
| Builder and Reviewer minutes | Sum of `durationMs` per role (`agentName`) on `subagent.completed` and `subagent.failed`. Also the count of runs. |
| Focused-test minutes | Orchestrator `tool.execution_start` → `tool.execution_complete` pairs whose command matches `pytest` and not `run_test_gate.py`. Also the count of calls (baseline: 162). |
| Gates per slice | Orchestrator commands matching `run_test_gate.py` without `--preflight-only`, divided by slices. Cross-check against `logs/gates/*.receipt.json`. |
| Reviewer rounds per slice | Diff Reviewer `subagent.started` count per slice group. Also split full rounds from delta rounds by brief name. |
| Bridge minutes | Tool executions whose command contains `claude_architect.py`, split into foreground and overlapped. |
| Defects | Review: Critical, High and Medium findings per round, tallied by hand from Reviewer results. Gate: red gate exits. CI: failed required checks per PR (`gh pr checks`, not in `events.jsonl`). Before versus after. |

**What cannot be measured:**
- defects a full re-review would have caught that a scoped one missed (the only lagging signal is later CI failures or issues filed against those slices);
- reasoning time, which is only a residual;
- CI and PR minutes, which come from GitHub rather than the log;
- whether a notification was delivered, since there may be no event for it *(exp)*;
- a sample of three, with uneven slice sizes (report changed lines per slice alongside).

**Revert rule (per the Captain's guardrails):**
- If gate-red or CI-red per slice rises, or a gate or CI defect lands in code that a delta-only review covered, revert §1 and §12.
- If the gate catches a test failure the consolidated check should have caught, revert §6.

## 7. Acceptance criteria, validation, do-not-build list, milestones

**Acceptance criteria**
1. Sections 1–16 are applied byte-exact. Each SEARCH matched exactly once.
2. Nothing in either file or in the 7 agent files says that ending a turn while waiting is forbidden, or that a parent-backed slice needs its own receipt.
3. "A single issue may still take its own gate" no longer exists.
4. Every standing order listed in the Captain's guardrails is still present, verbatim: sync review (line 63), the receipted gate on the committed tree (line 188), verified closure (line 87), the watchdog requirement, and the Reviewer model pin (line 43).
5. `copilot-instructions.md` grows by 25 lines or fewer, and `CLAUDE.md` by 8 or fewer.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Validation (docs only)**
- Consolidated focused check: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1231_hybrid_coordination_principle.py tests/test_measure_agent_token_usage.py -q -n 0 -p no:randomly`
- Then the Diff Reviewer (GPT-6.1 Sol, sync).
- Then `run_test_gate.py --preflight-only`, a local commit, and the single receipted gate (`--label wallclock-orders --receipt logs/gates/wallclock-orders.receipt.json`).
- Then a PR with the 4 required CI checks.

**Do not build**
- no new scripts (lag is measured with ad hoc queries and the existing `measure_agent_token_usage.py`);
- no CI or gate-wrapper change;
- no model-pin change;
- no edit to agent files (`claude-builder.md:161` is consistent as it stands);
- no "failure-only output" rule (a follow-up, below);
- no weakening of any standing order;
- no tracker edits, and no AD number.

**Milestones.** One Builder milestone is warranted, per the Captain's "normal flow". Name it `wallclock-docs-1` and run it with `reasoning_effort: high`, as line 69 provides for docs edits.

*Builder brief:*
- Apply Sections 1–16 of this contract.
- Audit with grep that none of the files below contradicts the new text:
  - `.github/agents/*.agent.md`
  - `.claude/agents/claude-*.md`
  - `config/standing_orders/builder.md`
  - `config/standing_orders/architect.md`
- Report the line and character growth.
- Run the two focused tests.
- Follow the reading rule (line 68).

**Diff Reviewer brief hints** (properties to verify; about 1.5 KB):
1. Each of the 5 changes is encoded, and every guardrail sentence listed in acceptance criterion 4 survives unchanged.
2. No pair of sentences contradicts:
   - watchdog requirement versus "end the turn";
   - line 61 "synchronously" versus the overlapped consult;
   - the WIP limits (lines 85 and 121) versus overlap;
   - line 130's receipt versus the batch gate.
3. The shared-contract list and the coupling test can be decided from a diff or the issue graph alone.
4. The consumer `scripts/measure_agent_token_usage.py:350` still classifies the watchdog commands as watchdog sleeps.
5. The CLAUDE.md workflow agrees with Testing Standards and Delegation and Waiting.
6. The agent files do not contradict the new text.

Read `git diff --cached -- <path>` per file. Start from Adversarial Review and Evidence Standard.

## Prior art and blind spots

**Considered and rejected:**
- **Tighter polling everywhere:** a model call every minute over a context of about 426K tokens, when ending the turn costs nothing.
- **Parallel or concurrent gates:** two 15–19 min `-n 16` suites on one machine compete for it, and a gate on an unfrozen tree is invalidated anyway.
- **Skipping per-slice review:** a guardrail.
- **A background Reviewer to enable overlap:** loses the sync failure handling at line 63 and brings back the lag.

**Adopted from merge-queue practice:** batch the gate, then trace a failure back to one batch member, which per-slice commits make possible. This is general knowledge of merge queues; I fetched no source, because this is ProbOS process plumbing with little outside analogue.

**Gaps the baseline points to that the five changes do not cover** (follow-ups, not edits):
- The orchestrator's ~50 min of reasoning per slice is the largest cost, and only §4 touches it. Measure its repeated reads with the existing report.
- 2.75 Builder runs per slice suggests the milestone sizing should be checked.
- The "failure-only test output" rule from #1518 is not written down anywhere.
- The baseline components overlap, so the after-numbers are only comparable if the same definitions are used.

## Orchestrator amendments (2026-10-14, after the Builder audit and the orchestrator's read of the applied text)

1. **Scope of the 60-second rule.** Section 5 named only the watchdog shell, and CLAUDE.md's sentence (Section 16) said "never wait in the foreground for more than 60 seconds", which a reader could apply to the sync delegation that the overlap paragraph itself uses. Both now state the mechanism: while a background agent is running, do not read any background shell (the watchdog, a gate, a campaign, the Architect bridge) for more than 60 seconds at a time, and a sync delegation, which returns when it completes, is not covered. Evidence: the repo's `scripts/measure_agent_token_usage.py` on this session's log classifies 35 long `read_powershell` calls (300 minutes), of which 5 were watchdog sleeps (37 minutes); the rest were gates, campaigns, diagnostics and bridge calls.
2. **Baseline caveats found by re-deriving it from the log (they go in the PR body).** The orchestrator's own counts are 573 turns, 119 file views and 67 greps; the 1,065 / 649 / 235 figures are all-agent counts (subagents: 489 turns, 530 views, 188 greps). "162 focused pytest calls, about 87 min" is not reproducible by any definition tried (orchestrator only: 24 synchronous calls, 20.0 min; all agents: 107 calls, 38.4 min). Idle after a completion, orchestrator events only: 9 cases, 47.1 min, range 2.1 to 8.0 min (the Captain's figure: 7 cases, 38 min).
3. **Builder audit (wallclock-docs-1, Sonnet 5.5, effort high).** All 16 sections are present once; the seven consistency pairs are CONSISTENT; the guardrail sentences are present; 35 focused tests pass. It noted that `.claude/agents/claude-builder.md` lines 23 and 161 and `.claude/agents/claude-architect.md` line 277 say "once per issue or batch (up to three issues)": stale but not contradictory. Per the contract's do-not-build list they are not edited.
