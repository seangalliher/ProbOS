"""AD-429c: Operations, Communication & Resources ontology domain tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from probos.ontology import VesselOntologyService

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

ONTOLOGY_SRC = Path(__file__).resolve().parent.parent / "config" / "ontology"


@pytest.fixture()
def ontology_dir(tmp_path: Path) -> Path:
    """Copy YAML schemas into a temp dir for test isolation."""
    dest = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_SRC, dest)
    return dest


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
async def service(ontology_dir: Path, data_dir: Path) -> VesselOntologyService:
    svc = VesselOntologyService(ontology_dir, data_dir=data_dir)
    await svc.initialize()
    return svc


# ==================================================================
# Operations domain (8 tests)
# ==================================================================

class TestOperationsSchemaLoading:
    @pytest.mark.asyncio
    async def test_load_operations_yaml(self, service: VesselOntologyService) -> None:
        """operations.yaml parses successfully."""
        assert len(service.get_standing_order_tiers()) > 0
        assert len(service.get_watch_types()) > 0
        assert service.get_alert_procedure("GREEN") is not None
        assert len(service.get_duty_categories()) > 0


class TestStandingOrderTiers:
    @pytest.mark.asyncio
    async def test_seven_tiers_loaded(self, service: VesselOntologyService) -> None:
        tiers = service.get_standing_order_tiers()
        assert len(tiers) == 7
        tier_numbers = sorted(t.tier for t in tiers)
        assert tier_numbers == [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]

    @pytest.mark.asyncio
    async def test_tier_mutability(self, service: VesselOntologyService) -> None:
        tiers = service.get_standing_order_tiers()
        immutable = [t for t in tiers if not t.mutable]
        mutable = [t for t in tiers if t.mutable]
        assert sorted(t.tier for t in immutable) == [1.0, 1.5, 2.0]
        assert sorted(t.tier for t in mutable) == [3.0, 4.0, 5.0, 6.0]


class TestWatchTypes:
    @pytest.mark.asyncio
    async def test_three_watch_types(self, service: VesselOntologyService) -> None:
        wt = service.get_watch_types()
        assert len(wt) == 3
        ids = {w.id for w in wt}
        assert ids == {"alpha", "beta", "gamma"}


class TestAlertProcedures:
    @pytest.mark.asyncio
    async def test_green_procedure(self, service: VesselOntologyService) -> None:
        proc = service.get_alert_procedure("GREEN")
        assert proc is not None
        assert proc.description == "Normal operations"
        assert proc.watch_default == "alpha"
        assert proc.actions == []

    @pytest.mark.asyncio
    async def test_red_procedure_has_actions(self, service: VesselOntologyService) -> None:
        proc = service.get_alert_procedure("RED")
        assert proc is not None
        assert len(proc.actions) == 4

    @pytest.mark.asyncio
    async def test_unknown_procedure(self, service: VesselOntologyService) -> None:
        assert service.get_alert_procedure("BLUE") is None


class TestDutyCategories:
    @pytest.mark.asyncio
    async def test_four_categories(self, service: VesselOntologyService) -> None:
        cats = service.get_duty_categories()
        assert len(cats) == 4
        ids = {c.id for c in cats}
        assert ids == {"monitoring", "analysis", "reporting", "maintenance"}


# ==================================================================
# Communication domain (7 tests)
# ==================================================================

class TestCommunicationSchemaLoading:
    @pytest.mark.asyncio
    async def test_load_communication_yaml(self, service: VesselOntologyService) -> None:
        assert len(service.get_channel_types()) > 0
        assert len(service.get_thread_modes()) > 0
        assert len(service.get_message_patterns()) > 0


class TestChannelTypes:
    @pytest.mark.asyncio
    async def test_four_channel_types(self, service: VesselOntologyService) -> None:
        ct = service.get_channel_types()
        assert len(ct) == 4
        ids = {c.id for c in ct}
        assert ids == {"ship", "department", "dm", "custom"}


class TestThreadModes:
    @pytest.mark.asyncio
    async def test_four_thread_modes(self, service: VesselOntologyService) -> None:
        tm = service.get_thread_modes()
        assert len(tm) == 4
        ids = {t.id for t in tm}
        assert ids == {"inform", "discuss", "action", "announce"}

    @pytest.mark.asyncio
    async def test_thread_mode_query(self, service: VesselOntologyService) -> None:
        discuss = service.get_thread_mode("discuss")
        assert discuss is not None
        assert discuss.reply_expected is True
        assert discuss.routing == "department_preference"

    @pytest.mark.asyncio
    async def test_thread_mode_unknown(self, service: VesselOntologyService) -> None:
        assert service.get_thread_mode("debate") is None


class TestMessagePatterns:
    @pytest.mark.asyncio
    async def test_at_least_five_patterns(self, service: VesselOntologyService) -> None:
        mp = service.get_message_patterns()
        assert len(mp) >= 5

    @pytest.mark.asyncio
    async def test_min_rank_on_structured_actions(self, service: VesselOntologyService) -> None:
        mp = service.get_message_patterns()
        ranked = [p for p in mp if p.min_rank is not None]
        assert len(ranked) >= 2
        for p in ranked:
            assert p.min_rank == "lieutenant"


# ==================================================================
# Resources domain (7 tests)
# ==================================================================

class TestResourcesSchemaLoading:
    @pytest.mark.asyncio
    async def test_load_resources_yaml(self, service: VesselOntologyService) -> None:
        assert len(service.get_model_tiers()) > 0
        assert len(service.get_tool_capabilities()) > 0
        assert len(service.get_knowledge_sources()) > 0


class TestModelTiers:
    @pytest.mark.asyncio
    async def test_three_model_tiers(self, service: VesselOntologyService) -> None:
        mt = service.get_model_tiers()
        assert len(mt) == 3
        ids = {m.id for m in mt}
        assert ids == {"fast", "standard", "deep"}

    @pytest.mark.asyncio
    async def test_model_tier_query(self, service: VesselOntologyService) -> None:
        fast = service.get_model_tier("fast")
        assert fast is not None
        assert fast.default_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_model_tier_unknown(self, service: VesselOntologyService) -> None:
        assert service.get_model_tier("extreme") is None


class TestToolCapabilities:
    @pytest.mark.asyncio
    async def test_all_capabilities(self, service: VesselOntologyService) -> None:
        tc = service.get_tool_capabilities()
        assert len(tc) >= 7

    @pytest.mark.asyncio
    async def test_filtered_capabilities(self, service: VesselOntologyService) -> None:
        all_crew = service.get_tool_capabilities(available_to="all_crew")
        lt_plus = service.get_tool_capabilities(available_to="lieutenant_plus")
        assert len(all_crew) >= 4
        assert len(lt_plus) >= 2
        assert len(all_crew) + len(lt_plus) == len(service.get_tool_capabilities())


class TestKnowledgeSources:
    @pytest.mark.asyncio
    async def test_three_knowledge_sources(self, service: VesselOntologyService) -> None:
        ks = service.get_knowledge_sources()
        assert len(ks) == 3
        tiers = sorted(k.tier for k in ks)
        assert tiers == [1, 2, 3]


# ==================================================================
# Integration (3 tests)
# ==================================================================

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_initialize_loads_all_domains(self, service: VesselOntologyService) -> None:
        """All domain counts > 0 after full initialization."""
        assert len(service.get_departments()) > 0
        assert len(service.get_posts()) > 0
        assert len(service.get_standing_order_tiers()) > 0
        assert len(service.get_channel_types()) > 0
        assert len(service.get_model_tiers()) > 0

    @pytest.mark.asyncio
    async def test_crew_context_includes_alert_info(self, service: VesselOntologyService) -> None:
        ctx = service.get_crew_context("architect")
        assert ctx is not None
        assert "alert_condition" in ctx
        assert ctx["alert_condition"] == "GREEN"
        assert "alert_procedure" in ctx
        assert ctx["alert_procedure"] == "Normal operations"

    @pytest.mark.asyncio
    async def test_crew_context_includes_available_actions(self, service: VesselOntologyService) -> None:
        ctx = service.get_crew_context("architect")
        assert ctx is not None
        assert "available_actions" in ctx
        actions = ctx["available_actions"]
        assert isinstance(actions, list)
        assert len(actions) >= 3  # observation, proposal, no_response (no min_rank)
        tags = [a["tag"] for a in actions]
        assert "[Observation]" in tags
        assert "[Proposal]" in tags
