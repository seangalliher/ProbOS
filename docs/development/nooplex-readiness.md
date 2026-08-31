# Nooplex Readiness Map

**Status:** Active tracking authority

**Purpose:** Record what ProbOS has demonstrated relative to the Nooplex architecture, what claim the evidence permits, and which existing decision owns the next gate.

This document tracks **readiness**, not aspiration and not implementation inventory. A component existing in source, passing a unit test, or being enabled in one local configuration does not advance a readiness tier by itself. A tier advances only when its evidence gate passes through the production paths named below.

## Tracking Authorities

| Question | Authority |
|---|---|
| Which AD/BF numbers are allocated or shipped? | Live enumeration of Git subjects, GitHub issue titles in all states, and in-flight `prompts/ad-*.md`; the generated [AD/BF ledger](open-ads-report.md) is a reconciliation view |
| What is ordered for future implementation? | [Development roadmap](roadmap.md) |
| What work makes one ProbOS mesh dependable? | [AD-1270 Platform Maturity Program](platform-maturity-program.md) / [#1324](https://github.com/seangalliher/ProbOS/issues/1324) |
| What is the Tier A P0 seam denominator? | [Stable-ID P0 manifest](seams/p0-manifest.yaml); removed IDs remain reasoned tombstones |
| What is the initial maintainability/test-cost observation? | [2026-08-30 reproducible baseline](platform-maturity-baseline-2026-08-30.md); discovery evidence, not a passing readiness gate |
| What evidence supports a release? | AD-1186 Ship Trials / [#1123](https://github.com/seangalliher/ProbOS/issues/1123) |
| What does the Nooplex architecture require? | [The Nooplex](../../Vibes/Nooplex_Final.md) |
| What readiness claim is currently permitted? | **This document** |

Technical readiness belongs in the OSS repository because it describes how the product works. Commercial positioning may link here but must not maintain a competing technical status table.

## Status Vocabulary

| Status | Meaning |
|---|---|
| `not-started` | No active implementation owner or evidence program |
| `planned` | Decision and owner exist; implementation has not passed its gate |
| `experimental` | A working path exists, but security, repeatability, scale, or evidence is insufficient for supported use |
| `supported` | Versioned configuration, production-path exercise, recovery, security floor, and release evidence pass |
| `research` | A falsifiable hypothesis is being studied; it is not a product capability claim |
| `disconfirmed` | Required evidence failed a predeclared criterion |

`unknown`, `skipped`, `not exercised`, and `judge unavailable` are never synonyms for `passed`.

## Readiness Tiers

| Tier | Name | Current status | Owning program | Permitted claim |
|---|---|---|---|---|
| A | Dependable Cognitive Mesh | `planned` | AD-1270 / #1324 | “ProbOS is an alpha implementation of a governed Cognitive Mesh.” |
| B | Secure Multi-Mesh | `planned` | AD-1196–1198 / #1140 | “ProbOS has an experimental federation transport.” |
| C | Nooplex Core Fabric | `not-started` | No active owner | “ProbOS provides local foundations for a future Nooplex Core.” |
| D | Emergence Research | `research` | No active complete owner | “ProbOS is an experimental platform for testing the Nooplex hypothesis.” |

### Tier A — Dependable Cognitive Mesh

Tier A establishes one ProbOS vessel as a supported Cognitive Mesh: heterogeneous agents, shared memory, governed action, durable work, learning loops, human participation, recovery, and truthful operational evidence.

**Required evidence**

- AD-1185 defines and boots the supported profile.
- AD-1270a distinguishes present, configured, advertised, activated, exercised, and healthy.
- Every active Tier A P0 seam in the canonical manifest crosses its real producer and consumer.
- Runtime, startup, configuration, and cognitive orchestration retain compatibility while ownership moves behind bounded facades.
- Every durable store declares lifecycle, criticality, retention, backup, and restore disposition through AD-1256.
- AD-1265/1266 pass snapshot -> verify -> restore -> reboot -> production-read.
- P0 paths carry correlated run/tool evidence, latency, errors, and bounded resource measurements through AD-1152 and AD-1195 or equivalent owners.
- Supported capabilities have no unresolved Critical or High security/governance defect; otherwise they report unavailable or degraded.
- AD-1186 Ship Trials are non-vacuous: skipped, absent-data, and judge-unavailable outcomes are inconclusive or blocking, never passing evidence.
- AD-1270g keeps product claims synchronized with executable authorities.

**Exit claim**

> ProbOS is a supported implementation of one governed Cognitive Mesh.

This claim does not imply authenticated federation, a Global Knowledge Fabric, or evidence of emergent general intelligence.

### Tier B — Secure Multi-Mesh

Tier B connects independently running Cognitive Meshes without shared process memory, filesystem, or database authority.

**Existing owners**

- AD-1196: bind `did:probos` identities to Ed25519 keys with rotation and revocation.
- AD-1197: sign canonical federation envelopes and prevent replay.
- AD-1198: authenticate transport admission and prove behavior on the existing two-node cluster.
- AD-703: distribute fleet policy; its version/conflict semantics must be settled before Tier B is supported.
- AD-1152 and AD-1195: preserve correlation and durable event meaning across the boundary.

**Required evidence**

- Two separately started nodes communicate over real sockets with no shared storage.
- Source, target, topic, body, and attachment references are authenticated and tamper-evident.
- Duplicate, replayed, stale-key, malicious-peer, partition, restart, and clock-skew cases are exercised.
- Policy version mismatch fails closed for safety-critical operations.
- Cross-node traces preserve causality and bounded provenance.
- Latency/error/resource SLOs are measured for local and federated paths.
- Fault injection proves bounded degradation and recovery.

**Exit claim**

> ProbOS supports an authenticated federation of sovereign Cognitive Meshes.

Use “federated ProbOS cluster” or “multi-mesh substrate” before this gate. Do not call transport connectivity alone a Nooplex.

### Tier C — Nooplex Core Fabric

Tier C implements the paper's Core Fabric rather than only forwarding intents between nodes.

**Owner status:** No active integrated owner. Local ontology, knowledge graph, memory, trust, and federation components are prerequisites, not substitutes for this tier.

**Required architecture**

- Global ontology with explicit pluralism, versioning, deprecation, migration, and conflict review.
- Cross-mesh schema registry and compatibility negotiation.
- Federated semantic query with routing, score normalization, partial-result semantics, and provenance.
- Embedding-space alignment or an evidence-backed alternative that preserves semantic meaning across heterogeneous meshes.
- Multi-mesh knowledge graph with trust-weighted integration, quarantine, retraction, and lineage.
- Model-of-models for mesh capability, health, latency, cost, and routing fitness.
- Cross-mesh governance with policy reconciliation, human override, and independent watchdog evidence.
- Byzantine/Sybil/poisoning controls at knowledge-ingestion boundaries.
- Privacy, confidentiality, data-residency, and provenance-minimization contracts.
- Human and agent knowledge entering the same governed lifecycle, including validation, deprecation, archival, retraction, and deletion.

**Exit claim**

> ProbOS implements a prototype Nooplex Core Fabric across multiple sovereign meshes.

This is the earliest tier at which the unqualified architectural term “Nooplex” is appropriate. It still does not demonstrate emergence.

### Tier D — Emergence Research

Tier D tests the paper's falsifiable research hypothesis. It is not a release milestone and must permit disconfirmation.

**Required research program**

- Re-establish the objective of retired AD-1188 under a new evaluation owner.
- Compare the full system, independent-mesh ensemble, and predeclared ablations under identical models, tasks, budgets, and evidence policies.
- Measure cross-domain synthesis against an ensemble baseline.
- Replace or clearly separate vessel-local collaboration proxies from the paper's cross-mesh $TC_N$ measure.
- Detect novel coordination against a frozen initial-protocol catalog.
- Track held-out capability growth and accumulated knowledge longitudinally for at least six months.
- Report performance per dollar, latency, energy/resource use, and coordination overhead.
- Use expert human panels with predeclared rubrics and inter-rater reliability.
- Publish confidence intervals, effect sizes, multiple-comparison corrections, and disconfirmation outcomes.

The paper's planetary-scale profile remains a long-horizon condition: at least 50 meshes, 500 active agents, three regions, 100,000 cross-mesh knowledge operations per day, and sustained federated memory at the stated scale. Smaller experiments may test early effects but cannot claim planetary validation.

**Permitted claim before evidence**

> ProbOS is a research platform for evaluating whether governed federated cognition produces measurable emergent capabilities.

**Permitted claim after evidence**

> The tested ProbOS federation showed evidence for specific predeclared emergence criteria under the published conditions.

Never generalize one successful demonstration into “ProbOS achieved AGI” or “the Nooplex hypothesis is proven.”

## Cross-Cutting Evidence Programs

These do not form a fifth tier. They supply evidence required by more than one tier.

| Program | Existing owner | Readiness role |
|---|---|---|
| Supported configuration | AD-1185 / #1121 | Defines what is actually supported |
| Ship Trials | AD-1186 / #1123 | Release evidence for Tier A and later tiers |
| Orchestration ablation | AD-1188 retired | Needs a new owner before Tier D experiments |
| Event persistence | AD-1195 / #1132 | Defines what historical claims event storage can answer |
| Trace correlation | AD-1152 / #1079 | Connects ingress, reasoning, tools, artifacts, and outcomes |
| Agentic risk/cost bounds | AD-1208 / #1154 | Begins resource governance for individual turns |
| Secure federation | AD-1196–1198 / #1140 | Tier B identity, envelopes, and admission |
| Fleet policy | AD-703 / #479 | Tier B/C policy propagation; conflict semantics remain required |
| Store lifecycle/recovery | AD-1256, AD-1265, AD-1266 | Tier A durability and Tier C storage foundation |
| Platform maturity | AD-1270 / #1324 | Tier A evidence and maintainability |

## Currently Unowned Programs

Do not file one issue per bullet. When work is scheduled, create one bounded epic per program and keep independent findings as checklist items.

1. **Core Fabric:** global ontology/schema evolution, federated semantic query, embedding alignment, global knowledge graph, model-of-models, and cross-mesh governance.
2. **Operational Science:** platform SLOs, performance/cost accounting, load shedding, chaos engineering, and concrete shadow deployment/rollback.
3. **Knowledge Lifecycle and Human Contribution:** common human/agent ingestion, validation, citation effects, deprecation, archival, retraction, deletion, and rights-aware provenance.
4. **Federation Adversarial Assurance:** Byzantine knowledge validation, Sybil resistance beyond key possession, poisoning quarantine, privacy-preserving cross-mesh cognition, and data-sovereignty enforcement.
5. **Emergence Evaluation:** controlled multi-mesh baselines, cross-mesh $TC_N$, novel coordination, longitudinal capability curves, and human evaluation.

## Update Rules

1. Update this file only when a readiness gate, owner, or permitted claim changes. Routine implementation detail belongs in the owning AD or issue.
2. A tier changes status only when its required evidence artifact is committed and linked.
3. Every status change records the commit, supported profile, evidence artifact, and residual risks.
4. GitHub issues track executable work. Do not create issues merely to mirror this table.
5. Use one epic per active tier/program. Existing epics remain authoritative: #1324 for Tier A and #1140 for Tier B.
6. Do not open Tier C or Tier D epics until the Captain schedules those programs.
7. AD-1270g should generate the readiness summary exposed in README; this full document remains human-reviewed architecture narrative.
8. Commercial documentation links to this status rather than duplicating it.

## Current Assessment

As of 2026-08-25:

- ProbOS contains unusually advanced local governance, memory, trust, learning, self-modification, durable crew, and HXI mechanisms.
- AD-1270 is planned but not yet complete, so Tier A remains `planned`, not `supported`.
- Federation transport exists, but authenticated multi-node admission and real-socket evidence remain open, so Tier B remains `planned` with an experimental substrate.
- Tier C has strong local prerequisites but no active integrated owner.
- Tier D has useful local emergence instrumentation and a narrow Sigma ablation, but no complete multi-mesh, longitudinal, statistically governed evidence program.

ProbOS therefore appears capable of evolving toward the Nooplex without a foundational rewrite. The next architectural step is to prove the Cognitive Mesh unit cell, then federate sovereign units securely, then build the Core Fabric as a new layer rather than enlarging `ProbOSRuntime` into a planetary controller.
