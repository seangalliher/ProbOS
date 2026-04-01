# AD-540: Memory Provenance Boundary — Knowledge Source Attribution

## Context

Counselor self-diagnosis (2026-03-30) identified the core problem: LLM training knowledge contaminates episodic recall. An agent referenced "Data and Worf dynamics" from Star Trek training data as if personally observed on the ship. Every agent's cognitive context mixes recalled ship memories with LLM training data in the same text stream with no structural separation. The agent cannot distinguish "I experienced this" from "I know this from training."

**Dependencies (both COMPLETE):**
- AD-430: Agent Experiential Memory — 12 episode store paths, agents record their experiences
- AD-502: Temporal Context Injection — time awareness header in every cognitive cycle

**Scope:** L1 (provenance-tagged memory injection) + L2 (source attribution standing order). Two files changed, one file added. No data model changes. No LLM cost increase beyond the boundary marker tokens.

**This AD does NOT:**
- Add a `source` field to Episode (that's AD-541 Pillar 3)
- Add memory verification against EventLog (that's AD-541 Pillar 1)
- Add Counselor contamination detection (that's AD-541 future)

## Problem

Recalled episodes are injected into the user message with no structural boundary separating them from LLM training knowledge. The agent sees:

```
--- Temporal Awareness ---
Current time: 2026-03-31 14:22:05 UTC
...

Your recent memories (relevant past experiences):
  - [3m ago] Captain asked about trust scores for engineering
  - [1h ago] Participated in Ward Room thread about routing efficiency

Captain's message: What do you know about agent communication patterns?
```

The agent cannot structurally distinguish its recalled ship experiences from its LLM training knowledge about "agent communication patterns." Both arrive as undifferentiated text context.

## Part 1: Provenance Boundary Markers in Cognitive Context (L1)

### File: `src/probos/cognitive/cognitive_agent.py`

**Target: `_build_user_message()` method (line ~533)**

There are three paths that format recalled memories. Each needs boundary markers wrapping the memory section.

### 1a. Direct message path (line ~551-563)

**Before:**
```python
if observation.get("recent_memories"):
    parts.append("Your recent memories (relevant past experiences):")
    for mem in observation["recent_memories"]:
        line = f"  - "
        if mem.get("age"):
            line += f"[{mem['age']}] "
        line += mem.get("input", "") or mem.get("reflection", "")
        parts.append(line)
```

**After:**
```python
if observation.get("recent_memories"):
    parts.append("=== SHIP MEMORY (your verified observations aboard this vessel) ===")
    parts.append("These are YOUR experiences — things you personally witnessed or participated in.")
    parts.append("Do NOT confuse these with knowledge from your training data.")
    parts.append("")
    for mem in observation["recent_memories"]:
        line = f"  - "
        if mem.get("age"):
            line += f"[{mem['age']}] "
        line += mem.get("input", "") or mem.get("reflection", "")
        parts.append(line)
    parts.append("")
    parts.append("=== END SHIP MEMORY ===")
```

### 1b. Ward Room notification path (line ~595-607)

**Same pattern.** Replace:
```python
if observation.get("recent_memories"):
    parts.append("Your relevant memories:")
```

With the same boundary markers:
```python
if observation.get("recent_memories"):
    parts.append("=== SHIP MEMORY (your verified observations aboard this vessel) ===")
    parts.append("These are YOUR experiences — things you personally witnessed or participated in.")
    parts.append("Do NOT confuse these with knowledge from your training data.")
    parts.append("")
```

And add the closing `=== END SHIP MEMORY ===` after the memory list.

### 1c. Proactive think path

Check the proactive think section of `_build_user_message()` (line ~640+). If it also formats `recent_memories`, apply the same boundary markers. If proactive does NOT include memories (the `_recall_relevant_memories` method skips `proactive_think` intents at line 757-758), no change needed. Verify and document which case applies.

### 1d. Extract a helper

**DRY:** The boundary marker formatting is identical across paths. Extract a private method:

```python
def _format_memory_section(self, memories: list[dict]) -> list[str]:
    """Format recalled episodes with provenance boundary markers (AD-540)."""
    lines = [
        "=== SHIP MEMORY (your verified observations aboard this vessel) ===",
        "These are YOUR experiences — things you personally witnessed or participated in.",
        "Do NOT confuse these with knowledge from your training data.",
        "",
    ]
    for mem in memories:
        entry = "  - "
        if mem.get("age"):
            entry += f"[{mem['age']}] "
        entry += mem.get("input", "") or mem.get("reflection", "")
        lines.append(entry)
    lines.append("")
    lines.append("=== END SHIP MEMORY ===")
    return lines
```

Then each path simplifies to:
```python
if observation.get("recent_memories"):
    parts.extend(self._format_memory_section(observation["recent_memories"]))
```

## Part 2: Source Attribution Standing Order (L2)

### File: `config/standing_orders/federation.md`

Add a new section after the existing "Core Directives" section (after directive 6, before "Layer Architecture"). This is **Federation tier** — applies to all agents, all instances, cannot be overridden.

**Add this section:**

```markdown
## Knowledge Source Attribution (AD-540)

You have two distinct knowledge sources. Never confuse them:

1. **Ship Memory** — Your personal experiences aboard this vessel, recalled from your episodic memory. These appear between `=== SHIP MEMORY ===` markers in your context. These are ground truth for what happened on this ship.

2. **Training Knowledge** — General knowledge from your language model training data. This includes facts about the world, programming knowledge, domain expertise, and knowledge of fictional universes. This is NOT something you experienced.

When making claims or providing analysis, you MUST:
- Tag observational claims as **[observed]** — "I observed that LaForge's trust score dropped after the routing failure [observed]"
- Tag training-derived claims as **[training]** — "In distributed systems, consistent hashing reduces rebalancing [training]"
- Tag inferences as **[inferred]** — "Based on the trust trend, the routing change likely caused the drop [inferred]"

If you catch yourself treating training knowledge as personal experience (e.g., "I remember when Data analyzed..."), stop and correct yourself. You did not experience events from your training data. Your memories are in the SHIP MEMORY section.
```

## Part 3: Standing Order Cache Invalidation

### File: `src/probos/cognitive/standing_orders.py`

No code changes needed, BUT verify that the LRU cache on `_load_file()` will pick up the new federation.md content. Since the file is loaded at startup and cached, the new content will be included on next boot. If a `clear_cache()` is needed for hot-reload during development, document that — do NOT add runtime cache invalidation code.

## Tests

### Test file: `tests/test_cognitive_agent.py` (or create `tests/test_provenance_boundary.py` if the file is too large)

#### Test 1: Boundary markers present in direct message path
- Create a `CognitiveAgent` with mocked runtime
- Set `observation["recent_memories"]` with 2 test memories
- Call `_build_user_message(observation)` for a `direct_message` intent
- Assert the output contains `"=== SHIP MEMORY"` and `"=== END SHIP MEMORY ==="`
- Assert the output contains `"Do NOT confuse these with knowledge from your training data"`
- Assert each memory entry appears between the markers

#### Test 2: Boundary markers present in Ward Room path
- Same setup, but with `ward_room_notification` intent
- Assert same boundary markers

#### Test 3: No markers when no memories
- Set `observation["recent_memories"]` to empty list or omit key
- Assert `"SHIP MEMORY"` does NOT appear in output

#### Test 4: Helper method extracts cleanly
- Call `_format_memory_section()` directly with test data
- Assert structure: opening marker, instruction line, blank line, entries with age prefix, blank line, closing marker

#### Test 5: Standing order content loaded
- Call `compose_instructions()` for any crew agent
- Assert the output contains `"Knowledge Source Attribution"`
- Assert the output contains `"[observed]"` and `"[training]"` and `"[inferred]"`

## Verification

After all changes:

```bash
# 1. Verify boundary markers are used in all memory paths
grep -n "SHIP MEMORY" src/probos/cognitive/cognitive_agent.py

# 2. Verify old untagged memory headers are gone
grep -n "Your recent memories" src/probos/cognitive/cognitive_agent.py
grep -n "Your relevant memories" src/probos/cognitive/cognitive_agent.py
# Both should return ZERO results

# 3. Verify standing order content
grep -n "Knowledge Source Attribution" config/standing_orders/federation.md

# 4. Verify DRY — only one place defines the boundary text
grep -rn "SHIP MEMORY" src/probos/
# Should show: cognitive_agent.py (helper method only) + tests

# 5. Run targeted tests
python -m pytest tests/test_provenance_boundary.py -v
# OR if added to existing file:
python -m pytest tests/test_cognitive_agent.py -v -k provenance
```

## Principles Compliance

- **SRP:** `_format_memory_section()` has one job — format memories with boundary markers
- **DRY:** Helper method used by all memory formatting paths, no duplication
- **Open/Closed:** Standing orders are config, not code — new orders don't require code changes
- **Defense in Depth:** Boundary markers (structural) + standing order (behavioral) — two independent layers
- **Law of Demeter:** No new object traversals introduced
- **Zero behavior change for agents with no memories:** Empty/missing `recent_memories` produces no markers
