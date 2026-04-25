# Phase 10: Self-Modification — The System Designs Its Own Agents

**Goal:** When ProbOS encounters an intent that no existing agent can handle, the cognitive layer designs a new agent type, validates it through a safety pipeline, and hot-loads it into the running system. The new agent starts with probationary trust, earns its way up through successful operations, and can be removed by the existing trust-aware scale-down if it underperforms.

This implements the Noöplex Agent Lifecycle Management (§7.10):

> *"Shadow deployment → Comparative evaluation → Knowledge impact assessment → Cutover or rollback"*

And fulfils the original ProbOS vision:

> *"New capability is added by introducing new agent types to the mesh. They self-integrate by broadcasting capabilities and forming connections."* — AD-81

The infrastructure for this already exists. `register_agent_type()` (AD-80) registers new agent classes and refreshes the decomposer. Phase 10 automates the pipeline that feeds into it.

---

## Context

Right now, when a user asks for something no agent handles, the decomposer returns `{"intents": [], "response": "I can't do that yet"}`. The system knows it can't help but has no mechanism to learn how.

ProbOS has 9 agent types handling 11 intents. The architecture was designed for extensibility — `register_agent_type()` already hot-loads new agent classes and refreshes the decomposer's intent table. But adding an agent type currently requires a developer to write Python code and restart the system.

This phase adds:
1. An `AgentDesigner` that generates agent code via LLM when an unhandled intent is detected
2. A `CodeValidator` that statically analyzes generated code for safety (AST analysis, forbidden imports, schema conformance)
3. A `SandboxRunner` that test-executes the generated agent in an isolated context
4. A `ProbationaryTrust` tier with lower starting prior for self-created agents
5. A `BehavioralMonitor` that tracks side effects of self-created agents beyond output verification
6. Integration with the existing `register_agent_type()` → decomposer refresh pipeline
7. A `/designed` shell command showing self-created agent status
8. User confirmation gate before any self-created agent goes live

**What the existing safety infrastructure already handles:**
- Consensus voting weights by trust → low-trust probationary agents can't swing outcomes
- Red team verification on outputs → self-created agents' results are verified like all others
- Trust-aware scale-down (AD-96) → underperforming self-created agents are removed first
- Hebbian routing → agents that fail don't get routed work
- Episodic memory → the system remembers whether self-created agents succeeded or failed

**What this phase adds that doesn't exist yet:**
- Code-level validation before the agent ever runs (static analysis)
- Behavioral monitoring of side effects (not just output correctness)
- Probationary trust tier (lower starting prior than established agents)
- Human confirmation before a self-designed agent enters the live system

---

## ⚠ AD Numbering: Start at AD-109

AD-101 through AD-108 exist from Phase 9. All architectural decisions in this phase start at **AD-109**. Do NOT reuse AD-101 through AD-108.

---

## ⚠ Pre-Build Audit: Existing Agent Structure

**Before writing any code**, examine the following to understand the agent contract:

1. `src/probos/substrate/agent.py` — `BaseAgent` ABC, `__init__` signature, lifecycle methods
2. `src/probos/agents/file_reader.py` — simplest existing agent (~40 lines), use as template reference
3. `src/probos/agents/directory_list.py` — another simple agent for reference
4. `src/probos/substrate/spawner.py` — `register_template()` and `spawn()` signatures
5. `src/probos/runtime.py` — `register_agent_type()` and `_collect_intent_descriptors()`
6. `src/probos/consensus/trust.py` — `TrustNetwork` constructor and how priors work

The generated agent code must conform exactly to the `BaseAgent` contract. Understanding the existing agents is essential before writing the code generation prompts.

---

## Deliverables

### 1. Add `SelfModConfig` to `src/probos/config.py`

