# Self-Evolving Harness Absorption

*Sean Galliher, 2026-10-17*
*Sources (abstracts and search summaries read; full texts not read):*
- *Xia et al., "Live-SWE-agent: Can Software Engineering Agents Self-Evolve on the Fly?", [arXiv 2511.13646](https://arxiv.org/abs/2511.13646), with code at OpenAutoCoder/live-swe-agent.*
- *Chen et al., "HarnessX: A Composable, Adaptive, and Evolvable Agent Harness Foundry", [arXiv 2606.14249](https://arxiv.org/abs/2606.14249), 2026-06-12.*
- *"Dynamic Agent Skills: A Lifecycle Survey and Taxonomy of Evolving Skill Libraries", [arXiv 2607.10113](https://arxiv.org/abs/2607.10113).*
- *"SkillRouter", [arXiv 2603.22455](https://arxiv.org/abs/2603.22455), 2026-03.*
- *Yang et al., "SkillSeek", [arXiv 2609.38822](https://arxiv.org/abs/2609.38822), submitted 2026-09-30 (AACL-IJCNLP 2026).*

## Purpose

Live-SWE-agent sets a minimal, bash-only scaffold against hand-crafted agents, which raises the question of how much of a harness an agent needs, and how much it can build on the fly. The Captain's framing (2026-10-17) is a **liquid agent**: adaptive, but not reinventing the wheel. It should generate procedurally from patterns it has already learned, which are skills and tools that are optimized and reused. It works inside a container that, in the Captain's words, holds "everything together and protect[s] all components inside". This note records what the research shows, what ProbOS absorbs, and where each idea is owned. These are technical design references only.

## What the research shows

- **A minimal scaffold can evolve its own tools during a task.** Live-SWE-agent "starts with the most basic agent scaffold with only access to bash tools" and "autonomously evolves its own scaffold implementation while solving real-world software problems". It reports 77.4% on SWE-bench Verified without test-time scaling, and 45.8% on SWE-Bench Pro. A search summary gives 75.4% for an earlier version; that figure was not checked. It positions itself against the Darwin Gödel Machine's "costly offline training on specific benchmarks". **Its abstract does not say whether evolved tools carry over between tasks.**
- **Harnesses can be composed and evolved from traces.** HarnessX composes harness components and evolves them from execution traces with an engine called AEGIS (the abstract summary; the component and engine design was not checked against the paper body). It reports +14.5% on average and up to +44.0% across ALFWorld, GAIA, WebShop, tau^3-Bench and SWE-bench Verified, with the largest gains where the baseline was weakest: "composing and evolving runtime interfaces from execution feedback is an actionable and complementary lever".
- **Skill selection degrades as libraries grow.**
  - The "Dynamic Agent Skills" survey states that "flat retrieval can degrade as libraries grow", reports a "sharp decline beyond roughly 64–128 skills" (attributed there to Li, 2026), and finds that "admission and repair are repeatedly important".
  - SkillRouter reaches 74.0% Hit@1 over about 80K skills with retrieve-and-rerank. The skill **body**, not only its name and description, drives correct selection: removing it costs 37–44 percentage points.
  - SkillSeek reports that plain BM25 matches or beats a refined LLM-mediated retrieval loop in 3 of 4 settings on SkillsBench (89 tasks, OpenHands harness). Separately, its full two-stage pipeline (a bi-encoder plus a cross-encoder) cut cost from USD 51.30 to 27.54.

## What it means: the container

A simple harness with a strong skill selector works only while the library is small. A liquid agent with a large, growing library needs **retrieval and routing as a service**: a persistent container that holds, indexes, protects and serves what it has learned. Without one, a liquid agent reinvents its tools on every task. With one, adaptation accumulates. In AD-1342's terms ("The harness is the body; ProbOS is the self"), the container functions below are provided by the body and the self together.

| Container function | ProbOS |
|---|---|
| Contain and protect | Governance, sandboxes, the write boundary, the fixed evaluator |
| Hold it together | Identity (DID), persistent state, lineage |
| Integrate | Memory, context assembly, skill and tool routing, the Ward Room |
| Remember how | Skills and procedures (nature), refined over time |
| Sense and act | Tools, I/O, native or external harness bodies (AD-1342) |

The Ship's Computer provides most of these as shared services, so crew can adapt freely because the ship holds everything together.

## Absorbed

| # | Pattern | ProbOS use | Owner |
|---|---|---|---|
| 1 | Skill selection as a measured service | Retrieval over the skill body (BM25 default), hierarchical routing past a measured library size, and selection accuracy tracked as the library grows | AD-1338 (#1565), [comment](https://github.com/seangalliher/ProbOS/issues/1565#issuecomment-6244821407) |
| 2 | Reuse, then compose, then generate | Generate only on a gap detected by the existing capability-gap detection (AD-539, dream Step 8). Build in a confined runtime; the capability-only interpreter is an option under evaluation (#1537) | AD-1338 (#1565) |
| 3 | In-task tool evolution (Live-SWE-agent) | Tools made during a task become promotion candidates under AD-1338's recurrence bar and fixed evaluator, with lineage kept, so adaptation persists | AD-1338 (#1565) |
| 4 | Library maintenance (survey) | Retirement and repair are first-class lifecycle steps alongside promotion | AD-1338 (#1565) |
| 5 | Trace-driven harness evolution (HarnessX) | The mechanism for the meta-level class: the improver's prompts, procedures and harness configuration change from AD-1329 run traces, with the evaluation kept fixed | AD-1299 (#1352), [comment](https://github.com/seangalliher/ProbOS/issues/1352#issuecomment-6244821573) |

## Rejected or deferred

- **An agent with no fixed core.** Rejected. The Darwin Gödel Machine forged evidence and removed its own check's markers (`darwin-godel-machine-absorption.md`), and even HyperAgents keeps evaluation fixed. ProbOS keeps a fixed spine: identity, memory, governance and the evaluator. Only the hands (tools and skills) are liquid.
- **Generating tools without a recurrence bar.** Rejected. Generation costs time and tokens on every task, and a library amortizes that cost. The Captain's rule: "a script used once is clutter."

## Consistent with existing ProbOS principles

A liquid agent inside a protective container applies AD-1342's principle, "The harness is the body; ProbOS is the self", to skills and tools: adapt freely at the edges, keep the core trustworthy, and make everything learned reusable.
