# AD-928 — Show-Your-Work Status Protocol

**Target repo:** OSS (`d:\ProbOS`)
**Status:** Ready to build · **Epic:** Task Workspace Rooms (AD-925..929) · **Priority:** 3
**Dependencies:** AD-924 (`[GROUP_CHAT]` extractor pattern), AD-925 (auto-created task room), AD-927 (`_resolve_agent_task_room` + `[ARTIFACT]` extractor). All committed LOCAL.
**Estimated tests:** +12 pytest (`tests/test_ad928_show_your_work.py`). No Vitest (UI deferred — see Decision 5).
**Highest committed AD:** **AD-929** (`72f4eb6b`, **LOCAL-ONLY, 5 ahead of origin — NOT pushed**). AD-928 was reserved in the epic plan (deferred for Captain review) and is **unused in code** — this prompt fills it.
**Commit policy:** Builder commits **LOCAL ONLY. DO NOT PUSH.** The whole epic is held for Captain review.

---

## Goal

Deliver the Microsoft-Teams "activity feed" feel for a task workspace room: as the crew work a task they **narrate meaningful progress** in the room and post a **clear final result** — so a human (HR-style collaborator) watching the room sees the work happen and a crisp completion, like a Teams channel where people post "started X", "draft ready", "done — final attached".

The mechanism mirrors AD-924/AD-927 exactly: a rank-gated, anti-flooded proactive **action tag** that posts a message **into the agent's bound task room** (resolved by the AD-927 participation resolver), tagged with a distinct `metadata` marker so the room transcript can render it as activity — plus a `federation.md` **standing order** that teaches the crew the norm.

---

## Decisions (made by the Architect — build exactly these)

### Decision 1 — One `[STATUS]` tag with an optional `final` flag (NOT two tags)

A **single** paired tag carries both progress narration and the final result:

```
[STATUS]Drafting the comparative analysis section now.[/STATUS]
[STATUS final]Complete. Final report attached to the room.[/STATUS]
```

- **Progress:** `[STATUS]body[/STATUS]` → `metadata = {"kind": "status"}`
- **Final:** `[STATUS final]body[/STATUS]` → `metadata = {"kind": "status", "status_final": true}`

**Why one tag, not `[STATUS]` + `[RESULT]`:** DRY. A second tag doubles the regex / extractor / rank-gate / cap surface for a semantic that is just a boolean on the same message kind. The Teams activity-feed feel = a stream of `kind="status"` messages plus one distinctly-marked completion (`status_final`); a flag on the same kind gives a UI consumer exactly what it needs (AD-928b) without a second code path. This mirrors AD-923's deterministic `metadata.meeting_end` marker approach.

### Decision 2 — Binding: REUSE `_resolve_agent_task_room(agent.id)` identically

The proactive turn carries no inherent thread. Bind the status post to the agent's task room with the **existing AD-927 participation resolver, unchanged** (`proactive.py:4055`): the most-recently-active non-archived thread that has a `task_id` and lists the agent as a participant. No room → honest-degrade (suppress, strip the tag, no crash). This builds on AD-925 (the agent IS a participant of its auto-created room).

> **Signature note:** the resolver is `def _resolve_agent_task_room(self, agent_id: str)` — it takes the **agent id string**, not the agent object. The artifact extractor calls `self._resolve_agent_task_room(agent.id)`. Mirror that call exactly.

### Decision 3 — Post via `ChatThreadStore.append_message` (message-only)

Post the status as a normal thread message authored by the agent:

```python
msg = store.append_message(
    room.id,
    author_id=agent.id,
    role="agent",
    body=body,
    metadata=metadata,   # {"kind": "status"} (+ "status_final": True when final)
)
```

`append_message` is **synchronous**, returns `ChatThreadMessage | None` (`None` if the thread is missing — built-in honest-degrade), and its `to_dict()` carries `metadata` (`threads/__init__.py:148`), so the existing `GET /api/threads/{id}/messages` already surfaces the marker for any future UI consumer (AD-928b). `role="agent"` is not validated at the store layer and is a valid role at the router layer too.

### Decision 4 — Rank gate **Lieutenant+**, caps `status_max_per_turn=3` + `status_max_bytes=4096`