```python
class SelfModConfig(BaseModel):
    """Self-modification configuration."""

    enabled: bool = False  # Disabled by default — opt-in capability
    require_user_approval: bool = True  # Human must confirm before agent goes live
    probationary_alpha: float = 1.0  # Beta prior alpha for self-created agents
    probationary_beta: float = 3.0   # Beta prior beta → E[trust] = 0.25
    max_designed_agents: int = 5  # Maximum self-created agent types in system
    sandbox_timeout_seconds: float = 10.0  # Timeout for sandbox test execution
    allowed_imports: list[str] = [  # Whitelist of allowed imports in generated code
        "asyncio", "pathlib", "json", "os", "re", "datetime",
        "typing", "dataclasses", "collections", "math", "hashlib",
        "urllib.parse", "base64", "csv", "io", "tempfile",
    ]
    forbidden_patterns: list[str] = [  # Patterns forbidden in generated code (regex)
        r"subprocess", r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
        r"eval\s*\(", r"exec\s*\(", r"__import__",
        r"open\s*\(.*['\"]w['\"]", r"socket\b", r"ctypes\b",
    ]
```

Add `self_mod: SelfModConfig = SelfModConfig()` to `SystemConfig`.

Add `self_mod:` section to `config/system.yaml` with defaults (enabled: false).

### 2. Create `src/probos/cognitive/agent_designer.py`

The `AgentDesigner` generates agent code via the LLM.

```python
# Template that the LLM uses to generate agent code.
# This is the prompt — the LLM fills in the blanks.
AGENT_DESIGN_PROMPT = """You are the cognitive layer of ProbOS, a probabilistic agent-native OS.
The system received an intent that no existing agent can handle.

UNHANDLED INTENT:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}

Your job is to write a Python agent class that handles this intent.
The agent MUST:
1. Subclass BaseAgent
2. Define intent_descriptors as a class variable
3. Implement handle_intent(self, intent: IntentMessage) -> IntentResult
4. Return IntentResult with success=True/False and data dict
5. Be self-contained (~40-80 lines)

TEMPLATE (fill in the implementation):

```python
from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult, IntentDescriptor

class {class_name}(BaseAgent):
    \"\"\"Auto-generated agent for {intent_name}.\"\"\"

    agent_type = "{agent_type}"
    _handled_intents = ["{intent_name}"]
    intent_descriptors = [
        IntentDescriptor(
            name="{intent_name}",
            params={param_schema},
            description="{intent_description}",
            requires_consensus={requires_consensus},
            requires_reflect=False,
        )
    ]

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None
        # YOUR IMPLEMENTATION HERE
```

RULES:
- Only use imports from this whitelist: {allowed_imports}
- Do NOT use subprocess, eval, exec, __import__, socket, ctypes
- Do NOT write files (no open() with 'w' mode) — use the existing FileWriterAgent for writes
- Do NOT make network calls — use the existing HttpFetchAgent for HTTP
- Return the COMPLETE Python file content, nothing else
- No markdown code fences, no explanation, just the Python code
"""


class AgentDesigner:
    """Designs new agent types via LLM when unhandled intents are detected.

    Flow:
    1. Receives unhandled intent description
    2. Builds prompt from AGENT_DESIGN_PROMPT template
    3. Calls LLM (standard tier) to generate agent code
    4. Returns raw code string for validation pipeline
    """

    def __init__(self, llm_client, config: SelfModConfig) -> None:
        self._llm = llm_client
        self._config = config

    async def design_agent(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        requires_consensus: bool = False,
    ) -> str:
        """Generate agent source code for an unhandled intent.

        Returns raw Python source code string.
        Raises ValueError if LLM returns unparseable output.
        """

    def _build_class_name(self, intent_name: str) -> str:
        """Convert intent_name like 'count_words' to 'CountWordsAgent'."""

    def _build_agent_type(self, intent_name: str) -> str:
        """Convert intent_name like 'count_words' to 'count_words'."""
```

### 3. Create `src/probos/cognitive/code_validator.py`

Static analysis of generated code before it ever executes.

