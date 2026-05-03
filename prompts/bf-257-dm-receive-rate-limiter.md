# BF-257: DM Receive Rate Limiter — Break Ping-Pong Loops

**Priority:** P0 — Observed production incident (2026-05-02): three Science agents (Atlas, Sage, Lyra) entered a DM ping-pong loop that exhausted all LLM capacity, caused cascading JSON parse failures across the crew, collapsed routing entropy to 0.00, and triggered a false `greet_user` capability gap for the Captain.

**Root Cause:** Multiple DM rate-limiting mechanisms exist on the **send** side (BF-163 send cooldown, AD-614 self-similarity, AD-623 convergence), but none limit how many times an agent **responds to incoming DMs** in a window. The send cooldown is unidirectional per-pair — A→B and B→A are tracked independently. Combined with BF-184/187's social obligation auto-approve (DMs bypass evaluate/reflect quality gates), this creates an unthrottled feedback loop:

```
Agent A sends DM to Agent B
  → B gets unread DM notification (_check_unread_dms)
  → B routes through cognitive chain (auto-approved by BF-187)
  → B composes reply DM to A
  → A gets unread DM notification
  → A routes through cognitive chain (auto-approved by BF-187)
  → A composes reply DM to B
  → (repeat indefinitely)
```

**What This Does NOT Change:**
- BF-163 send cooldown logic (still needed for non-loop flood scenarios)
- AD-614 self-similarity gate (still needed for dedup)
- AD-623 DM convergence gate (still needed for thread-level convergence)
- BF-184/187 social obligation bypass in evaluate.py/reflect.py (DMs should still auto-approve when budget permits)
- AD-643b undeclared action detection (re-reflect feedback loop is a separate concern)
- Captain DMs (always exempt from rate limiting)

---

## Implementation

### 1. Add Config Fields to `WardRoomConfig`

**File:** `src/probos/config.py`

Around line 1243, after the `event_coalesce_ms` field, add:

```python
    dm_response_budget: int = 6             # BF-257: max DM responses per agent per window
    dm_response_window_seconds: float = 600.0  # BF-257: sliding window (10 minutes)
    dm_pair_exchange_budget: int = 8        # BF-257: max exchanges per A↔B pair per window
```

**Rationale:** 6 DM responses per 10 minutes allows substantive multi-thread DM conversations while preventing unbounded loops. 8 per-pair catches bilateral loops specifically. Both values are configurable for tuning.

### 2. Add Receive Tracking State to `ProactiveCognitiveLoop.__init__`

**File:** `src/probos/proactive.py`

Around line 188-190 (after the `_notified_dm_threads_reset` initializer; verify with content-anchored SEARCH on `self._notified_dm_threads_reset = time.monotonic()  # hourly reset`), add:

```python
        self._dm_response_counts: dict[str, list[float]] = {}  # BF-257: agent_id -> [timestamps]
        self._dm_pair_counts: dict[str, list[float]] = {}      # BF-257: "a_id:b_id" -> [timestamps]
```

### 3. Add Rate Limit Check Method

**File:** `src/probos/proactive.py`

Add a new private method on `ProactiveCognitiveLoop`. Place it near the existing `_check_unread_dms` method (after the `_check_unread_dms` body ends; around line 626-629 — verify by content-anchored SEARCH on the closing `except Exception as exc:` block of `_check_unread_dms`). The class is `ProactiveCognitiveLoop` (not `ProactiveCognitive` — verify at `src/probos/proactive.py:146`).

```python
    def _dm_response_budget_exceeded(
        self, agent_id: str, partner_id: str, config: "WardRoomConfig",
    ) -> str | None:
        """BF-257: Check if agent has exceeded DM response budget.

        Returns a reason string if budget is exceeded, None if allowed.
        Uses a sliding window — expired timestamps are pruned on each call.
        """
        now = time.monotonic()
        window = config.dm_response_window_seconds
        cutoff = now - window

        # Layer 1: Per-agent global DM response budget
        budget = config.dm_response_budget
        agent_times = self._dm_response_counts.get(agent_id, [])
        agent_times = [t for t in agent_times if t > cutoff]
        self._dm_response_counts[agent_id] = agent_times
        if len(agent_times) >= budget:
            return f"agent_budget ({len(agent_times)}/{budget} in {window:.0f}s)"

        # Layer 2: Per-pair exchange budget (bidirectional key)
        pair_budget = config.dm_pair_exchange_budget
        pair_key = ":".join(sorted([agent_id, partner_id]))
        pair_times = self._dm_pair_counts.get(pair_key, [])
        pair_times = [t for t in pair_times if t > cutoff]
        self._dm_pair_counts[pair_key] = pair_times
        if len(pair_times) >= pair_budget:
            return f"pair_budget ({len(pair_times)}/{pair_budget} in {window:.0f}s)"

        return None
```

