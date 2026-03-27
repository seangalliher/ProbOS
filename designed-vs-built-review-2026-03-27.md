## Designed vs Built Review

Scope: d:/ProbOS only. Design sources reviewed were d:/ProbOS/prompts plus OSS design/state documents: PROGRESS.md, DECISIONS.md, Vibes/Nooplex_Final.md, and repo HXI/design rules in .github/copilot-instructions.md. No source-code changes were made.

Method:
- Pass 1: prompt-to-code traceability mapping
- Pass 2: direct source review of candidate gaps
- Pass 3: doc/status truthfulness check
- Falsification pass: re-read each candidate issue against source and tests before keeping it
- Matrix pass: classify each major prompt cluster as built, partial, deferred, or unverifiable even when no finding survives

Status legend:
- Built: materially implemented and supported by source and tests
- Partial: implemented in meaningful part, but missing a required behavior, UI surface, or enforcement layer
- Deferred: explicitly designed or implied, but not materially built yet
- Unverifiable: design intent found, but I could not establish implementation truth from the current code/docs/tests

## Executive Summary

Most of the backend cognition, governance, ontology, journal, identity, and proactive-system claims held up under direct source review. The durable gaps are concentrated in the HXI layer, with one additional runtime-level partial around directive overlays and one infrastructure-level partial around checkpoint resume.

The initial findings-first version of this report was directionally right but too narrow to count as a full prompt-cluster traceability audit. This revised version adds the broader matrix the review needed: major prompt clusters are now explicitly marked built, partial, deferred, or unverifiable, including aligned areas and superseded specs.

Several early candidates were explicitly cleared in the falsification pass:
- AD-323 bell/dropdown was intentionally superseded by AD-325 unified Bridge
- AD-432 journal traceability is implemented and tested
- Ontology breadth and ship commissioning claims are materially implemented and supported by tests
- Standing orders composition is implemented as described, even though runtime directive overlays remain incomplete

## Findings

### 1. HXI icon system diverges from the canonical SVG-only design language

Severity: Medium

Design evidence:
- d:/ProbOS/.github/copilot-instructions.md says all HXI icons must be inline SVG with strokeWidth 1.5 and strokeLinecap round
- It also explicitly flags emoji/icon violations as review issues

Built evidence:
- ui/src/components/bridge/BridgeCards.tsx uses Unicode step glyphs and dot separators
- ui/src/components/bridge/BridgeNotifications.tsx uses Unicode dot separators
- ui/src/components/AgentTooltip.tsx uses a Unicode warning badge and dot separator
- ui/src/components/BridgePanel.tsx uses Unicode chevrons, expand arrow, and close glyph
- ui/src/components/IntentSurface.tsx uses Unicode expand/collapse glyphs for text panels
- Additional Unicode glyph usage also appears in glass components such as GlassDAGNodes and ContextRibbon

Why this is a real gap:
- The repo defines the HXI icon system as part of the product language, not as an optional style preference
- The implementation still relies on text glyphs across core HXI surfaces, which breaks that rule consistently

Risk:
- Visual drift from the intended HXI identity
- Continued propagation of non-canonical icon usage into future UI work
- Inconsistent rendering and styling control versus SVG glyph components

Recommended remediation:
1. Introduce a shared SVG glyph set for status, chevron, divider, warning, expand, and close actions
2. Replace text glyphs across Bridge, tooltip, IntentSurface, and glass components
3. Align prompt examples so future HXI specs stop prescribing text glyphs where canonical rules require SVG

### 2. AD-324 attention-orb behavior is only partially implemented

Severity: Medium

Design evidence:
- d:/ProbOS/prompts/ad-324-orb-hover.md requires a pulsing amber effect on any orb whose task requires Captain attention
- The acceptance criteria says agents with requires_action tasks must pulse amber in the 3D view

Built evidence:
- ui/src/canvas/agents.tsx detects needsAttention and increases breathing amplitude from 0.03 to 0.08
- The orb body color still comes from poolTintBlend(agent.trust, agent.pool)
- Amber constants exist, but they are applied to notification orbitals, not the orb body itself

Why this is a real gap:
- The implementation adds stronger breathing and related notification signaling, but it does not implement the designed amber color pulse on the orb itself
- This is a partial substitute, not the same behavior the spec describes

Risk:
- Attention-needed agents are less visually distinct than designed
- The runtime state is not projected into the canvas in the exact way the HXI contract promises

