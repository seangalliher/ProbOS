# AD-431: Cognitive Journal — Agent Reasoning Trace Service

## Context

Agents currently have no trace of their own reasoning. `decide()` calls `self._llm_client.complete(request)` and discards `response.model`, `response.tokens_used`, and `response.request_id`. There is no timing of LLM calls. The ship has zero memory of its own thought processes — only compressed episode summaries of what happened, not how agents arrived at their decisions.

The Cognitive Journal is an append-only SQLite store that captures every LLM call with full metadata: who asked, what tier, which model, how many tokens, how long it took, and what intent it served. This gives agents (and the Captain) queryable access to reasoning history.

**Architecture:**
- Ship's Computer service (infrastructure tier — no identity, no Character/Reason/Duty)
- aiosqlite, follows existing WardRoomService / PersistentTaskStore patterns exactly
- Single instrumentation point in `decide()` — minimal code surface
- Non-critical — all journal writes are fire-and-forget with try/except

**What this does NOT do:**
- Does NOT replace or modify episode storage (AD-430 — working correctly)
- Does NOT depend on Ship's Telemetry (journals directly in decide())
- Does NOT do knowledge promotion (separate future concern)
- Does NOT modify dream consolidation (future integration)

## Changes

### Step 1: Add LLMResponse fields for richer token data

**File:** `src/probos/types.py`

Find the `LLMResponse` dataclass. Add two new fields after `tokens_used`:

```python
@dataclass
class LLMResponse:
    """Response from the LLM client."""
    content: str
    model: str = ""
    tier: str = "standard"
    tokens_used: int = 0
    prompt_tokens: int = 0       # AD-431: separate prompt token count
    completion_tokens: int = 0   # AD-431: separate completion token count
    cached: bool = False
    error: str | None = None
    request_id: str = ""
```

### Step 2: Extract separate token counts in LLM client

**File:** `src/probos/cognitive/llm_client.py`

**2a. OpenAI path** — in `_call_openai()` (around line 340, where `tokens_used` is set):

Change:
```python
tokens_used = data.get("usage", {}).get("total_tokens", 0)
```
To:
```python
usage = data.get("usage", {})
tokens_used = usage.get("total_tokens", 0)
prompt_tokens = usage.get("prompt_tokens", 0)
completion_tokens = usage.get("completion_tokens", 0)
```

And in the `LLMResponse(...)` constructor call in the same method, add:
```python
prompt_tokens=prompt_tokens,
completion_tokens=completion_tokens,
```

**2b. Ollama native path** — in `_call_ollama_native()` (around line 394):

Change:
```python
tokens_used = (
    data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
)
```
To:
```python
prompt_tokens = data.get("prompt_eval_count", 0)
completion_tokens = data.get("eval_count", 0)
tokens_used = prompt_tokens + completion_tokens
```

And in the `LLMResponse(...)` constructor call, add:
```python
prompt_tokens=prompt_tokens,
completion_tokens=completion_tokens,
```

### Step 3: Create CognitiveJournal service

**File:** `src/probos/cognitive/journal.py` (NEW FILE)

