"""AD-1279 / BF-855: a fault that can find its own trace.

AD-1269 made the fault row's signature the identity computed ONCE at detection,
over the untruncated error. The trace it points at is bounded before it is
written. When the two disagree, ``find_failing_arguments`` returns ``None`` and
the fault -- filed correctly, coalesced correctly, keyed correctly -- can never
enter the repair path.

**The precondition the issue does not state.** ``normalise_error`` collapses hex
runs, then digit runs, and only THEN truncates to ``_ERROR_MAX``. Head+tail
truncation preserves the head. So when the collapsed head is already at least
``_ERROR_MAX`` characters, the first ``_ERROR_MAX`` collapsed characters are
identical either way and the two signatures AGREE. The defect fires only when
the collapsed head is SHORTER than that bound.

A first probe built its long error from a repeating pattern, got a
collapse-resistant head, and wrongly refuted the issue. The three cases below
are single-dimension for that reason: DENSE differs from COLLAPSING only in
where the long run sits, CONTROL differs only in length. Measured on the real
writer and the real reader against unfixed HEAD:

    case         raw    persisted  collapsed head  recovered
    CONTROL       34           34              34  yes
    DENSE      25800         8192            2000  yes
    COLLAPSING 11671         8191               4  NO
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    _tool_id_resolver,
)
from probos.cognitive.repair_verification import find_failing_arguments
from probos.cognitive.swe_harness.agentic_loop import (
    _durable_head_tail,
    build_tool_trace_payload,
)
from probos.cognitive.swe_harness.tool_call import (
    ToolCallRequest,
    ToolCallResult,
    llm_function_name,
)
from probos.fault_report import (
    _ERROR_MAX,
    FaultReportStore,
    ToolDefect,
    error_signature,
    normalise_error,
)

TRACE_CAP = 8192
TOOL = "run_python"
ARGS = {"path": "/srv/pkg/manifest.lock", "mode": "resolve"}

# ── the three cases ───────────────────────────────────────────────

CONTROL_ERROR = "unknown browser action: 'key_type'"

# Wordy head: nothing for the collapse rules to bite on, so the collapsed head
# stays at the _ERROR_MAX ceiling and the two signatures agree even unfixed.
DENSE_ERROR = (
    "Traceback (most recent call last): the package resolver could not settle "
    "a consistent version set for the requested environment; "
) * 200

# The same length class, but the run is in the HEAD. 5,400 digits is longer
# than _durable_head_tail's head slice, so the whole retained head collapses to
# a single token and the elision marker lands inside the first _ERROR_MAX
# collapsed characters -- which is what makes the digests differ.
COLLAPSING_ERROR = (
    "9" * 5400
    + " ERROR: the package resolver could not settle a consistent version set "
    + "for the requested environment. " * 200
)


def _call(name: str = TOOL, call_id: str = "c1", args: dict | None = None):
    return ToolCallRequest(
        name=name, arguments=ARGS if args is None else args,
        id=call_id, timestamp=0.0,
    )


def _trace(error_text: Any, *, name: str = TOOL, resolver=None,
           output_max_chars: int = TRACE_CAP) -> list[dict]:
    entries, _ = build_tool_trace_payload(
        [_call(name)],
        [ToolCallResult(id="c1", output=error_text, is_error=True)],
        output_max_chars=output_max_chars,
        blob_max_bytes=0,
        resolve_tool_id=resolver,
    )
    return entries


def _defect(error_text: Any, *, tool_id: str = TOOL) -> ToolDefect:
    return ToolDefect(tool_id=tool_id, error_text=error_text, count=2)


def _collapsed_head_len(error_text: str) -> int:
    head_chars, _tail = _durable_head_tail(TRACE_CAP, len(error_text))
    return len(normalise_error(error_text[:head_chars]))


# ── 6.1 the three-case matrix ─────────────────────────────────────


def test_control_a_short_error_recovers_its_arguments() -> None:
    """The row that makes the other two mean anything.

    Without it, a failing recovery is indistinguishable from a broken harness.
    """
    entries = _trace(CONTROL_ERROR)
    defect = _defect(CONTROL_ERROR)

    assert entries[0]["output"] == CONTROL_ERROR, "premise: nothing truncated"
    assert find_failing_arguments(
        entries, tool_id=TOOL, signature=defect.signature,
    ) == ARGS


def test_a_long_error_with_a_collapse_resistant_head_still_recovers() -> None:
    """DENSE pins the BOUNDARY, and it is a fixture in its own right.

    Length alone is not the trigger. This error is three times the trace bound
    and recovers anyway, because its head has no digit or hex run to collapse,
    so the first _ERROR_MAX collapsed characters are the same on both sides.
    A regression test built like this passes against the UNFIXED code and pins
    nothing -- and a future change to _ERROR_MAX or the head/tail split cannot
    silently widen or close the defect without moving this assertion.
    """
    entries = _trace(DENSE_ERROR)
    defect = _defect(DENSE_ERROR)

    assert len(DENSE_ERROR) > TRACE_CAP, "premise: over the trace bound"
    assert len(entries[0]["output"]) < len(DENSE_ERROR), "premise: truncated"
    assert _collapsed_head_len(DENSE_ERROR) >= _ERROR_MAX, (
        "premise: the head resists collapse, which is why the digests agree"
    )
    # The mechanism, not just the outcome: recomputation from the persisted
    # output happens to land on the right answer here.
    assert error_signature(
        tool_id=TOOL, error_text=entries[0]["output"],
    ) == defect.signature

    assert find_failing_arguments(
        entries, tool_id=TOOL, signature=defect.signature,
    ) == ARGS


def test_a_long_error_whose_head_collapses_recovers_its_arguments() -> None:
    """BF-855, the defect. Measured returning None against unfixed HEAD.

    The assertions on the persisted output are deliberate: without them a
    future change that stopped truncating would make this pass for the wrong
    reason and the regression would be unguarded.
    """
    entries = _trace(COLLAPSING_ERROR)
    defect = _defect(COLLAPSING_ERROR)
    persisted = entries[0]["output"]

    assert len(persisted) < len(COLLAPSING_ERROR), "premise: truncated"
    assert _collapsed_head_len(COLLAPSING_ERROR) < _ERROR_MAX, (
        "premise: the retained head collapses below the signature bound"
    )
    assert error_signature(
        tool_id=TOOL, error_text=persisted,
    ) != defect.signature, (
        "premise: recomputing from the bounded output derives a DIFFERENT "
        "identity -- this is the asymmetry BF-855 reports"
    )

    assert find_failing_arguments(
        entries, tool_id=TOOL, signature=defect.signature,
    ) == ARGS


def test_the_carried_identity_is_the_detectors_not_the_traces() -> None:
    """The written digest signs the raw output, never the persisted one."""
    entries = _trace(COLLAPSING_ERROR)

    assert entries[0]["error_signature"] == _defect(COLLAPSING_ERROR).signature
    assert entries[0]["error_signature"] != error_signature(
        tool_id=TOOL, error_text=entries[0]["output"],
    )


# ── 6.2 #2 / #3 the legacy path ───────────────────────────────────


def test_a_trace_with_no_carried_identity_still_recovers_by_recomputation() -> None:
    """D2: recomputation is retained, not replaced. Nothing to migrate."""
    legacy = [
        {"name": TOOL, "arguments": ARGS, "output": CONTROL_ERROR,
         "is_error": True},
    ]
    assert "error_signature" not in legacy[0]

    assert find_failing_arguments(
        legacy, tool_id=TOOL, signature=_defect(CONTROL_ERROR).signature,
    ) == ARGS


def test_a_mismatched_carried_identity_falls_back_to_recomputation() -> None:
    """D2: the field is a shortcut, not an authority.

    A writer and a detector handed different resolvers would otherwise make it
    authoritative AND wrong. Recomputation cannot produce a false positive
    against a specific target except by collision, so keeping it is strictly
    more permissive.
    """
    entry = {
        "name": TOOL, "arguments": ARGS, "output": CONTROL_ERROR,
        "is_error": True, "error_signature": "f" * 64,
    }

    assert find_failing_arguments(
        [entry], tool_id=TOOL, signature=_defect(CONTROL_ERROR).signature,
    ) == ARGS


def test_a_non_string_carried_identity_is_ignored_not_trusted() -> None:
    """A malformed value must not short-circuit the comparison."""
    entry = {
        "name": TOOL, "arguments": ARGS, "output": CONTROL_ERROR,
        "is_error": True, "error_signature": None,
    }

    assert find_failing_arguments(
        [entry], tool_id=TOOL, signature=_defect(CONTROL_ERROR).signature,
    ) == ARGS


# ── 6.2 #4 / #5 / #6 the non-error blob is untouched ──────────────


def test_a_success_entry_carries_no_identity() -> None:
    """Error-only, so every non-error blob stays byte-identical."""
    entries, _ = build_tool_trace_payload(
        [_call()],
        [ToolCallResult(id="c1", output="all good", is_error=False)],
        output_max_chars=TRACE_CAP, blob_max_bytes=0,
        resolve_tool_id=lambda name: "mcp:docs:search",
    )

    assert entries[0]["is_error"] is False
    assert "error_signature" not in entries[0]


def test_an_all_success_blob_is_byte_identical_with_and_without_a_resolver() -> None:
    calls = [_call(call_id=f"c{i}") for i in range(4)]
    results = [
        ToolCallResult(id=f"c{i}", output=f"result {i}", is_error=False)
        for i in range(4)
    ]

    _, without = build_tool_trace_payload(
        calls, results, output_max_chars=TRACE_CAP, blob_max_bytes=0,
    )
    _, with_resolver = build_tool_trace_payload(
        calls, results, output_max_chars=TRACE_CAP, blob_max_bytes=0,
        resolve_tool_id=lambda name: "something:else",
    )

    assert without == with_resolver
    assert b"error_signature" not in without


def test_output_max_chars_zero_still_yields_the_pre_ad1151_blob() -> None:
    """No result is joined, so no identity is written either."""
    entries, blob = build_tool_trace_payload(
        [_call()],
        [ToolCallResult(id="c1", output=COLLAPSING_ERROR, is_error=True)],
        output_max_chars=0, blob_max_bytes=0,
        resolve_tool_id=lambda name: "mcp:docs:search",
    )

    assert set(entries[0]) == {"name", "arguments", "id", "timestamp"}
    assert b"error_signature" not in blob


# ── 6.2 #7 / #8 / #9 the resolver contract ────────────────────────


def test_no_resolver_signs_against_the_observed_name() -> None:
    """Exactly what the detector does when there is no registry to ask."""
    entries = _trace(CONTROL_ERROR, resolver=None)

    assert entries[0]["error_signature"] == error_signature(
        tool_id=TOOL, error_text=CONTROL_ERROR,
    )
    assert find_failing_arguments(
        entries, tool_id=TOOL, signature=_defect(CONTROL_ERROR).signature,
    ) == ARGS


def test_a_raising_resolver_still_produces_a_full_trace() -> None:
    """``canonical_tool_id`` degrades to the observed name for every failure
    mode, so a broken resolver costs the alias mapping and nothing else."""

    def _boom(_name: str) -> str:
        raise RuntimeError("registry unavailable")

    calls = [_call(call_id="c1"), _call(call_id="c2")]
    entries, _ = build_tool_trace_payload(
        calls,
        [
            ToolCallResult(id="c1", output=CONTROL_ERROR, is_error=True),
            ToolCallResult(id="c2", output=CONTROL_ERROR, is_error=True),
        ],
        output_max_chars=TRACE_CAP, blob_max_bytes=0, resolve_tool_id=_boom,
    )

    assert len(entries) == 2, "requests are never dropped"
    for entry in entries:
        assert entry["error_signature"] == error_signature(
            tool_id=TOOL, error_text=CONTROL_ERROR,
        )


def test_a_resolver_answering_with_a_non_string_falls_back_to_the_name() -> None:
    entries = _trace(CONTROL_ERROR, resolver=lambda _n: None)  # type: ignore[arg-type,return-value]

    assert entries[0]["error_signature"] == error_signature(
        tool_id=TOOL, error_text=CONTROL_ERROR,
    )


def test_an_mcp_alias_recovers_from_a_trace_that_records_the_alias() -> None:
    """The AD-1269 seam, now carrying a digest across it.

    The row is keyed on the canonical id; the trace records the name the model
    used. The written identity must be the canonical one or the fault cannot
    match its own trace even when nothing was truncated.
    """
    canonical = "mcp:docs:search"
    alias = llm_function_name(canonical)
    assert alias != canonical, "premise: the provider regex rejects the id"

    entries = _trace(
        COLLAPSING_ERROR, name=alias,
        resolver=lambda observed: canonical if observed == alias else observed,
    )
    defect = ToolDefect(
        tool_id=canonical, error_text=COLLAPSING_ERROR, count=2,
        observed_as=alias,
    )

    assert entries[0]["name"] == alias
    assert find_failing_arguments(
        entries, tool_id=canonical, signature=defect.signature,
        observed_as=alias,
    ) == ARGS


def test_the_entry_gains_no_second_name() -> None:
    """AD-1269's do-not-build #12 stays: a digest is not a name.

    Provenance stays where AD-1269 put it -- ``name`` is what the model used,
    and the fault row owns the canonical id.
    """
    entries = _trace(
        CONTROL_ERROR, name=llm_function_name("mcp:docs:search"),
        resolver=lambda _n: "mcp:docs:search",
    )

    for forbidden in ("tool_id", "canonical_tool_id", "observed_as", "tool"):
        assert forbidden not in entries[0], forbidden


# ── 6.2 #10 the coercion seam ─────────────────────────────────────


def test_a_none_output_signs_the_way_the_detector_signs_it() -> None:
    """COERCION DRIFT, the seam.

    The writer renders a ``None`` output as ``""`` for the persisted value; the
    detector renders it as ``"None"``. Signing the writer's value would make
    the two disagree on exactly the malformed-result case the writer's own
    comment says is reachable.
    """
    entries = _trace(None)

    assert entries[0]["output"] == "", "the persisted value is unchanged"
    assert entries[0]["error_signature"] == error_signature(
        tool_id=TOOL, error_text="None",
    )
    assert entries[0]["error_signature"] != error_signature(
        tool_id=TOOL, error_text="",
    )


def test_a_none_output_recovers_against_the_detectors_own_verdict() -> None:
    """The crossing test for the coercion: detector in, reader out."""

    class _Outcome:
        tool_calls = [_call(call_id="c1"), _call(call_id="c2")]
        tool_results = [
            ToolCallResult(id="c1", output=None, is_error=True),  # type: ignore[arg-type]
            ToolCallResult(id="c2", output=None, is_error=True),  # type: ignore[arg-type]
        ]

    from probos.fault_report import detect_tool_defect

    defect = detect_tool_defect(_Outcome())
    assert defect is not None and defect.count == 2

    entries, _ = build_tool_trace_payload(
        _Outcome.tool_calls, _Outcome.tool_results,
        output_max_chars=TRACE_CAP, blob_max_bytes=0,
    )

    assert find_failing_arguments(
        entries, tool_id=defect.tool_id, signature=defect.signature,
        observed_as=defect.observed_as,
    ) == ARGS


# ── 6.2 #11 the diagnostic branches stay distinguishable ──────────


def test_a_carried_identity_with_no_argument_dict_takes_the_other_branch(
    caplog,
) -> None:
    """The two causes need different repairs, so they stay counted separately.

    An entry that matched by the carried digest and yielded nothing has a
    non-dict ``arguments`` -- saying "none carries the signature" here would
    assert something this branch did not check.
    """
    entry = {
        "name": TOOL, "arguments": "not-a-dict", "output": "bounded",
        "is_error": True,
        "error_signature": _defect(COLLAPSING_ERROR).signature,
    }

    with caplog.at_level("DEBUG", logger="probos.cognitive.repair_verification"):
        assert find_failing_arguments(
            [entry], tool_id=TOOL,
            signature=_defect(COLLAPSING_ERROR).signature,
        ) is None

    assert "none has a recoverable argument dictionary" in caplog.text
    assert "none carries error signature" not in caplog.text


# ── criterion 5 — ONE resolver, both consumers ────────────────────


def test_the_writer_and_the_detector_are_handed_the_same_resolver() -> None:
    """Structural, because the point is that a skew is UNREACHABLE.

    Two ``_tool_id_resolver(registry)`` calls would close over the same
    registry and answer identically today. One object makes "the writer and
    the detector cannot disagree" a property of the code rather than of the
    current implementation of the resolver.
    """
    tree = ast.parse(inspect.getsource(WorkItemAgenticExecutor.run).lstrip())

    built = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_tool_id_resolver"
    ]
    assert len(built) == 1, "the resolver is built exactly once"

    handed: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = None
        if isinstance(node.func, ast.Name) and node.func.id == "detect_tool_defect":
            target = "detector"
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "_persist_tool_trace"
        ):
            target = "writer"
        if target is None:
            continue
        for kw in node.keywords:
            if kw.arg == "resolve_tool_id" and isinstance(kw.value, ast.Name):
                handed[target] = kw.value.id

    assert set(handed) == {"detector", "writer"}, handed
    assert handed["detector"] == handed["writer"], handed


@pytest.mark.asyncio
async def test_the_persisted_trace_carries_the_identity_through_the_dispatcher(
    tmp_path,
) -> None:
    """End to end through the real ``_persist_tool_trace``, real store, real
    reader -- the seam this AD exists to close."""
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.config import AgenticLoopConfig

    class _Result:
        tool_calls = [_call()]
        tool_results = [
            ToolCallResult(id="c1", output=COLLAPSING_ERROR, is_error=True),
        ]

    class _Runtime:
        def __init__(self, store: Any) -> None:
            self.attachment_store = store

            class _Cfg:
                agentic_loop = AgenticLoopConfig(
                    tool_trace_output_max_chars=TRACE_CAP,
                )

            self.config = _Cfg()

    store = FilesystemAttachmentStore(tmp_path)
    executor = WorkItemAgenticExecutor(llm_client=None)

    ref = await executor._persist_tool_trace(
        _Result(), _Runtime(store), "a-1",
        resolve_tool_id=_tool_id_resolver(None),
    )

    assert ref is not None
    entries = json.loads((await store.read(ref)).decode("utf-8"))
    assert find_failing_arguments(
        entries, tool_id=TOOL, signature=_defect(COLLAPSING_ERROR).signature,
    ) == ARGS


# ── §5 FaultReportStore.start() ───────────────────────────────────


class _FakeCursor:
    """Awaitable AND an async context manager, as aiosqlite's cursor is."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def __await__(self):
        async def _noop() -> "_FakeCursor":
            return self

        return _noop().__await__()

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def __aiter__(self):
        for row in self._rows:
            yield row


