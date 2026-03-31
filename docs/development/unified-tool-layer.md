# AD-543: Unified Tool Layer — Skill-Tool Binding & Agentic Tool Adapters

*"The crew member is the sovereign constant; everything else is infrastructure."*

## Context

ProbOS has extensive **design** for the tool layer (AD-422 taxonomy, AD-423 registry, AD-483 instruments) but limited **implementation** (one hardcoded adapter in `cognitive/copilot_adapter.py`). The current Copilot SDK integration works but has three architectural problems:

1. **Wrong location:** `CopilotBuilderAdapter` lives in `cognitive/` — implying it's a cognitive component. It's a tool. Tools don't think; crew members think.
2. **Hardcoded to one role:** The adapter is Builder-specific, but the same external tools serve Code Review, Test Writing, and infrastructure roles. GitHub Copilot CLI's `/review` command is a code review tool; its agentic loop writes tests. One tool, multiple crew skills.
3. **No skill↔tool binding:** Three systems exist independently — SkillFramework (AD-428, how well agents do things), CapabilityRegistry (what agents can do), and the Tool Layer design (AD-422/423/483, what tools are available). The missing link: how a crew member's skill resolves to a tool.

Additionally, the "visiting officer" language was applied to tools, creating confusion. Per AD-398's three-tier architecture: tools have no sovereign identity. Real visiting officers are future federation crew from other ProbOS ships. The language cleanup is overdue.

## Decision

### Part 1: `src/probos/tools/` Package — Tool Layer Home

Create a new top-level package for all tool-layer code. This is the physical manifestation of AD-422/423/483 in the source tree.

```
src/probos/tools/
  __init__.py              # Package exports
  protocol.py             # AgenticToolAdapter protocol + base Tool protocol
  context_provider.py     # ProbOS MCP context provider (extracted from copilot_adapter)
  copilot_adapter.py      # CopilotSDKAdapter (moved from cognitive/copilot_adapter.py)
```

**What moves:**
- `cognitive/copilot_adapter.py` → `tools/copilot_adapter.py` (renamed: `CopilotBuilderAdapter` → `CopilotSDKAdapter`)
- MCP tool construction logic extracted into `context_provider.py` — reusable by any adapter

**What stays in `cognitive/`:**
- `builder.py` — still a CognitiveAgent. It *uses* tools; it doesn't *become* one.
- `builder.py` imports from `tools.copilot_adapter` instead of `cognitive.copilot_adapter`

### Part 2: AgenticToolAdapter Protocol

A generic interface for external AI coding tools. Any tool that provides an agentic loop (read files, generate code, iterate, run tests) implements this protocol.

```python
# src/probos/tools/protocol.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class AgenticToolAdapter(Protocol):
    """Protocol for external AI coding tools used by ProbOS crew.

    An agentic tool provides a full agent loop (plan, code, iterate, test)
    governed by ProbOS's chain of command. The tool executes; ProbOS controls
    context, commits, model selection, and output capture.

    Implementations: CopilotSDKAdapter, ClaudeCodeAdapter (future),
    CodexAdapter (future).
    """

    @classmethod
    def is_available(cls) -> bool:
        """Check if this tool is installed and accessible."""
        ...

    async def start(self) -> None:
        """Initialize the tool (auth, session setup)."""
        ...

    async def stop(self) -> None:
        """Shut down the tool (cleanup, session teardown)."""
        ...

    async def execute(
        self,
        spec: "BuildSpec",
        file_contents: dict[str, str],
        *,
        timeout: float = 300.0,
    ) -> "AgenticToolResult":
        """Execute a task using the tool's agentic loop.

        The tool receives:
        - spec: What to build (title, description, target files, constraints)
        - file_contents: Current state of relevant files
        - timeout: Maximum execution time

        The tool returns:
        - AgenticToolResult with file changes, raw output, success status

        ProbOS controls everything else: Standing Orders (via system message),
        context (via MCP tools), model selection, output validation.
        """
        ...

    async def list_capabilities(self) -> list[str]:
        """What this tool can do: ["code-generation", "code-review", "test-generation"]."""
        ...

    @property
    def tool_id(self) -> str:
        """Unique identifier for this tool in the ToolRegistry."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name for HXI display."""
        ...
```

