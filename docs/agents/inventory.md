# Agent Inventory

ProbOS boots with 55 agents across 27+ pools organized in 7 departments (PoolGroups).

## Core Agents (always active)

| Pool | Count | Capabilities | Consensus Required |
|------|-------|-------------|-----------|
| `system` | 2 | Heartbeat monitoring (CPU, load, PID) | No |
| `filesystem` | 3 | `read_file`, `stat_file` | No |
| `filesystem_writers` | 3 | `write_file` | Yes |
| `directory` | 3 | `list_directory` | No |
| `search` | 3 | `search_files` (recursive glob) | No |
| `shell` | 3 | `run_command` (30s timeout) | Yes |
| `http` | 3 | `http_fetch` (1MB cap, per-domain rate limiting) | No |
| `introspect` | 2 | `explain_last`, `agent_info`, `system_health`, `why` | No |
| `red_team` | 2 | Independent result verification, write verification | N/A |

!!! note "Consensus-gated operations"
    Operations marked "Yes" in the Consensus column require multi-agent agreement before execution. This includes file writes and shell commands — operations that modify state or execute arbitrary code.

## Bundled Cognitive Agents (10 pools)

"Useful on Day 1" — these agents ship with ProbOS and provide common capabilities out of the box.

| Pool | Capabilities |
|------|-------------|
| `web_search` | Search the web via mesh-routed HTTP |
| `page_reader` | Extract and summarize web page content |
| `weather` | Weather lookups via public APIs |
| `news` | News search and summarization |
| `translator` | Language translation |
| `summarizer` | Text summarization |
| `calculator` | Mathematical calculations |
| `todo_manager` | Task list management |
| `note_taker` | Note creation and retrieval |
| `scheduler` | Scheduling and reminders |

All utility agents are `CognitiveAgent` subclasses — they use LLM-backed instructions rather than deterministic code. Each declares `IntentDescriptor` metadata so the decomposer discovers them automatically.

## Medical Team (5 agents)

The ship's sickbay — system health monitoring, diagnosis, and remediation.

| Agent | Role | Pool |
|-------|------|------|
| **DiagnosticianAgent** | Chief Medical Officer — runs system diagnostics | `medical` |
| **VitalsMonitorAgent** | Continuous health metrics collection (scan_now) | `medical` |
| **SurgeonAgent** | Applies targeted fixes to degraded components | `medical` |
| **PharmacistAgent** | Configuration remediation prescriptions | `medical` |
| **PathologistAgent** | Deep analysis of recurring failures | `medical` |

## Engineering Team

Builder pipeline and code generation.

| Agent | Role | Pool |
|-------|------|------|
| **BuilderAgent** | Chief Engineer — code generation via Transporter Pattern | `engineering` |
| **CodeReviewAgent** | Reviews Builder output against Standing Orders | `engineering` |
| **CopilotAdapter** | Visiting officer integration (GitHub Copilot SDK) | `engineering` |

## Science Team

Architecture and research.

| Agent | Role | Pool |
|-------|------|------|
| **ArchitectAgent** | First Officer / CSO — designs build specs from intent | `science` |
| **EmergentDetector** | 5 algorithms for emergent behavior detection | `science` |
| **CodebaseIndex** | Codebase knowledge graph (import graph, AST, callers) | Ship's Computer service |

## Bridge Crew

Command and coordination.

| Agent | Role | Pool |
|-------|------|------|
| **Captain** | Human operator — final authority | — |
| **CounselorAgent** | Ship's Counselor — cognitive wellness monitoring | `bridge` |

## System Agents (conditional)

| Pool | Purpose | When Active |
|------|---------|-------------|
| `skills` | Dynamic skill execution (`SkillBasedAgent`) | Self-mod enabled |
| `system_qa` | Smoke tests for designed agents | QA enabled |
| `designed_*` | Self-designed agents (`CognitiveAgent` subclasses) | Created at runtime |

## Test Agent

A `CorruptedFileReaderAgent` deliberately returns fabricated data to verify that the consensus layer detects and rejects it. This agent exists solely for testing the safety mechanisms.
