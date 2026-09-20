"""The external-write journal shares fault persistence, never its cache authority."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from probos.fault_issue_filings import (
    FilingUnavailable, IssueReceipt, valid_github_repository, valid_issue_receipt,
    valid_repository_url,
)
from probos.fault_report import FaultReportStore
from probos.storage.declarations import declaration_errors
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import default_factory


class _Connection:
    def __init__(self, inner):
        self.inner = inner
        self.fail_sql = ""
        self.fail_commit = False
        self.fail_schema = False
        self.fail_close = False
        self.pause_commit = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    def execute(self, sql, parameters=()):
        if self.fail_sql and self.fail_sql in sql:
            raise RuntimeError("injected persistence failure")
        return self.inner.execute(sql, parameters)

    async def executescript(self, sql):
        if self.fail_schema:
            raise RuntimeError("injected schema failure")
        await self.inner.executescript(sql)

    async def commit(self):
        if self.pause_commit:
            self.pause_commit = False
            self.entered.set()
            await self.release.wait()
        if self.fail_commit:
            self.fail_commit = False
            raise RuntimeError("injected commit failure")
        await self.inner.commit()

    async def close(self):
        await self.inner.close()
        self.closed = True
        if self.fail_close:
            raise RuntimeError("injected close failure")


class _Factory:
    def __init__(self, *, fail_schema=False, fail_close=False, pause_commit=False):
        self.options = fail_schema, fail_close, pause_commit
        self.connection = None

    async def connect(self, path):
        self.connection = _Connection(await default_factory.connect(path))
        (
            self.connection.fail_schema, self.connection.fail_close,
            self.connection.pause_commit,
        ) = self.options
        return self.connection


@pytest.fixture
async def faults(tmp_path):
    factory = _Factory()
    store = FaultReportStore(str(tmp_path / "faults.db"), connection_factory=factory)
    await store.start()
    try:
        fault = await store.file_fault(
            tool_id="browser", error_text="unknown action: key_type",
            agent_id="agent", thread_id="thread", attempted="Enter a value",
        )
        yield store, fault, factory.connection
    finally:
        await store.stop()


def _identity(fault, **changes):
    return {
        "fault_id": fault.id, "signature": fault.signature, "tool_id": fault.tool_id,
        "request_id": "request", "agent_id": fault.agent_id or "system",
        "thread_id": fault.thread_id[:64], "work_item_id": None, **changes,
    }


async def _claim(store, fault, *, minimum_occurrences=1, **changes):
    # These journal tests use a single durable occurrence under an explicit policy of one.
    return await store.issue_filings.claim(
        repository="owner/repo", minimum_occurrences=minimum_occurrences,
        **_identity(fault, **changes),
    )


async def test_claim_minimum_occurrences_is_required(faults):
    store, fault, _ = faults
    with pytest.raises(TypeError, match="minimum_occurrences"):
        await store.issue_filings.claim(repository="owner/repo", **_identity(fault))
    assert await store.issue_filings.get(fault.signature) is None


@pytest.mark.parametrize("minimum", [None, True, False, 0, -1, 1.0, "2", 2**63])
async def test_claim_invalid_minimum_is_refused_without_acquisition(faults, minimum):
    store, fault, _ = faults
    with pytest.raises(ValueError, match="invalid_minimum_occurrences"):
        await _claim(store, fault, minimum_occurrences=minimum)
    assert await store.issue_filings.get(fault.signature) is None


@pytest.mark.parametrize("minimum", [1, 2, 2**63 - 1])
async def test_claim_uses_fresh_durable_occurrences_as_witness(faults, minimum):
    store, fault, _ = faults
    with sqlite3.connect(store.db_path) as db:
        db.execute("UPDATE fault_reports SET occurrences = ? WHERE id = ?", (minimum, fault.id))
    assert fault.occurrences == 1
    claim = await _claim(store, fault, minimum_occurrences=minimum)
    assert claim.acquired and claim.fault is not fault
    assert claim.fault.occurrences == minimum


@pytest.mark.parametrize("count", [0, -1, 1.5, "invalid", float(2**63)])
async def test_claim_malformed_durable_occurrences_is_refused(faults, count):
    store, fault, _ = faults
    with sqlite3.connect(store.db_path) as db:
        db.execute("UPDATE fault_reports SET occurrences = ? WHERE id = ?", (count, fault.id))
    with pytest.raises(FilingUnavailable, match="durable_qualification_unavailable"):
        await _claim(store, fault)
    assert await store.issue_filings.get(fault.signature) is None


@pytest.mark.parametrize("previous", [None, "declined", "retryable_failure"])
async def test_claim_unqualified_acquisition_leaves_journal_unchanged(faults, previous):
    store, fault, _ = faults
    if previous == "declined":
        await store.issue_filings.decline(**_identity(fault))
    elif previous == "retryable_failure":
        claim = await _claim(store, fault)
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id,
            disposition="retryable_failure", failure_code="pre_send_failure",
        )
    before = await store.issue_filings.get(fault.signature)
    with pytest.raises(FilingUnavailable, match="durable_qualification_unavailable"):
        await _claim(store, fault, minimum_occurrences=2)
    assert await store.issue_filings.get(fault.signature) == before


@pytest.mark.parametrize("disposition", ["attempting", "outcome_unknown", "filed"])
async def test_claim_existing_nonreplayable_attempt_survives_threshold_increase(faults, disposition):
    store, fault, _ = faults
    claim = await _claim(store, fault)
    if disposition != "attempting":
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id, disposition=disposition,
            receipt=IssueReceipt(37, "https://github.com/owner/repo/issues/37")
            if disposition == "filed" else None,
        )
    before = await store.issue_filings.get(fault.signature)
    reused = await _claim(store, fault, minimum_occurrences=3)
    assert not reused.acquired and reused.filing == before
    assert reused.fault.occurrences == 1


INVALID_ISSUE_URLS = (
    "", None,
    "http://github.com/owner/repo/issues/37",
    "HTTPS://github.com/owner/repo/issues/37",
    "https://GitHub.com/owner/repo/issues/37",
    "https://github.com.evil.invalid/owner/repo/issues/37",
    "https://user@github.com/owner/repo/issues/37",
    "https://github.com:443/owner/repo/issues/37",
    "https://github.com/owner/repo/issues/37?",
    "https://github.com/owner/repo/issues/37?x=1",
    "https://github.com/owner/repo/issues/37#",
    "https://github.com/owner/repo/issues/37#fragment",
    "\nhttps://github.com/owner/repo/issues/37",
    "https://github.com/owner/repo/issues/37\n",
    "https://github.com/owner/repo/issues/37 ",
    "https://github.com/own\ter/repo/issues/37",
    "https://github.com/owner/repo/issues/37\x7f",
    "https://github.com/%6fwner/repo/issues/37",
    "https://github.com/owner/%72epo/issues/37",
    "https://github.com/owner/repo/%69ssues/37",
    "https://github.com/owner/repo/issues/%33%37",
    "https://github.com/owner%2Frepo/issues/37",
    "https://github.com/owner/repo/Issues/37",
    "https://github.com/owner/repo/issues/37/more",
    "https://github.com/owner/repo/issues/37/",
    "https://github.com/other/repo/issues/37",
    "https://github.com/owner/other/issues/37",
    "https://github.com/owner/repo/issues/38",
    "https://github.com/owner/repo/issues/037",
    "https://github.com/owner/repo/issues/+37",
    "https://github.com/owner/repo/issues/0",
)
INVALID_REPOSITORY_URLS = (
    "", None,
    "http://api.github.com/repos/owner/repo",
    "HTTPS://api.github.com/repos/owner/repo",
    "https://API.github.com/repos/owner/repo",
    "https://api.github.com.evil.invalid/repos/owner/repo",
    "https://user@api.github.com/repos/owner/repo",
    "https://api.github.com:443/repos/owner/repo",
    "https://api.github.com/repos/owner/repo?",
    "https://api.github.com/repos/owner/repo?x=1",
    "https://api.github.com/repos/owner/repo#",
    "https://api.github.com/repos/owner/repo#fragment",
    "\nhttps://api.github.com/repos/owner/repo",
    "https://api.github.com/repos/owner/repo\n",
    "https://api.github.com/repos/owner/repo ",
    "https://api.github.com/repos/own\ter/repo",
    "https://api.github.com/repos/owner/repo\x7f",
    "https://api.github.com/repos/%6fwner/repo",
    "https://api.github.com/repos/owner/%72epo",
    "https://api.github.com/%72epos/owner/repo",
    "https://api.github.com/repos/owner%2Frepo",
    "https://api.github.com/Repos/owner/repo",
    "https://api.github.com/repos/owner/repo/more",
    "https://api.github.com/repos/owner/repo/",
    "https://api.github.com/repos/other/repo",
    "https://api.github.com/repos/owner/other",
)


@pytest.mark.parametrize("url", INVALID_ISSUE_URLS)
def test_valid_issue_receipt_rejects_noncanonical_structure(url):
    assert not valid_issue_receipt("owner/repo", IssueReceipt(37, url))


@pytest.mark.parametrize("url", INVALID_REPOSITORY_URLS)
def test_repository_url_rejects_noncanonical_structure(url):
    assert not valid_repository_url("owner/repo", url)


@pytest.mark.parametrize("number", [None, True, False, 0, -1, 37.0, "37"])
def test_valid_issue_receipt_requires_positive_integer_spelling(number):
    assert not valid_issue_receipt("owner/repo", IssueReceipt(number, f"https://github.com/owner/repo/issues/{number}"))


@pytest.mark.parametrize("repository", ["a/repo", "a-b/R_epo.git", "A" * 39 + "/Repo"])
def test_repository_grammar_accepts_single_hyphens_and_length_boundary(repository):
    assert valid_github_repository(repository)


@pytest.mark.parametrize("repository", [
    None, "", "a--b/repo", "-a/repo", "a-/repo", "a_b/repo", "a" * 40 + "/repo",
])
def test_repository_grammar_rejects_invalid_owner(repository):
    assert not valid_github_repository(repository)
    assert not valid_repository_url(repository, "https://api.github.com/repos/owner/repo")
    assert not valid_issue_receipt(repository, IssueReceipt(37, "https://github.com/owner/repo/issues/37"))


async def test_canonical_case_receipt_complete_reopen_retains_pinned_repository(faults):
    store, fault, _ = faults
    claim = await _claim(store, fault)
    receipt = IssueReceipt(37, "https://github.com/Owner/RePo/issues/37")
    assert valid_issue_receipt("owner/repo", receipt)
    result = await store.issue_filings.complete(
        fault.signature, claim.filing.attempt_id, disposition="filed", receipt=receipt,
    )
    assert result.repository == "owner/repo" and result.issue_url == receipt.url
    await store.stop()
    await store.start()
    assert await store.issue_filings.get(fault.signature) == result
    assert (await _claim(store, fault, minimum_occurrences=3)).filing == result


async def test_claim_receipt_reopen_preserves_fault_identity(faults):
    store, fault, _ = faults
    original = fault.to_dict()
    claim = await _claim(store, fault)
    receipt = IssueReceipt(37, "https://github.com/owner/repo/issues/37")
    result = await store.issue_filings.complete(
        fault.signature, claim.filing.attempt_id, disposition="filed", receipt=receipt,
    )
    assert result.disposition == "filed" and result.issue_url == receipt.url
    await store.stop()
    await store.start()
    assert await store.issue_filings.get(fault.signature) == result
    assert store.get(fault.id).to_dict() == original
    assert store.list_open()[0].status == "open"


async def test_claim_simultaneous_connections_have_one_winner(faults):
    store, fault, _ = faults
    second = FaultReportStore(store.db_path)
    await second.start()
    try:
        results = await asyncio.gather(_claim(store, fault), _claim(second, fault))
        assert sorted(result.acquired for result in results) == [False, True]
        assert results[0].filing.attempt_id == results[1].filing.attempt_id
    finally:
        await second.stop()


@pytest.mark.parametrize("changes", [
    {"fault_id": "missing"}, {"signature": "b" * 64}, {"tool_id": "shell"},
    {"agent_id": "other"}, {"thread_id": "other"}, {"work_item_id": "other"},
])
async def test_claim_wrong_persisted_identity_is_refused(faults, changes):
    store, fault, _ = faults
    with pytest.raises(FilingUnavailable):
        await _claim(store, fault, **changes)
    assert await store.issue_filings.get(fault.signature) is None


async def test_claim_cache_only_is_not_authority():
    store = FaultReportStore()
    await store.start()
    fault = await store.file_fault(tool_id="browser", error_text="failed")
    with pytest.raises(FilingUnavailable, match="unavailable"):
        await _claim(store, fault)
    with pytest.raises(FilingUnavailable):
        await store.issue_filings.get(fault.signature)
    await store.stop()


async def test_claim_failed_fault_persistence_is_not_authority(faults):
    store, _, connection = faults
    connection.fail_sql = "INSERT INTO fault_reports"
    fault = await store.file_fault(tool_id="shell", error_text="new fault", agent_id="agent")
    assert store.get(fault.id) is fault
    connection.fail_sql = ""
    with pytest.raises(FilingUnavailable, match="fault_not_durable"):
        await _claim(store, fault)
    assert await store.issue_filings.get(fault.signature) is None


async def test_claim_failed_commit_never_publishes_a_claim(faults):
    store, fault, connection = faults
    connection.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        await _claim(store, fault)
    assert await store.issue_filings.get(fault.signature) is None


async def test_complete_failed_commit_keeps_attempt_uncertain(faults):
    store, fault, connection = faults
    claim = await _claim(store, fault)
    connection.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id, disposition="filed",
            receipt=IssueReceipt(37, "https://github.com/owner/repo/issues/37"),
        )
    assert (await store.issue_filings.get(fault.signature)).disposition == "attempting"
    await store.stop()
    await store.start()
    assert not (await _claim(store, fault)).acquired


async def test_complete_stale_attempt_cannot_replace_retry(faults):
    store, fault, _ = faults
    first = await _claim(store, fault)
    await store.issue_filings.complete(
        fault.signature, first.filing.attempt_id,
        disposition="retryable_failure", failure_code="pre_send_failure",
    )
    second = await _claim(store, fault)
    assert second.acquired and first.filing.attempt_id != second.filing.attempt_id
    assert await store.issue_filings.complete(
        fault.signature, first.filing.attempt_id, disposition="filed",
        receipt=IssueReceipt(37, "https://github.com/owner/repo/issues/37"),
    ) is None
    assert await store.issue_filings.get(fault.signature) == second.filing


async def test_complete_cannot_downgrade_uncertainty_to_resend_permission(faults):
    store, fault, _ = faults
    claim = await _claim(store, fault)
    await store.issue_filings.complete(
        fault.signature, claim.filing.attempt_id, disposition="outcome_unknown",
        failure_code="remote_uncertain",
    )
    with pytest.raises(ValueError, match="uncertain_attempt"):
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id, disposition="retryable_failure",
            failure_code="pre_send_failure",
        )
    assert not (await _claim(store, fault)).acquired


@pytest.mark.parametrize("receipt", [
    IssueReceipt(True, "https://github.com/owner/repo/issues/True"),
    IssueReceipt(0, "https://github.com/owner/repo/issues/0"),
    IssueReceipt(37, "https://github.com/other/repo/issues/37"),
    IssueReceipt(37, "https://github.com/owner/repo/issues/37?secret=private"),
])
async def test_complete_invalid_receipt_is_refused(faults, receipt):
    store, fault, _ = faults
    claim = await _claim(store, fault)
    with pytest.raises(ValueError, match="invalid_issue_receipt"):
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id, disposition="filed", receipt=receipt,
        )
    assert await store.issue_filings.get(fault.signature) == claim.filing


async def test_complete_missing_or_invalid_outcome_is_not_a_receipt(faults):
    store, fault, _ = faults
    assert await store.issue_filings.get("") is None
    assert await store.issue_filings.complete(
        "", "", disposition="outcome_unknown", failure_code="remote_uncertain",
    ) is None
    with pytest.raises(ValueError, match="invalid_filing_outcome"):
        await store.issue_filings.complete(
            fault.signature, "", disposition="filed", failure_code="raw secret",
        )
    with pytest.raises(ValueError, match="invalid_filing_identity"):
        await _claim(store, fault, request_id="")


@pytest.mark.parametrize("disposition", ["attempting", "outcome_unknown", "filed"])
async def test_decline_never_erases_active_or_completed_attempt(faults, disposition):
    store, fault, _ = faults
    claim = await _claim(store, fault)
    if disposition != "attempting":
        await store.issue_filings.complete(
            fault.signature, claim.filing.attempt_id, disposition=disposition,
            receipt=IssueReceipt(37, "https://github.com/owner/repo/issues/37")
            if disposition == "filed" else None,
        )
    previous = await store.issue_filings.get(fault.signature)
    assert await store.issue_filings.decline(**_identity(fault, request_id="denied")) == previous


async def test_decline_unattempted_and_new_approval_can_claim(faults):
    store, fault, _ = faults
    declined = await store.issue_filings.decline(**_identity(fault))
    assert declined.disposition == "declined" and declined.issue_url == ""
    assert (await _claim(store, fault, request_id="new-approval")).acquired


@pytest.mark.parametrize("operation", ["insert", "occurrence", "resolution"])
async def test_legacy_writes_cannot_commit_another_claims_transaction(faults, operation):
    store, fault, connection = faults
    connection.pause_commit = True
    claim_task = asyncio.create_task(_claim(store, fault))
    await asyncio.wait_for(connection.entered.wait(), 2)
    if operation == "resolution":
        operation_coro = store.resolve(fault.id, status="diagnosing")
    else:
        operation_coro = store.file_fault(
            tool_id="browser" if operation == "occurrence" else "shell",
            error_text=fault.error_text, agent_id="agent", thread_id="thread",
        )
    write_task = asyncio.create_task(operation_coro)
    try:
        await asyncio.sleep(0)
        assert not write_task.done(), "the legacy write must wait for the whole claim transaction"
        connection.fail_commit = True
        connection.release.set()
        with pytest.raises(RuntimeError, match="commit failure"):
            await claim_task
        await write_task
        assert await store.issue_filings.get(fault.signature) is None
        with sqlite3.connect(store.db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM fault_reports").fetchone()[0] == (
                2 if operation == "insert" else 1
            )
    finally:
        connection.release.set()
        await asyncio.gather(claim_task, write_task, return_exceptions=True)


async def test_cancelled_claim_rolls_back_and_releases_shared_lock(faults):
    store, fault, connection = faults
    connection.pause_commit = True
    task = asyncio.create_task(_claim(store, fault))
    try:
        await asyncio.wait_for(connection.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await store.issue_filings.get(fault.signature) is None
        assert (await _claim(store, fault)).acquired
    finally:
        connection.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("fail_close", [False, True])
async def test_failed_start_unbinds_even_when_close_fails(tmp_path, fail_close):
    factory = _Factory(fail_schema=True, fail_close=fail_close)
    store = FaultReportStore(str(tmp_path / "failed.db"), connection_factory=factory)
    with pytest.raises(RuntimeError, match="schema failure"):
        await store.start()
    assert factory.connection.closed
    with pytest.raises(FilingUnavailable):
        await store.issue_filings.get("a" * 64)
    await store.stop()


async def test_stop_unbinds_before_failing_close(faults):
    store, fault, connection = faults
    connection.fail_close = True
    with pytest.raises(RuntimeError, match="close failure"):
        await store.stop()
    assert connection.closed
    with pytest.raises(FilingUnavailable):
        await _claim(store, fault)


async def test_cancelled_start_closes_and_leaves_unbound(tmp_path):
    factory = _Factory(pause_commit=True)
    store = FaultReportStore(str(tmp_path / "cancelled.db"), connection_factory=factory)
    task = asyncio.create_task(store.start())
    try:
        while factory.connection is None:
            await asyncio.sleep(0)
        await asyncio.wait_for(factory.connection.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert factory.connection.closed
        with pytest.raises(FilingUnavailable):
            await store.issue_filings.get("a" * 64)
    finally:
        factory.connection.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await store.stop()


async def test_legacy_database_gains_empty_companion_without_fault_schema_change(faults):
    store, fault, _ = faults
    original = fault.to_dict()
    await store.stop()
    with sqlite3.connect(store.db_path) as db:
        db.execute("DROP TABLE fault_issue_filings")
    await store.start()
    assert store.get(fault.id).to_dict() == original
    with sqlite3.connect(store.db_path) as db:
        assert len(db.execute("PRAGMA table_info(fault_reports)").fetchall()) == 16
        assert db.execute("SELECT COUNT(*) FROM fault_issue_filings").fetchone() == (0,)


async def test_registered_filing_store_metadata_matches_real_journal_lifecycle(
    tmp_path: Path,
) -> None:
    registry = load_default_store_registry()
    declaration = registry.get("fault.issue-filings")
    assert declaration is not None
    assert declaration.to_dict() == {
        "id": "fault.issue-filings",
        "title": "Fault issue-filing duplicate-suppression journal",
        "owner_module": "probos.fault_issue_filings",
        "owner_symbol": "FaultIssueFilings",
        "canonical_path": "fault_reports.db",
        "criticality": "required",
        "lifecycle_owner": "probos.fault_report.FaultReportStore",
        "retention": "unbounded",
        "retention_note": (
            "Retain signature rows indefinitely for durable duplicate "
            "suppression across restarts."
        ),
        "backup": "included",
        "restore": "unknown",
        "reconstruction": "",
        "notes": (
            "Companion table co-located with fault_reports in fault_reports.db, "
            "sharing FaultReportStore's connection and persistence lock. "
            "FaultReportStore start/stop own lifecycle; no independent companion "
            "lifecycle. Retention describes journal only. Backup inclusion is "
            "conditional on enabled snapshots; restore behavior is unverified."
        ),
    }
    assert declaration_errors(declaration) == ()
    assert registry.by_canonical_path("fault_reports.db") is declaration

    db_path = tmp_path / declaration.canonical_path
    assert db_path.resolve().is_relative_to(tmp_path.resolve())
    store = FaultReportStore(str(db_path))
    await store.start()
    try:
        with sqlite3.connect(db_path) as db:
            assert {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            } == {"fault_reports", "fault_issue_filings"}
            assert db.execute("SELECT COUNT(*) FROM fault_issue_filings").fetchone() == (0,)
        assert await store.issue_filings.get("a" * 64) is None
    finally:
        await store.stop()
    with pytest.raises(FilingUnavailable, match="fault_store_unavailable"):
        await store.issue_filings.get("a" * 64)
