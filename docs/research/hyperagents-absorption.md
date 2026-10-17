# HyperAgents Absorption

*Sean Galliher, 2026-10-15*
*Source: "Hyperagents" (Jenny Zhang, Bingchen Zhao, Wannan Yang, Jakob Foerster, Jeff Clune, Minqi Jiang, Sam Devlin, Tatiana Shavrina; UBC and FAIR / Meta Superintelligence Labs), [arXiv 2603.19461](https://arxiv.org/abs/2603.19461), 2026-03-19. Read: the abstract and the first 100,000 of about 179,000 characters of the HTML text. Section 6 (safety discussion) was read in part. The cost appendix (D.2), the meta-capability details (E.3), the outer-loop results (E.5) and Appendix F were not read. Related prior art for the procedures below is listed at the end.*

## Purpose

This note records which patterns from HyperAgents ProbOS absorbs, which it rejects, and where each absorbed idea is owned. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note is the durable link between the source and the issues below. It follows the Darwin Gödel Machine note (`darwin-godel-machine-absorption.md`), which HyperAgents extends.

## What HyperAgents is

- **The problem it addresses.** DGM improves only when getting better at the task also means getting better at self-improvement. That holds for coding. The paper argues it "does not generally hold beyond coding domains".
- **The mechanism.** A *hyperagent* is one editable program holding a **task agent**, which does the work, and a **meta agent**, which modifies agents and may rewrite itself. The paper calls this metacognitive self-modification. The archive, parent selection (proportional to score, inversely to compiled children; m=3, λ=10) and staged evaluation are inherited from DGM.
- **What stays fixed on purpose.** Parent selection and the evaluation protocol. Keeping them fixed "improves experimental stability and safety, but limits full self-modifiability".
- **Results** (test sets):
  - paper review: 0.0 initially, 0.0 for DGM, 0.590 for DGM-custom, **0.710** for DGM-H, against 0.630 for the static AI-Scientist-v2 reviewer;
  - robotics reward design: 0.060, 0.0, 0.348, **0.372**;
  - Olympiad math grading: 0.610 from the initial agent and 0.640 from a transferred agent, against 0.670 for ProofAutoGrader. Seeded from ProofAutoGrader, it reached 0.700;
  - Polyglot coding: 0.267, below DGM's 0.307.

  Without self-improvement, or without open-ended exploration, paper review stayed at 0.0.
- **Meta-level capabilities it evolved.** A `PerformanceTracker` (scores per generation and domain, with a moving-average trend). Persistent memory of insights, causal hypotheses and plans, consulted in later generations: for example, "Gen55 has best accuracy but is too harsh".
- **Transfer.** Transferred meta agents reached imp@50 = 0.630 on math grading; transferred DGM-custom agents reached about 0.0. What transfers is the improver, not the domain agent. Gains accumulated across runs (0.640 vs 0.610), but not significantly (p > 0.05).
- **Safety, as far as read (Section 6, in part).** Sandboxing, timeouts, restricted internet, predefined tasks and metrics, and human oversight. The authors warn that safeguards "may become increasingly strained" as systems "evolve faster than human oversight". In one logged run, the agent's own memory flagged a regression after an over-correction produced a 94% accept rate. No reward hacking was reported in the part read.

## Absorbed

| # | HyperAgents pattern or finding | ProbOS gap (verified 2026-10-15) | Owner |
|---|---|---|---|
| 1 | **Revisions replace their parent only when an evaluator they cannot touch says they are better**, with lineage kept. | Two pieces already exist. AD-1326 (#1510) is the champion/challenger for Cognitive JIT procedures: wired and on by default when the procedure store and ledger exist (`config_models/cognition.py:168-177`), with held-out cases, a judge asked in both orders, lineage kept (`cognitive/procedure_challenger.py:1-25`). AD-1287's `ExecutionProfile` binds a skill's digest to the model, prompts, tools, policy and evaluation suite (`cognitive/execution_profile.py:3-18`), but it is unwired, and it checks an absolute threshold, not a parent. The skill catalog keys skills by name (`name TEXT PRIMARY KEY`, `cognitive/skill_catalog.py:37`); `import_skill` refuses a duplicate (`:668-671`) and `register` overwrites (`:309`), so a revision cannot sit beside its parent. SkillForge (AD-1069) is never constructed in production. | AD-1338 (#1565): a skill-refinement loop that generalizes AD-1326 and reuses AD-1287, with model-specific variants. |
| 2 | **The outer loop stays fixed**: selection and evaluation are never changed by the loop. | AD-1336's 2026-10-15 amendment covers grader edits for self-maintenance. AD-1299 had no class for improvements to the improver itself. | AD-1299 (#1352), amendment of 2026-10-15: a meta-level authority class. The improver's instruction text may change under evaluation; suites, judges, selection, approvals, review, the gate and the write boundary are never changed by the loop. |
| 3 | **The improver, not the worker, is what transfers.** | Same owner as row 2: the meta-level class makes improver changes possible, under evaluation, without opening the outer loop. | AD-1299 (#1352) amendment. |
| 4 | **Persistent memory and performance tracking** were among the capabilities the meta agent developed for itself. | ProbOS provides both as infrastructure: episodic memory, notebooks and Ship's Records for memory; trust, earned agency and Ship Trials (AD-1186, #1123) for performance. | Already owned. HyperAgents is external evidence that a self-improving loop needs them. |
| 5 | **Self-improvement beyond coding** (reviewing, grading, reward design). | The crew's non-code work had no loop for improving skills against measured outcomes. Agents can't yet edit their own instructions: nothing writes agent-tier standing orders (AD-339), and nothing creates `LEARNED_LESSON` directives. | AD-1338 (#1565) for skills and self-authored tools (the performance loop). AD-1339 (#1566) for the instruction audit (the identity loop). |

## The two loops

The Captain's own procedures for persistent agents shaped AD-1338 and AD-1339. Those procedures are an instruction audit and a build-your-own-tools rule. Together the two ADs split self-improvement into two loops that touch only through typed records:

- **Performance loop (AD-1338).** Skills and agent-authored tool scripts improve by revision against recorded outcomes. A revision is scored by a fixed evaluator and promoted only when it beats its parent, with the Captain's approval at first. Lineage is kept, and variants are specific to each model. Usage counts come from service records only.
- **Identity loop (AD-1339).** An agent audits its own instructions on a schedule, with authority graded by file class:
  - operational fixes are applied and recorded;
  - persona changes are proposed and reviewed by the Counselor, then the Captain;
  - identity changes are proposed only when they have genuinely become true, and blanks are never force-filled;
  - memory is deleted only when plainly stale, and otherwise proposed.

  It is never optimized against a score. Its standing-cost check nominates rarely used notes and recurring personal scripts to the performance loop, and only reads the verdicts that come back.

No prior art reviewed here grades an agent's authority over its own files by class.

## Rejected or deferred

- **An editable outer loop.** HyperAgents itself keeps selection and evaluation fixed, and its preliminary outer-loop results (Appendix E.5) were not read. ProbOS keeps them fixed by rule (AD-1299 amendment, AD-1336 amendment).
- **Open-ended population search.** Rejected on cost, as for DGM. HyperAgents' own cost appendix was not read.
- **Optimizing character against a score.** Rejected. The identity loop may *detect* drift against a behavioral baseline, but drift is never an optimization target.

## Related prior art for the two loops

These are cited in the Prior Art sections of AD-1338 and AD-1339. Figures are as reported by search summaries, not verified against each paper. Only Voyager and Letta, which other notes also cite, have rows in `reference-projects.md`.

- Voyager ([arXiv 2305.16291](https://arxiv.org/abs/2305.16291)): a skill library admitted only after self-verification.
- LLMs as Tool Makers: a strong model makes a tool and a cheap model uses it.
- SkillWeaver ([arXiv 2504.07079](https://arxiv.org/abs/2504.07079)): skills are proposed, synthesized and honed. Tools from strong agents improved weak agents.
- Alita: builds MCP tools from minimal predefinition.
- MASA ([arXiv 2605.30723](https://arxiv.org/abs/2605.30723)): "skill effectiveness is strongly model-dependent".
- Letta: memory blocks and sleep-time agents.
- Anthropic persona vectors: trait monitoring at the activation level.
