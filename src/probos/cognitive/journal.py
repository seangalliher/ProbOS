"""Cognitive Journal — append-only LLM reasoning trace store.

Records every LLM call with agent, tier, model, tokens, latency, and
intent linkage.  Ship's Computer infrastructure service (no identity).
AD-431.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

_SCHEMA_BASE = """
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
    response_length  INTEGER NOT NULL DEFAULT 0,
    intent_id        TEXT NOT NULL DEFAULT '',
    dag_node_id      TEXT NOT NULL DEFAULT '',
    response_hash    TEXT NOT NULL DEFAULT '',
    procedure_id     TEXT NOT NULL DEFAULT '',
    correlation_id   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_journal_agent ON journal(agent_id);
CREATE INDEX IF NOT EXISTS idx_journal_timestamp ON journal(timestamp);
CREATE INDEX IF NOT EXISTS idx_journal_intent ON journal(intent);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_journal_intent_id ON journal(intent_id);
CREATE INDEX IF NOT EXISTS idx_journal_correlation_id ON journal(correlation_id);
"""

_SCHEMA_CHAIN_TRACES = """
CREATE TABLE IF NOT EXISTS chain_traces (
    chain_id            TEXT NOT NULL,
    step_index          INTEGER NOT NULL,
    step_name           TEXT NOT NULL,
    sub_task_type       TEXT NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'standard',
    chain_source        TEXT NOT NULL DEFAULT '',
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_type          TEXT NOT NULL DEFAULT '',
    intent              TEXT NOT NULL DEFAULT '',
    intent_id           TEXT NOT NULL DEFAULT '',
    started_at          REAL NOT NULL DEFAULT 0.0,
    duration_ms         REAL NOT NULL DEFAULT 0.0,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    success             INTEGER NOT NULL DEFAULT 1,
    error_truncated     TEXT NOT NULL DEFAULT '',
    context_keys_declared INTEGER NOT NULL DEFAULT 0,
    context_keys_passed   INTEGER NOT NULL DEFAULT 0,
    context_filter_applied INTEGER NOT NULL DEFAULT 0,
    communication_context TEXT,
    chain_trust_band      TEXT,
    trust_score           REAL,
    boot_camp_active      INTEGER NOT NULL DEFAULT 0,
    from_captain          INTEGER NOT NULL DEFAULT 0,
    is_dm                 INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chain_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_chain_traces_started_at ON chain_traces(started_at);
CREATE INDEX IF NOT EXISTS idx_chain_traces_agent ON chain_traces(agent_id);
CREATE INDEX IF NOT EXISTS idx_chain_traces_chain_id ON chain_traces(chain_id);
"""

_SCHEMA_CAUSAL_TEMPLATES = """
CREATE TABLE IF NOT EXISTS causal_templates (
    template_id         TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    triggered_at        REAL NOT NULL DEFAULT 0.0,
    trigger_summary     TEXT NOT NULL DEFAULT '',
    what_changed        TEXT NOT NULL DEFAULT '[]',
    confounded_variables TEXT NOT NULL DEFAULT '[]',
    testable_hypotheses TEXT NOT NULL DEFAULT '[]',
    diagnostic_actions  TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.0,
    source_event_ref    TEXT,
    ranked_hypotheses_json TEXT,
    recommended_actions_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_causal_templates_triggered_at ON causal_templates(triggered_at);
CREATE INDEX IF NOT EXISTS idx_causal_templates_agent ON causal_templates(agent_id);
"""

# AD-660b: idempotent migration for warm-boot DBs created under AD-660 v1.
_MIGRATIONS_CAUSAL_TEMPLATES_AD660B = (
    "ALTER TABLE causal_templates ADD COLUMN ranked_hypotheses_json TEXT",
    "ALTER TABLE causal_templates ADD COLUMN recommended_actions_json TEXT",
)

# AD-658a: idempotent migration for warm-boot DBs created under AD-658 v1.
_MIGRATIONS_CHAIN_TRACES_AD658A = (
    "ALTER TABLE chain_traces ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chain_traces ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
)

# AD-659b: ChainOptimizer proposal persistence (net-new table; no warm-boot migration).
_SCHEMA_OPTIMIZATION_PROPOSALS = """
CREATE TABLE IF NOT EXISTS optimization_proposals (
    proposal_id        TEXT PRIMARY KEY,
    detector_name      TEXT NOT NULL DEFAULT '',
    target_parameter   TEXT NOT NULL DEFAULT '',
    current_value_json TEXT NOT NULL DEFAULT 'null',
    proposed_value_json TEXT NOT NULL DEFAULT 'null',
    rationale          TEXT NOT NULL DEFAULT '',
    supporting_metric  TEXT NOT NULL DEFAULT '',
    risk_level         TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL DEFAULT 0.0,
    decision           TEXT,
    decided_at         REAL,
    decided_by         TEXT,
    applied            INTEGER NOT NULL DEFAULT 0,
    applied_at         REAL,
    applied_by         TEXT,
    pre_apply_value_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_optimization_proposals_created_at
    ON optimization_proposals(created_at);
CREATE INDEX IF NOT EXISTS idx_optimization_proposals_dedup_key
    ON optimization_proposals(detector_name, target_parameter, decision);
"""

# AD-659c: OptimizationCounselor watchdog decision audit trail (net-new table).
_SCHEMA_OPTIMIZATION_DECISIONS = """
CREATE TABLE IF NOT EXISTS optimization_decisions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id        TEXT NOT NULL DEFAULT '',
    decided_at         REAL NOT NULL DEFAULT 0.0,
    decision           TEXT NOT NULL DEFAULT '',
    baseline_success_rate REAL,
    post_success_rate  REAL,
    drop_amount        REAL,
    sample_count_baseline INTEGER NOT NULL DEFAULT 0,
    sample_count_post  INTEGER NOT NULL DEFAULT 0,
    auto_revert_attempted INTEGER NOT NULL DEFAULT 0,
    auto_revert_succeeded INTEGER NOT NULL DEFAULT 0,
    detail             TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_optimization_decisions_proposal
    ON optimization_decisions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_optimization_decisions_decided_at
    ON optimization_decisions(decided_at);
"""


class CognitiveJournal:
    """Append-only SQLite journal for LLM reasoning traces."""

    def __init__(self, db_path: str | None = None, connection_factory: ConnectionFactory | None = None) -> None:
        self.db_path = db_path
        self._db: Any = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if not self.db_path:
            return
        import aiosqlite
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        self._db.row_factory = __import__("aiosqlite").Row
        # AD-432: Migrate columns BEFORE full schema (indexes reference them)
        # Create base table first (without AD-432 columns for pre-existing DBs)
        await self._db.executescript(_SCHEMA_BASE)
        for col, typedef in [
            ("intent_id", "TEXT NOT NULL DEFAULT ''"),
            ("dag_node_id", "TEXT NOT NULL DEFAULT ''"),
            ("response_hash", "TEXT NOT NULL DEFAULT ''"),
            ("procedure_id", "TEXT NOT NULL DEFAULT ''"),  # AD-534: procedure replay tracking
            ("correlation_id", "TEXT NOT NULL DEFAULT ''"),  # AD-492: cognitive correlation ID
        ]:
            try:
                await self._db.execute(f"ALTER TABLE journal ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
        await self._db.commit()
        # Now create indexes that depend on migrated columns
        await self._db.executescript(_SCHEMA_INDEXES)
        # AD-658: chain harness traces (separate from per-LLM-call journal rows)
        await self._db.executescript(_SCHEMA_CHAIN_TRACES)
        # AD-660: causal-reasoning templates
        await self._db.executescript(_SCHEMA_CAUSAL_TEMPLATES)
        # AD-660b: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-660b.
        for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # AD-658a: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-658a.
        for stmt in _MIGRATIONS_CHAIN_TRACES_AD658A:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # AD-659b: ChainOptimizer proposal persistence (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_PROPOSALS)
        # AD-659c: OptimizationCounselor watchdog decisions (idempotent CREATE).
        await self._db.executescript(_SCHEMA_OPTIMIZATION_DECISIONS)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def wipe(self) -> None:
        """Delete all journal entries. Used by probos reset."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM journal")
            await self._db.commit()
        except Exception:
            logger.debug("Journal wipe failed", exc_info=True)

    async def prune(self, retention_days: int = 14, max_rows: int = 500_000) -> int:
        """Delete journal entries older than retention_days and enforce max_rows.

        Returns number of rows deleted.
        """
        if not self._db:
            return 0

        import time as _time
        deleted = 0

        # Age-based pruning (timestamp is Unix epoch float)
        if retention_days > 0:
            cutoff = _time.time() - (retention_days * 86400)
            cursor = await self._db.execute(
                "DELETE FROM journal WHERE timestamp < ?", (cutoff,)
            )
            deleted += cursor.rowcount

        # AD-658: extend retention to chain_traces
        if retention_days > 0:
            cursor = await self._db.execute(
                "DELETE FROM chain_traces WHERE started_at < ?", (cutoff,)
            )
            deleted += cursor.rowcount

        # Row-count cap
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM journal")
            row = await cursor.fetchone()
            total = row[0] if row else 0
            if total > max_rows:
                excess = total - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM journal WHERE id IN "
                    "(SELECT id FROM journal ORDER BY timestamp ASC LIMIT ?)",
                    (excess,)
                )
                deleted += cursor.rowcount

        # AD-658: row-count cap on chain_traces
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM chain_traces")
            row = await cursor.fetchone()
            total_traces = row[0] if row else 0
            if total_traces > max_rows:
                excess = total_traces - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM chain_traces WHERE rowid IN "
                    "(SELECT rowid FROM chain_traces ORDER BY started_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount

        # AD-660: extend retention + row-cap to causal_templates
        if retention_days > 0:
            cursor = await self._db.execute(
                "DELETE FROM causal_templates WHERE triggered_at < ?", (cutoff,)
            )
            deleted += cursor.rowcount
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM causal_templates")
            row = await cursor.fetchone()
            total_templates = row[0] if row else 0
            if total_templates > max_rows:
                excess = total_templates - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM causal_templates WHERE rowid IN "
                    "(SELECT rowid FROM causal_templates ORDER BY triggered_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("CognitiveJournal pruned: %d entries removed", deleted)

        return deleted

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
        intent_id: str = "",
        dag_node_id: str = "",
        response_hash: str = "",
        procedure_id: str = "",  # AD-534: procedure ID if this was a replay
        correlation_id: str = "",  # AD-492: cognitive cycle correlation ID
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
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Journal record failed", exc_info=True)

    async def record_chain_trace(self, trace: Any) -> None:
        """AD-658: Append a chain-step trace row. Fire-and-forget — never raises.

        Accepts a ChainExecutionTrace (or any object with the same field set
        accessible via attribute lookup). Conflicts on (chain_id, step_index)
        are silently dropped via INSERT OR IGNORE — chain steps are write-once.
        """
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO chain_traces
                   (chain_id, step_index, step_name, sub_task_type, tier,
                    chain_source, agent_id, agent_type, intent, intent_id,
                    started_at, duration_ms, tokens_used,
                    prompt_tokens, completion_tokens,
                    success, error_truncated,
                    context_keys_declared, context_keys_passed, context_filter_applied,
                    communication_context, chain_trust_band, trust_score,
                    boot_camp_active, from_captain, is_dm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.chain_id, trace.step_index, trace.step_name,
                    trace.sub_task_type, trace.tier, trace.chain_source,
                    trace.agent_id, trace.agent_type, trace.intent, trace.intent_id,
                    trace.started_at, trace.duration_ms, trace.tokens_used,
                    # AD-658a: defensive getattr — tolerates pre-AD-658a trace objects
                    # produced by external test fixtures or stub journals.
                    getattr(trace, "prompt_tokens", 0),
                    getattr(trace, "completion_tokens", 0),
                    1 if trace.success else 0, trace.error_truncated,
                    trace.context_keys_declared, trace.context_keys_passed,
                    1 if trace.context_filter_applied else 0,
                    trace.communication_context, trace.chain_trust_band,
                    trace.trust_score,
                    1 if trace.boot_camp_active else 0,
                    1 if trace.from_captain else 0,
                    1 if trace.is_dm else 0,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Chain trace record failed", exc_info=True)

    async def get_recent_chain_traces(
        self,
        *,
        limit: int = 50,
        agent_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """AD-658: Return recent chain-step traces, most recent first.

        Args:
            limit: Max rows (capped by caller; default 50).
            agent_id: Optional filter by agent.
            since: Optional Unix-timestamp lower bound on started_at.
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id is not None:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if since is not None:
                clauses.append("started_at >= ?")
                params.append(since)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM chain_traces {where} ORDER BY started_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []

    async def record_optimization_proposal(self, proposal: Any) -> None:
        """AD-659b: Persist or update a single OptimizationProposal.

        Uses INSERT OR REPLACE keyed on `proposal_id` so the same call site
        handles initial creation and post-decide / post-apply / post-revert
        updates. Fire-and-forget — never raises.
        """
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR REPLACE INTO optimization_proposals
                   (proposal_id, detector_name, target_parameter,
                    current_value_json, proposed_value_json,
                    rationale, supporting_metric, risk_level, created_at,
                    decision, decided_at, decided_by,
                    applied, applied_at, applied_by, pre_apply_value_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.proposal_id,
                    proposal.detector_name,
                    proposal.target_parameter,
                    json.dumps(proposal.current_value),
                    json.dumps(proposal.proposed_value),
                    proposal.rationale,
                    proposal.supporting_metric,
                    proposal.risk_level,
                    proposal.created_at,
                    proposal.decision,
                    proposal.decided_at,
                    proposal.decided_by,
                    1 if proposal.applied else 0,
                    proposal.applied_at,
                    proposal.applied_by,
                    json.dumps(proposal.pre_apply_value),
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-659b: optimization proposal record failed", exc_info=True)

    async def get_pending_optimization_proposals(
        self, *, detector_name: str | None = None,
        target_parameter: str | None = None,
    ) -> list[dict[str, Any]]:
        """AD-659b: Return undecided (decision IS NULL) proposals, oldest-first.

        Optional dedup-key filter for `(detector_name, target_parameter)` lookups.
        """
        if not self._db:
            return []
        try:
            clauses = ["decision IS NULL"]
            params: list[Any] = []
            if detector_name is not None:
                clauses.append("detector_name = ?")
                params.append(detector_name)
            if target_parameter is not None:
                clauses.append("target_parameter = ?")
                params.append(target_parameter)
            where = "WHERE " + " AND ".join(clauses)
            cursor = await self._db.execute(
                f"SELECT * FROM optimization_proposals {where} ORDER BY created_at ASC",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("AD-659b: pending proposals query failed", exc_info=True)
            return []

    async def get_optimization_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """AD-659b: Fetch a single proposal by id."""
        if not self._db:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT * FROM optimization_proposals WHERE proposal_id = ?",
                (proposal_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            logger.debug("AD-659b: proposal fetch failed", exc_info=True)
            return None

    async def record_optimization_decision(
        self,
        *,
        proposal_id: str,
        decided_at: float,
        decision: str,
        baseline_success_rate: float | None = None,
        post_success_rate: float | None = None,
        drop_amount: float | None = None,
        sample_count_baseline: int = 0,
        sample_count_post: int = 0,
        auto_revert_attempted: bool = False,
        auto_revert_succeeded: bool = False,
        detail: str = "",
    ) -> None:
        """AD-659c: Persist a single OptimizationCounselor watchdog decision.

        INSERT-only (no upsert). Each watchdog observation is a new row.
        Fire-and-forget — never raises.
        """
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO optimization_decisions
                   (proposal_id, decided_at, decision,
                    baseline_success_rate, post_success_rate, drop_amount,
                    sample_count_baseline, sample_count_post,
                    auto_revert_attempted, auto_revert_succeeded, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id,
                    decided_at,
                    decision,
                    baseline_success_rate,
                    post_success_rate,
                    drop_amount,
                    sample_count_baseline,
                    sample_count_post,
                    1 if auto_revert_attempted else 0,
                    1 if auto_revert_succeeded else 0,
                    detail,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("AD-659c: optimization decision record failed", exc_info=True)

    async def get_recent_optimization_decisions(
        self,
        *,
        limit: int = 50,
        proposal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """AD-659c: Return recent watchdog decisions, newest-first.

        Optional `proposal_id` filter for per-proposal audit lookups.
        """
        if not self._db:
            return []
        try:
            if proposal_id is not None:
                cursor = await self._db.execute(
                    "SELECT * FROM optimization_decisions "
                    "WHERE proposal_id = ? ORDER BY decided_at DESC LIMIT ?",
                    (proposal_id, limit),
                )
            else:
                cursor = await self._db.execute(
                    "SELECT * FROM optimization_decisions "
                    "ORDER BY decided_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("AD-659c: optimization decisions query failed", exc_info=True)
            return []

    async def record_causal_template(self, template: Any) -> None:
        """AD-660: Persist a CausalReasoningTemplate. Fire-and-forget — never raises.

        Accepts any object exposing the CausalReasoningTemplate field set
        via attribute lookup. List fields are JSON-serialized; triggered_at
        is stored as Unix-epoch float (datetime.timestamp()). Conflict on
        template_id is silently dropped via INSERT OR IGNORE.
        """
        if not self._db:
            return
        try:
            triggered_ts = template.triggered_at.timestamp()
            await self._db.execute(
                """INSERT OR IGNORE INTO causal_templates
                   (template_id, agent_id, triggered_at, trigger_summary,
                    what_changed, confounded_variables, testable_hypotheses,
                    diagnostic_actions, confidence, source_event_ref,
                    ranked_hypotheses_json, recommended_actions_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    template.template_id,
                    template.agent_id,
                    triggered_ts,
                    template.trigger_summary,
                    json.dumps(template.what_changed),
                    json.dumps(template.confounded_variables),
                    json.dumps(template.testable_hypotheses),
                    json.dumps(template.diagnostic_actions),
                    float(template.confidence),
                    template.source_event_ref,
                    json.dumps(getattr(template, "ranked_hypotheses", []) or []),
                    json.dumps(getattr(template, "recommended_actions", []) or []),
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Causal template record failed", exc_info=True)

    async def get_recent_causal_templates(
        self,
        *,
        limit: int = 50,
        agent_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """AD-660: Return recent causal templates, most recent first.

        Args:
            limit: Max rows.
            agent_id: Optional filter by agent.
            since: Optional Unix-timestamp lower bound on triggered_at.

        List fields are returned JSON-decoded back to list[str].
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id is not None:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if since is not None:
                clauses.append("triggered_at >= ?")
                params.append(since)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM causal_templates {where} ORDER BY triggered_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = json.loads(raw) if isinstance(raw, str) else []
                    except (ValueError, TypeError):
                        d[key] = []
                # AD-660b: decode list-of-dict columns (default to empty list)
                for json_col, dest_key in (
                    ("ranked_hypotheses_json", "ranked_hypotheses"),
                    ("recommended_actions_json", "recommended_actions"),
                ):
                    raw = d.pop(json_col, None) if json_col in d else None
                    if not isinstance(raw, str):
                        d[dest_key] = []
                        continue
                    try:
                        decoded = json.loads(raw)
                        d[dest_key] = decoded if isinstance(decoded, list) else []
                    except (ValueError, TypeError):
                        d[dest_key] = []
                out.append(d)
            return out
        except Exception:
            logger.debug("Causal template query failed", exc_info=True)
            return []

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

    async def get_token_usage_since(
        self, agent_id: str, since_timestamp: float
    ) -> int:
        """AD-617b: Get total tokens used by an agent since a given timestamp.

        Returns total_tokens (int). Used for hourly budget enforcement.
        Returns 0 on error (fail-open for queries, fail-closed for enforcement
        happens at the caller).
        """
        if not self._db:
            return 0
        try:
            cursor = await self._db.execute(
                """SELECT COALESCE(SUM(total_tokens), 0) as tokens
                   FROM journal
                   WHERE agent_id = ? AND timestamp >= ? AND cached = 0""",
                (agent_id, since_timestamp),
            )
            row = await cursor.fetchone()
            return int(row["tokens"]) if row else 0
        except Exception:
            logger.debug("Journal hourly query failed", exc_info=True)
            return 0

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
