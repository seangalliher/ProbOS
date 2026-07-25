# AD-1072 — Tool search + sub-agent delegation tool

**Target repo:** OSS (`d:\ProbOS`)
**Epic:** #1006 — Conversational tool-calling + Skills for crew agents (Cowork/Codex/Copilot parity). This is the **last AD** of the epic (AD-1070 and AD-1071 are the other two open items; this prompt covers only AD-1072).
**AD numbering:** Current highest top-level = **AD-1094** (HEAD). **AD-1072 is the pre-reserved epic #1006 sub-number** (issue #1006 lists AD-1070/1071/1072 as the remaining decomposed ADs) — it does **NOT** consume a new top-level. Do not mint AD-1095.

---

## Goal

Give a crew agent in a 1:1 chat two new keystone tools inside the already-proven AD-1065 conversational `AgenticLoop`:

1. **`search_capabilities`** — discover what tools / skills / mesh-intents exist on the ship (read-only). The loop already has `run_python` (AD-1066) and `use_skill` (AD-1068); this closes the loop by letting the agent *find* a capability before invoking it, instead of guessing or confabulating (the BF-651 / AD-1064 confabulation class).
2. **`delegate_task`** — hand a bounded subtask to **another crew agent by callsign** and return that agent's result. Delegation routes through the **same governed `WorkItemAgenticExecutor`** the task dispatcher uses, so the delegated agent's tool permissions, consensus gates, and tool-trace logging all apply — no governance bypass.

Both tools are **default-OFF** and additive. With the flags off, `WorkItemAgenticExecutor.run` is byte-identical to today.

---

## Verified seams (read these before building — all confirmed at HEAD)

### Tool protocol & registry
- `Tool` Protocol — [src/probos/tools/protocol.py](../src/probos/tools/protocol.py) lines 82–126: properties `tool_id`, `name`, `tool_type`, `description`, `input_schema`, `output_schema`, and `async def invoke(self, params, context=None) -> ToolResult`.
- `ToolResult` frozen dataclass — same file lines 67–75: `output: Any`, `error: str | None`, `duration_ms: float`, `metadata: dict`; `.success` == `error is None`.
- `ToolRegistry.register(...)`, `.get(tool_id)`, `.list_tools(...)` — `src/probos/tools/registry.py`.

### The two sibling tools to mirror exactly
- **`CodeExecutionTool`** — [src/probos/tools/code_execution_tool.py](../src/probos/tools/code_execution_tool.py): `__init__(self, *, runtime)`, `tool_id == "run_python"`, `async def invoke(self, params, context=None)`, reads `params["code"]` + `context["thread_id"]/["agent_id"]`, returns `ToolResult(output={...}, error=...)`, never raises.
- **`UseSkillTool`** — [src/probos/tools/use_skill_tool.py](../src/probos/tools/use_skill_tool.py): `__init__(self, *, runtime)`, `tool_id == "use_skill"`, reads `params["name"]` + `context["department"]/["rank"]/["agent_id"]`, honest-degrades to `{"found": False, "available": [...]}` on a miss.

### The registration site (where the new block goes)
- **`WorkItemAgenticExecutor.run`** — [src/probos/cognitive/agentic_dispatch.py](../src/probos/cognitive/agentic_dispatch.py) lines 443–698. The two existing registration blocks are the template:
  - `exec_ids` block (lines 547–566): gates on `config.execution.enabled`, idempotent `if registry.get("run_python") is None: registry.register(CodeExecutionTool(runtime=runtime), provider="AD-1066", tags=[...])`.
  - `skill_ids` block (lines 575–596): gates on `runtime.cognitive_skill_catalog is not None`, registers `UseSkillTool`.
  - Dedup (lines 598–599): `tool_ids = list(dict.fromkeys([*granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids]))`.
  - Loop build (lines 619–621): `loop = AgenticLoop(llm_client=self._llm, tool_executor=DispatchToolExecutor(registry=registry), ...)`; the `context={"agent_id":..., "department":..., "rank":..., "thread_id":...}` dict is built from `run`'s parameters and passed into `AgenticLoop.run(... context=context)`.
