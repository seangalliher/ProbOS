# WAVE 130 DISPATCH — 10-pack mixed code + research

**Wave:** 130
**Mode:** main
**Depends on:** 129
**Builder required:** yes
**Issues to close:** #477, #478, #483, #490, #492, #493, #495, #496, #497, #501
**Date:** 2026-05-08

## Special note for the Architect: research is part of drafting

This wave mixes 6 **code-tier** prompts and 4 **research-tier** prompts. For the research-tier prompts, the Architect performs the research as part of drafting — not as a deferred Builder action. The Builder's job for those four is to **execute the research plan the Architect has already substantially completed**, producing a concrete deliverable (a research doc + a small concrete code or test artifact that demonstrates the absorption).

Concretely:
- For **research-ragflow-context-layer**, **research-opencode-magic-context**, **research-locomo-benchmark**: the Architect must already pull the upstream repo's README + relevant headers, summarize the absorbable patterns, and write a verify-first comparison against ProbOS's existing surface (AD-573 working memory, AD-644 situation awareness, AD-606 think-in-memory, AD-590-593 recall pipeline). The drafted prompt's Deliverables include both a research doc at `docs/research/<name>-absorption.md` AND a small concrete artifact (a benchmark harness stub, a test that compares one ProbOS metric to the upstream tool, or a documented absorbed pattern with an issue stub for follow-up).
- For **research-warm-boot-fragmentation-design**: the Architect drafts the design AD itself (no upstream tool to research). Builder's job is to commit the AD as a design document under `docs/research/` and update DECISIONS.md with the design summary. Implementation is deferred to a future wave.

This pattern keeps research artifacts in the standard wave loop — verify-first, reviewed, scoped — rather than letting them drift as informal notes.

## Subagent Prompt — Architect (drafting pass)

You are drafting **10 prompts** for Wave 130. Match the format of `prompts/archive/ad-697-extension-registry-v1.md` and the recently-archived Wave 129 prompts.

For **every** prompt: verify-first against the live codebase. State "Verified Against Codebase (2026-05-08)" with bullet citations of file paths and line ranges. Apply all 19 standing conventions (DECISIONS.md Wave 5/5-7/8/10 retrospectives) and the new Wave 129 retrospective convention #20: **always run the working-tree integrity check before reading source files** (`git diff --numstat | sort -k2nr | head -5`; >200 deletions on a tracked file = STOP).

### Code-tier prompts (6)

1. **`prompts/ad-701-visiting-officers-v1.md`** — closes #477.
   - Formal Ward Room registration for external participants (Claude Code, Copilot, etc.).
   - Builds on the existing MCP bridge (AD-449) and the External Participant Bridge concept in roadmap.md (Phase 33).
   - Substrate: a `VisitingOfficerRegistry` (callsign, sovereign DID issued under the visiting tier, scoped capabilities, Ward Room subscription, time-bounded session). Verify-first: check what AD-449 MCP bridge currently exposes; check if Ward Room has a participant model that can be extended vs. needs a new tier.
   - Tests: registration, deregistration, capability-scope enforcement, Ward Room post attribution, session expiry.

2. **`prompts/ad-702-diplomatic-relations-v1.md`** — closes #478.
   - Discounted trust transitivity computation T(A→C) = T(A→B) × T(B→C) × δ.
   - Builds on the existing TrustNetwork. Verify-first: where does TrustNetwork live, what's its current API, and is there already any transitivity code?
   - Per the Nooplex paper §4.3.4: safety-critical operations never use transitive trust; only direct first-party trust. Implement the override.
   - Trust decay (90-day default) toward neutral baseline if A and C have not interacted directly.
   - Sybil resistance: provenance-depth weighting in the transitive computation.
   - Tests: chain bounded by min link, decay, safety-critical override, sybil resistance via provenance.

3. **`prompts/ad-707-workflow-cron-trigger-v1.md`** — closes #483 (NARROWED to cron only; defer webhook + workflow API to v2).
   - WorkflowCache (AD-580) is shipped. This adds a cron trigger that re-runs cached workflows on schedule.
   - Verify-first: how does WorkflowCache identify a workflow? What's the cache key shape? Is there an existing scheduler (TaskScheduler / DutyScheduler / PostgreScheduler / AsyncIO) we plug into?
   - Substrate: a `WorkflowCronTrigger` config + finalize-wirer + heartbeat tick that fires expired schedules.
   - Tests: schedule registration, cron parsing, expired-trigger fires the workflow, cancelled trigger doesn't fire.
   - Document that webhook + workflow API surfaces are deferred to AD-707b/c.

4. **`prompts/memvid-queryplanner-relational-v1.md`** — closes #490 (NARROWED to QueryPlanner pattern only; defer VersionRelation enum + per-engine-version enrichment).
   - Detects relational queries (`who works at X`, `where is Y`, `when did Z happen`) and resolves via entity-slot-value lookup BEFORE falling back to vector similarity.
   - Verify-first: what does the current recall pipeline look like at HEAD (post-recovery)? Where in episodic.py do queries route?
   - Substrate: a `QueryPlanner` class that classifies an incoming query string into RELATIONAL or SEMANTIC; for RELATIONAL, runs an anchor-based lookup against episode anchors; falls back to existing vector + composite scoring.
   - Tests: query classification correctness, relational hit returns the right episodes, fallback to semantic when no relational match.
   - Document that VersionRelation enum + per-engine-version enrichment are out of scope (Memvid pattern 2 + 3) — file as memvid-versionrelation-v1 and memvid-engineversion-v1 follow-ups.

