# AD-620: Clearance Model Foundation — Billet-Based Access Tier

## Context

ProbOS currently maps Recall Tier (BASIC / ENHANCED / FULL / ORACLE) 1:1 from agent Rank via `recall_tier_from_rank()` in `earned_agency.py`. AD-619 patched around this with a hardcoded `has_ship_wide_authority()` set in `crew_utils.py` to give the Counselor Oracle access regardless of rank.

AD-620 replaces that hack with a proper Navy-inspired clearance model: **Rank ≠ Clearance**. Clearance follows the **billet** (the post an agent fills), not the individual. The Counselor gets Oracle access because her *post* carries Oracle clearance, not because of a hardcoded set.

**Design reference:** `docs/research/clearance-system-design.md`

## Scope

AD-620 is the foundation layer. It:
1. Adds `clearance` field to the Post dataclass and organization.yaml
2. Adds `effective_recall_tier()` function that resolves max(rank-tier, billet-tier)
3. Replaces all `recall_tier_from_rank()` + AD-619 override call sites
4. Replaces the hardcoded SWA set in `crew_utils.py`
5. Simplifies the Oracle gate (clearance alone sufficient, no strategy gate)
6. Replaces SWA-based Ward Room subscription with clearance-based subscription

**Out of scope (AD-621/622):**
- AD-621: Communication/visibility scoping by clearance
- AD-622: Dynamic ClearanceGrant model (SAP-style temporary grants)

## Engineering Principles Compliance

- **SOLID/O**: Extend `Post` with optional field (backward compatible). New `effective_recall_tier()` is additive.
- **SOLID/S**: Clearance resolution is a single concern in `earned_agency.py`.
- **Law of Demeter**: Pass `ontology` service or resolved clearance string — never reach through `runtime.ontology._dept._posts[x].clearance`.
- **DRY**: One `effective_recall_tier()` function replaces two identical tier-resolution blocks (cognitive_agent.py + proactive.py) plus the SWA override.
- **Fail Fast**: If ontology unavailable, degrade to rank-only tier (existing behavior). Log warning, don't crash.
- **Defense in Depth**: Oracle gate still validates `_oracle_service` exists — clearance alone doesn't conjure the service.

## Changes

### 1. `src/probos/ontology/models.py` — Post dataclass (line 19-26)

Add `clearance` field to the `Post` dataclass:

```python
@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str] = field(default_factory=list)  # post_ids
    tier: str = "crew"  # "crew", "utility", "infrastructure", "external"
    clearance: str = ""  # AD-620: RecallTier name (BASIC/ENHANCED/FULL/ORACLE). Empty = no billet clearance.
```

No other model changes. The parser in `ontology/loader.py` already passes through YAML fields to the Post constructor — verify it handles the optional field. If the loader constructs `Post` via `Post(**data)` from the YAML dict, then adding `clearance: str = ""` with a default is backward-compatible. If it uses positional args, add `clearance=data.get("clearance", "")`.

### 2. `config/ontology/organization.yaml` — Add clearance to posts

Add `clearance` field to each post entry. Clearance assignments per the design doc:

```yaml
posts:
  # Bridge
  - id: captain
    title: "Captain"
    department: bridge
    reports_to: null
    authority_over: [first_officer, counselor]
    tier: external
    clearance: ORACLE

  - id: first_officer
    title: "First Officer"
    department: bridge
    reports_to: captain
    authority_over: [chief_engineer, chief_science, chief_medical, chief_security, chief_operations]
    tier: crew
    clearance: ORACLE

  - id: counselor
    title: "Ship's Counselor"
    department: bridge
    reports_to: captain
    authority_over: []
    tier: crew
    clearance: ORACLE

  # Department Chiefs — FULL clearance
  - id: chief_engineer
    clearance: FULL
  - id: chief_science
    clearance: FULL
  - id: chief_medical
    clearance: FULL
  - id: chief_security
    clearance: FULL
  - id: chief_operations
    clearance: FULL

  # Officers — ENHANCED clearance
  - id: engineering_officer
    clearance: ENHANCED
  - id: builder_officer
    clearance: ENHANCED
  - id: scout_officer
    clearance: ENHANCED
  - id: data_analyst_officer
    clearance: ENHANCED
  - id: systems_analyst_officer
    clearance: ENHANCED
  - id: research_specialist_officer
    clearance: ENHANCED
  - id: surgeon_officer
    clearance: ENHANCED
  - id: pharmacist_officer
    clearance: ENHANCED
  - id: pathologist_officer
    clearance: ENHANCED
```