- **`AgenticLoop.run`** — [src/probos/cognitive/swe_harness/agentic_loop.py](../src/probos/cognitive/swe_harness/agentic_loop.py) lines 68–327: forwards `context` straight to `executor.invoke(tool_id, params, context=context)` (line ~244). Tools are offered to the LLM via `tool_registration_to_llm_definition(reg)` (uses each tool's `input_schema`).

### Search target (what `search_capabilities` queries)
- **`list_capability_catalog(runtime)`** — [src/probos/routers/tools.py](../src/probos/routers/tools.py): `@router.get("/catalog")` at line 43, `async def list_capability_catalog` at line 44. **CONFIRMED return shape (read the item builders, not the docstring):**
  - `tools` (built ~tools.py L107–116): each item `{"id", "name", "description", "origin", "tool_type", "domain", "department", "held_by"}` — **the id key is `id`, NOT `tool_id`** (do not read `tool_id` off a catalog item).
  - `skills` (built ~tools.py L119–127): each item `{"id", "name", "description", "department", "min_rank", "intents", "held_by"}`.
  - `mesh_intents` (via `_mesh_intents`, [routers/agents.py](../src/probos/routers/agents.py) L1196; items built L1221–1230): each item `{"id", "name", "description", "usage_hint", "requires_consensus", "tier", "origin", "reachable"}` — **no `domain` key**.
  - plus top-level `mcp_servers` and a `counts` dict.
  All three searchable axes carry `name` + `description` (the rank fields the tool sorts on); `held_by` exists on `tools`/`skills` only (mesh-intents are ship-served → no `held_by`). It is an `async def` with a `Depends(get_runtime)` default — **call it directly as `await list_capability_catalog(runtime)`** (passing `runtime` explicitly bypasses `Depends`; established in-process pattern). Keyword-filter the result inside the tool.

### Delegation seam (what `delegate_task` reuses) — HIGHEST RISK
- **`WorkItemAgenticExecutor.run(...)`** is the reusable governed executor. **CONFIRMED signature** (agentic_dispatch.py:460–471):
  ```python
  async def run(self, *, agent_id: str, instructions: str, task_text: str,
                runtime: Any, department: str = "", rank: str = "ensign",
                thread_id: str = "", max_iterations: int | None = None,
                tier: str | None = None) -> WorkItemAgenticOutcome
  ```
  `WorkItemAgenticOutcome` exposes `.final_text`, `.stopped_reason`, `.denied_tools`, `.tool_trace_ref`. **There is NO `extra_context` param** — the loop context is built inline as a 4-key dict literal `context={"agent_id", "department", "rank", "thread_id"}` at the `await loop.run(...)` call (agentic_dispatch.py:625–634). Threading `_delegation_depth` therefore requires the additive `extra_context` param (Step 2.5 + Step 3).
- `WorkItemAgenticExecutor.__init__(self, *, llm_client)` stores the client as **`self._llm`** (agentic_dispatch.py:458) and builds the loop with `llm_client=self._llm` (line 620). The delegate tool must reuse the *parent* executor's `self._llm` (see Step 3). (The conversational entry in [cognitive_agent.py](../src/probos/cognitive/cognitive_agent.py) `_maybe_run_conversational_agentic` ~3403–3440 constructs the executor with the *agent's* own client.)
- **AVOID** (governance bypass, do not do): raw `agent_b.perceive()/decide()/act()` Python calls; using `direct_message` (it returns free text, not a governed execution); hand-rolling votes into `QuorumEngine.evaluate`.

### Config
- `DmAgenticConfig` (AD-1065) — [src/probos/config.py](../src/probos/config.py) lines ~5720–5728: `enabled=False`, `max_iterations=Field(5, ge=1, le=25)`, `tier="standard"`. Mounted on `SystemConfig` as `dm_agentic`.
- `ExecutionConfig` (AD-1066) — same file ~3099+.

---

## Build

### Step 1 — `SearchCapabilitiesTool` (the tool-search half, low risk)

New file `src/probos/tools/search_capabilities_tool.py`, mirroring `UseSkillTool`:
- `class SearchCapabilitiesTool` implementing `Tool`; `__init__(self, *, runtime)`; `tool_id == "search_capabilities"`.
- `input_schema`: `{ "query": str (required), "kind": "tool"|"skill"|"intent"|"all" (default "all") }`.
- `output_schema`: `{ "results": [ {name, kind, description, held_by?} ], "count": int }`.
- `invoke(params, context=None)`:
  - Read `query` (required; empty/missing → `ToolResult(output={"results":[],"count":0,"message":"query required"})`, no error).
  - `from probos.routers.tools import list_capability_catalog`; `catalog = await list_capability_catalog(self._runtime)`.
  - Build a unified candidate list across `tools`/`skills`/`mesh_intents` (tag each with its `kind`), filtered by `kind` when not `"all"`.
  - Keyword-rank by case-insensitive token overlap on `name` (weight 3) + `description` (weight 1); drop score-0; sort `(-score, name)`; cap to top **10**.
  - Return `ToolResult(output={"results": [...], "count": len})`. Tier-2 honest-degrade: any exception → `ToolResult(error="search_failed: <reason>")`, never raise.
