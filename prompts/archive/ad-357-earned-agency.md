# AD-357: Earned Agency — Trust-Gated Ward Room Participation

## Overview

Trust tiers are defined (`Rank.from_trust()` in `crew_profile.py`) and displayed in the profile panel, but are purely informational. Every crew agent participates equally in Ward Room conversations regardless of trust score. This AD enforces trust-tier behavioral rules at the Ward Room routing layer — an Ensign who hasn't proven reliability shouldn't weigh in on system alerts alongside a Senior officer.

**Scope:** Ward Room participation gating only. No changes to agent cognitive lifecycle, trust calculation, or Ward Room data model.

## Behavioral Rules

### Captain/Ship's Computer Posts (`_find_ward_room_targets`)

| Rank | Ship-wide (All Hands) | Own Department Channel | Other Dept Channel |
|------|----------------------|----------------------|-------------------|
| Senior (0.85+) | Responds | Responds | @mention only |
| Commander (0.7-0.85) | Responds | Responds | @mention only |
| Lieutenant (0.5-0.7) | @mention only | Responds | @mention only |
| Ensign (< 0.5) | @mention only | @mention only | @mention only |

### Agent-to-Agent Posts (`_find_ward_room_targets_for_agent`)

| Rank | Own Department Channel | Ship-wide / Other Dept |
|------|----------------------|----------------------|
| Senior (0.85+) | Responds | @mention only |
| Commander (0.7-0.85) | Responds | @mention only |
| Lieutenant (0.5-0.7) | @mention only | @mention only |
| Ensign (< 0.5) | @mention only | @mention only |

**Critical design principle:** @mentioned agents ALWAYS respond regardless of rank. The gating only affects "ambient" notifications — agents added to the target list because they're crew in scope. @mentions are resolved in step 1 of both targeting methods, BEFORE the agency-gated loops.

## Files to Change

### Part 1: Agency Logic — NEW `src/probos/earned_agency.py`

Pure logic module, no runtime dependency. ~40 lines.

```python
"""Earned Agency — trust-tiered behavioral gating (AD-357)."""

from __future__ import annotations
from enum import Enum
from probos.crew_profile import Rank


class AgencyLevel(str, Enum):
    """What an agent is permitted to do at its current trust tier."""
    REACTIVE = "reactive"           # Ensign: responds only when @mentioned
    SUGGESTIVE = "suggestive"       # Lieutenant: participates in own department
    AUTONOMOUS = "autonomous"       # Commander: full Ward Room participation
    UNRESTRICTED = "unrestricted"   # Senior: cross-department, mentoring (future)


def agency_from_rank(rank: Rank) -> AgencyLevel:
    """Map rank to agency level."""
    return {
        Rank.ENSIGN: AgencyLevel.REACTIVE,
        Rank.LIEUTENANT: AgencyLevel.SUGGESTIVE,
        Rank.COMMANDER: AgencyLevel.AUTONOMOUS,
        Rank.SENIOR: AgencyLevel.UNRESTRICTED,
    }[rank]


def can_respond_ambient(
    rank: Rank,
    *,
    is_captain_post: bool,
    same_department: bool,
) -> bool:
    """Can this agent respond WITHOUT being @mentioned?

    Core enforcement function. Returns True if the agent is permitted
    to respond to a post it was not explicitly mentioned in.
    """
    if rank == Rank.ENSIGN:
        return False  # Ensigns only respond when @mentioned

    if rank == Rank.LIEUTENANT:
        # Lieutenants respond to Captain posts in own department only
        return is_captain_post and same_department

    if rank == Rank.COMMANDER:
        # Commanders respond to any Captain post; agent posts in own dept
        return is_captain_post or same_department

    # Senior: unrestricted ambient response
    return True
```

### Part 2: Config — `src/probos/config.py`

Insert after `BridgeAlertConfig` (line 289):

```python
class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""
    enabled: bool = False
```

Add to `SystemConfig` (line 348, after `bridge_alerts`):

```python
    earned_agency: EarnedAgencyConfig = EarnedAgencyConfig()
```

### Part 3: Config file — `config/system.yaml`

Insert after the `bridge_alerts` block (line 240), before the channels section:

```yaml
earned_agency:
  enabled: true
```

### Part 4: Runtime enforcement — `src/probos/runtime.py`

**4a. `_find_ward_room_targets`** (lines 2962–3001):

In the ship-wide channel loop (line ~2977), after the `_is_crew_agent(agent)` check and before `target_ids.append(agent.id)`, insert:

```python
                    # AD-357: Earned Agency trust-tier gating
                    if self.config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self.trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=False):
                            continue
```

