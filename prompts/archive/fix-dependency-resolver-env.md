# Fix: Dependency Resolver — Use Venv Python, Not System PATH

## Problem

The dependency resolver (Phase 17) uses `uv add` to install packages. This fails when:
1. `uv` is not on the system PATH (common — uv was used to create the venv but isn't globally installed)
2. `pip` is not on PATH either (uv-managed venvs don't always include pip.exe)
3. `run_command` uses `python` which may not resolve to the venv's Python

**The user should NEVER have to open PowerShell to install packages.** ProbOS must handle dependency installation entirely within its own process, using its own Python environment.

## Root Cause

`DependencyResolver._install_package()` in `src/probos/cognitive/dependency_resolver.py` calls `uv add <package>` via subprocess. This depends on `uv` being on PATH, which it often isn't.

## Fix

**File:** `src/probos/cognitive/dependency_resolver.py`

Replace the install command with a reliable fallback chain:

```python
import sys
import subprocess

async def _install_package(self, package_name: str) -> bool:
    """Install a package using the best available method.
    
    Fallback chain:
    1. sys.executable -m pip install <package>  (always works — uses the running Python's venv)
    2. uv pip install <package>  (if uv is available)
    3. uv add <package>  (if uv is available and we're in a uv project)
    """
    python_exe = sys.executable  # The Python running ProbOS — guaranteed to be the venv Python
    
    # Method 1: pip via the running Python (most reliable)
    try:
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", package_name],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return True
        logger.warning("pip install failed: %s", result.stderr[:200])
    except Exception as e:
        logger.warning("pip install exception: %s", e)
    
    # Method 2: uv pip install (faster if available)
    try:
        import shutil
        uv_path = shutil.which("uv")
        if uv_path:
            result = subprocess.run(
                [uv_path, "pip", "install", package_name],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return True
    except Exception as e:
        logger.debug("uv pip install failed: %s", e)
    
    # Method 3: uv add (for uv-managed projects)
    try:
        if uv_path:
            result = subprocess.run(
                [uv_path, "add", package_name],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return True
    except Exception:
        pass
    
    return False
```

**The key insight:** `sys.executable` always points to the Python that's running ProbOS — which is the venv's Python. Using `sys.executable -m pip install` is the most reliable cross-platform method. It doesn't depend on PATH, doesn't need `uv` installed globally, and works in any venv regardless of how it was created.

## Also fix: ShellCommandAgent Python detection

**File:** `src/probos/agents/shell_command.py`

When the LLM generates a `run_command` with `python -c "..."`, the command fails because `python` on PATH may not be the venv Python. 

This is harder to fix properly (the shell command agent runs arbitrary commands), but a quick improvement: if the command starts with `python ` or `python3 `, replace it with `sys.executable`:

```python
import sys

def _prepare_command(self, command: str) -> str:
    """Substitute 'python' with the venv Python if applicable."""
    if command.startswith("python ") or command.startswith("python3 "):
        return sys.executable + command[command.index(" "):]
    return command
```

## After fix

1. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
2. Test: start ProbOS → trigger self-mod with a query that needs a new package → the package should install automatically without the user touching PowerShell
3. Verify: `sys.executable` resolves to the venv Python path
