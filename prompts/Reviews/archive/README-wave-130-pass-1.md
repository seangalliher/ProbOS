# Wave 130 — Pass-1 Review Summary

**Date:** 2026-05-08
**Reviewer:** Architect
**Tolerance:** Convention #15 (relaxed) — 1 ⚠️ allowed on highest-risk prompt; >1 triggers revision cycle.

## Per-prompt verdicts

| # | Prompt | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| 1 | `ad-701-visiting-officers-v1` | ✅ Approved | 0 | 2 | 3 |
| 2 | `ad-702-diplomatic-relations-v1` | ⚠️ Conditional | 3 | 4 | 2 |
| 3 | `ad-707-workflow-cron-trigger-v1` | ⚠️ Conditional | 2 | 4 | 2 |
| 4 | `memvid-queryplanner-relational-v1` | ✅ Approved | 0 | 4 | 2 |
| 5 | `better-agents-behavior-contract-v1` | ✅ Approved | 0 | 4 | 3 |
| 6 | `claude-bootstrap-init-defaults-v1` | ✅ Approved | 0 | 4 | 3 |
| 7 | `research-ragflow-context-layer-v1` | ✅ Approved | 0 | 4 | 2 |
| 8 | `research-opencode-magic-context-v1` | ✅ Approved | 0 | 4 | 3 |
| 9 | `research-locomo-benchmark-v1` | ⚠️ Conditional | 1 | 4 | 2 |
| 10 | `research-warm-boot-fragmentation-design-v1` | ⚠️ Conditional | 1 | 4 | 3 |

**Tally:** 6 ✅ / 4 ⚠️ / 0 ❌

Tolerance budget exceeds by 3 conditional prompts. However, the four ⚠️ verdicts collectively contain only **7 Required findings**, and 5 of those 7 are one-line literal-text fixes (phantom method name, wrong store signature, hardcoded AD number). Total revision surface is small.

## Highest-risk prompt + recommended revision

**AD-702 (Diplomatic Relations)** is the wave's highest-risk prompt as predicted. Three Required findings:

1. **`max_hops` parameter is ignored by the implementation.** Test #5 explicitly tests `max_hops=1` semantics that the body never reads. Either (a) gate the auto-bridge loop on `if max_hops < 2: return None` or (b) drop test #5 and document `max_hops` as reserved-for-AD-702b. Pick one.
2. **Add the dispatch-required Protocol-widening fan-out check.** Verified count today: **0 mock sites for `TrustNetworkProtocol`** — widening is safe — but the prompt must record that finding and the conditional rule ("if >5 mock sites at build time, accept `Any` instead").
3. **D2 sequencing is ambiguous.** Show the merged code block (transitive_score with both `safety_critical` and `intent_descriptor` checks in place) so the Builder doesn't double-return.

If those three are fixed, AD-702 promotes to ✅ on pass-2. The other Recommended items (DRY of bridge-loop into a helper, line-number drift cleanup) can ride along.

## Cross-prompt concerns

### Shared file regions — merge-ordering risk

| File | Touched by | Conflict tier |
|---|---|---|
| `src/probos/config.py` | AD-701, AD-702 (none — no config), AD-707, Memvid-QP, claude-bootstrap | **HIGH** — 4 prompts add new Pydantic config classes; if landed in parallel, register-block edits collide. **Land in dependency order: claude-bootstrap → AD-701 → AD-707 → Memvid-QP** (alphabetical-by-section is fine; just serialize the file edits). |
| `src/probos/startup/finalize.py` | AD-701, AD-707 | **MEDIUM** — both insert wiring blocks. AD-701 says "after identity-registry start, before MCPBridge"; AD-707 says "after `register_workflow_cache`". Different anchors, low collision risk. Build AD-701 first (substrate), AD-707 second (cognitive). |
| `src/probos/__main__.py` | better-agents (`qa run-contracts` subparser), claude-bootstrap (`--security-profile` flag on `init`) | **LOW** — disjoint subparsers. Either order works. |
| `src/probos/cognitive/episodic.py` | Memvid-QP (uses; no edit), locomo (uses; no edit) | **LOW** — both are read-only consumers. |
| `DECISIONS.md` | warm-boot (appends entry) | **N/A** — single writer; just verify highest AD number first. |

### Convention #20 violation across the wave

