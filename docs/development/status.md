# Development Status

**Alpha.** ProbOS implements one governed Cognitive Mesh with an experimental federation transport. The getting-started path is Beta: an automated test runs the [Quickstart](../quickstart.md) from `probos setup` on.

## Snapshot (October 2026)

Measured on `main` on 2026-10-07. The agent figures come from booting the shipped `config/system.yaml` with the built-in mock LLM client; a smaller configuration, such as the one `probos setup` writes, boots fewer agents.

| Metric | Value |
|--------|-------|
| Python tests (`pytest --collect-only`) | 39,707 |
| Vitest test files | 357 (HXI) + 10 (desktop host) |
| Python modules in `src/probos` | 993 (~344,000 lines) |
| Agents at boot | 81, in 51 pools |
| Sovereign crew agents | 15, in 6 departments |
| Pool groups | 9 (Bridge, Core Systems, Engineering, Medical, Operations, Science, Security, Self-Modification, Utility) |
| Shell slash commands | 61 |
| API router modules | 67 |
| Sections in `config/system.yaml` | 181 |
| Architecture decisions | AD numbers past AD-1300 |
| Latest tag | `v0.4.0-phase29c` (March 2026); no release since — PyPI packaging is tracked in [#1053](https://github.com/seangalliher/ProbOS/issues/1053) |

## Eras

| Era | Highlights |
|-----|------------|
| I — Genesis (Phases 1–9) | Substrate, mesh, consensus, cognitive core, shell, federation transport |
| II — Emergence (Phases 10–21) | Self-modification, skills, LLM tiers, dreaming, persistent knowledge, Shapley trust |
| III — Product (Phases 22–29) | HXI, Discord adapter, bundled agents, medical and science teams |
| IV — Evolution (Phase 30+) | Standing orders, Ward Room, sovereign DID identity, ontology, Cognitive JIT, self-regulation, emergence metrics |
| V — Unification | Knowledge graph, brain-enhancement work, commercial-overlay seam |
| VI — Commercial Bridge (May 2026) | Extension-point registry, NATS cognitive-chain pipeline, contagion firewall, voice substrate |

Since June 2026 the work has been organized as programs rather than eras:

| Program | What landed |
|---------|-------------|
| Agentic execution and tools | A multi-turn agentic loop with tool search and delegation; MCP servers with per-agent and per-tool authorization; governed Python execution in per-agent workspaces; office-document agents; a browser tool and browser workstation |
| Crew execution and approvals | Durable crew sessions with recovery and verified finalization; work items agents can discover and claim; an approvals center; delegated approvals with chain-of-command routing and decision pre-clearance |
| Composable cognition | The cognitive spine and organ contracts, with attention and dreaming as the first organs ([design](composable-cognition.md)) |
| Onboarding | `probos setup` provider wizard, `probos doctor`, and a tested [Quickstart](../quickstart.md) |
| Identity and federation | Ed25519 key binding for the ship's `did:probos` identity, signed federation envelopes, and authenticated peer admission proven between two separately started nodes (AD-1196–1198) |
| Platform maturity | The [AD-1270 program](platform-maturity-program.md): exercised capabilities, robust seams, modular owners, fast gates and truthful docs |

## Current Priorities

From the [Roadmap](roadmap.md) (2026-09-07):

1. **Finish the dependable mesh** — AD-1270 / [#1324](https://github.com/seangalliher/ProbOS/issues/1324).
2. **Measure benefit as paths become ready** — the Sigma ablation ([#1064](https://github.com/seangalliher/ProbOS/issues/1064)) and Ship Trials ([#1123](https://github.com/seangalliher/ProbOS/issues/1123)).
3. **Bring human contribution and independent adoption forward** — typed human claims ([#1136](https://github.com/seangalliher/ProbOS/issues/1136)) and a PyPI release ([#1053](https://github.com/seangalliher/ProbOS/issues/1053)).
4. **Authenticate before wider federation** — fleet policy ([#479](https://github.com/seangalliher/ProbOS/issues/479)) follows the two-node authentication now in place.
5. **Keep extensions tied to outcomes** — elastic-team trials ([#1337](https://github.com/seangalliher/ProbOS/issues/1337)) and governed self-maintenance ([#1352](https://github.com/seangalliher/ProbOS/issues/1352)).

## Nooplex Readiness

From the [Nooplex Readiness Map](nooplex-readiness.md), which is the authority for these claims:

| Tier | Name | Status | Permitted claim |
|------|------|--------|-----------------|
| A | Dependable Cognitive Mesh | `planned` | "ProbOS is an alpha implementation of a governed Cognitive Mesh." |
| B | Secure Multi-Mesh | `planned` | "ProbOS has an experimental federation transport." |
| C | Nooplex Core Fabric | `not-started` | "ProbOS provides local foundations for a future Nooplex Core." |
| D | Emergence Research | `research` | "ProbOS is an experimental platform for testing the Nooplex hypothesis." |

Live GitHub issues and their evidence receipts are the completion authority; [PROGRESS.md](https://github.com/seangalliher/ProbOS/blob/main/PROGRESS.md) and [DECISIONS.md](https://github.com/seangalliher/ProbOS/blob/main/DECISIONS.md) hold the narrative and decision logs.
