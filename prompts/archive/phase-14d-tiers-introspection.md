# Phase 14d — Agent Tier Classification & Self-Introspection

## Phase Goal

Two bounded changes that formalize ProbOS's agent architecture:

1. **Agent Tier Classification.** Add a `tier` field to `BaseAgent` and classify all existing agents as `"core"`, `"utility"`, or `"domain"`. Replace the hardcoded `_EXCLUDED_AGENT_TYPES` set in the runtime with tier-based filtering. This establishes the architectural framework that Phase 15 (Cognitive Agents) and domain meshes will build on.

2. **Self-Introspection Intent.** Add `introspect_memory` and `introspect_system` intent handlers to the IntrospectionAgent so the system can accurately report its own capabilities when asked "do you have memory?" or "how healthy are you?" Currently these fall through to the LLM which doesn't know about ProbOS's internal state.

---

## Part 1: Agent Tier Classification

### Architecture

Three tiers, matching the Noöplex's layered architecture:

- **`"core"`** — Infrastructure agents. Domain-agnostic, deterministic tool agents. The substrate's hands. Every domain mesh uses them. They handle hardware-touching intents (file I/O, shell, HTTP). Always available to all agents through the shared intent bus.
- **`"utility"`** — Meta-cognitive agents. Operate *on* the system, not *for* the user. Monitor, test, repair. Have access to system internals. Governed by system-level policies.
- **`"domain"`** — User-facing cognitive work. Currently: designed agents and skill-based agents. In the future: Cognitive Agents organized into domain meshes.

### Classification of existing agents

| Agent | Tier | Rationale |
|-------|------|-----------|
| SystemHeartbeatAgent | core | System rhythm, always running |
| FileReaderAgent | core | Infrastructure I/O |
| FileWriterAgent | core | Infrastructure I/O (consensus-gated) |
| DirectoryListAgent | core | Infrastructure I/O |
| FileSearchAgent | core | Infrastructure I/O |
| ShellCommandAgent | core | Infrastructure I/O (consensus-gated) |
| HttpFetchAgent | core | Infrastructure I/O (consensus-gated) |
| RedTeamAgent | core | Verification infrastructure |
| IntrospectionAgent | utility | System self-monitoring |
| SystemQAAgent | utility | System self-testing |
| SkillBasedAgent | domain | User-facing skill dispatch |
| CorruptedFileReaderAgent | core | Test infrastructure (same tier as the agent it mimics) |
| Designed agents | domain | User-facing cognitive work |

### Deliverables (build in this order)

#### 1a. Add `tier` to BaseAgent

**File:** `src/probos/types.py`
- Add `tier: str` field to `IntentDescriptor` with default `"domain"`. This lets the PromptBuilder and decomposer reason about tiers.

**File:** `src/probos/substrate/agent.py`
- Add `tier: str = "domain"` class-level attribute to `BaseAgent`. Default is `"domain"` so that any new agent (including designed agents from self-mod) is automatically domain-tier unless explicitly overridden. This is backward compatible — no existing agent needs to change to get a default tier.

#### 1b. Classify all existing agents

**File:** `src/probos/agents/file_reader.py` — add `tier = "core"`
**File:** `src/probos/agents/file_writer.py` — add `tier = "core"`
**File:** `src/probos/agents/directory_list.py` — add `tier = "core"`
**File:** `src/probos/agents/file_search.py` — add `tier = "core"`
**File:** `src/probos/agents/shell_command.py` — add `tier = "core"`
**File:** `src/probos/agents/http_fetch.py` — add `tier = "core"`
**File:** `src/probos/agents/red_team.py` — add `tier = "core"`
**File:** `src/probos/agents/corrupted.py` — add `tier = "core"`
**File:** `src/probos/agents/heartbeat_monitor.py` — add `tier = "core"`
**File:** `src/probos/substrate/heartbeat.py` — add `tier = "core"` (HeartbeatAgent base)
**File:** `src/probos/agents/introspect.py` — add `tier = "utility"`
**File:** `src/probos/agents/system_qa.py` — add `tier = "utility"`
**File:** `src/probos/substrate/skill_agent.py` — add `tier = "domain"` (already the default, but make explicit)

