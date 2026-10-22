"""BF-901 S3 (#1575): the journal's token spend per tier, per intent and per UTC day, measured and estimated apart.

Reads cognitive_journal.db through the approved ConnectionFactory adapter's ``read_only`` open (SQLite
``mode=ro``), as BF-906's crew_enrollment check reads its stores: it never creates the file, never writes and
never migrates, so a journal that predates BF-901 is read as it is. The journal runs in SQLite's default
rollback mode (the journal's ``start`` sets no journal mode), so each read statement holds a shared lock
while it runs; the vessel's writer waits for it under its connection's default busy timeout.

The outcome is OK or WARN, never FAIL: this is an account, not a component that can be broken. WARN means the
journal could not be read or holds a value the reader cannot convert, or a row recorded since the first row
with a token source names no model (BF-901 requires the answering model or ``unknown``). The breakdown is the
result's ``detail``, shown on every outcome; a day no calendar date can name reads ``(unknown day)``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from probos.cognitive.journal_token_report import (
    BUCKET_ESTIMATED,
    BUCKET_MEASURED,
    BUCKET_MOCK,
    BUCKET_OTHER,
    BUCKET_REPLAYED,
    BUCKET_UNCHARGED,
    GroupUsage,
    JournalTokenReport,
    read_journal_token_report,
)
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.storage.sqlite_factory import default_factory

#: The file ``startup/communication.py`` opens under the data directory.
JOURNAL_FILE = "cognitive_journal.db"
#: Shown per dimension; the rest are counted in one line.
MAX_INTENTS = 8
MAX_DAYS = 7
_BUSY_TIMEOUT_S = 2.0
_LEGEND = (
    "Spend is measured plus estimated. Replayed rows (cached) and the mock client are not spend; "
    "uncharged rows made no model call, failed, or were recorded before BF-901."
)
_COVERAGE = (
    "Journaled calls only (one-shot decisions and sub-task chain steps); the agentic loop writes no journal row."
)
#: Shown for a day no calendar date names: a timestamp out of range for SQLite's date functions or Python's.
UNKNOWN_DAY = "(unknown day)"


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _utc_day(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return UNKNOWN_DAY


def _shown_day(day: str) -> str:
    """A reader's day key, or the unknown-day label when SQLite could not name the day (an empty key)."""
    return day or UNKNOWN_DAY


def _amount(group: GroupUsage, bucket: str) -> str:
    return f"{bucket} {group.tokens[bucket]:,} tokens over {_plural(group.calls[bucket], 'call')}"


def _describe(group: GroupUsage) -> str:
    """One group's line: measured and estimated always, the other buckets when they hold a row."""
    parts = [_amount(group, BUCKET_MEASURED), _amount(group, BUCKET_ESTIMATED)]
    for bucket in (BUCKET_UNCHARGED, BUCKET_REPLAYED, BUCKET_MOCK, BUCKET_OTHER):
        if group.calls[bucket]:
            parts.append(_amount(group, bucket))
    return f"{group.key}: " + "; ".join(parts)


def _summary(report: JournalTokenReport) -> str:
    total = report.total
    text = (
        f"Token accounting: {total.spend_tokens:,} tokens spent over {_plural(total.spend_calls, 'call')} "
        f"({total.tokens[BUCKET_MEASURED]:,} measured, {total.tokens[BUCKET_ESTIMATED]:,} estimated), "
        f"{_shown_day(report.first_day)} to {_shown_day(report.last_day)} UTC"
    )
    if not report.has_token_source:
        text += (
            "; this journal predates BF-901: no row carries a token source until ProbOS restarts on BF-901, "
            "which adds the column"
        )
    return text


def _no_model_line(report: JournalTokenReport) -> str:
    if not report.no_model_rows:
        return "Rows naming no model: none."
    head = (
        f"Rows naming no model: {report.no_model_rows:,} ({_plural(report.no_model_chain_steps, 'chain step')}), "
        f"the last on {_shown_day(report.no_model_last_day)}"
    )
    if report.labelled_since is None:
        return head + "; no row carries a token source yet, so none can be dated after BF-901."
    return (
        head + f"; {report.no_model_since_labelled:,} since token sources began on "
        f"{_utc_day(report.labelled_since)}."
    )


def _detail_lines(report: JournalTokenReport) -> list[str]:
    lines = [_LEGEND, _COVERAGE, "By tier:"]
    lines.extend(f"  {_describe(group)}" for group in report.by_tier)
    lines.append("By intent:")
    lines.extend(f"  {_describe(group)}" for group in report.by_intent[:MAX_INTENTS])
    if len(report.by_intent) > MAX_INTENTS:
        lines.append(f"  ({_plural(len(report.by_intent) - MAX_INTENTS, 'more intent')})")
    lines.append("By UTC day, newest first:")
    lines.extend(f"  {_describe(group)}" for group in report.by_day[:MAX_DAYS])
    if len(report.by_day) > MAX_DAYS:
        lines.append(f"  ({_plural(len(report.by_day) - MAX_DAYS, 'earlier day')})")
    lines.append(_no_model_line(report))
    return lines


async def _read(path: Path) -> JournalTokenReport | None:
    """The report from the journal at ``path``, opened read-only and closed again."""
    conn = await default_factory.connect(str(path), read_only=True)
    try:
        await conn.execute(f"PRAGMA busy_timeout = {int(_BUSY_TIMEOUT_S * 1000)}")
        return await read_journal_token_report(conn)
    finally:
        await conn.close()


@dataclass(frozen=True)
class _TokenAccountingCheck:
    name: str = "token_accounting"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        path = ctx.data_dir / JOURNAL_FILE
        if not path.exists():
            return CheckResult(CheckOutcome.OK, "Token accounting: no cognitive journal yet")
        try:
            report = await _read(path)
        except sqlite3.Error as exc:
            return CheckResult(
                CheckOutcome.WARN,
                f"Token accounting: could not read {JOURNAL_FILE}: {exc}",
                "The running vessel may be writing to it; rerun `probos doctor`.",
            )
        except (OverflowError, TypeError, ValueError) as exc:
            return CheckResult(
                CheckOutcome.WARN,
                f"Token accounting: {JOURNAL_FILE} holds a value this view cannot read: {exc}",
                "A journal row's timestamp or token count is not a number in range. Find it on a copy of "
                "cognitive_journal.db.",
            )
        if report is None or not report.rows:
            return CheckResult(CheckOutcome.OK, "Token accounting: no model calls recorded yet")
        detail = "\n".join(_detail_lines(report))
        if report.no_model_since_labelled:
            return CheckResult(
                CheckOutcome.WARN,
                f"Token accounting: {_plural(report.no_model_since_labelled, 'journal row')} with no model "
                f"since token sources began on {_utc_day(report.labelled_since)}",
                "BF-901 requires every journal row to name the model that answered, or 'unknown'. Find the "
                "writer from these rows' dag_node_id and intent, on a copy of cognitive_journal.db.",
                detail,
            )
        return CheckResult(CheckOutcome.OK, _summary(report), "", detail)


register_check(_TokenAccountingCheck())
