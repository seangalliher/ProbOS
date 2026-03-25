# AD-432: Cognitive Journal Expansion — Traceability + Query Depth

## Context

AD-431 delivered the Cognitive Journal MVP: append-only SQLite store recording every LLM call with agent/tier/model/tokens/latency/intent. But the roadmap envisions a "complete token ledger recording every LLM request/response with full context for replay, analysis, and learning." Several gaps remain between the MVP and the full spec.

This AD addresses the highest-impact gaps. Full text storage, replay/summarize, cost pricing, and retention policies are deferred to future ADs.

## Changes

### Step 1: Schema expansion — Add intent_id, dag_node_id, response_hash columns

**File:** `src/probos/cognitive/journal.py`

**1a. Add new columns to `_SCHEMA`** (lines 17-40):

Add three columns to the `journal` table definition, after `response_length`:

```sql
    intent_id        TEXT NOT NULL DEFAULT '',
    dag_node_id      TEXT NOT NULL DEFAULT '',
    response_hash    TEXT NOT NULL DEFAULT ''
```

Add an index for intent_id (after the existing indexes):

```sql
CREATE INDEX IF NOT EXISTS idx_journal_intent_id ON journal(intent_id);
```

**1b. Add migration logic** to `start()` (after `await self._db.executescript(_SCHEMA)`):

The journal is append-only and may have existing data. Add the new columns idempotently:

```python
        # AD-432: Schema migration — add columns if missing
        for col, typedef in [
            ("intent_id", "TEXT NOT NULL DEFAULT ''"),
            ("dag_node_id", "TEXT NOT NULL DEFAULT ''"),
            ("response_hash", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                await self._db.execute(f"ALTER TABLE journal ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # Column already exists
        await self._db.commit()
```

**1c. Update `record()` signature and INSERT** (lines 66-107):

Add three new keyword-only parameters after `response_length`:

```python
        intent_id: str = "",
        dag_node_id: str = "",
        response_hash: str = "",
```

Update the INSERT statement to include the new columns. Change the column list and VALUES placeholder to include `intent_id, dag_node_id, response_hash` and the corresponding `(intent_id, dag_node_id, response_hash)` values tuple.

### Step 2: Plumb intent_id through perceive() → decide() → journal

**File:** `src/probos/cognitive/cognitive_agent.py`

**2a. Pass intent_id through perceive()** (lines 78-91):

The `IntentMessage` has an `id` field (UUID hex) that is currently discarded. Add it to the observation:

```python
    async def perceive(self, intent: Any) -> dict:
        """Package the intent as an observation for the LLM."""
        if isinstance(intent, IntentMessage):
            return {
                "intent": intent.intent,
                "params": intent.params,
                "context": intent.context,
                "intent_id": intent.id,  # AD-432: Preserve for journal traceability
            }
        # Dict fallback (for compatibility with BaseAgent contract)
        return {
            "intent": intent.get("intent", "unknown") if isinstance(intent, dict) else "unknown",
            "params": intent.get("params", {}) if isinstance(intent, dict) else {},
            "context": intent.get("context", "") if isinstance(intent, dict) else "",
        }
```

**2b. Pass intent_id to journal.record()** in decide() (lines 218-234):

In the journal record block (the LLM call path, not the cache hit path), add `intent_id` to the `record()` call:

```python
                    intent_id=observation.get("intent_id", ""),
```

Also add it to the cache-hit journal record (lines 115-122):

```python
                    intent_id=observation.get("intent_id", ""),
```

### Step 3: Add time-range filtering to get_reasoning_chain()

**File:** `src/probos/cognitive/journal.py`

**3a. Add `since` and `until` parameters** to `get_reasoning_chain()` (lines 109-127):

```python
    async def get_reasoning_chain(
        self, agent_id: str, *, limit: int = 20,
        since: float | None = None, until: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent journal entries for an agent, most recent first.

        Args:
            agent_id: Agent to query.
            limit: Max entries to return.
            since: Unix timestamp — only entries after this time.
            until: Unix timestamp — only entries before this time.
        """
        if not self._db:
            return []
        try:
            clauses = ["agent_id = ?"]
            params: list[Any] = [agent_id]
            if since is not None:
                clauses.append("timestamp >= ?")
                params.append(since)
            if until is not None:
                clauses.append("timestamp <= ?")
                params.append(until)
            where = " AND ".join(clauses)
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM journal WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Journal query failed", exc_info=True)
            return []
```

### Step 4: Add grouped token usage query

**File:** `src/probos/cognitive/journal.py`

**4a. Add `get_token_usage_by()` method** (after `get_token_usage()`):

