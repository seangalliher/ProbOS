# Review: AD-439 — Emergent Leadership Detection

**Reviewer:** Architect (self-review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — analytic core is sound and verify-first. One phantom import path and one Demeter violation that the prompt itself acknowledges but does not commit to fixing.

---

## Required (must fix before building)

### 1. Section 5 import path is wrong: `routers._deps` does not exist

The prompt's Section 5 imports:
```python
from probos.routers._deps import get_runtime
```

Verified — the underscore module does NOT exist:
```
grep -rn "_deps" src/probos/routers/
  (no matches)
```

The real module is `probos.routers.deps` (no underscore). Confirmed across 20+ existing routers:

```
grep -n "from probos.routers" src/probos/routers/system.py
  14: from probos.routers.deps import get_runtime, get_task_tracker

grep -n "from probos.routers" src/probos/routers/identity.py
  11: from probos.routers.deps import get_runtime
```

**Action:** Replace `_deps` with `deps` in Section 5.

### 2. Demeter violation in `_superior_agent_ids` is unresolved

The prompt's Section 1 implementation includes:

```python
assignments = self._ontology._dept.get_agents_for_post(superior_post_id)
```

This reaches through `VesselOntologyService._dept` (verified private at `service.py:54`). The prompt's own builder note says:

> Add a public passthrough on `VesselOntologyService` if a reviewer flags the Demeter violation; pattern matches existing private-attr reads in `service.py:191`.

Reviewer is flagging it. The pattern the prompt cites (`service.py:191`) is **inside** `service.py` — that's not a Demeter violation because it's the same module. AD-439 is reaching through from a different module (`cognitive/emergent_leadership.py`), which is the textbook violation `.github/copilot-instructions.md` prohibits.

`VesselOntologyService` already exposes ~10 public delegating wrappers (`get_post`, `get_chain_of_command`, `get_subordinate_agent_types`, etc.) — verified at `service.py:120–151`. Adding `get_agents_for_post` is trivial (3 lines, same pattern):

```python
def get_agents_for_post(self, post_id: str) -> list[Assignment]:
    return self._dept.get_agents_for_post(post_id)  # type: ignore[union-attr]
```

`DepartmentService.get_agents_for_post` exists at `departments.py:117` — verified.

**Action:** Promote the prompt's "if a reviewer flags" note to a hard Section 1.5: add the public passthrough on `VesselOntologyService`. Then `_superior_agent_ids` calls `self._ontology.get_agents_for_post(post_id)` cleanly.

### 3. Section 4 assumes `runtime.emit_event` is callable as a positional `(event, data)` callable; verify the AD-680 signature shape

The prompt passes `emit_event=runtime.emit_event` to the detector constructor, which then calls:

```python
self._emit_event(EventType.LEADERSHIP_DIVERGENCE, {...})
```

This is the post-AD-680 standard — `runtime.emit_event(event_type, data)`. Verified at `runtime.py:771` (per the AD-680 review notes). However, the prompt should grep-confirm this signature in its verify-first footer rather than assume it. The footer currently confirms `runtime.emit_event` exists conceptually but doesn't paste the signature.

**Action:** Add a verify-first line:
```
grep -n "def emit_event" src/probos/runtime.py
  771:    def emit_event(self, event: BaseEvent | EventType | str, data: ...
```

Cosmetic but enforces the standard.

---

## Recommended

### R1. Section 4 wiring uses `runtime.hebbian_router` and `runtime.ontology` and `runtime.registry`

All three are confirmed public attributes:
- `hebbian_router`: `runtime.py:180, 304` ✓
- `ontology`: `runtime.py:454` (`Optional[VesselOntologyService]`) ✓
- `registry`: `runtime.py:293` ✓

But Section 4 should add a guard for `runtime.ontology is None` because the type is `VesselOntologyService | None`. Without the guard, the wiring crashes at startup if ontology is disabled. Pattern:

```python
if config.emergent_leadership.enabled and runtime.ontology is not None:
    ...
```

### R2. Test 5 assumes `emit_event` is called with positional args

The test plan says: "emit called once with `EventType.LEADERSHIP_DIVERGENCE`". Confirm the test uses `assert_called_once_with(EventType.LEADERSHIP_DIVERGENCE, {...})` shape, matching the call site in Section 1. Document in the test name or docstring.

### R3. `_superior_agent_ids` performs O(N) scan over registry per agent in `analyze()`

If the registry has 50 crew agents and 15 of them have superiors, that's 50 × 15 = 750 lookups per `analyze()` call. For an analytics tool called on demand, fine. If a future caller invokes it in a tight loop, surface this as a perf consideration. Minor — document or add a one-shot agent_type→agent_id index inside `analyze()`.

### R4. Frozen dataclass `LeadershipDivergence` should declare `slots=True`

Minor: matches the recent codebase trend (governance/risk_tiers.py uses `@dataclass(frozen=True)` without slots; not mandatory). Skip if not adopting elsewhere.

---

## Nits

- Section 0 says insertion point is "near `WRONG_CONVERGENCE_DETECTED` at line 163" and Section 2 SEARCH/REPLACE places it between `WRONG_CONVERGENCE_DETECTED` and `WARD_ROOM_ECHO_DETECTED`. Consistent. Confirmed via:
  ```
  grep -n "WRONG_CONVERGENCE_DETECTED\|WARD_ROOM_ECHO_DETECTED" src/probos/events.py
    163:    WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583
    164:    WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"  # AD-583g
  ```
- The class docstring on `EmergentLeadershipDetector` says "Stateless on construction" — it does hold references to ontology/hebbian/registry. "Read-only on shared state" is more precise.
- The prompt mentions `TASK_ROUTED = "task_routed"  # AD-438` in events.py at line 215, but the SEARCH/REPLACE for `LEADERSHIP_DIVERGENCE` targets line 163 — confirm the SEARCH literal exactly matches the live file lines (`grep -A 1` to verify the SEARCH block).

---

## Verified

- `EventType.LEADERSHIP_DIVERGENCE` is absent — Section 0 introduces cleanly.
- `HebbianRouter.get_agent_weights` exists at `routing.py:180` ✓
- `HebbianRouter.all_weights` exists at `routing.py:237` ✓
- `VesselOntologyService.get_assignment_for_agent` exists at `service.py:153` ✓
- `VesselOntologyService.get_post` exists at `service.py:120` ✓
- `authority_over` field used at `service.py:177,187,190` ✓
- `config/ontology/organization.yaml` `reports_to` and `authority_over` fields confirmed at lines 27,28,38,80,124 ✓
- `runtime.hebbian_router`, `runtime.ontology`, `runtime.registry` all public ✓
- `finalize.py:297` insertion neighborhood (next to AD-676 risk-registry block) is clean ✓
- No EventType collision with AD-440/455/468/499 ✓

---

## Required Disposition

⚠️ **Conditional approval.** Two surgical fixes (import path + Demeter passthrough) and one verify-first addition. Estimated rework: ~10 minutes architect time. After fixes, this is a clean Group 3 prompt suitable for Builder dispatch.
