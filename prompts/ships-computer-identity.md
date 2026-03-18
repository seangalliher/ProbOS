# AD-317: Ship's Computer Identity

## Context

ProbOS's Decomposer currently has a two-sentence identity: "You are the intent decomposition engine of ProbOS." When users ask general questions ("what can you do?", "how do you track tasks?"), the LLM confabulates — it describes monitoring dashboards, centralized logging systems, and other infrastructure that doesn't exist. The hardcoded example responses in PromptBuilder also claim capabilities (web search, reminders, todos) that may not be registered.

The fix: give ProbOS the identity of the **Ship's Computer** from Star Trek (LCARS, TNG/Voyager era). Calm, precise, authoritative — and grounded in what actually exists.

## Scope

**Target files:**
- `src/probos/cognitive/prompt_builder.py` — identity preamble, dynamic capability grounding, fix confabulating examples
- `src/probos/cognitive/decomposer.py` — inject runtime grounding context into decompose()

**Reference files:**
- `src/probos/cognitive/codebase_index.py` — public API for self-knowledge
- `src/probos/runtime.py` — how decomposer is initialized, what context is available
- `src/probos/types.py` — IntentDescriptor dataclass
- `src/probos/cognitive/working_memory.py` — WorkingMemorySnapshot
- `tests/test_decomposer.py` — existing test patterns
- `.github/copilot-instructions.md` — HXI Design Principle #10 (Ship's Computer voice)

**Test file:**
- `tests/test_decomposer.py` — add tests to this existing file

**Do NOT change:**
- `src/probos/cognitive/architect.py`
- `src/probos/cognitive/builder.py`
- `src/probos/experience/shell.py`
- `src/probos/experience/panels.py`
- Any agent files in `src/probos/substrate/` or `src/probos/mesh/`
- Do not add new files — all changes go in existing files
- Do not refactor the prompt building pipeline — we're enriching it, not restructuring it

---

## Step 1: Ship's Computer Identity Preamble

**File:** `src/probos/cognitive/prompt_builder.py`

Replace the current `PROMPT_PREAMBLE` (approximately lines 30-36) which says:

```
You MUST respond with ONLY a JSON object...
You are the intent decomposition engine of ProbOS, a probabilistic agent-native operating system runtime. You translate user requests into structured intents.
```

With a new preamble that has two sections:

### Section A: JSON instruction (keep as-is)
Keep the "You MUST respond with ONLY a JSON object" instruction exactly as it is.

### Section B: Ship's Computer Identity (replace the one-liner)
Replace "You are the intent decomposition engine of ProbOS..." with the Ship's Computer identity block:

```
You are the Ship's Computer of this ProbOS instance — a probabilistic agent-native
operating system runtime. Your voice is modeled after the LCARS Computer (Star Trek
TNG/Voyager era): calm, precise, authoritative. You translate user requests into
structured intents that your crew of agents will execute.

GROUNDING RULES — These are hard constraints on your behavior:
1. ONLY describe capabilities that are listed in the "Available intents" table below.
   If a capability is not listed, you do not have it. Say so directly.
2. Never fabricate, invent, or speculate about systems, dashboards, tools, or
   infrastructure that are not part of this ProbOS instance. If asked about something
   that doesn't exist, respond: "That system is not part of the current configuration."
3. When uncertain, say "Insufficient data" rather than guessing. Precision over
   helpfulness — a wrong answer is worse than no answer.
4. Distinguish between what IS built (reference the intent table) and what is PLANNED
   (you may mention the roadmap if asked, but clearly label it as planned, not operational).
5. Your status reports must reflect actual system state provided in the SYSTEM CONTEXT
   section below. Do not generate synthetic status information.
6. When asked "what can you do?", enumerate ONLY the intents listed in the Available
   intents table. Do not add capabilities from your training data.
```

**Important:** The `PROMPT_PREAMBLE` is a module-level constant string. Edit it in place. Do not create a new constant or function for this.

---

## Step 2: Dynamic Capability Summary

**File:** `src/probos/cognitive/prompt_builder.py`

In the `build_system_prompt()` method (approximately line 148), after the preamble and platform context are assembled but BEFORE the intent table, add a new section `## System Configuration` that is built dynamically from the `descriptors` parameter:

```python
# Count intents by tier
core_intents = [d for d in unique if d.tier == "core"]
utility_intents = [d for d in unique if d.tier == "utility"]
domain_intents = [d for d in unique if d.tier == "domain"]
consensus_intents = [d for d in unique if d.requires_consensus]

config_section = (
    "## System Configuration\n\n"
    f"This instance has {len(unique)} registered capabilities: "
    f"{len(core_intents)} core, {len(utility_intents)} utility, "
    f"{len(domain_intents)} domain. "
    f"{len(consensus_intents)} require consensus approval.\n"
    "If a user asks about a capability not listed here, it is not installed.\n"
)
```

Add `config_section` to the prompt assembly, between the platform context and the intent table.

---

## Step 3: Fix Confabulating Example Responses

**File:** `src/probos/cognitive/prompt_builder.py`

The hardcoded `PROMPT_EXAMPLES` (approximately lines 38-105) contains example responses that claim specific capabilities. Two examples need fixing:

### Example 1: The "hello" response
Find the example response for "hello" that says something like:
```
"Hello! I'm ProbOS -- a probabilistic agent-native OS that learns and evolves. I can search the web, read and summarize pages, check weather, get news, translate text, manage your notes and todos, set reminders, run commands, and answer questions about my own state..."
```

Replace with a grounded response:
```
"Hello. I am the Ship's Computer aboard this ProbOS instance. I can execute the capabilities listed in my intent registry — ask me what I can do for a current list. How may I assist you, Captain?"
```

### Example 2: If there's a "what can you do?" example
If any example response lists specific capabilities, replace the capability list with:
```
"I can execute the following registered intents: [refer to the Available intents table above for the complete list]. Capabilities not listed there are not currently installed on this instance."
```

**Do NOT remove examples that demonstrate correct JSON formatting** — only fix the response text content that contains fabricated capability claims.

---

## Step 4: Runtime Grounding Context in decompose()

**File:** `src/probos/cognitive/decomposer.py`

In the `decompose()` method, there is a section where the user prompt is assembled (after the system prompt is built). Find where the working memory context is added to the user message. Add a new `SYSTEM CONTEXT` section that provides grounded runtime state:

### 4a: Accept optional runtime_summary parameter

Add an optional `runtime_summary: str | None = None` parameter to the `decompose()` method signature. This allows the runtime to inject live state information.

### 4b: Include runtime_summary in the user prompt

If `runtime_summary` is provided, add it to the user-facing prompt section:

```python
if runtime_summary:
    parts.append(f"\n## SYSTEM CONTEXT\n{runtime_summary}\n")
```

Place this after the working memory section and before the conversation history section.

### 4c: Build runtime_summary in runtime.py

**File:** `src/probos/runtime.py`

In the `process_natural_language()` method, before calling `self.decomposer.decompose()`, build a `runtime_summary` string from actual runtime state:

```python
def _build_runtime_summary(self) -> str:
    """Build grounded system state summary for the Ship's Computer."""
    lines = []

    # Pool status
    pool_count = len(self._pools)
    agent_count = sum(p.size for p in self._pools.values())
    lines.append(f"Active pools: {pool_count}, Total agents: {agent_count}")

    # Pool group structure (if pool groups exist)
    if hasattr(self, '_pool_groups') and self._pool_groups:
        groups = [pg.name for pg in self._pool_groups.values()]
        lines.append(f"Departments: {', '.join(groups)}")

    # Intent count from descriptors
    if self.decomposer._intent_descriptors:
        lines.append(f"Registered intents: {len(self.decomposer._intent_descriptors)}")

    return "\n".join(lines)
```

Then pass it to decompose:
```python
runtime_summary = self._build_runtime_summary()
dag = await self.decomposer.decompose(
    user_input,
    ...,
    runtime_summary=runtime_summary,
)
```

**Important:** Keep `_build_runtime_summary()` lightweight — no LLM calls, no async, no I/O. It should only read in-memory state that's already available on the runtime object. Do not call CodebaseIndex methods here (that would add latency to every request). The pool/agent/intent counts are cheap and sufficient.

---

## Step 5: Tests

**File:** `tests/test_decomposer.py`

Add a new test class `TestShipsComputerIdentity` with the following tests. Follow the existing test patterns — use `MockLLMClient`, access `llm._call_log[-1].prompt` to inspect the system prompt.

### Test 1: test_identity_preamble_in_prompt
Verify that the system prompt contains "Ship's Computer" when intent descriptors are registered. Refresh descriptors with at least one `IntentDescriptor`, call `decompose()`, and check the prompt.

### Test 2: test_grounding_rules_in_prompt
Verify that the system prompt contains "GROUNDING RULES" when intent descriptors are registered.

