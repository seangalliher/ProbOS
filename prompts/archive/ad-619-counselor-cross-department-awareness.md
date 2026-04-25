# AD-619: Counselor Cross-Department Awareness

**Status:** Ready for builder
**Scope:** OSS
**Complexity:** Small (3 source files modified, 1 new test file)
**Issue:** #205

## Problem

Bridge officers with ship-wide authority (Counselor, First Officer) are
subscribed only to their own department channel at startup. The Counselor is
`bridge` department → gets only Bridge. Zero visibility into Medical,
Engineering, Science, Security, or Operations channels. Can't monitor crew
she can't see.

Additionally, the Oracle Service (cross-shard episodic recall) is gated behind
`RecallTier.ORACLE` (requires `Rank.SENIOR`) AND `RetrievalStrategy.DEEP`
(requires diagnostic/operational intent). DM conversations classify as
`direct_message` → `SHALLOW` strategy. The Counselor asking "What has Chapel
been working on?" gets zero cross-agent context — both gates block her.

## Engineering Principles Applied

- **DRY / Open-Closed:** New `has_ship_wide_authority()` helper in `crew_utils.py`
  with a `_SHIP_WIDE_AUTHORITY_TYPES` set. Used in both `startup/communication.py`
  and `cognitive_agent.py`. Extensible — adding the First Officer later is a
  one-line set addition, not a conditional change in two files. No hardcoded
  `agent_type == "counselor"` checks in consuming code.
- **Defense in Depth:** Oracle failure already wrapped in try/except with
  log-and-degrade (line 2854). No new failure modes introduced.
- **Fail Fast:** Add `logger.debug` when the ship-wide authority override fires
  for recall tier. Establishes the first recall-tier logging in the codebase.
- **Law of Demeter:** Follow established `self._runtime._oracle_service` pattern
  (AD-568a precedent). Not introducing a new access pattern.
- **Interface Segregation:** `self.agent_type` is a class attribute on `BaseAgent`,
  always present. Use direct access, not `getattr` with fallback.

## Prior Work Absorbed

- **AD-568a** (Retrieval Strategy + Oracle gate) — the gating logic being modified.
- **AD-462c/e** (Recall tiers + Oracle Service) — RecallTier enum and
  `recall_tier_from_rank()` being supplemented with role-based override.
- **AD-425** (Ward Room auto-subscription) — the subscription loop being extended.
- **Standing orders** already updated (`config/standing_orders/counselor.md`)
  with Cross-Department Awareness section (channel monitoring, wellness rounds,
  crew-specific inquiry guidance, clinical note-taking).

## Solution

Three changes across 3 source files:

### Change 1: `has_ship_wide_authority()` helper

**File:** `src/probos/crew_utils.py`

Add a `_SHIP_WIDE_AUTHORITY_TYPES` set and a `has_ship_wide_authority()` function
after the existing `is_crew_agent()` function.

```python
# AD-619: Agent types with ship-wide cross-department authority.
# Bridge officers who report directly to the Captain and need visibility
# into all department channels + cross-shard Oracle recall.
# Ontology equivalent: posts with reports_to == "captain" and tier == "crew".
_SHIP_WIDE_AUTHORITY_TYPES = {"counselor"}


def has_ship_wide_authority(agent: Any) -> bool:
    """Check if an agent has ship-wide cross-department authority (AD-619)."""
    return getattr(agent, 'agent_type', '') in _SHIP_WIDE_AUTHORITY_TYPES
```

**Why a set, not ontology query:** The ontology is not initialized at the time
the Ward Room subscription loop runs in `startup/communication.py` (ontology
initializes ~100 lines later). A static set in `crew_utils.py` follows the
same pattern as `_WARD_ROOM_CREW` — legacy fallback set that works without
ontology. Add the First Officer (`"architect"`) to the set when extending
cross-department visibility to that role.

### Change 2: Subscribe ship-wide authority agents to all department channels

**File:** `src/probos/startup/communication.py`

In the agent subscription loop (lines 157–171), after subscribing the agent
to their own department channel, add a block that subscribes ship-wide
authority agents to ALL department channels.

**Location:** After line 162, inside the `for agent in registry.all()` loop.

