# Review: AD-602 Question-Adaptive Retrieval (Re-review #2)

**Prompt:** prompts/ad-602-question-adaptive-retrieval.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ✅ Approved

## Status
Stable. `Field(default_factory=dict)` for strategy_overrides with explicit Builder note. Pure keyword classification — no LLM. Four QuestionTypes, four default strategies, with config-driven per-type overrides. Lazy init in CognitiveAgent.

## Required
None.

## Recommended
- Classification is mutually-exclusive in priority order (TEMPORAL > CAUSAL > SOCIAL > FACTUAL). A query like "Why did this happen yesterday?" classifies as TEMPORAL, missing the CAUSAL signal. Document this explicitly so future tuning doesn't break expectations.

## Nits
- `QuestionType` is `class QuestionType(str, Enum)` — could be `StrEnum` for Python 3.11+ consistency with AD-571 and AD-606. Minor stylistic.

## Recommendation
Ship it.
