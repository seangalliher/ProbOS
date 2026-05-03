# Review: AD-641f — Engineering Chief Ship's Systems Observability

**Reviewer:** Architect
**Date:** 2026-05-02
**Verdict:** ✅ Approved

## Required (must fix before building)

None.

## Recommended

R1. **`get_all_capabilities()` return shape verification.** Section 3 `_collect_capabilities()` calls `registry.get_all_capabilities() or {}` and treats the result as a dict whose keys are intent strings. Live signature is `def get_all_capabilities(self) -> dict:` at `src/probos/mesh/capability.py:50` — return type is bare `dict` with no value annotation. Add a one-line grep evidence to the footer confirming the keys are intent names (not agent IDs); if the dict is keyed by agent_id, `intents` would be wrong. Defensive shape check (`isinstance(all_caps, dict)`) recommended in the helper.

R2. **`_engineering_sensor_start_task` is a leading-underscore public wiring attribute.** Section 5 wires `runtime._engineering_sensor_start_task = asyncio.create_task(...)`. Wave 5 convention #1 prefers no leading underscore on consumer-facing names. The Wave 8.5 split summary classifies this as "intentionally private — internal task-handle, not consumer-facing" — defensible but inconsistent with the other Wave 9A prompts. Either rename to `runtime.engineering_sensor_start_task` for consistency or add a one-line comment in Section 5 stating the intentional privacy classification.

R3. **`auto_start_periodic_report` default is `False`** but Section 6 test 10 (`test_start_creates_named_task`) requires explicit `start()` invocation — fine in tests, but the operational default means the report task never runs out-of-the-box. State this explicitly in the Solution Overview ("v1 ships with `auto_start_periodic_report=False`; operators flip the flag once they want the periodic emit") so the deferred capability is honest.

## Nits

- N1. Section 6 test 12 (`test_report_interval_minimum_enforced`) — the constructor clamps to 1.0; the test should also assert behavior at the negative-input boundary (`report_interval_seconds=-5.0` clamps to 1.0). One-line addition.
- N2. Section 3 `report()` emits payload field `pools = list(snap.pool_summary.keys())` — list of names only. Consumers (the future LaForge instructions wire) probably want `current_size`/`target_size` summary in the payload, not just names. Acceptable for v1; flag as `AD-641f-iv` (richer payload) if it doesn't fit existing grandchildren.

## Verified Against Codebase (2026-05-02)

```
grep -n "class EngineeringAgent" src/probos/cognitive/engineering_officer.py
  37: class EngineeringAgent(CognitiveAgent):

grep -n "def agent_count\|def get_all_capabilities" src/probos/mesh/capability.py
  50: def get_all_capabilities(self) -> dict:
  98: def agent_count(self) -> int:

grep -n "def view_size\|def get_view" src/probos/mesh/gossip.py
  99:  def get_view(self) -> dict[AgentID, GossipEntry]:
  119: def view_size(self) -> int:

grep -n "self\.spawner\s*=\|self\.capability_registry\s*=\|self\.gossip\s*=" src/probos/runtime.py
  294: self.spawner = AgentSpawner(self.registry)
  301: self.capability_registry = CapabilityRegistry(
  309: self.gossip = GossipProtocol(

grep -n "def current_size\|def target_size" src/probos/substrate/pool.py
  53:  def current_size(self) -> int:

grep -n "ENGINEERING_SENSOR_REPORT" src/probos/events.py
  (no matches; introduced by this prompt — not a phantom)

grep -n "engineering_sensor\|EngineeringSensorBundle\|EngineeringSensorService" src/probos/
  (no matches; new module — not a phantom)
```

Section 0 EventType collision check vs sibling Wave 9A prompts:

| Prompt | EventType(s) introduced |
|---|---|
| 641a | `OBSERVABILITY_SNAPSHOT_PUBLISHED`, `OBSERVABILITY_BRIDGE_FAILED` |
| 641b | `WARD_ROOM_HEBBIAN_UPDATED`, `WARD_ROOM_HEBBIAN_DECAYED` |
| 641f | `ENGINEERING_SENSOR_REPORT` |

No collisions across prompts; none collide with existing `events.py` members.

## Convention audit (19 standing conventions)

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring | ⚠️ partial — `runtime._engineering_sensor_start_task` is private (R2) |
| 2 | stdlib persistence | ✅ N/A (no persistence in v1) |
| 3 | Coordinator first | ✅ Service is the coordinator; periodic emit is opt-in |
| 4 | Superset filter discipline | ✅ N/A |
| 5 | startup `emit_event_fn` | ✅ uses `runtime.emit_event` |
| 6 | verify-first | ✅ all claims grep-confirmed |
| 7 | No theater | ✅ all 3 sensors return real data; periodic emit is honest opt-in |
| 8 | TYPE_CHECKING cross-layer | ✅ N/A (intra-cognitive) |
| 9 | ASCII-only comments | ✅ confirmed |
| 10 | work_item_store vs workforce | ✅ N/A |
| 11 | `__new__`-bypass `getattr` | ✅ all `_collect_*` use `getattr(self._runtime, ..., None)` |
| 12 | Solution Overview drift watch | ✅ Solution Overview matches Section bodies |
| 13 | Pool template name collision | ✅ N/A |
| 14 | Aggressive pre-deferral | ✅ 3 v1 / 3 deferred grandchildren |
| 15 | Relaxed tolerance | ✅ — verdict ✅, no ⚠️ used |
| 16 | Phantom-API pre-check | ✅ ran in Wave 8.5; 2 false positives, 0 real phantoms |
| 17 | Per-instance mutable state in `__init__` | ✅ `_task`, `_stopping`, `_interval` all instance |
| 18 | Mock all attributes | ✅ N/A (no httpx; `AsyncMock` not required) |
| 19 | Session-id in headers | ✅ N/A (no JSON-RPC) |

Tolerance reservation: convention #15 allows 1 ⚠️ on the highest-risk prompt only. 641f is medium-risk and uses no tolerance; the partial-#1 hit (R2) is a Recommended, not a verdict-blocker.

## Disposition

641f is the cleanest of the three Wave 9A prompts. The sensor bundle is honest (3 real sensors, no fakes), `getattr` defensive against `__new__`-bypass test instances (#11), task-handle named (`engineering_sensor_report`) and instance-held (Wave 5 convention), and 3 grandchildren are explicitly listed for deferral. The two Recommended items (`get_all_capabilities` shape check, `_engineering_sensor_start_task` underscore inconsistency) are polish, not correctness. Approve for build pass.

---
