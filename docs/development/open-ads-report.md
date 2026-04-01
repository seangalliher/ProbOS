# ProbOS — Open Architecture Decisions (Prioritized)

*Generated 2026-03-31. 87 open ADs + 7 open bugs = 94 open items.*

---

## Tier 1: In-Flight (Wave 6 — Active Now)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 1 | BF-093 | API Boundary Validation | All API endpoints use Pydantic models with proper HTTP error codes — no raw `dict` payloads remain. |
| 2 | BF-094 | Sync File I/O in Async Methods | Event loop never blocks on file I/O — all sync reads/writes wrapped in `run_in_executor`. |
| 3 | BF-095 | God Object Reduction (Ontology + WardRoom) | VesselOntologyService and WardRoomService decomposed into focused sub-services, each ≤20 methods. |

## Tier 2: Open Bugs (Standalone, Pre-Wave 6)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 4 | BF-041 | HXI Icon System Divergence | Consistent SVG-only icon language across all HXI surfaces — no Unicode glyph fallbacks. |
| 5 | BF-063 | Naming Ceremony Silent Default | Distinguishable logs when LLM fails vs when agent deliberately accepts default name. |
| 6 | BF-069 | LLM Proxy Failure Silent | Bridge alerts on consecutive LLM failures with health check and system panel status indicator. |
| 7 | BF-080 | DM Channels Not Clickable in HXI | Captain can click DM channels in Ward Room to read agent-to-agent conversations. |

## Tier 3: Wave 5 — Agent Resilience (Next Wave)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 8 | AD-528 | Ground-Truth Task Verification | WorkItems declare verifiable postconditions; second-agent spot checks reduce trust on discrepancy. |
| 9 | AD-529 | Communication Contagion Firewall | Ward Room content scanned for dangerous patterns with quarantine protocol and trust-based filtering. |
| 10 | AD-530 | Information Classification Enforcement | Data sources carry classification labels with enforced disclosure gates at communication boundaries. |

## Tier 4: Extension & Self-Improvement (Phase 30+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 11 | AD-481 | Extension-First Architecture — Sealed Core | Core sealed with 8 defined extension points; extensions hot-toggleable and evergreen-updateable. |
| 12 | AD-482 | Self-Improvement Pipeline — Discovery to Deployment | Closed-loop improvement from capability proposals through QA to git-backed agent persistence. |
| 13 | AD-483 | Tool Layer — Instruments | Lightweight `Tool` base class with ToolRegistry, trust integration, and MCP compatibility. |
| 14 | AD-543 | Unified Tool Layer | Internal and external tools under one abstraction; AgenticToolAdapter protocol; skill→tool resolution. |

## Tier 5: Security Hardening (Phase 31)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 15 | AD-455 | Security Team — Threat Detection & Trust Integrity | Formalized Security Team with Threat Detector, Trust Integrity Monitor, Input Validator, Red Team Lead. |
| 16 | AD-456 | Security Infrastructure — Secrets, Sandboxing, Egress, Audit | Secrets management, runtime sandboxing, network egress policy, inference audit layer in place. |
| 17 | AD-490 | Agent Wiring Security Logs | Agent wiring events enriched with callsign/DID/department; startup audit summary. |
| 18 | AD-492 | Cognitive Correlation IDs | Full cognitive chain tracing from perception to meta-thought with depth-based spiral detection. |

## Tier 6: Cognitive Self-Regulation Wave (Phase 31+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 19 | AD-495 | Counselor Auto-Assessment on Circuit Breaker Trip | Circuit breaker trips auto-dispatch Counselor assessment instead of silent suppression. |
| 20 | AD-503 | Counselor Activation — Data Gathering & Persistence | Counselor gathers own metrics, persists CognitiveProfiles to SQLite, runs wellness sweeps. |
| 21 | AD-504 | Agent Self-Monitoring Context | Agents see their own recent outputs in cognitive context with self-similarity scoring. |
| 22 | AD-505 | Counselor Therapeutic Intervention | Counselor sends proactive 1:1 DMs with therapeutic recommendations based on behavioral data. |
| 23 | AD-506 | Graduated System Response | Binary circuit breaker replaced with Green/Amber/Red/Critical zones using SPC-informed thresholds. |

