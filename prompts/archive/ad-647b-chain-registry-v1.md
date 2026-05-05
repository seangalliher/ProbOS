# AD-647b v1 — Process Chain Registry + BF-209 Bypass Removal

**Status:** Draft (Wave 48)
**Depends on:** AD-647 v1 (Wave 34, shipped)
**Closes:** GH issue #404
**Estimated tests:** ≥10 (target 12)

---

## Problem

AD-647 v1 (Wave 34) shipped `ProcessChainStepKind` / `ProcessChainStep` /
`ProcessChainDefinition` / `ProcessChainExecutor` in
`src/probos/cognitive/process_chains.py`. ScoutAgent uses a per-invocation
inline-constructed chain inside `act()` (handlers are bound methods
`self._scout_step_*`).

Two problems remain:

1. **No registry.** Chains live wherever they happen to be constructed.
   No introspection, no replacement, no central registration. AD-647c
   (Bills/Watch Bill integration) and AD-647 future-LLM-templates need
   a discoverable registry.

2. **BF-209 bypass still in place.** `ScoutAgent._should_activate_chain`
   (`scout.py:253`) overrides the base-class gate to return `False` for
   `proactive_think` with `duty_id == "scout_report"`. This prevents the
   AD-632 communication chain (`SubTaskExecutor`) from competing with
   the AD-647 process chain on the same intent. The override is a
   per-agent opt-out — it does not generalize.

AD-647b ships the registry, generalizes the BF-209 bypass into a base-class
hook keyed off a class attribute, and migrates Scout to use the registry
end-to-end.

---

## Solution overview

1. New `ProcessChainRegistry` in `src/probos/cognitive/process_chains.py`
   storing `ProcessChainDefinition` keyed by `chain_id: str`. API matches
   user spec exactly: `register_chain(definition)`, `get_chain(chain_id)`,
   `list_chains()`, `unregister_chain(chain_id)`. Duplicate registrations
   replace with WARNING log (mirrors `ToolRegistry.register` precedent at
   `tools/registry.py:113`).

2. Class attribute `process_chain_id: str | None = None` on `CognitiveAgent`.
   `CognitiveAgent._should_activate_chain` short-circuits to `False` when
   `self.process_chain_id` is set AND the observation is duty-triggered
   with `duty_id == self.process_chain_id`. This generalizes BF-209.

3. **Scout handler refactor.** The four `_scout_step_*` methods move from
   bound instance methods to module-level functions in `scout.py` that
   read `_agent` from the chain context dict. The chain definition then
   becomes a static module-level constant `SCOUT_REPORT_CHAIN`. This
   matches user spec: `register_chain(definition)` accepts a
   `ProcessChainDefinition`, not a per-agent factory.

4. **Scout migration.** `ScoutAgent.process_chain_id = "scout_report"`.
   `act()` looks up `chain = runtime.process_chain_registry.get_chain("scout_report")`
   and runs it via `ProcessChainExecutor` with
   `context={"_agent": self, "llm_output": llm_output}`. Existing
   `act()` scaffolding (early returns for `direct_message` /
   `ward_room_notification` / non-duty `proactive_think` /
   "No new repositories") is retained — registry lookup happens after
   those gates. The `_should_activate_chain` override is REMOVED
   (BF-209 closure).

5. New `ProcessChainRegistryConfig` Pydantic model with `enabled: bool = True`
   on `SystemConfig`. New `_wire_process_chain_registry` wirer in
   `startup/finalize.py` that creates the registry on
   `runtime.process_chain_registry` and registers `SCOUT_REPORT_CHAIN`.

### Architect calls

- **DLog #1 — handlers move to module level.** Wave 34 handlers were bound
  to the agent because they reach `self._reports_dir` /
  `self._pending_seen_repos` / `self._deliver_discord` / `self.id`. The
  registry stores definitions, not factories — handlers cannot be
  per-instance bound. Refactor: each handler becomes
  `async def _scout_step_X(ctx: dict[str, Any]) -> dict[str, Any]` and
  reads `agent = ctx["_agent"]` then `agent._reports_dir`, etc. This is
  the correct long-term shape (handlers are stateless w.r.t. instance;
  agent reached through context). The refactor is mechanical.

