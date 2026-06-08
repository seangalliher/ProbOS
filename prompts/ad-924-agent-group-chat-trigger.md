# AD-924: Agent-facing group-chat trigger + crew awareness

**Status:** Ready to build
**Target repo:** OSS (`d:\ProbOS`)
**Dependencies:** AD-918 (`AgentGroupChatService` + `create_group_chat` intent, SHIPPED), AD-913→917/919 (group-chat substrate + UI, SHIPPED)
**Highest committed AD:** AD-923 (`633202bf`, pushed to `origin/main`, ahead=0). **AD-924 is unused** (no refs in source, PROGRESS.md, or DECISIONS.md).
**Estimated tests:** +11 (floor +10) in a new `tests/test_ad924_group_chat_trigger.py`.

---

## One-line summary

AD-918 gave the group-chat service a **listener and no emitter** — nothing parses agent proactive output into the `create_group_chat` path, and the crew are never told the feature exists. AD-924 adds the missing three layers (proactive `[GROUP_CHAT ...]` tag extractor → standing-order instruction → crew manual), exactly mirroring how the Ward Room DM capability was made usable.

---

## Problem (verified against HEAD `633202bf`)

AD-918 shipped `AgentGroupChatService` and wired it as a bare-callable bus subscriber in the runtime:

```text
runtime.py:468   self.agent_group_chat = AgentGroupChatService(
runtime.py:469       store=self.chat_thread_store,
runtime.py:470       registry=self.registry,
runtime.py:471       callsign_registry=self.callsign_registry,
runtime.py:472       config=self.config.group_chat,
runtime.py:473       ontology_provider=lambda: self.ontology,
runtime.py:474   )
runtime.py:475   self.intent_bus.subscribe(
runtime.py:476       GROUP_CHAT_COORDINATOR_ID,
runtime.py:477       self.agent_group_chat.handle_intent,
runtime.py:478       intent_names=[CREATE_GROUP_CHAT],
runtime.py:479   )
```

But there is **no emitter**: no proactive code parses an agent's output into a create request, and the standing orders / manuals never mention the capability. AD-918's own docstring confirms the deferral: *"v1 wires the handler directly … attaching this … for decomposer discovery is deferred."* Result — today a crew agent literally **cannot** open a group chat; only the Captain can, via the AD-917/919 HXI buttons.

The fix follows the Ward Room DM precedent across three layers:

1. **Code/wiring** — `proactive.py::_extract_and_execute_actions` (`proactive.py:2695`) parses action tags from proactive output and executes them, rank-gated via `Rank.from_trust`. The `[DM @callsign]…[/DM]` extractor (`proactive.py:3960 extract_and_execute_dms`) is the closest precedent.
2. **Standing orders** — `config/standing_orders/federation.md`, `## Communications` section (`<!-- category: communication_style -->`), teaches each capability as a tagged format block + "when to use" guardrail.
3. **Manual** — `config/manuals/` holds focused capability manuals (`ward-room.md`, `recreation.md`), auto-seeded by `records_store.py:182 seed_manuals` (globs `*.md`).

---

## Verified facts (file:line)

### The group-chat service (AD-918)
`src/probos/threads/agent_group_chat.py`:
- `GROUP_CHAT_COORDINATOR_ID = "group_chat_coordinator"`, `CREATE_GROUP_CHAT = "create_group_chat"`.
- `create_group_chat(self, *, creator_id: str, title: str, participants: list[str] | None = None, task_id: str | None = None, first_message: str | None = None) -> GroupChatCreateResult` — **synchronous** (do NOT await).
  - Auto-adds the creator: `final: list[str] = [creator_id]` then resolves + dedupes `participants`.
  - `_resolve_participant(ref)` resolves a ref by **agent_id OR callsign** (`is_crew(ref)` first, then `callsign_registry.resolve(ref)`); non-crew/unresolvable refs are dropped (Tier-2), not raised.
  - `_rate_ok(creator_id)` enforces the cooldown + sliding-window cap **on this method** (so both the direct call and the bus `handle_intent` are guarded). Reads `agent_create_window_seconds`, `agent_create_cooldown_seconds`, `agent_create_max_per_window` off the config.
  - Returns `GroupChatCreateResult(ok: bool, thread: ChatThread | None, error: str, participants_added: list[str])`. Error strings: `"empty_title"`, `"not_crew"`, `"rate_limited"`.