**IMPORTANT:** Add `clearance` to each existing post entry — don't rewrite the file. Each post already has its full definition; just add the `clearance:` line after `tier:`. Posts without explicit clearance default to empty string (no billet clearance, rank-only).

### 3. `src/probos/ontology/loader.py` — Verify Post parsing

Check how `Post` is constructed from YAML data. The loader likely does something like:

```python
Post(id=p["id"], title=p["title"], ...)
```

If keyword construction, add `clearance=p.get("clearance", "")`. If it already unpacks as `Post(**p)`, no change needed (the default handles missing keys).

Search for how the loader handles the `department` → `department_id` rename (the YAML uses `department:` but Post uses `department_id:`). Follow the same pattern for `clearance`.

### 4. `src/probos/earned_agency.py` — Add `effective_recall_tier()`

After the existing `recall_tier_from_rank()` function (line 31), add:

```python
# Ordering map — RecallTier is a str enum ("basic", "enhanced", etc.)
# so we need explicit numeric ordering for comparison.
_TIER_ORDER: dict[RecallTier, int] = {
    RecallTier.BASIC: 0,
    RecallTier.ENHANCED: 1,
    RecallTier.FULL: 2,
    RecallTier.ORACLE: 3,
}


def effective_recall_tier(
    rank: Rank | None,
    billet_clearance: str = "",
) -> RecallTier:
    """AD-620: Resolve effective recall tier — max(rank-based, billet-based).

    Billet clearance comes from the Post.clearance field in organization.yaml.
    Takes the higher of rank-derived tier and billet clearance.
    """
    rank_tier = recall_tier_from_rank(rank) if rank else RecallTier.ENHANCED

    if not billet_clearance:
        return rank_tier

    # Parse billet clearance string to RecallTier
    try:
        billet_tier = RecallTier(billet_clearance.lower())
    except ValueError:
        return rank_tier

    # Return whichever is higher
    if _TIER_ORDER.get(billet_tier, 0) > _TIER_ORDER.get(rank_tier, 0):
        return billet_tier
    return rank_tier
```

**IMPORTANT:** RecallTier is a `str, Enum` with string values (`"basic"`, `"enhanced"`, `"full"`, `"oracle"`) — NOT numeric. Use `RecallTier(clearance_string.lower())` to construct from value, not `RecallTier[clearance_string]` (which uses the NAME). The `_TIER_ORDER` dict provides explicit numeric ordering for comparison. The YAML stores uppercase (`ORACLE`) but the enum values are lowercase (`"oracle"`) — normalize with `.lower()`.

### 5. `src/probos/earned_agency.py` — Add `resolve_billet_clearance()` helper

Add a helper that takes `agent_type` + ontology service and returns the clearance string:

```python
def resolve_billet_clearance(
    agent_type: str,
    ontology: Any | None,
) -> str:
    """AD-620: Look up billet clearance for an agent type from the ontology.

    Returns the Post.clearance string, or "" if ontology unavailable or
    agent has no post assignment.
    """
    if not ontology:
        return ""
    try:
        post = ontology.get_post_for_agent(agent_type)
        return post.clearance if post else ""
    except Exception:
        return ""
```

This helper isolates the ontology lookup so call sites don't need to import ontology service details. Law of Demeter: callers ask `resolve_billet_clearance()`, not `runtime.ontology.get_post_for_agent(x).clearance`.

### 6. `src/probos/cognitive/cognitive_agent.py` — Replace tier resolution (lines 2683-2696)

