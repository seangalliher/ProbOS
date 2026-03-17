# Roadmap

Upcoming development phases:

| Phase | Title | Goal |
|-------|-------|------|
| 24 | Channel Integration | Discord, Slack, Telegram adapters + external tool connectors |
| 25 | Persistent Tasks | Long-running autonomous tasks with checkpointing, browser automation |
| 26 | Inter-Agent Deliberation | Structured multi-turn agent debates, agent-to-agent messaging |
| 28 | Meta-Learning | Workspace Ontology, dream cycle abstractions, session context, goal planning |
| 29 | Federation + Emergence | Knowledge federation, trust transitivity, TC_N measurement |
| 30 | Self-Improvement Pipeline (OSS) | Capability proposals, stage contracts, QA agent pool, evolution store, human approval gate |

### Phase 30 — Self-Improvement Pipeline (OSS Infrastructure)

The mechanisms that allow ProbOS to participate in its own evolution. This phase builds the infrastructure for a closed-loop improvement cycle: discover capabilities, evaluate fit, propose changes, validate results, and learn from outcomes.

**Stage Contracts (Typed Agent Handoffs)**

- Formal I/O specifications for inter-agent task handoffs
- Each contract declares: input artifacts, output artifacts, definition of done, error codes, max retries
- Enables reliable multi-step workflows where agents hand off work to each other with clear expectations

**Capability Proposal Format**

- Typed schema for "here's what was found, why it matters, and how it fits"
- Fields: source (repo/paper/API), relevance score, architectural fit assessment, integration effort estimate, dependency analysis, license compatibility
- Proposals flow through a review queue with approve/reject/modify actions

**Human Approval Gate**

- Stage-gate mechanism that pauses automated pipelines for human review
- Approval queue surfaced via HXI, shell, or API
- Supports approve, reject, or modify-and-resubmit workflows
- Audit trail of all decisions for traceability

**QA Agent Pool**

- Automated validation agents that go beyond pytest
- Behavioral testing: does the new capability actually improve the metric it claimed to?
- Regression detection: did anything break?
- Performance benchmarking: latency, memory, throughput before and after
- Shapley scoring to measure marginal contribution of new capabilities

**Evolution Store**

- Append-only store of lessons learned from capability integrations (successes, failures, and why)
- Time-decayed retrieval: recent lessons weighted higher, stale lessons fade
- Fed into episodic memory and dream consolidation for cross-session learning
- Future research/architect agents query this store to avoid repeating past mistakes

**PIVOT/REFINE Decision Loops**

- Autonomous decision points in multi-step workflows: proceed, refine (tweak and retry), or pivot (abandon and try a different approach)
- Artifact versioning on rollback: previous work is preserved, not overwritten
- Hard iteration caps to prevent infinite loops

**Capability Injection (Adapter Bundle)**

- Agents declare needed capabilities (search, store, fetch, notify) via typed Protocol interfaces
- Runtime injects concrete implementations at startup
- Swappable providers without changing agent code (e.g., swap OpenAlex for Semantic Scholar)
- Recording stubs for testing: log calls without side effects, verify agent behavior in isolation

**Multi-Layer Verification (Anti-Hallucination)**

- Graduated verification of agent-produced claims against external sources
- Multiple verification layers, each catching what the previous missed (e.g., direct ID lookup -> API search -> fuzzy title match -> LLM relevance scoring)
- Classifications: VERIFIED (high confidence), SUSPICIOUS (needs review), HALLUCINATED (fabricated), SKIPPED (unverifiable)
- Extends the trust network from binary success/fail to graduated confidence scoring
- Applied to research findings, generated references, claimed capabilities, and factual assertions

!!! info "Want to contribute?"
    See the [Contributing guide](contributing.md) for how to get involved.
