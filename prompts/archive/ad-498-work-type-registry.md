# AD-498: Work Type Registry & Templates

## Context

AD-496 built the Workforce Scheduling Engine — seven-entity data model (WorkItem, BookableResource, ResourceRequirement, Booking, BookingTimestamp, BookingJournal, AgentCalendar), SQLite persistence, CRUD, push/pull assignment, booking lifecycle, journal generation, resource registry, REST API, and state snapshot integration.

AD-497 built the HXI surface — Scrumban Board (WorkBoard.tsx) with drag-and-drop, swim lanes, filters, quick create; ProfileWorkTab.tsx with active/blocked/completed sections, create task, reassign/cancel/retry; WebSocket event handling and snapshot hydration.

AD-471 built Night Orders / Autonomous Operations with standalone `NightOrdersManager` and `NIGHT_ORDER_TEMPLATES` in `watch_rotation.py`. Night Orders currently operate independently from WorkItems — integration was deferred.

**What AD-496 explicitly deferred to AD-498:**
1. Per-type state machine validation in `transition_work_item()`
2. Template instantiation endpoint (`POST /api/work-items/from-template/{template_id}`)
3. BuildQueue migration evaluation
4. Work type validation on the `work_type` field (currently an unvalidated string)

## Objective

Build the Work Type Registry and Template system. This adds formal work type definitions with per-type state machines and a template catalog for stamping out pre-configured work items.

## Architecture Decisions

### Work Type Registry
- Each work type defines: valid states, state machine (transition matrix), required fields, optional fields metadata, supports_children flag, auto_assign eligibility, verification_required flag
- Five built-in types: `card`, `task`, `work_order`, `duty`, `incident`
- Registry is config-driven (YAML) + code defaults as fallback
- Custom work types can be defined in config (extensible)
- `transition_work_item()` validates transitions against the type's state machine

### Template System
- Templates define reusable work item patterns with variable substitution
- Templates are defined in YAML config (`config/work_templates.yaml`)
- Each template specifies: template_id, name, work_type, title_pattern, default_steps, required_capabilities, estimated_tokens, min_trust, default_priority, tags, metadata
- Instantiation endpoint with `{variable}` substitution in title_pattern and description
- Night Orders templates from `NIGHT_ORDER_TEMPLATES` become entries in the template catalog

## Files to Modify

### 1. `src/probos/workforce.py` — Work Type Registry + Template Store

**(a) Add `WorkTypeDefinition` dataclass** (after the existing enums, ~line 78):

```python
@dataclass
class WorkTypeTransition:
    """A valid state transition for a work type."""
    from_status: str
    to_status: str
    requires_assignment: bool = False  # Must be assigned to transition
    auto_creates_booking: bool = False  # Automatically start a booking

@dataclass
class WorkTypeDefinition:
    """Formal definition of a work type with state machine."""
    type_id: str  # card, task, work_order, duty, incident
    display_name: str
    description: str
    initial_status: str  # Default status on creation
    terminal_statuses: frozenset[str]  # States that end the lifecycle
    valid_transitions: list[WorkTypeTransition]
    required_fields: list[str] = field(default_factory=list)  # Fields that must be non-None
    supports_children: bool = False  # Can have parent_id children (WBS)
    auto_assign_eligible: bool = True  # Can be pull-claimed
    verification_required: bool = False  # Must pass verification before Done
    default_priority: int = 3
    metadata_schema: dict = field(default_factory=dict)  # Expected metadata keys
```

**(b) Add `BUILTIN_WORK_TYPES` dict** with five built-in definitions:

| Type | States | Key Transitions | Notes |
|------|--------|-----------------|-------|
| `card` | draft → open → done \| cancelled | Lightest. No assignment required. No verification. |
| `task` | open → in_progress → done \| failed \| cancelled | Single-agent. `open→in_progress` requires assignment. Supports subtasks. |
| `work_order` | draft → open → scheduled → in_progress → review → done \| failed \| cancelled | Multi-step. `in_progress→review` always. Verification required. Supports children. |
| `duty` | scheduled → in_progress → done \| failed | Recurring. Generated from templates. `scheduled→in_progress` auto-creates booking. |
| `incident` | open → in_progress → review → done \| failed | High urgency. All transitions require assignment. |

