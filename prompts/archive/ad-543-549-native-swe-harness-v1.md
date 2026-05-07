# AD-543/544/545/546/547/548/549 v1 — Native SWE Harness (Agentic Tool Loop) [combined v1, closes #13]

**Wave:** 98 — combined v1 across seven planned ADs that the spec itself groups (`docs/development/roadmap.md:6650-6868`).
**HEAD:** `632398f`. **Baseline pytest:** Captain reference 12138 (live `pytest --collect-only` 12160 collected). **Target:** ≥12211 passed (Δ ≥ +73 nominal; minimum gate +60).
**Issues closed:** #13.
**Compliance:** Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 0 — Reframe summary (read first)

Seven planned ADs (543/544/545/546/547/548/549) are shipped as one combined v1 because the substrate has no observable behaviour without the loop and the loop cannot compile without the substrate. Three deferrals carry explicit forcing functions (AD-547b exact tokenizer, AD-548b YAML tool-policy schema, AD-549b A/B shadow-mode comparison). The Pro-tier SWE-depth overlay and two fleet-telemetry surfaces are out-of-repo plug-in points under AD-452 — descriptor-only references throughout. Zero new GH issues minted.

Substrate already shipped at HEAD that this wave reuses without parallel-defining:
- AD-423a `Tool` Protocol at `src/probos/tools/protocol.py:83` (acts as AD-543's `ToolDefinition`).
- AD-423a `ToolRegistration` at `src/probos/tools/protocol.py:139` with rank-keyed `default_permissions`.
- AD-423b `ToolPermission` enum (NONE/OBSERVE/READ/WRITE/FULL) at `:30`.
- AD-423c `ToolContext` at `src/probos/tools/context.py`.
- AD-448 `ToolExecutor` at `src/probos/tools/executor.py:40` with `add_pre_hook`/`add_post_hook`/`invoke` (acts as AD-543's `ToolExecutor` Protocol AND AD-548's hook substrate).
- AD-448 `make_audit_hook` emitting `EventType.TOOL_INVOKED` at `src/probos/events.py:197` (acts as AD-548's audit trail).
- AD-521 `BuildPipeline` at `src/probos/build_pipeline.py:36` (the harness produces file_changes upstream; pipeline writes them downstream — no pipeline kwargs added).
- AD-476 specialist subclasses + `SpecialistRouter` at `src/probos/cognitive/builder_specialists.py`.

Net new substrate: wire-format dataclasses (`ToolCallRequest` / `ToolCallResult` / `ContentBlock` / `TextBlock` / `ToolUseBlock` / `ToolResultBlock`), `LLMRequest.tools` / `LLMResponse.content_blocks` extensions, `OpenAICompatibleClient` tool-call response parsing.

---

## Section 1 — `src/probos/cognitive/swe_harness/__init__.py` + `tool_call.py` (AD-543 substrate)

**File:** `src/probos/cognitive/swe_harness/__init__.py` (NEW)

```python
"""AD-543/544/545/546/547/548/549: Native SWE Harness — agentic tool loop.

Combined v1 wave shipping the full ProbOS-native multi-turn LLM-tool-calling
harness. Reuses AD-423a Tool Protocol, AD-423b ToolPermission, AD-423c
ToolContext, AD-448 ToolExecutor pre/post hooks + audit, AD-521 BuildPipeline,
AD-476 specialist subclasses. See prompts/archive/ad-543-549-native-swe-harness-v1.md.
"""

from probos.cognitive.swe_harness.tool_call import (
    ContentBlock,
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolResultBlock,
    ToolUseBlock,
    tool_registration_to_llm_definition,
)

__all__ = [
    "ContentBlock",
    "TextBlock",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolResultBlock",
    "ToolUseBlock",
    "tool_registration_to_llm_definition",
]
```

**File:** `src/probos/cognitive/swe_harness/tool_call.py` (NEW, ~210 lines)

Define frozen dataclasses with full type annotations:

- `@dataclass(frozen=True) class ToolCallRequest`: `id: str = field(default_factory=lambda: uuid.uuid4().hex)`, `name: str`, `arguments: dict[str, Any] = field(default_factory=dict)`, `timestamp: float = field(default_factory=time.time)`.
- `@dataclass(frozen=True) class ToolCallResult`: `id: str` (matches request), `output: str = ""`, `is_error: bool = False`, `duration_ms: float = 0.0`. Class method `from_tool_result(request_id: str, tool_result: ToolResult, duration_ms: float) -> ToolCallResult` adapts an AD-423a `ToolResult` (`from probos.tools.protocol import ToolResult`) — preserves `output` (str-coerced via `str(tool_result.output)` if non-string) and maps `tool_result.error is not None` → `is_error=True`.
- `@dataclass(frozen=True) class TextBlock`: `text: str`. `kind: str = "text"` literal.
- `@dataclass(frozen=True) class ToolUseBlock`: `tool_call: ToolCallRequest`. `kind: str = "tool_use"` literal.
- `@dataclass(frozen=True) class ToolResultBlock`: `result: ToolCallResult`. `kind: str = "tool_result"` literal.
- `ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock` union (Python 3.10+ syntax — confirmed at `pyproject.toml`).

Helper:

```python
def tool_registration_to_llm_definition(reg: "ToolRegistration") -> dict[str, Any]:
    """Adapt an AD-423a ToolRegistration record to an LLM-API tool definition.

    Returns the OpenAI/Anthropic-compatible JSON shape:
        {"type": "function",
         "function": {"name": str, "description": str, "parameters": dict}}
    
    The 'parameters' field is reg.tool.input_schema verbatim (already a JSON
    Schema dict per AD-423a Tool Protocol). LLM providers consume this format
    directly via the Copilot proxy; no per-provider translation needed.
    """
    return {
        "type": "function",
        "function": {
            "name": reg.tool.tool_id,
            "description": reg.tool.description,
            "parameters": reg.tool.input_schema or {"type": "object", "properties": {}},
        },
    }
```

Top-level imports: `from __future__ import annotations`, `import time`, `import uuid`, `from dataclasses import dataclass, field`, `from typing import Any, TYPE_CHECKING`, `if TYPE_CHECKING: from probos.tools.protocol import ToolRegistration, ToolResult`.

---

## Section 2 — `src/probos/types.py` + `events.py` extensions

**File:** `src/probos/types.py`

Two SEARCH/REPLACE pairs:

**Pair 2a — `LLMRequest`:**

```
===SEARCH===
@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"  # LLMTier value
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
===REPLACE===
@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"  # LLMTier value
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # AD-543: Tool-aware completion (None preserves byte-for-byte text-only behaviour).
    tools: list[dict] | None = None
    tool_choice: str = "auto"
===END REPLACE===
```

**Pair 2b — `LLMResponse`:**

```
===SEARCH===
@dataclass
class LLMResponse:
    """Response from the LLM client."""

    content: str
    model: str = ""
    tier: str = "standard"
    tokens_used: int = 0
    prompt_tokens: int = 0       # AD-431: separate prompt token count
    completion_tokens: int = 0   # AD-431: separate completion token count
    cached: bool = False
    error: str | None = None
    request_id: str = ""
===REPLACE===
@dataclass
class LLMResponse:
    """Response from the LLM client."""

    content: str
    model: str = ""
    tier: str = "standard"
    tokens_used: int = 0
    prompt_tokens: int = 0       # AD-431: separate prompt token count
    completion_tokens: int = 0   # AD-431: separate completion token count
    cached: bool = False
    error: str | None = None
    request_id: str = ""
    # AD-543: Structured content blocks when tools are active (empty when text-only).
    content_blocks: list = field(default_factory=list)
    stop_reason: str = "stop"
===END REPLACE===
```

**File:** `src/probos/events.py`

```
===SEARCH===
    TOOL_INVOKED = "tool_invoked"  # AD-448
===REPLACE===
    TOOL_INVOKED = "tool_invoked"  # AD-448
    AGENTIC_TOOL_CALL_STARTED = "agentic_tool_call_started"      # AD-545
    AGENTIC_TOOL_CALL_COMPLETED = "agentic_tool_call_completed"  # AD-545
    AGENTIC_LOOP_ITERATION = "agentic_loop_iteration"            # AD-545
===END REPLACE===
```

---

## Section 3 — `src/probos/cognitive/llm_client.py` extensions (~80 lines additive)

**Pair 3a — `_call_openai` payload:** Inside `_call_openai` after the existing `if effective_top_p is not None: payload["top_p"] = effective_top_p` line at `:680`, INSERT:

```python
        # AD-543: Forward tools + tool_choice when caller requested tool-aware completion.
        if request.tools is not None:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice
```

**Pair 3b — `_call_openai` response parse:** After the existing `content = message.get("content") or ""` line and the `if not content and message.get("reasoning"):` reasoning fallback, BEFORE `usage = data.get("usage", {})`, INSERT response parsing for tool_calls:

```python
        # AD-543: Parse tool_calls into ContentBlock list when tools were active.
        content_blocks_list: list = []
        raw_tool_calls = message.get("tool_calls") or []
        if request.tools is not None:
            from probos.cognitive.swe_harness.tool_call import (
                TextBlock, ToolCallRequest, ToolUseBlock,
            )
            if content:
                content_blocks_list.append(TextBlock(text=content))
            for tc in raw_tool_calls:
                fn = tc.get("function", {}) or {}
                args_raw = fn.get("arguments", "{}")
                try:
                    args_parsed = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                except (ValueError, TypeError):
                    logger.warning(
                        "AD-543: Failed to parse tool_call.function.arguments for tool=%s; "
                        "treating as empty dict",
                        fn.get("name", "<unknown>"),
                    )
                    args_parsed = {}
                content_blocks_list.append(ToolUseBlock(
                    tool_call=ToolCallRequest(
                        id=tc.get("id", uuid.uuid4().hex),
                        name=fn.get("name", ""),
                        arguments=args_parsed,
                    )
                ))
        stop_reason_value = data["choices"][0].get("finish_reason", "stop") or "stop"
```

Add `import uuid` at module top if not already present (verify before adding). Then in the `return LLMResponse(...)` constructor at the end of `_call_openai`, append two kwargs:

```
===SEARCH===
        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
        )
===REPLACE===
        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier or self.default_tier,
            tokens_used=tokens_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached=False,
            request_id=request.id,
            content_blocks=content_blocks_list,
            stop_reason=stop_reason_value,
        )
===END REPLACE===
```

**Pair 3c — `MockLLMClient.script_content_blocks` helper:** Inside `class MockLLMClient(BaseLLMClient):` at `:860`, add an instance state slot (in `__init__`) `self._scripted_content_blocks: list[list] = []` and a public method:

```python
    def script_content_blocks(self, blocks: list) -> None:
        """AD-543: Queue a scripted ContentBlock-list response for the next complete() call.

        Tests call this before invoking a code path that issues a tool-aware
        LLMRequest. The next complete() call returns content_blocks=blocks.
        Calls beyond the queue length fall back to the existing scripted/default
        text response.
        """
        self._scripted_content_blocks.append(list(blocks))
```

In `MockLLMClient.complete()`, after the existing scripted-text resolution, add a check: if `request.tools is not None` and `self._scripted_content_blocks`, pop the first scripted block list, derive `content` as the concatenation of `TextBlock.text` from any TextBlocks in the list (or empty string), and return `LLMResponse(content=content, content_blocks=blocks, stop_reason="tool_use" if any ToolUseBlock else "stop", ...)`. Existing text-path callers untouched.

---

## Section 4 — `src/probos/cognitive/swe_harness/tools.py` (AD-544, ~520 lines)

NEW file. Twelve `Tool`-Protocol-conforming adapters:

**Read-only tier (Trust 0.0+ Ensign / READ permission):**
- `ReadFileTool` — `tool_id="read_file"`, `tool_type=ToolType.UTILITY_AGENT`, wraps `FileReaderAgent.handle_intent()` via runtime intent dispatch. `input_schema={"type":"object","properties":{"path":{"type":"string"},"offset":{"type":"integer"},"limit":{"type":"integer"}},"required":["path"]}`.
- `ListFilesTool` — `tool_id="list_files"`, wraps `FileSearchAgent.handle_intent()` (existing search agent at `agents/file_search.py:38`). `input_schema={"type":"object","properties":{"pattern":{"type":"string"},"path":{"type":"string"}},"required":["pattern"]}`.
- `CodebaseQueryTool` — `tool_id="codebase_query"`, `tool_type=ToolType.DETERMINISTIC_FUNCTION`, wraps `runtime.codebase_index.query(concept)` at `cognitive/codebase_index.py:158`.
- `CodebaseFindCallersTool` — `tool_id="codebase_find_callers"`, wraps `codebase_index.find_callers(method_name, max_results)` at `:339`.
- `CodebaseFindTestsTool` — `tool_id="codebase_find_tests"`, wraps `codebase_index.find_tests_for(file_path)` at `:368`.
- `CodebaseGetImportsTool` — `tool_id="codebase_get_imports"`, wraps `codebase_index.get_imports(file_path)` at `:397`.
- `CodebaseReadSourceTool` — `tool_id="codebase_read_source"`. Reads a file with optional `start_line`/`end_line` slicing via `Path.read_text` with line-range filter (no codebase_index method needed at HEAD; uses direct file read with `_resolve_path` helper from `cognitive/builder.py:45`).
- `StandingOrdersLookupTool` — `tool_id="standing_orders_lookup"`. `input_schema={"type":"object","properties":{"scope":{"type":"string","enum":["ship","department","agent"]},"department":{"type":"string"}},"required":["scope"]}`. Reads `config/standing_orders/<file>.md` text via `Path.read_text` (config layout verified per W77 ConsultationWorkspaces precedent).
- `SystemSelfModelTool` — `tool_id="system_self_model"`. Returns compact runtime topology dict via `runtime.system_self_model.snapshot()` if attribute present (defensive `getattr`), else a hand-built dict from `runtime.spawner.list_pools()` / department map / agent count.

**Write tier (Trust 0.3+ Lieutenant / WRITE permission):**
- `WriteFileTool` — `tool_id="write_file"`, wraps `FileWriterAgent.handle_intent()`. Consensus-gated per FileWriterAgent's existing AD-302 design.
- `EditFileTool` — `tool_id="edit_file"`. Args: `path`, `old_text`, `new_text`, `replace_all` (bool). Performs in-memory search/replace then delegates to FileWriterAgent. First-occurrence-only when `replace_all=False`. Returns count of replacements made.

**Shell tier (Trust 0.5+ Commander / WRITE+CONSENSUS+REFLECT):**
- `RunCommandTool` — `tool_id="run_command"`, wraps `ShellCommandAgent.handle_intent()`. Args: `command`, `timeout` (default 30s), `working_directory`. Returns `{"stdout": str, "stderr": str, "exit_code": int}`.

Each adapter is a class with:
- `__init__(self, runtime: ProbOSRuntime) -> None: self._runtime = runtime`.
- `@property tool_id: str`, `name: str`, `tool_type: ToolType`, `description: str`, `input_schema: dict`, `output_schema: dict`.
- `async def invoke(self, params: dict, context: dict | None = None) -> ToolResult`.

Each `invoke()` body:
1. Validate required params (raise `ValueError` → caught upstream by AD-448 `ToolExecutor` and translated to `ToolResult(error=...)`).
2. Dispatch to underlying capability via runtime.
3. Wrap result in `ToolResult(output=<output>, error=None)` on success or `ToolResult(error=str(exc))` on failure.

Helper at module bottom:

```python
def register_native_swe_tools(registry: "ToolRegistry", runtime: "ProbOSRuntime") -> int:
    """AD-544: Register all 12 native SWE tools into the registry.

    Returns count registered. Idempotent — existing entries are replaced
    with WARNING (mirrors AD-647b ProcessChainRegistry duplicate-register
    semantics, which itself mirrors ToolRegistry.register at registry.py:113).
    """
    tools = [
        (ReadFileTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (ListFilesTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (CodebaseQueryTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (CodebaseFindCallersTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (CodebaseFindTestsTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (CodebaseGetImportsTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (CodebaseReadSourceTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (StandingOrdersLookupTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (SystemSelfModelTool(runtime), {"ensign": "read", "lieutenant": "read", "commander": "read", "senior_officer": "full"}),
        (WriteFileTool(runtime), {"ensign": "none", "lieutenant": "write", "commander": "write", "senior_officer": "full"}),
        (EditFileTool(runtime), {"ensign": "none", "lieutenant": "write", "commander": "write", "senior_officer": "full"}),
        (RunCommandTool(runtime), {"ensign": "none", "lieutenant": "none", "commander": "write", "senior_officer": "full"}),
    ]
    count = 0
    for tool, perms in tools:
        from probos.tools.protocol import ToolRegistration
        reg = ToolRegistration(
            tool=tool,
            domain="engineering",
            provider="swe_harness",
            tags=["native", "swe", tool.tool_id],
            default_permissions=perms,
        )
        registry.register(reg)
        count += 1
    logger.info("AD-544: Registered %d native SWE tools into registry", count)
    return count
```

---

## Section 5 — `src/probos/cognitive/swe_harness/policies.py` (AD-548, ~80 lines)

NEW file. Single factory:

```python
"""AD-548 v1: Standing-orders blocked-paths pre-hook for native SWE tools.

Reframed scope: AD-423a/b/c + AD-448 already ship the trust-tiered access
matrix and pre/post hook substrate. v1 adds only the blocked-paths factory;
the YAML tool-policy schema (per-tool blocked_paths under tools.<name>.<key>
with hot-reload) is deferred to AD-548b — forcing function: first production
deny-policy that needs operator-side tunability without code change.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

PreHook = Callable[[dict[str, Any]], bool]


def make_blocked_paths_hook(blocked_paths: list[str]) -> PreHook:
    """Factory returning an AD-448 PreHook that denies tool calls touching blocked paths.

    Match strategy:
    - For tools with a 'path' param (read_file/write_file/edit_file/list_files/
      codebase_*): substring match against any blocked pattern.
    - For run_command: cwd-relative substring match against the 'command'
      string AND the 'working_directory' param (if present).
    - All other tools: hook returns True (no path semantics → no enforcement).

    Returns False to deny (which AD-448 ToolExecutor translates to
    ToolResult(error="Blocked by standing-order policy: ...") fed back to
    the LLM as a tool_result so the loop can adapt — never raises.

    Tier-2 log-and-degrade: hook errors warn and fail open (return True).
    The deny path is the safety-relevant code path; the hook itself
    failing should not block legitimate work.
    """
    if not blocked_paths:
        # Empty policy → permissive identity hook.
        return lambda ctx: True

    patterns = [p for p in blocked_paths if p]

    def hook(ctx: dict[str, Any]) -> bool:
        try:
            params = ctx.get("params", {}) or {}
            tool_id = ctx.get("tool_id", "")

            check_targets: list[str] = []
            if "path" in params:
                check_targets.append(str(params["path"]))
            if tool_id == "run_command":
                if "command" in params:
                    check_targets.append(str(params["command"]))
                if "working_directory" in params:
                    check_targets.append(str(params["working_directory"]))

            for target in check_targets:
                for pattern in patterns:
                    if pattern in target:
                        logger.warning(
                            "AD-548: Pre-hook denied tool=%s for agent=%s — "
                            "param matched blocked pattern '%s' in '%s'",
                            tool_id,
                            ctx.get("agent_id", "<unknown>")[:12],
                            pattern,
                            target[:80],
                        )
                        return False
            return True
        except Exception:
            logger.warning(
                "AD-548: blocked_paths hook itself failed; failing open (permissive)",
                exc_info=True,
            )
            return True

    return hook
```

---

## Section 6 — `src/probos/cognitive/swe_harness/agentic_loop.py` (AD-545, ~340 lines)

NEW file. Key surface:

```python
"""AD-545: Multi-turn LLM ↔ tool-call orchestrator.

Replaces the single-shot LLM call pattern. Receives a task, iterates
LLM → tool_use → execute → result → LLM until task complete or limits hit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from probos.cognitive.swe_harness.tool_call import (
    ContentBlock, TextBlock, ToolCallRequest, ToolCallResult,
    ToolResultBlock, ToolUseBlock,
)
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

# Defaults — AD-549 NativeSWEHarnessConfig overrides at runtime.
AGENTIC_MAX_ITERATIONS = 25
AGENTIC_DEFAULT_TIER = "deep"


@dataclass
class AgenticResult:
    """AD-545: Outcome of an agentic loop run."""

    final_text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
    error: str = ""


class AgenticLoop:
    """Multi-turn agentic tool-calling loop."""

    def __init__(
        self,
        *,
        llm_client: "BaseLLMClient",
        tool_executor: "ToolExecutor",
        max_iterations: int = AGENTIC_MAX_ITERATIONS,
        token_budget: int | None = None,
        event_emit_fn: Callable | None = None,
        tier: str = AGENTIC_DEFAULT_TIER,
        compactor: Any | None = None,  # Optional SessionCompactor (AD-547)
        compaction_threshold: int | None = None,
    ) -> None:
        self._llm = llm_client
        self._executor = tool_executor
        self._max_iter = max_iterations
        self._budget = token_budget
        self._emit = event_emit_fn
        self._tier = tier
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold

    async def run(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        context: dict[str, Any],
    ) -> AgenticResult:
        """Run the agentic loop until completion or limit reached.

        AD-545 mechanics:
        1. Send system_prompt + user_message + tool definitions to LLM.
        2. Parse response into ContentBlock list.
        3. For each ToolUseBlock: execute via ToolExecutor, collect result.
        4. If response is TextBlock-only with no tool calls → done.
        5. Else append assistant + tool results, send back to LLM.
        6. Repeat from step 2.
        Exit on max_iterations / token_budget / unrecoverable error.
        """
        result = AgenticResult()
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        agent_id = context.get("agent_id", "<unknown>")
        tool_id_history: list[str] = []

        for iteration in range(1, self._max_iter + 1):
            result.iterations = iteration
            self._fire_event("AGENTIC_LOOP_ITERATION", {
                "agent_id": agent_id, "iteration": iteration,
                "tools_used_so_far": list(tool_id_history),
                "total_tokens": result.total_tokens,
            })

            # Optional compaction (AD-547) before LLM call.
            if (self._compactor is not None
                    and self._compaction_threshold is not None
                    and result.total_tokens >= self._compaction_threshold):
                try:
                    messages = await self._compactor.compact(
                        messages,
                        budget_tokens=self._compaction_threshold,
                        fast_llm=self._llm,
                    )
                    logger.info(
                        "AD-547: Compacted message list at iteration=%d total_tokens=%d",
                        iteration, result.total_tokens,
                    )
                except Exception:
                    logger.warning(
                        "AD-547: SessionCompactor.compact failed; continuing without compaction",
                        exc_info=True,
                    )

            # Issue tool-aware LLM call. Build prompt from latest user/tool messages
            # since LLMRequest models a single user turn at HEAD.
            assembled_user_prompt = "\n\n".join(
                f"[{m['role']}] {m['content']}"
                for m in messages[1:]  # skip system; system_prompt is its own field
            )
            req = LLMRequest(
                prompt=assembled_user_prompt,
                system_prompt=system_prompt,
                tier=self._tier,
                tools=tools,
                tool_choice="auto",
                max_tokens=4096,
            )
            try:
                response = await self._llm.complete(req)
            except Exception as exc:
                logger.warning(
                    "AD-545: LLM complete() failed at iteration=%d agent=%s; "
                    "stopping with stopped_reason=error",
                    iteration, agent_id[:12], exc_info=True,
                )
                result.stopped_reason = "error"
                result.error = str(exc)
                return result

            result.total_tokens += int(response.tokens_used or 0)

            if self._budget is not None and result.total_tokens >= self._budget:
                result.stopped_reason = "token_budget"
                # Try to capture last text before exit
                for block in response.content_blocks:
                    if isinstance(block, TextBlock):
                        result.final_text = block.text
                        break
                else:
                    result.final_text = response.content or ""
                return result

            blocks = list(response.content_blocks) or [TextBlock(text=response.content or "")]
            tool_uses = [b for b in blocks if isinstance(b, ToolUseBlock)]

            # Append assistant turn (raw content text + serialised tool_uses for protocol fidelity).
            assistant_text = "\n".join(b.text for b in blocks if isinstance(b, TextBlock))
            messages.append({"role": "assistant", "content": assistant_text or response.content or ""})

            if not tool_uses:
                # No tool calls — task complete.
                result.final_text = assistant_text or response.content or ""
                result.stopped_reason = "complete"
                return result

            # Execute each tool call.
            tool_result_blocks: list[ToolResultBlock] = []
            for use in tool_uses:
                self._fire_event("AGENTIC_TOOL_CALL_STARTED", {
                    "agent_id": agent_id,
                    "tool_id": use.tool_call.name,
                    "iteration": iteration,
                })
                start = time.perf_counter()
                try:
                    raw_result = await self._executor.invoke(
                        agent_id=context.get("agent_id", ""),
                        tool_id=use.tool_call.name,
                        params=use.tool_call.arguments,
                        agent_department=context.get("department", "engineering"),
                        agent_rank=context.get("rank", "ensign"),
                    )
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    tcr = ToolCallResult.from_tool_result(use.tool_call.id, raw_result, duration_ms)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    logger.warning(
                        "AD-545: Tool execution raised for tool=%s agent=%s; "
                        "feeding error result back to LLM",
                        use.tool_call.name, agent_id[:12], exc_info=True,
                    )
                    tcr = ToolCallResult(
                        id=use.tool_call.id,
                        output=f"Tool {use.tool_call.name} failed: {exc}",
                        is_error=True,
                        duration_ms=duration_ms,
                    )
                self._fire_event("AGENTIC_TOOL_CALL_COMPLETED", {
                    "agent_id": agent_id,
                    "tool_id": use.tool_call.name,
                    "iteration": iteration,
                    "is_error": tcr.is_error,
                    "duration_ms": tcr.duration_ms,
                })
                result.tool_calls.append(use.tool_call)
                tool_id_history.append(use.tool_call.name)
                tool_result_blocks.append(ToolResultBlock(result=tcr))

            # Feed tool results back into conversation.
            tool_result_text = "\n\n".join(
                f"[tool_result:{trb.result.id} error={trb.result.is_error}]\n{trb.result.output}"
                for trb in tool_result_blocks
            )
            messages.append({"role": "user", "content": tool_result_text})

        # Loop exited due to max_iterations.
        result.stopped_reason = "max_iterations"
        return result

    def _fire_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """AD-545: Fire-and-forget event emission. Mirrors TRANSPORTER_DECOMPOSED pattern."""
        if self._emit is None:
            return
        try:
            from probos.events import EventType
            event_type = getattr(EventType, event_name, None)
            if event_type is None:
                return
            maybe_coro = self._emit(event_type, payload)
            if asyncio.iscoroutine(maybe_coro):
                # Fire-and-forget — store reference per copilot-instructions async hygiene
                task = asyncio.create_task(maybe_coro)
                # Best-effort: forget the reference once scheduled; agentic loop is short-lived.
                _ = task
        except Exception:
            logger.debug("AD-545: Event emission failed for %s; degrading silently", event_name, exc_info=True)
```

---

## Section 7 — `src/probos/cognitive/swe_harness/session_compactor.py` (AD-547, ~130 lines)

NEW file:

```python
"""AD-547 v1: Session compaction for long agentic-loop conversations.

v1 ships a char-count token approximation (len(text) // 4). Exact tokenizer
is deferred to AD-547b — forcing function: first compaction false-trip
where the len/4 estimate diverges >25% from actual model context counting.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """v1 char-count approximation. AD-547b ships exact tokenizer."""
    if not text:
        return 1
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Sum estimated tokens across message contents."""
    return sum(estimate_tokens(str(m.get("content", ""))) for m in messages)


class SessionCompactor:
    """AD-547: Compact older messages via fast-tier LLM summarisation."""

    SYSTEM_PROMPT = (
        "Summarise the following tool interactions concisely. Preserve: "
        "(1) key findings the LLM produced, (2) decisions made, "
        "(3) files changed and the rationale, (4) any errors that informed "
        "later choices. Output a single paragraph, no preamble."
    )

    async def compact(
        self,
        messages: list[dict],
        *,
        preserve_count: int = 5,
        budget_tokens: int | None = None,
        fast_llm: "BaseLLMClient",
    ) -> list[dict]:
        """Compact messages while preserving system prompt + last preserve_count exchanges.

        Args:
            messages: Full message list including system prompt at index 0.
            preserve_count: Number of trailing assistant+tool exchanges to keep verbatim.
            budget_tokens: Token budget the result must fit within. Re-compaction
                is triggered if first pass result still exceeds budget.
            fast_llm: LLMClient using fast-tier (Sonnet via Copilot proxy).

        Returns:
            Compacted message list. System prompt + summary + preserved tail.
        """
        if len(messages) <= preserve_count + 2:
            # Not enough messages to compact meaningfully.
            return messages

        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        # Identify original user task — first user message after system.
        original_user = None
        for m in messages[1:]:
            if m.get("role") == "user":
                original_user = m
                break
        # Older messages: everything between original_user and the trailing preserve_count.
        tail = messages[-preserve_count:] if preserve_count > 0 else []
        head_indices = []
        if system_msg is not None:
            head_indices.append(0)
        if original_user is not None and id(original_user) != id(system_msg):
            head_indices.append(messages.index(original_user))
        preserved_ids = {id(messages[i]) for i in head_indices} | {id(m) for m in tail}
        older = [m for m in messages if id(m) not in preserved_ids]

        if not older:
            return messages

        older_text = "\n\n".join(
            f"[{m.get('role','?')}] {m.get('content','')}" for m in older
        )

        try:
            req = LLMRequest(
                prompt=older_text,
                system_prompt=self.SYSTEM_PROMPT,
                tier="fast",
                max_tokens=1024,
            )
            response = await fast_llm.complete(req)
            summary = response.content or "[compaction summary unavailable]"
        except Exception:
            logger.warning(
                "AD-547: Compaction LLM call failed; returning original messages",
                exc_info=True,
            )
            return messages

        compacted: list[dict] = []
        if system_msg is not None:
            compacted.append(system_msg)
        if original_user is not None and id(original_user) != id(system_msg):
            compacted.append(original_user)
        compacted.append({
            "role": "user",
            "content": f"[CONTEXT SUMMARY — earlier exchanges]\n{summary}",
        })
        compacted.extend(tail)

        # Re-compaction: if still over budget, summarise the summary.
        if budget_tokens is not None:
            current = estimate_messages_tokens(compacted)
            if current > budget_tokens and len(compacted) > 3:
                logger.info(
                    "AD-547: First pass still over budget (%d > %d); re-compacting",
                    current, budget_tokens,
                )
                # Drop the original_user re-inclusion if needed; keep system + summary + last 2.
                if len(compacted) > 4:
                    compacted = [compacted[0], compacted[2]] + compacted[-2:]
        return compacted
```

---

## Section 8 — `src/probos/cognitive/swe_harness/native_builder.py` + `SoftwareEngineerAgent.perceive()` routing branch (AD-546, ~280 lines)

**File:** `src/probos/cognitive/swe_harness/native_builder.py` (NEW)

```python
"""AD-546 v1: NativeBuilderHarness wrapping AgenticLoop for build execution."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
from probos.cognitive.swe_harness.tool_call import tool_registration_to_llm_definition

if TYPE_CHECKING:
    from probos.cognitive.builder import BuildSpec
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime
    from probos.tools.executor import ToolExecutor
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_HARNESS_TOOL_IDS_BUILD = [
    "read_file", "edit_file", "write_file", "list_files", "run_command",
    "codebase_query", "codebase_find_callers", "codebase_find_tests",
    "codebase_read_source",
]


class NativeBuilderHarness:
    """Multi-turn agentic builder. Wraps AgenticLoop with build-specific config."""

    def __init__(
        self,
        *,
        runtime: "ProbOSRuntime",
        llm_client: "BaseLLMClient",
        tool_executor: "ToolExecutor",
        tool_registry: "ToolRegistry",
        max_iterations: int = 25,
        max_fix_iterations: int = 5,
        token_budget: int | None = None,
        compactor: Any | None = None,
        compaction_threshold: int | None = None,
    ) -> None:
        self._runtime = runtime
        self._llm = llm_client
        self._executor = tool_executor
        self._registry = tool_registry
        self._max_iter = max_iterations
        self._max_fix_iter = max_fix_iterations
        self._budget = token_budget
        self._compactor = compactor
        self._compaction_threshold = compaction_threshold

    async def run_build(
        self, spec: "BuildSpec", work_dir: str, *, agent_id: str = "swe", department: str = "engineering",
        rank: str = "lieutenant",
    ) -> dict[str, Any]:
        """Run an agentic build. Returns a dict with 'file_changes' + metadata.

        Output shape mirrors what BuilderAgent._parse_file_blocks() consumers
        expect, plus AD-549 metadata fields (iterations / tools_used / compactions).
        """
        tools_definitions = self._select_build_tools()
        system_prompt = self._compose_system_prompt(spec)
        user_message = self._format_build_message(spec, work_dir)

        loop = AgenticLoop(
            llm_client=self._llm,
            tool_executor=self._executor,
            max_iterations=self._max_iter,
            token_budget=self._budget,
            event_emit_fn=getattr(self._runtime, "emit_event", None),
            compactor=self._compactor,
            compaction_threshold=self._compaction_threshold,
        )

        agentic_result: AgenticResult = await loop.run(
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools_definitions,
            context={"agent_id": agent_id, "department": department, "rank": rank},
        )

        # Parse file blocks from final-text output.
        from probos.build_pipeline import BuildPipeline
        file_changes = BuildPipeline.parse_file_blocks(agentic_result.final_text)

        return {
            "file_changes": file_changes,
            "llm_output": agentic_result.final_text,
            "builder_source": "native_harness",
            "metadata": {
                "builder_type": "native_harness",
                "iterations": agentic_result.iterations,
                "tools_used": [tc.name for tc in agentic_result.tool_calls],
                "compactions": 0,  # SessionCompactor doesn't expose count v1; AD-547b extends.
                "stopped_reason": agentic_result.stopped_reason,
                "total_tokens": agentic_result.total_tokens,
            },
        }

    def _select_build_tools(self) -> list[dict]:
        """Select code-generation-relevant tools and convert to LLM definitions."""
        defs: list[dict] = []
        for tool_id in _HARNESS_TOOL_IDS_BUILD:
            reg = self._registry.get(tool_id) if hasattr(self._registry, "get") else None
            if reg is None:
                logger.debug("AD-546: Build harness tool '%s' not registered; skipping", tool_id)
                continue
            defs.append(tool_registration_to_llm_definition(reg))
        return defs

    def _compose_system_prompt(self, spec: "BuildSpec") -> str:
        """Compose Standing Orders + BuildSpec constraints + tool-usage instructions."""
        # Pull engineering standing orders if available; fall back to inline.
        try:
            from probos.cognitive.standing_orders import compose_instructions
            base = compose_instructions(department="engineering", agent_type="builder") or ""
        except Exception:
            base = ""
        constraints = "\n".join(f"- {c}" for c in (spec.constraints or []))
        return (
            f"{base}\n\n"
            "You are the SWE crew agent executing a build via the native agentic harness.\n"
            "Use the provided tools to inspect the codebase before writing. "
            "Use `read_file` and `codebase_*` tools to understand existing code. "
            "Use `edit_file` for surgical changes within existing files; use `write_file` "
            "for new files. Use `run_command pytest <path>` to validate before claiming "
            "completion. End your final response with the final file content as either "
            "===FILE: path=== blocks (new files) or ===MODIFY: path=== blocks "
            "(with ===SEARCH===/===REPLACE===/===END REPLACE=== triples for changes).\n\n"
            f"Build constraints:\n{constraints or '- (none specified)'}\n"
        )

    def _format_build_message(self, spec: "BuildSpec", work_dir: str) -> str:
        return (
            f"# Build Spec: {spec.title}\n"
            f"AD Number: AD-{spec.ad_number}\n\n"
            f"## Description\n{spec.description}\n\n"
            f"## Target Files\n" + "\n".join(f"- {f}" for f in (spec.target_files or [])) + "\n\n"
            f"## Reference Files\n" + "\n".join(f"- {f}" for f in (spec.reference_files or [])) + "\n\n"
            f"## Test Files\n" + "\n".join(f"- {f}" for f in (spec.test_files or [])) + "\n\n"
            f"Working directory: {work_dir}\n"
        )
```

**Routing branch in `src/probos/cognitive/builder.py`:** Inside `SoftwareEngineerAgent.perceive()` at `:1964`, INSERT a routing check after the existing Visiting Builder + Transporter routing. The exact insertion site is after the Transporter result short-circuit returns and before the standard file-loading path. Use this SEARCH/REPLACE on the boundary line that ends the Transporter branch:

(Builder: locate the precise SEARCH anchor mid-build by reading the surrounding 6 lines around `:2030` in `cognitive/builder.py`. The branch should:
1. Check `getattr(self._runtime, 'config', None)` and resolve `cfg.native_swe_harness`.
2. If `cfg.enabled` is True AND `cfg.eligibility_modify_only` is True AND every `params['target_files']` resolves to an existing file in working tree → harness eligible.
3. Get harness via `getattr(self._runtime, 'native_builder_harness', None)`. If None → log INFO + skip (defensive degradation).
4. Call `await harness.run_build(spec, work_dir=os.getcwd(), agent_id=self.id, department='engineering', rank=self._resolve_rank() if hasattr(self,'_resolve_rank') else 'lieutenant')`.
5. Stash result on `self._transporter_result = {"action": "transporter_complete", "file_changes": result["file_changes"], "llm_output": result["llm_output"], "builder_source": "native_harness"}` reusing the existing short-circuit at `:2148`.
6. Stash metadata on `self._native_harness_metadata = result.get("metadata", {})` for later attachment to BuildResult.

The downstream `act()` method's `transporter_complete` branch at `:2197-2210` already constructs a result dict — extend it to include `metadata` from `self._native_harness_metadata` when present.)

---

## Section 9 — `src/probos/config.py` + `BuildResult.metadata` + `startup/finalize.py` wirer (AD-549)

**Pair 9a — `src/probos/config.py` insert NativeSWEHarnessConfig** immediately after `class SoftwareEngineerSpecialistsConfig(BaseModel):` block at `:1770`. (Builder: locate the closing line of that class — likely a closing `# ...` comment or blank line — and insert the new class below it.)

```python
class NativeSWEHarnessConfig(BaseModel):
    """AD-549: Configuration for the native SWE agentic harness.

    Default-False on `enabled` per AD-695 transitional-flag precedent —
    pool wiring + tool registration happen unconditionally, but route
    selection in SoftwareEngineerAgent.perceive() requires opt-in.
    """

    enabled: bool = Field(
        default=False,
        description="Master gate. When False, builds route to existing native/visiting paths.",
    )
    eligibility_modify_only: bool = Field(
        default=True,
        description="Phase α default. Only modify-only builds (all targets exist) eligible.",
    )
    max_iterations: int = Field(default=25, ge=1, le=200)
    max_fix_iterations: int = Field(default=5, ge=1, le=20)
    token_budget: int | None = Field(default=None, ge=1024)
    compaction_threshold_pct: float = Field(default=0.8, ge=0.1, le=0.95)
    blocked_paths: list[str] = Field(
        default_factory=lambda: ["src/probos/security/", ".env", "config/sealed_modules.yaml"],
        description="AD-548: Pre-hook denies tool calls touching these path substrings.",
    )
```

**Pair 9b — `SystemConfig.native_swe_harness` field** at `config.py:2734`:

```
===SEARCH===
    swe_specialists: SoftwareEngineerSpecialistsConfig = Field(
===REPLACE===
    native_swe_harness: NativeSWEHarnessConfig = Field(
        default_factory=NativeSWEHarnessConfig,
        description="AD-549: Native SWE agentic harness configuration.",
    )
    swe_specialists: SoftwareEngineerSpecialistsConfig = Field(
===END REPLACE===
```

**Pair 9c — `BuildResult.metadata`** at `cognitive/builder.py:160`:

```
===SEARCH===
@dataclass
class BuildResult:
    """Result of a builder agent execution."""

    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""
    fix_attempts: int = 0
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    builder_source: str = "native"  # "native" or "visiting" (AD-353)
===REPLACE===
@dataclass
class BuildResult:
    """Result of a builder agent execution."""

    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""
    fix_attempts: int = 0
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    builder_source: str = "native"  # "native" | "visiting" | "native_harness" (AD-353/546)
    # AD-549: Structured execution metadata. Populated by NativeBuilderHarness with
    # builder_type / iterations / tools_used / compactions / stopped_reason / total_tokens.
    metadata: dict[str, Any] = field(default_factory=dict)
===END REPLACE===
```

**Pair 9d — Finalize wirer in `src/probos/startup/finalize.py`** — locate the existing W97 specialty-pools wirer (likely `_wire_specialty_pools` or analogous adjacent function). INSERT a new wirer `_wire_native_swe_harness(*, runtime, config) -> bool` immediately AFTER it. Body:

```python
def _wire_native_swe_harness(*, runtime: ProbOSRuntime, config: SystemConfig) -> bool:
    """AD-543/544/548/549: Register native SWE tools, attach blocked-paths hook,
    construct NativeBuilderHarness, expose on runtime.

    Tool registration is unconditional (cheap, observable). Harness construction
    happens regardless; route selection in SoftwareEngineerAgent.perceive()
    gates by config.native_swe_harness.enabled.
    """
    try:
        from probos.cognitive.swe_harness.tools import register_native_swe_tools
        from probos.cognitive.swe_harness.policies import make_blocked_paths_hook
        from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
        from probos.cognitive.swe_harness.session_compactor import SessionCompactor

        registry = getattr(runtime, "tool_registry", None)
        executor = getattr(runtime, "tool_executor", None)
        if registry is None or executor is None:
            logger.info(
                "AD-549: tool_registry / tool_executor missing on runtime; "
                "skipping native SWE harness wire-up"
            )
            return False

        count = register_native_swe_tools(registry, runtime)
        cfg = config.native_swe_harness
        if cfg.blocked_paths:
            executor.add_pre_hook(make_blocked_paths_hook(cfg.blocked_paths))

        llm_client = getattr(runtime, "llm_client", None)
        if llm_client is None:
            logger.info("AD-549: llm_client missing; skipping NativeBuilderHarness construction")
            return False

        harness = NativeBuilderHarness(
            runtime=runtime,
            llm_client=llm_client,
            tool_executor=executor,
            tool_registry=registry,
            max_iterations=cfg.max_iterations,
            max_fix_iterations=cfg.max_fix_iterations,
            token_budget=cfg.token_budget,
            compactor=SessionCompactor(),
            compaction_threshold=int(cfg.compaction_threshold_pct * 100_000),  # heuristic char-budget
        )
        runtime.native_builder_harness = harness
        logger.info(
            "AD-549: Native SWE harness wired (tools=%d, enabled=%s, blocked_paths=%d)",
            count, cfg.enabled, len(cfg.blocked_paths),
        )
        return True
    except Exception:
        logger.warning(
            "AD-549: Native SWE harness wire-up failed; route selection will degrade to visiting/legacy",
            exc_info=True,
        )
        return False
```

Then call `_wire_native_swe_harness(runtime=runtime, config=config)` at the appropriate place in `finalize_startup()` — adjacent to the W97 specialty wirer call site (Builder: read finalize.py to confirm the exact line).

---

## Section 10 — Tracker updates

**`DECISIONS.md`** + **`decisions-era-4-evolution.md`** + **`docs/development/roadmap.md`**: flip `*(planned)*` to `*(v1 shipped Wave 98 — combined harness; AD-547b exact tokenizer / AD-548b YAML tool-policy schema / AD-549b A/B shadow-mode comparison deferred with forcing functions)*` for each of the seven AD entries (lines `:6677` / `:6707` / `:6734` / `:6768` / `:6797` / `:6817` / `:6844` in roadmap.md).

**`PROGRESS.md`**: INSERT a new closed-AD prose paragraph at the top (after line 3, before the first existing paragraph) summarising the wave with: AD numbers shipped, files touched, test count delta, three deferrals + forcing functions, banned-pattern audit clean, four review-pass record. Pattern matches the W97 / W96 / W95 / W90 entries already at `PROGRESS.md:3-44`.

**`prompts/wave-plan.yaml`**: append the W98 entry after the W97 tail (line `2610`).

```yaml
  - id: "98"
    title: "AD-543/544/545/546/547/548/549 v1 Native SWE Harness — Agentic Tool Loop (combined; closes #13)"
    kind: combo
    depends_on: ["97"]
    dispatch_prompt: "prompts/WAVE-98-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-543-549-native-swe-harness-v1.md"
    builder_required: true
    issues_to_close: [13]
    notes: |
      Combined v1 wave for the seven Native SWE Harness ADs (AD-543 ToolCall
      protocol + LLM extension, AD-544 12-tool native suite, AD-545 AgenticLoop,
      AD-546 NativeBuilderHarness + SoftwareEngineerAgent routing, AD-547
      SessionCompactor with len/4 token estimator, AD-548 standing-orders
      blocked-paths pre-hook, AD-549 NativeSWEHarnessConfig + BuildResult.metadata).
      Seven planned ADs shipped as one wave because the substrate has no
      observable behaviour without the loop and the loop cannot compile
      without the substrate; the spec's own implementation order at
      docs/development/roadmap.md:6868 already groups them.

      Three deferrals tracked with explicit forcing functions, NOT minted
      as new GH issues: AD-547b exact tokenizer (forcing function: first
      compaction false-trip where len/4 estimate diverges >25% from actual
      model context counting); AD-548b YAML tool-policy schema with hot-reload
      (forcing function: first production deny-policy that needs operator-side
      tunability without code change); AD-549b A/B shadow-mode comparison
      with build_metrics table + HXI Builder Comparison tab (forcing function:
      native harness enabled in default config AND first cross-builder file-change
      discrepancy detected).

      Heavy substrate reuse: AD-423a Tool Protocol at tools/protocol.py:83
      acts as AD-543's ToolDefinition surface (JSON-schema adapter, no
      parallel protocol); AD-448 ToolExecutor at tools/executor.py:40 acts
      as AD-543's ToolExecutor + AD-548's hook substrate; AD-448's
      make_audit_hook + EventType.TOOL_INVOKED at events.py:197 acts as
      AD-548's audit trail; AD-521 BuildPipeline at build_pipeline.py:36
      writes file_changes downstream (no pipeline kwargs added — harness
      produces upstream); AD-476 specialist subclasses at
      cognitive/builder_specialists.py untouched (orthogonal to harness).

      Pro-tier SWE-depth overlay (deeper-cognitive-chains variant, peer-level
      architectural review across subsystems, solution-tree-search,
      Cognitive-JIT-mastery) is class-extension territory under AD-452 and
      lives in the private commercial-repo path token surface; v1 ships zero
      closed-source content; descriptor-only references throughout. Two
      additional fleet-level out-of-repo surfaces: cross-instance
      native-vs-visiting-builder usage telemetry dashboard, per-fleet
      skill-catalog adoption metrics for SWE specialty distribution.
      Banned-pattern audit on this dispatch + per-AD prompt + this notes
      block: zero hits across all 11 patterns (descriptor-only references
      throughout; pre-commit hook simulation Select-String -SimpleMatch
      returns zero per pattern across all artefacts).

      4 review passes recorded: P1 (initial draft against HEAD 632398f —
      seven-section structure + reframe table + AD-543-549 spec mapping
      verified against docs/development/roadmap.md:6650-6868); P2
      (verify-first sweep — twenty grep-anchored claims confirmed,
      including AD-423a Tool Protocol reuse, AD-448 ToolExecutor reuse,
      AD-521 BuildPipeline non-modification, no parallel-define of
      ToolDefinition); P3 (reframe table — combined v1 not split, three
      forcing-function deferrals not hard-deferrals, Captain rule
      "don't defer unless no choice" satisfied non-vacuously by the three
      concrete adoption signals); P4 (banned-pattern audit + SEARCH/REPLACE
      uniqueness check across 9 sections plus 5 trackers; AD numbering
      verified AD-696 highest no collision, BF-596 highest no collision).

      Builder execution: read prompt top-to-bottom, apply 9 sections + 5
      tracker updates + 7 new test files. Verify git diff --stat shows
      5 trackers modified + ~6 source files modified + 7 new source files
      in cognitive/swe_harness/ + 7 new test files + this prompt + dispatch
      (Builder will archive after commit). Pre-commit hook runs naturally
      on commit. Full pytest gate (expected ≥12211 passed; minimum gate
      is +60 hard floor to allow up to ~10 boundary test deferrals
      mid-build for any single section that flips). Commit with
      "AD-543/544/545/546/547/548/549 v1: Native SWE Harness — agentic
      tool loop (combined wave; +73 tests; closes #13)". Archive both
      prompts. gh issue close 13 with the canonical paragraph in
      Section 8 of this per-AD prompt.
    status: pending
```

---

## Section 11 — Test plan (7 NEW test files, 73 nominal tests)

### `tests/test_ad543_tool_call_protocol.py` (14 tests)

1. `ToolCallRequest` constructs with auto-id and timestamp.
2. `ToolCallRequest` is frozen (mutation raises).
3. `ToolCallResult.from_tool_result` adapts AD-423a `ToolResult` preserving `output` + maps `error` to `is_error=True`.
4. `TextBlock` / `ToolUseBlock` / `ToolResultBlock` all expose `kind` literal.
5. `ContentBlock` union accepts each subtype.
6. `tool_registration_to_llm_definition` produces correct OpenAI shape (`{"type":"function","function":{"name","description","parameters"}}`).
7. `tool_registration_to_llm_definition` defaults `parameters` to `{"type":"object","properties":{}}` when input_schema is None/empty.
8. `LLMRequest.tools=None` preserves payload unchanged in `_call_openai` (verify via mocked httpx — payload has no `tools` / `tool_choice` keys).
9. `LLMRequest.tools=[{...}]` → payload contains `tools` and `tool_choice` keys.
10. `_call_openai` parses `tool_calls` array into `content_blocks` with one `ToolUseBlock` per entry.
11. `_call_openai` parses `function.arguments` JSON string into `arguments` dict.
12. `_call_openai` falls back to empty arguments dict on malformed JSON (with WARNING).
13. `LLMResponse.content_blocks` defaults to empty list when `tools` is None.
14. `MockLLMClient.script_content_blocks` queues a response consumed by next `complete()` call.

### `tests/test_ad544_native_tools.py` (16 tests)

1-12. Each of 12 tools: instantiate, expose `tool_id`/`name`/`tool_type`/`input_schema`/`output_schema` correctly.
13. `register_native_swe_tools` returns 12 + each tool registered with `domain="engineering"` + correct `default_permissions` matrix.
14. `ReadFileTool.invoke` reads existing file via runtime intent dispatch.
15. `WriteFileTool.invoke` returns error `ToolResult` when params missing required `content`.
16. `RunCommandTool.invoke` dispatches to ShellCommandAgent and returns `{stdout, stderr, exit_code}` shape.

### `tests/test_ad545_agentic_loop.py` (14 tests)

1. `AgenticResult` defaults are correct (`stopped_reason="complete"`, empty lists).
2. Loop with text-only response stops after iteration 1 with `stopped_reason="complete"`.
3. Loop with single tool_use → tool execution → text response stops at iteration 2.
4. Loop emits `AGENTIC_LOOP_ITERATION` event each iteration.
5. Loop emits `AGENTIC_TOOL_CALL_STARTED` and `AGENTIC_TOOL_CALL_COMPLETED` per tool use.
6. Loop max_iterations=2 forces stop with `stopped_reason="max_iterations"`.
7. Loop token_budget exhausted → `stopped_reason="token_budget"`.
8. Tool execution exception → `ToolCallResult(is_error=True)` fed back; loop continues.
9. LLM `complete()` exception → `stopped_reason="error"` + `result.error` populated.
10. Loop never raises (verified by inducing failures in tool executor + LLM).
11. Loop appends assistant turn + tool-result user turn each iteration.
12. Loop with 0 tools allowed (text-only) — single iteration text response.
13. Compactor invoked between iterations when `total_tokens >= compaction_threshold`.
14. Tool call history populated correctly across multi-iteration loop.

### `tests/test_ad546_native_builder_harness.py` (10 tests)

1. `NativeBuilderHarness.__init__` accepts all required + optional kwargs.
2. `_select_build_tools` returns subset filtered to build-relevant tool_ids.
3. `_compose_system_prompt` includes Standing Orders + constraints + tool-usage instructions.
4. `_format_build_message` includes title + AD number + target/reference/test files.
5. `run_build` invokes `AgenticLoop.run` and returns dict with `file_changes` + `metadata`.
6. `run_build` populates metadata with `builder_type="native_harness"` + `iterations` + `tools_used`.
7. `BuildPipeline.parse_file_blocks` is invoked on `agentic_result.final_text`.
8. `SoftwareEngineerAgent.perceive()` routes to native harness when `enabled=True` + eligibility met.
9. Native harness route bypassed when `enabled=False` (default).
10. Native harness route bypassed when target file does not exist (modify-only eligibility).

### `tests/test_ad547_session_compactor.py` (8 tests)

1. `estimate_tokens("")` returns 1.
2. `estimate_tokens("hello world")` returns `max(1, len(text)//4)` = 2.
3. `SessionCompactor.compact` short-circuits when `len(messages) <= preserve_count + 2`.
4. `compact` calls fast-tier LLM with summarisation prompt.
5. `compact` returns system + summary + last `preserve_count` messages.
6. `compact` re-compacts when first pass still exceeds budget.
7. `compact` falls back to original messages on LLM failure (with WARNING).
8. `compact` preserves original user task in compacted output.

### `tests/test_ad548_blocked_paths_policy.py` (6 tests)

1. `make_blocked_paths_hook([])` returns identity (always True).
2. `make_blocked_paths_hook(["src/probos/security/"])` denies `read_file` with matching path.
3. Hook denies `write_file` with matching path substring.
4. Hook denies `run_command` with matching command substring.
5. Hook permits tools with no `path` / `command` params (no enforcement).
6. Hook fails open (returns True) on internal exception with WARNING.

### `tests/test_ad549_harness_config_metadata.py` (5 tests)

1. `NativeSWEHarnessConfig()` defaults: `enabled=False`, `eligibility_modify_only=True`, `max_iterations=25`, `max_fix_iterations=5`, `token_budget=None`, `compaction_threshold_pct=0.8`, `blocked_paths=["src/probos/security/", ".env", "config/sealed_modules.yaml"]`.
2. `NativeSWEHarnessConfig(max_iterations=0)` raises validation error (`ge=1`).
3. `NativeSWEHarnessConfig(compaction_threshold_pct=1.0)` raises validation error (`le=0.95`).
4. `SystemConfig().native_swe_harness` is a `NativeSWEHarnessConfig` instance.
5. `BuildResult` accepts and preserves `metadata` dict (additive field).

---

## Section 12 — Verified Against Codebase (2026-05-07, HEAD 632398f)

```
Select-String -Path docs\development\roadmap.md -Pattern '^### Native SWE Harness' -SimpleMatch
  6650: ### Native SWE Harness (AD-543–549)

Select-String -Path docs\development\roadmap.md -Pattern '^\*\*AD-(543|544|545|546|547|548|549):' -AllMatches
  6677: **AD-543: Tool Execution Abstraction — ToolCall Protocol & Executor** *(planned, OSS, depends: AD-521)*
  6707: **AD-544: Native Tool Suite — ProbOS-Integrated Tool Implementations** *(planned, OSS, depends: AD-543)*
  6734: **AD-545: Agentic Loop Engine — Multi-Turn Tool-Calling Orchestrator** *(planned, OSS, depends: AD-543, AD-544)*
  6768: **AD-546: BuildPipeline Integration — Wiring the Harness into the Build System** *(planned, OSS, depends: AD-545, AD-521)*
  6797: **AD-547: Session Compaction — Context Window Management for Long Sessions** *(planned, OSS, depends: AD-545)*
  6817: **AD-548: Trust-Gated Tool Permissions & Standing Orders Hooks** *(planned, OSS, depends: AD-543, AD-544)*
  6844: **AD-549: Builder Migration & Validation** *(planned, OSS, depends: AD-546, AD-548)*

Select-String -Path src\probos\tools\protocol.py -Pattern '^class Tool|^class ToolRegistration|class ToolPermission'
  30: class ToolPermission(str, Enum):
  83: class Tool(Protocol):
  139: class ToolRegistration:

Select-String -Path src\probos\tools\executor.py -Pattern '^class ToolExecutor|def add_pre_hook|def add_post_hook'
  40: class ToolExecutor:
  60: def add_pre_hook(self, hook: PreHook) -> None:
  64: def add_post_hook(self, hook: PostHook) -> None:

Select-String -Path src\probos\events.py -Pattern 'TOOL_INVOKED|^class EventType'
  20: class EventType(str, Enum):
  197: TOOL_INVOKED = "tool_invoked"  # AD-448

Select-String -Path src\probos\types.py -Pattern '^class LLMRequest|^class LLMResponse'
  227: class LLMRequest:
  240: class LLMResponse:

Select-String -Path src\probos\cognitive\llm_client.py -Pattern 'class OpenAICompatibleClient|async def _call_openai|class MockLLMClient'
  44: class OpenAICompatibleClient(BaseLLMClient):
  660: async def _call_openai(
  860: class MockLLMClient(BaseLLMClient):

Select-String -Path src\probos\cognitive\builder.py -Pattern '^class BuildResult|^class SoftwareEngineerAgent|async def perceive|async def decide|async def act'
  160: class BuildResult:
  1690: class SoftwareEngineerAgent(CognitiveAgent):
  1964: async def perceive(self, intent: Any) -> dict:
  2144: async def decide(self, observation: dict) -> dict:
  2190: async def act(self, decision: dict) -> dict:

Select-String -Path src\probos\build_pipeline.py -Pattern '^class BuildPipeline|def execute_approved_build|def parse_file_blocks'
  36: class BuildPipeline:
  56: async def execute_approved_build(
  103: def parse_file_blocks(text: str) -> list[dict[str, Any]]:

Select-String -Path src\probos\config.py -Pattern 'class SoftwareEngineerSpecialistsConfig|class SystemConfig|swe_specialists:'
  1770: class SoftwareEngineerSpecialistsConfig(BaseModel):
  2705: class SystemConfig(BaseModel):
  2734: swe_specialists: SoftwareEngineerSpecialistsConfig = Field(

Select-String -Path src\probos\agents\file_reader.py,src\probos\agents\file_writer.py,src\probos\agents\shell_command.py,src\probos\agents\file_search.py -Pattern '^class.*Agent|async def handle_intent'
  agents/file_reader.py:16: class FileReaderAgent(BaseAgent):
  agents/file_reader.py:45: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  agents/file_search.py:15: class FileSearchAgent(BaseAgent):
  agents/file_search.py:38: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  agents/file_writer.py:15: class FileWriterAgent(BaseAgent):
  agents/file_writer.py:41: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  agents/shell_command.py:33: class ShellCommandAgent(BaseAgent):
  agents/shell_command.py:61: async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:

Select-String -Path src\probos\cognitive\codebase_index.py -Pattern '^class CodebaseIndex|def query|def find_callers|def find_tests_for|def get_imports|def find_importers'
  74: class CodebaseIndex:
  158: def query(self, concept: str) -> dict[str, Any]:
  339: def find_callers(self, method_name: str, max_results: int = 10) -> list[dict[str, Any]]:
  368: def find_tests_for(self, file_path: str) -> list[str]:
  397: def get_imports(self, file_path: str) -> list[str]:
  406: def find_importers(self, file_path: str) -> list[str]:

PROGRESS.md AD-(543|544|545|546|547|548|549) hits at HEAD: zero (verified pre-build — INSERT-only operation).
```

---

## Section 13 — Acceptance Criteria

1. All 9 sections applied with SEARCH/REPLACE pairs and new files created as specified.
2. All five trackers updated (DECISIONS / decisions-era-4 / roadmap / PROGRESS / wave-plan).
3. Seven new test files created with the 73 nominal tests detailed in Section 11.
4. Full pytest gate ≥12211 passed; minimum hard floor +60 against Captain reference 12138.
5. Banned-pattern audit on the resulting commit produces zero hits across all 11 patterns.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
7. Commit message: `"AD-543/544/545/546/547/548/549 v1: Native SWE Harness — agentic tool loop (combined wave; +73 tests; closes #13)"`.
8. Both prompts (this file + `prompts/WAVE-98-DISPATCH.md`) archived under `prompts/archive/` after commit. `gh issue close 13` with the canonical paragraph below.

### Section 8 canonical issue-close paragraph for `gh issue close 13`

> Closed by Wave 98 (AD-543/544/545/546/547/548/549 v1 combined Native SWE Harness, +73 tests). Substrate: ToolCallRequest/ToolCallResult/ContentBlock/TextBlock/ToolUseBlock/ToolResultBlock wire format + LLMRequest.tools/tool_choice extension + LLMResponse.content_blocks/stop_reason extension + OpenAICompatibleClient tool_calls parsing + MockLLMClient.script_content_blocks helper + tool_registration_to_llm_definition adapter (reuses AD-423a Tool Protocol + AD-423b ToolPermission + AD-423c ToolContext + AD-448 ToolExecutor without parallel-defining new protocols). Tool suite: 12 native adapters (read_file/write_file/edit_file/list_files/run_command/codebase_query/codebase_find_callers/codebase_find_tests/codebase_get_imports/codebase_read_source/standing_orders_lookup/system_self_model) registered into ToolRegistry under engineering domain with rank-keyed default_permissions. Loop: AgenticLoop class with max_iterations/token_budget/event-emit fire-and-forget pattern matching TRANSPORTER_DECOMPOSED + AgenticResult dataclass + three new EventType values (AGENTIC_TOOL_CALL_STARTED/AGENTIC_TOOL_CALL_COMPLETED/AGENTIC_LOOP_ITERATION). Compaction: SessionCompactor with len/4 token approximation + fast-tier LLM summarisation + re-compaction. Harness: NativeBuilderHarness wrapping AgenticLoop + SoftwareEngineerAgent.perceive() routing branch (default-False enabled flag, modify-only eligibility) + BuildResult.metadata dict. Permissions: AD-548 reframed to verify-only (AD-423b rank↔ToolPermission matrix already shipped) + make_blocked_paths_hook factory (AD-548b YAML schema deferred). Migration: NativeSWEHarnessConfig Pydantic model with AD-695 default-False precedent + finalize wirer (AD-549b shadow-mode comparison deferred). Three deferrals tracked with explicit forcing functions (AD-547b len/4 divergence >25%, AD-548b operator-tunability demand, AD-549b cross-builder discrepancy). Pro-tier SWE-depth overlay + cross-instance fleet telemetry + per-fleet skill catalog adoption metrics carry forward as out-of-repo plug-in points under AD-452 class-extension mechanism.