class _FakeConn:
    """Records ``close()``, and fails at exactly one post-connect step."""

    def __init__(self, *, fail_on: str = "", close_raises: bool = False) -> None:
        self.fail_on = fail_on
        self.close_raises = close_raises
        self.closes = 0

    async def executescript(self, _script: str) -> None:
        if self.fail_on == "schema":
            raise RuntimeError("schema step failed")

    async def commit(self) -> None:
        return None

    def execute(self, sql: str, *_args: Any) -> _FakeCursor:
        if self.fail_on == "cache" and sql.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("no such column: observed_as")
        if "PRAGMA" in sql:
            return _FakeCursor([(0, "observed_as")])
        return _FakeCursor([])

    async def close(self) -> None:
        self.closes += 1
        if self.close_raises:
            raise RuntimeError("close failed")


class _FakeFactory:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def connect(self, _db_path: str) -> _FakeConn:
        return self.conn


@pytest.mark.asyncio
async def test_a_failing_cache_load_closes_the_connection_and_re_raises() -> None:
    """Measured before the guard: pytest HUNG rather than failing.

    The aiosqlite connection was left open and its worker thread never died,
    so a diagnosable error became a stalled run. The bounded wait is why a
    regression here fails instead of hanging.
    """
    conn = _FakeConn(fail_on="cache")
    store = FaultReportStore(db_path="faults.db", connection_factory=_FakeFactory(conn))

    with pytest.raises(RuntimeError, match="no such column"):
        await asyncio.wait_for(store.start(), timeout=10)

    assert conn.closes == 1, "the connection must not be left open"