- **DLog #2 — hook lives on `_should_activate_chain`, NOT `act()`.** The
  user spec wrote "the agent's `act()` is wrapped (or default `act()`
  implementation calls)…". I pick "or" path: Scout's `act()` retains its
  scaffolding and explicitly invokes the registry. The base class does
  NOT get a default `act()` that auto-runs chains — `CognitiveAgent.act()`
  already has substantial logic (chain-result aggregation, validation)
  that we don't want to fork. The cleaner hook is on
  `_should_activate_chain`, which is exactly what BF-209 overrides.
  Generalizing it into the base class is the BF-209 closure.

- **DLog #3 — duplicate-registration semantics.** Replace + WARNING
  (matches `ToolRegistry.register` at `tools/registry.py:113`). User
  spec said "pick one and document"; replacement is more useful for
  hot-reload / test isolation than rejection.

- **DLog #4 — registry NEVER raises** on lookup miss. `get_chain(unknown)`
  returns `None` (Demeter-friendly; caller decides fallback).
  `unregister_chain(unknown)` returns `False` (no-op, no exception).

- **DLog #5 — `enabled=True` default.** Registry construction cost is one
  empty dict + one `register_chain(SCOUT_REPORT_CHAIN)` call at boot.
  Disabling means Scout's `act()` falls back to `None` and currently has
  no inline-construction fallback path — disabling would break Scout.
  Same precedent as `KnowledgeEdgesConfig` / `EdgeBackfillConfig` /
  `ConsultationWorkspaceConfig`. Documented in the config docstring.

- **DLog #6 — backward-compat invariant.** All 8 existing
  `tests/test_ad647_process_chains.py` tests must continue to pass.
  The end-to-end Scout test
  (`test_scout_act_runs_through_process_chain`) bypasses the spawner via
  `ScoutAgent.__new__` and sets `_runtime = None`. After AD-647b, that
  test expects `runtime.process_chain_registry` to be reachable — not
  through `_runtime=None`. Update the test fixture to inject a minimal
  runtime stub carrying `process_chain_registry` populated with
  `SCOUT_REPORT_CHAIN`. Pure test scaffolding amendment; ScoutAgent
  semantics unchanged.

---

## Verified Against Codebase (2026-05-04)

```text
grep -n "class ProcessChainExecutor" src/probos/cognitive/process_chains.py
  108: class ProcessChainExecutor:

grep -n "_should_activate_chain" src/probos/cognitive/scout.py
  253:    def _should_activate_chain(self, observation: dict) -> bool:
  268:        return super()._should_activate_chain(observation)

grep -n "_should_activate_chain" src/probos/cognitive/cognitive_agent.py
  1685:    def _should_activate_chain(self, observation: dict) -> bool:

grep -n "class ScoutAgent" src/probos/cognitive/scout.py
  206: class ScoutAgent(CognitiveAgent):

grep -n "_scout_step_" src/probos/cognitive/scout.py
  414:                    handler=self._scout_step_parse_and_mark_seen,
  419:                    handler=self._scout_step_enrich_and_filter,
  424:                    handler=self._scout_step_persist_report,
  429:                    handler=self._scout_step_notify_and_deliver,
  449:    async def _scout_step_parse_and_mark_seen
  475:    async def _scout_step_enrich_and_filter
  489:    async def _scout_step_persist_report
  506:    async def _scout_step_notify_and_deliver

grep -n "class ToolRegistry" src/probos/tools/registry.py
  49: class ToolRegistry:
  113:        if tool.tool_id in self._tools:
  114:            logger.warning("Replacing existing tool registration: %s", tool.tool_id)

grep -n "def _wire_consultation_workspaces" src/probos/startup/finalize.py
  515: def _wire_consultation_workspaces(*, runtime: Any, config: "SystemConfig") -> bool:

grep -n "consultation_workspaces: ConsultationWorkspaceConfig" src/probos/config.py
  2260:    consultation_workspaces: ConsultationWorkspaceConfig = Field(
```

No collision: `runtime.process_chain_registry` is fresh
(`grep -rn "process_chain_registry" src/probos/` returns 0 hits).
No `process_chain_id` collision on `CognitiveAgent` or `BaseAgent`.

