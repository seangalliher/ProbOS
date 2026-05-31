# Research Synthesis: Yeo Feature-Complete Slate (2026-05-20)

Status: architect research synthesis for planning only (no production code changes).
Scope: AD-749 through AD-758 issue/prompt slate for Yeo OSS feature completeness under AD-710 umbrella.
Primary sources:
- Captain-provided Yeo gap sections (10 areas) in the request.
- AionUi repo pattern research (`iOfficeAI/AionUi`).
- Current ProbOS roadmap + open issues (dedupe against #486, #480, #484, #538 and Waves 175-180 shipped stacks).

## Captain Requirement (Program Invariant)
"Yeo is primary assistant front door, but all crew agents can use these capabilities. Yeo delegates tasks to specialists."

Every AD in this slate carries this invariant as an acceptance criterion.

## License-Aware Absorbability Matrix

| Source | License | Absorbability | Pattern to Absorb (not code) | Do Not Absorb |
|---|---|---|---|---|
| `iOfficeAI/AionUi` | Apache-2.0 | Allowed (pattern-only preferred) | Channel plugin manager boundary, pairing approval flow, session manager lifecycle, permission modes surface, streaming merge conventions | Any direct implementation copy/paste |
| `iOfficeAI/AionHub` | Apache-2.0 | Allowed (pattern-only) | Extension packaging/discovery shape for channel capabilities | Hub implementation code |
| `QwenLM/qwen-code` (referenced by AionUi mode handling) | Apache-2.0 | Allowed (pattern-only) | Backend mode capability gating behavior | Backend-specific mode logic copy |
| `anomalyco/opencode` (referenced by AionUi mode map) | MIT | Allowed (pattern-only) | Mode taxonomy and backend feature flags approach | Runtime code copy |
| `openai/codex` (referenced by AionUi mode map) | Apache-2.0 | Allowed (pattern-only) | Safe auto/plan/full-auto mode presentation conventions | Any vendor-specific protocol coupling |

Disposition: absorb architecture patterns only. Implement ProbOS-native code and interfaces.

## AionUi Pattern Extraction (What to Copy as Pattern Only)

1. Channel/plugin architecture and adapter boundary:
- Pattern: central channel orchestrator with plugin manager + session manager + action executor + pairing service.
- ProbOS fit: AD-749 foundation for M365 connectors and shared agent-facing channel contracts.

2. Pairing/authorization flow for remote channels:
- Pattern: pending pairing queue, approve/reject actions, authorized user list, TTL cleanup.
- ProbOS fit: AD-749/AD-753 permission entry surfaces and unattended policy controls.

3. Message streaming/merge strategy:
- Pattern: streaming chunks merged into coherent turn artifacts; explicit thinking/status phases.
- ProbOS fit: AD-756 front-door UX stream merge and delegation transparency.

4. Session manager model:
- Pattern: explicit session lifecycle, resume/reassert configuration, backend compatibility adapter.
- ProbOS fit: AD-750 semantic continuity + AD-757 identity continuity.

5. Cron automation UX conventions:
- Pattern: surfaced schedule state, obvious execution mode, low-friction edits.
- ProbOS fit: AD-752 heartbeat and work-hours/quiet-hours policy with user-visible status.

6. Permission mode surfaces (manual approve vs autopilot analog):
- Pattern: mode taxonomy shown clearly with backend-safe gating.
- ProbOS fit: AD-753 `autoApproveReadOnly`, approval cards, tenant-policy extension hook.

7. Credential encryption utility pattern:
- Pattern: dedicated utility boundary for credential storage/cryptography, not ad-hoc storage in adapters.
- ProbOS fit: AD-754 hardening baseline and secure token/session material handling.

## Gap-to-AD Translation (Complete Coverage)

1. M365 auth + core agents -> AD-749 (#695)
2. WorkIQ semantic layer -> AD-750 (#696)
3. Desktop UX surface -> AD-751 (#697)
4. Proactive scheduling + quiet-hours -> AD-752 (#698)
5. Unattended permissions -> AD-753 (#699)
6. Data hardening -> AD-754 (#700)
7. Office doc skills + SharePoint + templates -> AD-755 (#701)
8. Conversational front door UX -> AD-756 (#702)
9. Identity + continuity -> AD-757 (#703)
10. Program integration gate + learning upgrades criteria -> AD-758 (#704)

## Dedupe + Conflict Avoidance

- Keep AD-710 (#486) as umbrella; this slate is child decomposition.
- Do not duplicate channel adapter delivery scope from AD-704 (#480).
- Do not duplicate mobile companion scope from AD-708 (#484).
- Do not overlap Blender connector delivery from AD-721j (#538).
- Do not reopen already shipped voice/perception stacks in Waves 175-180.

## Commercial Boundary Notes

Public OSS repo can define extension points only for:
- Tenant policy hook integration.
- Enterprise governance/compliance plugin points.

Must NOT include in public roadmap/issues/prompts:
- Pricing, packaging tiers, customer segmentation, or go-to-market details.

## Non-Goals (for this slate)

- No production implementation in this change.
- No DECISIONS.md edits.
- No new paid-license dependencies.
- No replacement of existing Ward Room/PADD foundations.

## Suggested Build Sequencing (for future wave planning)

Phase 1 foundation:
- AD-749, AD-750, AD-753, AD-754

Phase 2 capability surfaces:
- AD-755, AD-752, AD-751

Phase 3 front-door + continuity:
- AD-756, AD-757

Phase 4 program completion gate:
- AD-758
