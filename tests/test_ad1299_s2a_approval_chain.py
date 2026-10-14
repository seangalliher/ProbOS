"""AD-1299 S2a (#1352), M2: the candidate-approval chain on the real approval store and the real decide route.

File -> committed row -> the Captain's decision through ``decide_capability_request`` -> restart ->
``authorize_candidate_execution``. The only double is the runtime the route reads. Each test asserts its own
premise first (an unmodified approval authorizes, or the row exists), so a setup that never reached the
boundary fails loudly instead of passing.

Not shown here: that the store prevents a rewritten row (it cannot: a writer with ProbOS's own OS identity can
edit the database, D-B2; test 6 shows only that the check judges the row it reads), that candidate code is
contained, or that anything under ``src/`` consumes the module (test 7 pins that nothing does yet).
"""

from __future__ import annotations

import ast
import contextlib
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.cognitive.repair_approval import (
    CandidateApprovalCheck,
    authorize_candidate_execution,
    file_candidate_approval,
)
from probos.cognitive.repair_candidate import AuthorityClass, RepairCandidate
from probos.delegated_approvals import RequestClass, classify_capability_request
from probos.routers.capability_requests import decide_capability_request

AGENT = "agent-1"
CAMPAIGN = "campaign-1"

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
SRC_PROBOS = SRC_ROOT / "probos"
APPROVAL_MODULE = SRC_PROBOS / "cognitive" / "repair_approval.py"
APPROVAL_DOTTED = "probos.cognitive.repair_approval"


# ---------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------


def _candidate(tree_char: str) -> RepairCandidate:
    tree = tree_char * 40
    return RepairCandidate("a" * 40, "b" * 40, tree, tree)


class _FakeRuntime:
    """The four attributes the decide route reads from the runtime."""

    def __init__(
        self, *, store: CapabilityRequestStore, approvals: Any = None, config: Any = None,
        work_item_store: Any = None,
    ) -> None:
        self.capability_request_store = store
        self.action_approval_store = approvals
        self.config = config
        self.work_item_store = work_item_store


class _TrippedApprovalStore:
    """A standing-rule store that fails the test on any use, and records the use in case the route swallows the error."""

    def __init__(self) -> None:
        self.touched: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.touched.append(name)
        raise AssertionError(f"action_approval_store.{name} was used while deciding a candidate approval")


@contextlib.asynccontextmanager
async def _open_store(db_path: Path) -> AsyncIterator[CapabilityRequestStore]:
    """A started real store on ``db_path``. Leaving the block stops it, so entering again on the same path is a restart."""
    store = CapabilityRequestStore(db_path=str(db_path))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _file(store: CapabilityRequestStore, candidate: RepairCandidate) -> CapabilityRequest:
    return await file_candidate_approval(
        store, candidate, authority_class="repair", campaign_id=CAMPAIGN, agent_id=AGENT,
    )


async def _authorize(
    store: CapabilityRequestStore,
    request_id: str,
    candidate: RepairCandidate,
    *,
    authority_class: AuthorityClass = "repair",
    campaign_id: str = CAMPAIGN,
    now: float | None = None,
) -> CandidateApprovalCheck:
    """``authorize_candidate_execution`` at the frozen clock ``now``; at the module's own clock when ``now`` is None."""
    if now is None:
        return await authorize_candidate_execution(
            store, candidate, request_id=request_id, authority_class=authority_class, campaign_id=campaign_id,
        )
    return await authorize_candidate_execution(
        store, candidate, request_id=request_id, authority_class=authority_class, campaign_id=campaign_id,
        clock=lambda: now,
    )


def _rewrite_row(db_path: Path, statement: str, parameters: tuple[object, ...]) -> None:
    """Change one committed row behind the store's back, as a writer holding the database file could."""
    connection = sqlite3.connect(str(db_path))
    try:
        rewritten = connection.execute(statement, parameters).rowcount
        connection.commit()
    finally:
        connection.close()
    assert rewritten == 1  # premise: the rewrite reached exactly one row


