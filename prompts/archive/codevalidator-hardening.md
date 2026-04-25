# AD-327: CodeValidator Hardening

## Context

The `CodeValidator` in `src/probos/cognitive/code_validator.py` has two gaps identified by a GPT-5.4 code review:

1. **Single-agent invariant not enforced** (line 133): `_check_schema()` promises "exactly one class that subclasses BaseAgent or CognitiveAgent" (docstring at line 105), but if the LLM generates code with *multiple* agent classes, it silently picks `agent_classes[0]` and ignores the rest. This means the second agent class is never registered, never tested, and could contain anything — a security gap in the self-mod pipeline.

2. **Class-body side effects unscanned** (line 195): `_check_module_side_effects()` gives `ClassDef` a blanket pass, but class bodies execute at import time. A generated class could contain bare function calls in its body (not inside methods) that execute as side effects when the module is imported. For example: `print("pwned")` or `os.system("rm -rf /")` at class level would bypass the side-effect scanner.

Both fixes are small and surgical.

## Scope

**Target file:**
- `src/probos/cognitive/code_validator.py` — both fixes

**Test file (MODIFY existing):**
- `tests/test_self_mod.py` — add tests to existing `TestCodeValidator` class

**Do NOT change:**
- Any other source files
- Do not create new files
- Do not modify test infrastructure or other test classes
- Do not modify the `validate()` method flow or the other check methods
- Do not change the constructor or config handling

---

## Step 1: Enforce Single-Agent Invariant

**File:** `src/probos/cognitive/code_validator.py`

### 1a: Add multi-agent rejection in `_check_schema()`

After the `if not agent_classes:` check (line 129-131), add a check for too many agent classes:

```python
# BEFORE (lines 129-133):
if not agent_classes:
    errors.append("No BaseAgent subclass found")
    return errors

cls = agent_classes[0]

# AFTER:
if not agent_classes:
    errors.append("No BaseAgent subclass found")
    return errors

if len(agent_classes) > 1:
    names = ", ".join(c.name for c in agent_classes)
    errors.append(
        f"Multiple agent classes found ({names}); "
        f"exactly one BaseAgent subclass is allowed"
    )
    return errors

cls = agent_classes[0]
```

**Design decision:** Return early (like the "no agent" case) rather than continuing validation. If there are multiple agents, the remaining checks would only apply to the first one, which is misleading. Better to reject outright and tell the LLM to regenerate.

---

## Step 2: Scan Class-Body Side Effects

**File:** `src/probos/cognitive/code_validator.py`

### 2a: Recurse into `ClassDef.body` in `_check_module_side_effects()`

Currently `ClassDef` is in the allowed list at line 195. Keep it there (class definitions at module level are fine), but after the main loop, recurse into each class body to check for side effects.

Add a new helper method `_check_class_body_side_effects()` and call it from `_check_module_side_effects()`:

```python
def _check_module_side_effects(self, tree: ast.Module) -> list[str]:
    """Module-level statements must be: imports, class defs, function defs,
    assignments, or string expressions (docstrings).

    Bare function calls, loops, or conditionals at module level are errors.
    Class bodies are also scanned for non-method side effects.
    """
    errors: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (
            ast.Import, ast.ImportFrom,
            ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
            ast.Assign, ast.AnnAssign,
        )):
            # ClassDef is allowed at module level, but scan its body
            if isinstance(node, ast.ClassDef):
                errors.extend(self._check_class_body_side_effects(node))
            continue
        # Allow string constants (docstrings)
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant,)):
            if isinstance(node.value.value, str):
                continue
        # Everything else is a side effect
        errors.append(
            f"Module-level side effect at line {node.lineno}: "
            f"{type(node).__name__}"
        )
    return errors

def _check_class_body_side_effects(self, cls: ast.ClassDef) -> list[str]:
    """Scan class body for non-method side effects.

    Allowed in class body:
    - Method definitions (FunctionDef, AsyncFunctionDef)
    - Assignments / annotated assignments (class attributes)
    - String expressions (docstrings)
    - Pass statements

    Bare function calls, loops, conditionals, etc. are side effects
    that execute at import time.
    """
    errors: list[str] = []
    for node in cls.body:
        if isinstance(node, (
            ast.FunctionDef, ast.AsyncFunctionDef,
            ast.Assign, ast.AnnAssign,
            ast.Pass,
        )):
            continue
        # Allow string constants (docstrings)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                continue
        # Everything else is a class-body side effect
        errors.append(
            f"Class-body side effect in '{cls.name}' at line {node.lineno}: "
            f"{type(node).__name__}"
        )
    return errors
```

**Design decisions:**
- `Pass` is explicitly allowed in class bodies (common in stub classes).
- Assignments are allowed — class attributes like `agent_type = "foo"` are not side effects, they're class variable definitions that set up the class namespace.
- Nested classes inside a class body: would be caught as a side effect. This is acceptable — generated agent code should not have nested classes.
- The error message includes the class name for clarity: `"Class-body side effect in 'CountWordsAgent' at line 15: Expr"`.

