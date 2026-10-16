# Reference Projects

*Sean Galliher, 2026-10-15*

## Purpose

Absorbing outside work has been ad hoc: a project gets researched when someone happens to hear of it, and the Architect's prior-art review can only find what an earlier note already recorded in `docs/research/`. This list keeps the projects ProbOS learns from in one place, with when each was last examined and how deeply. During its prior-art review (`.claude/agents/claude-architect.md`), the Architect re-examines a bounded number of the overdue projects that are relevant to the AD it is drafting.

Projects appear here only as technical design references. Positioning against them belongs in the commercial repository.

## How to use it

- **Last reviewed** is the date of the work that examined or cited the project: the research note, or the commit that added the citation. It is not the date a file was last edited.
- **Overdue** means *Last reviewed* is older than the row's *Interval*, or the project has never been reviewed. Judge it against today's date, and state the date you used.
- **Depth:**
  - *absorption*: a dedicated note in `docs/research/`.
  - *checked*: examined for a specific AD, with the result recorded in that AD, including "nothing new".
  - *passing*: named inside another note or prompt, not examined.
  - *never*: not reviewed.
- **Interval:** 90 days for fast-moving agent harnesses and sandboxes; 180 days for frameworks, protocols, memory systems and research lines.
- **When drafting a design AD,** pick at most two overdue projects that are relevant to its problem and examine them within the bounded external search. The other overdue ones become one-line "considered, deferred" notes and stay overdue. Update each examined row: date, depth (*checked* or *absorption*), and where it is recorded. Under `--read-only`, put the row updates in the answer, and the caller (the orchestrator) applies them in its next docs change.
- **Add a project** when it bears on more than one AD or on the harnesses ProbOS's own workflow runs on. A project that matters to one problem only belongs in that AD's Prior Art section.

## Coding-agent harnesses (interval: 90 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| OpenHands (Software Agent SDK, Agent Canvas, GitHub resolver) | 2026-10-15 | absorption | `openhands-absorption.md` (PR #1561); earlier passing in AD-360 (2026-03-20) |
| OpenAI Codex | 2026-10-14 | absorption | `codex-harness-absorption.md` |
| Claude Code | 2026-10-15 | checked | sandbox and permission model studied for AD-1335 (#1557); lexical search in the AD-989 ripgrep absorption (2026-06-13, `DECISIONS.md`); context forking in `cognitive-sub-task-protocol.md` (2026-04-15) |
| GitHub Copilot coding agent | 2026-10-15 | checked | AD-1336 (#1558) Prior art |
| OpenCode (magic context) | 2026-05-08 | absorption | `opencode-magic-context-absorption.md` |
| SWE-agent | 2026-03-20 | passing | AD-360 builder guardrails (container-scoped isolation) |
| Aider | 2026-06-13 | passing | AD-360 (pre-edit dirty commit, edit-lint-test-reflect); AD-989 (lexical search) |
| Cline | 2026-03-20 | passing | AD-360 (shadow git checkpoints, workspace access tiers) |
| Cursor | 2026-06-13 | passing | AD-989 (lexical search); also named as an AgentSkills.io adopter |
| Goose | 2026-04-08 | passing | `universal-agent-activation-research.md` (as an MCP Apps host) |
| Darwin Gödel Machine (Sakana) | 2026-10-15 | absorption | `darwin-godel-machine-absorption.md`; drove BF-898 (#1563) and the AD-1336 (#1558) evidence amendment. Its follow-up is the HyperAgents row |

## Agent frameworks and SDKs (interval: 180 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| LangGraph | 2026-09-03 | passing | `cognitive-jit-procedural-learning-research.md` (orchestration survey) |
| AutoGen | 2026-09-03 | passing | `cognitive-jit-procedural-learning-research.md`; `dynamic-communication-register-research.md` |
| CrewAI | 2026-09-03 | passing | the same two notes; `emergence-taxonomy.md` |
| Letta (MemGPT) | 2026-10-15 | passing | `cognitive-jit-procedural-learning-research.md` (self-editing memory blocks); AD-1339 (#1566) Prior art (sleep-time agents, from a search summary) |
| Voyager (skill library) | 2026-10-15 | passing | `cognitive-jit-procedural-learning-research.md`; AD-1338 (#1565) Prior art (from a search summary) |
| Hermes Agent | 2026-06-06 | passing | `crew-capability-architecture.md` (self-improving skills, AD-596) |
| Google Agent Development Kit | 2026-04-08 | passing | `universal-agent-activation-research.md` (the agent layer of Solace Agent Mesh) |
| OpenAI Agents SDK | never | never | none |

## Memory, retrieval and knowledge (interval: 180 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| RAGFlow | 2026-05-08 | absorption | `ragflow-absorption.md` |
| LoCoMo benchmark | 2026-05-08 | absorption | `locomo-benchmark-absorption.md` |
| Memvid | 2026-04-05 | absorption | `memvid-evaluation.md` |
| AI Meets Brain memory survey (arXiv 2512.23343) | 2026-04-12 | absorption | `agent-memory-survey-absorption.md` |

## Protocols and standards (interval: 180 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| AgentSkills.io (`SKILL.md`) | 2026-06-06 | passing | `crew-capability-architecture.md`; adopted for T2 skills (AD-596) |
| MCP Apps | 2026-04-08 | passing | AD-597; `universal-agent-activation-research.md` |
| AG-UI | never | never | none in the repository |

## Isolation and sandboxing (interval: 90 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| Microsoft MXC | 2026-10-15 | checked | AD-1334 (#1556) and AD-1335 (#1557), from the README and the v1.0.0 release notes; the per-backend docs are not yet read (AD-1334, Decision 1). Earlier: AD-995 (#939, 2026-06-13) |

## Research lines (interval: 180 days)

| Project | Last reviewed | Depth | Where recorded |
|---|---|---|---|
| MASS multi-agent self-supervision (UC Berkeley, Sakana AI) | 2026-10-11 | absorption | `mass-self-supervision-absorption.md` |
| HyperAgents (arXiv 2603.19461) | 2026-10-15 | absorption | `hyperagents-absorption.md`; drove AD-1338 (#1565), AD-1339 (#1566) and the AD-1299 (#1352) meta-level amendment. Read in part (first 100K of about 179K characters) |

A *passing* row is a weak signal: the project was named, not examined. When an AD's problem is the one a passing project addresses, treat the row as *never*.
