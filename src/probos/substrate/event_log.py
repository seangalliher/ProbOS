"""Append-only event log — SQLite-backed lifecycle and system event log."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probos.protocols import (
    ConnectionFactory,
    CooperationSignatureAggregate,
    CooperationSignatureGroup,
    DatabaseConnection,
    EventLogJsonValue,
    EventLogQueryAudit,
    EventLogQueryBatch,
    EventLogQueryRow,
    EventLogQuerySpec,
)
from probos.security.pii_redaction import PIIRedactor

logger = logging.getLogger(__name__)

_MAX_QUERY_ROWS = 200
_MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60
_MAX_JSON_DEPTH = 4
_MAX_JSON_CONTAINER_ITEMS = 32
_MAX_JSON_STRING_CHARS = 512
_MAX_RAW_DATA_BYTES = 16_384
_MAX_SERIALIZED_ROW_BYTES = 4_096
_MAX_AGGREGATE_GROUPS = 10
_TRUNCATION_MARKER = "[TRUNCATED]"
_TRUNCATED_DATA: dict[str, EventLogJsonValue] = {"_truncated": True}
_SECRET_KEY_PARTS = (
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "refresh_token",
    "secret",
    "token",
)
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_AUDIT_OUTCOMES = frozenset({"success", "denied", "invalid", "failed"})
_AUDIT_AGGREGATES = frozenset({"none", "cooperation_signature"})
_AUDIT_DETAILS = {
    "success": "Governed EventLog query succeeded.",
    "denied": "Governed EventLog query was denied.",
    "invalid": "Governed EventLog query was invalid.",
    "failed": "Governed EventLog query failed.",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    event           TEXT    NOT NULL,
    agent_id        TEXT,
    agent_type      TEXT,
    pool            TEXT,
    detail          TEXT,
    correlation_id  TEXT,
    parent_event_id INTEGER,
    data            TEXT,
    prev_hash       TEXT NOT NULL DEFAULT '',
    row_hash        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_category ON events (category);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events (agent_id);
"""


def _compute_row_hash(*, prev_hash: str, payload: dict[str, Any]) -> str:
    """SHA-256 over (prev_hash || canonical_json(payload)) — AD-490.

    Mirrors AD-456 AuditLog._hash() but operates on a serialized row dict.
    Canonical form = ``json.dumps(payload, sort_keys=True, default=str)``
    so the same row produces the same hash on rehash during verification.
    """
    serialized = json.dumps(payload, sort_keys=True, default=str)
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(serialized.encode("utf-8"))
    return h.hexdigest()


def _bounded_redacted_text(value: object, cap: int) -> tuple[str, bool]:
    if type(value) is not str:
        raise ValueError("event_log_query_invalid:stored_text")
    redacted = PIIRedactor.redact_all(value)
    if len(redacted) <= cap:
        return redacted, False
    prefix_length = max(0, cap - len(_TRUNCATION_MARKER))
    return redacted[:prefix_length] + _TRUNCATION_MARKER[:cap], True


