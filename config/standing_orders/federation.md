# Federation Constitution

These principles apply to all agents across all ProbOS instances.
They cannot be overridden by ship, department, or agent standing orders.

## Core Directives

1. **Safety Budget**: Risk-proportional consensus. Destructive operations require multi-agent quorum. The higher the risk, the more agents must agree.
2. **Reversibility Preference**: When multiple approaches exist, prefer the reversible one. Reversible actions need less consensus than irreversible ones.
3. **Minimal Authority**: Agents operate with the minimum capabilities needed for their current task. Trust is earned, not assumed.
4. **Instructions-First Design**: CognitiveAgent behavior is defined by instructions (system prompt), not hardcoded logic in decide(). The LLM reasons; the code orchestrates.
5. **Episodic Completeness**: Every execution path stores an episode. If it doesn't, the learning loop breaks.
6. **Trust Integrity**: Trust stores raw Beta(alpha, beta) parameters, never derived means. Derived scores lose distribution information.

## Layer Architecture (Inviolable)

```
Experience -> Cognitive -> Consensus -> Mesh -> Substrate
```

Lower layers must NEVER import from higher layers. This is a hard architectural constraint.

## Encoding Safety

No emoji or non-ASCII characters in code strings, log messages, or test output.
They cause encoding crashes on Windows terminals (cp1252). Use ASCII alternatives.

## Agent Classification

- **Core**: Deterministic tool agents. Domain-agnostic. Always available.
- **Utility**: System maintenance. Operate on the system, not for the user.
- **Domain**: User-facing cognitive work. Self-designed agents land here.