---

## Step 3: Tests

**File:** `tests/test_self_mod.py`

Add 4 new tests to the existing `TestCodeValidator` class (after test 19 / `test_module_level_side_effect`):

### Test 20: test_multiple_agent_classes_rejected

```python
def test_multiple_agent_classes_rejected(self):
    """Test 20: Multiple BaseAgent subclasses in one file rejected."""
    v = self._make_validator()
    source = textwrap.dedent('''\
        from probos.substrate.agent import BaseAgent
        from probos.types import IntentDescriptor, IntentMessage, IntentResult

        class AgentOne(BaseAgent):
            agent_type = "one"
            _handled_intents = ["one"]
            intent_descriptors = [
                IntentDescriptor(name="one", params={}, description="first")
            ]
            async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                return None

        class AgentTwo(BaseAgent):
            agent_type = "two"
            _handled_intents = ["two"]
            intent_descriptors = [
                IntentDescriptor(name="two", params={}, description="second")
            ]
            async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                return None
    ''')
    errors = v.validate(source)
    assert any("Multiple agent classes" in e for e in errors)
    assert any("AgentOne" in e and "AgentTwo" in e for e in errors)
```

### Test 21: test_class_body_bare_call_detected

```python
def test_class_body_bare_call_detected(self):
    """Test 21: Bare function call in class body detected as side effect."""
    v = self._make_validator()
    source = VALID_AGENT_SOURCE.replace(
        'agent_type = "count_words"',
        'agent_type = "count_words"\n        print("class loaded")',
    )
    errors = v.validate(source)
    assert any("class-body side effect" in e.lower() for e in errors)
```

### Test 22: test_class_body_loop_detected

```python
def test_class_body_loop_detected(self):
    """Test 22: Loop in class body detected as side effect."""
    v = self._make_validator()
    source = VALID_AGENT_SOURCE.replace(
        'agent_type = "count_words"',
        'agent_type = "count_words"\n        for i in range(10): pass',
    )
    errors = v.validate(source)
    assert any("class-body side effect" in e.lower() for e in errors)
```

### Test 23: test_class_body_docstring_allowed

```python
def test_class_body_docstring_allowed(self):
    """Test 23: Docstrings in class body do not trigger side effect error."""
    v = self._make_validator()
    # VALID_AGENT_SOURCE already has a docstring in the class body
    errors = v.validate(VALID_AGENT_SOURCE)
    side_effects = [e for e in errors if "side effect" in e.lower()]
    assert side_effects == []
```

**Total: 4 new tests.**

---

## Step 4: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update: `Phase 32m complete — Phase 32 in progress (NNNN/NNNN tests + 21 Vitest + NN skipped)`

### DECISIONS.md
Append:
```
## Phase 32m: CodeValidator Hardening (AD-327)

| AD | Decision |
|----|----------|
| AD-327 | CodeValidator Hardening — (a) `_check_schema()` now rejects code with multiple `BaseAgent` subclasses (was silently picking first). (b) New `_check_class_body_side_effects()` scans class bodies for bare function calls, loops, and conditionals that execute at import time. Both are early-return patterns consistent with existing validator flow. |

**Status:** Complete — N new Python tests, NNNN Python + 21 Vitest total
```

### progress-era-4-evolution.md
Append:
```
## Phase 32m: CodeValidator Hardening (AD-327)

**Decision:** AD-327 — Multi-agent rejection in `_check_schema()`, class-body side effect scanning via `_check_class_body_side_effects()`.

**Status:** Phase 32m complete — NNNN Python + 21 Vitest
```

---

## Verification Checklist

Before committing, verify:

1. [ ] `_check_schema()` rejects `len(agent_classes) > 1` with error naming all classes
2. [ ] Multi-agent check returns early (like the no-agent check)
3. [ ] `_check_module_side_effects()` calls `_check_class_body_side_effects()` for `ClassDef` nodes
4. [ ] `_check_class_body_side_effects()` allows: FunctionDef, AsyncFunctionDef, Assign, AnnAssign, Pass, docstrings
5. [ ] `_check_class_body_side_effects()` rejects: Expr (bare calls), For, While, If, etc.
6. [ ] Error messages include class name and line number
7. [ ] `VALID_AGENT_SOURCE` still passes validation (no false positives from class-body scan)
8. [ ] All 4 new tests pass
9. [ ] Existing TestCodeValidator tests still pass (no regressions)
10. [ ] Full suite passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
11. [ ] PROGRESS.md, DECISIONS.md, progress-era-4-evolution.md updated

## Anti-Scope (Do NOT Build)

- Do NOT modify the `validate()` method's check order or flow
- Do NOT modify `_check_imports()` or `_check_forbidden_patterns()`
- Do NOT add new config options or constructor parameters
- Do NOT modify any other source files
- Do NOT create new test files — add to existing `TestCodeValidator` class
- Do NOT add recursive scanning for nested classes inside class bodies (unnecessary for generated agent code)
- Do NOT modify the import whitelist or forbidden patterns
