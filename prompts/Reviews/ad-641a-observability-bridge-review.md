# Review: AD-641a — Observability Bridge

**Reviewer:** Architect
**Date:** 2026-05-02
**Verdict:** ⚠️ Conditional (1 Required, 3 Recommended) — uses Wave 9A's tolerance reservation

## Required (must fix before building)

1. **Section 4 (Startup wiring) is prose-only; no code block.** Compared to siblings 641b/641f, which provide a full python wiring snippet, 641a's Section 4 says only "Wire `runtime.observability_bridge = ObservabilityBridge(...)` ... when `cfg.enabled` is True". The variable `cfg` is undefined — no lookup pattern is shown — and the task-attribute name (`runtime._observability_bridge_start_task`? `runtime.observability_bridge_start_task`?) is not specified. Builder will have to invent both the cfg-lookup pattern and the task attribute name. Replace Section 4 prose with an actual python block matching the Wave 9A house pattern (mirror 641f Section 5's `getattr(getattr(runtime, "config", None), "X", None)` cfg lookup and `runtime._<service>_start_task` naming). Without this, Builder cycles will be wasted on style guesswork.

## Recommended

R1. **EventType.AGENT_STATE.value as event_log filter is unverified.** Section 2 `_collect_vitals` calls `event_log.query(event_type=EventType.AGENT_STATE.value, limit=5)`. The footer doesn't grep `event_log.query` to confirm the parameter name (`event_type`) and that it accepts the `.value` string form rather than the enum. Add a footer line confirming `def query(...event_type=...)` signature. If the live signature is `def query(event_type: EventType, ...)` (enum-typed), pass the enum directly; if it's typed as `str`, pass `.value`. Either way, grep before the Builder finds out at test time.

R2. **Reading `attn._queue` is private-attribute access across module boundaries** (the prompt openly acknowledges this in `What This Does NOT Change` item 2). Wave 5 convention #1 strongly discourages this; the prompt's footnote that "future grandchild AD may add `snapshot()` public method" is honest but ships the smell anyway. Acceptable for v1 if you add: (a) a one-line comment in `_collect_attention()` flagging the `# AD-641a-iv: replace with attn.snapshot() once exposed`, AND (b) a corresponding grandchild entry in the deferred section (`AD-641a-iv: AttentionManager.snapshot() public API`). Today only 3 grandchildren (i/ii/iii) are listed; raise to 4. Do not block the build, but tag the smell explicitly.

R3. **`SystemConfig` field placement assumes `mcp` exists at the same level.** Section 3 says "Add `observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)` to `SystemConfig` (mirror placement after `mcp` field)." The prompt does not grep-confirm that `mcp` is a top-level field on `SystemConfig` (vs nested in another config). One additional footer grep `grep -n "mcp:.*MCPConfig\|mcp_config:" src/probos/config.py` would close this gap.

## Nits

- N1. Section 5 test 5 (`test_take_snapshot_with_no_runtime_state_returns_empty_collections`) — runtime stub description says "no `event_log`/`spawner`/`attention_manager`". Per Wave 8.5 dispatch's own `runtime.attention_manager` slip catch, the stub should say `attention` not `attention_manager`. One-word fix in the test plan description; the live code already uses `getattr(self._runtime, "attention", None)`.
- N2. Section 2 `_format_post` produces a multi-line `body` containing raw `dict` `repr()` output (`f"vitals: {snap.vitals_summary}"`). This is fine for v1 logging-grade content but renders poorly in HXI surfaces. Acceptable now; flag for AD-641a-ii (HXI surfaces).
- N3. Section 5 test 11 (`test_publish_loop_emits_failed_on_exception`) — exercising the loop requires `await asyncio.sleep(0)` between cancel and assert, plus `_stopping=True` to break out cleanly. Test description glosses this; Builder should be ready for an asyncio-flake landmine here. Consider rewriting as `_publish_once` direct call rather than loop exercise.

## Verified Against Codebase (2026-05-02)