---

## Implementation

### Section 1: `ProcessChainRegistry` in `process_chains.py`

Append below `ProcessChainExecutor` at the end of the module:

```python
===FILE: src/probos/cognitive/process_chains.py (append)===
class ProcessChainRegistry:
    """AD-647b v1 — runtime catalog of `ProcessChainDefinition` keyed by chain_id.

    Public API:
        register_chain(definition)       -> None        (replace + WARN on duplicate)
        get_chain(chain_id)              -> ProcessChainDefinition | None
        list_chains()                    -> list[str]   (sorted chain_ids)
        unregister_chain(chain_id)       -> bool        (False if absent)

    Registration uses ``definition.name`` as the chain_id. Builders that
    need to disambiguate two chains with the same human-readable name
    must distinguish them at definition construction (not at registration).
    """

    def __init__(self) -> None:
        self._chains: dict[str, ProcessChainDefinition] = {}

    def register_chain(self, definition: ProcessChainDefinition) -> None:
        chain_id = definition.name
        if chain_id in self._chains:
            logger.warning(
                "AD-647b: replacing existing process chain registration: %s",
                chain_id,
            )
        self._chains[chain_id] = definition

    def get_chain(self, chain_id: str) -> ProcessChainDefinition | None:
        return self._chains.get(chain_id)

    def list_chains(self) -> list[str]:
        return sorted(self._chains.keys())

    def unregister_chain(self, chain_id: str) -> bool:
        return self._chains.pop(chain_id, None) is not None
```

### Section 2: `process_chain_id` hook on `CognitiveAgent`

Add the class attribute next to other class attributes (search for the
existing `_handled_intents: set[str] = set()` declaration on
`CognitiveAgent` and insert after it; if not present, place near the
other declarative class attributes in the class body).

```python
===SEARCH===
class CognitiveAgent(BaseAgent):
===REPLACE===
class CognitiveAgent(BaseAgent):
    # AD-647b v1: agents that own a registered ProcessChainDefinition set
    # this to the chain_id ("name" of the definition). When set, the
    # AD-632 communication-chain gate (_should_activate_chain) returns
    # False for any observation whose duty_id matches — the agent runs
    # its process chain via runtime.process_chain_registry instead.
    process_chain_id: str | None = None
===END REPLACE===
```

Modify `_should_activate_chain` (the AD-632f gate at
`cognitive_agent.py:1685`) to short-circuit when the duty matches:

```python
===SEARCH===
    def _should_activate_chain(self, observation: dict) -> bool:
        """AD-632f: Evaluate whether this observation warrants a multi-step chain.

        Gates (evaluated in order, first failure short-circuits):
          0. Executor exists and is enabled
          1. Intent type is in _CHAIN_ELIGIBLE_INTENTS
        """
        # Gate 0: executor readiness
        if self._sub_task_executor is None:
            return False
        if not self._sub_task_executor.enabled:
            return False
        # Gate 1: intent type filter
        intent = observation.get("intent", "")
        if intent not in _CHAIN_ELIGIBLE_INTENTS:
            logger.debug(
                "AD-632f: Chain skipped for %s (intent=%s not eligible)",
                self.agent_type, intent,
            )
            return False
        return True
===REPLACE===
    def _should_activate_chain(self, observation: dict) -> bool:
        """AD-632f: Evaluate whether this observation warrants a multi-step chain.

        Gates (evaluated in order, first failure short-circuits):
          0. AD-647b — observation is a duty-triggered proactive_think for the
             agent's registered process_chain_id (agent runs the process chain,
             not the comm chain). Generalizes BF-209.
          1. Executor exists and is enabled
          2. Intent type is in _CHAIN_ELIGIBLE_INTENTS
        """
        # Gate 0 (AD-647b): process-chain owners skip the comm chain when
        # the duty matches their registered chain_id.
        if self.process_chain_id is not None:
            intent = observation.get("intent", "")
            if intent == "proactive_think":
                duty = (observation.get("params") or {}).get("duty") or {}
                if duty.get("duty_id") == self.process_chain_id:
                    return False
        # Gate 1: executor readiness
        if self._sub_task_executor is None:
            return False
        if not self._sub_task_executor.enabled:
            return False
        # Gate 2: intent type filter
        intent = observation.get("intent", "")
        if intent not in _CHAIN_ELIGIBLE_INTENTS:
            logger.debug(
                "AD-632f: Chain skipped for %s (intent=%s not eligible)",
                self.agent_type, intent,
            )
            return False
        return True
===END REPLACE===
```

