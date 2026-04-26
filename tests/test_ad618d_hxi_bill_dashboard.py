"""Tests for AD-618d: HXI Bill Dashboard — API router endpoints."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.sop.schema import (
    BillActivation, BillDefinition, BillRole, BillStep, GatewayType,
)
from probos.sop.instance import (
    BillInstance, InstanceStatus, RoleAssignment, StepState, StepStatus,
)


# ── Helpers ─────────────────────────────────────────────────────────


def _make_definition(bill_id: str = "general_quarters", title: str = "General Quarters") -> BillDefinition:
    """Create a test BillDefinition."""
    return BillDefinition(
        bill=bill_id,
        version=1,
        title=title,
        description="All hands to battle stations",
        activation=BillActivation(trigger="manual", authority="captain"),
        roles={
            "officer_of_deck": BillRole(id="officer_of_deck", department="operations", count="1"),
        },
        steps=[
            BillStep(id="sound_alarm", name="Sound Alarm", role="officer_of_deck", action="announce"),
        ],
    )


def _make_instance(instance_id: str = "inst001", bill_id: str = "general_quarters") -> BillInstance:
    """Create a test BillInstance."""
    inst = BillInstance(
        id=instance_id,
        bill_id=bill_id,
        bill_title="General Quarters",
        bill_version=1,
        status=InstanceStatus.ACTIVE,
        activated_by="captain",
        activated_at=1000.0,
    )
    inst.role_assignments["officer_of_deck"] = RoleAssignment(
        role_id="officer_of_deck",
        agent_id="agent-1",
        agent_type="OpsAgent",
        callsign="O'Brien",
        department="operations",
    )
    inst.step_states["sound_alarm"] = StepState(
        step_id="sound_alarm",
        status=StepStatus.ACTIVE,
        action="announce",
        assigned_agent_id="agent-1",
        assigned_agent_callsign="O'Brien",
    )
    return inst


def _make_mock_runtime(bill_runtime=None):
    """Create a mock runtime with optional bill_runtime."""
    from probos.runtime import ProbOSRuntime
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime._bill_runtime = bill_runtime
    runtime.add_event_listener = MagicMock()
    return runtime


def _make_mock_bill_runtime():
    """Create a mock BillRuntime."""
    br = MagicMock()
    br.list_definitions = MagicMock(return_value=[])
    br.get_definition = MagicMock(return_value=None)
    br.list_instances = MagicMock(return_value=[])
    br.get_instance = MagicMock(return_value=None)
    br.activate = AsyncMock()
    br.cancel = MagicMock(return_value=False)
    br.get_agent_assignments = MagicMock(return_value=[])
    return br


@pytest.fixture
def bill_runtime():
    return _make_mock_bill_runtime()


@pytest.fixture
def client(bill_runtime):
    from probos.api import create_app
    from fastapi.testclient import TestClient
    runtime = _make_mock_runtime(bill_runtime=bill_runtime)
    app = create_app(runtime)
    return TestClient(app)


@pytest.fixture
def client_no_bills():
    """Client with no bill runtime (service unavailable)."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    runtime = _make_mock_runtime(bill_runtime=None)
    app = create_app(runtime)
    return TestClient(app)


# ── Definition endpoint tests ──────────────────────────────────────