@pytest.mark.asyncio
async def test_a_failing_schema_step_closes_the_connection_and_re_raises() -> None:
    conn = _FakeConn(fail_on="schema")
    store = FaultReportStore(db_path="faults.db", connection_factory=_FakeFactory(conn))

    with pytest.raises(RuntimeError, match="schema step failed"):
        await asyncio.wait_for(store.start(), timeout=10)

    assert conn.closes == 1


@pytest.mark.asyncio
async def test_a_failing_close_does_not_mask_the_original_cause() -> None:
    """Propagate tier: the caller must learn WHY the store would not open."""
    conn = _FakeConn(fail_on="cache", close_raises=True)
    store = FaultReportStore(db_path="faults.db", connection_factory=_FakeFactory(conn))

    with pytest.raises(RuntimeError, match="no such column"):
        await asyncio.wait_for(store.start(), timeout=10)

    assert conn.closes == 1


@pytest.mark.asyncio
async def test_a_failed_start_leaves_no_connection_behind() -> None:
    """``stop()`` after a failed ``start()`` must not double-close."""
    conn = _FakeConn(fail_on="cache")
    store = FaultReportStore(db_path="faults.db", connection_factory=_FakeFactory(conn))

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(store.start(), timeout=10)
    await store.stop()

    assert conn.closes == 1


