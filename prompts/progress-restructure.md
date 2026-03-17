# AD-292: PROGRESS.md Era Restructuring

## Objective

Split the monolithic `PROGRESS.md` (3,357 lines) into era-based progress files, a separate architectural decisions file, and a slim hub document. No content is deleted — everything is reorganized into logical groupings by development era.

## Era Definitions

| Era | File | Phases | Codename | Theme |
|-----|------|--------|----------|-------|
| I | `progress-era-1-genesis.md` | 1-9 | Genesis | Building the ship |
| II | `progress-era-2-emergence.md` | 10-21 | Emergence | The ship comes alive |
| III | `progress-era-3-product.md` | 22-29 | Product | The ship sets sail |
| IV | `progress-era-4-evolution.md` | 30+ | Evolution | The ship evolves |

## Files to Create

All new files go in the repository root alongside the existing `PROGRESS.md`.

### `DECISIONS.md`

Architectural decisions log. Extract from `PROGRESS.md` lines 1110-2766 (the `## Architectural Decisions Made` section through the end of `### Phase 24c`).

**Header:**
```markdown
# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

---
```

Then paste the entire `## Architectural Decisions Made` section content (all AD entries from AD-1 through the latest). Keep the `##` heading as-is.

### `progress-era-1-genesis.md`

**Content:** Everything related to Phases 1-9 (building the core infrastructure).

**Header:**
```markdown
# Era I: Genesis — Building the Ship

*Phases 1-9: Substrate, Mesh, Consensus, Cognitive, Experience, Scaling, Federation*

This era established ProbOS's core architecture — the seven layers from Substrate to Experience, plus Federation. By the end of Genesis, ProbOS could decompose natural language into intent DAGs, execute them through a self-organizing mesh with consensus governance, learn from experience via Hebbian routing and episodic memory, consolidate during dreaming, and federate across multiple nodes.

---
```

**Sections to include (extract from PROGRESS.md):**

From `## What's Been Built` (lines 7-150):
- `### Substrate Layer (complete)` (lines 9-26)
- `### Mesh Layer (complete)` (lines 28-36)
- `### Consensus Layer (complete)` (lines 38-46)
- `### Cognitive Layer (complete — new in Phase 3a)` (lines 48-56) — the Federation section that's misplaced here
- `### Cognitive Layer (continued)` (lines 58-85)
- `### Experience Layer (complete)` (lines 87-96)
- `### Agents` (lines 98-112)
- `### Runtime` (lines 138-149)

From `## What's Working` (lines 151-1108):
- `### Substrate tests` through `### Scaling tests` — all test sections for Phases 1-9
- Specifically: Substrate tests, Mesh tests, Consensus tests, Runtime integration tests, Cognitive tests, Experience tests, Episodic memory tests, Attention mechanism tests, Cross-request attention tests, Dreaming tests, Workflow cache tests, Introspection tests, Dynamic Intent Discovery tests, Expansion agent tests (Phase 5), Scaling tests, Federation tests
- **Include test sections up through Phase 9**: lines 151-646

From `## Completed Phase Checklist (archive)` (lines 3006-3261):
- Extract all checklist items related to Phases 1-9 only

### `progress-era-2-emergence.md`

**Content:** Everything related to Phases 10-21 (self-modification, learning, intelligence).

**Header:**
```markdown
# Era II: Emergence — The Ship Comes Alive

*Phases 10-21: Self-Modification, QA, Knowledge Store, Tiers, CognitiveAgent, Feedback, Shapley, Correction, Emergent Detection, Semantic Knowledge*

This era gave ProbOS intelligence beyond execution. The system learned to design new agents at runtime, validate them through QA, persist knowledge across sessions, classify agents by tier, attach skills to cognitive agents, learn from human feedback and corrections, detect emergent patterns in its own population dynamics, and build a semantic knowledge layer. By the end of Emergence, ProbOS was not just executing tasks — it was learning, adapting, and self-modifying.

---
```

**Sections to include:**

From `## What's Working`:
- `### Phase 4 Milestone — Achieved` (line 647)
- All test sections for Phases 10-21: Phase 11 tests, Phase 12 tests, SystemQA tests, Phase 14 Knowledge Store tests, Phase 14b ChromaDB tests
- Lines 647-1108

From `## What's Been Built`:
- `### Knowledge Layer` (lines 130-136)

From `## Completed Phase Checklist`:
- Checklist items for Phases 10-21

### `progress-era-3-product.md`

**Content:** Everything related to Phases 22-29 (user-facing product, channels, federation).

**Header:**
```markdown
# Era III: Product — The Ship Sets Sail

*Phases 22-29: Bundled Agents, Distribution, HXI, Channels, Self-Mod Hardening, Medical Team, Codebase Knowledge*

This era transformed ProbOS from a research prototype into a usable product. Bundled agents made it useful on day one, the HXI canvas let users watch cognition in real-time, channel adapters connected ProbOS to Discord, the medical team added self-healing, and the codebase knowledge service gave agents structural self-awareness. By the end of Product, ProbOS was installable, visual, connectable, and self-maintaining.

---
```

**Sections to include:**

From `## What's Built`:
- `### Bundled Agents (new in Phase 22)` (lines 114-122)
- `### Distribution (new in Phase 22)` (lines 124-128)

From `## What's Working`:
- `### Bundled agent tests` (lines 1024-1031)
- `### Distribution tests` (lines 1033-1108)

