# ProbOS — Progress Tracker

## Current Status: AD-371 complete — BuildQueue + WorktreeManager (AD-371), SIF (AD-370), BF-004 closed

---

## Development Eras

| Era | Phases | Codename | Status |
|-----|--------|----------|--------|
| [**Era I: Genesis**](progress-era-1-genesis.md) | 1-9 | Building the Ship | Complete |
| [**Era II: Emergence**](progress-era-2-emergence.md) | 10-21 | The Ship Comes Alive | Complete |
| [**Era III: Product**](progress-era-3-product.md) | 22-29 | The Ship Sets Sail | In Progress |
| [**Era IV: Evolution**](progress-era-4-evolution.md) | 30+ | The Ship Evolves | Planned |

## Quick Links

- **[Architectural Decisions](DECISIONS.md)** — AD-1 through AD-291+, append-only decision log
- **[Roadmap](docs/development/roadmap.md)** — crew structure, future phases, team details
- **[Project Structure](docs/development/structure.md)** — file tree and module descriptions

## Release Tagging Policy

Tags use the format `v{major}.{minor}.{patch}-phase{N}` (e.g., `v0.4.0-phase29c`).

| Event | Tag? | Example |
|-------|------|---------|
| Phase completed | Yes — bump minor version | `v0.5.0-phase30` |
| Critical bug fix between phases | Yes — bump patch version | `v0.4.1-phase29c` |
| Roadmap/docs-only changes | No | — |
| Mid-phase work (partial features) | No | — |
| First production-ready release | Yes — `v1.0.0` | After security hardening (Phase 31) |

**Current tags:**

| Tag | Commit | Date | Notes |
|-----|--------|------|-------|
| `v0.1.0-phase12` | — | — | End of Era I: Genesis |
| `v0.4.0-phase29c` | `13d52a7` | 2026-03-17 | End of Phase 29c: Codebase Knowledge |

## Design Principles

### HXI Self-Sufficiency

The HXI is the single surface for all ProbOS interaction. A user should never have to leave the HXI to configure, operate, or understand their system. Every capability that exists — channel setup, LLM endpoint configuration, agent management, trust inspection, knowledge browsing, credential storage — must be accessible from within the HXI.

This means:
- **No config file editing required.** YAML config files exist as a persistence format and for advanced/headless use, but the primary path is always through the HXI. A new user should be able to set up Discord integration, configure LLM backends, and manage agent pools entirely from the UI.
- **No external dashboards.** Monitoring, logs, trust scores, episodic memory, workflow cache — all surfaced inside ProbOS, not in separate tools.
- **No context switching.** If ProbOS needs a token, API key, or user decision, it asks within the HXI (or the active channel). The user stays in flow.
- **Slash commands are the keyboard shortcut.** Everything the UI can do, a `/command` can do. Power users stay in the shell; casual users click buttons. Same capabilities, two access patterns.

This principle applies retroactively: as new features ship, their configuration and management surfaces ship with them. A feature without an HXI management surface is incomplete.

### Probabilistic Agents, Consensus Governance

ProbOS must remain probabilistic at its core. There is a critical distinction between **deterministic logic** and **governance**. Agents are not deterministic automata — they are probabilistic entities with Bayesian confidence, stochastic routing (Hebbian weights), and non-deterministic LLM-driven decision-making. Like humans with free will who still follow rules in a society, agents in the ProbOS ecosystem are probabilistic but must still follow consensus.

Consensus is governance, not control. It constrains *outcomes* (quorum approval, trust-weighted voting, red team verification) without constraining the *process* by which agents arrive at those outcomes. An agent may choose how to handle an intent, how confident it is, and what it reports — but destructive actions require collective agreement. This mirrors how societies work: individuals think freely, but shared rules prevent harm.

As ProbOS evolves, every new capability must preserve this principle:
- **Agent behavior stays probabilistic:** Confidence is Bayesian (Beta distributions), routing is learned (Hebbian weights with decay), trust evolves from observations, attention is scored not prescribed, dreaming replays and consolidates stochastically.
- **Governance stays collective:** Consensus is quorum-based (not dictated by a single authority), escalation cascades through tiers, self-modification requires user approval, designed agents start with probationary trust and earn standing through repeated successful interactions.
- **No deterministic overrides:** Avoid hardcoded "always do X" logic. Prefer probabilistic priors that converge toward correct behavior through experience. The system should *learn* what works, not be *told* what works.

