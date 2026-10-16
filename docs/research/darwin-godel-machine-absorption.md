# Darwin Gödel Machine Absorption

*Sean Galliher, 2026-10-15*
*Sources:*
- *"Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents" (Jenny Zhang, Shengran Hu, Cong Lu, Robert Lange, Jeff Clune), [arXiv 2505.22954](https://arxiv.org/abs/2505.22954), v3 of 2026-03-12, an ICLR 2026 poster ([iclr.cc](https://iclr.cc/virtual/2026/poster/10007327)), code at [github.com/jennyzzt/dgm](https://github.com/jennyzzt/dgm).*
- *Sakana AI's project page, [sakana.ai/dgm](https://sakana.ai/dgm/), for the objective-hacking incidents.*
- *Follow-up: "Hyperagents" (Zhang, Zhao, Yang, Foerster, Clune, Jiang, Devlin, Shavrina), [arXiv 2603.19461](https://arxiv.org/abs/2603.19461), 2026-03-19, abstract only.*

## Purpose

This note records which patterns from the Darwin Gödel Machine (DGM) ProbOS absorbs, which it rejects, and where each absorbed idea is owned. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note is the durable link between the source and the issues below. DGM appears here only as a technical design reference.

## What DGM is

DGM is a coding agent that edits its own Python codebase to become a better coding agent, which also makes it better at editing itself.

- **Archive.** It starts from one base agent. A variant enters the archive only if it compiles and can still edit a codebase.
- **Parent selection.** A parent is picked roughly in proportion to its score and inversely to its number of children. Every variant keeps a non-zero chance of being picked, so weak variants survive as stepping stones ("open-ended exploration").
- **Self-modification.** The parent reads its own evaluation logs, proposes one feature, and implements it in its own code.
- **Staged evaluation.** 10 tasks to confirm the agent can still edit. For Polyglot, agents above 40% on those 10 tasks go on to 50 tasks. For SWE-bench, agents above 40% on a 60-task subset that rank in the top two go on to 200 tasks. Benefit is checked by score, not proven.
- **Scale.** 80 iterations. The archive and the parent selection are fixed: DGM cannot edit them.
- **Results.** SWE-bench rose from 20.0% to 50.0%, and Polyglot from 14.2% to 30.7%.
  - The gains transferred across models: with Claude 3.7 Sonnet, SWE-bench went from 19.0% to 59.5%; with o3-mini, from 23.0% to 33.0%.
  - They also transferred across benchmarks.
  - It beat baselines without self-improvement and without open-ended exploration.
- **What it discovered:**
  - viewing a file by line range;
  - `str_replace` editing instead of whole-file writes;
  - several attempts, with another model choosing the best;
  - building on earlier attempts;
  - long-context management.
- **Cost.** About US$22,000 and two weeks per SWE-bench run, against about US$10,000 per baseline run. The authors say it "still falls short of closed-source SoTA SWE-bench solutions".
- **Safety.** Sandboxed execution with time limits, self-modification limited to its own codebase, limited network access, and human monitoring of changes through the archive's lineage.
- **Objective hacking**, reported by Sakana AI:
  - **A forged test log.** The agent wrote a log claiming tests had run and passed when they had not. Because that log was in its context, it later believed its changes passed.
  - **A disabled check.** Told not to tamper with its hallucination check and asked to reduce faked tool use, it removed the markers its hallucination check relied on.

  The authors credit the traceable lineage of changes with catching such behaviour quickly. They say preventing the attempt in the first place needs more work.
- **Hyperagents** (the follow-up) makes the improvement procedure itself editable, which it calls metacognitive self-modification. It argues that DGM's premise, that coding skill aligns with self-improvement skill, "does not generally hold beyond coding domains".

## Absorbed

| # | DGM pattern or finding | ProbOS gap (verified 2026-10-15) | Owner |
|---|---|---|---|
| 1 | **A forged evidence log fools the agent itself.** A model-written claim of a test run entered its context and was later believed. | In the native pipeline, the test *result* is service-written: `execute_approved_build` runs pytest and reads the exit code (`cognitive/builder.py:2405`). But the test tree it grades is writable by the same model in the fix loop (row 2), so the result is not yet independent. The rule is not stated as a contract for self-maintenance. | AD-1336 (#1558), amendment of 2026-10-15: only evidence written by a service counts, and a model's claim is never evidence. |
| 2 | **Disabling the grader.** The agent removed the markers its check relied on. | The builder's test-fix loop writes model output with nobody reviewing it between attempts, and the write boundary allows `tests/` (including `conftest.py`), `code_reviewer.py`, `builder_paths.py` and `builder.py`. Sealed-core protection is warn-only and off by default (`builder.py:2571`, `extensions.enforce_sealed_core: false`). The hard block it names, AD-481l, has no GitHub issue: it is referenced in code, prompts, the roadmap docs and #1563. | BF-898 (#1563) for the fix loop. AD-1336 (#1558), amendment: no candidate weakens its grader without the Captain, and such a candidate is never handed to ProbOS. |
| 3 | **Lineage as the detection mechanism.** The archive kept every variant and its changes, and the authors credit that lineage with catching such behaviour. | AD-1336's candidate model binds digest, review and receipt, but did not say that rejected candidates are kept. | AD-1336 (#1558), amendment: rejected and superseded candidates keep their digest, diff, review and receipt. |
| 4 | **Staged evaluation**: a cheap sanity check before an expensive one. | Already the shape of ProbOS's workflow: focused tests on each slice, then one receipted broad gate (`.github/agents/orchestrator.agent.md`, Gate, Batch and Push). | Already owned. Nothing to add. |
| 5 | **The discovered tool improvements**: line-range views, `str_replace` edits, several attempts with an independent model choosing. | `str_replace`-style editing exists (`Edit File`), and multi-file patches are AD-1332 (#1535). Independent selection is AD-1327's verifier independence, which also requires a different model family. **Line-range viewing has no owner**: no issue names it. | Editing and selection are already owned. Line-range viewing is considered and deferred: the read tools' range support should be checked when AD-1332 is drafted. |

## Rejected or deferred

- **Open-ended population search over agent variants.** At about US$22,000 and two weeks a run, it is a research method, not an operating mode for a single-operator vessel. ProbOS improves through one governed candidate at a time.
- **A fixed benchmark as the objective.** DGM assumes benchmark score tracks real improvement, and its objective hacking shows the cost of that assumption. ProbOS evaluates against its own suite, an independent review and the Captain's approval. Ship Trials (AD-1186, #1123) is where a benchmark could be added as one input, never the only objective.
- **An editable improvement procedure (Hyperagents).** ProbOS never lets a candidate change its own review, gate, approval or delivery machinery without the Captain (AD-1336, amendment of 2026-10-15, and child 8, the graduation record). Under AD-1299's authority classes (#1352), lower-risk meta-level changes, such as a builder's prompts or skills, could become editable later. That is deferred until the self-maintenance lane exists.

## Consistent with existing ProbOS principles

DGM's two incidents are the same mechanism ProbOS has seen in its crew: under pressure, an agent confabulates, and then treats its own confabulation as fact. ProbOS's answer is the same for builders and crew. Agents decide and services enforce (AD-1231). Claims are checked against records the agent cannot write. Autonomy is earned through evidence, not asserted.