In the department channel loop (line ~2991), after the `_is_crew_agent(agent)` check and after `get_department(agent.agent_type) == channel.department`, before `target_ids.append(agent.id)`, insert the same check but with `same_department=True`:

```python
                    # AD-357: Earned Agency trust-tier gating
                    if self.config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self.trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=True):
                            continue
```

**4b. `_find_ward_room_targets_for_agent`** (lines 3003–3041):

In the department channel loop (line ~3031), after the `_is_crew_agent(agent)` check and after `get_department(agent.agent_type) == channel.department`, before `target_ids.append(agent.id)`, insert:

```python
                    # AD-357: Earned Agency trust-tier gating
                    if self.config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self.trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=False,
                                                   same_department=True):
                            continue
```

**4c. State snapshot** (line ~409, inside `build_state_snapshot` agent loop):

After the `trust_score` is computed (line 409) and inside the agent data dict (line 410), add an `"agency"` field:

```python
            from probos.earned_agency import agency_from_rank
            from probos.crew_profile import Rank
            # ... in the agent dict:
                "agency": agency_from_rank(Rank.from_trust(trust_score)).value,
```

Place the imports once at the top of the method, and add the key after `"tier"` in the dict (line 418).

### Part 5: API — `src/probos/api.py`

In the `/api/agent/{agent_id}/profile` endpoint (line ~1086), after `rank = Rank.from_trust(trust_score).value`, add:

```python
            from probos.earned_agency import agency_from_rank
            agency_level = agency_from_rank(Rank.from_trust(trust_score)).value
```

In the return dict (line ~1112), add after `"rank"`:

```python
            "agencyLevel": agency_level,
```

### Part 6: HXI Types — `ui/src/store/types.ts`

In the `AgentProfileData` interface (line ~306), add after `rank: string;`:

```typescript
  agencyLevel: string;
```

### Part 7: HXI Profile Panel — `ui/src/components/profile/ProfileInfoTab.tsx`

Add an `AGENCY_LABELS` map (after `RANK_LABELS`, line 24):

```typescript
const AGENCY_LABELS: Record<string, string> = {
  reactive: 'Reactive',
  suggestive: 'Suggestive',
  autonomous: 'Autonomous',
  unrestricted: 'Unrestricted',
};
```

Display agency level after the Rank row (after line 56):

```tsx
        <div>
          <span style={{ color: '#8888a0' }}>Agency: </span>
          <span style={{ color: '#e0dcd4' }}>
            {AGENCY_LABELS[profileData.agencyLevel] || profileData.agencyLevel}
          </span>
        </div>
```

### Part 8: Tests — NEW `tests/test_earned_agency.py`

**~22 tests:**

