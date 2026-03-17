# AD-293: Crew Team Introspection

## Objective

Add a `team_info` intent to `IntrospectionAgent` so users can query crew teams (pool groups) by name. Currently, asking "tell me about the medical team" fails because `agent_info` searches by `agent_type` and no agent has type `"medical"`. Pool groups are a first-class runtime concept (AD-291) but invisible to the intent system.

This also adds a minor defense-in-depth fix to `agent_info`: when substring matching on `agent_type` finds nothing, fall back to searching pool names. This ensures partial queries still return useful results even if routed to the wrong intent.

## Architecture

```
User: "Tell me about the medical team"
    → Decomposer → team_info(team="medical")
        → IntrospectionAgent._team_info()
            → runtime.pool_groups.get_group("medical")
            → runtime.pool_groups.group_health("medical", runtime.pools)
            → Collect agent details for all agents in the group's pools
        → Structured response: team health, agent roster, pool statuses, purpose
```

## Files to Modify

### `src/probos/agents/introspect.py`

**1. Add `team_info` IntentDescriptor** (in the `intent_descriptors` list, after `agent_info`):

```python
IntentDescriptor(
    name="team_info",
    params={"team": "crew team name (e.g. medical, core, bundled, self_mod)"},
    description="Get info about a crew team (pool group) — health, agent roster, pool statuses",
    requires_reflect=True,
),
```

**2. Add `"team_info"` to `_handled_intents`** set.

**3. Update the `CapabilityDescriptor` detail** to mention `team_info`:

```python
detail="Introspect ProbOS internals: explain_last, agent_info, team_info, system_health, why",
```

**4. Add routing** in `act()`, after the `agent_info` branch:

```python
elif action == "team_info":
    return self._team_info(rt, params)
```

**5. Add `_team_info` method:**

```python
def _team_info(self, rt: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Return details about a crew team (pool group)."""
    team_name = params.get("team", "").strip().lower()

    if not team_name:
        # No specific team — list all teams
        groups = rt.pool_groups.all_groups()
        if not groups:
            return {
                "success": True,
                "data": {"message": "No crew teams registered."},
            }
        team_summaries = []
        for group in groups:
            health = rt.pool_groups.group_health(group.name, rt.pools)
            team_summaries.append({
                "name": group.name,
                "display_name": group.display_name,
                "total_agents": health.get("total_agents", 0),
                "healthy_agents": health.get("healthy_agents", 0),
                "health_ratio": health.get("health_ratio", 1.0),
                "pool_count": len(group.pool_names),
            })
        return {
            "success": True,
            "data": {"teams": team_summaries, "count": len(team_summaries)},
        }

    # Look up the specific team
    group = rt.pool_groups.get_group(team_name)

    # Fuzzy fallback: try substring match on group names
    if group is None:
        for g in rt.pool_groups.all_groups():
            if team_name in g.name or team_name in g.display_name.lower():
                group = g
                break

    if group is None:
        return {
            "success": True,
            "data": {
                "message": f"No crew team found matching '{team_name}'.",
                "available_teams": [g.name for g in rt.pool_groups.all_groups()],
            },
        }

    # Get aggregate health
    health = rt.pool_groups.group_health(group.name, rt.pools)

    # Get individual agent details for all pools in this group
    agent_details = []
    for pool_name in sorted(group.pool_names):
        pool = rt.pools.get(pool_name)
        if pool is None:
            continue
        for agent in pool.healthy_agents:
            info: dict[str, Any] = agent.info()
            trust = rt.trust_network.get_score(agent.id)
            info["trust_score"] = round(trust, 4)
            info["pool"] = pool_name
            agent_details.append(info)

    return {
        "success": True,
        "data": {
            "team": {
                "name": group.name,
                "display_name": group.display_name,
                "exclude_from_scaler": group.exclude_from_scaler,
            },
            "health": {
                "total_agents": health.get("total_agents", 0),
                "healthy_agents": health.get("healthy_agents", 0),
                "health_ratio": round(health.get("health_ratio", 1.0), 4),
            },
            "pools": health.get("pools", {}),
            "agents": agent_details,
        },
    }
```

**6. Enhance `_agent_info` fallback** — after the existing substring search on `agent_type` (line ~203), if still no agents found, add a pool name fallback:

```python
if not agents:
    # Pool name fallback — search for agents in pools matching the query
    needle = agent_type.lower()
    for pool_name, pool in rt.pools.items():
        if needle in pool_name.lower():
            agents.extend(pool.healthy_agents)
```

Insert this block after the existing substring fallback (after line 203) and before the `if not agents:` empty-result return (line 208).

## Testing

### Add to `tests/test_introspect.py` (or create `tests/test_team_introspection.py` if test file is too large)

**1. `test_team_info_specific_team`** — Boot runtime, call `team_info` with `team="medical"`. Verify response includes team name, display_name, health data, pool details, and agent list with trust scores.

**2. `test_team_info_all_teams`** — Call `team_info` with no team param. Verify response lists all registered teams with summary health data.

**3. `test_team_info_unknown_team`** — Call `team_info` with `team="nonexistent"`. Verify response includes helpful error message and lists available team names.

**4. `test_team_info_fuzzy_match`** — Call `team_info` with `team="med"`. Verify it finds the medical team via substring match.

**5. `test_agent_info_pool_name_fallback`** — Call `agent_info` with `agent_type="medical"`. Verify it now returns agents from medical pools via the pool name fallback (defense-in-depth).

**6. `test_team_info_core_team`** — Call `team_info` with `team="core"`. Verify it returns core system agents (filesystem, shell, http, etc.).

## Constraints

- `_team_info` is purely observational — never mutates runtime state (same as all introspection)
- Pool group data comes from `runtime.pool_groups` (PoolGroupRegistry, AD-291)
- Agent details include trust scores for consistency with `_agent_info` output
- Fuzzy matching uses simple substring, not Levenshtein — keeps it lightweight
- No new dependencies

## Success Criteria

- `"Tell me about the medical team"` returns structured data about all 5 medical agents with health and trust scores
- `"What crew teams are there?"` lists all registered pool groups with health summaries
- `"Tell me about the medical agents"` still works via `agent_info` pool name fallback
- All 6 new tests pass
- All existing tests still pass — no regressions