**`AgenticToolResult` dataclass:**

```python
@dataclass
class AgenticToolResult:
    success: bool
    file_blocks: list[dict]      # [{path, content, mode}] — same format as BuilderAgent
    raw_output: str
    error: str | None = None
    tool_id: str = ""
    model_used: str = ""
    tokens_used: int = 0
    duration_seconds: float = 0.0
    capabilities_used: list[str] = field(default_factory=list)  # Which capabilities were exercised
```

**Relationship to AD-483 `Tool` base class:** `AgenticToolAdapter` is a specialization. AD-483's `Tool` is the generic callable instrument (file reader, HTTP fetch). `AgenticToolAdapter` is specifically for tools that run their own agentic loop. The `ToolRegistry` (AD-423) registers both — an `AgenticToolAdapter` is a `Tool` with `category=agentic`.

**Three Execution Models:**

The protocol is deliberately execution-model-agnostic. Under the hood, `execute()` can use any of these — the crew member never knows or cares:

| Model | Execution Pattern | Context Delivery | Output Capture | Example |
|-------|------------------|-----------------|----------------|---------|
| **SDK (in-process)** | Python library call, session-based | MCP tools registered on session | SDK return values + worktree scan | Copilot SDK (`session.send_and_wait()`) |
| **CLI (subprocess)** | `asyncio.create_subprocess_exec()` with timeout + kill | `--system-prompt` flag, `--mcp-server` flag, stdin injection, context files in worktree | stdout/stderr capture + worktree diff (before/after snapshot) | Claude Code (`claude --print`), Codex CLI |
| **API (HTTP)** | `httpx.AsyncClient` POST/stream | Request body (system message, tools array) | JSON response body | Future cloud-hosted agentic tools |

**CLI-specific patterns (subprocess adapters):**

CLI tools like Claude Code CLI and Codex CLI are shell commands, not libraries. Their adapters handle:

1. **Subprocess lifecycle** — `asyncio.create_subprocess_exec()` with `timeout` enforcement. On timeout: `SIGTERM` → grace period → `SIGKILL`. On cancellation: clean process teardown.
2. **Working directory isolation** — CLI tools operate in the worktree directory (already provided by BuildDispatcher). The adapter sets `cwd=worktree_path` on the subprocess.
3. **File change detection** — Snapshot the worktree file tree + hashes before invocation. After completion, diff against snapshot. New/modified files become `file_blocks` in `AgenticToolResult`. This is the same pattern `CopilotBuilderAdapter` already uses (lines 288-320 in current code: `cwd.rglob("*")` scan).
4. **Context injection** — Each CLI has its own flags:
   - Claude Code: `claude --print --system-prompt "..." --mcp-server "probos-context"` or context via `CLAUDE.md` file placed in worktree
   - Codex: `codex --model ... --prompt "..."` with context in prompt or config
   - Generic: Standing Orders + file contents injected via system prompt flag or stdin
5. **Non-interactive mode** — CLI tools must run in non-interactive (headless) mode. Claude Code's `--print` flag, Codex's API mode, etc. Interactive TUI modes are incompatible with subprocess capture.
6. **Auth via environment** — CLI tools authenticate via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GH_TOKEN`). The adapter sets these on the subprocess environment, sourced from ProbOS's credential configuration (future CredentialStore).
7. **Output parsing** — Raw stdout is parsed for file blocks. The existing `BuilderAgent._parse_file_blocks()` function handles `===FILE:===` / `===MODIFY:===` format. CLI tools that produce structured output (JSON mode) get a format-specific parser; tools that produce free-form output fall back to the file block parser or worktree diff.

**The key insight:** From the crew member's perspective, all three models look identical. Scotty says "generate code for this spec." Whether that invokes a Python SDK, spawns a shell process, or calls a cloud API is an adapter implementation detail behind the `AgenticToolAdapter` protocol. The crew member's skill is the same; the tool is interchangeable.

### Part 3: ProbOS Context Provider

The current `CopilotBuilderAdapter._build_mcp_tools()` hardcodes MCP tool construction. Extract this into a reusable provider that any adapter can use.

```python
# src/probos/tools/context_provider.py