- **Rank = `lieutenant`** (mirror AD-927 artifacts). Status narration and artifact output are the two **task-room work-output channels** — same tier reads cleanly. The whole proactive-action surface (endorse/reply) is already Lieutenant+ (Ensigns "can't think proactively anyway"), so Lieutenant is the floor of "can take proactive actions at all"; dropping to Ensign would make status the *only* action an Ensign can take — inconsistent. Configurable, default `lieutenant`.
- **`status_max_per_turn = 3`** (mirror `artifact_max_per_turn`). Status is frequent by design (narrate *milestones*, not micro-steps); 3 allows at most "started / progress / done" in one turn. The 4th+ is suppressed (`reason="rate_limited"`), tag stripped, no crash.
- **`status_max_bytes = 4096`** (4 KiB; smaller than the artifact 256 KiB because status lines are short prose, not documents). Oversized → suppressed (`reason="too_large"`), defense-in-depth. Keeps the extractor structurally identical to AD-927.

### Decision 5 — UI status-chip rendering is **DEFERRED to forward marker AD-928b** (NOT in this AD)

Rendering `metadata.kind="status"` distinctly in the transcript is **not cheap** at HEAD and is therefore out of scope:

- `ChatMessage` (`ui/src/store/types.ts:211`) has **no `metadata`/`kind` field**.
- The thread-message load path renames `body → text` and **does not carry `metadata`** into the conversation, so surfacing `kind` needs a type change + a load-path mapping change + a render branch across 3+ files in the heavy `ProfileChatTab` (`messages.map` inline loop at `ui/src/components/profile/ProfileChatTab.tsx:865`, which the AD-917 work already flagged as "too heavy to render whole").
- There is an **open live-refresh question** (does the task-room transcript poll for agent-posted messages between Captain turns?) that a chip alone does not answer — the "live activity feed" feel needs a refresh path, which is its own scope.

Because the backend persists the marker and the existing `GET messages` endpoint already surfaces it, **AD-928b is a pure presentational follow-up with no backend dependency.** This mirrors the epic's discipline (AD-927 shipped backend-only off the existing `ArtifactDrawer`; AD-926 shipped the `InputsList` unmounted). Add **AD-928b** as the forward marker.

### Decision 6 — Message-only v1; lifecycle transition is forward marker AD-928a

The roadmap row aspires to tie the final result to the work-item lifecycle (`in_progress → done`). **v1 is MESSAGE-ONLY: do NOT transition any work item.** Verified: `grep "work_item|current_task|task_id|transition_work_item"` over `proactive.py` returns **only the two references inside the AD-927 resolver** — there is **no clean current-work-item handle in the proactive context** (the same gap AD-925/AD-927 documented). A lifecycle transition is a validated state-machine write (`transition_work_item`, AD-498/BF-72/AD-861) that needs the work-item id, which is not available here. The transition stays with `CrewTaskExecutor` / a richer binding → forward marker **AD-928a** (shares the AD-927a gap).

---

## Implementation

### Section 0 — Tag pattern (module constant)

In `src/probos/proactive.py`, immediately **after** `_ARTIFACT_PATTERN` (currently ends ~line 82), add:

```python
# AD-928: agent-facing "show your work" status protocol. Matches a progress
# narration [STATUS]...[/STATUS] or a final result [STATUS final]...[/STATUS]
# posted into the agent's task room (AD-925). group(1)=" final" marker or None,
# group(2)=body (the status / final-result text).
_STATUS_PATTERN = re.compile(
    r'\[STATUS(\s+final)?\s*\]'  # 1=optional " final" marker
    r'(.*?)'                     # 2=body
    r'\[/STATUS\]',
    re.DOTALL | re.IGNORECASE,
)
```

`bool(m.group(1))` is the final flag (case-insensitive via `IGNORECASE`); `"final"` appearing inside the body is NOT the marker (the group only captures the token immediately after `STATUS` before `]`).

### Section 1 — The extractor `_extract_and_execute_statuses`

In `src/probos/proactive.py`, immediately **after** `_extract_and_execute_artifacts` (currently ends ~line 4172, right before `extract_and_execute_dms`), add a near-clone of the artifact extractor — same `(cleaned_text, actions)` contract, same room binding, same caps, same honest-degrade, minus the two-call store write (replaced by one `append_message`):