**Design notes:**
- **Bidirectional pair key:** `sorted([a, b])` ensures A→B and B→A share the same counter. This is the key gap BF-163 didn't cover — BF-163 tracks A→B and B→A as separate keys.
- **Sliding window with lazy pruning:** Each check prunes expired timestamps. No background timer needed. Memory bounded by `budget` per key (max 6-8 entries per key).
- **Synchronous method:** No I/O needed — pure in-memory check. Called from async context but doesn't need to be async.

### 4. Gate DM Routing in `_check_unread_dms`

**File:** `src/probos/proactive.py`

In `_check_unread_dms` (the `for dm in unread_dms:` loop — verify by content-anchored SEARCH on `for dm in unread_dms:`), add the budget check **after** the dedup guard and **before** routing. The current code (preceded by the `# BF-164: pass exchange limit so query excludes capped threads` comment at the live source) is:

```python
            for dm in unread_dms:
                tid = dm["thread_id"]
                if tid in self._notified_dm_threads:
                    continue
                self._notified_dm_threads.add(tid)
                # Route through existing notification pipeline
                event_data = {
                    "thread_id": tid,
                    "channel_id": dm["channel_id"],
                    "author_id": dm["author_id"],
                    "author_callsign": dm["author_callsign"],
                    "title": dm["title"],
                    "body": dm["body"],
                }
                await rt.ward_room_router.route_event(
                    "ward_room_thread_created", event_data,
                )
                routed += 1
```

Replace with:

```python
            for dm in unread_dms:
                tid = dm["thread_id"]
                if tid in self._notified_dm_threads:
                    continue

                # BF-257: DM response budget check — skip Captain DMs.
                # v1: callsign-based check (case-insensitive). The Captain's
                # callsign is canonical at "Captain" per AD-499 ShipNamingPolicy
                # and BF-244 ontology callsign sync. If a future AD introduces a
                # canonical captain DID or `is_captain(rt, author_id)` helper,
                # this check should switch to identity-based.
                author_callsign = (dm.get("author_callsign") or "").strip().lower()
                if author_callsign != "captain":
                    wr_config = getattr(
                        getattr(rt, 'config', None), 'ward_room', None
                    )
                    if wr_config:
                        reason = self._dm_response_budget_exceeded(
                            agent.id, dm["author_id"], wr_config,
                        )
                        if reason:
                            logger.info(
                                "BF-257: %s DM response to @%s throttled (%s)",
                                getattr(agent, 'callsign', agent.agent_type),
                                dm.get("author_callsign", dm["author_id"]),
                                reason,
                            )
                            # Don't add to _notified_dm_threads — allow retry
                            # after window expires.
                            continue

                self._notified_dm_threads.add(tid)

                # BF-257: Record this DM response in budget trackers.
                now = time.monotonic()
                self._dm_response_counts.setdefault(agent.id, []).append(now)
                # Canonical pair key — A→B and B→A share the same counter.
                pair_key = ":".join(sorted([agent.id, dm["author_id"]]))
                self._dm_pair_counts.setdefault(pair_key, []).append(now)

                # Route through existing notification pipeline
                event_data = {
                    "thread_id": tid,
                    "channel_id": dm["channel_id"],
                    "author_id": dm["author_id"],
                    "author_callsign": dm["author_callsign"],
                    "title": dm["title"],
                    "body": dm["body"],
                }
                await rt.ward_room_router.route_event(
                    "ward_room_thread_created", event_data,
                )
                routed += 1
```

**Key behaviors:**
- **Caller audit:** `_check_unread_dms` has 1 caller: `_run_proactive_cycle` (around line 513 in proactive.py). The change is safe for this caller — it adds an early `continue` gate that defers (not drops) DM routing.
- Captain DMs are **always** exempt (checked before budget gate).
- Throttled DMs are NOT added to `_notified_dm_threads`, so they'll be retried on the next proactive cycle after the window expires. This preserves message delivery — just delays it.
- Budget timestamps are recorded **after** the budget check passes and **before** routing, ensuring the count is accurate.

