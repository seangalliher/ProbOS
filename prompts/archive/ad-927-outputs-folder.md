# AD-927 — Outputs Folder: agent-authored `[ARTIFACT]` into the task room

**One-line:** Let a crew agent write a versioned text/markdown artifact into its task room from proactive output via an `[ARTIFACT name="..."]…[/ARTIFACT]` tag — stored in the existing `ArtifactStore` keyed to the room's `thread_id`, so it surfaces in the already-built `ArtifactDrawer` Output pane. No new UI.

**Status:** Ready to build
**Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-797 (ArtifactStore + ArtifactDrawer), AD-720/733-1 (AttachmentStore), AD-918/924 (AgentGroupChatService + `[GROUP_CHAT]` extractor pattern), AD-925 (auto-created task room — the agent is a participant of it)
**Estimated tests:** +11 pytest (`tests/test_ad927_outputs_folder.py`). No new vitest (no UI). No new EventType.
**Current highest committed AD: AD-926** (`2c988800`, **LOCAL-ONLY — 3 ahead of origin, not pushed**). origin/main = AD-924. Commit AD-927 locally; **do NOT push.**

---

## Problem

The task workspace room (AD-925) has a transcript (work log) and an Inputs read surface (AD-926). It has **no way for an agent to deposit a finished deliverable into the room.** The Output substrate already exists end-to-end — `ArtifactStore` (AD-797) is `thread_id`-keyed + versioned, bytes live in `AttachmentStore`, and the `ArtifactDrawer` UI already lists + views a thread's artifacts. What's missing is the **agent-facing write path**: a way for a crew agent, during its proactive turn, to say "this is my output" and have it land in the room.

AD-924 already established the exact pattern for an agent-facing action tag (`[GROUP_CHAT …]`): a module-level regex, an async `_extract_and_execute_*` method returning `(cleaned_text, actions)`, gated inline in `_extract_and_execute_actions` by rank. AD-927 mirrors it for artifacts.

