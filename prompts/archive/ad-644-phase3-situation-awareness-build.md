# AD-644 Phase 3 Build Prompt: Situation Awareness for Cognitive Chain

**Issue:** #285
**Priority:** High — agents on the chain path have innate faculties (Phase 2) but zero
environmental perception. They know who they are and what time it is, but not what's
happening around them. Ward Room activity, alerts, events, subordinate stats, games —
all invisible to ANALYZE.
**Scope:** 2 files modified, 1 test file created

## Context

Phase 1 restored duty context. Phase 2 restored innate faculties (temporal, working
memory, self-monitoring, confabulation guard, etc.). Phase 3 completes the perceptual
pipeline by giving ANALYZE the same environmental data the one-shot path has.

**Root cause:** `observation["context"]` is empty for every `proactive_think` chain
execution. The `IntentMessage` (proactive.py line 552) stores all dynamic data in
`params.context_parts`, not in `context`. ANALYZE reads `context.get("context", "")`
which is always `""`. Meanwhile, `_build_user_message()` (the one-shot path) reads
all 7 environmental items directly from `context_parts`.

**After Phase 3:** The 23-item parity checklist will have 21 of 23 items covered.
Only Phase 4 (standing orders markdown — 2 items) and Phase 5 (deprecation) remain.

## Design

### Approach: Observation dict pass-through (NOT new QUERY operations)

The research doc proposed adding 7 new QUERY operations to `query.py` that call
services directly. However, `_gather_context()` in `proactive.py` already calls these
exact services and puts the data in `context_parts`. The one-shot path still needs
`_gather_context()` for DMs and other intents. Adding QUERY operations that re-call
the same services would violate DRY and waste runtime cycles.

**Decision:** Follow Phase 2's pattern — extract from `context_parts` in
`_execute_chain_with_intent_routing()`, inject into observation dict, render in ANALYZE.
When NATS decouples the pipeline (AD-641g), QUERY becomes a real autonomous perception
step and `_gather_context()` gets refactored. Until then, pass-through is correct.

**Why this doesn't violate the research doc's intent:** The research doc's Category 2
design describes *what the agent should perceive*, not *how it should be gathered*.
The gathering mechanism (`_gather_context()`) already works. Phase 3's job is to get
that data into the chain's prompt templates. The QUERY-operation approach was designed
for a NATS-decoupled future; the observation-dict approach gets parity now.

### Data sources (all from `context_parts`)

| Observation Key | `context_parts` Key | One-Shot Reference | What It Contains |
|----------------|---------------------|-------------------|-----------------|
| `_ward_room_activity` | `ward_room_activity` | Lines 3660-3699 | Dept + All Hands + Rec activity, filtered, scored, sorted |
| `_recent_alerts` | `recent_alerts` | Lines 3644-3649 | Bridge alerts: severity, title, source |
| `_recent_events` | `recent_events` | Lines 3652-3658 | System events: category, event, agent_type |
| `_infrastructure_status` | `infrastructure_status` | Lines 3564-3570 | LLM backend health: status, message |
| `_subordinate_stats` | `subordinate_stats` | Lines 3590-3602 | Chief-only: per-subordinate posts, endorsements, credibility |
| `_cold_start_note` | `system_note` | Lines 3558-3562 | BF-034: Fresh-start advisory after reset |
| `_active_game` | `active_game` | Lines 3686-3702 | BF-110: Game board, turn status, valid moves |

### What does NOT change

- **`proactive.py`** — `_gather_context()` untouched, continues to populate `context_parts`
- **`query.py`** — no new QUERY operations; existing `unread_counts` + `trust_score` operations unchanged
- **`compose.py`** — COMPOSE does NOT render environmental data. Ward Room activity, alerts, events, etc. inform ANALYZE's situation assessment, not the composed response. COMPOSE already has innate faculties from Phase 2.
- **`_build_chain_for_intent()`** — `context_keys` tuple unchanged; the QUERY step still runs `unread_counts` and `trust_score` as before
- **Skill injection** — the one-shot path ties skill framing to Ward Room activity (lines 3662-3669). The chain path handles skill injection separately via `_inject_skills()` in compose.py. Do NOT duplicate skill framing in Phase 3.