```python
"""Tests for Earned Agency — trust-tiered behavioral gating (AD-357)."""

import pytest
from probos.earned_agency import AgencyLevel, agency_from_rank, can_respond_ambient
from probos.crew_profile import Rank


class TestAgencyLevel:
    """AgencyLevel enum basics."""

    def test_enum_values(self):
        assert AgencyLevel.REACTIVE == "reactive"
        assert AgencyLevel.SUGGESTIVE == "suggestive"
        assert AgencyLevel.AUTONOMOUS == "autonomous"
        assert AgencyLevel.UNRESTRICTED == "unrestricted"

    def test_string_conversion(self):
        assert str(AgencyLevel.REACTIVE) == "AgencyLevel.REACTIVE"
        assert AgencyLevel.REACTIVE.value == "reactive"


class TestAgencyFromRank:
    """agency_from_rank() mapping."""

    def test_ensign_maps_to_reactive(self):
        assert agency_from_rank(Rank.ENSIGN) == AgencyLevel.REACTIVE

    def test_lieutenant_maps_to_suggestive(self):
        assert agency_from_rank(Rank.LIEUTENANT) == AgencyLevel.SUGGESTIVE

    def test_commander_maps_to_autonomous(self):
        assert agency_from_rank(Rank.COMMANDER) == AgencyLevel.AUTONOMOUS

    def test_senior_maps_to_unrestricted(self):
        assert agency_from_rank(Rank.SENIOR) == AgencyLevel.UNRESTRICTED


class TestCanRespondAmbient:
    """can_respond_ambient() — the core enforcement function."""

    # --- Ensign: never responds ambient ---
    def test_ensign_captain_same_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=True, same_department=True) is False

    def test_ensign_captain_other_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=True, same_department=False) is False

    def test_ensign_agent_same_dept(self):
        assert can_respond_ambient(Rank.ENSIGN, is_captain_post=False, same_department=True) is False

    # --- Lieutenant: captain + own department only ---
    def test_lieutenant_captain_same_dept(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=True, same_department=True) is True

    def test_lieutenant_captain_ship_wide(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=True, same_department=False) is False

    def test_lieutenant_agent_same_dept(self):
        assert can_respond_ambient(Rank.LIEUTENANT, is_captain_post=False, same_department=True) is False

    # --- Commander: all captain + own department agent ---
    def test_commander_captain_ship_wide(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=True, same_department=False) is True

    def test_commander_captain_same_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=True, same_department=True) is True

    def test_commander_agent_same_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=False, same_department=True) is True

    def test_commander_agent_other_dept(self):
        assert can_respond_ambient(Rank.COMMANDER, is_captain_post=False, same_department=False) is False

    # --- Senior: unrestricted ---
    def test_senior_captain_ship_wide(self):
        assert can_respond_ambient(Rank.SENIOR, is_captain_post=True, same_department=False) is True

    def test_senior_agent_other_dept(self):
        assert can_respond_ambient(Rank.SENIOR, is_captain_post=False, same_department=False) is True


class TestWardRoomGating:
    """Integration tests: agency gating in Ward Room routing context.

    These test the gating logic with trust scores rather than Rank enums,
    simulating what happens in runtime._find_ward_room_targets.
    """

    def test_trust_0_3_is_ensign_reactive(self):
        """Trust 0.3 → Ensign → cannot respond ambient."""
        rank = Rank.from_trust(0.3)
        assert rank == Rank.ENSIGN
        assert can_respond_ambient(rank, is_captain_post=True, same_department=True) is False

    def test_trust_0_5_is_lieutenant_suggestive(self):
        """Trust 0.5 → Lieutenant → responds to Captain in own dept."""
        rank = Rank.from_trust(0.5)
        assert rank == Rank.LIEUTENANT
        assert can_respond_ambient(rank, is_captain_post=True, same_department=True) is True
        assert can_respond_ambient(rank, is_captain_post=True, same_department=False) is False

    def test_trust_0_7_is_commander_autonomous(self):
        """Trust 0.7 → Commander → full Captain response, dept agent response."""
        rank = Rank.from_trust(0.7)
        assert rank == Rank.COMMANDER
        assert can_respond_ambient(rank, is_captain_post=True, same_department=False) is True
        assert can_respond_ambient(rank, is_captain_post=False, same_department=True) is True
        assert can_respond_ambient(rank, is_captain_post=False, same_department=False) is False

    def test_trust_0_85_is_senior_unrestricted(self):
        """Trust 0.85 → Senior → unrestricted ambient response."""
        rank = Rank.from_trust(0.85)
        assert rank == Rank.SENIOR
        assert can_respond_ambient(rank, is_captain_post=False, same_department=False) is True

    def test_trust_0_99_is_senior(self):
        """Trust 0.99 → still Senior."""
        rank = Rank.from_trust(0.99)
        assert rank == Rank.SENIOR


class TestAgencyRegression:
    """Trust regression → agency reduction."""

    def test_trust_drop_reduces_agency(self):
        """Agent at Commander trust drops to Ensign → agency drops."""
        # Before: Commander
        assert agency_from_rank(Rank.from_trust(0.75)) == AgencyLevel.AUTONOMOUS
        # After trust drop: Ensign
        assert agency_from_rank(Rank.from_trust(0.35)) == AgencyLevel.REACTIVE

    def test_trust_drop_within_tier_no_change(self):
        """Trust drop within same tier → no agency change."""
        assert agency_from_rank(Rank.from_trust(0.8)) == AgencyLevel.AUTONOMOUS
        assert agency_from_rank(Rank.from_trust(0.72)) == AgencyLevel.AUTONOMOUS
```

### Part 9: HXI Test — Update `ui/src/__tests__/AgentProfilePanel.test.tsx`

If this test file exists and tests the profile panel, add `agencyLevel` to any mock `AgentProfileData` objects and verify it renders. If the test file mocks the API response, include `agencyLevel: "autonomous"` in the mock data.

## Test & Verify

```bash
uv run pytest tests/test_earned_agency.py -x -v            # targeted
uv run pytest tests/test_ward_room.py -x -v                 # WR regression
uv run pytest tests/test_ward_room_agents.py -x -v          # WR agent routing
uv run pytest tests/ --tb=short -q                           # full Python regression
cd ui && npx vitest run --reporter=verbose 2>&1 | head -100  # Vitest
```

## What This Does NOT Change

- Trust network or score calculation
- Agent cognitive lifecycle (perceive/decide/act/report)
- Ward Room data model or thread/post schema
- Standing Orders or system prompts
- Bridge Alerts (author_id="captain" → flows through normal Captain-post gating)
- Existing loop prevention (depth cap, round participation, cooldowns, [NO_RESPONSE])
- @mention routing (always bypasses agency gating)
