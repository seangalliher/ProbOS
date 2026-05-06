# AD-696 v1: Agentic Oracle Retrieval — On-Demand Ship's Records Query

**Status:** Build prompt for Wave 72 (single AD)
**Dependencies:** AD-462e (OracleService — COMPLETE), AD-632b (QueryHandler — COMPLETE), AD-643a (chain triage/execute split — COMPLETE), AD-686 / AD-688 (Tier 5/6 — COMPLETE), AD-423a (ToolRegistry — COMPLETE)
**Estimated tests:** +13 (window [+10, +14])
**Baseline:** 11433 → expected 11446
**HEAD:** `66ee2eb`
**Closes:** GH issue #416

## Problem

`OracleService` at HEAD runs in exactly one mode: pre-instantiation RAG injection. `cognitive_agent.py:5208-5226` queries Oracle once (under the `RecallTier.ORACLE` gate) before the cognitive cycle starts and writes the formatted output into `observation["_oracle_context"]`, which `analyze.py:128` and `compose.py:495` then render into the LLM prompt.

If the LLM's analysis discovers it needs different records mid-chain — a counselling DM that pivots to an unanticipated topic, an investigation that surfaces a new entity to look up — there is no mechanism. The agent self-reported the asymmetry verbatim:

> *"The Oracle shapes what I know before I start thinking, but I can't direct it once I'm already thinking."*

The full surface needed to close this seam already exists at HEAD:

- A deterministic, zero-LLM-call dispatch table (`QueryHandler._QUERY_OPERATIONS` at `query.py:266-280`) — Open/Closed: add a key, wire a function, no `__call__` change.
- A two-phase chain executor (`_execute_chain_with_intent_routing` at `cognitive_agent.py:1979-2284`) that splits chains into triage (QUERY + ANALYZE) and execute (COMPOSE + EVALUATE + REFLECT) — the seam between phases is the obvious insertion point.
- An ANALYZE prompt that already emits `intended_actions` as a JSON array (`analyze.py:174,379,467`) — adding one new vocab token requires one prompt-text change per surface.
- A registered `runtime.oracle` public attribute (`runtime.py:1349`) and a `ToolRegistry.register()` API (`registry.py:96`) with a working `DirectServiceAdapter` precedent at `startup/communication.py:373-396`.

v1 wires these four pieces: a new `oracle_lookup` QUERY operation, an `oracle_query` action token in the ANALYZE vocab, a single-shot dispatch between the triage and execute phases, and a `ToolRegistry` registration so other consumers (slash commands, future utility agents) can invoke Oracle through the canonical tool seam. The result is injected as `_oracle_context` — the existing rendering convention — so COMPOSE renders it without any new template work.

## Solution

Five additive sections. No file outside the named set is modified.

1. **Section 0 — One new EventType:** `ORACLE_LOOKUP_DISPATCHED` in `events.py`. Single event per dispatched lookup; carries `agent_id`, `agent_type`, `query_text`, `tiers`, `result_chars`. Observability + future rate-limit hook (AD-696c will read this).
2. **Section 1 — One new QUERY operation:** `_query_oracle_lookup(runtime, spec, context)` registered as `"oracle_lookup"` in `_QUERY_OPERATIONS`. Reads `oracle_query_text` (required) + optional `oracle_tiers` from context. Tier-2 log-and-degrade across four failure modes: no `runtime.oracle`, missing `oracle_query_text`, recall-tier insufficient, oracle exception. Returns `{"oracle_lookup": <formatted str>}` (empty string on any degraded path).
3. **Section 2 — ANALYZE vocab + new field:** Three prompt surfaces in `analyze.py` (lines 174, 379, 467 — DM comprehension, ward-room thread, situation review) gain `oracle_query` in their `intended_actions` vocab plus a new optional `oracle_query_text` JSON key (one short paragraph each, ≤ 6 lines added per surface). Discipline guidance lives in the prompt text: "Only include `oracle_query` when the situation references information you do not have in your context."
4. **Section 3 — Chain dispatch seam:** Between triage and execute phases in `_execute_chain_with_intent_routing` (`cognitive_agent.py:2206-2226`), a new `_maybe_dispatch_oracle_lookup` helper fires exactly once per chain when `oracle_query` ∈ `intended_actions`, the agent has `RecallTier.ORACLE`, and `oracle_query_text` is present. The helper builds a single-step `SubTaskChain` of `SubTaskType.QUERY` with `context_keys=("oracle_lookup",)` and dispatches through the same `_sub_task_executor`. Result is written to `observation["_oracle_context"]`; existing COMPOSE rendering at `compose.py:495` picks it up unchanged.
5. **Section 4 — ToolRegistry registration:** In `startup/communication.py`, after the existing `ontology.get_tool_capabilities()` loop (line 391-396), register `DirectServiceAdapter(tool_id="oracle_lookup", handler=runtime.oracle.query_formatted, tool_type=INFRA_SERVICE)` with `ToolPermission.READ` as the default permission and `tags=["oracle", "memory", "rag"]`. Single registration block; mirrors existing pattern.