```python
    async def _extract_and_execute_statuses(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """AD-928: Extract [STATUS]...[/STATUS] (and [STATUS final]...) blocks and
        post each as a status message into the agent's task room (AD-925).

        Mirrors the AD-927 artifact extractor: rank-gated by the caller, returns
        (cleaned_text, actions), strips the tag regardless of outcome. Each block
        is posted to the room thread via ChatThreadStore.append_message with
        metadata.kind="status" (and metadata.status_final=True for the final
        result), so the room transcript can render it as activity. Honest-degrade
        (suppressed, no crash) when there is no resolvable task room, the body is
        empty/oversized, the per-turn cap is hit, the store is unavailable, or the
        post fails. v1 is MESSAGE-ONLY: the work item is NOT transitioned (AD-928a).
        """
        rt = self._runtime
        store = getattr(rt, "chat_thread_store", None)
        actions: list[dict] = []
        if store is None:
            return text, actions  # misconfigured runtime — leave text untouched (mirror GROUP_CHAT svc-None)

        # Anti-flood config (Tier-2 defaults if config absent).
        max_per_turn = 3
        max_bytes = 4096
        comms = getattr(getattr(rt, "config", None), "communications", None)
        if comms is not None:
            max_per_turn = getattr(comms, "status_max_per_turn", 3)
            max_bytes = getattr(comms, "status_max_bytes", 4096)

        room = self._resolve_agent_task_room(agent.id)
        produced = 0
        for m in _STATUS_PATTERN.finditer(text):
            is_final = bool(m.group(1))
            body = (m.group(2) or "").strip()
            if not body:
                actions.append({"type": "status_suppressed", "reason": "empty"})
                continue
            if room is None:
                actions.append({"type": "status_suppressed", "reason": "no_task_room"})
                continue
            if len(body.encode("utf-8")) > max_bytes:
                actions.append({"type": "status_suppressed", "reason": "too_large", "final": is_final})
                continue
            if produced >= max_per_turn:
                actions.append({"type": "status_suppressed", "reason": "rate_limited", "final": is_final})
                continue
            metadata: dict = {"kind": "status"}
            if is_final:
                metadata["status_final"] = True
            try:
                msg = store.append_message(
                    room.id,
                    author_id=agent.id,
                    role="agent",
                    body=body,
                    metadata=metadata,
                )
            except Exception:
                logger.warning(
                    "AD-928: status post failed for %s (final=%s)",
                    getattr(agent, "id", "?"), is_final, exc_info=True,
                )
                actions.append({"type": "status_suppressed", "reason": "post_failed", "final": is_final})
                continue
            if msg is None:
                actions.append({"type": "status_suppressed", "reason": "post_failed", "final": is_final})
                continue
            produced += 1
            actions.append({
                "type": "status",
                "thread_id": room.id,
                "final": is_final,
                "message_id": msg.id,
            })
            logger.info(
                "AD-928: %s posted %sstatus into task room %s",
                getattr(agent, "callsign", None) or agent.agent_type,
                "FINAL " if is_final else "", room.id,
            )

        text = _STATUS_PATTERN.sub("", text)
        return text, actions
```

### Section 2 — Wire the rank gate inline in `_extract_and_execute_actions`

In `src/probos/proactive.py`, immediately **after** the AD-927 artifact gate block (currently ~lines 2801–2809, ending with `actions_executed.extend(art_actions)`) and **before** the `# --- Notebook writes (AD-434) ---` block, add the status gate mirroring the artifact gate (reusing the in-scope `_RANK_ORDER_DM`):

```python
        # --- Show your work: status updates (Lieutenant+) --- AD-928
        status_min_rank_str = "lieutenant"
        if hasattr(rt, 'config') and hasattr(rt.config, 'communications'):
            status_min_rank_str = getattr(rt.config.communications, 'status_min_rank', 'lieutenant')
        status_min_rank = Rank[status_min_rank_str.upper()] if status_min_rank_str.upper() in Rank.__members__ else Rank.LIEUTENANT
        if _RANK_ORDER_DM.index(rank) >= _RANK_ORDER_DM.index(status_min_rank):
            text, status_actions = await self._extract_and_execute_statuses(agent, text)
            actions_executed.extend(status_actions)
```

### Section 3 — Config fields

In `src/probos/config.py`, in `class CommunicationsConfig` (line 4606), immediately **after** `artifact_max_bytes` (line 4614), add:

```python
    # AD-928: agent-authored [STATUS] -> task-room "show your work" activity.
    status_min_rank: str = "lieutenant"  # min rank to post a status into a task room: ensign|lieutenant|commander|senior
    status_max_per_turn: int = 3         # anti-flood: honor at most this many [STATUS] tags per proactive turn
    status_max_bytes: int = 4096         # anti-flood: reject status bodies larger than 4 KiB (oversized -> honest-degrade)
```