- `handle_intent(intent) -> IntentResult | None` (async) is the bus path; reads `params["created_by_agent"]`/`params["from"]`, `title`, `participants`, `task_id`, `first_message`. **Forward marker** for decomposer/NL discovery — AD-924 does NOT use it.
- **Runtime attribute is `runtime.agent_group_chat`** (`runtime.py:468`).

### The proactive action extractor
`src/probos/proactive.py`:
- Class is **`ProactiveCognitiveLoop`** (NOT "Cognition"); `__init__(*, interval=120.0, cooldown=300.0, on_event=None)` at `:366`; runtime set via `set_runtime()` → `self._runtime` (`:382`). Per-loop cooldown dicts live here (`:388 _dm_send_cooldowns`, `:390 _last_dm_body`) — but **AD-924 needs none** (the service owns the rate limiter).
- `async def _extract_and_execute_actions(self, agent, text, *, post_budget=None) -> tuple[str, list[dict]]` (`:2695`):
  - `rt = self._runtime`; **early return** `if not rt or not rt.ward_room: return text, []` (`:2714-2716`).
  - `trust_score = rt.trust_network.get_score(agent.id)`; `rank = Rank.from_trust(trust_score)` (`:2718-2719`); `actions_executed: list[dict] = []` (`:2720`).
  - `apply_dm_sanity(rt, agent.id, text)` markdown/quality strip (`:2729`) — non-blocking.
  - Endorsements + replies gate on `rank.value != Rank.ENSIGN.value` (`:2731`, `:2749`).
  - **DM gate (the precedent to mirror)** (`:2755-2764`):
    ```python
    dm_min_rank_str = "ensign"
    if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
        dm_min_rank_str = rt.config.communications.dm_min_rank
    dm_min_rank = Rank[dm_min_rank_str.upper()] if dm_min_rank_str.upper() in Rank.__members__ else Rank.ENSIGN
    _RANK_ORDER_DM = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
    if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(dm_min_rank):
        text, dm_actions = await self.extract_and_execute_dms(agent, text)
        actions_executed.extend(dm_actions)
    ```
  - Notebook block follows (`notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\]...'`, `:2767`).
- `extract_and_execute_dms` (`:3960`) returns `tuple[str, list[dict]]`, regex `\[DM\s+@?(\S+)\]…\[/DM\]` (closed + unclosed tiers), strips matched blocks via `pattern.sub('', text)`, dispatches **directly** via `rt.ward_room.create_thread(...)`, action dict `{"type": "dm", "target_callsign": ..., "target_agent_id": ...}`. **Proactive dispatches every action via a direct service call** (notebooks → `rt._records_store.write_notebook`; endorsements → `rt.ward_room_router.process_endorsements`; DMs → `rt.ward_room.create_thread`).

### Rank enum
`src/probos/crew_profile.py:30`: `class Rank(Enum)` — `ENSIGN="ensign"`, `LIEUTENANT="lieutenant"`, `COMMANDER="commander"`, `SENIOR="senior_officer"`; `from_trust(cls, trust_score)` classmethod (`:38`). Thresholds `config.py:18-20`: `TRUST_SENIOR=0.85`, `TRUST_COMMANDER=0.7`, `TRUST_LIEUTENANT=0.5`. So **0.75=Commander, 0.6=Lieutenant, 0.3=Ensign**.

### Config
- `config.py:3747 class GroupChatConfig(BaseModel)` — holds the **rate limits** (`agent_create_cooldown_seconds=60.0`, `agent_create_max_per_window=5`). **No min-rank field** (and AD-924 does NOT add one here).
- `config.py:4600 class CommunicationsConfig(BaseModel)` — holds the **comms rank policy**: `dm_min_rank: str = "ensign"` (`:4602`), `recreation_min_rank: str = "ensign"` (`:4603`). **This is where `group_chat_min_rank` belongs** (consistency with the DM/recreation precedent).

