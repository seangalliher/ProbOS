# Review: AD-679 — Selective Disclosure Routing

**Verdict:** ✅ Approved
**Re-review (2026-04-29 second pass): ✅ Approved.** Revisions clean. Event-collision note added.

**Headline:** All dependencies verified; ready for builder.

## Required

None.

## Recommended

1. **Department clearance defaults.** `DEFAULT_CLEARANCES` hardcodes `bridge`, `security`, `engineering`. Cross-check against the actual department enum/strings used elsewhere. If departments are dynamic, move to `config.yaml`.
2. **Captain override semantics.** `set_agent_clearance()` allows individual override. Be explicit about whether/where an `is_captain` check exists.
3. **Audit-log verbosity.** `DisclosureDecision.reason` strings ("Clearance X >= Y") — pick technical or user-friendly phrasing and stick with it.

## Nits

- Add a `count_permitted()` method if downstream consumers (HXI) want a quick stats view without reconstructing the list.
- `get_clearance_map()` returns `dict[str, str]` of level names — confirm HXI accepts the format.

## Verified

- `IntentBus.broadcast()` at [mesh/intent.py:369](src/probos/mesh/intent.py#L369); `_intent_index` at [mesh/intent.py:35](src/probos/mesh/intent.py#L35). DisclosureRouter is a separate filter layer (not integrated into IntentBus) — correct design.
- `Depends(get_runtime)` pattern at [routers/system.py:21](src/probos/routers/system.py#L21).
- `get_runtime` import at [routers/system.py:13](src/probos/routers/system.py#L13).
- `KNOWLEDGE_TIER_LOADED` at [events.py:169](src/probos/events.py#L169) — `DISCLOSURE_FILTERED` insertion confirmed (potential collision with AD-677's CONTEXT_PROVENANCE_INJECTED if AD-679 builds first; SEARCH block must check actual state at build time).
- `DisclosureLevel(IntEnum)` ordering for comparison ops — correct.
- 8 tests covering ordering, defaults, permit/deny, overrides, filtering — adequate.
- Type annotations complete; logging context adequate.

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

Revisions added a proactive event-collision note for `DISCLOSURE_FILTERED` ("if AD-677 or AD-438 ships first, update SEARCH block"). Good defensive guidance.

`DisclosureDecision.reason` strings now use consistent technical phrasing: `f"Clearance {clearance.name} >= {content_level.name}"` / `< {content_level.name}"`. ✅

Minor unresolved Recommended items (department defaults hardcoded; Captain-override path not explicit) remain low-priority. Not blockers.