# ---------------------------------------------------------------------------
# 1. The whole chain, across a restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_approval_crosses_store_route_and_restart(tmp_path: Path) -> None:
    """File -> the route's Captain decision -> restart -> authorized for exactly this candidate, class, campaign and window.

    The route grants no standing rule and never uses the standing-rule store. This does NOT isolate the ``repair``
    tool-id exclusion from the other gates: with no ``work_item_id``, AD-1321's work-item gate would withhold
    the rule as well, so ``standing_rule is None`` holds either way. What is pinned is the outcome.
    """
    db_path = tmp_path / "capability_requests.db"
    candidate = _candidate("c")
    approvals = _TrippedApprovalStore()
    config = SimpleNamespace(
        approval_inbox=SimpleNamespace(
            standing_rules_enabled=True,
            standing_rule_max_ttl_hours=168,
            standing_rule_default_ttl_hours=24,
        ),
    )

    async with _open_store(db_path) as store:
        filed = await _file(store, candidate)
        row = await store.get(filed.id, durable=True)
        assert row is not None  # premise: the filing reached the committed row
        assert (row.kind, row.status) == ("action", "pending")
        pending = await _authorize(store, filed.id, candidate)
        assert pending.reason == "approval_pending"
        assert pending.authorized is False

        response = await decide_capability_request(
            filed.id,
            CapabilityRequestDecideRequest(
                approve=True, reason="run exactly this candidate", grant_standing=True, standing_ttl_hours=1,
            ),
            runtime=_FakeRuntime(store=store, approvals=approvals, config=config),
        )
        assert response["request"]["status"] == "approved"
        assert response["request"]["decided_by"] == "captain"
        assert response["standing_rule"] is None
        assert response["fulfilled"] is False
        assert approvals.touched == []

    async with _open_store(db_path) as restarted:
        approved = await restarted.get(filed.id, durable=True)
        assert approved is not None  # premise: the decision is on the committed row after the restart
        assert (approved.status, approved.decided_by) == ("approved", "captain")
        decided_at = approved.decided_at
        assert isinstance(decided_at, float)

        inside = await _authorize(restarted, filed.id, candidate, now=decided_at + 60)
        assert inside.reason == "approval_authorized"
        assert inside.authorized is True
        assert inside.request_id == filed.id
        assert inside.candidate_digest == candidate.digest()
        assert inside.expires_at == decided_at + 86_400

        # each refusal below changes one thing from the authorized call above (the clock, or the candidate,
        # the campaign or the class asked about) and keeps every other input, so the premise above applies
        last_second = await _authorize(restarted, filed.id, candidate, now=decided_at + 86_399)
        assert last_second.reason == "approval_authorized"
        expired = await _authorize(restarted, filed.id, candidate, now=decided_at + 86_400)
        assert expired.reason == "approval_expired"
        assert expired.authorized is False
        other_candidate = await _authorize(restarted, filed.id, _candidate("d"), now=decided_at + 60)
        assert other_candidate.reason == "approval_candidate_mismatch"
        other_campaign = await _authorize(restarted, filed.id, candidate, campaign_id="campaign-2", now=decided_at + 60)
        assert other_campaign.reason == "approval_campaign_mismatch"
        other_class = await _authorize(restarted, filed.id, candidate, authority_class="maintenance", now=decided_at + 60)
        assert other_class.reason == "approval_class_mismatch"


# ---------------------------------------------------------------------------
# 2. A denial survives a restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denial_through_the_route_reads_denied_after_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "capability_requests.db"
    candidate = _candidate("c")

    async with _open_store(db_path) as store:
        filed = await _file(store, candidate)
        response = await decide_capability_request(
            filed.id,
            CapabilityRequestDecideRequest(approve=False, reason="this diff is not the repair"),
            runtime=_FakeRuntime(store=store),
        )
        assert response["request"]["status"] == "denied"  # premise: the route recorded a denial

    async with _open_store(db_path) as restarted:
        row = await restarted.get(filed.id, durable=True)
        assert row is not None  # premise: the denial is on the committed row, not only in the first store's cache
        assert (row.status, row.decided_by, row.decision_reason) == ("denied", "captain", "this diff is not the repair")
        assert isinstance(row.decided_at, float)

        check = await _authorize(restarted, filed.id, candidate, now=row.decided_at + 60)
        assert check.reason == "approval_denied"
        assert check.authorized is False
        assert check.expires_at is None


