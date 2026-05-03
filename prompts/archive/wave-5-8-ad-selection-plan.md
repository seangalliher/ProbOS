# Plan: Select 20 ADs for Build Prompt Drafting (Wave 5-8)

## Context

ProbOS Era V (Phases 31-36). All 20 ADs from Waves 1-4 are COMPLETE (AD-438, 445-448, 461, 465, 470, 489, 490, 524, 561, 566f, 566i, 674-679). Need a fresh set of 20 ADs for the next builder waves.

**Selection criteria:** Priority, readiness (all deps met or included), sufficient roadmap detail for prompt drafting, no blockers.

**Key completed prerequisites:** AD-398, 427, 429, 429b, 438, 441, 441b, 442, 445-448, 461, 470, 494, 502, 504, 505, 523-539, 541d, 553-558, 567a-g, 589, 625, 637, 674-680.

**Known blockers (not included):** AD-479 (Federation Display — NOT BUILT, blocks AD-499), AD-486 (Holodeck — NOT BUILT, blocks AD-487/509/510/512), AD-477 (Qualifications — NOT BUILT, blocks AD-507/509), AD-452 (Self-Mod Pipeline — NOT BUILT, blocks AD-521), AD-543-546 (Tool Executor suite — NOT BUILT, blocks AD-521), AD-496-498 (Workforce Scheduling — status unclear, blocks AD-581).

---

## Selected 20 ADs — Build Priority Order

### Wave 5: Independent Foundation (5 ADs, fully parallel)

| # | AD | Title | Risk | Est. Tests | Deps Met? |
|---|---|---|---|---|---|
| 1 | AD-439 | Emergent Leadership Detection | LOW | 6-8 | AD-429 ✓ |
| 2 | AD-440 | Chain of Command Delegation | LOW-MED | 8-10 | AD-429 ✓ |
| 3 | AD-443 | Agent Mobility Protocol — Transfer Certificates | MED | 10-14 | AD-441, 441b ✓ |
| 4 | AD-455 | Security Team — Threat Detection & Trust Integrity | MED | 10-12 | RedTeamAgent, SIF ✓ |
| 5 | AD-468 | Runtime Configuration Service — Ship's Computer | LOW-MED | 8-10 | Standing Orders, Ward Room ✓ |

