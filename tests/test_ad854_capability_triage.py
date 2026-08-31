"""AD-854: tests for the acquire-vs-build capability triage router."""
from __future__ import annotations

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_triage import (
    evaluate_grant_fast_path,
    triage,
    triage_and_file,
)
from probos.config import CapabilityTriageConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission


# --------------------------------------------------------------------------- #
# Fakes (registries only — storage uses real stores per BF-287)
# --------------------------------------------------------------------------- #
class _FakeRegistration:
    def __init__(self, default_permissions: dict | None = None) -> None:
        self.default_permissions = default_permissions or {}


class _FakeToolRegistry:
    def __init__(self, registrations: dict[str, _FakeRegistration]) -> None:
        self._regs = registrations

    def get(self, tool_id: str):
        return self._regs.get(tool_id)


class _FakeMcpServerRecord:
    """Mirrors the McpServerRecord fields resolve_installable_mcp_server reads."""

    def __init__(self, *, id: str, name: str, enabled: bool) -> None:
        self.id = id
        self.name = name
        self.enabled = enabled


class _FakeMcpServerStore:
    def __init__(self, records: list[_FakeMcpServerRecord]) -> None:
        self._records = records
        self.set_enabled_calls: list[tuple[str, bool]] = []

    def list_sync(self) -> list[_FakeMcpServerRecord]:
        return list(self._records)

    async def set_enabled(self, server_id: str, enabled: bool):
        self.set_enabled_calls.append((server_id, enabled))
        for rec in self._records:
            if rec.id == server_id:
                rec.enabled = enabled
                return rec
        return None


class _FakeOntology:
    def __init__(self, departments: dict[str, str]) -> None:
        self._departments = departments

    def get_agent_department(self, agent_id: str):
        return self._departments.get(agent_id)


class _FakeRecord:
    def __init__(self, status: str) -> None:
        self.status = status


class _FakeSelfMod:
    def __init__(self, record: _FakeRecord | None) -> None:
        self._record = record
        self.calls: list[tuple] = []

    async def handle_unhandled_intent(self, intent_name, description, params, **_kw):
        self.calls.append((intent_name, description, params))
        return self._record


# --------------------------------------------------------------------------- #
# Pure: triage()
# --------------------------------------------------------------------------- #
class TestTriagePure:
    def test_registered_tool_without_permission_returns_grant(self):
        # Arrange / Act
        rung = triage(
            tool_registered=True, agent_has_permission=False, skill_known=False
        )
        # Assert
        assert rung == "grant"

    def test_known_skill_returns_install(self):
        rung = triage(
            tool_registered=False, agent_has_permission=False, skill_known=True
        )
        assert rung == "install"

    def test_novel_capability_returns_build(self):
        rung = triage(
            tool_registered=False, agent_has_permission=False, skill_known=False
        )
        assert rung == "build"

    def test_registered_with_permission_falls_through_to_skill_or_build(self):
        # Already-permitted registered tool is not a grant; falls to skill/build.
        assert (
            triage(tool_registered=True, agent_has_permission=True, skill_known=True)
            == "install"
        )
        assert (
            triage(tool_registered=True, agent_has_permission=True, skill_known=False)
            == "build"
        )

    def test_triage_is_deterministic(self):
        for _ in range(5):
            assert (
                triage(
                    tool_registered=True,
                    agent_has_permission=False,
                    skill_known=True,
                )
                == "grant"
            )


