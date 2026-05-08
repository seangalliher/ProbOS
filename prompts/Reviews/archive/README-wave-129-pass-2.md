# Wave 129 — Review Pass-2 Summary

**Date:** 2026-05-08
**Reviewer:** ProbOS Architect (post-revision verify-first pass against HEAD)
**Tolerance applied:** Convention #15 (relaxed) — 1 ⚠️ permitted on the highest-risk prompt. **Used: 0.**

## Verdicts at a Glance

| # | Prompt | Pass-1 | Pass-2 | Required | Recommended | Δ |
|---|---|---|---|---:|---:|---|
| 1 | `ad-581-completion-v1.md` | ✅ | ✅ | 0 | 0 | All revisions landed; `OrderState`/`OrderStatus` phantom scrubbed |
| 2 | `bf-505-consultation-delivery-wiring-v1.md` | ✅ | ✅ | 0 | 0 | No revision; pass-1 carried forward |
| 3 | `ad-490-eventlog-hash-chain-v1.md` | ✅ | ✅ | 0 | 0 | `sort_keys=True` determinism contract pinned |
| 4 | `ad-700a-diagnostic-slash-command-v1.md` | ⚠️ | ✅ | 0 | 0 | Required closed; scout-precedent dispatch pinned |
| 5 | `ad-700b-cognitive-journal-level-tagging-v1.md` | ✅ | ✅ | 0 | 0 | Line range corrected to `1722-1748` |
| 6 | `ad-700c-diagnostician-tier-routing-v1.md` | ✅ | ✅ | 0 | 0 | Dead `tier_used` Non-Goals line struck |
| 7 | `ad-633-finalize-wirer-v1.md` | ✅ | ✅ | 0 | 0 | HEBBIAN_WEIGHT frozen-baseline Non-Goal added |
| 8 | `ad-607-memory-security-write-path-v1.md` | ✅ | ✅ | 0 | 0 | Init site pinned to `__main__.py:316`; FP tradeoff documented |
| 9 | `ad-491-gitagent-interop-adapter-v1.md` | ✅ | ✅ | 0 | 0 | `CapabilityDescriptor.can` confirmed |
| | **Totals** | 8 ✅ / 1 ⚠️ | **9 ✅ / 0 ⚠️** | **0** | **0** | Tolerance budget unused |

## Wave Verdict

**APPROVED for Builder dispatch (gate_1).** All 9 prompts converged to ✅ in one revision cycle. Zero Required, zero Recommended, zero Nits flagged on pass-2. The single ⚠️ on AD-700a (Pass-1 Required: dispatch path unspecified) closed cleanly with the scout precedent at `commands_knowledge.py:130-148`.

No third revision cycle required.

## Phantom-API Sweep Results (Pass-2 Addition)

The Wave-10 `DutyConfig`/`DutyScheduleConfig` and Wave-129 `OrderStatus`/`OrderState` patterns were the trigger for this sweep. Searched every other prompt for class/enum members and verified each against HEAD.

