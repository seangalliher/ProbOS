# Engineering Principles (Standing Order)

Index and authority: `.github/copilot-instructions.md`, section Building: Engineering Principles.

### SOLID Principles

- **(S) Single Responsibility**: One reason to change per class. No god objects. Extract focused modules when classes exceed ~500 lines or ~15 methods.
- **(O) Open/Closed**: Extend via public APIs, not private member patching. Never access `obj._private_attr` from outside the owning class. If you need to modify behavior, define a public method on the target.
- **(L) Liskov Substitution**: Subtypes must honor base contracts. If `BaseAgent` defines `act()`, every subclass must implement it compatibly.
- **(I) Interface Segregation**: Depend on narrow `typing.Protocol` interfaces, not entire classes. Consumers should only see the methods they use.
- **(D) Dependency Inversion**: Constructor injection. Depend on abstractions (protocols), not concretions. New services should accept dependencies as parameters, not import and instantiate them internally.

### Additional Engineering Principles

- **Law of Demeter**: Don't reach through objects. No `a.b._c` chains. If wiring is needed, define a public API on the target.
- **Fail Fast**: Default to log-and-degrade. Three tiers for exception handling:

  | Tier | When | Pattern |
  |------|------|---------|
  | Swallow | Non-critical, no user impact | `except: pass` (rare, must justify) |
  | Log-and-degrade | Visible degradation acceptable | `except: logger.warning(...); return fallback` |
  | Propagate | Security, data integrity, safety | `except: logger.error(...); raise` |

- **Defense in Depth**: Validate at every boundary. Input sanitization at API AND service layers. Never assume the caller already checked.
- **DRY**: Search for existing implementations before writing new ones. If same logic exists in 2+ places, extract it.
- **Cloud-Ready Storage**: New database modules must use an abstract connection interface (`typing.Protocol`), not direct `aiosqlite.connect()`. This enables the commercial overlay to swap storage backends (SQLite → Postgres) without changing business logic.

### Coding Standards

- Follow existing patterns. Check how similar things are already done before inventing new approaches.
- New agents must follow the `perceive -> decide -> act -> report` lifecycle. CognitiveAgent subclasses use `instructions`-first design.
- Destructive intents must set `requires_consensus=True` in their IntentDescriptor.
- Store raw trust parameters `(alpha, beta)`, never derived mean scores. Derived scores lose the full Beta distribution information.
- Restored designed agent code must pass `CodeValidator` validation before `importlib` loading. No exceptions on warm boot.

### Testing Standards

