# AD-794 + AD-809 (v3) — Wire auto-naming and personality overlay into the chat flow

**Wave:** 194. Single Builder commit at completion.
**Sequence:** AD-794 (#718) + AD-809 (#733). No new AD numbers required.
**Builds on:** AD-791a / AD-827 (Wave 193) — substrate + 1:1 wiring. `ChatThreadStore.append_message` exists (L432); `list_messages` exists (L466); `get_thread` exists (L215); `update_thread` exists (L245); `chat_threads.personality_override` column exists (initial schema); `chat_threads.metadata` column exists (added by `_migrate_v2()`); `chat_threads.title` exists. The naming helper `suggest_title()` (naming.py:29) and personality resolver `resolve_personality()` (naming.py:58) already exist with ZERO consumers. The existing `POST /api/threads/{id}/auto-name` endpoint (routers/threads.py:188) also already exists. `IntentMessage.thread_id` is populated on every chat dispatch (AD-791a Section 1).

v3 addresses the v2 Required layer-mislocation: personality consumption rides `intent.thread_id` to the **receiving agent's** system-prompt assembly site (NOT through `DmReplyContext` — that's post-LLM cleanup, too late). Plus 1 recommended fix (real `extract_callsign_mention` helper instead of phantom `extract_message_after_callsign`) and 1 recommended fix (`force` flag on `maybe_auto_name` to preserve existing endpoint behavior).

**The actual work:** wire the existing helpers into the actual chat flow + add the `/personality` slash command. The helpers themselves are not under development; only their callers and a small set of new methods to centralize the trigger logic.

---

## Section 0 — Conceptual frame (consistent with AD-791a Section 0)

ProbOS agents have persistent sovereign identity. Personality is part of identity — Ezri is calm, attentive, gently probing; Worf is direct, blunt, formal. The `personality_override` column on `chat_threads` is NOT a way to change who Ezri IS for this thread; it's a way to ask Ezri to adopt a particular **register** in this conversation (e.g., "be more concise here," "be more technical here"). Same person, different room voice.

The thread title is operator-visible navigation aid, not memory. Auto-naming from the first turn produces 3–6 words that let the Captain recognize the thread in a future sidebar (AD-792). Manual rename is final authority — the AI does not re-rename a thread the Captain has named.

Two pieces wire in this AD:

1. **AD-794** — first-turn auto-name: when a new thread is created via `get_or_create_default_for_agent` (the only creation path today) OR by future explicit `/api/threads` POST, the existing default title ("Ezri", "Worf", etc., from `agent.callsign`) is acceptable for v1 default-thread case. The trigger for AD-794 is when the title is still the agent's callsign (i.e., never edited) AND it's the FIRST message — replace with a `suggest_title(body)`-derived title. Track "the operator manually renamed it" via a new `title_locked: bool` flag in `chat_threads.metadata` (no new column needed; metadata JSON column already exists per AD-791a).

2. **AD-809** — `/personality <name>` slash command: a small registry of named personality strings + a slash command that writes the resolved string to `chat_threads.personality_override`. Consumers (the chat handlers, the DM reply pipeline) call `resolve_personality(thread, default=agent.personality)` at prompt-assembly time — the helper already exists.

---

## Section 1 — Personality registry (small, deliberate)

New file `src/probos/cognitive/personality_registry.py`:

```python
"""AD-809: personality registry — named register/style overlays.

These are NOT identity replacements. They are register knobs the Captain
can flip per thread to ask an agent to adopt a particular voice (more
concise, more formal, etc.). The agent's underlying identity (callsign,
crew role, persistent memory, trust state) is unchanged.

The default registry ships with 5 entries derived from common
operator-facing styles. Operators can add more via config (forward
marker AD-809a) — v1 ships the fixed registry.
"""
from __future__ import annotations

# Personality fragments append to the agent's existing system prompt.
# They are written as overlays — short, additive, never absolute.
_REGISTRY: dict[str, str] = {
    "concise": (
        "For this conversation, default to short answers. Aim for 1-3 sentences "
        "unless the Captain explicitly asks for depth."
    ),
    "formal": (
        "For this conversation, use formal register. Address the Captain as "
        "'Captain' rather than by callsign familiarity. Avoid contractions."
    ),
    "socratic": (
        "For this conversation, favor questions over assertions when the topic "
        "permits. Help the Captain think through the problem rather than handing "
        "over a final answer first."
    ),
    "expert": (
        "For this conversation, write at expert-to-expert technical register. "
        "Skip introductions; assume the Captain has the background context. "
        "Cite specific mechanisms, terms of art, and trade-offs."
    ),
    "casual": (
        "For this conversation, drop into a relaxed, conversational register. "
        "Contractions and asides are fine. Keep it human."
    ),
}


def list_personalities() -> list[str]:
    """Return the names of all available personalities."""
    return sorted(_REGISTRY.keys())


def resolve_personality_text(name: str) -> str | None:
    """Resolve a personality name to its registry fragment, or None if unknown."""
    return _REGISTRY.get(name.strip().lower())
```

Touchpoints: NEW file. Tested with 3 unit tests (lookup hit, lookup miss, list).

---

## Section 2 — `/personality` slash command in chat handlers

The chat handlers in `routers/agents.py::agent_chat` and `routers/chat.py` (inline-callsign + vision paths) inspect `req.message` for leading slash commands. AD-812 already shipped this pattern for `/remind` and `/schedule` — copy that shape.

**Module-top imports** (NOT inline inside the function — per architect R3):

```python
# top of routers/agents.py (after existing imports)
from probos.cognitive.commands.personality_command import (
    is_personality_command,
    handle_personality_command,
)
```

**The command parser** (NEW helper at `src/probos/cognitive/commands/personality_command.py`):

```python
"""AD-809: /personality <name|list|clear> slash command."""
from __future__ import annotations
from typing import Any
from probos.cognitive.personality_registry import (
    list_personalities,
    resolve_personality_text,
)
from probos.threads import ChatThreadStore


def is_personality_command(message: str) -> bool:
    """True if the message starts with `/personality` (case-sensitive).

    NOTE: callers MUST strip leading @-mentions before testing (the inline-
    callsign branch in routers/chat.py receives raw `@Ezri /personality formal`).
    The agent_chat handler in routers/agents.py receives stripped messages
    already (the agent identity is path-routed, not in the body)."""
    return message.strip().startswith("/personality")


def handle_personality_command(
    message: str,
    *,
    thread_id: str,
    store: ChatThreadStore,
) -> dict[str, Any]:
    """Parse and apply a /personality command. Returns a dict suitable
    for inclusion in the chat-response body.

    Side effects: EVERY variant (list/set/clear/unknown) appends BOTH the
    captain command and the system reply to chat_thread_messages so the
    operator sees their own typed input and the system response on
    reload. (Architect R6 decision: append-always matches the operator's
    mental model of 'what I typed is in the log'.)
    """
    parts = message.strip().split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    if arg == "" or arg == "list":
        available = list_personalities()
        return {
            "system_reply": (
                "Available personalities: " + ", ".join(available) +
                ". Use `/personality <name>` to apply, or `/personality clear` to reset."
            ),
            "applied": None,
            "available": available,
        }

    if arg == "clear":
        store.set_personality_override(thread_id, override=None)
        return {
            "system_reply": "Personality cleared; using the agent's default register.",
            "applied": None,
            "available": list_personalities(),
        }

    text = resolve_personality_text(arg)
    if text is None:
        return {
            "system_reply": (
                f"Unknown personality `{arg}`. Available: " +
                ", ".join(list_personalities())
            ),
            "applied": None,
            "available": list_personalities(),
        }

    store.set_personality_override(thread_id, override=text)
    return {
        "system_reply": (
            f"Personality set to `{arg}` for this thread. The agent will "
            f"adopt this register on subsequent turns."
        ),
        "applied": arg,
        "available": list_personalities(),
    }
```

This requires a new method `ChatThreadStore.set_personality_override(thread_id, override: str | None)` — see Section 4.

### Wiring into the chat handlers — explicit ordering (architect Required #3 + #5)

The per-turn ordering MUST be:

```
1. (inline-callsign branch only) @-mention strip
2. /personality slash-command guard (early-return on match)
3. Auto-name trigger (Section 5)
4. Append captain message to chat_thread_messages
5. Dispatch IntentMessage (agent turn)
```