### 5. Lower Default `dm_exchange_limit`

**File:** `src/probos/config.py`

Around line 1242, change:

```python
    dm_exchange_limit: int = 40          # BF-200: raised from 5 — DMs need room for substantive conversation
```

To:

```python
    dm_exchange_limit: int = 15          # BF-257: lowered from 40 — 15 still allows substantive DM conversations
```

**Rationale:** 40 posts per agent per thread is excessive. At 15, even a 2-agent DM thread allows 30 total posts (15 each) — more than enough for substantive conversation. The old value of 40 meant a pair could exchange 80 messages before the thread limit kicked in, far more than any productive DM exchange.

---

## Tests

**File:** `tests/test_bf257_dm_receive_rate_limiter.py`

Follow the pattern established in `tests/test_bf163_dm_send_flood.py` — source-level verification + behavioral unit tests.

```python
"""BF-257: DM receive rate limiter tests.

Verifies that the per-agent DM response budget and per-pair exchange budget
prevent ping-pong loops where agents auto-reply to each other's DMs
indefinitely, exhausting LLM capacity.
"""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Section 1: Source-level verification
# ---------------------------------------------------------------------------

class TestBf257SourcePresence:
    """BF-257: Verify rate limiter structures exist in source."""

    def test_dm_response_counts_initialized(self):
        """_dm_response_counts dict must be in __init__."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_response_counts" in source

    def test_dm_pair_counts_initialized(self):
        """_dm_pair_counts dict must be in __init__."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_pair_counts" in source

    def test_budget_check_method_exists(self):
        """_dm_response_budget_exceeded method must exist."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_response_budget_exceeded" in source

    def test_config_fields_exist(self):
        """WardRoomConfig must have BF-257 config fields."""
        source = Path("src/probos/config.py").read_text()
        assert "dm_response_budget" in source
        assert "dm_response_window_seconds" in source
        assert "dm_pair_exchange_budget" in source

    def test_dm_exchange_limit_lowered(self):
        """dm_exchange_limit default should be 15, not 40."""
        from probos.config import WardRoomConfig
        cfg = WardRoomConfig()
        assert cfg.dm_exchange_limit == 15


# ---------------------------------------------------------------------------
# Section 2: Budget check logic
# ---------------------------------------------------------------------------

class TestDmResponseBudget:
    """BF-257: _dm_response_budget_exceeded unit tests."""

    def _make_proactive(self):
        """Create minimal ProactiveCognitiveLoop-like object with BF-257 state."""
        obj = MagicMock()
        obj._dm_response_counts = {}
        obj._dm_pair_counts = {}
        # Import and bind the real method
        from probos.proactive import ProactiveCognitiveLoop
        import types
        obj._dm_response_budget_exceeded = types.MethodType(
            ProactiveCognitiveLoop._dm_response_budget_exceeded, obj,
        )
        return obj

    def _make_config(self, budget=6, window=600.0, pair_budget=8):
        cfg = MagicMock()
        cfg.dm_response_budget = budget
        cfg.dm_response_window_seconds = window
        cfg.dm_pair_exchange_budget = pair_budget
        return cfg

    def test_allows_first_dm(self):
        """First DM response should always be allowed."""
        p = self._make_proactive()
        cfg = self._make_config()
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is None

    def test_blocks_after_budget_exhausted(self):
        """Should block after budget responses in window."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 10, now - 5, now - 1]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is not None
        assert "agent_budget" in result

    def test_expired_timestamps_pruned(self):
        """Timestamps older than window should be pruned and not count."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=60.0)
        now = time.monotonic()
        # 3 timestamps, but all expired
        p._dm_response_counts["agent-a"] = [now - 120, now - 90, now - 61]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is None
        # Expired entries should be pruned
        assert len(p._dm_response_counts["agent-a"]) == 0

    def test_pair_budget_bidirectional(self):
        """A→B and B→A should share the same pair counter."""
        p = self._make_proactive()
        cfg = self._make_config(pair_budget=2, window=600.0)
        now = time.monotonic()
        # Use sorted key to verify bidirectionality
        pair_key = ":".join(sorted(["agent-a", "agent-b"]))
        p._dm_pair_counts[pair_key] = [now - 10, now - 5]
        # Check from A's perspective
        result_a = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result_a is not None
        assert "pair_budget" in result_a
        # Check from B's perspective — same pair key
        p._dm_pair_counts[pair_key] = [now - 10, now - 5]
        result_b = p._dm_response_budget_exceeded("agent-b", "agent-a", cfg)
        assert result_b is not None
        assert "pair_budget" in result_b

    def test_agent_budget_checked_before_pair(self):
        """Agent-level budget should be checked first."""
        p = self._make_proactive()
        cfg = self._make_config(budget=2, pair_budget=8, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 10, now - 5]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is not None
        assert "agent_budget" in result

    def test_different_partners_share_agent_budget(self):
        """DMs to different partners all count toward agent budget."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 30, now - 20, now - 10]
        # Third partner should still be blocked
        result = p._dm_response_budget_exceeded("agent-a", "agent-c", cfg)
        assert result is not None
        assert "agent_budget" in result


# ---------------------------------------------------------------------------
# Section 3: Integration — _check_unread_dms gating
# ---------------------------------------------------------------------------

class TestCheckUnreadDmsGating:
    """BF-257: Verify _check_unread_dms applies budget gate."""

    def test_budget_check_in_check_unread_dms(self):
        """_check_unread_dms must call _dm_response_budget_exceeded."""
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    assert "_dm_response_budget_exceeded" in body_source
                    assert "BF-257" in body_source
                    break
        else:
            pytest.fail("_check_unread_dms not found")

    def test_captain_dm_exempt(self):
        """Captain DMs must bypass the budget check."""
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    assert 'captain' in body_source.lower()
                    break
        else:
            pytest.fail("_check_unread_dms not found")

    def test_throttled_dm_not_added_to_notified(self):
        """Throttled DMs should NOT be added to _notified_dm_threads."""
        # Verify via source analysis: the 'continue' must come BEFORE
        # self._notified_dm_threads.add(tid)
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    # BF-257 continue must appear before notified_dm_threads.add
                    bf257_pos = body_source.find("BF-257")
                    continue_pos = body_source.find("continue", bf257_pos)
                    add_pos = body_source.find("_notified_dm_threads.add", continue_pos)
                    assert bf257_pos < continue_pos < add_pos, (
                        "BF-257 throttle 'continue' must come before _notified_dm_threads.add"
                    )
                    break
        else:
            pytest.fail("_check_unread_dms not found")
```