Recommended remediation:
1. Extract orb-color computation into a testable helper
2. Blend the base orb color toward amber when needsAttention is true
3. Keep the orbital electron dots as an additive signal rather than the primary attention indicator
4. Add a regression test around the helper or per-agent color decision path

### 3. The HXI changes are not protected by the component-level Vitest coverage required by the repo and by AD-324

Severity: Medium

Design evidence:
- d:/ProbOS/.github/copilot-instructions.md requires every UI change to include a Vitest component test and explicitly says no UI PR without tests
- d:/ProbOS/prompts/ad-324-orb-hover.md requires new UI tests under ui/src/__tests__ and lists tooltip-related behaviors to verify

Built evidence:
- Existing UI test coverage is concentrated in store and integration surfaces such as ui/src/__tests__/useStore.test.ts and ui/src/__tests__/GlassLayer.test.tsx
- I did not find component render tests covering the actual Bridge and tooltip surfaces that implement the reviewed behavior: BridgePanel, TaskCard, NotificationCard, AgentTooltip, or the Bridge toggle/visible behavior in IntentSurface

Why this is a real gap:
- The repo's own process rule requires component tests for UI changes
- The reviewed HXI changes touch exactly the kinds of surfaces the repo says have regressed before: tooltips, bloom, chat rendering, interaction layers

Risk:
- Regressions in tooltip rendering, Bridge behavior, unread/attention partitioning, and visible interaction affordances
- Design-contract drift can persist unnoticed because only store-level behavior is covered

Recommended remediation:
1. Add render-level tests for AgentTooltip task section present/absent behavior
2. Add tests for attention badge rendering and Bridge open behavior
3. Add tests for BridgePanel section partitioning: Attention, Active, Notifications
4. Add tests for NotificationCard acknowledge interactions and empty-state rendering
5. For the orb pulse, test an extracted calculation helper rather than raw R3F internals

## Full Traceability Matrix

### Cognition and Runtime

| Cluster | Representative prompts/docs | Primary built surface | Status | Evidence and notes |
|---|---|---|---|---|
| Ship's Computer grounding | ships-computer-identity.md, systemselfmodel.md, pre-response-verification.md, introspection-delegation.md | prompt_builder.py, decomposer.py, runtime.py | Built | Prompt preamble, runtime summary injection, and response verification are implemented and covered by tests. |
| Standing orders composition | per-agent-standing-orders.md | cognitive_agent.py, config/standing_orders/, standing_orders.py | Built | Ordered standing-order composition exists and matches the written model. |
| Runtime directive overlays | runtime-directives.md | standing_orders.py, cognitive_agent.py | Partial | The static standing-order layer exists, but the spec's runtime-issued directive overlay layer is not materially present as a managed system. |
| Architect agent | add-architect-agent.md, improve-architect-quality.md, architect-deep-localize.md, architect-call-graph.md | architect.py, codebase_index.py | Built | Deep-localize context assembly, call-graph/import expansion, and proposal generation are present and tested. |
| Builder and transporter pipeline | add-builder-agent.md, builder-file-edit-support.md, builder-test-fix-loop.md, ad-330-build-blueprint.md through ad-336-end-to-end-integration.md | builder.py, build_queue.py, worktree_manager.py, build_dispatcher.py | Built | Blueprint decomposition, chunk execution, assembly, validation, and test-fix loops are materially implemented. |
| Self-modification pipeline | phase-10-self-mod.md, phase-15a-cognitive-agent-base.md, selfmod-durability.md, codevalidator-hardening.md | self_mod.py, agent_designer.py, code_validator.py, sandbox.py | Built | Gap detection through design, validation, sandboxing, deploy, and trust/Hebbian updates is present and tested. |
| Skills and competency model | phase-11-skills-transparency-research.md, phase-15b-domain-aware-skill-attachment.md, ad-428-agent-skill-framework.md | skill_framework.py, runtime.py | Built | Skill registry, proficiency model, role templates, and API surface are present. |
| Correction and feedback loop | phase-18-feedback-to-learning.md, phase-18b-correction-feedback.md | correction_detector.py, agent_patcher.py, feedback.py | Built | Correction parsing, patch flow, and feedback-to-trust/Hebbian wiring are implemented and tested. |
| Episodic memory lifecycle | phase-14-persistent-knowledge.md, phase-14b-chromadb.md, ad-430a-c | episodic.py, cognitive_agent.py, runtime.py | Built | Perceive-time recall and act-time episode storage are in place. |
| Cognitive journal and traceability | ad-431-cognitive-journal.md, ad-432-cognitive-journal-expansion.md | journal.py, llm_client.py, cognitive_agent.py | Built | intent_id, response_hash, grouped token queries, and anomaly/decision queries are implemented and tested. |
| Proactive cognitive loop | phase-28b-proactive-cognitive-loop.md | proactive.py, runtime.py | Built | Idle-think loop, gating, context gathering, and proactive execution are live. |
| Ward Room backend and agent action flow | ad-407a-d, ad-424, ad-425, ad-426, ad-437 | ward_room.py, proactive.py, runtime.py | Built | Ward Room storage, thread mechanics, endorsement flow, and structured agent actions are implemented. |