**Import:** Add `has_ship_wide_authority` to the existing import from
`probos.crew_utils` at line 137:
```python
from probos.crew_utils import is_crew_agent, has_ship_wide_authority
```

**Logic:**
```python
            # AD-619: Ship-wide authority agents get all department channels
            if has_ship_wide_authority(agent):
                for dept_ch_id in dept_channel_map.values():
                    await ward_room.subscribe(agent.id, dept_ch_id)
```

`subscribe()` is idempotent — uses `ON CONFLICT(agent_id, channel_id) DO UPDATE`
(see `src/probos/ward_room/messages.py:552-563`). Re-subscribing to Bridge is
harmless. No need to skip the own-department subscription at line 162.

### Change 3: Ship-wide authority agents get Oracle recall tier + relaxed strategy gate

**File:** `src/probos/cognitive/cognitive_agent.py`

**3a. Recall tier override** — After line 2687 where `_recall_tier` is assigned
from rank:

```python
            _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

Add immediately after (before `_tier_params` is used):

```python
            # AD-619: Ship-wide authority agents get Oracle tier regardless of rank
            from probos.crew_utils import has_ship_wide_authority as _has_swa
            if _has_swa(self):
                _recall_tier = RecallTier.ORACLE
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
                logger.debug("AD-619: %s recall tier override -> ORACLE", self.agent_type)