```python
"""Cognitive Journal — append-only LLM reasoning trace store.

Records every LLM call with agent, tier, model, tokens, latency, and
intent linkage.  Ship's Computer infrastructure service (no identity).
AD-431.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    agent_id    TEXT NOT NULL,
    agent_type  TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL DEFAULT 'standard',
    model       TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0.0,
    intent           TEXT NOT NULL DEFAULT '',
    success          INTEGER NOT NULL DEFAULT 1,
    cached           INTEGER NOT NULL DEFAULT 0,
    request_id       TEXT NOT NULL DEFAULT '',
    prompt_hash      TEXT NOT NULL DEFAULT '',
    response_length  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_journal_agent ON journal(agent_id);
CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_journal_intent ON journal(intent);
"""


class CognitiveJournal:
    """Append-only SQLite journal for LLM reasoning traces."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path
        self._db: Any = None

    async def start(self) -> None:
        if not self.db_path:
            return
        import aiosqlite
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = __import__("aiosqlite").Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def record(
        self,
        *,
        entry_id: str,
        timestamp: float,
        agent_id: str,
        agent_type: str = "",
        tier: str = "standard",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: float = 0.0,
        intent: str = "",
        success: bool = True,
        cached: bool = False,
        request_id: str = "",
        prompt_hash: str = "",
        response_length: int = 0,
    ) -> None:
        """Append a journal entry. Fire-and-forget — never raises."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO journal
                   (id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, success, cached, request_id,
                    prompt_hash, response_length)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Journal record failed", exc_info=True)

    async def get_reasoning_chain(
        self, agent_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent journal entries for an agent, most recent first."""
        if not self._db:
            return []
        try:
            cursor = await self._db.execute(
                """SELECT * FROM journal
                   WHERE agent_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (agent_id, limit),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Journal query failed", exc_info=True)
            return []

    async def get_token_usage(
        self, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Token usage summary. If agent_id is None, returns ship-wide totals."""
        if not self._db:
            return {"total_tokens": 0, "total_calls": 0}
        try:
            if agent_id:
                cursor = await self._db.execute(
                    """SELECT COUNT(*) as calls,
                              SUM(total_tokens) as tokens,
                              SUM(prompt_tokens) as prompt_tok,
                              SUM(completion_tokens) as comp_tok,
                              AVG(latency_ms) as avg_latency
                       FROM journal WHERE agent_id = ? AND cached = 0""",
                    (agent_id,),
                )
            else:
                cursor = await self._db.execute(
                    """SELECT COUNT(*) as calls,
                              SUM(total_tokens) as tokens,
                              SUM(prompt_tokens) as prompt_tok,
                              SUM(completion_tokens) as comp_tok,
                              AVG(latency_ms) as avg_latency
                       FROM journal WHERE cached = 0""",
                )
            row = await cursor.fetchone()
            if row:
                return {
                    "total_calls": row["calls"] or 0,
                    "total_tokens": row["tokens"] or 0,
                    "prompt_tokens": row["prompt_tok"] or 0,
                    "completion_tokens": row["comp_tok"] or 0,
                    "avg_latency_ms": round(row["avg_latency"] or 0, 1),
                }
            return {"total_tokens": 0, "total_calls": 0}
        except Exception:
            logger.debug("Journal token query failed", exc_info=True)
            return {"total_tokens": 0, "total_calls": 0}

    async def get_stats(self) -> dict[str, Any]:
        """Overall journal statistics."""
        if not self._db:
            return {"total_entries": 0}
        try:
            cursor = await self._db.execute("SELECT COUNT(*) FROM journal")
            row = await cursor.fetchone()
            total = row[0] if row else 0

            cursor = await self._db.execute(
                """SELECT agent_type, COUNT(*) as cnt
                   FROM journal GROUP BY agent_type
                   ORDER BY cnt DESC LIMIT 10"""
            )
            by_type = {r["agent_type"]: r["cnt"] for r in await cursor.fetchall()}

            cursor = await self._db.execute(
                """SELECT intent, COUNT(*) as cnt
                   FROM journal GROUP BY intent
                   ORDER BY cnt DESC LIMIT 10"""
            )
            by_intent = {r["intent"]: r["cnt"] for r in await cursor.fetchall()}

            return {
                "total_entries": total,
                "by_agent_type": by_type,
                "by_intent": by_intent,
            }
        except Exception:
            logger.debug("Journal stats failed", exc_info=True)
            return {"total_entries": 0}
```

### Step 4: Config model

**File:** `src/probos/config.py`

Add a new config model near the other service configs:

```python
class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
```

Register it in `SystemConfig`:

```python
class SystemConfig(BaseModel):
    # ... existing fields ...
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
```

### Step 5: Instrument `decide()` in CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

**5a.** Add a `_cognitive_journal` property helper (near the top of the class, after `__init__`):

```python
@property
def _cognitive_journal(self):
    """AD-431: Access journal via runtime (Ship's Computer service)."""
    if self._runtime and hasattr(self._runtime, 'cognitive_journal'):
        return self._runtime.cognitive_journal
    return None
```