def _bounded_optional_text(value: object, cap: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return _bounded_redacted_text(value, cap)


def _bounded_utf8_text(value: str, byte_cap: int) -> tuple[str, bool]:
    if len(value.encode("utf-8")) <= byte_cap:
        return value, False
    marker = _TRUNCATION_MARKER
    marker_bytes = len(marker.encode("utf-8"))
    prefix_budget = max(0, byte_cap - marker_bytes)
    prefix: list[str] = []
    used = 0
    for character in value:
        encoded_length = len(character.encode("utf-8"))
        if used + encoded_length > prefix_budget:
            break
        prefix.append(character)
        used += encoded_length
    return "".join(prefix) + marker, True


def _bounded_optional_utf8_text(
    value: str | None,
    byte_cap: int,
) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return _bounded_utf8_text(value, byte_cap)


def _truncated_data() -> dict[str, EventLogJsonValue]:
    return dict(_TRUNCATED_DATA)


def _detach_json_value(
    value: object,
    *,
    depth: int = 0,
) -> tuple[EventLogJsonValue, bool]:
    if value is None:
        return None, False
    if type(value) is bool:
        return value, False
    if type(value) is int:
        if _INT64_MIN <= value <= _INT64_MAX:
            return value, False
        return _truncated_data(), True
    if type(value) is float:
        if math.isfinite(value):
            return value, False
        return _truncated_data(), True
    if type(value) is str:
        return _bounded_redacted_text(value, _MAX_JSON_STRING_CHARS)
    if type(value) is dict:
        if depth >= _MAX_JSON_DEPTH:
            return _truncated_data(), True
        source: dict[object, object] = value
        overflow = len(source) > _MAX_JSON_CONTAINER_ITEMS
        inspect_limit = (
            _MAX_JSON_CONTAINER_ITEMS - 1
            if overflow
            else _MAX_JSON_CONTAINER_ITEMS
        )
        detached: dict[str, EventLogJsonValue] = {}
        truncated = overflow
        for index, (raw_key, raw_value) in enumerate(source.items()):
            if index >= inspect_limit:
                break
            if type(raw_key) is not str:
                truncated = True
                continue
            key, key_truncated = _bounded_redacted_text(
                raw_key, _MAX_JSON_STRING_CHARS
            )
            if key in detached:
                truncated = True
                continue
            if any(part in raw_key.casefold() for part in _SECRET_KEY_PARTS):
                detached[key] = "[REDACTED]"
                truncated = truncated or key_truncated
                continue
            child, child_truncated = _detach_json_value(
                raw_value,
                depth=depth + 1,
            )
            detached[key] = child
            truncated = truncated or key_truncated or child_truncated
        if overflow:
            detached["_truncated"] = True
        return detached, truncated
    if type(value) is list:
        if depth >= _MAX_JSON_DEPTH:
            return _truncated_data(), True
        source_list: list[object] = value
        overflow = len(source_list) > _MAX_JSON_CONTAINER_ITEMS
        inspect_limit = (
            _MAX_JSON_CONTAINER_ITEMS - 1
            if overflow
            else _MAX_JSON_CONTAINER_ITEMS
        )
        detached_items: list[EventLogJsonValue] = []
        truncated = overflow
        for index, raw_item in enumerate(source_list):
            if index >= inspect_limit:
                break
            child, child_truncated = _detach_json_value(
                raw_item,
                depth=depth + 1,
            )
            detached_items.append(child)
            truncated = truncated or child_truncated
        if overflow:
            detached_items.append(_truncated_data())
        return tuple(detached_items), truncated
    return _truncated_data(), True


def _decode_event_data(raw_data: object) -> tuple[object, EventLogJsonValue, bool]:
    if raw_data is None:
        return None, None, False
    if type(raw_data) is not str:
        marker = _truncated_data()
        return marker, marker, True
    try:
        decoded = json.loads(raw_data)
    except (TypeError, ValueError):
        marker = _truncated_data()
        return marker, marker, True
    detached, truncated = _detach_json_value(decoded)
    if decoded == _TRUNCATED_DATA:
        truncated = True
    return decoded, detached, truncated


def _parse_stored_timestamp(value: object) -> datetime:
    if type(value) is not str or len(value) > 64:
        raise ValueError("event_log_query_invalid:stored_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("event_log_query_invalid:stored_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event_log_query_invalid:stored_timestamp")
    return parsed.astimezone(timezone.utc)


def _row_as_json(row: EventLogQueryRow) -> dict[str, object]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.isoformat().replace("+00:00", "Z"),
        "category": row.category,
        "event": row.event,
        "agent_id": row.agent_id,
        "agent_type": row.agent_type,
        "pool": row.pool,
        "detail": row.detail,
        "correlation_id": row.correlation_id,
        "parent_event_id": row.parent_event_id,
        "data": row.data,
    }


def _canonical_json_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _fit_row_to_byte_cap(
    row: EventLogQueryRow,
) -> tuple[EventLogQueryRow, bool]:
    if _canonical_json_size(_row_as_json(row)) <= _MAX_SERIALIZED_ROW_BYTES:
        return row, False
    row = EventLogQueryRow(
        id=row.id,
        timestamp=row.timestamp,
        category=row.category,
        event=row.event,
        agent_id=row.agent_id,
        agent_type=row.agent_type,
        pool=row.pool,
        detail=row.detail,
        correlation_id=row.correlation_id,
        parent_event_id=row.parent_event_id,
        data=_truncated_data(),
    )
    if _canonical_json_size(_row_as_json(row)) <= _MAX_SERIALIZED_ROW_BYTES:
        return row, True

    category, category_truncated = _bounded_utf8_text(row.category, 128)
    event, event_truncated = _bounded_utf8_text(row.event, 128)
    agent_id, agent_id_truncated = _bounded_optional_utf8_text(row.agent_id, 256)
    agent_type, agent_type_truncated = _bounded_optional_utf8_text(
        row.agent_type, 128
    )
    pool, pool_truncated = _bounded_optional_utf8_text(row.pool, 128)
    detail, detail_truncated = _bounded_optional_utf8_text(row.detail, 512)
    correlation_id, correlation_truncated = _bounded_optional_utf8_text(
        row.correlation_id, 256
    )
    fitted = EventLogQueryRow(
        id=row.id,
        timestamp=row.timestamp,
        category=category,
        event=event,
        agent_id=agent_id,
        agent_type=agent_type,
        pool=pool,
        detail=detail,
        correlation_id=correlation_id,
        parent_event_id=row.parent_event_id,
        data=row.data,
    )
    if _canonical_json_size(_row_as_json(fitted)) > _MAX_SERIALIZED_ROW_BYTES:
        raise ValueError("event_log_query_invalid:stored_row_size")
    return fitted, any(
        (
            category_truncated,
            event_truncated,
            agent_id_truncated,
            agent_type_truncated,
            pool_truncated,
            detail_truncated,
            correlation_truncated,
        )
    )


def _validate_governed_spec(
    spec: EventLogQuerySpec,
) -> tuple[datetime, datetime, int]:
    if type(spec) is not EventLogQuerySpec:
        raise ValueError("event_log_query_invalid:spec")
    if type(spec.start_time) is not datetime or type(spec.end_time) is not datetime:
        raise ValueError("event_log_query_invalid:time_type")
    if (
        spec.start_time.tzinfo is None
        or spec.start_time.utcoffset() is None
        or spec.end_time.tzinfo is None
        or spec.end_time.utcoffset() is None
    ):
        raise ValueError("event_log_query_invalid:time_offset")
    start_time = spec.start_time.astimezone(timezone.utc)
    end_time = spec.end_time.astimezone(timezone.utc)
    if start_time >= end_time:
        raise ValueError("event_log_query_invalid:time_order")
    if (end_time - start_time).total_seconds() > _MAX_WINDOW_SECONDS:
        raise ValueError("event_log_query_invalid:window")
    for name, value, cap in (
        ("category", spec.category, 128),
        ("event", spec.event, 128),
        ("correlation_id", spec.correlation_id, 256),
        ("agent_id", spec.agent_id, 256),
    ):
        if value is not None and (
            type(value) is not str or not value or len(value) > cap
        ):
            raise ValueError(f"event_log_query_invalid:{name}")
    if not any(
        value is not None
        for value in (
            spec.category,
            spec.event,
            spec.correlation_id,
            spec.agent_id,
        )
    ):
        raise ValueError("event_log_query_invalid:filter_required")
    if type(spec.limit) is not int or not 1 <= spec.limit <= _MAX_QUERY_ROWS:
        raise ValueError("event_log_query_invalid:limit")
    if type(spec.order) is not str or spec.order not in (
        "newest_first",
        "oldest_first",
    ):
        raise ValueError("event_log_query_invalid:order")
    if type(spec.aggregate) is not str or spec.aggregate not in (
        "none",
        "cooperation_signature",
    ):
        raise ValueError("event_log_query_invalid:aggregate")
    if spec.aggregate == "cooperation_signature" and (
        spec.category != "emergent" or spec.event != "cooperation_cluster"
    ):
        raise ValueError("event_log_query_invalid:aggregate_filters")
    return start_time, end_time, min(spec.limit, _MAX_QUERY_ROWS)


def _extract_cooperation_signature(
    decoded: object,
) -> tuple[tuple[str, ...], float] | None:
    if type(decoded) is not dict:
        return None
    evidence = decoded.get("evidence")
    if type(evidence) is not dict:
        return None
    intents = evidence.get("intents")
    avg_weight = evidence.get("avg_weight")
    if type(intents) is not list or not intents or len(intents) > _MAX_JSON_CONTAINER_ITEMS:
        return None
    normalized_intents: set[str] = set()
    for intent in intents:
        if type(intent) is not str:
            return None
        normalized = intent.strip()
        if not normalized or len(normalized) > _MAX_JSON_STRING_CHARS:
            return None
        redacted, _ = _bounded_redacted_text(normalized, _MAX_JSON_STRING_CHARS)
        normalized_intents.add(redacted)
    if not normalized_intents:
        return None
    if type(avg_weight) is int:
        if not _INT64_MIN <= avg_weight <= _INT64_MAX:
            return None
        numeric_weight = float(avg_weight)
    elif type(avg_weight) is float and math.isfinite(avg_weight):
        numeric_weight = avg_weight
    else:
        return None
    return tuple(sorted(normalized_intents)), round(numeric_weight, 3)


class EventLog:
    """Append-only event log persisted to SQLite.

    Records agent lifecycle events (spawn, active, degraded, recycled),
    mesh events (intent broadcast, intent resolved, gossip exchange),
    and system events (startup, shutdown, pool health check).
    """

    GENESIS_HASH: str = "0" * 64

    def __init__(self, db_path: str | Path, connection_factory: ConnectionFactory | None = None) -> None:
        self.db_path = str(db_path)
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # AD-664: Migrate existing databases — add new columns if missing
        await self._migrate_ad664()
        # AD-490: Add hash chain columns if missing
        await self._migrate_ad490()
        logger.info("EventLog opened: %s", self.db_path)

    async def _migrate_ad664(self) -> None:
        """Add correlation_id, parent_event_id, data columns if missing (AD-664)."""
        if not self._db:
            return
        try:
            async with self._db.execute("PRAGMA table_info(events)") as cursor:
                columns = {row[1] async for row in cursor}
            migrations = []
            if "correlation_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN correlation_id TEXT")
            if "parent_event_id" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN parent_event_id INTEGER")
            if "data" not in columns:
                migrations.append("ALTER TABLE events ADD COLUMN data TEXT")
            for sql in migrations:
                await self._db.execute(sql)
            # Always ensure indexes exist — IF NOT EXISTS makes this idempotent
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events (correlation_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_parent ON events (parent_event_id)"
            )
            if migrations:
                await self._db.commit()
                logger.info("AD-664: Migrated EventLog schema (%d columns added)", len(migrations))
        except Exception:
            logger.debug("AD-664: EventLog migration check failed", exc_info=True)

    async def _migrate_ad490(self) -> None:
        """Add prev_hash, row_hash columns if missing (AD-490)."""
        if not self._db:
            return
        try:
            async with self._db.execute("PRAGMA table_info(events)") as cursor:
                columns = {row[1] async for row in cursor}
            migrations = []
            if "prev_hash" not in columns:
                migrations.append(
                    "ALTER TABLE events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''"
                )
            if "row_hash" not in columns:
                migrations.append(
                    "ALTER TABLE events ADD COLUMN row_hash TEXT NOT NULL DEFAULT ''"
                )
            for sql in migrations:
                await self._db.execute(sql)
            if migrations:
                await self._db.commit()
                logger.info(
                    "AD-490: Migrated EventLog hash chain (%d columns added)",
                    len(migrations),
                )
        except Exception:
            logger.debug("AD-490: EventLog migration check failed", exc_info=True)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def log(
        self,
        category: str,
        event: str,
        agent_id: str | None = None,
        agent_type: str | None = None,
        pool: str | None = None,
        detail: str | None = None,
        *,
        correlation_id: str | None = None,
        parent_event_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None:
        """Append an event to the log.

        Returns the inserted row ID (for parent_event_id chaining),
        or None if the database is not available.

        AD-664: New keyword-only params:
        - correlation_id: groups causally related events
        - parent_event_id: references the preceding event's row ID
        - data: structured payload (dict, JSON-serialized on write)
        """
        if not self._db:
            return None
        now = datetime.now(timezone.utc).isoformat()
        # AD-490: sort_keys=True for deterministic rehash during verify_chain()
        data_json = json.dumps(data, sort_keys=True, default=str) if data is not None else None
        # AD-490: Compute hash chain — read prior row_hash, then chain this row.
        prev_hash = self.GENESIS_HASH
        async with self._db.execute(
            "SELECT row_hash FROM events ORDER BY id DESC LIMIT 1"
        ) as cursor:
            async for row in cursor:
                prior = row[0]
                if prior:
                    prev_hash = prior
                break
        payload = {
            "timestamp": now,
            "category": category,
            "event": event,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "pool": pool,
            "detail": detail,
            "correlation_id": correlation_id,
            "parent_event_id": parent_event_id,
            "data": data_json,
        }
        row_hash = _compute_row_hash(prev_hash=prev_hash, payload=payload)
        cursor = await self._db.execute(
            "INSERT INTO events "
            "(timestamp, category, event, agent_id, agent_type, pool, detail, "
            " correlation_id, parent_event_id, data, prev_hash, row_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, category, event, agent_id, agent_type, pool, detail,
             correlation_id, parent_event_id, data_json, prev_hash, row_hash),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def query(
        self,
        category: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query recent events, optionally filtered.

        AD-664: Results now include correlation_id, parent_event_id, and
        data (deserialized from JSON).
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
        conditions = []
        params: list[str] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(str(limit))

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def query_structured(
        self,
        *,
        correlation_id: str | None = None,
        category: str | None = None,
        event: str | None = None,
        parent_event_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with structured filtering (AD-664).

        Supports querying by correlation_id (causal chain), event name,
        and parent_event_id (direct predecessor).

        Returns same dict shape as query(), with deserialized data field.
        """
        if not self._db:
            return []

        sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
               "pool, detail, correlation_id, parent_event_id, data "
               "FROM events")
        conditions = []
        params: list = []

        if correlation_id is not None:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if event is not None:
            conditions.append("event = ?")
            params.append(event)
        if parent_event_id is not None:
            conditions.append("parent_event_id = ?")
            params.append(parent_event_id)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                rows.append(self._row_to_dict(row))
        return rows

    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch:
        """Return one bounded, redacted EventLog query batch."""
        if self._db is None:
            return EventLogQueryBatch(
                available=False,
                rows=(),
                matched_count=0,
                scanned_count=0,
                truncated=False,
                aggregate=None,
            )

        start_time, end_time, row_limit = _validate_governed_spec(spec)
        conditions = ["timestamp >= ?", "timestamp < ?"]
        params: list[object] = [
            start_time.isoformat(),
            end_time.isoformat(),
        ]
        for column, value in (
            ("category", spec.category),
            ("event", spec.event),
            ("correlation_id", spec.correlation_id),
            ("agent_id", spec.agent_id),
        ):
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        direction = "DESC" if spec.order == "newest_first" else "ASC"
        sql = (
            "SELECT id, "
            "substr(timestamp, 1, 65) AS timestamp, "
            "substr(category, 1, 129) AS category, "
            "substr(event, 1, 129) AS event, "
            "substr(agent_id, 1, 257) AS agent_id, "
            "substr(agent_type, 1, 129) AS agent_type, "
            "substr(pool, 1, 129) AS pool, "
            "substr(detail, 1, 513) AS detail, "
            "substr(correlation_id, 1, 257) AS correlation_id, "
            "parent_event_id, "
            "CASE "
            "WHEN data IS NULL THEN NULL "
            f"WHEN length(CAST(data AS BLOB)) <= {_MAX_RAW_DATA_BYTES} THEN data "
            "ELSE '{\"_truncated\":true}' END AS data "
            "FROM events WHERE "
            + " AND ".join(conditions)
            + f" ORDER BY timestamp {direction}, id {direction} LIMIT ?"
        )
        params.append(row_limit + 1)

        raw_rows: list[tuple[object, ...]] = []
        async with self._db.execute(sql, params) as cursor:
            async for raw_row in cursor:
                raw_rows.append(tuple(raw_row))

        scanned_count = len(raw_rows)
        usable_rows = raw_rows[:row_limit]
        matched_count = len(usable_rows)
        truncated = scanned_count > row_limit
        projected_rows: list[EventLogQueryRow] = []
        signature_counts: Counter[tuple[tuple[str, ...], float]] = Counter()
        valid_signature_rows = 0

        for raw_row in usable_rows:
            if len(raw_row) != 11:
                raise ValueError("event_log_query_invalid:stored_row")
            row_id = raw_row[0]
            parent_event_id = raw_row[9]
            if type(row_id) is not int:
                raise ValueError("event_log_query_invalid:stored_id")
            if parent_event_id is not None and type(parent_event_id) is not int:
                raise ValueError("event_log_query_invalid:stored_parent_id")
            category, category_truncated = _bounded_redacted_text(raw_row[2], 128)
            event, event_truncated = _bounded_redacted_text(raw_row[3], 128)
            agent_id, agent_id_truncated = _bounded_optional_text(raw_row[4], 256)
            agent_type, agent_type_truncated = _bounded_optional_text(raw_row[5], 128)
            pool, pool_truncated = _bounded_optional_text(raw_row[6], 128)
            detail, detail_truncated = _bounded_optional_text(raw_row[7], 512)
            correlation_id, correlation_truncated = _bounded_optional_text(
                raw_row[8], 256
            )
            decoded, data, data_truncated = _decode_event_data(raw_row[10])
            row = EventLogQueryRow(
                id=row_id,
                timestamp=_parse_stored_timestamp(raw_row[1]),
                category=category,
                event=event,
                agent_id=agent_id,
                agent_type=agent_type,
                pool=pool,
                detail=detail,
                correlation_id=correlation_id,
                parent_event_id=parent_event_id,
                data=data,
            )
            row, row_truncated = _fit_row_to_byte_cap(row)
            truncated = truncated or any(
                (
                    category_truncated,
                    event_truncated,
                    agent_id_truncated,
                    agent_type_truncated,
                    pool_truncated,
                    detail_truncated,
                    correlation_truncated,
                    data_truncated,
                    row_truncated,
                )
            )
            if spec.aggregate == "none":
                projected_rows.append(row)
            else:
                signature = _extract_cooperation_signature(decoded)
                if signature is not None:
                    signature_counts[signature] += 1
                    valid_signature_rows += 1

        aggregate = None
        if spec.aggregate == "cooperation_signature":
            ordered_groups = sorted(
                signature_counts.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
            groups_truncated = len(ordered_groups) > _MAX_AGGREGATE_GROUPS
            groups = tuple(
                CooperationSignatureGroup(
                    intents=signature[0],
                    avg_weight=signature[1],
                    count=count,
                )
                for signature, count in ordered_groups[:_MAX_AGGREGATE_GROUPS]
            )
            aggregate_truncated = scanned_count > row_limit or groups_truncated
            aggregate = CooperationSignatureAggregate(
                kind="cooperation_signature",
                total_rows=matched_count,
                valid_signature_rows=valid_signature_rows,
                groups=groups,
                truncated=aggregate_truncated,
            )
            truncated = truncated or aggregate_truncated

        return EventLogQueryBatch(
            available=True,
            rows=tuple(projected_rows),
            matched_count=matched_count,
            scanned_count=scanned_count,
            truncated=truncated,
            aggregate=aggregate,
        )

    async def audit_governed_query(self, audit: EventLogQueryAudit) -> bool:
        """Append content-free governance metadata for one query attempt."""
        if type(audit) is not EventLogQueryAudit:
            raise ValueError("event_log_query_invalid:audit")
        if type(audit.actor_id) is not str:
            raise ValueError("event_log_query_invalid:audit_actor")
        if type(audit.department) is not str or type(audit.rank) is not str:
            raise ValueError("event_log_query_invalid:audit_identity")
        if type(audit.outcome) is not str or audit.outcome not in _AUDIT_OUTCOMES:
            raise ValueError("event_log_query_invalid:audit_outcome")
        if (
            type(audit.aggregate) is not str
            or audit.aggregate not in _AUDIT_AGGREGATES
        ):
            raise ValueError("event_log_query_invalid:audit_aggregate")
        if type(audit.parameter_names) is not tuple:
            raise ValueError("event_log_query_invalid:audit_parameters")
        if audit.window_seconds is not None and (
            type(audit.window_seconds) is not int
            or not 0 <= audit.window_seconds <= _MAX_WINDOW_SECONDS
        ):
            raise ValueError("event_log_query_invalid:audit_window")
        if any(
            type(count) is not int or not 0 <= count <= _MAX_QUERY_ROWS
            for count in (audit.matched_count, audit.returned_count)
        ):
            raise ValueError("event_log_query_invalid:audit_count")
        if audit.returned_count > audit.matched_count:
            raise ValueError("event_log_query_invalid:audit_count_order")
        if type(audit.truncated) is not bool:
            raise ValueError("event_log_query_invalid:audit_truncated")
        actor_id, _ = _bounded_redacted_text(audit.actor_id, 256)
        department, _ = _bounded_redacted_text(audit.department, 64)
        rank, _ = _bounded_redacted_text(audit.rank, 64)
        parameter_names: list[str] = []
        for name in audit.parameter_names[:10]:
            if type(name) is not str:
                raise ValueError("event_log_query_invalid:audit_parameter")
            bounded_name, _ = _bounded_redacted_text(name, 64)
            parameter_names.append(bounded_name)
        row_id = await self.log(
            category="audit",
            event="event_log_query",
            agent_id=actor_id,
            detail=_AUDIT_DETAILS[audit.outcome],
            data={
                "actor_id": actor_id,
                "department": department,
                "rank": rank,
                "outcome": audit.outcome,
                "parameter_names": sorted(set(parameter_names)),
                "window_seconds": audit.window_seconds,
                "aggregate": audit.aggregate,
                "matched_count": audit.matched_count,
                "returned_count": audit.returned_count,
                "truncated": audit.truncated,
            },
        )
        return row_id is not None

    async def get_event_chain(self, event_id: int, max_depth: int = 20) -> list[dict]:
        """Walk the parent_event_id chain from a given event upward (AD-664).

        Returns events from the given event up to the root (parent_event_id is NULL),
        ordered from root to leaf. Stops at max_depth to prevent infinite loops
        from data corruption.
        """
        if not self._db:
            return []

        chain: list[dict] = []
        current_id: int | None = event_id

        for _ in range(max_depth):
            if current_id is None:
                break
            sql = ("SELECT id, timestamp, category, event, agent_id, agent_type, "
                   "pool, detail, correlation_id, parent_event_id, data "
                   "FROM events WHERE id = ?")
            async with self._db.execute(sql, (current_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                break
            chain.append(self._row_to_dict(row))
            current_id = row[9]  # parent_event_id

        chain.reverse()  # root-to-leaf order
        return chain

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        """Convert a SELECT row (11 columns) to a dict with JSON-parsed data."""
        data_raw = row[10]
        try:
            data_parsed = json.loads(data_raw) if data_raw else None
        except (ValueError, TypeError):
            data_parsed = None
        return {
            "id": row[0],
            "timestamp": row[1],
            "category": row[2],
            "event": row[3],
            "agent_id": row[4],
            "agent_type": row[5],
            "pool": row[6],
            "detail": row[7],
            "correlation_id": row[8],
            "parent_event_id": row[9],
            "data": data_parsed,
        }

    async def count(self, category: str | None = None) -> int:
        """Count events, optionally filtered by category."""
        if not self._db:
            return 0
        if category:
            sql = "SELECT COUNT(*) FROM events WHERE category = ?"
            params: tuple = (category,)
        else:
            sql = "SELECT COUNT(*) FROM events"
            params = ()
        async with self._db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_all(self) -> int:
        """Total event count."""
        return await self.count()

    async def verify_chain(self) -> tuple[bool, int | None]:
        """AD-490: Walk the events table by id; return (ok, broken_at).

        Returns (True, None) if every row's row_hash equals the recomputed
        hash of (prev row's row_hash || canonical_json(payload)). Returns
        (False, broken_id) on the first mismatch. Empty table -> (True, None).
        """
        if not self._db:
            return (True, None)
        sql = (
            "SELECT id, timestamp, category, event, agent_id, agent_type, "
            "pool, detail, correlation_id, parent_event_id, data, "
            "prev_hash, row_hash FROM events ORDER BY id ASC"
        )
        expected_prev = self.GENESIS_HASH
        async with self._db.execute(sql) as cursor:
            async for row in cursor:
                payload = {
                    "timestamp": row[1],
                    "category": row[2],
                    "event": row[3],
                    "agent_id": row[4],
                    "agent_type": row[5],
                    "pool": row[6],
                    "detail": row[7],
                    "correlation_id": row[8],
                    "parent_event_id": row[9],
                    "data": row[10],
                }
                stored_prev = row[11]
                stored_row_hash = row[12]
                if stored_prev != expected_prev:
                    return (False, row[0])
                recomputed = _compute_row_hash(prev_hash=expected_prev, payload=payload)
                if recomputed != stored_row_hash:
                    return (False, row[0])
                expected_prev = stored_row_hash
        return (True, None)

    async def prune(self, retention_days: int = 7, max_rows: int = 100_000) -> int:
        """Delete events older than retention_days and enforce max_rows cap.

        Returns number of rows deleted.
        """
        if not self._db:
            return 0

        deleted = 0

        # Age-based pruning
        if retention_days > 0:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
            cursor = await self._db.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff,)
            )
            deleted += cursor.rowcount

        # Row-count cap
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            total = row[0] if row else 0
            if total > max_rows:
                excess = total - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM events WHERE id IN "
                    "(SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                    (excess,)
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("EventLog pruned: %d events removed", deleted)

        return deleted

    async def wipe(self) -> None:
        """Delete all events. Used by probos reset."""
        if not self._db:
            return
        try:
            await self._db.execute("DELETE FROM events")
            await self._db.commit()
        except Exception:
            logger.debug("EventLog wipe failed", exc_info=True)
