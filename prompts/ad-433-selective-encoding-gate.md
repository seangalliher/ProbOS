# AD-433: Selective Encoding Gate — Biologically-Inspired Memory Filtering

## Context

AD-430a-c established universal episode storage for crew agents. This works — every meaningful action is captured. But it also stores *everything*, including noise. The highest-volume noise source is proactive no-response episodes (Site 4: `"reviewed context, nothing to report"` fires every tick for every agent). QA routine passes and proactive-to-Ward Room duplication add more noise. This pollution degrades recall quality because ChromaDB returns noise episodes that push meaningful ones below the `k=3` limit.

The Sensory Cortex principle (roadmap Northstar II) states: *"The solution isn't a wider channel — it's smarter selection."* Applied to memory: don't store noise. The brain doesn't encode every sensory experience — only those with emotional significance, novelty, or goal relevance pass the selective encoding gate.

This AD implements the first memory staging filter: a lightweight importance heuristic at the `store()` boundary. No LLM calls. No new infrastructure services. Just a gate function that returns True/False based on episode metadata.

## Changes

### Step 1: Add `should_store()` gate function to EpisodicMemory

**File:** `src/probos/cognitive/episodic.py`

Add a static method to `EpisodicMemory` (before `store()`):

```python
    @staticmethod
    def should_store(episode: Episode) -> bool:
        """Selective Encoding Gate — biologically-inspired memory filter.

        Not every experience merits a memory. Skip noise; store signal.
        The brain encodes experiences with significance, novelty, or goal relevance.
        """
        text = episode.user_input or ""
        outcomes = episode.outcomes or []

        # Always store Captain-initiated interactions (high significance)
        if text.startswith("[1:1 with"):
            return True

        # Always store failures (learning opportunities)
        for o in outcomes:
            if isinstance(o, dict) and not o.get("success", True):
                return True

        # Skip proactive no-response episodes (highest-volume noise)
        if "[Proactive thought" in text and "no response" in text.lower():
            return False

        # Skip QA routine passes (mechanical, no insight)
        if text.startswith("[SystemQA]"):
            for o in outcomes:
                if isinstance(o, dict) and not o.get("success", True):
                    return True  # QA failures ARE signal
            return False  # QA passes are noise

        # Skip episodes with no meaningful content
        for o in outcomes:
            if isinstance(o, dict):
                response = o.get("response", "")
                if isinstance(response, str) and response.strip() in ("", "[NO_RESPONSE]"):
                    continue
                return True  # Has a real response → store
        # No outcomes with real responses and not caught above
        if not outcomes:
            return True  # No outcomes metadata → store conservatively
        return False
```

### Step 2: Apply the gate at each store call site

The gate must be applied at the call sites, not inside `store()` itself, because `store()` is a general-purpose method that non-agent callers (runtime DAG pipeline, tests) should still use freely. The gate is an *agent experience* filter, not a storage-level restriction.

**File:** `src/probos/proactive.py` — Site 4 (no-response, line ~254)

Wrap the store call with the gate:

```python
                from probos.cognitive.episodic import EpisodicMemory
                # ...existing Episode construction...
                if EpisodicMemory.should_store(episode):
                    await rt.episodic_memory.store(episode)
```

**File:** `src/probos/proactive.py` — Site 5 (with response, line ~313)

Same pattern:

```python
                from probos.cognitive.episodic import EpisodicMemory
                # ...existing Episode construction...
                if EpisodicMemory.should_store(episode):
                    await rt.episodic_memory.store(episode)
```

**File:** `src/probos/runtime.py` — Site 3 (SystemQA, line ~4192)

Same pattern:

```python
                from probos.cognitive.episodic import EpisodicMemory
                # ...existing Episode construction...
                if EpisodicMemory.should_store(episode):
                    await self.episodic_memory.store(episode)
```

**File:** `src/probos/cognitive/cognitive_agent.py` — Site 8 (catch-all, line ~626)

Same pattern in `_store_action_episode()`:

```python
                from probos.cognitive.episodic import EpisodicMemory
                # ...existing Episode construction...
                if EpisodicMemory.should_store(episode):
                    await self._runtime.episodic_memory.store(episode)
```

**DO NOT gate these sites** — they are always signal:
- `runtime.py:2270` (Site 1) — Captain command via runtime.execute()
- `renderer.py:408` (Site 2) — Captain command via renderer
- `shell.py:1551` (Site 6) — Captain 1:1 session
- `api.py:1233` (Site 7) — HXI 1:1 chat
- `ward_room.py:863` (Site 9) — Ward Room thread creation
- `ward_room.py:1059` (Site 10) — Ward Room reply

These are all Captain-initiated or Ward Room authoring events that are always valuable.

### Step 3: Add MockEpisodicMemory.should_store() pass-through

**File:** `src/probos/cognitive/episodic_mock.py`

Add the same static method (or import from the real class). Since it's a static method with no dependencies on instance state, either approach works:

