# AD-516: Extract api.py into FastAPI Routers

## Context

`src/probos/api.py` is a 3,109-line monolith containing 122 route handlers, 17+ Pydantic models, background task helpers, and WebSocket management — all defined as closures inside `create_app(runtime)`. This violates SRP and makes the file difficult to navigate, test, and extend.

AD-514 added protocols and public APIs. AD-515 extracted runtime.py modules. AD-516 continues Wave 3 by decomposing api.py into FastAPI `APIRouter` modules.

## Objective

Extract route handlers from `api.py` into a `src/probos/routers/` package. After extraction, `api.py` should be ~100 lines: `create_app()`, CORS setup, lifespan, WebSocket infrastructure, static file serving, and `app.include_router()` calls.

## Infrastructure (do this FIRST)

### 1. Create `src/probos/routers/__init__.py`

Empty package init.

### 2. Create `src/probos/routers/deps.py`

Shared FastAPI dependencies:

```python
from fastapi import Request

def get_runtime(request: Request):
    """Inject ProbOSRuntime from app state."""
    return request.app.state.runtime

def get_ws_broadcast(request: Request):
    """Inject WebSocket broadcast function from app state."""
    return request.app.state.broadcast_event

def get_task_tracker(request: Request):
    """Inject background task tracker from app state."""
    return request.app.state.track_task
```

### 3. Create `src/probos/api_models.py`

