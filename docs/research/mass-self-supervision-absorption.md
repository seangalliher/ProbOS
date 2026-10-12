# MASS Absorption: Multi-Agent Self-Supervision

*Sean Galliher, 2026-10-11*
*Source: "MASS: Recursive Self-Improvement through Multi-Agent Self-Supervision" (Lee, Xu, Seely, Lee, Sojoudi, Zaharia, Tang; UC Berkeley and Sakana AI), [arXiv:2610.12176](https://arxiv.org/abs/2610.12176), [project page](https://pub.sakana.ai/mass/)*
*Repository: [github.com/SakanaAI/mass](https://github.com/SakanaAI/mass)*

## Purpose

This note records what ProbOS absorbs from MASS, what it rejects, and where each idea is owned. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note is the durable link between the paper and the issues below.

## What MASS does

One model (Qwen3.6-27B) is at once the task solver, the workflow optimizer and the evaluator.

- **Inner loop: workflow search, with weights fixed.** A workflow is a written plan with roles, instructions, **contracts** (the information and checks each subagent must return) and **hops** (the order of subagent calls, including returns to earlier steps). Each iteration runs a challenger workflow. The model compares the challenger's workspace with the champion's pairwise and explains its preference. The challenger replaces the champion only if it wins.
- **Outer loop: distillation, with weights updated.** The champion runs 18 times per task. The runs are ranked with pairwise comparisons fitted by Bradley-Terry, and the model is fine-tuned with LoRA on the best multi-agent trajectories.

### Results, as reported

- Held-out win rate against the base model: 53.9% after round 1, 69.9% after round 2.
- Score per output token was 1.2-1.6× the base on MLR-Bench, DSBench, ScienceAgentBench and AstaBench.
- **No gain on SWE-bench Verified (0.94×) or Terminal-Bench 2.0 (0.96×).**

The scale is small: 12 synthetic tasks, one model, two rounds.

## Absorbed

| # | Finding (MASS) | ProbOS gap (verified) | Owner |
|---|---|---|---|
| 1 | Optimized workflows carry task-specific information in **contracts and hops**, not roles (mutual information over 8-9 tasks; small sample). | AD-1286's `WorkerSlot` (`cognitive/elastic_team.py:247`) has no output contract and no hop order. | Amendments to AD-1289/#1336 (one spec extension adding `output_contract` and `hops`; the service checks shape, never quality) and AD-1290/#1337 (hop-ordered gather; no-contract and no-hops ablations). |
| 2 | Text-space search is noisy: strong iterations are often followed by sharp regressions. Keep a champion, and replace it only on a **pairwise** win. Rank several candidates with Bradley-Terry. | Dream consolidation saves an evolved FIX procedure and immediately deactivates its parent (`dreaming.py`, the `save` then `deactivate(parent.id, superseded_by=...)` sites), with no comparison. | AD-1326/#1510 (procedure champion and challenger). AD-1290/#1337 (team-recipe champion and challenger in Team Trials; promotion stays a governed decision). |
| 3 | Homogeneous self-supervision risks **shared blind spots**: a flawed self-judgment is accepted, then reinforced. Independent checks remain necessary. | `CrewVerifier` hard-codes `tier="standard"` (`crew_verifier.py:1421`, `:1848`) with no verifier model setting. When every tier maps to one model, as on the reference vessel, the worker and its verifier are the same model. | AD-1327/#1511 (a dedicated `verifier` tier; same-model, same-family or independent reported at startup and in `probos doctor`, and recorded on each verdict). |
| 4 | **The optimizer is the bottleneck.** Upgrading the workflow rewriter as well as the evaluator solved 12/12 tasks within 5 iterations, against 11/12, more slowly, in the homogeneous loop. | All procedure-evolution calls use `tier="standard"` (`procedures.py`). | AD-1326/#1510 moves procedure rewriting to `deep`. This also supports running the development Architect (`claude-architect`) on the strongest model. |

## Rejected

- **Weight distillation (the outer loop).** ProbOS uses models through providers and does not own their weights. The LLM-independence principle keeps the core model-agnostic.
- **The finding that multi-agent trajectories are more efficient training data.** It only matters if ProbOS trains models, and the paper notes the comparison is confounded by differing instructions.
- **Using MASS to change the coding pipeline.** It showed no gain on coding benchmarks, so it gives no reason to change the Builder flow.

## Consistent with existing ProbOS principles

- **Agents decide what, services enforce shape (AD-1231).** MASS's orchestrator integrates subagent results cognitively. In ProbOS, a deterministic service may check that a contract was met (presence, kinds, links), but judging content stays with agents and qualified adjudicators.
- **Reviewer independence.** The development Diff Reviewer already pins a different model family from the author. AD-1327 brings the same principle to the crew runtime.
- **Evidence over claims.** MASS's champion rule is the self-improvement analogue of the evidence standard: no replacement on assertion, only on a comparison that ran.