- Gate: a new flag (Step 4) `agentic_tools.tool_search_enabled`.

### Step 2 — `DelegateTaskTool` (the delegation half, high risk — guards are mandatory)

New file `src/probos/tools/delegate_task_tool.py`:
- `class DelegateTaskTool` implementing `Tool`; `__init__(self, *, runtime, llm_client, max_depth: int, max_iterations: int, tier: str)` storing **all five**: `self._runtime = runtime` (mirrors `UseSkillTool`), `self._llm_client = llm_client` (the tool's OWN attribute — it receives the parent executor's `self._llm` at registration in Step 3; the *executor's* attribute is `self._llm`, the *tool's* is `self._llm_client`), `self._max_depth = max_depth`, `self._max_iterations = max_iterations`, `self._tier = tier`; `tool_id == "delegate_task"`.
- `input_schema`: `{ "task": str (required), "to": str (required — target crew callsign) }`. **`to` is required in v1** — auto-routing to a best-match agent is a FORWARD item; explicit targeting keeps fan-out bounded.
- `invoke(params, context=None)`:
  1. **Depth guard (first):** `depth = int((context or {}).get("_delegation_depth", 0))`. If `depth >= self._max_depth` → `ToolResult(output={"delegated": False, "reason": "max_delegation_depth_reached"})` (no error, no run). This prevents A→B→A recursion / fan-out blow-up (the IntentBus fan-out lesson).
  2. Validate `task` and `to` non-empty → honest-degrade output when missing.
  3. **Resolve the target crew agent by callsign (CONFIRMED accessors).**
     - `cs = getattr(self._runtime, "callsign_registry", None)`; `resolved = cs.resolve(to)` → dict `{"callsign","agent_type","agent_id","display_name","department"}` or `None` (`CallsignRegistry.resolve`, crew_profile.py:710; the registry only knows **crew** callsigns, so a non-crew name → `None`). `None` → `ToolResult(output={"delegated": False, "reason": "target_not_found"})`.
     - **AD-1076 (do NOT gate on momentary liveness):** `resolve()` fills `agent_id` only for an agent whose `is_alive` is True (crew_profile.py:730–735), so a *resting* crew member yields `agent_id=None`. To get the agent OBJECT (needed for `instructions`), go through the agent registry, which does **not** filter on liveness: `agents = getattr(self._runtime, "registry", None).get_by_pool(resolved["agent_type"])` (substrate/registry.py:61 — returns every agent with `.pool == agent_type`, resting included; guard the `None`-registry case). Pick `target = next((a for a in agents if a.id == resolved.get("agent_id")), None) or (agents[0] if agents else None)`. No registry / empty pool → `target_not_found`.
     - **Self-guard:** if `target.id == (context or {}).get("agent_id")` → `target_not_found` (an agent must not delegate to itself).
  4. **Derive the target's run args** (mirror the two existing `executor.run` callsites — cognitive_agent.py:1483 and :3425 — which read these off the agent object):
     - `instructions = getattr(target, "instructions", "") or ""` (the `instructions` attribute, set at cognitive_agent.py:586).
     - `agent_id = target.id`.
     - `department = getattr(target, "department", "") or resolved.get("department", "") or ""`.
     - `rank = str(getattr(target, "rank", "ensign") or "ensign")` — exactly what both existing callsites pass (BF-263: `self.rank` is unset on agents → defaults to `"ensign"`; do **not** add trust-derived rank — the `executor.run` callers don't).
  5. Run a **nested** governed executor (use the Step-2.4 derived vars; pass `extra_context` to thread the depth):
     ```python
     executor = WorkItemAgenticExecutor(llm_client=self._llm_client)  # the tool's own injected client (= parent's self._llm)
     outcome = await executor.run(
         agent_id=agent_id,                # = target.id (Step 2.4)
         instructions=instructions,        # Step 2.4
         task_text=task,
         runtime=self._runtime,
         department=department,            # Step 2.4
         rank=rank,                        # Step 2.4
         thread_id=str((context or {}).get("thread_id", "") or ""),
         max_iterations=self._max_iterations,   # bounded, separate from the parent loop
         tier=self._tier,
         extra_context={"_delegation_depth": depth + 1},  # Step-2.5 additive param
     )
     ```
     The nested run carries `_delegation_depth = depth + 1` so a delegated agent that itself delegates is depth-guarded. **CONFIRMED:** `WorkItemAgenticExecutor.run` has no context-threading param, so add an additive `extra_context: dict | None = None` param (default-None → byte-identical) and merge it into the 4-key context dict at agentic_dispatch.py:629 — build `_context = {… 4 keys …}; if extra_context: _context.update(extra_context)` then pass `context=_context` to `loop.run`. The `_`-prefixed key never collides with the four core keys, so the `.update()` merge order is safe.
  6. Return `ToolResult(output={"delegated": True, "to": <callsign>, "result": outcome.final_text, "stopped_reason": outcome.stopped_reason})`. Tier-2 honest-degrade on any exception.
- **Governance note (state in the docstring):** delegation performs no privileged action itself; the delegated agent runs through the same `WorkItemAgenticExecutor` as the task dispatcher, so its tool-permission grants/restrictions, mesh-intent restrictions, consensus gates on destructive intents, and tool-trace persistence all apply unchanged. (The nested run persists a tool trace via `_persist_tool_trace`; it does **not** itself write a separate episode — episodic storage is a turn-level concern *above* the executor, and the delegated result is folded into the calling agent's turn episode.)

### Step 3 — Register both tools in `WorkItemAgenticExecutor.run`

In [agentic_dispatch.py](../src/probos/cognitive/agentic_dispatch.py), immediately after the `skill_ids` block (which ends ~line 596) and before the `tool_ids` dedup (line 598), add two blocks mirroring the existing pattern:

- **`search_ids` block:** gate on `getattr(agentic_tools_cfg, "tool_search_enabled", False)` and `registry is not None`; idempotent `if registry.get("search_capabilities") is None: registry.register(SearchCapabilitiesTool(runtime=runtime), provider="AD-1072", tags=["search_capabilities","discovery"])`; `search_ids = ["search_capabilities"]`; `except Exception:` → log-and-degrade → `search_ids = []`.
- **`delegate_ids` block:** gate on `getattr(agentic_tools_cfg, "delegation_enabled", False)` and `registry is not None`; idempotent register of `DelegateTaskTool(runtime=runtime, llm_client=self._llm, max_depth=..., max_iterations=..., tier=...)` — pass the executor's own stored client **`self._llm`** (confirmed agentic_dispatch.py:458) and the AD-1072 config values; `delegate_ids = ["delegate_task"]`; `except` → degrade.
- Extend the dedup: `tool_ids = list(dict.fromkeys([*granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids, *search_ids, *delegate_ids]))`.
- Read the AD-1072 config once near the top of `run` (mirror how `exec_cfg` is read at agentic_dispatch.py:546): `agentic_tools_cfg = getattr(getattr(runtime, "config", None), "agentic_tools", None)`.

### Step 4 — Config

In [config.py](../src/probos/config.py), add a focused, default-OFF model and mount it on `SystemConfig` (mirror the `dm_agentic` mount):
```python
class AgenticToolsConfig(BaseModel):
    """AD-1072: conversational-loop discovery + delegation tools (default-OFF)."""
    tool_search_enabled: bool = False
    delegation_enabled: bool = False
    delegation_max_depth: int = Field(default=1, ge=0, le=3)
    delegation_max_iterations: int = Field(default=5, ge=1, le=25)
    delegation_tier: str = "standard"
```
Mount: `agentic_tools: AgenticToolsConfig = Field(default_factory=AgenticToolsConfig)`. **No `config/system.yaml` edit** (model defaults keep a default install byte-identical). CONFIRMED mount pattern: `dm_agentic` is mounted on `SystemConfig` at config.py:6092 and `class DmAgenticConfig` is at config.py:5720; **no existing `agentic_tools` field** → no collision. Mount `agentic_tools` beside `dm_agentic` (~config.py:6092).

### Step 5 — Tests

Follow the AD-1066/1068 pattern (BF-287 **real** fixtures — real `ToolRegistry`, real `WorkItemAgenticExecutor`, scripted-LLM loop; **no MagicMock** at the registry/executor boundary). Naming: `tests/test_ad1072_search_capabilities_tool.py` and `tests/test_ad1072_delegate_task_tool.py` (or one combined `test_ad1072_agentic_tools.py`).

Required cases:
- **search:** returns ranked results for a real catalog; `kind` filter narrows; empty query → empty result (no error); honest-degrade on a raising catalog.
- **delegation depth guard:** at `_delegation_depth == max_depth` the tool refuses **without** constructing a nested executor (assert the nested run never starts — e.g. a counting fake).
- **delegation happy path:** a scripted-LLM nested executor returns `final_text` that surfaces as `output["result"]`; the nested run receives `_delegation_depth == depth + 1`.
- **delegation target resolution:** unknown / self / non-crew callsign → `{"delegated": False, "reason": "target_not_found"}` (no error).
- **registration gating:** with both flags off, `run` registers neither tool (`registry.get("search_capabilities") is None` and `... "delegate_task" is None`) and `tool_ids` is byte-identical to today; with flags on, each is registered exactly once (idempotent on a second `run`).
- **end-to-end (the headline):** a scripted parent loop emits a `delegate_task` call → a nested governed executor runs the target agent → its result returns into the parent transcript.

---

## Verify-first checklist — ALL RESOLVED at HEAD (facts baked into the steps above; re-grep only if the file drifted)

1. **Executor llm_client attribute:** CONFIRMED `self._llm` (agentic_dispatch.py:458) — the `delegate_ids` registration passes `llm_client=self._llm`. Do **not** use `self._llm_client` (it does not exist on the executor).
2. **`WorkItemAgenticExecutor.run` signature:** CONFIRMED `run(*, agent_id, instructions, task_text, runtime, department="", rank="ensign", thread_id="", max_iterations=None, tier=None)` at agentic_dispatch.py:460–471. **No `extra_context` param exists** → add the additive `extra_context: dict | None = None` and merge into the 4-key `context={...}` dict at agentic_dispatch.py:629 (default-None → byte-identical).
3. **Callsign → agent resolution:** CONFIRMED `runtime.callsign_registry.resolve(callsign)` → dict (crew_profile.py:710), but its `agent_id` is liveness-gated (`is_alive`, crew_profile.py:730–735). Get the agent OBJECT via `runtime.registry.get_by_pool(agent_type)` (substrate/registry.py:61 — **not** liveness-filtered; falls back to a resting agent, honoring the AD-1076 lesson). Attributes: `instructions` (cognitive_agent.py:586), `id`, `department`, `rank` read off the agent object exactly as the existing `executor.run` callsites do (cognitive_agent.py:1483, :3425).
4. **`list_capability_catalog` direct call:** CONFIRMED `async def` at routers/tools.py:44; callable as `await list_capability_catalog(runtime)`. Returns `tools`/`skills`/`mesh_intents`/`mcp_servers`/`counts`; **the tool item id key is `id` (not `tool_id`)** and `mesh_intents` items have **no `domain`** (see Search-target seam above).
5. **`SystemConfig` mount point:** CONFIRMED `dm_agentic` mounted at config.py:6092 (`class DmAgenticConfig` at :5720); **no existing `agentic_tools` field** → no collision. Mount `agentic_tools` the same way (~config.py:6092).
6. **Loop tool-definition helper:** CONFIRMED `tool_registration_to_llm_definition(reg)` at swe_harness/tool_call.py:96 reads `reg.tool.input_schema` (:108) into the LLM `parameters` field → both new tools' `input_schema` is surfaced to the LLM.

---

## Acceptance criteria

- Both tools implement the `Tool` protocol and honest-degrade (never raise out of `invoke`).
- With `agentic_tools.tool_search_enabled=False` and `delegation_enabled=False` (defaults), `WorkItemAgenticExecutor.run` is byte-identical: neither tool registered, `tool_ids` unchanged. Prove with a test.
- Delegation cannot recurse past `delegation_max_depth` (default 1) and runs only through `WorkItemAgenticExecutor` (no raw agent calls, no `direct_message`, no `QuorumEngine` hand-roll).
- `tests/test_ad1072_*` green; report the count. Run the focused gate plus the blast-radius importers (`tests/test_ad1066_*`, `tests/test_ad1068_*`, `tests/test_config.py`) and report which subset ran.
- No `config/system.yaml` change. No edits outside: the two new tool files, `agentic_dispatch.py` (registration + optional `extra_context`), `config.py` (new model + mount), and the new test file(s).
- Update PROGRESS.md (an `**AD-1072 shipped**` line) and DECISIONS.md (an `### AD-1072` heading) in the same commit. Note the epic #1006 doc-log lag: DECISIONS.md is behind at AD-1054, so append an AD-1072 heading without renumbering.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (scope guards)

- **Do not** add auto-routing / best-capability-match delegation (explicit `to` callsign only in v1).
- **Do not** wire delegation into the group / ward-room fan-out (1:1 conversational loop + the task dispatcher path only).
- **Do not** add new MCP tools or a new sandbox tier.
- **Do not** touch epic #882 (collaboration rooms / project tasks) or the AD-1070 reply-tag retirement.
- **Do not** make `search_capabilities` mutate anything — it is read-only.
- **Do not** create a new top-level AD number; AD-1072 is the reserved epic #1006 sub-number.