## Tier 7: Orchestration & Knowledge (Phase 31+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 24 | AD-438 | Ontology-Based Task Routing | Directed assignment replaces broadcast-and-claim for routine tasks; broadcast preserved for novel ones. |
| 25 | AD-439 | Emergent Leadership Detection | Dashboard shows divergence between designed hierarchy and emergent Hebbian weight patterns. |
| 26 | AD-440 | Chain of Command Delegation | First Officer can coordinate without Captain via formalized `issue_order()` validated against chain of command. |
| 27 | AD-444 | Knowledge Confidence Scoring | Ship's Records learnings gain confidence scores that adjust on confirmation or contradiction. |
| 28 | AD-445 | Decision Queue & Pause/Resume Semantics | Agents pause on ambiguity with structured Decision Requests and priority-based auto-resolve. |
| 29 | AD-446 | Compensation & Recovery Pattern | Multi-step workflow failures produce compensation logs with SHA-256 idempotency guards. |
| 30 | AD-447 | Phase Gates for Pool Orchestration | Phase N must complete and validate before Phase N+1 starts in multi-pool workflows. |
| 31 | AD-448 | Wrapped Tool Executor — Security Intercept Layer | Transparent tool call interception for logging, rate limiting, and policy enforcement. |
| 32 | AD-451 | Validation Framework Hardening | Two-stage verification, self-verification, reconciliation escalation, and continuous validation. |
| 33 | AD-499 | Ship & Crew Naming Conventions | Three-layer naming: ship registry, agent personal names, federated display format. |
| 34 | AD-513 | Ship's Crew Manifest | Unified queryable crew roster with REST API, shell command, and agent tool access. |
| 35 | AD-522 | Statistical Process Control for Agent Calibration | Shewhart control charts replace threshold-based anomaly detection; Cp/Cpk behavioral stability scores. |

## Tier 8: Crew Development Wave (Phase 31+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 36 | AD-442 | Adaptive Onboarding — Phases 2-5 | Westworld Orientation, Temporal Consciousness, Ship State Adaptation, and Probationary Period complete. |
| 37 | AD-486 | Holodeck Birth Chamber | Five-phase graduated cognitive onboarding with staged activation and trait-adaptive pacing. |
| 38 | AD-487 | Self-Distillation — Personal Ontology via LLM Exploration | Agents explore their own LLM weights to build personal ontology; continues as "daydreaming" in dream cycles. |
| 39 | AD-489 | Federation Code of Conduct | Three Core Values, Six Articles of Conduct, Three-Tier Discipline formalized. |
| 40 | AD-507 | Crew Development Framework | Universal core knowledge curriculum with competency assessment and progression tracking. |
| 41 | AD-508 | Scoped Cognition — Knowledge Boundaries | Four-tier scope model (Duty/Role/Ship/Personal) with drift detection and extracurricular framework. |
| 42 | AD-509 | Onboarding Curriculum Pipeline | Navy Boot Camp structure: orientation → core curriculum → A-School → calibration → crew integration. |
| 43 | AD-510 | Holodeck Team Simulations | Mixed-department team scenarios with role rotation, communication constraints, and debrief. |
| 44 | AD-511 | Agent Autonomy Boundaries | Inviolable Federation-tier boundaries with protective disengagement and unlawful order refusal. |
| 45 | AD-512 | Discovery-Based Capability Building | Replace "you can't do X" with experiential discovery and Vygotsky ZPD-based capability confidence. |