class ProbOSContextProvider:
    """Provides ProbOS context to external agentic tools.

    Exposes internal capabilities (CodebaseIndex, SystemSelfModel,
    Standing Orders) in a tool-agnostic format. Each adapter translates
    these into its tool's native format (MCP tools for Copilot SDK,
    system prompt injection for Claude Code CLI, etc.).
    """

    def __init__(self, *, codebase_index=None, runtime=None):
        self._codebase_index = codebase_index
        self._runtime = runtime

    def get_context_tools(self) -> list[ContextToolSpec]:
        """Return tool specifications for all available ProbOS context.

        Each ContextToolSpec has: name, description, parameters, handler.
        Adapters translate these into their native format.
        """
        ...

    def compose_system_message(self, *, role: str = "builder") -> str:
        """Compose Standing Orders for the given role.

        Uses compose_instructions() to assemble the full chain:
        Federation → Ship → Department → Agent.
        """
        ...
```

**Why extract?** The Copilot SDK adapter wraps these as MCP `Tool` objects. A Claude Code CLI adapter would inject them differently (e.g., `--system-prompt` flag + STDIN context). A Codex adapter might package them as API function definitions. The context is the same; the delivery format varies by tool.

### Part 4: Skill→Tool Resolution

Connect AD-428 SkillFramework to the tool layer. When a crew member exercises a skill, the system resolves which tool(s) can fulfill it.

**New concept: `ToolRequirement`**

```python
@dataclass
class ToolRequirement:
    """What a skill needs from the tool layer."""
    capabilities: list[str]                # Required tool capabilities
    preferred_categories: list[str] = ()   # e.g., ["agentic", "onboard"]
    tool_allowlist: list[str] | None = None  # If set, only these tools
    tool_denylist: list[str] = ()          # Never use these tools
```

**Extended SkillDefinition:**

```python
# In skill_framework.py, SkillDefinition gains:
tool_requirements: ToolRequirement | None = None
```

**Resolution flow:**

```
1. Crew member exercises skill (e.g., "code-generation")
2. SkillDefinition.tool_requirements specifies: capabilities=["code-generation"]
3. ToolRegistry.discover(capabilities=["code-generation"]) returns:
   [copilot-sdk (weight=0.8), native-llm (weight=0.4)]
4. HebbianRouter.get_preferred_targets("code-generation", candidates) ranks by learned weight
5. Cost-aware filter applies (if commercial): prefer lower-cost tool at comparable quality
6. Fallback cascade: if preferred tool unavailable, next candidate
7. Selected tool executes via AgenticToolAdapter.execute()
```

**Skill→Tool examples:**

| Skill | tool_requirements.capabilities | Fulfilled By |
|-------|-------------------------------|--------------|
| Code Generation (PCC) | `["code-generation"]` | CopilotSDK, ClaudeCode, NativeLLM |
| Code Review (PCC) | `["code-review"]` | CopilotSDK (/review), NativeReviewer |
| Codebase Analysis (Role) | `["codebase-query", "import-graph"]` | CodebaseIndex (internal only) |
| Test Generation (Role) | `["code-generation", "test-execution"]` | CopilotSDK, ClaudeCode |
| Vulnerability Scan (Role) | `["security-scan"]` | Internal scanner, external tool |
| Desktop Automation (Acquired) | `["computer-use"]` | Anthropic Computer Use (external only) |

Some skills have mixed tool eligibility (internal + external). Some are internal-only (codebase analysis — no external tool has the ship's index). Some are external-only (computer use — no internal equivalent yet). The `ToolRequirement` makes this explicit.

### Part 5: Fallback Cascades & Cost-Aware Routing

**A. Fallback Cascades**

When a tool is unavailable (CLI not installed, API down, token quota exhausted), the system falls back to the next viable tool automatically.

```python
@dataclass
class FallbackChain:
    capability: str
    providers: list[str]      # Ordered tool_ids: preferred → fallback
    routing: str = "hebbian"  # "hebbian" | "round-robin" | "cost-optimized"
