# BF-072: Path Traversal Fix — Ship's Records

## Problem

`records_store.py` has **zero path sanitization** across 6 methods. User-supplied paths are directly concatenated with `self._repo_path / path`, allowing path traversal via `../../` sequences:

| Method | Line | Risk |
|--------|------|------|
| `write_entry()` | 119 | `../../etc` in path could write outside repo. Also calls `mkdir(parents=True)` — creates arbitrary directories. |
| `read_entry()` | 203 | `../../etc/passwd` could read outside repo |
| `list_entries()` | 236 | `directory` parameter unsanitized |
| `get_history()` | 264 | Path passed to `git log --follow -- {path}` |
| `write_notebook()` | 180 | Interpolates `callsign` and `topic_slug` into path |
| `publish()` | 288 | Same unsanitized `self._repo_path / path` pattern |

These flow from 5 API endpoints:
- `POST /api/records/notebooks/{callsign}` → `write_notebook()`
- `POST /api/records/entries` → `write_entry()`
- `GET /api/records/entries/{path:path}` → `read_entry()`
- `GET /api/records/list` → `list_entries()`
- `POST /api/records/publish` → `publish()`

## Solution

Add a private `_safe_path()` validator method that uses `Path.resolve()` + `is_relative_to()` to ensure all resolved paths stay within `self._repo_path`. Apply it to every method that constructs a file path from user input.

## Files to Modify

### 1. `src/probos/knowledge/records_store.py`

**a) Add the `_safe_path()` validator** (in the internal helpers section, after `_parse_document`):

```python
def _safe_path(self, user_path: str) -> Path:
    """Validate and resolve a user-supplied path, preventing traversal.

    Raises ValueError if the resolved path escapes the records repo.
    """
    # Normalize and resolve
    resolved = (self._repo_path / user_path).resolve()
    repo_resolved = self._repo_path.resolve()

    if not resolved.is_relative_to(repo_resolved):
        raise ValueError(f"Path traversal denied: {user_path!r}")

    return resolved
```

**b) Apply `_safe_path()` to each method:**

**`write_entry()` (line 119)** — Replace:
```python
file_path = self._repo_path / path
```
With:
```python
file_path = self._safe_path(path)
```

**`read_entry()` (line 203)** — Replace:
```python
file_path = self._repo_path / path
```
With:
```python
file_path = self._safe_path(path)
```

**`list_entries()` (line 236)** — Replace:
```python
search_path = self._repo_path / directory if directory else self._repo_path
```
With:
```python
search_path = self._safe_path(directory) if directory else self._repo_path
```

**`get_history()` (line 264)** — Add validation before the git command. The path is passed to `git log --follow -- {path}`, so validate the resolved path first:
```python
# At the start of get_history(), before the try block:
self._safe_path(path)  # Validate — raises ValueError if traversal
```

**`write_notebook()` (line 180)** — The path is constructed from `callsign` and `topic_slug`. These are interpolated into `notebooks/{callsign}/{topic_slug}.md`. The validation happens in `write_entry()` which this calls, but add an early check:
```python
# After constructing the path:
path = f"notebooks/{callsign}/{topic_slug}.md"
self._safe_path(path)  # Validate before delegating to write_entry
```

**`publish()` (line 288)** — Replace:
```python
file_path = self._repo_path / path
```
With:
```python
file_path = self._safe_path(path)
```

**c) Handle the ValueError in API endpoints:**

The `_safe_path()` method raises `ValueError` on traversal attempts. The API layer should catch this and return HTTP 400. Check `api.py` for the records endpoints and add appropriate error handling:

```python
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

This may already be handled by FastAPI's default error handling. If records endpoints have try/except blocks, add `ValueError` to the catch. If they don't, the ValueError will propagate as a 500 — add explicit handling to return 400.

### 2. Tests

Add tests in a new file `tests/test_path_traversal.py`:

```python
"""Tests for BF-072: Path traversal prevention in Ship's Records."""
```

Test cases:

1. **`_safe_path()` allows valid relative paths**: `"notebooks/data/analysis.md"` → succeeds
2. **`_safe_path()` blocks `../` traversal**: `"../../etc/passwd"` → raises ValueError
3. **`_safe_path()` blocks absolute paths**: `"/etc/passwd"` → raises ValueError (or treated as relative, then validated)
4. **`_safe_path()` blocks nested traversal**: `"notebooks/../../secret.txt"` → raises ValueError
5. **`_safe_path()` allows subdirectory paths**: `"captains-log/2026-03-29.md"` → succeeds
6. **`write_entry()` rejects traversal path**: Call with `path="../../hack.md"` → raises ValueError
7. **`read_entry()` rejects traversal path**: Call with `path="../../etc/passwd"` → raises ValueError
8. **`list_entries()` rejects traversal directory**: Call with `directory="../../"` → raises ValueError
9. **`write_notebook()` rejects traversal in callsign**: Call with `callsign="../../etc"` → raises ValueError
10. **`publish()` rejects traversal path**: Call with `path="../../hack.md"` → raises ValueError
11. **`get_history()` rejects traversal path**: Call with `path="../../etc/passwd"` → raises ValueError

## Implementation Notes

- `Path.is_relative_to()` is available since Python 3.9. ProbOS requires 3.10+, so this is safe.
- On Windows, `Path.resolve()` handles both `/` and `\` separators.
- The `_safe_path()` method returns the resolved `Path` object, which should be used directly for file operations instead of re-constructing from `self._repo_path / path`.
- `write_entry()` line 120 calls `file_path.parent.mkdir(parents=True, exist_ok=True)` — after the `_safe_path()` check, this is safe because the parent is guaranteed to be within the repo root.
- The `search()` method (line 308) uses `self._repo_path.rglob("*.md")` which is already safe — it only searches within the repo directory.
- `append_captains_log()` constructs a hardcoded path (`captains-log/{today}.md`) — no user input, so no traversal risk.

## Acceptance Criteria

- [ ] `_safe_path()` method added to `RecordsStore`
- [ ] All 6 methods with user-supplied paths use `_safe_path()`
- [ ] `ValueError` raised on traversal attempts
- [ ] API endpoints return HTTP 400 on traversal attempts (not 500)
- [ ] All new tests pass
- [ ] Existing records tests unaffected
