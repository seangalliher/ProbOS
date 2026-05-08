# Wave 129 — Review Pass-1 Summary

**Date:** 2026-05-08
**Reviewer:** ProbOS Architect (verify-first pass against HEAD)
**Tolerance applied:** Convention #15 (relaxed) — 1 ⚠️ permitted on the highest-risk prompt.

## Verdicts at a Glance

| # | Prompt | Verdict | Required | Recommended | Nits | Risk |
|---|---|---|---:|---:|---:|---|
| 1 | `ad-581-completion-v1.md` | ✅ | 0 | 2 | 2 | LOW |
| 2 | `bf-505-consultation-delivery-wiring-v1.md` | ✅ | 0 | 0 | 2 | LOW |
| 3 | `ad-490-eventlog-hash-chain-v1.md` | ✅ | 0 | 2 | 4 | MEDIUM-HIGH |
| 4 | `ad-700a-diagnostic-slash-command-v1.md` | ⚠️ | **1** | 2 | 3 | MEDIUM |
| 5 | `ad-700b-cognitive-journal-level-tagging-v1.md` | ✅ | 0 | 1 | 3 | LOW-MEDIUM |
| 6 | `ad-700c-diagnostician-tier-routing-v1.md` | ✅ | 0 | 2 | 2 | LOW-MEDIUM |
| 7 | `ad-633-finalize-wirer-v1.md` | ✅ | 0 | 1 | 3 | LOW |
| 8 | `ad-607-memory-security-write-path-v1.md` | ✅ | 0 | 2 | 4 | MEDIUM |
| 9 | `ad-491-gitagent-interop-adapter-v1.md` | ✅ | 0 | 1 | 5 | LOW |
| | **Totals** | **8 ✅ / 1 ⚠️** | **1** | **13** | **28** | |

Tolerance respected: 1 ⚠️, allocated to AD-700a per the Required finding (intent dispatch path unspecified).

## Highest-Risk Prompt

**`ad-700a-diagnostic-slash-command-v1.md`** — the only prompt with a Required finding. Risk source is *spec deferral*, not implementation complexity: D1 step 4 lists two candidate Captain-intent dispatch paths and tells the Builder to pick. This is a verify-first violation (architect responsibility). Without resolution, three concrete failure modes:

1. Builder picks the wrong path → DiagnosticianAgent never receives the intent → tests pass against a stub but ship behavior is broken.
2. Builder synthesizes a non-canonical path (e.g. `runtime.process_nl(f"diagnose level={level.value}")`) bypassing Captain dispatch / clearance / audit.
3. Test #2's "fake intent bus / runtime stub" papers over the real failure.

`ad-490-eventlog-hash-chain-v1` is structurally riskier (substrate write path + on-disk migration), but its prompt is well-grounded against `AuditLog` precedent and verifies every claim. AD-490's two Recommended findings are sharpenings, not gaps.

`ad-607-memory-security-write-path-v1` carries security-tier risk; both Recommended findings are addressable with a 5-line config tightening and an architect grep. Risk is real but contained by `enabled=False` opt-out and tier-2 log-and-degrade.

## Pass-1 → Revision Instructions for the Author

### Highest priority (must close before pass-2)

- **AD-700a Required #1**: Grep `experience/commands/commands_alert.py` (or any sibling slash command that issues an intent today). Pin the canonical Captain-intent dispatch path with file:line and exact kwargs. Update D1 step 4 with the concrete call. Drop the "Builder verifies" deferral.

### Convergent sharpenings (recommended; can be batched into one revision)

