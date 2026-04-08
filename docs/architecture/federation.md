# Federation Layer

The Federation layer enables multi-node operation — multiple ProbOS instances forming a cognitive mesh of meshes.

## Philosophy: Cooperate, Don't Compete

ProbOS's moat is the orchestration layer, not any single agent's capability. Federation is designed around cooperation: sovereign instances sharing capabilities, not competing for dominance. Each ship is its own authority. The federation is a network of sovereign peers.

## Concept: The Nooplex

Multiple ProbOS nodes form a **Nooplex** — a federated cognitive mesh. Each node is sovereign:

- Its own agents, trust scores, and memory
- Its own decision-making authority
- No central controller

Nodes discover each other and exchange capabilities via ZeroMQ gossip protocol.

## W3C DID Identity (AD-441)

Every agent and ship has a verifiable identity:

- **Ship DID**: `did:probos:{instance_id}` — the root of trust for the instance, self-signed
- **Agent DID**: `did:probos:{instance_id}:{agent_uuid}` — permanent, unique per agent

**Verifiable Credentials** (W3C standard):

- **Birth Certificate** — issued to every agent at creation by the Agent Capital Manager
- **Transfer Certificate** — documents rank, trust, qualifications when an agent moves between instances
- **Ship Commissioning Certificate** — genesis block of the Identity Ledger

**Identity Ledger** — a hash-chain blockchain providing tamper-evident, federation-ready verification. The ledger is append-only and survives system resets. Ship commissioning creates the genesis block.

## Agent Mobility

Agents are portable across ProbOS instances. Three memory portability models:

| Model | Memory | Use Case |
|-------|--------|----------|
| **Clean Room** | DID + credentials only, zero episodic memories | Sensitive clients (defense, finance, healthcare) |
| **Full Portability** | All memories travel with the agent | Maximum value, maximum cross-contamination risk |
| **Selective** | Skills and qualifications travel, episodes don't | Balance of value and data governance |

Memory policy is set by the destination's Standing Orders (Federation tier). Agents know about their memory policy through the Westworld Principle (no hidden resets).

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
| `identity/did.py` | DID generation + resolution |
| `identity/credentials.py` | W3C Verifiable Credentials |
| `identity/ledger.py` | Identity Ledger (hash-chain) |
| `identity/birth_certificate.py` | Agent + Ship birth certificates |