| Prompt | Reference | Verified Live Symbol | Status |
|---|---|---|---|
| AD-581 | `OrderState`, `OrderStatus` (warning only) | `cognitive/orders.py:28` | ✅ Correctly named; OrderStatus is the warning, not the directive |
| AD-700a | `DiagnosticLevel`, `parse_level` (module-level) | `agents/medical/diagnostic_levels.py:28,69` | ✅ Module-level helper, not enum method |
| AD-700a | `medical_diagnostician` pool name | `startup/fleet_organization.py:66` | ✅ |
| AD-700b | `CognitiveJournal._SCHEMA_BASE`, `record()` kwargs | `cognitive/journal.py:21-48,328-360` | ✅ |
| AD-700b | `cognitive_agent.py:1722-1748` journal block | Inlined; matches HEAD exactly | ✅ |
| AD-700c | `LLMRequest.tier`, `_resolve_tier()`, `_decide_via_llm` | `types.py:227`, `cognitive_agent.py:1701,6055-6060` | ✅ |
| AD-700c | `_decide_via_llm` return shape `{action, llm_output, tier_used}` | `cognitive_agent.py:1716-1720` | ✅ |
| AD-633 | `PredictionEngine`, `SpeculationCache`, `SpeculationBudget`, `SpeculationExecutor`, `AccuracyTracker`, `NoOpIdleSpeculationPolicy`, `NoOpPreplayHook` | `predictive_branching/__init__.py:7-30` | ✅ |
| AD-633 | `HEBBIAN_WEIGHT`, `THREAD_ACTIVITY_WEIGHT` (class constants) | `predictive_branching/engine.py:94-95,192-193` | ✅ |
| AD-633 | `cfg.cheap_tier_min_confidence` (engine read) | `predictive_branching/engine.py:219` | ✅ |
| AD-490 | `AuditLog.GENESIS_HASH`, `verify_chain()` | `security/audit.py:65,120` | ✅ |
| AD-607 | `Episode.user_input`, `agent_ids` | `types.py:411` | ✅ |
| AD-607 | `EpisodicMemory.store()` | `cognitive/episodic.py:942` | ✅ |
| AD-491 | `CapabilityDescriptor.can: str` | `types.py:26-32` | ✅ |
| AD-491 | `BaseAgent`, `agent.sovereign_id`, `agent.did` (AD-441) | `substrate/agent.py:18`, `decisions-era-4-evolution.md:1003` | ✅ |
| BF-505 | `LocalFileAdapter.name="local_file"`, `GitHubAdapter.name="github"`, `DeliveryPipeline` | `consultation/delivery.py:338,346,455,464,584` | ✅ |

**Result: zero phantom-API confusions found across the wave.** AD-581's `OrderStatus`→`OrderState` correction was the only live defect of this class in Wave 129; it was caught and scrubbed in the revision pass. No other prompt carries an analogous defect.

The Wave-10 forcing function (extend `phantom-api-precheck.ps1` to parse method calls + kwargs against AST signatures) remains a Wave-130 candidate — this manual sweep took ~5 architect-min and confirms the pattern's recurrence is being controlled at the review gate.

## Recommended Builder Order

Three of the 9 prompts touch `startup/finalize.py`; four touch `config.py`. Sequential merge ordering is required to avoid Git merge conflicts despite each prompt's section being additive in isolation. AD-700b and AD-700c both touch `cognitive_agent.py:1700-1750` and must serialize.

### Build Group A — finalize.py + config.py (serial; same file region)

| Order | Prompt | finalize.py? | config.py? | Notes |
|---|---|---|---|---|
| 1 | **BF-505** | + `_wire_consultation_delivery` (after `_wire_consultation_workspaces`) | + `ConsultationDeliveryConfig` | Smallest scope — restores 2 symbols, closes 3 tests. Lowest blast radius; ship first. |
| 2 | **AD-581-completion** | + `_wire_hybrid_dispatch` (after ontology, before bridge alerts) | + `HybridDispatchConfig` validators + SystemConfig field | 9 failing tests close. Additive everywhere. |
| 3 | **AD-633** | + `_wire_predictive_branching` (after `_wire_task_context`) | + `PredictiveBranchingConfig` adjacent to `AnomalyWindowConfig` | 2 new tests. Default-disabled; zero runtime impact unless flipped. |

After group A: full gate `pytest tests/ -q -n 16 --dist=loadfile` should be green or only environmental flakes.

### Build Group B — independent (parallelizable via wave-orchestrator loadfile)

| Prompt | Files | Notes |
|---|---|---|
| **AD-490** | `substrate/event_log.py` + new test file | Substrate-only; on-disk migration; D4 step 0 has the in-scope `sort_keys=True` fix on the existing `data_json` line. |
| **AD-491** | new `interop/__init__.py` + `interop/gitagent.py` + new test file | Greenfield package; zero edits to existing code. Lowest risk in the wave. |
| **AD-607** | `cognitive/episodic.py` + `__main__.py:316` + `config.py` (`MemorySecurityConfig`) | Highest-risk prompt (security tier); touches episode write path. `config.py` edit is additive (new class + new SystemConfig field) — should not conflict with group A's config.py edits if applied via `git pull --rebase` between commits. |

### Build Group C — cognitive_agent.py (serial; same ~80-line region)

