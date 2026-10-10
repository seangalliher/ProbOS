from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from probos.protocols import DatabaseConnection


PRIOR_ALPHA = 2
PRIOR_BETA = 2
MAX_SPENDS_PER_OUTCOME = 512
_VALUE_SOURCE_KINDS = frozenset({"captain", "agent"})
_VALUE_BANDS = frozenset({"minor", "moderate", "significant", "critical"})


@dataclass(frozen=True)
class ValueDeclarationIdentity:
    value_band: str
    source_kind: str
    source_id: str
    recorded_at: float


@dataclass(frozen=True)
class SpendPriceSnapshot:
    request_id: str
    provider_request_id: str | None
    requested_tier: str
    effective_tier: str
    tier_outcome: str | None
    tier_evidence: str | None
    model_reason: str | None
    model: str
    token_source: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_price_per_million: float | None
    output_price_per_million: float | None
    currency: str | None
    price_effective_at: float
    provider_reported_prompt_tokens: int | None = None
    provider_reported_completion_tokens: int | None = None
    provider_reported_total_tokens: int | None = None


@dataclass(frozen=True)
class CompletionCalibrationEvidence:
    outcome_id: str
    agent_id: str
    work_type: str
    estimated_tokens: int | None
    actual_tokens: int
    completed_at: float
    spends: tuple[SpendPriceSnapshot, ...] = ()


def completion_calibration_payload(
    evidence: CompletionCalibrationEvidence,
) -> dict[str, object]:
    return {
        "outcome_id": evidence.outcome_id,
        "agent_id": evidence.agent_id,
        "work_type": evidence.work_type,
        "estimated_tokens": evidence.estimated_tokens,
        "actual_tokens": evidence.actual_tokens,
        "completed_at": evidence.completed_at,
        "spends": [
            {
                field: getattr(spend, field)
                for field in SpendPriceSnapshot.__dataclass_fields__
            }
            for spend in evidence.spends
        ],
    }


def completion_calibration_from_payload(
    payload: object,
) -> CompletionCalibrationEvidence:
    if type(payload) is not dict or set(payload) != {
        "outcome_id",
        "agent_id",
        "work_type",
        "estimated_tokens",
        "actual_tokens",
        "completed_at",
        "spends",
    }:
        raise ValueError("completion_calibration_evidence_invalid")
    spends = payload["spends"]
    if type(spends) is not list or len(spends) > MAX_SPENDS_PER_OUTCOME:
        raise ValueError("completion_calibration_evidence_invalid")
    spend_fields = set(SpendPriceSnapshot.__dataclass_fields__)
    legacy_spend_fields = spend_fields - {
        "provider_reported_prompt_tokens",
        "provider_reported_completion_tokens",
        "provider_reported_total_tokens",
    }
    if any(
        type(spend) is not dict
        or set(spend) not in (spend_fields, legacy_spend_fields)
        for spend in spends
    ):
        raise ValueError("completion_calibration_evidence_invalid")
    try:
        normalized_spends = []
        for spend in spends:
            normalized = dict(spend)
            if set(normalized) == legacy_spend_fields:
                normalized.update(
                    provider_reported_prompt_tokens=normalized["prompt_tokens"],
                    provider_reported_completion_tokens=normalized["completion_tokens"],
                    provider_reported_total_tokens=normalized["total_tokens"],
                )
            normalized_spends.append(SpendPriceSnapshot(**normalized))
        return CompletionCalibrationEvidence(
            outcome_id=payload["outcome_id"],
            agent_id=payload["agent_id"],
            work_type=payload["work_type"],
            estimated_tokens=payload["estimated_tokens"],
            actual_tokens=payload["actual_tokens"],
            completed_at=payload["completed_at"],
            spends=tuple(normalized_spends),
        )
    except TypeError as exc:
        raise ValueError("completion_calibration_evidence_invalid") from exc


@dataclass(frozen=True)
class CompletionCalibrationSummary:
    agent_id: str
    work_type: str
    cost_within_alpha: int
    cost_within_beta: int
    cost_under_alpha: int
    cost_under_beta: int
    cost_over_alpha: int
    cost_over_beta: int
    value_match_alpha: int
    value_match_beta: int

    @property
    def cost_samples(self) -> int:
        return self.cost_within_alpha + self.cost_within_beta - PRIOR_ALPHA - PRIOR_BETA

    @property
    def within_count(self) -> int:
        return self.cost_within_alpha - PRIOR_ALPHA

    @property
    def underestimate_count(self) -> int:
        return self.cost_under_alpha - PRIOR_ALPHA

    @property
    def overestimate_count(self) -> int:
        return self.cost_over_alpha - PRIOR_ALPHA

    @property
    def value_samples(self) -> int:
        return self.value_match_alpha + self.value_match_beta - PRIOR_ALPHA - PRIOR_BETA


