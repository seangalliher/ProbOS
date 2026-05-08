# AD-700b v1 — Cognitive Journal level tagging for `diagnose_system`

**Issue:** [#508](https://github.com/seangalliher/ProbOS/issues/508)
**Type:** Architecture Decision (telemetry — single field addition)
**Depends on:** AD-700 (DiagnosticLevel + parse_level shipped); AD-431/432 (CognitiveJournal substrate).
**Wave:** 129

## Goal

Cognitive Journal already records every LLM call's `(agent_id, agent_type, tier, model, latency_ms, intent, ...)`. AD-700 introduced multi-level diagnostics, but the journal cannot answer "how often does the Diagnostician run at L1 vs L3?" — the depth is invisible. AD-700b adds a single `level` column (string, e.g. `"L1"`) and a corresponding `level_rank` column (int 1..5) to the journal table, populated only when the intent is `diagnose_system`. Existing rows tolerate the migration; absent values are persisted as empty/`0`.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/cognitive/journal.py:21–48` defines `_SCHEMA_BASE` for the `journal` table. Current columns: `id, timestamp, agent_id, agent_type, tier, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, intent, success, cached, request_id, prompt_hash, response_length, intent_id, dag_node_id, response_hash, procedure_id, correlation_id` — all fixed columns; **no free-form metadata column exists**. The dispatch's "verify-first: confirm whether free-form metadata is accepted" — answer: **NOT accepted; a schema migration is required**.
- ✅ `src/probos/cognitive/journal.py:51–54` defines `_SCHEMA_INDEXES` — the canonical site for new ALTER TABLE migrations is via the `start()` flow at `:197` (`_SCHEMA_BASE`) followed by `:211` (`_SCHEMA_INDEXES`). AD-700b's migration must be added between those steps for forward-compat with empty journal databases.
- ✅ `src/probos/cognitive/journal.py:328–360` `async def record(self, *, entry_id, timestamp, agent_id, ..., correlation_id="")` is the canonical write site — kwarg-only with explicit defaults. New params `level` and `level_rank` follow the same convention.
- ✅ `src/probos/cognitive/journal.py:341` shows the SQL INSERT against the fixed-column table; AD-700b extends this INSERT with the two new columns and adds them to the value tuple.
- ✅ `src/probos/agents/medical/diagnostician.py:73–141` `perceive()` already populates `result["level"] = level.value` and `result["level_rank"] = level.depth_rank` — the call site in `cognitive_agent.py` `_decide_via_llm` reads `observation` keys to build the journal record. **Builder must verify the journal-record call inside `_decide_via_llm()` and pass `observation.get("level", "")` / `observation.get("level_rank", 0)` from there**, gated on `intent == "diagnose_system"` (do not pollute non-diagnostic rows). The exact insertion line (immediately after `correlation_id=observation.get("correlation_id", ""),`) is shown in the inlined snippet below.
- ✅ `src/probos/cognitive/cognitive_agent.py:1722-1748` is the journal-record block. The existing call shape (verified at HEAD):

  ```python
  # cognitive_agent.py:1722-1748 (current)
  if self._cognitive_journal:
      try:
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
              intent_id=observation.get("intent_id", ""),
              response_hash=hashlib.md5(response.content[:500].encode()).hexdigest()[:12],
              correlation_id=observation.get("correlation_id", ""),
          )
      except Exception:
          logger.debug("Journal recording failed", exc_info=True)
  ```

  D4 inserts the new `level=` / `level_rank=` kwargs into this `record(...)` call, gated on `observation.get("intent") == "diagnose_system"`. Existing kwarg ordering and the wrapping `try/except` are preserved.

## Scope

Add two columns (`level`, `level_rank`) to the journal table, migrate existing DBs, extend `record()` to accept the new kwargs, and gate population on `intent == "diagnose_system"`. Do NOT add free-form metadata. Do NOT modify the AD-700 enum, the Diagnostician, or the journal's existing query API.

## Deliverables

### D1. Schema additions in `src/probos/cognitive/journal.py`

Append two columns to `_SCHEMA_BASE`'s journal table definition:

```sql
level            TEXT NOT NULL DEFAULT '',
level_rank       INTEGER NOT NULL DEFAULT 0
```

Place after `correlation_id   TEXT NOT NULL DEFAULT ''` (last current column). Ensure trailing comma is correct.

Add an index for level lookup in `_SCHEMA_INDEXES`:

```sql
CREATE INDEX IF NOT EXISTS idx_journal_level ON journal(level);
```

### D2. Add `_migrate_ad700b()` to `CognitiveJournal`

Mirror BF-031's pattern (split base / migration / dependent indexes). Insert after `_SCHEMA_BASE` is executed and BEFORE `_SCHEMA_INDEXES` is executed, in the `start()` flow.

```python
async def _migrate_ad700b(self) -> None:
    """AD-700b: Add level + level_rank columns if missing."""
    if not self._db:
        return
    try:
        async with self._db.execute("PRAGMA table_info(journal)") as cursor:
            columns = {row[1] async for row in cursor}
        migrations = []
        if "level" not in columns:
            migrations.append(
                "ALTER TABLE journal ADD COLUMN level TEXT NOT NULL DEFAULT ''"
            )
        if "level_rank" not in columns:
            migrations.append(
                "ALTER TABLE journal ADD COLUMN level_rank INTEGER NOT NULL DEFAULT 0"
            )
        for sql in migrations:
            await self._db.execute(sql)
        if migrations:
            await self._db.commit()
            logger.info(
                "AD-700b: Migrated CognitiveJournal level tags (%d columns added)",
                len(migrations),
            )
    except Exception:
        logger.debug("AD-700b: CognitiveJournal migration check failed", exc_info=True)
```

Wire into `start()` between `_SCHEMA_BASE` execution and `_SCHEMA_INDEXES` execution (BF-031 ordering).

### D3. Extend `record()` signature

Add two trailing keyword-only parameters (preserving the existing kwargs):

```python
level: str = "",
level_rank: int = 0,
```

Extend the INSERT statement and value tuple to include `level, level_rank`.

### D4. Populate from `cognitive_agent._decide_via_llm`

In the existing journal-record block at `cognitive_agent.py:1722-1748` (inlined in Verified-Against-Codebase above), when `observation.get("intent") == "diagnose_system"`, append two new kwargs **after** `correlation_id=observation.get("correlation_id", ""),` and **inside** the existing `record(...)` call:

```python
level=str(observation.get("level", "")) if observation.get("intent") == "diagnose_system" else "",
level_rank=int(observation.get("level_rank", 0)) if observation.get("intent") == "diagnose_system" else 0,
```

Non-diagnostic intents fall to the empty-string / zero defaults, preserving journal readability for non-diagnostic rows. The wrapping `try/except Exception: logger.debug(...)` is unchanged.

### D5. Tests in `tests/test_ad700b_journal_level_tag.py`

Minimum 6 tests using a tmp_path SQLite + asyncio:

1. `test_record_diagnose_system_l3_writes_level_and_rank` — `record(intent="diagnose_system", level="L3", level_rank=3, ...)`; query confirms both columns.
2. `test_record_non_diagnose_intent_keeps_level_empty` — `record(intent="medical_alert", ...)` with no level kwarg; row stores `level=""` and `level_rank=0`.
3. `test_record_l1_l5_round_trip` — write all five levels in five rows; query and confirm round-trip.
4. `test_migration_adds_columns_to_pre_ad700b_journal` — pre-create a journal DB with the AD-431/432 schema only; `start()` runs the migration; `PRAGMA table_info` shows both new columns.
5. `test_migration_idempotent` — call `_migrate_ad700b()` twice; no error, no duplicate columns.
6. `test_idx_journal_level_exists_after_start` — `PRAGMA index_list(journal)` includes `idx_journal_level`.

## Non-Goals

- Do NOT add a query API for filtering by level — that's a separate AD if/when needed.
- Do NOT add free-form metadata (per dispatch verify-first finding: schema is fixed-column).
- Do NOT modify `DiagnosticianAgent.perceive()` — `level`/`level_rank` are already populated there.
- Do NOT change the journal `record()` signature for non-diagnostic intents.
- Do NOT modify `_SCHEMA_CHAIN_TRACES`, `_SCHEMA_CAUSAL_TEMPLATES`, `_SCHEMA_OPTIMIZATION_*`.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.

## Acceptance

- Focused: `pytest tests/test_ad700b_journal_level_tag.py -v -n 0` — 6/6 pass.
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes. Existing journal tests (test_cognitive_journal.py) must continue to pass.
- `git diff` shows changes only in: `src/probos/cognitive/journal.py`, `src/probos/cognitive/cognitive_agent.py` (one block in `_decide_via_llm`), and the new test file.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#508](https://github.com/seangalliher/ProbOS/issues/508).
- DECISIONS.md entry stub: AD-700b — added `level` + `level_rank` columns to CognitiveJournal; populated only on `diagnose_system` rows; standard ALTER TABLE migration pattern.

## Revision (2026-05-08)

- **Recommended #1 applied**: Inlined the existing `await self._cognitive_journal.record(...)` call at `cognitive_agent.py:1722-1748` in Verified-Against-Codebase (line range corrected from the soft cite "1660-1740" to the exact 1722-1748). D4 now shows the precise insertion point (after `correlation_id=...`) and uses an inline ternary so the gating is explicit at the kwarg level.
