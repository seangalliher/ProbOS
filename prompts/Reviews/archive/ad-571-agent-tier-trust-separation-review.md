# Review: AD-571 Agent Tier Trust Separation (Re-review #2)

**Prompt:** prompts/ad-571-agent-tier-trust-separation.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ⚠️ Conditional

## Improvements Since Prior Review
- StrEnum `AgentTier` with three explicit members.
- `Field(default_factory=lambda: [...])` for both crew_types and core_types lists.
- Late-bind setter pattern (`set_tier_registry`) on TrustNetwork, EmergenceMetricsEngine, HebbianRouter — clean wiring.
- Backward-compatible `crew_only=False` defaults on all filter methods.
- Private-attribute access in `_populate_agent_tiers` is now flagged with explicit `# TODO(AD-571): Replace with public property` comments and an "acceptable here because this is wiring code" justification in the Builder note. This is the right way to ship a pragmatic compromise.

## Required
None.

## Recommended
- The TODO comments name the future migration but don't have an AD number assigned. Consider opening a tracking AD for "expose runtime.trust_network / .router / .emergence_metrics_engine as public properties" so the cleanup isn't lost.

## Nits
- Test 15's assertion `tn.outcomes_for(core_id) == []` requires verifying that `outcomes_for()` exists on TrustNetwork — add a Verify step.

## Recommendation
Ship it.
