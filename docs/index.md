# ProbOS

> **Alpha** — ProbOS is under active development. APIs will change, features may break, and documentation may lag behind the code. The getting-started path is **Beta**: an automated test runs the [Quickstart](quickstart.md) from `probos setup` on. Contributions and feedback welcome.

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior. Agents are organized as the crew of a starship — departments, ranks, a chain of command, standing orders, and a human Captain.

> *"What if an OS didn't execute instructions — it negotiated them?"*

!!! info "Nooplex readiness"
    ProbOS currently implements an alpha, single-mesh Cognitive Mesh with an experimental federation substrate. A dependable supported mesh, authenticated multi-mesh operation, the Nooplex Core Fabric, and emergence validation are separate evidence gates tracked in the [Nooplex Readiness Map](development/nooplex-readiness.md).

---

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a central scheduler, agents select their own work through capability matching, Hebbian-learned routing and Bayesian trust. Instead of permissions alone, consequential actions are governed by multi-agent consensus, chain-of-command approval and an audit trail.

```
[15 crew | health: 0.95] probos> read pyproject.toml and tell me about this project

  ✓ t1: read_file

  This project is ProbOS, a probabilistic agent-native OS runtime...
```

The agents are persistent. A ProbOS vessel keeps running when you step away: its crew remembers, talks in the Ward Room, consolidates what it learned while idle ("dreaming"), and continues durable work within the authority you delegate. Governance — consensus, trust, approvals, audit and the chain of command — is what buys the crew the autonomy to act unattended.

## What ProbOS Does Today

- **A crew, not a pipeline** — fifteen sovereign crew agents in six departments, each with a DID identity, a personality seed, episodic memory, a trust record and an earned rank. See [Agent Inventory](agents/inventory.md).
- **Agentic work with governed tools** — a multi-turn agentic loop for 1:1 conversations and work items, with capability search, delegation, work items, MCP servers, governed Python execution and a browser tool; office-document agents serve the whole mesh.
- **Consensus, trust and learned routing** — Bayesian trust, Hebbian routing, quorum voting with red-team verification, and an explicit statement of what each consensus vote authorizes. See [Consensus](architecture/consensus.md).
- **Durable, approvable work** — claimable work items, recoverable crew sessions, persistent tasks, an approvals center on the Bridge, delegated approvals, Night Orders and the conn.
- **Memory that consolidates** — episodic memory, Ship's Records, a vessel ontology and knowledge graph, and a multi-stage dream cycle. See [Memory](architecture/memory.md).
- **Identity and federation (experimental)** — `did:probos` identities, birth certificates, ship-level Ed25519 key binding, and signed, authenticated federation between nodes. See [Federation](architecture/federation.md).
- **Beyond the terminal** — the HXI bridge interface, a desktop tray host, and channel adapters for Discord, Slack, Telegram, Matrix, Microsoft Teams, Gmail and webhooks.

## Design Philosophy

Traditional operating systems use rigid, deterministic mechanisms: syscalls, schedulers, ACLs. ProbOS replaces each with a probabilistic, self-organizing equivalent:

| Traditional OS | ProbOS Equivalent |
|---------------|-------------------|
| Syscalls | Natural language decomposed into intent DAGs |
| Process scheduler | Attention-based priority scoring with Hebbian learning |
| File permissions / ACLs | Multi-agent consensus, earned trust and chain-of-command approval |
| Process table | Agent registry with health monitoring and auto-recycling |
| IPC | Pub/sub intent bus with concurrent fan-out; the Ward Room between crew |
| Cron / scheduled tasks | Dreaming engine — offline consolidation during idle periods |
| Command history | Episodic memory with semantic recall |
| Shell aliases | Workflow cache and compiled procedures — learned shortcuts for repeated patterns |

Every agent maintains a confidence score and trust reputation. The system doesn't just execute operations — it *deliberates*, *verifies*, and *learns*.

## How It Works

When you give the Ship's Computer a natural-language request:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** surfaces similar past interactions as context
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy with pre-warm intents)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency × relevance × deadline_factor × dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering
7. **Consensus** sends intents that require it to a quorum vote with red-team verification
8. **Reflection** (optional) sends execution results back to the LLM for synthesis
9. **Hebbian router** strengthens successful agent-intent pairings, weakens failures
10. **Episodic memory** stores the interaction for future recall
11. **Workflow cache** stores successful patterns to bypass the LLM on repeat queries
12. **Dreaming engine** consolidates learning during idle periods — replays episodes, prunes weak connections, adjusts trust scores, pre-warms likely upcoming intents

Conversations with crew members run through each agent's own cognitive cycle — its standing orders and its own memory, plus the agentic tool loop for 1:1 replies and work items — and feed the same learning loops.

## Quick Links

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Quickstart](quickstart.md)**

    Install ProbOS, configure a model with `probos setup`, check it with `probos doctor`, and start a first conversation.

-   :material-layers-triple: **[Architecture](architecture/overview.md)**

    Five layers from Substrate to Experience, plus Knowledge, Identity, Security and Federation services.

-   :material-robot: **[Agents](agents/inventory.md)**

    The crew of six departments, the Ship's Computer's infrastructure and utility agents, and how rank and trust are earned.

-   :material-map-marker-path: **[Status & Roadmap](development/status.md)**

    Where ProbOS stands today, current priorities, and the Nooplex readiness tiers.

-   :fontawesome-brands-github: **[GitHub](https://github.com/seangalliher/ProbOS)**

    Source, issues and the full decision log.

-   :fontawesome-brands-discord: **[Discord](https://discord.gg/cbprTVfsjt)**

    Join the community.

</div>