- **AD-490 Recommended #1**: Pin the `data_json` serialization contract — `json.dumps(payload, sort_keys=True, default=str)` — explicitly in the hash payload.
- **AD-490 Recommended #2**: Rephrase test #3 as a direct purity assertion on `_compute_row_hash`.
- **AD-700a Recommended #1**: Specify `monkeypatch` target as `probos.experience.commands.commands_diagnostic.cmd_diagnostic`.
- **AD-700a Recommended #2**: Cite the `self.COMMANDS` registry file:line.
- **AD-700b Recommended #1**: Inline the existing `journal.record(...)` call site (4 lines around `cognitive_agent.py:1660-1740`).
- **AD-700c Recommended #1**: Document the canonical `_decide_via_llm` return-dict shape and craft the L4/L5 short-circuit as a valid instance of it.
- **AD-700c Recommended #2**: Resolve the `tier_used` Non-Goals contradiction — strike or migrate.
- **AD-633 Recommended #1**: Add a Non-Goal pinning class-constant weights as deliberate (deferred to AD-633k).
- **AD-607 Recommended #1**: Tighten the `\bact\s+as\b` regex or document false-positive tradeoff.
- **AD-607 Recommended #2**: Cite the canonical `EpisodicMemory(...)` construction site.
- **AD-491 Recommended #1**: Grep `class CapabilityDescriptor` and confirm/correct the `.can` field reference.
- **AD-581 Recommended #1**: Confirm `OrderStatus.PENDING` existence at draft time.
- **AD-581 Recommended #2**: Read `work_item_router.py:162±30` and document the actual exception in D6.

### Cross-Prompt Concerns

1. **`startup/finalize.py` is touched by FOUR prompts**: AD-581 (`_wire_hybrid_dispatch`), BF-505 (`_wire_consultation_delivery`), AD-633 (`_wire_predictive_branching`), and the existing wirers. Build order matters: BF-505 → AD-581 → AD-633 to avoid merge conflicts. The wave-orchestrator's loadfile parallelism handles xdist isolation but Git merge ordering is sequential. Recommend an explicit "build serially in this order" hint in the wave dispatch.
2. **`config.py` is touched by FOUR prompts**: BF-505 (`ConsultationDeliveryConfig`), AD-633 (`PredictiveBranchingConfig`), AD-607 (`MemorySecurityConfig`), AD-581 (`HybridDispatchConfig` validators). Same merge-ordering concern. All four are additive (new classes + new SystemConfig fields) — Git's diff machinery should handle them as long as they target distinct line regions, but a `git pull --rebase` between commits is prudent.
3. **`cognitive_agent.py:_decide_via_llm`** is touched by AD-700b (D4 — journal record kwargs) and AD-700c (D2 — tier resolution + L4/L5 short-circuit). Both target the same ~80-line region. Build AD-700b first (it's purely additive — adds two record kwargs); AD-700c second (it modifies a line AD-700b doesn't touch). The two should compose cleanly. Recommend the wave-orchestrator pin AD-700b → AD-700c order.
4. **AD-700b ↔ AD-700c contradiction** about `tier_used` (see AD-700c Recommended #2). Resolve in revision pass.
5. **No prompt in this wave touches `runtime.py`**, `BaseAgent`, `IntentMessage`, or `RuntimeProtocol`. Good scope discipline overall.
6. **Phantom-API hazards observed in this pass**: AD-700a (intent dispatch path), AD-607 (cognitive-services init site), AD-491 (`CapabilityDescriptor.can`). All three are 30-second architect-grep fixes. Recurring pattern across the wave; surface to the wave-process retro.

## Wave Trajectory

**Wave 129 is on track for review pass-2 after one revision cycle.** Eight prompts are clean ✅ with only Recommended-tier sharpenings (no architectural rework). The single ⚠️ has one specific Required finding that resolves with a `git grep` and a one-line edit. No prompt requires deeper rework or scope re-framing. No phantom config classes. No method-shape phantom APIs. No transitional default-True flags. No scope-creep across ADs.

Builder readiness after revision: **HIGH**. Recommend a single revision pass (~author-15-min total across all 13 sharpenings + 1 Required), then pass-2 review (≤30 architect-min), then dispatch.

## Tracking

- Reviews stored at `prompts/Reviews/<stem>-review.md` for all 9 prompts.
- This summary: `prompts/Reviews/README-wave-129-pass-1.md`.
- No code, tests, `wave-plan.yaml`, `BUILDER-EXECUTION-PLAN.md`, or `DECISIONS.md` modified during this pass.
