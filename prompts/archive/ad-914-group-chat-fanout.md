# AD-914 — Group-chat fan-out + cross-agent visibility

**One-line:** When the Captain posts to a `ChatThreadStore` thread with **≥2 crew-agent participants**, fan the turn out to all agent participants in parallel, inject the recent thread history into each agent's prompt (so they see each other), and persist each reply as a `chat_thread_messages` row (`role="agent"`). The `ChatThreadStore` form of the dormant `AD-719a-wire` forward marker.

**Status:** Ready to build
**Target repo:** OSS (`d:\ProbOS`)
**Dependencies:** AD-913 (participant management — `add_participant`/`remove_participant` + `POST/DELETE /api/threads/{id}/participants`). AD-913 is shipped but **uncommitted** in the working tree (`M src/probos/threads/__init__.py`, `M src/probos/routers/threads.py`, `?? tests/test_ad913_participant_management.py`).
**Highest committed AD:** **AD-912** (`6285edca`). AD-913 shipped-uncommitted. **AD-914 is the next number.**
**Estimated tests:** ≥12 new in `tests/test_ad914_group_chat_fanout.py`.

---

## Problem

`ChatThreadStore` (AD-791) makes threads first-class with a participant list, and AD-913 lets the Captain add/remove participants. But a multi-participant thread today is **N parallel blind 1:1s**: there is no fan-out — the only reply path is the 1:1 `agent_chat` endpoint (`POST /api/agent/{id}/chat`, [routers/agents.py](../src/probos/routers/agents.py#L1664)), which targets a single agent and injects only the **client-supplied** `req.history`. Two agents in the same thread never see each other.

The transient @-mention fan-out already exists for the **main chat box** (AD-719, [routers/chat.py](../src/probos/routers/chat.py#L140-L264)) but it (a) resolves **callsigns**, not participant `agent_id`s, (b) passes `session_history: []` (blind — agents do not see each other), and (c) does **not** persist to `ChatThreadStore`. The roadmap (`AD-719a-wire`, [roadmap.md](../docs/development/roadmap.md#L576)) marks the wire-up of that transient fan-out into a persistence layer as deferred. AD-914 delivers it on the `ChatThreadStore` substrate.

### The AD-719a contract AD-914 implements (Captain ruling, [ward_room/multi_agent.py](../src/probos/ward_room/multi_agent.py#L1-L30))
- **Captain messages are always the seed.** AD-914 only fans out a turn authored by the Captain (`role == "captain"`).
- **Agents observe other agents' messages once both are in the thread** — implemented as recent thread history injected into each agent's prompt.
- **Agent-to-agent without a Captain seed is deferred.** AD-914 keeps this rule (no agent auto-reply). AD-918 later lifts it. AD-915 adds multi-round turn-taking.

AD-914 implements these rules on the `ChatThreadStore` substrate and **does not touch** the Ward Room `multi_agent.py` module (that is a separate WardRoom-thread namespace).

---

## Verified reuse path (the real intent + dispatch primitive)

This is the **exact** shape AD-914 reuses. Confirmed against live code (see footer for grep lines).

1. **Real intent name:** `"direct_message"`.
2. **Dispatch primitive:** `await runtime.intent_bus.send(intent)` — **`send`, not `broadcast`** (targeted, request/reply). Returns `IntentResult | None`. ([mesh/intent.py](../src/probos/mesh/intent.py#L407))
3. **IntentMessage build** (mirror the 1:1 `agent_chat` path, [routers/agents.py](../src/probos/routers/agents.py#L2173-L2192)):
   ```python
   intent = IntentMessage(
       intent="direct_message",
       params={
           "text": captain_body,                 # the Captain turn that triggered fan-out
           "from": "hxi_profile",                # makes the receiver treat it as a real DM
           "session": bool(session_history),
           "session_history": session_history,   # AD-914: REAL recent thread history (the "see each other" wire)
       },
       target_agent_id=agent_id,                 # a participant agent_id (NOT a callsign)
       ttl_seconds=60.0,                          # AD-636
       thread_id=thread_id,                       # AD-791a provenance
   )
   result = await runtime.intent_bus.send(intent)
   reply_text = str(result.result) if (result and result.result) else "(no response)"
   ```
4. **`session_history` entry shape** (the consumer is [cognitive_agent.py](../src/probos/cognitive/cognitive_agent.py#L6735)): a list of `{"role": <str>, "text": <str>}`. The consumer prints `"  {role}: {text}"`. **The key is `text`, not `content`.**
5. **Reply persistence** (mirror [routers/agents.py](../src/probos/routers/agents.py#L2289)):
   ```python
   store.append_message(
       thread_id, author_id=agent_id, role="agent",
       body=reply_text, metadata={"intent_id": intent.id, "fanout": "ad914"},
   )
   ```

### Why a focused helper, NOT a chat.py refactor (DRY scoping)
The chat.py AD-719 branch and the AD-914 thread path **share the parallel-dispatch shape** but differ materially: chat.py resolves **callsigns→agent_id**, passes **blind** `session_history`, returns `PerAgentReply` objects, and writes **episodes keyed on callsign**; the thread path has **agent_ids directly**, injects **real** history, and **persists to the store**. Extracting one shared helper would force the four AD-719 single-mention contract tests + the BF-287 `>= 2` semantics through a refactor — out of scope and risky. **Do NOT touch the chat.py AD-719 branch.** Instead introduce a new, focused router-layer helper module (below). A future `AD-914a` may unify the two; leave a one-line forward marker, do not unify now.

---

## Chosen trigger seam

**Extend the existing `POST /api/threads/{thread_id}/messages` handler** ([routers/threads.py](../src/probos/routers/threads.py#L211)). It already persists the appended message and touches the project. AD-914 adds, **after** the existing append + project-touch:

```
if body.role == "captain" and <thread has ≥2 crew-agent participants>:
    per_agent_replies = await group_chat_fanout(runtime, thread_id, captain_body=body.body, captain_msg=msg)
    return {**msg.to_dict(), "per_agent_replies": per_agent_replies}
return msg.to_dict()   # unchanged for every other case
```

This is the **least-invasive seam**:
- The Captain turn is already persisted by the existing handler; the fan-out reads history back from the store.
- **Non-captain authors** (`role` in `{"agent","system"}`) never trigger fan-out → no agent-to-agent storm (the AD-914 boundary, enforced structurally).
- **<2 crew-agent participants** → behavior is **byte-identical** to today (pure append; response stays `msg.to_dict()` with no `per_agent_replies` key). The 1:1 `agent_chat` endpoint is untouched.
- The response gains `per_agent_replies` **only** when fan-out fires — additive, backward-compatible.

### Identifying Captain vs agent participants
- **Captain** = the appended message's `role == "captain"` (the Captain is implicit; `author_id` is conventionally `"captain"`).
- **Crew-agent participants** = `[p for p in thread.participants if (a := runtime.registry.get(p)) is not None and is_crew_agent(a, runtime.ontology)]` ([crew_utils.py](../src/probos/crew_utils.py#L21)). This naturally excludes a literal `"captain"` sentinel participant (AD-919's Join path) and any non-crew / unresolvable id — `runtime.registry.get("captain")` is `None`/non-crew. Fan out **only** to these.

---

## History injection — the "see each other" mechanism

Build `session_history` **server-side** from the store so each agent sees the recent thread turns (including other agents' prior replies and prior Captain turns):

1. Fetch prior turns, **excluding the just-appended Captain message**, using the `before` filter:
   `prior = store.list_messages(thread_id, limit=1000, before=captain_msg.created_at)`.
   ⚠️ **Ordering gotcha:** `list_messages` is `ORDER BY created_at ASC LIMIT ?` ([threads/__init__.py](../src/probos/threads/__init__.py#L683)) — a bare `limit=N` returns the **oldest** N, not the most recent. To get the most recent window, fetch with the store max (`limit=1000`) then **tail-slice** in Python: `recent = prior[-_FANOUT_HISTORY_LIMIT:]`.
2. Map each `ChatThreadMessage` to `{"role": <label>, "text": m.body}`:
   - For `m.role == "agent"`: `<label>` = the author's **callsign** so agents are legible to each other (e.g. `"Ezri"` not `"agent"`). Resolve best-effort: `runtime.callsign_registry.get_callsign(runtime.registry.get(m.author_id).agent_type)`. **Tier-2 fallback** to `"agent"` on any failure.
   - For `m.role == "captain"`: `<label> = "Captain"`.
   - For `m.role == "system"`: `<label> = "system"`.
3. The **Captain's current turn** is delivered as `params["text"]` (not in history) — mirroring `agent_chat`.
4. **All agents in this turn receive the SAME history snapshot** (thread state at fan-out time). They do **not** see each other's replies from *this* turn — that parallel-fan-out semantics is intentional; sequential turn-taking where agent B sees agent A's same-turn reply is **AD-915**.

`_FANOUT_HISTORY_LIMIT` is a **module-level constant** (e.g. `20`) — **no new config field** (zero-config boot preserved).

---

## Persistence shape

Each agent reply → one `chat_thread_messages` row:
```python
store.append_message(
    thread_id, author_id=agent_id, role="agent",
    body=reply_text, metadata={"intent_id": intent.id, "fanout": "ad914"},
)
```
Replies are persisted via the **in-process store call** — **never** by re-POSTing to the endpoint — so there is **no recursion / no loop**.

---

## Implementation

### Section 1 — New helper module `src/probos/routers/thread_fanout.py`

Router-layer orchestration (legitimately spans store + mesh; no layer violation — `runtime` is dependency-injected, the module imports only `IntentMessage` from `probos.types` and `is_crew_agent` from `probos.crew_utils`).

```python
"""AD-914: group-chat fan-out for ChatThreadStore threads.

When the Captain posts to a thread with >= 2 crew-agent participants, fan
the turn out to all agent participants in parallel, inject recent thread
history into each agent's prompt (cross-agent visibility), and persist each
reply as a chat_thread_messages row (role="agent"). The ChatThreadStore form
of the dormant AD-719a-wire marker.

Boundary (AD-914): fan out the Captain's turn ONCE (parallel) and STOP.
Agents do NOT auto-reply to each other — that is AD-915 (turn-taking) and
AD-918 (agent-initiated). Captain-seeds rule per the AD-719a contract.

Forward marker (AD-914a): the chat.py AD-719 @-mention branch shares the
parallel-dispatch shape but resolves callsigns + passes blind history; a
future AD may unify the two. Not unified here by design.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.crew_utils import is_crew_agent
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

# AD-914: recent-history window injected into each agent's prompt. Module
# constant — NOT config (zero-config boot). Bounds prompt size.
_FANOUT_HISTORY_LIMIT = 20


def crew_agent_participants(runtime: Any, participants: list[str]) -> list[str]:
    """Participant agent_ids that resolve to crew agents (Captain/non-crew excluded)."""
    out: list[str] = []
    for pid in participants:
        agent = runtime.registry.get(pid)
        if agent is not None and is_crew_agent(agent, getattr(runtime, "ontology", None)):
            out.append(pid)
    return out


def _build_session_history(runtime: Any, store: Any, thread_id: str, before: float) -> list[dict[str, str]]:
    """Recent thread turns (excluding the just-appended Captain msg) as
    {"role": <callsign|Captain|system>, "text": body} entries. Tier-2:
    callsign resolution failures degrade to the raw stored role."""
    prior = store.list_messages(thread_id, limit=1000, before=before)
    recent = prior[-_FANOUT_HISTORY_LIMIT:]
    history: list[dict[str, str]] = []
    for m in recent:
        if m.role == "agent":
            label = "agent"
            try:
                agent = runtime.registry.get(m.author_id)
                if agent is not None and hasattr(runtime, "callsign_registry"):
                    label = runtime.callsign_registry.get_callsign(agent.agent_type) or "agent"
            except Exception:
                logger.debug("AD-914: callsign label resolve failed for %s", m.author_id, exc_info=True)
        elif m.role == "captain":
            label = "Captain"
        else:
            label = "system"
        history.append({"role": label, "text": m.body})
    return history


async def group_chat_fanout(
    runtime: Any,
    thread_id: str,
    *,
    captain_body: str,
    captain_msg: Any,
) -> list[dict[str, str]]:
    """Fan the Captain turn out to all crew-agent participants in parallel.

    Returns a list of {"agent_id", "callsign", "text"} dicts (one per
    dispatched agent). Persists each reply as a role="agent" message.
    Assumes the caller already verified role=="captain" AND >= 2 crew
    participants. Per-agent dispatch is Tier-2 log-and-degrade: one
    agent's failure never blocks the others.
    """
    store = runtime.chat_thread_store
    thread = store.get_thread(thread_id)
    if thread is None:
        return []
    agent_ids = crew_agent_participants(runtime, thread.participants)
    session_history = _build_session_history(runtime, store, thread_id, captain_msg.created_at)

    async def _send_one(agent_id: str) -> dict[str, str]:
        callsign = ""
        try:
            agent = runtime.registry.get(agent_id)
            if agent is not None and hasattr(runtime, "callsign_registry"):
                callsign = runtime.callsign_registry.get_callsign(agent.agent_type) or ""
        except Exception:
            logger.debug("AD-914: callsign resolve failed for %s", agent_id, exc_info=True)
        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": captain_body,
                "from": "hxi_profile",
                "session": bool(session_history),
                "session_history": session_history,
            },
            target_agent_id=agent_id,
            ttl_seconds=60.0,
            thread_id=thread_id,
        )
        try:
            result = await runtime.intent_bus.send(intent)
        except Exception as e:
            logger.warning(
                "AD-914 fan-out send failed for %s: %s: %s; other recipients unaffected",
                agent_id, type(e).__name__, e,
            )
            return {"agent_id": agent_id, "callsign": callsign, "text": "(delivery failed)"}
        reply_text = str(result.result) if (result and result.result) else "(no response)"
        try:
            store.append_message(
                thread_id, author_id=agent_id, role="agent",
                body=reply_text, metadata={"intent_id": intent.id, "fanout": "ad914"},
            )
        except Exception:
            logger.warning("AD-914: persist reply failed for thread=%s agent=%s", thread_id, agent_id, exc_info=True)
        return {"agent_id": agent_id, "callsign": callsign, "text": reply_text}

    replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])
    return list(replies)
```

> Builder: verify `ChatThreadMessage` exposes `.role`, `.author_id`, `.body`, `.created_at` (it does — `_row_to_message`/the dataclass in [threads/__init__.py](../src/probos/threads/__init__.py)). If `get_callsign` is absent on a test stub, the `hasattr` + try/except already degrades.

### Section 2 — Wire the helper into `POST /api/threads/{thread_id}/messages`

In [routers/threads.py](../src/probos/routers/threads.py#L211), **after** the existing `append_message` + project-touch block and **before** `return msg.to_dict()`:

```python
    # AD-914: group-chat fan-out. A Captain turn into a thread with >= 2
    # crew-agent participants fans out to all of them in parallel, injects
    # recent thread history (cross-agent visibility), and persists each
    # reply. Single-agent / non-Captain posts are byte-identical to before.
    if body.role == "captain":
        from probos.routers.thread_fanout import crew_agent_participants, group_chat_fanout
        thread = store.get_thread(thread_id)
        if thread is not None and len(crew_agent_participants(runtime, thread.participants)) >= 2:
            try:
                per_agent_replies = await group_chat_fanout(
                    runtime, thread_id, captain_body=body.body, captain_msg=msg,
                )
                return {**msg.to_dict(), "per_agent_replies": per_agent_replies}
            except Exception:
                logger.warning("AD-914: group fan-out failed for thread=%s; returning appended message only", thread_id, exc_info=True)
    return msg.to_dict()
```

Add `import logging` / `logger = logging.getLogger(__name__)` at module top if not already present (the existing handler uses an inline `logging.getLogger(__name__)` for the project-touch degrade — promote to a module logger or keep inline; Builder's choice, keep it minimal).

> The top-level `try/except` around `group_chat_fanout` is belt-and-braces Tier-2: a fan-out failure must never lose the Captain's already-persisted message.

---

## Tests — `tests/test_ad914_group_chat_fanout.py`

**BF-287 discipline: real `ChatThreadStore` on `tmp_path`, real `IntentBus(SignalManager())`, a real-but-fake handler agent subscribed to the bus, and a plain real `_FakeRegistry`/`_FakeAgent` (NOT `MagicMock`) at the substrate/bus boundary.** Mirror the fixture style of [tests/test_ad913_participant_management.py](../tests/test_ad913_participant_management.py) (store + REST via `SimpleNamespace` runtime + `dependency_overrides[get_runtime]`) and the real-bus round-trip of [tests/test_ad470_intent_bus_enhancements.py](../tests/test_ad470_intent_bus_enhancements.py#L29-L108).

### Fixtures (specify exactly)
```python
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type      # real attr; is_crew_agent reads .agent_type

class _FakeRegistry:
    def __init__(self, agents: dict) -> None:
        self._a = agents
    def get(self, agent_id: str):
        return self._a.get(agent_id)

class _FakeCallsigns:
    def __init__(self, mapping: dict) -> None:
        self._m = mapping            # agent_type -> callsign
    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")

# crew agent_types from crew_utils._WARD_ROOM_CREW (ontology=None path): e.g. "scout", "counselor"
```
- `runtime` = `SimpleNamespace(chat_thread_store=store, intent_bus=bus, registry=_FakeRegistry({...}), ontology=None, callsign_registry=_FakeCallsigns({...}), project_store=None)`.
- The handler records what it received so history-injection can be asserted:
  ```python
  received: dict[str, dict] = {}
  def make_handler(agent_id):
      async def _h(intent: IntentMessage) -> IntentResult:
          received[agent_id] = {"text": intent.params.get("text"), "history": intent.params.get("session_history")}
          return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}")
      return _h
  bus.subscribe(agent_id, make_handler(agent_id), intent_names=["direct_message"])
  ```
- Drive most tests by calling `await group_chat_fanout(...)` directly (after appending a `role="captain"` message via the store). Use 1–2 REST tests (mount `from probos.routers.threads import router`) for the response shape + back-compat.

### Required test cases (≥12)
1. `test_two_agent_thread_fans_out_to_all` — 2 crew participants; both handlers invoked (both keys in `received`); two reply dicts returned.
2. `test_replies_persisted_as_agent_messages` — after fan-out, `store.list_messages` contains 2 new `role="agent"` rows whose `author_id` ∈ the participant set and `body == "reply::<agent_id>"`.
3. `test_each_agent_prompt_contains_other_participants_turns` — seed a prior `role="agent"` reply from agent A (via `append_message`), then run fan-out on a fresh Captain turn; assert each handler's `received[...]["history"]` contains an entry whose `text` is A's prior body. (The "see each other" assertion.)
4. `test_agent_history_labelled_with_callsign` — the prior agent turn appears in `history` with `role` == A's **callsign** (not the literal `"agent"`).
5. `test_captain_turn_passed_as_text_not_history` — `received[...]["text"]` equals the Captain body; the Captain body is **not** present in `history` (it was the just-appended msg, excluded via `before`).
6. `test_single_agent_thread_does_not_fan_out` — 1 crew participant: `crew_agent_participants(...)` len == 1 → endpoint/handler path does NOT dispatch (handler not in `received`) and no extra `role="agent"` row persisted.
7. `test_non_captain_author_does_not_trigger_fanout` — a `role="agent"` (and a `role="system"`) post to a ≥2-agent thread does NOT fan out (no dispatch; loop-safety boundary). Drive via the REST endpoint and assert no `per_agent_replies` key + no new agent rows.
8. `test_non_crew_participant_excluded` — a participant id that resolves to a non-crew agent (or to `None`, or the literal `"captain"`) is excluded from `crew_agent_participants` and from dispatch; pair it with one crew agent → count == 1 → no fan-out.
9. `test_fanout_response_includes_per_agent_replies` (REST) — `POST /api/threads/{id}/messages` with `role="captain"` on a 2-crew thread returns `per_agent_replies` listing both agents with their reply text.
10. `test_messages_endpoint_unchanged_for_non_group` (REST, back-compat) — `POST .../messages` on a single-crew thread returns a plain message dict with **no** `per_agent_replies` key.
11. `test_reply_persistence_metadata_tags_fanout` — persisted agent rows carry `metadata["intent_id"]` and `metadata["fanout"] == "ad914"`.
12. `test_one_agent_failure_does_not_block_other` — one agent has **no** subscriber (or its handler raises) → its reply dict is `"(no response)"`/`"(delivery failed)"`, the other agent still replies and persists. (Tier-2 degrade.)

(Builder may add an order-independence assertion for parallel dispatch; keep the floor at 12.)

---

## What this does NOT change (Do NOT build)

- **Do NOT touch the AD-719 fan-out branch** in [routers/chat.py](../src/probos/routers/chat.py#L140-L264) — the four AD-719 single-mention contract tests + the BF-287 `>= 2` callsign semantics are load-bearing. No extraction, no refactor of that branch.
- **Do NOT add agent-to-agent auto-reply or multi-round turn-taking.** Fan out the Captain's turn once, persist, stop. (That is **AD-915** turn-taking + **AD-918** agent-initiated.)
- **Do NOT add a turn-taking facilitator, convergence gating, or speaking-order ranking** (AD-915).
- **Do NOT add file/attachment handling** to the thread path (AD-916).
- **Do NOT add a `create_group_chat` intent** or agent-initiated threads (AD-918).
- **Do NOT modify** `IntentMessage` / `IntentResult` / `BaseAgent` / `IntentBus` protocols, or the `ChatThreadStore` public API (no new store methods — use existing `list_messages(before=...)` + `append_message`).
- **Do NOT change** the 1:1 `agent_chat` endpoint ([routers/agents.py](../src/probos/routers/agents.py#L1664)) behavior.
- **Do NOT migrate or modify** the Ward Room `multi_agent.py` contract — AD-914 implements its rules on the `ChatThreadStore` substrate, leaving WardRoom untouched.
- **Do NOT add a config field.** The history window is a module constant.

---

## Tracking

- `PROGRESS.md` — add the AD-914 entry (group-chat fan-out + cross-agent visibility on `ChatThreadStore`; new `routers/thread_fanout.py`; `POST /messages` seam; +N tests).
- `docs/development/roadmap.md` — mark the AD-914 row delivered in the "Ad-hoc crew collaboration" northstar table.
- `DECISIONS.md` — append the AD-914 decision (trigger seam = `POST /messages` gated on `role=="captain"` + ≥2 crew participants; history injected server-side from `list_messages`; single-turn parallel bound = loop safety; Captain-seeds rule retained, agent-to-agent deferred to AD-918).

## Acceptance criteria

- New module `src/probos/routers/thread_fanout.py` with `group_chat_fanout`, `crew_agent_participants`, `_build_session_history`; full type annotations on the public functions.
- `POST /api/threads/{thread_id}/messages` fans out **only** when `body.role == "captain"` AND ≥2 crew-agent participants; otherwise byte-identical to today (`return msg.to_dict()` with no new key).
- Each agent's injected `session_history` contains the other participants' recent turns, agent rows labelled by callsign; the Captain's current turn is delivered as `params["text"]`, excluded from history.
- Each reply persisted as a `role="agent"` `chat_thread_messages` row with `metadata.fanout == "ad914"`.
- Per-agent dispatch is Tier-2 log-and-degrade; one failure does not block the others; a fan-out failure never loses the Captain's appended message.
- `tests/test_ad914_group_chat_fanout.py` ≥12 tests, all green, **real `ChatThreadStore` + real `IntentBus` + real-but-fake registry/handler (no `MagicMock` at the store/bus boundary)**.
- Full gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. Thread blast-radius green: `pytest tests/test_ad791_chat_threads.py tests/test_ad913_participant_management.py tests/test_ad914_group_chat_fanout.py -q -n 0`.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```
roadmap.md:364   | AD-914 | Group-chat fan-out + cross-agent visibility ... persists replies as chat_thread_messages (the ChatThreadStore form of AD-719a-wire)
roadmap.md:576   | AD-719a-wire | Wire AD-719's transient fan-out into the AD-719a thread persistence layer (forward marker)

threads/__init__.py:649   def append_message(self, thread_id, *, author_id, role, body, metadata=None) -> ChatThreadMessage | None
threads/__init__.py:683   def list_messages(self, thread_id, *, limit=200, before=None) -> list[ChatThreadMessage]   # "ORDER BY created_at ASC LIMIT ?"
threads/__init__.py:230   def get_thread(self, thread_id) -> ChatThread | None
threads/__init__.py:377   def add_participant(...)   # AD-913
threads/__init__.py:410   def remove_participant(...)   # AD-913

routers/threads.py:211    @router.post("/{thread_id}/messages") async def append_message(... body: AppendMessageRequest ...) -> dict   # TRIGGER SEAM
routers/threads.py:62     class AppendMessageRequest: author_id; role=Field(pattern="^(captain|agent|system)$"); body; metadata

routers/chat.py:140-264   # AD-719 fan-out branch (REUSE REFERENCE — do NOT touch)
routers/chat.py:158         async def _send_one(callsign, resolved) -> PerAgentReply
routers/chat.py:187         intent="direct_message", params={"text", "from":"hxi_profile", "session":True, "session_history":[]}, target_agent_id, ttl_seconds=60.0
routers/chat.py:216         result = await runtime.intent_bus.send(intent)
routers/chat.py:223         reply_text = (result.result if result and result.result else "(no response)")

routers/agents.py:2173    _params = {"text": message_text, "from":"hxi_profile", "session": bool(req.history), "session_history": req.history[-10:] ...}
routers/agents.py:2186    IntentMessage(intent="direct_message", params=_params, target_agent_id=agent_id, ttl_seconds=60.0, thread_id=thread.id)
routers/agents.py:2224    response_text = str(result.result)
routers/agents.py:2289    _thread_store.append_message(thread.id, author_id=agent_id, role="agent", body=..., metadata={"intent_id": intent.id})

cognitive_agent.py:6735   session_history = params.get("session_history", []) ; for entry: entry.get("role"), entry.get("text")   # entry key is "text"

crew_utils.py:21          def is_crew_agent(agent, ontology=None) -> bool   # checks agent.agent_type (ontology=None -> _WARD_ROOM_CREW)

mesh/intent.py:72         class IntentBus.__init__(self, signal_manager: SignalManager)
mesh/intent.py:145        def subscribe(self, agent_id, handler, intent_names=None)
mesh/intent.py:407        async def send(self, intent) -> IntentResult | None   # direct-call fallback: handler = self._subscribers.get(intent.target_agent_id)
mesh/signal.py:22         class SignalManager.__init__(self, reap_interval: float = 1.0)

types.py:50               IntentMessage: intent; params; ttl_seconds=60.0; id=uuid; target_agent_id: str|None; thread_id: str|None
types.py:70               IntentResult: intent_id; agent_id; success; result: Any=None; error: str|None=None; confidence=0.0

ward_room/multi_agent.py:1-30   AD-719a contract: Captain seeds; @-mentioned agents observe; agent-to-agent w/o Captain deferred (AD-719a-2)

tests/test_ad913_participant_management.py   fixture: real ChatThreadStore(tmp_path) + SimpleNamespace runtime + dependency_overrides[get_runtime]
tests/test_ad470_intent_bus_enhancements.py:29-108   real handler(intent)->IntentResult + bus.subscribe + await bus.send round-trip

git: highest committed AD = AD-912 (6285edca); AD-913 shipped-uncommitted (M threads.py, M threads/__init__.py, ?? test_ad913)
```