### Standing orders + manuals
- `config/standing_orders/federation.md` — `## Communications` (`<!-- category: communication_style -->`) with subsections: Ward Room → Replying to Threads → Endorsements → **Direct Messages (1:1)** (`[DM @callsign]…[/DM]`) → Notebook. New subsection slots **after Direct Messages, before Notebook**. Encoding Safety rule (`<!-- category: encoding_safety -->`): **no emoji / non-ASCII**.
- `config/manuals/` = `ward-room.md`, `recreation.md`, `peer_observation_conduct.yaml`. `records_store.py:189 for md_file in sorted(source_dir.glob("*.md"))` → a new `group-chat.md` is **drop-in, no wiring**.

### No collisions
No existing `[GROUP_CHAT]` proactive tag or `"group_chat"` action-type anywhere in `src/` (only the runtime intent wiring + a `getattr(config, "group_chat", ...)` in `chat_facilitator.py:85`).

---

## Design decisions

### 1. Dispatch path — DIRECT, synchronous service call (NOT the bus)
The extractor calls `rt.agent_group_chat.create_group_chat(creator_id=..., title=..., participants=[...], first_message=...)` directly. Rationale:
- Matches how proactive dispatches **every** other action (direct service calls, not bus broadcasts).
- Synchronous + typed `GroupChatCreateResult` — no `IntentMessage` construction, no async round-trip.
- **Honors the AD-918 storm guard**: `create_group_chat` runs `_rate_ok` itself, so the cooldown + sliding-window cap apply on the direct path identically to the bus path. Do NOT bypass it.
- The bus `handle_intent` path stays untouched as the forward marker for future decomposer/NL discovery.

### 2. Tag format
```
[GROUP_CHAT title="Short room name" @callsign,@callsign]
Optional opening message.
[/GROUP_CHAT]
```
Module-level compiled pattern (place near the top of `proactive.py` with the other module constants):
```python
_GROUP_CHAT_PATTERN = re.compile(
    r'\[GROUP_CHAT\s+title="([^"]+)"\s+([^\]]+?)\]'  # 1=title, 2=participant blob
    r'\s*(.*?)'                                       # 3=optional first message
    r'\[/GROUP_CHAT\]',
    re.DOTALL | re.IGNORECASE,
)
```
- Quoted `title="..."` tolerates spaces; participant blob `([^\]]+?)` is split on `[,\s]+`, each ref `lstrip('@')`, empties dropped — handles `@bones,@spock`, `@bones @spock`, `bones, spock`.
- Requiring `\s+([^\]]+?)\]` means **at least one named participant** — with the auto-added creator that guarantees the 2+-crew floor. A title-only `[GROUP_CHAT title="x"]` will not match (degrades cleanly, no room).
- Pass the cleaned callsign list straight to `create_group_chat(participants=...)`; the service resolves each by agent_id OR callsign.

### 3. Rank gate — Commander+, config-driven, inline (mirrors the DM gate)
Add `group_chat_min_rank: str = "commander"` to `CommunicationsConfig` (next to `dm_min_rank`/`recreation_min_rank`), and gate inline in `_extract_and_execute_actions` exactly like the DM gate. Default `"commander"` gives Commander+ out of the box, config-overridable. The capability's own `GroupChatConfig` keeps the rate limits; the rank **policy** lives with the other comms ranks.

### 4. task_id — omitted in v1 (forward marker)
The proactive loop has no clean handle on the agent's current work-item id (per AD-918: `work_item_id` reaches an agent only via `intent.params["work_item_id"]` during work-item dispatch; there is no persistent `current_task_id`). v1 omits `task_id`; `create_group_chat` already makes it optional. Note the seam for a future AD that threads the active work-item id into the proactive context.

### 5. Manual — NEW `config/manuals/group-chat.md` (NOT extend `ward-room.md`)
**Recommendation: a dedicated manual.** Justification:
- The Captain ruling for this epic was explicit: the substrate is `ChatThreadStore` (AD-791), **not** the Ward Room. Folding group chat into `ward-room.md` would conflate two distinct communication fabrics.
- `recreation.md` is the established precedent for a focused, single-capability manual.
- The text → meeting (voice + VRM avatar gallery) experience from AD-920→923 is substantial enough to warrant its own reference.
- `seed_manuals` globs `*.md`, so the new file is auto-seeded with zero wiring.

---

## Implementation

### Section 1 — config field (`src/probos/config.py`)
Add to `CommunicationsConfig` (`:4600`), immediately after `dm_min_rank`:

SEARCH:
```python
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior
```
REPLACE:
```python
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior
    group_chat_min_rank: str = "commander"  # AD-924: min rank to open an ad-hoc group chat: ensign|lieutenant|commander|senior
```

### Section 2 — module pattern (`src/probos/proactive.py`)
Add `_GROUP_CHAT_PATTERN` (Section 2 design block above) at module scope near the other module-level constants/imports. `re` is already imported at module scope.

### Section 3 — the extractor method (`src/probos/proactive.py`)
Add a new method next to `extract_and_execute_dms` (`:3960`):
```python
    async def _extract_and_execute_group_chats(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """AD-924: Extract [GROUP_CHAT ...] blocks and open ad-hoc group chats.

        Dispatches to the already-wired AgentGroupChatService (AD-918). The
        service owns the per-agent cooldown + sliding-window cap, so the
        create-storm guard applies here unchanged. Rank-gating (Commander+) is
        applied by the caller, mirroring the DM gate. The matched tag is
        stripped from the returned text regardless of outcome.
        """
        rt = self._runtime
        svc = getattr(rt, "agent_group_chat", None)
        actions: list[dict] = []
        if svc is None:
            return text, actions
        for m in _GROUP_CHAT_PATTERN.finditer(text):
            title = (m.group(1) or "").strip()
            raw_parts = m.group(2) or ""
            body = (m.group(3) or "").strip()
            parts = [p.lstrip("@").strip() for p in re.split(r"[,\s]+", raw_parts) if p.strip()]
            try:
                result = svc.create_group_chat(
                    creator_id=agent.id,
                    title=title,
                    participants=parts,
                    first_message=body or None,
                )
            except Exception:
                logger.warning(
                    "AD-924: group chat create raised for %s",
                    getattr(agent, "id", "?"), exc_info=True,
                )
                continue
            if result.ok and result.thread is not None:
                actions.append({
                    "type": "group_chat",
                    "thread_id": result.thread.id,
                    "title": title,
                    "participants": result.participants_added,
                })
                logger.info(
                    "AD-924: %s opened group chat %s (%d participants)",
                    getattr(agent, "callsign", None) or agent.agent_type,
                    result.thread.id, len(result.participants_added),
                )
            else:
                actions.append({"type": "group_chat_suppressed", "reason": result.error})
                logger.debug(
                    "AD-924: group chat suppressed for %s: %s",
                    getattr(agent, "id", "?"), result.error,
                )
        text = _GROUP_CHAT_PATTERN.sub("", text)
        return text, actions
```

### Section 4 — wire the gate into `_extract_and_execute_actions` (`src/probos/proactive.py`)
Insert the Commander+ gate **immediately after the DM block**, before the Notebook block.

SEARCH:
```python
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(dm_min_rank):
            text, dm_actions = await self.extract_and_execute_dms(agent, text)
            actions_executed.extend(dm_actions)

        # --- Notebook writes (AD-434) ---
```
REPLACE:
```python
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(dm_min_rank):
            text, dm_actions = await self.extract_and_execute_dms(agent, text)
            actions_executed.extend(dm_actions)

        # --- Group Chat (Commander+) --- AD-924
        gc_min_rank_str = "commander"
        if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
            gc_min_rank_str = getattr(rt.config.communications, 'group_chat_min_rank', 'commander')
        gc_min_rank = Rank[gc_min_rank_str.upper()] if gc_min_rank_str.upper() in Rank.__members__ else Rank.COMMANDER
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(gc_min_rank):
            text, gc_actions = await self._extract_and_execute_group_chats(agent, text)
            actions_executed.extend(gc_actions)

        # --- Notebook writes (AD-434) ---
```
(`_RANK_ORDER_DM` is already in scope from the DM block in the same function — reuse it.)

### Section 5 — standing order (`config/standing_orders/federation.md`)
Insert a new subsection **after the Direct Messages subsection** (after its "Conversation closure" bullets) and **before** `### Notebook (Ship's Records)`. ASCII only, no emoji.