```python
import ast


class CodeValidationError(Exception):
    """Raised when generated code fails validation."""
    pass


class CodeValidator:
    """Statically validates generated agent code for safety.

    Checks:
    1. Syntax validity (ast.parse)
    2. Forbidden imports (not in allowed_imports whitelist)
    3. Forbidden patterns (regex match against source)
    4. Schema conformance (has BaseAgent subclass, has intent_descriptors,
       has handle_intent method)
    5. No module-level side effects (no bare function calls at module level
       except class/function definitions and assignments)
    """

    def __init__(self, config: SelfModConfig) -> None:
        self._allowed_imports = set(config.allowed_imports)
        self._forbidden_patterns = config.forbidden_patterns

    def validate(self, source_code: str) -> list[str]:
        """Validate source code. Returns list of error strings.

        Empty list = validation passed.
        """

    def _check_syntax(self, source_code: str) -> list[str]:
        """Parse with ast.parse(). Returns errors if syntax is invalid."""

    def _check_imports(self, tree: ast.Module) -> list[str]:
        """Walk AST for Import and ImportFrom nodes.

        Any import not in allowed_imports whitelist is an error.
        """

    def _check_forbidden_patterns(self, source_code: str) -> list[str]:
        """Regex scan source code for forbidden patterns."""

    def _check_schema(self, tree: ast.Module) -> list[str]:
        """Verify AST contains:
        - Exactly one class that appears to subclass BaseAgent
        - Class has 'intent_descriptors' assignment
        - Class has 'handle_intent' async method
        - Class has 'agent_type' assignment
        - Class has '_handled_intents' assignment
        """

    def _check_module_side_effects(self, tree: ast.Module) -> list[str]:
        """Module-level statements must be: imports, class defs, function defs,
        assignments, or string expressions (docstrings).

        Bare function calls, loops, or conditionals at module level are errors.
        """
```

### 4. Create `src/probos/cognitive/sandbox.py`

Isolated test execution of generated agents.

```python
class SandboxResult:
    """Result of sandbox test execution."""
    success: bool
    agent_class: type | None  # The loaded class if successful
    error: str | None
    execution_time_ms: float


class SandboxRunner:
    """Test-executes a generated agent in an isolated context.

    The sandbox:
    1. Writes the source code to a temp file
    2. Loads it as a Python module via importlib
    3. Finds the BaseAgent subclass in the module
    4. Instantiates the agent
    5. Sends a synthetic test intent and verifies the agent responds
    6. Checks that the agent conforms to the BaseAgent contract
    7. Returns the loaded class if successful

    This is NOT a security sandbox (no seccomp, no containers).
    Security is handled by CodeValidator's static analysis.
    The SandboxRunner verifies functional correctness.
    """

    def __init__(self, config: SelfModConfig) -> None:
        self._timeout = config.sandbox_timeout_seconds

    async def test_agent(
        self,
        source_code: str,
        intent_name: str,
        test_params: dict | None = None,
    ) -> SandboxResult:
        """Load and test a generated agent.

        Steps:
        1. Write source to temp file
        2. importlib.util.spec_from_file_location + module_from_spec + exec_module
        3. Find the class (iterate module.__dict__ for BaseAgent subclasses)
        4. Instantiate with a mock registry
        5. Create a test IntentMessage with intent_name and test_params
        6. Call agent.handle_intent(test_intent) with asyncio.wait_for timeout
        7. Verify result is IntentResult or None
        8. Return SandboxResult with the class if successful
        """

    def _find_agent_class(self, module) -> type | None:
        """Find the BaseAgent subclass in a loaded module.

        Must be a direct subclass of BaseAgent (not BaseAgent itself).
        Must have intent_descriptors defined.
        """
```

**Design constraint:** The sandbox uses `importlib` to load code, not `exec()`. The `CodeValidator` already verified no `exec`/`eval` in the source. Loading via `importlib` gives a proper module with a proper class that can be passed to `register_agent_type()`.

### 5. Create `src/probos/cognitive/behavioral_monitor.py`

Monitors self-created agents for unexpected side effects.