**The crux — thread binding.** A proactive turn is **not inherently tied to a chat thread** (the agent's proactive think posts to the Ward Room, not the task room). So unlike `[GROUP_CHAT]` (where the agent names participants), the `[ARTIFACT]` extractor must *resolve* which task room to write into. There is no "current task room" in the proactive context, and the agent's current in-flight work-item is not cleanly available either (noted in AD-925). The honest, minimal, faithful binding is **participation-based**: resolve the agent's most-recently-active non-archived thread that has a `task_id` and lists the agent as a participant. This builds directly on AD-925 — the auto-created task room sets the crew child-assignees (including this agent) as participants. If no such room exists, honest-degrade: strip the tag, record a suppression, write nothing, never crash.

---

## Verified against live code (2026-06-08)

| Claim | Evidence |
|---|---|
| `ArtifactStore.add_version(*, thread_id, name, content_hash, mime, size_bytes, created_by) -> Artifact` is **SYNC**, keyword-only, auto-versions `MAX(version)+1`, `BEGIN IMMEDIATE` (BF-324) | [src/probos/artifacts/__init__.py](../src/probos/artifacts/__init__.py#L101-L174) |
| `ArtifactStore.list_thread_latest(thread_id)` = the drawer's listing | [src/probos/artifacts/__init__.py](../src/probos/artifacts/__init__.py#L201-L218) |
| **No one-call helper that takes bytes** — caller must write bytes to AttachmentStore then call `add_version` | whole file [src/probos/artifacts/__init__.py](../src/probos/artifacts/__init__.py#L80-L250) |
| REST `add_artifact` proves the two-step shape: client uploads bytes separately, then POSTs a pre-existing `content_hash` to `add_version` | [src/probos/routers/artifacts.py](../src/probos/routers/artifacts.py#L32-L43) |
| `AttachmentStore.write(content_hash, blob, mime, *, origin="chat_attachment") -> Path` is **async**, idempotent, **caller computes the sha256** | [src/probos/attachments/store.py](../src/probos/attachments/store.py#L39-L55), [src/probos/attachments/filesystem_store.py](../src/probos/attachments/filesystem_store.py#L198-L250) |
| **`agent_artifact`** is a dedicated, valid AD-797 origin (= "artifact bytes extracted from agent replies") and is the **most durable** origin (never age-reaped) | [src/probos/attachments/store.py](../src/probos/attachments/store.py#L16-L23), [src/probos/attachments/filesystem_store.py](../src/probos/attachments/filesystem_store.py#L84-L90) |
| `filesystem_store._path_for` requires a **64-char lowercase hex** content_hash (sha256 hexdigest satisfies this) | [src/probos/attachments/filesystem_store.py](../src/probos/attachments/filesystem_store.py#L181-L196) |
| `_GROUP_CHAT_PATTERN` module-level regex (the pattern to mirror) | [src/probos/proactive.py](../src/probos/proactive.py#L62-L72) |
| `_extract_and_execute_group_chats(agent, text) -> (cleaned, actions)`; strips via `_GROUP_CHAT_PATTERN.sub("", text)`; early-returns `text, []` when the service is `None` | [src/probos/proactive.py](../src/probos/proactive.py#L3980-L4034) |
| Gate site: AD-924 group-chat rank gate inside `_extract_and_execute_actions`, reads `getattr(rt.config.communications, 'group_chat_min_rank', 'commander')`, compares via `_RANK_ORDER_DM` | [src/probos/proactive.py](../src/probos/proactive.py#L2779-L2785) |
| `CommunicationsConfig` (where the new fields go): `dm_min_rank`, `group_chat_min_rank` precedent | [src/probos/config.py](../src/probos/config.py#L4606-L4610) |
| `ChatThreadStore.list_threads(*, include_archived=False, project_id=None, task_id=None, limit=100)` is **SYNC**, ordered `pinned DESC, last_active_at DESC`; **has a `task_id` filter but NO participant filter** (participants is a JSON column) | [src/probos/threads/__init__.py](../src/probos/threads/__init__.py#L244-L267) |
| `ChatThread.participants: list[str]`, `ChatThread.task_id: str \| None` | [src/probos/threads/__init__.py](../src/probos/threads/__init__.py#L88-L95) |
| `runtime.artifact_store` (line 484), `runtime.chat_thread_store` (line 450), `runtime.attachment_store` (`@property`, line 1482) are all public | [src/probos/runtime.py](../src/probos/runtime.py#L450), [src/probos/runtime.py](../src/probos/runtime.py#L484), [src/probos/runtime.py](../src/probos/runtime.py#L1482-L1489) |
| **UI already covered:** `ArtifactDrawer` subscribes to `useStore.activeThreadId` and calls `fetchThreadArtifacts(activeThreadId)` → `GET /api/artifacts/thread/{thread_id}` | [ui/src/components/artifacts/ArtifactDrawer.tsx](../ui/src/components/artifacts/ArtifactDrawer.tsx#L43-L97), [ui/src/components/artifacts/artifactApi.ts](../ui/src/components/artifacts/artifactApi.ts#L17-L19) |
| `agent.id` is the right attribute (GROUP_CHAT uses `creator_id=agent.id`) | [src/probos/proactive.py](../src/probos/proactive.py#L4003-L4007) |
| No `tests/test_ad927*` exists yet | `file_search tests/test_ad927*` → none |

---

## Solution overview

1. **Config (Section 1):** add three fields to `CommunicationsConfig` — `artifact_min_rank: str = "lieutenant"`, `artifact_max_per_turn: int = 3`, `artifact_max_bytes: int = 262144` (256 KiB). All defaulted; ProbOS boots zero-config.
2. **Extractor (Section 2):** add a module-level `_ARTIFACT_PATTERN`, a participation-based resolver `_resolve_agent_task_room`, and an async `_extract_and_execute_artifacts(agent, text) -> (cleaned, actions)` that mirrors `_extract_and_execute_group_chats` and performs the verified two-call write (`sha256` → `attachment_store.write(origin="agent_artifact")` → `artifact_store.add_version`).
3. **Gate (Section 3):** wire the extractor inline in `_extract_and_execute_actions`, immediately after the AD-924 group-chat gate, with a Lieutenant+ rank check using the existing `_RANK_ORDER_DM` comparison.

**No UI work.** The artifact appears in the existing `ArtifactDrawer` when the operator opens the room thread (the drawer keys off `activeThreadId`). **No new EventType. No REST change** (the existing `POST /api/artifacts` + `GET /api/artifacts/thread/{id}` already cover programmatic + read paths).

---

## Section 1 — Config fields

In [src/probos/config.py](../src/probos/config.py#L4606-L4610), extend `CommunicationsConfig`:

```python
class CommunicationsConfig(BaseModel):
    """Communications settings (AD-485)."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior
    group_chat_min_rank: str = "commander"  # AD-924: min rank to open an ad-hoc group chat: ensign|lieutenant|commander|senior
    # AD-927: agent-authored [ARTIFACT] -> task-room Output pane.
    artifact_min_rank: str = "lieutenant"  # min rank to write an artifact into a task room: ensign|lieutenant|commander|senior
    artifact_max_per_turn: int = 3         # anti-flood: honor at most this many [ARTIFACT] tags per proactive turn
    artifact_max_bytes: int = 262144       # anti-flood: reject artifact bodies larger than 256 KiB (oversized -> honest-degrade)
```

Rationale for the defaults:
- **`lieutenant`** — producing a work artifact is a normal deliverable (lower social weight than *convening* a multi-agent room, which is Commander+). Lieutenants already DM + reply; gating their final output at Commander would be inconsistent. Ensigns are excluded because they cannot think proactively anyway (existing comment in `_extract_and_execute_actions`).
- **`artifact_max_per_turn=3`** / **`artifact_max_bytes=262144`** — an artifact write is heavier than a message (bytes + a DB row). The body is text written to the content-addressable `AttachmentStore` (the correct shape — NOT inline in an `IntentMessage`, per the BF-265/#636 lesson), but a size cap is prudent defense-in-depth against a runaway LLM dump. Both are honest-degrade, not hard errors.

---

## Section 2 — Regex, resolver, and extractor (`src/probos/proactive.py`)

### 2a. Module-level pattern

Add next to `_GROUP_CHAT_PATTERN` ([proactive.py:62](../src/probos/proactive.py#L62)):

```python
# AD-927: agent-facing trigger to deposit a versioned artifact into the
# agent's task room (AD-925). Matches [ARTIFACT name="Final report"] body [/ARTIFACT].
# group(1)=name, group(2)=body (text/markdown written inline).
_ARTIFACT_PATTERN = re.compile(
    r'\[ARTIFACT\s+name="([^"]+)"\s*\]'  # 1=name
    r'(.*?)'                              # 2=body
    r'\[/ARTIFACT\]',
    re.DOTALL | re.IGNORECASE,
)
```

### 2b. Participation-based resolver

Add a private helper on the proactive engine (same class as `_extract_and_execute_group_chats`). This is the binding crux — keep it small and Tier-2 (return `None` on any failure):

```python
def _resolve_agent_task_room(self, agent_id: str):
    """AD-927: resolve the task room this agent should write an artifact into.

    A proactive turn carries no inherent thread. The faithful, minimal
    binding (builds on AD-925) is participation-based: the most-recently
    active non-archived thread that (a) has a ``task_id`` and (b) lists
    this agent as a participant. ``list_threads`` is already ordered
    ``last_active_at DESC``, so the first match is the right room.

    Returns the ``ChatThread`` or ``None`` (no resolvable task room ->
    the caller honest-degrades). AD-927a is the forward marker for a
    richer binding off the agent's current in-flight work item, which is
    not cleanly available in the proactive context today.
    """
    store = getattr(self._runtime, "chat_thread_store", None)
    if store is None:
        return None
    try:
        threads = store.list_threads(include_archived=False, limit=50)
    except Exception:
        logger.warning(
            "AD-927: list_threads failed resolving task room for %s",
            agent_id, exc_info=True,
        )
        return None
    for t in threads:
        if t.task_id is not None and agent_id in t.participants:
            return t
    return None
```

> Convention note: `ChatThreadStore` methods are SYNC and called directly from this async extractor path — this matches AD-924/925/926 (the existing extractors call `create_group_chat` / `get_thread` / `list_messages` synchronously). A single indexed `SELECT` does not warrant an executor hop.

### 2c. Extractor (mirror `_extract_and_execute_group_chats`)

Add immediately after `_extract_and_execute_group_chats` ([proactive.py:4034](../src/probos/proactive.py#L4034)):

```python
async def _extract_and_execute_artifacts(
    self, agent: Any, text: str,
) -> tuple[str, list[dict]]:
    """AD-927: Extract [ARTIFACT name="..."]body[/ARTIFACT] blocks and write
    each as a versioned artifact into the agent's task room (AD-925).

    Mirrors the AD-924 group-chat extractor: rank-gated by the caller,
    returns (cleaned_text, actions), strips the tag regardless of outcome.
    The body is text/markdown written to the content-addressable
    AttachmentStore (origin="agent_artifact", AD-797) then registered in
    ArtifactStore keyed to the room's thread_id, so it surfaces in the
    existing ArtifactDrawer. Honest-degrade (suppressed, no crash) when
    there is no resolvable task room, the body is empty/oversized, the
    per-turn cap is hit, or a store is unavailable.
    """
    import hashlib

    rt = self._runtime
    artifact_store = getattr(rt, "artifact_store", None)
    attachment_store = getattr(rt, "attachment_store", None)
    actions: list[dict] = []
    if artifact_store is None or attachment_store is None:
        return text, actions  # misconfigured runtime — leave text untouched (mirror GROUP_CHAT svc-None)

    # Anti-flood config (Tier-2 defaults if config absent).
    max_per_turn = 3
    max_bytes = 262144
    comms = getattr(getattr(rt, "config", None), "communications", None)
    if comms is not None:
        max_per_turn = getattr(comms, "artifact_max_per_turn", 3)
        max_bytes = getattr(comms, "artifact_max_bytes", 262144)

    room = self._resolve_agent_task_room(agent.id)
    produced = 0
    for m in _ARTIFACT_PATTERN.finditer(text):
        name = (m.group(1) or "").strip()
        body = (m.group(2) or "").strip()
        if not name or not body:
            actions.append({"type": "artifact_suppressed", "reason": "empty"})
            continue
        if room is None:
            actions.append({"type": "artifact_suppressed", "reason": "no_task_room"})
            continue
        blob = body.encode("utf-8")
        if len(blob) > max_bytes:
            actions.append({"type": "artifact_suppressed", "reason": "too_large", "name": name})
            continue
        if produced >= max_per_turn:
            actions.append({"type": "artifact_suppressed", "reason": "rate_limited", "name": name})
            continue
        content_hash = hashlib.sha256(blob).hexdigest()
        try:
            await attachment_store.write(
                content_hash, blob, "text/markdown", origin="agent_artifact",
            )
            artifact = artifact_store.add_version(
                thread_id=room.id,
                name=name,
                content_hash=content_hash,
                mime="text/markdown",
                size_bytes=len(blob),
                created_by=agent.id,
            )
        except Exception:
            logger.warning(
                "AD-927: artifact write failed for %s (name=%r)",
                getattr(agent, "id", "?"), name, exc_info=True,
            )
            actions.append({"type": "artifact_suppressed", "reason": "write_failed", "name": name})
            continue
        produced += 1
        actions.append({
            "type": "artifact",
            "thread_id": room.id,
            "name": name,
            "version": artifact.version,
            "artifact_id": artifact.id,
        })
        logger.info(
            "AD-927: %s wrote artifact %r v%d into task room %s",
            getattr(agent, "callsign", None) or agent.agent_type,
            name, artifact.version, room.id,
        )

    text = _ARTIFACT_PATTERN.sub("", text)
    return text, actions
```

---

## Section 3 — Gate wiring (`_extract_and_execute_actions`)

Immediately after the AD-924 group-chat gate ([proactive.py:2779-2785](../src/probos/proactive.py#L2779)), add the Lieutenant+ artifact gate, mirroring the existing `_RANK_ORDER_DM` comparison:

```python
        # --- Artifact output (Lieutenant+) --- AD-927
        art_min_rank_str = "lieutenant"
        if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
            art_min_rank_str = getattr(rt.config.communications, 'artifact_min_rank', 'lieutenant')
        art_min_rank = Rank[art_min_rank_str.upper()] if art_min_rank_str.upper() in Rank.__members__ else Rank.LIEUTENANT
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(art_min_rank):
            text, art_actions = await self._extract_and_execute_artifacts(agent, text)
            actions_executed.extend(art_actions)
```

> `rank`, `Rank`, and `_RANK_ORDER_DM` are already in scope in this method (used by the DM and group-chat gates above). Do not redeclare them.

---

## Tests — `tests/test_ad927_outputs_folder.py` (~11)

Per **BF-287**, use **real** stores (no MagicMock at the substrate boundary): real `ArtifactStore`, real `FilesystemAttachmentStore`, real `ChatThreadStore`, real `TrustNetwork`/registry stub only where a non-substrate dependency is needed. Construct the proactive engine the way the existing proactive tests do (follow the closest sibling: `tests/test_ad924_*` or the nearest `test_*proactive*` that builds the engine). Pass a `Config()` (or `SystemConfig()`) with real `communications` so the rank/anti-flood reads hit reality — do **not** stub `config`.

Helper: a small fixture that (1) builds the three real stores on `tmp_path`, (2) creates a task room via `chat_thread_store.create_thread(title=..., participants=[agent_id], task_id="task-1")`, and (3) wires them onto a runtime stub exposing `artifact_store`, `attachment_store`, `chat_thread_store`, `config`, plus whatever `_extract_and_execute_actions` already requires (`ward_room`, `trust_network`, `ward_room_router`, etc. — copy the minimal stub shape from the AD-924 test).

Required cases:

1. **`test_artifact_written_to_task_room`** — a Lieutenant+ agent that is a participant of a `task_id` room emits `[ARTIFACT name="report"]# Final\nbody[/ARTIFACT]`; assert (a) the returned `actions` contains a `{"type":"artifact", "thread_id": <room.id>, "name":"report", "version":1}`, (b) `artifact_store.list_thread_latest(room.id)` returns one artifact named `report`, (c) `await attachment_store.read(content_hash)` returns the UTF-8 body bytes, (d) the tag is stripped from the cleaned text.
2. **`test_second_artifact_increments_version`** — emit `[ARTIFACT name="report"]…[/ARTIFACT]` twice (two turns or two tags across the cap); assert versions `1` then `2`, `supersedes` chained, and `list_thread_latest` shows `version=2`.
3. **`test_tag_stripped_from_posted_text`** — surrounding prose `"Here it is [ARTIFACT name=x]body[/ARTIFACT] done"` → cleaned text has no `[ARTIFACT]`/`[/ARTIFACT]` and retains the prose.
4. **`test_no_task_room_honest_degrades`** — agent participates in **no** `task_id` room (only a plain thread, or none); emit the tag; assert `actions` has `{"type":"artifact_suppressed","reason":"no_task_room"}`, **no** artifact row, **no** exception, tag stripped.
5. **`test_rank_gated_out_below_threshold`** — an Ensign-trust agent (or set `artifact_min_rank="commander"` and use a Lieutenant); assert `_extract_and_execute_artifacts` is **not** reached via the gate (no artifact written, tag NOT stripped by the artifact path — it remains because the gate skipped). Drive this through `_extract_and_execute_actions` (or the public `execute_actions` wrapper) so the gate is exercised, not the extractor directly.
6. **`test_empty_body_suppressed`** — `[ARTIFACT name="x"][/ARTIFACT]` (or whitespace body) → `{"type":"artifact_suppressed","reason":"empty"}`, no write, tag stripped.
7. **`test_oversized_body_suppressed`** — set `artifact_max_bytes` low (e.g. 10) and emit a longer body → `{"reason":"too_large"}`, no write, tag stripped.
8. **`test_per_turn_cap_enforced`** — set `artifact_max_per_turn=1`, emit two distinct `[ARTIFACT]` tags in one text → first writes (`type":"artifact"`), second `{"reason":"rate_limited"}`; only one artifact row exists; both tags stripped.
9. **`test_malformed_tag_left_intact`** — `[ARTIFACT]body[/ARTIFACT]` (missing `name="..."`) does not match `_ARTIFACT_PATTERN` → no action, no crash, text unchanged by the artifact path.
10. **`test_resolver_picks_most_recent_participating_task_room`** — two `task_id` rooms with the agent as participant, the second created/updated more recently; assert the artifact lands in the most-recently-active one (resolver honors `last_active_at DESC`). Also assert a room where the agent is **not** a participant is ignored.
11. **`test_store_unavailable_degrades`** — runtime stub with `artifact_store=None` (or `attachment_store=None`); emit the tag; assert no crash, no action, returned text unchanged (mirrors the GROUP_CHAT `svc is None` early return).

Run gate:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad927_outputs_folder.py -v -n 0 -p no:cacheprovider
```
Blast radius (must stay green):
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "proactive or artifact or thread or chat or group or attachment" -q -n 0 -p no:cacheprovider
```

---

## What this does NOT change / Do NOT build

- **No new artifact UI.** The AD-797 `ArtifactDrawer` already lists + views a thread's artifacts off `activeThreadId`. Do not add or modify any `ui/` component or vitest. (A drawer mount inside a dedicated 3-pane room view is **AD-929** — out of scope.)
- **No binary `[ARTIFACT]` upload in v1.** The tag path is text/markdown only (`mime` hardcoded). Binary artifacts (images/PPTX) already have a path: upload bytes via the existing AttachmentStore + `POST /api/artifacts` with the pre-uploaded `content_hash`. Note this; do not add a base64/binary tag (that is a later AD).
- **No unified 3-pane workspace view** (transcript + Inputs + Outputs) — **AD-929**.
- **No show-your-work status protocol** (standing-order progress/final-result messages) — **AD-928**.
- **No new REST route, no new EventType, no new ArtifactStore/AttachmentStore method.** Use the verified existing APIs only.
- **No richer work-item binding.** v1 resolves the task room by participation. The agent's current in-flight work-item binding is the **AD-927a** forward marker; do not invent it.
- Do not change `BaseAgent`, `IntentMessage`, the intent bus, or any consensus/trust path.

---

## Tracking

- **PROGRESS.md** — add an AD-927 CLOSED line: outputs folder (`[ARTIFACT]` tag → participation-bound task room → ArtifactStore; Lieutenant+; +11 tests; local commit, not pushed).
- **docs/development/roadmap.md** — flip AD-927 in the Task Workspace Rooms table from planned → done; add the AD-927a forward marker (richer current-work-item binding).
- **DECISIONS.md** — append AD-927 with the participation-based binding rationale and the AD-927a deferral.
- Session-memory epic file already records the design.

---

## Acceptance criteria

1. Three new defaulted fields on `CommunicationsConfig`; ProbOS boots zero-config (no YAML change required).
2. `_ARTIFACT_PATTERN`, `_resolve_agent_task_room`, and `_extract_and_execute_artifacts` added to `proactive.py`, mirroring the AD-924 group-chat structure; extractor returns the standard `(cleaned_text, actions)` shape and strips the tag on every path that reaches the `.sub("")`.
3. Gate wired after the AD-924 group-chat gate, Lieutenant+ via `_RANK_ORDER_DM`.
4. The two-call write path is exactly: `hashlib.sha256(blob).hexdigest()` → `await attachment_store.write(hash, blob, "text/markdown", origin="agent_artifact")` → `artifact_store.add_version(...)` (sync). No phantom one-call helper.
5. Artifact lands on `room.id` (the participation-resolved task room's `thread_id`) and is therefore visible via `GET /api/artifacts/thread/{room.id}` and the existing `ArtifactDrawer`.
6. Honest-degrade (suppressed action, no crash, tag stripped) for: no task room, empty body, oversized body, per-turn cap, write failure. Store-unavailable early-returns text untouched.
7. `tests/test_ad927_outputs_folder.py` green (~11 tests, BF-287 real stores); blast-radius gate green; no UI/vitest change.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Commit locally (`AD-927: …`); **do not push**. Report HEAD short-SHA and ahead-of-origin count.
