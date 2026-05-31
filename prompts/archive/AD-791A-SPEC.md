# AD-791a (v5) — Wire the chat-threads substrate; threads as meeting envelopes for persistent agents

**Status:** v5 draft. v4 was BLOCKED on a layer-mislocation: I assumed there was a separate cognitive-layer DM intent handler that constructed `DmReplyContext` from a received `IntentMessage`. In reality the ROUTER itself (`agents.py:2089`) constructs `DmReplyContext` after getting the LLM response back via `intent_bus.send()`. v5 collapses Section 5.6 accordingly — `chat_thread_id` is passed directly as a kwarg at the construction site; no bus round-trip for the 1:1 path. v5 also augments BOTH AnchorFrame sites in `reply_pipeline.py` (action-dispatch at L658 + DM episode at L757), not just one. Conceptual frame from v2 preserved verbatim.
**Sequence:** Wave 193. AD number TBD — confirm against PROGRESS.md highest before Builder dispatch (current architect-review notes top = AD-826).
**Builds on:** AD-791 substrate (`probos.threads.ChatThreadStore`, `chat_threads` + `chat_thread_messages` tables, `/api/threads` CRUD, `naming.py`). The store is already wired into runtime at `runtime.py:444`. `/api/threads` already serves requests.
**Blocks:** AD-792 (sidebar UI), AD-793 (Projects), AD-794 (auto-naming consumption), AD-797 (Artifacts pane), AD-809 (per-thread personality consumption).
**Absorbs from:** `huggingface/chat-ui` (Apache 2.0) data shapes only.

---

## Section 0 — Conceptual frame: threads as meeting envelopes for persistent agents

This AD wires chat threads into ProbOS in a way that fundamentally differs from how `huggingface/chat-ui`, ChatGPT, Claude, LibreChat, LobeChat, and the broader assistant-thread industry model conversations. We absorb their data shapes; we explicitly reject their identity model.

**The industry model:** the agent is stateless across threads. A thread carries the agent's entire identity-relevant context — preprompt, model, message history. Outside the thread, the agent does not exist. New thread = fresh agent.

**ProbOS's model:** the agent is a persistent sovereign identity. Each agent has a birth certificate (BF-057), a tiered trust profile (AD-640), accumulated episodic memory of the Captain, Hebbian-learned routing affinities, and a callsign-bound persona. Across all threads with the Captain, Ezri is still Ezri. Worf still has his trust score. Their relationships with the Captain accumulate across every conversation.

A thread, in this model, is not the agent's whole memory. It's a **meeting envelope** — the setting and scope of one conversation. Like meeting with the same coworker on Monday, then again on Friday: separate meetings, same person, continuity of relationship.

Concrete implications that shape this AD:

| Concept | Industry model | ProbOS model | This AD's implementation |
|---|---|---|---|
| Agent identity across threads | Reset per thread | Persistent | Agents retain identity. Threads don't override it. |
| Episodic memory | Per-thread only (or absent) | Per-AGENT, global | Episodes are agent-scoped. New `chat_thread_id` field tags WHICH thread the episode came from, but recall queries are not thread-filtered by default. |
| Trust state | None / per-thread | Per-agent, persistent | AD-640 trust unaffected by threads. |
| `preprompt` field on thread | The agent's primary identity | Optional overlay on agent identity | `preprompt` augments the agent's birth-certificate instructions for this thread only; agent identity remains primary. |
| `model` field on thread | The model that powers this thread | Optional tier override for this thread | Defaults to the agent's natural routing tier; per-thread can pin (e.g. "use deep tier for this strategic session"). |
| Multi-agent thread | One assistant per thread | Multiple persistent agents, each with own relationship to Captain | Participants list holds agent IDs; each agent's individual relationship with Captain (trust, episodic recall) persists alongside the shared thread experience. |
| Cross-thread reference by agent | Impossible (stateless) | Natural ("we discussed X last week") | Through global episodic recall + the new `chat_thread_id` anchor, an agent CAN bring forward knowledge from prior threads when relevant. AD-791a does not implement cross-thread recall ranking; it lays the metadata so AD-810 `/insights` and future relevance scoring can use it. |
| Thread deletion | Wipes everything | Wipes the meeting log, not the relationship | DELETE cascades to `chat_thread_messages` only. Episodes survive (they're the agent's memory of the Captain, not of the thread). Trust survives. The agent keeps everything they learned. |

**Context assembly at turn-time** is the operational expression of this model. When an agent generates a reply within a thread:

```
[agent's birth-certificate instructions]           ← identity, never overridden
+ [agent's tiered-trust / personality from AD-640] ← persistent
+ [global episodic recall about the Captain]       ← persistent, cross-thread
+ [thread-scoped preprompt overlay, if any]        ← additive, this AD's column
+ [last N messages from THIS thread]               ← scoped, this AD's table
+ [project system context, if any]                 ← AD-793 (future)
+ [current user turn]
```

This AD adds two pieces to that pipeline: the thread message log (which already exists in the substrate) and the optional `preprompt` overlay column. Everything else is already in place. No cognitive-layer changes are needed because the agent's identity is sourced from where it already lives.

This framing is not just philosophical. It dictates the back-compat shim shape (the implicit-default-thread is a per-agent convention, not a per-Captain ownership model), the lack of cross-thread visibility for raw messages (privacy + token-budget), the no-cascade-to-episodes policy (already in v1 spec, now with the explicit "why"), and the multi-agent participant model.

---

## Section 1 — IntentMessage carries `thread_id` (Required #1 from architect review)