### Section 3: Scout handler refactor — bound methods → module-level

Move all four `_scout_step_*` methods out of the `ScoutAgent` class body
and onto module-level functions. Each function receives `ctx: dict` and
reads `agent = ctx["_agent"]`. Build the static `SCOUT_REPORT_CHAIN`
constant.

The Builder must:

1. Replace the four `async def _scout_step_*` instance methods (currently
   at `scout.py:449/475/489/506`) with their module-level equivalents.
   Move the function bodies verbatim, replacing `self.X` with `agent.X`
   where `agent = ctx["_agent"]`. The internal `await self._deliver_discord(...)`
   call in `_scout_step_notify_and_deliver` becomes
   `await agent._deliver_discord(...)` — `_deliver_discord` stays as a
   bound instance method (it reads `self._runtime`, `self.config`, etc.).

2. Replace the inline `chain = ProcessChainDefinition(...)` block in
   `act()` (currently at `scout.py:407–434`) with a registry lookup
   plus a context dict that includes `_agent`.

Find a good insertion point for the module-level handlers — between
`_save_seen` (~line 200) and `class ScoutAgent` (line 206). Place
`SCOUT_REPORT_CHAIN` immediately after the four handlers.

```python
===SEARCH===
class ScoutAgent(CognitiveAgent):
    """GitHub intelligence scout -- finds AI agent projects relevant to ProbOS."""
===REPLACE===
# ----------------------------------------------------------------------
# AD-647 v1 / AD-647b v1: Scout process-chain handlers.
#
# Handlers are module-level (NOT bound to ScoutAgent) so the chain
# definition can be a static module-level constant registered with
# `runtime.process_chain_registry`. Each handler reads the agent from
# `ctx["_agent"]` and reaches per-instance state via the agent reference.
# ----------------------------------------------------------------------

async def _scout_step_parse_and_mark_seen(ctx: dict[str, Any]) -> dict[str, Any]:
    """TRANSFORM: parse ===SCOUT_REPORT=== blocks, mark seen on success."""
    agent = ctx["_agent"]
    llm_output = ctx.get("llm_output", "") or ""
    findings = parse_scout_reports(llm_output)

    # BF-214: mark seen only after classification succeeds
    # (succeeded = at least one ===SCOUT_REPORT=== block parsed, even if all are SKIP).
    _pending = getattr(agent, "_pending_seen_repos", [])
    _classification_succeeded = bool(findings) or "===SCOUT_REPORT===" in llm_output
    if _pending and _classification_succeeded:
        seen = _load_seen(agent._seen_file)
        _now = datetime.now(timezone.utc).isoformat()
        for repo_name in _pending:
            seen[repo_name] = _now
        _save_seen(seen, agent._seen_file)
        logger.info("Scout: marked %d repos as seen after classification", len(_pending))
        agent._pending_seen_repos = []
    elif _pending and not _classification_succeeded:
        logger.warning(
            "Scout: classification failed — %d repos NOT marked as seen, will retry next cycle",
            len(_pending),
        )
        agent._pending_seen_repos = []

    return {"findings": findings}


async def _scout_step_enrich_and_filter(ctx: dict[str, Any]) -> dict[str, Any]:
    """TRANSFORM: enrich findings with repo metadata, filter by relevance."""
    agent = ctx["_agent"]
    findings: list[ScoutFinding] = ctx.get("findings", []) or []
    metadata = getattr(agent, "_repo_metadata", {})
    for f in findings:
        meta = metadata.get(f.repo_full_name, {})
        f.language = meta.get("language", f.language)
        f.license = meta.get("license", f.license)
        f.topics = meta.get("topics", f.topics)

    filtered = filter_findings(findings, min_relevance=3)
    agent._last_findings = filtered
    return {"filtered": filtered, "total_classified": len(findings)}


async def _scout_step_persist_report(ctx: dict[str, Any]) -> dict[str, Any]:
    """STORE: write the day's report JSON to the reports directory."""
    agent = ctx["_agent"]
    filtered: list[ScoutFinding] = ctx.get("filtered", []) or []
    total_classified: int = ctx.get("total_classified", 0)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    agent._reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = agent._reports_dir / f"{date_str}.json"
    report_data = {
        "date": date_str,
        "total_classified": total_classified,
        "total_relevant": len(filtered),
        "findings": [asdict(f) for f in filtered],
    }
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    return {"date_str": date_str, "report_path": str(report_path)}


async def _scout_step_notify_and_deliver(ctx: dict[str, Any]) -> dict[str, Any]:
    """NOTIFY: post high-scoring findings to notification queue + deliver to Discord."""
    agent = ctx["_agent"]
    filtered: list[ScoutFinding] = ctx.get("filtered", []) or []
    date_str: str = ctx.get("date_str", "unknown")

    if agent._runtime and hasattr(agent._runtime, "notification_queue"):
        for f in filtered:
            if f.composite_score >= 4:
                agent._runtime.notification_queue.notify(
                    agent_id=agent.id,
                    agent_type="scout",
                    department="science",
                    title=f"Scout: {f.repo_full_name}",
                    detail=f"[{f.classification}] {f.summary}",
                    notification_type="info",
                    action_url=f.url,
                )

    await agent._deliver_discord(filtered, date_str)
    digest = format_digest(filtered, date_str)
    return {"digest": digest}


SCOUT_REPORT_CHAIN: ProcessChainDefinition = ProcessChainDefinition(
    name="scout_report",
    description="Scout: parse classification → enrich → filter+store → notify.",
    steps=(
        ProcessChainStep(
            kind=ProcessChainStepKind.TRANSFORM,
            name="parse_and_mark_seen",
            handler=_scout_step_parse_and_mark_seen,
        ),
        ProcessChainStep(
            kind=ProcessChainStepKind.TRANSFORM,
            name="enrich_and_filter",
            handler=_scout_step_enrich_and_filter,
        ),
        ProcessChainStep(
            kind=ProcessChainStepKind.STORE,
            name="persist_report",
            handler=_scout_step_persist_report,
        ),
        ProcessChainStep(
            kind=ProcessChainStepKind.NOTIFY,
            name="notify_and_deliver",
            handler=_scout_step_notify_and_deliver,
        ),
    ),
)


class ScoutAgent(CognitiveAgent):
    """GitHub intelligence scout -- finds AI agent projects relevant to ProbOS."""
===END REPLACE===
```