**5b.** In `decide()`, wrap the LLM call with timing and journal write.

Find the LLM call block (lines 176-187). Replace:

```python
        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=self._resolve_tier(),
        )
        response = await self._llm_client.complete(request)

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }
```

With:

```python
        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=self._resolve_tier(),
        )

        # AD-431: Time the LLM call for journal
        _t0 = time.monotonic()
        response = await self._llm_client.complete(request)
        _latency_ms = (time.monotonic() - _t0) * 1000

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

        # AD-431: Record to Cognitive Journal (fire-and-forget)
        if self._cognitive_journal:
            try:
                import hashlib
                _prompt_hash = hashlib.md5(user_message[:500].encode()).hexdigest()[:12]
                await self._cognitive_journal.record(
                    entry_id=request.id,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    tier=response.tier,
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.tokens_used,
                    latency_ms=_latency_ms,
                    intent=observation.get("intent", ""),
                    success=response.error is None,
                    cached=False,
                    request_id=request.id,
                    prompt_hash=_prompt_hash,
                    response_length=len(response.content),
                )
            except Exception:
                pass  # Non-critical — never block agent cognition
```

**Important:** `import time` is already present at the top of the file (used by decision cache). Confirm this. If not, add it.

**5c.** Also add a cache-hit journal entry in the early return path (lines 95-108). After the cache hit is detected:

Find:
```python
        _CACHE_HITS[self.agent_type] = _CACHE_HITS.get(self.agent_type, 0) + 1
        return {**decision, "cached": True}
```

Insert before the return:
```python
        _CACHE_HITS[self.agent_type] = _CACHE_HITS.get(self.agent_type, 0) + 1
        # AD-431: Journal cache hits too (for token accounting accuracy)
        if self._cognitive_journal:
            try:
                import uuid as _uuid
                await self._cognitive_journal.record(
                    entry_id=_uuid.uuid4().hex,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    intent=observation.get("intent", ""),
                    cached=True,
                )
            except Exception:
                pass
        return {**decision, "cached": True}
```

### Step 6: Wire into Runtime

**File:** `src/probos/runtime.py`

**6a. Declare attribute in `__init__`:**

Find the other `self.xxx = None` declarations (near `self.ward_room`, `self.persistent_task_store`). Add:

```python
self.cognitive_journal: Any = None
```

**6b. Initialize in `start()`:**

Add after KnowledgeStore initialization (around line 1027) but before the proactive loop (line 1273). Place it near the ward_room or persistent_tasks initialization:

```python
# AD-431: Cognitive Journal
if self.config.cognitive_journal.enabled:
    from probos.cognitive.journal import CognitiveJournal
    self.cognitive_journal = CognitiveJournal(
        db_path=str(self._data_dir / "cognitive_journal.db"),
    )
    await self.cognitive_journal.start()
```

**6c. Shutdown:**

Add to the shutdown sequence (near the ward_room/persistent_task_store stop blocks):

```python
if self.cognitive_journal:
    await self.cognitive_journal.stop()
    self.cognitive_journal = None
```

### Step 7: REST API endpoints

**File:** `src/probos/api.py`

Add two endpoints. Place near the existing agent endpoints:

```python
@app.get("/api/journal/stats")
async def journal_stats() -> dict[str, Any]:
    """AD-431: Cognitive Journal statistics."""
    if not runtime.cognitive_journal:
        return {"total_entries": 0}
    return await runtime.cognitive_journal.get_stats()


@app.get("/api/agent/{agent_id}/journal")
async def agent_journal(agent_id: str, limit: int = 20) -> dict[str, Any]:
    """AD-431: Agent reasoning chain from Cognitive Journal."""
    if not runtime.cognitive_journal:
        return {"entries": []}
    entries = await runtime.cognitive_journal.get_reasoning_chain(
        agent_id, limit=min(limit, 100)
    )
    return {"agent_id": agent_id, "entries": entries}


@app.get("/api/journal/tokens")
async def journal_token_usage(agent_id: str | None = None) -> dict[str, Any]:
    """AD-431: Token usage summary (ship-wide or per-agent)."""
    if not runtime.cognitive_journal:
        return {"total_tokens": 0, "total_calls": 0}
    return await runtime.cognitive_journal.get_token_usage(agent_id)
```

