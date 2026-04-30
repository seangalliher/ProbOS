# AD-490: Agent Wiring Security Logs

**Status:** Ready for builder
**Dependencies:** None (but if AD-489 builds first, update the events.py SEARCH block to include `CONDUCT_VIOLATION`)
**Estimated tests:** ~7

---

## Problem

The `agent_wired` event log entry is emitted **before** identity resolution
completes, so it captures no DID, callsign, or department. This makes the
event log useless for security auditing — you can see that agents were wired
but not who they became.

Two emission sites:

| Site | File | Line | Problem |
|---|---|---|---|
| Standard onboarding | `agent_onboarding.py` | 191-197 | Emitted before identity resolution (lines 281-341) |
| Red team spawn | `runtime.py` | 1134-1140 | Emitted without any identity enrichment |

Both emit `category="lifecycle", event="agent_wired"` with only `agent_id`,
`agent_type`, and `pool` — no DID, callsign, or department in the `data` column.

## Fix

### Section 1: Move `agent_wired` log emission after identity resolution

**File:** `src/probos/agent_onboarding.py`

The current emission is at lines 191-197, before identity resolution (lines 281-341).
Move it to **after** identity resolution and enrich with DID/callsign/department.

**Step 1:** Remove the premature emission.

SEARCH:
```python
        await self._event_log.log(
            category="lifecycle",
            event="agent_wired",
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
        )
```

REPLACE:
```python
        # AD-490: agent_wired emission moved after identity resolution (see below)
```

**Step 2:** Add enriched emission after identity resolution completes.

Find the identity resolution block end. The block ends after the billet
assignment notification (line ~349). Look for the pattern after
`# AD-595b: Notify BilletRegistry of billet assignment` (line 343).

After the billet assignment block (after its try/except), add:

```python
        # AD-490: Enriched agent_wired log — emitted AFTER identity resolution
        _wired_data: dict[str, Any] = {}
        if hasattr(agent, 'did') and agent.did:
            _wired_data["did"] = agent.did
        if hasattr(agent, 'sovereign_id') and agent.sovereign_id:
            _wired_data["sovereign_id"] = agent.sovereign_id
        if hasattr(agent, 'callsign') and agent.callsign:
            _wired_data["callsign"] = agent.callsign
        # Department resolution — follow pattern from identity resolution (lines 298-304)
        _dept = ""
        if self._ontology:
            _dept = self._ontology.get_agent_department(agent.agent_type) or ""
        if not _dept:
            from probos.cognitive.standing_orders import get_department as _get_dept
            _dept = _get_dept(agent.agent_type) or "unassigned"
        if _dept:
            _wired_data["department"] = _dept

        await self._event_log.log(
            category="lifecycle",
            event="agent_wired",
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
            data=_wired_data if _wired_data else None,
        )
```

Verify the `data` parameter is supported by `event_log.log()` — it was added
by AD-664 (event_log.py:94-106, `data: dict[str, Any] | None = None`).

Also verify the import for `Any` is available. Check the top of the file:
```
grep -n "from typing import" src/probos/agent_onboarding.py
```

### Section 2: Enrich red team `agent_wired` emission

**File:** `src/probos/runtime.py`

Red team agents are spawned via `_spawn_red_team_agents()` (around line 1134).
They use asset tags (not birth certificates) and have no callsign/DID. Enrich
with what IS available: `pool="red_team"` and `department="security"`.

SEARCH:
```python
            await self.event_log.log(
                category="lifecycle",
                event="agent_wired",
                agent_id=agent.id,
                agent_type=agent.agent_type,
                pool="red_team",
            )
```

REPLACE:
```python
            await self.event_log.log(
                category="lifecycle",
                event="agent_wired",
                agent_id=agent.id,
                agent_type=agent.agent_type,
                pool="red_team",
                data={"department": "security"},  # AD-490: enriched wiring log
            )
```

### Section 3: Add `AGENT_WIRED` event type constant

**File:** `src/probos/events.py`