Include `blocked` as a valid target from `in_progress` or `scheduled` for all types except `card`. Allow `blocked→in_progress` and `blocked→cancelled` transitions.

**(c) Add `WorkTypeRegistry` class:**

```python
class WorkTypeRegistry:
    """Registry of work type definitions with state machine validation."""

    def __init__(self) -> None:
        self._types: dict[str, WorkTypeDefinition] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register the five built-in work types."""
        for wt in BUILTIN_WORK_TYPES.values():
            self._types[wt.type_id] = wt

    def register(self, work_type: WorkTypeDefinition) -> None:
        """Register a custom work type (from config)."""
        self._types[work_type.type_id] = work_type

    def get(self, type_id: str) -> WorkTypeDefinition | None:
        return self._types.get(type_id)

    def list_types(self) -> list[WorkTypeDefinition]:
        return list(self._types.values())

    def validate_transition(self, type_id: str, from_status: str, to_status: str) -> tuple[bool, str]:
        """Check if a state transition is valid for this work type.
        Returns (valid, reason).
        """
        wt = self._types.get(type_id)
        if not wt:
            return True, ""  # Unknown type = permissive (backward compat)
        if from_status in wt.terminal_statuses:
            return False, f"Cannot transition from terminal status '{from_status}'"
        valid = any(
            t.from_status == from_status and t.to_status == to_status
            for t in wt.valid_transitions
        )
        if not valid:
            return False, f"Work type '{type_id}' does not allow transition '{from_status}' → '{to_status}'"
        return True, ""

    def get_initial_status(self, type_id: str) -> str:
        """Return the initial status for a work type, or 'open' as default."""
        wt = self._types.get(type_id)
        return wt.initial_status if wt else "open"

    def validate_required_fields(self, type_id: str, work_item: "WorkItem") -> tuple[bool, str]:
        """Check that required fields are populated."""
        wt = self._types.get(type_id)
        if not wt:
            return True, ""
        for field_name in wt.required_fields:
            if getattr(work_item, field_name, None) is None:
                return False, f"Work type '{type_id}' requires field '{field_name}'"
        return True, ""
```

**(d) Add `WorkItemTemplate` dataclass:**

```python
@dataclass
class WorkItemTemplate:
    """Reusable template for creating pre-configured work items."""
    template_id: str
    name: str
    description: str
    work_type: str  # Must be a registered work type
    title_pattern: str  # Supports {variable} substitution
    description_pattern: str = ""
    default_steps: list[dict] = field(default_factory=list)  # [{label, status}]
    required_capabilities: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    min_trust: float = 0.0
    default_priority: int = 3
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    ttl_seconds: int | None = None  # Auto-expire (for Night Orders etc.)
    category: str = "general"  # For UI grouping: general, security, engineering, medical, operations, night_orders
```

**(e) Add `TemplateStore` class:**

```python
class TemplateStore:
    """Registry of work item templates."""

    def __init__(self) -> None:
        self._templates: dict[str, WorkItemTemplate] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in templates from BUILTIN_TEMPLATES."""
        for t in BUILTIN_TEMPLATES.values():
            self._templates[t.template_id] = t

    def register(self, template: WorkItemTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> WorkItemTemplate | None:
        return self._templates.get(template_id)

    def list_templates(self, category: str | None = None) -> list[WorkItemTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return sorted(templates, key=lambda t: (t.category, t.name))

    def instantiate(
        self,
        template_id: str,
        variables: dict[str, str] | None = None,
        overrides: dict | None = None,
    ) -> dict:
        """Create a WorkItem kwargs dict from a template with variable substitution.
        Returns a dict suitable for passing to WorkItemStore.create_work_item().
        """
        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template '{template_id}' not found")

        variables = variables or {}
        title = template.title_pattern.format_map(defaultdict(str, variables))
        description = template.description_pattern.format_map(defaultdict(str, variables)) if template.description_pattern else ""

        kwargs: dict = {
            "title": title,
            "description": description,
            "work_type": template.work_type,
            "priority": template.default_priority,
            "estimated_tokens": template.estimated_tokens,
            "trust_requirement": template.min_trust,
            "required_capabilities": list(template.required_capabilities),
            "tags": list(template.tags),
            "steps": [dict(s) for s in template.default_steps],
            "metadata": {**template.metadata, "template_id": template.template_id},
            "template_id": template.template_id,
        }
        if template.ttl_seconds:
            kwargs["ttl_seconds"] = template.ttl_seconds

        if overrides:
            # Allow overriding priority, assigned_to, due_at, tags, metadata
            for key in ("priority", "assigned_to", "due_at", "tags", "description"):
                if key in overrides:
                    kwargs[key] = overrides[key]
            if "metadata" in overrides:
                kwargs["metadata"].update(overrides["metadata"])

        return kwargs
```

