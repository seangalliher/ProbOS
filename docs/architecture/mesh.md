# Mesh Layer

The Mesh handles agent coordination — how agents discover each other and communicate.

## Components

### Intent Bus

A pub/sub message bus with concurrent fan-out. When an intent is published, all subscribed agents receive it simultaneously. Agents self-select whether to handle it via their `perceive()` method.

### Hebbian Router

"Neurons that fire together wire together."

When an agent successfully handles an intent type, the connection weight between that intent and agent strengthens. When it fails, the weight weakens. Over time, the system learns optimal routing without any configuration.

Weights are persisted in SQLite and decay slowly over time to allow the system to adapt to changing conditions.

### Capability Registry

Agents declare their capabilities via structured `IntentDescriptor` metadata. The registry supports fuzzy matching — a request for "read a file" will match agents with `read_file` capability even without exact keyword overlap.

### Gossip Protocol

A SWIM-style protocol where agents exchange state information. Each gossip round, agents share:

- Their current health and confidence
- Known capabilities of other agents
- Trust scores

This ensures all agents have a consistent view of the mesh without centralized coordination.

### Signals

TTL-enforced signals propagate through the mesh. Signals decay as they travel, preventing infinite loops and ensuring locality of effect.

## Source Files

| File | Purpose |
|------|---------|
| `mesh/intent.py` | Pub/sub bus with fan-out |
| `mesh/routing.py` | Hebbian learning (SQLite) |
| `mesh/capability.py` | Fuzzy matching registry |
| `mesh/gossip.py` | SWIM-style state exchange |
| `mesh/signal.py` | TTL-enforced signals |
