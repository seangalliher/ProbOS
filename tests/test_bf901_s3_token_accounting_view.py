"""BF-901 S3 (#1575): the doctor's ``token_accounting`` view of the cognitive journal.

The contract is ``prompts/bf-901-s3-doctor-token-accounting-view.md``. Rows are written through the real
``CognitiveJournal.record`` (BF-901 S2's writer) into ``tmp_path`` and read back by the real check, or the real
reader, through the real read-only open, so each journal test crosses the seam the view depends on: what the
journal writes is what the doctor reports. The runner tests drive the real ``run_doctor``. Third-party and
standard-library classes are imported under underscore aliases (the phantom-API precheck reads the contract's
code). The contract's section 10 names the test that kills each mutant.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from argparse import Namespace as _Namespace  # a standard-library class, aliased (see the docstring)
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from rich.console import Console as _Console  # a third-party class, aliased (see the docstring)

from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.journal_token_report import (
    BUCKET_ESTIMATED,
    BUCKET_MEASURED,
    BUCKET_MOCK,
    BUCKET_OTHER,
    BUCKET_REPLAYED,
    BUCKET_UNCHARGED,
    read_journal_token_report,
)
from probos.doctor import registry as registry_module
from probos.doctor.checks import token_accounting_check
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.doctor.runner import run_doctor
from probos.storage.sqlite_factory import default_factory

DAY1 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
DAY2 = datetime(2026, 10, 21, 12, tzinfo=timezone.utc).timestamp()
HOUR = 3600.0

# One row per bucket across two tiers, two intents and two UTC days (T1, T2, T8, T10).
SPREAD_ROWS: list[dict[str, Any]] = [
    {"timestamp": DAY1, "tier": "standard", "intent": "proactive_think", "model": "claude-sonnet-5.5",
     "prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100, "token_source": "measured"},
    {"timestamp": DAY2, "tier": "deep", "intent": "ward_room_notification", "model": "claude-opus-4-6",
     "total_tokens": 40, "token_source": "estimated", "dag_node_id": "st:c1:0:compose"},
    {"timestamp": DAY2 + HOUR, "tier": "standard", "intent": "ward_room_notification", "model": "unknown",
     "dag_node_id": "st:c1:1:evaluate"},
    {"timestamp": DAY2 + 2 * HOUR, "tier": "deep", "intent": "ward_room_notification",
     "model": "claude-opus-4-6", "total_tokens": 30, "token_source": "estimated", "cached": True},
    {"timestamp": DAY1 + HOUR, "tier": "standard", "intent": "proactive_think", "model": "mock",
     "total_tokens": 32, "token_source": "measured"},
]
SPREAD_SUMMARY = (
    "Token accounting: 140 tokens spent over 2 calls (100 measured, 40 estimated), 2026-10-20 to 2026-10-21 UTC"
)
STANDARD_TIER = (
    "  standard: measured 100 tokens over 1 call; estimated 0 tokens over 0 calls; "
    "uncharged 0 tokens over 1 call; mock 32 tokens over 1 call"
)
DEEP_TIER = (
    "  deep: measured 0 tokens over 0 calls; estimated 40 tokens over 1 call; replayed 30 tokens over 1 call"
)
NEWEST_DAY = (
    "  2026-10-21: measured 0 tokens over 0 calls; estimated 40 tokens over 1 call; "
    "uncharged 0 tokens over 1 call; replayed 30 tokens over 1 call"
)
_PRE_BF901_JOURNAL = (
    "CREATE TABLE journal (id TEXT PRIMARY KEY, timestamp REAL NOT NULL, agent_id TEXT NOT NULL, "
    "tier TEXT NOT NULL DEFAULT 'standard', model TEXT NOT NULL DEFAULT '', "
    "total_tokens INTEGER NOT NULL DEFAULT 0, intent TEXT NOT NULL DEFAULT '', "
    "cached INTEGER NOT NULL DEFAULT 0, dag_node_id TEXT NOT NULL DEFAULT '')"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(data_dir: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=data_dir, data_dir=data_dir, config_path=None)


def _check() -> Any:
    return token_accounting_check._TokenAccountingCheck()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


async def _journal(data_dir: Path, rows: list[dict[str, Any]]) -> Path:
    """Write ``rows`` through the real journal (BF-901 S2's writer), then close it."""
    path = data_dir / "cognitive_journal.db"
    journal = CognitiveJournal(db_path=str(path))
    await journal.start()
    try:
        for index, row in enumerate(rows):
            await journal.record(entry_id=f"e{index}", agent_id="a1", **row)
    finally:
        await journal.stop()
    return path


async def _report(path: Path) -> Any:
    conn = await default_factory.connect(str(path), read_only=True)
    try:
        return await read_journal_token_report(conn)
    finally:
        await conn.close()


@pytest.fixture
def fresh_registry():
    """Swap the module-level registry for an empty one (tests/test_ad801_doctor.py's fixture, copied)."""
    saved_checks = list(registry_module._CHECKS)
    saved_names = set(registry_module._NAMES)
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    yield
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    registry_module._CHECKS.extend(saved_checks)
    registry_module._NAMES.update(saved_names)


@dataclass(frozen=True)
class _Stub:
    name: str
    result: CheckResult

    async def run(self, ctx: DoctorContext) -> CheckResult:
        return self.result


class _RecordingFactory:
    """Delegates to the real factory and records how each store was opened (BF-906's recorder)."""

    def __init__(self) -> None:
        self.read_only: list[bool] = []

    async def connect(self, db_path: str, *, read_only: bool = False) -> Any:
        self.read_only.append(read_only)
        return await default_factory.connect(db_path, read_only=read_only)


async def _doctor_lines(ctx: DoctorContext) -> tuple[int, list[str]]:
    console = _Console(record=True, width=240, soft_wrap=True)
    code = await run_doctor(_Namespace(), console, ctx=ctx)
    return code, console.export_text().splitlines()


# ---------------------------------------------------------------------------
# 1. The breakdown (T1, T2)
# ---------------------------------------------------------------------------


async def test_the_view_splits_spend_by_source_per_tier_intent_and_day(tmp_path: Path) -> None:
    path = await _journal(tmp_path, SPREAD_ROWS)
    before = (_sha256(path), _listing(tmp_path))

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.message == SPREAD_SUMMARY
    lines = result.detail.splitlines()
    tiers = lines.index("By tier:")
    assert lines[tiers + 1 : tiers + 3] == [STANDARD_TIER, DEEP_TIER]
    intents = lines.index("By intent:")
    assert lines[intents + 1].startswith("  proactive_think: measured 100 tokens over 1 call;")
    assert lines[intents + 2].startswith("  ward_room_notification: measured 0 tokens over 0 calls;")
    assert lines[lines.index("By UTC day, newest first:") + 1] == NEWEST_DAY
    assert lines[-1] == "Rows naming no model: none."
    assert (_sha256(path), _listing(tmp_path)) == before  # nothing written, no side file


async def test_the_reader_puts_each_row_in_exactly_one_bucket(tmp_path: Path) -> None:
    report = await _report(await _journal(tmp_path, SPREAD_ROWS))

    assert report.has_token_source is True
    assert report.total.tokens == {
        BUCKET_MEASURED: 100, BUCKET_ESTIMATED: 40, BUCKET_UNCHARGED: 0,
        BUCKET_REPLAYED: 30, BUCKET_MOCK: 32, BUCKET_OTHER: 0,
    }
    assert report.total.calls == {
        BUCKET_MEASURED: 1, BUCKET_ESTIMATED: 1, BUCKET_UNCHARGED: 1,
        BUCKET_REPLAYED: 1, BUCKET_MOCK: 1, BUCKET_OTHER: 0,
    }
    assert [group.key for group in report.by_tier] == ["standard", "deep"]
    assert [group.key for group in report.by_day] == ["2026-10-21", "2026-10-20"]
    assert (report.first_day, report.last_day) == ("2026-10-20", "2026-10-21")
    assert report.labelled_since == DAY1


# ---------------------------------------------------------------------------
# 2. Rows that name no model (T3, T4)
# ---------------------------------------------------------------------------


async def test_a_row_without_a_model_after_token_sources_began_warns(tmp_path: Path) -> None:
    await _journal(tmp_path, [
        {"timestamp": DAY1, "tier": "standard", "intent": "proactive_think", "model": "m1",
         "total_tokens": 10, "token_source": "measured"},
        {"timestamp": DAY1 + 6 * HOUR, "tier": "standard", "intent": "proactive_think", "model": "",
         "dag_node_id": "st:c9:0:compose"},
        {"timestamp": DAY2, "tier": "deep", "intent": "proactive_think", "model": "m2",
         "total_tokens": 20, "token_source": "estimated"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.message == (
        "Token accounting: 1 journal row with no model since token sources began on 2026-10-20"
    )
    assert result.remediation.startswith("BF-901 requires every journal row to name the model that answered")
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 1 (1 chain step), the last on 2026-10-20; "
        "1 since token sources began on 2026-10-20."
    )


async def test_rows_without_a_model_from_before_token_sources_are_reported_not_warned(tmp_path: Path) -> None:
    await _journal(tmp_path, [
        {"timestamp": DAY1, "intent": "ward_room_notification", "model": "", "dag_node_id": "st:c1:0:compose"},
        {"timestamp": DAY1 + HOUR, "intent": "proactive_think", "model": ""},
        {"timestamp": DAY2, "intent": "proactive_think", "model": "m1", "total_tokens": 10,
         "token_source": "measured"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 2 (1 chain step), the last on 2026-10-20; "
        "0 since token sources began on 2026-10-21."
    )


# ---------------------------------------------------------------------------
# 3. Journals that are old, absent, empty or unreadable (T5, T6, T7)
# ---------------------------------------------------------------------------


async def test_a_journal_from_before_bf901_is_read_as_it_is_without_a_fail(tmp_path: Path) -> None:
    path = tmp_path / "cognitive_journal.db"
    async with aiosqlite.connect(str(path)) as db:
        await db.execute(_PRE_BF901_JOURNAL)
        await db.executemany(
            "INSERT INTO journal (id, timestamp, agent_id, tier, model, total_tokens, intent, dag_node_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("r1", DAY1, "a1", "standard", "", 0, "ward_room_notification", "st:c1:0:compose"),
                ("r2", DAY1 + HOUR, "a1", "deep", "mock", 32, "proactive_think", ""),
                ("r3", DAY1 + 2 * HOUR, "a1", "standard", "claude-sonnet-5.5", 0, "proactive_think", ""),
            ],
        )
        await db.commit()
    before = (_sha256(path), _listing(tmp_path))

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.message == (
        "Token accounting: 0 tokens spent over 0 calls (0 measured, 0 estimated), 2026-10-20 to 2026-10-20 UTC; "
        "this journal predates BF-901: no row carries a token source until ProbOS restarts on BF-901, "
        "which adds the column"
    )
    assert result.detail.splitlines()[-1] == (
        "Rows naming no model: 1 (1 chain step), the last on 2026-10-20; "
        "no row carries a token source yet, so none can be dated after BF-901."
    )
    assert (_sha256(path), _listing(tmp_path)) == before  # never migrated
    report = await _report(path)
    assert report.has_token_source is False
    assert (report.total.calls[BUCKET_UNCHARGED], report.total.calls[BUCKET_MOCK]) == (2, 1)


@pytest.mark.parametrize("state", ["missing", "zero_byte", "no_journal_table", "empty_journal"])
async def test_a_missing_or_empty_journal_is_ok_and_left_as_it_was(tmp_path: Path, state: str) -> None:
    path = tmp_path / "cognitive_journal.db"
    if state == "zero_byte":  # SQLite's empty database; a healthy first start passes through it (A1, F2)
        path.write_bytes(b"")
    elif state == "no_journal_table":
        async with aiosqlite.connect(str(path)) as db:
            await db.execute("CREATE TABLE unrelated (x INTEGER)")
            await db.commit()
    elif state == "empty_journal":
        await _journal(tmp_path, [])
    before = _listing(tmp_path)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    expected = "no cognitive journal yet" if state == "missing" else "no model calls recorded yet"
    assert result.message == f"Token accounting: {expected}"
    assert result.detail == ""
    assert _listing(tmp_path) == before  # the read-only open creates nothing
    assert state != "zero_byte" or path.read_bytes() == b""  # nothing created the schema


async def test_an_unreadable_journal_warns_and_does_not_fail(tmp_path: Path) -> None:
    (tmp_path / "cognitive_journal.db").write_bytes(b"this is not a SQLite database. " * 64)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.message.startswith("Token accounting: could not read cognitive_journal.db: ")
    assert result.remediation == "The running vessel may be writing to it; rerun `probos doctor`."


async def test_the_check_opens_the_journal_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await _journal(tmp_path, SPREAD_ROWS[:1])
    recorder = _RecordingFactory()
    monkeypatch.setattr(token_accounting_check, "default_factory", recorder)

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK  # premise: the read went through the recorder
    assert recorder.read_only == [True]


@pytest.mark.parametrize("timestamp", [1e30, -1e30])
async def test_a_timestamp_no_calendar_day_can_name_warns_through_run_doctor_without_raising(
    fresh_registry: None, tmp_path: Path, timestamp: float,
) -> None:
    await _journal(tmp_path, [
        {"timestamp": timestamp, "intent": "proactive_think", "model": "m1", "total_tokens": 10,
         "token_source": "measured"},
        {"timestamp": timestamp, "intent": "proactive_think", "model": ""},
    ])
    register_check(_check())

    code, lines = await _doctor_lines(_ctx(tmp_path))

    assert code == 0  # a WARN, not a check that raised (the runner counts that as FAIL)
    assert not any("check raised" in line for line in lines)
    assert any(line.endswith(
        "Token accounting: 1 journal row with no model since token sources began on (unknown day)"
    ) for line in lines)
    assert (
        "    Rows naming no model: 1 (0 chain steps), the last on (unknown day); "
        "1 since token sources began on (unknown day)."
    ) in lines
    assert lines[-1] == "No check failed; 1 warning(s) above."


async def test_days_no_calendar_date_can_name_read_as_unknown_in_the_summary(tmp_path: Path) -> None:
    await _journal(tmp_path, [
        {"timestamp": 1e30, "intent": "proactive_think", "model": "m1", "total_tokens": 10,
         "token_source": "measured"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert result.message == (
        "Token accounting: 10 tokens spent over 1 call (10 measured, 0 estimated), "
        "(unknown day) to (unknown day) UTC"
    )
    assert result.detail.splitlines()[-1] == "Rows naming no model: none."


async def test_a_stored_value_the_reader_cannot_convert_warns_and_does_not_raise(tmp_path: Path) -> None:
    await _journal(tmp_path, [  # the REAL column keeps a non-numeric text value as text
        {"timestamp": "not a time", "intent": "proactive_think", "model": "m1", "total_tokens": 10,
         "token_source": "measured"},
    ])

    result = await _check().run(_ctx(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.message.startswith("Token accounting: cognitive_journal.db holds a value this view cannot read: ")
    assert result.remediation == (
        "A journal row's timestamp or token count is not a number in range. Find it on a copy of "
        "cognitive_journal.db."
    )
    assert result.detail == ""


# ---------------------------------------------------------------------------
# 4. The runner and the registration (T9, T10, T11)
# ---------------------------------------------------------------------------


async def test_detail_shows_on_every_outcome_and_remediation_only_on_warn_or_fail(
    fresh_registry: None, tmp_path: Path,
) -> None:
    register_check(_Stub("ok_stub", CheckResult(
        CheckOutcome.OK, "ok-summary", "ok-hidden-remediation", "ok-detail-1\nok-detail-2",
    )))
    register_check(_Stub("warn_stub", CheckResult(CheckOutcome.WARN, "warn-summary", "warn-remediation", "warn-detail")))
    register_check(_Stub("fail_stub", CheckResult(CheckOutcome.FAIL, "fail-summary", "fail-remediation", "fail-detail")))
    register_check(_Stub("plain_stub", CheckResult(CheckOutcome.OK, "plain-summary")))

    code, lines = await _doctor_lines(_ctx(tmp_path))

    assert code == 1  # the FAIL counts and the WARN does not (runner.py's contract, unchanged)
    ok = next(i for i, line in enumerate(lines) if "ok-summary" in line)
    assert lines[ok + 1 : ok + 3] == ["    ok-detail-1", "    ok-detail-2"]
    assert not any("ok-hidden-remediation" in line for line in lines)
    warn = next(i for i, line in enumerate(lines) if "warn-summary" in line)
    assert lines[warn + 1 : warn + 3] == ["    warn-remediation", "    warn-detail"]
    fail = next(i for i, line in enumerate(lines) if "fail-summary" in line)
    assert lines[fail + 1 : fail + 3] == ["    fail-remediation", "    fail-detail"]
    plain = next(i for i, line in enumerate(lines) if "plain-summary" in line)
    assert lines[plain + 1] == ""  # no detail, nothing rendered: the runner's closing blank line follows
    assert lines[-1] == "1 issue(s) found."


async def test_the_real_check_renders_its_breakdown_through_run_doctor(
    fresh_registry: None, tmp_path: Path,
) -> None:
    await _journal(tmp_path, SPREAD_ROWS)
    register_check(_check())

    code, lines = await _doctor_lines(_ctx(tmp_path))

    assert code == 0
    assert any(line.endswith(SPREAD_SUMMARY) for line in lines)
    assert "    " + STANDARD_TIER in lines
    assert "    " + NEWEST_DAY in lines


def test_the_check_is_registered_once_after_crew_enrollment() -> None:
    """A fresh interpreter, so that this file's own import of the check module cannot stand in for the
    registration line in ``probos/doctor/checks/__init__.py`` (tests/test_bf906_doctor_check.py's probe)."""
    import probos

    src_dir = Path(probos.__file__).resolve().parents[1]
    probe = (
        "import json; from probos.doctor import checks; from probos.doctor.registry import iter_checks; "
        "print(json.dumps([[c.name, type(c).__qualname__] for c in iter_checks()]))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
    )
    assert done.returncode == 0, done.stderr
    registered = json.loads(done.stdout.strip().splitlines()[-1])
    names = [name for name, _ in registered]

    assert [kind for name, kind in registered if name == "token_accounting"] == ["_TokenAccountingCheck"]
    assert names[names.index("crew_enrollment") + 1] == "token_accounting"
    assert names[names.index("extras") + 1] == "verifier_independence"