### Agent Classification Framework (Core / Utility / Domain)

ProbOS agents belong to one of three architectural tiers. This classification maps directly to the Noöplex's layered architecture (§4): Layer 4 Infrastructure, the Meta-Cognitive Layer (§4.3.3), and Layer 2 Cognitive Meshes (§4.2). The tiers determine routing behavior, governance policy, trust mechanics, and HXI visual rendering. As the agent population grows — especially with Cognitive Agents (Phase 15) and domain meshes — the tier system prevents the flat-pool structure from becoming architecturally incoherent.

**Tier 1: Core (Infrastructure).** Primitive capabilities that everything else builds on. Domain-agnostic, deterministic tool agents. They're the substrate's hands — they touch hardware resources, they're fast, and they're the foundation that all higher-level cognition depends on. In a traditional OS analogy, these are syscalls and device drivers. Every domain mesh uses them. They should never be removed, reorganized, or subordinated to a domain concern. Core agents are always available to all meshes through the shared intent bus.

| Agent | Pool | Intents | Notes |
|-------|------|---------|-------|
| SystemHeartbeatAgent | system | (heartbeat — no user intents) | System rhythm, health monitoring |
| FileReaderAgent | filesystem | read_file, stat_file | |
| FileWriterAgent | filesystem_writers | write_file | Consensus-gated |
| DirectoryListAgent | directory | list_directory | |
| FileSearchAgent | search | search_files | |
| ShellCommandAgent | shell | run_command | Consensus-gated |
| HttpFetchAgent | http | http_fetch | Consensus-gated |
| RedTeamAgent | red_team | (none — invoked directly by consensus pipeline) | Bypasses intent bus (AD-22) |

**Tier 2: Utility (Meta-Cognitive).** System maintenance agents that operate *on* the system, not *for* the user. They monitor, test, and repair. They have access to system internals (trust scores, Hebbian weights, episodic memory stats, agent rosters) that domain agents shouldn't need. They're governed by system-level policies. In the Noöplex, this corresponds to the Meta-Cognitive Layer (§4.3.3): "the system with the ability to reason about its own reasoning — to monitor, evaluate, and direct the cognitive processes occurring across all meshes."

| Agent | Pool | Intents | Notes |
|-------|------|---------|-------|
| IntrospectionAgent | introspect | explain_last, agent_info, system_health, why | All require reflect. Reads `_runtime` reference |
| SystemQAAgent | system_qa | (triggered by self-mod pipeline, not user intents) | Already excluded from decomposer descriptors (AD-158) |
| SkillBasedAgent | skills | (dynamic — varies by attached skills) | Skill carrier/dispatcher. Transitions to domain tier as skills specialize |

Utility agents are already informally separated: `_EXCLUDED_AGENT_TYPES` excludes `system_qa` and `red_team` from decomposer descriptors, RedTeamAgent bypasses the intent bus, IntrospectionAgent intents all require reflect. Formalizing this with a `tier` field replaces ad-hoc exclusion sets with a consistent architectural rule.

**Tier 3: Domain (Cognitive Meshes).** User-facing cognitive work grouped by domain. Each domain is a mesh — a semi-autonomous cognitive community with its own agents, internal Hebbian routing topology, and accumulated expertise. Domains are where Cognitive Agents (Phase 15) live: analyzer, planner, critic, synthesizer agents with domain-specific `instructions`. Currently, designed agents are the first domain-tier agents, though they're not yet organized into formal meshes.

| Domain (future) | Agent Types | Description |
|-----------------|-------------|-------------|
| (unclassified) | Designed agents | Currently created by self-mod pipeline without domain assignment |
| code_development | analyzer, planner, coder, reviewer | IDE/Copilot integration squad |
| data_analysis | data_loader, statistician, visualizer | Analytical cognitive agents |
| research | searcher, synthesizer, fact_checker | Web research and knowledge gathering |

Domain meshes develop their own internal topologies: intra-mesh Hebbian routing learns which agents within the domain work well together, while inter-mesh routing (at the decomposer level) learns which domains are relevant for which intent types. Both use the same Hebbian mechanism — the architecture is fractal. The same patterns that govern agents within a pool govern meshes within a node, and nodes within a federation.