Move ALL Pydantic request/response models from api.py (lines 94–270 + line 2406's inline `UpdateAgentHintRequest`) to this file. Keep all existing field definitions, defaults, and validators. No behavior changes.

### 4. Update `api.py` — `create_app()`

Store shared state on `app.state` so routers can access via dependencies:
```python
app.state.runtime = runtime
app.state.broadcast_event = _broadcast_event
app.state.track_task = _track_task
```

## Router Extraction Pattern

Each router follows this template:

```python
"""ProbOS API — {Domain} routes."""
import logging
from fastapi import APIRouter, Depends
from probos.routers.deps import get_runtime
from probos.api_models import SomeModel  # if needed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["{domain}"])

@router.get("/{path}")
async def handler_name(runtime=Depends(get_runtime)):
    ...
```

In `api.py`, register with:
```python
from probos.routers import workforce, ontology, records  # etc.
app.include_router(workforce.router)
```

## Router Extractions

**IMPORTANT:** Extract routers in the order listed below. Run tests after EACH router extraction. Do NOT batch multiple routers before testing.

### Router 1: `routers/workforce.py` — 18 routes

Prefix: `/api` (routes use `/work-items`, `/work-types`, `/templates`, `/bookings`, `/resources`)

Move routes:
- `list_work_types`, `get_work_type`, `get_work_type_transitions`
- `list_templates`, `get_template`, `create_from_template`
- `create_work_item`, `list_work_items`, `get_work_item`, `update_work_item`, `transition_work_item`, `assign_work_item`, `claim_work_item`, `delete_work_item`
- `list_bookings`, `get_booking_journal`
- `list_resources`, `get_resource_availability`

### Router 2: `routers/ontology.py` — 8 routes

Prefix: `/api/ontology`

Move routes: `get_vessel`, `get_organization`, `get_crew_member`, `get_ontology_skills`, `get_ontology_operations`, `get_ontology_communication`, `get_ontology_resources`, `get_ontology_records`

### Router 3: `routers/records.py` — 9 routes

Prefix: `/api/records`

Move routes: `get_records_stats`, `list_records`, `read_record`, `post_captains_log`, `get_captains_log`, `list_notebook`, `write_notebook_entry`, `search_records`, `get_record_history`

### Router 4: `routers/skills.py` — 6 routes

Prefix: `/api/skills`

Move routes: `skills_registry`, `skill_profile`, `skill_commission`, `skill_assess`, `skill_exercise`, `skill_prerequisites`

### Router 5: `routers/acm.py` — 5 routes

Prefix: `/api/acm`

Move routes: `get_acm_profile`, `get_acm_lifecycle`, `decommission_agent`, `suspend_agent`, `reinstate_agent`

### Router 6: `routers/assignments.py` — 7 routes

Prefix: `/api/assignments`

Move routes: `list_assignments`, `create_assignment`, `get_assignment`, `modify_assignment_members`, `complete_assignment`, `dissolve_assignment`, `agent_assignments`

### Router 7: `routers/scheduled_tasks.py` — 7 routes

Prefix: `/api/scheduled-tasks`

Move routes: `list_scheduled_tasks`, `create_scheduled_task`, `get_scheduled_task`, `cancel_scheduled_task`, `update_task_agent_hint`, `trigger_webhook`, `resume_dag_checkpoint`

Move the inline `UpdateAgentHintRequest` model to `api_models.py`.

### Router 8: `routers/identity.py` — 4 routes

Prefix: `/api/identity`

Move routes: `get_identity_ledger`, `list_birth_certificates`, `get_ship_identity`, `list_asset_tags`

### Router 9: `routers/journal.py` — 5 routes

Prefix: `/api/journal` (note: `agent_journal` uses `/api/agent/{agent_id}/journal` — keep that path, use `/api` prefix)

Move routes: `journal_stats`, `agent_journal`, `journal_token_usage`, `journal_token_usage_by`, `journal_decision_points`

### Router 10: `routers/wardroom.py` — 21 routes

Prefix: `/api/wardroom`

Move ALL ward room routes. Note: there's a prefix inconsistency — some routes use `/api/wardroom/` and others use `/api/ward-room/`. **Unify to `/api/wardroom/` during extraction.** Add redirect aliases for the old `/api/ward-room/` paths if any HXI code uses them.

Move routes: `list_dm_channels`, `list_dm_threads`, `list_captain_dms`, `search_dm_archive`, `wardroom_channels`, `wardroom_create_channel`, `wardroom_threads`, `wardroom_create_thread`, `wardroom_thread_detail`, `wardroom_update_thread`, `wardroom_create_post`, `wardroom_endorse`, `wardroom_endorse_thread`, `wardroom_subscribe`, `wardroom_credibility`, `wardroom_notifications`, `wardroom_activity_feed`, `wardroom_mark_seen`, `list_improvement_proposals`, `ward_room_stats`, `ward_room_prune`

### Router 11: `routers/system.py` — 13 routes (System + Notifications)

Prefix: `/api/system` for system routes, `/api/notifications` for notification routes.

Move routes: `health`, `status`, `list_tasks`, `system_services`, `system_circuit_breakers`, `system_shutdown`, `get_conn_status`, `get_night_orders_status`, `get_watch_status`, `get_communications_settings`, `update_communications_settings`, `ack_notification`, `ack_all_notifications`

### Router 12: `routers/agents.py` — 5 routes

Prefix: `/api/agent`

Move routes: `agent_profile`, `set_agent_proactive_cooldown`, `agent_chat`, `agent_chat_history`, `get_agent_identity`

Note: `agent_profile` is ~105 lines — keep it as-is during extraction, refactoring is a separate concern.

### Router 13: `routers/build.py` — 8 routes + background helpers

Prefix: `/api/build`

Move routes: `submit_build`, `approve_build`, `resolve_build`, `approve_queued_build`, `reject_queued_build`, `enqueue_build`, `get_build_queue`

Move background helpers: `_run_build()`, `_execute_build()`, `_emit_queue_snapshot()`

Move shared state: `_pending_failures` dict, `_clean_expired_failures()`, `_FAILURE_CACHE_TTL`

Dependencies: needs `get_task_tracker` and `get_ws_broadcast` from deps.py.

### Router 14: `routers/design.py` — 2 routes + background helper

Prefix: `/api/design`

Move routes: `submit_design`, `approve_design`

Move background helper: `_run_design()`

Move shared state: `_pending_designs` → store on `app.state.pending_designs` or pass via dependency.

### Router 15: `routers/chat.py` — 3 routes + background helper

Prefix: `/api`

Move routes: `chat`, `approve_selfmod`, `enrich_selfmod`

Move background helper: `_run_selfmod()`

Move module-level helpers: `_BLOCKED_COMMANDS`, `_strip_rich_formatting()`, `_handle_slash_command()`

This is the most complex extraction due to the `chat()` handler size (~218 lines) and `_run_selfmod()` (~207 lines). Move as-is — do not refactor during extraction.

### WebSocket — keep in `api.py`

The `/ws/events` endpoint, `_ws_clients`, `_broadcast_event`, and `_safe_serialize` stay in `api.py` since they manage shared WebSocket state that multiple routers reference via `app.state.broadcast_event`.

## General Rules

1. **Zero behavior changes.** Every route keeps its exact path, method, request/response format, and error handling.
2. **Test after each router.** Run `python -m pytest tests/ -x -q` after extracting each router. Fix breakages before proceeding.
3. **Preserve module-level helpers where they're used.** If a helper is used by only one router, move it there. If shared by multiple, keep in `api.py` or create a shared utility.
4. **Type annotations on all route parameters.** Follow Engineering Principles in `.github/copilot-instructions.md`.
5. **Structured logging.** Each router gets `logger = logging.getLogger(__name__)`.
6. **No circular imports.** Routers import from `deps.py` and `api_models.py`, never from each other.

## Acceptance Criteria

- [ ] `src/probos/routers/` package created with 15 router files + `deps.py` + `__init__.py`
- [ ] `src/probos/api_models.py` created with all Pydantic models
- [ ] `api.py` reduced to ~100 lines (create_app, CORS, lifespan, WebSocket, static files, router registration)
- [ ] All 122 routes accessible at the same paths as before
- [ ] All existing tests pass — zero regressions
- [ ] No circular imports
- [ ] Each router has `logging.getLogger(__name__)`
- [ ] Type annotations on all route handler parameters
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Testing

Run the full test suite after each router extraction. The extraction should be invisible to API consumers — same paths, same behavior, different file locations.

After all routers extracted, run: `python -m pytest tests/ -x -q`

Report: total tests passing, any failures, final line count of api.py, list of router files with line counts.