---

## Change 1: `src/probos/cognitive/cognitive_agent.py` — Situation awareness extraction

### New method: `_build_situation_awareness()`

**Location:** Place near `_build_cognitive_state()` (Phase 2 method).

```python
    def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]:
        """AD-644 Phase 3: Extract situation awareness data for chain prompts.

        Returns a dict of observation keys → rendered strings. Called from
        _execute_chain_with_intent_routing() after Phase 2 cognitive state.

        These are environmental percepts — what's happening around the agent.
        The one-shot path renders these inline in _build_user_message().
        This method extracts them into observation keys so ANALYZE can
        render the current situation.
        """
        state: dict[str, str] = {}

        # 1. Ward Room activity (AD-413) — dept + all-hands + recreation
        wr_activity = context_parts.get("ward_room_activity", [])
        if wr_activity:
            wr_lines: list[str] = []
            wr_lines.append("Recent Ward Room discussion:")
            for a in wr_activity:
                prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
                ids = ""
                if a.get("thread_id"):
                    ids += f" thread:{a['thread_id'][:8]}"
                if a.get("post_id"):
                    ids += f" post:{a['post_id'][:8]}"
                score = a.get("net_score", 0)
                score_str = f" [+{score}]" if score > 0 else f" [{score}]" if score < 0 else ""
                channel = f" ({a['channel']})" if a.get("channel") else ""
                wr_lines.append(
                    f"  - {prefix}{ids}{score_str} {a.get('author', '?')}{channel}: "
                    f"{a.get('body', '?')}"
                )
            state["_ward_room_activity"] = "\n".join(wr_lines)

        # 2. Recent bridge alerts
        alerts = context_parts.get("recent_alerts", [])
        if alerts:
            alert_lines = ["Recent bridge alerts:"]
            for a in alerts:
                alert_lines.append(
                    f"  - [{a.get('severity', '?')}] {a.get('title', '?')} "
                    f"(from {a.get('source', '?')})"
                )
            state["_recent_alerts"] = "\n".join(alert_lines)

        # 3. Recent system events
        events = context_parts.get("recent_events", [])
        if events:
            event_lines = ["Recent system events:"]
            for e in events:
                event_lines.append(
                    f"  - [{e.get('category', '?')}] {e.get('event', '?')}"
                )
            state["_recent_events"] = "\n".join(event_lines)

        # 4. Infrastructure status (AD-576)
        infra = context_parts.get("infrastructure_status")
        if infra:
            llm_status = infra.get("llm_status", "unknown")
            state["_infrastructure_status"] = (
                f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]\n"
                f"{infra.get('message', '')}"
            )

        # 5. Subordinate stats (AD-630) — Chiefs only
        sub_stats = context_parts.get("subordinate_stats")
        if sub_stats:
            sub_lines = ["<subordinate_activity>"]
            for callsign, stats in sub_stats.items():
                sub_lines.append(
                    f"  {callsign}: {stats['posts_total']} posts, "
                    f"{stats['endorsements_given']} endorsements given, "
                    f"{stats['endorsements_received']} endorsements received, "
                    f"credibility {stats['credibility_score']:.2f}"
                )
            sub_lines.append("</subordinate_activity>")
            state["_subordinate_stats"] = "\n".join(sub_lines)

        # 6. Cold-start system note (BF-034)
        system_note = context_parts.get("system_note")
        if system_note:
            state["_cold_start_note"] = system_note

        # 7. Active game state (BF-110)
        active_game = context_parts.get("active_game")
        if active_game:
            game_lines = [
                f"You are playing {active_game['game_type']} against "
                f"{active_game['opponent']}. "
                f"Moves so far: {active_game['moves_count']}.",
                f"\nCurrent board:\n```\n{active_game['board']}\n```",
            ]
            if active_game["is_my_turn"]:
                game_lines.append(
                    f"**It is YOUR turn.** Valid moves: "
                    f"{', '.join(str(m) for m in active_game['valid_moves'])}. "
                    f"Reply with [MOVE position] to play."
                )
            else:
                game_lines.append("Waiting for your opponent to move.")
            state["_active_game"] = "\n".join(game_lines)

        return state
```

