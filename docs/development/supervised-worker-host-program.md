# ProbOS-Hosted Strong Supervision

Status: **planned**, explicitly requested 2026-09-08. No strong-host deployment,
runtime change, or operational canary is claimed by this document.

The immediate delivery track is a working Supervised Worker Agent Plugin in
VS Code with GitHub Copilot as its harness. That track uses explicitly accepted
local-scoped assurance and stays in the
[Supervised Worker repository](https://github.com/seangalliher/supervised-worker).
This later program retains the original strong assurance requirements by placing
their enforcement and evidence sources inside a harness ProbOS actually owns.

## Issue Map

| AD | Issue | Deliverable | Dependency |
| --- | --- | --- | --- |
| AD-1314 | [#1379](https://github.com/seangalliher/ProbOS/issues/1379) | Program, trust boundary and complete acceptance contract. | Copilot-local usability is the immediate priority. |
| AD-1315 | [#1381](https://github.com/seangalliher/ProbOS/issues/1381) | Protected host authority and durable pre-dispatch admission witness. | Explicit strict-profile threat model. |
| AD-1316 | [#1383](https://github.com/seangalliher/ProbOS/issues/1383) | Governed effect broker, operation IDs and reconciliation. | AD-1315. |
| AD-1317 | [#1380](https://github.com/seangalliher/ProbOS/issues/1380) | Versioned host adapter, immutable activation/rollback, restart and strong canary. | AD-1315 and AD-1316. |
| AD-1318 | [#1382](https://github.com/seangalliher/ProbOS/issues/1382) | Optional VS Code surface and Copilot-assisted interoperability. | Proven headless AD-1317 contract. |

[Supervised Worker #11](https://github.com/seangalliher/supervised-worker/issues/11)
owns portable protocol/receipt compatibility and the retained strong obligations.
Its Copilot-local #10/#6/#5 scope change must not be interpreted as completing these
strong requirements. HydraFusion remains a separate experiment, not a prerequisite.

## Ownership

ProbOS supplies runtime identity, governed effect dispatch, a protected witness,
and host activation/recovery. Supervised Worker remains the sole owner of its
durable campaign plan, attachment, checkpoint and Doctor incident state. Define a
narrow versioned protocol instead of duplicating the JavaScript lifecycle kernel
or maintaining two independent campaign owners.

Preserve AD-1231: agents choose what to work on and how to reason; deterministic
services own admission, ordering, CAS, cancellation, drain, recovery and durable
evidence. A host adapter must not become a central cognitive dispatcher. Reuse
appropriate existing CrewSession and work-item services without creating another
work board, approval inbox, or general-purpose scheduler.

## Existing Foundations And Gaps

- [AgenticLoop](../../src/probos/cognitive/swe_harness/agentic_loop.py) owns a
  tool-call path and request/result IDs, but event emission is best effort.
  An observed producer event is not a pre-effect durable witness.
- [ToolExecutor](../../src/probos/tools/executor.py) and the
  [tool registry](../../src/probos/tools/registry.py) expose permission-aware
  invocation. Enumerate mesh, direct, MCP, shell, code-execution and delegated
  consumers before claiming complete coverage.
- [ExecutionAuditor](../../src/probos/execution/audit.py) deliberately permits
  durable-preferred recording. Keep that normal behavior; introduce a separately
  accepted strict profile if a persisted pre-dispatch record is mandatory.
- [CrewOrchestrator](../../src/probos/cognitive/crew_orchestrator.py) has admission
  and lifecycle generations. Closed AD-1127/#1046 is a reusable recovery foundation,
  not a shipped Supervised Worker host integration.

The earlier Copilot probes established genuine selected-agent identity and native
hook allow/deny enforcement. They did not establish a complete effective-hook
inventory or a protected authority issuer. Simply having ProbOS launch an opaque
Copilot CLI process would retain that limitation rather than solve it.

## Strong Contract

1. Admit against an immutable manifest of the real host instance, process,
   repository, session, selected source, effective enforcement components and
   generation. Reject missing, duplicated, stale or mismatched authority.
2. Keep the issuer, witness, policy and active installation inaccessible to the
   Worker/Doctor's granted tools. State and test the process/OS isolation boundary;
   same-user checksums alone do not protect against a malicious same-user process.
3. Persist attempt and intent identities before a covered effect can run. Retain
   rejected, failed and interrupted attempts in the denominator. Unknown outcome
   is an explicit state, not permission to replay.
4. Carry runtime-issued operation IDs through authorization, concurrent execution,
   results, retries and reconciliation. Model/provider IDs are supplementary;
   names, timing and matching parameters are not an identity mechanism.
5. Use scoped effect brokers and provider idempotency/reconciliation where possible.
   Exactly-once message delivery does not imply universal exactly-once external
   mutation. Opaque or ungoverned execution remains outside the strong profile.
6. Prepare and gate an immutable replacement; checkpoint and change generations
   at a verified boundary; confirm successor health and actual fresh-session resume.
   Failed health/history checks preserve or safely restore the prior installation.
   Do not invalidate in-flight authority before its final receipt is committed.
7. Preserve protected workflow acceptance, independent role-separated review,
   exact-tree tests, model-provenance limits, human work and append-only evidence.

Host facts, provider facts and externally sealed public-launch evidence remain
different authorities. A ProbOS witness cannot certify GitHub facts from an agent's
claim, nor serve as its own independent external evaluator. Existing local receipts
stay readable but cannot satisfy the strong profile. New protocol fields must
carry an explicit tested compatibility/migration path.

## Delivery Gates

AD-1315 first proves a positive/negative real-process admission crossing, including
a failing witness and a rejected pre-admission effect. AD-1316 proves concurrent
correlation and a bypass attempt across actual consumers. AD-1317 proves the full
failure/Doctor/repair/review/CI/activation/health/resume path with response-loss and
rollback injections before an operational campaign is admitted.

The strong operational test closes two pre-existing, bounded issues in a single
checkpoint-resumed campaign, with a declared recoverable incident and a novel
variant requiring Doctor reasoning. Require zero operator lifecycle intervention,
no replay of unknown mutations, dirty-work preservation, complete canonical
evidence and a verified final fresh-session resume. Report productive work and
supervision overhead separately; no model-quality or general-availability promise
follows from one successful campaign.

Every implementation slice requires focused and production-consumer tests,
different-family adversarial review, and a current canonical repository gate.
Do not spend repeated broad-gate cycles on an unproved host dependency. Preserve
all ordinary default behavior outside the explicitly accepted strict profile.

## Optional Editor Integration

The first strong harness is headless/native ProbOS. After it works, AD-1318 compares
supported VS Code session-provider APIs and Copilot-assisted options. VS Code may
be an interface to ProbOS as an alternative execution provider; Copilot may supply
reasoning or a delegated executor only if covered effects honor the same protocol.
Editor presentation and model access do not confer execution authority.

No VS Code internals patch, new LLM client, copied Copilot coding loop, replacement
runtime in the plugin, or UI dependency is part of the headless gates. The future
integration is optional and must not break the independent Copilot-local plugin.

## Allocation And Boundaries

The canonical `scripts/ad_ceiling.py` enumeration completed before allocation:
AD-1313 from GitHub issue titles in all states, AD-1304 from Git subjects, and
AD-1298 from prompt filenames. AD-1314 through AD-1318 were allocated sequentially.
All-state issue search found the narrower closed #1046, not an existing owner of
this program. The requested planning additions are not speculative defect filings.

All runtime implementation belongs in ProbOS OSS; portable plugin/protocol changes
belong in Supervised Worker. No commercial code, pricing, private strategy or live
production data crosses this boundary. This document does not activate any feature,
change the running system, or attest an implementation test result.