# Contributing

ProbOS is open source under the Apache License 2.0. Contributions are welcome!

## Getting Started

```bash
# Clone and install
git clone https://github.com/seangalliher/ProbOS.git
cd ProbOS
uv sync

# Run the test suite
uv run pytest tests/ -v
```

## Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the test suite — all tests must pass
5. Submit a pull request

## Code Style

- Python 3.12+ with type annotations
- Async-first — most interfaces are `async`
- Pydantic for configuration and data models
- `pytest` + `pytest-asyncio` for testing
- `encoding="utf-8"` on all `open()` calls
- `asyncio.create_task()` over `asyncio.ensure_future()`

## Engineering Principles

All contributions must adhere to the **ProbOS Principles Stack**. Pull requests that introduce violations will be flagged during review.

### Structure — SOLID

| Principle | Rule | ProbOS Example |
|-----------|------|----------------|
| **Single Responsibility** | One reason to change per class. No god objects. | New services get their own module — don't add methods to `runtime.py`. |
| **Open/Closed** | Extend via public APIs, not private member patching. | Never `obj._private_attr = value`. Define a public setter or constructor parameter. |
| **Liskov Substitution** | Subtypes must honor base contracts. | Any `CognitiveAgent` subclass must work wherever the base is expected. |
| **Interface Segregation** | Depend on narrow `typing.Protocol` interfaces, not entire classes. | An agent needing episodic memory depends on `EpisodicMemoryProtocol`, not all of `ProbOSRuntime`. |
| **Dependency Inversion** | Depend on abstractions, inject via constructor. | Services receive dependencies at construction — never reach into a runtime god object. |

### Communication — Law of Demeter

A method should only call methods on: (a) itself, (b) its parameters, (c) objects it creates, (d) its direct dependencies. Never chain through objects: `self.thing._internal_thing.do_stuff()`.

If two services need to be wired together, define a public API on the target service.

### Reliability — Fail Fast

Errors should be detected and reported as close to their origin as possible. Three tiers:

| Tier | When | Pattern |
|------|------|---------|
| **Swallow** | Truly non-critical: shutdown cleanup, telemetry, rebuildable indexes | `except Exception: pass` |
| **Log-and-degrade** | System continues but capability is reduced | `except Exception: logger.debug("...", exc_info=True)` |
| **Propagate** | Caller must know: security boundaries, data integrity | `raise` or re-raise |

**Default to log-and-degrade.** Every `except Exception: pass` must be justified.

### Security — Defense in Depth

- Validate at **every** boundary, not just the edge
- Input sanitization at the API layer **and** the service layer
- Database constraints enforced by the engine (`PRAGMA foreign_keys = ON`), not just application code
- File path operations must sanitize against traversal (no `../` escape from data directories)
- Never assume the caller already checked

### Efficiency — DRY

- Search for existing implementations before writing new ones
- If the same logic exists in 2+ places, extract to a shared utility (`src/probos/utils/`)
- This applies to patterns too — if 6 SQLite modules do the same migration dance, that's a shared helper

### Cloud-Ready Storage

New database modules must use an abstract connection interface rather than calling `aiosqlite.connect()` directly. This enables the commercial overlay to swap storage backends (SQLite → Postgres) without modifying business logic.

- OSS: SQLite implementation (embedded, zero config, single-ship)
- Commercial: Managed database services for multi-tenant cloud deployment

This principle ensures the OSS core remains deployable as a standalone application while supporting cloud-native scaling in the commercial product.

### Testing Standards

- **Framework**: pytest + pytest-asyncio. Prefer `_Fake*` stub classes over complex mock chains.
- **Coverage**: All new public methods and branches must have tests. Target 100% coverage on new code.
- **Test structure**: Arrange-Act-Assert. One behavior per test. Name tests: `test_{method}_{scenario}_{expected}`.
- **Boundary testing**: Every public method needs at minimum: happy path, error/edge case, and empty/None input where applicable.
- **Isolation**: Tests must not depend on execution order. No shared mutable state. Each test creates its own fixtures.
- **Cleanup**: Tests must clean up resources (temp files, tasks, DB entries). Use `tmp_path`, `try/finally`, or context managers.
- **API endpoints**: Minimum 3 tests per endpoint — happy path, error case, input validation.
- **UI changes**: Every TypeScript/React change requires a Vitest component test.

### Type Annotation Standards

- All public methods and properties must have full type annotations (parameters + return type).
- When a class implements a `typing.Protocol`, its method signatures must match exactly.
- Use modern syntax: `X | None` over `Optional[X]`, `list[str]` over `List[str]` (Python 3.10+).
- Internal `_private` methods: annotations recommended but not required.

### Logging Standards

Every log message must include **what** failed, **why** it matters, and **what happens next**.

```python
# Bad
logger.warning("error")

# Good
logger.warning("Template %s not found in spawner; falling back to default", template_name)
```