Set the class attribute:

```python
===SEARCH===
    agent_type = "scout"
    tier = "domain"
    instructions = _INSTRUCTIONS
===REPLACE===
    agent_type = "scout"
    tier = "domain"
    instructions = _INSTRUCTIONS
    process_chain_id = "scout_report"  # AD-647b v1
===END REPLACE===
```

Remove the BF-209 `_should_activate_chain` override (the entire method
body at `scout.py:253–268`):

```python
===SEARCH===
    def _should_activate_chain(self, observation: dict) -> bool:
        """BF-209: Scout report duty is a structured process, not a communication task.

        The scout report pipeline (parse → enrich → filter → store → notify)
        lives in act(). The communication chain bypasses act() entirely.
        Duty-triggered proactive_think must route through decide() → act().

        Ward room notifications still use the chain (communication task).
        """
        intent = observation.get("intent", "")
        if intent == "proactive_think":
            params = observation.get("params", {})
            duty = params.get("duty", {})
            if duty.get("duty_id") == "scout_report":
                return False
        return super()._should_activate_chain(observation)

    def _resolve_tier(self) -> str:
===REPLACE===
    # AD-647b v1: BF-209 override removed. The base CognitiveAgent
    # _should_activate_chain now generalizes the bypass via process_chain_id.

    def _resolve_tier(self) -> str:
===END REPLACE===
```

Replace the inline-construction `act()` body with registry lookup:

```python
===SEARCH===
        # AD-647 v1: build per-invocation chain (handlers are bound methods)
        chain = ProcessChainDefinition(
            name="scout_report",
            description="Scout: parse classification → enrich → filter+store → notify.",
            steps=(
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM,
                    name="parse_and_mark_seen",
                    handler=self._scout_step_parse_and_mark_seen,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM,
                    name="enrich_and_filter",
                    handler=self._scout_step_enrich_and_filter,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.STORE,
                    name="persist_report",
                    handler=self._scout_step_persist_report,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.NOTIFY,
                    name="notify_and_deliver",
                    handler=self._scout_step_notify_and_deliver,
                ),
            ),
        )
        executor = ProcessChainExecutor()
        try:
            result_ctx = await executor.run(chain, context={"llm_output": llm_output})
        except Exception:
            logger.warning("AD-647: scout_report chain failed; falling back to error result", exc_info=True)
            return {"success": False, "result": "Scout report pipeline failed. See logs."}

        digest = result_ctx.get("digest", "")
        return {"success": True, "result": digest}
===REPLACE===
        # AD-647b v1: look up SCOUT_REPORT_CHAIN via runtime registry.
        registry = getattr(self._runtime, "process_chain_registry", None) if self._runtime else None
        chain = registry.get_chain(self.process_chain_id) if registry else None
        if chain is None:
            logger.warning(
                "AD-647b: process chain '%s' not found in registry; using module-level fallback",
                self.process_chain_id,
            )
            chain = SCOUT_REPORT_CHAIN
        executor = ProcessChainExecutor()
        try:
            result_ctx = await executor.run(
                chain, context={"_agent": self, "llm_output": llm_output}
            )
        except Exception:
            logger.warning("AD-647: scout_report chain failed; falling back to error result", exc_info=True)
            return {"success": False, "result": "Scout report pipeline failed. See logs."}

        digest = result_ctx.get("digest", "")
        return {"success": True, "result": digest}
===END REPLACE===
```

Also DELETE the four `async def _scout_step_*` instance methods at
`scout.py:449/475/489/506` (their bodies were copied to module-level
above). The Builder should remove these via a single MODIFY block once
the module-level versions are in place — leaving them as dead code is
unacceptable per Demeter (they would still be callable as bound methods
and drift from the module-level versions).

```python
===SEARCH===
    # ------------------------------------------------------------------
    # AD-647 v1: Scout process-chain handlers (bound to this agent so
    # handlers can read self._runtime / self._reports_dir / self._seen_file
    # / self._repo_metadata / self._pending_seen_repos).
    # ------------------------------------------------------------------

    async def _scout_step_parse_and_mark_seen(self, ctx: dict[str, Any]) -> dict[str, Any]:
===REPLACE===
    # AD-647b v1: bound _scout_step_* methods removed. Handlers live as
    # module-level functions above; they reach per-instance state via
    # ctx["_agent"]. _deliver_discord remains a bound method (reads
    # self._runtime / self.config / self.id at call time).

    async def _scout_step_parse_and_mark_seen_REMOVED(self, ctx: dict[str, Any]) -> dict[str, Any]:
===END REPLACE===
```

(After the rename above, the Builder must delete the four
`_scout_step_*_REMOVED` method bodies entirely. Easiest path: a second
MODIFY block that deletes the block from `_scout_step_parse_and_mark_seen_REMOVED`
through the end of `_scout_step_notify_and_deliver` body. Builder
discretion on the exact SEARCH anchor — Captain accepts any minimal-diff
deletion that leaves `_deliver_discord` intact.)

### Section 4: Pydantic config

In `src/probos/config.py`, add `ProcessChainRegistryConfig` adjacent to
`ConsultationWorkspaceConfig` (~line 1904):

```python
===SEARCH===
class ConsultationWorkspaceConfig(BaseModel):
===REPLACE===
class ProcessChainRegistryConfig(BaseModel):
    """AD-647b v1: Registry of named process chains (`ProcessChainDefinition`).

    Default-True is intentional — registry construction cost is one empty
    dict + one ``register_chain(SCOUT_REPORT_CHAIN)`` call at boot, and
    Scout's ``act()`` depends on the registry being present (the
    module-level fallback is a defensive belt — disabling the registry
    would still log a WARNING per scout invocation).
    """
    enabled: bool = True


class ConsultationWorkspaceConfig(BaseModel):
===END REPLACE===
```

