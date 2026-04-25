# AD-423a: Tool Foundation — Tool Protocol + ToolRegistry

**Ticket:** AD-423a (Issue #144)
**Absorbs:** AD-483 (Issue #77 — close when complete)
**Depends on:** AD-422 (Tool Taxonomy, complete), AD-398 (three-tier classification, complete)
**Unlocks:** AD-423b (permissions), AD-423c (ToolContext + onboarding), AD-543–549 (Native SWE Harness)

## Problem

ProbOS has 9 categories of tools (utility agents, infra services, MCP servers, remote APIs, computer use, browser, communication, federation, deterministic functions) but no unified runtime interface. Each tool type is accessed through bespoke code paths — Ward Room via service calls, CodebaseIndex via intent bus, episodic recall via direct method calls. There is no way for an agent to discover, enumerate, or invoke tools through a common protocol.

The ontology has static `ToolCapability` definitions in `resources.yaml` (7 entries), but no runtime registry consumes them. The `CapabilityRegistry` in `mesh/capability.py` matches *agent capabilities* to intents — it is not a tool registry.

AD-423a establishes the foundation layer: a `Tool` protocol, a `ToolRegistry` service, and adapter implementations that wrap existing infrastructure as `Tool` instances.

## Design Decisions

1. **In-memory registry, no SQLite.** Unlike ClearanceGrantStore or SkillRegistry, tool definitions are deterministic from code + config. They are registered at startup and unregistered at shutdown. No user-created tools. No persistence layer in AD-423a. (AD-423b may add persistence for permission state.)

2. **Protocol, not ABC.** `Tool` is a `typing.Protocol` (Interface Segregation). Adapters implement it; no forced inheritance hierarchy.

3. **Enum from taxonomy.** `ToolType` enum with 9 values matching AD-422's taxonomy.

4. **ToolPreference on SkillDefinition.** Closes the Skill→Tool link in the capability hierarchy. Priority-ranked tool selection per skill.

5. **Seed from ontology.** At startup, the 7 `ToolCapability` entries from `resources.yaml` are converted to `ToolRegistration` records and registered.

6. **No agent-side wiring in AD-423a.** Agents do not get a `ToolContext` or use tools via the registry yet — that is AD-423c. This AD builds the registry and adapters only.

## Scope — 8 Changes

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/tools/__init__.py` | NEW — package init |
| 2 | `src/probos/tools/protocol.py` | NEW — Tool protocol, ToolType enum, ToolResult, ToolRegistration |
| 3 | `src/probos/tools/registry.py` | NEW — ToolRegistry service |
| 4 | `src/probos/tools/adapters.py` | NEW — InfraServiceAdapter, DirectServiceAdapter, DeterministicFunctionAdapter |
| 5 | `src/probos/skill_framework.py` | MODIFY — add ToolPreference dataclass, preferred_tools field on SkillDefinition |
| 6 | `src/probos/startup/results.py` | MODIFY — add tool_registry field to CommunicationResult |
| 7 | `src/probos/startup/communication.py` | MODIFY — create and seed ToolRegistry |
| 8 | `src/probos/runtime.py` | MODIFY — wire tool_registry |

No shutdown entry needed (in-memory, no DB connection to close).
No API router in AD-423a (deferred to AD-423b/c which add queryable endpoints with permission filtering).
No shell command (no user-facing CRUD — tools are code-defined).

---

## Change 1 — `src/probos/tools/__init__.py` (NEW)

```python
"""AD-423a: Tool Foundation — unified tool interface for ProbOS.

Provides the Tool protocol, ToolRegistry service, and adapter
implementations that wrap existing Ship's Computer services,
infrastructure agents, and deterministic functions as Tool instances.
"""
```

---

## Change 2 — `src/probos/tools/protocol.py` (NEW)

```python
"""AD-423a: Tool protocol and core types.

Defines the uniform interface for all tool types in ProbOS.
Absorbs AD-483 (Tool Layer — Instruments) programming model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ToolType(str, Enum):
    """Nine-category tool taxonomy (AD-422)."""

    UTILITY_AGENT = "utility_agent"
    INFRA_SERVICE = "infra_service"
    MCP_SERVER = "mcp_server"
    REMOTE_API = "remote_api"
    COMPUTER_USE = "computer_use"
    BROWSER = "browser"
    COMMUNICATION = "communication"
    FEDERATION = "federation"
    DETERMINISTIC_FUNCTION = "deterministic_function"


@dataclass(frozen=True)
class ToolResult:
    """Result of a tool invocation."""

    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


@runtime_checkable
class Tool(Protocol):
    """Uniform interface for all ProbOS tools.

    A Tool is any callable instrument an agent can invoke —
    a Ship's Computer service, an infrastructure agent, an MCP server,
    a deterministic function, etc.

    Implementations satisfy this protocol; no inheritance required
    (Interface Segregation Principle).
    """

    @property
    def tool_id(self) -> str:
        """Unique identifier (e.g., 'codebase_query', 'ward_room_post')."""
        ...

    @property
    def name(self) -> str:
        """Human-readable display name."""
        ...

    @property
    def tool_type(self) -> ToolType:
        """Category from the AD-422 taxonomy."""
        ...

    @property
    def description(self) -> str:
        """What this tool does — shown in discovery results."""
        ...

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema describing accepted parameters."""
        ...

    @property
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema describing the result structure."""
        ...

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            params: Input parameters matching input_schema.
            context: Optional invocation context (agent_id, department, etc.).
                     AD-423c will formalize this as ToolContext.

        Returns:
            ToolResult with output or error.
        """
        ...


@dataclass
class ToolRegistration:
    """Metadata record for a registered tool.

    Wraps a Tool instance with registration metadata used by the
    ToolRegistry for lookup, filtering, and lifecycle management.
    """

    tool: Tool
    domain: str = "*"  # "security", "engineering", "medical", "*" (universal)
    department: str | None = None  # Restricts to a department (None = ship-wide)
    tags: list[str] = field(default_factory=list)  # Capability tags for discovery
    provider: str = ""  # "ship_computer", "ward_room", "dreaming_engine", etc.
    enabled: bool = True
    registered_at: float = field(default_factory=time.time)

    @property
    def tool_id(self) -> str:
        return self.tool.tool_id

    @property
    def tool_type(self) -> ToolType:
        return self.tool.tool_type

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "tool_id": self.tool.tool_id,
            "name": self.tool.name,
            "tool_type": self.tool.tool_type.value,
            "description": self.tool.description,
            "domain": self.domain,
            "department": self.department,
            "tags": self.tags,
            "provider": self.provider,
            "enabled": self.enabled,
            "input_schema": self.tool.input_schema,
            "output_schema": self.tool.output_schema,
        }


@dataclass
class ToolPreference:
    """Priority-ranked tool selection for a skill.

    Links SkillDefinition → Tool with priority ordering.
    When a skill needs a tool, preferences are tried in priority order
    (lower number = higher priority). Fallback cascade is AD-423c scope.
    """

    tool_id: str
    priority: int = 0  # Lower = higher priority
    context: str = ""  # When to prefer this tool (e.g., "when offline", "for large files")
```

---

## Change 3 — `src/probos/tools/registry.py` (NEW)

```python
"""AD-423a: ToolRegistry — runtime catalog of available tools.

In-memory registry. Tools are registered at startup from code and
ontology config. No SQLite persistence (tools are deterministic from
code + config, not user-created).

Follows SkillRegistry's cache-based lookup pattern.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.tools.protocol import Tool, ToolRegistration, ToolType

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Ship's Computer service — manages the runtime catalog of available tools.

    Infrastructure tier (no identity). Provides register/unregister/lookup
    for all tool types. Tools are registered at startup and remain available
    until shutdown or explicit unregister.

    Public API:
        register(tool, **kwargs) → ToolRegistration
        unregister(tool_id) → bool
        get(tool_id) → ToolRegistration | None
        list_tools(tool_type?, domain?, department?, tag?, enabled_only?) → list[ToolRegistration]
        get_tool(tool_id) → Tool | None  (convenience — unwraps registration)
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}

    def register(
        self,
        tool: Tool,
        *,
        domain: str = "*",
        department: str | None = None,
        tags: list[str] | None = None,
        provider: str = "",
        enabled: bool = True,
    ) -> ToolRegistration:
        """Register a tool in the catalog.

        If a tool with the same tool_id already exists, it is replaced
        (last-write-wins). Logs a warning on replacement.
        """
        if tool.tool_id in self._tools:
            logger.warning(
                "Replacing existing tool registration: %s", tool.tool_id,
            )
        reg = ToolRegistration(
            tool=tool,
            domain=domain,
            department=department,
            tags=tags or [],
            provider=provider,
            enabled=enabled,
        )
        self._tools[tool.tool_id] = reg
        logger.debug("Tool registered: %s (%s)", tool.tool_id, tool.tool_type.value)
        return reg

    def unregister(self, tool_id: str) -> bool:
        """Remove a tool from the catalog. Returns True if found."""
        removed = self._tools.pop(tool_id, None)
        if removed:
            logger.debug("Tool unregistered: %s", tool_id)
        return removed is not None

    def get(self, tool_id: str) -> ToolRegistration | None:
        """Look up a registration by tool_id."""
        return self._tools.get(tool_id)

    def get_tool(self, tool_id: str) -> Tool | None:
        """Look up a Tool instance by tool_id (convenience)."""
        reg = self._tools.get(tool_id)
        return reg.tool if reg else None

    def list_tools(
        self,
        *,
        tool_type: ToolType | None = None,
        domain: str | None = None,
        department: str | None = None,
        tag: str | None = None,
        enabled_only: bool = True,
    ) -> list[ToolRegistration]:
        """List tool registrations with optional filters.

        Args:
            tool_type: Filter by ToolType enum value.
            domain: Filter by domain ("security", "engineering", "*").
            department: Filter by department restriction.
            tag: Filter by capability tag (substring match on tag list).
            enabled_only: If True (default), exclude disabled tools.
        """
        results = list(self._tools.values())
        if enabled_only:
            results = [r for r in results if r.enabled]
        if tool_type is not None:
            results = [r for r in results if r.tool_type == tool_type]
        if domain is not None:
            results = [r for r in results if r.domain in (domain, "*")]
        if department is not None:
            results = [r for r in results if r.department is None or r.department == department]
        if tag is not None:
            tag_lower = tag.lower()
            results = [r for r in results if any(tag_lower in t.lower() for t in r.tags)]
        return sorted(results, key=lambda r: r.tool_id)

    def count(self) -> int:
        """Total registered tools."""
        return len(self._tools)

    def enabled_count(self) -> int:
        """Count of enabled tools."""
        return sum(1 for r in self._tools.values() if r.enabled)
```

---

## Change 4 — `src/probos/tools/adapters.py` (NEW)

```python
"""AD-423a: Tool adapters — wrap existing infrastructure as Tool instances.

Three adapter types for the initial foundation:
- InfraServiceAdapter: wraps infrastructure agents (dispatched via intent bus)
- DirectServiceAdapter: wraps Ship's Computer services (direct method calls)
- DeterministicFunctionAdapter: wraps synchronous callables (Cognitive JIT procedures)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Awaitable

from probos.tools.protocol import Tool, ToolResult, ToolType

logger = logging.getLogger(__name__)


class InfraServiceAdapter:
    """Wraps an infrastructure agent as a Tool.

    Invocations are dispatched via the intent bus. The adapter
    translates Tool.invoke() params into an IntentMessage and
    awaits the result.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        intent_name: str,
        intent_bus: Any = None,  # IntentBus — late-bound to avoid circular imports
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._intent_name = intent_name
        self._intent_bus = intent_bus

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    def set_intent_bus(self, bus: Any) -> None:
        """Late-bind the intent bus (available after startup)."""
        self._intent_bus = bus

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        if self._intent_bus is None:
            return ToolResult(error="Intent bus not available")
        t0 = time.monotonic()
        try:
            from probos.types import IntentMessage

            intent = IntentMessage(
                intent=self._intent_name,
                payload=params,
                source=context.get("agent_id", "tool_registry") if context else "tool_registry",
            )
            result = await self._intent_bus.dispatch(intent)
            elapsed = (time.monotonic() - t0) * 1000
            if result and getattr(result, "success", False):
                return ToolResult(output=getattr(result, "data", None), duration_ms=elapsed)
            err = getattr(result, "error", "Unknown error") if result else "No result"
            return ToolResult(error=str(err), duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("InfraServiceAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)


class DirectServiceAdapter:
    """Wraps a Ship's Computer service method as a Tool.

    For services like EpisodicMemory, TrustNetwork, KnowledgeStore
    where invocation is a direct async method call.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        handler: Callable[..., Awaitable[Any]],
        tool_type: ToolType = ToolType.INFRA_SERVICE,
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._handler = handler
        self._tool_type = tool_type

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        t0 = time.monotonic()
        try:
            result = await self._handler(**params)
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResult(output=result, duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("DirectServiceAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)


class DeterministicFunctionAdapter:
    """Wraps a synchronous callable as a Tool.

    For Cognitive JIT executable skills — deterministic functions that
    were extracted from LLM workflows and compiled to direct code.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        handler: Callable[..., Any],
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._handler = handler

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        t0 = time.monotonic()
        try:
            result = self._handler(**params)
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResult(output=result, duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("DeterministicFunctionAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)
```

---

## Change 5 — `src/probos/skill_framework.py` (MODIFY)

### 5a. Import ToolPreference

After the existing imports (near line 17), add:

```python
from probos.tools.protocol import ToolPreference
```

### 5b. Add `preferred_tools` field to SkillDefinition

At `src/probos/skill_framework.py` — `SkillDefinition` dataclass (line 54), add after the `origin` field (line 63):

```python
    preferred_tools: list[ToolPreference] = field(default_factory=list)
```

This closes the Skill→Tool link: `Agent → Role → Duties → Skills → Tools`.

### 5c. Update `_row_to_definition()` in SkillRegistry

At line 348, the `_row_to_definition` method. Add preferred_tools deserialization after the `origin` field:

```python
    def _row_to_definition(self, row) -> SkillDefinition:
        prefs_raw = json.loads(row["preferred_tools"] if "preferred_tools" in row.keys() else "[]")
        prefs = [ToolPreference(tool_id=p["tool_id"], priority=p.get("priority", 0), context=p.get("context", "")) for p in prefs_raw]
        return SkillDefinition(
            skill_id=row["skill_id"],
            name=row["name"],
            category=SkillCategory(row["category"]),
            description=row["description"] or "",
            domain=row["domain"] or "*",
            prerequisites=json.loads(row["prerequisites"] or "[]"),
            decay_rate_days=row["decay_rate_days"] or 14,
            origin=row["origin"] or "built_in",
            preferred_tools=prefs,
        )
```

### 5d. Update `register_skill()` to persist preferred_tools

At line 360, the `register_skill` method. The INSERT statement needs preferred_tools added:

```python
    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
        """Register or update a skill definition."""
        self._cache[defn.skill_id] = defn
        if self._db:
            prefs_json = json.dumps([{"tool_id": p.tool_id, "priority": p.priority, "context": p.context} for p in defn.preferred_tools])
            await self._db.execute(
                "INSERT OR REPLACE INTO skill_definitions "
                "(skill_id, name, category, description, domain, prerequisites, decay_rate_days, origin, preferred_tools) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (defn.skill_id, defn.name, defn.category.value, defn.description,
                 defn.domain, json.dumps(defn.prerequisites), defn.decay_rate_days, defn.origin, prefs_json),
            )
            await self._db.commit()
        return defn
```

### 5e. Schema migration — add preferred_tools column

At module level, after the existing `_SCHEMA` string (near line 306), add a migration helper that the `start()` method calls:

```python
_MIGRATE_PREFERRED_TOOLS = """
ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]';
"""
```

In `SkillRegistry.start()`, after `await self._db.executescript(_SCHEMA)` and before `await self._db.commit()` (line 336):

```python
            # AD-423a: Add preferred_tools column if missing (migration)
            try:
                await self._db.execute(_MIGRATE_PREFERRED_TOOLS)
                await self._db.commit()
            except Exception:
                pass  # Column already exists
```

---

## Change 6 — `src/probos/startup/results.py` (MODIFY)

### 6a. Add TYPE_CHECKING import

In the `if TYPE_CHECKING:` block (lines 17–55), add:

```python
    from probos.tools.registry import ToolRegistry
```

### 6b. Add field to CommunicationResult

At `CommunicationResult` (line 138), add after `clearance_grant_store` (line 152):

```python
    tool_registry: "ToolRegistry | None"
```

---

## Change 7 — `src/probos/startup/communication.py` (MODIFY)

### 7a. Create and seed ToolRegistry

After the clearance grant store block (line 249) and before the Cognitive Journal block (line 251), insert:

```python
    # --- Tool Registry (AD-423a) ---
    from probos.tools.registry import ToolRegistry

    tool_registry = ToolRegistry()

    # Seed from ontology tool capabilities (resources.yaml)
    if ontology:
        from probos.tools.adapters import DirectServiceAdapter
        from probos.tools.protocol import ToolType

        for tc in ontology.get_tool_capabilities():
            # Map provider string to ToolType
            _type_map = {
                "ship_computer": ToolType.INFRA_SERVICE,
                "ward_room": ToolType.COMMUNICATION,
                "dreaming_engine": ToolType.INFRA_SERVICE,
            }
            adapter = DirectServiceAdapter(
                tool_id=tc.id,
                name=tc.name,
                description=tc.description,
                handler=_noop_handler,
                tool_type=_type_map.get(tc.provider, ToolType.INFRA_SERVICE),
            )
            tool_registry.register(
                adapter,
                provider=tc.provider,
                tags=[tc.id, tc.provider],
            )

    logger.info("tool-registry started (%d tools)", tool_registry.count())
```

### 7b. Add the noop handler near the top of the file

After the existing imports (around line 15), add:

```python
async def _noop_handler(**kwargs: Any) -> None:
    """Placeholder handler for ontology-seeded tools.

    AD-423c will replace these with real service bindings during
    onboarding when ToolContext is established.
    """
    return None
```

### 7c. Add tool_registry to CommunicationResult return

At the return statement (line 342), add `tool_registry=tool_registry`:

```python
    return CommunicationResult(
        persistent_task_store=persistent_task_store,
        work_item_store=work_item_store,
        ward_room=ward_room,
        assignment_service=assignment_service,
        bridge_alerts=bridge_alerts,
        cognitive_journal=cognitive_journal,
        skill_registry=skill_registry,
        skill_service=skill_service,
        acm=acm,
        ontology=ontology,
        clearance_grant_store=clearance_grant_store,
        tool_registry=tool_registry,
    )
```

---

## Change 8 — `src/probos/runtime.py` (MODIFY)

### 8a. Class-level type annotation

At line 200 (deferred-init services section), after `clearance_grant_store` (line 200), add:

```python
    tool_registry: ToolRegistry | None
```

And in the TYPE_CHECKING import block at the top of the file, add:

```python
    from probos.tools.registry import ToolRegistry
```

### 8b. `__init__` initialization

After the clearance grants initialization (line 390), add:

```python
        # --- Tool Registry (AD-423a) ---
        self.tool_registry: ToolRegistry | None = None
```

### 8c. `start()` assignment

After `self.clearance_grant_store = comm.clearance_grant_store` (line 1380), add:

```python
        self.tool_registry = comm.tool_registry
```

---

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **Single Responsibility** | `protocol.py` = types only, `registry.py` = lookup only, `adapters.py` = bridging only |
| **Open/Closed** | New tool types added by writing new adapters, not modifying registry |
| **Interface Segregation** | `Tool` is a `typing.Protocol` — adapters implement what they need |
| **Dependency Inversion** | Registry depends on `Tool` protocol, not concrete adapters |
| **Law of Demeter** | Adapters wrap service access; callers don't reach through objects |
| **Cloud-Ready Storage** | No DB in AD-423a; if persistence is added in AD-423b, it will follow ConnectionFactory pattern |
| **DRY** | ToolPreference lives in `protocol.py` and is imported into `skill_framework.py` — single definition |
| **Fail Fast** | Adapter `invoke()` catches exceptions and returns ToolResult with error — log-and-degrade tier |

---

## Tests — `tests/test_ad423a_tool_foundation.py` (NEW)

22 tests across 6 classes.

### Class 1: `TestToolProtocol` (3 tests)

```
test_tool_result_success — ToolResult with output, no error → success=True
test_tool_result_failure — ToolResult with error → success=False
test_tool_type_enum_values — All 9 ToolType values present and are str enum
```

### Class 2: `TestToolRegistration` (3 tests)

```
test_registration_to_dict — ToolRegistration.to_dict() includes all fields
test_registration_properties — tool_id and tool_type delegate to wrapped tool
test_tool_preference_dataclass — ToolPreference fields: tool_id, priority, context
```

### Class 3: `TestToolRegistry` (8 tests)

```
test_register_and_get — register a tool, get() returns registration
test_register_replace_warns — registering same tool_id logs warning, replaces
test_unregister — unregister removes tool, returns True; second call returns False
test_get_tool_convenience — get_tool() returns Tool instance, not registration
test_get_missing — get() returns None for unknown tool_id
test_list_tools_no_filter — list_tools() returns all enabled tools sorted by tool_id
test_list_tools_with_filters — filter by tool_type, domain, department, tag
test_list_tools_enabled_only — disabled tools excluded by default, included when enabled_only=False
```

### Class 4: `TestInfraServiceAdapter` (3 tests)

```
test_invoke_success — mock intent bus returns success → ToolResult.success=True
test_invoke_no_bus — invoke without intent bus → ToolResult.error="Intent bus not available"
test_invoke_bus_error — intent bus raises exception → ToolResult with error string
```

### Class 5: `TestDirectServiceAdapter` (3 tests)

```
test_invoke_async_handler — async handler called with params → output captured
test_invoke_handler_error — handler raises → ToolResult with error
test_custom_tool_type — custom tool_type passed to constructor is preserved
```

### Class 6: `TestDeterministicFunctionAdapter` (2 tests)

```
test_invoke_sync_handler — sync callable invoked → result captured
test_invoke_handler_error — handler raises → ToolResult with error string
```

### Bonus: `TestSkillDefinitionToolPreference` (2 tests in existing skill framework test file or new file)

```
test_skill_definition_preferred_tools_default — SkillDefinition().preferred_tools == []
test_skill_definition_with_preferences — SkillDefinition with ToolPreference list round-trips
```

---

## Tracking Updates

### PROGRESS.md

Add to the status line:

```
AD-423a COMPLETE — Tool Foundation (Tool protocol + ToolRegistry + 3 adapters + SkillDefinition.preferred_tools)
```

### DECISIONS.md

Add decision record:

```markdown
### AD-423a: Tool Foundation

| Aspect | Decision |
|--------|----------|
| **Scope** | Tool protocol + ToolRegistry + 3 adapters + SkillDefinition.preferred_tools |
| **Absorbs** | AD-483 (Tool Layer — Instruments). Issue #77 closed. |
| **Storage** | In-memory only — tools are deterministic from code+config, no SQLite |
| **Protocol** | typing.Protocol (ISP), not ABC — no forced inheritance |
| **Adapters** | InfraServiceAdapter (intent bus), DirectServiceAdapter (method call), DeterministicFunctionAdapter (sync callable) |
| **Ontology seed** | 7 ToolCapability entries from resources.yaml registered at startup with noop handlers |
| **Skill link** | SkillDefinition.preferred_tools: list[ToolPreference] — closes Skill→Tool hierarchy |
| **No agent wiring** | Agents don't use ToolRegistry yet — deferred to AD-423c (ToolContext) |
| **No API router** | Registry query endpoints deferred to AD-423b/c |
| **Unlocks** | AD-423b (permissions), AD-423c (ToolContext), AD-543–549 (SWE Harness) |
```

### roadmap.md

Update AD-423a status from `(planned, OSS)` to `(complete, OSS)`.

### GitHub

Close issue #77 (AD-483) with comment: "Absorbed into AD-423a (Tool Foundation). Tool protocol, registry, and adapter model implemented."

---

## Verification

```bash
# Run tests
uv run python -m pytest tests/test_ad423a_tool_foundation.py -v

# Import check
uv run python -c "from probos.tools.protocol import Tool, ToolType, ToolResult, ToolRegistration, ToolPreference; from probos.tools.registry import ToolRegistry; from probos.tools.adapters import InfraServiceAdapter, DirectServiceAdapter, DeterministicFunctionAdapter; print('All imports OK')"

# Skill framework migration check
uv run python -c "from probos.skill_framework import SkillDefinition; d = SkillDefinition(skill_id='test', name='Test', category='pcc'); print('preferred_tools:', d.preferred_tools)"
```
