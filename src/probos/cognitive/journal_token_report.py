"""BF-901 S3 (#1575): what the cognitive journal says was spent, per tier, per intent and per UTC day.

Read-only. ``read_journal_token_report`` takes a connection its caller opened (the doctor's
``token_accounting`` check opens ``cognitive_journal.db`` through the ConnectionFactory's ``read_only`` open,
as BF-906's check does) and runs at most three statements: the journal's column list, one grouped scan and,
once a row carries a token source, one count of the rows since then that name no model. It never writes,
creates or migrates anything, so a journal that predates BF-901 is read as it is.

Each row falls in exactly one bucket, tested in this order:

* ``replayed``: ``cached`` is set (a client cache replay, a decision-cache hit, a procedural replay). Never
  spend: the journal's own spend readers filter ``cached = 0``.
* ``mock``: ``model = 'mock'``, the mock client's fixed counts, which BF-901 S2 records as measured.
* ``measured`` and ``estimated``: the row's ``token_source``, as BF-901 S1's ``charge_completion`` set it.
* ``uncharged``: an empty ``token_source``: no model call (a bypassed step, a timed-out attempt), a failed
  call, or a row recorded before BF-901, which all read empty.
* ``other``: any other label. None is written today; it is counted apart so that a new label is never
  folded into another bucket.

Spend is measured plus estimated. The journal's empty source is not in ``crew_execution_usage``'s vocabulary
(measured, estimated, mixed), and nothing here passes a journal label to that module.

Only journaled calls are covered: one-shot decisions and sub-task chain steps. The agentic loop and the
other model calls that write no journal row (BF-901 S2, section 9) are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from probos.cognitive.token_accounting import TOKEN_SOURCE_NONE
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

BUCKET_MEASURED = TOKEN_SOURCE_MEASURED
BUCKET_ESTIMATED = TOKEN_SOURCE_ESTIMATED
BUCKET_UNCHARGED = "uncharged"
BUCKET_REPLAYED = "replayed"
BUCKET_MOCK = "mock"
BUCKET_OTHER = "other"
BUCKETS: tuple[str, ...] = (
    BUCKET_MEASURED, BUCKET_ESTIMATED, BUCKET_UNCHARGED, BUCKET_REPLAYED, BUCKET_MOCK, BUCKET_OTHER,
)
#: The key shown for a row whose tier or intent is empty.
NO_KEY = "(none)"

_COLUMNS_SQL = "PRAGMA table_info(journal)"
# The source expression is one of two fixed strings: the column, or an empty literal for a journal that
# predates BF-901. 'mock' is the mock client's model name (llm_client.py). 'st:' prefixes a chain step's
# dag_node_id (sub_task.py). Columns, in order: tier, intent, UTC day, source, replayed, mock, no model,
# chain step, calls, tokens, the earliest labelled timestamp in the group.
_SOURCE_COLUMN = "token_source"
_SOURCE_ABSENT = "''"
_GROUPED_SQL = (
    "SELECT tier, intent, strftime('%Y-%m-%d', timestamp, 'unixepoch'), {source}, cached <> 0, "
    "model = 'mock', model = '', dag_node_id LIKE 'st:%', COUNT(*), COALESCE(SUM(total_tokens), 0), "
    "MIN(CASE WHEN {source} <> '' THEN timestamp END) "
    "FROM journal GROUP BY 1, 2, 3, 4, 5, 6, 7, 8"
)
_NO_MODEL_SINCE_SQL = "SELECT COUNT(*) FROM journal WHERE model = '' AND timestamp >= ?"


@dataclass
class GroupUsage:
    """One tier, intent or UTC day, or the whole journal: calls and tokens per bucket."""

    key: str
    calls: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BUCKETS, 0))
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BUCKETS, 0))

    def add(self, bucket: str, calls: int, tokens: int) -> None:
        self.calls[bucket] += calls
        self.tokens[bucket] += tokens

    @property
    def rows(self) -> int:
        return sum(self.calls.values())

    @property
    def spend_tokens(self) -> int:
        """Measured plus estimated: what the journal says was spent."""
        return self.tokens[BUCKET_MEASURED] + self.tokens[BUCKET_ESTIMATED]

    @property
    def spend_calls(self) -> int:
        return self.calls[BUCKET_MEASURED] + self.calls[BUCKET_ESTIMATED]


@dataclass(frozen=True)
class JournalTokenReport:
    """What one read of the journal found. Days are UTC ``YYYY-MM-DD``; groups are in display order."""

    has_token_source: bool
    total: GroupUsage
    by_tier: tuple[GroupUsage, ...] = ()
    by_intent: tuple[GroupUsage, ...] = ()
    by_day: tuple[GroupUsage, ...] = ()
    first_day: str = ""
    last_day: str = ""
    #: The timestamp of the earliest row that carries a token source; ``None`` when none does.
    labelled_since: float | None = None
    no_model_rows: int = 0
    no_model_chain_steps: int = 0
    no_model_last_day: str = ""
    #: Rows naming no model recorded at or after ``labelled_since``: BF-901 requires a model or ``unknown``.
    no_model_since_labelled: int = 0

    @property
    def rows(self) -> int:
        return self.total.rows


def _bucket(source: object, replayed: object, mock: object) -> str:
    if replayed:
        return BUCKET_REPLAYED
    if mock:
        return BUCKET_MOCK
    if source == TOKEN_SOURCE_MEASURED:
        return BUCKET_MEASURED
    if source == TOKEN_SOURCE_ESTIMATED:
        return BUCKET_ESTIMATED
    if source == TOKEN_SOURCE_NONE:
        return BUCKET_UNCHARGED
    return BUCKET_OTHER


def _by_spend(group: GroupUsage) -> tuple[int, int, str]:
    return (-group.spend_tokens, -group.rows, group.key)


async def read_journal_token_report(conn: DatabaseConnection) -> JournalTokenReport | None:
    """Read the journal's spend by bucket; ``None`` when the database has no ``journal`` table.

    Errors propagate (``sqlite3.Error`` from SQLite): the caller decides how an unreadable store degrades.
    """
    cursor = await conn.execute(_COLUMNS_SQL)
    columns = {str(row[1]) for row in await cursor.fetchall()}
    if not columns:
        return None
    has_source = _SOURCE_COLUMN in columns
    sql = _GROUPED_SQL.format(source=_SOURCE_COLUMN if has_source else _SOURCE_ABSENT)
    cursor = await conn.execute(sql)
    grouped = await cursor.fetchall()

    total = GroupUsage("all")
    tiers: dict[str, GroupUsage] = {}
    intents: dict[str, GroupUsage] = {}
    days: dict[str, GroupUsage] = {}
    labelled_since: float | None = None
    no_model_rows = 0
    no_model_chain_steps = 0
    no_model_last_day = ""
    for tier, intent, day, source, replayed, mock, no_model, chain_step, calls, tokens, first_labelled in grouped:
        bucket = _bucket(source, replayed, mock)
        count = int(calls)
        spent = int(tokens)
        day_key = str(day or "")
        total.add(bucket, count, spent)
        for groups, key in ((tiers, tier), (intents, intent), (days, day_key)):
            name = str(key or "") or NO_KEY
            groups.setdefault(name, GroupUsage(name)).add(bucket, count, spent)
        if first_labelled is not None and (labelled_since is None or first_labelled < labelled_since):
            labelled_since = float(first_labelled)
        if no_model:
            no_model_rows += count
            if chain_step:
                no_model_chain_steps += count
            no_model_last_day = max(no_model_last_day, day_key)

    no_model_since_labelled = 0
    if labelled_since is not None and no_model_rows:
        cursor = await conn.execute(_NO_MODEL_SINCE_SQL, (labelled_since,))
        row = await cursor.fetchone()
        no_model_since_labelled = int(row[0]) if row else 0

    day_keys = sorted(key for key in days if key != NO_KEY)
    return JournalTokenReport(
        has_token_source=has_source,
        total=total,
        by_tier=tuple(sorted(tiers.values(), key=_by_spend)),
        by_intent=tuple(sorted(intents.values(), key=_by_spend)),
        by_day=tuple(sorted(days.values(), key=lambda group: group.key, reverse=True)),
        first_day=day_keys[0] if day_keys else "",
        last_day=day_keys[-1] if day_keys else "",
        labelled_since=labelled_since,
        no_model_rows=no_model_rows,
        no_model_chain_steps=no_model_chain_steps,
        no_model_last_day=no_model_last_day,
        no_model_since_labelled=no_model_since_labelled,
    )