### Step 8: Include in `probos reset`

**File:** `src/probos/runtime.py`

Find the reset method (search for `probos reset` or `async def reset`). It currently wipes `ward_room.db`, events.db, DAG checkpoints. Add `cognitive_journal.db` to the wipe list:

```python
# AD-431: Wipe cognitive journal on reset
journal_db = Path(self._data_dir) / "cognitive_journal.db"
if journal_db.exists():
    journal_db.unlink()
```

Also stop and restart the journal service around the reset (same pattern as ward_room).

## Tests

**File:** `tests/test_cognitive_journal.py` (NEW FILE)

### Test 1: Journal starts and stops cleanly
```
Create CognitiveJournal with a tmp_path db.
await start() — assert no error.
await stop() — assert no error.
Assert the db file exists.
```

### Test 2: record() stores an entry
```
Start a journal. Call record() with full metadata.
Call get_reasoning_chain(agent_id) — assert 1 entry with correct fields.
```

### Test 3: record() is fire-and-forget (no db = no crash)
```
Create a journal with db_path=None. Start it. Call record().
Assert no error raised.
```

### Test 4: get_reasoning_chain returns most recent first
```
Store 5 entries with incrementing timestamps.
get_reasoning_chain(agent_id, limit=3).
Assert 3 entries, first has highest timestamp.
```

### Test 5: get_reasoning_chain filters by agent_id
```
Store entries for agent-A and agent-B.
get_reasoning_chain("agent-A") — assert only A's entries.
```

### Test 6: get_token_usage returns correct totals
```
Store 3 entries with known token counts.
get_token_usage(agent_id) — assert sums match.
Assert cached entries are excluded from totals.
```

### Test 7: get_token_usage ship-wide (no agent_id)
```
Store entries for multiple agents. get_token_usage(None).
Assert totals include all agents.
```

### Test 8: get_stats returns entry counts by type and intent
```
Store entries with different agent_types and intents.
get_stats() — assert total_entries, by_agent_type, by_intent.
```

### Test 9: decide() records to journal
```
Create a CognitiveAgent with a mock runtime that has cognitive_journal.
Mock the journal's record() as AsyncMock.
Call decide() with a mock LLM client.
Assert record() was called with correct agent_id, tier, intent.
Assert latency_ms > 0.
```

### Test 10: decide() cache hit records cached=True
```
Call decide() twice with the same observation (to trigger cache hit).
Assert journal.record() called twice — second call has cached=True.
```

### Test 11: journal failure doesn't block decide()
```
Mock journal.record() to raise an exception.
Call decide() — assert it still returns a valid decision.
```

### Test 12: reset wipes journal db
```
Create runtime with cognitive journal. Store some entries.
Call reset method. Assert cognitive_journal.db is gone.
```

## Constraints

- All journal writes are fire-and-forget with try/except — never block agent cognition.
- Journal uses `INSERT OR IGNORE` — duplicate request_ids are silently skipped.
- `prompt_hash` is a truncated MD5 of the first 500 chars of the prompt — for pattern matching, not security.
- The journal does NOT store full prompt/response text (that would bloat the DB). It stores metadata for tracing. Full text replay is a future enhancement (retention policy, compression).
- The journal survives restart (SQLite persistence). It is wiped on `probos reset` (consistent with episodic memory, Ward Room, etc.).
- `CognitiveJournalConfig.enabled` defaults to `True` — the journal is lightweight and always useful.
- No dependency on Ship's Telemetry — journals directly in `decide()`.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_journal.py -x -v 2>&1 | tail -30
```

Broader validation:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_journal.py tests/test_cognitive_agent.py -x -v 2>&1 | tail -40
```
