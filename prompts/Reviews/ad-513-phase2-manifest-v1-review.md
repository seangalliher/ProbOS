# Review: AD-513 Phase 2 v1 — Crew Manifest Shell + Watch Filter + Ship Manifest

**Verdict:** ⚠️ Conditional
**One-line headline:** Backward-compat clean and v1 scope is honest, but two real specification defects need revision (phantom `alert_manager` parameter; under-specified WatchManager lookup pattern).

---

## Required (must fix before building)

### 1. Phantom `alert_manager` parameter on `get_ship_manifest()` (Section 2 + Section 3)

**Defect.** Section 2 declares:

```python
def get_ship_manifest(
    self,
    *,
    trust_network: Any | None = None,
    watch_manager: Any | None = None,
    alert_manager: Any | None = None,  # <-- phantom
) -> dict[str, Any]:
```

and Section 3's `cmd_manifest --ship` passes `alert_manager=getattr(runtime, "alert_manager", None)`.

There is no `AlertManager` class in `src/probos/`, no `runtime.alert_manager` attribute, no `self.alert_manager` anywhere. Verified:

```
grep -rn "class AlertManager\|alert_manager" src/probos/ → 0 matches in src/
grep -n "alert_manager" src/probos/runtime.py        → 0 matches
```

The ship's alert state actually lives **inside the ontology service itself**:

```
src/probos/ontology/loader.py:57       self.alert_condition: str = "GREEN"
src/probos/ontology/service.py:99-100  def get_alert_condition(self) -> str:
                                           return self._loader.alert_condition
src/probos/ontology/service.py:93-94   VesselState(alert_condition=self._loader.alert_condition, ...)
```

Real consumers already use this pattern (`vessel.get("alert_condition", "GREEN")` at cognitive_agent.py:3671, 3888, 4580). The defensive `getattr(runtime, "alert_manager", None)` won't crash, but it will *always* return `None`, so `alert_state` would always default to `"GREEN"` — silently wrong, and Builder effort spent on a parameter the runtime never wires.

**Required fix.**
- Drop `alert_manager: Any | None = None` from `get_ship_manifest()`'s signature.
- Inside `get_ship_manifest()` body, source alert from `self.get_alert_condition()` (or `self._loader.alert_condition`).
- In Section 3 `cmd_manifest`, drop `alert_manager=getattr(runtime, "alert_manager", None)` from the `--ship` call.
- Update test #9 from "alert_state defaults to GREEN when alert_manager None" to "alert_state reflects ontology's current alert_condition (initialized to GREEN)".

**Recurrence note.** This is a phantom-API defect of exactly the shape AD-685b's kwarg-name pre-check was designed to catch (Wave 9 retrospective convention #20-adjacent). Pre-check found `runtime.vessel_ontology → runtime.ontology` at dispatch (commit e4363e2) but did not catch the dead `alert_manager` kwarg because it isn't `runtime.X` shape — it's a *method parameter named after a non-existent collaborator*. Recommend extending pre-check rules to flag method parameters whose name is `<noun>_manager` / `<noun>_registry` / `<noun>_service` against runtime attribute lookup. Track as Wave 17 retrospective candidate.

### 2. WatchManager API spec gap for watch filter (Section 1)

**Defect.** Section 1 states:

> If `watch_manager` provided AND `watch` is set: filter manifest entries to only those with `watch_assignment == watch`.
> If `watch_manager` provided (regardless of `watch` filter): enrich entry with `watch` field.

But `WatchManager` exposes **no per-agent watch query API**. Verified at `src/probos/watch_rotation.py:136-180`:

```python
class WatchManager:
    def assign_to_watch(self, agent_id: str, watch: WatchType) -> None: ...
    def remove_from_watch(self, agent_id: str, watch: WatchType) -> None: ...
    def get_on_duty(self) -> list[str]: ...                           # current-watch only
    def get_roster(self) -> dict[str, list[str]]: ...                  # watch_name -> [agent_id]
    def get_watch_status(self) -> dict[str, Any]: ...
```