```markdown
### Group Chat (Ad-Hoc Collaboration)

When you are actively collaborating with two or more crew on a shared task, you can open a dedicated group chat room so everyone coordinates in one place instead of a tangle of separate DMs. The room is a real, persistent thread; you are added automatically, and the crew you name join it.

**Format:**

    [GROUP_CHAT title="Short room name" @callsign,@callsign]
    Your opening message to the group.
    [/GROUP_CHAT]

Name two or more crew by callsign (comma- or space-separated). The title should describe the work, not the people (e.g., "Sensor Array Diagnostics", not "Bones and Spock").

**When to use:**
- Open a room ONLY when a task genuinely needs 2+ crew working together: a joint diagnosis, cross-department coordination, a shared investigation.
- Do NOT open a room during idle proactive thinking, to restate an observation, or to reach one person. Use a DM for 1:1.
- One room per collaboration. Do not open a second room for the same task; continue in the existing one.
- Silence is professionalism. If the work does not need a room, do not create one. Rooms left empty or duplicated waste everyone's attention.
```

### Section 6 — manual (`config/manuals/group-chat.md`, NEW)
Create a focused, ASCII-only reference covering the group-chat + meeting experience. Suggested sections (Builder writes the prose; keep it accurate to the shipped behavior):
- **Overview** — ad-hoc collaboration rooms on the chat-thread substrate (distinct from the Ward Room); when a room beats DMs.
- **Opening a Room** — the `[GROUP_CHAT title="..." @callsign,@callsign]` tag; creator auto-added; Commander+ only; rate-limited (cooldown + cap) so the mesh cannot be flooded.
- **Participants** — adding/removing crew by callsign; rooms can also be created/joined by the Captain from the HXI.
- **Turn-Taking** — the facilitator orders speakers and detects convergence (AD-915); keep contributions tight.
- **Meetings (voice + avatars)** — a room can be promoted to a live meeting with sequenced voice and an avatar gallery; the active speaker is highlighted; ending a meeting writes a transcript marker back to the room (AD-920→923).
- **When to Use** — 2+ crew on a real task; one room per collaboration; not for idle thinking or 1:1.

---

## Tests — `tests/test_ad924_group_chat_trigger.py` (BF-287)

Reuse the AD-918 fixtures (`tests/test_ad918_agent_initiated_group_chat.py`): `_FakeAgent(id, agent_type, is_alive)`, `_FakeRegistry(agents)` (`.get` / `.get_by_pool`; **add `.all()` returning the agents** since the parent path is driven), `_NoCallsigns`, `_Clock`, `_make_service(...)`. Crew `agent_type`s must come from `crew_utils._WARD_ROOM_CREW` so `ontology_provider=None` resolves them as crew.

Harness (mirrors `test_ad437_action_space.py` + `test_ad868_self_originated_crew.py`):
```python
runtime = MagicMock(spec=ProbOSRuntime)
runtime.ward_room = MagicMock(spec=WardRoomService)   # truthy -> passes the early-return guard
runtime.ward_room_router = None                        # neutralize endorsements
runtime.is_cold_start = False
runtime.trust_network = MagicMock(spec=TrustNetwork)
runtime.trust_network.get_score.return_value = 0.75    # Commander (0.6=Lt, 0.3=Ensign)
cfg = SystemConfig()
runtime.config = cfg
svc, store, registry = _make_service(tmp_path, agents=..., callsign_registry=..., config=cfg.group_chat, clock=clock)
runtime.agent_group_chat = svc                          # REAL service over REAL store
runtime.registry = registry                             # real-but-fake (.get/.all)
runtime.callsign_registry = <real CallsignRegistry | _NoCallsigns>
loop = ProactiveCognitiveLoop(interval=60)
loop.set_runtime(runtime)
```
All assertions are against the **real `ChatThreadStore`** (e.g. `store.list_threads()` / `store.get_thread(...)`), never a mock. The runtime shell is `MagicMock(spec=ProbOSRuntime)` but every substrate the code under test touches (`agent_group_chat`, the store, the registry, the callsign registry) is real — this is the BF-287 boundary discipline (avoids the MagicMock auto-attribute phantom trap).