```

The HebbianRouter already supports `get_preferred_targets(source, candidates)` which ranks by learned weight. Extend with availability check:

```
1. HebbianRouter ranks candidates by weight
2. Filter to available tools (is_available() == True)
3. Apply cost filter if routing == "cost-optimized"
4. Return first available candidate
5. If none available: degrade gracefully, return error to crew member
```

This replaces the current binary `_should_use_visiting_builder()` with a generalized multi-tool resolution.

**B. Cost-Aware Routing**

HebbianRouter's `_score_match()` currently uses only success/failure signals. For commercial deployments, add a cost factor:

| Tool | Cost Model | Est. Cost/Task |
|------|-----------|---------------|
| Native LLM (Copilot proxy) | Included in subscription | ~$0 |
| Copilot SDK | Premium request quota | ~$0.10-0.50/task |
| Claude Code CLI | Anthropic API billing | ~$0.50-5.00/task |
| Codex CLI | OpenAI API billing | ~$0.20-2.00/task |

Commercial routing: `score = hebbian_weight * (1.0 - cost_weight * normalized_cost)`. The `cost_weight` is configurable per deployment (0.0 = pure quality, 1.0 = pure cost optimization).

This is a **commercial feature** — OSS always routes by quality (Hebbian + availability). Commercial adds cost awareness.

### Part 6: Bidirectional MCP

**Outbound (already implemented):** ProbOS exposes internal capabilities TO external tools via MCP. Currently hardcoded in `CopilotBuilderAdapter._build_mcp_tools()`. Moves to `ProbOSContextProvider`.

**Inbound (designed, not implemented):** External MCP servers consumed BY ProbOS crew. Designed in AD-449 (MCP Bridge). When the ToolRegistry and MCP Bridge are implemented, external MCP servers auto-register as ProbOS tools.

**Symmetry principle:** Agentic tools are both consumers (they use ProbOS's CodebaseIndex) and providers (they offer code generation). The adapter protocol handles both directions:

```
Outbound: ProbOSContextProvider → adapter-specific format → external tool
Inbound:  External tool → AgenticToolResult → ProbOS guardrail pipeline
```

### Part 7: Language Cleanup — Retiring "Visiting Officer" for Tools

Per AD-398, tools have no sovereign identity. The "visiting officer" label was incorrectly applied to external AI tools. Update:

| Current Language | New Language |
|-----------------|-------------|
| "Visiting officer" (for tools) | "Agentic tool" or "external tool" |
| `CopilotBuilderAdapter` | `CopilotSDKAdapter` |
| `_should_use_visiting_builder()` | `_select_agentic_tool()` |
| `builder_source: "visiting"` | `builder_source: "copilot-sdk"` (tool_id) |
| `REL_BUILDER_VARIANT` targets `"visiting"/"native"` | Targets tool_ids: `"copilot-sdk"/"native-llm"` |
| Roadmap "Visiting Officer" section title | "Agentic Tools — External AI Coding Tools" |

**What keeps "Visiting Officer":** The federation concept of crew from another ProbOS ship visiting this ship's Ward Room. That IS a visiting officer — a sovereign individual from another command. Tools are not this.

**Files to update:**
- `src/probos/cognitive/copilot_adapter.py` — module docstring, class name, comments
- `src/probos/cognitive/builder.py` — `_should_use_visiting_builder()` name, `builder_source` values, comments
- `src/probos/mesh/routing.py` — Hebbian weight targets (data migration)
- `docs/development/roadmap.md` — section titles, narrative
- `docs/development/tool-taxonomy.md` — minor language updates
- `C:\Users\seang\.claude\projects\d--ProbOS\memory\visiting-officers.md` — retitle, update framing
- `C:\Users\seang\.claude\projects\d--ProbOS\memory\copilot-sdk.md` — update framing
- Prompt files in `prompts/` — `copilot-sdk-visiting-officer.md`, etc.

### Part 8: Implementation Blueprint

**Phase 1 (Foundation) — Can be a single build prompt:**

1. Create `src/probos/tools/` package
2. Define `AgenticToolAdapter` protocol + `AgenticToolResult` in `tools/protocol.py`
3. Extract `ProbOSContextProvider` from `CopilotBuilderAdapter._build_mcp_tools()`
4. Move + rename `CopilotBuilderAdapter` → `CopilotSDKAdapter` in `tools/copilot_adapter.py`
5. Update all imports: `builder.py`, `build_dispatcher.py`, tests
6. Language cleanup in source code (docstrings, variable names, comments)
7. Backward-compat: `cognitive/copilot_adapter.py` re-exports from new location (deprecated)

**Phase 2 (Skill→Tool Binding) — Separate AD/build:**

1. Add `ToolRequirement` to `SkillDefinition` in `skill_framework.py`
2. Generalize `_should_use_visiting_builder()` → multi-tool resolution using HebbianRouter
3. `FallbackChain` configuration
4. Update BuildDispatcher to accept any `AgenticToolAdapter`, not just Copilot

**Phase 3 (New Adapters) — Per-tool builds:**

1. `ClaudeCodeAdapter` — spawn `claude --print` subprocess, scan for changes
2. `CodexAdapter` — Codex CLI integration
3. Each gets its own build prompt when the tool matures

**Phase 4 (Commercial Extensions):**

1. Cost-aware routing in HebbianRouter
2. Tool usage metering + billing
3. Nooplex tool marketplace

## What NOT to Do

- Do NOT move `BuilderAgent` out of `cognitive/` — it's a CognitiveAgent (crew role), not a tool
- Do NOT implement `ToolRegistry` in this AD — that's AD-483's scope (Phase 25b)
- Do NOT change any threshold values or behavior — this is structural refactoring
- Do NOT implement ClaudeCodeAdapter or CodexAdapter yet — protocol + CopilotSDK relocation only
- Do NOT modify the guardrail pipeline (`execute_approved_build()`) — it already works for any tool output
- Do NOT create a `Tool` base class — that's AD-483. This AD defines `AgenticToolAdapter` as a specialization

## Principles Compliance

- **SOLID (D):** `AgenticToolAdapter` protocol enables dependency inversion — BuilderAgent depends on the protocol, not CopilotSDKAdapter
- **SOLID (S):** Context provision (what the tool knows) separated from tool execution (what the tool does)
- **SOLID (I):** Narrow `AgenticToolAdapter` protocol — 6 methods. Tools implement only what they need.
- **DRY:** ProbOSContextProvider eliminates future per-adapter duplication of MCP tool construction
- **Law of Demeter:** BuilderAgent talks to tools through the protocol, never reaches into tool internals
- **AD-398:** Tools stay in the tool layer. Crew stays in cognitive. Clean separation.
- **Cloud-Ready:** Cost-aware routing planned as commercial extension

## Relationship to Existing ADs

| AD | Relationship |
|----|-------------|
| AD-398 | Three-tier architecture: this AD enforces tools≠crew at the code level |
| AD-422 | Tool taxonomy: agentic tools are a tool category, not a new concept |
| AD-423 | Tool Registry: `AgenticToolAdapter` registers there when ToolRegistry is built |
| AD-428 | Skill Framework: `ToolRequirement` connects skills to tools |
| AD-448 | Security Intercept: wraps tool calls with logging/rate limiting |
| AD-449 | MCP Bridge: bidirectional MCP design that this AD prepares for |
| AD-483 | Tool Layer Instruments: `AgenticToolAdapter` is a specialization of `Tool` |
| AD-351–355 | Copilot SDK: existing implementation that gets relocated + generalized |
| AD-542 | Database abstraction: same DI pattern (protocol + factory + default impl) |

## Prior Art

- **DSPy modules** — modules optimized independently of LLM provider. Same skill, different tool → different performance. Validates the skill↔tool separation.
- **Voyager skill library** — skills stored as reusable programs with tool references. Maps to SkillDefinition + ToolRequirement.
- **AutoGen/CrewAI tool binding** — bind tools at agent registration time. ProbOS's approach (dynamic resolution via HebbianRouter) is more flexible.
- **Kubernetes Operator pattern** — controllers reconcile desired state using available resources. Crew exercises skill (desired state), tool layer resolves to available tool (resource).
- **Service mesh (Istio)** — transparent routing layer between services. The tool layer is ProbOS's service mesh for capabilities.
- **Unix philosophy** — small, composable tools. Crew composes tools (CodebaseIndex → BuilderTool → TestRunner → Git) the same way shell scripts compose CLI tools.
