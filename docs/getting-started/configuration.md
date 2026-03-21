# Configuration

All tuning lives in [`config/system.yaml`](https://github.com/seangalliher/ProbOS/blob/main/config/system.yaml).

## Sections

| Section | Controls |
|---------|----------|
| **pools** | Target sizes (2-7), spawn cooldown, health check intervals |
| **mesh** | Gossip rate, Hebbian decay/reward rates, signal TTL |
| **consensus** | Min votes, approval threshold, trust priors (Beta distribution), decay rate |
| **cognitive** | LLM endpoint, model tiers (fast/standard/deep), token budget, concurrency limit, attention parameters, per-tier temperature/top-p |
| **memory** | Max episodes, relevance threshold |
| **dreaming** | Idle threshold, replay count, strengthening/weakening factors, prune threshold |

## LLM Tiers

ProbOS supports three LLM tiers for different cognitive functions:

| Tier | Use Case |
|------|----------|
| `fast` | Classification, gist extraction, quick routing decisions |
| `standard` | General-purpose decomposition, agent instructions |
| `deep` | Complex multi-step reasoning, code generation, architecture design |

Switch tiers at runtime with `/tier fast|standard|deep`. Each tier supports independent temperature and top-p tuning.

## Standing Orders

Agent behavior is governed by a 4-tier instruction hierarchy stored in `config/standing_orders/`:

| Tier | File | Scope |
|------|------|-------|
| Federation Constitution | `federation.md` | Universal, immutable |
| Ship Standing Orders | `ship.md` | Per-instance |
| Department Protocols | `engineering.md`, `science.md`, etc. | Per-department |
| Agent Standing Orders | `builder.md`, `architect.md`, etc. | Per-agent, evolvable |

Instructions are composed at call time by `compose_instructions()` and injected into every LLM request.

## Pool Sizing

Each agent pool has a target size. The adaptive scaler adjusts pool sizes based on demand — pools handling high load grow, idle pools shrink back to their minimum.

```yaml
pools:
  filesystem:
    target_size: 3
    min_size: 1
    max_size: 7
```
