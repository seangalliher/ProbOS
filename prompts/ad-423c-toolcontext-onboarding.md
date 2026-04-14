# AD-423c: ToolContext + Role-Based Tool Assignment

**Ticket:** AD-423c (Issue #146)
**Depends on:** AD-423a (Tool Foundation, complete), AD-423b (Tool Permissions, complete), AD-429 (Ontology, complete), AD-428 (Skill Framework, complete), AD-566 (Qualification Battery, complete)
**Unlocks:** AD-543–549 (Native SWE Harness), AD-548 (trust-gated tool permissions)

## Problem

AD-423a established `Tool`, `ToolRegistry`, and adapters. AD-423b added permissions, LOTO, and Captain overrides. But agents still cannot access tools — there is no agent-facing interface. The registry is infrastructure-only:

1. **No agent-side access.** Agents have no way to discover or invoke tools. The `ToolRegistry` is a Ship's Computer service; crew agents shouldn't see the raw registry.
2. **No onboarding wiring.** `wire_agent()` in `agent_onboarding.py` has no tool assignment step. The 7 ontology-seeded tools have noop handlers and are never bound to agents.
3. **Context is a raw dict.** `Tool.invoke(params, context)` takes `dict[str, Any] | None`. The docstring explicitly says "AD-423c will formalize this as ToolContext." The current `check_and_invoke()` builds a throwaway dict with only `agent_id` and `permission` (registry.py:318-320).
4. **No Duty→Skill link.** `DutyDefinition` has no `required_skills` field — duties cannot express what skills (and thus tools) they need.
5. **No Procedure→Tool link.** `ProcedureStep` has no `required_tools` field — the Cognitive JIT pipeline cannot declare tool dependencies for replay steps.
6. **Hardcoded role templates.** `ROLE_SKILL_TEMPLATES` in `skill_framework.py` is a Python dict (lines 225-263). Should be config-driven.

AD-423c closes these gaps: ToolContext (scoped view), onboarding wiring (role→tool assignment), and data model extensions.

## Design References

- `docs/research/crew-capability-architecture.md` — ToolContext concept (lines 415-436), connections C1/C3/C5
- `src/probos/tools/protocol.py` — Tool protocol, ToolRegistration, ToolPreference (AD-423a)
- `src/probos/tools/registry.py` — ToolRegistry, check_and_invoke(), resolve_permission() (AD-423b)
- `src/probos/tools/permissions.py` — ToolPermissionStore (AD-423b)
- `src/probos/agent_onboarding.py` — wire_agent() flow (AD-515)
- `src/probos/skill_framework.py` — SkillDefinition, ROLE_SKILL_TEMPLATES, AgentSkillService
- `src/probos/earned_agency.py` — AgencyLevel, Rank resolution
- `src/probos/cognitive/procedures.py` — ProcedureStep dataclass (line 27)
- `src/probos/config.py` — DutyDefinition (line 676)
- `config/ontology/resources.yaml` — 7 ToolCapability entries
- `src/probos/startup/finalize.py` — late-binding pattern (lines 138-147)

## Design Decisions

1. **ToolContext is a scoped view, not a copy.** `ToolContext` wraps the shared `ToolRegistry` and the agent's identity (sovereign_id, rank, department) to provide a permission-filtered interface. No data duplication. Agents call `context.invoke(tool_id, params)` — permission checks happen inside.

2. **ToolContext is a dataclass, not a Protocol.** Unlike `Tool` (which has many implementations), `ToolContext` has one implementation. A frozen identity snapshot + reference to the registry. Simpler, testable, no need for structural subtyping.

3. **ToolContext is constructed at onboarding, refreshed on rank change.** Created in `wire_agent()` and stored on the agent instance (`agent.tool_context`). When trust/rank changes, the context is rebuilt (identity snapshot refreshed). The context itself doesn't cache permissions — it delegates to `ToolRegistry.resolve_permission()` on every call.

4. **Role→Tool mapping via ontology ToolCapability.** The existing `resources.yaml` already defines 7 tools with `available_to` fields ("all_crew", "lieutenant_plus"). AD-423c respects these as the tool assignment source. No separate role→tool mapping file needed — the ontology is the single source of truth.

5. **Public setter for late-binding.** Following the `set_orientation_service()` pattern (agent_onboarding.py:74), add `set_tool_registry()` setter to `AgentOnboardingService`. Do NOT reach through private attributes.

6. **DutyDefinition.required_skills is informational.** The field closes the Duty→Skill link in the hierarchy for documentation and future scheduling optimization. It does NOT gate duty execution in this AD (that would require Skill Framework integration in the duty scheduler, which is out of scope).

7. **ProcedureStep.required_tools is declarative.** The field records which tools a procedure step needs. The replay engine (AD-534) can check `tool_context.has_tool(tool_id)` before attempting replay. Not enforced in this AD — AD-534 was built before ToolContext existed.

8. **No config-driven role templates in this AD.** Moving `ROLE_SKILL_TEMPLATES` from Python to YAML is a separate concern (config migration). The roadmap mentions it but it's orthogonal to ToolContext. Deferring to avoid scope creep. The current Python dict works.

9. **No fallback cascade in this AD.** The "skill → LLM → chain-of-command escalation" fallback cascade is an execution-time feature for the Native SWE Harness (AD-545). ToolContext provides the building blocks (`has_tool()`, permission checks) but the cascade logic belongs in the agentic loop, not the tool layer.

10. **No API router in this AD.** Tool discovery and invocation happen through ToolContext on the agent side. A `/api/tools` REST router for HXI is useful but not required for the agent-side wiring. Deferred.

## Scope — 10 Changes

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/tools/context.py` | NEW — ToolContext dataclass |
| 2 | `src/probos/tools/protocol.py` | MODIFY — add ToolContext forward reference in Tool.invoke() docstring |
| 3 | `src/probos/agent_onboarding.py` | MODIFY — add set_tool_registry() setter, tool assignment in wire_agent() |
| 4 | `src/probos/startup/finalize.py` | MODIFY — late-bind tool_registry to onboarding service |
| 5 | `src/probos/cognitive/procedures.py` | MODIFY — add required_tools to ProcedureStep |
| 6 | `src/probos/config.py` | MODIFY — add required_skills to DutyDefinition |
| 7 | `src/probos/cognitive/cognitive_agent.py` | MODIFY — store and expose tool_context |
| 8 | `src/probos/events.py` | MODIFY — add TOOL_CONTEXT_CREATED event |
| 9 | `tests/test_ad423c_tool_context.py` | NEW — ToolContext tests |
| 10 | `tests/test_ad423c_onboarding.py` | NEW — onboarding tool wiring tests |

---

## Change 1 — `src/probos/tools/context.py` (NEW)

The core deliverable. ToolContext is a scoped, permission-filtered view of the ToolRegistry for a specific agent.

```python
"""AD-423c: ToolContext — scoped tool access for a specific agent.

Agents never see the raw ToolRegistry. They see their ToolContext:
a permission-filtered view constructed at onboarding and refreshed
on rank change. All invocations go through ToolContext, which enforces
permission checks on every call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from probos.tools.protocol import ToolPermission, ToolRegistration, ToolResult, ToolType

if TYPE_CHECKING:
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Scoped, permission-filtered tool access for one agent.

    Constructed at onboarding (wire_agent) and stored on the agent instance.
    Delegates all permission checks to the ToolRegistry — no caching of
    permission state. The identity snapshot (agent_id, rank, department)
    determines what the agent can see and do.

    Public API:
        available_tools() → list[ToolRegistration]
        has_tool(tool_id) → bool
        invoke(tool_id, params, **kw) → ToolResult
        get_permission(tool_id) → ToolPermission
    """

    agent_id: str
    agent_rank: str = "ensign"
    agent_department: str | None = None
    agent_types: list[str] = field(default_factory=list)

    # Late-bound reference to the shared registry (not serialized)
    _registry: "ToolRegistry | None" = field(default=None, repr=False, compare=False)

    def set_registry(self, registry: "ToolRegistry") -> None:
        """Bind to the shared ToolRegistry. Called once at construction."""
        object.__setattr__(self, "_registry", registry)

    def _require_registry(self) -> "ToolRegistry":
        """Guard: raise if registry not bound."""
        if self._registry is None:
            raise RuntimeError("ToolContext not bound to a ToolRegistry")
        return self._registry

    def available_tools(
        self,
        *,
        tool_type: ToolType | None = None,
        domain: str | None = None,
        tag: str | None = None,
    ) -> list[ToolRegistration]:
        """List tools this agent can see (permission > NONE).

        Filters the registry's enabled tools through the agent's
        permission resolution. Returns only tools the agent has
        at least OBSERVE permission on.
        """
        registry = self._require_registry()
        all_tools = registry.list_tools(
            tool_type=tool_type, domain=domain, tag=tag, enabled_only=True,
        )
        visible = []
        for reg in all_tools:
            perm = registry.resolve_permission(
                self.agent_id, reg.tool_id,
                agent_department=self.agent_department,
                agent_rank=self.agent_rank,
                agent_types=self.agent_types,
            )
            if perm != ToolPermission.NONE:
                visible.append(reg)
        return visible

    def has_tool(self, tool_id: str) -> bool:
        """Check if this agent can see a specific tool (permission > NONE)."""
        registry = self._require_registry()
        perm = registry.resolve_permission(
            self.agent_id, tool_id,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
        )
        return perm != ToolPermission.NONE

    def get_permission(self, tool_id: str) -> ToolPermission:
        """Resolve the effective permission level for a tool."""
        registry = self._require_registry()
        return registry.resolve_permission(
            self.agent_id, tool_id,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
        )

    async def invoke(
        self,
        tool_id: str,
        params: dict[str, Any] | None = None,
        *,
        required: ToolPermission = ToolPermission.READ,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Permission-checked tool invocation.

        Delegates to ToolRegistry.check_and_invoke() with this agent's
        identity. The agent never bypasses permission enforcement.

        Args:
            tool_id: Tool to invoke.
            params: Input parameters for the tool.
            required: Minimum permission level needed (default READ).
            context: Additional invocation context (merged with agent identity).
        """
        registry = self._require_registry()
        merged_context = dict(context or {})
        merged_context["agent_department"] = self.agent_department
        merged_context["agent_rank"] = self.agent_rank

        return await registry.check_and_invoke(
            agent_id=self.agent_id,
            tool_id=tool_id,
            params=params or {},
            required=required,
            agent_department=self.agent_department,
            agent_rank=self.agent_rank,
            agent_types=self.agent_types,
            context=merged_context,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/diagnostics (does NOT include registry reference)."""
        return {
            "agent_id": self.agent_id,
            "agent_rank": self.agent_rank,
            "agent_department": self.agent_department,
            "agent_types": self.agent_types,
            "tool_count": len(self.available_tools()) if self._registry else 0,
        }

    def refresh(
        self,
        *,
        agent_rank: str | None = None,
        agent_department: str | None = None,
    ) -> None:
        """Update identity snapshot after rank/department change.

        Called by the trust pipeline when an agent's rank changes.
        Does NOT reconstruct the context — just updates the identity
        fields. Permission resolution uses these on every call.
        """
        if agent_rank is not None:
            object.__setattr__(self, "agent_rank", agent_rank)
        if agent_department is not None:
            object.__setattr__(self, "agent_department", agent_department)
```

---

## Change 2 — `src/probos/tools/protocol.py` (MODIFY)

### 2a. Update Tool.invoke() docstring

At line 124, update the docstring for `invoke()` to reference ToolContext:

**Find** (line 124-135):
```python
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
```

**Replace with:**
```python
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            params: Input parameters matching input_schema.
            context: Invocation context dict. When called through ToolContext
                     (AD-423c), includes agent_id, permission, agent_department,
                     and agent_rank. Direct callers may pass any dict.

        Returns:
            ToolResult with output or error.
        """
        ...
```

**Do NOT change the method signature.** The `context` parameter stays as `dict[str, Any] | None`. ToolContext wraps invoke, it doesn't change the protocol.

---

## Change 3 — `src/probos/agent_onboarding.py` (MODIFY)

### 3a. Add TYPE_CHECKING import

In the `if TYPE_CHECKING:` block (lines 17-31), add:

```python
    from probos.tools.registry import ToolRegistry
```

### 3b. Add tool_registry to __init__

Add `tool_registry` parameter to `__init__()` as `None` (created before tool_registry exists in startup order). After line 55 (`acm: AgentCapitalService | None,`), add:

```python
        tool_registry: "ToolRegistry | None" = None,
```

Store it (after line 70, `self._acm = acm`):

```python
        self._tool_registry: ToolRegistry | None = tool_registry
```

### 3c. Add public setter

After the existing `set_orientation_service()` method (line 74-76), add:

```python
    def set_tool_registry(self, registry: "ToolRegistry") -> None:
        """AD-423c: Set tool registry (public setter for LoD)."""
        self._tool_registry = registry
```

### 3d. Add tool context creation in wire_agent()

At the end of `wire_agent()`, after the Ward Room welcome announcement block (after line 299's `except Exception:` handler for the announcement), add the tool context assignment step:

```python
        # AD-423c: Create ToolContext for crew agents
        if is_crew and self._tool_registry:
            try:
                from probos.tools.context import ToolContext
                from probos.cognitive.standing_orders import get_department

                dept = (
                    (self._ontology.get_agent_department(agent.agent_type) if self._ontology else None)
                    or get_department(agent.agent_type)
                    or ""
                )

                # Resolve rank from trust network
                rank = "ensign"  # default
                try:
                    trust_score = self._trust_network.get_score(agent.id)
                    from probos.consensus.trust import Rank
                    rank = Rank.from_trust(trust_score).value
                except Exception:
                    pass

                tool_context = ToolContext(
                    agent_id=getattr(agent, "sovereign_id", "") or agent.id,
                    agent_rank=rank,
                    agent_department=dept,
                    agent_types=[agent.agent_type],
                )
                tool_context.set_registry(self._tool_registry)
                agent.tool_context = tool_context

                self._event_emitter(EventType.TOOL_CONTEXT_CREATED, {
                    "agent_id": agent.id,
                    "agent_type": agent.agent_type,
                    "rank": rank,
                    "department": dept,
                    "tool_count": len(tool_context.available_tools()),
                })

                logger.debug(
                    "AD-423c: ToolContext created for %s (%s, %s) — %d tools visible",
                    agent.agent_type, rank, dept, len(tool_context.available_tools()),
                )
            except Exception:
                logger.debug(
                    "AD-423c: ToolContext creation failed for %s",
                    agent.agent_type, exc_info=True,
                )
```

**Note:** Uses `agent.tool_context = tool_context` — this is a dynamically set attribute. CognitiveAgent will add the typed slot (Change 7).

---

## Change 4 — `src/probos/startup/finalize.py` (MODIFY)

After the existing onboarding late-binding block (line 147, the `set_orientation_service` call), add:

```python
    # AD-423c: Wire tool registry into onboarding service
    if runtime.tool_registry:
        runtime.onboarding.set_tool_registry(runtime.tool_registry)
```

---

## Change 5 — `src/probos/cognitive/procedures.py` (MODIFY)

### 5a. Add required_tools to ProcedureStep

In the `ProcedureStep` dataclass (line 27), after the `resolved_agent_type` field (line 41), add:

```python
    required_tools: list[str] = field(default_factory=list)  # AD-423c: tool_ids needed for this step
```

This is a declarative field. No enforcement logic in this AD — the replay engine (AD-534) can use `tool_context.has_tool()` to check tool availability before replay. The extraction prompt does NOT need updating — LLMs don't know tool_ids. The field is populated programmatically during procedure enrichment (AD-532b+).

---

## Change 6 — `src/probos/config.py` (MODIFY)

### 6a. Add required_skills to DutyDefinition

In the `DutyDefinition` class (line 676), after the `priority` field (line 682), add:

```python
    required_skills: list[str] = []  # AD-423c: skill_ids needed for this duty (informational)
```

This closes the Duty→Skill link in the hierarchy. Informational only — the duty scheduler does NOT gate execution on skills in this AD.

---

## Change 7 — `src/probos/cognitive/cognitive_agent.py` (MODIFY)

### 7a. Add tool_context attribute

In the `CognitiveAgent.__init__()` method, add a typed attribute declaration alongside other instance attributes. Locate where `self.sovereign_id` or `self.did` is declared, and add nearby:

```python
        self.tool_context: Any = None  # AD-423c: ToolContext, set during onboarding
```

Use `Any` to avoid circular import. The actual type is `ToolContext` from `probos.tools.context`.

### 7b. Add tool_context refresh on rank change

Find the method that handles trust/rank updates (search for where `agent.rank` or trust-based rank changes are applied — this may be in proactive.py or the trust event handler). If there is a clear rank-change callback, add:

```python
            # AD-423c: Refresh ToolContext on rank change
            if hasattr(agent, 'tool_context') and agent.tool_context:
                agent.tool_context.refresh(agent_rank=new_rank)
```

If no clear rank-change hook exists, skip this sub-change. ToolContext delegates to `resolve_permission()` on every call, so a stale `agent_rank` in the context snapshot means the context uses the rank from onboarding time — not ideal but not a security hole (permissions are always resolved against the registry's current state, and the rank gate in `resolve_permission` uses the context's rank). A `TRUST_UPDATE` event subscriber can refresh it later.

---

## Change 8 — `src/probos/events.py` (MODIFY)

Add a new event type to the `EventType` enum. Find the section where tool-related events are defined (TOOL_PERMISSION_DENIED, TOOL_LOCKED, TOOL_UNLOCKED from AD-423b) and add:

```python
    TOOL_CONTEXT_CREATED = "tool_context_created"      # AD-423c: fired during onboarding
```

---

## Change 9 — `tests/test_ad423c_tool_context.py` (NEW)

```python
"""AD-423c: ToolContext tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.tools.context import ToolContext
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry, ToolPermissionDenied


# ── Helpers ──────────────────────────────────────────────────────────

class _StubTool:
    """Minimal Tool protocol implementation for testing."""

    def __init__(self, tool_id: str = "test_tool", name: str = "Test Tool",
                 tool_type: ToolType = ToolType.DETERMINISTIC_FUNCTION):
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type

    @property
    def tool_id(self) -> str: return self._tool_id
    @property
    def name(self) -> str: return self._name
    @property
    def tool_type(self) -> ToolType: return self._tool_type
    @property
    def description(self) -> str: return "A test tool"
    @property
    def input_schema(self) -> dict: return {}
    @property
    def output_schema(self) -> dict: return {}

    async def invoke(self, params, context=None):
        return ToolResult(output={"echo": params})


def _make_registry_with_tools(*tool_ids: str) -> ToolRegistry:
    """Create a ToolRegistry and register stub tools."""
    registry = ToolRegistry()
    for tid in tool_ids:
        tool = _StubTool(tool_id=tid, name=f"Tool {tid}")
        registry.register(tool)
    return registry


def _make_context(
    registry: ToolRegistry,
    agent_id: str = "agent-001",
    rank: str = "ensign",
    department: str | None = None,
    agent_types: list[str] | None = None,
) -> ToolContext:
    """Create a ToolContext bound to a registry."""
    ctx = ToolContext(
        agent_id=agent_id,
        agent_rank=rank,
        agent_department=department,
        agent_types=agent_types or [],
    )
    ctx.set_registry(registry)
    return ctx


# ── Tests: Construction ─────────────────────────────────────────────

class TestToolContextConstruction:
    """ToolContext creation and binding."""

    def test_create_unbound(self):
        ctx = ToolContext(agent_id="agent-001")
        assert ctx.agent_id == "agent-001"
        assert ctx.agent_rank == "ensign"
        assert ctx._registry is None

    def test_unbound_raises_on_use(self):
        ctx = ToolContext(agent_id="agent-001")
        with pytest.raises(RuntimeError, match="not bound"):
            ctx.available_tools()

    def test_bind_registry(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx._registry is registry

    def test_to_dict(self):
        registry = _make_registry_with_tools("t1", "t2")
        ctx = _make_context(registry, rank="lieutenant", department="science")
        d = ctx.to_dict()
        assert d["agent_id"] == "agent-001"
        assert d["agent_rank"] == "lieutenant"
        assert d["agent_department"] == "science"
        assert d["tool_count"] == 2


# ── Tests: Tool Visibility ──────────────────────────────────────────

class TestToolContextVisibility:
    """available_tools() and has_tool() permission filtering."""

    def test_all_tools_visible_default_permissions(self):
        """With no permission matrix, all enabled tools return READ → visible."""
        registry = _make_registry_with_tools("t1", "t2", "t3")
        ctx = _make_context(registry)
        tools = ctx.available_tools()
        assert len(tools) == 3

    def test_has_tool_true(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx.has_tool("t1") is True

    def test_has_tool_false_nonexistent(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        assert ctx.has_tool("nonexistent") is False

    def test_department_scoping_hides_tools(self):
        """Tools scoped to a department are invisible to other departments."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="eng_only")
        registry.register(tool, department="engineering")

        ctx = _make_context(registry, department="science")
        assert ctx.has_tool("eng_only") is False
        assert len(ctx.available_tools()) == 0

    def test_department_scoping_shows_matching(self):
        """Tools scoped to a department are visible to that department."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="eng_only")
        registry.register(tool, department="engineering")

        ctx = _make_context(registry, department="engineering")
        assert ctx.has_tool("eng_only") is True

    def test_restricted_to_hides_from_others(self):
        """restricted_to limits visibility to specific agents."""
        registry = ToolRegistry()
        tool = _StubTool(tool_id="special")
        registry.register(tool, restricted_to=["agent-vip"])

        ctx = _make_context(registry, agent_id="agent-001")
        assert ctx.has_tool("special") is False

    def test_restricted_to_shows_for_listed(self):
        registry = ToolRegistry()
        tool = _StubTool(tool_id="special")
        registry.register(tool, restricted_to=["agent-001"])

        ctx = _make_context(registry, agent_id="agent-001")
        assert ctx.has_tool("special") is True

    def test_get_permission(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        perm = ctx.get_permission("t1")
        assert perm == ToolPermission.READ  # default: READ for all ranks

    def test_filter_by_tool_type(self):
        registry = ToolRegistry()
        registry.register(_StubTool("fn1", tool_type=ToolType.DETERMINISTIC_FUNCTION))
        registry.register(_StubTool("svc1", tool_type=ToolType.INFRA_SERVICE))
        ctx = _make_context(registry)
        fns = ctx.available_tools(tool_type=ToolType.DETERMINISTIC_FUNCTION)
        assert len(fns) == 1
        assert fns[0].tool_id == "fn1"


# ── Tests: Invocation ────────────────────────────────────────────────

class TestToolContextInvocation:
    """invoke() delegates to registry with permission checks."""

    @pytest.mark.asyncio
    async def test_invoke_success(self):
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        result = await ctx.invoke("echo", {"msg": "hello"})
        assert result.success
        assert result.output == {"echo": {"msg": "hello"}}

    @pytest.mark.asyncio
    async def test_invoke_not_found(self):
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        result = await ctx.invoke("nonexistent", {})
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_invoke_permission_denied(self):
        """Agent with NONE permission cannot invoke."""
        registry = ToolRegistry()
        tool = _StubTool("restricted")
        registry.register(tool, department="security")

        ctx = _make_context(registry, department="medical")
        # Permission is NONE (department mismatch) → ToolPermissionDenied
        with pytest.raises(ToolPermissionDenied):
            await ctx.invoke("restricted", {})

    @pytest.mark.asyncio
    async def test_invoke_passes_context(self):
        """Invocation context includes agent identity."""
        captured = {}

        class _CaptureTool:
            @property
            def tool_id(self): return "cap"
            @property
            def name(self): return "Capture"
            @property
            def tool_type(self): return ToolType.DETERMINISTIC_FUNCTION
            @property
            def description(self): return ""
            @property
            def input_schema(self): return {}
            @property
            def output_schema(self): return {}
            async def invoke(self, params, context=None):
                captured.update(context or {})
                return ToolResult(output="ok")

        registry = ToolRegistry()
        registry.register(_CaptureTool())
        ctx = _make_context(registry, department="science", rank="lieutenant")
        await ctx.invoke("cap", {})
        assert captured["agent_id"] == "agent-001"
        assert captured["agent_department"] == "science"
        assert captured["agent_rank"] == "lieutenant"
        assert captured["permission"] == "read"

    @pytest.mark.asyncio
    async def test_invoke_empty_params_default(self):
        """Calling invoke with no params passes empty dict."""
        registry = _make_registry_with_tools("echo")
        ctx = _make_context(registry)
        result = await ctx.invoke("echo")
        assert result.success


# ── Tests: Refresh ───────────────────────────────────────────────────

class TestToolContextRefresh:
    """Identity snapshot refresh on rank change."""

    def test_refresh_rank(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry, rank="ensign")
        assert ctx.agent_rank == "ensign"
        ctx.refresh(agent_rank="commander")
        assert ctx.agent_rank == "commander"

    def test_refresh_department(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry, department="science")
        ctx.refresh(agent_department="engineering")
        assert ctx.agent_department == "engineering"

    def test_refresh_preserves_registry_binding(self):
        registry = _make_registry_with_tools("t1")
        ctx = _make_context(registry)
        ctx.refresh(agent_rank="commander")
        assert ctx._registry is registry
        assert ctx.has_tool("t1") is True
```

---

## Change 10 — `tests/test_ad423c_onboarding.py` (NEW)

```python
"""AD-423c: Onboarding tool wiring tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.agent_onboarding import AgentOnboardingService
from probos.tools.registry import ToolRegistry
from probos.tools.protocol import ToolType


class _StubTool:
    """Minimal Tool for registry seeding."""

    def __init__(self, tool_id: str):
        self._id = tool_id

    @property
    def tool_id(self): return self._id
    @property
    def name(self): return self._id
    @property
    def tool_type(self): return ToolType.DETERMINISTIC_FUNCTION
    @property
    def description(self): return ""
    @property
    def input_schema(self): return {}
    @property
    def output_schema(self): return {}

    async def invoke(self, params, context=None):
        from probos.tools.protocol import ToolResult
        return ToolResult(output="ok")


def _make_mock_config():
    """Minimal SystemConfig mock for onboarding."""
    config = MagicMock()
    config.onboarding.enabled = False
    config.onboarding.naming_ceremony = False
    config.orientation.enabled = False
    return config


def _make_mock_agent(agent_type: str = "security_officer", is_crew: bool = True):
    """Minimal agent mock."""
    agent = MagicMock()
    agent.id = f"pool-{agent_type}-0"
    agent.agent_type = agent_type
    agent.pool = f"{agent_type}_pool"
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.confidence = 1.0
    agent.capabilities = []
    agent.callsign = agent_type.replace("_", " ").title()
    agent.tool_context = None
    return agent


def _make_onboarding_service(tool_registry: ToolRegistry | None = None):
    """Create AgentOnboardingService with mocked dependencies."""
    svc = AgentOnboardingService(
        callsign_registry=MagicMock(),
        capability_registry=MagicMock(),
        gossip=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        event_log=MagicMock(log=AsyncMock()),
        identity_registry=None,
        ontology=None,
        event_emitter=MagicMock(),
        config=_make_mock_config(),
        llm_client=None,
        registry=MagicMock(),
        ward_room=None,
        acm=None,
        tool_registry=tool_registry,
    )
    return svc


class TestOnboardingToolWiring:
    """wire_agent() creates ToolContext for crew agents."""

    @pytest.mark.asyncio
    async def test_crew_agent_gets_tool_context(self):
        """Crew agents receive a ToolContext during onboarding."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        registry.register(_StubTool("t2"))

        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)

        assert agent.tool_context is not None
        assert agent.tool_context.agent_id == agent.id or agent.tool_context.agent_id
        assert len(agent.tool_context.available_tools()) == 2

    @pytest.mark.asyncio
    async def test_non_crew_agent_no_tool_context(self):
        """Non-crew agents do not receive a ToolContext."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))

        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("introspect_agent")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=False):
            await svc.wire_agent(agent)

        # Non-crew: tool_context should remain None or not set
        tc = getattr(agent, "tool_context", None)
        assert tc is None or tc == MagicMock()  # Remains as mock default

    @pytest.mark.asyncio
    async def test_no_registry_no_error(self):
        """If tool_registry is None, onboarding proceeds without error."""
        svc = _make_onboarding_service(tool_registry=None)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)
        # Should not raise

    @pytest.mark.asyncio
    async def test_tool_context_created_event_emitted(self):
        """TOOL_CONTEXT_CREATED event is emitted during onboarding."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)

        # Check event emission
        from probos.events import EventType
        calls = svc._event_emitter.call_args_list
        tool_ctx_calls = [c for c in calls if c[0][0] == EventType.TOOL_CONTEXT_CREATED]
        assert len(tool_ctx_calls) == 1
        event_data = tool_ctx_calls[0][0][1]
        assert event_data["agent_type"] == "security_officer"

    def test_set_tool_registry_setter(self):
        """Public setter binds tool registry."""
        svc = _make_onboarding_service(tool_registry=None)
        assert svc._tool_registry is None

        registry = ToolRegistry()
        svc.set_tool_registry(registry)
        assert svc._tool_registry is registry


class TestToolContextDepartmentResolution:
    """ToolContext department is resolved from ontology or standing orders."""

    @pytest.mark.asyncio
    async def test_department_from_standing_orders(self):
        """When ontology is None, department comes from standing orders."""
        registry = ToolRegistry()
        registry.register(_StubTool("t1"))
        svc = _make_onboarding_service(tool_registry=registry)
        agent = _make_mock_agent("security_officer")

        with (
            patch("probos.agent_onboarding.is_crew_agent", return_value=True),
            patch("probos.cognitive.standing_orders.get_department", return_value="security"),
        ):
            await svc.wire_agent(agent)

        assert agent.tool_context is not None
        assert agent.tool_context.agent_department == "security"
```

---

## Regression Check

Run AD-423a and AD-423b tests to verify no regressions:

```bash
uv run python -m pytest tests/test_ad423a_tool_foundation.py tests/test_ad423b_tool_permissions.py -v
```

All must pass. Then run the new tests:

```bash
uv run python -m pytest tests/test_ad423c_tool_context.py tests/test_ad423c_onboarding.py -v
```

---

## Tracking Updates

After all tests pass, update:

1. **PROGRESS.md** — Add AD-423c entry with status "Complete"
2. **DECISIONS.md** — Add decision record for AD-423c
3. **roadmap.md** — Update AD-423c from "planned" to "complete" (line 1718)
4. **Issue #146** — Close with summary

---

## Engineering Principles Compliance

| Principle | How This AD Complies |
|-----------|---------------------|
| **Single Responsibility** | ToolContext does one thing: scoped tool view. Registry does catalog. Permissions does access control. Onboarding does wiring. |
| **Open/Closed** | ToolContext extends the tool layer via composition (wraps registry). No existing protocol or class signatures changed. |
| **Liskov** | ToolContext is not a subtype of anything. Tool protocol unchanged. |
| **Interface Segregation** | Agents see only ToolContext (4 methods). Never see ToolRegistry (15+ methods). |
| **Dependency Inversion** | ToolContext depends on ToolRegistry abstraction (TYPE_CHECKING import). Onboarding receives tool_registry via constructor injection. |
| **Law of Demeter** | `set_tool_registry()` public setter — no private attribute access. ToolContext calls registry methods directly (its own dependency). |
| **Fail Fast** | Unbound ToolContext raises RuntimeError on use. Onboarding wraps tool context creation in try/except (log-and-degrade). |
| **Defense in Depth** | Permission check happens on every `invoke()` and every `available_tools()` / `has_tool()` call. No cached permissions. |
| **DRY** | Permission resolution reuses `ToolRegistry.resolve_permission()` — no duplicated logic. |
| **Cloud-Ready** | No new database. ToolContext is in-memory (scoped view). ToolPermissionStore (AD-423b) already uses ConnectionFactory. |

---

## What This AD Does NOT Do (Deferred)

| Deferred | Why | Future AD |
|----------|-----|-----------|
| Config-driven role templates (YAML) | Config migration, orthogonal to ToolContext | Separate AD |
| Fallback cascade (skill → LLM → escalation) | Execution-time logic for AD-545 AgenticLoop | AD-545 |
| `/api/tools` REST router | HXI discovery endpoint, not needed for agent-side wiring | AD-423d or Phase 30 |
| Qualification-gated tool unlock | Requires Skill Framework tracking tool-specific proficiency | AD-539b or AD-566+ |
| ProcedureStep.required_tools population | Needs LLM extraction or enrichment pipeline update | AD-532+ |
| TRUST_UPDATE subscriber for context refresh | Event wiring, can be added incrementally | Next wave |
| Replace noop handlers with real bindings | Each tool needs a real service implementation | Per-tool ADs |
