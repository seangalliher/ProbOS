# Federation Layer

The Federation layer enables multi-node operation — multiple ProbOS instances forming a cognitive mesh of meshes.

## Concept: The Nooplex

Multiple ProbOS nodes form a **Nooplex** — a federated cognitive mesh. Each node is sovereign:

- Its own agents, trust scores, and memory
- Its own decision-making authority
- No central controller

Nodes discover each other and exchange capabilities via ZeroMQ gossip protocol.

## Intent Forwarding

When a node receives an intent it can't handle locally, the federation router forwards it to a node that has the required capability. Loop prevention ensures intents don't bounce infinitely between nodes.

## Components

### Node Bridge

A ZeroMQ-based bridge that connects ProbOS instances. Each node publishes its capabilities and subscribes to capability announcements from other nodes.

### Intent Router

Routes intents across the federation:

- Checks if the intent can be handled locally
- If not, finds a remote node with the capability
- Forwards the intent with loop-prevention metadata

### Transport

Abstraction over the ZeroMQ transport layer, allowing for different transport backends.

## Source Files

| File | Purpose |
|------|---------|
| `federation/bridge.py` | ZeroMQ node bridge |
| `federation/router.py` | Intent forwarding + loop prevention |
| `federation/transport.py` | Transport abstraction |
