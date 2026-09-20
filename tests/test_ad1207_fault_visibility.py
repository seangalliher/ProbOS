"""AD-1207: canonical fault reads, shared privacy policy and Bridge wire evidence."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.openapi.utils import get_openapi

from probos.api import create_app
from probos.cognitive.repair_issue import build_issue_report
from probos.cognitive.trace_analysis import analyse_trace
from probos.config import SystemConfig
from probos.diagnostic_safety import SanitisedTraceReader, TraceReader, sanitise_diagnostic_value
from probos.fault_issue_filings import IssueFiling, IssueReceipt
from probos.fault_report import FaultReport, FaultReportStore


class _FakeCredentials:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, name: str, *, requester: str = "unknown") -> str | None:
        self.calls += 1
        raise AssertionError("Diagnostic GETs must not retrieve credentials")


class _FakeTrace:
    def __init__(self, blob: bytes | str | None = None) -> None:
        self.blob = blob
        self.error = False
        self.calls = 0

    async def read(self, ref: str) -> bytes | str | None:
        self.calls += 1
        if self.error:
            raise RuntimeError("FAKE_TRACE_EXCEPTION_SENTINEL")
        return self.blob


class _FakeFilings:
    def __init__(
        self, filing: IssueFiling | None = None, *, on_read: Callable[[], None] | None = None,
    ) -> None:
        self.filing = filing
        self.on_read = on_read
        self.error = False

    async def get(self, signature: str) -> IssueFiling | None:
        if self.on_read is not None:
            self.on_read()
        if self.error:
            raise RuntimeError("FAKE_JOURNAL_EXCEPTION_SENTINEL")
        await asyncio.sleep(0)
        return self.filing


class _UnreadableStore:
    def __init__(self) -> None:
        self.calls = 0

    def list_open(self) -> list[FaultReport]:
        self.calls += 1
        raise RuntimeError("FAKE_STORE_EXCEPTION_SENTINEL")

    def get(self, signature_or_id: str) -> FaultReport | None:
        self.calls += 1
        raise RuntimeError("FAKE_STORE_EXCEPTION_SENTINEL")


@pytest.fixture
async def fault_visibility_api(tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    store = FaultReportStore(str(tmp_path / "ad1207-faults.db"))
    assert Path(store.db_path).resolve().parent == tmp_path.resolve()
    await store.start()
    filings = store.issue_filings
    credentials, trace = _FakeCredentials(), _FakeTrace()
    runtime = SimpleNamespace(
        config=SystemConfig(), fault_report_store=store, attachment_store=trace,
        credential_store=credentials,
    )
    app = create_app(runtime)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            yield SimpleNamespace(
                app=app, client=client, runtime=runtime, store=store,
                trace=trace, credentials=credentials,
            )
    finally:
        store.issue_filings = filings
        await store.stop()
    assert credentials.calls == 0


async def _fault(rig: SimpleNamespace, **overrides: Any) -> FaultReport:
    return await rig.store.file_fault(**{
        "tool_id": "browser", "error_text": "Opening the page failed: unknown action",
        "agent_id": "recorded-agent", "thread_id": "thread",
        "attempted": "Open the requested page", "tool_trace_ref": "test-trace",
        **overrides,
    })


async def test_list_faults_pages_records_not_occurrences_and_retains_int64(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    first = await _fault(rig)
    second = await _fault(rig, tool_id="shell")
    closed = await _fault(rig, tool_id="closed-tool")
    first.last_seen_at, second.last_seen_at = 10, 20
    first.occurrences = 2**63 - 1
    await rig.store.resolve(second.id, status="diagnosing")
    await rig.store.resolve(closed.id, status="dismissed")
    response = await rig.client.get("/api/faults?limit=1&offset=0")
    assert response.json()["total"] == 2
    assert response.json()["faults"][0]["id"] == second.id
    assert response.json()["faults"][0]["status"] == "diagnosing"
    last = (await rig.client.get("/api/faults?limit=1&offset=1")).json()
    assert last["faults"][0]["occurrences"] == "9223372036854775807"
    assert last["faults"][0]["id"] == first.id
    assert (await rig.client.get("/api/faults?offset=999")).json() == {
        "faults": [], "total": 2, "limit": 50, "offset": 999,
    }
    assert rig.trace.calls == 0, "list reads must not fetch attachments"


async def test_list_faults_detaches_all_rows_before_any_enrichment_await(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    first = await _fault(rig)
    second = await _fault(rig, tool_id="shell")
    first.last_seen_at, second.last_seen_at = 10, 20

    def change_live_rows() -> None:
        first.occurrences = 300
        first.error_text = "new live value"
        second.status = "dismissed"

    rig.store.issue_filings = _FakeFilings(on_read=change_live_rows)
    data = (await rig.client.get("/api/faults")).json()
    assert data["total"] == 2
    assert [row["occurrences"] for row in data["faults"]] == ["1", "1"]
    assert [row["status"] for row in data["faults"]] == ["open", "open"]
    assert data["faults"][1]["summary"] != first.error_text


async def test_get_fault_detaches_row_and_honestly_reads_retained_closed_record(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    await rig.store.resolve(fault.id, status="repaired", resolution="Closed by test")
    assert (await rig.client.get("/api/faults")).json()["total"] == 0
    rig.store.issue_filings = _FakeFilings(on_read=lambda: setattr(fault, "occurrences", 99))
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail["status"] == "repaired" and detail["occurrences"] == "1"
    assert detail["recorded_agent_id"] == "recorded-agent"
    assert "agent_ids" not in detail and "tool_trace_ref" not in detail
    assert fault.status == "repaired"


@pytest.mark.parametrize("endpoint", ["/api/faults", "/api/faults/abcdefabcdef"])
async def test_fault_reads_unreadable_store_is_safe_503(
    fault_visibility_api: SimpleNamespace, endpoint: str, caplog: Any,
) -> None:
    rig = fault_visibility_api
    rig.runtime.fault_report_store = _UnreadableStore()
    response = await rig.client.get(endpoint)
    assert response.status_code == 503
    assert response.json() == {"detail": "fault_store_unavailable"}
    assert "FAKE_STORE_EXCEPTION_SENTINEL" not in response.text + caplog.text


@pytest.mark.parametrize("endpoint", ["/api/faults", "/api/faults/abcdefabcdef", "/api/faults/BAD"])
@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic wrong", "Bearer correct"])
async def test_fault_reads_auth_precedes_diagnostic_access(
    fault_visibility_api: SimpleNamespace, endpoint: str, authorization: str | None,
) -> None:
    rig = fault_visibility_api
    store = _UnreadableStore()
    rig.runtime.fault_report_store = store
    rig.runtime.config.auth.crew_scope_token = "correct"
    response = await rig.client.get(
        endpoint, headers={} if authorization is None else {"Authorization": authorization},
    )
    expected = 422 if endpoint.endswith("BAD") else 503
    assert response.status_code == (expected if authorization == "Bearer correct" else 401)
    assert store.calls == int(authorization == "Bearer correct" and expected == 503)
    assert rig.trace.calls == rig.credentials.calls == 0


async def test_fault_reads_configured_auth_success_and_noncacheable_wire_schema(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    rig.runtime.config.auth.crew_scope_token = "correct"
    for endpoint in ("/api/faults", f"/api/faults/{fault.id}"):
        response = await rig.client.get(endpoint, headers={"Authorization": "Bearer correct"})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    # Inspect the actual canonical registrations without unrelated static UI routes'
    # locally imported HTMLResponse forward reference breaking global OpenAPI generation.
    document = get_openapi(
        title="Fault contract", version="1",
        routes=[route for route in rig.app.routes if getattr(route, "path", "").startswith("/api/faults")],
    )
    schemas = document["components"]["schemas"]
    assert schemas["FaultSummary"]["properties"]["occurrences"]["type"] == "string"
    assert schemas["FaultDetail"]["properties"]["trace_available"]["type"] == "boolean"
    assert "/api/faults" in document["paths"]
    assert "/api/faults/{fault_id}" in document["paths"]


@pytest.mark.parametrize("count", [0, -1, True, 1.5, "2", 2**63])
async def test_fault_reads_invalid_stored_counts_fail_closed(
    fault_visibility_api: SimpleNamespace, count: Any,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    fault.occurrences = count
    for endpoint in ("/api/faults", f"/api/faults/{fault.id}"):
        assert (await rig.client.get(endpoint)).status_code == 503


@pytest.mark.parametrize("disposition", ["declined", "retryable_failure", "attempting", "outcome_unknown", "filed"])
async def test_fault_reads_only_confirmed_pinned_issue_receipts_become_links(
    fault_visibility_api: SimpleNamespace, disposition: str,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    rig.runtime.config.repair.github_repository = "different/current"
    rig.store.issue_filings = _FakeFilings(IssueFiling(
        fault.signature, fault.id, "request", "owner/pinned", "attempt",
        disposition, 37, "https://github.com/owner/pinned/issues/37",
    ))
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail["issue_lookup_available"] is True
    expected = {
        "repository": "owner/pinned", "number": 37,
        "url": "https://github.com/owner/pinned/issues/37",
    } if disposition == "filed" else None
    assert detail["issue"] == expected


@pytest.mark.parametrize("change", [
    {"issue_url": "https://github.com/other/repo/issues/37"},
    {"issue_url": "https://github.com/owner/repo/issues/37?secret=sentinel"},
    {"issue_url": "javascript:alert(1)"},
    {"issue_number": None}, {"issue_number": True}, {"issue_number": 0},
    {"signature": "0" * 64}, {"repository": "../repo"},
])
async def test_fault_reads_invalid_receipts_do_not_expose_links(
    fault_visibility_api: SimpleNamespace, change: dict[str, Any],
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    filing = IssueFiling(
        fault.signature, fault.id, "request", "owner/repo", "attempt", "filed",
        37, "https://github.com/owner/repo/issues/37",
    )
    rig.store.issue_filings = _FakeFilings(replace(filing, **change))
    row = (await rig.client.get("/api/faults")).json()["faults"][0]
    assert row["issue"] is None and row["issue_lookup_available"] is True


async def test_fault_reads_journal_failure_is_visible_lookup_unavailable(
    fault_visibility_api: SimpleNamespace, caplog: Any,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    journal = _FakeFilings()
    journal.error = True
    rig.store.issue_filings = journal
    for endpoint in ("/api/faults", f"/api/faults/{fault.id}"):
        response = await rig.client.get(endpoint)
        assert response.status_code == 200
        row = response.json().get("fault") or response.json()["faults"][0]
        assert row["issue"] is None and row["issue_lookup_available"] is False
        assert "FAKE_JOURNAL_EXCEPTION_SENTINEL" not in response.text + caplog.text


async def test_fault_reads_new_id_same_signature_reuses_durable_receipt(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    old = await _fault(rig)
    claim = await rig.store.issue_filings.claim(
        fault_id=old.id, signature=old.signature, tool_id=old.tool_id,
        request_id="approved-test-request", repository="owner/repo",
        agent_id=old.agent_id, thread_id=old.thread_id, work_item_id=None, minimum_occurrences=1,
    )
    await rig.store.issue_filings.complete(
        old.signature, claim.filing.attempt_id, disposition="filed",
        receipt=IssueReceipt(37, "https://github.com/owner/repo/issues/37"),
    )
    await rig.store.resolve(old.id, status="dismissed")
    newer = await _fault(rig)
    assert newer.id != old.id and newer.signature == old.signature
    row = (await rig.client.get("/api/faults")).json()["faults"][0]
    assert row["id"] == newer.id and row["issue"]["number"] == 37
    assert (await rig.store.issue_filings.get(newer.signature)).fault_id == old.id


_NAMED_FIELDS = (
    "password", "passwd", "passphrase", "secret", "token", "access_token",
    "refresh_token", "api_key", "authorization", "cookie", "set-cookie",
    "private_key", "client_secret", "headers", "credential", "credentials",
)


@pytest.mark.parametrize("field", _NAMED_FIELDS)
async def test_fault_reads_named_data_policy_before_summary_and_nested_trace_analysis(
    fault_visibility_api: SimpleNamespace, field: str, caplog: Any,
) -> None:
    rig = fault_visibility_api
    text = f'Useful context "{field}": "FAKE_PRIVATE_MARKER with spaces"; safe tail'
    fault = await _fault(rig, error_text=text, attempted=text, agent_id=text)
    rig.trace.blob = json.dumps([{
        "name": "browser", "is_error": True,
        "arguments": {field: "FAKE_NESTED_MARKER", "action": "open"},
        "output": {"nested": [{field: "FAKE_NESTED_MARKER"}], "context": text},
    }] * 2)
    before = fault.to_dict()
    for endpoint in ("/api/faults", f"/api/faults/{fault.id}"):
        response = await rig.client.get(endpoint)
        assert response.status_code == 200
        assert "FAKE_PRIVATE_MARKER" not in response.text + caplog.text
        assert "FAKE_NESTED_MARKER" not in response.text + caplog.text
        assert "[REDACTED]" in response.text
        assert "Useful context" in response.text
    assert fault.to_dict() == before and rig.credentials.calls == 0


@pytest.mark.parametrize("field,wire,limit", [
    ("error_text", "summary", 160), ("error_text", "error_text", 2000),
    ("attempted", "attempted", 1000), ("tool_id", "tool_id", 128),
    ("agent_id", "recorded_agent_id", 128), ("thread_id", "thread_id", 128),
    ("work_item_id", "work_item_id", 128), ("observed_as", "observed_as", 128),
])
@pytest.mark.parametrize("extra", [0, 1])
async def test_get_fault_reports_exact_additional_clip_boundaries(
    fault_visibility_api: SimpleNamespace, field: str, wire: str, limit: int, extra: int,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    setattr(fault, field, "x" * (limit + extra))
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail[wire] == "x" * limit
    assert (wire in detail["clipped_fields"]) == bool(extra)


async def test_get_fault_redaction_precedes_all_clip_boundaries_and_trace_rendering(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    fault.error_text = "x" * 1930 + ' password="' + "FAKE_CLIP_MARKER " * 10
    fault.attempted = "x" * 980 + " Bearer FAKE_CLIP_MARKER"
    rig.trace.blob = json.dumps([{
        "name": "browser", "is_error": True,
        "arguments": {"note": "x" * 60 + " Basic FAKE_CLIP_MARKER"},
        "output": "x" * 265 + " -----BEGIN PRIVATE KEY-----\nFAKE_CLIP_MARKER\n" + "x" * 2000,
    }] * 2)
    response = await rig.client.get(f"/api/faults/{fault.id}")
    assert response.status_code == 200 and "FAKE_CLIP" not in response.text
    assert "[REDACTED]" in response.text
    assert response.json()["fault"]["trace_available"] is True


async def test_get_fault_trace_presentation_clipping_is_explicit(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    entries = [
        {"name": f"tool_{index}_" + "q" * 100, "is_error": False, "arguments": {}, "output": "ok"}
        for index in range(60)
    ]
    rig.trace.blob = json.dumps(entries)
    rendered = analyse_trace(entries).render()
    assert len(rendered) > 4000
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail["trace_available"] is True and detail["trace_summary"] == rendered[:4000]
    assert "trace_summary" in detail["clipped_fields"]


async def test_get_fault_empty_diagnostics_and_absent_attachment_store(
    fault_visibility_api: SimpleNamespace,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig, error_text="", attempted="", agent_id="", thread_id="", tool_trace_ref=None)
    rig.runtime.attachment_store = None
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail["summary"] == "Tool failure with no recorded error text."
    assert detail["work_item_id"] is None and detail["recorded_agent_id"] == ""
    assert detail["trace_available"] is False and detail["clipped_fields"] == []


@pytest.mark.parametrize("blob", [None, b"not json", "{}", "[]"])
async def test_get_fault_unreadable_or_empty_trace_is_honest(
    fault_visibility_api: SimpleNamespace, blob: bytes | str | None,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    rig.trace.blob = blob
    detail = (await rig.client.get(f"/api/faults/{fault.id}")).json()["fault"]
    assert detail["trace_available"] is False
    assert detail["trace_summary"] == "Stored trace sample unavailable: no readable recorded tool calls."


async def test_get_fault_trace_read_failure_never_returns_exception(
    fault_visibility_api: SimpleNamespace, caplog: Any,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(rig)
    rig.trace.error = True
    response = await rig.client.get(f"/api/faults/{fault.id}")
    assert response.status_code == 200 and not response.json()["fault"]["trace_available"]
    assert "FAKE_TRACE_EXCEPTION_SENTINEL" not in response.text + caplog.text


def test_shared_policy_preserves_trace_reader_import_and_primitive_boundaries() -> None:
    from probos.cognitive.repair_issue import TraceReader as OriginalTraceReader

    assert OriginalTraceReader is TraceReader
    assert sanitise_diagnostic_value(None) is None
    assert sanitise_diagnostic_value([True, 1, 1.5]) == [True, 1, 1.5]
    assert sanitise_diagnostic_value(object()) == "[unavailable]"
    assert sanitise_diagnostic_value("known fake", ("fake", "")) == "known [REDACTED]"
    assert sanitise_diagnostic_value("secret", depth=17) == "[REDACTED]"
    assert sanitise_diagnostic_value("\ud800") == "?"


async def test_shared_trace_reader_sanitizes_copies_and_handles_absence() -> None:
    reader = _FakeTrace(b'[{"password":"FAKE_PRIVATE","safe":"context"}]')
    safe = SanitisedTraceReader(reader)
    assert json.loads(await safe.read("ref")) == [{"password": "[REDACTED]", "safe": "context"}]
    assert b"FAKE_PRIVATE" in reader.blob
    assert await SanitisedTraceReader(None).read("ref") is None


@pytest.mark.parametrize("failure", ["read", "json"])
async def test_build_issue_report_trace_failure_logs_original_consumer_warning(
    fault_visibility_api: SimpleNamespace, caplog: Any, failure: str,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(
        rig, tool_trace_ref="FAKE_TRACE_REF_SENTINEL", error_text="FAKE_CONTEXT_SENTINEL",
    )
    rig.trace.blob = b"FAKE_TRACE_JSON_SENTINEL"
    rig.trace.error = failure == "read"
    caplog.set_level(logging.WARNING)
    caplog.clear()

    report = await build_issue_report(fault, attachment_store=rig.trace)

    assert rig.trace.calls == 1 and "Trace unavailable" in report.body
    assert caplog.record_tuples == [(
        "probos.cognitive.repair_issue", logging.WARNING,
        "AD-1206: fault trace could not be read safely; the issue report "
        "will explicitly identify unavailable trace evidence",
    )]
    assert "FAKE_" not in caplog.text
    assert "FAKE_TRACE_EXCEPTION_SENTINEL" not in report.body
    assert "FAKE_TRACE_JSON_SENTINEL" not in report.body


@pytest.mark.parametrize("failure", ["read", "json"])
async def test_get_fault_trace_failure_logs_detail_consumer_warning(
    fault_visibility_api: SimpleNamespace, caplog: Any, failure: str,
) -> None:
    rig = fault_visibility_api
    fault = await _fault(
        rig, tool_trace_ref="FAKE_TRACE_REF_SENTINEL", error_text="FAKE_CONTEXT_SENTINEL",
    )
    rig.trace.blob = b"FAKE_TRACE_JSON_SENTINEL"
    rig.trace.error = failure == "read"
    caplog.set_level(logging.WARNING)
    caplog.clear()

    response = await rig.client.get(f"/api/faults/{fault.id}")

    assert rig.trace.calls == 1 and response.status_code == 200
    assert response.json()["fault"]["trace_available"] is False
    assert caplog.record_tuples == [(
        "probos.routers.faults", logging.WARNING,
        "AD-1207: fault trace could not be read safely; fault detail "
        "will explicitly identify unavailable trace evidence",
    )]
    assert "FAKE_" not in caplog.text
    assert "FAKE_TRACE_EXCEPTION_SENTINEL" not in response.text
    assert "FAKE_TRACE_JSON_SENTINEL" not in response.text


@pytest.mark.parametrize("explicit_none", [False, True], ids=["default", "explicit-none"])
async def test_shared_trace_reader_default_warning_is_consumer_neutral(
    caplog: Any, explicit_none: bool,
) -> None:
    reader = _FakeTrace()
    reader.error = True
    safe = (
        SanitisedTraceReader(reader, warn_unavailable=None)
        if explicit_none else SanitisedTraceReader(reader)
    )
    caplog.set_level(logging.WARNING)

    assert await safe.read("FAKE_TRACE_REF_SENTINEL") is None
    assert reader.calls == 1
    assert caplog.record_tuples == [(
        "probos.diagnostic_safety", logging.WARNING,
        "Fault trace could not be read safely; diagnostic trace evidence will be unavailable",
    )]
    assert "FAKE_" not in caplog.text


@pytest.mark.parametrize("warning", [False, 0, "FAKE_CALLBACK_SENTINEL", object()])
def test_shared_trace_reader_invalid_warning_callback_is_rejected(warning: Any) -> None:
    reader = _FakeTrace()
    with pytest.raises(TypeError, match=r"^warn_unavailable must be callable$"):
        SanitisedTraceReader(reader, warn_unavailable=warning)
    assert reader.calls == 0


@pytest.mark.parametrize("state", ["absent", "empty", "safe", "read-failure", "invalid-json"])
async def test_shared_trace_reader_controlled_warning_only_runs_on_exception(
    caplog: Any, state: str,
) -> None:
    warnings: list[str] = []

    class _FalseyWarning:
        def __bool__(self) -> bool:
            return False

        def __call__(self) -> None:
            warnings.append("unavailable")

    reader = _FakeTrace(b'[{"safe":"FAKE_KNOWN_SECRET"}]')
    reader.error = state == "read-failure"
    if state == "empty":
        reader.blob = None
    elif state == "invalid-json":
        reader.blob = b"FAKE_TRACE_JSON_SENTINEL"
    safe = SanitisedTraceReader(
        None if state == "absent" else reader, ("FAKE_KNOWN_SECRET",),
        warn_unavailable=_FalseyWarning(),
    )

    result = await safe.read("FAKE_TRACE_REF_SENTINEL")

    assert result == (b'[{"safe": "[REDACTED]"}]' if state == "safe" else None)
    assert warnings == (["unavailable"] if state in {"read-failure", "invalid-json"} else [])
    assert caplog.records == []


def test_shared_trace_reader_warning_callback_is_keyword_only() -> None:
    with pytest.raises(TypeError, match="positional"):
        SanitisedTraceReader(None, (), lambda: None)


class _FaultReplay:
    """One owned producer/approval/API session, also driven interactively by Vitest."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from probos.attachments.filesystem_store import FilesystemAttachmentStore
        from probos.cognitive.architect import ArchitectAgent
        from probos.cognitive.builder import BuilderAgent
        from probos.execution.isolation import ExecutionResult, SubprocessSandbox
        from probos.notifications import NotificationQueue
        from tests.test_ad1066_code_execution_tool import _loop_runtime
        from tests.test_ad1205_fault_paths import HISTORIC_STDERR
        from tests.test_ad1206_repair_issue import _Bus, _Credentials, _HTTP
        import probos.capability_request as request_module
        import probos.fault_report as fault_module

        self.root = root.resolve()
        self.clock = SimpleNamespace(value=1000.0)
        fault_ids, request_ids = itertools.count(1), itertools.count(1)
        monkeypatch.setattr(fault_module, "uuid", SimpleNamespace(
            uuid4=lambda: uuid.UUID(hex=f"{next(fault_ids):012x}" + "0" * 20),
        ))
        monkeypatch.setattr(request_module, "uuid", SimpleNamespace(
            uuid4=lambda: uuid.UUID(int=next(request_ids)),
        ))
        monkeypatch.setattr(fault_module, "time", SimpleNamespace(time=lambda: self.clock.value))
        monkeypatch.setattr(request_module, "time", SimpleNamespace(time=lambda: self.clock.value))
        self.sandbox_calls: list[object] = []
        self.repair_calls: list[object] = []

        async def historical_result(sandbox: Any, request: Any) -> ExecutionResult:
            self.sandbox_calls.append(request)
            return ExecutionResult(
                success=False, exit_code=2, timed_out=False, stdout="",
                stderr=HISTORIC_STDERR, error=HISTORIC_STDERR,
            )

        async def forbidden_repair(*args: Any, **kwargs: Any) -> None:
            self.repair_calls.append((args, kwargs))
            raise AssertionError("Fault visibility/issue approval must not execute an internal repair")

        monkeypatch.setattr(SubprocessSandbox, "run", historical_result)
        monkeypatch.setattr(ArchitectAgent, "act", forbidden_repair)
        monkeypatch.setattr(BuilderAgent, "act", forbidden_repair)
        self.bus, self.credentials, self.http = _Bus(), _Credentials(), _HTTP()
        self.loop_runtime = _loop_runtime(self.root, enabled=True)
        self.loop_runtime.attachment_store = FilesystemAttachmentStore(self.root / "attachments")
        assert Path(self.loop_runtime.config.execution.scratch_dir).resolve().is_relative_to(self.root)
        self.runtime = SimpleNamespace(
            config=SystemConfig(), notification_queue=NotificationQueue(on_event=self.bus.emit),
            attachment_store=self.loop_runtime.attachment_store,
        )

        def notify(agent_id: str, title: str, **kwargs: Any) -> None:
            self.runtime.notification_queue.notify(agent_id, "fixture", "", title, **kwargs)

        self.runtime.notify = notify
        self.runtime.config.repair.enabled = True
        self.runtime.config.repair.github_repository = "owner/repo"
        self.runtime.config.repair.propose_after_occurrences = 2
        self.states: list[dict[str, Any]] = []

    async def start(self) -> None:
        from probos.capability_request import CapabilityRequestStore
        from probos.cognitive.repair_dispatch import RepairDispatcher
        from probos.cognitive.repair_issue import GitHubIssueClient, RepairIssueFulfiller

        self.faults = FaultReportStore(str(self.root / "faults.db"), emit_event=self.bus.emit)
        self.requests = CapabilityRequestStore(str(self.root / "requests.db"), emit_event=self.bus.emit)
        for store in (self.faults, self.requests):
            assert Path(store.db_path).resolve().parent == self.root
            await store.start()
        self.runtime.fault_report_store = self.loop_runtime.fault_report_store = self.faults
        self.runtime.capability_request_store = self.requests
        self.runtime.repair_issue_fulfiller = RepairIssueFulfiller(
            requests=self.requests, filings=self.faults.issue_filings,
            client=GitHubIssueClient(
                credential_store=self.credentials, http_client_factory=self.http.factory,
                attachment_store=self.runtime.attachment_store,
            ),
            repository="owner/repo", enabled=True, notify=self.runtime.notify, minimum_occurrences=2,
        )
        dispatcher = RepairDispatcher(
            runtime=self.loop_runtime, fault_report_store=self.faults,
            capability_request_store=self.requests, config=self.runtime.config.repair,
        )
        self.bus.listeners[:] = [dispatcher.on_fault_event]
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(self.runtime)), base_url="http://test",
        )

    async def stop(self) -> None:
        self.http.release.set()
        await self.bus.drain()
        await self.client.aclose()
        await self.requests.stop()
        await self.faults.stop()

    async def observe(self, turns: int) -> list[dict[str, Any]]:
        from tests.test_ad1066_code_execution_tool import _tool_use
        from tests.test_ad1205_fault_paths import HISTORIC_SIGNATURE, HISTORIC_STDERR, _run
        from tests.test_ad1257_defect_follows_failure import _text_response

        assert 1 <= turns <= 4
        for _ in range(turns):
            outcome = await _run(self.loop_runtime, [
                _tool_use("run_python", {"code": "print('historical identity fixture, not launch evidence')"}),
                _text_response("Controlled historical failure observed."),
            ], fault_attempted="Run the requested Python code")
            trace = json.loads(await self.runtime.attachment_store.read(outcome.tool_trace_ref))
            assert trace[0]["is_error"] is True and trace[0]["output"] == HISTORIC_STDERR
            assert trace[0]["error_signature"] == HISTORIC_SIGNATURE
            await self.bus.drain()
            rows = self.faults.list_open()
            assert not rows or rows[0].signature == HISTORIC_SIGNATURE
            self.states.append({
                "turn": len(self.states) + 1, "total": len(rows),
                "occurrences": rows[0].occurrences if rows else None,
                "approvals": len(await self.requests.list_pending()),
            })
        assert not self.repair_calls
        return self.states[-turns:]

    async def request(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        assert method in {"GET", "POST"}
        assert path.startswith(("/api/faults", "/api/capability-requests"))
        before = len(self.http.requests), len(self.credentials.calls)
        response = await self.client.request(method, path, json=body)
        await self.bus.drain()
        if method == "GET":
            assert before == (len(self.http.requests), len(self.credentials.calls))
        assert not self.repair_calls
        return {"status": response.status_code, "body": response.json()}

    async def snapshot(self) -> dict[str, Any]:
        listing = await self.request("GET", "/api/faults?limit=50&offset=0")
        assert listing["status"] == 200
        result = {"list": listing["body"]}
        if listing["body"]["faults"]:
            detail = await self.request("GET", "/api/faults/" + listing["body"]["faults"][0]["id"])
            assert detail["status"] == 200
            result["detail"] = detail["body"]
        return result

    async def restart(self) -> dict[str, Any]:
        before = await self.snapshot()
        await self.stop()
        await self.start()
        assert await self.snapshot() == before
        return before

    async def close_fault(self) -> dict[str, Any]:
        row = self.faults.list_open()[0]
        await self.faults.resolve(row.id, status="dismissed", resolution="Controlled replay closure")
        await self.bus.drain()
        self.clock.value = 3000.0
        return await self.snapshot()

    def evidence(self) -> dict[str, Any]:
        return {
            "observations": self.states,
            "posts": len([request for request in self.http.requests if request.method == "POST"]),
            "http_calls": len(self.http.requests),
            "credential_calls": len(self.credentials.calls),
            "internal_repairs": len(self.repair_calls),
            "sandbox_calls": len(self.sandbox_calls),
        }


@asynccontextmanager
async def _replay_context(root: Path) -> AsyncIterator[_FaultReplay]:
    from tests.test_ad1205_fault_paths import _assert_candidate_origins

    _assert_candidate_origins()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("PROBOS_DATA_DIR", str(root / "data"))
        monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
        replay = _FaultReplay(root, monkeypatch)
        await replay.start()
        try:
            yield replay
        finally:
            await replay.stop()
    _assert_candidate_origins()


async def _complete_replay(replay: _FaultReplay) -> dict[str, Any]:
    empty = await replay.snapshot()
    assert await replay.observe(2) == [
        {"turn": 1, "total": 0, "occurrences": None, "approvals": 0},
        {"turn": 2, "total": 0, "occurrences": None, "approvals": 0},
    ]
    assert (await replay.observe(1))[0]["occurrences"] == 1
    assert (await replay.observe(1))[0] == {"turn": 4, "total": 1, "occurrences": 2, "approvals": 1}
    pending = await replay.snapshot()
    fault_before = replay.faults.list_open()[0].to_dict()
    request = (await replay.requests.list_pending())[0]
    replay.clock.value = 2000.0
    decision = await replay.request("POST", f"/api/capability-requests/{request.id}/decide", {"approve": True})
    assert decision["status"] == 200 and decision["body"]["fulfilled"] is True
    assert replay.faults.list_open()[0].to_dict() == fault_before
    filed = await replay.snapshot()
    assert (await replay.faults.issue_filings.get(fault_before["signature"])).disposition == "filed"
    assert await replay.restart() == filed
    assert await replay.close_fault() == empty
    closed = await replay.request("GET", "/api/faults/" + fault_before["id"])
    assert closed["body"]["fault"]["status"] == "dismissed"
    assert (await replay.observe(2))[-1]["total"] == 0
    assert (await replay.observe(1))[0]["occurrences"] == 1
    assert (await replay.observe(1))[0]["occurrences"] == 2
    recurrence = await replay.snapshot()
    assert recurrence["list"]["faults"][0]["id"] != fault_before["id"]
    request = (await replay.requests.list_pending())[0]
    decision = await replay.request("POST", f"/api/capability-requests/{request.id}/decide", {"approve": True})
    assert decision["body"]["fulfilled"] is True
    assert recurrence == await replay.snapshot()
    assert replay.evidence() | {"observations": []} == {
        "observations": [], "posts": 1, "http_calls": 1, "credential_calls": 1,
        "internal_repairs": 0, "sandbox_calls": 8,
    }
    return {"empty": empty, "pending": pending, "filed": filed, "recurrence": recurrence}


async def test_continuous_historical_replay_matches_checked_bridge_wire(tmp_path: Path) -> None:
    async with _replay_context(tmp_path) as replay:
        observed = await _complete_replay(replay)
    fixture = Path(__file__).resolve().parents[1] / "ui/e2e/fixtures/ad1207-faults.json"
    assert observed == json.loads(fixture.read_text(encoding="utf-8"))


async def _serve_bridge(owned_root: str) -> None:
    """Bounded stdio protocol: real ASGI requests, never a host HTTP listener."""
    root = Path(__file__).resolve().parents[1]
    assert Path.cwd().resolve() == root
    directory = Path(owned_root).resolve()
    assert directory.is_dir() and directory.name.startswith("probos-ad1207-owned-")
    async with _replay_context(directory) as replay:
        for _ in range(200):
            line = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), timeout=60)
            if not line:
                break
            command = json.loads(line)
            action = command["action"]
            if action == "request":
                result = await replay.request(command["method"], command["path"], command.get("body"))
            elif action == "observe":
                result = await replay.observe(command["turns"])
            elif action == "snapshot":
                result = await replay.snapshot()
            elif action == "restart":
                result = await replay.restart()
            elif action == "close":
                result = await replay.close_fault()
            elif action == "evidence":
                result = replay.evidence()
            elif action == "hello":
                result = {
                    "root": str(root), "python": sys.executable,
                    "api": str(Path(sys.modules["probos.api"].__file__).resolve()),
                    "owned_store_root": str(directory),
                    "historical_fixture_not_launch_evidence": True,
                }
            else:
                raise AssertionError("Unknown replay command")
            sys.stdout.write(json.dumps({"id": command["id"], "result": result}) + "\n")
            sys.stdout.flush()
    assert not any(task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done())