Wire on `SystemConfig` adjacent to `consultation_workspaces`
(~line 2260):

```python
===SEARCH===
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
===REPLACE===
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    process_chain_registry: ProcessChainRegistryConfig = Field(
        default_factory=ProcessChainRegistryConfig
    )  # AD-647b
===END REPLACE===
```

### Section 5: Finalize wirer

In `src/probos/startup/finalize.py`, add `_wire_process_chain_registry`
adjacent to `_wire_consultation_workspaces` (~line 515):

```python
===SEARCH===
def _wire_consultation_workspaces(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
def _wire_process_chain_registry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-647b v1: Initialize ProcessChainRegistry and register built-in chains.

    Currently registered:
      - SCOUT_REPORT_CHAIN (chain_id="scout_report")
    """
    cfg = getattr(config, "process_chain_registry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.process_chains import ProcessChainRegistry
    from probos.cognitive.scout import SCOUT_REPORT_CHAIN

    registry = ProcessChainRegistry()
    registry.register_chain(SCOUT_REPORT_CHAIN)
    runtime.process_chain_registry = registry
    logger.info(
        "AD-647b: ProcessChainRegistry initialized (chains=%s)",
        registry.list_chains(),
    )
    return True


def _wire_consultation_workspaces(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

Invoke from the cascade in `finalize_startup`. Place adjacent to the
existing `_wire_consultation_workspaces` invocation
(~`finalize.py:853`):

```python
===SEARCH===
    if _wire_consultation_workspaces(runtime=runtime, config=config):
        logger.info("AD-594a: WorkspaceRegistry v1 wired during finalization")
===REPLACE===
    if _wire_process_chain_registry(runtime=runtime, config=config):
        logger.info("AD-647b: ProcessChainRegistry v1 wired during finalization")

    if _wire_consultation_workspaces(runtime=runtime, config=config):
        logger.info("AD-594a: WorkspaceRegistry v1 wired during finalization")
===END REPLACE===
```

### Section 6: Update `tests/test_ad647_process_chains.py`

The existing `test_scout_act_runs_through_process_chain` test sets
`agent._runtime = None`. After AD-647b, Scout's `act()` looks up the
registry on `self._runtime.process_chain_registry`. With `_runtime = None`,
the lookup returns `None` and `act()` falls back to the module-level
`SCOUT_REPORT_CHAIN` constant — this path still works, but it logs a
WARNING and the test would now produce noise.

Builder amendment: replace `agent._runtime = None` with a minimal stub
that exposes `process_chain_registry`:

```python
===SEARCH===
    agent = ScoutAgent.__new__(ScoutAgent)  # bypass spawner ctor — we wire the minimum we need
    agent.id = "scout-test"
    agent._runtime = None  # no notification queue, no discord
===REPLACE===
    agent = ScoutAgent.__new__(ScoutAgent)  # bypass spawner ctor — we wire the minimum we need
    agent.id = "scout-test"
    # AD-647b: minimal runtime stub with the chain registry; no notification queue / discord.
    from types import SimpleNamespace
    from probos.cognitive.process_chains import ProcessChainRegistry
    from probos.cognitive.scout import SCOUT_REPORT_CHAIN
    _registry = ProcessChainRegistry()
    _registry.register_chain(SCOUT_REPORT_CHAIN)
    agent._runtime = SimpleNamespace(process_chain_registry=_registry)