Each agent gets a single line: `tier = "core"` (or `"utility"`) as a class-level attribute alongside `agent_type` and `intent_descriptors`.

#### 1c. Replace `_EXCLUDED_AGENT_TYPES` with tier-based filtering

**File:** `src/probos/runtime.py`
- In `_collect_intent_descriptors()`: instead of checking `agent_type not in _EXCLUDED_AGENT_TYPES`, check `agent.tier == "domain"` (or check the class-level `tier` attribute on the template class). Only domain-tier agents contribute descriptors to the decomposer prompt. Core and utility agents are excluded by tier, not by a hardcoded name set.
- Remove the `_EXCLUDED_AGENT_TYPES` set. It's no longer needed.
- Designed agents created by `_register_designed_agent()` get `tier = "domain"` automatically (it's the BaseAgent default). No change needed there.

#### 1d. Update IntentDescriptor and PromptBuilder

**File:** `src/probos/types.py`
- The `tier` field added to `IntentDescriptor` in step 1a.

**File:** `src/probos/cognitive/prompt_builder.py`
- `build_system_prompt()` receives descriptors that are already filtered by tier (the runtime only sends domain-tier descriptors). No change needed to the builder itself — the filtering happens upstream in `_collect_intent_descriptors()`.
- However, include the `tier` field in the descriptor metadata passed to `refresh_descriptors()` so it's available for future use (e.g., when the decomposer needs to route sub-intents to core-tier agents explicitly).

#### 1e. Update panels and manifest

**File:** `src/probos/experience/panels.py`
- `render_agent_table()`: add a "Tier" column showing the agent's tier. Place it after "Pool" and before "State".

**File:** `src/probos/runtime.py`
- `_build_manifest()`: include `tier` in each manifest entry alongside `agent_id`, `agent_type`, `pool_name`, `instance_index`.

---

## Part 2: Self-Introspection Intent

### Architecture

The IntrospectionAgent already handles 4 intents (`explain_last`, `agent_info`, `system_health`, `why`). Add 2 more:

- **`introspect_memory`** — returns episodic memory stats: episode count, intent distribution, success rate, ChromaDB collection info (if available). When the user asks "do you have memory?" or "how many things have you remembered?", this intent fires instead of falling through to the LLM.
- **`introspect_system`** — returns comprehensive system status: agent count by tier, pool health, trust network summary (average trust, highest/lowest trust agents), Hebbian weight count, knowledge store status (artifact counts, commit count), dream cycle status. This is the runtime's `status()` dict reformatted for natural language consumption via reflect.

### Deliverables

#### 2a. Add intent handlers to IntrospectionAgent

**File:** `src/probos/agents/introspect.py`
- Add `introspect_memory` to `intent_descriptors` with `requires_reflect=True` (consistent with other introspection intents). Description: "Report episodic memory status — episode count, intent type distribution, success/failure rates, storage backend info."
- Add `introspect_system` to `intent_descriptors` with `requires_reflect=True`. Description: "Report comprehensive system status — agent tiers, pool health, trust network summary, Hebbian routing stats, knowledge store status, dream cycle state."
- In `handle_intent()`, add cases for both intents. Both read from `self._runtime`:
  - `introspect_memory`: call `runtime.episodic_memory.get_stats()` if episodic memory is available. Return the stats dict as the result. If episodic memory is not available, return a result indicating memory is not enabled.
  - `introspect_system`: call `runtime.status()` to get the full status dict. Additionally gather: agent count by tier (iterate registry, group by `agent.tier`), trust network summary (`trust_network.all_scores()` → compute mean, min, max), Hebbian weight count (`router.get_all_weights()` length), knowledge store status if available. Return the assembled dict.
- Both intents are `requires_reflect=True` so the LLM synthesizes the raw data into a natural language response. The agent returns structured data; the reflect step makes it readable.

#### 2b. Update MockLLMClient

**File:** `src/probos/cognitive/llm_client.py`
- Add patterns for `introspect_memory` and `introspect_system` to `MockLLMClient` so tests can exercise these intents without a live LLM. Follow the existing introspection pattern: match on intent name in the prompt, return a canned single-node DAG.

#### 2c. Update decomposer prompt awareness

No explicit changes needed — `refresh_descriptors()` will automatically pick up the new `introspect_memory` and `introspect_system` descriptors from IntrospectionAgent's `intent_descriptors` list since IntrospectionAgent is utility-tier but its descriptors ARE useful for the decomposer.

**Wait — this creates a conflict with Part 1.** If utility-tier agents are excluded from the decomposer prompt, the IntrospectionAgent's intents won't be visible to the LLM. This needs resolution:

**Resolution:** The tier-based filtering in `_collect_intent_descriptors()` should include BOTH `"domain"` and `"utility"` tier descriptors, but exclude `"core"` tier descriptors. Core agents (file readers, shell, HTTP) are already known to the decomposer through the built-in intent table — they don't need dynamic descriptors. Utility agents (introspection, future system-monitoring agents) DO need their descriptors in the decomposer prompt so the LLM knows to route "do you have memory?" to `introspect_memory` instead of generating a conversational response.

More precisely: the filter should exclude agents whose `intent_descriptors` is empty (RedTeamAgent, SystemHeartbeatAgent, CorruptedFileReaderAgent, SystemQAAgent — all have `intent_descriptors = []`). Agents with non-empty descriptors at any tier are included. This actually simplifies the logic: `_collect_intent_descriptors()` already skips agents with empty descriptor lists. The `_EXCLUDED_AGENT_TYPES` set was specifically needed for SystemQAAgent (which has descriptors but shouldn't be user-routable). 

**Revised approach:** Keep the exclusion narrow. Replace `_EXCLUDED_AGENT_TYPES = {"red_team", "system_qa"}` with: exclude agents where `tier == "core" and intent_descriptors == []` (heartbeat, red team, corrupted — already excluded because their descriptors are empty) plus exclude `SystemQAAgent` specifically because it has descriptors that are for internal use only (triggered by the self-mod pipeline, not user intents). Actually, SystemQAAgent already has `intent_descriptors = []` per the codebase — its `run_smoke_tests` is called directly, not through the intent bus. So the simplified rule is: **include all agents with non-empty `intent_descriptors`**. The `_EXCLUDED_AGENT_TYPES` set can be removed entirely because every agent it excludes already has `intent_descriptors = []`.

Verify this is true by checking: RedTeamAgent has `intent_descriptors = []` ✓. SystemQAAgent — check PROGRESS.md... it says "triggered by self-mod pipeline, not user intents" and the test `smoke_test_agent not in _collect_intent_descriptors` confirms it has empty descriptors. SystemHeartbeatAgent has no user-facing intents. CorruptedFileReaderAgent has `intent_descriptors = []`.

**Final rule for `_collect_intent_descriptors()`:** Collect descriptors from all registered agent templates that have non-empty `intent_descriptors`. Remove the `_EXCLUDED_AGENT_TYPES` check. The `tier` field is metadata for routing, panels, manifest, and future decomposer enhancements — but descriptor collection is simply "has descriptors or doesn't."

---

## Required Tests

### Tier classification tests (in `tests/test_agent_tiers.py`, NEW)
- BaseAgent default tier is "domain" (1 test)
- FileReaderAgent tier is "core" (1 test)
- FileWriterAgent tier is "core" (1 test)
- DirectoryListAgent tier is "core" (1 test)
- FileSearchAgent tier is "core" (1 test)
- ShellCommandAgent tier is "core" (1 test)
- HttpFetchAgent tier is "core" (1 test)
- RedTeamAgent tier is "core" (1 test)
- HeartbeatAgent tier is "core" (1 test)
- SystemHeartbeatAgent tier is "core" (1 test)
- IntrospectionAgent tier is "utility" (1 test)
- SystemQAAgent tier is "utility" (1 test)
- SkillBasedAgent tier is "domain" (1 test)
- CorruptedFileReaderAgent tier is "core" (1 test)
- IntentDescriptor has tier field with default "domain" (1 test)
- Tier field appears in agent manifest (1 test)
- Agent table panel includes Tier column (1 test)
- `_collect_intent_descriptors` does not use `_EXCLUDED_AGENT_TYPES` (verify set is removed) (1 test)
- `_collect_intent_descriptors` includes utility agents with non-empty descriptors (IntrospectionAgent) (1 test)
- `_collect_intent_descriptors` excludes agents with empty descriptors regardless of tier (1 test)

### Self-introspection tests (in `tests/test_introspection.py`, extend existing or new section)
- `introspect_memory` returns episode count and stats when memory enabled (1 test)
- `introspect_memory` returns "not enabled" when memory disabled (1 test)
- `introspect_system` returns agent count by tier (1 test)
- `introspect_system` returns trust network summary (1 test)
- `introspect_system` returns Hebbian weight count (1 test)
- `introspect_system` includes knowledge store status when available (1 test)
- Both new intents have `requires_reflect=True` (1 test)
- Both new intents appear in IntrospectionAgent.intent_descriptors (1 test)
- MockLLMClient handles introspect_memory pattern (1 test)
- MockLLMClient handles introspect_system pattern (1 test)

### Existing tests
- ALL existing 1041 tests must still pass. The `tier` field has a default value ("domain"), so no existing test should break.

---

## Milestone End-to-End Test

A runtime starts. `/agents` shows a Tier column — core agents (file_reader, shell_command, etc.), utility agents (introspection, system_qa), and domain agents (skill_based, any designed agents). The participant types "do you have memory?" The decomposer routes this to `introspect_memory` (not a conversational LLM response). The IntrospectionAgent queries episodic memory stats and returns episode count, intent distribution, and success rate. The reflect step synthesizes this into a natural language answer: "Yes — I have episodic memory with N episodes stored, covering M intent types, with a P% success rate." The participant types "how is the system?" The decomposer routes to `introspect_system`. The agent returns tier-grouped agent counts, trust summary, and knowledge store status. The reflect step synthesizes: "The system has X core agents, Y utility agents, Z domain agents. Average trust is 0.XX. The knowledge store has N episodes and M commits."

The system can describe itself accurately because its self-knowledge is routed through the same mesh architecture as everything else — not faked by the LLM.

---

## Do NOT Build

- **Do NOT build domain meshes or mesh-grouping logic.** The `tier` field is metadata. Domain meshes (formal mesh boundaries, intra-mesh routing, inter-mesh routing) are a Phase 15+ capability. This phase classifies agents; it does not reorganize them into separate meshes.
- **Do NOT add a `domain` field to BaseAgent.** That comes with Cognitive Agents. The `tier` field is sufficient for now.
- **Do NOT change routing logic beyond descriptor collection.** The decomposer, intent bus, and capability registry continue to work exactly as before. Tier-based routing (routing user intents to domain meshes first, then to agents) is a future capability.
- **Do NOT change the consensus pipeline, trust network, or Hebbian router.** Tier-aware governance (different trust mechanics per tier) is a future capability.
- **Do NOT change the DreamingEngine, WorkflowCache, or EpisodicMemory.** 
- **Do NOT change the Federation layer.**
- **Do NOT change the self-modification pipeline.** Designed agents automatically get `tier = "domain"` from the BaseAgent default.

---

## Build Order

1. `types.py` — add `tier` to IntentDescriptor
2. `agent.py` — add `tier` class attribute to BaseAgent
3. All agent files — add explicit `tier` to each agent class
4. `runtime.py` — replace `_EXCLUDED_AGENT_TYPES` with descriptor-based filtering, add tier to manifest
5. `panels.py` — add Tier column to agent table
6. `test_agent_tiers.py` — tier classification tests
7. Verify all 1041 existing tests pass
8. `introspect.py` — add `introspect_memory` and `introspect_system` handlers
9. `llm_client.py` — add MockLLMClient patterns for new intents
10. Self-introspection tests
11. Update PROGRESS.md

---

## Key Design Constraint

The `tier` field is metadata, not behavior. This phase adds classification to every agent and uses it for two things: decomposer descriptor filtering (replacing the hardcoded exclusion set) and panel display. All other tier-aware behavior (routing, governance, trust mechanics, HXI rendering) is deferred to future phases. The framework is established; the behavioral implications are built incrementally.