**Total: 12 tests** across 3 test classes (source presence, budget logic, integration gating).

---

## Existing Test Impact

Full live grep (2026-05-02) for `dm_exchange_limit` across `tests/` returns 8 files.
Classify each before committing:

**Asserts the default value (must update from 40 → 15):**
- `tests/test_ad614_dm_conversation_termination.py:106, 116` — `test_dm_exchange_limit_config_exists` asserts `config.dm_exchange_limit == 40`. Change to 15.
- `tests/test_bf200_thread_cap_awareness.py:46-48` — `test_dm_exchange_limit_default_40` method name + assertion. Rename to `test_dm_exchange_limit_default_15` and update value; keep a docstring referencing both BF-200 (raised from 5→40) and BF-257 (lowered from 40→15) for audit trail.

**Sets the value explicitly in test fixture (verify intent before changing):**
- `tests/test_unread_dms.py:147` — sets `rt.config.ward_room.dm_exchange_limit = 40`. Read the test: if it asserts behavior at the high cap, leave the explicit override in place. Otherwise reduce to match the new default (15).
- `tests/test_ad623_dm_convergence.py:75` — sets `config.ward_room.dm_exchange_limit = 6`. No change needed (test sets a low value intentionally).
- `tests/test_bf193_parallel_captain_dispatch.py:22` — sets `config.ward_room.dm_exchange_limit = 6`. No change needed.
- `tests/test_proactive.py:158` — sets `rt.config.ward_room.dm_exchange_limit = 6`. No change needed.

**References the field name only (no value assertion):**
- `tests/test_bf164_stale_unread_dm.py:71-77` — asserts SOURCE contains the string `dm_exchange_limit`. No change needed.
- `tests/test_bf201_thread_post_cap.py:202` — mentions `dm_exchange_limit` in a comment. No change needed.
- `tests/test_bf200_thread_cap_awareness.py:70, 74, 118` — calls `_post_cap_notification("thread-N", "agent-N", "dm_exchange_limit")` passing the field name as a string identifier. No change needed.