**Rationale:** Zero inbound deps on other selected ADs. All prerequisites already built. Mix of governance (439, 440), security (455), infrastructure (443), and operations (468).
- AD-439: Analytics-only feature, monitors Hebbian weights for emergent hierarchy — LOW risk
- AD-440: Adds `issue_order()` with chain-of-command validation — extends existing ontology
- AD-443: W3C VC transfer certificates, memory portability hooks — builds on complete DID stack
- AD-455: Formalizes Security Team pool (Threat Detector, Trust Integrity Monitor, Input Validator, Red Team Lead). Owns `src/probos/security/__init__.py` creation (mirroring AD-676's `governance/` precedent).
- AD-468: NL-driven config with runtime_overrides.toml — enables Captain to configure startup tasks via Ward Room

### Wave 6: Core Infrastructure (5 ADs, mostly parallel)

| # | AD | Title | Risk | Est. Tests | Deps Met? |
|---|---|---|---|---|---|
| 6 | AD-451 | Validation Framework Hardening | MED-HIGH | 10-14 | AD-447 ✓, AD-445 ✓, AD-448 ✓ |
| 7 | AD-457 | Engineering Crew — Performance, Maintenance, Damage Control | MED | 10-12 | VitalsMonitor, Surgeon ✓ |
| 8 | AD-458 | Navigational Deflector — Pre-Flight Validation | MED | 8-10 | AD-446 ✓ |
| 9 | AD-459 | Saucer Separation — Graceful Degradation | MED-HIGH | 10-12 | Alert Conditions ✓ |
| 10 | AD-460 | Cognitive Journal — Token Ledger & Reasoning Replay | MED | 10-14 | ModelRegistry, EPS (foundational) |

**Rationale:** These are chain-start ADs that enable downstream features. AD-460 is the most critical — it's a prerequisite for AD-463, AD-466, AD-467, and AD-469 in later waves.
- AD-451: Five validation capabilities — two-stage verification, inline self-verification, reconciliation escalation, disposition analysis, continuous validation
- AD-457: Four Engineering agents — Performance Monitor, Maintenance Agent, Infrastructure Agent, Damage Control Teams
- AD-458: Pre-flight validation middleware — build, self-mod, federation pre-flight checks
- AD-459: Three-tier service classification (Essential/Cognitive/Non-essential) with automatic degradation triggers
- AD-460: **CRITICAL PATH** — append-only SQLite recording of all LLM interactions. Enables token accounting, reasoning replay, and cost analytics

**Serialization note:** AD-460 must commit before Wave 7 begins (AD-463, AD-466, AD-467 depend on it).

### Wave 7: Infrastructure & Integration (5 ADs, serialize on AD-460)

| # | AD | Title | Risk | Est. Tests | Depends On |
|---|---|---|---|---|---|
| 11 | AD-456 | Security Infrastructure — Secrets, Sandboxing, Egress, Audit | MED-HIGH | 12-16 | AD-455 (Wave 5) |
| 12 | AD-463 | Model Diversity & Neural Routing | HIGH | 12-16 | AD-460 (Wave 6) |
| 13 | AD-466 | Engineering Infrastructure — Backup, CI/CD, Observability | MED | 10-14 | AD-460 (Wave 6), AD-461 ✓ |
| 14 | AD-467 | Operations Crew — Resource Management & Coordination | MED-HIGH | 12-16 | AD-460 (Wave 6), AD-461 ✓ |
| 15 | AD-641 | Ship's Computer / Crew Integration | MED | 10-14 | AD-637 ✓, AD-531-539 ✓ |

**Rationale:** AD-456 completes the security chain (AD-455 → AD-456). AD-463/466/467 all depend on AD-460's Cognitive Journal. AD-641 reconnects Ship's Computer (brain) with Ward Room (crew) — all deps already met.
- AD-456: Secrets management, runtime sandboxing, network egress policy, inference audit layer, data governance (PII/GDPR/CCPA)
- AD-463: ModelRegistry + provider abstraction + Hebbian neural routing + cost-aware selection. **HIGH risk** — touches routing core
- AD-466: Backup/restore, CI/CD pipeline config, performance benchmarks, OpenTelemetry export, storage abstraction
- AD-467: Resource Allocator, Scheduler (cron/webhook), Coordinator, Workflow Definition API, Response-Time Scaling, LLM Cost Tracker
- AD-641: Six sub-ADs (641a-641f) — Observability Bridge, WR Hebbian Learning, WR Thread Priority, Crew Deliberation, JIT↔Cache, Engineering Chief Observability

**Serialization:** AD-463 and AD-467 both touch routing infrastructure — build sequentially with full test gate between.

### Wave 8: Chain Completions (5 ADs, dependency-ordered)

| # | AD | Title | Risk | Est. Tests | Depends On |
|---|---|---|---|---|---|
| 16 | AD-469 | EPS — Compute/Token Distribution | MED-HIGH | 10-14 | AD-460, AD-467 (Waves 6-7) |
| 17 | AD-449 | MCP Bridge — External System Integration | MED | 10-12 | AD-448 ✓ (Commercial) |
| 18 | AD-472 | Channel Adapters — Multi-Platform Communication | LOW-MED | 8-12 | ChannelAdapter ABC ✓ |
| 19 | AD-484 | User Experience & Adoption Readiness | LOW | 6-8 | AD-465 ✓ |
| 20 | AD-475 | Captain's Ready Room — Strategic Planning Interface | MED | 8-10 | ArchitectAgent, Ward Room ✓ |

**Rationale:** AD-469 completes the ops chain (AD-460 → AD-467 → AD-469). AD-449/472/484/475 are independently buildable but placed last because they're primarily user-facing features that benefit from the infrastructure laid in Waves 5-7.
- AD-469: Department budgets, priority-based allocation, alert-aware reallocation, Captain override, back-pressure, prompt caching hierarchy
- AD-449: MCP bridge for external system integration (ERPs, CRMs) — **Commercial** but prompt can be drafted
- AD-472: Slack, Telegram, WhatsApp, Matrix, Teams, Webhook adapters — extends existing Discord pattern
- AD-484: PyPI packaging, onboarding wizard (`probos init`), `probos doctor`, quickstart docs
- AD-475: Idea capture, Ready Room sessions (multi-agent briefings), Idea→Spec pipeline with approval gates

---

## Exclusions with Rationale

| AD | Why Excluded |
|---|---|
| AD-476 (Specialized Builders) | Circular dep with AD-475 + needs AD-463; defer to next wave after both land |
| AD-487 (Self-Distillation) | Blocked by AD-486 (Holodeck — NOT BUILT) |
| AD-499 (Ship & Crew Naming) | Blocked by AD-479 (Federation Display — NOT BUILT) |
| AD-507-512 (Crew Development Framework) | Blocked by AD-477 (Qualifications) and AD-486 (Holodeck — both NOT BUILT) |
| AD-521 (SWE Pipeline Separation) | Blocked by AD-452 (Self-Mod Pipeline) and AD-543-546 (NOT BUILT) |
| AD-581 (Hybrid Dispatch) | Blocked by AD-496-498 (Workforce Scheduling — status unclear) |
| AD-628 (Crew Skill Readiness) | Blocked by AD-596 series (only SCOPED, not built) |
| AD-635 (Medical Diagnostic Data Access) | Blocked by AD-628g (LIMDU — NOT BUILT) |
| AD-647 (Process-Oriented Chains) | Blocked by AD-618, AD-595, AD-641g |

---

## Dependency Graph (build order)

```
Wave 5 (parallel):  AD-439  AD-440  AD-443  AD-455  AD-468
                                              │
Wave 6 (parallel):  AD-451  AD-457  AD-458  AD-459  AD-460 ◄── CRITICAL PATH
                                                       │
Wave 7 (serial on 460): AD-456  AD-463  AD-466  AD-467  AD-641
                          (←455)  (←460)  (←460) (←460)
                                           │
Wave 8 (dependency-ordered): AD-469  AD-449  AD-472  AD-484  AD-475
                              (←460,467)
```

## events.py Conflict Analysis

ADs that add EventType members (serialize within wave):
- **AD-439**: EMERGENT_LEADERSHIP_DETECTED (or similar)
- **AD-443**: AGENT_TRANSFER_INITIATED, AGENT_TRANSFER_COMPLETED
- **AD-455**: THREAT_DETECTED, TRUST_INTEGRITY_ALERT
- **AD-456**: SECURITY_AUDIT_EVENT, EGRESS_VIOLATION
- **AD-457**: DAMAGE_CONTROL_ACTIVATED, MAINTENANCE_SCHEDULED
- **AD-459**: SAUCER_SEPARATION_INITIATED, SERVICE_DEGRADED
- **AD-460**: COGNITIVE_JOURNAL_ENTRY (or similar)
- **AD-463**: MODEL_ROUTED, MODEL_FALLBACK
- **AD-467**: RESOURCE_ALLOCATED, WORKFLOW_STARTED
- **AD-469**: EPS_BUDGET_EXCEEDED, EPS_REALLOCATION
- **AD-641**: Multiple observability events

**Mitigation:** Within each wave, serialize ADs that add EventType members. Between waves, each wave's events.py additions commit before next wave starts. ~11 of 20 ADs add events — this is the primary merge conflict zone.

## Pre-Verification Requirements (per prompt)

Before drafting each prompt, architect must verify against live codebase:

1. **AD-439**: Check HebbianRouter weight access patterns; verify Hebbian data is queryable
2. **AD-440**: Read chain_of_command.py, verify `authority_over` ontology relationship exists
3. **AD-443**: Read identity/dids.py and identity_ledger.py; verify VC issuance API
4. **AD-455**: Grep for existing RedTeamAgent, SIF module locations; verify agent pool patterns
5. **AD-468**: Grep for existing runtime config patterns; check startup task toggle mechanism
6. **AD-451**: Read validation/ directory structure; check existing RedTeam/SystemQA patterns
7. **AD-457**: Read operations/ directory; verify VitalsMonitor and Surgeon interfaces
8. **AD-458**: Read builders/builder.py for pre-flight hook points; check middleware pattern
9. **AD-459**: Read alert_conditions.py; verify service classification exists or needs creation
10. **AD-460**: Read llm_client.py for token tracking hooks; check existing SQLite patterns
11. **AD-456**: Read security/ directory; check existing SIF patterns for extension
12. **AD-463**: Read models/ directory and llm_client.py provider abstraction; check HebbianRouter integration points
13. **AD-466**: Read infrastructure/ directory; check existing backup/observability patterns
14. **AD-467**: Read operations/ directory; verify PoolScaler and TaskScheduler interfaces
15. **AD-641**: Read Ward Room pipeline and Ship's Computer services; map 6 sub-AD touch points
16. **AD-469**: Read operations/ for EPS patterns; verify IntentBus budget enforcement hooks
17. **AD-449**: Read tools/ directory for MCP patterns; check Extension Architecture hooks
18. **AD-472**: Read communication/adapters/discord.py for ChannelAdapter ABC pattern
19. **AD-484**: Read cli/ for existing commands; check pyproject.toml packaging config
20. **AD-475**: Read Architect agent role; verify Ward Room session patterns

## Estimated Totals

- **Total new tests:** ~190 (range 170-220)
- **Total prompts to draft:** 20
- **GitHub issues to update:** 20 (move to In Progress in Project #2)
- **New GitHub issues needed:** TBD — some ADs may not have issues yet

## Execution Plan

### Step 1: Verify GitHub Issues Exist
Check which of the 20 ADs have existing GitHub issues. Create issues for any that don't.

### Step 2: Update GitHub Project Tracker
Move all 20 ADs to "In Progress" status in ProbOS Development Tracker (Project #2).

### Step 3: Prompt Drafting (separate multi-session effort)
Each of the 20 prompts drafted individually with full codebase verification per standing order. Priority order follows wave structure: Wave 5 first, then 6, 7, 8.

## Files Modified By This Plan

- GitHub Project #2: 20 items → In Progress
- GitHub Issues: create any missing issues
- No code changes — code changes happen when prompts are drafted and built