### Section 4 — Standing order (`federation.md`)

In `config/standing_orders/federation.md`, insert a new `### Show Your Work` subsection **after** the `### Group Chat (Ad-Hoc Collaboration)` block (ends ~line 393) and **before** `### Notebook (Ship's Records)` (line 395). **ASCII-only — no em-dash, no smart quotes.** (The pre-existing AD-924 test slices `### Group Chat`..`### Notebook` and asserts `all(ord(c) < 128)`; that slice will now span this block, so it MUST stay ASCII or the AD-924 test breaks.) Suggested content (the Builder may refine wording; keep ASCII + the exact tag literals):

```markdown
### Show Your Work

When you are working a task in a task room (a room opened for a shared task), narrate your meaningful progress so the room reads like a live activity feed and anyone watching can see the work happen. When the task is done, post a clear final result.

**Format:**

    [STATUS]A short note on a meaningful milestone.[/STATUS]
    [STATUS final]The task is complete. Here is the result.[/STATUS]

Use `[STATUS final]` for the single closing message that reports the outcome; use plain `[STATUS]` for progress along the way.

**When to use:**
- Post a status at a MEANINGFUL milestone -- you started the task, a draft is ready, a blocker was cleared, the result is attached. Not every micro-step.
- Post exactly one `[STATUS final]` when the work is done, with the result or where to find it.
- Do NOT narrate trivially. A flood of "still working" lines is noise; silence between milestones is fine. Quality over quantity.
- Status posts go into the task room you are working in. If you are not in a task room, there is nothing to narrate -- stay quiet.
```

### Section 5 — Manual section (`config/manuals/group-chat.md`)

Append a `## Showing Your Work` section to `config/manuals/group-chat.md` (the file already exists, AD-924; it is **all-ASCII** — keep the new section ASCII too). ~12-15 lines covering: what a status is (an activity-feed update in a task room), the `[STATUS]` / `[STATUS final]` format, the "meaningful milestone not micro-step" anti-flood norm, and one `[STATUS final]` for the outcome.

---

## Tests — `tests/test_ad928_show_your_work.py` (+12 floor)

Mirror `tests/test_ad927_outputs_folder.py` **exactly** (BF-287 discipline): a real `ChatThreadStore` on `tmp_path` behind a `MagicMock(spec=ProbOSRuntime)` shell; `_FakeAgent` / `_Clock` duck stubs (never `MagicMock` for the agent/clock); rank driven by the injected trust score (`Rank.from_trust`). Reuse the AD-927 trust constants: `_TRUST_LIEUTENANT = 0.6` (passes the gate), `_TRUST_ENSIGN = 0.3` (gated out). Build the loop with the REAL `chat_thread_store`:

```python
runtime.chat_thread_store = thread_store   # REAL ChatThreadStore(tmp_path, clock=clk)
```

Read posts back with `thread_store.list_messages(room.id)` and assert on `msg.metadata`.

Required cases:

1. **happy path (focused):** a Lieutenant agent emits `[STATUS]...[/STATUS]` while a participant of a `task_id` room → `_extract_and_execute_statuses` posts one message to that room with `metadata == {"kind": "status"}`; action `{"type": "status", "final": False, ...}`; tag stripped from `cleaned`.
2. **final variant:** `[STATUS final]...[/STATUS]` → the posted message has `metadata["status_final"] is True` AND `metadata["kind"] == "status"`; action `final` is `True`.
3. **end-to-end via `_extract_and_execute_actions`** (rank-gate integration, mirror AD-927 test 1): a Lieutenant posts a status; assert the message lands in the room and the `[STATUS` tag is gone from the returned text.
4. **no task room → honest-degrade:** agent in NO task room (`task_id is None` or not a participant) → no message posted (`list_messages` empty), action `status_suppressed reason="no_task_room"`, no exception.
5. **rank-gated out (Ensign):** drive `_extract_and_execute_actions` with `_TRUST_ENSIGN` → **assert NO status message posted AND no `status`/`status_suppressed` action**. **Do NOT assert the tag survives** — the bare `[STATUS ...]` opener is removed by the pre-existing BF-203 catch-all (`proactive.py:3476`, `re.sub(r'\[(?:[A-Z][A-Z_]+)...\]')`); the status path simply never ran.
6. **per-turn cap:** four `[STATUS]` blocks in one turn with `status_max_per_turn=3` → exactly 3 posted, the 4th `status_suppressed reason="rate_limited"`.
7. **oversized body:** a body larger than `status_max_bytes` → `status_suppressed reason="too_large"`, no post.
8. **empty body:** `[STATUS][/STATUS]` → `status_suppressed reason="empty"`, no post.
9. **malformed degrades:** `[STATUS] with no closing tag` → no match, no action, no crash, no post.
10. **mixed milestones in one turn:** two `[STATUS]` progress + one `[STATUS final]` → all three posted in document order; the third has `status_final`, the first two do not.
11. **federation.md content** (mirror AD-924 test 9): assert `"### Show Your Work" in text`, `"[STATUS" in text`, `"[/STATUS]" in text`, and the `### Show Your Work`..`### Notebook` slice is ASCII (`all(ord(c) < 128 for c in section)`).
12. **manual seeded** (mirror AD-924 test 10): `config/manuals/group-chat.md` exists, contains `"[STATUS"`, and is ASCII whole-file.
13. **config defaults:** `SystemConfig().communications.status_min_rank == "lieutenant"`, `.status_max_per_turn == 3`, `.status_max_bytes == 4096` (one test, three asserts).