def completion_calibration_armed(config: object) -> bool:
    if isinstance(config, Mapping):
        return config.get("enabled") is True
    return getattr(config, "enabled", False) is True


def classify_cost_outcome(
    estimated_tokens: object,
    actual_tokens: object,
    tolerance_percent: int = 20,
) -> str | None:
    if (
        type(estimated_tokens) is not int
        or estimated_tokens <= 0
        or type(actual_tokens) is not int
        or actual_tokens < 0
        or type(tolerance_percent) is not int
        or not 0 <= tolerance_percent <= 100
    ):
        return None
    difference = abs(actual_tokens - estimated_tokens) * 100
    if difference <= estimated_tokens * tolerance_percent:
        return "within"
    if actual_tokens * 100 > estimated_tokens * (100 + tolerance_percent):
        return "estimate_ran_low"
    return "estimate_ran_high"


def derive_calibrated_tokens(
    current_estimated_tokens: object,
    summary: CompletionCalibrationSummary | object,
) -> int | None:
    if (
        type(current_estimated_tokens) is CompletionCalibrationSummary
        and type(summary) is int
    ):
        current_estimated_tokens, summary = summary, current_estimated_tokens
    if type(current_estimated_tokens) is not int or current_estimated_tokens <= 0:
        return None
    if type(summary) is not CompletionCalibrationSummary:
        return None
    under_probability = summary.cost_under_alpha / (
        summary.cost_under_alpha + summary.cost_under_beta
    )
    over_probability = summary.cost_over_alpha / (
        summary.cost_over_alpha + summary.cost_over_beta
    )
    factor = max(0.8, min(1.2, 1.0 + 0.2 * (under_probability - over_probability)))
    return round(current_estimated_tokens * factor)


def render_calibration_evidence(
    summary: CompletionCalibrationSummary,
    *,
    tolerance_percent: int = 20,
    calibrated_tokens: int | None = None,
) -> str:
    text = (
        f"{summary.cost_samples} similar completions: "
        f"{summary.within_count} within +/-{tolerance_percent}%; "
        f"{summary.underestimate_count} estimates ran low; "
        f"{summary.overestimate_count} ran high."
    )
    if type(calibrated_tokens) is int and calibrated_tokens > 0:
        text += f" Calibrated total token estimate: {calibrated_tokens}."
    return text


_VALUE_RESOLUTION_SCHEMA = """
CREATE TABLE completion_value_resolutions (
    resolution_id INTEGER PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    declaration_value_band TEXT,
    declaration_source_kind TEXT,
    declaration_source_id TEXT,
    declaration_recorded_at REAL,
    proposed_value_band TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    proposed_at REAL NOT NULL,
    confirmed_value_band TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmation_kind TEXT NOT NULL CHECK(confirmation_kind IN ('captain','chain_of_command')),
    confirmed_at REAL NOT NULL,
    CHECK (
        (declaration_value_band IS NULL
         AND declaration_source_kind IS NULL
         AND declaration_source_id IS NULL
         AND declaration_recorded_at IS NULL)
        OR
        (declaration_value_band IS NOT NULL
         AND declaration_source_kind IN ('captain','agent')
         AND declaration_source_id IS NOT NULL
         AND declaration_recorded_at IS NOT NULL)
    )
)"""

_OUTCOMES_SCHEMA = """
CREATE TABLE completion_calibration_outcomes (
    work_item_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    work_type TEXT NOT NULL,
    estimated_tokens INTEGER,
    actual_tokens INTEGER NOT NULL,
    proposed_value_band TEXT,
    confirmed_value_band TEXT,
    completed_at REAL NOT NULL,
    PRIMARY KEY (work_item_id, outcome_id)
)"""

_STATS_SCHEMA = """
CREATE TABLE completion_calibration_stats (
    agent_id TEXT NOT NULL,
    work_type TEXT NOT NULL,
    cost_within_alpha INTEGER NOT NULL DEFAULT 2,
    cost_within_beta INTEGER NOT NULL DEFAULT 2,
    cost_under_alpha INTEGER NOT NULL DEFAULT 2,
    cost_under_beta INTEGER NOT NULL DEFAULT 2,
    cost_over_alpha INTEGER NOT NULL DEFAULT 2,
    cost_over_beta INTEGER NOT NULL DEFAULT 2,
    value_match_alpha INTEGER NOT NULL DEFAULT 2,
    value_match_beta INTEGER NOT NULL DEFAULT 2,
    PRIMARY KEY (agent_id, work_type)
)"""