**Discipline gate (DLog #4 below):** v1 is **once per chain**. The `_oracle_lookup_fired` flag on observation prevents reflexive re-querying. AD-696d (multi-turn) is the named extension point.

**Recall-tier gate:** Same gate as AD-620 line 5208 — `_recall_tier == RecallTier.ORACLE`. The QUERY operation reads `context["_recall_tier"]` (set by chain wiring) and degrades silently when the agent is below ORACLE. No new resolver, no new clearance protocol.

---

## Architect calls (Decision Log)

- **DLog #1 — Reuse `_oracle_context` injection key.** AD-643a / BF-189 / AD-646b already render `observation["_oracle_context"]` in three COMPOSE locations and one ANALYZE re-render path. Writing the agentic-retrieval result to the same key gets free downstream rendering and zero template changes. Trade-off: in a chain where pre-instantiation RAG and agentic retrieval both fire, the agentic result overwrites the pre-RAG result — acceptable in v1 because the LLM explicitly asked for the second query and the first context is now stale by definition. AD-696b (temporal decay) will preserve both with timestamp tags.
- **DLog #2 — `oracle_lookup` as a QUERY op, NOT a new SubTaskType.** The dispatch table at `query.py:266-280` is the canonical Open/Closed extension point. Adding `SubTaskType.ORACLE_QUERY` would fan out to every handler-mapping site (`finalize.py:2210`, `compose.py:454`, `cognitive_agent.py:1789`) and break the "5 sub-task types per SOAR + DECOMP synthesis" invariant in `sub_task.py:29`. The QUERY-op-table extension preserves both.
- **DLog #3 — `oracle_query_text` is a NEW ANALYZE output field, NOT reused from `composition_brief.sources_to_draw_on`.** `sources_to_draw_on` is free-form prose ("episodic memories, Ward Room observations, duty data") used by COMPOSE for narrative. Reusing it would require ANALYZE to emit a structured query in a prose field, then have the chain post-parse it. A dedicated optional string field is cleaner, fails loud (key missing → empty string → degrade), and gives the LLM unambiguous instruction.
- **DLog #4 — One oracle_lookup per chain, hard.** The agent self-report named the failure mode: *"An agent that fires Oracle queries on every uncertainty isn't thinking; it's just searching."* v1 sets `observation["_oracle_lookup_fired"] = True` on dispatch; the helper checks this flag and short-circuits on second invocation. AD-696d (multi-turn retrieval chains) lifts the cap with explicit budget. AD-696c (query intent classification) adds an upstream gate. Both are deferred.
- **DLog #5 — Recall-tier gate inside the QUERY op, NOT inside the chain helper.** Two reasons: (a) the QUERY op is the public seam — any future caller (utility agent, slash command, MCP bridge) gets the same gate for free. (b) the chain helper at `cognitive_agent.py` already handles many gates; adding clearance there bloats the call site. The op reads `context["_recall_tier"]` (a `RecallTier` enum value, already set by `cognitive_agent.py:5019` in the existing recall path — DLog #6 wires it for the chain path too).
- **DLog #6 — Chain wiring threads `_recall_tier` into observation.** `_execute_chain_with_intent_routing` already injects ~25 keys into observation (`_agent_id`, `_callsign`, `_department`, ...). Section 3 adds three more: `_recall_tier` (the resolved `RecallTier` enum), `_oracle_query_text` (mirror of the ANALYZE-emitted field, written by the chain helper after extraction), and `_oracle_lookup_fired` (False by default; flipped True after dispatch). Resolver call mirrors `cognitive_agent.py:5007-5019` line-for-line — no new resolver implementation.
- **DLog #7 — `runtime.oracle` (public) NOT `runtime._oracle_service` (private).** The public alias was added at `runtime.py:1349` (`self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)`). The legacy AD-620 path at `cognitive_agent.py:5212` still reaches through `_oracle_service` — out of scope for v1, will migrate when AD-686c lands the rename. v1 uses the public seam from day one (Wave-5 convention #1).
- **DLog #8 — `ToolPermission.READ` not `OBSERVE`.** Oracle queries return content the agent will quote, paraphrase, or reason from. That is "READ" in the AD-423b additive matrix (CRUD+O: NONE < OBSERVE < READ < WRITE < FULL). OBSERVE is for passive monitoring (counts, deltas, summaries — not full content). The five typed `index_*` write methods reached via `oracle.write_semantic` (AD-686b) are NOT exposed by this tool — the tool is read-only.
- **DLog #9 — Tool registration in `startup/communication.py`, NOT `startup/finalize.py`.** The existing precedent for `ToolRegistry.register()` is at `communication.py:391-396` (the ontology-driven loop). `finalize.py:2199-2230` wires the chain executor + handlers, which is a different concern. Mirroring the existing pattern keeps the registration fan-out colocated. Hard-stop on any new `register(...)` call in `finalize.py`.
- **DLog #10 — No new Pydantic config.** v1 ships with hard-coded budget (`k_per_tier=3`, `max_chars=2000` — same defaults as the existing AD-620 path at `cognitive_agent.py:5219`). AD-696b will introduce `OracleAgenticConfig(max_chars: int = 2000, k_per_tier: int = 3, per_chain_cap: int = 1)` when temporal decay needs to be tunable. v1 remains zero-config — boots out of the box.
- **DLog #11 — Empty-input contract.** When `oracle_query_text` is empty/whitespace, the QUERY op returns `{"oracle_lookup": ""}` immediately — no exception, no log. The chain helper sees empty result, does NOT write `_oracle_context`, does NOT emit `ORACLE_LOOKUP_DISPATCHED`. Mirrors AD-526d `record_game` empty-suppress at `preferences.py:48-49`.
- **DLog #12 — `tests/test_ad696_agentic_oracle_retrieval.py` is a NEW file.** Verified absent at HEAD `66ee2eb`. Builder creates from scratch — no SEARCH/REPLACE on the test file.
- **DLog #13 — Phantom-API pre-check status.** Same recurring blocker as Waves 52–71 (PowerShell parser error documented in user-memory). Manual verify-first pass at draft (16 verifying greps; all confirmed against HEAD `66ee2eb` — see footer). Net-new symbols are intra-prompt-introduction (`ORACLE_LOOKUP_DISPATCHED`, `_query_oracle_lookup`, `oracle_lookup` key, `_maybe_dispatch_oracle_lookup` helper, `_oracle_lookup_fired` / `_oracle_query_text` / `_recall_tier` observation keys, `oracle_lookup` tool_id). Same FP class as Waves 27–71.
- **DLog #14 — Commercial-leak audit: clean.** AD-696 is OSS plumbing — one EventType, one QUERY op, one tool registration, one chain helper, three short ANALYZE prompt insertions, fourteen tests. No tenant scoping, no rate-limit pricing, no per-mesh quotas, no professional-services positioning. Deferred children (AD-696b/c/d) are OSS too. Dispatch and prompt contain zero pricing, revenue model, customer counts, or competitive analysis.
- **DLog #15 — Test count target +13 (window [+10, +14]).** Test list (Builder may fold to 12 or split to 14 at discretion):
  1. `test_event_type_oracle_lookup_dispatched_exists`
  2. `test_oracle_lookup_op_registered_in_query_operations_dispatch_table`
  3. `test_oracle_lookup_returns_formatted_text_when_oracle_present`
  4. `test_oracle_lookup_returns_empty_when_oracle_query_text_missing`
  5. `test_oracle_lookup_returns_empty_when_runtime_oracle_absent`
  6. `test_oracle_lookup_returns_empty_when_recall_tier_below_oracle`
  7. `test_oracle_lookup_swallows_oracle_exception_and_returns_empty`
  8. `test_oracle_lookup_passes_optional_oracle_tiers_filter`
  9. `test_oracle_lookup_emits_oracle_lookup_dispatched_event_on_dispatch`
  10. `test_chain_helper_dispatches_oracle_lookup_when_intended_action_present`
  11. `test_chain_helper_skips_oracle_lookup_when_intended_action_absent`
  12. `test_chain_helper_dispatches_oracle_lookup_at_most_once_per_chain`
  13. `test_chain_helper_writes_result_to_observation_oracle_context_key`
  14. `test_oracle_tool_registered_in_tool_registry_with_read_permission`

---

## Section 0 — Add 1 new EventType

**File:** `src/probos/events.py`
**Mode:** SEARCH/REPLACE
**Insertion point:** directly below the existing AD-526e `RECREATION_SPECTATOR_COMMENTARY` line at line 234. Mirror placement of sibling. Do NOT introduce a new `# ── ` section header.

```search
    RECREATION_SPECTATOR_JOINED = "recreation_spectator_joined"  # AD-526e
    RECREATION_SPECTATOR_COMMENTARY = "recreation_spectator_commentary"  # AD-526e
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
```

```replace
    RECREATION_SPECTATOR_JOINED = "recreation_spectator_joined"  # AD-526e
    RECREATION_SPECTATOR_COMMENTARY = "recreation_spectator_commentary"  # AD-526e
    ORACLE_LOOKUP_DISPATCHED = "oracle_lookup_dispatched"  # AD-696
    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
```

---

## Section 1 — Add `oracle_lookup` QUERY operation

**File:** `src/probos/cognitive/sub_tasks/query.py`
**Mode:** SEARCH/REPLACE (×2 — one to add the function, one to register the key)

### 1.1 — Insert `_query_oracle_lookup` directly above `_query_introspective_telemetry`

```search
async def _query_introspective_telemetry(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Introspective telemetry for self-referential ward room threads.
```

```replace
async def _query_oracle_lookup(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-696: Agentic Oracle retrieval — on-demand Ship's Records query.

    Reads ``oracle_query_text`` (required) and optional ``oracle_tiers`` from
    context. Returns ``{"oracle_lookup": <formatted str>}``. Tier-2
    log-and-degrade: returns empty string on any of four failure modes:
    (1) ``runtime.oracle`` not attached, (2) ``oracle_query_text`` empty,
    (3) ``context["_recall_tier"]`` below ``RecallTier.ORACLE``, (4) Oracle
    raises. Emits ``ORACLE_LOOKUP_DISPATCHED`` only on a non-empty dispatch.
    """
    # Empty-input short-circuit (DLog #11)
    query_text = (context.get("oracle_query_text") or "").strip()
    if not query_text:
        return {"oracle_lookup": ""}

    # Recall-tier gate (DLog #5)
    from probos.earned_agency import RecallTier
    tier = context.get("_recall_tier")
    if tier != RecallTier.ORACLE:
        logger.debug(
            "AD-696: oracle_lookup denied — recall_tier=%s (need ORACLE)", tier,
        )
        return {"oracle_lookup": ""}

    # Public Oracle seam (DLog #7)
    oracle = getattr(runtime, "oracle", None)
    if oracle is None:
        logger.debug("AD-696: oracle_lookup — runtime.oracle not attached")
        return {"oracle_lookup": ""}

    tiers = context.get("oracle_tiers")  # optional list[str] | None
    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")

    try:
        formatted = await oracle.query_formatted(
            query_text=query_text,
            agent_id=agent_id,
            k_per_tier=3,
            tiers=tiers,
            max_chars=2000,
        )
    except Exception:
        logger.warning(
            "AD-696: oracle_lookup query failed for agent %s", agent_id,
            exc_info=True,
        )
        return {"oracle_lookup": ""}

    if not formatted:
        return {"oracle_lookup": ""}

    # Emit on successful non-empty dispatch (DLog #11)
    emit_fn = context.get("_emit_event_fn")
    if emit_fn is not None:
        try:
            from probos.events import EventType
            emit_fn(EventType.ORACLE_LOOKUP_DISPATCHED, {
                "agent_id": agent_id,
                "agent_type": context.get("_agent_type", ""),
                "query_text": query_text,
                "tiers": tiers or [],
                "result_chars": len(formatted),
            })
        except Exception:
            logger.warning("AD-696: ORACLE_LOOKUP_DISPATCHED emit failed", exc_info=True)

    return {"oracle_lookup": formatted}


async def _query_introspective_telemetry(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Introspective telemetry for self-referential ward room threads.
```

### 1.2 — Register `oracle_lookup` in the dispatch table

```search
    "self_monitoring": _query_self_monitoring,                   # AD-646b
    "introspective_telemetry": _query_introspective_telemetry,  # AD-646b
}
```

```replace
    "self_monitoring": _query_self_monitoring,                   # AD-646b
    "introspective_telemetry": _query_introspective_telemetry,  # AD-646b
    "oracle_lookup": _query_oracle_lookup,                       # AD-696
}
```

---

## Section 2 — Add `oracle_query` to ANALYZE vocab + new `oracle_query_text` field

**File:** `src/probos/cognitive/sub_tasks/analyze.py`
**Mode:** SEARCH/REPLACE (×3 — one per ANALYZE prompt surface)

The three surfaces all use the same vocab token list. Each REPLACE keeps the existing wording verbatim and inserts `oracle_query` plus the `oracle_query_text` JSON-key paragraph.

### 2.1 — Ward-room thread analysis prompt (line ~174)

```search
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent, speak_freely.\n"
        f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
        f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
        f"   Add \"speak_freely\" if you have something important to communicate\n"
```

```replace
        f"6. **intended_actions**: Based on your contribution_assessment, what\n"
        f"   specific actions will you take? List as a JSON array from:\n"
        f"   ward_room_reply, endorse, silent, speak_freely, oracle_query.\n"
        f"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
        f"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n"
        f"   Add \"oracle_query\" ONLY when the thread references information\n"
        f"   you do not have in your context (a name, an incident, a record\n"
        f"   you would need to look up). Then provide oracle_query_text below.\n"
        f"   Do NOT use oracle_query for general uncertainty — only for\n"
        f"   specific records you would need to retrieve. (AD-696)\n"
        f"   Add \"speak_freely\" if you have something important to communicate\n"
```

### 2.2 — Ward-room intended_actions ward-room-notification surface (line ~379)

```search
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent, speak_freely. Include ALL that apply.\n"
        "   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
        "   Add \"speak_freely\" if you have something important to communicate\n"
```

```replace
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent, speak_freely, oracle_query. Include ALL that apply.\n"
        "   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
        "   Add \"oracle_query\" ONLY when the situation references information\n"
        "   you do not have in your context (a specific record, name, incident,\n"
        "   or prior decision). Then provide oracle_query_text below. Do NOT\n"
        "   fire oracle_query on general uncertainty — only for specific\n"
        "   records you would need to retrieve. (AD-696)\n"
        "   Add \"speak_freely\" if you have something important to communicate\n"
```

### 2.3 — Add `oracle_query_text` field directive after `composition_brief` in both surfaces

The new field is documented once near the end of each prompt's `Return a JSON object with these N keys` line. The Builder inserts the same 4-line block at TWO locations: (a) directly above the `Return a JSON object with these 7 keys` line in the first prompt at `analyze.py:208`, and (b) directly above the `Return a JSON object with these 6 keys` line in the second prompt at `analyze.py:411`.

#### 2.3a — First prompt (line ~208)

```search
        f"   If contribution_assessment is \"SILENT\", composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 7 keys. No other text."
```

```replace
        f"   If contribution_assessment is \"SILENT\", composition_brief should be null.\n"
        f"8. **oracle_query_text** (optional): If intended_actions contains\n"
        f"   \"oracle_query\", provide the natural-language query string here.\n"
        f"   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        f"   oracle_query is not in intended_actions. (AD-696)\n"
        f"{_format_trigger_awareness(context)}\n"
        f"Return a JSON object with these 8 keys (oracle_query_text optional). No other text."
```

#### 2.3b — Second prompt (line ~411)

```search
        "   If intended_actions is [\"silent\"], composition_brief should be null.\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 6 keys. No other text."
```

```replace
        "   If intended_actions is [\"silent\"], composition_brief should be null.\n"
        "7. **oracle_query_text** (optional): If intended_actions contains\n"
        "   \"oracle_query\", provide the natural-language query string here.\n"
        "   Be specific (cite names, IDs, dates). Omit or set to null when\n"
        "   oracle_query is not in intended_actions. (AD-696)\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 7 keys (oracle_query_text optional). No other text."
```

(The third surface — DM comprehension prompt at line ~467 — does NOT receive vocab changes in v1. DMs are typically already scoped to a single conversation partner; oracle_query in DM context is deferred to AD-696b. The third surface remains unchanged.)

---

## Section 3 — Chain dispatch seam in `_execute_chain_with_intent_routing`

**File:** `src/probos/cognitive/cognitive_agent.py`
**Mode:** SEARCH/REPLACE (×3 — one to add the helper, two to wire the call site + the recall_tier injection)

### 3.1 — Inject `_recall_tier` into observation in chain wiring

The existing observation-key fan-out at `cognitive_agent.py:2074` is the right place. Insert after the `_emit_event_fn` line.

```search
        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, crew manifest
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # AD-644 Phase 1: Duty context for chain prompts
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty
```

```replace
        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, crew manifest
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # AD-696: Resolve recall tier for the agentic-oracle gate (DLog #6).
        # Mirrors the existing AD-620 resolver call at cognitive_agent.py:5007-5019
        # line-for-line — same import, same narrowed args (ontology + clearance_grant_store,
        # NOT _rt itself).
        try:
            from probos.earned_agency import (
                effective_recall_tier, resolve_billet_clearance,
                resolve_active_grants, RecallTier,
            )
            _rank = getattr(self, "rank", None)
            _billet_clearance = resolve_billet_clearance(
                getattr(self, "agent_type", ""),
                getattr(_rt, "ontology", None) if _rt else None,
            )
            _active_grants = resolve_active_grants(
                getattr(self, "sovereign_id", None) or self.id,
                getattr(_rt, "clearance_grant_store", None) if _rt else None,
            )
            observation["_recall_tier"] = effective_recall_tier(
                _rank, _billet_clearance, _active_grants,
            )
        except Exception:
            observation["_recall_tier"] = None  # Gate-closed by default
        observation["_oracle_lookup_fired"] = False  # AD-696 (DLog #4)

        # AD-644 Phase 1: Duty context for chain prompts
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty
```

### 3.2 — Dispatch helper between triage and execute phases

Insert directly after the `intended_actions` extraction, before the silent-short-circuit. The seam is `cognitive_agent.py:2191-2196`.

```search
        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)

        if not intended_actions:
            # ANALYZE didn't produce intended_actions — fall back to pre-AD-643 behavior
            logger.info("AD-643a: No intended_actions from ANALYZE, falling back to full chain")
```

```replace
        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)

        # AD-696: Agentic Oracle retrieval — once per chain (DLog #4)
        if "oracle_query" in intended_actions:
            await self._maybe_dispatch_oracle_lookup(triage_results, observation)

        if not intended_actions:
            # ANALYZE didn't produce intended_actions — fall back to pre-AD-643 behavior
            logger.info("AD-643a: No intended_actions from ANALYZE, falling back to full chain")
```

### 3.3 — `_maybe_dispatch_oracle_lookup` helper

Insert directly above `_extract_intended_actions` at line ~1725. The helper builds a single-step `SubTaskChain` of `SubTaskType.QUERY` and dispatches it through the existing executor.

```search
    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
        """AD-643a: Extract intended_actions from ANALYZE step results.
```

```replace
    async def _maybe_dispatch_oracle_lookup(
        self, triage_results: list, observation: dict,
    ) -> None:
        """AD-696: Dispatch a one-shot oracle_lookup QUERY between triage and execute phases.

        Reads ``oracle_query_text`` from the latest ANALYZE result, builds a
        single-step QUERY chain, executes it, and writes the formatted result
        to ``observation["_oracle_context"]`` (the existing rendering key
        used by COMPOSE / ANALYZE — DLog #1). Once per chain (DLog #4).
        """
        if observation.get("_oracle_lookup_fired"):
            return

        # Extract oracle_query_text from the latest ANALYZE result
        from probos.cognitive.sub_task import (
            SubTaskChain, SubTaskSpec, SubTaskType,
        )
        query_text = ""
        for r in reversed(triage_results):
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                query_text = (r.result.get("oracle_query_text") or "").strip()
                break
        if not query_text:
            return

        observation["oracle_query_text"] = query_text
        observation["_oracle_lookup_fired"] = True  # set BEFORE dispatch (idempotent)

        if self._sub_task_executor is None:
            return

        oracle_chain = SubTaskChain(
            steps=[
                SubTaskSpec(
                    sub_task_type=SubTaskType.QUERY,
                    name="oracle-agentic-lookup",
                    context_keys=("oracle_lookup",),
                ),
            ],
            chain_timeout_ms=30000,
            fallback="skip",
            source="ad696:oracle_query",
        )

        try:
            results = await self._sub_task_executor.execute(
                oracle_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception:
            logger.warning(
                "AD-696: oracle_lookup chain failed for %s", self.agent_type,
                exc_info=True,
            )
            return

        for r in results:
            if r.sub_task_type == SubTaskType.QUERY and r.success and r.result:
                formatted = r.result.get("oracle_lookup", "")
                if formatted:
                    observation["_oracle_context"] = formatted
                break

    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
        """AD-643a: Extract intended_actions from ANALYZE step results.
```

---

## Section 4 — Register OracleService as a ToolRegistry tool

**File:** `src/probos/startup/communication.py`
**Mode:** SEARCH/REPLACE

Insert directly after the existing `tool_registry.register(adapter, ...)` block in the `ontology.get_tool_capabilities()` loop. The new block is a single registration outside the loop (Oracle is a runtime service, not an ontology-driven capability).

```search
            tool_registry.register(
                adapter,
                provider=tc.provider,
                tags=[tc.id, tc.provider],
            )

    # --- Tool Permission Store (AD-423b) ---
```

```replace
            tool_registry.register(
                adapter,
                provider=tc.provider,
                tags=[tc.id, tc.provider],
            )

    # --- AD-696: Register OracleService as agent-invocable tool ---
    # Wave-5 convention #1: public seam runtime.oracle (NOT _oracle_service).
    # ToolPermission.READ — Oracle returns content the agent will quote/reason
    # from. Write-side (oracle.write_semantic) is NOT exposed by this tool.
    if getattr(runtime, "oracle", None) is not None:
        from probos.tools.adapters import DirectServiceAdapter
        from probos.tools.protocol import ToolType

        oracle_adapter = DirectServiceAdapter(
            tool_id="oracle_lookup",
            name="Oracle (Ship's Records Query)",
            description=(
                "Query Ship's Records (episodic memory, ship's records, knowledge "
                "store, semantic layer, knowledge graph, health telemetry) for "
                "specific records. Returns formatted text with provenance tags."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query_text": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "k_per_tier": {"type": "integer", "default": 3},
                    "tiers": {"type": "array", "items": {"type": "string"}},
                    "max_chars": {"type": "integer", "default": 2000},
                },
                "required": ["query_text"],
            },
            output_schema={"type": "string"},
            handler=runtime.oracle.query_formatted,
            tool_type=ToolType.INFRA_SERVICE,
        )
        tool_registry.register(
            oracle_adapter,
            provider="oracle_service",
            tags=["oracle", "memory", "rag", "ad696"],
            default_permissions={"*": "read"},
        )

    # --- Tool Permission Store (AD-423b) ---
```

---

## Section 5 — Tests

**File:** `tests/test_ad696_agentic_oracle_retrieval.py` (NEW)
**Mode:** CREATE

Builder writes 13 tests (target +13; window [+10, +14]). Each test is independent — no shared mutable state. `MagicMock` is the fixture pattern for runtime / oracle / executor — no `ProbOSRuntime(...)` boots in this file (Wave 13/66/67/68/69/70 fixture precedent).

Required test cases (DLog #15). Builder may fold any two adjacent operation-shape tests into a single parameterised case if test count exceeds +14, or split a boundary case if delta is below +10.

1. `test_event_type_oracle_lookup_dispatched_exists` — `EventType.ORACLE_LOOKUP_DISPATCHED.value == "oracle_lookup_dispatched"`.
2. `test_oracle_lookup_op_registered_in_query_operations_dispatch_table` — Import `_QUERY_OPERATIONS`, assert `"oracle_lookup" in _QUERY_OPERATIONS`.
3. `test_oracle_lookup_returns_formatted_text_when_oracle_present` — `MagicMock` runtime with `oracle.query_formatted` returning `"=== ORACLE ===..."`. Context has `oracle_query_text="who reports to bob"`, `_recall_tier=RecallTier.ORACLE`, `_emit_event_fn=Mock()`. Assert result `{"oracle_lookup": "=== ORACLE ===..."}`.
4. `test_oracle_lookup_returns_empty_when_oracle_query_text_missing` — Context omits the key. Assert `{"oracle_lookup": ""}`. Oracle NOT called.
5. `test_oracle_lookup_returns_empty_when_runtime_oracle_absent` — `runtime.oracle = None`. Context has all keys. Assert `{"oracle_lookup": ""}`.
6. `test_oracle_lookup_returns_empty_when_recall_tier_below_oracle` — Context `_recall_tier = RecallTier.FULL`. Assert `{"oracle_lookup": ""}`. Oracle NOT called.
7. `test_oracle_lookup_swallows_oracle_exception_and_returns_empty` — `oracle.query_formatted` raises `RuntimeError`. Assert `{"oracle_lookup": ""}` and warning logged.
8. `test_oracle_lookup_passes_optional_oracle_tiers_filter` — Context `oracle_tiers=["semantic", "graph"]`. Assert `oracle.query_formatted` called once with `tiers=["semantic", "graph"]`.
9. `test_oracle_lookup_emits_oracle_lookup_dispatched_event_on_dispatch` — Successful dispatch. Assert `_emit_event_fn` called once with `(EventType.ORACLE_LOOKUP_DISPATCHED, {agent_id, agent_type, query_text, tiers, result_chars})`.
10. `test_chain_helper_dispatches_oracle_lookup_when_intended_action_present` — Build a triage_result with `intended_actions=["ward_room_reply", "oracle_query"]`, `oracle_query_text="incident 47"`. Mock `_sub_task_executor.execute` to return a QUERY result with `{"oracle_lookup": "[graph: ...]"}`. Assert `observation["_oracle_context"] == "[graph: ...]"` after `_maybe_dispatch_oracle_lookup`.
11. `test_chain_helper_skips_oracle_lookup_when_intended_action_absent` — `intended_actions=["ward_room_reply"]` (no oracle_query). Assert `_sub_task_executor.execute` NOT called for `ad696:oracle_query` chain. `observation["_oracle_context"]` unchanged.
12. `test_chain_helper_dispatches_oracle_lookup_at_most_once_per_chain` — Set `observation["_oracle_lookup_fired"] = True` before calling. Assert `_sub_task_executor.execute` not called.
13. `test_chain_helper_writes_result_to_observation_oracle_context_key` — Same as #10 but assert the rendering-key contract: `observation["_oracle_context"]` is set, NOT `observation["_oracle_lookup"]` or any other key.
14. `test_oracle_tool_registered_in_tool_registry_with_read_permission` — Construct a real `ToolRegistry()`, attach a `MagicMock` runtime with non-None `oracle`. Run the wiring block from `communication.py` directly (NOT via full startup — copy the block into the test). Assert `tool_registry.get("oracle_lookup")` is not None and its `default_permissions` includes `{"*": "read"}`.

(Builder hint: tests #10/#11/#12/#13 share fixture infrastructure — Builder may extract a common `_make_chain_helper_fixture()` helper. Tests #4/#5/#6/#7 are degraded-path variants; if Builder needs to fold for ceiling, fold #5+#6 into a parametrised "any gate-closed reason returns empty" case.)

---

## Tracking and Acceptance

### Files modified
| File | Sections | Lines (estimated) |
|---|---|---|
| `src/probos/events.py` | 0 | +1 |
| `src/probos/cognitive/sub_tasks/query.py` | 1 | +75 |
| `src/probos/cognitive/sub_tasks/analyze.py` | 2 | +24 (3 surfaces × ~8 lines) |
| `src/probos/cognitive/cognitive_agent.py` | 3 | +90 (helper + ctor wiring + dispatch call) |
| `src/probos/startup/communication.py` | 4 | +35 |
| `tests/test_ad696_agentic_oracle_retrieval.py` | 5 | +280 (NEW file) |
| `PROGRESS.md` | tracking | +1 paragraph (CLOSED entry) |
| `docs/development/roadmap.md` | tracking | flip status to `(complete via AD-696 v1, Wave 72)` |
| `prompts/wave-plan.yaml` | tracking | flip wave-72 to `status: done` |

### What this AD does NOT change

- **No new SubTaskType.** v1 stays at 5 SubTaskTypes; the new operation rides the existing QUERY dispatch table (DLog #2).
- **No new Pydantic config.** Hard-coded budget mirrors AD-620 path. AD-696b adds tunables (DLog #10).
- **No multi-turn retrieval.** Once per chain via `_oracle_lookup_fired` flag (DLog #4). AD-696d.
- **No temporal decay scoring.** All Oracle results scored by existing `OracleService.query_formatted` ordering. AD-696b.
- **No query intent classification.** ANALYZE prompt instructs the LLM to gate; no upstream classifier. AD-696c.
- **No DM comprehension surface change.** Third ANALYZE prompt at `analyze.py:467` deliberately untouched (DLog ends-of-Section-2 note).
- **No write-path exposure.** ToolPermission.READ; `oracle.write_semantic` not exposed (DLog #8).
- **No legacy AD-620 path migration.** `cognitive_agent.py:5212` `_oracle_service` private access remains; v1 uses `runtime.oracle` public seam from day one (DLog #7).
- **No new EventType beyond `ORACLE_LOOKUP_DISPATCHED`.** Single observability hook.
- **No `startup/finalize.py` changes.** Tool registration happens in `startup/communication.py` (DLog #9). Hard-stop on register-call additions in finalize.py.
- **No real `ProbOSRuntime` boot in tests.** `MagicMock` fixture pattern only.

### Acceptance criteria

1. Full gate passes at 11446 ± 2 (target +13 vs baseline 11433; window [+10, +14] = [11443, 11447]).
2. All Section 0–4 SEARCH/REPLACE blocks applied byte-for-byte as specified.
3. 13 new tests in `tests/test_ad696_agentic_oracle_retrieval.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`).
5. The Builder build report cites the test count delta + the ten "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites which deferred children remain (AD-696b temporal decay, AD-696c query intent classification, AD-696d multi-turn retrieval) and what their forcing functions are (real-world false-positive rate signals; agentic-retrieval-confusion error class; actual chained-query usage data from this v1).
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-05, HEAD `66ee2eb`)

```
grep -n "RECREATION_SPECTATOR_COMMENTARY\|CONTRASTIVE_RECALL" src/probos/events.py
  234:    RECREATION_SPECTATOR_COMMENTARY = "recreation_spectator_commentary"  # AD-526e
  235:    CONTRASTIVE_RECALL = "contrastive_recall"  # AD-655
  (collision-free anchor for ORACLE_LOOKUP_DISPATCHED insertion)

grep -n "_QUERY_OPERATIONS" src/probos/cognitive/sub_tasks/query.py
  266:    _QUERY_OPERATIONS: dict[str, QueryOperation] = {
  279:    "introspective_telemetry": _query_introspective_telemetry,  # AD-646b
  (dispatch table + insertion anchor confirmed; new key "oracle_lookup" collision-free)

grep -n "async def _query_introspective_telemetry" src/probos/cognitive/sub_tasks/query.py
  239:    async def _query_introspective_telemetry(
  (Section 1.1 SEARCH anchor confirmed)

grep -n "self.oracle" src/probos/runtime.py
  1349:        self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
  (DLog #7 public-seam confirmed; runtime.oracle exists at HEAD)

grep -n "async def query_formatted" src/probos/cognitive/oracle_service.py
  334:    async def query_formatted(
  (handler signature confirmed: query_text, *, agent_id, intent_type, k_per_tier, tiers, max_chars)

grep -n "class OracleService" src/probos/cognitive/oracle_service.py
  113:    class OracleService:
  (target class confirmed)

grep -n "intended_actions.*JSON array from" src/probos/cognitive/sub_tasks/analyze.py
  173:    f"6. **intended_actions**: Based on your contribution_assessment, what\n"
  174:    f"   ... ward_room_reply, endorse, silent, speak_freely.\n"
  379:    "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
  (two SEARCH anchors for vocab insertion confirmed; third surface 467 deliberately untouched per Section 2)

grep -n "Return a JSON object with these" src/probos/cognitive/sub_tasks/analyze.py
  208:    f"Return a JSON object with these 7 keys. No other text."
  411:    "Return a JSON object with these 6 keys. No other text."
  (Section 2.3a + 2.3b SEARCH anchors confirmed)

grep -n "_extract_intended_actions" src/probos/cognitive/cognitive_agent.py
  1725:    def _extract_intended_actions(chain_results: list) -> list[str]:
  2191:        intended_actions = self._extract_intended_actions(triage_results)
  (Section 3.2 SEARCH anchor + Section 3.3 helper insertion anchor confirmed)

grep -n "AD-653: Wire event emission" src/probos/cognitive/cognitive_agent.py
  2071:        # AD-653: Wire event emission + agent identity for compose trust gates
  2076:        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
  (Section 3.1 SEARCH anchor confirmed; ctor-wiring fan-out site)

grep -n "effective_recall_tier\|RecallTier" src/probos/earned_agency.py
  53:    class RecallTier(str, Enum):
  61:    def recall_tier_from_rank(rank: Rank) -> RecallTier:
  104:    ) -> RecallTier:
  (RecallTier + effective_recall_tier resolver confirmed at HEAD)

grep -n "from probos.earned_agency import effective_recall_tier" src/probos/cognitive/cognitive_agent.py
  5007:            from probos.earned_agency import effective_recall_tier, resolve_billet_clearance, resolve_active_grants, RecallTier
  (Section 3.1 import pattern mirrored line-for-line from existing AD-620 path)

grep -n "tool_registry.register" src/probos/startup/communication.py
  391:            tool_registry.register(
  (Section 4 SEARCH anchor confirmed; register-call insertion site)

grep -n "DirectServiceAdapter" src/probos/tools/adapters.py
  101:    class DirectServiceAdapter:
  (handler protocol + ToolType import path confirmed)

grep -n "class ToolPermission" src/probos/tools/protocol.py
  29:    class ToolPermission(str, Enum):
  (READ permission confirmed at AD-423b; "read" string value verified at line 35)

grep -rn "test_ad696" tests/
  (no matches — net-new test file confirmed)

grep -n "AD-696" docs/development/roadmap.md
  7187: ### Agentic Oracle Retrieval (AD-696)
  7191: AD-696: Agentic Oracle Retrieval ... *(Scoped, OSS, Issue #416)*
  7202: v1 = QUERY operation + ToolRegistry registration + ANALYZE intent signal. Deferred: temporal decay scoring (AD-696b), query intent classification (AD-696c), multi-turn retrieval chains (AD-696d).
  (roadmap source-of-truth confirms scope alignment with this prompt)
```
