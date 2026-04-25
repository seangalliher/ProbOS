# Fix AD-263: PowerShell Call Operator for Quoted Python Path

## Problem

`_rewrite_python_interpreter()` produces `"D:\...\python.exe" -c "..."` which gets passed to `powershell -NoProfile -Command`. PowerShell treats a quoted string as a value expression, not a command invocation. It needs the call operator `&`:

```
& "D:\ProbOS\.venv\Scripts\python.exe" -c "..."   ← works
"D:\ProbOS\.venv\Scripts\python.exe" -c "..."      ← ParserError: UnexpectedToken
```

## Fix

### File: `src/probos/agents/shell_command.py`

In `_rewrite_python_interpreter()`, change the return line from:

```python
return f'"{sys.executable}"' + command[m.end(1):]
```

to:

```python
prefix = '& ' if sys.platform == 'win32' else ''
return f'{prefix}"{sys.executable}"' + command[m.end(1):]
```

### File: `tests/test_expansion_agents.py`

Update the python rewrite tests to be platform-aware. On Windows, the result should start with `& "` (call operator + quoted path). On other platforms, just `"`.

Find the test `test_rewrite_bare_python` and update the assertion:

```python
async def test_rewrite_bare_python(self):
    """Bare 'python -c ...' should be rewritten to sys.executable."""
    import sys
    result = ShellCommandAgent._rewrite_python_interpreter('python -c "print(1)"')
    assert sys.executable in result
    if sys.platform == 'win32':
        assert result.startswith('& "')
    else:
        assert result.startswith('"')
```

Do the same for `test_rewrite_python3` — add the platform-aware check.

## Constraints

- Only touch 2 files: `src/probos/agents/shell_command.py` and `tests/test_expansion_agents.py`
- Do NOT change any other files
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Update the test count on line 3 of `PROGRESS.md` if it changed
- Report the final test count
