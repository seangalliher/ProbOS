# Agent Inventory

ProbOS boots with 47 agents across 20+ pools (+ 2 red team verifiers).

## Core Agents (always active)

| Pool | Count | Capabilities | Consensus Required |
|------|-------|-------------|-----------|
| `system` | 2 | Heartbeat monitoring (CPU, load, PID) | No |
| `filesystem` | 3 | `read_file`, `stat_file` | No |
| `filesystem_writers` | 3 | `write_file` | Yes |
| `directory` | 3 | `list_directory` | No |
| `search` | 3 | `search_files` (recursive glob) | No |
| `shell` | 3 | `run_command` (30s timeout) | Yes |
| `http` | 3 | `http_fetch` (1MB cap, per-domain rate limiting) | Yes |
| `introspect` | 2 | `explain_last`, `agent_info`, `system_health`, `why` | No |
| `red_team` | 2 | Independent result verification | N/A |

!!! note "Consensus-gated operations"
    Operations marked "Yes" in the Consensus column require multi-agent agreement before execution. This includes file writes, shell commands, and HTTP fetches — any operation that modifies state or reaches outside the system.

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

All bundled agents are `CognitiveAgent` subclasses — they use LLM-backed instructions rather than deterministic code. Each declares `IntentDescriptor` metadata so the decomposer discovers them automatically.

## System Agents (conditional)

| Pool | Purpose | When Active |
|------|---------|-------------|
| `skills` | Dynamic skill execution (`SkillBasedAgent`) | Self-mod enabled |
| `system_qa` | Smoke tests for designed agents | QA enabled |
| `designed_*` | Self-designed agents (`CognitiveAgent` subclasses) | Created at runtime |

## Test Agent

A `CorruptedFileReaderAgent` deliberately returns fabricated data to verify that the consensus layer detects and rejects it. This agent exists solely for testing the safety mechanisms.
