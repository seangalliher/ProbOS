# AD-1139 — Governed Oracle query tool for the AgenticLoop (Σ reachable) (tools / cognitive)

**Issue: #1060 · Epic #1057 (Σ) · depends on BF-675 (#1058) and AD-1138 (#1059), both in-tree.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1139** (#1060). AD-1144–1151 assigned (#1069–#1076). No new BF.**

Give crew agents a governed, read-only tool to query the shared knowledge commons **during** a task — Σ tiers only, never episodic — with provenance and disposition framing carried inline. Default-OFF.

---

## Why / context

Σ reaches agents only **passively** today: the Oracle result is injected as `observation["_oracle_context"]` during `perceive`, and only for agents resolving to `RecallTier.ORACLE` = `Rank.SENIOR` (`src/probos/cognitive/cognitive_agent.py:9296`, `src/probos/earned_agency.py:62`). An agent working a task cannot ask the ship a question.

Crew children have no Σ access at all — their tool set is mesh (`web_search`/`read_page`/`http_fetch`) plus `run_python`, `use_skill`, `search_capabilities`, `delegate_task`, `event_log_query` (`src/probos/cognitive/agentic_dispatch.py`, the `tool_ids` assembly).

---

## Pinned design decisions

### DD-1 — Σ tiers only; never Tier 1 episodic (LOAD-BEARING)
The tool hard-codes its tier list: `records`, `semantic`, `graph`, `archive`, `operational`, `health`. It **never** passes `episodic`, and never accepts a caller-supplied tier list that could add it.

Consequences: no sovereignty surface at all (Tier 1 = **A**, the sovereign shard; Tiers 2–7 = **Σ**, the commons — see `_apply_access_policy`, `src/probos/cognitive/oracle_service.py:589`); the tool is strictly **weaker** than the existing passive ORACLE-tier injection, so it is not a privilege escalation; and it composes with BF-675 so "Σ tiers only" is genuinely episode-free.

### DD-2 — Framing is mandatory and must be INLINE (LOAD-BEARING)
Past live testing showed agents finding Oracle content jarring — it "just appeared" with no explanation. Deliberate work fixed that and this AD must not regress it.

The existing framing wrapper is applied at the **consumer**, not the Oracle (`src/probos/cognitive/sub_tasks/analyze.py:128`, `compose.py:495`):

```
## Cross-Tier Knowledge (Ship's Records)

These are NOT your personal experiences. They are from the ship's shared
knowledge stores. Treat as reference material, not memory.
```

**The trap:** `AgenticLoop` has no such wrapper. It renders tool results as bare content (legacy text path, or the AD-1146 `role:"tool"` entries). A naive tool would deliver raw Σ text straight into a crew child.

So the tool's own `ToolResult` output carries framing **inline**:
- a short **disposition preamble** modelled on `_VISUAL_DISPOSITION` (`src/probos/perception/working_memory.py:28`, AD-1059) — parenthetical, states default behaviour plus explicit exceptions, no imperative;
- **per-item provenance** via `ProvenanceEnvelope.render()` → `[source:records confidence:0.82 age:3m]` (`src/probos/cognitive/provenance.py`, AD-677). `query_with_provenance()` is the ready-made helper — prefer it over hand-rolling.

The framing must state: where it came from, that it is **not** the agent's own memory, how much to trust it, and that citing it is expected while narrating it is not.

### DD-3 — Wording must be gap-regex safe
All injected/teaching text must NOT match `_CAPABILITY_GAP_RE` (`src/probos/cognitive/decomposer.py:33`) — no "can't", "cannot", "unable to", "don't have", "not available/supported/possible", "outside scope". Use "do not" (with a space). **Assert with the real imported regex.**

### DD-4 — Bounded output, counted against the sensorium budget
`SensoriumConfig.warning_chars = 10000` (`src/probos/config.py:3735`). Tool output must be bounded (cap results and total characters). AD-1148's `truncate_tool_output` exists in `swe_harness/agentic_loop.py` — reuse the concept; do not duplicate the helper if it can be imported cleanly.

