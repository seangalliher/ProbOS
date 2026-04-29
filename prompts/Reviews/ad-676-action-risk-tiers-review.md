# Review: AD-676 — Action Risk Tiers

**Verdict:** ✅ Approved
**Headline:** All dependencies verified; ready for builder.

## Required

None.

## Recommended

1. **Avoid mutating module-level `TIER_POLICIES` dict.** Section 4 modifies it during wiring; safer to construct fresh `RiskPolicy` instances, preventing race conditions if wiring becomes re-entrant.
2. **Startup ordering.** Confirm `ActionRiskRegistry._register_defaults()` runs to completion before any policy override is applied.

## Nits

- 10 tests covering enum / classification / authorization / overrides — well-scoped.
- `governance/` is a new cross-cutting module — confirm it's also referenced by AD-445 (DecisionQueue) so directory creation is shared.

## Verified

- `Rank` enum at [earned_agency.py:9](src/probos/earned_agency.py#L9) (imported from `probos.crew_profile`); ENSIGN/LIEUTENANT/COMMANDER/SENIOR ordinals (0–3) confirmed.
- `ClearanceGrant` dataclass at [earned_agency.py:38](src/probos/earned_agency.py#L38).
- `EarnedAgencyConfig` at [config.py:1099](src/probos/config.py#L1099).
- `EventType.TOOL_PERMISSION_DENIED` at [events.py:165](src/probos/events.py#L165) — `ACTION_RISK_DENIED` insertion confirmed.
- `ActionType` at [initiative.py:24](src/probos/initiative.py#L24): DIAGNOSE / SCALE / RECYCLE / PATCH / ALERT_CAPTAIN.
- `_ACTION_TIERS` map at [earned_agency.py:189-195](src/probos/earned_agency.py#L189) aligned with proposed risk tiers.
- `ToolPermission` enum at [tools/protocol.py:29](src/probos/tools/protocol.py#L29).
- `governance/` does not exist yet — prompt correctly instructs builder to create `__init__.py`.
- Finalize wiring at [startup/finalize.py:276](src/probos/startup/finalize.py#L276) matches the `Depends(get_runtime)` pattern.
- Type annotations and logging context all comply.