**All 10 prompts omit the working-tree integrity reminder** (run `git diff --numstat | sort -k2nr | head -5` before reading source). The dispatch document mentions it once at WAVE-130-DISPATCH.md:24, but no individual prompt echoes it. Dispatch report claimed "at least 3 prompts of the 10 explicitly remind the Builder" — that claim is **incorrect**. Add the reminder to all 10 prompts in revision pass, or accept that the dispatch-level reminder is sufficient and update the dispatch report's claim.

### AD-numbering discipline

- **Warm-boot prompt hardcodes AD-713** in 5+ places while also instructing the Builder to verify the highest AD number. Resolve one way or the other.
- AD-701 forward-markers (AD-701b/c/d), AD-702 forward-markers (AD-702b/c), AD-707 forward-markers (AD-707b/c/d), better-agents (AD-708-1/2/3), claude-bootstrap (AD-712, AD-709-1/2), Memvid-QP (memvid-versionrelation-v1, memvid-engineversion-v1) — all use letter-suffixes consistently. No collisions in v1 names.

### Default-True flag audit

Only `research-warm-boot-fragmentation-design-v1.md` has `enabled: true`, and the prompt explicitly justifies it as a safety mechanism. All other 9 prompts default `enabled=False`. Convention #14 honored — but warm-boot prompt should make the exception more prominent.

### Phantom-API spot-checks

| Prompt | Cited symbol | At HEAD | Status |
|---|---|---|---|
| AD-702 | `TrustNetwork`, `TrustRecord`, `_records`, `_event_log`, `set_department_lookup` | All present | ✅ symbols correct, line numbers drift 15–37 lines |
| AD-707 | `WorkflowCache.store/lookup/_normalize` | All present | ✅ line drift 1–4 lines |
| AD-707 | `runtime.process_nl` | **MISSING** — actual is `process_natural_language` (`runtime.py:2533`) | ❌ phantom — Required finding |
| Memvid-QP | `recall_by_anchor` (`episodic.py:2747`) | Present | ✅ line correct |
| AD-701 | `AgentIdentityRegistry` (`identity.py:403`), `WardRoomService` (`ward_room/service.py:29`), `issue_birth_certificate` (`identity.py:707`) | All present | ✅ all lines correct |
| LoCoMo | `EpisodicMemory.store(user_input=..., dag_summary=..., outcomes=...)` | **MISSING** — actual is `store(self, episode: Episode)` (`episodic.py:1056`) | ❌ phantom — Required finding |

Two genuine phantom APIs in the wave. Both have verify-first caveats inline, but the example code is wrong and Builder will copy-paste. Both fixable with a one-line spec edit.

## Wave readiness

**Wave 130 is on track for review pass-2 after one revision cycle.** Deeper rework is not needed.

Specifically:
- AD-701, Memvid-QP, better-agents, claude-bootstrap, ragflow, opencode-magic-context — ship as-is or with the recommended Convention #20 reminder bolted on.
- AD-702, AD-707, LoCoMo, warm-boot — apply the Required fixes (7 total, all small) and re-submit for pass-2.

If the 4 ⚠️ prompts return clean on pass-2, the wave can proceed to Builder dispatch. The merge-ordering rule (config.py serialization: claude-bootstrap → AD-701 → AD-707 → Memvid-QP) should be added to the WAVE-130-DISPATCH.md as a build-order constraint before dispatch.

## Per-review file map

- [ad-701-visiting-officers-v1-review.md](ad-701-visiting-officers-v1-review.md)
- [ad-702-diplomatic-relations-v1-review.md](ad-702-diplomatic-relations-v1-review.md)
- [ad-707-workflow-cron-trigger-v1-review.md](ad-707-workflow-cron-trigger-v1-review.md)
- [memvid-queryplanner-relational-v1-review.md](memvid-queryplanner-relational-v1-review.md)
- [better-agents-behavior-contract-v1-review.md](better-agents-behavior-contract-v1-review.md)
- [claude-bootstrap-init-defaults-v1-review.md](claude-bootstrap-init-defaults-v1-review.md)
- [research-ragflow-context-layer-v1-review.md](research-ragflow-context-layer-v1-review.md)
- [research-opencode-magic-context-v1-review.md](research-opencode-magic-context-v1-review.md)
- [research-locomo-benchmark-v1-review.md](research-locomo-benchmark-v1-review.md)
- [research-warm-boot-fragmentation-design-v1-review.md](research-warm-boot-fragmentation-design-v1-review.md)