===END REPLACE===
```

---

## Test plan — ≥10 (target 12)

New file `tests/test_ad647b_chain_registry.py`:

1. `test_registry_register_get_list` — register one definition; `get_chain` returns it; `list_chains` returns `["scout_report"]`.
2. `test_registry_get_unknown_returns_none` — empty registry; `get_chain("nope")` returns `None`.
3. `test_registry_unregister_returns_true_when_present` — register, unregister, returns `True`; `get_chain` then returns `None`.
4. `test_registry_unregister_unknown_returns_false` — fresh registry; `unregister_chain("nope")` returns `False`.
5. `test_registry_duplicate_registration_replaces_with_warning` — register definition A under name `"x"`, register definition B under same name; `caplog` captures WARNING; `get_chain("x")` returns B (object identity).
6. `test_should_activate_chain_returns_false_when_process_chain_id_matches_duty` — minimal subclass of `CognitiveAgent` with `process_chain_id = "scout_report"`; observation `{"intent": "proactive_think", "params": {"duty": {"duty_id": "scout_report"}}}`; `_should_activate_chain` returns `False` even when `_sub_task_executor.enabled=True` and intent is in `_CHAIN_ELIGIBLE_INTENTS`.
7. `test_should_activate_chain_falls_through_when_process_chain_id_is_none` — base `CognitiveAgent` (no override); same proactive_think duty observation; behavior matches the pre-AD-647b path (executor-readiness gate + intent gate).
8. `test_should_activate_chain_falls_through_when_duty_id_mismatches` — `process_chain_id="scout_report"` but observation duty has `duty_id="other"`; falls through to gate 1+2.
9. `test_scout_agent_class_attribute_is_scout_report` — `ScoutAgent.process_chain_id == "scout_report"`.
10. `test_scout_no_longer_overrides_should_activate_chain` — `ScoutAgent._should_activate_chain is CognitiveAgent._should_activate_chain` (Python method lookup; assert the function objects are identical, confirming the override is gone).
11. `test_module_level_handler_reads_agent_from_context` — call `_scout_step_enrich_and_filter` with a `SimpleNamespace`-style stub agent + a synthetic `findings` list; assert filtered/total_classified shape.
12. `test_wirer_registers_scout_report_chain` — invoke `_wire_process_chain_registry` against a `SimpleNamespace` runtime + a real `SystemConfig()`; assert `runtime.process_chain_registry.list_chains() == ["scout_report"]` and the registered chain's first step name is `"parse_and_mark_seen"`.

Test floor is 10; targeting 12 (over by 2). Drop targets if drift:
test #4 (covered by #3 mechanism) and test #8 (covered by #6/#7 logic).

**Backward compat invariant:** all 8 existing tests in
`tests/test_ad647_process_chains.py` must continue to pass after the
Section 6 amendment.

**BF-209 grep-marker check** is implicitly covered by test #10 (the
override has been removed). No separate grep test required.

---

## What this AD does NOT change

- **No NATS / Bills / Watch Bill integration.** That is AD-647c
  (Wave 49, GH issue #405).
- **No parallel / conditional / rollback steps.** v1 stays sequential.
- **No LLM step templates.** `prompt_template_id` field on
  `ProcessChainStep` remains rejected at construction (AD-647 v1
  invariant).
- **No registry persistence.** Registry is in-memory only.
- **No HXI surface.** `list_chains()` is not exposed via REST or shell.
- **No `_deliver_discord` refactor.** It remains a bound instance
  method; only the four step methods move to module level.
- **No `BaseAgent` change.** `process_chain_id` lives on
  `CognitiveAgent` (Scout's actual parent). If a future non-cognitive
  agent needs process chains, AD-647d can promote.

---

## Tracking

Update on completion:

- `PROGRESS.md` — prepend AD-647b CLOSED entry with full summary.
- `docs/development/roadmap.md` — flip AD-647b status to Complete.
- `DECISIONS.md` — prepend AD-647b decision entry under Era V.

---

## Acceptance criteria

- [ ] All sections applied; full file diff shows no surprise deletions.
- [ ] `_scout_step_*` instance methods are removed from `ScoutAgent`;
      module-level functions read `_agent` from `ctx`.
- [ ] `ScoutAgent._should_activate_chain` override is removed; behavior
      preserved via `process_chain_id` attribute + base-class hook.
- [ ] `runtime.process_chain_registry` is populated at finalize with
      `SCOUT_REPORT_CHAIN` registered.
- [ ] All 12 new tests in `tests/test_ad647b_chain_registry.py` pass.
- [ ] All 8 existing `tests/test_ad647_process_chains.py` tests still
      pass (with the Section 6 amendment).
- [ ] Phantom-API pre-check on this prompt and on the touched source
      files reports zero NEW phantoms (allowed FPs documented in the
      dispatch).
- [ ] Full gate `pytest tests/ -q -n 8 --dist=loadfile` shows
      `11146 passed` (11134 + 12) or higher; no new xdist environmental
      failures.
- [ ] Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.