```python
class BehavioralAlert:
    """A detected behavioral anomaly."""
    agent_id: str
    agent_type: str
    alert_type: str  # "slow_execution", "high_failure_rate", "unexpected_result_size"
    detail: str
    timestamp: float


class BehavioralMonitor:
    """Monitors self-created agents for behavioral anomalies.

    Unlike red team agents (which verify output correctness),
    the behavioral monitor tracks operational patterns:
    1. Execution time — is the agent consistently slower than expected?
    2. Failure rate — is the agent failing more than established agents?
    3. Result size — is the agent returning unexpectedly large payloads?
    4. Trust trajectory — is the agent's trust declining over time?

    The monitor does NOT block agent execution. It records alerts
    that are visible via /designed and can trigger removal recommendations.
    """

    def __init__(self) -> None:
        self._tracked_agents: dict[str, dict] = {}  # agent_type → tracking data
        self._alerts: list[BehavioralAlert] = []
        self._execution_times: dict[str, list[float]] = {}  # agent_type → durations
        self._failure_counts: dict[str, int] = {}
        self._success_counts: dict[str, int] = {}

    def track_agent_type(self, agent_type: str) -> None:
        """Start tracking a self-created agent type."""

    def record_execution(
        self,
        agent_type: str,
        duration_ms: float,
        success: bool,
        result_size: int = 0,
    ) -> None:
        """Record an execution by a self-created agent. Checks for anomalies."""

    def check_trust_trajectory(self, agent_type: str, trust_score: float) -> None:
        """Record a trust snapshot. Alert if trust is declining consistently."""

    def get_alerts(self, agent_type: str | None = None) -> list[BehavioralAlert]:
        """Return alerts, optionally filtered by agent type."""

    def get_status(self) -> dict:
        """Return monitoring status for all tracked agent types."""

    def should_recommend_removal(self, agent_type: str) -> bool:
        """Return True if behavioral evidence suggests the agent should be removed.

        Criteria: failure rate > 50% over 10+ executions, OR
        trust declining for 3+ consecutive observations, OR
        average execution time > 5x the sandbox test time.
        """
```

### 6. Add probationary trust to `TrustNetwork` — `src/probos/consensus/trust.py`

Minimal change — add a method to create trust records with custom priors:

```python
def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None:
    """Create a trust record with a custom Beta prior.

    Used for probationary agents (e.g., self-created with alpha=1, beta=3).
    If the agent already has a trust record, this is a no-op.
    """
    if agent_id not in self._records:
        self._records[agent_id] = {"alpha": alpha, "beta": beta}
```

The existing `create()` method uses Beta(2,2). Self-created agents use `create_with_prior()` with the configured `probationary_alpha` and `probationary_beta`. Everything else — observation recording, decay, scoring — works unchanged with the lower prior.

### 7. Create the self-modification pipeline — `src/probos/cognitive/self_mod.py`

This is the orchestrator that ties the components together.

```python
class DesignedAgentRecord:
    """Record of a self-created agent type."""
    intent_name: str
    agent_type: str
    class_name: str
    source_code: str
    created_at: float
    sandbox_time_ms: float
    pool_name: str
    status: str  # "active", "removed", "failed_validation", "rejected_by_user"


class SelfModificationPipeline:
    """Orchestrates the full self-modification flow.

    Flow:
    1. Detect unhandled intent (called by runtime when decomposer returns empty)
    2. Check config: is self_mod enabled? Under max_designed_agents?
    3. Ask user for approval to design an agent (if require_user_approval)
    4. Call AgentDesigner to generate code
    5. Call CodeValidator to statically analyze code
    6. Call SandboxRunner to test-execute the agent
    7. Register the agent type via register_fn callback
    8. Create a pool for the new agent type
    9. Set probationary trust for all agents in the new pool
    10. Track with BehavioralMonitor
    11. Retry the original intent
    """

    def __init__(
        self,
        designer: AgentDesigner,
        validator: CodeValidator,
        sandbox: SandboxRunner,
        monitor: BehavioralMonitor,
        config: SelfModConfig,
        register_fn: Callable,  # runtime.register_agent_type
        create_pool_fn: Callable,  # runtime creates a pool for the new type
        set_trust_fn: Callable,  # trust_network.create_with_prior
        user_approval_fn: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None: ...

    async def handle_unhandled_intent(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        requires_consensus: bool = False,
    ) -> DesignedAgentRecord | None:
        """Full pipeline: design → validate → sandbox → register → track.

        Returns DesignedAgentRecord if successful, None if any step fails.
        """

    def designed_agents(self) -> list[DesignedAgentRecord]:
        """Return all designed agent records (active and removed)."""

    def designed_agent_status(self) -> dict:
        """Return status summary for shell/panels."""
```