```python
    async def get_token_usage_by(
        self, group_by: str = "model", agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Token usage grouped by a column (model, tier, agent_id, intent).

        Returns a list of dicts with the group key plus token/call stats.
        """
        if not self._db:
            return []
        # Whitelist allowed group columns to prevent SQL injection
        allowed = {"model", "tier", "agent_id", "agent_type", "intent"}
        if group_by not in allowed:
            return []
        try:
            where = "WHERE cached = 0"
            params: list[Any] = []
            if agent_id:
                where += " AND agent_id = ?"
                params.append(agent_id)
            cursor = await self._db.execute(
                f"""SELECT {group_by} as group_key,
                           COUNT(*) as calls,
                           SUM(total_tokens) as tokens,
                           SUM(prompt_tokens) as prompt_tok,
                           SUM(completion_tokens) as comp_tok,
                           AVG(latency_ms) as avg_latency
                    FROM journal {where}
                    GROUP BY {group_by}
                    ORDER BY tokens DESC""",
                params,
            )
            rows = await cursor.fetchall()
            return [
                {
                    group_by: row["group_key"],
                    "total_calls": row["calls"] or 0,
                    "total_tokens": row["tokens"] or 0,
                    "prompt_tokens": row["prompt_tok"] or 0,
                    "completion_tokens": row["comp_tok"] or 0,
                    "avg_latency_ms": round(row["avg_latency"] or 0, 1),
                }
                for row in rows
            ]
        except Exception:
            logger.debug("Journal grouped query failed", exc_info=True)
            return []
```

### Step 5: Add decision points query (anomaly detection)

**File:** `src/probos/cognitive/journal.py`

**5a. Add `get_decision_points()` method** (after `get_token_usage_by()`):

```python
    async def get_decision_points(
        self,
        agent_id: str | None = None,
        *,
        min_latency_ms: float | None = None,
        failures_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find notable decision points — high-latency or failed LLM calls.

        Useful for diagnosing slow agents or finding patterns in failures.
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if min_latency_ms is not None:
                clauses.append("latency_ms >= ?")
                params.append(min_latency_ms)
            if failures_only:
                clauses.append("success = 0")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"""SELECT * FROM journal {where}
                    ORDER BY latency_ms DESC
                    LIMIT ?""",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Journal decision points query failed", exc_info=True)
            return []
```

### Step 6: Add response_hash to decide() journal recording

**File:** `src/probos/cognitive/cognitive_agent.py`

In the journal record block (the LLM call path, lines 218-234), add a response hash. Import `hashlib` at the top of the file if not already imported (it already is — used for `prompt_hash`).

Add to the `record()` call:

```python
                    response_hash=hashlib.md5(response.content[:500].encode()).hexdigest()[:12],
```

### Step 7: Expose new queries via API

**File:** `src/probos/api.py`

**7a. Add time-range params to agent journal endpoint** (lines 1275-1283):

Update the existing `/api/agent/{agent_id}/journal` endpoint to accept optional `since` and `until` query params:

```python
    @app.get("/api/agent/{agent_id}/journal")
    async def agent_journal(
        agent_id: str, limit: int = 20,
        since: float | None = None, until: float | None = None,
    ) -> dict[str, Any]:
        """AD-431: Agent reasoning chain from Cognitive Journal."""
        if not runtime.cognitive_journal:
            return {"entries": []}
        entries = await runtime.cognitive_journal.get_reasoning_chain(
            agent_id, limit=min(limit, 100), since=since, until=until,
        )
        return {"agent_id": agent_id, "entries": entries}
```

**7b. Add grouped token usage endpoint** (after `/api/journal/tokens`):

```python
    @app.get("/api/journal/tokens/by")
    async def journal_token_usage_by(
        group_by: str = "model", agent_id: str | None = None,
    ) -> dict[str, Any]:
        """AD-432: Token usage grouped by model, tier, agent, or intent."""
        if not runtime.cognitive_journal:
            return {"groups": []}
        groups = await runtime.cognitive_journal.get_token_usage_by(
            group_by=group_by, agent_id=agent_id,
        )
        return {"group_by": group_by, "groups": groups}
```

**7c. Add decision points endpoint** (after `/api/journal/tokens/by`):

```python
    @app.get("/api/journal/decisions")
    async def journal_decision_points(
        agent_id: str | None = None,
        min_latency_ms: float | None = None,
        failures_only: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """AD-432: Notable decision points — high-latency or failed LLM calls."""
        if not runtime.cognitive_journal:
            return {"entries": []}
        entries = await runtime.cognitive_journal.get_decision_points(
            agent_id=agent_id,
            min_latency_ms=min_latency_ms,
            failures_only=failures_only,
            limit=min(limit, 100),
        )
        return {"entries": entries}
```

### Step 8: Add `wipe()` method for `probos reset`

**File:** `src/probos/cognitive/journal.py`

Add a `wipe()` method (after `stop()`):

```python
    async def wipe(self) -> None:
        """Delete all journal entries. Used by probos reset."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM journal")
            await self._db.commit()
        except Exception:
            logger.debug("Journal wipe failed", exc_info=True)
```

**File:** `src/probos/runtime.py`

Find the `probos reset` handler (search for `reset` method or `wipe` calls — likely near where episodic_memory and knowledge_store are wiped). Add:

