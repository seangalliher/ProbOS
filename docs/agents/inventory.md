# Agent Inventory

ProbOS boots with ~60 agent instances across 36 pools organized in 9 pool groups (6 departments + core, utility, self-mod).

## Three-Tier Agent Architecture

ProbOS distinguishes three tiers of agents based on identity:

| Tier | Identity | Example |
|------|----------|---------|
| **Infrastructure** | No identity — Ship's Computer services | IntrospectAgent, VitalsMonitor, RedTeamAgent |
| **Utility** | No identity — bundled tools | WebSearch, Calculator, Translator |
| **Crew** | Sovereign individuals with callsigns, personality, memory | Meridian (Architect), Echo (Counselor), Worf (Security) |

The principle: *"If it doesn't have Character/Reason/Duty, it's not crew. A microwave with a name tag isn't a person."*

---

## Infrastructure Agents (Ship's Computer)

These agents provide system services. They may use LLMs but have no sovereign identity, personality, or episodic memory shard.

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
| `system_qa` | 1 | Smoke tests for designed agents | No |

!!! note "Consensus-gated operations"
    Operations marked "Yes" require multi-agent agreement before execution. This includes file writes and shell commands — operations that modify state or execute arbitrary code.

## Utility Agents (10 pools)

"Useful on Day 1" — bundled tools that ship with ProbOS.

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

All utility agents are `CognitiveAgent` subclasses with `IntentDescriptor` metadata for automatic discovery.

---

## Crew Agents (Sovereign Individuals)

Each crew agent has a callsign, Big Five personality traits, episodic memory shard, trust reputation, and rank (Ensign → Lieutenant → Commander → Senior). They communicate through the Ward Room and form memories from their interactions.

### Bridge

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| Captain | — | Human operator — final authority | — |
| **ArchitectAgent** | Meridian | First Officer — designs build specs from intent | `architect` |
| **CounselorAgent** | Echo | Ship's Counselor — cognitive wellness, therapeutic intervention | `counselor` |

### Engineering Department

Chief: LaForge (EngineeringAgent)

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| **EngineeringAgent** | LaForge | Department Chief — system architecture + performance | `engineering_officer` |
| **BuilderAgent** | — | Code generation via Transporter Pattern | `builder` |
| **CodeReviewAgent** | — | Reviews Builder output against Standing Orders | `code_reviewer` |

### Science Department

Chief: Number One (ArchitectAgent, dual-hatted)

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| **DataAnalystAgent** | Kira | Data Analyst — quantitative analysis | `science_data_analyst` |
| **SystemsAnalystAgent** | Lynx | Systems Analyst — cross-system pattern analysis | `science_systems_analyst` |
| **ResearchSpecialistAgent** | Atlas | Research Specialist — deep domain research | `science_research_specialist` |
| **ScoutAgent** | Horizon | Scout — external + internal research | `scout` |

The Science Analytical Pyramid: Data flows up (Kira → Lynx → Atlas), questions flow down.

### Medical Department

Chief: Bones (DiagnosticianAgent)

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| **DiagnosticianAgent** | Bones | Chief Medical Officer — system diagnostics | `medical_diagnostician` |
| **SurgeonAgent** | Chapel | Targeted remediation of degraded components | `medical_surgeon` |
| **VitalsMonitorAgent** | Chapel | Continuous health metrics collection | `medical_vitals` |
| **PharmacistAgent** | Keiko | Configuration remediation prescriptions | `medical_pharmacist` |
| **PathologistAgent** | Cortez | Deep failure analysis + post-mortem | `medical_pathologist` |

### Security Department

Chief: Worf (SecurityAgent)

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| **SecurityAgent** | Worf | Trust integrity, threat detection | `security_officer` |

### Operations Department

Chief: O'Brien (OperationsAgent)

| Agent | Callsign | Role | Pool |
|-------|----------|------|------|
| **OperationsAgent** | O'Brien | Resource management, scheduling, watch rotation | `operations_officer` |

---

## System Agents (conditional)

| Pool | Purpose | When Active |
|------|---------|-------------|
| `skills` | Dynamic skill execution (`SkillBasedAgent`) | Self-mod enabled |
| `designed_*` | Self-designed agents (`CognitiveAgent` subclasses) | Created at runtime |

## Test Agent

A `CorruptedFileReaderAgent` deliberately returns fabricated data to verify that the consensus layer detects and rejects it.
