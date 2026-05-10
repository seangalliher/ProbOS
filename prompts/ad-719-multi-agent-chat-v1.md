# AD-719 — Multi-agent chat v1 (`@<callsign>` fan-out + per-turn attribution)

**Wave:** 135
**Depends on:** AD-397/BF-009 (callsign DM short-circuit), AD-636 (Captain DMs), BF-013 (`callsign` field)
**Pairs with:** AD-720 (same wave; **AD-719 ships first as commit N, AD-720 ships second as commit N+1** — HARD ORDER)
**Issue:** [#513](https://github.com/seangalliher/ProbOS/issues/513)
**Risk:** MEDIUM (UI surface widening + new server-side fan-out branch + episodic-write loop)
**Estimated tests:** ≥ 12 Python + 1 Vitest

> **Builder:** read `prompts/WAVE-135-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Evolve the Ship's Computer chat (`ui/src/components/IntentSurface.tsx`) into a **multi-agent chat** addressed by `@<callsign>`. v1 picks **mental model (a)** — Captain composes one turn in `IntentSurface`, mentions zero-or-more crew, the runtime fans out, and each mentioned crewmember replies inline with avatar + callsign attribution. Default routing (no mention) stays Ship's Computer single-reply.

The runtime already understands `@<callsign>` parsing (BF-009/AD-397 — see `src/probos/routers/chat.py:107-126` and `src/probos/cognitive/decomposer.py` `_callsign_map` substrate). v1 is mostly a **UI + response-shape change**, not a new routing primitive. The richer "crew-see-each-other thread" (mental model b) and the "Copilot-style left rail" (mental model c) are explicit forward markers (AD-719a, AD-719b) — out of scope.

## 2. Why now

- Captain ruling 2026-05-09 picked mental model (a) for v1 — fan-out + attribution is the smallest slice that delivers @-mention multi-recipient chat without persistent thread storage.
- Cluster-A roadmap calls for multi-recipient chat by end of Wave 135 so AD-718-1 (voice on multi-agent surface) and AD-720 (image attachments) can build on the widened `ChatMessage` shape.
- The `@<callsign>` parsing substrate is already shipped — the runtime emits structured `mentions` and the DM short-circuit at `chat.py:107-126` already routes single-mention turns. Multi-mention fan-out is the missing branch.

## 3. Verified Against Codebase (2026-05-09)

Line numbers are "around line N" — exact line drift between authoring and Builder dispatch is expected. Greps below are ground truth at 2026-05-09 HEAD.

```
grep -n "router = APIRouter|@router\.post\(\"/chat" src/probos/routers/chat.py
   23: router = APIRouter(prefix="/api", tags=["chat"])
   26: @router.post("/chat")
   27: async def chat(
   29:     runtime: Any = Depends(get_runtime),

grep -n "extract_callsign_mention\|is_directed_mention\|direct_message" src/probos/routers/chat.py
   95: from probos.crew_profile import extract_callsign_mention, is_directed_mention
   96: mention = extract_callsign_mention(text)
   97: if mention and is_directed_mention(text):
  113: from probos.types import IntentMessage
  114: intent = IntentMessage(
  115:     intent="direct_message",
  116:     params={"text": message_text, "from": "hxi", "session": False},

grep -n "process_natural_language" src/probos/routers/chat.py
  142: dag_result = await asyncio.wait_for(
  143:     runtime.process_natural_language(

grep -n "class ChatRequest\|class ChatResponse\|class ChatMessage" src/probos/api_models.py
   15: class ChatMessage(BaseModel):
   20: class ChatRequest(BaseModel):
   25: class ChatResponse(BaseModel):
   26:     response: str
   27:     dag: dict[str, Any] | None = None
   28:     results: dict[str, Any] | None = None

grep -n "await self.episodic_memory.store" src/probos/runtime.py
  2870: await self.episodic_memory.store(episode)
        # Step 6 of process_natural_language(...). The fan-out branch
        # MUST loop a sibling write — one episode per (captain_turn, agent).

grep -n "export interface ChatMessage" ui/src/store/types.ts
  196: export interface ChatMessage {
  197:     id: string;
  198:     role: 'user' | 'system';
  199:     text: string;
  200:     timestamp: number;
        # widen role + add agent_id/callsign here.

grep -n "addChatMessage:" ui/src/store/useStore.ts
  337: addChatMessage: (role: 'user' | 'system', text: string, meta?: ...) => void;
 1306: addChatMessage: (role, text, meta) => {
        # Store action signature also hardcodes 'user' | 'system' — must widen
        # in lockstep with types.ts. 8+ existing callers pass 'system' literals;
        # all stay valid because we ADD 'agent', not remove 'system'.

grep -n "DEPT_COLORS\|deptColor" ui/src/components/profile/AgentProfilePanel.tsx
   22: const DEPT_COLORS: Record<string, string> = {
  149: const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';
  197: width: 8, height: 8, borderRadius: '50%',
  198: background: deptColor,

grep -n "CrewAvatarPopout" ui/src/components/profile/CrewAvatarPopout.tsx
   37: export function CrewAvatarPopout(...)
        # 3D VRM popout — HEAVY. NOT used for inline 24-32px chat attribution.
```

**Dispatch contradictions surfaced (fix in this prompt only — do NOT edit the dispatch):**

1. **Dispatch §4 D7 cites `AgentProfilePanel.tsx:195-198` and `:22`** without subpath. **Actual path:** `ui/src/components/profile/AgentProfilePanel.tsx` (the file lives under `profile/`, not directly under `components/`). `DEPT_COLORS` is at L22, the inline 8×8 dot is at L197-198.
2. **Dispatch §4 D5 says "Response model is a new Pydantic `ChatResponse`."** **Actual:** `ChatResponse` already exists in `src/probos/api_models.py:25-28` with `response: str`, `dag`, `results`. AD-719 **extends** it with two new optional fields — does NOT create a new class.
3. **Dispatch implicitly widens `ChatMessage.role` only at `types.ts`.** The store action `addChatMessage` at `useStore.ts:337` ALSO hardcodes the role union and must be widened in the same commit. 8+ existing call-sites pass the string literal `'system'`; all remain valid because we **add** `'agent'`, not remove `'system'`. **Backward-compatible widening only.**

## 4. Scope (v1 only)

- Widen `ChatMessage.role` to `'user' | 'agent' | 'system'`; add `agent_id?` and `callsign?`.
- Widen `addChatMessage` store action signature in lockstep with the type widening.
- Server-side multi-mention fan-out branch on `POST /api/chat` (parallel `asyncio.gather`).
- Extend `ChatResponse` with `mentions: list[str]` and `per_agent_replies: list[PerAgentReply]` (both optional / default empty for backward compat).
- `@`-picker autocomplete in `IntentSurface.tsx` — **mouse + Enter only** (Captain ruling 2026-05-09).
- Recipient chip strip with inline-SVG `x` to remove (no emoji).
- Per-turn attribution UI: new `AgentAvatarBadge.tsx` (24/32px colored circle + initial), used inline in multi-reply rendering.
- One episode per fanned-out reply (the `for` loop wraps the existing Step 6 write at `runtime.py:2870` — **see §5 D6 for the exact insertion shape**).
- Tests: ≥ 12 Python + 1 Vitest.

## 5. Non-goals (deferred forward markers)

| Out of scope | Why deferred | Forward marker |
|---|---|---|
| Persistent multi-agent thread storage (mental model b: crew see each other) | Requires WardRoom adoption + agent-observes-thread routing. Architectural surface, not v1 polish. | **AD-719a** |
| Copilot-style left rail + Agents nav (mental model c) | UI refactor, not a feature. v1 keeps `IntentSurface` shape. | **AD-719b** |
| `@`-picker keyboard navigation (↑/↓/Esc/Tab) | Captain ruling 2026-05-09 — v1 ships mouse + Enter only; a11y polish lands separately. | **AD-719c** |
| Voice on multi-agent surface | Already filed pre-Wave 135. | **AD-718-1** |
| Consensus / quorum within chat | Wrong surface — use AD-594b `consult()`. **NEVER in this surface.** Builder MUST NOT touch `src/probos/consensus/`. | n/a |
| Replacing `ProfileChatTab` 1:1 DMs | DMs and multi-agent chat coexist. v1 leaves `ProfileChatTab` untouched. | n/a |
| Refactoring `AgentProfilePanel.tsx`'s inline 8×8 dot to use the new `AgentAvatarBadge` | Scope creep; lands separately. | n/a |

## 6. Deliverables

### D1. Widen `ChatMessage` in `ui/src/store/types.ts`

**File:** `ui/src/store/types.ts` (around line 196)

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';   // AD-719: was 'user' | 'system'
  text: string;
  timestamp: number;
  // AD-719: per-reply attribution for multi-agent fan-out turns.
  agent_id?: string;
  callsign?: string;
  selfModProposal?: SelfModProposal;
  buildProposal?: BuildProposal;
  buildFailureReport?: BuildFailureReport;
  architectProposal?: ArchitectProposalView;
}
```

### D2. Widen `addChatMessage` store action signature

**File:** `ui/src/store/useStore.ts` (around lines 337 and 1306)

Change BOTH the interface declaration AND the action definition:

```typescript
// L337 — interface (was: role: 'user' | 'system')
addChatMessage: (
  role: 'user' | 'agent' | 'system',
  text: string,
  meta?: { selfModProposal?: SelfModProposal; buildProposal?: BuildProposal; buildFailureReport?: BuildFailureReport; architectProposal?: ArchitectProposalView; agent_id?: string; callsign?: string }
) => void;

// L1306 — implementation: append agent_id/callsign onto the appended ChatMessage
//   when meta carries them.
```

**Backward compatibility:** all 8+ existing `addChatMessage('system', ...)` call-sites in this file remain valid — `'agent'` is **added**, `'system'` is **kept**. Builder MUST NOT change any existing call-site to use `'agent'`. Only the new fan-out renderer in D7 emits `'agent'`.

### D3. `@`-picker autocomplete in `IntentSurface.tsx`

**File:** `ui/src/components/IntentSurface.tsx`

- Read live crew from the existing `agents` Map already in the store (`useStore.ts:486` — `agents: new Map()`). Use `useStore((s) => s.agents)`. Do NOT add a new fetch.
- When the input contains an unclosed `@<prefix>` token (no whitespace after the `@`), open a popover anchored below the input.
- Popover renders one row per matching crewmember: department-colored dot + callsign + display_name + tier badge (`core` / `utility` / `domain`).
- Filter: case-insensitive prefix match on `callsign` and `display_name`.
- **Confirmation: mouse-click OR Enter on the focused row.** ↑/↓ arrow keys, Esc, and Tab are **explicitly NOT wired** in v1 — clicking outside or pressing any non-Enter key on the input dismisses the popover. (Note: keyboard nav goes to AD-719c.)
- Outside-click MUST close the popover. Input-blur MUST close the popover.
- On confirm, replace the `@<prefix>` token in the input with `@<callsign> ` (trailing space) and add the callsign to the local `selectedMentions: string[]` state.

### D4. Recipient chip strip

**File:** `ui/src/components/IntentSurface.tsx`

- Above OR below the input (Builder picks; just consistent), render one chip per entry in `selectedMentions`.
- Chip shape: department-colored dot + `@<callsign>` + inline-SVG `x` button (12×12, `strokeWidth: 1.5`, `strokeLinecap: 'round'`, amber `#f0b060` on hover, dim `#666680` default).
- **No emoji literals anywhere.** Reviewer greps the diff.
- Click `x` removes the chip AND removes the `@<callsign>` token from the input. Multi-select is supported (Captain can mention 1..N crew per turn).

### D5. Server-side fan-out + extended response shape

**File:** `src/probos/api_models.py` (around line 25)

Extend `ChatResponse`:

```python
class PerAgentReply(BaseModel):
    agent_id: str
    callsign: str
    text: str

class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None
    # AD-719: multi-agent fan-out attribution. Both optional for backward compat.
    mentions: list[str] = Field(default_factory=list)
    per_agent_replies: list[PerAgentReply] = Field(default_factory=list)
```

> **Pydantic discipline (Wave 5 convention):** `Field(default_factory=list)`, NOT `= []` bare mutable default. Add `from pydantic import Field` if not already imported.

**File:** `src/probos/routers/chat.py`

- The existing single-mention DM short-circuit at L107-126 stays untouched (one `extract_callsign_mention` hit → existing path).
- Add a **NEW branch** below it that detects **multiple `@<callsign>` mentions** in the leading run of tokens. Use a small new helper in `crew_profile.py` (e.g. `extract_all_leading_callsign_mentions(text) -> tuple[list[str], str]` returning `(callsigns, remaining_message)`) — Builder picks the exact API but it MUST live next to `extract_callsign_mention` and reuse the same regex primitive. **Do NOT** invent a separate parser.
- For the multi-mention branch:
  1. Resolve each callsign via `runtime.callsign_registry.resolve(callsign)`.
  2. For each resolved-and-on-duty crewmember, build an `IntentMessage(intent="direct_message", params={"text": remaining_message, "from": "hxi", "session": False}, target_agent_id=resolved["agent_id"], ttl_seconds=60.0)` (mirror L114-118 exactly).
  3. Dispatch all of them in parallel via `asyncio.gather(*[runtime.intent_bus.send(intent) for intent in intents])`.
  4. For each unresolved or off-duty callsign, append a stub `PerAgentReply(agent_id="", callsign=resolved_or_raw_callsign, text="(not currently on duty)")` — others succeed.
  5. Return `ChatResponse(response=<computer-summary or empty>, mentions=callsigns, per_agent_replies=[...], dag=None, results=None)`.
- When `mentions` is empty (no leading `@`), behavior is unchanged — the existing NL-decomposition path runs and `per_agent_replies` stays empty.
- **Backward compat:** clients that ignore `mentions` / `per_agent_replies` see the same `response` / `dag` / `results` they always saw.

### D6. Episodic write per fan-out reply

**File:** `src/probos/runtime.py` (around line 2870)

The current Step 6 writes one episode per turn from `process_natural_language`. AD-719's multi-mention fan-out runs **inside `routers/chat.py`**, NOT inside `process_natural_language` — so the episodic-write loop lives **in `chat.py`**, not in `runtime.py`. The Builder MUST add an episode write per `PerAgentReply` immediately after the `asyncio.gather(...)` returns and BEFORE constructing the `ChatResponse`.

Implementation shape (in `routers/chat.py`):

```python
# AD-719: one episode per (captain_turn, replying_agent).
if runtime.episodic_memory:
    for reply in per_agent_replies:
        if not reply.agent_id:
            continue  # skip stubs for unresolved callsigns
        try:
            t_end = time.monotonic()
            if runtime.dream_adapter:
                # build_episode signature expects (text, execution_result, t_start, t_end)
                episode = runtime.dream_adapter.build_episode(
                    f"@{reply.callsign} {remaining_message}",
                    {"response": reply.text, "agent_ids": [reply.agent_id]},
                    t_start, t_end,
                )
            else:
                from probos.types import Episode, AnchorFrame
                episode = Episode(
                    timestamp=time.time(),
                    user_input=f"@{reply.callsign} {remaining_message}",
                    dag_summary={},
                    outcomes=[],
                    agent_ids=[reply.agent_id],
                    duration_ms=(t_end - t_start) * 1000,
                    source="multi_agent_chat",  # AD-719 distinct source tag
                    anchors=AnchorFrame(channel="chat", trigger_type="at_mention_fanout"),
                )
            await runtime.episodic_memory.store(episode)
        except Exception as e:
            logger.warning("AD-719 fan-out episode store failed for %s: %s: %s",
                           reply.callsign, type(e).__name__, e)
```

> **Note** the existing single-mention DM short-circuit at L107-126 does NOT currently write an episode. v1 keeps that gap as-is (out of scope; existing behavior). AD-719's loop only covers the multi-mention fan-out branch. Reviewer fails the prompt if the multi-mention branch skips the write.

### D7. Per-turn attribution UI — new `AgentAvatarBadge.tsx`

**New file:** `ui/src/components/AgentAvatarBadge.tsx`

```typescript
// AD-719: lightweight per-message attribution badge.
// 24/32px department-colored circle with first-letter-of-callsign initial.
// NOT to be confused with CrewAvatarPopout.tsx (3D VRM popout).
//
// Used ONLY in IntentSurface multi-reply rendering for v1.

import type { CSSProperties } from 'react';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

interface Props {
  agentId: string;
  callsign: string;
  department?: string;
  size?: 24 | 32;
}

export function AgentAvatarBadge({ agentId: _agentId, callsign, department = '', size = 24 }: Props) {
  const color = DEPT_COLORS[department.toLowerCase()] ?? '#666';
  const initial = callsign.charAt(0).toUpperCase();
  const style: CSSProperties = {
    width: size, height: size, borderRadius: '50%',
    background: color,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    color: '#0a0a12', fontWeight: 600, fontSize: size * 0.5,
    flexShrink: 0,
  };
  return <span style={style} aria-label={`Agent ${callsign}`}>{initial}</span>;
}
```

**File:** `ui/src/components/IntentSurface.tsx`

- In the response handler (around line 200, where `addChatMessage('system', response)` runs after the fetch), branch on `data.per_agent_replies`:
  - If non-empty: for each `{agent_id, callsign, text}`, call `addChatMessage('agent', text, { agent_id, callsign })`.
  - Else: existing `addChatMessage('system', response)` path runs unchanged.
- In the message-render loop, when `m.role === 'agent'`, prepend `<AgentAvatarBadge ... />` to the rendered row. Department comes from the local `agents` Map lookup (the same store selector used by D3).
- **Do NOT touch `AgentProfilePanel.tsx:197-198`** (the inline 8×8 dot). Refactoring that to use the new badge is scope creep.
- **Do NOT use `CrewAvatarPopout`** in chat — it's the 3D VRM popout, wrong size/weight.
- **Do NOT introduce a third-party avatar library.**

> **DRY note:** if reusing `DEPT_COLORS` from both `AgentAvatarBadge.tsx` AND `AgentProfilePanel.tsx:22` becomes a duplication concern, the Builder MAY (small/low-risk) extract to `ui/src/utils/deptColors.ts` and import from both — but ONLY if the diff stays trivial. Otherwise leave duplicate.

### D8. Tests — Python (≥ 12 boundary tests)

**New file:** `tests/test_ad719_chat_fanout.py`

Each public method exercised must have at minimum: happy path, error/edge case, empty/None where applicable.

| # | Test | Validates |
|---|---|---|
| 1 | `test_extract_all_leading_callsigns_zero_mentions` | New helper returns `([], full_text)` when no `@` token. |
| 2 | `test_extract_all_leading_callsigns_one_mention` | Returns `(["counselor"], "...")`. |
| 3 | `test_extract_all_leading_callsigns_n_mentions` | Returns `(["counselor", "worf", "echo"], "...")` with the trailing message intact. |
| 4 | `test_extract_all_leading_callsigns_unknown_callsign` | Helper does NOT validate against the registry; resolution is the caller's job. |
| 5 | `test_chat_fanout_zero_mentions_falls_through_to_nl` | POST `/api/chat` with no `@` — existing `process_natural_language` path runs; `per_agent_replies == []`. |
| 6 | `test_chat_fanout_single_mention_uses_existing_dm_path` | POST `@counselor hi` — uses the single-mention DM short-circuit (L107-126); `per_agent_replies == []`, response is the DM result. |
| 7 | `test_chat_fanout_two_mentions_dispatches_in_parallel` | POST `@counselor @worf hello team` — `intent_bus.send` invoked twice; `per_agent_replies` length 2 with both callsigns. |
| 8 | `test_chat_fanout_unknown_callsign_returns_stub` | POST `@counselor @ghost hi` — counselor reply present; ghost gets `text="(not currently on duty)"` stub. |
| 9 | `test_chat_fanout_offline_agent_returns_stub` | POST mention of an on-registry but `agent_id is None` callsign — stub reply for that recipient; others succeed. |
| 10 | `test_chat_response_model_backward_compat` | `ChatResponse(response="x")` validates with empty `mentions` / `per_agent_replies` defaults. |
| 11 | `test_chat_response_per_agent_reply_shape` | `PerAgentReply(agent_id="a", callsign="counselor", text="hi")` round-trips through Pydantic. |
| 12 | `test_chat_fanout_does_not_touch_consensus` | Asserts no import/call into `probos.consensus` from the fan-out branch (use `unittest.mock.patch` on `probos.consensus.quorum` to fail-fast if invoked). |

**New file:** `tests/test_ad719_episodic_writes.py`

| # | Test | Validates |
|---|---|---|
| 13 | `test_fanout_writes_one_episode_per_reply` | Two-mention fan-out → `episodic_memory.store` called twice with distinct `agent_ids`. |
| 14 | `test_fanout_skips_episode_for_stub_reply` | Unknown-callsign stubs do NOT produce an episode (only resolved replies do). |
| 15 | `test_fanout_episode_source_tag_is_multi_agent_chat` | Stored Episode `.source == "multi_agent_chat"` (or whatever tag the Builder picks; assert it's distinct from `"direct"`). |

> **Test gate command (single file):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad719_chat_fanout.py tests/test_ad719_episodic_writes.py -v -n 0 --timeout=60`. **Wave gate:** `pytest tests/ -q -n 16 --dist=loadfile` is green; if `-n 16` regresses (heavy fixture concurrency), drop to `-n 8` and document in the build report — do **not** silently switch to `-n auto` (BF #466).

### D9. Tests — UI (Vitest)

**New file:** `ui/src/__tests__/IntentSurface.atMention.test.tsx`

Component-level coverage:

1. Typing `@e` in the input opens a popover containing matching crewmembers.
2. Pressing Enter on the focused row adds the matched crewmember as a chip; the input replaces `@e` with `@<full-callsign> `.
3. Clicking outside the popover closes it.
4. Multi-select: typing `@counselor @worf` produces two chips and two `per_agent_replies` rendered rows when the mocked `/api/chat` returns the fan-out shape.
5. Removing a chip via the SVG `x` removes the matching `@<callsign>` token from the input.
6. **No emoji in any rendered glyph** — assert by querying the DOM for codepoints in common emoji ranges (`\u{1F300}-\u{1FAFF}`, `\u{2600}-\u{27BF}`, etc.) and asserting empty result.

Mock `/api/chat` with `vi.fn()` returning a stub `ChatResponse` shape.

> **UI test gate:** `cd ui && npx vitest run` MUST be green. If Vitest is not yet wired locally, follow `prompts/archive/setup-vitest.md`.

## 7. Cross-AD integration with AD-720

| Touchpoint | This AD's responsibility | AD-720's responsibility |
|---|---|---|
| `ChatMessage` shape | Widens `role`; adds `agent_id`/`callsign`. | Adds optional `attachments?: ChatAttachment[]`. |
| `IntentSurface.tsx` | Owns input area, `@`-picker, chip strip, multi-reply rendering. | Adds paste handler + preview thumbnail + paperclip-icon (placeholder tooltip in v1). |
| `/api/chat` request body | Pass-through `mentions` (parsed by decomposer; no body change). | Adds optional `attachment_ids: string[]` field. |
| `/api/chat` response body | Adds `mentions` + `per_agent_replies`. | No change. |
| Episodic writes | One episode per fanned-out reply. | Episode metadata records `attachment_ids` if any. |
| **Build order** | **AD-719 lands as commit N — full diff merged FIRST.** | AD-720 lands as commit N+1, builds on top of AD-719's widened `ChatMessage`. **Builder MUST NOT interleave commits.** |

## 8. Hard-stop conditions for the Builder

Standard hard-stops from `BUILDER-EXECUTION-PLAN.md` apply, **plus** (verbatim from `WAVE-135-DISPATCH.md` §8):

1. **Phantom field on `ChatMessage`.** If tests reference a `ChatMessage` field this AD didn't actually add (e.g. `mentions: string[]` instead of `agent_id` + `callsign`), STOP — do not silently add the field elsewhere.
2. **Working-tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain (per `/memories/probos-architect-learnings.md` 2026-05-08 incident).
3. **Emoji literal in the diff.** Hard stop. Inline SVG only.
4. **Consensus/quorum coupling.** Any commit from this AD that touches `src/probos/consensus/` is a hard stop. Multi-target chat is fan-out, NOT deliberation.
5. **Episodic write skipped on a fan-out branch.** Hard stop. Every resolved reply produces an episode.
6. **Architectural change required** (modify `BaseAgent`/`IntentMessage`/`ChatRequest` protocols). Hard stop.
7. **PROGRESS.md L11 stale.** Pre-flight: confirm `current highest AD: AD-721i` is the line. If stale, update in-wave; otherwise leave alone.

## 9. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specifically (Builder confirms each in the build report):
- **Defense in depth:** server re-validates callsigns via `runtime.callsign_registry.resolve(...)`; no client trust.
- **No private-attr access:** runtime exposes parsed `mentions` via the public response payload; no reaching into `decomposer._callsign_map` from `chat.py`.
- **Fail-fast tier:** episodic-write failure is **log-and-degrade** (warn + continue) — does NOT propagate. Mention-resolution failure is **log-and-degrade** (stub reply for that recipient).
- **DRY:** `extract_all_leading_callsign_mentions` lives next to `extract_callsign_mention` in `crew_profile.py` and reuses the same regex primitive. NO parallel parser.
- **No emoji in HXI** (HXI Design Principle #3): all icons inline SVG `strokeWidth: 1.5`, `strokeLinecap: 'round'`. Active amber `#f0b060`, inactive `#666680`.
- **Episodic completeness:** every fan-out reply produces an episode (D6).
- **Async discipline:** `asyncio.gather(...)` is used for parallel fan-out; the gather call's exceptions are handled per-reply (`return_exceptions=True` recommended; if one DM fails, others still return).
- **Type annotations:** `PerAgentReply` is fully typed; the new `extract_all_leading_callsign_mentions` helper has full annotations.
- **Logging quality:** every `logger.warning(...)` includes context (callsign, error type, what next).

## 10. Acceptance criteria

- All ≥ 12 Python tests + 1 Vitest test pass.
- `pytest tests/ -q -n 16 --dist=loadfile` is green (or `-n 8` with build-report note if `-n 16` regresses).
- `cd ui && npx vitest run` is green.
- Phantom-API pre-check on this prompt body returns zero true phantoms (the `.tsx` and `APIRouter` candidates are known false positives — note in build report).
- GH issue [#513](https://github.com/seangalliher/ProbOS/issues/513) closed in the merge commit.
- **Files touched (target list):**
  - **New:** `ui/src/components/AgentAvatarBadge.tsx`, `tests/test_ad719_chat_fanout.py`, `tests/test_ad719_episodic_writes.py`, `ui/src/__tests__/IntentSurface.atMention.test.tsx`. Optionally `ui/src/utils/deptColors.ts` if extraction stays trivial.
  - **Modified:** `ui/src/store/types.ts`, `ui/src/store/useStore.ts`, `ui/src/components/IntentSurface.tsx`, `src/probos/routers/chat.py`, `src/probos/api_models.py`, `src/probos/crew_profile.py` (new helper).
  - **Untouched (hard stop if modified):** `src/probos/consensus/**`, `ui/src/components/profile/AgentProfilePanel.tsx:197-198`, `ui/src/components/profile/CrewAvatarPopout.tsx`, `ui/src/components/profile/ProfileChatTab.tsx`.

## 11. Forward markers (file at gate-3 per `BUILDER-EXECUTION-PLAN.md` Post-Sweep step 6)

| Marker | Scope |
|---|---|
| **AD-719a** | Persistent multi-agent threads under WardRoom (mental model b — crew see each other and chime in mid-thread). |
| **AD-719b** | Copilot-style left rail + Agents nav (mental model c — UI refactor). |
| **AD-719c** | `@`-picker keyboard navigation polish (↑/↓ arrow nav, Esc-to-close, Tab-completion). v1 ships mouse + Enter only per Captain ruling 2026-05-09. |

## 12. AD-numbering

Highest pre-existing AD at HEAD: **AD-721i** (per `PROGRESS.md` L11, confirmed 2026-05-09).

| AD | Status |
|---|---|
| AD-718 / AD-718-1 | SHIPPED / forward marker. |
| **AD-719** | **THIS PROMPT — issue #513.** |
| AD-719a / 719b / 719c | Reserved forward markers (file at gate-3). |
| AD-720 | Same wave, ships SECOND as commit N+1. See `prompts/ad-720-chat-attachments-image-paste-v1.md`. |
| AD-721 / 721a–721i | In flight or shipped (Wave 133/134). |

No collisions. Drafter re-greps `DECISIONS.md` and `decisions-era-*.md` for `AD-719a`/`b`/`c` labels before finalizing — none present at HEAD 2026-05-09.