## Tier 9: Circuit Breaker Extensions (Phase 31+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 46 | AD-493 | Novelty Gate — Experiential Baseline Filtering | True novelty detection with experiential baseline; cold-start bypass until ≥50 episodes. |
| 47 | AD-494 | Trait-Adaptive Circuit Breaker Thresholds | Circuit breaker thresholds personalized per agent based on Big Five personality scores. |

## Tier 10: Cognitive JIT / Procedural Learning (Phase 32)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 48 | AD-464 | Procedural Learning / Cognitive JIT | Procedure extraction from execution traces with replay-first dispatch at zero tokens. |
| 49 | AD-531 | Episode Clustering | Dream cycles cluster repeating episodic patterns for procedure candidate identification. |
| 50 | AD-532 | Procedure Extraction | Deterministic procedures extracted from clustered episodes with three evolution types. |
| 51 | AD-533 | Procedure Store | Git YAML + SQLite index hybrid store with version DAG, quality metrics, and semantic indexing. |
| 52 | AD-534 | Replay-First Dispatch | `decide()` checks procedural memory before LLM; deterministic replay at zero token cost. |
| 53 | AD-535 | Graduated Compilation Levels | Five Dreyfus levels from Novice (full LLM) to Expert (can teach) with trust-gated transitions. |
| 54 | AD-536 | Trust-Gated Procedure Promotion | Two-tier approval for shared procedure library promotion. |
| 55 | AD-537 | Observational Learning | Agents learn from observing others' Ward Room successes via Bandura's social learning theory. |
| 56 | AD-538 | Procedure Lifecycle Management | Decay, re-validation, deduplication, and archival keep procedure store fresh. |
| 57 | AD-539 | Knowledge Gap to Qualification Pipeline | Failure clustering identifies gaps → feeds Holodeck scenario generation and qualification programs. |

## Tier 11: Engineering Team (Phase 32)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 58 | AD-457 | Engineering Crew | Performance Monitor, Maintenance Agent, Infrastructure Agent, and Damage Control Teams operational. |
| 59 | AD-458 | Navigational Deflector — Pre-Flight Validation | Build/self-mod/federation pre-flight validation prevents bad changes from landing. |
| 60 | AD-459 | Saucer Separation — Graceful Degradation | Three-tier service classification enables crisis shedding of non-essential services. |
| 61 | AD-460 | Cognitive Journal — Token Ledger | Append-only LLM request/response recording with reasoning chain replay and token accounting. |
| 62 | AD-461 | Ship's Telemetry | TelemetryEvent dataclass with wall-clock LLM timing and zero-cost fire-and-forget recording. |
| 63 | AD-462 | Memory Architecture — Biological Memory Model | Biological memory staging with active forgetting, variable recall, and Oracle service. |
| 64 | AD-463 | Model Diversity & Neural Routing | Multi-model cognitive architecture with ModelRegistry, provider abstraction, and cost-aware routing. |
| 65 | AD-478 | Meta-Learning — Cross-Session Concept Formation | Workspace ontology and dream cycle abstractions enable cross-session concept retention. |

## Tier 12: Operations & Communications (Phase 33-34)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 66 | AD-467 | Operations Crew | Resource Allocator, Scheduler, Coordinator, and LLM Cost Tracker operational. |
| 67 | AD-468 | Runtime Configuration Service | NL-driven runtime configuration with HXI config panel and persistence. |
| 68 | AD-469 | EPS — Compute/Token Distribution | Department LLM budgets with alert-aware reallocation and back-pressure. |
| 69 | AD-470 | IntentBus Enhancements | Priority levels, back-pressure, rate limiting, and self-claiming task queue on IntentBus. |
| 70 | AD-472 | Channel Adapters — Multi-Platform | Slack, Telegram, WhatsApp, Matrix, Teams adapters for external communication. |
| 71 | AD-473 | Mobile Companion — PWA | Progressive web app with push notifications, responsive HXI, and mDNS discovery. |
| 72 | AD-474 | Voice Interaction | Speech-to-text, wake word, continuous talk mode, and Ship's Computer voice. |
| 73 | AD-475 | Captain's Ready Room | Strategic planning interface with idea capture, multi-agent briefings, and idea-to-spec pipeline. |
| 74 | AD-476 | Specialized Builders | Backend/Frontend/Test/Infrastructure/Data builders as extensions with model routing. |
| 75 | AD-477 | Naval Organization Protocols | Qualification Programs, Plan of the Day, Captain's Log synthesis, 3M System, Damage Control. |