To compute "watch for agent X", Builder must reverse `get_roster()`. Three under-specified points the Builder will have to invent (and likely get wrong on first pass per Wave 10 retrospective lesson #18 on under-specified read-modify-write patterns):

(a) **Lookup pattern.** Required spec:
```python
roster = watch_manager.get_roster()  # {"alpha": [aid, ...], "beta": [...], "gamma": [...]}
agent_to_watch: dict[str, str] = {aid: w for w, aids in roster.items() for aid in aids}
```

(b) **Match key.** Manifest entries carry `agent_id` (may be empty string per service.py:497-503) AND `agent_type`. WatchManager rosters key by `agent_id` (line 136 signature: `assign_to_watch(self, agent_id: str, ...)`). Spec must say `agent_to_watch.get(entry["agent_id"])` and explicitly handle the empty-agent_id case (skip enrichment for unassigned crew).

(c) **Case + enum.** `WatchType` values are lowercase strings (`ALPHA = "alpha"`, watch_rotation.py:22). User types `/manifest watch:alpha` (already lowercase by convention) but Section 3 doesn't normalize. Spec must say either: (i) lowercase `watch` arg before comparing, or (ii) `watch_arg.upper()` then `WatchType[...]` — pick one. Recommend lowercase compare to match the existing `WatchType.value` shape.

**Required fix.** Rewrite Section 1's "Behavior change" bullets with explicit pseudo-code for the lookup, the `agent_id` match key, and the case-normalization rule. The hard-stop entry "WatchManager doesn't expose query-by-watch API — surface; v1 may need to fall back to per-agent iteration" is correct in spirit but only escalates *after* Builder discovers the gap; spell out the fallback in the prompt body.

---

## Recommended

### 3. `get_ship_manifest()` — pin sources for `ship_name` and `vessel_class`

Section 2 declares the return shape but doesn't tell Builder where to source `ship_name` / `vessel_class`. Real source on the same service:

```
src/probos/ontology/service.py:83  def get_vessel_identity(self) -> VesselIdentity:
                                       return VesselIdentity(name="ProbOS", version="0.0.0", description="", ...)
```

`VesselIdentity` carries `name`, `version`, `description`, `instance_id`, `started_at` — no `vessel_class` field. Builder will either invent a field or guess (`config.system.vessel_class`?). Two acceptable fixes:

- **Drop `vessel_class`** from the return shape (cleanest).
- Or **map `vessel_class = self.get_vessel_identity().description`** with a comment explaining the convention.

Either way, spell it out — same paragraph that lists the return-shape keys.

### 4. `watches` field — choose "active watch" vs "all populated watches"

Section 2's return shape: `"watches": list[str] (active watch names; empty if watch_manager None)`.

Two reasonable interpretations:

- (a) Single currently-active watch: `[watch_manager.current_watch.value]` — matches the "alert_state is current alert" pattern.
- (b) All watches with at least one assigned crew: `[w for w, aids in watch_manager.get_roster().items() if aids]`.

Pick one. (a) is cheaper and parallel to `alert_state`; (b) gives a fuller manifest. Recommend (b) for federation gossip use case (the stated purpose). Spec the chosen one.

### 5. `/manifest watch:<arg>` case-normalization

Section 3 token parser: `watch = token.split(":", 1)[1]`. If user types `/manifest watch:Alpha`, it won't match `WatchType.ALPHA.value == "alpha"`. Add `.lower()` or document the convention. One-line fix in the prompt.

---

## Nits

### 6. Section 5 is empty; delete it.

"### Section 5 — Pydantic config (optional). No new config required." — adds noise. Drop the section header.

### 7. `runtime.callsign_registry` is verified, not "(Builder verifies)"

The footer's "Verified Against Codebase" block says callsign_registry verification is the Builder's job. Already verified at `cognitive_agent.py:4126` (`getattr(rt, 'callsign_registry', None)`) and `routers/ontology.py:67` — same pattern. Promote to "verified" and remove the deferred line.

### 8. Hard-stop "Existing `/manifest` command name collides" — grep already confirms 0 collisions

```
grep -n "/manifest" src/probos/experience/shell.py → 0 matches
```

Move from "Hard-Stops" to "Verified" in the footer; reduces Builder pre-flight noise.

---

## Verified

- **`runtime.watch_manager` exists.** runtime.py:238 (annotation), 580 (init), 1659 (warm-boot restore). ✅
- **`runtime.ontology` exists** and is the correct attribute name (not `runtime.vessel_ontology`). Pre-check caught the slip at dispatch (commit e4363e2). ✅
- **Backward-compat on `get_crew_manifest()`.** Two existing callers, both kwargs-only:
  - `src/probos/cognitive/cognitive_agent.py:4126` — `rt.ontology.get_crew_manifest(callsign_registry=...)`. New `watch=None`, `watch_manager=None` defaults preserve behavior. ✅
  - `src/probos/routers/ontology.py:64` — `ont.get_crew_manifest(department=..., trust_network=..., callsign_registry=...)`. New defaults preserve behavior. ✅
  - REST endpoint also unchanged (no new query param in v1, per "What This Does NOT Change" — verified consistent).
- **Shell command pattern conformance.** Existing `cmd_agents(runtime, console, args)` (commands_status.py:30) matches prompt's `cmd_manifest(runtime, console, arg)`. Module shape `commands_manifest.py` is consistent with `commands_status.py`. Lambda-wrapper dispatch idiom matches all other entries. ✅
- **`self.COMMANDS` registry shape** is `dict[str, str]` (cmd → one-line description) at shell.py:51-106. Section 4's "include with usage one-liner" is type-correct. ✅
- **No `/manifest` collision** in shell.py (0 matches before this prompt). ✅
- **`/help` mechanism**: `cmd_help(con, self.COMMANDS)` at shell.py:235 reads the dict — adding a `/manifest` entry will surface automatically. ✅
- **No new public runtime attributes.** v1 ships only methods on existing `VesselOntologyService` and a new `commands_manifest.py` handler module. Wave 5 convention #1 (public-attribute discipline) trivially satisfied. ✅
- **No new EventTypes.** Section 0 explicitly empty. ✅
- **v1 scope discipline.** No trust-gated visibility (Phase 2b), no agent tool access (Phase 2c), no ACM-competency fields (Phase 2e) smuggling found. The deferred bullets are correctly named with forcing functions per convention #14 aggressive pre-deferral. ✅
- **AD-685b 2nd consecutive real catch.** Pre-check caught `runtime.vessel_ontology → runtime.ontology` at dispatch time (commit e4363e2). Following Wave 16's first real catch, this is the second consecutive wave with a non-zero scripted-check value. Recurrence-class catches are now compounding rather than re-emerging in review.
- **Test plan coverage.** 17 tests cover Section 1 (5: filter happy/empty/backward-compat/enrichment/optional-dep), Section 2 (4: happy/no-enrichment/watches/alert-default), Section 3 (6: no-args/dept/watch/--ship/no-ontology/empty), Section 4 (2: dispatch/help). Boundary coverage is thorough. ✅
- **Tracking section** correctly names PROGRESS.md, DECISIONS.md (Era V), roadmap.md flip-to-partial. ✅

---

## Standing Convention Audit (Wave 5 + 5-7 + 8 + 9 = 23 conventions)

Spot-checks against the high-risk subset for this prompt:

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring (no `_`-prefixed cross-module reads) | ✅ no new attrs |
| 6 | Layer discipline | ✅ ontology → watch_manager + trust read-only |
| 7 | Two-pass review | in progress |
| 8 | TYPE_CHECKING cross-layer imports | n/a (no new imports) |
| 9 | ASCII-only source comments | ✅ prompt uses ASCII |
| 13 | Pool template name collision | n/a (no pools) |
| 14 | Aggressive pre-deferral | ✅ 3-of-6 |
| 15 | Relaxed tolerance (1 ⚠️ allowed) | this review uses ⚠️ for **2** Required, exceeds tolerance → revision required |
| 16 | Dispatch-time scripted phantom-API pre-check | ✅ ran; caught `vessel_ontology` slip |
| 17 | Defense-in-depth on read paths | partial — `getattr(rt, "alert_manager", None)` is defensive but the param itself is the defect |
| 19 | Prompt header consistency on revision | n/a (first pass) |
| 20 | AD-685b kwarg pre-check | ✅ ran; did not catch `alert_manager` (param-name not `runtime.X` shape — flag for retrospective) |

Overall: clean on 11 of 12 spot-checked conventions. Convention 15 tolerance breached by Required #1 + #2; convention 17 partially flagged on Required #1.

---

## Failure Modes If Shipped As-Is

1. **Builder produces a `get_ship_manifest()` whose `alert_state` is permanently `"GREEN"`** because `runtime.alert_manager` doesn't exist. Tests pass (test #9 specifically asserts this!) but the feature is a placeholder. Federation gossip / workforce planning consumers get wrong data.
2. **Builder invents a per-agent watch lookup pattern** — likely matches on `agent_type` rather than `agent_id`, or skips the empty-agent_id case. Tests likely cover the happy path with populated rosters; edge cases (unassigned crew, case-mismatch arg) silently fail.
3. **`vessel_class` field becomes a hardcoded empty string or invents a config field** that doesn't exist. Federation consumer expects vessel_class for ship-class routing → returns wrong value.

All three are catchable at draft time per the relevant conventions; revision pass should close them in one cycle.

---

## Recommended Disposition

⚠️ Conditional. Apply Required #1 + #2; fold Recommended #3-5; judgment on Nits #6-8. Single revision pass should converge to ✅ at second-pass review.
