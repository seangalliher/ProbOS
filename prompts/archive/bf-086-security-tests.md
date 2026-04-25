# BF-086: Security Tests for code_validator.py and sandbox.py

## Problem

`CodeValidator` and `SandboxRunner` are security-critical modules handling agent self-modification — they decide what code agents are allowed to write and execute. Despite this, they have no dedicated test files. Existing coverage lives inside `test_self_mod.py` with 16 validator tests and 3 sandbox tests, but these only cover the happy path and basic rejections. Critical bypass vectors are untested.

## Files Under Test

- `src/probos/cognitive/code_validator.py` (252 lines)
- `src/probos/cognitive/sandbox.py` (179 lines)
- Default config: `src/probos/cognitive/self_mod.py` → `SelfModConfig` (for default patterns/imports)

## Part 1: CodeValidator Security Tests

Create `tests/test_code_validator_security.py`. All tests use `CodeValidator(SelfModConfig())` with default config — test the actual security boundary, not a weakened mock.

### A. Import Whitelist Tests

```
test_blocks_requests_import           — `import requests` → error
test_blocks_httpx_import              — `import httpx` → error
test_blocks_aiohttp_import            — `from aiohttp import ClientSession` → error
test_blocks_importlib_import          — `import importlib` → error
test_blocks_sys_import                — `import sys` → error
test_blocks_ctypes_import             — `import ctypes` → error
test_blocks_pickle_import             — `import pickle` → error
test_blocks_marshal_import            — `import marshal` → error
test_blocks_code_import               — `import code` → error (interactive interpreter)
test_blocks_compileall_import         — `import compileall` → error
test_allows_probos_internal_imports   — `from probos.types import IntentResult` → pass
test_allows_probos_substrate_import   — `from probos.substrate.agent import BaseAgent` → pass
test_blocks_from_x_import_y_syntax   — `from subprocess import Popen` → error
test_blocks_dotted_forbidden_import   — `import subprocess.Popen` → error
```

### B. Forbidden Pattern Bypass Tests

These test known bypass vectors that the current patterns may NOT catch. If a test reveals a gap, fix the pattern — don't weaken the test.

```
test_blocks_os_system                 — `os.system("ls")` in agent code → error
                                        (os is whitelisted but os.system is command execution)
                                        NOTE: If this PASSES validation (no error), it's a real
                                        security gap. Add `r"os\.system"` to forbidden patterns
                                        and document in the test.

test_blocks_os_popen                  — `os.popen("ls")` → error
                                        Same vector as os.system. Add pattern if missing.

test_blocks_os_execv                  — `os.execv("/bin/sh", [])` → error
                                        Process replacement. Add pattern if missing.

test_blocks_os_kill                   — `os.kill(1, 9)` → error
                                        Signal injection. Add pattern if missing.

test_blocks_pathlib_write_text        — `Path("/tmp/x").write_text("pwned")` → error
                                        pathlib is whitelisted. Add pattern if missing:
                                        `r"\.write_text\s*\("` and `r"\.write_bytes\s*\("`

test_blocks_pathlib_unlink            — `Path("/tmp/x").unlink()` → error
                                        File deletion via pathlib. Add pattern if missing.

test_blocks_open_append_mode          — `open("/tmp/x", "a")` → error
                                        Current pattern only matches 'w'. Extend to catch
                                        'a', 'w+', 'x', 'wb', 'ab', 'xb' modes.
                                        Suggested pattern: r"open\s*\(.*['\"][waxWAX]"

test_blocks_open_binary_write         — `open("/tmp/x", "wb")` → error

test_blocks_tempfile_write            — `tempfile.NamedTemporaryFile(mode='w')` in code → error
                                        tempfile is whitelisted. Add pattern if missing.

test_blocks_getattr_eval_bypass       — `getattr(__builtins__, 'eval')("1+1")` → error
                                        Pattern evasion via getattr. Add `r"getattr\s*\(" to
                                        forbidden patterns OR `r"__builtins__"`.

test_blocks_builtins_access           — `__builtins__.__import__("os")` → error
                                        Already caught by `__import__` pattern — verify.

test_blocks_compile_builtin           — `compile("code", "<>", "exec")` → error
                                        Code compilation. Add `r"compile\s*\("` if missing.

test_pattern_in_comment_false_positive — `# don't use eval() here` in a comment
                                        Current text-based pattern WILL match this. Document
                                        as known limitation (acceptable false positive for
                                        security). This test should verify the current behavior
                                        and add a comment explaining the trade-off.

test_pattern_in_string_false_positive  — `msg = "use eval() carefully"` in string literal
                                        Same trade-off. Document.
```

### C. Schema Enforcement Tests

```
test_nested_class_evasion             — Agent class defined inside a function:
                                        `def factory(): class Evil(BaseAgent): ...`
                                        Should this be caught? Currently module-level scan only.
                                        Document behavior either way.

test_aliased_base_class               — `B = BaseAgent; class MyAgent(B): ...`
                                        Verify schema check handles (or explicitly rejects) this.

test_no_class_at_all                  — Source with only functions, no class → error

test_class_without_base               — `class MyAgent: ...` (no BaseAgent inheritance) → error

test_agent_type_as_annotation         — `agent_type: str = "test"` (AnnAssign) → pass