@pytest.mark.asyncio
async def test_the_happy_path_still_opens_and_populates_the_cache(tmp_path) -> None:
    """The guard must not change what a working start does."""
    db = str(tmp_path / "faults.db")
    store = FaultReportStore(db_path=db)
    await store.start()
    try:
        await store.file_fault(
            tool_id=TOOL, error_text=CONTROL_ERROR,
            defect=_defect(CONTROL_ERROR),
        )
    finally:
        await store.stop()

    reopened = FaultReportStore(db_path=db)
    await asyncio.wait_for(reopened.start(), timeout=30)
    try:
        assert reopened.get(_defect(CONTROL_ERROR).signature) is not None
    finally:
        await reopened.stop()


# ── review repairs: writer/detector skew across time ──────────────


class TestTheResolverFreezesItsAnswers:
    """AD-1279 review, High: "same helper, same authority" is not "same answer".

    ``registry.list_ids()`` is live, and the trace writer and the fault
    detector are separated by an await. A tool registered or dropped in between
    made one run's identity depend on WHEN each caller asked -- reopening the
    writer/detector skew this AD exists to close. Review reproduced it by
    mutating the registry between the two calls.
    """

    def test_a_registry_that_changes_does_not_change_the_answer(self):
        from probos.cognitive.agentic_dispatch import _tool_id_resolver

        class _Reg:
            def __init__(self):
                self.ids = ["mcp:docs:search"]

            def list_ids(self):
                return list(self.ids)

        reg = _Reg()
        resolve = _tool_id_resolver(reg)
        assert resolve is not None

        first = resolve("mcp_docs_search_38c53abe80026e47")
        assert first == "mcp:docs:search", "probe setup: the alias must resolve"

        # The tool is dropped mid-run -- a server disconnecting, a pool
        # scaling down. A live lookup now finds no claimant and falls back to
        # the observed name, which is a DIFFERENT identity for the same run.
        reg.ids.clear()
        second = resolve("mcp_docs_search_38c53abe80026e47")

        assert second == first, (
            "one resolver object must give one answer per name for its "
            "lifetime, or the carried trace signature and the filed fault "
            "are different identities"
        )

    def test_the_control_a_fresh_resolver_does_see_the_change(self):
        """The discriminator. Without this, the test above would also pass
        against a mutation the resolver never noticed in the first place --
        which is exactly what an earlier draft of it did."""
        from probos.cognitive.agentic_dispatch import _tool_id_resolver

        class _Reg:
            def __init__(self, ids):
                self.ids = ids

            def list_ids(self):
                return list(self.ids)

        present = _tool_id_resolver(_Reg(["mcp:docs:search"]))
        assert present is not None
        assert present("mcp_docs_search_38c53abe80026e47") == "mcp:docs:search"

        # A FRESH resolver over the emptied registry gives the other answer,
        # so the mutation in the test above is genuinely visible.
        absent = _tool_id_resolver(_Reg([]))
        assert absent is not None
        assert absent("mcp_docs_search_38c53abe80026e47") == (
            "mcp_docs_search_38c53abe80026e47"
        )