class TestBillDefinitions:
    """Tests for GET /api/bills/definitions endpoints."""

    def test_list_definitions_returns_catalog(self, client, bill_runtime):
        """List returns all loaded definitions."""
        d1 = _make_definition("gq", "General Quarters")
        d2 = _make_definition("fire", "Fire Drill")
        bill_runtime.list_definitions.return_value = [d1, d2]

        resp = client.get("/api/bills/definitions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["definitions"]) == 2
        assert data["definitions"][0]["bill_id"] == "gq"
        assert data["definitions"][1]["bill_id"] == "fire"

    def test_get_definition_found(self, client, bill_runtime):
        """Get single definition by slug."""
        defn = _make_definition()
        bill_runtime.get_definition.return_value = defn

        resp = client.get("/api/bills/definitions/general_quarters")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bill_id"] == "general_quarters"
        assert data["title"] == "General Quarters"
        assert data["version"] == 1
        assert data["activation"]["trigger"] == "manual"
        assert data["activation"]["authority"] == "captain"
        assert data["role_count"] == 1
        assert data["step_count"] == 1
        assert data["roles"][0]["role_id"] == "officer_of_deck"
        assert data["steps"][0]["step_id"] == "sound_alarm"

    def test_get_definition_not_found(self, client, bill_runtime):
        """404 for unknown bill slug."""
        bill_runtime.get_definition.return_value = None

        resp = client.get("/api/bills/definitions/nonexistent")
        assert resp.status_code == 404

    def test_definitions_service_unavailable(self, client_no_bills):
        """503 when BillRuntime not loaded."""
        resp = client_no_bills.get("/api/bills/definitions")
        assert resp.status_code == 503


# ── Instance endpoint tests ────────────────────────────────────────


class TestBillInstances:
    """Tests for GET /api/bills/instances endpoints."""

    def test_list_instances_all(self, client, bill_runtime):
        """List returns all instances via to_dict()."""
        inst = _make_instance()
        bill_runtime.list_instances.return_value = [inst]

        resp = client.get("/api/bills/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["instances"][0]["id"] == "inst001"
        assert data["instances"][0]["status"] == "active"

    def test_list_instances_filtered_by_status(self, client, bill_runtime):
        """Status param converted to InstanceStatus enum."""
        bill_runtime.list_instances.return_value = []

        resp = client.get("/api/bills/instances?status=active")
        assert resp.status_code == 200
        bill_runtime.list_instances.assert_called_once_with(
            status=InstanceStatus.ACTIVE,
            bill_id=None,
        )

    def test_get_instance_detail(self, client, bill_runtime):
        """Get instance with step_states and role_assignments."""
        inst = _make_instance()
        bill_runtime.get_instance.return_value = inst

        resp = client.get("/api/bills/instances/inst001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "inst001"
        assert "role_assignments" in data
        assert "step_states" in data
        assert "officer_of_deck" in data["role_assignments"]

    def test_get_instance_not_found(self, client, bill_runtime):
        """404 for unknown instance."""
        bill_runtime.get_instance.return_value = None

        resp = client.get("/api/bills/instances/nonexistent")
        assert resp.status_code == 404

    def test_get_instance_assignments(self, client, bill_runtime):
        """Assignments endpoint reads instance.role_assignments, not get_agent_assignments."""
        inst = _make_instance()
        bill_runtime.get_instance.return_value = inst

        resp = client.get("/api/bills/instances/inst001/assignments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["assignments"][0]["role_id"] == "officer_of_deck"
        assert data["assignments"][0]["callsign"] == "O'Brien"
        # Must NOT call get_agent_assignments — that answers a different question
        bill_runtime.get_agent_assignments.assert_not_called()


# ── Action endpoint tests ──────────────────────────────────────────


class TestBillActions:
    """Tests for POST /api/bills/activate and cancel."""

    def test_activate_bill_success(self, client, bill_runtime):
        """Activate passes BillDefinition (not bill_id) to br.activate()."""
        defn = _make_definition()
        inst = _make_instance()
        bill_runtime.get_definition.return_value = defn
        bill_runtime.activate.return_value = inst

        resp = client.post("/api/bills/activate", json={
            "bill_id": "general_quarters",
            "context": {"severity": "high"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "inst001"

        # Verify activate received BillDefinition, not string
        bill_runtime.activate.assert_called_once()
        call_args = bill_runtime.activate.call_args
        assert call_args[0][0] is defn  # first positional arg is the definition object
        assert call_args[1]["activation_data"] == {"severity": "high"}

    def test_activate_bill_unknown_id(self, client, bill_runtime):
        """404 when bill_id not found in registry."""
        bill_runtime.get_definition.return_value = None

        resp = client.post("/api/bills/activate", json={"bill_id": "nonexistent"})
        assert resp.status_code == 404

    def test_cancel_instance_success(self, client, bill_runtime):
        """Cancel returns instance dict after successful cancellation."""
        inst = _make_instance()
        inst.status = InstanceStatus.CANCELLED
        bill_runtime.cancel.return_value = True
        bill_runtime.get_instance.return_value = inst

        resp = client.post("/api/bills/instances/inst001/cancel", json={"reason": "drill complete"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        bill_runtime.cancel.assert_called_once_with("inst001", reason="drill complete")

    def test_cancel_instance_not_found(self, client, bill_runtime):
        """404 when cancel returns False (not found or already terminal)."""
        bill_runtime.cancel.return_value = False

        resp = client.post("/api/bills/instances/inst001/cancel", json={"reason": "test"})
        assert resp.status_code == 404


# ── Serialization tests ────────────────────────────────────────────


class TestSerialization:
    """Tests for _serialize_definition edge cases."""

    def test_serialize_definition_handles_none_activation(self, client, bill_runtime):
        """Definition with activation=None serializes correctly."""
        defn = BillDefinition(bill="test", title="Test", activation=None)
        bill_runtime.get_definition.return_value = defn

        resp = client.get("/api/bills/definitions/test")
        assert resp.status_code == 200
        assert resp.json()["activation"] is None

    def test_serialize_definition_roles_as_dict(self, client, bill_runtime):
        """Roles dict is iterated via .values(), not serialized as raw dict."""
        defn = _make_definition()
        bill_runtime.list_definitions.return_value = [defn]

        resp = client.get("/api/bills/definitions")
        data = resp.json()
        roles = data["definitions"][0]["roles"]
        assert isinstance(roles, list)
        assert roles[0]["role_id"] == "officer_of_deck"
        assert roles[0]["department"] == "operations"