This ordering ensures that a Captain typing `/personality formal` as the first message in a fresh thread does NOT auto-name the thread to "personality formal" (step 2 returns early before step 3 fires).

### At `agent_chat` (`routers/agents.py:1660`)

After the agent lookup and thread resolution from AD-791a:

```python
# AD-809: handle /personality slash command BEFORE auto-name and intent dispatch.
# Personality commands are pure thread-state ops — no agent turn fires.
if is_personality_command(req.message):
    result = handle_personality_command(
        req.message,
        thread_id=thread.id,
        store=runtime.chat_thread_store,
    )
    store.append_message(
        thread_id=thread.id, author_id="captain", role="captain",
        body=req.message, metadata={"slash_command": "personality"},
    )
    store.append_message(
        thread_id=thread.id, author_id="system", role="system",
        body=result["system_reply"],
        metadata={"slash_command": "personality", "applied": result["applied"]},
    )
    return {
        "response": result["system_reply"],
        "thread_id": thread.id,
        "system": True,
        # ... other existing keys preserved (or set to empty/None as appropriate) ...
    }

# Continue with auto-name (Section 5) + intent dispatch + AD-791a wiring ...
```

### At `routers/chat.py` inline-callsign branch (~L263 — existing site)

**Use the real helper** `extract_callsign_mention` (defined in `crew_profile.py:836`) which returns `(callsign, message_text) | None`. The inline-callsign branch at `routers/chat.py:263` already calls it via `callsign, message_text = mention`. Insert the `/personality` guard after that unpacking:

```python
# Existing code at routers/chat.py:~263:
mention = extract_callsign_mention(req.message)
if mention is not None:
    callsign, message_text = mention
    # ... existing thread resolution + AD-791a thread_id wiring ...

    # NEW: AD-809 /personality guard, using message_text (already @-stripped)
    if is_personality_command(message_text):
        result = handle_personality_command(
            message_text,
            thread_id=thread.id,
            store=runtime.chat_thread_store,
        )
        store.append_message(
            thread_id=thread.id, author_id="captain", role="captain",
            body=message_text, metadata={"slash_command": "personality"},
        )
        store.append_message(
            thread_id=thread.id, author_id="system", role="system",
            body=result["system_reply"],
            metadata={"slash_command": "personality", "applied": result["applied"]},
        )
        # Return a plain dict matching the existing inline-callsign branch's
        # shape (chat.py:344-348). ChatResponse(BaseModel) has no `system`
        # field; the wire-format is a dict that the UI selects on via the
        # `system` key. Do NOT construct ChatResponse(system=True, ...).
        return {
            "response": result["system_reply"],
            "thread_id": thread.id,
            "system": True,
            "dag": None,
            "results": None,
            "applied": result["applied"],
        }
    # Continue with the existing intent dispatch path...
```

The vision branch (~L424) does NOT include a `/personality` guard — vision turns are inherently about images. If a vision request starts with `/personality`, fall through to normal processing (the command is harmless text in that context).

---

## Section 3 — Personality consumption: receiving agent reads `intent.thread_id` (v3 layer-precise correction)

**v3 layer-precise correction.** v2 added `personality_text` to `DmReplyContext` and proposed consumption "inside the pipeline," but `DmReplyPipeline` is **post-LLM cleanup** (AD-726): by the time `DmReplyContext` is constructed at `routers/agents.py:2089`, the LLM has already produced `response_text` via `intent_bus.send(intent)` at L2076. The system prompt is assembled by the **receiving agent** processing the `direct_message` intent.

v3 follows Shape A from the architect review: the receiving agent's DM handler reads `intent.thread_id` (already wired by AD-791a Section 1), looks up the thread via the runtime's `chat_thread_store`, calls `resolve_personality(thread, default=agent.personality)`, and appends the result to its system prompt.

**No changes to `DmReplyContext` for AD-809.** No new fields on `IntentMessage.params`. The `intent.thread_id` field is the canonical wire (per AD-791a Section 1).

### Builder steps

