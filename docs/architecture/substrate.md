# Substrate Layer

The Substrate is the foundation — it manages agent lifecycle from creation to recycling.

## Agent Lifecycle

Every agent follows a four-phase cycle:

```
perceive → decide → act → report
```

- **Perceive**: Agent examines an incoming intent and decides if it's relevant
- **Decide**: Agent determines how to handle the intent
- **Act**: Agent executes the operation
- **Report**: Agent returns results with a confidence score

## Components

### Spawner

Creates agents from templates. Each agent type is registered with a template that specifies its class, default configuration, and pool assignment.

### Resource Pools

Pools maintain a target number of agents for each capability. Key behaviors:

- **Auto-recycling**: Agents with confidence below 0.2 are replaced
- **Health checks**: Periodic liveness verification
- **Demand scaling**: Pools grow under load, shrink when idle

### Pool Groups

Pools are organized into 7 department-level PoolGroups (Medical, Engineering, Science, Security, Operations, Communications, Bridge). Each group maintains health metrics and provides department-wide views via the `PoolGroupRegistry`.

### Registry

An async-safe index of all running agents. Supports lookup by ID, pool, capability, and state.

### Heartbeat

A periodic pulse loop that checks agent liveness. Agents that miss heartbeats are marked degraded and eventually recycled.

### Event Log

Append-only SQLite log of all agent lifecycle events — spawns, completions, failures, recycling. Used for introspection and debugging.

### Identity

Persistent agent identity that survives restarts. Agents maintain a stable ID tied to their role and lineage.

## Source Files

| File | Purpose |
|------|---------|
| `substrate/agent.py` | `BaseAgent` ABC (perceive/decide/act/report) |
| `substrate/registry.py` | Async-safe agent index |
| `substrate/spawner.py` | Template-based factory |
| `substrate/pool.py` | Resource pools + health checks |
| `substrate/pool_group.py` | PoolGroup + PoolGroupRegistry (7 departments) |
| `substrate/scaler.py` | Demand-based pool scaling |
| `substrate/heartbeat.py` | Periodic pulse loop |
| `substrate/event_log.py` | Append-only SQLite audit log |
| `substrate/identity.py` | Persistent agent identity |
| `substrate/skill_agent.py` | SkillBasedAgent (dynamic skill dispatch) |