```
grep -n "class VitalsMonitorAgent" src/probos/agents/medical/vitals_monitor.py
  28: class VitalsMonitorAgent(HeartbeatAgent):

grep -n "class AttentionManager" src/probos/cognitive/attention.py
  24: class AttentionManager:

grep -n "self\._queue:" src/probos/cognitive/attention.py
  42: self._queue: dict[str, AttentionEntry] = {}

grep -n "class WardRoomService" src/probos/ward_room/service.py
  29: class WardRoomService(EventEmitterMixin):

grep -n "async def create_post" src/probos/ward_room/service.py
  400: async def create_post(
       self, thread_id: str, author_id: str, body: str,
       parent_id: str | None = None, author_callsign: str = "",
  )
  → confirms 641a Section 2 call shape `body=body, author_callsign="System"` ✅

grep -n "self\.attention\s*=\|attention:\s*AttentionManager" src/probos/runtime.py
  197: attention: AttentionManager
  359: self.attention = AttentionManager(

grep -n "self\.spawner\s*=\|self\.event_log\s*=" src/probos/runtime.py
  294: self.spawner = AgentSpawner(self.registry)
  314: self.event_log = EventLog(db_path=self._data_dir / "events.db")

grep -n "def current_size" src/probos/substrate/pool.py
  53: def current_size(self) -> int:

grep -n "MCP_BRIDGE_FAILED\|AGENT_STATE\b" src/probos/events.py
  76:  AGENT_STATE = "agent_state"
  224: MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449

grep -n "OBSERVABILITY_SNAPSHOT_PUBLISHED\|OBSERVABILITY_BRIDGE_FAILED" src/probos/events.py
  (no matches; introduced by this prompt — not a phantom)

grep -n "class ObservabilityBridge\|observability_bridge" src/probos/
  (no matches; new module — not a phantom)
```

Cross-prompt dependency check — verified:

- AD-641a INTRODUCES `runtime.observability_bridge` in Section 4. ✅
- AD-641b's mention of `runtime.observability_bridge` is anchor-prose only ("after AD-641a's `runtime.observability_bridge` if 641a lands first"); 641b does NOT functionally consume it. The Wave 9A dispatch description's "consumer dep" is overstated — there is no source-code dependency. Builder order 641a→641b is a soft anchor preference, not hard.

## Convention audit (19 standing conventions)

| # | Convention | Status |
|---|---|---|
| 1 | Public-attribute wiring | ⚠️ — reads `attn._queue` private (R2); `runtime.observability_bridge` is public ✅ |
| 2 | stdlib persistence | ✅ N/A |
| 3 | Coordinator first | ✅ |
| 4 | Superset filter discipline | ✅ N/A |
| 5 | startup `emit_event_fn` | ⚠️ — Section 4 prose-only (Required #1) |
| 6 | verify-first | ⚠️ — gaps R1, R3 |
| 7 | No theater | ✅ — 3 sensors return real data; vitals reads real `event_log.query` |
| 8 | TYPE_CHECKING | ✅ N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | ✅ N/A |
| 11 | `__new__`-bypass `getattr` | ✅ all `_collect_*` use `getattr(self._runtime, ..., None)` |
| 12 | Solution Overview drift | ✅ |
| 13 | Pool template name collision | ✅ N/A |
| 14 | Aggressive pre-deferral | ✅ 3 v1 / 3 deferred (R2 suggests adding 4th) |
| 15 | Relaxed tolerance | ⚠️ used here — see verdict |
| 16 | Phantom-API pre-check | ✅ ran; 2 false positives documented |
| 17 | Per-instance state in `__init__` | ✅ `_task`, `_stopping`, `_interval`, `_channel` |
| 18 | Mock attributes | ✅ test plan calls out `AsyncMock(spec=WardRoomService)` |
| 19 | Session-id in headers | ✅ N/A |

## Disposition

641a is structurally correct and verify-first compliant on the major load-bearing claims (`runtime.attention`, `WardRoomService.create_post` signature, `current_size`/`target_size`, EventType absences). The single Required is mechanical — Section 4 needs a python code block matching the sibling-prompt house pattern so Builder doesn't have to reinvent the cfg-lookup and task-naming idioms. The three Recommended items are verify-first gap-closers (`event_log.query` signature, `mcp` field placement) and a smell-flag (private `_queue` read with explicit grandchild ticket). Verdict ⚠️ Conditional, using Wave 9A's tolerance reservation (convention #15) — the prompt is approvable once Section 4 has a real code block. Suggest pass-2 reviewer auto-promote to ✅ once Section 4 is rewritten with a python block.

---