**Routing implications:** The decomposer becomes tier-aware. User intents route to domain meshes first (which domain handles this?), then to agents within the mesh (which agent?). Domain agents dispatch infrastructure needs (file I/O, shell, HTTP) downward to the core tier through the shared intent bus — they never bypass governance by doing their own I/O. Utility agents are invoked by system triggers (self-mod pipeline, dream cycle, health monitoring), not by user intents.

**Governance implications:** Core agents have system trust — they're always available and start with the default Beta(2,2) prior. Utility agents have elevated system trust — they need access to internals and shouldn't be constrained by user-intent trust dynamics. Domain agents earn trust through the normal Bayesian pathway — probationary trust, observation-based updates, decay toward prior. Domain-specific governance policies (from the roadmapped Formal Policy Engine) can apply per-mesh without affecting other domains.

**HXI implications:** The three tiers render differently in the Cognitive Canvas. Core agents form the substrate layer — always visible, stable, the system's foundation. Utility agents form a distinct cluster — visible but separate from productive work, rendered with a different visual quality (perhaps more muted, monitoring-station aesthetics). Domain meshes are the primary visual focus — luminous, active, where the participant sees cognitive work happening. Each domain mesh is a visually coherent cluster with its own internal topology. The tier classification gives the HXI's spatial composition a natural organizing principle.

**Fractal scaling:** This classification proves the Noöplex's fractal hypothesis at the unit-cell scale. The same architectural patterns (agent pools, Hebbian routing, trust, consensus) organize agents within a mesh, meshes within a node, and nodes within a federation. A domain mesh is governed by the same mechanisms as an agent pool — one level up. The three-tier structure within a single ProbOS node is the same three-tier structure the Noöplex describes across a planetary ecosystem: infrastructure substrate, meta-cognitive oversight, and specialized cognitive communities. The unit cell contains the full pattern.

### Foundational Governance Axioms

Three axioms underpin ProbOS's safety model. Unlike Asimov's Three Laws (which were literary devices designed to demonstrate failure modes of absolute rules in autonomous systems), these axioms are mechanistic, testable, and compatible with probabilistic agency. They constrain *outcomes* without constraining the *process* — agents are still free to reason probabilistically, but the governance layer enforces structural safeguards.

1. **Safety Budget:** Every agent action carries an implicit risk score. Low-risk actions (reads, queries) proceed with normal routing. Higher-risk actions (writes, deletes, shell commands) require proportionally stronger consensus — higher quorum thresholds, trust-weighted voting, red team verification. The safety budget is not a hardcoded gate; it is a continuous score that shifts consensus requirements. As an agent's trust grows, its safety budget widens — but destructive actions always require collective agreement regardless of trust.

2. **Reversibility Preference:** When multiple strategies can achieve a goal, prefer the one whose effects are most reversible. Read before write. Backup before delete. Query before mutate. This is enforced at the decomposer level — the DAG planning stage can order nodes to front-load information-gathering and defer state-changing actions. Reversibility is a planning heuristic, not an absolute prohibition: sometimes irreversible actions are the only path, and the system proceeds after appropriate consensus.

3. **Minimal Authority:** Agents request only the capabilities they need for the current task. The capability mesh already enforces this — agents declare their intents, and the router matches only on declared capabilities. Self-modification extends this: designed agents receive a scoped import whitelist, sandboxed execution, and probationary trust. No agent starts with full system access. Authority is earned through repeated successful interactions, not granted by default.

These axioms are already partially implemented across the existing architecture (consensus quorum, CodeValidator, capability mesh, probationary trust). Phase 11 and beyond should formalize them as explicit, testable properties — not as vague principles, but as measurable invariants with test coverage.

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, chromadb 1.5.4, pytest 9.0.2, pytest-asyncio 1.3.0
- **LLM endpoints:** Fast tier: Ollama at `http://127.0.0.1:11434/v1`, Standard/Deep tier: VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=qwen3.5:35b (local Ollama), standard=claude-sonnet-4.6 (Copilot proxy), deep=claude-opus-4.6 (Copilot proxy)
- **Run tests:** `uv run pytest tests/ -v`
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
