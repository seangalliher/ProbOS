# AD-413: Fine-Grained Reset Scope + Ward Room Awareness

## Context

`probos reset` currently wipes KnowledgeStore subdirs (episodes, agents, skills, trust, routing, workflows, qa), ChromaDB, and Hebbian weights DB — but does not touch Ward Room (`ward_room.db`), DAG checkpoints (`checkpoints/`), or several other SQLite databases. This creates a cognitive coherence problem: after reset, agents have no episodic memory but the Ward Room still contains posts they authored pre-reset.

**Design decision:** A reset = day 0. One clean timeline. No bifurcated history. Archive old data to files for human reference, then wipe. Simple and clean.

Additionally, the proactive cognitive loop (Phase 28b) gives agents zero awareness of Ward Room discussions during their think cycles. They can only react to new post notifications. Adding Ward Room context to proactive thinks makes the communication fabric actually useful for agent cognition.

## Reference Files

- `src/probos/__main__.py` — `_cmd_reset()` at line 517, `_RESET_SUBDIRS` at line 514, argparse at line 639
- `src/probos/ward_room.py` — `WardRoomService` at line 200, `list_threads()` at line 369
- `src/probos/proactive.py` — `_gather_context()` at line 161, `_post_to_ward_room()` at line 217
- `src/probos/cognitive/cognitive_agent.py` — `_format_observation()` proactive_think branch at line 346
- `src/probos/runtime.py` — data_dir DBs at lines 136/143/168/1158/1166/1179/1216/1226, checkpoint_dir at line 119
- `src/probos/config.py` — WardRoomConfig

## Part 1: Expand Reset Scope — `__main__.py`

### 1a. Add Ward Room + checkpoints to default reset

In `_cmd_reset()`, after the Hebbian weights DB cleanup (line 567), add:

```python
# Clear Ward Room DB (AD-413)
wardroom_cleared = False
wardroom_db = data_dir / "ward_room.db"
if wardroom_db.is_file() and not args.keep_wardroom:
    # Archive before wiping
    archive_dir = data_dir / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive_path = archive_dir / f"ward_room_{timestamp}.db"
    shutil.copy2(str(wardroom_db), str(archive_path))
    wardroom_db.unlink()
    wardroom_cleared = True

# Clear DAG checkpoints (AD-413)
checkpoints_cleared = False
checkpoint_dir = data_dir / "checkpoints"
if checkpoint_dir.is_dir():
    for fp in checkpoint_dir.glob("*.json"):
        fp.unlink()
    checkpoints_cleared = True

# Clear credibility/endorsement state (lives in ward_room.db, wiped above)
# Clear event log (development artifact, reset = day 0)
events_cleared = False
events_db = data_dir / "events.db"
if events_db.is_file():
    events_db.unlink()
    events_cleared = True
```

Update the confirmation prompt (line 534) to mention Ward Room:

```python
answer = input(
    "This will permanently delete all learned state "
    "(designed agents, trust, routing weights, episodes, workflows, QA reports, "
    "Ward Room history, event log, DAG checkpoints). "
    "Continue? [y/N]: "
).strip().lower()
```

Update the summary line (line 583) to include new items:

```python
wardroom_msg = " Ward Room archived and wiped." if wardroom_cleared else ""
checkpoint_msg = " DAG checkpoints cleared." if checkpoints_cleared else ""
events_msg = " Event log cleared." if events_cleared else ""
console.print(
    f"[bold green]Reset complete.[/bold green] Cleared: {summary}."
    f"{chroma_msg}{hebbian_msg}{wardroom_msg}{checkpoint_msg}{events_msg}"
)
if wardroom_cleared:
    console.print(f"  Ward Room archived to: {archive_path}")
```

### 1b. Add `--keep-wardroom` flag

In the argparse section (after line 642), add:

```python
reset_parser.add_argument("--keep-wardroom", action="store_true", help="Preserve Ward Room history")
```

### 1c. Do NOT wipe these (by design):
- `scheduled_tasks.db` — User-defined schedules are intent, not learned state
- `assignments.db` — User-created assignments are intent, not learned state
- `trust.db` — Already has `--keep-trust` flag
- `service_profiles.db` — Deterministic from routing data, rebuilds naturally
- `directives.db` — Captain-issued directives are orders, not learned state

## Part 2: Ward Room Awareness in Proactive Loop — `ward_room.py`

Add a new method to `WardRoomService` for retrieving recent activity suitable for agent context. Place it after `list_threads()` (after line 393):