The `agent_wired` event is currently logged as a raw string. Add a formal
`EventType` constant for consistency. Insert after `AGENT_STATE` (line 76):

SEARCH:
```python
    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"
```

REPLACE:
```python
    # Agent lifecycle
    AGENT_STATE = "agent_state"
    AGENT_WIRED = "agent_wired"  # AD-490
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"
```

**Note:** Do NOT change the emission sites to use `EventType.AGENT_WIRED` yet.
The `event_log.log()` takes a raw string `event` parameter, not `EventType`.
The constant exists for downstream consumers (dashboards, queries) that want
to reference the event by constant rather than magic string.

## Tests

**File:** `tests/test_ad490_agent_wiring_security_logs.py`

7 tests:

1. `test_agent_wired_event_type_exists` — verify `EventType.AGENT_WIRED` exists
   and its value is `"agent_wired"`
2. `test_agent_wired_contains_did` — wire a crew agent through onboarding with
   a mock identity registry that returns a cert with DID. Capture the `event_log.log()`
   call args. Verify `data["did"]` is present and matches the cert DID.
3. `test_agent_wired_contains_callsign` — same setup, verify `data["callsign"]`
   is present
4. `test_agent_wired_contains_department` — same setup, verify `data["department"]`
   is present and non-empty
5. `test_agent_wired_without_identity` — wire a non-crew agent (asset tag path).
   Verify `agent_wired` is still emitted but `data` has no `did` key (asset agents
   don't get DIDs)
6. `test_agent_wired_emitted_after_identity_resolution` — verify the `event_log.log()`
   call for `agent_wired` happens AFTER `identity_registry.resolve_or_issue()`.
   Use mock call ordering (e.g., `call_args_list` index comparison on the mocks)
7. `test_red_team_agent_wired_has_department` — exercise the red team spawn path.
   Verify `data["department"]` is `"security"`.

## What This Does NOT Change

- No changes to `AGENT_STATE` events — those remain at their current position
- No changes to identity resolution logic itself (lines 281-341)
- No changes to the naming ceremony flow
- Does NOT add real-time event emission via NATS for `agent_wired` — this is
  event_log only (structured SQLite audit trail)
- Does NOT add new columns to event_log — uses existing `data` JSON column (AD-664)
- Does NOT change how non-crew/infrastructure agents are wired

## Tracking

- `PROGRESS.md`: Add AD-490 as COMPLETE
- `docs/development/roadmap.md`: Update AD-490 status

## Acceptance Criteria

- `agent_wired` log entries contain DID, callsign, department for crew agents
- `agent_wired` emission occurs AFTER identity resolution, not before
- Red team agents include `department: "security"` in wired log
- `EventType.AGENT_WIRED` exists in events.py
- All 7 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Current premature emission location
grep -n "agent_wired" src/probos/agent_onboarding.py
  194: event="agent_wired"   ← BEFORE identity resolution

# Identity resolution block
grep -n "resolve_or_issue" src/probos/agent_onboarding.py
  309: cert = await self._identity_registry.resolve_or_issue(...)  ← AFTER line 194

# Red team emission
grep -n "agent_wired" src/probos/runtime.py
  1136: event="agent_wired"

# event_log.log() signature
grep -n "def log" src/probos/substrate/event_log.py
  94: async def log(category, event, agent_id, agent_type, pool, detail,
                    *, correlation_id, parent_event_id, data)

# data param exists (AD-664)
grep -n "data:" src/probos/substrate/event_log.py
  105: data: dict[str, Any] | None = None

# Department resolution pattern
grep -n "get_agent_department" src/probos/agent_onboarding.py
  299: dept = self._ontology.get_agent_department(agent.agent_type) or ""

# No AGENT_WIRED in events.py yet
grep -n "AGENT_WIRED" src/probos/events.py → no matches

# AGENT_STATE location
grep -n "AGENT_STATE" src/probos/events.py
  76: AGENT_STATE = "agent_state"
```
