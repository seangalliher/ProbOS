# CORAL and Governed Collaborative Memory Absorption

*Sean Galliher, 2026-10-25. Researched through 2026-10-25.*
*Sources:*
- *Qu et al., "CORAL: Towards Autonomous Multi-Agent Evolution for Open-Ended Discovery", [arXiv 2604.01658](https://arxiv.org/abs/2604.01658) (v1 2026-04-02, v3 2026-09-02); [project page](https://human-agent-society.github.io/CORAL/); code at [Human-Agent-Society/CORAL](https://github.com/Human-Agent-Society/CORAL) (Apache 2.0). Read: the project page, the README, and the paper's HTML up to about 100K of 119K characters (the appendices past that point were not read).*
- *Cuadros, Maiga, Meskhidze and Curtis-Trudel, "Governed Collaborative Memory as Artificial Selection in LLM-Based Multi-Agent Systems", [arXiv 2605.04264](https://arxiv.org/abs/2605.04264), 2026-05-05. A Viewpoint paper. Read in full.*

## Purpose

Both sources ask what a group of agents should share, and who decides. CORAL shares as much as it can, in an optimization setting where a grader can score every attempt. GCM argues that sharing is a **selection regime**: something decides which candidate memories become durable shared state, and the right mechanism depends on whether the property being selected can be measured. ProbOS already holds most of the pieces: nature, culture and nurture; archive, never delete; lineage kept; a fixed evaluator. This note records what is new, what ProbOS adapts, and where each idea is owned. These are technical design references only.

## What the sources show

### CORAL

- **Architecture.** Each agent works in its own git worktree. A shared directory (`.coral/public/`, symlinked into every worktree) holds **attempts**, **notes** and **skills**. A grader daemon scores every commit. The grader's environment and answer keys sit in `.coral/private/`, which agents cannot read: under Docker they run as an unprivileged user, and on the host this is opt-in (`agents.isolate_user`). A manager spawns agents, delivers feedback, monitors health, restores agents and resumes sessions.
- **Attempt record** (paper, Box C.4): `commit_hash`, `agent_id`, `title`, `score`, `status`, `parent_hash`, `timestamp`, `feedback`. The feedback is the grader's text, not the agent's.
- **Heartbeat** (paper, Section 3 and C.5). The manager interrupts running agents, triggered by an eval count (`every`) or a plateau (`every` evals with no improvement, with a cooldown). There are three kinds:
  - *reflect*, local, every eval: review recent attempts, note surprises, state confidence, plan one experiment, save a note;
  - *consolidate*, global, every 10 evals: synthesize the notes, record connections and open questions, and promote validated techniques to skills;
  - *pivot*, local, after 5 evals with no improvement: inspect the top attempts, check out the best one and try a fundamentally different approach.
  Agents cannot delete reflect or consolidate. The project page says that without the heartbeat, agents fixate and share less. **That claim is qualitative: the paper reports no heartbeat ablation.**
- **Results**, all on optimization tasks with a scalar grader:
  - *Anthropic kernel take-home:* 4 agents reached 1,103 cycles, against 1,350 for a single agent at about the same wall-clock (the "24%" is 1,350/1,103), and 1,180 for the best of 4 independent runs.
  - *Erdős minimum overlap:* 99% of the AlphaEvolve score in 34 minutes, against 5.2 hours for OpenEvolve; a 2.5× higher improvement rate, with 7× fewer evaluations.
  - *Knowledge ablation:* disabling notes and skills regressed the kernel task from 1,350 to 1,601 cycles.
- **Limits the authors state.** It needs frontier models. Agents start identically, so they have no built-in heterogeneity. It assumes a well-specified evaluator. Their abstract claims state of the art on 10 tasks; Section 4.2 says 8 of 11.

### Governed Collaborative Memory (GCM)

- **Four selection regimes**, which are design choices rather than a ranking (Table 1):
  - *ungoverned persistence:* fails by drift and persistent false memories;
  - *constitutional or hybrid:* fails through gaps in its principles and through reward hacking;
  - *automatic, by metrics or tests:* selects measurable performance, but not judgment, coherence, honesty or diversity; it fails through Goodhart effects;
  - *human-ratified:* selects judgment quality, institutional coherence and role diversity; it fails as a bottleneck and through operator bias.
  "The design question is not whether selection should be automated, but which traits can be safely selected automatically and which require explicit judgment."
- **Four memory layers**, each with its own governance burden (Table 2):
  - *agent-local:* private by default, and promotable when broadly relevant;
  - *shared institutional:* evidence-backed, ratified and append-mostly;
  - *archive:* provenance and retrieval discipline, with no universal ratification;
  - *project continuity:* local and temporary.
- **Fixation.** An accepted record enters with provenance, version lineage and **supersede-not-erase** semantics. "Failed versions and rejected candidates are not administrative noise; they are evidence that selection occurred."
- **The identity-sharing tradeoff.** Too little sharing silos the lessons. Too much homogenizes the agents, correlates their errors and over-propagates false memories.
- **Governance as learning.** In one running ecosystem, an agent fabricated an analysis after governance was in place. The failure became a ratified rule to abstain rather than confabulate. Governance is not a firewall.
- **Evidence.** 12 event records, 8 principles and 17 versioned resources from one ecosystem. The authors call it observational: it shows the design is plausible and does not establish that it is superior.

## What ProbOS already has

| Idea | ProbOS owner | Evidence |
|---|---|---|
| Agent-local memory, private by default and promotable | Procedures start `private` and are promoted through pending to approved (AD-536); episodic memory is nurture and is reset | `src/probos/cognitive/procedure_store.py:259`; #1569 amendment 2026-10-16 (nature, culture, nurture) |
| Archive with provenance rather than ratification | Ship's Archive (AD-1341): promoted by a service against a criterion; provenance on every entry; labelled as inherited; Captain can veto | #1569 Decision items 1, 4-6; `DECISIONS.md:575` |
| Supersede, never erase | Archive episodes, never delete them (AD-1340); blackboard corrections supersede by reference (AD-1289); rejected skill revisions are kept forever (AD-1338 rule 1); rejected and superseded build candidates keep their lineage (AD-1336, DGM amendment) | #1568 Decision 1-4; #1336 Decision; #1565 rule 1; #1558 DGM amendment |
| Regime chosen by target property | AD-1338 runs two loops: a fixed evaluator for measurable skill revisions, and a reflective self-audit, "never optimized against a score", for judgment | #1565, the "Judged by" row |
| A repeated claim is not more true | AD-1289: "a claim does not become true because many workers repeated it"; AD-1349: crew sharing a distinctive error are one witness | #1336 Decision; #1634 |
| Rejections become lessons | `ProposalStore` sends APPROVED, REJECTED and PIVOTED decisions to the EvolutionStore as lessons (AD-482b); the store is in memory and is constructed at startup | `src/probos/cognitive/self_improvement/proposal.py:106-112`; `src/probos/startup/finalize.py:2576` |
| Pivot as a decision primitive | AD-482e `PivotRefineDecision` (PROCEED, REFINE, PIVOT) with an `IterationGuard` cap | `src/probos/cognitive/self_improvement/proposal.py:38-48,72-98` |
| Evaluator isolation and grader protection | Evidence written only by services; candidates never weaken their own grader (DGM amendment, BF-898 #1563); AD-1338's suites are stored outside every candidate's write reach | #1558 DGM amendment; #1565 rule 3 |
| Isolated workspaces, restore and resume | Per-agent workspaces (AD-997); campaign worktrees (AD-1299 S3); attempt replacement and restart recovery (AD-1288 S4, AD-1290) | #1335 Acceptance; #1337 Acceptance |
| Context cleanup in long work | AD-1142 compacts a crew child's working context at a token threshold. It shrinks the context and continues: no reflection, and nothing externalized | `src/probos/cognitive/crew_executor.py:171-215` |
| Offline consolidation | Dream cycles run while the ship is idle, not during a task; champion/challenger promotion for procedures runs there | `src/probos/cognitive/dreaming.py:1-5`; #1565 (`startup/dreaming.py:168,201`) |
| Crew proposals with a ratifying gate | AD-1336 amendment 2026-10-25: intake writes drafts; the Captain accepts; classes that never graduate; status back to the thread, declined included | #1558 amendment 2026-10-25 §§1-4 |

## Decisions

| # | Idea | Decision | Reason | Owner |
|---|---|---|---|---|
| 1 | GCM selection-regime test: automatic or crew selection only for measurable, pre-registered properties; ratification for judgment | **Adapt** | Child 8 says *which* classes may graduate only by exclusion, through the never-graduated list. GCM supplies the positive test | AD-1336 (#1558) child 8, draft amendment |
| 2 | Rejected and superseded candidates are kept as evidence of selection | **Adapt** | Already true for build candidates, skill revisions and archive entries. Proposal intake records a declined draft's reason, but not that the draft is kept or what replaces it | AD-1336 (#1558) intake, draft amendment |
| 3 | Four memory layers with separate governance burdens | **Absorb as a mapping**, no new work | The layers map one-for-one: agent-local is nurture plus private procedures; archive is the Ship's Archive; project continuity is WorkItem, CrewSession and the AD-1289 blackboard; shared institutional is Ship's Records, standing orders and `DECISIONS.md` | This note |
| 4 | Identity-sharing tradeoff: homogenization and correlated errors | **Absorb**, as already held | It matches `diversity-scaling-absorption.md`, AD-1349, and AD-1336's exclusion of the builder's context from the reviewer. It also bounds idea 7 | This note; idea 7 |
| 5 | Ostrom's commons principles | **Adapt as framing only** | Defined boundaries, monitoring by lineage, graduated ratification and a final arbiter are already present. No mechanism to add | None |
| 6 | Evaluation of provenance fidelity, selection traceability, role preservation | **Adapt** into the loop metrics | Declined and superseded counts go into idea 2's amendment. Role preservation is #1139's diversity measurement | AD-1336 (#1558) §5; #1139 |
| 7 | CORAL shared attempts ledger: score, feedback, parent | **Adapt** | `WorkerAttemptOutcome` records a terminal status and an error code only (`src/probos/cognitive/elastic_team.py:384-396`); no score, no evaluator feedback, no parent. Workers read **outcomes** written by services, never a peer's reasoning, which keeps idea 4 | AD-1290 (#1337), draft amendment |
| 8 | CORAL heartbeat (reflect, consolidate, pivot) | **Adapt**, default off, measured | No mid-task reflection or externalization exists (AD-1142 only compacts). The service triggers, the agent decides the content (AD-1231). It ships behind a trial arm because CORAL reports no ablation for it. It is named a *reflection checkpoint*: `HeartbeatAgent` already means liveness pulses (`src/probos/substrate/heartbeat.py:1`) | AD-1290 (#1337), draft amendment |
| 9 | Evaluator isolation, grader recompute, anti-tampering | **Already covered** | DGM amendment, BF-898, AD-1338 rule 3 | None |
| 10 | Isolated workspaces, restore, session resume | **Already covered** | AD-997, AD-1299 S3, AD-1288 S4, AD-1290 | None |
| 11 | Copying breakthroughs and a shared consensus note | **Reject** for review, verification and adjudication slots; allowed for build slots that optimize a measured score | Consensus among reviewers is the echo-chamber failure (Chapel case, AD-1349) | AD-1290 draft amendment |
| 12 | Identical initialization of all agents | **Reject** | CORAL names it as its own limitation; ProbOS's diversity thesis says the opposite | #1139 |
| 13 | Open-ended population search | **Reject** | The cost reasons in `darwin-godel-machine-absorption.md` and AD-1338 still hold | None |

## Blind spots

- **Ship's Records carry the lightest gate of any shared, behavior-shaping store.** A notebook is published by its author alone: `records_store.py:1036-1037` lets the author or the Captain publish, with no review. Git history keeps the earlier versions (`get_history`, `records_store.py:1003`). Crew reach published records through the Oracle. In GCM's terms this is shared institutional memory under a nearly ungoverned regime. *Considered, deferred:* AD-1341's promotion criteria already govern what crosses into the archive. Ratifying in-generation Records would add a bottleneck to ordinary crew work, and nothing measured yet shows a false record propagating there. Revisit if AD-1349 traces a cascade to a published notebook.
- **Legacy memory** (GCM §5): records written before a gate existed can shape behavior before their evidence status is known. AD-1341 labels inherited culture, and the 2026-10-16 amendment requires inherited nature to requalify. In-generation records from before a gate, such as proposals filed before intake, have no such status. Idea 2's amendment marks them as such, rather than treating them as ratified.
- **Goodhart risk once a class graduates.** A class graduated on measurable criteria can still drift. Idea 1's amendment makes an escaped defect suspend the grant.
- **The transfer of CORAL's gains is unproven.** All of them come from tasks with a scalar grader. The AD-1290 financial-close fixture, and ProbOS lane items, are judged mostly against a contract, not a score.

## Draft amendments

These are drafts only, not yet applied to any issue. The Captain or the orchestrator applies them.

- AD-1336 (#1558) child 8: the selection-regime graduation rule.
- AD-1336 (#1558) intake: declined and superseded proposals are kept as evidence of selection.
- AD-1290 (#1337): reflection checkpoints and a readable attempts ledger. AD-1290 is the target, not AD-1288, because it owns attempt execution, gather and Team Trials, where an ablation arm can measure the checkpoint. AD-1288 owns provisioning, leases and drain, and its S4 already covers restore.
