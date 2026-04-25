# Phase 23 Patch: Close `run_command` Escape Hatch + Fix Python Interpreter Path

## AD-262: Prevent `run_command` from being used as a universal programming environment
## AD-263: ShellCommandAgent should use the venv's Python, not bare `python`

**Context:** Sonnet routes requests like "generate a QR code" to `run_command` with `python -c "import qrcode; ..."` instead of flagging a capability gap and triggering self-modification. This happens because:
1. The `IntentDescriptor.description` for `run_command` says "or anything a shell can do" — a blank check
2. There is no rule explicitly banning `python -c`/`node -e` workarounds
3. There is no example showing a capability gap for a task that *could* be done via a Python one-liner
4. When the LLM does route to `run_command` with `python`, it uses bare `python` which isn't on PATH — the venv's Python at `sys.executable` is the running interpreter

Two targeted fixes. No scope creep.

---

## AD-262: Prompt hardening against `run_command` abuse

### File: `src/probos/agents/shell_command.py` (line 45)

**Change the IntentDescriptor description.** Currently:

```python
IntentDescriptor(name="run_command", params={"command": "<shell_command>"}, description="Execute a shell command (use for calculations, dates, system info, or anything a shell can do)", requires_consensus=True, requires_reflect=True),
```

Change the description to:

```
"Execute an OS shell command (dates, system info, process management, package install). NOT for scripting workarounds."
```

The key change: remove "or anything a shell can do" and add "NOT for scripting workarounds." This description lands in the dynamic intent table that the LLM sees.

### File: `src/probos/cognitive/prompt_builder.py` — `_build_rules()` method (around line 273)

**Add a new explicit rule** after the existing run_command rules (the block starting at line 273 with comment `# Encourage using run_command as a general-purpose fallback`). Change that comment to `# Constrain run_command to prevent shell-as-programming-language abuse`. After the existing two run_command rules, add a third:

```python
rules.append(
    f'{rule_num}. NEVER use run_command to run Python, Node, Ruby, or any '
    'programming language interpreter (e.g. python -c "...", node -e "...", '
    'ruby -e "...") as a workaround for missing capabilities. If the task '
    'requires a library or capability not in the intent table, return '
    '{"intents": [], "response": "I don\'t have that capability yet.", '
    '"capability_gap": true}. The system will design a dedicated agent.'
)
rule_num += 1
```

### File: `src/probos/cognitive/prompt_builder.py` — `_GAP_EXAMPLES` list (around line 122)

**Add a QR code gap example** to the `_GAP_EXAMPLES` list:

```python
(
    "generate a QR code for https://example.com",
    "I don't have an intent for QR code generation yet.",
    "qr",
),
```

This ensures that when no QR-related intent exists, the LLM sees an explicit example of a capability gap for this class of task. The keyword `"qr"` means the example will be suppressed if a QR agent is ever registered (just like the translate example is suppressed when TranslateAgent exists).

---

## AD-263: Fix bare `python` invocations in ShellCommandAgent

### File: `src/probos/agents/shell_command.py`

**Add a method `_rewrite_python_interpreter()`** that detects commands starting with bare `python` or `python3` and replaces with `sys.executable`. Call it in `_run_command()` right after `_strip_ps_wrapper()` (around line 125).

Pattern — same preprocessing approach as `_strip_ps_wrapper()`:

```python
_BARE_PYTHON_RE = re.compile(
    r"^(python3?(?:\.exe)?)\s",
    re.IGNORECASE,
)

@staticmethod
def _rewrite_python_interpreter(command: str) -> str:
    """Replace bare ``python``/``python3`` with the current interpreter.

    When the LLM generates ``python -c "..."``, the bare name may not
    be on PATH.  Replace it with ``sys.executable`` which is guaranteed
    to be the running interpreter (inside the venv).
    """
    m = _BARE_PYTHON_RE.match(command)
    if m:
        return f'"{sys.executable}"' + command[m.end(1):]
    return command
```

Wire it in `_run_command()`:

```python
if sys.platform == "win32":
    command = self._strip_ps_wrapper(command)
command = self._rewrite_python_interpreter(command)
```

Note: the rewrite applies on ALL platforms, not just Windows. The venv's Python may not be on PATH on Linux/Mac either.

---

## Tests

### File: `tests/test_prompt_builder.py`

Add these tests to the existing `TestPromptBuilder` class:

```python
def test_run_command_description_no_blank_check(self):
    """run_command descriptor should NOT say 'anything a shell can do'."""
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(_all_current_descriptors())
    assert "anything a shell can do" not in prompt

def test_anti_scripting_rule_present(self):
    """Prompt should contain explicit rule against python -c workarounds."""
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(_all_current_descriptors())
    assert "python -c" in prompt or "NEVER use run_command to run Python" in prompt
```

Add this test to the existing `TestCapabilityGapExamples` class:

```python
def test_qr_gap_example_present(self):
    """QR code gap example should appear when no QR intent exists."""
    builder = PromptBuilder()
    prompt = builder.build_system_prompt(_all_current_descriptors())
    assert "QR code" in prompt or "qr" in prompt.lower()
    assert "capability_gap" in prompt

def test_qr_gap_suppressed_when_qr_intent_exists(self):
    """QR code gap example suppressed when a qr-related intent exists."""
    builder = PromptBuilder()
    descs = _all_current_descriptors() + [
        IntentDescriptor(
            name="generate_qr_code",
            params={"data": "..."},
            description="Generate a QR code",
        ),
    ]
    prompt = builder.build_system_prompt(descs)
    assert "I don't have an intent for QR code generation yet" not in prompt
```

### File: `tests/test_expansion_agents.py`

Add to the existing `TestShellCommandAgent` class:

```python
async def test_rewrite_bare_python(self):
    """Bare 'python -c ...' should be rewritten to sys.executable."""
    import sys
    result = ShellCommandAgent._rewrite_python_interpreter('python -c "print(1)"')
    assert sys.executable in result
    assert result.startswith(f'"{sys.executable}"')

async def test_rewrite_python3(self):
    """Bare 'python3 -c ...' should be rewritten too."""
    import sys
    result = ShellCommandAgent._rewrite_python_interpreter('python3 -c "print(1)"')
    assert sys.executable in result

async def test_no_rewrite_other_commands(self):
    """Non-python commands should pass through unchanged."""
    cmd = "echo hello"
    assert ShellCommandAgent._rewrite_python_interpreter(cmd) == cmd

async def test_no_rewrite_full_path_python(self):
    """Full path python should NOT be rewritten (already qualified)."""
    cmd = '/usr/bin/python -c "print(1)"'
    assert ShellCommandAgent._rewrite_python_interpreter(cmd) == cmd
```

---

## Acceptance criteria

1. **All existing tests pass.** No regressions. The run_command descriptor description change may break `test_build_contains_all_current_intents` if it checks for exact description text — verify and update if needed.
2. **6 new tests pass** (2 prompt builder + 2 gap example + 2-4 shell rewrite). More if you see edge cases worth covering.
3. **Total test count: baseline + new tests.** Report the final count.
4. `run_command` descriptor no longer says "anything a shell can do"
5. The generated prompt contains the anti-scripting rule
6. QR code gap example appears in the prompt when no QR intent is registered
7. `ShellCommandAgent._rewrite_python_interpreter("python -c ...")` returns a command using `sys.executable`

---

## Do NOT change

- Do not modify `decomposer.py` (the `_LEGACY_SYSTEM_PROMPT` is a fallback — it's fine if it's stale)
- Do not modify `renderer.py` or `shell.py` — these are UX layers, not prompt logic
- Do not modify `runtime.py` — the self-mod trigger path is correct
- Do not add new agents, intents, or capabilities
- Do not refactor `PromptBuilder` beyond adding the new rule and gap example
- Do not change the `_run_sync()` subprocess logic beyond calling `_rewrite_python_interpreter()`
- Do not touch `_CAPABILITY_GAP_RE` in `decomposer.py`
- Do not modify any HXI/UI files
- Do not modify `api.py`
- Do not change `config/system.yaml`

---

## File summary

| File | Change |
|------|--------|
| `src/probos/agents/shell_command.py` | Reword `IntentDescriptor.description`, add `_BARE_PYTHON_RE` + `_rewrite_python_interpreter()`, call it in `_run_command()` |
| `src/probos/cognitive/prompt_builder.py` | Add anti-scripting rule to `_build_rules()`, add QR code entry to `_GAP_EXAMPLES`, update comment |
| `tests/test_prompt_builder.py` | 4 new tests: descriptor wording, anti-scripting rule, QR gap present, QR gap suppressed |
| `tests/test_expansion_agents.py` | 3-4 new tests: python rewrite, python3 rewrite, passthrough, full-path passthrough |