1. **Find the system-prompt assembly site for direct_message intents.** Architect-verified location: **`cognitive_agent.py:2087-2112`** — inside `CognitiveAgent.decide()`, the `composed = ...` build that flows into `LLMRequest(..., system_prompt=composed, ...)` at L2180/2192/2198. Per-turn assembly confirmed (no caching at agent construction). Builder pre-flight greps:

   ```
   grep -n "composed = \|system_prompt=composed\|LLMRequest" src/probos/cognitive/cognitive_agent.py
   ```

   If the line numbers have drifted, re-anchor. If the site has moved out of `cognitive_agent.py`, stop and report.

2. **At the assembly site**, append the personality overlay. Architect-confirmed site: **`cognitive_agent.py` L2087-L2112** — the `composed = ...` system-prompt build inside `CognitiveAgent.decide()`. The personality overlay should append to `composed` after both DM and non-DM branches converge, BEFORE the `LLMRequest(..., system_prompt=composed, ...)` calls at L2180/2192/2198. The canonical runtime attribute is `self._runtime` (underscore), per `substrate/agent.py:47`:

   ```python
   # Conceptual shape — actual variable names follow cognitive_agent.py's existing local idiom.
   # `composed` is the agent's built system-prompt string from L2087-L2112.
   # `intent` is the IntentMessage handed to the handler (DM branch).
   from probos.threads.naming import resolve_personality

   if intent.thread_id and self._runtime is not None:
       store = getattr(self._runtime, "chat_thread_store", None)
       if store is not None:
           thread = store.get_thread(intent.thread_id)
           overlay = resolve_personality(thread, default="")
           if overlay:
               composed = composed + "\n\n" + overlay
   ```

   When no override is set on the thread, `resolve_personality(thread, default="")` returns `""` and nothing is appended. Section 0's invariant holds: the agent's default identity is unchanged.

   Honest-degrade: when `self._runtime` is None (test harnesses without a runtime) OR when `getattr(self._runtime, "chat_thread_store", None)` is None (federated/foreign agents without local store access), the overlay is silently skipped. The agent gets its base identity-only prompt; no error raised.

3. **If the receiving agent does NOT have access to `self._runtime`** at the L2087-L2112 assembly site, STOP and report. Personality consumption may need a small runtime-threading AD. The `if self._runtime is not None` guard above is the defensive shape — verify the assertion holds for the common DM path.

4. **Telemetry comment** at the consumption site: document that this is the AD-809 hook and that personality is an OVERLAY on the agent's identity per Section 0 framing. Future audits should not confuse this with identity-replacement code.

### Why not `IntentMessage.params["personality_text"]` (Shape B)?

Shape B would resolve personality at dispatch time (router-side) and ship the rendered text as a param. Pros: receiver doesn't need the store. Cons: (1) duplicates effort if many messages flow through the same thread; (2) caches the personality text in flight — if the Captain runs `/personality clear` between dispatch and processing, the stale text still wins; (3) introduces a new params field that other consumers might need to ignore. Shape A wins on cache-coherence and AD-791a alignment.

The inline-callsign branch in `routers/chat.py` also dispatches `IntentMessage(intent="direct_message", thread_id=...)` per AD-791a, so the Shape A consumption automatically covers it — no separate wiring.

The acceptance test for this section is end-to-end: set a personality on a thread, send a turn, verify the system prompt that hit the LLM client contained the personality fragment.

---

## Section 4 — `ChatThreadStore` new methods

