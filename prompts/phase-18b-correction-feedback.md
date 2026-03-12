# Phase 18b — Correction Feedback Loop

## Context

You are building Phase 18b of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1272/1272 tests passing + 11 skipped. Latest AD: AD-228.**

Phase 18 introduced the Feedback-to-Learning loop: `/feedback good|bad` rates the last execution and adjusts trust, Hebbian routing, and episodic memory. Phase 10 introduced the self-modification pipeline that designs new agents and skills for unhandled intents. Phase 18b bridges the gap between these systems: **when a self-mod'd agent fails and the user provides a correction, the system should fix the agent instead of starting a new self-mod cycle.**

### The Problem (observed in production)

1. User: "Get me news from CNN" → decomposer maps to `http_fetch` → agent uses `http://rss.cnn.com/rss/cnn_topstories.rss` → **success**
2. User: "Use that URL in the future if I ask for news from CNN" → decomposer finds no matching intent → capability gap → self-mod creates `fetch_news_headlines` agent
3. The `AgentDesigner` LLM generates code that hardcodes `https://rss.cnn.com/...` (wrong protocol — HTTPS instead of HTTP)
4. System re-decomposes, new agent runs → **fails** (HTTPS doesn't work for this feed)
5. User wants to correct the URL, but **ProbOS interprets the correction as yet another unhandled intent** (`store_news_source_preference`) and starts a new self-mod cycle

The system can learn new capabilities (self-mod) and rate past executions (feedback), but it cannot accept a **targeted correction** to fix a specific agent's behavior. This phase adds that missing link.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-228 is the latest. Phase 18b AD numbers start at **AD-229**. If AD-228 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1272 tests pass before starting: `uv run pytest tests/ -v`
3. **Read these files thoroughly:**
   - `src/probos/cognitive/feedback.py` — understand `FeedbackEngine`, `FeedbackResult`, `apply_execution_feedback()`, `_extract_agent_ids()`, `_extract_intent_agent_pairs()`
   - `src/probos/cognitive/self_mod.py` — understand `SelfModificationPipeline`, `DesignedAgentRecord` (especially `source_code` field), `_records` list, `handle_unhandled_intent()`, `handle_add_skill()`, skill compilation via importlib
   - `src/probos/cognitive/agent_designer.py` — understand `AgentDesigner.design_agent()`, the prompt template structure, `_AGENT_DESIGN_PROMPT`
   - `src/probos/cognitive/skill_designer.py` — understand how skills are designed (similar pattern to agent designer)
   - `src/probos/cognitive/code_validator.py` — understand `CodeValidator.validate()` — you'll reuse it for patched code
   - `src/probos/cognitive/sandbox.py` — understand `SandboxRunner.test_agent()` — you'll reuse it for patched agents
   - `src/probos/runtime.py` — understand `process_natural_language()`, `_last_execution`, `_last_execution_text`, `_last_feedback_applied`, `record_feedback()`, `_add_skill_to_agents()`, the self-mod trigger block (around line 890), `_extract_unhandled_intent()`
   - `src/probos/experience/shell.py` — understand `/feedback` command dispatch, command registration pattern
   - `src/probos/types.py` — understand `Episode`, `Skill` (especially `source_code` field), `TaskDAG`, `TaskNode`
   - `src/probos/knowledge/store.py` — understand `store_agent()`, `store_skill()` for persistence of patched code
   - `src/probos/cognitive/cognitive_agent.py` — understand `CognitiveAgent`, `add_skill()`, `remove_skill()`, `_skills` dict

---

## What To Build

### Step 1: Correction Detector (AD-229)

**File:** `src/probos/cognitive/correction_detector.py` (new)

**AD-229: `CorrectionDetector` — distinguishes user corrections from new requests.** When the user says something like "use the http URL, not https" or "the URL should be http://..." or "no, use this URL instead" after a failed execution, the system should recognize this as a **correction targeting the last execution** rather than a brand-new capability gap.

The detector uses the LLM to classify user input in the context of the last execution:

```python
class CorrectionDetector:
    """Detects whether user input is a correction targeting a recent execution."""

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def detect(
        self,
        user_text: str,
        last_execution_text: str | None,
        last_execution_dag: TaskDAG | None,
        last_execution_success: bool,
    ) -> CorrectionSignal | None:
        """Analyze user input for correction intent.

        Returns CorrectionSignal if the input is a correction, None if it's
        a new request. Only triggers when there's a recent execution to correct.
        """
```

**`CorrectionSignal` dataclass:**

```python
@dataclasses.dataclass
class CorrectionSignal:
    """A detected correction targeting a recent execution."""
    correction_type: str          # "parameter_fix", "url_fix", "approach_fix"
    target_intent: str            # Which intent in the DAG to fix (e.g., "fetch_news_headlines")
    target_agent_type: str        # Which agent type to patch (e.g., "fetch_news_headlines")
    corrected_values: dict[str, str]  # What should change (e.g., {"url": "http://..."})
    explanation: str              # Human-readable explanation of the correction
    confidence: float             # 0.0-1.0
```

Detection logic:
1. If `last_execution_dag` is None or `last_execution_text` is None, return None — nothing to correct.
2. Build a prompt that shows the LLM: the original request, the executed DAG (intent names + params + results), and the user's new input.
3. Ask the LLM: "Is this a correction/fix for the previous execution, or a new independent request? If it's a correction, what specifically should change?"
4. Parse the LLM's structured JSON response into a `CorrectionSignal`.
5. Only accept corrections with `confidence >= 0.5`.

The LLM prompt should include examples:
- "use http not https" → correction (parameter_fix, url change)
- "use that URL in the future" → correction (parameter_fix, referencing previous successful result)  
- "now read the file at /tmp/foo" → new request (not a correction)
- "that's wrong, the port should be 8080" → correction (parameter_fix)

**Important design constraint:** The detector must be **conservative**. False positives (treating a new request as a correction) are worse than false negatives (treating a correction as a new request, which just triggers normal self-mod). Set the confidence threshold at 0.5 and err on the side of not detecting a correction.

**Run tests after this step: `uv run pytest tests/ -v` — all 1272 existing tests must still pass.**

---

### Step 2: Agent Patcher (AD-230)

**File:** `src/probos/cognitive/agent_patcher.py` (new)

**AD-230: `AgentPatcher` — applies corrections to self-mod'd agent code.** When a correction is detected, the patcher modifies the agent's source code and hot-reloads it.

```python
class AgentPatcher:
    """Patches self-mod'd agent source code based on correction signals."""

    def __init__(
        self,
        llm_client: Any,
        code_validator: CodeValidator,
        sandbox: SandboxRunner,
    ) -> None:
        self._llm_client = llm_client
        self._validator = code_validator
        self._sandbox = sandbox

    async def patch(
        self,
        record: DesignedAgentRecord,
        correction: CorrectionSignal,
        original_execution_text: str,
    ) -> PatchResult:
        """Generate a patched version of the agent source code.

        1. Send the original source + correction to the LLM
        2. Validate the patched code (same CodeValidator as self-mod)
        3. Test in sandbox (same SandboxRunner as self-mod)
        4. Return PatchResult with the new source + compiled class/handler
        """
```

**`PatchResult` dataclass:**

```python
@dataclasses.dataclass
class PatchResult:
    success: bool
    patched_source: str          # New source code (empty on failure)
    agent_class: type | None     # Compiled class (for agent strategy)
    handler: Any | None          # Compiled handler (for skill strategy)
    error: str | None            # Error message on failure
    original_source: str         # Original source (for rollback reference)
    changes_description: str     # Human-readable description of what changed
```

Patching logic:

1. Build an LLM prompt containing:
   - The original agent source code (`record.source_code`)
   - The correction signal (`corrected_values`, `explanation`)
   - The original user request and the error from the last execution
   - Instructions: "Modify the source code to apply the correction. Return ONLY the complete modified Python source code. Do not change the class structure, imports, or agent_type — only fix what the correction targets."
2. Receive patched source code from the LLM.
3. Run `CodeValidator.validate()` on the patched source — if it fails, return `PatchResult(success=False, error=...)`.
4. Run `SandboxRunner.test_agent()` on the patched source — if the sandbox fails, return `PatchResult(success=False, error=...)`.
5. Return `PatchResult(success=True, patched_source=..., agent_class=..., ...)`.

**Safety:** The patcher reuses the same `CodeValidator` and `SandboxRunner` as self-mod. No new security surface. The LLM cannot introduce code that wouldn't pass the existing validation pipeline.

**Run tests: all 1272 must pass.**

---

### Step 3: Hot-Reload for Patched Agents (AD-231)

**File:** `src/probos/runtime.py`

**AD-231: `apply_correction()` — hot-reloads a patched agent into the live runtime.** This is the runtime method that takes a `PatchResult` and swaps the live agent.

```python
async def apply_correction(
    self,
    correction: CorrectionSignal,
    patch_result: PatchResult,
    original_record: DesignedAgentRecord,
) -> CorrectionResult:
    """Hot-reload a patched self-mod'd agent into the runtime."""
```

**`CorrectionResult` dataclass** (in `src/probos/cognitive/agent_patcher.py`):

```python
@dataclasses.dataclass
class CorrectionResult:
    success: bool
    agent_type: str
    strategy: str               # "new_agent" or "skill"
    changes_description: str
    retried: bool               # Whether the original request was retried
    retry_result: dict | None   # Result of the retry, if retried
```

Logic depends on the original `record.strategy`:

**For `strategy="new_agent"`:**
1. Find the pool for this agent type: `f"designed_{record.agent_type}"`.
2. For each agent in the pool:
   a. Create a new instance of `patch_result.agent_class` with the same kwargs the original was created with (id, llm_client, runtime).
   b. Replace the agent in the registry: `self.registry.register(new_agent)` (overwrite by id).
   c. **Or simpler: drain the pool, unregister old agents, re-register the new class, re-create the pool.** Study how pools are created during self-mod and replicate that flow.
3. Update `self._spawner._templates[agent_type]` to point to the new class.
4. Update the `DesignedAgentRecord.source_code` with the patched source.
5. Update the `DesignedAgentRecord.status` to `"patched"`.
6. Refresh decomposer descriptors (`self.decomposer.refresh_descriptors()`).
7. Persist to knowledge store.

**For `strategy="skill"`:**
1. Find agents with the skill attached (by intent name from `correction.target_intent`).
2. `agent.remove_skill(correction.target_intent)`.
3. `agent.add_skill(new_skill)` where `new_skill` has `patch_result.handler` and `patch_result.patched_source`.
4. Update the `DesignedAgentRecord.source_code` with the patched source.
5. Refresh decomposer descriptors.
6. Persist skill to knowledge store (overwrite).

**After hot-reload, automatically retry the original request:**
1. Re-decompose `_last_execution_text` (the request that failed).
2. If nodes are produced, execute the DAG.
3. Include the retry result in `CorrectionResult`.

**Run tests: all 1272 must pass.**

---

### Step 4: Wire Correction into the Main Execution Path (AD-232)

**File:** `src/probos/runtime.py`

**AD-232: Intercept corrections before self-mod trigger.** Modify `process_natural_language()` to check for corrections **before** the capability-gap self-mod logic.

The detection should happen early, right after decomposition yields an empty DAG:

```python
# In process_natural_language(), after decompose() returns empty dag:
if not dag.nodes:
    # Check for correction BEFORE self-mod
    if self._correction_detector and self._last_execution is not None:
        correction = await self._correction_detector.detect(
            user_text=text,
            last_execution_text=self._last_execution_text,
            last_execution_dag=self._last_execution,
            last_execution_success=self._was_last_execution_successful(),
        )
        if correction:
            # Find the DesignedAgentRecord for the target agent
            record = self._find_designed_record(correction.target_agent_type)
            if record:
                patch_result = await self._agent_patcher.patch(
                    record, correction, self._last_execution_text or text,
                )
                if patch_result.success:
                    result = await self.apply_correction(
                        correction, patch_result, record,
                    )
                    # Return correction result to user
                    return self._format_correction_result(result)
                # Patch failed — fall through to normal self-mod or gap response

    # Existing self-mod logic continues here...
    from probos.cognitive.decomposer import is_capability_gap
    ...
```

**Key design decisions:**
- Correction detection runs **only when there's a recent execution** (`_last_execution is not None`).
- Correction detection runs **before** the capability-gap self-mod check.
- If correction is detected but the target agent is **not** a designed agent (it's a built-in), skip correction — you can't patch built-in agents. Fall through to normal flow.
- If correction is detected but patching **fails** (validation, sandbox), log a warning and fall through to normal flow. Don't block the user.

Add a helper `_find_designed_record(agent_type: str) -> DesignedAgentRecord | None` that searches `self_mod_pipeline._records` for the most recent active record matching the agent type.

Add a helper `_was_last_execution_successful() -> bool` that checks whether the last execution had any failed nodes.

**Run tests: all 1272 must pass.**

---

### Step 5: `/correct` Shell Command (AD-233)

**File:** `src/probos/experience/shell.py`

**AD-233: `/correct <text>` — explicit correction command.** While Step 4 adds automatic correction detection in the natural language flow, `/correct` provides an explicit path for the user to say "this is a correction, not a new request."

- `/correct use http:// instead of https://` — explicitly targets the last execution.
- `/correct` (no argument) — print usage: `"Usage: /correct <what to fix> — correct the last execution's behavior"`

The command:
1. Checks `runtime._last_execution` exists.
2. Builds a `CorrectionSignal` using the `CorrectionDetector` (with the explicit text as the correction).
3. Finds the designed agent record.
4. Patches, hot-reloads, and retries (same flow as Step 4).
5. Displays results: what was changed, whether the retry succeeded.

Display format:
```
✓ Correction applied to fetch_news_headlines agent
  Changed: URL updated from https://rss.cnn.com/... to http://rss.cnn.com/...
  Retrying original request...
  ✓ Retry successful — 1/1 tasks completed
```

Or on failure:
```
✗ Correction failed: patched code did not pass validation
  Error: <validation error>
  You can try /feedback bad to mark this execution as negative.
```

**Update `/help` to include `/correct`.**

**Run tests: all 1272 must pass.**

---

### Step 6: Correction Episodes (AD-234)

**File:** `src/probos/cognitive/feedback.py`

**AD-234: `apply_correction_feedback()` — store correction-tagged episodes.** Extend `FeedbackEngine` with a new method for correction events:

```python
async def apply_correction_feedback(
    self,
    original_text: str,
    correction: CorrectionSignal,
    patch_result: PatchResult,
    retry_success: bool,
) -> FeedbackResult:
    """Record a correction event in the learning substrate.

    Corrections are the richest feedback signal — they include both
    "what went wrong" and "how to fix it". The episode stores:
    - The original request
    - The correction details (what was wrong, what was fixed)
    - Whether the fix worked (retry success)
    """
```

This method:
1. **Hebbian** — if retry succeeded, strengthen the intent→agent route (the agent works now). If retry failed, weaken it (correction didn't help).
2. **Trust** — small positive trust bump if retry succeeded (the agent can be taught). No trust change if retry failed (already low from the original failure).
3. **Episodic memory** — store a correction episode with:
   - `human_feedback: "correction_applied"` or `"correction_failed"`
   - `correction_type: correction.correction_type`
   - `corrected_values: correction.corrected_values`
   - `changes_description: patch_result.changes_description`
   - `retry_success: retry_success`
4. **Event log** — `feedback_correction_applied` or `feedback_correction_failed`.

These correction episodes are particularly valuable for the decomposer: when a similar request comes up in the future, the PAST EXPERIENCE section will include "user corrected the URL from X to Y, and the fix worked" — teaching the LLM decomposer to use the correct parameters next time.

**Run tests: all 1272 must pass.**

---

### Step 7: Correction-Aware Self-Mod Context (AD-235)

**File:** `src/probos/cognitive/agent_designer.py`

**AD-235: Pass execution history to AgentDesigner.** One reason the AgentDesigner generated the wrong URL is that it had no visibility into what worked in prior executions. Extend `design_agent()` to accept an optional `execution_context: str` parameter:

```python
async def design_agent(
    self,
    intent_name: str,
    intent_description: str,
    parameters: dict[str, str],
    requires_consensus: bool = False,
    research_context: str = "",
    execution_context: str = "",  # NEW — prior execution results for this session
) -> str:
```

When the runtime triggers self-mod after a successful execution that led to a "remember this" type request:
1. Format the last execution's results as context: "The user's prior request was: '...' which executed as: [intent: http_fetch, params: {url: 'http://rss.cnn.com/...'}, result: success]"
2. Pass this as `execution_context` to the designer.
3. The designer includes it in the LLM prompt so the generated agent uses the **known-working values** from the prior execution.

This addresses the root cause: the AgentDesigner was guessing the URL instead of using the one that demonstrably worked.

Wire the context in `process_natural_language()` when calling `self_mod_pipeline.handle_unhandled_intent()` — if `_last_execution` exists and was successful, format its results and pass them through the pipeline to the designer.

**Run tests: all 1272 must pass.**

---

### Step 8: Tests (target: 1310+ total)

Write comprehensive tests across these test files:

**`tests/test_correction_detector.py`** (new) — ~12 tests:

*Detection:*
- Detects "use http not https" as a correction after failed execution
- Detects "use that URL in the future" as a correction after successful execution
- Returns None for unrelated new request ("read /tmp/foo.txt")
- Returns None when no prior execution exists
- Returns None when confidence < 0.5
- Parses correction_type correctly (parameter_fix, url_fix, approach_fix)
- Parses corrected_values dict from LLM response
- Handles malformed LLM response gracefully (returns None)
- Includes last execution context in the LLM prompt
- Handles empty DAG (no nodes) gracefully

*Edge cases:*
- Very short correction text ("no, http") still detected
- Long correction with explanation ("the URL should be http://... because the server doesn't support TLS") parsed correctly

**`tests/test_agent_patcher.py`** (new) — ~14 tests:

*Patching:*
- Patches agent source with URL correction
- Patched code passes CodeValidator
- Patched code passes SandboxRunner
- Returns PatchResult with patched source on success
- Returns PatchResult with error on validation failure
- Returns PatchResult with error on sandbox failure
- Preserves original source in PatchResult.original_source
- Includes changes_description in PatchResult
- Patching a skill returns handler (not agent_class)
- Patching an agent returns agent_class (not handler)

*Safety:*
- Patched source cannot introduce disallowed imports
- Patched source cannot change agent_type
- Patched source cannot remove safety checks
- Patched source retains original class structure

**`tests/test_correction_runtime.py`** (new) — ~12 tests:

*Runtime integration:*
- `apply_correction()` hot-reloads agent in pool
- `apply_correction()` updates DesignedAgentRecord.source_code
- `apply_correction()` refreshes decomposer descriptors
- `apply_correction()` persists to knowledge store
- `apply_correction()` retries original request
- `apply_correction()` returns CorrectionResult with retry_result
- Correction detection runs before self-mod trigger
- Correction skipped for built-in (non-designed) agents
- Failed patch falls through to normal self-mod flow
- `_find_designed_record()` returns most recent active record
- `_was_last_execution_successful()` checks node results
- `/correct` shell command dispatches to runtime

**Run final test suite: `uv run pytest tests/ -v` — target 1310+ tests passing (1272 existing + ~38 new). All 11 skipped tests remain skipped.**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-229 | `CorrectionDetector` — LLM-based classifier distinguishes corrections from new requests. Requires recent execution context. Conservative threshold (confidence >= 0.5). Returns `CorrectionSignal` with correction_type, target_intent, corrected_values |
| AD-230 | `AgentPatcher` — generates patched source via LLM, validates with same `CodeValidator` + `SandboxRunner` as self-mod. Returns `PatchResult` with compiled class/handler. No new security surface |
| AD-231 | `apply_correction()` hot-reloads patched agent into live runtime. Agent strategy: drain pool, swap class, re-create pool. Skill strategy: remove + re-add skill. Auto-retries original request after reload |
| AD-232 | Correction detection runs in `process_natural_language()` before self-mod trigger. Only targets designed agents. Falls through gracefully on failure |
| AD-233 | `/correct <text>` explicit shell command. Same pipeline as auto-detection but user-initiated. Displays patch diff and retry result |
| AD-234 | `apply_correction_feedback()` stores correction episodes with rich metadata (corrected_values, changes_description, retry_success). Correction episodes are the highest-quality learning signal — they encode both "what went wrong" and "how to fix it" |
| AD-235 | `execution_context` parameter on `AgentDesigner.design_agent()`. Prior successful execution results passed to the LLM so generated agents use known-working values instead of guessing |

---

## Do NOT Build

- **Interactive patching** (showing the user a diff and asking "apply this?") — the existing sandbox validation is sufficient. If patching fails, the user sees the error and can retry with `/correct`
- **Automatic correction without user signal** — never auto-patch an agent just because it failed. Corrections require explicit human intent (either detected from NL or via `/correct`)
- **Patching built-in agents** — only designed agents (those in `self_mod_pipeline._records`) can be patched. Built-in agents are part of the core codebase and must not be modified at runtime
- **Multi-step correction chains** — one correction per execution. If the first correction doesn't fix it, the user can run the request again, get a new failure, and correct again. Don't build a "correction history" or "correction undo" yet
- **Source code diffing** — don't compute or display a line-by-line diff between original and patched source. The `changes_description` from the LLM is sufficient for user-facing display
- **Persistent correction rules** ("always use http for CNN") — corrections fix agent code directly. The fixed code is persisted via knowledge store. No separate "rules" store needed. If the agent is re-designed from scratch (e.g., after rollback), the correction is lost — but the correction episode in episodic memory will guide the new design via PAST EXPERIENCE context
- **Changes to the decomposer** — the decomposer remains unchanged. Corrections influence it indirectly through episodic recall (correction episodes appear in PAST EXPERIENCE context)
- **Changes to the DreamingEngine** — dreaming already processes all episodes including correction-tagged ones

---

## Milestone

Demonstrate the following end-to-end scenario:

1. User: "Get me news from CNN"
2. ProbOS decomposes to `http_fetch` with `url: http://rss.cnn.com/rss/cnn_topstories.rss` → **success**
3. User: "Use that URL in the future if I ask for news from CNN"
4. ProbOS detects capability gap → self-mod creates `fetch_news_headlines` agent
5. Agent uses `https://rss.cnn.com/...` (wrong protocol) → **failure**
6. User: "No, use http not https — the URL that worked was http://rss.cnn.com/rss/cnn_topstories.rss"
7. **CorrectionDetector** recognizes this as a correction targeting `fetch_news_headlines` (not a new request)
8. **AgentPatcher** generates patched source with `http://` URL, validates, sandboxes
9. **apply_correction()** hot-swaps the agent in the live pool
10. Auto-retry: "Get me news from CNN" → decomposes to `fetch_news_headlines` → **success**
11. User sees:
    ```
    ✓ Correction applied to fetch_news_headlines agent
      Changed: URL protocol updated from https:// to http://
      Retrying original request...
      ✓ 1/1 tasks completed
        ✓ t1: fetch_news_headlines
          <CNN headlines>
    ```
12. Correction episode stored with `human_feedback: "correction_applied"`, `retry_success: True`
13. Next time user asks "get news from CNN" → `fetch_news_headlines` uses `http://` → works

And separately (prevention path):

14. User: "Get me news from Reuters"
15. ProbOS detects capability gap → self-mod begins
16. **AgentDesigner** receives `execution_context` from the prior CNN execution, including the correction episode: "user corrected URL from https to http for CNN RSS feed"
17. The designed agent is more likely to use the correct protocol because the LLM has seen the correction

---

## Update PROGRESS.md When Done

Add Phase 18b section with:
- AD decisions (AD-229 through AD-235)
- Files changed/created table
- Test count (target: 1310+)
- Update the Current Status line at the top
- Update the What's Been Built tables for new/changed files
- Add `/correct` to the shell command list in the experience layer description
- In the "Human-Agent Collaboration" roadmap item, mark Correction Feedback as implemented
- Note that Phase 18's "Do NOT Build" item for "Correction mode" is now addressed by this phase