From `## Completed Phase Checklist`:
- Checklist items for Phases 22+

### `progress-era-4-evolution.md`

**Content:** Placeholder for Phases 30+ (self-improvement pipeline, crew teams at full maturity).

```markdown
# Era IV: Evolution — The Ship Evolves

*Phases 30+: Self-Improvement Pipeline, Security Team, Engineering Team, Operations Team*

This era is where ProbOS begins to evolve itself. Research agents discover capabilities, architect agents spec them, builder agents implement them, QA agents validate them — all with a human approval gate. The crew teams mature from pool groups into fully autonomous departments. The ship doesn't just sail — it upgrades itself.

See [docs/development/roadmap.md](docs/development/roadmap.md) for the crew structure and phase details.

---

*Era IV has not yet begun. This file will be populated as Phases 30+ are built.*
```

## Files to Modify

### `PROGRESS.md`

Replace the entire file with a slim hub document:

```markdown
# ProbOS — Progress Tracker

## Current Status: Phase 27 complete — Phase 24 in progress (1675/1675 tests + 15 Vitest + 11 skipped)

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

## Design Principles

### HXI Self-Sufficiency
[Keep existing content from lines 3263-3273]

### Probabilistic Agents, Consensus Governance
[Keep existing content from lines 3275-3284]

### Agent Classification Framework (Core / Utility / Domain)
[Keep existing content from lines 3286-3330]

### Foundational Governance Axioms
[Keep existing content from lines 3332-3344]

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
```

**Important:** The `## Active Roadmap — Product + Emergence Track` section (lines 2767-3004) is **removed** from PROGRESS.md entirely. This content now lives in `docs/development/roadmap.md` which already has the comprehensive crew-structured roadmap. Do NOT duplicate it into any era file.

### `docs/development/status.md`

Check if this file references PROGRESS.md. If so, update any links to point to the new structure.

### `.github/copilot-instructions.md`

If this file references PROGRESS.md for context, update to mention the era files and DECISIONS.md.

## Content Distribution Rules

1. **Component inventory** ("What's Been Built" tables) → era file matching when the component was built
2. **Test inventories** ("What's Working" test lists) → era file matching when the tests were added
3. **Architectural Decisions** (AD-*) → `DECISIONS.md` (all in one file, append-only)
4. **Active Roadmap** → removed, already covered by `docs/development/roadmap.md`
5. **Completed Phase Checklist** → split across era files as a "Milestones" section at the bottom of each
6. **Design Principles** → stay in `PROGRESS.md` hub (they're cross-cutting, not era-specific)
7. **Environment** → stays in `PROGRESS.md` hub

## Phase-to-Era Mapping

For clarity on which phases go in which era:

**Era I: Genesis (Phases 1-9)**
- Phase 1: Substrate + Mesh
- Phase 2: Consensus
- Phase 3a: Cognitive core (LLM, decomposer, working memory)
- Phase 3b: Episodic memory, attention, dreaming, workflow cache
- Phase 4: Experience layer (panels, renderer, shell)
- Phase 5: Expansion agents (introspection, directory list, file search, shell command, http fetch)
- Phase 6: Dynamic intent discovery + prompt builder
- Phase 7: Escalation cascade
- Phase 8: Pool scaling
- Phase 9: Federation

**Era II: Emergence (Phases 10-21)**
- Phase 10: Self-modification pipeline
- Phase 11: Skills, research, strategy, LLM config
- Phase 12: Live LLM integration
- Phase 13: SystemQA
- Phase 14: Knowledge store + ChromaDB + persistent identity + tiers
- Phase 15: CognitiveAgent + domain-aware skills
- Phase 16: DAG proposal mode
- Phase 17: Dependency resolution
- Phase 18: Feedback-to-learning loop + correction feedback
- Phase 19: Shapley trust attribution
- Phase 20: Emergent behavior detection
- Phase 21: Semantic knowledge layer

**Era III: Product (Phases 22-29)**
- Phase 22: Bundled agents + distribution
- Phase 23: HXI MVP
- Phase 24: Channel integration (Discord, task scheduler)
- Phase 25-29: Persistent tasks, deliberation, meta-learning, federation, medical team, codebase knowledge
- Self-mod hardening (AD-262 through AD-273)
- AD-289: Performance optimization
- AD-290: Medical team + codebase knowledge
- AD-291: Pool groups

## Constraints

- **No content deletion** — every line from PROGRESS.md must appear in exactly one output file
- **No duplication** — content appears in only one place (exception: the status line in PROGRESS.md hub)
- **Preserve formatting** — tables, code blocks, and markdown structure must be maintained exactly
- **AD entries stay together** — all architectural decisions go in DECISIONS.md regardless of which era they belong to. This keeps the AD numbering sequence intact and makes it easy to find any AD by number
- **The Active Roadmap section is removed, not moved** — it's already superseded by docs/development/roadmap.md

## Success Criteria

- `PROGRESS.md` is under 150 lines (hub + design principles + environment)
- Each era file has a clear header with era number, codename, theme, and phase list
- `DECISIONS.md` contains all AD entries in original order
- `git diff --stat` shows the original PROGRESS.md line count distributed across the new files
- No content is lost — `wc -l` across all output files should approximately equal the original 3,357 lines
- All internal markdown links still work
- The builder copilot-instructions.md is updated if it references PROGRESS.md