5. **`prompts/better-agents-behavior-contract-v1.md`** — closes #493.
   - Architect must first study langwatch/better-agents (read the README and the `cli` + `eval` directories from the upstream repo URL in the issue) and synthesize the absorbable subset.
   - Substrate: a `BehaviorContract` Pydantic model + a `qa_run_contracts` CLI command that evaluates a list of contracts against an agent.
   - Map onto AD-477 qualification programs + AD-566 psychometrics so contracts can be expressed declaratively.
   - Tests: contract parsing, contract pass/fail evaluation against a stub agent, CLI exit codes.

6. **`prompts/claude-bootstrap-init-defaults-v1.md`** — closes #495.
   - Per the issue's guardrail: low priority, scoped to the `probos init` wizard's security defaults.
   - Architect must read alinaqi/claude-bootstrap (upstream repo URL in the issue) for the spec-driven scaffolding pattern.
   - Substrate: extend the existing init wizard (likely `experience/init/` or similar — verify-first) with a "security profile" prompt that bakes in defaults the user explicitly weakens, not strengthens.
   - Tests: default profile generated correctly, weakening requires explicit flag, no strengthening flag exists.

### Research-tier prompts (4)

For each of these, the Architect does the research as part of drafting. The drafted prompt has TWO halves:
- **Research summary (Architect-authored, in the prompt itself)**: what's in the upstream tool, what ProbOS already has that's similar, what the absorption opportunity is, what the trade-offs are.
- **Deliverable spec (Builder-executable)**: a research doc to write at `docs/research/<name>-absorption.md` with a stated structure, plus one concrete artifact (test stub, benchmark harness, design AD entry).

7. **`prompts/research-ragflow-context-layer-v1.md`** — closes #496.
   - Upstream: infiniflow/ragflow (Apache-2.0, 79.8k stars). Architect must read its README + the directory structure to extract the context-layer design.
   - Compare to AD-573 (Working Memory) + AD-644 (Situation Awareness). Identify absorbable patterns (e.g. retrieval-iteration loop, document parsing pipeline) and document trade-offs.
   - Builder deliverable: `docs/research/ragflow-absorption.md` with sections (What It Does / Architecture / What ProbOS Has / Absorption Candidates / Recommended Follow-ups). Plus 1 follow-up issue stub if a clear next step emerges.

8. **`prompts/research-opencode-magic-context-v1.md`** — closes #492.
   - Upstream: cortexkit/opencode-magic-context. Architect reads README + compression algorithm.
   - Compare to AD-606 (Think-in-Memory) + AD-538 (Ebbinghaus decay) + dream consolidation pipeline. Document the compression strategy and whether it's a meaningful improvement.
   - Builder deliverable: `docs/research/opencode-magic-context-absorption.md` + a small test harness in `tests/research/` that measures ProbOS's current compression ratio so future absorption can be quantitatively justified.

9. **`prompts/research-locomo-benchmark-v1.md`** — closes #497 (and #494 which was closed as duplicate).
   - Upstream: NirDiamant/Agent_Memory_Techniques (Apache-2.0). Architect reads the LoCoMo notebook, summarizes the benchmark methodology, and identifies the harness shape.
   - Plus: pull the MemOS benchmark methodology too (per the closed #494 — both compete on the same benchmark).
   - Builder deliverable: `docs/research/locomo-benchmark-absorption.md` + a runnable harness stub at `tests/benchmarks/test_locomo_episodic.py` that computes ProbOS's score on a small LoCoMo subset (skipped by default; opt-in via env var). Goal is a reproducible "we score X%" metric for the next memory-architecture AD.

10. **`prompts/research-warm-boot-fragmentation-design-v1.md`** — closes #501.
    - Pure design AD (no upstream tool). Architect drafts the full design from Reed's two proposals + Sentinel's coordination on stale trust context.
    - Sections: Fragment detection heuristics (anchor-temporal mismatch, missing dream-cycle markers, stale trust deltas), triage rules (safe-discard vs. recovery), minimum-stasis threshold, optional checkpoint-resume.
    - Builder deliverable: `docs/research/warm-boot-fragmentation-design.md` + a DECISIONS.md design entry tagged "AD-711 — Warm-Boot State Fragmentation (DESIGN, implementation deferred)". No code beyond the AD entry stub.

## Output rules

- Place all 10 prompts under `prompts/`. Match the exact filenames in the wave-plan paths above.
- Touch nothing else. Do not modify code, tests, wave-plan.yaml, BUILDER-EXECUTION-PLAN.md, or DECISIONS.md.
- For each research-tier prompt, include the upstream URL the Architect was supposed to fetch.

## Final report

After all 10 are written, return ONE message containing:
1. One-line summary per prompt (filename + scope summary).
2. Verify-first findings that contradicted the dispatch (if any) — these block their respective prompts and need user attention before review pass-1.
3. Risk classification per prompt (LOW / MEDIUM / HIGH).
4. Any standing-convention concerns surfaced during drafting.
5. For each research-tier prompt: the upstream tool's README/repo URL the Architect actually fetched as part of drafting (so we can audit research depth).

Do not include the prompt bodies in your final message — they live in their files. Return the summary only.

## Build-phase ordering (after prompts pass review pass-2)

Standard continuous-build mode. Recommended order (Architect may revise after pass-1 surfaces actual collisions):

1. `claude-bootstrap-init-defaults` (smallest, low risk, isolated to init)
2. `better-agents-behavior-contract` (CLI extension, additive)
3. `ad-707-workflow-cron-trigger` (WorkflowCache extension)
4. `ad-702-diplomatic-relations` (TrustNetwork extension)
5. `ad-701-visiting-officers` (Ward Room substrate, depends on AD-449)
6. `memvid-queryplanner-relational` (recall-pipeline extension)
7. Then the 4 research-tier prompts in any order — they only write docs/tests.
