# Configuration

All tuning lives in [`config/system.yaml`](https://github.com/seangalliher/ProbOS/blob/main/config/system.yaml).

## Sections

| Section | Controls |
|---------|----------|
| **pools** | Target sizes (2-7), spawn cooldown, health check intervals |
| **mesh** | Gossip rate, Hebbian decay/reward rates, signal TTL |
| **consensus** | Min votes, approval threshold, trust priors (Beta distribution), decay rate |
| **cognitive** | LLM endpoint, model tiers (fast/standard/deep), token budget, concurrency limit, attention parameters |
| **memory** | Max episodes, relevance threshold |
| **dreaming** | Idle threshold, replay count, strengthening/weakening factors, prune threshold |

## LLM Tiers

ProbOS supports three LLM tiers for different use cases:

| Tier | Use Case |
|------|----------|
| `fast` | Simple operations, quick responses |
| `standard` | General-purpose decomposition |
| `deep` | Complex multi-step reasoning |

Switch tiers at runtime with `/tier fast|standard|deep`.

## Pool Sizing

Each agent pool has a target size. The adaptive scaler adjusts pool sizes based on demand — pools handling high load grow, idle pools shrink back to their minimum.

```yaml
pools:
  filesystem:
    target_size: 3
    min_size: 1
    max_size: 7
```
