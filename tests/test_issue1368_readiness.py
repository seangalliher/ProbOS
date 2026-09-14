"""Issue 1368: actual read-route envelopes consumed by resourceState.ts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from probos.config import SystemConfig
from probos.knowledge.provo import project_record_frontmatter
from probos.routers.deps import get_runtime
from probos.routers.ontology import router as ontology_router
from probos.routers.readiness import Feature, failed_read, integration_availability, unavailable_dependency
from probos.routers.records import router


_SECRET = "credential=secret-token path=C:/private/records.db"
_KNOWLEDGE_ROUTES = ["/graph", "/timeline", "/backlinks/x.md"]


class _FakeStore:
    def __init__(self, result: Any, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def list_entries(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _FakeDocumentStore(_FakeStore):
    async def read_entry(self, path: str, reader_id: str = "") -> Any:
        self.calls += 1
        self.last_read = (path, reader_id)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeKnowledge:
    def __init__(self, result: Any, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def _read(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result

    async def get_graph(self, **kwargs: Any) -> Any:
        return self._read()

    async def get_timeline(self, **kwargs: Any) -> Any:
        return self._read()

    async def get_backlinks(self, path: str, **kwargs: Any) -> Any:
        return self._read()


class _FakeRuntime:
    def __init__(
        self,
        config: object | None,
        store: _FakeStore | None = None,
        knowledge: _FakeKnowledge | None = None,
    ) -> None:
        self.config = config
        self.records_store = store
        self.knowledge_browser = knowledge
        self.ontology: object | None = None


def _app(runtime: _FakeRuntime) -> FastAPI:
    app = FastAPI()
    app.state.runtime = runtime
    app.include_router(router)
    app.include_router(ontology_router)
    return app


@pytest.mark.parametrize("feature", ["records", "knowledge_browser", "skill_requests", "spatial_explorer", "nats"])
@pytest.mark.parametrize("enabled", [False, True])
def test_unavailable_dependency_typed_config_controls_disabled(
    feature: Feature, enabled: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)
    config = SystemConfig.model_validate({feature: {"enabled": enabled}})
    assert getattr(config, feature).enabled is enabled
    result = unavailable_dependency(config, feature)
    assert result == {
        "state": "unavailable" if enabled else "disabled",
        "code": f"{feature}.unavailable" if enabled else f"{feature}.disabled",
        "message": "Unavailable. Retry the request." if enabled else "Disabled. Review configuration with the operator.",
        "retryable": enabled,
    }


@pytest.mark.parametrize("config", [None, {}, {"records": {"enabled": False}}, MagicMock()])
@pytest.mark.parametrize("feature", ["records", "knowledge_browser", "skill_requests", "spatial_explorer", "nats", "ontology_graph"])
def test_unavailable_dependency_unknown_config_never_disabled(
    config: object | None, feature: Feature,
) -> None:
    result = unavailable_dependency(config, feature)
    assert result["state"] == "unavailable"
    assert result["code"] == f"{feature}.configuration_unknown"
    assert result["retryable"] is True


@pytest.mark.parametrize("route", ["/browse", "/documents/x.md", *_KNOWLEDGE_ROUTES])
@pytest.mark.parametrize("enabled", [False, True, None])
def test_records_missing_dependency_http_envelope(route: str, enabled: bool | None) -> None:
    feature = "records" if route in ("/browse", "/documents/x.md") else "knowledge_browser"
    config = None if enabled is None else SystemConfig.model_validate({feature: {"enabled": enabled}})
    with TestClient(_app(_FakeRuntime(config))) as client:
        response = client.get(f"/api/records{route}")
    assert response.status_code == 503
    payload = response.json()
    assert payload["error"] == ("Ship's Records not available" if feature == "records" else "Knowledge Browser not available")
    assert payload["availability"] == unavailable_dependency(config, feature)


@pytest.mark.parametrize("entries", [[], [{"path": "x.md", "frontmatter": {"author": "captain"}}]])
def test_browse_success_payload_unchanged(entries: list[dict[str, Any]]) -> None:
    store = _FakeStore(entries)
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/browse")
    assert store.calls == 1
    assert response.status_code == 200
    assert response.json() == {
        "documents": entries, "count": len(entries),
        "filters_applied": {
            "author": "", "department": "", "classification": "", "directory": "",
            "tags": [], "since": "", "until": "",
        },
    }


@pytest.mark.parametrize("error", [RuntimeError(_SECRET), OSError(_SECRET), None])
def test_browse_storage_failure_not_successful_empty(
    error: Exception | None, caplog: pytest.LogCaptureFixture,
) -> None:
    store = _FakeStore(None, error)
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/browse")
    assert store.calls == 1
    assert response.status_code == 503
    assert response.json() == {
        "error": "Records browse unavailable",
        "availability": {
            "state": "unavailable", "code": "records.read_failed",
            "message": "Records browse unavailable", "retryable": True,
        },
    }
    assert "returning HTTP 503" in caplog.text
    assert _SECRET not in response.text + caplog.text


@pytest.mark.parametrize("route,error_text,code", [
    ("/graph", "graph assembly failed", "graph_failed"),
    ("/timeline", "timeline assembly failed", "timeline_failed"),
    ("/backlinks/x.md", "backlink lookup failed", "backlinks_failed"),
])
def test_knowledge_failure_preserves_http_error_without_leaking_exception(
    route: str, error_text: str, code: str, caplog: pytest.LogCaptureFixture,
) -> None:
    service = _FakeKnowledge(None, RuntimeError(_SECRET))
    with TestClient(_app(_FakeRuntime(SystemConfig(), knowledge=service))) as client:
        response = client.get(f"/api/records{route}")
    assert service.calls == 1
    assert response.status_code == 500
    assert response.json() == {
        "error": error_text,
        "availability": {
            "state": "failed", "code": f"knowledge_browser.{code}",
            "message": error_text, "retryable": True,
        },
    }
    assert "returning HTTP 500" in caplog.text
    assert _SECRET not in response.text + caplog.text


@pytest.mark.parametrize("route", _KNOWLEDGE_ROUTES)
def test_knowledge_none_result_not_successful_empty(route: str) -> None:
    service = _FakeKnowledge(None)
    with TestClient(_app(_FakeRuntime(SystemConfig(), knowledge=service))) as client:
        response = client.get(f"/api/records{route}")
    assert service.calls == 1
    assert response.status_code == (404 if route.startswith("/backlinks") else 500)
    assert response.json()["availability"]["state"] == "failed"


@pytest.mark.parametrize("route,payload", [
    ("/graph", {"nodes": [], "edges": []}),
    ("/graph", {"nodes": [{"id": "x.md"}], "edges": []}),
    ("/timeline", {"bucket": "day", "buckets": [], "total": 0}),
    ("/timeline", {"bucket": "day", "buckets": [{"date": "2026-09-13", "count": 1, "by_department": {"science": 1}}], "total": 1}),
    ("/backlinks/x.md", {"path": "x.md", "explicit": [], "suggested": []}),
    ("/backlinks/x.md", {"path": "x.md", "explicit": [{"path": "y.md"}], "suggested": []}),
])
def test_knowledge_success_payload_unchanged(route: str, payload: dict[str, Any]) -> None:
    service = _FakeKnowledge(payload)
    config = SystemConfig.model_validate({"knowledge_browser": {"enabled": True}})
    with TestClient(_app(_FakeRuntime(config, knowledge=service))) as client:
        response = client.get(f"/api/records{route}")
    assert service.calls == 1
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.parametrize("route", ["/browse", "/timeline"])
def test_invalid_read_parameters_do_not_leak_exception(route: str) -> None:
    runtime = _FakeRuntime(
        SystemConfig(), store=_FakeStore(None, ValueError(_SECRET)),
        knowledge=_FakeKnowledge(None, ValueError(_SECRET)),
    )
    with TestClient(_app(runtime)) as client:
        response = client.get(f"/api/records{route}")
    assert response.status_code == 400
    assert response.json()["availability"]["state"] == "failed"
    assert response.json()["availability"]["retryable"] is False
    assert _SECRET not in response.text


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("route", ["/browse", "/documents/x.md", *_KNOWLEDGE_ROUTES, "/api/ontology/graph"])
def test_authorization_failure_keeps_http_contract(status: int, route: str) -> None:
    def deny_access() -> None:
        raise HTTPException(status_code=status, detail="Access denied")

    app = _app(_FakeRuntime(SystemConfig()))
    app.dependency_overrides[get_runtime] = deny_access
    with TestClient(app) as client:
        response = client.get(route if route.startswith("/api/") else f"/api/records{route}")
    assert response.status_code == status
    assert response.json() == {"detail": "Access denied"}


def test_document_success_preserves_body_and_reader_side_effect() -> None:
    payload = {"path": "x.md", "frontmatter": {}, "body": "", "content": "raw document"}
    store = _FakeDocumentStore(payload)
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/documents/x.md?reader=science")
    assert response.status_code == 200
    assert response.json() == payload
    assert store.calls == 1
    assert store.last_read == ("x.md", "science")


@pytest.mark.parametrize("error,status,code", [
    (None, 404, "records.not_found"),
    (ValueError(_SECRET), 400, "records.invalid_parameters"),
    (OSError(_SECRET), 503, "records.read_failed"),
])
def test_document_read_failure_controlled_envelope(
    error: Exception | None, status: int, code: str, caplog: pytest.LogCaptureFixture,
) -> None:
    store = _FakeDocumentStore(None, error)
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/documents/x.md")
    assert store.calls == 1
    assert response.status_code == status
    assert response.json()["availability"]["code"] == code
    assert response.json()["availability"]["retryable"] is (status == 503)
    if status == 404:
        assert response.json()["error"] == "Not found or access denied"
    assert _SECRET not in response.text + caplog.text


def test_document_invalid_format_does_not_read() -> None:
    store = _FakeDocumentStore({})
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/documents/x.md?format=unsupported")
    assert store.calls == 0
    assert response.status_code == 400
    assert response.json()["error"] == "Unsupported format; expected 'prov-jsonld'"
    assert response.json()["availability"]["retryable"] is False


def test_document_provenance_projection_preserves_reader_and_shape() -> None:
    payload = {"path": "x.md", "frontmatter": {"title": "Report", "author": "captain"}, "body": "raw"}
    store = _FakeDocumentStore(payload)
    with TestClient(_app(_FakeRuntime(SystemConfig(), store=store))) as client:
        response = client.get("/api/records/documents/x.md?format=prov-jsonld&reader=science")
    assert response.status_code == 200
    assert response.json() == project_record_frontmatter("x.md", payload["frontmatter"])
    assert store.calls == 1
    assert store.last_read == ("x.md", "science")


@pytest.mark.parametrize("enabled", [False, True])
def test_document_absent_from_present_store_remains_404(enabled: bool) -> None:
    config = SystemConfig.model_validate({"records": {"enabled": enabled}})
    store = _FakeDocumentStore(None)
    with TestClient(_app(_FakeRuntime(config, store=store))) as client:
        response = client.get("/api/records/documents/missing.md")
    assert store.calls == 1
    assert response.status_code == 404
    assert response.json() == {
        "error": "Not found or access denied",
        "availability": {
            "state": "failed", "code": "records.not_found",
            "message": "Not found or access denied", "retryable": False,
        },
    }


@pytest.mark.parametrize("status,state,retryable", [
    (400, "failed", False), (404, "failed", False),
    (500, "failed", True), (503, "unavailable", True),
])
def test_failed_read_wire_fields_match_resource_classifier(
    status: int, state: str, retryable: bool,
) -> None:
    availability = failed_read("Read unavailable", "records.read_failed", status)
    assert availability == {
        "state": state, "code": "records.read_failed",
        "message": "Read unavailable", "retryable": retryable,
    }
    assert re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", availability["code"])
    assert 0 < len(availability["message"].strip()) <= 240
    assert type(availability["retryable"]) is bool


def test_unavailable_ontology_has_no_disabled_configuration_authority() -> None:
    assert unavailable_dependency(SystemConfig(), "ontology_graph") == {
        "state": "unavailable", "code": "ontology_graph.unavailable",
        "message": "Unavailable. Retry the request.", "retryable": True,
    }


@pytest.mark.parametrize("feature", ["records", "knowledge_browser", "skill_requests", "spatial_explorer", "ontology_graph"])
@pytest.mark.parametrize("initialized", [False, True])
def test_integration_initialization_is_not_io_readiness(feature: Feature, initialized: bool) -> None:
    config = SystemConfig.model_validate({
        key: {"enabled": True}
        for key in ("records", "knowledge_browser", "skill_requests", "spatial_explorer")
    })
    result = integration_availability(config, feature, initialized=initialized)
    assert result["id"] == ("spatial_layout" if feature == "spatial_explorer" else feature)
    assert result["scope"] == "initialization"
    assert result["state"] == ("initialized" if initialized else "unavailable")
    assert result["retryable"] is (not initialized)


@pytest.mark.parametrize("feature", ["records", "knowledge_browser", "skill_requests", "spatial_explorer", "nats"])
def test_integration_explicit_config_off_overrides_presence(feature: Feature) -> None:
    config = SystemConfig.model_validate({feature: {"enabled": False}})
    result = integration_availability(config, feature, initialized=True, connected=True)
    assert result["state"] == "disabled"
    assert result["retryable"] is False


@pytest.mark.parametrize("connected,state", [(True, "ready"), (False, "unavailable"), (None, "unavailable")])
def test_integration_nats_requires_current_connection(
    connected: bool | None, state: str, real_nats: None,
) -> None:
    config = SystemConfig.model_validate({"nats": {"enabled": True}})
    assert config.nats.enabled is True
    result = integration_availability(config, "nats", initialized=True, connected=connected)
    assert result["state"] == state
    assert result["scope"] == "connection"


def test_integration_unknown_config_and_absence_remain_unavailable() -> None:
    result = integration_availability(None, "records", initialized=False)
    assert result["state"] == "unavailable"
    assert result["code"] == "records.configuration_unknown"
    assert integration_availability(None, "nats", initialized=True, connected=True)["state"] == "unavailable"


@dataclass
class _FakeDepartment:
    id: str = "science"
    name: str = "Science"
    accent_color: str = "#00aaaa"


class _FakeOntology:
    def __init__(self, populated: bool = False, error: Exception | None = None) -> None:
        self.populated = populated
        self.error = error
        self.calls = 0

    def get_departments(self) -> list[_FakeDepartment]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [_FakeDepartment()] if self.populated else []

    def get_crew_manifest(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def get_all_assignments(self) -> list[Any]:
        return []


@pytest.mark.parametrize("config", [None, SystemConfig(), {"ontology": {"enabled": False}}])
def test_ontology_graph_missing_dependency_never_disabled(config: object | None) -> None:
    with TestClient(_app(_FakeRuntime(config))) as client:
        response = client.get("/api/ontology/graph")
    assert response.status_code == 503
    assert response.json()["error"] == "Ontology not initialized"
    assert response.json()["availability"]["state"] == "unavailable"


@pytest.mark.parametrize("populated", [False, True])
def test_ontology_graph_real_snapshot_success_body(populated: bool) -> None:
    runtime = _FakeRuntime(SystemConfig())
    ontology = _FakeOntology(populated)
    runtime.ontology = ontology
    with TestClient(_app(runtime)) as client:
        response = client.get("/api/ontology/graph?include_edges=false")
    assert ontology.calls == 1
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"nodes", "edges", "generated_at"}
    assert payload["edges"] == []
    assert isinstance(payload["generated_at"], (float, int))
    assert payload["nodes"] == ([{
        "id": "science", "label": "Science", "type": "department", "accent_color": "#00aaaa",
    }] if populated else [])


def test_ontology_graph_read_failure_http_controlled(caplog: pytest.LogCaptureFixture) -> None:
    runtime = _FakeRuntime(SystemConfig())
    ontology = _FakeOntology(error=RuntimeError(_SECRET))
    runtime.ontology = ontology
    with TestClient(_app(runtime)) as client:
        response = client.get("/api/ontology/graph")
    assert ontology.calls == 1
    assert response.status_code == 500
    assert response.json() == {
        "error": "Ontology graph unavailable",
        "availability": {
            "state": "failed", "code": "ontology_graph.read_failed",
            "message": "Ontology graph unavailable", "retryable": True,
        },
    }
    assert "returning HTTP 500" in caplog.text
    assert _SECRET not in response.text + caplog.text


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("route", ["/api/records/documents/x.md", "/api/ontology/graph"])
def test_dependency_http_authorization_not_reclassified(route: str, status: int) -> None:
    error = HTTPException(status_code=status, detail="Access denied")
    store = _FakeDocumentStore(None, error)
    ontology = _FakeOntology(error=error)
    runtime = _FakeRuntime(SystemConfig(), store=store)
    runtime.ontology = ontology
    with TestClient(_app(runtime)) as client:
        response = client.get(route)
    assert store.calls + ontology.calls == 1
    assert response.status_code == status
    assert response.json() == {"detail": "Access denied"}