```

Note: `_tier_params` must be re-resolved after the override so budget/config
matches the ORACLE tier. The import is inline (matches existing inline import
pattern at lines 2684-2685).

**3b. Relax Oracle strategy gate** — At lines 2836-2842, modify the Oracle
condition to allow ship-wide authority agents on any strategy (not just DEEP):

Current:
```python
                # AD-568a: Oracle Service for ORACLE-tier agents with DEEP strategy
                if (
                    _recall_tier == RecallTier.ORACLE
                    and _retrieval_strategy == RetrievalStrategy.DEEP
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
```

Change to:
```python
                # AD-568a / AD-619: Oracle Service for ORACLE-tier agents
                # DEEP strategy required for rank-based ORACLE agents.
                # Ship-wide authority agents (AD-619) get Oracle on any strategy.
                _swa = _has_swa(self)  # reuse import from 3a above
                if (
                    _recall_tier == RecallTier.ORACLE
                    and (_retrieval_strategy == RetrievalStrategy.DEEP or _swa)
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
```

The `_has_swa` reference reuses the `from probos.crew_utils import
has_ship_wide_authority as _has_swa` import added in step 3a. Both are in
the same method (`perceive()`), so the import is in scope.

**Effect:**
- Ship-wide authority agents always get `RecallTier.ORACLE` regardless of rank
- Ship-wide authority agents can trigger Oracle on SHALLOW intent (DM conversations)
- All other agents still require `Rank.SENIOR` + `RetrievalStrategy.DEEP`

## Files

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/crew_utils.py` | MODIFY — add `_SHIP_WIDE_AUTHORITY_TYPES` set + `has_ship_wide_authority()` |
| 2 | `src/probos/startup/communication.py` | MODIFY — subscribe ship-wide authority agents to all dept channels |
| 3 | `src/probos/cognitive/cognitive_agent.py` | MODIFY — recall tier override + relax Oracle strategy gate |
| 4 | `tests/test_ad619_counselor_awareness.py` | NEW — tests for all three changes |

## Tests

Create `tests/test_ad619_counselor_awareness.py`:

### `TestShipWideAuthority`

**`test_has_ship_wide_authority_counselor`**
- Agent with `agent_type="counselor"` → `has_ship_wide_authority()` returns True.

**`test_has_ship_wide_authority_non_counselor`**
- Agent with `agent_type="data_analyst"` → returns False.

**`test_has_ship_wide_authority_no_agent_type`**
- Object without `agent_type` attribute → returns False (defensive).

### `TestChannelSubscriptions`

**`test_ship_wide_agent_subscribed_to_all_department_channels`**
- Mock `ward_room.subscribe()`, `ward_room.list_channels()` (return channels
  for Bridge, Medical, Engineering, Science, Security, Operations + All Hands),
  `registry.all()` (return a counselor agent + a science agent).
- Run the subscription loop logic (extract relevant lines as a testable
  coroutine, or mock enough context to call the startup function).
- Assert counselor's `subscribe()` calls include ALL 6 department channel IDs.
- Assert science agent is subscribed to only Science department (+ ship-wide channels).

### `TestRecallTierOverride`

**`test_ship_wide_agent_gets_oracle_tier_at_any_rank`**
- For each rank (Ensign, Lieutenant, Commander, Senior): create a mock
  CognitiveAgent with `agent_type="counselor"` and that rank.
- Simulate the recall tier resolution logic.
- Assert `_recall_tier == RecallTier.ORACLE` for all ranks.

**`test_non_ship_wide_agent_uses_rank_based_tier`**
- Agent with `agent_type="data_analyst"`, `rank=Rank.ENSIGN`.
- Assert `_recall_tier == RecallTier.BASIC` (not overridden).

**`test_recall_tier_override_re_resolves_tier_params`**
- Agent with `agent_type="counselor"`, `rank=Rank.ENSIGN`.
- Verify that `_tier_params` corresponds to ORACLE tier config, not BASIC.

### `TestOracleStrategyGate`

**`test_ship_wide_agent_oracle_on_shallow_strategy`**
- Mock CognitiveAgent with `agent_type="counselor"`,
  `_recall_tier=RecallTier.ORACLE`, `_retrieval_strategy=RetrievalStrategy.SHALLOW`.
- Mock `_runtime._oracle_service.query_formatted()` to return "test oracle text".
- Assert the Oracle gate condition passes and `_oracle_context` is set.

**`test_non_ship_wide_agent_no_oracle_on_shallow`**
- Mock CognitiveAgent with `agent_type="systems_analyst"`,
  `_recall_tier=RecallTier.ORACLE`, `_retrieval_strategy=RetrievalStrategy.SHALLOW`.
- Assert the Oracle gate condition does NOT pass (`_oracle_context` not set).

**`test_ship_wide_agent_oracle_on_deep_strategy`**
- Ship-wide agent with DEEP strategy → Oracle still works (not regression).

**`test_override_logged`**
- Verify `logger.debug` is called with "AD-619" prefix when override fires.

## Key References

- `src/probos/crew_utils.py` — `is_crew_agent()` pattern + `_WARD_ROOM_CREW` set (lines 10-27)
- `src/probos/startup/communication.py:135-171` — subscription loop (AD-425)
- `src/probos/cognitive/cognitive_agent.py:2683-2689` — recall tier resolution (AD-462c)
- `src/probos/cognitive/cognitive_agent.py:2836-2855` — Oracle gate (AD-568a)
- `src/probos/cognitive/source_governance.py:27-57` — RetrievalStrategy + intent map
- `src/probos/earned_agency.py:16-31` — RecallTier enum + `recall_tier_from_rank()`
- `src/probos/ward_room/messages.py:552-563` — `subscribe()` is idempotent (ON CONFLICT DO UPDATE)
- `src/probos/cognitive/oracle_service.py:125-169` — `query_formatted()` signature
- `config/ontology/organization.yaml:30-41` — Bridge posts (First Officer, Counselor)
- `config/standing_orders/counselor.md` — already updated with Cross-Department Awareness section

## Design Notes

**Why `_SHIP_WIDE_AUTHORITY_TYPES` set and not ontology query:**
The ontology initializes AFTER the Ward Room subscription loop in
`startup/communication.py` (ontology at line 251, subscriptions at line 135).
A static set in `crew_utils.py` follows the `_WARD_ROOM_CREW` precedent — works
without ontology. When extending to the First Officer, add `"architect"` to the set.

**Why not `agent_type == "counselor"` directly:**
DRY + Open/Closed. The check appears in two files. Centralizing in `crew_utils.py`
means extending to another agent type is a set addition, not a conditional edit
in each consuming file.

**Future extensibility:**
The First Officer (Architect) has `authority_over` spanning all 5 department chiefs
in the ontology. When the First Officer needs cross-department visibility,
add `"architect"` to `_SHIP_WIDE_AUTHORITY_TYPES`. No other changes needed.