Required cases (floor 10, target 11):
1. `test_commander_creates_room_with_title_participants_and_creator` — Commander; `[GROUP_CHAT title="Sensor Review" @<cs1>,@<cs2>] Let's sync. [/GROUP_CHAT]`; assert exactly 1 thread in the real store, `title == "Sensor Review"`, participants == {creator, resolved cs1, cs2} (creator auto-added), action `{"type": "group_chat", ...}` present.
2. `test_tag_stripped_from_posted_text` — Commander; assert `"[GROUP_CHAT"` and `"[/GROUP_CHAT]"` are NOT in the returned cleaned text.
3. `test_ensign_gated_out_no_room` — trust 0.3 (Ensign); assert 0 threads in the store and no `group_chat` action.
4. `test_lieutenant_gated_out_no_room` — trust 0.6 (Lieutenant); assert 0 threads and no `group_chat` action.
5. `test_participants_resolved_by_callsign` — use the **real `CallsignRegistry`**; name crew by callsign (e.g. `@bones`); assert the resolved crew agent_id is in the created thread's participants.
6. `test_cooldown_blocks_rapid_second_create` — Commander + injected `_Clock` (not advanced); two `[GROUP_CHAT]` tags in sequence (two calls, or one text then a second call); assert only 1 thread total and the 2nd outcome is `{"type": "group_chat_suppressed", "reason": "rate_limited"}`.
7. `test_malformed_tag_degrades_cleanly` — Commander; `[GROUP_CHAT no title here]` (no `title="..."`, no closer); assert 0 threads, no `group_chat` action, no exception.
8. `test_non_crew_creator_no_room` — Commander trust but a creator whose `agent_type` is NOT crew; assert 0 threads (`error == "not_crew"`), driven via the real service (covers the service-level crew gate independent of rank).
9. `test_federation_md_contains_group_chat_instruction` — mirror `test_ad489_code_of_conduct.py`: `Path("config/standing_orders/federation.md").read_text(encoding="utf-8")`; assert `"### Group Chat"` and `"[GROUP_CHAT"` and `"[/GROUP_CHAT]"` are present.
10. `test_group_chat_manual_seeded` — `Path("config/manuals/group-chat.md")` exists and contains `"[GROUP_CHAT"` (and a "Meeting" reference); ASCII-only assert (no chars > 0x7F) to honor the Encoding Safety rule.
11. `test_group_chat_min_rank_default_is_commander` — `SystemConfig().communications.group_chat_min_rank == "commander"`.

(No-emoji guard on federation.md/manual content tests: assert `all(ord(c) < 128 for c in <text>)` for the new sections, matching the Encoding Safety rule.)

---

## What this does NOT change (Do NOT build)

