# Diversity Scaling Absorption

*Sean Galliher, 2026-10-17*
*Sources (abstracts and summaries read; full texts not read unless noted):*
- *Yang et al., "Understanding Agent Scaling in LLM-Based Multi-Agent Systems via Diversity", [arXiv 2602.03794](https://arxiv.org/abs/2602.03794), 2026-02-03, with code at SafeRL-Lab/Agent-Scaling.*
- *Ye et al., "X-MAS: Towards Building Multi-Agent Systems with Heterogeneous LLMs", [arXiv 2505.16997](https://arxiv.org/abs/2505.16997).*
- *Goel et al., "Great Models Think Alike and this Undermines AI Oversight", ICML 2025, [arXiv 2502.04313](https://arxiv.org/abs/2502.04313).*
- *Zheng et al., "Claw-SWE-Bench", [arXiv 2606.12344](https://arxiv.org/abs/2606.12344), 2026-06-10.*
- *Ben Sghaier et al., "Don't Blame the Large Language Model: How Agent Harness Evolution Shapes Coding Agent Quality", [arXiv 2607.03691](https://arxiv.org/abs/2607.03691), 2026-07-04.*

## Purpose

The Captain's collaborative-intelligence thesis, as extended on 2026-10-17 (the dimensions are listed in the [#1139 comment](https://github.com/seangalliher/ProbOS/issues/1139#issuecomment-6243984785); the harness half, "flexibility and choice", is recorded in [AD-1342's harness-choice comment](https://github.com/seangalliher/ProbOS/issues/1582#issuecomment-6243870668)), is that a crew needs diversity of **brains** (models) *and* **bodies** (harnesses and their tools), on top of diversity of experience, knowledge, skills, character and role, with a shared culture to integrate them. This note records the research that tests that thesis, what ProbOS absorbs from it, and where each idea is owned. These are technical design references only.

## What the research shows

- **Diversity beats headcount.** Yang et al. find that adding homogeneous agents shows "strong diminishing returns", while heterogeneity in **models, prompts or tools** "continues to yield substantial gains", because homogeneous agents' outputs are strongly correlated. Headline: "2 diverse agents can match or exceed the performance of 16 homogeneous agents". Per the abstract page, they give an information-theoretic bound and a metric, **K\***, an *effective channel count* that can be estimated without ground-truth labels.
- **Assign models to functions.** X-MAS tested 27 LLMs across 5 domains and 5 functions. Heterogeneous systems beat homogeneous ones in the reported settings: up to 8.4% on MATH with chatbots only, and 47% on AIME when chatbots and reasoners were mixed. The authors' stated aim is to identify the best model for each domain-function combination; attributing the gains to that matching is their framing, not verified here. Some headline gains may come from the authors' own benchmark.
- **Models are converging, and that weakens oversight.** Goel et al. propose **CAPA**, a chance-adjusted measure of how often two models make the *same* mistakes. Judges favour outputs from models similar to themselves. In weak-to-strong training, "complementary knowledge between the weak supervisor and strong student model plays a crucial role in gains". And "model mistakes are becoming more similar with increasing capabilities", a risk of correlated failures.
- **The harness changes results with the model held fixed.** Claw-SWE-Bench compares general-purpose harnesses through a shared adapter protocol. Success and cost "vary substantially even when the underlying model is held fixed". Ben Sghaier et al. hold the model fixed across 35 releases of one harness and find that quality fluctuates from release to release. Open-source harnesses ship more than two releases a day.

## Absorbed

| # | Finding | ProbOS use | Owner |
|---|---|---|---|
| 1 | **K\*, a label-free count of effective independent channels** | Measure crew diversity: does adding a member, model or harness add *independent* evidence? Use it to guide crew composition, meaning which brain and body a new member should get | Cooperation research, #1139, and Ship Trials, AD-1186 (#1123): to be measured there |
| 2 | **CAPA, error-overlap similarity** | Choose reviewer and verifier pairs by *measured* error overlap, not only by model family. Two families can share blind spots | Live home: a comment on #1139 (AD-1327, #1511, is closed). Considered, deferred until AD-1327 is next revised |
| 3 | **Function-specific model assignment** (X-MAS) | Assign models by function (reasoning, conversation, review) within billets, not only by tier | Live home: a comment on #1139 (AD-1324, #1479, is closed). To be measured under #1139; considered, deferred until AD-1324 is next revised |
| 4 | **A shared adapter protocol for fair harness comparison** (Claw-SWE-Bench) | Native-versus-harness trials must fix the prompt, budget, workspace contract and output extraction, or adapter quality dominates the result | AD-1342 (#1582) |
| 5 | **Harness quality swings between releases** | Record the body *and its version* in `ExecutionProfile`, and re-qualify after every harness upgrade | AD-1342 (#1582); see its [harness-choice comment](https://github.com/seangalliher/ProbOS/issues/1582#issuecomment-6243870668) |
| 6 | **Model convergence makes body, tool and prompt diversity more valuable over time** | Supports keeping both the native harness and external bodies, and diversifying character and role | The Captain's 2026-10-17 decision to keep both the native harness and external bodies (AD-1342 comments) |

## Rejected or deferred

- **Adding more agents of the same kind as a scaling strategy.** Rejected: the evidence says it saturates early.
- **Mixture-of-Agents-style layered ensembling of every answer.** Deferred: costly per request, and ProbOS crews collaborate through the Ward Room and consultation rather than fixed aggregation layers. Consider it for specific high-stakes duties if Ship Trials show a gain.

## Consistent with existing ProbOS principles

Diversity helps only when it is integrated. The Chapel echo-chamber case showed a department amplifying an error instead of catching it. ProbOS's shared self layer, Ward Room, chain of command, trust and culture are what turn diverse members into a crew. The research supports the thesis, and #1139 is where ProbOS has to show it for its own crew.