**Important design constraints:**
- The pipeline uses injected callables, NOT runtime references. Same pattern as `surge_fn` (AD-98), `idle_scale_down_fn` (AD-99), `_federation_fn` (AD-103). The pipeline receives `register_fn`, `create_pool_fn`, `set_trust_fn`, `user_approval_fn`.
- `user_approval_fn` is an async callable that presents the proposed agent to the user and returns True/False. The shell provides this. When `require_user_approval` is False, this step is skipped.
- If any step fails (validation errors, sandbox crash, user rejection), the pipeline returns None and the intent remains unhandled. The failure is logged as a `DesignedAgentRecord` with the appropriate status.
- The pipeline stores generated source code in `DesignedAgentRecord` for auditability.

### 8. Wire into runtime — `src/probos/runtime.py`

```python
# In __init__:
self.self_mod_pipeline: SelfModificationPipeline | None = None
self.behavioral_monitor: BehavioralMonitor | None = None

# In start(), after pool creation:
if self.config.self_mod.enabled:
    from probos.cognitive.agent_designer import AgentDesigner
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.sandbox import SandboxRunner
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.self_mod import SelfModificationPipeline

    designer = AgentDesigner(self.llm_client, self.config.self_mod)
    validator = CodeValidator(self.config.self_mod)
    sandbox = SandboxRunner(self.config.self_mod)
    self.behavioral_monitor = BehavioralMonitor()

    self.self_mod_pipeline = SelfModificationPipeline(
        designer=designer,
        validator=validator,
        sandbox=sandbox,
        monitor=self.behavioral_monitor,
        config=self.config.self_mod,
        register_fn=self._register_designed_agent,
        create_pool_fn=self._create_designed_pool,
        set_trust_fn=self._set_probationary_trust,
        user_approval_fn=None,  # Shell sets this after creation
    )

# New methods:
async def _register_designed_agent(self, agent_class: type) -> None:
    """Register a self-designed agent class. Wraps register_agent_type()."""
    self.register_agent_type(agent_class)

async def _create_designed_pool(self, agent_type: str, pool_name: str, size: int = 2) -> None:
    """Create a pool for a self-designed agent type."""
    pool = ResourcePool(
        name=pool_name,
        agent_type=agent_type,
        target_size=size,
        spawner=self.spawner,
        registry=self.registry,
        pool_config=self.config.pools,
    )
    await pool.start()
    self.pools[pool_name] = pool

async def _set_probationary_trust(self, agent_ids: list[str]) -> None:
    """Set probationary trust for self-created agents."""
    for aid in agent_ids:
        self.trust_network.create_with_prior(
            aid,
            alpha=self.config.self_mod.probationary_alpha,
            beta=self.config.self_mod.probationary_beta,
        )
```

### 9. Detect unhandled intents in `process_natural_language()` — `src/probos/runtime.py`

```python
# In process_natural_language(), after decomposition:
# If decomposer returns empty intents and self_mod is enabled:
if (
    dag and not dag.nodes and not dag.response
    and self.self_mod_pipeline
):
    # Ask the LLM what the user wanted (intent name + description)
    # This is a lightweight LLM call to extract intent metadata
    intent_meta = await self._extract_unhandled_intent(text)
    if intent_meta:
        record = await self.self_mod_pipeline.handle_unhandled_intent(
            intent_name=intent_meta["name"],
            intent_description=intent_meta["description"],
            parameters=intent_meta.get("parameters", {}),
            requires_consensus=intent_meta.get("requires_consensus", False),
        )
        if record and record.status == "active":
            # Retry the original request now that the new agent exists
            dag = await self.decomposer.decompose(text, context)
            # ... continue with normal execution ...
```

