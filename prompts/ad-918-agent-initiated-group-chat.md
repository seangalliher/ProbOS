# AD-918 — Agent-initiated group chats (`create_group_chat` intent)

**Status:** Ready for Builder
**Epic:** Ad-hoc Crew Collaboration (group chat → meeting), roadmap northstar (`docs/development/roadmap.md:357`)
**Dependencies:** AD-913 (`add_participant`/`remove_participant`), AD-914 (`group_chat_fanout`), AD-915 (`GroupChatConfig` + facilitator). All shipped + committed.
**Current highest committed AD:** **AD-917 (`dae090a5`)** — `git log --oneline -1` → `dae090a5 (HEAD -> main) AD-917`. No AD-918 commit exists. This is the next sequential AD.
**Estimated new tests:** floor **14**, target **16** (`tests/test_ad918_agent_initiated_group_chat.py`).

One-liner: let a **crew agent** create + name a group chat on its own, add crew collaborators, optionally link it to a work item, and (optionally) post the first message — via a governed `create_group_chat` intent backed by a rate-limited service. Tag `metadata.created_by_agent` so the Captain can later see + join it (AD-919). Lifts the AD-719a-2 deferral on the **ChatThreadStore** substrate (NOT Ward Room).

---

## Problem

The AD-913→917 epic gave the Captain a full group-chat surface (participant management, fan-out, file sharing, UI). But every chat is still **Captain-seeded**:

- `ChatThreadStore.create_thread` is only ever called by the 1:1 default-thread path (`get_or_create_default_for_agent`) and the REST `POST /api/threads` handler — both Captain-driven. (`src/probos/threads/__init__.py:184`).
- AD-914 `group_chat_fanout` only fires on a **Captain** post (`role == "captain"`) with ≥2 crew participants (`src/probos/routers/thread_fanout.py` gate). An agent cannot start a room.
- The AD-719a Ward Room contract froze this explicitly: *"Captain messages are always the seed. Agent-to-agent messages without a Captain prompt are not generated in v1 (deferred to AD-719a-2)"* (`src/probos/ward_room/multi_agent.py:16,77`).

There is no mechanism for a crew agent, mid-task, to say *"Bones and I need to coordinate — open a room."* AD-918 adds exactly that capability, on the new epic substrate (ChatThreadStore), with conservative spam controls.

---

## Solution overview

### Mechanism decision: a `create_group_chat` **intent** + bare-callable handler backed by a stateful service

The roadmap row prescribes *"a `create_group_chat` intent"* (`roadmap.md:368`). This is the correct, principle-aligned choice over a bare service method:

- **Uniform transport invariant.** Agent *actions* route through the intent bus (Design Principle #10 — "designed agents must route through the bus, not a side-channel"). Creating a persistent, spam-capable thread row is an action; a direct `runtime.<svc>.create()` call from agent code would be a side-channel that bypasses the bus (the BF-265/267 lesson: don't bolt side-channels onto the runtime to make a feature work).
- **Bare-callable handler, not a new agent/pool.** `IntentHandler = Callable[[IntentMessage], Awaitable[IntentResult | None]]` (`src/probos/mesh/intent.py:21`). Non-agent handlers already subscribe directly — `runtime.intent_bus.subscribe(sub_id, self._handle_proactive_scan, intent_names=["proactive_scan"])` (`src/probos/cognitive/yeoman.py:242`); also `perception/consumer.py:193`, `perception/aggregator.py:86`. So the coordinator is a **synthetic subscriber** (no `_create_pools` wiring, no registry entry). This is the lightest *governed* wiring.
- **Logic in a testable service.** All create/validation/rate-limit logic lives in a new `AgentGroupChatService` (constructor-injected, real-fixture testable per BF-287). The handler is a thin shell. This mirrors the AD-915 pure/impure split (pure `chat_facilitator.py` + impure wiring inside `group_chat_fanout`).

**Rejected alternatives** (state in commit body): (a) full new `GroupChatCoordinatorAgent` utility agent — heavier (`_create_pools` + registry + onboarding wiring) with no v1 benefit, since decomposer/Captain-NL discovery is deferred; (b) bare `runtime.agent_group_chat.create()` service method called directly from agent code — bypasses the uniform intent transport.

### Consensus: `requires_consensus=False` — JUSTIFIED, do **NOT** gate

Creating a chat is **low-risk and reversible** (`ChatThreadStore.delete_thread` exists, `__init__.py:501`). Per the **Safety Budget** axiom (consensus is *risk-proportional*) and **Minimal Authority** (scoped capability, earned trust), a reversible, non-destructive create does **not** warrant a consensus gate. Consensus is reserved for destructive/irreversible intents (`requires_consensus=True` is for ops like `delete`/`run_command`). The genuine risk here is a **create-storm**, which is addressed by a per-agent cooldown + window cap (below) — **not** consensus. So `IntentDescriptor(..., requires_consensus=False)`.

### Safety / loop model — what prevents a create-storm

Reuse the established per-agent rate-limit shape (BF-163 per-agent DM cooldown + BF-257 sliding-window budget, both in `proactive.py`): a long-lived dict on the service holding per-agent create timestamps. Two conservative gates, default-on, configured via the existing `GroupChatConfig`:

- **Cooldown** — min seconds between two creates by the same agent (`agent_create_cooldown_seconds`, default `60.0`; BF-163 uses 60s).
- **Window cap** — max creates per agent per sliding window (`agent_create_max_per_window`, default `5`; `agent_create_window_seconds`, default `3600.0`).

A misbehaving agent can create at most 5 rooms/hour, ≥60 s apart. (See the **Loop-safety analysis** section for the full argument, including why no auto-reply storm is possible in v1.)

### `task_id` linkage: optional caller param + documented seam (v1)

`chat_threads.task_id` is a real column (AD-791a, `__init__.py:48`) and already a `create_thread` param (`__init__.py:189`). **But** a working agent has **no persistent `current_task_id`**: the work-item id reaches an agent only inside `intent.params["work_item_id"]` while it handles a `work_item_dispatch` intent (`src/probos/cognitive/cognitive_agent.py:1097`). Auto-wiring the live task id is too deep for v1.

**v1:** `task_id` is an **optional param** the caller passes (or the emitting intent carries in `params["task_id"]`). **Deferred seam (document, do not build):** a future AD has the agent forward `intent.params["work_item_id"]` (available during `work_item_dispatch`) as the `task_id` when it emits `create_group_chat`. Type-compatible (both `str`).

---

## Section 1 — `ChatThreadStore.create_thread`: additive `metadata` param

**File:** `src/probos/threads/__init__.py`

`create_thread` (line 184) does **not** persist metadata — its INSERT omits the `metadata` column, so it defaults `NULL` and reads back as `{}` via `_row_to_thread` (`__init__.py:1061`). The `metadata` column exists (AD-791a `_migrate_v2`, `__init__.py:1100`). Precedent for an INSERT that writes metadata: `create_default_for_agent` (`__init__.py:550`) and `get_or_create_default_for_agent` (`__init__.py:615`), both `metadata = {"is_default": True}`.

Add an **optional** `metadata: dict | None = None` keyword param. Extend the INSERT to write the `metadata` column (`json.dumps(metadata or {})`) and set it on the returned `ChatThread`.

SEARCH/REPLACE (preserve the keyword-only `*`):

```python
    def create_thread(
        self,
        *,
        title: str,
        participants: Iterable[str],
        project_id: str | None = None,
        task_id: str | None = None,
        personality_override: str | None = None,
        workspace_root: str | None = None,
    ) -> ChatThread:
        thread_id = self._id_factory()
        now = self._clock()
        parts = list(participants)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_threads (id, title, participants, project_id, task_id, "
                "pinned, archived, personality_override, workspace_root, "
                "created_at, last_active_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    thread_id,
                    title,
                    json.dumps(parts),
                    project_id,
                    task_id,
                    0,
                    0,
                    personality_override,
                    workspace_root,
                    now,
                    now,
                ),
            )
        return ChatThread(
            id=thread_id,
            title=title,
            participants=parts,
            project_id=project_id,
            task_id=task_id,
            pinned=False,
            archived=False,
            personality_override=personality_override,
            workspace_root=workspace_root,
            created_at=now,
            last_active_at=now,
        )
```

→

```python
    def create_thread(
        self,
        *,
        title: str,
        participants: Iterable[str],
        project_id: str | None = None,
        task_id: str | None = None,
        personality_override: str | None = None,
        workspace_root: str | None = None,
        metadata: dict | None = None,
    ) -> ChatThread:
        thread_id = self._id_factory()
        now = self._clock()
        parts = list(participants)
        # AD-918: optional creation metadata (e.g. {"created_by_agent": <id>}).
        # None preserves the pre-AD-918 read shape — NULL and "{}" both
        # decode to {} via _row_to_thread, so existing callers are unaffected.
        meta = dict(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_threads (id, title, participants, project_id, task_id, "
                "pinned, archived, personality_override, workspace_root, "
                "created_at, last_active_at, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    thread_id,
                    title,
                    json.dumps(parts),
                    project_id,
                    task_id,
                    0,
                    0,
                    personality_override,
                    workspace_root,
                    now,
                    now,
                    json.dumps(meta),
                ),
            )
        return ChatThread(
            id=thread_id,
            title=title,
            participants=parts,
            project_id=project_id,
            task_id=task_id,
            pinned=False,
            archived=False,
            personality_override=personality_override,
            workspace_root=workspace_root,
            created_at=now,
            last_active_at=now,
            metadata=meta,
        )
```

**Build-time check:** grep `tests/test_ad791*.py` for any assertion that a `create_thread`-created thread has `metadata is None` / NULL. None exists at HEAD (`test_ad791a:134` only asserts the column *exists*). If one surfaces, it is an obsolete-contract test — update it to expect `{}` (reads are identical).

---

## Section 2 — `GroupChatConfig`: agent-create rate-limit fields

**File:** `src/probos/config.py` — extend the existing `GroupChatConfig` (line 3747, AD-915). **Do not** create a new config class (DRY / config-standards: new config goes into existing Pydantic models, every field has a sensible default).

Append three fields after `weight_trust`:

```python
    weight_trust: float = 0.10
    # AD-918: per-agent rate limit on agent-initiated group-chat creation.
    # Conservative defaults prevent a create-storm without blocking
    # legitimate ad-hoc collaboration. Reuses the BF-163 (60s DM cooldown)
    # + BF-257 (sliding-window budget) shape.
    agent_create_cooldown_seconds: float = 60.0   # min seconds between two creates by one agent
    agent_create_max_per_window: int = 5          # max creates per agent per window
    agent_create_window_seconds: float = 3600.0   # sliding window (1 hour)
```

Zero-config boot is preserved (sensible defaults; `group_chat: GroupChatConfig = GroupChatConfig()` already mounted at `config.py:5167`).

---

## Section 3 — `AgentGroupChatService` (new module — the testable core)

**New file:** `src/probos/threads/agent_group_chat.py`

Cohesion: lives in the `threads` package next to `ChatThreadStore`. Constructor-injection (Dependency Inversion); every external lookup is **Tier-2 log-and-degrade**. `ontology` is read **lazily** via an injected provider because `runtime.ontology` is set late (`runtime.py:2211`, after `__init__`); `is_crew_agent` falls back to the legacy crew set when ontology is `None` (`crew_utils.py:21`), so tests can pass `ontology_provider=None`.

Required behaviour:

```python
"""AD-918: agent-initiated group-chat creation.

Lets a crew agent open + name a group chat on the ChatThreadStore substrate
(the epic substrate per the Captain ruling — NOT Ward Room), add crew
collaborators, optionally link a work item via chat_threads.task_id, and
optionally post the first message. Tagged metadata.created_by_agent=<id> so
AD-919 can surface + Captain-join it. Lifts the AD-719a-2 deferral
("agent-to-agent without a Captain seed").

Mechanism: invoked via the create_group_chat intent (handle_intent is a
bare-callable bus subscriber per the yeoman.py:242 precedent). All logic
lives here so it is testable with real fixtures (BF-287) without the bus.

Safety: per-agent cooldown + sliding-window cap (BF-163 + BF-257 shape)
prevent a create-storm. Creating a chat is reversible + low-risk, so it is
NOT consensus-gated (Safety Budget axiom: risk-proportional consensus).

Boundary (v1): this creates the room + adds participants + (optionally)
posts ONE first message. It does NOT build an agent-to-agent auto-reply
loop, and the created thread has no Captain post so AD-914 fan-out does not
auto-run on it (fan-out gates on role=="captain"). The created thread is a
normal ChatThread — a later Captain post fans out normally (AD-919), and
AD-913 add/remove_participant work on it unchanged.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.crew_utils import is_crew_agent
from probos.threads import ChatThread, ChatThreadStore
from probos.types import IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)

# AD-918: synthetic subscriber id for the bare-callable handler (yeoman.py:242
# pattern — non-agent handler under a stable id, NOT a registry entry).
GROUP_CHAT_COORDINATOR_ID = "group_chat_coordinator"

CREATE_GROUP_CHAT = "create_group_chat"

# AD-918 forward marker: descriptor for future decomposer/Captain-NL exposure.
# v1 wires the handler directly (crew agents emit via the bus); attaching this
# to a registered agent for decomposer discovery is deferred (see boundary).
CREATE_GROUP_CHAT_DESCRIPTOR = IntentDescriptor(
    name=CREATE_GROUP_CHAT,
    params={
        "title": "Name for the new group chat",
        "participants": "list of crew agent_ids or callsigns to add",
        "task_id": "optional work-item id to link the chat to",
        "first_message": "optional first message body the creator posts",
    },
    description="Open + name a crew group chat and add collaborators while working a task.",
    requires_consensus=False,  # reversible, low-risk — Safety Budget axiom (see AD-918 prompt)
    tier="utility",
)


@dataclass
class GroupChatCreateResult:
    ok: bool
    thread: ChatThread | None = None
    error: str = ""
    participants_added: list[str] = field(default_factory=list)


class AgentGroupChatService:
    """Stateful service: create-logic + per-agent rate limiting for
    agent-initiated group chats. Constructor-injected; bus-agnostic."""

    def __init__(
        self,
        *,
        store: ChatThreadStore,
        registry: Any,
        callsign_registry: Any,
        config: Any,  # GroupChatConfig
        ontology_provider: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._registry = registry
        self._callsign_registry = callsign_registry
        self._config = config
        self._ontology_provider = ontology_provider
        self._clock = clock
        # agent_id -> [monotonic create timestamps] (BF-257 sliding-window shape)
        self._create_times: dict[str, list[float]] = {}

    # ---- helpers -----------------------------------------------------

    def _ontology(self) -> Any:
        if self._ontology_provider is None:
            return None
        try:
            return self._ontology_provider()
        except Exception:
            logger.debug("AD-918: ontology provider failed", exc_info=True)
            return None

    def _is_crew(self, agent_id: str) -> bool:
        agent = self._registry.get(agent_id) if agent_id else None
        if agent is None:
            return False
        return is_crew_agent(agent, self._ontology())

    def _resolve_participant(self, ref: str) -> str | None:
        """Resolve a participant ref (agent_id OR callsign) to a crew agent_id.
        Tier-2: unresolvable / non-crew refs are dropped, not raised."""
        if not ref or not ref.strip():
            return None
        ref = ref.strip()
        # agent_id path
        if self._is_crew(ref):
            return ref
        # callsign path
        try:
            resolved = self._callsign_registry.resolve(ref)
        except Exception:
            logger.debug("AD-918: callsign resolve failed for %s", ref, exc_info=True)
            resolved = None
        if resolved and resolved.get("agent_id") and self._is_crew(resolved["agent_id"]):
            return resolved["agent_id"]
        return None

    def _rate_ok(self, creator_id: str) -> bool:
        """Cooldown + sliding-window cap. Records the timestamp on success."""
        now = self._clock()
        window = float(getattr(self._config, "agent_create_window_seconds", 3600.0))
        cooldown = float(getattr(self._config, "agent_create_cooldown_seconds", 60.0))
        cap = int(getattr(self._config, "agent_create_max_per_window", 5))
        times = self._create_times.setdefault(creator_id, [])
        times[:] = [t for t in times if now - t < window]  # prune
        if len(times) >= cap:
            return False
        if times and now - times[-1] < cooldown:
            return False
        times.append(now)
        return True

    # ---- core --------------------------------------------------------

    def create_group_chat(
        self,
        *,
        creator_id: str,
        title: str,
        participants: list[str] | None = None,
        task_id: str | None = None,
        first_message: str | None = None,
    ) -> GroupChatCreateResult:
        title = (title or "").strip()
        if not title:
            return GroupChatCreateResult(ok=False, error="empty_title")
        if not self._is_crew(creator_id):
            return GroupChatCreateResult(ok=False, error="not_crew")
        if not self._rate_ok(creator_id):
            return GroupChatCreateResult(ok=False, error="rate_limited")

        # Resolve + dedupe participants; creator is always included.
        final: list[str] = [creator_id]
        for ref in participants or []:
            aid = self._resolve_participant(ref)
            if aid and aid not in final:
                final.append(aid)

        thread = self._store.create_thread(
            title=title,
            participants=final,
            task_id=task_id,
            metadata={"created_by_agent": creator_id},
        )
        if first_message and first_message.strip():
            self._store.append_message(
                thread.id,
                author_id=creator_id,
                role="agent",
                body=first_message.strip(),
                metadata={"created_by_agent": creator_id},
            )
        logger.info(
            "AD-918: %s opened group chat %s (%d participants, task_id=%s)",
            creator_id, thread.id, len(final), task_id,
        )
        return GroupChatCreateResult(ok=True, thread=thread, participants_added=final)

    # ---- bus handler -------------------------------------------------

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Bare-callable bus handler for the create_group_chat intent.

        Self-deselects (returns None) for non-matching intents so it is inert
        as a fallback subscriber. Caller identity travels in params (AD-914
        convention) — params["created_by_agent"] or params["from"]."""
        if intent.intent != CREATE_GROUP_CHAT:
            return None
        params = intent.params or {}
        creator_id = params.get("created_by_agent") or params.get("from") or ""
        result = self.create_group_chat(
            creator_id=creator_id,
            title=params.get("title", ""),
            participants=params.get("participants") or [],
            task_id=params.get("task_id"),
            first_message=params.get("first_message"),
        )
        return IntentResult(
            intent_id=intent.id,
            agent_id=GROUP_CHAT_COORDINATOR_ID,
            success=result.ok,
            result=(
                {"thread_id": result.thread.id, "participants": result.participants_added}
                if result.thread else None
            ),
            error=None if result.ok else result.error,
            confidence=1.0 if result.ok else 0.0,
        )
```

> Engineering notes the Builder must honor: full type annotations on all public methods; Tier-2 log-and-degrade on every registry/callsign/ontology lookup; structured log context (what + who + outcome); frozen-default ordering on the dataclass (non-defaulted `ok` first). `clock=time.monotonic` is injectable so tests advance a fake clock.

---

## Section 4 — Runtime wiring

**File:** `src/probos/runtime.py`

`ChatThreadStore` is instantiated at `runtime.py:450` (`self.chat_thread_store = ChatThreadStore(...)`), inside `__init__`, after `intent_bus` (374), `callsign_registry` (411-413). Instantiate the service there and subscribe the handler (yeoman.py:242 precedent — synthetic id + `intent_names`).

After the `chat_thread_store` / `ProjectStore` block, add:

```python
        # AD-918: agent-initiated group-chat creation. Bare-callable handler
        # subscribed under a synthetic id (yeoman.py:242 pattern) — no pool,
        # no registry entry. ontology read lazily (set later at startup).
        from probos.threads.agent_group_chat import (
            AgentGroupChatService,
            CREATE_GROUP_CHAT,
            GROUP_CHAT_COORDINATOR_ID,
        )
        self.agent_group_chat = AgentGroupChatService(
            store=self.chat_thread_store,
            registry=self.registry,
            callsign_registry=self.callsign_registry,
            config=self.config.group_chat,
            ontology_provider=lambda: self.ontology,
        )
        self.intent_bus.subscribe(
            GROUP_CHAT_COORDINATOR_ID,
            self.agent_group_chat.handle_intent,
            intent_names=[CREATE_GROUP_CHAT],
        )
```

> Build-time confirm: `self.registry`, `self.callsign_registry`, `self.intent_bus`, `self.config.group_chat` are all live at the `chat_thread_store` instantiation point (they are — 374/411/450, and `config` is set in `__init__`). `subscribe` with `intent_names=[CREATE_GROUP_CHAT]` indexes the handler so only `create_group_chat` broadcasts reach it; crew `CognitiveAgent`s subscribe *with* their own `intent_names` so they are not fallback subscribers for this intent. Add a `agent_group_chat: AgentGroupChatService` attribute to the runtime type/`__init__` annotations block if the file declares attrs up top (mirror how `chat_thread_store` is declared).

---

## Tests — `tests/test_ad918_agent_initiated_group_chat.py`

**BF-287 discipline** (mirror `tests/test_ad914_group_chat_fanout.py:1-40`): real `ChatThreadStore` on `tmp_path`; real `IntentBus(SignalManager(reap_interval=1.0))`; real-but-fake registry/callsign stubs (NOT `MagicMock`) at the substrate/bus boundary. A `_FakeAgent` exposes a real `.agent_type`; a `_FakeRegistry` exposes `.get(agent_id)`. Use crew `agent_type`s from the legacy set (`crew_utils._WARD_ROOM_CREW`, e.g. `"diagnostician"`, `"builder"`, `"architect"`) so `ontology_provider=None` resolves crew correctly. Use a real `GroupChatConfig()` (or one with small windows) and an injectable fake clock (a mutable `[t]` closure) to exercise cooldown/cap deterministically.

Floor 14 (target 16):

1. `test_create_named_chat_persisted_and_tagged` — `create_group_chat(creator=crew, title="Coord")` → `ok`; `store.get_thread(...)` shows title, `metadata["created_by_agent"] == creator`, creator in participants.
2. `test_creator_auto_added_when_participants_empty` — `participants=None`/`[]` → creator still the sole participant.
3. `test_add_second_crew_participant_by_agent_id` — `participants=[other_crew_id]` → both present, deduped.
4. `test_add_participant_by_callsign` — real `CallsignRegistry().load_from_profiles()` + `bind_registry(fake)`; pass a callsign → resolves to crew agent_id and is added (Tier-2: bad callsign dropped).
5. `test_non_crew_participant_filtered` — a non-crew ref is dropped; creator still added; `ok`.
6. `test_task_id_linkage_when_provided` — `task_id="wi-123"` → `thread.task_id == "wi-123"`.
7. `test_task_id_none_default` — omitted → `thread.task_id is None`.
8. `test_first_message_posted_when_provided` — `first_message="kick off"` → exactly one `chat_thread_messages` row, `role=="agent"`, `author_id==creator`.
9. `test_no_first_message_when_omitted` — no `first_message` → zero messages.
10. `test_cooldown_blocks_rapid_second_create` — two creates with clock advanced < cooldown → 2nd `ok=False, error=="rate_limited"`; only one thread persisted.
11. `test_window_cap_blocks_after_max` — advance past cooldown each time; the `(max+1)`th create → `rate_limited`.
12. `test_rate_resets_after_window` — advance clock past `agent_create_window_seconds` → create allowed again (`ok`).
13. `test_non_crew_creator_rejected` — non-crew creator → `ok=False, error=="not_crew"`; nothing persisted; budget not consumed.
14. `test_empty_title_rejected` — blank/whitespace title → `ok=False, error=="empty_title"`.
15. `test_handle_intent_creates_thread_via_real_bus` — subscribe `service.handle_intent` on a real `IntentBus`; `broadcast(IntentMessage(intent="create_group_chat", params={"created_by_agent": crew, "title": "Bridge", "participants": [...]}))` → one `IntentResult`, `success`, `result["thread_id"]` resolves to a persisted thread tagged `created_by_agent`.
16. `test_created_thread_is_normal_chatthread_for_ad913_and_ad914` — on the created thread: `store.add_participant(...)` / `remove_participant(...)` mutate as normal (AD-913); `crew_agent_participants(fake_runtime, thread.participants)` (from `routers.thread_fanout`) returns the crew set — confirming the thread is fan-out-ready while **no** fan-out auto-ran on create (no captain message exists). Also assert `handle_intent` returns `None` for a non-matching intent (`intent="something_else"`).

**Gate (focused, per repo convention):**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad918_agent_initiated_group_chat.py -q -n 0 -p no:cacheprovider
```
**Blast-radius gate:**
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat or fanout or intent or group" -q -p no:cacheprovider
```

---

## Loop-safety analysis (read before building)

**Create-storm:** bounded by the per-agent cooldown (60 s) + sliding-window cap (5/hour) on the long-lived `AgentGroupChatService._create_times` dict. Budget is consumed only on a passing gate, *after* the crew check, so non-crew rejections don't consume budget. Worst case for a single rogue agent: 5 rooms/hour, ≥60 s apart.

**Auto-reply storm:** structurally impossible in v1. (1) AD-918 wires **no** agent-to-agent auto-reply. (2) The created thread has **no Captain post**, and AD-914 `group_chat_fanout` only fires on `role=="captain"` — so creating a room never triggers a fan-out, hence never triggers any agent reply. (3) The optional first message is a **single persisted** `role=="agent"` row; it is **not** dispatched to other agents and does **not** satisfy the captain-gate, so it triggers no cascade. A reply loop could only begin if a *future* AD makes the Captain (or an agent) post into the room with the captain role — and that path is already bounded by the AD-915 facilitator (convergence + speaker cap). Not in v1 scope.

**AD-719a-2 lift / visibility risk:** lifting "agents seed without a Captain" creates rooms the Captain didn't start. (1) Discoverability is *intended*: `metadata.created_by_agent` tags them precisely so AD-919 can surface + Captain-join them — there is no hidden channel. (2) No cross-agent data leak: participants are only the explicit crew the creator names (resolved + crew-filtered); an agent cannot add the Captain (creator adds crew; the Captain joins via AD-919 `add_participant(captain)`), and cannot add non-crew. (3) The room is just a `ChatThread` — same persistence + visibility model as every other thread; nothing new is exposed beyond "a crew-created thread exists."

---

## What this does NOT change — Do NOT build

- **No agent-to-agent auto-reply loop.** AD-918 creates the room, adds participants, and optionally posts ONE first message. It does **not** dispatch that message to other agents or wire any reply cascade. (Future / facilitator-gated.)
- **No consensus gate.** `requires_consensus=False` is deliberate and justified (Safety Budget). Do not add a quorum/red-team path.
- **No UI.** The visibility surface + Join button is **AD-919** (wire the dormant LeftRail AD-719b). Touch no `ui/` files.
- **No meeting / voice / avatars.** Phase 2 (AD-920–923).
- **No live task-id auto-wiring.** `task_id` is an optional caller param; do not reach into `work_item_store` or the dispatch path to infer the current task. Document the seam only.
- **No decomposer / Captain-NL discovery.** Do not attach `CREATE_GROUP_CHAT_DESCRIPTOR` to a registered agent or modify the decomposer/PromptBuilder. The descriptor is a forward marker; the v1 mechanism is the directly-subscribed handler.
- **No Ward Room changes.** Do not touch `src/probos/ward_room/multi_agent.py`. The deferral is lifted on the **ChatThreadStore** substrate per the Captain ruling.
- **No new agent / pool.** The handler is a bare-callable subscriber; do not add to `_create_pools` or the registry.
- **No `append_message` / fan-out gate changes.** Do not alter `group_chat_fanout` or its `role=="captain"` trigger.

---

## Tracking

- **PROGRESS.md** — prepend an AD-918 block (mechanism, safety model, files, test count).
- **`docs/development/roadmap.md`** — flip the AD-918 row (line 368) to `SHIPPED <date> gate-verified` (the epic's AD-913→917 rows set this precedent).
- **DECISIONS.md** — one entry: AD-918 mechanism (intent + bare-callable handler + service), the `requires_consensus=False` justification (Safety Budget), and the v1/deferred line (task_id optional param; decomposer discovery + agent-to-agent reply deferred).
- One AD = one commit: `AD-918: agent-initiated group chats (create_group_chat intent)`. Do not push until the sweep completes.

---

## Acceptance criteria

1. `ChatThreadStore.create_thread` accepts optional `metadata` and persists it; existing callers unaffected (NULL/`{}` read-identical). All current `test_ad791*` / `test_ad79*` thread tests stay green.
2. `GroupChatConfig` gains the three rate-limit fields with the stated conservative defaults; zero-config boot unaffected.
3. `AgentGroupChatService.create_group_chat`: crew-only (non-crew → `not_crew`), creator auto-added, crew participants resolved by agent_id **and** callsign (non-crew dropped), `metadata.created_by_agent` persisted, optional `task_id` linked, optional single first message posted, cooldown + window-cap enforced (`rate_limited`), empty title rejected.
4. `handle_intent` is subscribed on the real `IntentBus` for `create_group_chat`, returns a populated `IntentResult` on success and `None` for non-matching intents; `requires_consensus=False` on the descriptor.
5. The created thread is a normal `ChatThread`: AD-913 `add_participant`/`remove_participant` and AD-914 `crew_agent_participants` operate on it; **no** fan-out auto-runs on create.
6. New `tests/test_ad918_agent_initiated_group_chat.py` with ≥14 tests (BF-287 real fixtures, no `MagicMock` at the store/bus boundary). Focused gate green; blast-radius gate (`-k "thread or chat or fanout or intent or group"`) green.
7. None of the **Do NOT build** items are touched (no UI, no Ward Room, no consensus gate, no new agent/pool, no fan-out changes, no live task-id wiring).
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```
git log --oneline -1
  dae090a5 (HEAD -> main) AD-917: UI group-chat experience      # highest committed AD = AD-917

src/probos/threads/__init__.py:184   def create_thread(self, *, title, participants, project_id=None, task_id=None, personality_override=None, workspace_root=None) -> ChatThread   # NO metadata param
src/probos/threads/__init__.py:48    task_id TEXT,                                  # chat_threads.task_id column (AD-791a)
src/probos/threads/__init__.py:110   metadata: dict = field(default_factory=dict)   # ChatThread.metadata field
src/probos/threads/__init__.py:550   "(... preprompt, model, metadata) ..." metadata={"is_default": True}   # INSERT-with-metadata precedent (create_default_for_agent)
src/probos/threads/__init__.py:1061  raw_meta = row["metadata"] if "metadata" in keys else None; metadata = json.loads(raw_meta) if raw_meta else {}   # NULL/"{}" both -> {}
src/probos/threads/__init__.py:1100  "metadata": "ALTER TABLE chat_threads ADD COLUMN metadata TEXT"   # column exists (_migrate_v2)
src/probos/threads/__init__.py:377   def add_participant(self, thread_id, agent_id) -> ChatThread | None     # AD-913
src/probos/threads/__init__.py:649   def append_message(self, thread_id, *, author_id, role, body, metadata=None)   # first-message post path
src/probos/config.py:3747            class GroupChatConfig(BaseModel)               # AD-915 — extend, do not create new
src/probos/config.py:5167            group_chat: GroupChatConfig = GroupChatConfig()   # mounted
src/probos/types.py:716              @dataclass class IntentDescriptor: name; params; description=""; requires_consensus=False; requires_reflect=False; tier="domain"
src/probos/types.py:50               class IntentMessage: intent; params; ...; target_agent_id=None; thread_id=None   # caller identity travels in params (AD-914 convention)
src/probos/mesh/intent.py:21         IntentHandler = Callable[[IntentMessage], Awaitable[IntentResult | None]]   # bare callable can subscribe
src/probos/mesh/intent.py:145        def subscribe(self, agent_id, handler, intent_names=None)
src/probos/mesh/intent.py:483        async def broadcast(...)  -> routes by self._intent_index.get(intent.intent)   # indexed handler only
src/probos/cognitive/yeoman.py:242   runtime.intent_bus.subscribe(self._proactive_sub_id, self._handle_proactive_scan, intent_names=["proactive_scan"])   # non-agent handler precedent
src/probos/agent_onboarding.py:151   intent_names = [d.name for d in getattr(agent, "intent_descriptors", [])]   # decomposer discovery needs a REGISTERED agent -> deferred
src/probos/crew_utils.py:21          def is_crew_agent(agent, ontology=None) -> bool   # ontology None -> legacy _WARD_ROOM_CREW set
src/probos/crew_profile.py:711       def resolve(self, callsign) -> {callsign, agent_type, agent_id, display_name, department} | None   # callsign -> agent_id
src/probos/cognitive/cognitive_agent.py:1097  work_item_id = params.get("work_item_id", "")   # task id reaches agent ONLY via intent params -> task_id optional in v1
src/probos/runtime.py:374            self.intent_bus = IntentBus(self.signal_manager)
src/probos/runtime.py:411-413        self.callsign_registry = CallsignRegistry(); load_from_profiles(); bind_registry(self.registry)
src/probos/runtime.py:450            self.chat_thread_store = ChatThreadStore(...)   # service instantiation + subscribe site
src/probos/runtime.py:790            self.ontology: VesselOntologyService | None = None   # set later (2211) -> read lazily
src/probos/routers/thread_fanout.py  group_chat_fanout fires on role=="captain" AND >=2 crew   # created chat has no captain post -> no auto-fan
tests/test_ad914_group_chat_fanout.py:1-40   BF-287 fixture template (real ChatThreadStore + real IntentBus(SignalManager) + _FakeAgent/_FakeRegistry, NOT MagicMock)
tests/test_ad918_agent_initiated_group_chat.py   does NOT exist (new file)
```
