"""AD-429d: Records ontology domain tests."""

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
# Records domain (16 tests)
# ==================================================================

class TestRecordsSchemaLoading:
    @pytest.mark.asyncio
    async def test_load_records_yaml(self, service: VesselOntologyService) -> None:
        """records.yaml parses successfully."""
        assert len(service.get_knowledge_tiers()) > 0
        assert len(service.get_classifications()) > 0
        assert len(service.get_document_classes()) > 0
        assert len(service.get_retention_policies()) > 0


class TestKnowledgeTiers:
    @pytest.mark.asyncio
    async def test_three_tiers(self, service: VesselOntologyService) -> None:
        tiers = service.get_knowledge_tiers()
        assert len(tiers) == 3
        tier_numbers = sorted(kt.tier for kt in tiers)
        assert tier_numbers == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_knowledge_tier_query(self, service: VesselOntologyService) -> None:
        kt = service.get_knowledge_tier(2)
        assert kt is not None
        assert kt.name == "Records"
        assert kt.access == "all_crew"

    @pytest.mark.asyncio
    async def test_knowledge_tier_unknown(self, service: VesselOntologyService) -> None:
        assert service.get_knowledge_tier(99) is None


class TestClassifications:
    @pytest.mark.asyncio
    async def test_four_classifications(self, service: VesselOntologyService) -> None:
        cls = service.get_classifications()
        assert len(cls) == 4
        ids = {c.id for c in cls}
        assert ids == {"private", "department", "ship", "fleet"}


class TestDocumentClasses:
    @pytest.mark.asyncio
    async def test_six_document_classes(self, service: VesselOntologyService) -> None:
        dcs = service.get_document_classes()
        assert len(dcs) == 6
        ids = {dc.id for dc in dcs}
        assert ids == {"captains_log", "notebook", "report", "duty_log", "operations", "manual"}

    @pytest.mark.asyncio
    async def test_document_class_query(self, service: VesselOntologyService) -> None:
        dc = service.get_document_class("captains_log")
        assert dc is not None
        assert dc.name == "Captain's Log"

    @pytest.mark.asyncio
    async def test_document_class_unknown(self, service: VesselOntologyService) -> None:
        assert service.get_document_class("blog_post") is None

    @pytest.mark.asyncio
    async def test_captains_log_rules(self, service: VesselOntologyService) -> None:
        dc = service.get_document_class("captains_log")
        assert dc is not None
        assert dc.classification_default == "ship"
        assert dc.retention == "permanent"
        assert any("Append-only" in rule for rule in dc.special_rules)

    @pytest.mark.asyncio
    async def test_notebook_defaults(self, service: VesselOntologyService) -> None:
        dc = service.get_document_class("notebook")
        assert dc is not None
        assert dc.classification_default == "private"
        assert dc.retention == "archive_90_days"


class TestRetentionPolicies:
    @pytest.mark.asyncio
    async def test_four_retention_policies(self, service: VesselOntologyService) -> None:
        rps = service.get_retention_policies()
        assert len(rps) == 4

    @pytest.mark.asyncio
    async def test_permanent_policy(self, service: VesselOntologyService) -> None:
        rp = service.get_retention_policy("permanent")
        assert rp is not None
        assert rp.archive_after_days is None
        assert rp.delete_after_days is None

    @pytest.mark.asyncio
    async def test_retention_policy_unknown(self, service: VesselOntologyService) -> None:
        assert service.get_retention_policy("immediate") is None

    @pytest.mark.asyncio
    async def test_archive_90_days(self, service: VesselOntologyService) -> None:
        rp = service.get_retention_policy("archive_90_days")
        assert rp is not None
        assert rp.archive_after_days == 90


class TestRepositoryStructure:
    @pytest.mark.asyncio
    async def test_seven_directories(self, service: VesselOntologyService) -> None:
        dirs = service.get_repository_structure()
        assert len(dirs) == 7


class TestCrewContextRecords:
    @pytest.mark.asyncio
    async def test_crew_context_includes_knowledge_model(self, service: VesselOntologyService) -> None:
        ctx = service.get_crew_context("architect")
        assert ctx is not None
        assert "knowledge_model" in ctx
        km = ctx["knowledge_model"]
        assert len(km["tiers"]) == 3
        assert "note" in km
        tier_names = [t["name"] for t in km["tiers"]]
        assert "Experience" in tier_names
        assert "Records" in tier_names
        assert "Operational State" in tier_names
