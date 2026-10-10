from __future__ import annotations

import inspect
import json

import aiosqlite
import pytest

from probos.config_models.agentic import EconomicJudgmentConfig
from probos.economic_calibration import (
    PRIOR_ALPHA,
    PRIOR_BETA,
    CompletionCalibrationEvidence,
    CompletionCalibrationLedger,
    CompletionCalibrationSummary,
    SpendPriceSnapshot,
    ValueDeclarationIdentity,
    classify_cost_outcome,
    completion_calibration_from_payload,
    completion_calibration_payload,
    derive_calibrated_tokens,
)
from probos.workforce import WorkItemStore


def _evidence(
    number: int,
    *,
    actual: int = 100,
    estimate: int | None = 100,
    spend: SpendPriceSnapshot | None = None,
) -> CompletionCalibrationEvidence:
    return CompletionCalibrationEvidence(
        outcome_id=f"{number:064x}",
        agent_id="agent-1",
        work_type="task",
        estimated_tokens=estimate,
        actual_tokens=actual,
        completed_at=float(number),
        spends=(() if spend is None else (spend,)),
    )


def _spend(*, total: int = 30, input_price: float | None = 2.0) -> SpendPriceSnapshot:
    return SpendPriceSnapshot(
        request_id="request-1",
        provider_request_id="provider-1",
        requested_tier="standard",
        effective_tier="standard",
        tier_outcome="agent_choice",
        tier_evidence="prior_error",
        model_reason="complexity",
        model="model-1",
        token_source="measured",
        prompt_tokens=20,
        completion_tokens=10,
        total_tokens=total,
        input_price_per_million=input_price,
        output_price_per_million=8.0 if input_price is not None else None,
        currency="USD" if input_price is not None else None,
        price_effective_at=10.0,
    )


def _spends(*request_ids: str) -> tuple[SpendPriceSnapshot, ...]:
    return tuple(
        SpendPriceSnapshot(
            **{
                **_spend().__dict__,
                "request_id": request_id,
                "provider_request_id": f"provider-{request_id}",
            }
        )
        for request_id in request_ids
    )


def _identity(
        value_band: str = "moderate",
        *,
        source_kind: str = "agent",
        source_id: str = "agent-1",
        recorded_at: float = 0.5,
) -> ValueDeclarationIdentity:
    return ValueDeclarationIdentity(
        value_band=value_band,
        source_kind=source_kind,
        source_id=source_id,
        recorded_at=recorded_at,
    )


async def _ledger(
    *, minimum: int = 8,
) -> tuple[aiosqlite.Connection, CompletionCalibrationLedger]:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    ledger = CompletionCalibrationLedger(connection, minimum_samples=minimum)
    await ledger.migrate()
    return connection, ledger


