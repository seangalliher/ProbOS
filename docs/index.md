# ProbOS

**Probabilistic agent-native OS runtime** — an operating system kernel where every component is an autonomous agent, coordination happens through consensus, and the system learns from its own behavior.

> *"What if an OS didn't execute instructions — it negotiated them?"*

---

## What Is This?

ProbOS reimagines the OS as a mesh of probabilistic agents rather than deterministic processes. Instead of syscalls, you speak natural language. Instead of a scheduler, agents self-organize through Hebbian learning and trust networks. Instead of permissions, destructive operations require multi-agent consensus.

```
[47 agents | health: 0.95] probos> read pyproject.toml and tell me about this project

  ✓ t1: read_file

  This project is ProbOS v0.1.0, a probabilistic agent-native OS runtime...
```

## Design Philosophy

Traditional operating systems use rigid, deterministic mechanisms: syscalls, schedulers, ACLs. ProbOS replaces each with a probabilistic, self-organizing equivalent:

| Traditional OS | ProbOS Equivalent |
|---------------|-------------------|
| Syscalls | Natural language decomposed into intent DAGs |
| Process scheduler | Attention-based priority scoring with Hebbian learning |
| File permissions / ACLs | Multi-agent consensus voting with red team verification |
| Process table | Agent registry with health monitoring and auto-recycling |
| IPC | Pub/sub intent bus with concurrent fan-out |
| Cron / scheduled tasks | Dreaming engine — offline consolidation during idle periods |
| Command history | Episodic memory with semantic recall |
| Shell aliases | Workflow cache — learned shortcuts for repeated patterns |

Every agent maintains a confidence score and trust reputation. The system doesn't just execute operations — it *deliberates*, *verifies*, and *learns*.

## How It Works

When you type natural language:

1. **Working memory** assembles system state (agent health, trust scores, Hebbian weights, capabilities) within a token budget
2. **Episodic recall** finds similar past interactions for context (top-3 by keyword-overlap cosine similarity)
3. **Workflow cache** checks for previously successful DAG patterns (exact match, then fuzzy with pre-warm intents)
4. **LLM decomposer** converts text into a `TaskDAG` — a directed acyclic graph of typed intents with dependencies
5. **Attention manager** scores tasks: `urgency × relevance × deadline_factor × dependency_bonus`
6. **DAG executor** runs independent intents in parallel, respects dependency ordering
7. **Consensus** gates destructive operations through multi-agent voting + red team verification
8. **Reflection** (optional) sends execution results back to the LLM for synthesis
9. **Hebbian router** strengthens successful agent-intent pairings, weakens failures
10. **Episodic memory** stores the interaction for future recall
11. **Workflow cache** stores successful patterns to bypass the LLM on repeat queries
12. **Dreaming engine** consolidates learning during idle periods — replays episodes, prunes weak connections, adjusts trust scores, pre-warms likely upcoming intents

## Quick Links

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting Started](getting-started/installation.md)**

    Install ProbOS and launch the interactive shell in under a minute.

-   :material-layers-triple: **[Architecture](architecture/overview.md)**

    Seven layers from Substrate to Experience, plus Federation and Knowledge.

-   :material-robot: **[Agents](agents/inventory.md)**

    47 agents across 20+ pools — core, cognitive, and self-designed.

-   :fontawesome-brands-discord: **[Discord](https://discord.gg/probos)**

    Join the community.

</div>