Add a new LLM prompt for intent extraction:

```python
INTENT_EXTRACTION_PROMPT = """The user asked ProbOS to do something, but no existing agent can handle it.
User request: "{text}"

Extract what kind of agent would be needed. Respond with ONLY a JSON object:
{{
    "name": "intent_name_snake_case",
    "description": "What this intent does in one sentence",
    "parameters": {{"param_name": "description"}},
    "requires_consensus": false
}}

Rules:
- name must be snake_case, 2-4 words (e.g., "count_words", "parse_json", "calculate_checksum")
- Do NOT create intents that duplicate existing capabilities: {existing_intents}
- requires_consensus should be true only for destructive or external operations
"""
```

### 10. Add `/designed` command to shell — `src/probos/experience/shell.py`

```python
elif cmd == "/designed":
    if self.runtime.self_mod_pipeline:
        from probos.experience.panels import render_designed_panel
        status = self.runtime.self_mod_pipeline.designed_agent_status()
        if self.runtime.behavioral_monitor:
            status["behavioral"] = self.runtime.behavioral_monitor.get_status()
        self.console.print(render_designed_panel(status))
    else:
        self.console.print("[yellow]Self-modification not enabled[/yellow]")
```

Wire the `user_approval_fn` in the shell:

```python
# In shell setup, after runtime is available:
if self.runtime.self_mod_pipeline:
    self.runtime.self_mod_pipeline._user_approval_fn = self._design_approval_callback

async def _design_approval_callback(self, description: str) -> bool:
    """Present a proposed agent design to the user for approval."""
    self.console.print(f"\n[bold yellow]⚡ ProbOS wants to create a new agent:[/bold yellow]")
    self.console.print(description)
    response = input("\nApprove this agent? [y/N]: ").strip().lower()
    return response in ("y", "yes")
```

### 11. Add `render_designed_panel()` to `src/probos/experience/panels.py`

Rich table showing per designed agent:
- Agent type / class name
- Intent handled
- Status (active / removed / failed)
- Created timestamp
- Trust score (current)
- Execution count (success / failure)
- Behavioral alerts (count)

### 12. Add MockLLMClient patterns for testing — `src/probos/cognitive/llm_client.py`

Add patterns to `MockLLMClient` for:
- Agent design requests (detect AGENT_DESIGN_PROMPT signature, return valid agent code)
- Intent extraction requests (detect INTENT_EXTRACTION_PROMPT signature, return valid JSON)

The mock agent code should be a minimal valid agent that handles a test intent (e.g., `count_words`) and returns a simple result. This enables the full pipeline to be tested without a live LLM.

### 13. Add self-mod events to renderer — `src/probos/experience/renderer.py`

Handle events:
- `"🔧 Designing agent for: count_words"`
- `"✓ Agent CountWordsAgent validated and loaded"`
- `"✗ Agent design failed: forbidden import 'subprocess'"`

---

## Test Plan — ~40 new tests in `tests/test_self_mod.py`

### TestSelfModConfig (3 tests)
1. Defaults: enabled=False, require_user_approval=True, max 5 agents
2. Custom values override defaults
3. SystemConfig includes self_mod section

### TestAgentDesigner (4 tests)
4. design_agent returns valid Python source code (via MockLLMClient)
5. Class name correctly derived from intent name (count_words → CountWordsAgent)
6. Agent type correctly derived from intent name
7. Design prompt includes allowed_imports whitelist

### TestCodeValidator (12 tests)
8. Valid agent code passes all checks (empty error list)
9. Syntax error detected (invalid Python)
10. Forbidden import detected (subprocess)
11. Forbidden import detected (socket)
12. Allowed import passes (pathlib, json, re)
13. Forbidden pattern detected (eval())
14. Forbidden pattern detected (exec())
15. Forbidden pattern detected (open with 'w')
16. Missing BaseAgent subclass detected
17. Missing intent_descriptors detected
18. Missing handle_intent method detected
19. Module-level side effect detected (bare function call)