(11-13 push the count to ~13; floor is +12.)

**Gate commands:**
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad928_show_your_work.py tests/test_ad927_outputs_folder.py tests/test_ad924_group_chat_trigger.py -q -n 0 -p no:cacheprovider`
- Blast-radius: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "proactive or status or thread or chat or group or artifact or standing or manual" -q -p no:cacheprovider` (report the passed count).
- Confirm the AD-924 federation/manual content tests still pass (the new ASCII block must not break the AD-924 slice assertion).

---

## What this does NOT change (Do NOT build)

- **No work-item lifecycle transition** (`in_progress → done`) in v1 — message-only. Forward marker **AD-928a** (no clean current-work-item handle in the proactive context; verified).
- **No UI** — no status-chip rendering, no `ChatMessage` type change, no `ProfileChatTab` edit, no store-slice change, no live-refresh/poll change. Forward marker **AD-928b**.
- **No presence layer** (online/working/in-meeting) — that is **AD-930**.
- **No second tag** (`[RESULT]`) — one `[STATUS]` family with a `final` flag.
- **No change** to `_resolve_agent_task_room` (reuse as-is), `ChatThreadStore.append_message`, the `[ARTIFACT]`/`[GROUP_CHAT]` extractors, `AgentGroupChatService`, the intent bus, `CrewTaskExecutor`, `CrewOrchestrator`, `agentic_dispatch.orchestrator_enabled`, any consensus/trust path, `BaseAgent`, or `IntentMessage`.
- **No new REST route, no new `EventType`, no new store method, no new config class** (extend `CommunicationsConfig` only).
- **No binary/attachment status** — status is short text only.

---

## Tracking (same local commit)

- `docs/development/roadmap.md` — flip the AD-928 row (line 388) to `SHIPPED 2026-06-08 gate-verified` with the one-line summary; drop the "deferred — Captain review" tag. Add forward markers **AD-928a** (lifecycle) and **AD-928b** (UI chip).
- `PROGRESS.md` — prepend an AD-928 block.
- `DECISIONS.md` — add an AD-928 entry above AD-929 (Decisions 1–6 + non-goals + the AD-928a/AD-928b forward markers).
- Write `ad928_gate.txt` with the focused + blast-radius gate output.

---

## Acceptance Criteria

1. `[STATUS]...[/STATUS]` and `[STATUS final]...[/STATUS]` from a Lieutenant+ participant of a task room post a message into that room via `append_message` with `metadata.kind="status"` (and `status_final=true` for the final), tag stripped, `(cleaned_text, actions)` returned.
2. Honest-degrade on no-room / empty / oversize / per-turn-cap / post-fail — suppressed action, no crash, no partial post.
3. Rank-gated out below `status_min_rank` — no post, no status action.
4. Three new `CommunicationsConfig` fields with the stated defaults; zero-config boot unaffected.
5. `federation.md` `### Show Your Work` block (ASCII, exact tag literals) + `group-chat.md` `## Showing Your Work` section.
6. `tests/test_ad928_show_your_work.py` +12 floor, BF-287 discipline (real `ChatThreadStore`), all green; AD-924/AD-927 focused tests still green; blast-radius reported.
7. Trackers updated; `ad928_gate.txt` written; **committed LOCAL ONLY, NOT pushed.**
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-08, HEAD `72f4eb6b`)