**Current code (lines 2683-2696):**
```python
            # AD-462c: Resolve recall tier from agent rank
            from probos.earned_agency import recall_tier_from_rank, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            _rank = getattr(self, 'rank', None)
            _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

            # AD-619: Ship-wide authority agents get Oracle tier regardless of rank
            from probos.crew_utils import has_ship_wide_authority as _has_swa
            if _has_swa(self):
                _recall_tier = RecallTier.ORACLE
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
                logger.debug("AD-619: %s recall tier override -> ORACLE", self.agent_type)
```

**Replace with:**
```python
            # AD-620: Resolve recall tier from rank + billet clearance
            from probos.earned_agency import effective_recall_tier, resolve_billet_clearance, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            _rank = getattr(self, 'rank', None)
            _billet_clearance = resolve_billet_clearance(
                getattr(self, 'agent_type', ''),
                getattr(self._runtime, 'ontology', None),
            )
            _recall_tier = effective_recall_tier(_rank, _billet_clearance)
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

This removes the SWA import and override block entirely. The `_has_swa` import is still used later at line 2846 for the Oracle gate — that also changes (see step 8).

### 7. `src/probos/proactive.py` — Replace tier resolution (lines 897-906)

**Current code (lines 897-906):**
```python
                # AD-462c: Resolve recall tier from agent rank
                from probos.earned_agency import recall_tier_from_rank, RecallTier
                from probos.cognitive.episodic import resolve_recall_tier_params
                _rank = getattr(agent, 'rank', None)
                _recall_tier = recall_tier_from_rank(_rank) if _rank else RecallTier.ENHANCED
                mem_cfg = None
                if hasattr(rt, 'config') and hasattr(rt.config, 'memory'):
                    mem_cfg = rt.config.memory
                _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

**Replace with:**
```python
                # AD-620: Resolve recall tier from rank + billet clearance
                from probos.earned_agency import effective_recall_tier, resolve_billet_clearance, RecallTier
                from probos.cognitive.episodic import resolve_recall_tier_params
                _rank = getattr(agent, 'rank', None)
                _billet_clearance = resolve_billet_clearance(
                    getattr(agent, 'agent_type', ''),
                    getattr(rt, 'ontology', None),
                )
                _recall_tier = effective_recall_tier(_rank, _billet_clearance)
                mem_cfg = None
                if hasattr(rt, 'config') and hasattr(rt.config, 'memory'):
                    mem_cfg = rt.config.memory
                _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
                _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)
```

### 8. `src/probos/cognitive/cognitive_agent.py` — Simplify Oracle gate (lines 2843-2865)

**Current code (lines 2843-2853):**
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

**Replace with:**
```python
                # AD-620: Oracle Service — clearance-based access
                # Agents with ORACLE tier (via rank or billet clearance) get Oracle on any strategy.
                if (
                    _recall_tier == RecallTier.ORACLE
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
```

The strategy gate (`_retrieval_strategy == RetrievalStrategy.DEEP`) is removed. If you have ORACLE clearance, you get Oracle access on any retrieval strategy. The `_has_swa` variable and its import are no longer needed.

### 9. `src/probos/startup/communication.py` — Replace SWA subscription (lines 163-166)

**Current code (lines 163-166):**
```python
            # AD-619: Ship-wide authority agents get all department channels
            if has_ship_wide_authority(agent):
                for dept_ch_id in dept_channel_map.values():
                    await ward_room.subscribe(agent.id, dept_ch_id)
```

**Replace with clearance-based subscription:**
```python
            # AD-620: Agents with FULL+ billet clearance get all department channels
            from probos.earned_agency import resolve_billet_clearance, RecallTier, _TIER_ORDER
            _billet_cl = resolve_billet_clearance(agent.agent_type, getattr(runtime, 'ontology', None))
            if _billet_cl:
                try:
                    _cl_tier = RecallTier(_billet_cl.lower())
                    if _TIER_ORDER.get(_cl_tier, 0) >= _TIER_ORDER.get(RecallTier.FULL, 0):
                        for dept_ch_id in dept_channel_map.values():
                            await ward_room.subscribe(agent.id, dept_ch_id)
                except ValueError:
                    pass  # Invalid clearance string — skip
```