## Tier 13: Workforce Cleanup (Phase 31+, Depends AD-496/498)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 76 | AD-500 | DutyScheduleTracker to WorkItem Migration | DutyScheduleTracker generates duty-type WorkItems instead of directly triggering proactive thinks. |
| 77 | AD-501 | TaskTracker Deprecation | NotificationQueue separated to own module; orphaned TaskTracker deprecated. |

## Tier 14: Skill Framework Advanced (Phase 32+, Blocked)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 78 | AD-428b | Agent Skill Framework — Advanced Features | Model-skill alignment, INNATE skills, composite skills, Holodeck assessment, dream reinforcement. |

## Tier 15: HXI & Visualization (Phase 31+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 79 | AD-520 | Spatial Knowledge Explorer | Knowledge graph view + spatial ship layout + immersive digital twin (VR/XR commercial). |
| 80 | AD-523 | HXI Ward Room & Records Overhaul | DM Channel Viewer, Crew Notebooks Browser, Ship's Records Dashboard in HXI. |

## Tier 16: Infrastructure & Deployment (Phase 35)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 81 | AD-465 | Containerized Deployment (Docker) | Official Dockerfile and docker-compose with cross-platform support and Ollama sidecar. |
| 82 | AD-466 | Engineering Infrastructure | Backup/restore, GitHub Actions CI/CD, performance testing, OpenTelemetry, storage abstraction. |
| 83 | AD-484 | User Experience & Adoption Readiness | PyPI publishing, onboarding wizard, quickstart docs, browser automation. |

## Tier 17: Federation & Mobility (Phase 29+)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 84 | AD-443 | Agent Mobility Protocol | Transfer Certificate VCs enable agents to move between ProbOS instances with governed memory portability. |
| 85 | AD-479 | Federation Hardening | Dynamic peer discovery, cross-node episodic memory, TLS/auth, and cluster management. |
| 86 | AD-480 | Federation Protocol Adapters — MCP & A2A | ProbOS participates in MCP and A2A federation as both server and client. |

## Tier 18: Commercial (Private Repo)

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 87 | AD-449 | MCP Bridge — External System Integration | Session-managed MCP bridge for ProbOS agents to interact with ERPs/CRMs/databases. |
| 88 | AD-450 | ERP Implementation Ship Class | D365 ERP Company Designer reimplemented as a ProbOS Ship Class — first Nooplex engagement. |
| 89 | AD-452 | Agent Tier Licensing Framework | OSS/Commercial crew boundary defined — capability depth is the product, not capability existence. |

## Tier 19: Research & Future

| # | ID | Title | Expected Outcome |
|---|-----|-------|-----------------|
| 90 | AD-491 | Infodynamic Telemetry | Measured information entropy testing Second Law of Infodynamics in multi-agent systems. |
| 91 | AD-524 | Ship's Archive — Generational Knowledge | Previous generations' Ship's Records readable by new crews after reset. |
| 92 | AD-525 | Agent Creative Expression | Creative skill catalog with trust-tiered creative time and creative output to Ship's Records. |
| 93 | AD-526 | Agent Chess & Recreation | Chess via `python-chess` + LLM reasoning with Elo ratings; Recreation channels. |
| 94 | AD-540 | Memory Provenance Boundary | Structural separation of episodic memory from LLM training data with source attribution. |
| 95 | AD-541 | Memory Integrity Verification | Episode verification against EventLog with anti-confabulation and reconsolidation protection. |