**(f) Define `BUILTIN_TEMPLATES` dict** with the template catalog from the roadmap:

| template_id | name | work_type | title_pattern | category |
|---|---|---|---|---|
| `security_scan` | Security Scan | work_order | `Security Scan — {target}` | security |
| `engineering_diagnostic` | Engineering Diagnostic | work_order | `Engineering Diagnostic — {system}` | engineering |
| `code_review` | Code Review | task | `Code Review — {subject}` | engineering |
| `scout_report` | Scout Report | duty | `Scout Report — {date}` | operations |
| `crew_health_check` | Crew Health Check | duty | `Crew Health Check — {date}` | medical |
| `night_maintenance` | Maintenance Watch | task | `Night Orders — Maintenance Watch` | night_orders |
| `night_build` | Build Watch | task | `Night Orders — Build Watch` | night_orders |
| `night_quiet` | Quiet Watch | task | `Night Orders — Quiet Watch` | night_orders |

Night Orders templates should carry the operational metadata (can_approve_builds, alert_boundary, escalation_triggers) in their `metadata` dict, bridging the `NIGHT_ORDER_TEMPLATES` structure into the template system. Keep `ttl_seconds` on night order templates (default 8 hours = 28800).

**(g) Integrate registry into `WorkItemStore`:**

- Add `work_type_registry: WorkTypeRegistry` and `template_store: TemplateStore` as attributes, initialized in `__init__`
- In `create_work_item()`: validate `work_type` against registry. Set `status` to the type's `initial_status` if not explicitly provided. Validate required fields.
- In `transition_work_item()`: replace the simple terminal-status check with `self.work_type_registry.validate_transition(item.work_type, item.status, new_status)`. Return error tuple if invalid.
- Add `create_from_template(template_id, variables, overrides, created_by)` method that calls `template_store.instantiate()` then `create_work_item()`.
- In `start()`: load custom work types and templates from config if provided.

**(h) Add config loading** for custom work types and templates:

Add to `WorkItemStore.__init__()` a parameter `config: dict | None = None` that can contain:
- `custom_work_types`: list of work type definitions from YAML
- `custom_templates`: list of template definitions from YAML

Parse these and register them in the respective registries after builtins. This keeps builtins as code, customizations as config.

### 2. `config/work_templates.yaml` — Template Catalog Config (NEW FILE)