- **Framework**: pytest + pytest-asyncio. Prefer `_Fake*` stub classes over complex mock chains. Test files mirror source paths.
- **Test gates**: The Builder runs focused tests for the changed slice and its immediate consumers after each milestone, with the focused command below; the orchestrator's gates are in `.github/agents/orchestrator.agent.md` (**Gate, Batch and Push**).
- **Mutation testing is targeted, not routine (Captain, 2026-08-25)**: use it when acceptance criteria demand it, when scoped review raises a test-validity concern ordinary regression tests cannot settle, or for Critical/High-risk behaviour. Do not run routine mutation campaigns.
  - Run the unmutated baseline FIRST and abort if it is already red, or every mutant looks killed.
  - Mutate **in place** with a `.mutbak` sibling and restore in `finally`. A copied tree is inert under an editable install.
  - **Single-line anchors only** — this is a CRLF tree and multi-line anchors silently match nothing. An anchor that is not found is an INERT mutant, not a killed one; say so.
  - Classify a timeout banner as **INVALID, never SURVIVED**: a run that never completed proves nothing.
  - **A surviving mutant may mean the MUTANT is wrong, not the test.** Measured twice this session: a mutant that dropped a `<redacted>@` marker rather than the stripping itself, and one whose subclass was rejected by an earlier gate so the bound under test was never reached. Before concluding a test is weak, check that the mutant actually reaches the behaviour it claims to break.
  - **One campaign per candidate.** When a build contract pins byte-exact files and carries its author's executed mutation table for them, a Builder whose base tree and file hashes match does not repeat the campaign; it reruns only the mutants whose files differ, or those a review's test-validity concern names. Measured 2026-10-05 (#1135 slice 2a): repeating it on byte-identical files cost the Builder about 50 minutes across two rounds.
- **Run focused tests with**: `d:/ProbOS/.venv/Scripts/pytest.exe <test-files-or-node-ids> -q -n 0 -p no:randomly`
- **Coverage rule**: All new public methods and branches must have tests. Target 100% coverage on new code — gaps require justification.
- **Test structure**: Follow Arrange-Act-Assert. Each test should verify one behavior. Name tests descriptively: `test_{method}_{scenario}_{expected}` (e.g., `test_get_template_missing_key_returns_none`).
- **Boundary testing**: Every public method must test at minimum: (1) happy path, (2) error/edge case, (3) empty/None input where applicable.
- **Test isolation**: Tests must not depend on execution order. No shared mutable state between tests. Each test creates its own fixtures. If a test fails when run alone, it's broken.
- **No test pollution**: Tests must clean up any resources they create (temp files, background tasks, DB entries). Use `tmp_path` fixture for files, `try/finally` or context managers for cleanup.
- **API test requirement**: Every new API endpoint (`api.py`) must have at least 3 tests — happy path, error case, and input validation. Test in `tests/test_distribution.py` or `tests/test_hxi_chat_integration.py`.
- **UI test requirement**: Every UI change (TypeScript/React) must include a Vitest component test. The HXI has broken from untested UI changes multiple times — tooltips, bloom position, chat rendering. No UI PR without tests.
- **UI tests run with**: `cd ui && npx vitest run` (when Vitest is set up)

### Type Annotation Standards

- **Public API rule**: All public methods and properties must have full type annotations (parameters + return type). No exceptions.
- **Protocol compliance**: When a class structurally implements a `typing.Protocol`, its method signatures must match exactly — annotate to prove it.
- **Use modern Python typing**: `X | None` over `Optional[X]`, `list[str]` over `List[str]` (Python 3.10+ syntax). Use `from __future__ import annotations` in modules with complex types.
- **Internal methods**: Type annotations recommended but not required on private (`_method`) internals.

### Logging Standards

- **Structured context**: Every log message must include *what* failed, *why* it matters, and *what happens next*. Bad: `logger.warning("error")`. Good: `logger.warning("Template %s not found in spawner; falling back to default", template_name)`.
- **Log levels**:

  | Level | When |
  |-------|------|
  | `debug` | Internal state useful during development only |
  | `info` | System lifecycle events (startup, shutdown, agent spawned, pool created) |
  | `warning` | Degraded operation — something failed but the system compensated |
  | `error` | Operation failed, user impact, requires investigation |
  | `exception` | Same as error but with traceback — use inside `except` blocks |

- **No bare `print()`**: Use `logger` for all operational output. `print()` is only for CLI/shell user-facing output.
- **No sensitive data in logs**: Never log API keys, tokens, full file contents, or user credentials.

### Async Discipline

- Always use `asyncio.get_running_loop()`, never `get_event_loop()`.
- **Task references**: Always hold a reference to tasks created with `asyncio.create_task()`. Fire-and-forget tasks silently swallow exceptions and can be garbage collected. Store in a set or instance variable and remove on completion.
- **Never use `asyncio.ensure_future()`** — use `asyncio.create_task()`. `ensure_future` is ambiguous about whether it receives a coroutine or future.
- **Cancellation handling**: Long-running async methods should catch `asyncio.CancelledError`, perform cleanup, and re-raise. Never swallow cancellation.
- **Async context cleanup**: Use `async with` for resources that need async teardown. If a class has `async def start()`, it must have `async def stop()` with corresponding cleanup.

### Import & Module Standards

- **Layer discipline**: Lower layers must not import from higher layers (Substrate cannot import from Cognitive). Cross-cutting modules (`federation/`, `knowledge/`, `runtime.py`) may import from any layer.
- **Circular import prevention**: Use `TYPE_CHECKING` guard for type-only imports that would create cycles:
  ```python
  from __future__ import annotations
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from probos.runtime import ProbOSRuntime
  ```
- **Import order**: stdlib → third-party → local, separated by blank lines. Tools like `isort` conventions.
- **No wildcard imports**: Never use `from module import *`. Always import specific names.

### Configuration Standards

- **Pydantic models only**: New configuration must be added to the existing Pydantic models in `config.py`. Never read config from raw dicts, environment variables, or ad-hoc YAML parsing.
- **Defaults required**: Every config field must have a sensible default so ProbOS runs out of the box with zero configuration.
- **Validation at parse time**: Use Pydantic validators. Invalid config should fail at startup, not at runtime when the feature is first used.