```python
# probos.threads.ChatThreadStore (add to existing class)
import json

def set_personality_override(self, thread_id: str, *, override: str | None) -> None:
    """Update the thread's personality_override column. None clears it."""
    with self._connect() as conn:
        conn.execute(
            "UPDATE chat_threads SET personality_override = ? WHERE id = ?",
            (override, thread_id),
        )
        conn.commit()

def set_title(self, thread_id: str, title: str, *, lock: bool = False) -> None:
    """Update the thread title. When lock=True, sets metadata.title_locked=true
    so subsequent auto-naming attempts skip this thread.

    Architect R1: read-modify-write of metadata uses BEGIN IMMEDIATE for race
    safety, matching the AD-791a get_or_create_default_for_agent pattern."""
    with self._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if lock:
                row = conn.execute(
                    "SELECT metadata FROM chat_threads WHERE id = ?", (thread_id,),
                ).fetchone()
                existing: dict = {}
                if row and row["metadata"]:
                    try:
                        existing = json.loads(row["metadata"]) or {}
                    except (json.JSONDecodeError, TypeError):
                        existing = {}
                existing["title_locked"] = True
                conn.execute(
                    "UPDATE chat_threads SET title = ?, metadata = ? WHERE id = ?",
                    (title, json.dumps(existing), thread_id),
                )
            else:
                conn.execute(
                    "UPDATE chat_threads SET title = ? WHERE id = ?",
                    (title, thread_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

def is_title_locked(self, thread_id: str) -> bool:
    """True if metadata.title_locked is set. Guards against JSON errors
    (architect R2 — defensive against TypeError from json.loads(None))."""
    with self._connect() as conn:
        row = conn.execute(
            "SELECT metadata FROM chat_threads WHERE id = ?", (thread_id,),
        ).fetchone()
        if not row or not row["metadata"]:
            return False
        try:
            return bool(json.loads(row["metadata"]).get("title_locked"))
        except (json.JSONDecodeError, TypeError, AttributeError):
            return False

def maybe_auto_name(self, thread_id: str, body: str, *, force: bool = False) -> ChatThread | None:
    """AD-794: idempotent auto-name (architect Required #2).

    Returns the renamed thread if naming fired; None if conditions weren't met.

    When ``force=False`` (default, used by the first-turn auto-trigger):
    - title is already locked, OR
    - title differs from the original participant-callsign (i.e., already
      named — either by prior auto-naming or operator rename without lock), OR
    - suggested title equals current title or is the fallback "New thread".
      → returns None.

    When ``force=True`` (used by POST /api/threads/{id}/auto-name endpoint to
    preserve existing always-rename behavior): only the lock check applies.
    The endpoint was always-rename pre-AD-794; force=True preserves that.

    Both modes respect the title_locked flag — manual operator rename is
    always authoritative.
    """
    from probos.threads.naming import suggest_title

    thread = self.get_thread(thread_id)
    if thread is None:
        return None
    if self.is_title_locked(thread_id):
        return None

    suggested = suggest_title(body)
    if not suggested or suggested == "New thread":
        return None

    if not force:
        # First-turn auto-trigger pre-conditions: single-participant default-thread,
        # title still in default state (matches participants[0] callsign).
        if len(thread.participants) != 1:
            return None
        if thread.title not in (thread.participants[0], "New thread"):
            return None

    if suggested == thread.title:
        return None
    self.set_title(thread_id, suggested, lock=False)
    return self.get_thread(thread_id)
```

The existing `POST /api/threads/{id}/auto-name` endpoint at `routers/threads.py:188` refactors to call `store.maybe_auto_name(thread_id, body, force=True)` to preserve its previous always-rename behavior. The new first-turn auto-trigger in `agent_chat` (Section 5) calls `store.maybe_auto_name(thread_id, body)` (default `force=False`) so it only fires for the actual first turn of a default-state thread.

---

## Section 5 — Auto-name trigger (AD-794)

