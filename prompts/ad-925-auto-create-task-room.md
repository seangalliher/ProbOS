# AD-925 — Auto-create the task-linked workspace room

**Foundation of the "Task Workspace Rooms" epic (AD-925 → AD-929).** When `CrewTaskExecutor` fans a
parent `WorkItem` out to **≥2 distinct crew** agents, automatically open **ONE** task-linked group chat
(via the existing AD-918 `AgentGroupChatService.create_group_chat` path) so the collaborators share a
room while they work. The room IS the workspace.

| Field | Value |
|-------|-------|
| Target repo | **OSS** (`d:\ProbOS`) |
| Highest committed AD | **AD-924** (`a4a3971d`, pushed) |
| Layer | Cognitive (`crew_executor.py`) + a 3-line additive store filter + 1 config field |
| Depends on | AD-859 `CrewTaskExecutor`, AD-918 `AgentGroupChatService`, AD-791a `chat_threads.task_id`, AD-919 `GroupChatListPanel` (surface — no change) |
| Estimated tests | **+7** (new `tests/test_ad925_auto_task_room.py`); BF-287 real fixtures |
| Commit | local only — **do NOT push** (Captain reviews the epic before it goes public) |

---

## Problem

The Captain wants a decomposed task's collaborators to share a task-linked group chat that acts as a
Cowork-style workspace. The substrate ruling (autonomous, Captain away) is **Option A**: extend the
chat-thread + `ArtifactStore` world, not bridge `ConsultationWorkspace` (recorded in
[docs/development/roadmap.md](../docs/development/roadmap.md) — search "Task Workspace Rooms northstar").