### Governance and Infrastructure

| Cluster | Representative prompts/docs | Primary built surface | Status | Evidence and notes |
|---|---|---|---|---|
| Bayesian trust network | phase-19-shapley-trust-matching.md | consensus/trust.py | Built | Raw Beta trust storage, persistence, and update mechanics exist and are tested. |
| Quorum and Shapley attribution | phase-19-shapley-trust-matching.md | consensus/quorum.py, consensus/shapley.py | Built | Confidence-weighted quorum and Shapley attribution are materially implemented. |
| Earned agency core gating | ad-357-earned-agency.md | earned_agency.py, crew_profile.py, ward_room.py, proactive.py | Built | Rank and agency gating for ambient/proactive behavior are present. |
| Earned agency reinforcement extensions | ad-357-earned-agency.md, DECISIONS.md notes | earned_agency.py and surrounding future hooks | Deferred | The core gating is built, but reinforcement extensions called out in the decision trail remain future work. |
| Agent Capital Management | ad-427-acm-core-framework.md | acm.py, runtime.py | Built | Lifecycle state machine, audit trail, consolidated profile, and runtime integration are present. |
| Vessel ontology foundation | ad-429a-d | ontology.py, config/ontology/ | Built | Vessel, organization, crew, skills, operations, communication, resources, and records domains all exist. |
| Ontology dict migration | ad-429e-ontology-dict-migration.md | runtime.py, ward_room.py, proactive.py, shell.py | Built | Preferred ontology reads with legacy fallback are wired across runtime call sites. |
| Sovereign identity and ship commissioning | ad-441-sovereign-agent-identity.md, ad-441b-ship-commissioning.md | identity.py | Built | DIDs, birth certificates, ledger, ship VC, and genesis block integration are implemented. |
| Emergent behavior detection | phase-20-emergent-detection.md, ad-411-emergent-detector-dedup.md | emergent_detector.py | Built | Multi-signal emergence monitoring exists and has follow-on bugfixes for false positive control. |
| DAG checkpoint persistence | ad-405-dag-checkpointing.md | checkpoint.py | Partial | Checkpoint write path exists, but full automatic resume behavior is not materially complete. |
| Duty scheduling | ad-419-duty-schedule.md | duty_schedule.py, proactive.py | Built | Scheduled duties, due checks, and proactive routing are implemented. |

### HXI and Frontend