| Level | When |
|-------|------|
| `debug` | Internal state useful during development only |
| `info` | System lifecycle events (startup, shutdown, agent spawned) |
| `warning` | Degraded operation — failed but compensated |
| `error` | Operation failed, user impact, requires investigation |
| `exception` | Same as error but with traceback — use inside `except` blocks |

No bare `print()` for operational output — use `logger`. No sensitive data (API keys, tokens) in logs.

### Async Discipline

- Use `asyncio.get_running_loop()`, never `get_event_loop()`.
- Use `asyncio.create_task()`, never `asyncio.ensure_future()`.
- Always hold a reference to created tasks — fire-and-forget silently swallows exceptions.
- Long-running async methods must catch `asyncio.CancelledError`, clean up, and re-raise.
- Use `async with` for resources that need async teardown. `start()` implies `stop()`.

### Import & Module Standards

- Lower layers must not import from higher layers.
- Use `TYPE_CHECKING` guard for type-only imports that would create cycles.
- Import order: stdlib → third-party → local, separated by blank lines.
- Never use `from module import *`.

### Configuration Standards

- New config must use Pydantic models in `config.py`. No raw dicts or ad-hoc env var parsing.
- Every config field must have a sensible default (zero-config startup).
- Use Pydantic validators — invalid config should fail at startup, not at runtime.

## Architecture Guidelines

- **Three capability tiers: Agents, Tools, Skills.** Agents are the unit of behavior (crew members who think and decide). Tools are the unit of action (instruments like tricorders — typed callables shared across agents). Skills are the unit of knowledge (data access attached to agents). Rule of thumb: if someone would ask for it, it's an agent. If it performs a specific action any agent might need, it's a tool. If an agent needs reference data to do its job, it's a skill.
- **Self-describing agents.** Every agent declares `IntentDescriptor` metadata so the system discovers it automatically.
- **Consensus for side effects.** Any operation that modifies external state must go through the consensus layer.
- **Test everything.** Each layer has comprehensive tests. New code should maintain coverage.

## Dependencies

| Package | Purpose |
|---------|---------|
| [pydantic](https://docs.pydantic.dev/) >=2.0 | Configuration validation |
| [pyyaml](https://pyyaml.org/) >=6.0 | YAML config loading |
| [aiosqlite](https://github.com/omnilib/aiosqlite) >=0.19 | Async SQLite |
| [rich](https://rich.readthedocs.io/) >=13.0 | Terminal UI |
| [httpx](https://www.python-httpx.org/) >=0.27 | HTTP client |
| [pyzmq](https://pyzmq.readthedocs.io/) >=27.1 | ZeroMQ transport |
| [chromadb](https://docs.trychroma.com/) >=1.0 | Vector database |
| [fastapi](https://fastapi.tiangolo.com/) >=0.115 | API server |
| [uvicorn](https://www.uvicorn.org/) >=0.34 | ASGI server |

Dev: pytest >=8.0, pytest-asyncio >=0.23, vitest (UI)

## Windows Development

ProbOS is developed primarily on Windows. A few environment setup steps are needed:

### Prerequisites

- **Python 3.12+** via [uv](https://docs.astral.sh/uv/) (recommended) or standalone install
- **Git for Windows** — ensure `git` is on your system PATH (`where git` should resolve)
- **Node.js 18+** — for the HXI/UI layer (`ui/`)

### Shell Setup

`uv` installs to `~/.local/bin` which isn't on the default PATH for either shell. Add it to your profile:

**PowerShell** (recommended) — create/edit `$PROFILE`:
```powershell
# ProbOS developer environment
$env:PATH += ";$env:USERPROFILE\.local\bin"
```

**Git Bash** — create/edit `~/.bashrc`:
```bash
# ProbOS developer environment
export PATH="$PATH:/c/Users/$USER/.local/bin"
```

Open a new terminal after saving for changes to take effect.

### Known Platform Notes

| Issue | Cause | Workaround |
|-------|-------|------------|
| `uv: command not found` in bash | uv installs to `~/.local/bin` which isn't on Git Bash's default PATH | Add to `~/.bashrc` (see above) |
| `asyncio.to_thread()` hangs during shutdown | Windows `SelectorEventLoop` (required for pyzmq) has limited threading support | BF-011/BF-012: async polling replaces `to_thread` in shutdown paths |
| `echo` not found in subprocess tests | `echo` is a CMD builtin, not an executable on Windows | Tests mock subprocess calls (AD-404) |
| `pip` not found | uv manages its own Python; system pip may not exist | Use `uv run pip` or `.venv/Scripts/pip3.exe` |

### Event Loop

ProbOS uses `WindowsSelectorEventLoopPolicy` on Windows because pyzmq's `add_reader()` requires it (ProactorEventLoop doesn't support this). This means `asyncio.subprocess` and `asyncio.to_thread()` have limitations. Production code should use `threading.Thread` + `asyncio.sleep()` polling for subprocess operations that may block.
