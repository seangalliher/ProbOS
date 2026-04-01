# ProbOS — Progress Tracker

## Current Status: AD-531 (Episode Clustering & Pattern Detection) CLOSED. Cognitive JIT MVP begins. 4,549+ tests passing (4,400+ pytest + 149 vitest).

---

## Development Eras

| Era | Phases | Codename | Status |
|-----|--------|----------|--------|
| [**Era I: Genesis**](progress-era-1-genesis.md) | 1-9 | Building the Ship | Complete |
| [**Era II: Emergence**](progress-era-2-emergence.md) | 10-21 | The Ship Comes Alive | Complete |
| [**Era III: Product**](progress-era-3-product.md) | 22-29 | The Ship Sets Sail | Complete |
| [**Era IV: Evolution**](DECISIONS.md) | 30 | The Ship Evolves | Active |
| Era V: Civilization | 31-36 | The Ship Becomes a Society | Planned |

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

See [roadmap.md](docs/development/roadmap.md#design-principles) for full design principles:
- "Brains are Brains" (Nooplex core principle)
- Agent Development Model (Communication + Simulation)
- HXI Self-Sufficiency, Agent-First Design, Cockpit View
- Probabilistic Agents, Consensus Governance
- Agent Classification Framework (Core / Utility / Domain)
- Foundational Governance Axioms (Safety Budget, Reversibility, Minimal Authority)

---

## Environment

- **Platform:** Windows 11 Pro (10.0.26200)
- **Python:** 3.12.13 (installed via uv)
- **Toolchain:** uv 0.10.9
- **Key deps:** pydantic 2.12.5, pyyaml 6.0.3, aiosqlite 0.22.1, httpx 0.28+, rich 13.0+, chromadb 1.5.4, pytest 9.0.2, pytest-asyncio 1.3.0, pytest-xdist 3.8.0, pytest-timeout 2.4.0
- **LLM endpoints:** Fast tier: Ollama at `http://127.0.0.1:11434/v1`, Standard/Deep tier: VS Code Copilot proxy at `http://127.0.0.1:8080/v1`
- **LLM models:** fast=qwen3.5:35b (local Ollama), standard=claude-sonnet-4.6 (Copilot proxy), deep=claude-opus-4.6 (Copilot proxy)
- **Run tests:** `uv run pytest tests/ -v` (sequential) or `uv run pytest -n auto` (parallel, 13x faster)
- **Run fast tests:** `uv run pytest -n auto -m "not slow"` (skip 65 sleep-heavy tests)
- **Run demo:** `uv run python demo.py`
- **Run interactive:** `uv run python -m probos`