# --------------------------------------------------------------------------- #
# Pure: evaluate_grant_fast_path()
# --------------------------------------------------------------------------- #
class TestEvaluateGrantFastPath:
    def test_all_conditions_true_auto_approves(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=True,
                peer_precedent=True,
                agent_trust=0.9,
                trust_floor=0.8,
                fast_path_enabled=True,
            )
            is True
        )

    def test_disabled_blocks(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=True,
                peer_precedent=True,
                agent_trust=0.9,
                trust_floor=0.8,
                fast_path_enabled=False,
            )
            is False
        )

    def test_destructive_blocks(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=False,
                peer_precedent=True,
                agent_trust=0.9,
                trust_floor=0.8,
                fast_path_enabled=True,
            )
            is False
        )

    def test_no_peer_precedent_blocks(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=True,
                peer_precedent=False,
                agent_trust=0.9,
                trust_floor=0.8,
                fast_path_enabled=True,
            )
            is False
        )

    def test_trust_below_floor_blocks(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=True,
                peer_precedent=True,
                agent_trust=0.7,
                trust_floor=0.8,
                fast_path_enabled=True,
            )
            is False
        )

    def test_trust_exactly_at_floor_passes(self):
        assert (
            evaluate_grant_fast_path(
                non_destructive=True,
                peer_precedent=True,
                agent_trust=0.8,
                trust_floor=0.8,
                fast_path_enabled=True,
            )
            is True
        )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
class TestCapabilityTriageConfig:
    def test_defaults_are_conservative(self):
        cfg = CapabilityTriageConfig()
        assert cfg.grant_fast_path_enabled is False
        assert cfg.grant_trust_floor == 0.8

    def test_trust_floor_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            CapabilityTriageConfig(grant_trust_floor=1.5)
        with pytest.raises(ValueError):
            CapabilityTriageConfig(grant_trust_floor=-0.1)

    def test_zero_config_system_boots_with_triage_defaults(self):
        cfg = SystemConfig()
        assert cfg.capability_triage.grant_fast_path_enabled is False
        assert cfg.capability_triage.grant_trust_floor == 0.8