async def _replace_declaration_index_with_agent_predicate(
    connection: aiosqlite.Connection,
) -> str:
    await connection.execute(
        "DROP INDEX completion_value_resolutions_declaration",
    )
    await connection.execute(
        "CREATE UNIQUE INDEX completion_value_resolutions_declaration "
        "ON completion_value_resolutions ("
        "work_item_id, declaration_value_band, declaration_source_kind, "
        "declaration_source_id, declaration_recorded_at"
        ") WHERE declaration_source_kind='agent'",
    )
    row = await (
        await connection.execute(
            "SELECT sql FROM sqlite_schema "
            "WHERE type='index' "
            "AND name='completion_value_resolutions_declaration' "
            "AND tbl_name='completion_value_resolutions'",
        )
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_default_config_is_fully_off_with_fixed_priors_tolerance_and_minimum() -> None:
    config = EconomicJudgmentConfig().completion_calibration
    assert config.model_dump() == {
        "enabled": False,
        "cost_tolerance_percent": 20,
        "minimum_samples": 8,
        "feed_cost_estimates_to_organ": False,
    }
    assert (PRIOR_ALPHA, PRIOR_BETA) == (2, 2)


def test_cost_bucket_boundaries_use_exact_integer_twenty_percent_tolerance() -> None:
    assert classify_cost_outcome(100, 80) == "within"
    assert classify_cost_outcome(100, 120) == "within"
    assert classify_cost_outcome(100, 79) == "estimate_ran_high"
    assert classify_cost_outcome(100, 121) == "estimate_ran_low"
    assert classify_cost_outcome(0, 0) is None


@pytest.mark.asyncio
async def test_stats_persist_only_raw_alpha_beta_counts() -> None:
    connection, ledger = await _ledger(minimum=1)
    try:
        await ledger.record_completion("work-1", _evidence(1, actual=121))
        await connection.commit()
        cursor = await connection.execute(
            "SELECT * FROM completion_calibration_stats",
        )
        row = await cursor.fetchone()
        assert tuple(row)[2:] == (2, 3, 3, 2, 2, 3, 2, 2)
        columns = [entry[1] for entry in await (await connection.execute(
            "PRAGMA table_info(completion_calibration_stats)"
        )).fetchall()]
        assert all("mean" not in name and "sample" not in name for name in columns)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_minimum_eight_samples_returns_none_before_threshold() -> None:
    connection, ledger = await _ledger()
    try:
        for number in range(1, 8):
            await ledger.record_completion(f"work-{number}", _evidence(number))
        assert await ledger.get_summary("agent-1", "task") is None
        await ledger.record_completion("work-8", _evidence(8))
        assert (await ledger.get_summary("agent-1", "task")).cost_samples == 8
    finally:
        await connection.close()


def test_derived_estimate_is_in_memory_and_bounded_to_point_eight_through_one_point_two() -> None:
    low = CompletionCalibrationSummary(
        "a", "t", 2, 10, 2, 10, 10, 2, 2, 2,
    )
    high = CompletionCalibrationSummary(
        "a", "t", 2, 10, 10, 2, 2, 10, 2, 2,
    )
    assert derive_calibrated_tokens(100, low) >= 80
    assert derive_calibrated_tokens(100, high) <= 120
    assert derive_calibrated_tokens(None, high) is None


@pytest.mark.asyncio
async def test_duplicate_outcome_is_exact_noop_and_does_not_increment_counts() -> None:
    connection, ledger = await _ledger(minimum=1)
    try:
        evidence = _evidence(1)
        assert await ledger.record_completion("work-1", evidence) is True
        assert await ledger.record_completion("work-1", evidence) is False
        summary = await ledger.get_summary("agent-1", "task")
        assert summary.cost_samples == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_divergent_duplicate_outcome_raises_identity_conflict() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_completion("work-1", _evidence(1))
        with pytest.raises(ValueError, match="completion_calibration_identity_conflict"):
            await ledger.record_completion("work-1", _evidence(1, actual=101))
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_duplicate_spend_is_exact_noop_and_divergent_spend_conflicts() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_completion("work-1", _evidence(1, spend=_spend()))
        assert await ledger.record_completion("work-1", _evidence(1, spend=_spend())) is False
        with pytest.raises(ValueError, match="completion_calibration_spend_conflict"):
            await ledger.record_completion(
                "work-1", _evidence(1, spend=_spend(total=31)),
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_zero_estimate_is_valid_evidence_but_cost_ineligible() -> None:
    connection, ledger = await _ledger(minimum=1)
    try:
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=_identity(),
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=0.5,
            confirmed_value_band="moderate",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=0.75,
        )
        evidence = _evidence(1, estimate=0, spend=_spend())
        assert await ledger.record_completion(
            "work-1", evidence, declaration_identity=_identity(),
        ) is True
        outcome = await (await connection.execute(
            "SELECT estimated_tokens FROM completion_calibration_outcomes"
        )).fetchone()
        stats = await (await connection.execute(
            "SELECT cost_within_alpha, cost_within_beta, cost_under_alpha, "
            "cost_under_beta, cost_over_alpha, cost_over_beta, "
            "value_match_alpha, value_match_beta FROM completion_calibration_stats"
        )).fetchone()
        spends = await (await connection.execute(
            "SELECT COUNT(*) FROM completion_calibration_spends"
        )).fetchone()
        assert outcome[0] == 0
        assert tuple(stats) == (2, 2, 2, 2, 2, 2, 3, 2)
        assert spends[0] == 1
    finally:
        await connection.close()


def test_completion_payload_rejects_caller_supplied_value_band_keys() -> None:
    payload = completion_calibration_payload(_evidence(1))
    assert "proposed_value_band" not in payload
    assert "confirmed_value_band" not in payload
    payload["proposed_value_band"] = "critical"
    payload["confirmed_value_band"] = "critical"

    with pytest.raises(
        ValueError, match="completion_calibration_evidence_invalid"
    ):
        completion_calibration_from_payload(payload)


@pytest.mark.asyncio
async def test_first_commit_without_resolution_freezes_null_value_observation() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_completion("work-1", _evidence(1, estimate=None))
        row = await (await connection.execute(
            "SELECT proposed_value_band, confirmed_value_band "
            "FROM completion_calibration_outcomes"
        )).fetchone()
        stats = await (await connection.execute(
            "SELECT COUNT(*) FROM completion_calibration_stats"
        )).fetchone()
        assert tuple(row) == (None, None)
        assert stats[0] == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_later_resolution_does_not_reinterpret_exact_completion_replay() -> None:
    connection, ledger = await _ledger()
    try:
        evidence = _evidence(1, estimate=None)
        assert await ledger.record_completion("work-1", evidence) is True
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=_identity("critical", source_kind="captain", source_id="captain", recorded_at=2.5),
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=2.0,
            confirmed_value_band="critical",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=3.0,
        )
        assert await ledger.record_completion("work-1", evidence) is False
        row = await (await connection.execute(
            "SELECT proposed_value_band, confirmed_value_band "
            "FROM completion_calibration_outcomes"
        )).fetchone()
        assert tuple(row) == (None, None)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_later_resolution_does_not_invalidate_exact_completion_proof() -> None:
    connection, ledger = await _ledger()
    try:
        evidence = _evidence(1, spend=_spend())
        await ledger.record_completion("work-1", evidence)
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=_identity(recorded_at=2.0),
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=2.0,
            confirmed_value_band="moderate",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=3.0,
        )
        assert await ledger.matches_completion("work-1", evidence) is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_first_commit_with_authoritative_resolution_freezes_exact_value_pair() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=_identity(),
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=0.5,
            confirmed_value_band="critical",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=0.75,
        )
        await ledger.record_completion(
            "work-1", _evidence(1, estimate=None),
            declaration_identity=_identity(),
        )
        outcome = await (await connection.execute(
            "SELECT proposed_value_band, confirmed_value_band "
            "FROM completion_calibration_outcomes"
        )).fetchone()
        stats = await (await connection.execute(
            "SELECT value_match_alpha, value_match_beta "
            "FROM completion_calibration_stats"
        )).fetchone()
        assert tuple(outcome) == ("moderate", "critical")
        assert tuple(stats) == (2, 3)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_existing_completion_replay_does_not_query_current_value_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, ledger = await _ledger()
    try:
        evidence = _evidence(1)
        await ledger.record_completion("work-1", evidence)

        async def fail_resolution_lookup(
            _work_item_id: str,
            _identity: ValueDeclarationIdentity | None,
        ) -> tuple[str | None, str | None]:
            raise AssertionError("existing completion replay queried mutable resolution")

        monkeypatch.setattr(ledger, "_read_value_resolution", fail_resolution_lookup)
        assert await ledger.record_completion("work-1", evidence) is False
        assert await ledger.matches_completion("work-1", evidence) is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_exact_replay_after_later_confirmation_does_not_increment_value_counts() -> None:
    connection, ledger = await _ledger(minimum=1)
    try:
        evidence = _evidence(1)
        await ledger.record_completion("work-1", evidence)
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=_identity(recorded_at=2.0),
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=2.0,
            confirmed_value_band="moderate",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=3.0,
        )
        assert await ledger.record_completion("work-1", evidence) is False
        stats = await (await connection.execute(
            "SELECT value_match_alpha, value_match_beta "
            "FROM completion_calibration_stats"
        )).fetchone()
        assert tuple(stats) == (2, 2)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_distinct_declarations_append_resolutions_and_exact_replay_conflicts_only_per_identity() -> None:
    connection, ledger = await _ledger()
    try:
        first = _identity(recorded_at=1.0)
        replacement = _identity(
            "critical",
            source_kind="captain",
            source_id="captain",
            recorded_at=2.0,
        )
        first_values = {
            "work_item_id": "work-1",
            "declaration_identity": first,
            "proposed_value_band": "moderate",
            "proposed_by": "agent-1",
            "proposed_at": 1.0,
            "confirmed_value_band": "moderate",
            "confirmed_by": "captain",
            "confirmation_kind": "captain",
            "confirmed_at": 1.5,
        }
        await ledger.record_value_resolution(**first_values)
        await ledger.record_value_resolution(**first_values)
        await ledger.record_value_resolution(
            work_item_id="work-1",
            declaration_identity=replacement,
            proposed_value_band="moderate",
            proposed_by="agent-1",
            proposed_at=1.0,
            confirmed_value_band="critical",
            confirmed_by="captain",
            confirmation_kind="captain",
            confirmed_at=2.0,
        )
        with pytest.raises(
            ValueError, match="completion_value_resolution_conflict",
        ):
            await ledger.record_value_resolution(
                **{**first_values, "confirmed_value_band": "critical"},
            )
        rows = await (await connection.execute(
            "SELECT declaration_value_band, proposed_value_band, "
            "confirmed_value_band FROM completion_value_resolutions "
            "WHERE work_item_id=? ORDER BY resolution_id",
            ("work-1",),
        )).fetchall()
        assert [tuple(row) for row in rows] == [
            ("moderate", "moderate", "moderate"),
            ("critical", "moderate", "critical"),
        ]
    finally:
        await connection.close()