```
grep -n "_ARTIFACT_PATTERN|_GROUP_CHAT_PATTERN" src/probos/proactive.py
  65: _GROUP_CHAT_PATTERN = re.compile(           # tag-pattern precedent
  76: _ARTIFACT_PATTERN = re.compile(             # insert _STATUS_PATTERN after this (~line 82)

grep -n "def _resolve_agent_task_room|def _extract_and_execute_artifacts|def _extract_and_execute_group_chats" src/probos/proactive.py
  4000: async def _extract_and_execute_group_chats(self, agent, text)
  4055: def _resolve_agent_task_room(self, agent_id: str):   # REUSE; takes agent_id STRING, returns ChatThread|None
  4085: async def _extract_and_execute_artifacts(self, agent, text)   # clone shape; insert _extract_and_execute_statuses after (~4172)
  4117:     room = self._resolve_agent_task_room(agent.id)   # the exact call to mirror

grep -n "Artifact output (Lieutenant" src/probos/proactive.py
  ~2801: # --- Artifact output (Lieutenant+) --- AD-927    # status gate goes immediately AFTER this block, before Notebook (~2811)
  2740: trust_score = rt.trust_network.get_score(agent.id); rank = Rank.from_trust(trust_score)
  2785: _RANK_ORDER_DM = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]   # in-scope, reuse

grep -n "def append_message" src/probos/threads/__init__.py
  707: def append_message(self, thread_id, *, author_id, role, body, metadata=None) -> ChatThreadMessage | None   # SYNC; None if thread missing
  148: "metadata": dict(self.metadata),   # ChatThreadMessage.to_dict carries metadata -> GET messages surfaces kind

grep -n "class CommunicationsConfig|artifact_max_bytes" src/probos/config.py
  4606: class CommunicationsConfig(BaseModel):
  4614: artifact_max_bytes: int = 262144   # add status_min_rank/status_max_per_turn/status_max_bytes right after

grep -n "## Communications|### Group Chat|### Notebook" config/standing_orders/federation.md
  312: ## Communications
  377: ### Group Chat (Ad-Hoc Collaboration)
  395: ### Notebook (Ship's Records)   # insert ### Show Your Work between Group Chat-end (~393) and here; ASCII-only

grep -n "re.sub(r'\\[(?:\[A-Z\]\[A-Z_\]+)" src/probos/proactive.py
  3476: text = re.sub(r'\[(?:[A-Z][A-Z_]+)(?:\s[^\]]{0,120})?\]', '', text).strip()   # BF-203 strips a gated-out [STATUS ...] opener -> gated-out test asserts no-post+no-action, NOT tag-survives

grep -rn "work_item|current_task|transition_work_item" src/probos/proactive.py
  4060, 4081: ONLY the two task_id refs inside _resolve_agent_task_room   # NO current-work-item handle -> message-only v1 (AD-928a)

grep -n "export interface ChatMessage" ui/src/store/types.ts
  211: export interface ChatMessage { id; role; text; timestamp; agent_id?; callsign?; attachments?; ... }   # NO metadata/kind field -> UI chip deferred (AD-928b)
  ui/src/components/profile/ProfileChatTab.tsx:865  {messages.map(msg => (...))}   # heavy inline render, branches on msg.role only

grep -n "FEDERATION_ORDERS|def test_federation_md|def test_group_chat_manual" tests/test_ad924_group_chat_trigger.py
  39-40, 299, 314: federation/manual content-test idiom to mirror (ASCII slice assertion)

# collision check: no [STATUS ...] proactive tag, no _STATUS_PATTERN, no metadata.kind="status" anywhere in src/  -> free
# AD-928 unused in code (only roadmap row 388 + DECISIONS/PROGRESS non-goal mentions)
```

---

## Dormancy clarification (report to Captain)

Unlike the auto-create wiring (AD-925), the `[STATUS]` tag is **NOT** gated by `agentic_dispatch.orchestrator_enabled` and does **NOT** depend on `CrewTaskExecutor`. It fires whenever **any Lieutenant+ agent that participates in a task room** emits the tag during a proactive turn — the binding is participation-based (`_resolve_agent_task_room`), independent of the crew orchestrator. So a task room created by any path (including a Captain-created group chat with a `task_id`, or a future orchestrator-driven room) immediately supports show-your-work narration. The capability is live the moment a task room with participants exists; it is not dormant behind the orchestrator gate.