With `maybe_auto_name()` centralizing the heuristic (Section 4), the first-turn trigger in chat handlers is a single call. **Ordering** (architect Required #3): runs AFTER the `/personality` guard and BEFORE the captain-message append. This guarantees:

- A `/personality` command never names the thread.
- The thread is renamed using the captain's substantive first message, not the slash-command syntax.
- The first captain message in the log already shows the renamed thread (UI loads the renamed thread + message together).

Wired in `agents.py::agent_chat`, after personality guard, before captain-message append:

```python
# AD-794: idempotent auto-name from the first turn body.
store.maybe_auto_name(thread.id, req.message)
thread = store.get_thread(thread.id) or thread  # refresh in case rename fired
```

The mirror call lands in `routers/chat.py` inline-callsign branch (~L281) using `stripped_body` (after @-mention strip) so `suggest_title` doesn't see the `@Ezri` prefix.

The existing `POST /api/threads/{id}/auto-name` endpoint at `routers/threads.py:188` should refactor to call `store.maybe_auto_name(...)` — the heuristic lives in one place.

The naming source-of-truth tradeoffs (heuristic vs LLM, when to retrigger) are addressed in `maybe_auto_name`'s pre-conditions. Operators who don't want the auto-name can immediately rename via the PATCH endpoint (Section 6) which sets `title_locked=true`.

---

## Section 6 — Manual rename locks the title (architect Required #1)

**v2 correction:** Section 6 v1 added a new `PATCH /api/threads/{id}/title` endpoint, but the existing `PATCH /api/threads/{thread_id}` at `routers/threads.py:121` already takes `UpdateThreadRequest` with a `title` field. v2 extends the existing endpoint rather than adding a sibling.

**Change** to `routers/threads.py` `UpdateThreadRequest`:

```python
class UpdateThreadRequest(BaseModel):
    title: str | None = None
    # ... existing fields preserved ...
    title_locked: bool | None = None   # NEW (AD-794): when True (operator-initiated rename),
                                       # set metadata.title_locked=true so auto-naming skips
                                       # this thread forever.
```

In the PATCH handler (existing logic at `routers/threads.py:121`):

```python
# Existing behavior: title update via store.update_thread(...) — keep as-is for the
# non-locking path (used by AD-794's internal auto-name flow which never sends title_locked).
# NEW: when title_locked is explicitly True in the request, route through set_title(lock=True)
# instead so the title update + metadata flag happen atomically.
if req.title is not None and req.title_locked is True:
    store.set_title(thread_id, req.title, lock=True)
elif req.title is not None:
    store.update_thread(thread_id, title=req.title)  # existing path

# ... handle other UpdateThreadRequest fields (pinned, archived, etc.) ...
```

UI hook to this endpoint lands in AD-792 sidebar (right-click → rename, sends `title_locked: true`). v1 just exposes the API. The internal first-turn auto-name from Section 5 calls `set_title(lock=False)` directly through the store and bypasses the API.

---

## Section 7 — Test coverage

Python tests (target ~10-12 total):

1. `test_personality_registry_lookup` — 3 sub-checks (hit, miss, list).
2. `test_handle_personality_command_set` — `/personality concise` sets the override.
3. `test_handle_personality_command_clear` — `/personality clear` removes the override.
4. `test_handle_personality_command_list` — `/personality` and `/personality list` return the registry.
5. `test_handle_personality_command_unknown` — `/personality wibble` returns error message + available list.
6. `test_agent_chat_personality_slash_command_does_not_dispatch_intent` — POST `/api/agent/{id}/chat` with `/personality formal`; assert IntentBus never dispatched a `direct_message` intent.
7. `test_agent_chat_auto_names_thread_on_first_turn` — fresh agent, first turn, assert title changes from callsign to derived.
8. `test_agent_chat_does_not_rename_after_lock` — `PATCH /api/threads/{id}/title`, then chat turn; title unchanged.
9. `test_agent_chat_does_not_rename_on_second_turn` — two turns; title only set after first.
10. `test_personality_overlay_in_dm_system_prompt` — set personality, chat turn, capture the LLM call's system text, assert overlay present. (Builder may need to mock or instrument the LLM client; reuse existing patterns in `tests/test_ad726_dm_reply_pipeline.py`.)
11. `test_rename_thread_endpoint_locks_title` — PATCH endpoint; assert `is_title_locked` returns True after.
12. `test_set_personality_override_persists` — direct store call; reopen store; verify column.

UI vitest (target ~3):

- `test_ProfileChatTab_personality_slash_command_renders_system_reply` — mock `/api/agent/{id}/chat` to return `{system: true, response: "Personality set to formal..."}`; assert system reply rendered (subtle styling vs agent reply).
- `test_ProfileChatTab_personality_does_not_clear_input_until_send` — UX: typing `/personality` stays in the input until Send.
- `test_useStore_threads_title_updates_on_response` — when chat response includes a new title, the local `chatThreads` map updates.

---

## Section 8 — Non-goals

- ❌ AD-794a: LLM-backed naming (forward marker; ships once we have usage data).
- ❌ AD-809a: full per-channel/per-agent personality matrix.
- ❌ `/personality` in `/api/chat` fan-out (AD-791g territory; per-thread state on a multi-agent thread has its own design Q).
- ❌ Personality UI affordance in HXI (slash-command works; visual indicator + dropdown lands with AD-792 sidebar).
- ❌ Forced re-render of in-memory `DmReplyContext` mid-turn (personality applies on NEXT turn after `/personality` runs — same as channel-wide bots like Slackbot).
- ❌ Operator-extensible personality registry via config (AD-809a forward marker).
- ❌ Multi-Captain personality scoping (everyone shares the registry for now).

---

## Section 9 — Acceptance criteria

1. `src/probos/cognitive/personality_registry.py` exists with 5 registry entries + `list_personalities()` + `resolve_personality_text()`.
2. `src/probos/cognitive/commands/personality_command.py` exists with `is_personality_command()` + `handle_personality_command()`.
3. `ChatThreadStore` has three new methods: `set_personality_override`, `set_title(lock=False/True)`, `is_title_locked`.
4. `PATCH /api/threads/{thread_id}` accepts a new optional `title_locked: bool | None = None` field. When `title_locked is True`, the title update goes through `set_title(lock=True)` which writes `metadata.title_locked=true` atomically. Existing PATCH behavior is unchanged when `title_locked` is omitted.
5. `/personality <name>` in a 1:1 chat:
   - Does NOT dispatch any IntentMessage.
   - Persists the resolved personality string in `chat_threads.personality_override`.
   - Returns a `{"system": true, "response": "Personality set to ..."}` body.
   - Appends both the captain command and the system reply to `chat_thread_messages`.
6. `/personality list`, `/personality`, and `/personality clear` work per spec.
7. `/personality unknown` returns an error message + available list, does not modify state.
8. First-turn auto-naming via `suggest_title(body)` fires when title equals the agent callsign and no message exists yet.
9. `PATCH /api/threads/{id}/title` locks the title; subsequent first-turn calls do NOT re-name.
10. Personality overlay is appended to the agent's system prompt at the LLM-call site found by Builder grep. Verified end-to-end by `test_personality_overlay_in_dm_system_prompt`.
11. 10-12 pytest + 3 vitest added. All existing tests still pass.
12. `npm run build` clean. `pytest -n auto` no new failures vs main.
13. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 10 — File touchpoints

| File | Change |
|---|---|
| `src/probos/cognitive/personality_registry.py` | NEW. Registry + lookup helpers. |
| `src/probos/cognitive/commands/personality_command.py` | NEW. Slash command parser + handler. |
| `src/probos/threads/__init__.py` | Add `set_personality_override`, `set_title(lock)`, `is_title_locked`, `maybe_auto_name(force=False)`. |
| `src/probos/routers/agents.py` | At `agent_chat` (line 1660), add `/personality` early-return guard BEFORE intent dispatch + `maybe_auto_name` trigger BEFORE captain-message append. Explicit ordering per Section 2. |
| `src/probos/routers/chat.py` | At inline-callsign branch (~L263, where `extract_callsign_mention` returns), add `/personality` guard using `message_text` (already @-stripped) + `maybe_auto_name` trigger for parity. |
| `src/probos/routers/threads.py` | Extend existing `UpdateThreadRequest` (L44) with `title_locked: bool | None = None`. Extend existing PATCH handler (L121) to route through `set_title(lock=True)` when `title_locked is True`. Refactor existing `POST /{id}/auto-name` (L188) to call `store.maybe_auto_name(..., force=True)` to preserve its always-rename behavior. |
| `src/probos/cognitive/cognitive_agent.py` (or the actual receiving agent class for `direct_message` intent, identified by Builder grep) | At the system-prompt assembly site, append `resolve_personality(store.get_thread(intent.thread_id), default="")` overlay when `intent.thread_id` is set. **No changes to `DmReplyContext`.** |
| `ui/src/components/profile/ProfileChatTab.tsx` | When response.system === true, render the turn as a system note (mirror any existing sidebar-system styling — dim italic acceptable). |
| `ui/src/store/useStore.ts` | When chat response carries an updated thread title, update `chatThreads` map (additive to AD-791a wiring). |
| `tests/test_ad809_personality.py` | NEW. ~7 tests for the personality slash command + registry + cognitive consumption. |
| `tests/test_ad794_auto_name.py` | NEW. ~3 tests for auto-naming + rename lock + force vs default behavior. |
| `tests/test_threads.py` | +2 tests for new ChatThreadStore methods. |
| `ui/src/__tests__/ProfileChatTab.personality.test.tsx` | NEW. 2 vitest. |
| `ui/src/__tests__/useStore.threadTitle.test.ts` | NEW. 1 vitest. |

---

## Section 11 — Forward markers

- **AD-794a** — LLM-backed naming. Replace the `suggest_title` heuristic with a fast-tier LLM call (3-6 words, branded title-case). Triggered as a background task after the first agent response lands so it doesn't block the turn. v1 heuristic stays as the fallback.
- **AD-809a** — Operator-extensible personality registry via config. Define a `cognitive.personality_registry: dict[str, str]` config field; merge with the built-in registry.
- **AD-809b** — Personality UI affordance in HXI sidebar (AD-792 dependency): visible badge on the thread row + dropdown picker.
- **AD-794b** — Auto-rename on topic drift. If a thread's recent N messages diverge semantically from the title, suggest a rename (Captain confirms). Pairs with AD-810 `/insights`.
- **AD-791g link** — `/personality` in main-chat threads needs design (per-Captain or per-active-agent?).

---

## Section 12 — Verify-first audit checklist (Builder pre-flight)

```
grep "suggest_title\|resolve_personality" src/probos/threads/naming.py
    → Expected: both helpers present (L29 + L58). No production consumers today.

grep -n "async def agent_chat" src/probos/routers/agents.py
    → Expected: L1660 (AD-791a wiring). Re-anchor before edit.

grep "extract_callsign_mention" src/probos/crew_profile.py
    → Expected: L836 `def extract_callsign_mention(text: str) -> tuple[str, str] | None`.
    → Used in routers/chat.py:263 via `callsign, message_text = mention`.

grep -n "is_personality_command\|/personality" src/probos
    → Expected: no matches (AD-809 adds them).

grep -n "set_personality_override\|set_title\|is_title_locked\|maybe_auto_name" src/probos/threads/__init__.py
    → Expected: no matches (AD-794 + AD-809 add them).

grep -n "composed = \|system_prompt=composed\|LLMRequest" src/probos/cognitive/cognitive_agent.py
    → Expected: `composed = ...` build at L2087-L2112, `system_prompt=composed` at L2180/2192/2198.
    → This is the AD-809 personality-overlay consumption site.

grep -n "self._runtime" src/probos/substrate/agent.py
    → Expected: L47 `self._runtime: Any = kwargs.get("runtime")`. Use underscore form in cognitive_agent.py too.

grep -n "@router\." src/probos/routers/threads.py
    → Expected: existing PATCH `/{thread_id}` at L121, POST `/{thread_id}/auto-name` at L188.
    → v3 extends both — does NOT add a new sibling endpoint.

grep "class ChatResponse" src/probos/api_models.py
    → Expected: L34, no `system: bool` field. The inline-callsign /personality branch returns a plain dict, NOT ChatResponse(...).

read src/probos/routers/threads.py L186-204
    → Confirm POST /{id}/auto-name is unconditionally rename today (no lock check).
      maybe_auto_name(force=True) preserves this behavior; force=False (default) adds the lock + single-participant + title-still-callsign pre-conditions.

read src/probos/routers/chat.py L255-348
    → Confirm inline-callsign branch returns `{"response": ..., "dag": None, "results": None, "thread_id": ...}` plain dict at L344-348. The /personality early-return matches this shape.

read src/probos/threads/naming.py in full
    → ~85 LOC; confirm both helpers' shapes match this spec's expectations.

read src/probos/routers/agents.py around L1660-L2089
    → Confirm AD-791a wiring is present (the slash-command guard goes just before intent dispatch; the auto-name trigger goes after thread resolution but before captain-message append).
```

If any of these don't match, stop and report — the spec needs revision.

---

## Section 13 — Scope estimate

~250-350 LOC net diff. ~12 files touched. One Builder commit at completion. **Single Builder dispatch.**