### Injection point in `_execute_chain_with_intent_routing()`

**Location:** After the Phase 2 injection (which is after the Phase 1 block).
There should be a line like:

```python
        _cognitive_state = self._build_cognitive_state(_context_parts)
        observation.update(_cognitive_state)
```

**Insert immediately after that block:**

```python
        # AD-644 Phase 3: Situation awareness — environmental perception
        _situation = self._build_situation_awareness(_context_parts)
        observation.update(_situation)
```

Two lines. All rendering logic is in the method.

---

## Change 2: `src/probos/cognitive/sub_tasks/analyze.py` — ANALYZE prompt

**Location:** `_build_situation_review_prompt()`. The Phase 2 build prompt added an
`innate_section` between `duty_section` and `## Current Situation`. Phase 3 replaces
the empty `situation_content` with the actual environmental data.

**Current state after Phase 2** (the relevant section):

```python
    situation_content = context.get("context", "")
    # ... context_section, memory_section, duty_section, innate_section ...
    user_prompt = (
        f"{duty_section}"
        f"{innate_section}"
        f"## Current Situation\n\n{situation_content}\n\n"
        ...
    )
```

**Problem:** `situation_content` is always empty for `proactive_think` because
`observation["context"]` is never set (the IntentMessage has no `context` field).

**Fix:** Build `situation_content` from the Phase 3 observation keys. Replace the
`situation_content = context.get("context", "")` line and expand the situation section.

**Replace the `situation_content` assignment and the user_prompt construction.**

After the Phase 2 `innate_section` block (and before the `user_prompt = ...`
construction), insert:

```python
    # AD-644 Phase 3: Build situation content from environmental perception keys.
    # For proactive_think, context.get("context") is empty — all dynamic data
    # arrives via observation dict keys populated from context_parts.
    situation_parts: list[str] = []

    # Original context (non-empty for ward_room_notification, empty for proactive_think)
    _raw_context = context.get("context", "")
    if _raw_context:
        situation_parts.append(_raw_context)

    # Cold-start note (BF-034)
    _cold_start = context.get("_cold_start_note", "")
    if _cold_start:
        situation_parts.append(_cold_start)

    # Infrastructure status (AD-576)
    _infra = context.get("_infrastructure_status", "")
    if _infra:
        situation_parts.append(_infra)

    # Ward Room activity (AD-413)
    _wr_activity = context.get("_ward_room_activity", "")
    if _wr_activity:
        situation_parts.append(_wr_activity)

    # Recent alerts
    _alerts = context.get("_recent_alerts", "")
    if _alerts:
        situation_parts.append(_alerts)

    # Recent events
    _events = context.get("_recent_events", "")
    if _events:
        situation_parts.append(_events)

    # Subordinate stats (AD-630) — Chiefs
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        situation_parts.append(_sub_stats)

    # Active game (BF-110)
    _game = context.get("_active_game", "")
    if _game:
        situation_parts.append(f"--- Active Game ---\n{_game}")

    situation_content = "\n\n".join(situation_parts) if situation_parts else ""
```

**Then remove or replace the original `situation_content = context.get("context", "")`
line** — the new block above supersedes it.

The `user_prompt` construction remains the same structure:

```python
    user_prompt = (
        f"{duty_section}"
        f"{innate_section}"
        f"## Current Situation\n\n{situation_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        "## Assessment Required\n\n"
        ...  # unchanged
    )
```

**What changes:** `situation_content` goes from always-empty to populated with
Ward Room activity, alerts, events, infrastructure status, subordinate stats,
cold-start notes, and game state. ANALYZE can now actually assess the situation.

---

## Change 3: Test File — `tests/test_ad644_phase3_situation_awareness.py`