Create a new YAML file for the template catalog. Include all built-in templates as reference examples (commented out since they're registered in code) plus a clear extension point:

```yaml
# Work Item Templates — ProbOS AD-498
# Built-in templates are registered in code. Add custom templates here.
# See docs for template schema.

# Custom templates (uncomment and modify):
# templates:
#   - template_id: custom_review
#     name: "Custom Review"
#     work_type: task
#     title_pattern: "Review — {subject}"
#     description_pattern: "Perform review of {subject}"
#     default_priority: 3
#     estimated_tokens: 20000
#     tags: [review]
#     category: general
```

### 3. `src/probos/config.py` — Extend WorkforceConfig

Add template and work type config fields to `WorkforceConfig`:

```python
class WorkforceConfig(BaseModel):
    enabled: bool = False
    tick_interval_seconds: float = 10.0
    default_capacity: int = 1
    custom_work_types: list[dict] = Field(default_factory=list)
    custom_templates: list[dict] = Field(default_factory=list)
    template_config_path: str = "config/work_templates.yaml"
```

### 4. `src/probos/runtime.py` — Pass config to WorkItemStore

Update the `WorkItemStore` instantiation (~line 1501-1511) to pass the workforce config so it can load custom types and templates:

```python
if self.config.workforce.enabled:
    self.work_item_store = WorkItemStore(
        db_path=str(self._data_dir / "workforce.db"),
        event_callback=self._broadcast_event,
        config={
            "custom_work_types": self.config.workforce.custom_work_types,
            "custom_templates": self.config.workforce.custom_templates,
            "template_config_path": self.config.workforce.template_config_path,
        },
    )
```

### 5. `src/probos/api.py` — Template endpoints

Add these REST endpoints alongside the existing workforce endpoints:

```
GET  /api/work-types                          → List registered work types
GET  /api/work-types/{type_id}                → Get work type definition (includes state machine)
GET  /api/work-types/{type_id}/transitions    → Get valid transitions for a work type from a given status (?from_status=open)
GET  /api/templates                           → List templates (?category=security)
GET  /api/templates/{template_id}             → Get template details
POST /api/work-items/from-template/{template_id} → Create work item from template
     Body: { "variables": {"target": "auth module"}, "overrides": {"priority": 1, "assigned_to": "agent-uuid"} }
```

The `from-template` endpoint should:
1. Call `template_store.instantiate()` to build kwargs
2. Call `create_work_item()` with the result
3. Return the created work item
4. Broadcast `work_item_created` WebSocket event (already happens via create_work_item)

### 6. `ui/src/store/types.ts` — Add TypeScript types

```typescript
interface WorkTypeDefinitionView {
    type_id: string;
    display_name: string;
    description: string;
    initial_status: string;
    terminal_statuses: string[];
    valid_transitions: Array<{
        from_status: string;
        to_status: string;
        requires_assignment: boolean;
    }>;
    supports_children: boolean;
    verification_required: boolean;
    default_priority: number;
}

interface WorkItemTemplateView {
    template_id: string;
    name: string;
    description: string;
    work_type: string;
    title_pattern: string;
    category: string;
    estimated_tokens: number;
    default_priority: number;
    tags: string[];
    default_steps: Array<{ label: string; status: string }>;
}
```

### 7. `ui/src/store/useStore.ts` — Fetch and cache work types/templates

Add state fields:
```typescript
workTypes: WorkTypeDefinitionView[] | null;
workTemplates: WorkItemTemplateView[] | null;
```

Add actions:
```typescript
fetchWorkTypes: () => Promise<void>;    // GET /api/work-types
fetchWorkTemplates: () => Promise<void>; // GET /api/templates
createFromTemplate: (templateId: string, variables?: Record<string, string>, overrides?: Record<string, any>) => Promise<void>;
```

Fetch work types and templates on initial snapshot hydration (alongside workforce data).

### 8. `ui/src/components/work/WorkBoard.tsx` — Template picker in Quick Create

Enhance the Quick Create toolbar:
- Add a "From Template" button/dropdown alongside the existing title + priority quick create
- Clicking "From Template" shows a dropdown of available templates grouped by category
- Selecting a template shows variable input fields (parsed from `title_pattern` `{variable}` placeholders)
- Submit calls `createFromTemplate(templateId, variables)`
- The work type is auto-set from the template (no manual work_type selection needed)

Also:
- Add work type selector dropdown to the existing Quick Create (currently hardcodes `card`)
- When work type is selected, the card's initial status should reflect that type's `initial_status`

### 9. `ui/src/components/profile/ProfileWorkTab.tsx` — Template picker in Create Task

Enhance the Create Task section:
- Add a "From Template" option alongside the existing title + priority create
- Filter templates by category relevant to the agent's department
- Auto-assign to the viewed agent

### 10. `tests/test_workforce.py` — Extend tests

Add test classes:

**`TestWorkTypeRegistry`** (~15 tests):
- Test built-in types are registered (5 types)
- Test each type's state machine transitions (valid and invalid)
- Test terminal status rejection
- Test custom type registration
- Test `validate_transition()` returns correct (bool, reason) tuples
- Test `get_initial_status()` for each type
- Test `validate_required_fields()`
- Test unknown type is permissive (backward compat)

**`TestTemplateStore`** (~12 tests):
- Test built-in templates are registered
- Test `instantiate()` with variable substitution
- Test `instantiate()` with missing variables (defaultdict gives empty string)
- Test `instantiate()` with overrides
- Test `list_templates()` with category filter
- Test night orders templates carry metadata (can_approve_builds, etc.)
- Test TTL propagation from template to work item
- Test template not found error
- Test custom template registration

**`TestWorkTypeValidationIntegration`** (~10 tests):
- Test `create_work_item()` rejects unknown work_type when registry is strict
- Test `create_work_item()` sets correct initial_status per type
- Test `transition_work_item()` enforces state machine (valid transition succeeds)
- Test `transition_work_item()` rejects invalid transition (returns error)
- Test `create_from_template()` end-to-end
- Test card allows any→done transition
- Test work_order requires review before done
- Test duty starts at scheduled

**`TestWorkTypeAPI`** (~8 tests):
- Test `GET /api/work-types` returns list
- Test `GET /api/work-types/task` returns definition
- Test `GET /api/templates` returns list
- Test `GET /api/templates?category=security` filters
- Test `POST /api/work-items/from-template/security_scan` creates work item
- Test template variable substitution via API
- Test invalid template_id returns 404
- Test `GET /api/work-types/task/transitions?from_status=open` returns valid targets

Add vitest tests for UI:

**`WorkBoard.test.ts`** additions (~5 tests):
- Test template dropdown renders templates grouped by category
- Test template selection shows variable input fields
- Test create from template calls correct API
- Test work type selector in quick create

**`ProfileWorkTab.test.ts`** additions (~3 tests):
- Test "From Template" option appears
- Test template filtered by agent department
- Test create from template pre-assigns agent

## Validation Checklist

Before marking complete:
- [ ] All existing workforce tests still pass (no regressions in AD-496/497 behavior)
- [ ] `transition_work_item()` now validates against type state machine
- [ ] Unknown work types are permissive (backward compatibility)
- [ ] All 5 built-in types have correct state machines
- [ ] All built-in templates instantiate correctly
- [ ] Night Orders templates carry operational metadata
- [ ] REST endpoints return correct data
- [ ] HXI template picker works in both WorkBoard and ProfileWorkTab
- [ ] WebSocket events still fire on template-created work items
- [ ] State snapshot includes work types and templates for HXI hydration
- [ ] `work_templates.yaml` created with extension examples
- [ ] WorkforceConfig updated with new fields
- [ ] No regressions in vitest

## Recommendations (Builder: Implement These)

These items were identified during research as gaps that SHOULD be part of AD-498 but were not explicitly in the original roadmap entry:

1. **Transition side-effects:** When transitioning `open→in_progress` for types with `auto_creates_booking: True`, automatically call `start_booking()`. Currently the caller must manually create a booking after transitioning. This closes a common workflow gap.

2. **Valid next transitions API:** `GET /api/work-types/{type_id}/transitions?from_status=open` should return the list of valid target statuses. The HXI can use this to only show valid drop targets during drag-and-drop (grey out invalid columns).

3. **Blocked state:** `blocked` should be a valid intermediate state for all types except `card`. Transitions: any non-terminal → blocked, blocked → in_progress (resume), blocked → cancelled (abandon). This was mentioned in the roadmap but not fully specified.

4. **Template variables discovery:** The `GET /api/templates/{id}` response should include a `variables: string[]` field listing the `{variable}` placeholders parsed from `title_pattern` and `description_pattern`. The HXI needs this to dynamically render input fields.

5. **WorkBoard drag validation:** When dragging a card to a new column, validate the transition against the type's state machine BEFORE allowing the drop. Show a red indicator on invalid targets. Currently any drop is allowed and only fails on the API call.

6. **Default status on create:** `create_work_item()` should set `status` to the work type's `initial_status` instead of always defaulting to `open`. A `work_order` should start as `draft`, a `duty` should start as `scheduled`. This is a subtle but important correctness fix.

7. **Template config hot-reload:** The `TemplateStore` should support reloading templates from YAML without restart. Add a `reload_templates()` method. Not critical but useful for Captain customization.

## What This Does NOT Cover (Explicitly Deferred)

- **DutyScheduleTracker migration to WorkItems** → AD-500
- **BuildQueue migration** → evaluate after AD-498 is stable (noted in deferred table)
- **Night Orders → WorkItem integration** → future (AD-471 implemented standalone)
- **SLA tracking on incidents** → future commercial AD
- **Scheduling optimization / offer pattern** → AD-C-010
- **Full calendar-based capacity planning** → AD-C-012