# --------------------------------------------------------------------------- #
# Async driver: triage_and_file()
# --------------------------------------------------------------------------- #
class TestTriageAndFile:
    @pytest.fixture
    async def store(self, tmp_path):
        captured: list[tuple] = []
        s = CapabilityRequestStore(
            db_path=str(tmp_path / "cap_triage.db"),
            emit_event=lambda et, data: captured.append((et, data)),
        )
        await s.start()
        s.captured = captured  # type: ignore[attr-defined]
        yield s
        await s.stop()

    @pytest.mark.asyncio
    async def test_build_files_request_and_routes_to_self_mod(self, store):
        # Arrange
        self_mod = _FakeSelfMod(_FakeRecord(status="active"))
        # Act — novel capability, no registries -> build
        req = await triage_and_file(
            gap_target="WeatherAgent",
            agent_id="agent-1",
            store=store,
            rationale="needs forecast",
            work_item_id="wi-7",
            self_mod_pipeline=self_mod,
        )
        # Assert
        assert req.kind == "build"
        assert req.work_item_id == "wi-7"
        assert req.status == "fulfilled"
        assert self_mod.calls and self_mod.calls[0][0] == "WeatherAgent"

    @pytest.mark.asyncio
    async def test_build_left_pending_when_self_mod_returns_inactive(self, store):
        # Arrange
        self_mod = _FakeSelfMod(_FakeRecord(status="rejected"))
        # Act
        req = await triage_and_file(
            gap_target="WeatherAgent",
            agent_id="agent-1",
            store=store,
            self_mod_pipeline=self_mod,
        )
        # Assert — self-mod owns its own gate; not fulfilled, no double-prompt
        assert req.kind == "build"
        assert req.status == "pending"

    @pytest.mark.asyncio
    async def test_install_left_pending_for_captain(self, store):
        # Arrange — AD-1215: a registered-but-disabled MCP server is the install rung
        mcp = _FakeMcpServerStore(
            [_FakeMcpServerRecord(id="pdf_extract", name="pdf-extract", enabled=False)]
        )
        # Act
        req = await triage_and_file(
            gap_target="pdf_extract",
            agent_id="agent-2",
            store=store,
            mcp_server_store=mcp,
        )
        # Assert
        assert req.kind == "install"
        assert req.status == "pending"

    @pytest.mark.asyncio
    async def test_honest_degrades_to_build_with_no_registries(self, store, caplog):
        # Arrange / Act — no tool or MCP registry present
        import logging

        with caplog.at_level(logging.WARNING):
            req = await triage_and_file(
                gap_target="UnknownThing",
                agent_id="agent-3",
                store=store,
                self_mod_pipeline=_FakeSelfMod(None),
            )
        # Assert
        assert req.kind == "build"
        assert any("honest-degrad" in r.message.lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_grant_fast_path_auto_approves_and_fulfils(self, tmp_path, store):
        # Arrange — real stores + real trust; in-dept peer already holds the grant.
        perm = ToolPermissionStore(db_path=str(tmp_path / "perms.db"))
        await perm.start()
        try:
            await perm.issue_grant(
                "peer-agent",
                "calc_tool",
                ToolPermission.READ,
                reason="seed peer precedent",
            )
            trust = TrustNetwork()
            for _ in range(50):
                trust.record_outcome("requester", True, intent_type="seed")
            tool_reg = _FakeToolRegistry(
                {"calc_tool": _FakeRegistration({"domain": "read"})}
            )
            ontology = _FakeOntology(
                {"requester": "science", "peer-agent": "science"}
            )
            cfg = CapabilityTriageConfig(
                grant_fast_path_enabled=True, grant_trust_floor=0.5
            )
            store.captured.clear()  # type: ignore[attr-defined]
            # Act
            req = await triage_and_file(
                gap_target="calc_tool",
                agent_id="requester",
                store=store,
                tool_registry=tool_reg,
                permission_store=perm,
                ontology=ontology,
                trust_network=trust,
                config=cfg,
            )
            # Assert
            assert req.kind == "grant"
            assert req.status == "fulfilled"
            fulfilled = [
                d
                for et, d in store.captured  # type: ignore[attr-defined]
                if et == EventType.CAPABILITY_REQUEST_FULFILLED
            ]
            assert fulfilled
            held = perm.get_active_grants_sync("requester", "calc_tool")
            assert any(not g.is_restriction for g in held)
        finally:
            await perm.stop()

    @pytest.mark.asyncio
    async def test_grant_left_pending_when_fast_path_disabled(self, tmp_path, store):
        # Arrange — registered tool, agent lacks permission, fast path OFF (default).
        perm = ToolPermissionStore(db_path=str(tmp_path / "perms2.db"))
        await perm.start()
        try:
            tool_reg = _FakeToolRegistry(
                {"calc_tool": _FakeRegistration({"domain": "read"})}
            )
            # Act — config None -> fast path defaults OFF
            req = await triage_and_file(
                gap_target="calc_tool",
                agent_id="requester",
                store=store,
                tool_registry=tool_reg,
                permission_store=perm,
            )
            # Assert
            assert req.kind == "grant"
            assert req.status == "pending"
        finally:
            await perm.stop()


# --------------------------------------------------------------------------- #
# Store: mark_fulfilled()
# --------------------------------------------------------------------------- #
class TestMarkFulfilled:
    @pytest.fixture
    async def store(self, tmp_path):
        captured: list[tuple] = []
        s = CapabilityRequestStore(
            db_path=str(tmp_path / "mf.db"),
            emit_event=lambda et, data: captured.append((et, data)),
        )
        await s.start()
        s.captured = captured  # type: ignore[attr-defined]
        yield s
        await s.stop()

    @pytest.mark.asyncio
    async def test_mark_fulfilled_sets_status_and_emits(self, store):
        # Arrange
        req = await store.file_request("agent-9", "install", "httpx")
        store.captured.clear()  # type: ignore[attr-defined]
        # Act
        updated = await store.mark_fulfilled(req.id)
        # Assert
        assert updated is not None
        assert updated.status == "fulfilled"
        assert (await store.get(req.id)).status == "fulfilled"
        assert any(
            et == EventType.CAPABILITY_REQUEST_FULFILLED
            for et, _ in store.captured  # type: ignore[attr-defined]
        )

    @pytest.mark.asyncio
    async def test_mark_fulfilled_unknown_id_returns_none(self, store):
        # Act / Assert
        assert await store.mark_fulfilled("does-not-exist") is None
