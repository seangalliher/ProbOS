# Harness² Absorption

*Sean Galliher, 2026-10-18*
*Sources (the abstract, the README, and the first 100K of about 169K characters of the HTML paper were read; the remainder was not):*
- *Xu et al., "Harness²: Recursive Agent Harnessing for an Open World", [arXiv 2610.14224](https://arxiv.org/abs/2610.14224), 2026-10-09 ([HTML](https://arxiv.org/html/2610.14224)).*
- *Code: [google-research/harness2](https://github.com/google-research/harness2), Apache 2.0, "not an officially supported Google product". The Captain found it through a one-star fork, `henri-edh/google-harness2`, which adds nothing to the original.*

## Purpose

Harness² improves the harness around a fixed model, both within a task and across tasks, without a ground-truth verifier. It is the closest published design yet to ProbOS's meta-level self-improvement (AD-1299, #1352) and to skill and tool admission (AD-1338, #1565). This note records what the paper shows, what ProbOS absorbs, and where each idea is owned. These are technical design references only.

## What the research shows

- **Two levels of recursion.** Task-level recursion refines the execution harness for the current task. Harnessing-level recursion turns the experience from those edits into a separate "continual improvement harness" for future tasks. Model weights, stage instructions and the decision rule stay fixed. Only the library changes (§2.3).
- **Propose–Probe–Compose, without ground truth** (§2.2.1).
  - *Propose:* the current harness runs once as a reference. Two candidate edits are proposed: an **invariant** one for recurring agentic weaknesses (planning, tool use, context management, delegation) and a **domain-specific** one for task knowledge and constraints.
  - *Probe:* each candidate runs on the same task under matched model and environment settings, and its trajectory and deliverable are compared with the reference: was the targeted weakness mitigated, unchanged, or worse?
  - *Compose:* an editor model (Claude Opus 4.8 in the main experiments) reads the reference, the candidates, the diffs and the evidence, then merges supported changes, adopts one candidate, or keeps the current harness.
  - The paper says the contrasts "inform subsequent composition rather than verify task correctness", and acknowledges that execution stochasticity and shared model biases limit how reliable the evidence is.
- **The improvement library** (§2.3). Each entry is an executable harness plus an `EXPERIENCE.md` that records the applicable situation, the lessons and the supporting evidence, with an index for on-demand lookup. A reflection step after each task admits lessons only when execution contrasts support them, and adds no entry when evidence is weak. Selecting an output alone is not treated as evidence of transferability. Later tasks start from the **base** harness and reuse earlier components only through the Propose step, never by automatic inheritance. The library is frozen during a task and updated afterwards (§2.1). No retirement or eviction mechanism is described.
- **Grader isolation** (Appendix B). Benchmark graders are reserved for evaluation, and rubrics are never shown to the executor, editor or selector.
- **Results.** One step improves GLM-5 and Gemini 3.5 Flash across three benchmarks and four model-harness configurations: up to 11.5 points on WorkBuddy-Bench, 4.5 on JobBench and 11.8 percentage points on LAB, with gains increasing with the task-level budget.
- **Ablations** (Table 3; k=1, Gemini 3.5 Flash under OpenCode):

  | Removed | WorkBuddy-Bench | JobBench |
  |---|---|---|
  | Library | −3.1 | −1.8 |
  | Scoped editors | −2.9 | −3.7 |
  | Composition | −1.6 | −1.9 |

- **Transfer.** A library built on JobBench improves one-step WorkBuddy-Bench results by 0.6, 0.5 and 2.9 points (Code, Web, Office). This is a retrospective test, not online adaptation.
- **Budget is not monotonic.** The Harness Scaling baseline "regresses from k=2 to 3 on both domains" (Analysis, "Effect of Task-Level Recursion").
- **Safety settings.** The README states that executor network access is "unrestricted" and that Codex "runs with its sandbox disabled", and warns that public rubrics may be reachable online.

## Absorbed

| # | Pattern | ProbOS use | Owner |
|---|---|---|---|
| 1 | Matched probes as evidence | For tasks with no deterministic suite, compare a candidate against a reference run on the same task with model, budget and environment fixed. Recorded as **advisory** evidence only, never in place of owned-step review or the receipted gate | AD-1299 (#1352), [comment](https://github.com/seangalliher/ProbOS/issues/1352#issuecomment-6252810265) |
| 2 | Invariant and domain-specific edits as separate candidates | A general fix and a task-specific one are reviewed, recorded and rolled back independently | AD-1299 (#1352) |
| 3 | Scoped editors | One editor per harness component. Independent evidence for the Billet Instruction Principle (AD-651) | AD-1299 (#1352) |
| 4 | Frozen during a run | The improvement library and the improver's procedures change only between campaigns, through review | AD-1299 (#1352) |
| 5 | A lesson record that carries its evidence | A promoted skill or tool keeps a sidecar: situation, lesson, and links to the evaluator verdicts behind it. Matches the lessons-learned shape used for crew lessons | AD-1338 (#1565), [comment](https://github.com/seangalliher/ProbOS/issues/1565#issuecomment-6252810024) |
| 6 | Selection is not evidence | Being picked or used never admits a candidate. Admission still needs the fixed evaluator's `better` verdict | AD-1338 (#1565) |
| 7 | Start from the base, pull lessons in | A role starts from its promoted set and pulls candidates in by retrieval. Unpromoted edits never carry over by default, which guards against compositional drift | AD-1338 (#1565) |

## Rejected or deferred

- **An LLM editor as the deciding judge.** Rejected. The paper itself names shared model biases as a limit, which is the correlated-error risk in `diversity-scaling-absorption.md`. In ProbOS the fixed evaluator and the Captain decide, and LLM comparisons are advisory.
- **Raising the recursion budget by default.** Rejected. A baseline regressed from k=2 to k=3. Any budget is measured per task class.
- **The default execution settings** (unrestricted network, Codex sandbox disabled). Rejected. Harness² is a design reference, never a runtime dependency.
- **Retirement.** Not absorbed, because Harness² has none. AD-1338 already makes retirement a lifecycle step.

## Consistent with existing ProbOS principles

Harness² keeps the model, the decision rule and the graders fixed, and lets only the library change, between tasks. That is the fixed-spine rule in `self-evolving-harness-absorption.md` and the DGM rule in `darwin-godel-machine-absorption.md`: the parts that judge improvement stay out of the improver's reach.