```python
        if self.cognitive_journal:
            await self.cognitive_journal.wipe()
```

## Tests

**File:** `tests/test_cognitive_journal.py` — Add to existing test file.

### Test 1: Schema migration adds new columns to existing DB
```
Create a CognitiveJournal, start() it (creates DB with _SCHEMA).
Stop it. Re-create with same DB path, start() again.
Assert no errors (migration is idempotent).
Record an entry with intent_id, dag_node_id, response_hash.
Query it back and assert the new fields are present.
```

### Test 2: record() stores intent_id, dag_node_id, response_hash
```
Create a CognitiveJournal, start() it.
Call record() with intent_id="abc123", dag_node_id="node-1", response_hash="deadbeef".
Query get_reasoning_chain() and assert the entry has these values.
```

### Test 3: get_reasoning_chain with since filter
```
Record 3 entries with timestamps 100.0, 200.0, 300.0.
Call get_reasoning_chain(agent_id, since=150.0).
Assert returns 2 entries (200.0, 300.0).
```

### Test 4: get_reasoning_chain with until filter
```
Record 3 entries with timestamps 100.0, 200.0, 300.0.
Call get_reasoning_chain(agent_id, until=250.0).
Assert returns 2 entries (200.0, 100.0).
```

### Test 5: get_reasoning_chain with since AND until
```
Record 3 entries with timestamps 100.0, 200.0, 300.0.
Call get_reasoning_chain(agent_id, since=150.0, until=250.0).
Assert returns 1 entry (200.0).
```

### Test 6: get_token_usage_by groups by model
```
Record entries: 2 with model="opus", 1 with model="haiku".
Call get_token_usage_by(group_by="model").
Assert 2 groups, opus group has 2 calls, haiku has 1.
```

### Test 7: get_token_usage_by groups by tier
```
Record entries: 1 tier="standard", 2 tier="fast".
Call get_token_usage_by(group_by="tier").
Assert 2 groups with correct call counts.
```

### Test 8: get_token_usage_by rejects invalid group_by
```
Call get_token_usage_by(group_by="DROP TABLE").
Assert returns empty list (SQL injection prevented).
```

### Test 9: get_token_usage_by with agent_id filter
```
Record entries for 2 agents, different models.
Call get_token_usage_by(group_by="model", agent_id="agent-1").
Assert only agent-1's entries are grouped.
```

### Test 10: get_decision_points returns high-latency entries
```
Record 3 entries with latency_ms=100, 500, 1000.
Call get_decision_points(min_latency_ms=400).
Assert returns 2 entries, ordered by latency DESC.
```

### Test 11: get_decision_points failures_only
```
Record 3 entries: 2 success, 1 failure.
Call get_decision_points(failures_only=True).
Assert returns 1 entry (the failure).
```

### Test 12: get_decision_points with agent_id filter
```
Record entries for 2 agents.
Call get_decision_points(agent_id="agent-1", min_latency_ms=0).
Assert only agent-1's entries returned.
```

### Test 13: wipe() deletes all entries
```
Record 3 entries.
Call wipe().
Call get_stats(). Assert total_entries == 0.
```

### Test 14: perceive() includes intent_id from IntentMessage
```
Create a CognitiveAgent.
Call perceive() with an IntentMessage(intent="test", id="abc123").
Assert returned observation has "intent_id" == "abc123".
```

### Test 15: perceive() dict fallback does NOT add intent_id
```
Call perceive() with a plain dict.
Assert returned observation does NOT have "intent_id" key.
```

## Constraints

- Schema migration is idempotent — `ALTER TABLE ADD COLUMN` wrapped in try/except for each column. Safe to run on existing DBs.
- `get_token_usage_by()` uses a whitelist of allowed group columns — prevents SQL injection.
- `intent_id` only propagates when the intent comes as an `IntentMessage` (not dict fallback). This is correct — dict fallback is for legacy/compatibility paths that don't have traceability.
- `response_hash` is MD5 of first 500 chars — same approach as `prompt_hash`. Not cryptographic — just a fingerprint for dedup detection.
- `wipe()` uses DELETE, not DROP TABLE — preserves schema for immediate re-use after reset.
- The `dag_node_id` column is plumbed in the schema but NOT yet populated in `decide()`. Populating it requires changes to `submit_intent()` in runtime.py to pass the DAG node ID through, which is Step 3 → separate future AD. The column exists as a placeholder for forward compatibility.
- DreamingEngine integration (reading journal for dream consolidation) is deferred — requires design decisions about what dream insights the journal should inform.
- Cost/pricing data is deferred — no model pricing configuration exists anywhere in the codebase yet.
- Full prompt/response text storage is deferred — privacy and storage size implications need design.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_journal.py -x -v 2>&1 | tail -30
```

Broader validation:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_journal.py tests/test_cognitive_agent.py -x -v 2>&1 | tail -40
```