| Order | Prompt | Region | Notes |
|---|---|---|---|
| 4 | **AD-700b** | `cognitive_agent.py:1722-1748` (journal `record()` block) | Pure-additive: appends `level=` and `level_rank=` kwargs. Reorders nothing. |
| 5 | **AD-700c** | `cognitive_agent.py:1701` (LLMRequest `tier=`) + new helper + short-circuit guard | Replaces the `tier=` kwarg call; adds the L4/L5 short-circuit `return` above the `LLMRequest` construction. AD-700b's region (1722-1748) is below the short-circuit `return`, so AD-700c bypasses AD-700b's block on L4/L5 paths — by design. The two compose cleanly when AD-700b lands first. |

### Build Group D — independent (last)

| Prompt | Files | Notes |
|---|---|---|
| **AD-700a** | `experience/shell.py` + `experience/panels.py` + new `commands_diagnostic.py` + new test file | Depends on AD-700 substrate (already shipped). Independent of AD-700b/c — they touch CognitiveAgent internals; AD-700a is the HXI surface. Can ship anytime after AD-700b/c (no compile-time dep, but sequencing avoids a potential mid-air collision in `cognitive_agent.py` if a Builder ever needs to fall back). |

### Suggested Wave Dispatch Sequence

```
Stage 1: BF-505                              (finalize + config)
Stage 2: AD-581-completion                   (finalize + config)
Stage 3: AD-633                              (finalize + config)
Stage 4: AD-607                              (config + episodic + __main__)
Stage 5: AD-490                              (substrate, parallel-safe)
Stage 6: AD-491                              (greenfield, parallel-safe)
Stage 7: AD-700b                             (cognitive_agent journal)
Stage 8: AD-700c                             (cognitive_agent tier routing)
Stage 9: AD-700a                             (HXI shell surface)
```

Stages 5 and 6 can be issued in parallel (different files, both isolated). All other stages serialize on shared file regions.

Hard-stop conditions per `prompts/BUILDER-EXECUTION-PLAN.md` apply unchanged.

## Cross-Prompt Concerns Status (from Pass-1)

1. ~~**`startup/finalize.py` touched by FOUR prompts**~~ — Confirmed: BF-505, AD-581, AD-633 (AD-607 wires from `__main__.py`, not finalize). Build order resolved above.
2. ~~**`config.py` touched by FOUR prompts**~~ — Confirmed: BF-505, AD-581, AD-633, AD-607. Each adds a distinct config class; line regions are far apart. `git pull --rebase` between commits as prudent.
3. ~~**`cognitive_agent.py:_decide_via_llm` touched by AD-700b and AD-700c**~~ — Confirmed and resolved: AD-700b first (additive at `:1722-1748`), AD-700c second (modifies `:1701` + adds short-circuit above). Composition validated.
4. ~~**AD-700b ↔ AD-700c contradiction about `tier_used`**~~ — Resolved in revision: AD-700c struck the dead Non-Goals line. AD-700b adds `level`/`level_rank` (not `tier_used`); the journal already has a `tier` column from AD-431.
5. **No prompt touches `runtime.py`, `BaseAgent`, `IntentMessage`, or `RuntimeProtocol`** — Confirmed across all 9 prompts.
6. **Phantom-API hazards from Pass-1**: AD-700a (intent dispatch path) → fixed; AD-607 (`EpisodicMemory(...)` site) → fixed; AD-491 (`CapabilityDescriptor.can`) → fixed. All three closed in revision.

## Wave Trajectory

**Wave 129 ships clean after one revision cycle.** Eight prompts converged with no Required findings; the single ⚠️ closed with a one-line dispatch-path pin. Phantom-API sweep found zero residual confusions.

Builder readiness: **HIGH**. Recommend dispatch via `scripts/wave-orchestrator.ps1` per `prompts/BUILDER-EXECUTION-PLAN.md` with the sequencing above.

## Tracking

- Pass-2 reviews stored at `prompts/Reviews/<stem>-review.md` for all 9 prompts (each with a `## Pass 2 Review (2026-05-08)` section appended).
- This summary: `prompts/Reviews/README-wave-129-pass-2.md`.
- No code, tests, `wave-plan.yaml`, `BUILDER-EXECUTION-PLAN.md`, or `DECISIONS.md` modified during this pass.