### Test 1: `test_build_situation_awareness_ward_room_activity`
- Create a CognitiveAgent with `agent_id="test-agent"`
- Call `agent._build_situation_awareness({"ward_room_activity": [{"type": "thread", "author": "Bones", "body": "[abc12345] Status update", "thread_id": "abc12345678", "post_id": "def87654321", "net_score": 2, "created_at": 1000.0}]})`
- Assert `"_ward_room_activity"` in result
- Assert result contains `"Bones"` and `"thread:abc12345"` and `"[+2]"`

### Test 2: `test_build_situation_awareness_ward_room_with_channel`
- Same but activity item includes `"channel": "All Hands"`
- Assert result contains `"(All Hands)"`

### Test 3: `test_build_situation_awareness_alerts`
- Call with `{"recent_alerts": [{"severity": "WARNING", "title": "High latency", "source": "VitalsMonitor"}]}`
- Assert `"_recent_alerts"` in result
- Assert result contains `"[WARNING]"`, `"High latency"`, `"VitalsMonitor"`

### Test 4: `test_build_situation_awareness_events`
- Call with `{"recent_events": [{"category": "TRUST", "event": "Trust updated for agent-1"}]}`
- Assert `"_recent_events"` in result
- Assert result contains `"[TRUST]"` and `"Trust updated"`

### Test 5: `test_build_situation_awareness_infrastructure`
- Call with `{"infrastructure_status": {"llm_status": "degraded", "message": "Backend timeout"}}`
- Assert `"_infrastructure_status"` in result
- Assert result contains `"degraded"` and `"Backend timeout"`

### Test 6: `test_build_situation_awareness_subordinate_stats`
- Call with `{"subordinate_stats": {"Kira": {"posts_total": 5, "endorsements_given": 2, "endorsements_received": 3, "credibility_score": 0.75}}}`
- Assert `"_subordinate_stats"` in result
- Assert result contains `"Kira"`, `"5 posts"`, `"0.75"`
- Assert result contains `"<subordinate_activity>"` and `"</subordinate_activity>"`

### Test 7: `test_build_situation_awareness_cold_start`
- Call with `{"system_note": "SYSTEM NOTE: This is a fresh start..."}`
- Assert `"_cold_start_note"` in result
- Assert result contains `"fresh start"`

### Test 8: `test_build_situation_awareness_active_game_my_turn`
- Call with `{"active_game": {"game_type": "tictactoe", "opponent": "Chapel", "moves_count": 3, "board": " X | O | \n-----------\n   |   | X\n-----------\n   | O |  ", "is_my_turn": True, "valid_moves": [3, 4, 6, 7, 9]}}`
- Assert `"_active_game"` in result
- Assert result contains `"YOUR turn"`, `"Chapel"`, `"tictactoe"`

### Test 9: `test_build_situation_awareness_active_game_not_my_turn`
- Same game but `is_my_turn: False`
- Assert result contains `"Waiting for your opponent"`
- Assert `"YOUR turn"` NOT in result

### Test 10: `test_build_situation_awareness_empty`
- Call with empty dict `{}`
- Assert result is empty dict (no keys set)

### Test 11: `test_analyze_prompt_includes_situation_content`
- Import `_build_situation_review_prompt` from `probos.cognitive.sub_tasks.analyze`
- Build a context dict with:
  - `_agent_type`: `"agent"`
  - `_agent_rank`: `None`
  - `_skill_profile`: `None`
  - `_ward_room_activity`: `"Recent Ward Room discussion:\n  - [thread] Bones: Status update"`
  - `_recent_alerts`: `"Recent bridge alerts:\n  - [WARNING] High latency (from VitalsMonitor)"`
  - `_cold_start_note`: `"SYSTEM NOTE: Fresh start after reset."`
  - `context`: `""` (empty, as in real proactive_think)
- Call `_build_situation_review_prompt(context, [], "Echo", "Medical")`
- Assert the user_prompt contains `"## Current Situation"`
- Assert `"Ward Room discussion"` in user_prompt
- Assert `"WARNING"` in user_prompt
- Assert `"Fresh start"` in user_prompt
- Assert `"## Assessment Required"` still appears