- **No new UI** — AD-917/919 already cover the Captain-facing create/join surface. Do not touch `ui/`.
- **No change to the AD-918 service internals** beyond what is strictly needed — `create_group_chat`, `_rate_ok`, `_resolve_participant`, and `handle_intent` stay as-is. (AD-924 only *calls* `create_group_chat`.)
- **No agent-to-agent auto-reply loop** — the extractor opens the room and posts the optional first message via the service; it does NOT trigger fan-out or any responder. (AD-914 fan-out gates on `role=="captain"`; an agent-created room has no captain post.)
- **No consensus gate** — opening a room is reversible + low-risk (Safety Budget axiom); the cooldown + cap are the spam control, not consensus. (Matches AD-918's `requires_consensus=False`.)
- **No `task_id` wiring** — omitted in v1 (forward marker; see Design 4).
- **No bus/`handle_intent` change**, no decomposer/NL exposure, no new agent or pool, no `GroupChatConfig` min-rank field (the rank policy lives in `CommunicationsConfig`).
- **No new cooldown dict in `proactive.py`** — the service owns the rate limiter (DRY).

---

## Tracking

- `PROGRESS.md` — prepend an AD-924 block.
- `docs/development/roadmap.md` — add/flip the AD-924 row to SHIPPED on gate-pass.
- `DECISIONS.md` — add an AD-924 entry (dispatch = direct `create_group_chat`; rank policy in `CommunicationsConfig`; dedicated manual; task_id deferred).

---

## Acceptance criteria

- `[GROUP_CHAT title="..." @cs,@cs] ... [/GROUP_CHAT]` in a Commander+ agent's proactive output opens exactly one real group chat (right title, creator + named crew as participants) and strips the tag from the posted text.
- An Ensign or Lieutenant emitting the same tag creates **no** room.
- A rapid second create is blocked by the AD-918 cooldown/cap; a malformed tag and a non-crew creator both degrade cleanly (no room, no crash).
- `federation.md` teaches the `[GROUP_CHAT ...]` tag with the 2+-crew anti-flood guardrail; `config/manuals/group-chat.md` exists and is ASCII-only.
- Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad924_group_chat_trigger.py -q -n 0` (+11). Blast-radius green: `pytest tests/ -k "thread or chat or proactive or group or dm" -q -n 0`.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08)

```text
git log --oneline -1            -> 633202bf AD-923 (HEAD, origin/main, ahead=0)
git grep "AD-924"               -> (empty; unused)

runtime.py:468                   self.agent_group_chat = AgentGroupChatService(
runtime.py:475-478               self.intent_bus.subscribe(GROUP_CHAT_COORDINATOR_ID, self.agent_group_chat.handle_intent, intent_names=[CREATE_GROUP_CHAT])

agent_group_chat.py              def create_group_chat(self, *, creator_id, title, participants=None, task_id=None, first_message=None) -> GroupChatCreateResult  (sync; final=[creator_id]; _rate_ok; _resolve_participant agent_id OR callsign)
agent_group_chat.py              GroupChatCreateResult(ok, thread, error, participants_added); errors empty_title|not_crew|rate_limited
agent_group_chat.py              GROUP_CHAT_COORDINATOR_ID="group_chat_coordinator"; CREATE_GROUP_CHAT="create_group_chat"

proactive.py:366                 class ProactiveCognitiveLoop __init__(*, interval=120.0, cooldown=300.0, on_event=None); set_runtime -> self._runtime
proactive.py:2695                async def _extract_and_execute_actions(self, agent, text, *, post_budget=None) -> tuple[str, list[dict]]
proactive.py:2714-2716           if not rt or not rt.ward_room: return text, []
proactive.py:2718-2719           trust_score = rt.trust_network.get_score(agent.id); rank = Rank.from_trust(trust_score)
proactive.py:2755-2764           DM gate: rt.config.communications.dm_min_rank; _RANK_ORDER_DM=[ENSIGN,LIEUTENANT,COMMANDER,SENIOR]; index>=index -> extract_and_execute_dms
proactive.py:3960                async def extract_and_execute_dms(self, agent, text) -> tuple[str, list[dict]]  (regex [DM @cs]...[/DM]; sub('') strip; direct rt.ward_room.create_thread)

crew_profile.py:30-38            class Rank(Enum) ENSIGN/LIEUTENANT/COMMANDER/SENIOR("senior_officer"); from_trust(cls, trust_score)
config.py:18-20                  TRUST_SENIOR=0.85; TRUST_COMMANDER=0.7; TRUST_LIEUTENANT=0.5
config.py:3747,3768-3769         GroupChatConfig: agent_create_cooldown_seconds=60.0; agent_create_max_per_window=5  (no min-rank)
config.py:4600-4603              CommunicationsConfig: dm_min_rank="ensign"; recreation_min_rank="ensign"  (-> add group_chat_min_rank="commander")

federation.md                    ## Communications (<!-- category: communication_style -->): Ward Room/Replying/Endorsements/Direct Messages([DM @cs]...[/DM])/Notebook; Encoding Safety = ASCII only
config/manuals/                  ward-room.md, recreation.md, peer_observation_conduct.yaml
records_store.py:189             for md_file in sorted(source_dir.glob("*.md"))  -> new manual is drop-in

tests/test_ad489_code_of_conduct.py:16-19   FEDERATION_ORDERS.read_text(encoding="utf-8"); assert "..." in text   (content-test precedent)
tests/test_ad437_action_space.py:64-110     loop=ProactiveCognitiveLoop(interval=60); loop.set_runtime(MagicMock(spec=ProbOSRuntime)); ward_room=MagicMock; trust_network.get_score.return_value; drive _extract_and_execute_actions
tests/test_ad918_agent_initiated_group_chat.py:31-95   _FakeAgent/_FakeRegistry/_NoCallsigns/_Clock/_make_service  (BF-287 real ChatThreadStore + real CallsignRegistry)

grep "[GROUP_CHAT" / "group_chat" action-type in src  -> none (no collision)
```