**Architect finding:** the spec was building on a phantom field. `IntentMessage` in `src/probos/types.py` (around line 50) defines `intent`, `params`, `urgency`, `context`, `ttl_seconds`, `id`, `created_at`, `target_agent_id` — no `thread_id`. The misleading docstring in `threads/__init__.py:18` (claiming the field exists "in activation/task_event.py") refers to `TaskEvent.thread_id`, which is a different type entirely.

**Resolution:** add `thread_id` as a real first-class field on `IntentMessage`, not buried in `params`.

```python
# src/probos/types.py — IntentMessage dataclass
@dataclass(frozen=True)
class IntentMessage:
    intent: str
    params: dict[str, Any]
    urgency: float = 0.5
    context: list[str] = field(default_factory=list)
    ttl_seconds: float = 30.0
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: float = field(default_factory=time.time)
    target_agent_id: str | None = None
    thread_id: str | None = None   # AD-791a: chat-thread provenance; None for non-chat dispatches
```

`thread_id` is `None` by default for backward compatibility. Existing consumers don't need to change. Chat-router emitters (Section 5) populate it.

**Also fix the misleading docstring** in `src/probos/threads/__init__.py` line 18-19 — it currently says "IntentMessage.thread_id already exists (activation/task_event.py)." Replace with: "AD-791a adds `IntentMessage.thread_id` so chat-routed intents carry conversation provenance; non-chat intents leave it None."

**Touchpoints:** `src/probos/types.py` (+1 line), `src/probos/threads/__init__.py` (docstring fix), no consumer changes required.

---

## Section 2 — `chat_thread_id` on Episode / AnchorFrame to avoid Ward Room namespace collision (Required #2)

**Architect finding:** `AnchorFrame.thread_id` already exists at `src/probos/types.py:389` with `# Ward Room thread ID for cross-reference` semantics. If we route chat-thread IDs into that field, we silently merge two distinct namespaces forever.

**Resolution:** add a new, separately-named field on `AnchorFrame` (and propagate to `Episode` via metadata if Episode doesn't carry AnchorFrame fields directly).

```python
# src/probos/types.py — AnchorFrame dataclass
@dataclass
class AnchorFrame:
    # ... existing fields ...
    thread_id: str = ""                # Ward Room thread ID — UNCHANGED, leave the comment.
    chat_thread_id: str = ""           # AD-791a: chat-thread provenance for episodes
                                       # originating from chat turns; "" for non-chat episodes
                                       # (proactive scans, dream consolidation, etc.).
```

**The comment block at the field site is the deliverable** — it documents the namespace separation so future contributors don't repeat the collision. Required architect Recommendation #2 lands here.

Episodic memory storage (`probos.cognitive.episodic_memory` or wherever `episode.store(...)` accepts AnchorFrame) does not need API changes; AnchorFrame just carries one more field through.

**Touchpoints:** `src/probos/types.py` (+1 field + comment block).

---

## Section 3 — Schema additions to `chat_threads` and `chat_thread_messages` (revised per Required #4)

Five additive nullable columns. All are absorbed from `huggingface/chat-ui` shape decisions. The schema can be extended further later (AD-791b FTS, AD-793 project linkage strengthening); these are what AD-791a lands.

### `chat_threads` adds three columns:

```sql
ALTER TABLE chat_threads ADD COLUMN preprompt TEXT;
ALTER TABLE chat_threads ADD COLUMN model TEXT;
ALTER TABLE chat_threads ADD COLUMN metadata TEXT;
```

- **`preprompt TEXT NULL`** — overlay system-prompt fragment. Per Section 0, this is additive to the agent's identity, not a replacement. Used at turn-time as part of context assembly; AD-791a stores the value, does not consume it. The consumer (AD-809 personality, AD-793 projects, or future thread-specific instructions) lands later.

- **`model TEXT NULL`** — per-thread LLM tier override. Permitted values: `"deep"`, `"fast"`, `"standard"`, `"vision"`, `"compute_use"`, or a specific model identifier. NULL = use the agent's natural routing tier. AD-791a stores the value; chat router consumption lands later (chat router currently picks tier via AD-463 cost-routing — AD-791a doesn't change that).

- **`metadata TEXT NULL`** — JSON blob for flexible per-thread tags. Replaces the architect's #4 question about `is_default` flags. Default-thread convention is captured in `metadata.is_default = true`; future tags (last-summarized timestamp, archive reason, etc.) land here without further migrations.

### `chat_thread_messages` adds four columns:

```sql
ALTER TABLE chat_thread_messages ADD COLUMN parent_message_id TEXT;
ALTER TABLE chat_thread_messages ADD COLUMN branch_ordinal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_thread_messages ADD COLUMN score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_thread_messages ADD COLUMN interrupted INTEGER NOT NULL DEFAULT 0;
```

