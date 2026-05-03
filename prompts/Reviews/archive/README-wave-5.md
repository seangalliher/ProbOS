# Wave 5 Prompt Review Sweep — 2026-05-01

**Reviewer:** Architect (self-review of own drafts)
**Scope:** 5 prompts drafted in commit `dad4ac6` for AD-439, AD-440, AD-455, AD-468, AD-499.
**Review file path pattern:** `prompts/Reviews/ad-NNN-*-review.md`.

---

## Verdicts at a Glance

| AD | Title | Verdict | Required | Recommended | Nits | Build Readiness |
|---|---|---|---|---|---|---|
| AD-499 | Ship & Crew Naming Conventions | ⚠️ Conditional | 5 | 4 | 3 | After fix |
| AD-439 | Emergent Leadership Detection | ⚠️ Conditional | 3 | 4 | 3 | After fix |
| AD-468 | Runtime Configuration Service | ❌ Not Ready | 5 | 4 | 3 | After rework |
| AD-440 | Chain of Command Delegation | ⚠️ Conditional | 4 | 5 | 4 | After fix |
| AD-455 | Security Team — Threat & Trust Integrity | ❌ Not Ready | 5 | 5 | 4 | After rework |
| **Totals** | | **0 ✅ / 3 ⚠️ / 2 ❌** | **22** | **22** | **17** | |

No Wave 5 prompt is currently ✅ Approved. Three are surgical fixes (~10–30 min each). Two require architectural rework (~30–45 min each).

---

## Aggregate Themes (recurring findings across the wave)

1. **`runtime._foo` Demeter pattern carried over from earlier waves** — AD-440, AD-455, AD-468 all set new private-named attributes on the runtime (`_order_manager`, `_threat_detector`, etc.). The post-AD-680 standard is public-named attributes for cross-module access. Three prompts need consistent uplift; this is also a candidate for a future AD-684 sweep that promotes existing `_risk_registry`, `_disclosure_router`, etc. retroactively.
2. **Phantom APIs in wiring sketches** — AD-468 (`runtime.data_dir`, `set_cycle_interval`), AD-455 (`RedTeamAgent.run_probe`, `runtime.red_team_agents`), AD-499 (`EventLog.append`, `_BANNED_DEFAULT`). Each violates the verify-first standing order. Pattern: when a Section's "wiring sketch" is hand-waved as Builder-discretion, phantom APIs slip in.
3. **Test coverage gaps in rejection-reason matrices** — AD-440's `_emit_rejection` has 6 reasons, only 4 are tested. Recurring theme — error-path branches are under-covered.
4. **Section 0 EventTypes are clean across the batch** — no name collisions between AD-439/440/455/468/499. All values absent from current `events.py`. Section 0 discipline holds.
5. **Pre-flagged items confirmed as real issues:**
   - **AD-440 `_superior_agent_ids` Demeter** — Dispatch labeled this as AD-440; symbol is actually in **AD-439**. AD-439's review flags it as Required (#2): promote to a public `VesselOntologyService.get_agents_for_post(post_id)` passthrough.
   - **AD-468 `_cooldown` setter** — Required (#3): direct private-attr assignment is the pattern's exemplar Demeter violation. AD-468 must add `set_cooldown` and `set_cycle_interval` public setters as new sections.
   - **AD-455 `RedTeamAgent.run_probe` interface** — Required (#1): the assumed method does not exist; the prompt's proposed default no-ops the campaign. AD-455 must redesign Section 5 to use the existing `verify(...)` API or add `run_probe` as a real (non-no-op) method.

---

## Recommended Build Readiness Order (after fixes)

After all required fixes land, dispatch order should match the pattern-establishment dependency:

1. **AD-499** — smallest blast radius, establishes the AD-499 naming policy library. Independent.
2. **AD-439** — analytics-only, low risk. Establishes the public-passthrough precedent on `VesselOntologyService`.
3. **AD-468** — establishes the `runtime.data_dir` public property and `set_cycle_interval`/`set_cooldown` public setters that AD-455 and AD-440 will mirror.
4. **AD-455** — establishes the `runtime.red_team_agents` public attribute (or rename) and the `runtime.{threat_detector,input_validator,trust_integrity_monitor,red_team_lead}` public-name pattern.
5. **AD-440** — mirrors the public-name pattern from AD-455. Highest-risk semantically (authority delegation) so lands last when supporting infrastructure is settled.

---

## Cross-Prompt Concerns (none Required, but worth noting)

- **No EventType naming collisions** between Wave 5 prompts. Verified.
- **Source-file overlap:** all 5 prompts modify `events.py`, `config.py`, and `startup/finalize.py`. SEARCH anchors are at distinct line neighborhoods, so merge conflicts are unlikely if Builder commits one prompt at a time. If Builder runs prompts in parallel, the SEARCH anchors for `events.py` (`DISCLOSURE_FILTERED`, `WRONG_CONVERGENCE_DETECTED ... WARD_ROOM_ECHO_DETECTED`, `DM_CONVERGENCE_DETECTED ... SENSORIUM_BUDGET_EXCEEDED`) are non-overlapping but adjacent — second-mover may need a rebase if they target the same neighborhood.
- **AD-468 introduces `tomli-w` as a runtime dependency** — must be added to `pyproject.toml`. Surface to dispatching architect for confirmation before the rewrite.

---

## Architect Disposition

The 5 Wave 5 drafts are **actionable but require revision** before Builder dispatch. None should ship as-is. The recurring themes (Demeter, phantom APIs in wiring sketches) are easy to fix with a focused second pass.

**Recommended next step:** the dispatching architect revises the 3 Conditional prompts (AD-439, AD-440, AD-499) and the 2 Not Ready prompts (AD-455, AD-468) per their respective review files. Total architect rework: **~2 hours.** Each revision should append a `## Revision (date)` section to the bottom of the prompt summarizing the changes (so the Builder can see what changed without re-reading the diff).

After revision, re-review pass — expect all 5 to pass to ✅ Approved on the second iteration.