```python
async def get_recent_activity(
    self, channel_id: str, since: float, limit: int = 10,
) -> list[dict[str, Any]]:
    """Recent threads + posts in a channel since a timestamp.

    Returns a flat list of dicts with author_callsign, body (truncated),
    created_at, and type ('thread' or 'reply').  Designed for proactive
    loop context injection — compact, no nesting.
    """
    if not self._db:
        return []

    items: list[dict[str, Any]] = []

    # Recent threads
    async with self._db.execute(
        "SELECT author_callsign, title, body, created_at "
        "FROM threads WHERE channel_id = ? AND created_at > ? "
        "ORDER BY created_at DESC LIMIT ?",
        (channel_id, since, limit),
    ) as cursor:
        async for row in cursor:
            items.append({
                "type": "thread",
                "author": row[0] or "unknown",
                "title": row[1][:100],
                "body": row[2][:200],
                "created_at": row[3],
            })

    # Recent replies in threads from this channel
    async with self._db.execute(
        "SELECT p.author_callsign, p.body, p.created_at "
        "FROM posts p JOIN threads t ON p.thread_id = t.id "
        "WHERE t.channel_id = ? AND p.created_at > ? AND p.deleted = 0 "
        "ORDER BY p.created_at DESC LIMIT ?",
        (channel_id, since, limit),
    ) as cursor:
        async for row in cursor:
            items.append({
                "type": "reply",
                "author": row[0] or "unknown",
                "body": row[1][:200],
                "created_at": row[2],
            })

    # Sort by time, most recent first, cap total
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:limit]
```

## Part 3: Wire Ward Room Context into Proactive Loop — `proactive.py`

In `_gather_context()` (after the "Recent system events" block, line 213), add a 4th context source:

```python
# 4. Recent Ward Room activity in agent's department (AD-413)
if hasattr(rt, 'ward_room') and rt.ward_room:
    try:
        from probos.cognitive.standing_orders import get_department
        dept = get_department(agent.agent_type)

        if dept:
            channels = await rt.ward_room.list_channels()
            dept_channel = None
            for ch in channels:
                if ch.channel_type == "department" and ch.department == dept:
                    dept_channel = ch
                    break

            if dept_channel:
                # Look back one cooldown window (what happened since last think)
                cooldown = self._agent_cooldowns.get(agent.id, self._default_cooldown)
                since = time.time() - cooldown
                activity = await rt.ward_room.get_recent_activity(
                    dept_channel.id, since=since, limit=5
                )
                if activity:
                    context["ward_room_activity"] = [
                        {
                            "type": a["type"],
                            "author": a["author"],
                            "body": a.get("title", a.get("body", ""))[:150],
                        }
                        for a in activity
                    ]
    except Exception:
        logger.debug("Ward Room context fetch failed for %s", agent.id, exc_info=True)
```

Add `import time` at the top of `proactive.py` if not already present.

## Part 4: Render Ward Room Context in Proactive Think — `cognitive_agent.py`

In `_format_observation()`, in the proactive_think branch (after the "Recent events" block, after line 382), add:

```python
# Recent Ward Room activity (AD-413)
wr_activity = context_parts.get("ward_room_activity", [])
if wr_activity:
    pt_parts.append("Recent Ward Room discussion in your department:")
    for a in wr_activity:
        prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
        pt_parts.append(f"  - {prefix} {a.get('author', '?')}: {a.get('body', '?')}")
    pt_parts.append("")
```

## Part 5: Tests

Add the following tests to `tests/test_proactive.py` (append to existing test class or create new class):

### Test 5a: Reset archives Ward Room DB

