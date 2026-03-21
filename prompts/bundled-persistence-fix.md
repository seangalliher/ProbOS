# Build Prompt: Fix Bundled Persistence Writes (AD-362)

## Context

GPT-5.4 code review found that bundled agents (TodoAgent, NoteTakerAgent,
SchedulerAgent) report successful persistence while nothing is actually written
to disk. This is a **silent data loss** bug.

**Root cause chain:**
1. Bundled agents call `_mesh_write_file()` which broadcasts a `write_file`
   intent via `intent_bus.broadcast()`
2. `FileWriterAgent.handle_intent()` receives it, validates, and returns
   `IntentResult(success=True)` — but this is a *proposal*, not a committed write
3. `_mesh_write_file` sees `any(r.success for r in results)` is `True`, returns `True`
4. The bundled agents don't even check the return value (fire-and-forget)
5. Nobody calls `FileWriterAgent.commit_write()` — the only path that actually
   writes to disk is `runtime.submit_write_with_consensus()`, which the bundled
   agents never use

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Design Decision

The full consensus pipeline (`submit_write_with_consensus`) is heavyweight
(multi-agent quorum + red team verification). For personal user data (todos,
notes, reminders stored in `~/.probos/`), this is inappropriate — these are
user-owned files, not system files.

**Fix approach:** `_mesh_write_file` should call `FileWriterAgent.commit_write()`
directly for personal data writes. This skips consensus (correct for user data)
while actually committing to disk (fixing the bug). The bundled agents should
also check the return value and propagate failure.

---

## Changes

### File: `src/probos/agents/bundled/productivity_agents.py`

**Change 1:** Fix `_mesh_write_file` (line 116) to actually commit writes.

Replace the existing `_mesh_write_file` function with:

```python
async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
    """Write a file via FileWriterAgent.commit_write (personal data path).

    Bundled agents write user-owned personal data (~/.probos/) which does
    not require multi-agent consensus. This calls commit_write() directly
    to ensure data actually reaches disk.
    """
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content)
    return result.get("success", False)
```

Note: the `runtime` parameter is kept for backward compatibility but is no
longer used for the write. If you want, you can log through the runtime's
event_log if available, but the primary goal is fixing the silent data loss.

**Change 2:** In `TodoAgent.act()` (around line 188), check the return value
of `_mesh_write_file` and propagate failure:

```python
# Current (fire-and-forget):
await _mesh_write_file(
    self._runtime, path, json.dumps(data["todos"], indent=2),
)

# Fixed (check result):
written = await _mesh_write_file(
    self._runtime, path, json.dumps(data["todos"], indent=2),
)
if not written:
    return {"success": False, "error": "Failed to save todos"}
```

### File: `src/probos/agents/bundled/organizer_agents.py`

**Change 3:** Fix `_mesh_write_file` (line 55) — same change as Change 1.
Both files have their own copy of this helper.

Replace the existing `_mesh_write_file` function with the same implementation
as Change 1 above.

**Change 4:** In `NoteTakerAgent.act()` (around line 172), check the return
value:

```python
# Current (fire-and-forget):
await _mesh_write_file(self._runtime, path, content)

# Fixed (check result):
written = await _mesh_write_file(self._runtime, path, content)
if not written:
    return {"success": False, "error": f"Failed to save note: {filename}"}
```

**Change 5:** In `SchedulerAgent.act()` (around line 296), check the return
value:

```python
# Current (fire-and-forget):
await _mesh_write_file(
    self._runtime, path,
    json.dumps(data["reminders"], indent=2),
)

# Fixed (check result):
written = await _mesh_write_file(
    self._runtime, path,
    json.dumps(data["reminders"], indent=2),
)
if not written:
    return {"success": False, "error": "Failed to save reminders"}
```

---

## Tests

### File: `tests/test_bundled_agents.py`

Add integration tests that verify data actually reaches disk. Import `tmp_path`
from pytest fixtures.

```python
class TestBundledPersistence:
    """Verify bundled agents actually write to disk (AD-362)."""

    @pytest.mark.asyncio
    async def test_todo_agent_persists_to_disk(self, tmp_path):
        """TodoAgent.act() should write todos to a real file."""
        todo_path = tmp_path / "todos.json"
        agent = _make_agent(TodoAgent, runtime=MagicMock())
        agent._TODO_PATH = str(todo_path)

        decision = {
            "llm_output": json.dumps({
                "action": "add",
                "todos": [{"text": "Buy milk", "priority": "high", "due": None, "done": False}],
                "message": "Added: Buy milk",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert todo_path.exists(), "Todo file should exist on disk"
        data = json.loads(todo_path.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "Buy milk"

    @pytest.mark.asyncio
    async def test_note_taker_persists_to_disk(self, tmp_path):
        """NoteTakerAgent.act() should write notes to a real file."""
        notes_dir = tmp_path / "notes"
        agent = _make_agent(NoteTakerAgent, runtime=MagicMock())
        agent._NOTES_DIR = str(notes_dir)

        decision = {
            "llm_output": json.dumps({
                "action": "save",
                "filename": "test-note.md",
                "content": "# Test Note\nHello world",
                "message": "Note saved",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        note_file = notes_dir / "test-note.md"
        assert note_file.exists(), "Note file should exist on disk"
        assert "Hello world" in note_file.read_text()

    @pytest.mark.asyncio
    async def test_scheduler_persists_reminders_to_disk(self, tmp_path):
        """SchedulerAgent.act() should write reminders to a real file."""
        reminders_path = tmp_path / "reminders.json"
        agent = _make_agent(SchedulerAgent, runtime=MagicMock())
        agent._REMINDERS_PATH = str(reminders_path)

        decision = {
            "llm_output": json.dumps({
                "action": "set",
                "reminders": [{"text": "Call dentist", "time": "3pm"}],
                "message": "Reminder set",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert reminders_path.exists(), "Reminders file should exist on disk"
        data = json.loads(reminders_path.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "Call dentist"

    @pytest.mark.asyncio
    async def test_write_failure_propagates(self, tmp_path):
        """If FileWriterAgent.commit_write fails, act() should report failure."""
        from unittest.mock import patch

        agent = _make_agent(TodoAgent, runtime=MagicMock())
        agent._TODO_PATH = "/nonexistent/deep/path/that/requires/root/todos.json"

        decision = {
            "llm_output": json.dumps({
                "action": "add",
                "todos": [{"text": "Test", "priority": "low", "due": None, "done": False}],
                "message": "Added",
            })
        }
        # Patch commit_write to simulate failure
        with patch(
            "probos.agents.file_writer.FileWriterAgent.commit_write",
            return_value={"success": False, "error": "Permission denied"},
        ):
            result = await agent.act(decision)
        assert result["success"] is False
        assert "error" in result
```

Make sure `json` is imported at the test file top. Also add `NoteTakerAgent`
and `SchedulerAgent` to the imports from `organizer_agents`, and `TodoAgent`
from `productivity_agents` (check if they are already imported).

---

## Constraints

- Modify ONLY `productivity_agents.py`, `organizer_agents.py`, and
  `test_bundled_agents.py`
- Do NOT change `file_writer.py` or `runtime.py`
- Do NOT add consensus to the personal data write path — that's by design
- Do NOT remove the `runtime` parameter from `_mesh_write_file` (backward compat)
- Do NOT refactor surrounding code — only fix the persistence bug
- Run `pytest tests/test_bundled_agents.py -x -q` to verify