_SPENDS_SCHEMA = """
CREATE TABLE completion_calibration_spends (
    work_item_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    provider_request_id TEXT,
    requested_tier TEXT NOT NULL,
    effective_tier TEXT NOT NULL,
    tier_outcome TEXT,
    tier_evidence TEXT,
    model_reason TEXT,
    model TEXT NOT NULL,
    token_source TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    input_price_per_million REAL,
    output_price_per_million REAL,
    currency TEXT,
    price_effective_at REAL NOT NULL,
    provider_reported_prompt_tokens INTEGER,
    provider_reported_completion_tokens INTEGER,
    provider_reported_total_tokens INTEGER,
    PRIMARY KEY (work_item_id, outcome_id, request_id),
    FOREIGN KEY (work_item_id, outcome_id)
        REFERENCES completion_calibration_outcomes(work_item_id, outcome_id)
)"""

_VALUE_RESOLUTION_INDEX = """
CREATE UNIQUE INDEX completion_value_resolutions_declaration
ON completion_value_resolutions (
    work_item_id,
    declaration_value_band,
    declaration_source_kind,
    declaration_source_id,
    declaration_recorded_at
)
WHERE declaration_value_band IS NOT NULL
"""


def _normalize_value_resolution_index(sql: str) -> str:
    terminal = sql.rstrip(" \t\r\n\f\v")
    if terminal.endswith(";"):
        terminal = terminal[:-1]
    ascii_lower = terminal.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"),
    )
    return ascii_lower.translate(str.maketrans("", "", " \t\r\n\f\v"))


_NORMALIZED_VALUE_RESOLUTION_INDEX = _normalize_value_resolution_index(
    _VALUE_RESOLUTION_INDEX,
)

_EXPECTED_COLUMNS: dict[str, tuple[tuple[str, str, int], ...]] = {
    "completion_value_resolutions": (
        ("resolution_id", "INTEGER", 1), ("work_item_id", "TEXT", 0),
        ("declaration_value_band", "TEXT", 0),
        ("declaration_source_kind", "TEXT", 0),
        ("declaration_source_id", "TEXT", 0),
        ("declaration_recorded_at", "REAL", 0),
        ("proposed_value_band", "TEXT", 0), ("proposed_by", "TEXT", 0),
        ("proposed_at", "REAL", 0), ("confirmed_value_band", "TEXT", 0),
        ("confirmed_by", "TEXT", 0), ("confirmation_kind", "TEXT", 0),
        ("confirmed_at", "REAL", 0),
    ),
    "completion_calibration_outcomes": (
        ("work_item_id", "TEXT", 1), ("outcome_id", "TEXT", 2),
        ("agent_id", "TEXT", 0), ("work_type", "TEXT", 0),
        ("estimated_tokens", "INTEGER", 0), ("actual_tokens", "INTEGER", 0),
        ("proposed_value_band", "TEXT", 0),
        ("confirmed_value_band", "TEXT", 0), ("completed_at", "REAL", 0),
    ),
    "completion_calibration_stats": (
        ("agent_id", "TEXT", 1), ("work_type", "TEXT", 2),
        ("cost_within_alpha", "INTEGER", 0), ("cost_within_beta", "INTEGER", 0),
        ("cost_under_alpha", "INTEGER", 0), ("cost_under_beta", "INTEGER", 0),
        ("cost_over_alpha", "INTEGER", 0), ("cost_over_beta", "INTEGER", 0),
        ("value_match_alpha", "INTEGER", 0), ("value_match_beta", "INTEGER", 0),
    ),
    "completion_calibration_spends": (
        ("work_item_id", "TEXT", 1), ("outcome_id", "TEXT", 2),
        ("request_id", "TEXT", 3), ("provider_request_id", "TEXT", 0),
        ("requested_tier", "TEXT", 0), ("effective_tier", "TEXT", 0),
        ("tier_outcome", "TEXT", 0), ("tier_evidence", "TEXT", 0),
        ("model_reason", "TEXT", 0), ("model", "TEXT", 0),
        ("token_source", "TEXT", 0), ("prompt_tokens", "INTEGER", 0),
        ("completion_tokens", "INTEGER", 0), ("total_tokens", "INTEGER", 0),
        ("input_price_per_million", "REAL", 0),
        ("output_price_per_million", "REAL", 0), ("currency", "TEXT", 0),
        ("price_effective_at", "REAL", 0),
        ("provider_reported_prompt_tokens", "INTEGER", 0),
        ("provider_reported_completion_tokens", "INTEGER", 0),
        ("provider_reported_total_tokens", "INTEGER", 0),
    ),
}