### Test 12: `test_analyze_prompt_preserves_raw_context`
- Same but set `context: "Thread about engineering report"` (non-empty, as in ward_room_notification)
- Assert `"engineering report"` appears in user_prompt (raw context preserved)

### Test 13: `test_observation_dict_receives_situation_awareness`
- Integration test: verify wiring in `_execute_chain_with_intent_routing()`
- Create a CognitiveAgent
- Mock `_build_situation_awareness` to return `{"_ward_room_activity": "test-wr", "_recent_alerts": "test-alerts"}`
- Mock `_sub_task_executor.execute_chain` to capture the observation dict
- Call `_execute_chain_with_intent_routing()` with proactive_think intent and `params` containing `context_parts: {}`
- Assert the captured observation contains `_ward_room_activity` == `"test-wr"` and `_recent_alerts` == `"test-alerts"`

### CognitiveAgent construction for tests:

```python
agent = CognitiveAgent(agent_id="test-agent")
```

### Import patterns:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
```

---

## What NOT to change

- **Do NOT modify `proactive.py`** — `_gather_context()` already gathers all data
- **Do NOT modify `query.py`** — no new QUERY operations; deferred to AD-641g (NATS)
- **Do NOT modify `compose.py`** — environmental data informs assessment (ANALYZE), not composition (COMPOSE)
- **Do NOT modify `_build_chain_for_intent()`** — `context_keys` unchanged
- **Do NOT add skill framing to Ward Room rendering** — the chain's COMPOSE step handles skill injection separately via `_inject_skills()`
- **Do NOT modify `_build_user_message()`** — one-shot path is reference, not a change target
- **Do NOT modify `_build_cognitive_state()`** — Phase 2 method is complete

## Engineering Principles Compliance

| Principle | How |
|-----------|-----|
| **SRP** | `_build_situation_awareness()` has one job: extract environmental percepts. ANALYZE renders. Clear separation. |
| **Open/Closed** | New observation keys added without modifying chain plumbing or QUERY dispatch. ANALYZE prompt extended, not rewritten. |
| **DRY** | Data gathered once in `_gather_context()`, passed through `context_parts`, extracted once in `_build_situation_awareness()`. No duplicate service calls. Rendering format matches one-shot path exactly. |
| **Law of Demeter** | Method reads from `context_parts` dict (passed as parameter). No reaching through `self._runtime` or other objects. |
| **Fail Fast** | Missing data = key not set = section skipped. Ward Room activity empty = no `_ward_room_activity` key = `## Current Situation` section empty = ANALYZE assesses based on what it has. |

## Validation

```bash
python -m pytest tests/test_ad644_phase3_situation_awareness.py -v
python -m pytest tests/ -k "ad644 or analyze" --timeout=30 -x
```

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | `_build_situation_awareness()` method (~90 lines) + 2-line injection |
| `src/probos/cognitive/sub_tasks/analyze.py` | ~35-line situation content builder in `_build_situation_review_prompt()` |
| `tests/test_ad644_phase3_situation_awareness.py` | 13 new tests |

## Parity Status After Phase 3

| Phase | Items | Status |
|-------|-------|--------|
| Phase 1 (Duty) | #1 duty framing, #2 agent metrics, #22 duty instructions | Complete |
| Phase 2 (Innate) | #3 temporal, #4 working memory, #7 ontology, #9 orientation, #12 confab guard, #13 source attribution, #17 comm proficiency, #20 self-monitoring, #21 telemetry | Complete |
| Phase 3 (Situation) | #5 cold-start, #6 infrastructure, #8 subordinate stats, #15 alerts, #16 events, #18 Ward Room activity, #19 active game | This prompt |
| Phase 4 (Standing Orders) | #14 source attribution policy, #23 duty reporting policy | Markdown-only, zero code |
| Already Flows | #10 skill profile, #11 episodic memories | No work needed |

**After Phase 3: 21 of 23 items complete. Chain path has full perceptual parity.**