**Note:** Move the import of `resolve_billet_clearance` and `RecallTier` to the top of the block (near line 136-137) alongside the existing imports, not inside the loop. The code above shows it inline for clarity.

Also remove the `has_ship_wide_authority` import from line 137:
```python
# Before:
from probos.crew_utils import is_crew_agent, has_ship_wide_authority
# After:
from probos.crew_utils import is_crew_agent
```

### 10. `src/probos/crew_utils.py` — Remove SWA (lines 20-29)

Remove the hardcoded `_SHIP_WIDE_AUTHORITY_TYPES` set and `has_ship_wide_authority()` function:

```python
# DELETE these lines:
_SHIP_WIDE_AUTHORITY_TYPES = {"counselor"}

def has_ship_wide_authority(agent: Any) -> bool:
    """AD-619: Check if agent type has ship-wide cross-department authority."""
    agent_type = getattr(agent, 'agent_type', '')
    return agent_type in _SHIP_WIDE_AUTHORITY_TYPES
```

Verify no other callers remain (grep for `has_ship_wide_authority` — should only be the three sites modified above). If any unexpected callers exist, migrate them to `resolve_billet_clearance()` + tier check.

## Tests

### File: `tests/test_ad620_clearance_model.py` (NEW)

Test the following:

1. **`effective_recall_tier()` — rank only**: No clearance → returns rank-based tier.
2. **`effective_recall_tier()` — billet upgrades**: Low rank + ORACLE clearance → ORACLE.
3. **`effective_recall_tier()` — rank higher**: Commander rank (FULL) + ENHANCED clearance → FULL.
4. **`effective_recall_tier()` — invalid clearance string**: Returns rank-based tier.
5. **`effective_recall_tier()` — empty clearance**: Returns rank-based tier.
6. **`resolve_billet_clearance()` — with ontology**: Mock ontology with Post(clearance="ORACLE") → returns "ORACLE".
7. **`resolve_billet_clearance()` — no ontology**: Returns "".
8. **`resolve_billet_clearance()` — agent not assigned**: ontology.get_post_for_agent returns None → returns "".
9. **Post dataclass**: Verify `clearance` field defaults to "".
10. **Organization YAML parsing**: Load organization.yaml, verify captain post has clearance="ORACLE", engineering_officer has clearance="ENHANCED".
11. **Integration: cognitive_agent tier resolution**: Mock agent with counselor type, verify gets ORACLE tier via billet clearance (not SWA hack).
12. **Integration: proactive tier resolution**: Same pattern for proactive.py call site.
13. **Oracle gate: clearance-only access**: ORACLE-tier agent with ANALYTICAL strategy (not DEEP) → Oracle gate opens. Verify strategy is NOT a blocker.
14. **Ward Room subscription: FULL clearance gets all channels**: Agent with FULL billet clearance → subscribed to all department channels.
15. **Ward Room subscription: ENHANCED does not get all channels**: Agent with ENHANCED clearance → NOT subscribed to all department channels.
16. **SWA removal verification**: Grep for `has_ship_wide_authority` in `src/probos/` — should return 0 results.

## Verification

```bash
# Unit + integration tests
uv run python -m pytest tests/test_ad620_clearance_model.py -v

# Verify no remaining SWA references (should be 0)
grep -rn "has_ship_wide_authority" src/probos/

# Verify organization.yaml loads cleanly
uv run python -c "from probos.ontology.service import VesselOntologyService; from pathlib import Path; v = VesselOntologyService(Path('config/ontology')); print(v.get_post('counselor').clearance)"

# Full test suite
uv run python -m pytest tests/ -x -q
```

## Tracking Updates

- PROGRESS.md: AD-620 → IN PROGRESS
- DECISIONS.md: Add AD-620 entry after build
- roadmap.md: Update status
- GitHub Project: Issue #206 → In Progress
