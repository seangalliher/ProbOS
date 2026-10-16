# OpenHands Absorption

*Sean Galliher, 2026-10-15*
*Source: OpenHands ([github.com/All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands), MIT). Read: the repository README (Agent Canvas); the Software Agent SDK paper, [arXiv 2511.03690](https://arxiv.org/html/2511.03690v1) (MLSys 2026); the Agent Canvas release notes for 1.10 to 1.17; the `openhands-resolver` package description on PyPI (0.3.1). Secondary sources are marked where used.*

## Purpose

This note records which patterns from OpenHands ProbOS absorbs, which it rejects, and where each absorbed idea is owned. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note is the durable link between the source and the issues below. OpenHands appears here only as a technical design reference. Positioning against it belongs in the commercial repository.

## What OpenHands is (2026-10)

- **Software Agent SDK (V1).** A ground-up redesign in four packages: SDK, tools, workspace and server. Its design principles:
  - immutable components;
  - event-sourced state, where `ConversationState` is `base_state.json` plus an append-only event log and resume replays the events;
  - optional isolation, local first.
- **Tools.** Action, Executor and Observation, each validated by Pydantic. MCP tools are translated into SDK tools through a registry.
- **Workspaces.** `LocalWorkspace` runs in process. `RemoteWorkspace` runs over HTTP to an Agent Server, and `DockerWorkspace` gives one container per conversation.
- **Context.** `LLMSummarizingCondenser` writes its condensations as events. The paper cites a separate post for "up to 2×" lower API cost.
- **Security.** An LLM-based `SecurityAnalyzer` rates each action low, medium, high or unknown. A `ConfirmationPolicy`, by default `ConfirmRisky` at high, puts the agent in `WAITING_FOR_CONFIRMATION` until a human approves.
- **Secrets.** A per-conversation secret registry. Secrets reach Bash as environment variables, and output shows `<secret-hidden>`. Secrets can be rotated mid-conversation.
- **Other.** `RouterLLM` picks a model per request. Delegation is a tool, and the parent blocks until its sub-agents finish. Skills are markdown files, always active or activated by keyword.
- **Agent Canvas.** A self-hosted control center. It runs the OpenHands agent or third-party agents (Claude Code, Codex, Gemini CLI), and adds automations: cron schedules, webhooks, a catalog, and separate view and manage permissions as of 1.17.
- **GitHub resolver.** A `fix-me` label or an `@openhands-agent` mention starts an attempt. Success opens a draft PR, and failure pushes a branch. Either way it comments on the issue and removes the label.
- **Reported results.** SWE-Bench Verified 72.8% and GAIA 67.9%, both with Claude Sonnet 4.5 (paper, Table 2).
- **Builds itself.** About 20% of commits were "created or co-created by OpenHands" in January 2025. This is secondhand, attributed to the CEO in a Hacker News comment, and not verified against the repository.

## Absorbed

| # | OpenHands pattern | ProbOS gap (verified 2026-10-15) | Owner |
|---|---|---|---|
| 1 | **A Docker container per session** as the proven default isolation for agent commands. | Only Tier 1 is built (`execution/isolation.py:651`, `SubprocessSandbox`). `ContainerSandbox` (`security/container_sandbox.py`, AD-798) is built and tested, but no production code path instantiates it: its `src/` mentions are docstrings (`task_sessions/browser.py:18`, `:134`; `doctor/__init__.py:5`), and the doctor's sandbox check probes only the Docker CLI. The Copilot SDK build session's shell is `approve_all` on the host (BF-896, #1550). | AD-1335/#1557, amended: Docker first, then MXC (AD-1334/#1556), otherwise refuse. |
| 2 | **Resolver loop.** Label or mention triggers, a draft PR on success, a pushed branch on failure, an issue comment either way, and iteration on review comments. | ProbOS files issues (AD-1206, `cognitive/repair_issue.py`) but does not work them. Merges go to local main (`worktree_manager.py:146`, BF-897, #1559). | AD-1336/#1558, amendment of 2026-10-15 (children 1 and 6). Triggers come only from the owner or a collaborator and never bypass ranking or the Captain's approval. |
| 3 | **Secret masking in tool output** (`<secret-hidden>`). | BF-890 strips credential-shaped names from child environments (`execution/command_env.py`), and `PIIRedactor.redact_tokens` masks token *patterns* in logs and traces. Nothing masks known credential *values* in tool output before it reaches a model. | AD-1337/#1560. |
| 4 | **Event-sourced, replayable runs.** | Lifecycle records (AD-1224) and tool traces (AD-1203) exist but are not one replayable graph. | Already owned: AD-1329/#1531 (the run reducer, from the Codex absorption). |
| 5 | **Published benchmark numbers** per model. | ProbOS publishes none for its builder. | Ship Trials, AD-1186/#1123. A SWE-Bench Verified subset is a candidate evaluator. |

## Rejected or deferred

- **LLM-rated risk plus human confirmation as the gate.** It assumes a person is present, and the paper does not say how the analyzer's ratings are checked. ProbOS gates with policy and services: AD-1328 command policy, the AD-1316 effect broker, consensus. It escalates through the chain of command instead of waiting (Design Principle 13, AD-1231). An independent pre-action reviewer is AD-1330/#1532.
- **Blocking delegation.** ProbOS delegates through elastic teams (AD-1288, #1332) and crew consultation and has no blocking-delegation primitive.
- **Markdown skills activated by keyword.** ProbOS's T2 cognitive skills (AD-596, AD-625) already cover this.
- **The condenser.** ProbOS has its own compaction (AD-1142) and offload (AD-1240). Compare designs when compaction is next touched.
- **Running third-party agents as backends** (Agent Canvas). This partly overlaps ProbOS's harness-neutral repair briefs (AD-1172), which record a target but dispatch nothing (`cognitive/repair_dispatch.py:9-11`). Dispatch is a child of AD-1336/#1558, not a separate absorption.
- **Hosted cloud, enterprise and the automation catalog.** These are commercial concerns, for the commercial repository.

## Consistent with existing ProbOS principles

The patterns absorbed here are mechanical: isolation, a delivery loop and output hygiene. They change nothing about who decides. ProbOS keeps its governance model: agents decide and services enforce, every step leaves evidence, and autonomy is earned.
