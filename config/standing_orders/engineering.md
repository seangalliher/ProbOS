# Engineering Department Protocols

Standards for all agents in the Engineering department (Builder, Code Reviewer, etc.).

## ProbOS Principles Stack (Standing Order)

All code produced by Engineering department agents MUST comply with these principles. Violations are review blockers.

### SOLID
- **(S) Single Responsibility** — One reason to change per class. No god objects. Extract when classes exceed ~500 lines or ~15 methods.
- **(O) Open/Closed** — Extend via public APIs, not private member patching. Never access `obj._private_attr` from outside the owning class.
- **(L) Liskov Substitution** — Subtypes must honor base contracts.
- **(I) Interface Segregation** — Depend on narrow `typing.Protocol` interfaces, not entire classes.
- **(D) Dependency Inversion** — Constructor injection. Depend on abstractions (protocols), not concretions.

### Additional Principles
- **Law of Demeter** — Don't reach through objects. No `a.b._c` chains.
- **Fail Fast** — Default to log-and-degrade. Three tiers: swallow (non-critical), log-and-degrade (visible degradation), propagate (security/data integrity).
- **Defense in Depth** — Validate at every boundary. Never assume the caller already checked.
- **DRY** — Search for existing implementations before writing new ones.
- **Cloud-Ready Storage** — New DB modules must use an abstract connection interface, not direct `aiosqlite.connect()`.

## Type Annotation Standards

- All public methods must have full type annotations (parameters + return type). No exceptions.
- Use modern syntax: `X | None` not `Optional[X]`, `list[str]` not `List[str]`.
- When implementing a `typing.Protocol`, signatures must match exactly.

## Logging Standards

- Every log message must include what failed, why it matters, and what happens next.
- No bare `logger.warning("error")`. Include structured context.
- No bare `print()` for operational output — use `logger`.
- No sensitive data in logs (API keys, tokens, credentials).

## Async Discipline

- Use `asyncio.get_running_loop()`, never `get_event_loop()`.
- Use `asyncio.create_task()`, never `asyncio.ensure_future()`.
- Always hold a reference to created tasks. Fire-and-forget silently swallows exceptions.
- Long-running methods must catch `asyncio.CancelledError`, clean up, and re-raise.

## Import & Module Standards

- Lower layers must not import from higher layers (Substrate cannot import from Cognitive).
- Use `TYPE_CHECKING` guard for type-only imports that would create cycles.
- Import order: stdlib → third-party → local. No wildcard imports.

## Configuration Standards

- New config must use Pydantic models in `config.py`. No raw dicts or ad-hoc env var parsing.
- Every config field must have a sensible default (zero-config startup).

## Build Pipeline Standards

- Builder output uses `===FILE: path===` for new files and `===MODIFY: path===` with SEARCH/REPLACE blocks for modifications
- SEARCH blocks must match existing code EXACTLY — character-for-character
- Keep SEARCH blocks small — just enough context to be unique
- Order SEARCH/REPLACE pairs top-to-bottom in the file
- Test-gate: run the full test suite after each logical build step. Do not proceed if tests fail.

## Testing Standards

- All new public methods and branches must have tests. Target 100% coverage on new code.
- Follow Arrange-Act-Assert. One behavior per test. Name: `test_{method}_{scenario}_{expected}`.
- Boundary testing: every public method needs happy path, error/edge case, and empty/None input.
- Tests must not depend on execution order. No shared mutable state between tests.
- Tests must clean up resources. Use `tmp_path`, `try/finally`, or context managers.
- API endpoints: minimum 3 tests (happy path, error, input validation).
- Before writing test fixtures, READ the target class `__init__` signature. Only pass arguments `__init__` accepts.
- Every mock must cover ALL attributes accessed in the code path under test.
- Test assertions must match the ACTUAL output format, not a guessed format.
- Use `pytest.mark.asyncio` and `async def test_*` for async methods.

## Code Review Checklist

1. Import correctness — full `probos.*` paths, no layer violations
2. Constructor contracts — only pass args the `__init__` accepts
3. Mock completeness — every accessed attribute has a mock
4. Assertion accuracy — assertions match actual output
5. Pattern adherence — follows existing codebase patterns
6. Scope discipline — no unrequested changes
7. Consensus gates — destructive intents gated
8. Agent contracts — instructions-first, not hardcoded `decide()`
9. Type annotations — all public methods fully typed
10. Logging quality — structured context on all log messages
11. Async hygiene — `create_task` with stored references, cancellation handled
12. Principles compliance — verify against the ProbOS Principles Stack
