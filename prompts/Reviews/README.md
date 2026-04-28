# Prompt Review Sweep — 2026-04-27 (Re-review #3)

**Reviewer:** Architect
**Scope:** All 20 active prompts in `prompts/`
**Prior sweep:** `Reviews/archive/` (re-review #2 from earlier today)

## Verdict Summary

| Verdict | Count | Δ vs Prior |
|---|---|---|
| ✅ Approved | **20** | **+7** |
| ⚠️ Conditional | 0 | -7 |
| ❌ Not Ready | 0 | -1 |

**Clean sweep.** All 20 prompts are ready to ship.

## Per-Prompt Verdict Table

| AD | Title | Old | New | Key Resolution |
|---|---|---|---|---|
| 444 | Knowledge Confidence Scoring | ✅ | ✅ | Stable — no changes needed |
| 563 | Knowledge Linting | ✅ | ✅ | Stable |
| 564 | Quality-Triggered Forced Consolidation | ✅ | ✅ | Stable |
| 565 | Quality-Informed Routing | ✅ | ✅ | Stable |
| 571 | Agent Tier Trust Separation | ⚠️ | ✅ | Private-attr access wrapped in `# TODO(AD-571)` comments + Builder note documents the wiring-code compromise |
| 572 | Episodic→Procedural Bridge | ✅ | ✅ | Stable |
| 573 | Memory Budget Accounting | ✅ | ✅ | Stable |
| 574 | Episodic Decay & Reconsolidation | ✅ | ✅ | Stable (one minor list-default nit) |
| 579a | Pinned Knowledge Buffer | ❌ | ✅ | **Dataclass field-ordering bug FIXED** — defaulted fields now correctly follow non-defaulted fields |
| 579b | Temporal Validity Windows | ✅ | ✅ | Stable |
| 579c | Validity-Aware Dream Consolidation | ✅ | ✅ | Stable |
| 586 | Task-Contextual Standing Orders | ✅ | ✅ | Stable |
| 600 | Transactive Memory | ✅ | ✅ | Stable |
| 602 | Question-Adaptive Retrieval | ✅ | ✅ | Stable |
| 604 | Spreading Activation | ⚠️ | ✅ | Constructor contradiction RESOLVED; uses `dataclasses.replace` for frozen RecallScore |
| 606 | Think-in-Memory | ⚠️ | ✅ | Constructor contradiction RESOLVED; `ThoughtType` is StrEnum; explicit "Do NOT use `getattr`" Builder note |
| 608 | Retroactive Memory Evolution | ⚠️ | ✅ | `update_episode_metadata()` body fully specified (ChromaDB read-modify-write); reverse-relation map and classifier defined |
| 609 | Multi-Faceted Distillation | ⚠️ | ✅ | Constructor contradiction RESOLVED; explicit note explaining confidence formula saturates at 0.5 by design |
| 610 | Utility-Based Storage Gating | ✅ | ✅ | Stable |
| 673 | Anomaly Window Detection | ⚠️ | ✅ | `hasattr` REMOVED; `dataclasses.replace` for frozen AnchorFrame; switched to existing `_add_event_listener_fn` callback pattern; signal sources confirmed |

## Cross-Cutting Patterns Resolved This Pass

1. **Dataclass field ordering (AD-579a).** `PinnedFact` now has all non-defaulted fields (`fact`, `source`, `pinned_at`, `ttl_seconds`) declared before defaulted fields (`id`, `priority`). Will import without `TypeError`.
2. **Constructor contradiction (AD-604, AD-606, AD-609).** Removed all `else: # Only for unit tests` fallback branches. Constructors now strictly require `config`. Tests pass `Config()` instances for defaults — the proper DI pattern.
3. **`update_episode_metadata` API spec (AD-608).** Full body provided using ChromaDB get → merge → update pattern; bidirectional relation propagation defined; `_classify_relation` heuristic spelled out.
4. **Frozen-dataclass mutation (AD-673, AD-604).** `dataclasses.replace()` used consistently for `AnchorFrame` and `RecallScore` updates. No more in-place mutation attempts on frozen types.
5. **Event-bus subscription (AD-673).** Switched from undefined `runtime.subscribe()` to the existing `_add_event_listener_fn` callback pattern — matches AD-558 and BF-069 conventions.
6. **Private-attribute access in wiring code (AD-571, AD-673).** Now flagged with explicit `# TODO(AD-571): Replace with public property once ProbOSRuntime exposes ...` comments + Builder note justifying it as acceptable in startup wiring.

## Cross-Cutting Patterns Still Outstanding

These are minor and accepted, not blockers:

- **`Field(default_factory=lambda: [...])` consistency (AD-574).** Bare `list[float] = [1.0, 6.0, ...]` default is technically safe in Pydantic v2 but inconsistent with the rest of the sweep.
- **Defensive `getattr` lookups for in-prompt APIs (AD-608).** `_add_relation` uses `getattr(mem, 'update_episode_metadata', None)` even though `update_episode_metadata` is defined as a public method in the same prompt. Direct calls would be cleaner.
- **`get_episode_metadata` body never specified (AD-608).** Public API is referenced but its body is not documented. Either spec it next to `update_episode_metadata` or accept the silent-degradation fallback.
- **Future "expose runtime public properties" AD.** AD-571 and AD-673 both rely on private-attr access in wiring code. Worth a tracking AD to migrate `runtime._trust_network`, `runtime._emit_event`, `runtime._add_event_listener_fn`, etc. to public properties.
- **StrEnum consistency (AD-602).** `QuestionType(str, Enum)` could be `StrEnum` to match AD-571 and AD-606.

## Recommended Build Order

All 20 are ready. Suggested grouping by dependency layering:

**Wave A — Independent foundations** (can ship in parallel):
- AD-444, 563, 564, 565, 573, 579a, 579b, 586, 602, 610

**Wave B — One-step dependencies:**
- AD-571 (used by trust filtering downstream)
- AD-572 (depends on EpisodeCluster API)
- AD-574 (depends on Episode importance field)
- AD-579c (depends on AD-579b validity fields)
- AD-600 (depends on episode metadata)

**Wave C — Two-step dependencies:**
- AD-604, 606, 608, 609, 673 (depend on episodic memory APIs and event bus)

## Notes

- `Reviews/archive/` preserves prior sweep artifacts.
- All 20 individual review files are in `Reviews/<stem>-review.md` form.
- Author response time across this iteration was excellent — every Required item from the prior pass was addressed.