- **`parent_message_id TEXT NULL`** — regenerate-as-sibling support (chat-ui's `ancestors[]`/`children[]` flattened). NULL on the linear default path. Indexed for `(thread_id, parent_message_id)`.

- **`branch_ordinal INTEGER DEFAULT 0`** — sibling ordinal under same parent. 0 = canonical reply.

- **`score INTEGER DEFAULT 0`** — three-valued: -1 / 0 / 1 (chat-ui's `Message.score`). Operator thumbs feedback; consumer lands with AD-792 sidebar UI.

- **`interrupted INTEGER DEFAULT 0`** — boolean: LLM stream was cancelled mid-token. Currently no consumer; reserves the column slot.

### Index additions:

```sql
CREATE INDEX IF NOT EXISTS idx_messages_branch ON chat_thread_messages (thread_id, parent_message_id);
```

`CREATE INDEX IF NOT EXISTS` is valid SQLite syntax; the `ADD COLUMN` calls below are not idempotent and need the PRAGMA pattern (Section 4).

**No data migration of existing rows.** Both tables are empty in practice (zero consumers wrote to them), but the migration must not assume that.

---

## Section 4 — Schema migration: `PRAGMA table_info` pattern (Required #5)

**Architect finding:** SQLite does not support `ADD COLUMN IF NOT EXISTS` in any version. The v1 spec hedged this; v2 mandates the documented pattern.

**Reference:** `src/probos/substrate/event_log.py` lines 86-124 — uses `aiosqlite` async. `probos.threads.ChatThreadStore` uses sync `sqlite3`. The translation pattern:

```python
# In probos.threads.__init__ — new helper called from ChatThreadStore.__init__()
# after the initial _SCHEMA execute block.
def _migrate_v2(conn: sqlite3.Connection) -> None:
    """AD-791a: idempotently add v2 columns to chat_threads / chat_thread_messages."""
    threads_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_threads)")}
    messages_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_thread_messages)")}

    threads_additions = {
        "preprompt": "ALTER TABLE chat_threads ADD COLUMN preprompt TEXT",
        "model":     "ALTER TABLE chat_threads ADD COLUMN model TEXT",
        "metadata":  "ALTER TABLE chat_threads ADD COLUMN metadata TEXT",
    }
    for col, ddl in threads_additions.items():
        if col not in threads_cols:
            conn.execute(ddl)

    messages_additions = {
        "parent_message_id": "ALTER TABLE chat_thread_messages ADD COLUMN parent_message_id TEXT",
        "branch_ordinal":    "ALTER TABLE chat_thread_messages ADD COLUMN branch_ordinal INTEGER NOT NULL DEFAULT 0",
        "score":             "ALTER TABLE chat_thread_messages ADD COLUMN score INTEGER NOT NULL DEFAULT 0",
        "interrupted":       "ALTER TABLE chat_thread_messages ADD COLUMN interrupted INTEGER NOT NULL DEFAULT 0",
    }
    for col, ddl in messages_additions.items():
        if col not in messages_cols:
            conn.execute(ddl)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_branch "
        "ON chat_thread_messages (thread_id, parent_message_id)"
    )
    conn.commit()
```

Called from `ChatThreadStore.__init__()` after the existing `_SCHEMA` execute. Idempotent across reboots and across fresh data dirs.

**Test:** `test_alter_table_idempotent` — open an empty DB twice, verify all columns present, no errors.

---

## Section 5 — Back-compat shim for `/api/agent/{id}/chat` (Required #3, #4, #7, #8 collectively)

The core deliverable. Connects chat turns to threads without breaking any existing client.

### 5.1 Define "default thread" by convention (no `captain_id`, no `is_default` column)

Architect finding (#4): there's no stable Captain identity in the codebase. `config.captain_callsign` is the closest thing — a configurable string, default `"Captain"`. The Captain is implicit in every chat turn; there's only ever one Captain per ProbOS instance in the current architecture.

**Resolution:** the implicit default thread for an agent is defined by:

```
The chat_threads row with:
  participants = [agent_id]           (exactly one participant, the agent — Captain is implicit)
  archived = 0
  project_id IS NULL
  metadata.is_default = true OR title = <agent_callsign>
ORDER BY created_at ASC
LIMIT 1.
```

`participants` excludes the Captain. Captain is the implicit other side of every 1:1 thread. This matches Section 0's "thread is a meeting envelope" framing — the agent is the participant, the Captain is the implicit operator. If/when multi-Captain lands (future), the model is extended to `participants = [agent_id]` + a new `operator_card_id` field.

### 5.2 New store method: `find_default_for_agent`

```python
# probos.threads.ChatThreadStore
def find_default_for_agent(self, agent_id: str) -> ChatThread | None:
    """Find the implicit default 1:1 thread for an agent.

    A default thread is the oldest non-archived, non-project-bound row whose
    sole participant is the given agent_id. Returns None if no such thread
    exists; caller is responsible for creating one (see ``create_default_for_agent``).
    """
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_threads "
            "WHERE participants = ? AND archived = 0 AND project_id IS NULL "
            "ORDER BY created_at ASC LIMIT 1",
            (json.dumps([agent_id]),),
        ).fetchall()
        return self._row_to_thread(rows[0]) if rows else None

def create_default_for_agent(self, agent_id: str, agent_callsign: str) -> ChatThread:
    """Create the default 1:1 thread for an agent with metadata.is_default=True."""
    now = time.time()
    thread = ChatThread(
        id=str(uuid.uuid4()),
        title=agent_callsign,                # "Ezri", "Worf", etc.
        participants=[agent_id],
        created_at=now,
        last_active_at=now,
        project_id=None,
        task_id=None,
        pinned=False,
        archived=False,
        personality_override=None,
        workspace_root=None,
    )
    metadata = json.dumps({"is_default": True})
    with self._connect() as conn:
        # _connect() opens autocommit; explicit conn.commit() below is a no-op but documents intent.
        conn.execute(
            "INSERT INTO chat_threads "
            "(id, title, participants, project_id, task_id, pinned, archived, "
            " personality_override, workspace_root, created_at, last_active_at, "
            " preprompt, model, metadata) "
            "VALUES (?, ?, ?, NULL, NULL, 0, 0, NULL, NULL, ?, ?, NULL, NULL, ?)",
            (thread.id, thread.title, json.dumps(thread.participants),
             thread.created_at, thread.last_active_at, metadata),
        )
        conn.commit()
    return thread
```

### 5.3 Concurrent-creation race — `BEGIN IMMEDIATE` (Recommended #4 from architect)

Two concurrent first-turn requests for the same agent could both pass `find_default_for_agent → None` then both `create_default_for_agent`. Wrap the lookup-then-insert in a single transaction:

```python
def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> ChatThread:
    """Atomic: find existing default thread, or create one. Safe under concurrent first-turn."""
    with self._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "SELECT * FROM chat_threads "
                "WHERE participants = ? AND archived = 0 AND project_id IS NULL "
                "ORDER BY created_at ASC LIMIT 1",
                (json.dumps([agent_id]),),
            ).fetchall()
            if rows:
                conn.commit()
                return self._row_to_thread(rows[0])
            # Insert path
            thread = self._build_default(agent_id, agent_callsign)
            conn.execute("INSERT INTO chat_threads ...", (...))
            conn.commit()
            return thread
        except Exception:
            conn.rollback()
            raise
```

`BEGIN IMMEDIATE` acquires a RESERVED lock so a second concurrent `BEGIN IMMEDIATE` waits, then on retry will find the row inserted by the first transaction. SQLite handles this correctly under the default `_connect()` settings.

**Test:** `test_concurrent_first_turn_creates_one_thread` — two concurrent `get_or_create_default_for_agent` calls under same agent_id; assert exactly one row in `chat_threads` post.

### 5.4 Chat router integration

**The primary 1:1 endpoint is `routers/agents.py::agent_chat` at line 1660, NOT `routers/chat.py`.** `ProfileChatTab` (the UI surface the Captain has been testing voice in) hits `/api/agent/{id}/chat`, which is served from `agents.py`. `routers/chat.py` serves `/api/chat` (the main-chat multi-agent fan-out surface) and `chat.py`'s line-270-295 inline-callsign branch is a parser inside that handler, not a separate endpoint.

**Critical layering correction (v4):** the 1:1 chat-turn episodic write does NOT happen in `agents.py::agent_chat`. The router dispatches an `IntentMessage` and returns. The actual `AnchorFrame` + `Episode` build + `episodic_memory.store(...)` happens in the cognitive layer at `cognitive/dm/reply_pipeline.py:758-764` after the receiving agent processes the intent. This means `chat_thread_id` flows: **router writes `IntentMessage.thread_id` (Section 1) → receiving agent's direct_message handler reads `intent.thread_id` and sets `DmReplyContext.chat_thread_id` (Section 5.6) → `reply_pipeline.py` builds the AnchorFrame with `chat_thread_id=ctx.chat_thread_id` (Section 5.6)**.

There are FOUR paths that touch chat turns + episodic memory:

| Path | Location | Thread wiring | Episodic write | Notes |
|---|---|---|---|---|
| **1:1 DM endpoint** — the primary target | `routers/agents.py::agent_chat` (line 1660) | **YES** — via `get_or_create_default_for_agent`; populate `IntentMessage.thread_id`; append captain + agent messages | NO inline AnchorFrame build in router; the cognitive-layer write at `reply_pipeline.py:758` carries the `chat_thread_id` through `DmReplyContext` (Section 5.6) | What `ProfileChatTab.tsx` hits. Single agent. Default thread mapping. |
| Vision-routed (1:1 + vision) | `routers/chat.py` line ~429 | YES — same default-thread mapping | YES — augment `AnchorFrame.chat_thread_id` at the existing inline-build site at ~line 416 (`AnchorFrame(channel="captain_chat", trigger_type="vision_attachment", ...)`) | Same agent context as 1:1; routed through `/chat` because the request carries an image. This is the ONE place the router builds AnchorFrame inline. |
| Inline `@callsign` DM branch | `routers/chat.py` lines ~270-295 | YES — same default-thread mapping for parity (populate `IntentMessage.thread_id` on dispatch) | NO change — still no episode write today; this AD does NOT close that gap (preserves current behavior). When the receiving agent processes the intent, the `reply_pipeline.py` site DOES write an episode with `chat_thread_id` populated via Section 5.6's wiring. | Inline-mention parser inside `/chat`; behavioral parity with 1:1 |
| AD-719 multi-agent fan-out | `routers/chat.py` line ~247 | **DEFERRED to AD-791g (new forward marker)** | NO change in this AD | Architect Required #7 (v1): main-chat thread modeling has write-skew and semantic questions deserving its own AD |

`/api/agent/{agent_id}/chat` is the endpoint AD-791a wires fully. `/api/chat` (the main-chat surface) keeps current behavior; episodes from that path write `chat_thread_id=""`.

`/api/agent/{agent_id}/chat` is the endpoint AD-791a wires fully — served from `routers/agents.py`. `/api/chat` (the main-chat surface, served from `routers/chat.py`) keeps current behavior; the inline-callsign branch gets thread wiring for parity, the fan-out branch is deferred.

### 5.5 Per-turn flow (1:1 DM endpoint — `routers/agents.py::agent_chat`)

The handler at line 1660 has substantial pre-existing logic (AD-743 pacing cancel, AD-725 targeted lookup, AD-730 vision pipe-through, BF-289 empty-response distinguishing, AD-726 post-LLM cleanup pipeline). The snippet below shows only the NEW wiring inline; Builder MUST preserve all existing branches. Insert `get_or_create_default_for_agent` immediately after the `agent = runtime.registry.get(agent_id)` lookup. Insert the captain-side `store.append_message` before the intent build. Insert the agent-side `store.append_message` after the final `response_text` is computed in the existing handler (around line ~2065, after AD-726 cleanup). Augment the dict return.

**No AnchorFrame is built here. No `episodic_memory.store(...)` is called here.** The episodic write happens downstream in `cognitive/dm/reply_pipeline.py:758-764` (Section 5.6).

```python
# routers/agents.py — agent_chat handler, NEW wiring only (existing branches preserved)
async def agent_chat(agent_id: str, req: AgentChatRequest, ...) -> dict[str, Any]:
    # EXISTING: agent lookup
    agent = runtime.registry.get(agent_id)                # NOT get_by_id (v2->v3 phantom correction)
    if agent is None:
        raise HTTPException(404, "Agent not found")

    # NEW: resolve or create the implicit default thread for this agent
    store = runtime.chat_thread_store
    callsign = getattr(agent, "callsign", None) or agent_id
    thread = store.get_or_create_default_for_agent(agent_id, callsign)

    # NEW: optional explicit thread_id override (forward-compatible with AD-792)
    if getattr(req, "thread_id", None):
        explicit = store.get_thread(req.thread_id)
        if not explicit or agent_id not in explicit.participants:
            raise HTTPException(400, "Invalid thread_id for this agent")
        thread = explicit

    # NEW: append Captain's message
    store.append_message(
        thread_id=thread.id,
        author_id="captain",
        role="captain",
        body=req.message,
        metadata={},
    )

    # EXISTING (modified): IntentMessage now carries thread_id (Section 1)
    # Builder: preserve every existing IntentMessage construction site in this handler;
    # add thread_id=thread.id to each. Do not collapse branches.
    intent = IntentMessage(
        intent="direct_message",                          # actual intent name in this handler
        params={...},                                     # existing params shape
        target_agent_id=agent_id,
        thread_id=thread.id,                              # NEW (Section 1)
    )
    result: IntentResult = await runtime.intent_bus.send(intent)

    # EXISTING: response_text extracted via existing logic (AD-726 cleanup, etc.)
    # The variable name in the real handler may differ; this is the post-extraction string.
    response_text = ...  # whatever the existing handler computes by line ~2065

    # NEW: append agent's reply
    store.append_message(
        thread_id=thread.id,
        author_id=agent_id,
        role="agent",
        body=response_text,
        metadata={"intent_id": intent.id},
    )

    # AUGMENTED: dict return adds thread_id key; existing keys preserved
    return {
        "response": response_text,
        "thread_id": thread.id,                           # NEW
        # ... existing keys preserved ...
    }
```

### 5.6 Cognitive-layer wiring of `chat_thread_id` (v5 layer-precise correction)

The 1:1 chat-turn `DmReplyPipeline` is constructed BY THE ROUTER at `routers/agents.py:2089`. The bus is used for the LLM round-trip; the `DmReplyContext` is then built in the same function with `thread` already in scope. There is no separate cognitive-layer intent handler that constructs `DmReplyContext` from a received `IntentMessage`. So the `chat_thread_id` wire is simpler than v4 described:

**Three small changes:**

**(a) Add `chat_thread_id` field to `DmReplyContext`** (dataclass at `cognitive/dm/reply_pipeline.py:31`):

```python
@dataclass
class DmReplyContext:
    # ... existing fields preserved ...
    chat_thread_id: str = ""   # AD-791a: chat-thread provenance, passed by the
                               # router at construction time. Default "" makes
                               # all existing test fixtures (7+ sites) continue
                               # to pass without modification.
```

**(b) Pass `chat_thread_id=thread.id` at the DmReplyContext construction site** (`routers/agents.py:2089`). The real `DmReplyContext` fields are `req_message` (NOT `request_message`) and `response_text` — verify field names with `grep -n 'class DmReplyContext\|^\s*[a-z_]*:.*=' src/probos/cognitive/dm/reply_pipeline.py` before edit:

```python
# routers/agents.py around line 2089 — add ONE kwarg, preserve all existing kwargs
pipeline = DmReplyPipeline(DmReplyContext(
    runtime=runtime,
    agent=agent,
    agent_id=agent_id,
    callsign=callsign,
    req_message=req.message,                 # existing kwarg — actual field name, not request_message
    response_text=response_text,             # existing kwarg
    chat_thread_id=thread.id,                # NEW — thread is already in scope here
    # ... other existing kwargs preserved ...
))
```

**(c) Augment BOTH `AnchorFrame` sites in `reply_pipeline.py` with `chat_thread_id=self.ctx.chat_thread_id`:**

There are TWO `AnchorFrame(` sites in `reply_pipeline.py`, not one. Both fire during a 1:1 chat turn through `DmReplyPipeline.run()`. Augmenting only one would leak chat-thread provenance from one episode while leaving the other (same chat turn, same Captain, same agent) untagged — the same provenance-leak class the namespace separation (Section 2) was designed to prevent.

- **L658** — `AnchorFrame(channel="action", trigger_type="agent_action_executed", ...)` (AD-745 action-dispatch episode):

  ```python
  anchors=AnchorFrame(
      channel="action",
      trigger_type="agent_action_executed",
      # ... existing fields preserved ...
      chat_thread_id=self.ctx.chat_thread_id,   # NEW (Section 2)
  ),
  ```

- **L757** — `AnchorFrame(channel="dm", trigger_type="direct_message", ...)` (AD-430b 1:1 HXI episode):

  ```python
  anchors=AnchorFrame(
      channel="dm",
      trigger_type="direct_message",
      trigger_agent="captain",
      participants=["captain", self.ctx.callsign or self.ctx.agent_id],
      chat_thread_id=self.ctx.chat_thread_id,   # NEW (Section 2)
  ),
  ```

**Layer discipline:** the router imports `DmReplyContext` from `cognitive/dm/reply_pipeline.py` (already does today; see existing imports in `agents.py`). `DmReplyContext` is a value-typed dataclass in the cognitive layer; the router constructs it but does not call into the pipeline's internals beyond `pipeline.run()`. No upward imports. The new `chat_thread_id` field is a string — opaque to the cognitive layer, sourced from the router's `thread.id`, threaded into the AnchorFrame at write time.

**`IntentMessage.thread_id` (Section 1) is still architecturally correct — it's NOT the wire for the 1:1 episode (router holds `thread` in scope and passes directly to `DmReplyContext`), but it IS used by:**

- The inline-callsign branch in `chat.py:282` which dispatches `IntentMessage(intent="direct_message", ...)` through the bus. If/when a future AD wires inline-callsign episode writes, `IntentMessage.thread_id` is already there to consume.
- Future federation work (intent crosses peer boundaries).
- Any future cognitive-side consumer that needs chat-thread provenance from an intent without router context.

Leave the field in. Document it as the provenance contract for bus-mediated chat dispatches.

---

## Section 6 — UI store wiring (additive, no breaking change) [unchanged from v1]

(Same as v1: keep `agentConversations`; add `chatThreads: Map<thread_id, ChatThreadView>`, `threadIdByAgent: Map<agent_id, thread_id>`, `activeThreadId`. Round-trip the `thread_id` field from response back to next request. No visible UI change.)

---

## Section 7 — Runtime wiring is a no-op (Required #6)

`runtime.py:444` already imports and initializes `ChatThreadStore`. Verify via grep before commit:

```
grep "chat_thread_store" src/probos/runtime.py
```

Expected: one site at line ~444 wiring `self.chat_thread_store = ChatThreadStore(self._data_dir / "chat_threads.db")`. **No action needed.** If the line is missing or different (the architect verified it as present at 2026-05-25), add the wiring in-place; do not "rewire" otherwise.

---

## Section 8 — API response shape (dict augmentation, no new Pydantic model)

**v2 introduced a new `AgentChatResponse` Pydantic model; v3 drops it.** The existing handler at `routers/agents.py:1660` returns `dict[str, Any]`. Following adjacent endpoints in `agents.py`, v3 simply adds a `"thread_id": thread.id` key to the dict and adds the optional `thread_id` field to the existing `AgentChatRequest` Pydantic model.

```python
# src/probos/api_models.py — AgentChatRequest gets optional thread_id field
class AgentChatRequest(BaseModel):
    message: str
    # ... existing fields preserved ...
    thread_id: str | None = None   # AD-791a: optional explicit thread override
```

The response stays a plain dict (`{"response": ..., "thread_id": ..., ...existing keys}`); existing clients that ignore the extra key continue to work.

For `routers/chat.py` (the inline-callsign and vision paths), the existing `ChatResponse` Pydantic model at `api_models.py:34` gains:

```python
class ChatResponse(BaseModel):
    # ... existing fields ...
    thread_id: str | None = None   # AD-791a: thread provenance; NULL for /api/chat fan-out (until AD-791g)
```

`ChatResponse` is not configured with `extra="forbid"`, so adding a new optional field is non-breaking for any consumer that uses `model_validate`. Spot-check `ui/src/CompactApp.tsx` and the existing `tests/test_distribution.py` ChatResponse tests during Builder pre-flight to confirm.

---

## Section 9 — Tests (12 total)

### Python (10):

1. `test_alter_table_idempotent` — open empty + already-migrated DBs, both succeed.
2. `test_get_or_create_default_creates_one_thread` — first call creates, second call returns same thread.
3. `test_concurrent_first_turn_creates_one_thread` — two concurrent `get_or_create_default_for_agent` calls under same agent_id; assert exactly one row in `chat_threads`.
4. `test_chat_endpoint_creates_default_thread` — POST `/api/agent/{id}/chat` once; assert one row in `chat_threads` with the right participants and Captain's + agent's messages in `chat_thread_messages`.
5. `test_chat_endpoint_reuses_default_thread` — POST twice; assert exactly one thread, two pairs of messages.
6. `test_explicit_thread_id_routes_correctly` — POST with `thread_id=<existing>`; assert message lands in that thread.
7. `test_invalid_thread_id_400s` — POST with bogus or wrong-agent thread_id; expect 400.
8. `test_episodic_write_carries_chat_thread_id` — POST a turn; assert the latest episode's AnchorFrame has `chat_thread_id` matching the thread, NOT in the existing `thread_id` Ward-Room field.
9. `test_thread_delete_preserves_episodes` — Create thread, write turn, DELETE thread, assert episode still exists with `chat_thread_id` populated (now orphan-reference, but present).
10. `test_intent_message_carries_thread_id` — Mock IntentBus capture; POST a turn; assert dispatched IntentMessage has `thread_id` populated, `target_agent_id` set, and the Ward-Room namespace field is untouched.

### Vitest (2):

11. `ProfileChatTab.threadId.test.tsx` — Mock response with `thread_id`; assert it lands in `threadIdByAgent` and is sent back on next request.
12. `useStore.chatThreads.test.ts` — Hydrate from `/api/threads`; assert `chatThreads` map populated; assert no regression to `agentConversations` selector usage in mounted components.

### Recommended deferred (but documented for AD-792 or AD-791b):

- `test_concurrent_reader_during_write` — WAL mode contract (architect Recommended #6). Leave a `# TODO AD-791b` next to ChatThreadStore's `_connect()` referencing `PRAGMA journal_mode=WAL` enablement.

---

## Section 10 — Non-goals (Do NOT build)

- ❌ AD-792 sidebar UI rendering
- ❌ AD-793 Projects table or system-context injection
- ❌ AD-794 LLM-driven thread auto-naming (substrate at `naming.py` is untouched in this AD)
- ❌ AD-797 Artifacts extraction
- ❌ AD-809 personality override CONSUMPTION (preprompt column lands; the slash command + lookup is later)
- ❌ AD-791b FTS5 search (forward marker preserved)
- ❌ AD-791c archival lifecycle (forward marker preserved)
- ❌ AD-791g main-chat thread modeling (`/api/chat` fan-out + main-chat thread shape) — **NEW forward marker; covers the deferred Required #7**
- ❌ Closing the legacy-single-mention-DM episode write gap (preserves current behavior)
- ❌ Cognitive-mesh / substrate / consensus / mesh changes
- ❌ Changing the existing `AnchorFrame.thread_id` Ward Room field's name or semantics

---

## Section 11 — Acceptance criteria

1. `IntentMessage` has new `thread_id: str | None = None` field. Existing dispatchers compile and run unchanged.
2. `AnchorFrame` has new `chat_thread_id: str = ""` field, distinct from existing `thread_id` Ward-Room field. Comment block at the field site documents the namespace separation.
3. `chat_threads` table has new `preprompt`, `model`, `metadata` columns after first boot following this commit.
4. `chat_thread_messages` table has new `parent_message_id`, `branch_ordinal`, `score`, `interrupted` columns.
5. `/api/agent/{id}/chat` responses include `thread_id` field. Body unchanged for clients that ignore the field.
6. After two chat turns with the same agent on the same endpoint, `/api/threads` returns one thread with that agent in participants and four messages in `chat_thread_messages` (two captain, two agent).
7. Episodes written from a 1:1 chat turn (via `cognitive/dm/reply_pipeline.py`) have `AnchorFrame.chat_thread_id` populated. This applies to BOTH the L658 action-dispatch AnchorFrame and the L757 DM AnchorFrame — either both populated or neither (test asserts both). The Ward-Room `AnchorFrame.thread_id` field is untouched. `DmReplyContext.chat_thread_id` carries the value from the router's `thread.id` at construction time (`routers/agents.py:2089`).
8. IntentMessage objects dispatched from `/api/agent/{id}/chat` carry `thread_id`. IntentMessages from non-chat origins carry `thread_id=None`.
9. UI's `agentConversations` map and existing chat UX are bit-for-bit unchanged from operator perspective.
10. 12 new tests added (10 pytest + 2 vitest). All existing tests still pass.
11. `npm run build` clean. `pytest -n auto` no new failures vs main.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 12 — File touchpoints (anticipated)

| File | Change |
|---|---|
| `src/probos/types.py` | Add `IntentMessage.thread_id: str \| None = None` (Section 1). Add `AnchorFrame.chat_thread_id: str = ""` with namespace-separation comment (Section 2). |
| `src/probos/threads/__init__.py` | Add `_migrate_v2()` helper (Section 4). Add `find_default_for_agent`, `create_default_for_agent`, `get_or_create_default_for_agent` methods. (`append_message` already exists — verified at threads/__init__.py:274.) Fix misleading docstring at L18-L19 (Section 1 closeout). |
| `src/probos/cognitive/dm/reply_pipeline.py` | **(v5 layer-precise correction)** Exactly two changes: (1) Add `DmReplyContext.chat_thread_id: str = ""` field at L31. (2) Augment BOTH `AnchorFrame(...)` sites: L658 (action-dispatch episode) and L757 (DM episode) with `chat_thread_id=self.ctx.chat_thread_id`. Existing test fixtures using `DmReplyContext` (7+ sites in tests/) do NOT need updates — the field defaults to `""`. |
| `src/probos/routers/agents.py` | **PRIMARY 1:1 wiring target (line 1660 `agent_chat` handler).** Wire `get_or_create_default_for_agent`; populate `IntentMessage.thread_id` on the existing `IntentMessage(intent="direct_message", ...)` construction (around L2005); append captain + agent messages to `chat_thread_messages`; **pass `chat_thread_id=thread.id` at the `DmReplyContext(...)` construction (around L2089)**. Augment dict return with `thread_id` key. Accept optional `req.thread_id`. **No AnchorFrame work in this file.** |
| `src/probos/routers/chat.py` | Wire `get_or_create_default_for_agent` for the inline-callsign branch (~L281) and the vision-routed branch (~L424), both for behavioral parity with 1:1. Populate `IntentMessage.thread_id` on dispatched intents AT THOSE TWO SITES. Augment the inline AnchorFrame at the vision-path episodic write (~line 424, `AnchorFrame(channel="captain_chat", trigger_type="vision_attachment", ...)`) with `chat_thread_id`. The inline-callsign branch keeps its current no-episode-write behavior. **`/api/chat` fan-out path (L177 IntentMessage + L242 AnchorFrame) UNCHANGED — AD-791g territory; do NOT touch.** |
| `src/probos/api_models.py` | Add optional `thread_id: str \| None = None` to `AgentChatRequest` (request) and `ChatResponse` (response). No new Pydantic model. |
| `src/probos/runtime.py` | **No changes expected.** Verify the existing `chat_thread_store` init at line 444 (Section 7). |
| `ui/src/store/useStore.ts` | Add `chatThreads`, `threadIdByAgent`, `activeThreadId` slices. Add `setChatThread`, `setThreadForAgent`, `setActiveThread` actions. |
| `ui/src/components/profile/ProfileChatTab.tsx` | On successful chat response, store `response.thread_id` via `setThreadForAgent(agentId, thread_id)`; on subsequent request, send `thread_id` back from the ref. **No visual change.** |
| `ui/src/CompactApp.tsx` | Mirror: store thread_id from main-chat (`/api/chat`) responses (will be NULL until AD-791g for fan-out; populated for inline-callsign and vision). |
| `tests/test_threads.py` | New tests #1, #2, #3, #11 round-trip pieces. |
| `tests/test_distribution.py` | New tests #4-10 for the API contract. |
| `tests/test_dm_reply_pipeline.py` (or wherever DmReplyPipeline tests live — Builder greps) | New test for `chat_thread_id` propagation from `DmReplyContext` into the written episode's `AnchorFrame`. Counts as one of the Python tests (likely splits test #8 into #8a router-side + #8b cognitive-side). |
| `ui/src/__tests__/ProfileChatTab.threadId.test.tsx` | New vitest #11. |
| `ui/src/__tests__/useStore.chatThreads.test.ts` | New vitest #12. |

---

## Section 13 — Estimated scope

~300-400 LOC net diff (modest growth vs v1 estimate due to v2's clearer migration helper, race-safe shim, and namespace fixes). ~14 small files touched. One commit at completion. **Single Builder dispatch.**

---

## Section 14 — Forward markers (carried + new)

- **AD-791b** — FTS5 search over `chat_thread_messages.body`. Spec: virtual table `chat_thread_messages_fts(thread_id, body)` indexed on insert. Also lands `PRAGMA journal_mode=WAL` on the threads DB and the concurrent-reader test (Recommended architect #6).
- **AD-791c** — archival lifecycle policy. Cron sweep auto-archives threads inactive >N days, prunes archived >Y days.
- **AD-791d** — regenerate-as-sibling UI affordance. Schema landed in AD-791a; consumer UI lands with AD-792.
- **AD-791e** — thumbs up/down UI. Schema column landed; consumer UI lands with AD-792.
- **AD-791g (NEW per architect Required #7 resolution)** — main-chat (`/api/chat`) thread modeling. Resolve the fan-out write-skew + fixed-vs-dynamic membership question for the multi-agent thread on the main chat surface.

---

## Section 15 — Verify-first audit checklist (Builder pre-flight)

Builder must confirm before writing code:

```
grep "thread_id" src/probos/types.py
    → Expected: line 389 (AnchorFrame.thread_id, Ward Room) only — AD-791a adds two new fields.

grep "class IntentMessage" src/probos/types.py
    → Expected: confirms current fields; AD-791a adds thread_id.

grep "chat_thread_store" src/probos/runtime.py
    → Expected: one initialization site at ~line 444.

grep "find_default_for_agent\|get_or_create_default" src/probos/threads/__init__.py
    → Expected: no matches (AD-791a adds them).

grep "def append_message" src/probos/threads/__init__.py
    → Expected: line ~274 (already exists; do NOT re-add).

grep "PRAGMA table_info" src/probos/substrate/event_log.py
    → Expected: reference pattern present (translate aiosqlite → sync sqlite3).

grep "def get(" src/probos/substrate/registry.py
    → Expected: `def get(self, agent_id: AgentID) -> BaseAgent | None`. NOT `get_by_id`.

grep -n "async def agent_chat" src/probos/routers/agents.py
    → Expected: line ~1660 — the actual 1:1 endpoint. THIS is where router-side wiring goes.
    → Builder MUST re-anchor line numbers at build start; cite line 1660 only as orientation.

grep -n "AnchorFrame(\|episodic_memory.store" src/probos/cognitive/dm/reply_pipeline.py
    → Expected: AnchorFrame() at ~line 758, `await self.ctx.runtime.episodic_memory.store(episode)` at ~line 764.
    → THIS is where 1:1 chat-turn episode is written. Augment AnchorFrame here with chat_thread_id.

grep -rn "DmReplyContext(" src/probos
    → Expected: a small number of construction sites in the cognitive layer (likely the agent's direct_message intent handler).
    → Each site reads the dispatching intent and threads `chat_thread_id=intent.thread_id or ""` into the ctx.

grep "class DmReplyContext" src/probos/cognitive/dm/reply_pipeline.py
    → Expected: dataclass at line ~31 with params + message_text but NO thread_id field. AD-791a adds it.

grep "AnchorFrame(" src/probos/routers/chat.py
    → Expected: hit at ~line 416 in the vision-routed branch (`channel="captain_chat", trigger_type="vision_attachment"`). Augment with chat_thread_id.

grep "anchors=\|anchor=" src/probos/routers/agents.py src/probos/cognitive/dm/reply_pipeline.py
    → Expected: existing call-sites use `anchors=` (plural). AD-791a follows that convention.

grep "result.result\|result.text" src/probos/routers/agents.py src/probos/routers/chat.py
    → Expected: existing call-sites use `result.result`. AD-791a follows that convention.

read src/probos/routers/chat.py around lines 247, 270-295, 429
    → Confirm episodic write call sites for the inline-callsign, vision, and fan-out paths.

read src/probos/routers/agents.py around line 1660 (handler entry) and where response_text is finalized (~2065)
    → Confirm 1:1 handler shape; identify the post-AD-726 cleanup point where the agent-side append_message should land.

read ui/src/store/useStore.ts L264-L984
    → Confirm `agentConversations` selectors will not break under additive-store changes.
```

If any of these don't match, stop and report — the spec needs another revision.