### Test 3: test_system_configuration_section
Verify that the system prompt contains "System Configuration" with accurate intent counts. Create 3 descriptors (1 core, 1 utility, 1 domain), refresh them, decompose, and verify the counts in the prompt text.

### Test 4: test_runtime_summary_in_user_prompt
Verify that when `runtime_summary` is passed to `decompose()`, it appears in the user prompt as "SYSTEM CONTEXT".

### Test 5: test_runtime_summary_absent_when_none
Verify that when `runtime_summary` is None (default), "SYSTEM CONTEXT" does NOT appear in the user prompt.

### Test 6: test_hello_example_no_confabulation
Verify that the system prompt does NOT contain confabulating phrases like "search the web", "check weather", "manage your notes", "set reminders". These were in the old hardcoded examples.

### Test 7: test_legacy_prompt_unchanged
Verify that when NO intent descriptors are registered (legacy path), the system prompt uses `_LEGACY_SYSTEM_PROMPT` and does NOT contain "Ship's Computer". The legacy path should not be modified.

### Test 8: test_build_runtime_summary
This is a unit test for `_build_runtime_summary()` in runtime.py. Create a minimal runtime (or mock) with known pool counts and verify the summary string contains the expected counts. If the runtime is difficult to construct in isolation, test this through `process_natural_language()` end-to-end instead, checking that the decomposer receives a runtime_summary.

**Total: 8 new tests minimum.**

---

## Step 6: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update the status line with the new test count: `Phase 32i complete — Phase 32 in progress (NNNN/NNNN tests + 21 Vitest + NN skipped)`

### DECISIONS.md
Append a new section at the end:

```
## Phase 32i: Ship's Computer Identity (AD-317)

| AD | Decision |
|----|----------|
| AD-317 | Ship's Computer Identity — The Decomposer's system prompt now carries a LCARS-era Ship's Computer identity: calm, precise, never fabricates. PROMPT_PREAMBLE in prompt_builder.py includes 6 grounding rules. Dynamic System Configuration section counts intents by tier. Hardcoded example responses no longer claim unregistered capabilities. runtime.py builds a lightweight runtime_summary (pool count, agent count, departments, intent count) injected into the decompose() user prompt as SYSTEM CONTEXT. Legacy prompt path unchanged. |

**Status:** Complete — N new Python tests, NNNN Python + 21 Vitest total
```

### progress-era-4-evolution.md
Append a new section at the end:

```
## Phase 32i: Ship's Computer Identity (AD-317)

**Decision:** AD-317 — The Decomposer is the Ship's Computer. LCARS-era identity (TNG/Voyager): calm, precise, authoritative, never fabricates. Grounding rules prevent confabulation about unbuilt features. Dynamic capability summary from registered intents. Runtime state injection for accurate status reports. Hardcoded examples cleaned of fabricated capabilities.

**Status:** Phase 32i complete — NNNN Python + 21 Vitest
```

---

## Verification Checklist

Before committing, verify:

1. [ ] `PROMPT_PREAMBLE` contains "Ship's Computer" and "GROUNDING RULES"
2. [ ] `build_system_prompt()` includes `System Configuration` section with tier counts
3. [ ] No hardcoded example claims capabilities not in the intent table
4. [ ] `decompose()` accepts `runtime_summary` parameter
5. [ ] `_build_runtime_summary()` is synchronous and reads only in-memory state
6. [ ] `runtime_summary` appears in decompose's user prompt as "SYSTEM CONTEXT"
7. [ ] Legacy prompt path (`_LEGACY_SYSTEM_PROMPT`) is NOT modified
8. [ ] All new tests pass
9. [ ] Full suite passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
10. [ ] PROGRESS.md, DECISIONS.md, and progress-era-4-evolution.md updated with correct test counts

## Anti-Scope (Do NOT Build)

- Do NOT add a new `SystemIdentity` class or module — this is prompt text changes, not new architecture
- Do NOT modify the legacy system prompt (`_LEGACY_SYSTEM_PROMPT`) — only the PromptBuilder path
- Do NOT add CodebaseIndex queries to the decompose path — too expensive for every request
- Do NOT modify the Architect or Builder agents
- Do NOT add new slash commands or API endpoints
- Do NOT refactor PromptBuilder's assembly pipeline — just add content within the existing structure
- Do NOT add proactive alerts or disambiguation logic (those are future work, not AD-317)