Today nothing opens that room. `CrewTaskExecutor.run(parent_id)`
([src/probos/cognitive/crew_executor.py](../src/probos/cognitive/crew_executor.py#L84)) drives a parent's
child sub-tasks across multiple crew agents but never creates a shared thread. The primitives all exist:

- `AgentGroupChatService.create_group_chat(*, creator_id, title, participants=None, task_id=None, first_message=None)`
  ([agent_group_chat.py:145](../src/probos/threads/agent_group_chat.py#L145)) already persists
  `chat_threads.task_id` + `metadata.created_by_agent` and honors the AD-918 cooldown/cap. It is **synchronous**.
- `runtime.agent_group_chat` ([runtime.py:468](../src/probos/runtime.py#L468)) and
  `runtime.chat_thread_store` ([runtime.py:450](../src/probos/runtime.py#L450)) are both **public**.
- `CrewTaskExecutor` holds `self._runtime` and `self._store` (a `WorkItemStore` with async `get_work_item`).

AD-925 wires the auto-create into the executor and adds the two minimal additive primitives it needs
(a `task_id` filter on `list_threads` for idempotency; a default-OFF config flag).

---

## Solution overview

Add a single `await self._maybe_open_task_room(parent_id, children)` call at the top of
`CrewTaskExecutor.run`, right after the `if not children: return []` guard (so the room exists **before**
the children execute). The helper:

1. **Config gate** — return unless `runtime.config.group_chat.auto_task_room_enabled` is `True`.
2. **Substrate gate** — honest-degrade (return) if `runtime.agent_group_chat` / `runtime.chat_thread_store`
   are not wired (existing AD-859 tests pass `runtime=object()`; the new path must never assume a full runtime).
3. **≥2-crew gate** — collect the **distinct crew** `child.assigned_to` ids (via the shared public
   `is_crew_agent` util, None-guarded); return if `< 2`.
4. **Idempotency** — return if a thread already exists with this `task_id`
   (`store.list_threads(task_id=parent_id, include_archived=True, limit=1)`).
5. **Create** — fetch the parent for its title, then call the **existing**
   `service.create_group_chat(creator_id=<first crew assignee>, title="Task: <parent title>",
   participants=<the rest>, task_id=parent_id)`. The service auto-adds the creator, so the final
   participants are exactly the crew child-assignees; it tags `metadata.created_by_agent` so AD-919 surfaces it.
6. Honest-degrade every branch (Tier 2: log + return; never raise out of the fan-out).

**`creator_id` decision (the `_is_crew` gate concern).** `create_group_chat` rejects a non-crew creator
(`_is_crew(creator_id)` → `error="not_crew"`) and **always auto-adds the creator as a participant**. A
synthetic system id (e.g. `GROUP_CHAT_COORDINATOR_ID`) would therefore be rejected AND would pollute the
participant list. **Resolution: use the first crew child-assignee (stable-sorted) as `creator_id`** — it
passes `_is_crew`, it is a participant anyway, and its `_rate_ok` budget is the natural anti-storm guard.
**No service change is required.** (We deliberately do NOT add a `system_created` bypass: it would either
re-introduce a non-crew participant or fork the create path — both worse than reusing a real crew creator.)

**Default-OFF, justified.** `auto_task_room_enabled` ships `False` (transitional flag, wave-10 convention
#14 + the AD-918 create-storm history). The Captain flips it on after reviewing AD-925..927. Note the path
is **doubly gated**: even with this flag ON, the crew pipeline that calls the executor
(`agentic_dispatch.orchestrator_enabled`) itself ships OFF, so a zero-config boot creates no rooms.

---

## Section 1 — Config flag (`config.py`)

Add one default-OFF field to the existing `GroupChatConfig` (do **not** create a new config class).

**SEARCH** (`src/probos/config.py`, in `class GroupChatConfig`):

```python
    agent_create_cooldown_seconds: float = 60.0   # min seconds between two creates by one agent
    agent_create_max_per_window: int = 5          # max creates per agent per window
    agent_create_window_seconds: float = 3600.0   # sliding window (1 hour)
```

**REPLACE**:

```python
    agent_create_cooldown_seconds: float = 60.0   # min seconds between two creates by one agent
    agent_create_max_per_window: int = 5          # max creates per agent per window
    agent_create_window_seconds: float = 3600.0   # sliding window (1 hour)
    # AD-925: auto-create ONE task-linked workspace room when CrewTaskExecutor
    # fans a parent out to >=2 distinct crew. Transitional flag (wave-10 #14) —
    # ships OFF; the Captain flips it on after reviewing AD-925..927. Note the
    # crew pipeline that drives the executor (agentic_dispatch.orchestrator_enabled)
    # also ships OFF, so a zero-config boot creates no task rooms.
    auto_task_room_enabled: bool = False
```

No mount change needed — `group_chat: GroupChatConfig = GroupChatConfig()` is already on `SystemConfig`
([config.py:5175](../src/probos/config.py#L5175)), so the field reaches `runtime.config.group_chat`. The three
`agent_create_*` fields the SEARCH anchors on end at config.py:3770.

---

## Section 2 — Idempotency primitive: `task_id` filter on `list_threads` (`threads/__init__.py`)

`ChatThreadStore.list_threads` ([threads/__init__.py:244](../src/probos/threads/__init__.py#L244)) supports
`include_archived` / `project_id` / `limit` but **not** `task_id`. Add a `task_id` filter mirroring the
existing `project_id` clause exactly. The `task_id` column already exists (AD-791a; written by
`create_thread`/`update_thread`). This is the queryable primitive AD-926/927/929 will also reuse.

**SEARCH** (`src/probos/threads/__init__.py`):

```python
    def list_threads(
        self,
        *,
        include_archived: bool = False,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatThread]:
        clauses: list[str] = []
        params: list = []
        if not include_archived:
            clauses.append("archived = 0")
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
```

**REPLACE**:

```python
    def list_threads(
        self,
        *,
        include_archived: bool = False,
        project_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatThread]:
        clauses: list[str] = []
        params: list = []
        if not include_archived:
            clauses.append("archived = 0")
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if task_id is not None:  # AD-925: idempotency lookup for the task room
            clauses.append("task_id = ?")
            params.append(task_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
```

---

## Section 3 — Auto-create wiring (`crew_executor.py`)

### 3a. Import the shared crew predicate

**SEARCH** (`src/probos/cognitive/crew_executor.py`, top imports):

```python
from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.substrate.registry import AgentRegistry
    from probos.workforce import WorkItem, WorkItemStore
```

**REPLACE**:

```python
from probos.crew_utils import is_crew_agent
from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.substrate.registry import AgentRegistry
    from probos.workforce import WorkItem, WorkItemStore
```

### 3b. Fire the auto-create at the top of `run`

**SEARCH** (in `async def run`):

```python
        if not children:
            return []

        by_id: dict[str, WorkItem] = {c.id: c for c in children}
```

**REPLACE**:

```python
        if not children:
            return []

        # AD-925: open the ONE task-linked workspace room before the children
        # work, so the collaborators share it while executing. Honest-degrade —
        # never blocks or aborts the fan-out.
        await self._maybe_open_task_room(parent_id, children)

        by_id: dict[str, WorkItem] = {c.id: c for c in children}
```

### 3c. The helper + crew predicate

Add these two methods to `CrewTaskExecutor`, immediately **before** the existing `_emit` method.

**SEARCH**:

```python
    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Publish a lifecycle event, honest-degrading when no emit fn is wired."""
```

**REPLACE**:

```python
    def _is_crew_assignee(self, agent_id: str) -> bool:
        """True iff ``agent_id`` resolves to a live crew agent.

        Mirrors ``AgentGroupChatService._is_crew`` via the shared public
        ``is_crew_agent`` predicate (ontology=None — the legacy crew-type path,
        AD-918 test precedent), None-guarding an unresolvable id.
        """
        agent = self._registry.get(agent_id)
        return bool(agent) and is_crew_agent(agent, None)

    async def _maybe_open_task_room(
        self, parent_id: str, children: list[WorkItem]
    ) -> None:
        """AD-925: open ONE task-linked group chat for a >=2-crew fan-out.

        Reuses the AD-918 ``AgentGroupChatService.create_group_chat`` path so
        the cooldown / sliding-window cap + crew participant resolution all
        apply — no parallel thread-creation path. Every branch that cannot
        proceed returns without raising (Tier-2 honest-degrade) so a disabled
        flag / missing collaborator never breaks the fan-out.
        """
        runtime = self._runtime
        group_chat_cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
        if not getattr(group_chat_cfg, "auto_task_room_enabled", False):
            return
        service = getattr(runtime, "agent_group_chat", None)
        store = getattr(runtime, "chat_thread_store", None)
        if service is None or store is None:
            logger.debug(
                "AD-925: group-chat substrate not wired on runtime; skipping "
                "task room for parent %s.",
                parent_id,
            )
            return

        # >=2 DISTINCT crew assignees (a single-agent task needs no room).
        crew_assignees = sorted(
            {
                c.assigned_to
                for c in children
                if c.assigned_to and self._is_crew_assignee(c.assigned_to)
            }
        )
        if len(crew_assignees) < 2:
            return

        # Idempotency: exactly one room per task (AD-791a task_id + the AD-925
        # list_threads(task_id=) filter). A retry / re-run finds it and stops.
        if store.list_threads(task_id=parent_id, include_archived=True, limit=1):
            return

        parent = await self._store.get_work_item(parent_id)
        title = (
            f"Task: {parent.title}"
            if parent and parent.title
            else f"Task {parent_id}"
        )
        # The first crew assignee is the creator: it passes the service's
        # _is_crew gate and is auto-added as a participant, so the final
        # participants are exactly the crew child-assignees.
        creator_id = crew_assignees[0]
        result = service.create_group_chat(
            creator_id=creator_id,
            title=title,
            participants=crew_assignees[1:],
            task_id=parent_id,
        )
        if result.ok and result.thread is not None:
            logger.info(
                "AD-925: opened task room %s for parent %s (%d crew, creator=%s).",
                result.thread.id,
                parent_id,
                len(crew_assignees),
                creator_id,
            )
        else:
            logger.info(
                "AD-925: task room not opened for parent %s (%s); fan-out continues.",
                parent_id,
                result.error or "unknown",
            )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Publish a lifecycle event, honest-degrading when no emit fn is wired."""
```

> No new `EventType` is added (the service already logs the create; AD-928 owns the status protocol). The
> existing `CREW_TASK_STARTED` / `SUBTASK_COMPLETED` events are untouched.

---

## Tests — `tests/test_ad925_auto_task_room.py` (BF-287 real fixtures, +7)

**Discipline (BF-287, MagicMock-at-substrate-boundary trap):** use a **real** `WorkItemStore`, a **real**
`ChatThreadStore`, and a **real** `AgentGroupChatService`. The `ChatThreadStore` passed to the service and
the one on the runtime stub **must be the SAME instance** (the idempotency check reads what the service
wrote). Registry/agentic-executor are `_Fake*` duck stubs (the AD-859/AD-918 precedent), never `MagicMock`.

**Fixtures (assemble from the verified precedents):**

- Combined `_FakeAgent` carrying both crew identity and execution fields:
  `id`, `agent_type` (a legacy crew type so `is_crew_agent(agent, None)` is True, e.g. `"builder"`,
  `"diagnostician"`), `is_alive=True`, plus `instructions` / `department` / `rank` (read by `_run_child`).
- `_FakeRegistry` with `get(agent_id)` (the AD-918 shape).
- `_FakeAgenticExecutor` from [tests/test_ad859_crew_executor.py](../tests/test_ad859_crew_executor.py)
  (records calls, returns `stopped_reason="complete"`).
- Real `WorkItemStore(db_path=tmp/"crew.db", emit_event=MagicMock(), tick_interval=1000)` started/stopped
  (the AD-859 `store` fixture — `MagicMock` for `emit_event` only, not the store).
- **ONE** real `ChatThreadStore(tmp/"chat_threads.db")` shared by:
  `service = AgentGroupChatService(store=chat_store, registry=registry, callsign_registry=_NoCallsigns(),
  config=group_chat_cfg, ontology_provider=None, clock=_Clock())`.
- Runtime stub: `SimpleNamespace(config=SimpleNamespace(group_chat=group_chat_cfg),
  agent_group_chat=service, chat_thread_store=chat_store)`.
- Build the executor: `CrewTaskExecutor(work_item_store=wi_store, agent_registry=registry,
  agentic_executor=fake_agentic, runtime=runtime_stub, max_parallel_subtasks=3)`.
- Helper: create a **real** parent (`await wi_store.create_work_item(title="Build the dashboard", ...)`),
  then children with `parent_id=parent.id`, `assigned_to=<agent id>` (the AD-859 `_make_child` shape).

**Test cases:**

1. `test_two_crew_fanout_opens_one_task_room` — parent + 2 children assigned to 2 distinct crew agents,
   `auto_task_room_enabled=True`. After `await executor.run(parent.id)`:
   `chat_store.list_threads(task_id=parent.id, include_archived=True)` has **exactly one** thread; its
   `title == "Task: Build the dashboard"`, `task_id == parent.id`, `metadata["created_by_agent"]` is the
   first (sorted) crew assignee, and `set(thread.participants) == {both child-assignees}`.
2. `test_single_crew_parent_opens_no_room` — one child (or all children assigned to the SAME single agent);
   after `run`, `list_threads(task_id=parent.id)` is empty.
3. `test_idempotent_second_run_no_duplicate` — call `await executor.run(parent.id)` **twice**; still
   exactly one thread for that `task_id` (the second run hits the idempotency guard).
4. `test_config_off_opens_no_room` — `GroupChatConfig(auto_task_room_enabled=False)`; 2-crew fan-out; no room.
5. `test_noncrew_assignees_open_no_room` — both children assigned to **non-crew** agents
   (`agent_type` outside the crew set); `< 2` crew → no room (crew gate holds).
6. `test_rate_limited_creator_degrades_no_room` — `GroupChatConfig(auto_task_room_enabled=True,
   agent_create_max_per_window=0)` so `_rate_ok` always denies; 2-crew fan-out → **no room**, and
   `executor.run` still returns its `SubtaskResult`s (the fan-out is not aborted — AD-918 rate guard holds).
7. `test_list_threads_filters_by_task_id` — direct `ChatThreadStore` unit test of the Section-2 primitive:
   create two threads with different `task_id`s (and one with none); `list_threads(task_id=X)` returns only X.

Gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad925_auto_task_room.py tests/test_ad859_crew_executor.py tests/test_ad918_agent_initiated_group_chat.py -q -n 0 -p no:cacheprovider`,
then the full parallel gate `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.

---

## What this does NOT change (non-goals — out of scope)

- **No Input pane (AD-926):** task/parent attached files are not surfaced here.
- **No Output/artifact tag (AD-927):** the `ArtifactDrawer` is not mounted and no `[ARTIFACT]` tag is added.
- **No status protocol (AD-928):** no `federation.md` standing order, no progress/final-result convention.
- **No UI (AD-929 / AD-919):** the room already surfaces via the AD-919 `GroupChatListPanel`
  (`metadata.created_by_agent`); no frontend change.
- **No `AgentGroupChatService` change:** the create path, cooldown/cap, and `_is_crew` gate are reused as-is.
- **No new `EventType`.** No change to `CrewOrchestrator` / `maybe_dispatch_crew` / `originate_crew_task`,
  and no change to `agentic_dispatch.orchestrator_enabled` (the crew pipeline stays OFF by default).
- **No `first_message`** posted (that is the AD-928 status protocol's job).

---

## Tracking

- **PROGRESS.md** — add an `AD-925 shipped` entry (auto-create task room; +7 tests; the doubly-gated note).
- **DECISIONS.md** — append AD-925 (Option-A substrate; first-crew-assignee creator; `task_id` filter
  idempotency; default-OFF flag).
- **docs/development/roadmap.md** — mark the AD-925 row shipped (the epic table already exists).
- One commit `AD-925: auto-create the task-linked workspace room` — **local only, do NOT push.**

---

## Acceptance criteria

- [ ] `GroupChatConfig.auto_task_room_enabled: bool = False` added; zero-config boot byte-identical.
- [ ] `ChatThreadStore.list_threads` accepts `task_id` and filters on it (mirrors `project_id`).
- [ ] A ≥2-distinct-crew fan-out with the flag ON creates **exactly one** thread with `task_id == parent_id`,
      `title == "Task: <parent title>"`, and participants == the crew child-assignees.
- [ ] A single-crew (or non-crew) fan-out creates **no** room.
- [ ] A second `run` of the same parent creates **no** duplicate (idempotent).
- [ ] Flag OFF → no room. Rate-limited creator → no room, fan-out still returns its results.
- [ ] The AD-918 cooldown/cap + `_is_crew` creator gate are honored (reused, not bypassed).
- [ ] `tests/test_ad925_auto_task_room.py` (+7) green; `test_ad859_*` and `test_ad918_*` still green;
      full parallel gate green (real `passed` count up, no new failures).
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08)

```
# CrewTaskExecutor: holds runtime + store; run() loads children then guards
src/probos/cognitive/crew_executor.py:58   class CrewTaskExecutor:
  :64  def __init__(self, *, work_item_store, agent_registry, agentic_executor, runtime: Any, max_parallel_subtasks=3, emit_fn=None)
  :73  self._runtime = runtime
  :84  async def run(self, parent_id: str) -> list[SubtaskResult]:
  :89  children = await self._store.list_work_items(parent_id=parent_id, limit=1000)
  :96  if not children: return []
  :99  by_id: dict[str, WorkItem] = {c.id: c for c in children}     # <- insertion point is just above this
  :49  child.assigned_to  read at _run_child:171 (single str|None)

# create_group_chat: SYNC, _is_crew + _rate_ok gates, auto-adds creator, persists task_id + created_by_agent
src/probos/threads/agent_group_chat.py:145 def create_group_chat(self, *, creator_id, title, participants=None, task_id=None, first_message=None) -> GroupChatCreateResult
       if not self._is_crew(creator_id): return GroupChatCreateResult(ok=False, error="not_crew")
       if not self._rate_ok(creator_id): return ... error="rate_limited"
       final: list[str] = [creator_id]            # creator always included
       self._store.create_thread(title=, participants=final, task_id=task_id, metadata={"created_by_agent": creator_id})
  _is_crew(agent_id): agent = self._registry.get(agent_id); if agent is None: return False; return is_crew_agent(agent, ...)

# Public runtime handles (no Demeter violation)
src/probos/runtime.py:468  self.agent_group_chat = AgentGroupChatService(... config=self.config.group_chat ...)
src/probos/runtime.py:450  self.chat_thread_store = ChatThreadStore(db_path=self._data_dir / "chat_threads.db")

# Config: GroupChatConfig at 3747, mounted as config.group_chat at 5175
src/probos/config.py:3747  class GroupChatConfig(BaseModel)
src/probos/config.py:3770  agent_create_window_seconds: float = 3600.0   # <- append the new field after this
src/probos/config.py:5175  group_chat: GroupChatConfig = GroupChatConfig()  # AD-915

# list_threads has NO task_id filter today (additive needed)
src/probos/threads/__init__.py:244  def list_threads(self, *, include_archived=False, project_id=None, limit=100)
src/probos/threads/__init__.py:256  if project_id is not None: clauses.append("project_id = ?")   # mirror this for task_id

# Parent title source (async)
src/probos/workforce.py:1076  async def get_work_item(self, work_item_id: str) -> WorkItem | None

# Shared crew predicate (used by runtime + agent_group_chat already)
src/probos/crew_utils.py  is_crew_agent(agent, ontology)   # imported at runtime.py + agent_group_chat.py:31

# Live invocation chain (DORMANCY NOTE): executor fires via the AD-868 proactive [CREW] path, gated OFF
src/probos/cognitive/crew_orchestrator.py:97  async def maybe_dispatch_crew(...)   # NO live caller (forward marker)
  run_crew_task -> Stage 2: results = await crew_executor.run(parent_id)            # PROGRESS.md:129
  gate: agentic_dispatch.orchestrator_enabled: bool = False (ships OFF)             # PROGRESS.md:129
```