_LEGACY_VALUE_RESOLUTION_COLUMNS = (
    ("work_item_id", "TEXT", 1), ("proposed_value_band", "TEXT", 0),
    ("proposed_by", "TEXT", 0), ("proposed_at", "REAL", 0),
    ("confirmed_value_band", "TEXT", 0), ("confirmed_by", "TEXT", 0),
    ("confirmation_kind", "TEXT", 0), ("confirmed_at", "REAL", 0),
)
_LEGACY_SPEND_COLUMNS = _EXPECTED_COLUMNS["completion_calibration_spends"][:-3]


class _CompletionCalibrationMigrator:
    def __init__(
        self,
        connection: DatabaseConnection,
    ) -> None:
        self._connection = connection

    async def migrate(self) -> None:
        await self._connection.execute(
            "SAVEPOINT completion_calibration_migrate",
        )
        try:
            await self._migrate_value_resolutions()
            await self._ensure_exact_table(
                "completion_calibration_outcomes", _OUTCOMES_SCHEMA,
            )
            await self._ensure_exact_table(
                "completion_calibration_stats", _STATS_SCHEMA,
            )
            await self._migrate_spends()
            await self._validate_schema()
            await self._connection.execute(
                "RELEASE SAVEPOINT completion_calibration_migrate",
            )
        except BaseException:
            await self._connection.execute(
                "ROLLBACK TO SAVEPOINT completion_calibration_migrate",
            )
            await self._connection.execute(
                "RELEASE SAVEPOINT completion_calibration_migrate",
            )
            raise

    async def _table_columns(
        self, table: str,
    ) -> tuple[tuple[str, str, int], ...]:
        cursor = await self._connection.execute(f"PRAGMA table_info({table})")
        return tuple(
            (row[1], str(row[2]).upper(), int(row[5]))
            for row in await cursor.fetchall()
        )

    async def _ensure_exact_table(self, table: str, schema: str) -> None:
        actual = await self._table_columns(table)
        if not actual:
            await self._connection.execute(schema)
            return
        if actual != _EXPECTED_COLUMNS[table]:
            raise ValueError(f"completion_calibration_schema_invalid:{table}")

    async def _migrate_value_resolutions(self) -> None:
        table = "completion_value_resolutions"
        actual = await self._table_columns(table)
        if not actual:
            await self._connection.execute(_VALUE_RESOLUTION_SCHEMA)
            await self._connection.execute(_VALUE_RESOLUTION_INDEX)
            return
        if actual == _EXPECTED_COLUMNS[table]:
            return
        if actual != _LEGACY_VALUE_RESOLUTION_COLUMNS:
            raise ValueError(f"completion_calibration_schema_invalid:{table}")
        await self._connection.execute(
            "ALTER TABLE completion_value_resolutions "
            "RENAME TO completion_value_resolutions_legacy",
        )
        await self._connection.execute(_VALUE_RESOLUTION_SCHEMA)
        await self._connection.execute(_VALUE_RESOLUTION_INDEX)
        cursor = await self._connection.execute(
            "SELECT work_item_id, proposed_value_band, proposed_by, proposed_at, "
            "confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at "
            "FROM completion_value_resolutions_legacy ORDER BY work_item_id",
        )
        for row in await cursor.fetchall():
            identity = await self._legacy_resolution_identity(tuple(row))
            await self._connection.execute(
                "INSERT INTO completion_value_resolutions ("
                "work_item_id, declaration_value_band, declaration_source_kind, "
                "declaration_source_id, declaration_recorded_at, "
                "proposed_value_band, proposed_by, proposed_at, "
                "confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row[0],
                    None if identity is None else identity.value_band,
                    None if identity is None else identity.source_kind,
                    None if identity is None else identity.source_id,
                    None if identity is None else identity.recorded_at,
                    *tuple(row)[1:],
                ),
            )
        await self._connection.execute(
            "DROP TABLE completion_value_resolutions_legacy",
        )

    async def _legacy_resolution_identity(
        self, row: tuple[Any, ...],
    ) -> ValueDeclarationIdentity | None:
        work_item_columns = await self._table_columns("work_items")
        if not {
            "id", "value_band", "value_band_provenance",
        }.issubset(column[0] for column in work_item_columns):
            return None
        cursor = await self._connection.execute(
            "SELECT value_band, value_band_provenance FROM work_items WHERE id=?",
            (row[0],),
        )
        item = await cursor.fetchone()
        if item is None or type(item[1]) is not str:
            return None
        try:
            provenance = json.loads(item[1])
        except (TypeError, ValueError):
            return None
        if (
            type(provenance) is not dict
            or provenance.get("source_kind") not in _VALUE_SOURCE_KINDS
            or type(provenance.get("source_id")) is not str
            or type(provenance.get("recorded_at")) not in (int, float)
            or item[0] != row[4]
            or provenance.get("confirmed_by") != row[5]
            or provenance.get("confirmation_kind") != row[6]
            or provenance.get("confirmed_at") != row[7]
        ):
            return None
        if provenance["source_kind"] == "agent" and (
            item[0] != row[1]
            or provenance["source_id"] != row[2]
            or provenance["recorded_at"] != row[3]
        ):
            return None
        if provenance["source_kind"] == "captain" and (
            provenance["source_id"] != "captain"
            or row[6] != "captain"
        ):
            return None
        return ValueDeclarationIdentity(
            value_band=item[0],
            source_kind=provenance["source_kind"],
            source_id=provenance["source_id"],
            recorded_at=float(provenance["recorded_at"]),
        )

    async def _migrate_spends(self) -> None:
        table = "completion_calibration_spends"
        actual = await self._table_columns(table)
        if not actual:
            await self._connection.execute(_SPENDS_SCHEMA)
            return
        if actual == _EXPECTED_COLUMNS[table]:
            return
        if actual != _LEGACY_SPEND_COLUMNS:
            raise ValueError(f"completion_calibration_schema_invalid:{table}")
        await self._connection.execute(
            "ALTER TABLE completion_calibration_spends "
            "RENAME TO completion_calibration_spends_legacy",
        )
        await self._connection.execute(_SPENDS_SCHEMA)
        legacy_names = ", ".join(column[0] for column in _LEGACY_SPEND_COLUMNS)
        await self._connection.execute(
            "INSERT INTO completion_calibration_spends ("
            + legacy_names
            + ", provider_reported_prompt_tokens, "
            "provider_reported_completion_tokens, provider_reported_total_tokens) "
            "SELECT "
            + legacy_names
            + ", prompt_tokens, completion_tokens, total_tokens "
            "FROM completion_calibration_spends_legacy",
        )
        await self._connection.execute(
            "DROP TABLE completion_calibration_spends_legacy",
        )

    async def _validate_schema(self) -> None:
        for table, expected in _EXPECTED_COLUMNS.items():
            if await self._table_columns(table) != expected:
                raise ValueError(f"completion_calibration_schema_invalid:{table}")
        cursor = await self._connection.execute(
            "PRAGMA index_info(completion_value_resolutions_declaration)",
        )
        index_columns = tuple(row[2] for row in await cursor.fetchall())
        index_list = await (
            await self._connection.execute(
                "PRAGMA index_list(completion_value_resolutions)",
            )
        ).fetchall()
        index_metadata = next(
            (
                row for row in index_list
                if row[1] == "completion_value_resolutions_declaration"
            ),
            None,
        )
        index_sql_rows = await (
            await self._connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE type='index' "
                "AND name='completion_value_resolutions_declaration' "
                "AND tbl_name='completion_value_resolutions'",
            )
        ).fetchall()
        stored_index_sql = (
            index_sql_rows[0][0] if len(index_sql_rows) == 1 else None
        )
        if (
            index_metadata is None
            or int(index_metadata[2]) != 1
            or int(index_metadata[4]) != 1
            or index_columns != (
            "work_item_id",
            "declaration_value_band",
            "declaration_source_kind",
            "declaration_source_id",
            "declaration_recorded_at",
            )
            or not isinstance(stored_index_sql, str)
            or _normalize_value_resolution_index(stored_index_sql)
            != _NORMALIZED_VALUE_RESOLUTION_INDEX
        ):
            raise ValueError(
                "completion_calibration_schema_invalid:"
                "completion_value_resolutions",
            )
        duplicate = await (
            await self._connection.execute(
                "SELECT 1 FROM completion_value_resolutions "
                "WHERE declaration_value_band IS NOT NULL "
                "AND declaration_source_kind IS NOT NULL "
                "AND declaration_source_id IS NOT NULL "
                "AND declaration_recorded_at IS NOT NULL "
                "GROUP BY work_item_id, declaration_value_band, "
                "declaration_source_kind, declaration_source_id, "
                "declaration_recorded_at HAVING COUNT(*) > 1 LIMIT 1",
            )
        ).fetchone()
        if duplicate is not None:
            raise ValueError(
                "completion_calibration_schema_invalid:"
                "completion_value_resolutions",
            )