def test_legacy_spend_payload_upgrades_raw_provenance_and_partial_shape_fails() -> None:
    payload = completion_calibration_payload(_evidence(1, spend=_spend()))
    raw_fields = {
        "provider_reported_prompt_tokens",
        "provider_reported_completion_tokens",
        "provider_reported_total_tokens",
    }
    legacy = {**payload, "spends": [dict(payload["spends"][0])]}
    for field in raw_fields:
        legacy["spends"][0].pop(field)
    upgraded = completion_calibration_from_payload(legacy).spends[0]
    assert (
        upgraded.provider_reported_prompt_tokens,
        upgraded.provider_reported_completion_tokens,
        upgraded.provider_reported_total_tokens,
    ) == (20, 10, 30)
    partial = {**legacy, "spends": [dict(legacy["spends"][0])]}
    partial["spends"][0]["provider_reported_total_tokens"] = 30
    with pytest.raises(
        ValueError, match="completion_calibration_evidence_invalid",
    ):
        completion_calibration_from_payload(partial)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incoming", "matches"),
    [
        ((), False),
        (_spends("first"), False),
        (_spends("first", "second"), True),
        (_spends("first", "second", "third"), False),
        (_spends("second", "first"), True),
    ],
    ids=["none", "subset", "exact", "superset", "reordered"],
)
async def test_exact_replay_requires_full_stored_spend_set(
    incoming: tuple[SpendPriceSnapshot, ...],
    matches: bool,
) -> None:
    connection, ledger = await _ledger()
    try:
        original = CompletionCalibrationEvidence(
            **{**_evidence(1).__dict__, "spends": _spends("first", "second")}
        )
        await ledger.record_completion("work-1", original)
        replay = CompletionCalibrationEvidence(
            **{**original.__dict__, "spends": incoming}
        )
        if matches:
            assert await ledger.record_completion("work-1", replay) is False
        else:
            with pytest.raises(
                ValueError, match="completion_calibration_spend_conflict"
            ):
                await ledger.record_completion("work-1", replay)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_replay_with_same_request_id_and_divergent_payload_conflicts() -> None:
    connection, ledger = await _ledger()
    try:
        original = CompletionCalibrationEvidence(
            **{**_evidence(1).__dict__, "spends": _spends("first")}
        )
        await ledger.record_completion("work-1", original)
        divergent = CompletionCalibrationEvidence(
            **{
                **original.__dict__,
                "spends": (
                    SpendPriceSnapshot(
                        **{**_spends("first")[0].__dict__, "total_tokens": 31}
                    ),
                ),
            }
        )
        with pytest.raises(
            ValueError, match="completion_calibration_spend_conflict"
        ):
            await ledger.record_completion("work-1", divergent)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_price_snapshot_retains_original_prices_after_registry_descriptor_changes() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_completion("work-1", _evidence(1, spend=_spend(input_price=2.0)))
        cursor = await connection.execute(
            "SELECT input_price_per_million FROM completion_calibration_spends",
        )
        assert (await cursor.fetchone())[0] == 2.0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_unknown_or_zero_price_is_persisted_as_null_not_free() -> None:
    connection, ledger = await _ledger()
    try:
        await ledger.record_completion("work-1", _evidence(1, spend=_spend(input_price=None)))
        cursor = await connection.execute(
            "SELECT input_price_per_million, output_price_per_million, currency "
            "FROM completion_calibration_spends",
        )
        assert tuple(await cursor.fetchone()) == (None, None, None)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_enabled_migration_preserves_existing_work_item_rows_and_column_order() -> None:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    try:
        await connection.execute("CREATE TABLE work_items (id TEXT, payload TEXT)")
        await connection.execute("INSERT INTO work_items VALUES ('w', 'raw')")
        before = await (await connection.execute("PRAGMA table_info(work_items)")).fetchall()
        ledger = CompletionCalibrationLedger(connection)
        await ledger.migrate()
        after = await (await connection.execute("PRAGMA table_info(work_items)")).fetchall()
        row = await (await connection.execute("SELECT * FROM work_items")).fetchone()
        assert [tuple(value) for value in before] == [tuple(value) for value in after]
        assert tuple(row) == ("w", "raw")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_legacy_migration_preserves_rows_binds_only_proven_current_and_restarts() -> None:
    connection = await aiosqlite.connect(":memory:")
    connection.row_factory = aiosqlite.Row
    try:
        await connection.executescript(
            """
            CREATE TABLE work_items (
                id TEXT PRIMARY KEY,
                value_band TEXT,
                value_band_provenance TEXT
            );
            CREATE TABLE completion_value_resolutions (
                work_item_id TEXT NOT NULL PRIMARY KEY,
                proposed_value_band TEXT NOT NULL,
                proposed_by TEXT NOT NULL,
                proposed_at REAL NOT NULL,
                confirmed_value_band TEXT NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmation_kind TEXT NOT NULL,
                confirmed_at REAL NOT NULL
            );
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
            );
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
            );
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
                PRIMARY KEY (work_item_id, outcome_id, request_id)
            );
            """
        )
        current = {
            "source_kind": "agent",
            "source_id": "agent-1",
            "recorded_at": 1.0,
            "inherited_template_id": None,
            "confirmed_by": "captain",
            "confirmed_at": 2.0,
            "confirmation_kind": "captain",
        }
        stale = {**current, "recorded_at": 9.0}
        await connection.executemany(
            "INSERT INTO work_items VALUES (?,?,?)",
            (
                ("current", "moderate", json.dumps(current)),
                ("stale", "critical", json.dumps(stale)),
            ),
        )
        await connection.executemany(
            "INSERT INTO completion_value_resolutions VALUES (?,?,?,?,?,?,?,?)",
            (
                ("current", "moderate", "agent-1", 1.0, "moderate", "captain", "captain", 2.0),
                ("stale", "minor", "agent-1", 3.0, "minor", "captain", "captain", 4.0),
            ),
        )
        await connection.execute(
            "INSERT INTO completion_calibration_outcomes VALUES (?,?,?,?,?,?,?,?,?)",
            ("current", "1" * 64, "agent-1", "task", 30, 30, None, None, 5.0),
        )
        await connection.execute(
            "INSERT INTO completion_calibration_spends VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "current", "1" * 64, "request-1", "provider-1", "fast", "fast",
                None, None, None, "model-fast", "measured", 20, 10, 30,
                2.0, 8.0, "USD", 5.0,
            ),
        )
        ledger = CompletionCalibrationLedger(connection)
        await ledger.migrate()
        await ledger.migrate()
        resolutions = await (await connection.execute(
            "SELECT work_item_id, declaration_value_band, declaration_source_kind, "
            "declaration_source_id, declaration_recorded_at, proposed_value_band, "
            "confirmed_value_band FROM completion_value_resolutions "
            "ORDER BY work_item_id",
        )).fetchall()
        spend = await (await connection.execute(
            "SELECT prompt_tokens, completion_tokens, total_tokens, "
            "provider_reported_prompt_tokens, "
            "provider_reported_completion_tokens, provider_reported_total_tokens "
            "FROM completion_calibration_spends",
        )).fetchone()
        assert [tuple(row) for row in resolutions] == [
            ("current", "moderate", "agent", "agent-1", 1.0, "moderate", "moderate"),
            ("stale", None, None, None, None, "minor", "minor"),
        ]
        assert tuple(spend) == (20, 10, 30, 20, 10, 30)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_incompatible_partial_schema_rolls_back_legacy_rebuild() -> None:
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.executescript(
            """
            CREATE TABLE completion_value_resolutions (
                work_item_id TEXT NOT NULL PRIMARY KEY,
                proposed_value_band TEXT NOT NULL,
                proposed_by TEXT NOT NULL,
                proposed_at REAL NOT NULL,
                confirmed_value_band TEXT NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmation_kind TEXT NOT NULL,
                confirmed_at REAL NOT NULL
            );
            INSERT INTO completion_value_resolutions
            VALUES ('work-1','minor','agent-1',1.0,'minor','captain','captain',2.0);
            CREATE TABLE completion_calibration_outcomes (work_item_id TEXT);
            """
        )
        ledger = CompletionCalibrationLedger(connection)
        with pytest.raises(
            ValueError,
            match="completion_calibration_schema_invalid:"
            "completion_calibration_outcomes",
        ):
            await ledger.migrate()
        columns = await (await connection.execute(
            "PRAGMA table_info(completion_value_resolutions)",
        )).fetchall()
        rows = await (await connection.execute(
            "SELECT * FROM completion_value_resolutions",
        )).fetchall()
        assert [column[1] for column in columns] == [
            "work_item_id",
            "proposed_value_band",
            "proposed_by",
            "proposed_at",
            "confirmed_value_band",
            "confirmed_by",
            "confirmation_kind",
            "confirmed_at",
        ]
        assert len(rows) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_wrong_declaration_index_predicate_is_rejected_without_duplicates() -> None:
    connection, ledger = await _ledger()
    try:
        wrong_sql = await _replace_declaration_index_with_agent_predicate(
            connection,
        )
        assert "WHERE declaration_source_kind='agent'" in wrong_sql
        metadata = await (
            await connection.execute(
                "PRAGMA index_list(completion_value_resolutions)",
            )
        ).fetchall()
        columns = await (
            await connection.execute(
                "PRAGMA index_info(completion_value_resolutions_declaration)",
            )
        ).fetchall()
        assert next(row for row in metadata if row[1] == (
            "completion_value_resolutions_declaration"
        ))[2:5:2] == (1, 1)
        assert tuple(row[2] for row in columns) == (
            "work_item_id",
            "declaration_value_band",
            "declaration_source_kind",
            "declaration_source_id",
            "declaration_recorded_at",
        )

        with pytest.raises(
            ValueError,
            match="completion_calibration_schema_invalid:"
            "completion_value_resolutions",
        ):
            await ledger.migrate()

        stored_sql = await (
            await connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE name='completion_value_resolutions_declaration'",
            )
        ).fetchone()
        assert stored_sql is not None and stored_sql[0] == wrong_sql
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_duplicate_complete_bound_identities_fail_migration_transactionally() -> None:
    connection, ledger = await _ledger()
    try:
        await connection.execute(
            "INSERT INTO completion_calibration_stats (agent_id, work_type) "
            "VALUES ('unrelated-agent','task')",
        )
        wrong_sql = await _replace_declaration_index_with_agent_predicate(
            connection,
        )
        assert "WHERE declaration_source_kind='agent'" in wrong_sql
        duplicate = (
            "work-duplicate",
            "moderate",
            "captain",
            "captain-1",
            10.0,
            "moderate",
            "captain-1",
            11.0,
            "moderate",
            "captain-1",
            "captain",
            11.0,
        )
        await connection.executemany(
            "INSERT INTO completion_value_resolutions ("
            "work_item_id, declaration_value_band, declaration_source_kind, "
            "declaration_source_id, declaration_recorded_at, "
            "proposed_value_band, proposed_by, proposed_at, "
            "confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (duplicate, duplicate),
        )
        duplicate_count = await (
            await connection.execute(
                "SELECT COUNT(*) FROM completion_value_resolutions "
                "WHERE work_item_id='work-duplicate'",
            )
        ).fetchone()
        before_stats = await (
            await connection.execute(
                "SELECT * FROM completion_calibration_stats "
                "WHERE agent_id='unrelated-agent'",
            )
        ).fetchall()
        assert duplicate_count is not None and duplicate_count[0] == 2

        with pytest.raises(
            ValueError,
            match="completion_calibration_schema_invalid:"
            "completion_value_resolutions",
        ):
            await ledger.migrate()

        after_sql = await (
            await connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE name='completion_value_resolutions_declaration'",
            )
        ).fetchone()
        after_rows = await (
            await connection.execute(
                "SELECT * FROM completion_value_resolutions "
                "WHERE work_item_id='work-duplicate' ORDER BY resolution_id",
            )
        ).fetchall()
        after_stats = await (
            await connection.execute(
                "SELECT * FROM completion_calibration_stats "
                "WHERE agent_id='unrelated-agent'",
            )
        ).fetchall()
        legacy_artifacts = await (
            await connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE name LIKE 'completion_%_legacy'",
            )
        ).fetchall()
        assert after_sql is not None and after_sql[0] == wrong_sql
        assert len(after_rows) == 2
        assert [tuple(row) for row in after_stats] == [
            tuple(row) for row in before_stats
        ]
        assert legacy_artifacts == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_duplicate_bound_identity_check_is_independent_of_stored_ddl_check() -> None:
    connection, ledger = await _ledger()
    try:
        valid_sql_row = await (
            await connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE name='completion_value_resolutions_declaration'",
            )
        ).fetchone()
        assert valid_sql_row is not None
        valid_sql = str(valid_sql_row[0])
        await _replace_declaration_index_with_agent_predicate(connection)
        duplicate = (
            "work-duplicate-defense",
            "moderate",
            "captain",
            "captain-1",
            10.0,
            "moderate",
            "captain-1",
            11.0,
            "moderate",
            "captain-1",
            "captain",
            11.0,
        )
        await connection.executemany(
            "INSERT INTO completion_value_resolutions ("
            "work_item_id, declaration_value_band, declaration_source_kind, "
            "declaration_source_id, declaration_recorded_at, "
            "proposed_value_band, proposed_by, proposed_at, "
            "confirmed_value_band, confirmed_by, confirmation_kind, confirmed_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (duplicate, duplicate),
        )
        await connection.execute("PRAGMA writable_schema=ON")
        await connection.execute(
            "UPDATE sqlite_schema SET sql=? "
            "WHERE name='completion_value_resolutions_declaration'",
            (valid_sql,),
        )
        await connection.execute("PRAGMA writable_schema=OFF")
        stored_sql = await (
            await connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE name='completion_value_resolutions_declaration'",
            )
        ).fetchone()
        duplicate_count = await (
            await connection.execute(
                "SELECT COUNT(*) FROM completion_value_resolutions "
                "WHERE work_item_id='work-duplicate-defense'",
            )
        ).fetchone()
        assert stored_sql is not None and stored_sql[0] == valid_sql
        assert duplicate_count is not None and duplicate_count[0] == 2

        with pytest.raises(
            ValueError,
            match="completion_calibration_schema_invalid:"
            "completion_value_resolutions",
        ):
            await ledger.migrate()

        remaining = await (
            await connection.execute(
                "SELECT COUNT(*) FROM completion_value_resolutions "
                "WHERE work_item_id='work-duplicate-defense'",
            )
        ).fetchone()
        assert remaining is not None and remaining[0] == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_public_store_restart_rejects_corrupted_declaration_index(
    tmp_path,
) -> None:
    db_path = tmp_path / "corrupted-restart.db"
    config = {
        "completion_calibration": {
            "enabled": True,
            "minimum_samples": 1,
        }
    }
    original = WorkItemStore(
        db_path=str(db_path),
        tick_interval=3600,
        config=config,
    )
    await original.start()
    await original.stop()
    connection = await aiosqlite.connect(db_path)
    try:
        wrong_sql = await _replace_declaration_index_with_agent_predicate(
            connection,
        )
        await connection.commit()
    finally:
        await connection.close()

    reopened = WorkItemStore(
        db_path=str(db_path),
        tick_interval=3600,
        config=config,
    )
    with pytest.raises(
        ValueError,
        match="completion_calibration_schema_invalid:"
        "completion_value_resolutions",
    ):
        await reopened.start()

    connection = await aiosqlite.connect(db_path)
    try:
        stored_sql = await (
            await connection.execute(
                "SELECT sql FROM sqlite_schema "
                "WHERE name='completion_value_resolutions_declaration'",
            )
        ).fetchone()
        assert stored_sql is not None and stored_sql[0] == wrong_sql
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_flag_off_startup_creates_no_calibration_tables(tmp_path) -> None:
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        tick_interval=3600,
        config={"completion_calibration": {"enabled": False}},
    )
    await store.start()
    await store.stop()
    connection = await aiosqlite.connect(tmp_path / "workforce.db")
    try:
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'completion_calibration_%'"
        )
        assert await cursor.fetchall() == []
    finally:
        await connection.close()


def test_ledger_uses_injected_database_connection_and_contains_no_direct_connect() -> None:
    source = inspect.getsource(CompletionCalibrationLedger)
    assert "aiosqlite" not in source
    assert ".connect(" not in source
