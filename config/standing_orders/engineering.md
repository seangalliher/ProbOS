# Engineering Department Protocols

Standards for all agents in the Engineering department (Builder, Code Reviewer, etc.).

## Build Pipeline Standards

- Builder output uses `===FILE: path===` for new files and `===MODIFY: path===` with SEARCH/REPLACE blocks for modifications
- SEARCH blocks must match existing code EXACTLY -- character-for-character
- Keep SEARCH blocks small -- just enough context to be unique
- Order SEARCH/REPLACE pairs top-to-bottom in the file
- Test-gate: run the full test suite after each logical build step. Do not proceed if tests fail.

## Test Writing Rules

- Before writing test fixtures, READ the target class __init__ signature. Only pass arguments __init__ accepts. Do NOT invent keyword arguments.
- Every mock must cover ALL attributes accessed in the code path under test. Trace the method body to find every self.runtime.*, self.console.*, etc. access.
- Test assertions must match the ACTUAL output format of the code being tested, not a guessed format. If you wrote `console.print(f"Uptime: {x}")`, the test must assert that exact string.
- Use `pytest.mark.asyncio` and `async def test_*` for async methods.
- Test validation: the pipeline runs pytest after generating code. Tests must pass for the commit to proceed.

## Code Review Checklist

1. Import correctness -- full `probos.*` paths, no layer violations
2. Constructor contracts -- only pass args the __init__ accepts
3. Mock completeness -- every accessed attribute has a mock
4. Assertion accuracy -- assertions match actual output
5. Pattern adherence -- follows existing codebase patterns
6. Scope discipline -- no unrequested changes
7. Consensus gates -- destructive intents gated
8. Agent contracts -- instructions-first, not hardcoded decide()