class TestAMismatchIsNotSilent:
    """AD-1279 review, Medium: the fallback hid the skew perfectly.

    On a carried/recomputed disagreement the reader recovers anyway, which is
    the permissive choice and correct -- but it also means a broken trace
    identity produces a successful repair and says nothing. The repair still
    proceeds; it just no longer proceeds silently.
    """

    def test_a_wrong_carried_signature_is_logged_and_still_recovers(self, caplog):
        import logging

        from probos.cognitive.repair_verification import find_failing_arguments
        from probos.fault_report import error_signature

        tool = "shell"
        err = "boom 0xdeadbeef at offset 12345 failed"
        sig = error_signature(tool_id=tool, error_text=err)

        entries = [{
            "name": tool,
            "is_error": True,
            "output": err,
            "arguments": {"command": "git status"},
            "error_signature": "f" * 64,  # a writer that canonicalised differently
        }]

        with caplog.at_level(logging.WARNING):
            got = find_failing_arguments(entries, tool_id=tool, signature=sig)

        assert got == {"command": "git status"}, (
            "recomputation must still rescue the match -- the fallback is the "
            "permissive path and removing it would lose real repairs"
        )
        assert any("carries error signature" in r.getMessage() for r in caplog.records), (
            "a carried identity that disagreed with the truth must not pass "
            "unremarked; that is the skew this AD set out to remove"
        )

    def test_the_control_an_agreeing_signature_logs_nothing(self, caplog):
        import logging

        from probos.cognitive.repair_verification import find_failing_arguments
        from probos.fault_report import error_signature

        tool = "shell"
        err = "boom 0xdeadbeef at offset 12345 failed"
        sig = error_signature(tool_id=tool, error_text=err)

        entries = [{
            "name": tool,
            "is_error": True,
            "output": err,
            "arguments": {"command": "git status"},
            "error_signature": sig,
        }]

        with caplog.at_level(logging.WARNING):
            got = find_failing_arguments(entries, tool_id=tool, signature=sig)

        assert got == {"command": "git status"}
        assert not any(
            "carries error signature" in r.getMessage() for r in caplog.records
        ), "the happy path must stay quiet, or the warning means nothing"