# ---------------------------------------------------------------------------
# 3. Re-filing a pending candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refiling_the_same_pending_candidate_dedups(tmp_path: Path) -> None:
    async with _open_store(tmp_path / "capability_requests.db") as store:
        first = await _file(store, _candidate("c"))
        assert first.status == "pending"  # premise: the first filing is a pending ask
        assert [request.id for request in await store.list_pending()] == [first.id]

        second = await _file(store, _candidate("c"))
        assert second.id == first.id
        assert [request.id for request in await store.list_pending()] == [first.id]

        # control: the dedup is per candidate, not per agent, so a different candidate is a second ask
        other = await _file(store, _candidate("d"))
        assert other.id != first.id
        assert {request.id for request in await store.list_pending()} == {first.id, other.id}


# ---------------------------------------------------------------------------
# 4. Only the Captain decides it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_approval_is_captain_reserved(tmp_path: Path) -> None:
    async with _open_store(tmp_path / "capability_requests.db") as store:
        filed = await _file(store, _candidate("c"))
        stored = await store.get(filed.id, durable=True)
        assert stored is not None  # premise: the filing reached the committed row
        assert filed.payload is not None
        assert (filed.kind, filed.payload["tool_id"], filed.payload["action"]) == ("action", "repair", "approve_candidate")

        assert classify_capability_request(filed, tool_registry=None) is RequestClass.CAPTAIN_RESERVED
        assert classify_capability_request(stored, tool_registry=None) is RequestClass.CAPTAIN_RESERVED


# ---------------------------------------------------------------------------
# 5. A store with no database cannot authorize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_only_store_never_authorizes() -> None:
    candidate = _candidate("c")
    store = CapabilityRequestStore(db_path="")
    try:
        await store.start()
        filed = await _file(store, candidate)
        decided = await store.decide(filed.id, True, decided_by="captain")
        cached = await store.get(filed.id)
        assert decided is not None and cached is not None  # premise: the request exists and is decided
        assert (cached.status, cached.decided_by) == ("approved", "captain")
        assert isinstance(cached.decided_at, float)

        check = await _authorize(store, filed.id, candidate, now=cached.decided_at + 60)
        assert check.reason == "approval_not_found"
        assert check.authorized is False
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# 6. A row rewritten behind the store is judged by what it now says
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewritten_row_is_judged_by_its_new_content(tmp_path: Path) -> None:
    """Detection by re-reading, not prevention: whoever can write the database file can still write the row."""
    db_path = tmp_path / "capability_requests.db"
    first_candidate, second_candidate = _candidate("c"), _candidate("d")

    async with _open_store(db_path) as store:
        runtime = _FakeRuntime(store=store)
        first = await _file(store, first_candidate)
        second = await _file(store, second_candidate)
        assert first.id != second.id  # premise: two requests, so each rewrite below has its own row
        for request in (first, second):
            await decide_capability_request(
                request.id, CapabilityRequestDecideRequest(approve=True, reason="run it"), runtime=runtime,
            )
        first_row = await store.get(first.id, durable=True)
        second_row = await store.get(second.id, durable=True)
        assert first_row is not None and second_row is not None
        assert isinstance(first_row.decided_at, float) and isinstance(second_row.decided_at, float)
        first_now = first_row.decided_at + 60
        second_now = second_row.decided_at + 60
        # premise: both approvals, unmodified, authorize at the clocks the rewritten rows are judged at
        assert (await _authorize(store, first.id, first_candidate, now=first_now)).reason == "approval_authorized"
        assert (await _authorize(store, second.id, second_candidate, now=second_now)).reason == "approval_authorized"

    future = first_now + 3_600.0  # one hour ahead of the clock the first row is judged at
    _rewrite_row(db_path, "UPDATE capability_requests SET decided_at = ? WHERE id = ?", (future, first.id))
    _rewrite_row(db_path, "UPDATE capability_requests SET decided_by = ? WHERE id = ?", ("first_officer", second.id))

    async with _open_store(db_path) as restarted:
        future_row = await restarted.get(first.id, durable=True)
        assert future_row is not None  # premise: the restarted store reads the rewrite, and only the rewrite
        assert (future_row.status, future_row.decided_by, future_row.decided_at) == ("approved", "captain", future)
        future_check = await _authorize(restarted, first.id, first_candidate, now=first_now)
        assert future_check.reason == "approval_decision_time_invalid"
        assert future_check.authorized is False

        officer_row = await restarted.get(second.id, durable=True)
        assert officer_row is not None
        assert (officer_row.status, officer_row.decided_by, officer_row.decided_at) == (
            "approved", "first_officer", second_row.decided_at,
        )
        officer_check = await _authorize(restarted, second.id, second_candidate, now=second_now)
        assert officer_check.reason == "approval_not_captain"
        assert officer_check.authorized is False