### TestSandboxRunner (5 tests)
20. Valid agent loads and handles test intent successfully
21. Agent that raises exception returns SandboxResult with success=False
22. Agent that times out returns SandboxResult with success=False
23. Agent that returns wrong type returns SandboxResult with success=False
24. Loaded class is a proper BaseAgent subclass

### TestBehavioralMonitor (6 tests)
25. track_agent_type registers agent for monitoring
26. record_execution tracks success/failure counts
27. High failure rate triggers alert
28. Slow execution triggers alert
29. should_recommend_removal True when failure rate > 50% over 10+ executions
30. should_recommend_removal False when agent performing well

### TestProbationaryTrust (3 tests)
31. create_with_prior creates record with custom alpha/beta
32. create_with_prior is no-op if record exists
33. Probationary agent has E[trust] = 0.25 (alpha=1, beta=3)

### TestSelfModPipeline (5 tests)
34. Full pipeline: design → validate → sandbox → register (end-to-end with mocks)
35. Pipeline stops at validation failure (returns None, record has failed_validation status)
36. Pipeline stops at sandbox failure (returns None, record has status)
37. Pipeline stops at user rejection (returns None, record has rejected_by_user status)
38. Pipeline respects max_designed_agents limit

### TestRuntimeSelfMod (4 tests)
39. Runtime creates pipeline when self_mod.enabled=True
40. Runtime does NOT create pipeline when self_mod.enabled=False
41. Unhandled intent triggers pipeline (end-to-end with MockLLMClient)
42. status() includes self_mod info

### TestDesignedPanels (2 tests)
43. render_designed_panel shows agent records
44. /designed command renders panel (or "not enabled")

---

## Build Order

Follow this sequence. Run `uv run pytest tests/ -v` after each step and confirm all tests pass before moving on.

1. **Pre-build audit**: Read BaseAgent, FileReaderAgent, DirectoryListAgent, spawner, runtime.register_agent_type(), TrustNetwork. Understand the agent contract.
2. **SelfModConfig**: Add to `config.py` and `SystemConfig`. Add to `system.yaml`. Write tests 1–3.
3. **CodeValidator**: Create `cognitive/code_validator.py` with AST analysis. Write tests 8–19.
4. **AgentDesigner**: Create `cognitive/agent_designer.py`. Add MockLLMClient patterns. Write tests 4–7.
5. **SandboxRunner**: Create `cognitive/sandbox.py`. Write tests 20–24.
6. **BehavioralMonitor**: Create `cognitive/behavioral_monitor.py`. Write tests 25–30.
7. **ProbationaryTrust**: Add `create_with_prior()` to TrustNetwork. Write tests 31–33.
8. **SelfModificationPipeline**: Create `cognitive/self_mod.py`. Wire components. Write tests 34–38.
9. **Runtime wiring**: Wire pipeline creation in runtime start(). Add `_register_designed_agent`, `_create_designed_pool`, `_set_probationary_trust`. Add unhandled intent detection in `process_natural_language()`. Write tests 39–42.
10. **Shell and panels**: Add `/designed` command. Wire `user_approval_fn`. Add `render_designed_panel()`. Write tests 43–44.
11. **Renderer events**: Add self-mod event handling.
12. **`/help` update**: Add `/designed` to help output.
13. **PROGRESS.md update**: Document Phase 10, all ADs (starting at AD-109), test counts.
14. **Final verification**: `uv run pytest tests/ -v` — all tests pass.

---

## Architectural Decisions to Document