```python
    @staticmethod
    def should_store(episode: Episode) -> bool:
        """Delegate to the real gate for test consistency."""
        from probos.cognitive.episodic import EpisodicMemory
        return EpisodicMemory.should_store(episode)
```

## Tests

**File:** `tests/test_episodic_memory.py` or a new `tests/test_selective_encoding.py` — whichever is more appropriate given the existing test file size.

### Test 1: Gate allows Captain 1:1 episodes
```
episode = Episode(user_input="[1:1 with Counselor] Captain: How are you?", outcomes=[...])
assert EpisodicMemory.should_store(episode) is True
```

### Test 2: Gate blocks proactive no-response
```
episode = Episode(user_input="[Proactive thought — no response] Counselor: reviewed context, nothing to report", outcomes=[{"intent": "proactive_think", "success": True, "response": "[NO_RESPONSE]"}])
assert EpisodicMemory.should_store(episode) is False
```

### Test 3: Gate allows proactive WITH response
```
episode = Episode(user_input="[Proactive thought] Counselor: I've noticed trust variance", outcomes=[{"intent": "proactive_think", "success": True, "response": "I've noticed trust variance across departments"}])
assert EpisodicMemory.should_store(episode) is True
```

### Test 4: Gate blocks QA routine pass
```
episode = Episode(user_input="[SystemQA] Smoke test: code_search", outcomes=[{"intent": "smoke_test", "success": True, "status": "completed"}])
assert EpisodicMemory.should_store(episode) is False
```

### Test 5: Gate allows QA failure
```
episode = Episode(user_input="[SystemQA] Smoke test: code_search", outcomes=[{"intent": "smoke_test", "success": False, "status": "failed"}])
assert EpisodicMemory.should_store(episode) is True
```

### Test 6: Gate allows any episode with failure outcome
```
episode = Episode(user_input="[Action: health_check] Chapel: ran diagnostics", outcomes=[{"intent": "health_check", "success": False, "response": "Timeout"}])
assert EpisodicMemory.should_store(episode) is True
```

### Test 7: Gate blocks episodes where all responses are empty or NO_RESPONSE
```
episode = Episode(user_input="[Action: status_check] O'Brien: routine check", outcomes=[{"intent": "status_check", "success": True, "response": "[NO_RESPONSE]"}])
assert EpisodicMemory.should_store(episode) is False
```

### Test 8: Gate allows episodes with real response content
```
episode = Episode(user_input="[Action: code_review] Number One: reviewing module", outcomes=[{"intent": "code_review", "success": True, "response": "Found 3 issues in the routing module"}])
assert EpisodicMemory.should_store(episode) is True
```

### Test 9: Gate allows episodes with no outcomes (conservative)
```
episode = Episode(user_input="Some unexpected episode format", outcomes=[])
assert EpisodicMemory.should_store(episode) is True
```

### Test 10: Gate allows Ward Room episodes (not gated at call site, but verify the function works)
```
episode = Episode(user_input="[Ward Room] All Hands — Counselor: Trust report", outcomes=[{"intent": "ward_room_post", "success": True}])
assert EpisodicMemory.should_store(episode) is True
```

### Test 11: MockEpisodicMemory.should_store() delegates correctly
```
episode = Episode(user_input="[Proactive thought — no response] Counselor: nothing to report", outcomes=[{"intent": "proactive_think", "success": True, "response": "[NO_RESPONSE]"}])
assert MockEpisodicMemory.should_store(episode) is False
```

## Constraints

- `should_store()` is a **static method** with zero I/O, zero LLM calls, zero async. It's a pure function that inspects Episode fields and returns bool. Sub-microsecond execution.
- The gate is applied at **call sites**, not inside `store()`. This preserves `store()` as a general-purpose method for the DAG pipeline, tests, and any future callers that have already made their own storage decisions.
- **Conservative by default** — unknown episode formats (no outcomes, unexpected user_input patterns) are stored. The gate only blocks known noise patterns.
- Sites 1, 2, 6, 7, 9, 10 are NOT gated — they are always signal (Captain-initiated or Ward Room authoring).
- The proactive no-response episode still served a "prevent re-analysis" purpose (AD-430a). With the gate blocking storage, agents MAY re-analyze the same context on the next tick cycle. This is acceptable — the re-analysis is cheap (fast tier) and the memory pollution cost was far higher. If re-analysis becomes a problem, add a lightweight in-memory set tracking "recent context hashes" in the proactive loop instead.
- This is Layer 2 of the Memory Architecture roadmap. Layer 3 (reinforcement tracking + active forgetting in dream cycles) builds on this by tracking how often stored episodes are recalled and pruning unreinforced ones.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_selective_encoding.py -x -v 2>&1 | tail -30
```

If tests are in test_episodic_memory.py instead:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_episodic_memory.py -x -v -k "should_store or selective" 2>&1 | tail -30
```

Broader validation (ensure no regressions in memory storage):
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_agent.py tests/test_proactive.py tests/test_ward_room.py tests/test_experience.py tests/test_dreaming.py -x -v 2>&1 | tail -40
```