test_intent_descriptors_as_dict       — `intent_descriptors = [{"intent": "test"}]` → pass

test_handled_intents_missing          — All required attributes except `_handled_intents` → error
```

### D. Side Effect Tests

```
test_module_level_function_call       — `setup()` at module level → error
test_module_level_if_statement        — `if True: pass` at module level → error
test_module_level_for_loop            — `for i in range(10): pass` at module level → error
test_class_body_conditional           — `if DEBUG: print()` in class body → error
test_class_body_assignment_ok         — `_cache = {}` in class body → pass
test_class_body_annotated_ok          — `name: str = "test"` in class body → pass
test_class_body_method_ok             — `async def handle_intent(...)` in class body → pass
```

## Part 2: SandboxRunner Security Tests

Create `tests/test_sandbox_security.py`.

### A. Execution Boundary Tests

```
test_valid_agent_succeeds             — Valid minimal agent → SandboxResult(success=True)
test_syntax_error_fails               — Broken syntax → SandboxResult(success=False)
test_no_agent_class_fails             — Module with no BaseAgent subclass → success=False
test_wrong_return_type_fails          — handle_intent returns string (not IntentResult) → success=False
test_timeout_enforced                 — Agent sleeps 999s, timeout=0.1 → success=False, "timed out"
test_exception_in_handle_intent       — Agent raises ValueError → success=False
test_exception_in_init                — Agent __init__ raises → success=False
test_execution_time_measured          — result.execution_time_ms > 0 on success
test_temp_file_cleaned_up             — After test_agent(), verify no temp files left in tempdir
test_module_removed_from_sys_modules  — After test_agent(), verify no `_probos_sandbox_*` in sys.modules
```

### B. Agent Class Discovery Tests

```
test_finds_base_agent_subclass        — Module with BaseAgent subclass → found
test_finds_cognitive_agent_subclass   — Module with CognitiveAgent subclass → found
test_skips_base_agent_itself          — Module that only defines BaseAgent (import) → not found
test_skips_cognitive_agent_itself     — Same for CognitiveAgent
test_requires_intent_descriptors      — Subclass without intent_descriptors → not found → success=False
```

### C. Integration with CodeValidator

```
test_validator_then_sandbox_pipeline  — Valid code passes validator, then passes sandbox
test_validator_rejects_sandbox_skipped — Invalid code fails validator; sandbox never called
```

## Part 3: Fix Security Gaps Found

If any bypass test reveals a gap (code passes validation when it shouldn't), fix it immediately:

1. Add the missing forbidden pattern to `SelfModConfig._DEFAULT_FORBIDDEN_PATTERNS` in `src/probos/cognitive/self_mod.py`
2. Verify the fix makes the test pass
3. Document the gap and fix in the test docstring

**Expected gaps to fix (based on analysis):**

| Gap | Vector | Fix |
|-----|--------|-----|
| `os.system` | Command execution | Add `r"os\.system"` |
| `os.popen` | Command execution | Add `r"os\.popen"` |
| `os.execv` / `os.exec*` | Process replacement | Add `r"os\.exec"` |
| `os.kill` | Signal injection | Add `r"os\.kill"` |
| `Path.write_text/write_bytes` | File mutation via pathlib | Add `r"\.write_text\s*\("`, `r"\.write_bytes\s*\("` |
| `Path.unlink` | File deletion via pathlib | Add `r"\.unlink\s*\("` |
| `open(..., 'a')` | Append mode not caught | Broaden pattern: `r"open\s*\(.*['\"][waxWAX]"` |
| `getattr(__builtins__, ...)` | Dynamic builtin access | Add `r"__builtins__"` |
| `compile()` | Code compilation | Add `r"compile\s*\("` |

**Important:** Adding patterns to `_DEFAULT_FORBIDDEN_PATTERNS` may cause existing tests in `test_self_mod.py` to need updates if their valid agent fixtures use any of these patterns. Check and update accordingly.

## Constraints

1. **Mock discipline** — use `spec=SelfModConfig` where mocking config. Most tests should use the real `SelfModConfig()` default — we're testing the actual security boundary.
2. **No behavior changes** to valid code paths — only tighten rejection of invalid/dangerous patterns.
3. **Document known limitations** — text-based pattern matching has inherent false positives (comments, strings). This is an acceptable trade-off documented in tests.
4. **Exception handler logging** — any new exception handlers must use `warning` or higher, never `debug`.

## Validation

1. All existing tests pass: `pytest tests/test_self_mod.py tests/test_agent_designer_cognitive.py -x -q`
2. New security tests pass: `pytest tests/test_code_validator_security.py tests/test_sandbox_security.py -x -q`
3. Full suite: `pytest tests/ -x -q`
4. Count the gaps found and fixed — document in commit message

## Reference

- `src/probos/cognitive/code_validator.py` (252 lines) — static analysis validator
- `src/probos/cognitive/sandbox.py` (179 lines) — functional correctness runner
- `src/probos/cognitive/self_mod.py` — `SelfModConfig` with default patterns/imports
- Existing tests: `tests/test_self_mod.py` (TestCodeValidator: 16 tests, TestSandboxRunner: 3 tests)
- Code review finding #14: "Add security tests for code_validator.py and sandbox.py — These are security-critical with zero dedicated tests."