- **AD-109**: Self-modification is opt-in (`enabled: false` by default). The system never designs agents unless explicitly configured. This is the most safety-critical capability in ProbOS and must require conscious opt-in.
- **AD-110**: Human approval gate before self-designed agents go live. When `require_user_approval=True` (default), the user sees the proposed agent description and source code and must confirm. This implements the Noöplex governance principle — "safety constraints that cannot be overridden by any agent" (§4.3.4).
- **AD-111**: Static code analysis via AST, not runtime sandboxing. The `CodeValidator` uses Python's `ast` module to parse generated code into an abstract syntax tree and walks it checking for forbidden imports, forbidden patterns, schema conformance, and module-level side effects. This catches unsafe code before it ever executes. The `SandboxRunner` then tests functional correctness — it's not a security boundary.
- **AD-112**: Probationary trust via custom Beta priors. Self-created agents start at Beta(1,3) → E[trust] = 0.25. Established agents start at Beta(2,2) → E[trust] = 0.5. This means self-created agents need more successful observations to reach the same trust level. Consensus voting, which weights by trust, naturally de-weights probationary agents. Trust-aware scale-down removes them first when they underperform (AD-96).
- **AD-113**: Import whitelist, not blocklist. Generated code can only import from `allowed_imports`. This is safer than a blocklist — unknown dangerous imports are blocked by default. The whitelist is intentionally conservative (stdlib only, no network, no filesystem modification).
- **AD-114**: Forbidden pattern regex as defense in depth. In addition to import whitelisting, the validator regex-scans source code for patterns like `eval(`, `exec(`, `subprocess`, `socket`, `open(...'w'...)`. This catches attempts to sneak dangerous operations through string manipulation or aliasing that AST import analysis might miss.
- **AD-115**: BehavioralMonitor is observational, not blocking. The monitor tracks execution patterns (speed, failure rate, trust trajectory, result size) and raises alerts, but never blocks agent execution. Removal decisions are surfaced as recommendations via `/designed`. The user or trust-aware scale-down performs actual removal.
- **AD-116**: Self-modification pipeline uses injected callables. Same pattern as AD-98 (surge_fn), AD-99 (idle_scale_down_fn), AD-103 (federation_fn). The pipeline receives `register_fn`, `create_pool_fn`, `set_trust_fn`, `user_approval_fn`. No runtime reference. Keeps the pipeline testable without a full runtime.
- **AD-117**: Agent code loaded via importlib, not exec(). Generated source is written to a temp file and loaded as a proper Python module via `importlib.util.spec_from_file_location`. This gives a real module with a real class that can be inspected, registered, and spawned through the existing `AgentSpawner` infrastructure. The CodeValidator already verified no exec/eval in the source.
- **AD-118**: Retry after successful agent creation. When the pipeline successfully creates and registers a new agent, the runtime re-decomposes the original user request. The decomposer's intent table now includes the new intent (via `register_agent_type()` → `refresh_descriptors()`), so the LLM can route to the new agent. If re-decomposition still fails, the system reports failure normally.
- **AD-119**: Designed agent source stored for auditability. `DesignedAgentRecord` stores the full Python source code that was generated, validated, and loaded. This is visible via `/designed` and enables post-hoc review of what the system created. The source is the provenance record — you can always see exactly what code is running.

---

## Non-Goals

- **Container/seccomp sandboxing**: The sandbox is a functional correctness test, not a security boundary. Security comes from static analysis (whitelist imports, forbidden patterns, AST checking). Container sandboxing would add Docker as a dependency, violating the zero-corporate-dependency principle.
- **Self-modifying existing agents**: The system creates new agent types. It does not modify the source code of existing agents. That would require a different (and more dangerous) pipeline.
- **Automatic agent removal**: The BehavioralMonitor recommends removal but never removes agents automatically. The user decides via `/designed`, or trust-aware scale-down handles it naturally. No autonomous agent removal without human visibility.
- **Cross-node agent propagation**: Self-designed agents are local to the node that created them. Sharing agent designs across federated nodes is a future phase that requires cross-node governance.
- **Persistent agent storage**: Designed agents live in memory. If the node restarts, they're gone. Persistent storage of designed agent code (to disk or Git) is a future phase.
- **Learning from failed designs**: The pipeline doesn't use failed design attempts to improve future designs. Feedback from validation/sandbox failures could be fed back to the LLM, but this adds prompt complexity for marginal benefit at this stage.
