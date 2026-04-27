# Prompt Reviews

Architect reviews of prompts in `prompts/`. One file per prompt, named `<prompt-stem>-review.md`.

## Sweep — 2026-04-27

13 prompts reviewed. Verdicts:

| Prompt | Verdict | Blockers |
|--------|---------|----------|
| [ad-585-tiered-knowledge-loading](ad-585-tiered-knowledge-loading-review.md) | ✅ Approved | Fixed: wiring added, SEARCH/REPLACE throughout, typed event, CancelledError handling |
| [ad-594-crew-consultation-protocol](ad-594-crew-consultation-protocol-review.md) | ✅ Approved | Fixed: handler exception emits CONSULTATION_FAILED, urgency documented as metadata, rate tracker eviction, typed config, CancelledError guard, Do Not Build, typed event dataclasses |
| [ad-603-anchor-recall-composite-scoring](ad-603-anchor-recall-composite-scoring-review.md) | ✅ Approved | None (minor type-alias polish) |
| [ad-651-standing-order-decomposition](ad-651-standing-order-decomposition-review.md) | ✅ Approved | None — **model prompt** |
| ad-663-provenance-producer-wiring | _completed prior session_ | n/a — see [status note](ad-663-and-ad-665-status-note.md) |
| ad-665-corroboration-source-validation | _completed prior session_ | n/a — see [status note](ad-663-and-ad-665-status-note.md) |
| [ad-666-agent-sensorium-formalization](ad-666-agent-sensorium-formalization-review.md) | ✅ Approved | Fixed: typed config via SystemConfig.sensorium, SEARCH/REPLACE anchors, ClassVar note, typed event dataclass, acceptance criteria |
| [ad-667-named-working-memory-buffers](ad-667-named-working-memory-buffers-review.md) | ✅ Approved | None (minor polish) |
| [ad-668-salience-filter](ad-668-salience-filter-review.md) | ✅ Approved | None (typed context recommended) |
| [ad-669-cross-thread-conclusion-sharing](ad-669-cross-thread-conclusion-sharing-review.md) | ✅ Approved | None (SEARCH/REPLACE anchoring recommended) |
| [ad-670-working-memory-metabolism](ad-670-working-memory-metabolism-review.md) | ✅ Approved | None (scheduler wiring must be specified) |
| [ad-671-dream-working-memory-integration](ad-671-dream-working-memory-integration-review.md) | ✅ Approved | None (SEARCH/REPLACE anchoring recommended) |
| [ad-672-agent-concurrency-management](ad-672-agent-concurrency-management-review.md) | ✅ Approved | Fixed: Field(default_factory), queue overflow documented, capacity warning debounced (30s cooldown), cancelled future handling, typed event dataclass, Do Not Build, acceptance criteria |
| [bf-240-llm-health-dwell-criterion](bf-240-llm-health-dwell-criterion-review.md) | ✅ Approved | None — final pass |

## Cross-Cutting Patterns

These issues recurred across multiple prompts. Consider codifying them in `prompts/review-criteria.md`:

1. **Mutable dict/list defaults in Pydantic configs.** Always use `Field(default_factory=...)`. Recurs in: AD-585, AD-651, AD-672. Pydantic v2 will error or silently share state across instances.
2. **`getattr(config, "section", default)` instead of typed config.** Add the section to `SystemConfig` as a typed field and access via `runtime.config.section`. Recurs in: AD-594, AD-666, AD-670.
3. **Silent exception swallows.** `except Exception: pass` violates Fail Fast. Always log-and-degrade with context (what, why, what-next). Recurs in: AD-585, AD-594.
4. **Line-number hints instead of SEARCH/REPLACE blocks.** Files like `cognitive_agent.py` (5000+ lines) change constantly. Anchor on real text. Recurs in: AD-585, AD-666, AD-667, AD-669, AD-671.
5. **Missing "Do not build" constraints.** Architect prompt-drafting rule requires naming adjacent tempting features and forbidding them. Most prompts lack this. AD-651 is the model.
6. **Missing acceptance criteria line for Engineering Principles compliance.** Required line per `.github/copilot-instructions.md`: *"Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."* Most prompts omit this.
7. **Missing tracker sections.** PROGRESS.md / docs/development/roadmap.md / DECISIONS.md update directives. AD-651 and AD-603 do this well; others vary.
8. **Untyped event payloads.** New EventTypes added without corresponding typed dataclasses. The pattern at `events.py:544` (`CounselorAssessment`) should be the standard.

## Bright Spots

- **AD-651** — gold standard for tracker section, scope discipline, DO NOT block, and opt-in default rollout.
- **AD-668, AD-670, AD-671** — exemplary dependency discipline (acknowledge unimplemented dependency ADs, design to work standalone with forward-compat notes).
- **AD-603** — small, focused, well-anchored Find/Replace blocks; explicit DRY-duplication justification.

## Recommended Next Actions

1. ~~Block AD-585 until loader-wiring section is added.~~ **Done** — wiring added in finalize.py.
2. ~~Fix AD-672 mutable dict default and queue-overflow semantics before builder pickup.~~ **Done** — Field(default_factory), overflow documented, debounce added.
3. ~~Address AD-594 silent exception and rate tracker leak.~~ **Done** — CONSULTATION_FAILED event, eviction, typed config.
4. ~~Sweep all conditional/approved prompts for the mutable-dict and `getattr`-config patterns.~~ **Done** — all three conditional prompts fixed.
5. Move AD-663 and AD-665 prompts to `prompts/archive/` to clean the active backlog.

## Build Order

All 13 prompts are now approved. Recommended execution order:

1. **BF-240** (standalone bug fix, no dependencies)
2. **AD-585** (standalone, unlocks knowledge loading)
3. **AD-603** (standalone scoring)
4. **AD-651** (standalone standing orders)
5. **AD-666** (prerequisite for AD-667-672 wave)
6. **AD-667** → **AD-668** → **AD-669** → **AD-670** → **AD-671** (Ambient Awareness wave, sequential)
7. **AD-672** (concurrency, can run parallel with Ambient Awareness wave)
8. **AD-594** (consultation protocol, independent)