```python
class TestResetScope:
    """AD-413: Fine-grained reset scope tests."""

    def test_reset_archives_wardroom(self, tmp_path):
        """probos reset should archive ward_room.db before deleting."""
        import shutil
        from probos.__main__ import _cmd_reset

        # Create fake data_dir with ward_room.db
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        wr_db = data_dir / "ward_room.db"
        wr_db.write_text("fake ward room data")

        # Create minimal knowledge dir
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        # Mock args
        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

        # Patch _load_config_with_fallback and _default_data_dir
        from unittest.mock import patch, MagicMock
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        # ward_room.db should be gone
        assert not wr_db.exists()

        # Archive should exist
        archive_dir = data_dir / "archives"
        assert archive_dir.exists()
        archives = list(archive_dir.glob("ward_room_*.db"))
        assert len(archives) == 1
        assert archives[0].read_text() == "fake ward room data"

    def test_reset_keeps_wardroom_with_flag(self, tmp_path):
        """--keep-wardroom should preserve ward_room.db."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        wr_db = data_dir / "ward_room.db"
        wr_db.write_text("keep me")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=True,
            config=None,
            data_dir=data_dir,
        )

        from unittest.mock import patch, MagicMock
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        assert wr_db.exists()
        assert wr_db.read_text() == "keep me"

    def test_reset_clears_checkpoints(self, tmp_path):
        """probos reset should clear DAG checkpoint JSON files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")
        (cp_dir / "dag2.json").write_text("{}")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

        from unittest.mock import patch, MagicMock
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        remaining = list(cp_dir.glob("*.json"))
        assert len(remaining) == 0

    def test_reset_clears_events_db(self, tmp_path):
        """probos reset should clear events.db."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        events_db = data_dir / "events.db"
        events_db.write_text("fake events")

        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()

        args = argparse.Namespace(
            yes=True,
            keep_trust=False,
            keep_wardroom=False,
            config=None,
            data_dir=data_dir,
        )

        from unittest.mock import patch, MagicMock
        mock_config = MagicMock()
        mock_config.knowledge.repo_path = str(knowledge_dir)

        with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
            with patch("probos.__main__._default_data_dir", return_value=data_dir):
                _cmd_reset(args)

        assert not events_db.exists()
```

### Test 5b: Ward Room `get_recent_activity`

Add to `tests/test_ward_room.py`:

```python
class TestWardRoomRecentActivity:
    """AD-413: Recent activity for proactive loop context."""

    @pytest.fixture
    async def wr(self, tmp_path):
        svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await svc.start()
        yield svc
        await svc.stop()

    async def test_get_recent_activity_returns_threads(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]  # All Hands
        await wr.create_thread(ch.id, "agent1", "Test Thread", "Body text", author_callsign="LaForge")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        assert len(activity) >= 1
        assert activity[0]["type"] == "thread"
        assert activity[0]["author"] == "LaForge"

    async def test_get_recent_activity_respects_since(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        await wr.create_thread(ch.id, "agent1", "Old Thread", "old", author_callsign="Worf")
        import time
        cutoff = time.time() + 1  # Future cutoff
        activity = await wr.get_recent_activity(ch.id, since=cutoff, limit=10)
        assert len(activity) == 0

    async def test_get_recent_activity_includes_replies(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        thread = await wr.create_thread(ch.id, "agent1", "Thread", "body", author_callsign="Number One")
        await wr.create_post(thread.id, "agent2", "I agree", author_callsign="Wesley")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        types = {a["type"] for a in activity}
        assert "thread" in types
        assert "reply" in types

    async def test_get_recent_activity_limits_results(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        for i in range(10):
            await wr.create_thread(ch.id, "agent1", f"Thread {i}", "body", author_callsign="LaForge")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=3)
        assert len(activity) == 3

    async def test_get_recent_activity_no_db(self):
        svc = WardRoomService(db_path=None)
        await svc.start()
        result = await svc.get_recent_activity("fake", since=0.0)
        assert result == []
        await svc.stop()
```

### Test 5c: Proactive loop includes Ward Room context

Add to `tests/test_proactive.py`:

```python
async def test_gather_context_includes_ward_room(self):
    """AD-413: _gather_context should include recent Ward Room activity."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
    loop._default_cooldown = 300
    loop._agent_cooldowns = {}

    # Mock runtime with ward_room
    rt = MagicMock()
    rt.episodic_memory = None
    rt.bridge_alerts = None
    rt.event_log = None

    mock_channel = MagicMock()
    mock_channel.channel_type = "department"
    mock_channel.department = "engineering"
    mock_channel.id = "ch-eng"

    rt.ward_room = AsyncMock()
    rt.ward_room.list_channels = AsyncMock(return_value=[mock_channel])
    rt.ward_room.get_recent_activity = AsyncMock(return_value=[
        {"type": "thread", "author": "LaForge", "title": "EPS conduit check", "body": "All nominal", "created_at": 1.0},
    ])

    loop._runtime = rt

    agent = MagicMock()
    agent.id = "eng-1"
    agent.agent_type = "engineering_officer"

    context = await loop._gather_context(agent, trust_score=0.7)
    assert "ward_room_activity" in context
    assert len(context["ward_room_activity"]) == 1
    assert context["ward_room_activity"][0]["author"] == "LaForge"
```

## Verification

Run these commands to verify:

```bash
# Targeted tests
uv run pytest tests/test_ward_room.py -x -v -k "RecentActivity"
uv run pytest tests/test_proactive.py -x -v -k "ward_room or reset"

# If reset tests are in a separate file, run those too

# Full regression
uv run pytest tests/ --tb=short -q
```

Expected: all new tests pass, no regressions.