| Cluster | Representative prompts/docs | Primary built surface | Status | Evidence and notes |
|---|---|---|---|---|
| Phase 23 HXI MVP | phase-23-hxi-mvp.md, phase-23-execution-instructions.md | CognitiveCanvas.tsx, IntentSurface.tsx, DecisionSurface.tsx, api.py | Built | Core canvas, event flow, overlays, and serve-time UX are materially present. |
| Unified Bridge redesign | ad-325-unified-bridge.md | BridgePanel.tsx, bridge/BridgeCards.tsx, bridge/FullKanban.tsx | Built | The single Bridge panel is implemented and AD-323's separate bell/dropdown design is intentionally superseded. |
| Notification queue bell/dropdown | ad-323-notification-queue.md | superseded by Bridge surfaces | Deferred | Not a bug: the standalone control path was replaced by AD-325 rather than omitted by accident. |
| Attention-orb hover/attention state | ad-324-orb-hover.md | canvas/agents.tsx | Partial | NeedsAttention affects breathing and orbitals, but the designed amber pulse on the orb body is not fully implemented. |
| Transporter HXI visualization | ad-335-hxi-transporter-viz.md, ad-330 through ad-334 | IntentSurface.tsx, useStore.ts, builder.py events | Partial | Backend eventing and chat-surface progress messages exist; richer canvas-level visualization is not present. |
| Glass Bridge suite | ad-388 through ad-392 | components/glass/* | Built | Glass overlay, DAG nodes, ambient state, atmosphere, and adaptive bridge behaviors are implemented with Vitest coverage. |
| Chat and approval surfaces | phase-23-hxi-mvp.md, ad-335-hxi-transporter-viz.md | IntentSurface.tsx | Partial | The user-facing surfaces exist, but the reviewed component behaviors are not protected by the expected render-level tests. |
| Welcome overlay | phase-23-hxi-mvp.md, visiting-officer-hxi-integration.md | WelcomeOverlay.tsx | Partial | The overlay exists, but I did not find direct UI test coverage for its behavior. |
| Crew profile HXI surface | ad-393, ad-397, ad-398 | profile/ProfileInfoTab.tsx, profile/AgentProfilePanel.tsx | Built | Profile and identity views are materially present. |
| Ward Room HXI surface | ad-407c-ward-room-hxi.md and later Ward Room prompts | no mature dedicated Ward Room panel found in active HXI flow | Deferred | Ward Room backend exists, but the corresponding HXI thread-browsing/posting surface is not materially present in the reviewed UI. |
| HXI icon language compliance | .github/copilot-instructions.md HXI rules | Bridge, tooltip, intent, and glass components | Partial | Core surfaces still use Unicode glyphs instead of the repo's canonical inline SVG icon language. |
| Component-level HXI regression coverage | .github/copilot-instructions.md, ad-324-orb-hover.md | ui/src/__tests__ | Partial | Store/integration tests exist, but several reviewed UI components lack direct render-level Vitest protection. |

## Cleared Candidates

These were investigated and dropped from the final findings because the built code matched the spec after direct review:

### AD-323 notification bell/dropdown as a missing feature
- AD-325 explicitly replaces the separate NOTIF, ACTIVITY, and MISSION CTRL controls with a single BRIDGE button and Bridge panel
- The built UI follows the AD-325 direction
- Conclusion: not a defect; treat as a superseded design path

### AD-432 journal traceability incomplete
- intent_id, dag_node_id, response_hash schema fields are present
- CognitiveAgent passes intent_id into journal recording paths
- Tests cover the AD-432 fields and related queries
- Conclusion: not a surviving finding

### Ontology breadth overstated
- config/ontology contains vessel, organization, crew, skills, operations, communication, resources, and records schemas
- DECISIONS.md status text is supported materially by the current codebase
- Conclusion: initial concern was stale after direct inspection

### Ship commissioning / W3C VC claims overstated
- ShipBirthCertificate is implemented in src/probos/identity.py
- Ship DID, VC serialization, genesis block integration, and tests exist
- Conclusion: not a surviving finding

### Standing orders hierarchy not enforced
- The prompt spec describes ordered composition into the final system prompt
- standing_orders.py implements that composition model and tests cover ordering
- Conclusion: composition is built; the surviving issue is narrower and limited to runtime directive overlays

## Alignment Notes

Areas that remained aligned after re-check:
- Ship's Computer prompt grounding
- Standing orders composition
- Correction detection parsing robustness
- Architect/builder/transporter pipeline existence and wiring
- Cognitive journal expansion
- Ontology breadth and ontology migration wiring
- Ship commissioning and sovereign identity
- Trust, quorum, and Shapley governance substrate
- ACM lifecycle/profile integration
- Proactive loop and Ward Room backend action space

## Status Rollup

By major cluster count in this review:
- Built: 20
- Partial: 8
- Deferred: 4
- Unverifiable: 0

Interpretation:
- The runtime and governance substrate are substantially aligned with the design corpus.
- The highest concentration of design-vs-built divergence is the HXI layer.
- The most meaningful non-HXI partials are runtime directive overlays and checkpoint resume behavior.

## Recommended Priority Order

1. Fix the HXI icon system first to restore the canonical design language
2. Add component-level tests for Bridge, tooltip, chat, and welcome surfaces before more HXI changes land
3. Complete the orb amber pulse behavior so AD-324 is actually satisfied rather than approximated
4. Decide whether runtime directives are meant to remain static standing orders or become a first-class runtime overlay system
5. Either finish DAG auto-resume from checkpoints or explicitly narrow the spec/status language to checkpoint persistence only
6. Decide whether Ward Room HXI is the next real product surface or should remain explicitly deferred in roadmap/prompt language

## Notes

- No production source files were modified for this review; only this markdown artifact was updated
- This report was intentionally narrowed through multiple validation passes to avoid false positives, then broadened into a full prompt-cluster matrix
- The commercial repo was not part of the implementation traceability findings because its prompts directory is empty and the request was scoped to OSS designed-vs-built behavior