**Builder action:** before committing, re-grep `dm_exchange_limit` in `tests/` to catch any new references that may have landed since this list was generated.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **evaluate.py / reflect.py** — BF-184/187 social obligation auto-approve stays. The fix is at the receive/routing layer, not the cognitive chain quality gate.
2. **ward_room_router.py** — AD-623 convergence gate and AD-614 per-thread exchange limit stay unchanged. BF-257 operates at the proactive receive layer, upstream of the router.
3. **cognitive_agent.py** — AD-643b undeclared action detection and re-reflect are unchanged. Re-reflect still does not suppress undeclared DMs. (This is a separate concern — the rate limiter prevents the loop before it starts.)
4. **ward_room/messages.py** — `get_unread_dms()` SQL is unchanged. No read receipts needed.
5. **Any NATS subjects/streams/consumers** — This is pure in-memory rate limiting. No NATS state touched.

---

## Engineering Principles Compliance

- **Single Responsibility:** Rate limiting logic is contained in one new method (`_dm_response_budget_exceeded`) with a single concern. Config in WardRoomConfig (where all DM config lives). Gate in `_check_unread_dms` (where DMs enter the system).
- **Open/Closed:** Extends existing `_check_unread_dms` with a new gate — no changes to existing gates (BF-163, AD-614, AD-623).
- **Dependency Inversion:** Config injected via `WardRoomConfig` parameter, not hardcoded.
- **Fail Fast / Log-and-Degrade:** Throttled DMs are logged at INFO level with actionable detail (agent, target, reason, counts). DMs are deferred, not dropped — they'll be retried after the window expires.
- **DRY:** Sliding window + lazy pruning pattern is self-contained. Didn't extract a shared helper because no other code uses this pattern (BF-163 uses a simpler last-timestamp approach).
- **Law of Demeter:** Config access uses `getattr` with defaults for safety. No deep object chain traversal.
- **Defense in Depth:** Three layers of DM protection now exist: (1) BF-257 receive budget (this fix), (2) BF-163 send cooldown, (3) AD-614/AD-623 content-based gates. Each independently prevents a different failure mode.

---

## Verification

After building, run:

```bash
python -m pytest tests/test_bf257_dm_receive_rate_limiter.py -v
python -m pytest tests/test_bf163_dm_send_flood.py tests/test_bf164_stale_unread_dm.py tests/test_ad614_dm_conversation_termination.py tests/test_ad623_dm_convergence.py -v
python -m pytest tests/ -x --timeout=120
```

---

## Tracking

1. **PROGRESS.md:** Add under active bug fixes:
   ```
   - **BF-257** DM Receive Rate Limiter — COMPLETE
     - Per-agent DM response budget (6/10min) + per-pair exchange budget (8/10min)
     - Breaks ping-pong loops at receive layer; Captain DMs exempt
     - dm_exchange_limit lowered 40→15
   ```

2. **DECISIONS.md:** Add entry:
   ```
   ### BF-257: DM Receive Rate Limiter (2026-05-02)
   **Problem:** Science agents (Atlas/Sage/Lyra) entered DM ping-pong loop that exhausted LLM capacity.
   **Decision:** Two-layer sliding-window rate limiter at the proactive DM receive layer.
   Layer 1: Per-agent budget (6 DM responses per 10min window).
   Layer 2: Per-pair budget (8 exchanges per pair per 10min, bidirectional key).
   **Why receive-side:** Send-side cooldowns (BF-163) are unidirectional — A→B and B→A are independent.
   The receive gate catches the round-trip pattern.
   **Why not suppress in evaluate/reflect:** BF-184/187 social obligation bypass is correct —
   DMs should auto-approve when capacity exists. The rate limiter prevents capacity exhaustion.
   **Alternatives considered:** (1) Bidirectional BF-163 keys — would fix pair loops but not
   multi-agent fan-out. (2) AD-643b DM suppression — treats symptom (undeclared actions) not cause.
   (3) LLM-level circuit breaker — too coarse, would block all agents not just the looping ones.
   ```

3. **docs/development/roadmap.md:** Add BF-257 to bug tracker section.