class CompletionCalibrationLedger:
    def __init__(
        self,
        connection: DatabaseConnection,
        *,
        cost_tolerance_percent: int = 20,
        minimum_samples: int = 8,
    ) -> None:
        if not 0 <= cost_tolerance_percent <= 100:
            raise ValueError("completion_calibration_tolerance_invalid")
        if not 1 <= minimum_samples <= 1000:
            raise ValueError("completion_calibration_minimum_samples_invalid")
        self._connection = connection
        self._tolerance = cost_tolerance_percent
        self._minimum_samples = minimum_samples

    async def migrate(self) -> None:
        await _CompletionCalibrationMigrator(self._connection).migrate()

    async def record_value_resolution(
        self,
        *,
        work_item_id: str,
        declaration_identity: ValueDeclarationIdentity,
        proposed_value_band: str,
        proposed_by: str,
        proposed_at: float,
        confirmed_value_band: str,
        confirmed_by: str,
        confirmation_kind: str,
        confirmed_at: float,
    ) -> None:
        self._validate_declaration_identity(declaration_identity)
        payload = (
            work_item_id,
            declaration_identity.value_band,
            declaration_identity.source_kind,
            declaration_identity.source_id,
            declaration_identity.recorded_at,
            proposed_value_band, proposed_by, proposed_at,
            confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at,
        )
        cursor = await self._connection.execute(
            "SELECT work_item_id, declaration_value_band, "
            "declaration_source_kind, declaration_source_id, "
            "declaration_recorded_at, proposed_value_band, proposed_by, proposed_at, "
            "confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at "
            "FROM completion_value_resolutions WHERE work_item_id=? "
            "AND declaration_value_band=? AND declaration_source_kind=? "
            "AND declaration_source_id=? AND declaration_recorded_at=?",
            payload[:5],
        )
        existing = await cursor.fetchone()
        if existing is not None:
            if tuple(existing) == payload:
                return
            raise ValueError("completion_value_resolution_conflict")
        await self._connection.execute(
            "INSERT INTO completion_value_resolutions ("
            "work_item_id, declaration_value_band, declaration_source_kind, "
            "declaration_source_id, declaration_recorded_at, proposed_value_band, "
            "proposed_by, proposed_at, confirmed_value_band, confirmed_by, "
            "confirmation_kind, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )

    async def record_completion(
        self,
        work_item_id: str,
        evidence: CompletionCalibrationEvidence,
        *,
        declaration_identity: ValueDeclarationIdentity | None = None,
    ) -> bool:
        self._validate_evidence(evidence)
        if declaration_identity is not None:
            self._validate_declaration_identity(declaration_identity)
        raw_outcome = (
            work_item_id, evidence.outcome_id, evidence.agent_id, evidence.work_type,
            evidence.estimated_tokens, evidence.actual_tokens, evidence.completed_at,
        )
        cursor = await self._connection.execute(
            "SELECT work_item_id, outcome_id, agent_id, work_type, estimated_tokens, "
            "actual_tokens, proposed_value_band, confirmed_value_band, completed_at "
            "FROM completion_calibration_outcomes WHERE work_item_id=? AND outcome_id=?",
            (work_item_id, evidence.outcome_id),
        )
        existing = await cursor.fetchone()
        if existing is not None:
            stored_raw_outcome = (
                existing[0], existing[1], existing[2], existing[3],
                existing[4], existing[5], existing[8],
            )
            if stored_raw_outcome != raw_outcome:
                raise ValueError("completion_calibration_identity_conflict")
            await self._check_existing_spends(work_item_id, evidence)
            return False
        proposed_value_band, confirmed_value_band = await self._read_value_resolution(
            work_item_id, declaration_identity,
        )
        outcome = (
            *raw_outcome[:-1],
            proposed_value_band,
            confirmed_value_band,
            raw_outcome[-1],
        )
        await self._connection.execute(
            "INSERT INTO completion_calibration_outcomes VALUES (?,?,?,?,?,?,?,?,?)",
            outcome,
        )
        for spend in evidence.spends:
            await self._insert_spend(work_item_id, evidence.outcome_id, spend)
        cost_bucket = classify_cost_outcome(
            evidence.estimated_tokens, evidence.actual_tokens, self._tolerance,
        )
        value_match = (
            proposed_value_band == confirmed_value_band
            if proposed_value_band is not None and confirmed_value_band is not None
            else None
        )
        if cost_bucket is not None or value_match is not None:
            await self._increment_stats(
                evidence.agent_id, evidence.work_type, cost_bucket, value_match,
            )
        return True

    async def matches_completion(
        self,
        work_item_id: str,
        evidence: CompletionCalibrationEvidence,
    ) -> bool:
        self._validate_evidence(evidence)
        raw_outcome = (
            work_item_id, evidence.outcome_id, evidence.agent_id, evidence.work_type,
            evidence.estimated_tokens, evidence.actual_tokens, evidence.completed_at,
        )
        cursor = await self._connection.execute(
            "SELECT work_item_id, outcome_id, agent_id, work_type, estimated_tokens, "
            "actual_tokens, proposed_value_band, confirmed_value_band, completed_at "
            "FROM completion_calibration_outcomes WHERE work_item_id=? AND outcome_id=?",
            (work_item_id, evidence.outcome_id),
        )
        existing = await cursor.fetchone()
        if existing is None:
            return False
        stored_raw_outcome = (
            existing[0], existing[1], existing[2], existing[3],
            existing[4], existing[5], existing[8],
        )
        if stored_raw_outcome != raw_outcome:
            return False
        return await self._stored_spends_match(work_item_id, evidence)

    async def _read_value_resolution(
        self,
        work_item_id: str,
        declaration_identity: ValueDeclarationIdentity | None,
    ) -> tuple[str | None, str | None]:
        if declaration_identity is None:
            return None, None
        cursor = await self._connection.execute(
            "SELECT proposed_value_band, confirmed_value_band "
            "FROM completion_value_resolutions WHERE work_item_id=? "
            "AND declaration_value_band=? AND declaration_source_kind=? "
            "AND declaration_source_id=? AND declaration_recorded_at=?",
            (
                work_item_id,
                declaration_identity.value_band,
                declaration_identity.source_kind,
                declaration_identity.source_id,
                declaration_identity.recorded_at,
            ),
        )
        resolution = await cursor.fetchone()
        if resolution is None:
            return None, None
        return resolution[0], resolution[1]

    @staticmethod
    def _validate_declaration_identity(
        identity: ValueDeclarationIdentity,
    ) -> None:
        if (
            type(identity) is not ValueDeclarationIdentity
            or identity.value_band not in _VALUE_BANDS
            or identity.source_kind not in _VALUE_SOURCE_KINDS
            or not identity.source_id
            or type(identity.recorded_at) not in (int, float)
            or not math.isfinite(float(identity.recorded_at))
            or identity.recorded_at < 0
        ):
            raise ValueError("completion_value_declaration_invalid")

    async def get_summary(
        self, agent_id: str, work_type: str,
    ) -> CompletionCalibrationSummary | None:
        cursor = await self._connection.execute(
            "SELECT agent_id, work_type, cost_within_alpha, cost_within_beta, "
            "cost_under_alpha, cost_under_beta, cost_over_alpha, cost_over_beta, "
            "value_match_alpha, value_match_beta FROM completion_calibration_stats "
            "WHERE agent_id=? AND work_type=?",
            (agent_id, work_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        summary = CompletionCalibrationSummary(*tuple(row))
        if summary.cost_samples < self._minimum_samples:
            return None
        return summary

    def _validate_evidence(self, evidence: CompletionCalibrationEvidence) -> None:
        if (
            type(evidence) is not CompletionCalibrationEvidence
            or len(evidence.outcome_id) != 64
            or any(character not in "0123456789abcdef" for character in evidence.outcome_id)
            or not evidence.agent_id
            or not evidence.work_type
            or type(evidence.actual_tokens) is not int
            or evidence.actual_tokens < 0
            or (
                evidence.estimated_tokens is not None
                and (
                    type(evidence.estimated_tokens) is not int
                    or evidence.estimated_tokens < 0
                )
            )
            or type(evidence.completed_at) not in (int, float)
            or len(evidence.spends) > MAX_SPENDS_PER_OUTCOME
            or any(
                type(spend) is not SpendPriceSnapshot
                or not spend.request_id
                or not spend.requested_tier
                or not spend.effective_tier
                or not spend.model
                or spend.token_source
                not in {"measured", "estimated", "mixed", "unavailable"}
                or type(spend.prompt_tokens) is not int
                or spend.prompt_tokens < 0
                or type(spend.completion_tokens) is not int
                or spend.completion_tokens < 0
                or type(spend.total_tokens) is not int
                or spend.total_tokens < 0
                or any(
                    value is not None and type(value) is not int
                    for value in (
                        spend.provider_reported_prompt_tokens,
                        spend.provider_reported_completion_tokens,
                        spend.provider_reported_total_tokens,
                    )
                )
                for spend in evidence.spends
            )
            or len({spend.request_id for spend in evidence.spends})
            != len(evidence.spends)
        ):
            raise ValueError("completion_calibration_evidence_invalid")

    async def _check_existing_spends(
        self, work_item_id: str, evidence: CompletionCalibrationEvidence,
    ) -> None:
        if not await self._stored_spends_match(work_item_id, evidence):
            raise ValueError("completion_calibration_spend_conflict")

    async def _stored_spends_match(
        self, work_item_id: str, evidence: CompletionCalibrationEvidence,
    ) -> bool:
        cursor = await self._connection.execute(
            "SELECT request_id, provider_request_id, requested_tier, effective_tier, "
            "tier_outcome, tier_evidence, model_reason, model, token_source, "
            "prompt_tokens, completion_tokens, total_tokens, input_price_per_million, "
            "output_price_per_million, currency, price_effective_at, "
            "provider_reported_prompt_tokens, "
            "provider_reported_completion_tokens, provider_reported_total_tokens "
            "FROM completion_calibration_spends "
            "WHERE work_item_id=? AND outcome_id=?",
            (work_item_id, evidence.outcome_id),
        )
        stored = {
            row[0]: tuple(row)
            for row in await cursor.fetchall()
        }
        incoming = {
            spend.request_id: self._spend_payload(spend)
            for spend in evidence.spends
        }
        return stored == incoming

    async def _insert_spend(
        self, work_item_id: str, outcome_id: str, spend: SpendPriceSnapshot,
    ) -> None:
        payload = self._spend_payload(spend)
        cursor = await self._connection.execute(
            "SELECT request_id, provider_request_id, requested_tier, effective_tier, "
            "tier_outcome, tier_evidence, model_reason, model, token_source, "
            "prompt_tokens, completion_tokens, total_tokens, input_price_per_million, "
            "output_price_per_million, currency, price_effective_at, "
            "provider_reported_prompt_tokens, "
            "provider_reported_completion_tokens, provider_reported_total_tokens "
            "FROM completion_calibration_spends "
            "WHERE work_item_id=? AND outcome_id=? AND request_id=?",
            (work_item_id, outcome_id, spend.request_id),
        )
        existing = await cursor.fetchone()
        if existing is not None:
            if tuple(existing) == payload:
                return
            raise ValueError("completion_calibration_spend_conflict")
        await self._connection.execute(
            "INSERT INTO completion_calibration_spends ("
            "work_item_id, outcome_id, request_id, provider_request_id, "
            "requested_tier, effective_tier, tier_outcome, tier_evidence, "
            "model_reason, model, token_source, prompt_tokens, completion_tokens, "
            "total_tokens, input_price_per_million, output_price_per_million, "
            "currency, price_effective_at, provider_reported_prompt_tokens, "
            "provider_reported_completion_tokens, provider_reported_total_tokens"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (work_item_id, outcome_id, *payload),
        )

    @staticmethod
    def _spend_payload(spend: SpendPriceSnapshot) -> tuple[Any, ...]:
        return (
            spend.request_id, spend.provider_request_id, spend.requested_tier,
            spend.effective_tier, spend.tier_outcome, spend.tier_evidence,
            spend.model_reason, spend.model, spend.token_source,
            spend.prompt_tokens, spend.completion_tokens, spend.total_tokens,
            spend.input_price_per_million, spend.output_price_per_million,
            spend.currency, spend.price_effective_at,
            spend.provider_reported_prompt_tokens,
            spend.provider_reported_completion_tokens,
            spend.provider_reported_total_tokens,
        )

    async def _increment_stats(
        self,
        agent_id: str,
        work_type: str,
        cost_bucket: str | None,
        value_match: bool | None,
    ) -> None:
        await self._connection.execute(
            "INSERT INTO completion_calibration_stats (agent_id, work_type) VALUES (?,?) "
            "ON CONFLICT(agent_id, work_type) DO NOTHING",
            (agent_id, work_type),
        )
        increments = {
            "cost_within_alpha": int(cost_bucket == "within"),
            "cost_within_beta": int(cost_bucket is not None and cost_bucket != "within"),
            "cost_under_alpha": int(cost_bucket == "estimate_ran_low"),
            "cost_under_beta": int(cost_bucket is not None and cost_bucket != "estimate_ran_low"),
            "cost_over_alpha": int(cost_bucket == "estimate_ran_high"),
            "cost_over_beta": int(cost_bucket is not None and cost_bucket != "estimate_ran_high"),
            "value_match_alpha": int(value_match is True),
            "value_match_beta": int(value_match is False),
        }
        await self._connection.execute(
            "UPDATE completion_calibration_stats SET "
            + ", ".join(f"{name}={name}+?" for name in increments)
            + " WHERE agent_id=? AND work_type=?",
            (*increments.values(), agent_id, work_type),
        )
