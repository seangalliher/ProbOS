# Capability Truth Inventory

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_capability_truth.py`.

This is an **observation-only** inventory (AD-1270a, migration step 1). Nothing
reads a row to make a decision: it changes no routing, permission, trust or
startup behaviour. It exists so that *shipped* and *working* stop looking alike.

Each capability is resolved against three **different** authorities, so the
facts cannot collapse into one another:

| Axis | Authority |
|---|---|
| `present` | the Python import system over the source tree |
| `configured` | `SystemConfig` loaded from the config file |
| `advertised` | `routers.tools.list_capability_catalog(runtime)` |

`unknown` means *not observed*, never *absent*. A declaration whose
`configured_when` does not resolve is reported `unknown` with a note, because a
broken declaration is not a disabled capability.

**Why so much of this page says `unknown`, and why that is the finding.**
`activated`, `exercise` and `health` have no producer yet — emitting activation
receipts is migration step 2 and recording exercise receipts is migration step 3.
The generator also runs offline and constructs no runtime, which keeps `--check`
hermetic and is why `advertised` is `unknown` here even though the axis is
genuinely wired and covered by tests. `live` is **derived, never stored**, and no
row can read `live` without both an activation fact and at least one exercise
attempt — so in this slice no capability is provably live, and the page says so
rather than defaulting to optimism.

## Inventory

| Capability | Present | Configured | Advertised | Activated | Exercise attempts | Health | Live |
|---|---|---|---|---|---|---|---|
| `agents.http-fetch` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `cognitive.crew-session` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `cognitive.episodic-memory` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `cognitive.intent-decomposition` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `cognitive.self-modification` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `infrastructure.snapshot-manifest` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `tools.code-execution` | yes | yes | unknown | unknown | 0 | unknown | unknown |
| `tools.governed-invocation` | yes | yes | unknown | unknown | 0 | unknown | unknown |

## Detail

### `agents.http-fetch` — Mesh HTTP fetch

- **Owner:** `probos.agents.http_fetch.HttpFetchAgent`
- **Configured when:** always (unconditional in the profile)
- **Catalog binding:** `http_fetch` on the `mesh_intents` axis
- **Notes:** Catalog-bound on the mesh-intent axis. Designed agents route HTTP through this intent so governance and per-domain rate limiting apply; a row advertised nowhere means that route is unreachable.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `cognitive.crew-session` — Crew session orchestration

- **Owner:** `probos.cognitive.crew_orchestrator.CrewOrchestrator`
- **Configured when:** `workforce.enabled`
- **Catalog binding:** none declared
- **Related seams:** `TA-P0-007-crew-outcome-trust`
- **Notes:** Owns durable workflow time for crew work: admission bounds, compare-and-set transitions, crash recovery, cancellation.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `cognitive.episodic-memory` — Episodic memory

- **Owner:** `probos.cognitive.episodic.EpisodicMemory`
- **Configured when:** always (unconditional in the profile)
- **Catalog binding:** none declared
- **Notes:** Semantic recall over past executions. An execution path that stores no episode breaks the learning loop silently.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `cognitive.intent-decomposition` — Intent decomposition

- **Owner:** `probos.cognitive.decomposer.IntentDecomposer`
- **Configured when:** always (unconditional in the profile)
- **Catalog binding:** none declared
- **Related seams:** `TA-P0-001-turn-act-evidence`
- **Notes:** Turns natural language into a TaskDAG of typed intents. On the request path for every cognitive turn.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `cognitive.self-modification` — Self-modification pipeline

- **Owner:** `probos.cognitive.self_mod.SelfModificationPipeline`
- **Configured when:** `self_mod.enabled`
- **Catalog binding:** none declared
- **Notes:** Capability-gap driven agent and skill design. Ships default-OFF, so a shipped-but-disabled row here is correct rather than a defect.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `infrastructure.snapshot-manifest` — Snapshot manifest

- **Owner:** `probos.infrastructure.snapshot_manifest.SnapshotManifest`
- **Configured when:** `ship_state_snapshot.enabled`
- **Catalog binding:** none declared
- **Related seams:** `TA-P0-006-snapshot-restore-read`
- **Notes:** Attests what a snapshot contains. A snapshot whose manifest is absent is not restorable, which is why this is declared rather than assumed from the presence of the backup service.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `tools.code-execution` — Governed code execution

- **Owner:** `probos.tools.code_execution_tool.CodeExecutionTool`
- **Configured when:** always (unconditional in the profile)
- **Catalog binding:** `run_python` on the `tools` axis
- **Notes:** Catalog-bound: the advertised axis resolves this against the live capability catalog rather than against its own declaration.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)

### `tools.governed-invocation` — Governed tool invocation

- **Owner:** `probos.tools.registry.ToolRegistry`
- **Configured when:** always (unconditional in the profile)
- **Catalog binding:** none declared
- **Related seams:** `TA-P0-002-tool-fault-repair`
- **Notes:** The ship-wide tool asset catalog and the permission surface every governed invocation passes through.
- **Resolution notes:**
  - advertised: no runtime attached (offline projection)