# ---------------------------------------------------------------------------
# 7. Nothing in src/ imports the module yet (pins D5)
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST, package: str) -> set[str]:
    """Every dotted module ``tree`` may import, a relative import resolved against ``package``.

    ``from pkg import name`` may import the submodule ``pkg.name``, so both spellings are reported.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _importers_of(module: str, *, exclude: Path | None = None) -> list[str]:
    """The files under ``src/probos`` (posix paths relative to it) that import ``module``, ``exclude`` aside."""
    needle = module.rsplit(".", 1)[-1].encode()
    found: list[str] = []
    for path in sorted(SRC_PROBOS.rglob("*.py")):
        if path == exclude:
            continue
        raw = path.read_bytes()
        if needle not in raw:
            continue  # every static import form spells the module's last name; a file without it cannot import it
        package = ".".join(path.parent.relative_to(SRC_ROOT).parts)
        if module in _imported_modules(ast.parse(raw, filename=str(path)), package):
            found.append(path.relative_to(SRC_PROBOS).as_posix())
    return found


def test_nothing_in_src_imports_the_module() -> None:
    """Pins D5: the module is runtime-unwired, so nothing under ``src/`` imports it.

    AD-1299 S2e (campaign admission) wires it and changes this test deliberately. The scan is AST-based: a
    docstring or comment that names the module is not an import. It does not see a dynamic import such as
    ``importlib.import_module("probos.cognitive.repair_approval")``.
    """
    assert APPROVAL_MODULE.is_file()  # premise: the module the scan excludes is where the exclusion expects it

    # the scanner is not vacuous: it reports each import shape it exists to forbid, and neither a sibling nor a string
    for source, package in (
        ("import probos.cognitive.repair_approval", "probos.runtime"),
        ("import probos.cognitive.repair_approval as approval", "probos.runtime"),
        ("from probos.cognitive.repair_approval import authorize_candidate_execution", "probos.runtime"),
        ("from probos.cognitive import repair_approval", "probos.runtime"),
        ("from .repair_approval import authorize_candidate_execution", "probos.cognitive"),
        ("from . import repair_approval", "probos.cognitive"),
        ("from ..cognitive import repair_approval", "probos.routers"),
        ("def late():\n    from probos.cognitive.repair_approval import file_candidate_approval", "probos.runtime"),
    ):
        assert APPROVAL_DOTTED in _imported_modules(ast.parse(source), package), source
    for source in (
        "from probos.cognitive.repair_candidate import RepairCandidate",
        "from probos.cognitive import repair_candidate",
        "from probos.cognitive.repair_approval_notes import note",
        "MODULE = 'probos.cognitive.repair_approval'",
    ):
        assert APPROVAL_DOTTED not in _imported_modules(ast.parse(source), "probos.runtime"), source

    # positive control: the same scan, over the same tree, finds the one import of the sibling S1a module it should
    assert "cognitive/repair_evidence_store.py" in _importers_of("probos.cognitive.repair_candidate")

    assert _importers_of(APPROVAL_DOTTED, exclude=APPROVAL_MODULE) == []