### DD-5 — Registration mirrors `event_log_query` exactly
Follow `_register_event_log_query_tool` (`src/probos/startup/communication.py:40`): `tool_registry.register(tool, provider=…, tags=[…], allowed_departments=(…), default_permissions={rank: perm})`, and offer it in `agentic_dispatch.py` via `registry.check_permission(agent_id, "oracle_query", ToolPermission.READ, agent_department=department, agent_rank=rank)` with silent honest-degrade when denied.

**Grant: all six departments** — engineering, science, medical, security, operations, bridge (`src/probos/cognitive/standing_orders.py:40`) — and `ensign: read` upward. A commons that excludes half the ship is not a commons, and a narrower grant would silently starve some crew children of Σ and corrupt the AD-1143 ablation.

### DD-6 — Read-only, never mutating
No write path. `ToolPermission.READ` only. Honest-degrade to an empty-but-framed result on any Oracle failure; never raise.

---

## Build

1. **NEW `src/probos/tools/oracle_query_tool.py`** — `OracleQueryTool` (Tool protocol, `tool_id="oracle_query"`), mirroring `src/probos/tools/event_log_query_tool.py` in structure. `invoke(params={query, kind?}, context={agent_id, department, rank, thread_id})`. Hard-coded Σ tier list. Framed, provenance-tagged, bounded output.
2. **Registration** in `startup/communication.py` mirroring `_register_event_log_query_tool`, gated on a new default-OFF config flag.
3. **Offer** in `cognitive/agentic_dispatch.py` — an `oracle_ids` block beside `event_log_ids`, permission-checked, added to the `tool_ids` dedup list.
4. **Config** — new default-`False` flag; choose the clearest home (`AgenticToolsConfig` is the closest sibling — verify at build).
5. **Tests** — `tests/test_ad1139_oracle_query_tool.py`.

## Acceptance

- **DD-1:** a test proves the tool never returns `source_tier == "episodic"`, even when the caller is an ORACLE-tier/`Rank.SENIOR` agent, and even if a caller attempts to pass `episodic` in params.
- **DD-2:** every returned payload contains the disposition preamble **and** per-item provenance markers. Assert both.
- **DD-3:** the full rendered output does not match `_CAPABILITY_GAP_RE` — asserted with the real imported regex.
- **DD-4:** output is bounded; a large Oracle result set is capped.
- **DD-5:** registered with all six departments and `ensign: read`; an agent whose department/rank is denied simply does not receive the tool (no error). Crew children receive it automatically via the per-run tool computation.
- **DD-6:** Oracle raising ⇒ framed empty result, no exception escapes.
- Default-OFF ⇒ `WorkItemAgenticExecutor.run`'s `tool_ids` byte-identical to today.
- Real fixtures per BF-287 — real `ToolRegistry`/`ToolPermissionStore`; no MagicMock at the registry boundary.
- Verify compliance with `.github/copilot-instructions.md`.

## Validation plan — targeted only

- **Focused:** `tests/test_ad1139_oracle_query_tool.py -q -n 0`
- **Adjacent ONCE:** `tests/test_ad1129_eventlog_query_tool.py tests/test_ad1072_tool_search_delegation.py tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad1138_records_semantic_index.py -q -n 0` (verify each exists; drop any that do not).
- **Do NOT run the full suite.**

## Do NOT build here

❌ The publish path (AD-1140 #1061) — this tool is read-only. ❌ Crew consult/publish wiring (AD-1141 #1062). ❌ Any episodic tier access. ❌ Widening `RecallTier` or changing the passive `_oracle_context` injection. ❌ Changing `_apply_access_policy`. ❌ A new AD or BF number.

## Files (verify each at build)

- `src/probos/tools/oracle_query_tool.py` (NEW).
- `src/probos/startup/communication.py` — registration.
- `src/probos/cognitive/agentic_dispatch.py` — offer block.
- `src/probos/config.py` — default-OFF flag.
- `tests/test_ad1139_oracle_query_tool.py` (NEW).

## Done-when

Acceptance green; focused + adjacent gates green; no-episodic and framing assertions in place; default-OFF byte-identity proven; **verify compliance with `.github/copilot-instructions.md`.**
