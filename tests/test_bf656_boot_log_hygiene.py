"""BF-656: boot-log hygiene — eliminate two benign-but-recurring boot WARNINGs.

Part A — the AD-423a ontology seed no longer registers a no-op ``codebase_query``
placeholder that the real AD-544 native ``CodebaseQueryTool`` then legitimately
replaced (one ``Replacing existing tool registration: codebase_query`` per boot).
Part B — warm boot now prunes a *definitively* un-restorable skill (source that
exec's fine but has no ``handle_<name>`` function — a PERMANENT condition) instead
of re-warning ``no handler function for skill …`` on every boot.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.swe_harness.tools import CodebaseQueryTool
from probos.config import KnowledgeConfig, SystemConfig
from probos.knowledge.store import KnowledgeStore
from probos.ontology import VesselOntologyService
from probos.startup.communication import _noop_handler
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.protocol import ToolType
from probos.tools.registry import ToolRegistry
from probos.types import Skill
from probos.warm_boot import WarmBootService

# ------------------------------------------------------------------
# Fixtures / helpers
# ------------------------------------------------------------------

ONTOLOGY_SRC = Path(__file__).resolve().parent.parent / "config" / "ontology"


@pytest.fixture()
def ontology_dir(tmp_path: Path) -> Path:
    """Copy the real YAML schemas into a temp dir for test isolation."""
    dest = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_SRC, dest)
    return dest


@pytest.fixture()
async def service(ontology_dir: Path, tmp_path: Path) -> VesselOntologyService:
    svc = VesselOntologyService(ontology_dir, data_dir=tmp_path / "data")
    await svc.initialize()
    return svc


class _StubTool:
    """Minimal Tool protocol implementation for registry fixtures."""

    def __init__(
        self,
        tool_id: str,
        *,
        name: str = "Stub",
        tool_type: ToolType = ToolType.INFRA_SERVICE,
        description: str = "stub",
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description


def _stub_runtime() -> SimpleNamespace:
    """Minimal runtime stand-in for CodebaseQueryTool construction (mirrors AD-544 tests)."""
    return SimpleNamespace(
        codebase_index=SimpleNamespace(
            query=lambda c: {"matches": [c]},
            find_callers=lambda n, max_results=10: [{"name": n}],
            find_tests_for=lambda p: [f"tests/test_{Path(p).stem}.py"],
            get_imports=lambda p: ["os", "sys"],
        ),
        spawner=SimpleNamespace(list_pools=lambda: ["filesystem"]),
        registry=SimpleNamespace(all=lambda: []),
    )


def _make_warm_boot(
    tmp_path: Path, add_skill_fn: AsyncMock,
) -> tuple[WarmBootService, KnowledgeStore]:
    """Build a WarmBootService backed by a real KnowledgeStore on tmp_path.

    Only the skills restore step is exercised; the other load_* steps hit an
    empty fresh store and are no-ops. auto_commit=False keeps git out of tests.
    """
    kcfg = KnowledgeConfig(
        enabled=True, repo_path=str(tmp_path / "knowledge"), auto_commit=False,
    )
    store = KnowledgeStore(kcfg)
    config = SystemConfig()
    config.self_mod.enabled = True  # skills restore is gated on this
    service = WarmBootService(
        knowledge_store=store,
        trust_network=SimpleNamespace(),
        hebbian_router=SimpleNamespace(),
        episodic_memory=None,
        workflow_cache=None,
        config=config,
        register_designed_agent_fn=AsyncMock(),
        create_designed_pool_fn=AsyncMock(),
        add_skill_to_agents_fn=add_skill_fn,
        qa_reports={},
        pools={},
    )
    return service, store


# ==================================================================
# Part A — codebase_query no longer collides at boot
# ==================================================================


class TestCodebaseQueryNoBootWarning:
    @pytest.mark.asyncio
    async def test_ontology_no_longer_exposes_codebase_query(
        self, service: VesselOntologyService,
    ) -> None:
        # #A1: the collision source is gone from the ontology taxonomy.
        caps = service.get_tool_capabilities()
        assert all(c.id != "codebase_query" for c in caps)
        assert len(caps) == 6

    def test_native_codebase_query_tool_preserves_access(self) -> None:
        # #A2: the real AD-544 native tool still owns the id (access preserved).
        tool = CodebaseQueryTool(_stub_runtime())
        assert tool.tool_id == "codebase_query"

    def test_registry_replace_guard_still_warns_for_real_dupes(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # #A3 (GUARD): the accidental-collision warning is fully intact.
        registry = ToolRegistry()
        with caplog.at_level(logging.WARNING):
            registry.register(_StubTool("dupe_id"))
            registry.register(_StubTool("dupe_id"))
        assert "Replacing existing tool registration: dupe_id" in caplog.text

    @pytest.mark.asyncio
    async def test_seeding_ontology_then_registering_codebase_query_does_not_warn(
        self, service: VesselOntologyService, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # #A4 (HEADLINE): seed the registry exactly as the AD-423a loop does, then
        # register the real codebase_query tool — no collision warning must fire.
        registry = ToolRegistry()
        type_map = {
            "ship_computer": ToolType.INFRA_SERVICE,
            "ward_room": ToolType.COMMUNICATION,
            "dreaming_engine": ToolType.INFRA_SERVICE,
        }
        with caplog.at_level(logging.WARNING):
            for tc in service.get_tool_capabilities():
                adapter = DirectServiceAdapter(
                    tool_id=tc.id,
                    name=tc.name,
                    description=tc.description,
                    handler=_noop_handler,
                    tool_type=type_map.get(tc.provider, ToolType.INFRA_SERVICE),
                )
                registry.register(adapter, provider=tc.provider, tags=[tc.id, tc.provider])
            # AD-544 registers the real native tool for the same id at boot.
            registry.register(_StubTool("codebase_query"))
        assert "Replacing existing tool registration: codebase_query" not in caplog.text


# ==================================================================
# Part B — warm boot prunes a definitively un-restorable skill
# ==================================================================


class TestUnrestorableSkillPruned:
    @pytest.mark.asyncio
    async def test_remove_skill_deletes_files_and_commits(self, tmp_path: Path) -> None:
        # #B5: the new KnowledgeStore.remove_skill mirrors remove_agent —
        # deletes .py + .json and schedules a removal commit.
        kcfg = KnowledgeConfig(
            enabled=True, repo_path=str(tmp_path / "knowledge"), auto_commit=False,
        )
        store = KnowledgeStore(kcfg)
        await store.initialize()
        await store.store_skill("gone", "# x\n", {"name": "gone"})
        assert (store.repo_path / "skills" / "gone.py").is_file()
        assert (store.repo_path / "skills" / "gone.json").is_file()

        commit_msgs: list[str] = []

        async def _spy_commit(message: str) -> None:
            commit_msgs.append(message)

        store._schedule_commit = _spy_commit  # type: ignore[method-assign]
        await store.remove_skill("gone")

        assert not (store.repo_path / "skills" / "gone.py").exists()
        assert not (store.repo_path / "skills" / "gone.json").exists()
        assert commit_msgs == ["Remove skill gone"]

    @pytest.mark.asyncio
    async def test_no_handler_skill_is_pruned_and_not_re_warned(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # #B6 (HEADLINE): a no-handler skill is pruned + INFO logged; the old
        # "no handler function" WARNING no longer fires.
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill("nohandler", "# no handler\n", {"name": "nohandler"})

        pruned: list[str] = []
        _orig_remove = store.remove_skill

        async def _spy_remove(intent_name: str) -> None:
            pruned.append(intent_name)
            await _orig_remove(intent_name)

        store.remove_skill = _spy_remove  # type: ignore[method-assign]

        with caplog.at_level(logging.INFO):
            await service.restore()

        assert "nohandler" in pruned
        assert not (store.repo_path / "skills" / "nohandler.py").exists()
        assert not (store.repo_path / "skills" / "nohandler.json").exists()
        assert "pruning from knowledge store" in caplog.text
        assert "nohandler" in caplog.text
        assert "no handler function" not in caplog.text  # old WARNING removed

    @pytest.mark.asyncio
    async def test_valid_skill_restores_and_is_not_pruned(self, tmp_path: Path) -> None:
        # #B7: a valid skill still restores (attached to agents) and is NOT pruned.
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "valid_skill",
            "def handle_valid_skill(**k):\n    return 'ok'\n",
            {"name": "valid_skill"},
        )

        pruned: list[str] = []
        _orig_remove = store.remove_skill

        async def _spy_remove(intent_name: str) -> None:
            pruned.append(intent_name)
            await _orig_remove(intent_name)

        store.remove_skill = _spy_remove  # type: ignore[method-assign]

        await service.restore()

        add_skill_fn.assert_awaited_once()
        skill_obj = add_skill_fn.await_args.args[0]
        assert isinstance(skill_obj, Skill)
        assert skill_obj.name == "valid_skill"
        assert "valid_skill" not in pruned
        assert (store.repo_path / "skills" / "valid_skill.py").is_file()
        assert (store.repo_path / "skills" / "valid_skill.json").is_file()

    @pytest.mark.asyncio
    async def test_transient_exec_error_skill_is_not_pruned(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # #B8 (SAFETY): a transient exec failure (ImportError) hits the OUTER
        # except — it must NOT be pruned and must still log "restore failed".
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "broken_skill",
            "import definitely_not_a_real_module_bf656\n",
            {"name": "broken_skill"},
        )

        pruned: list[str] = []
        _orig_remove = store.remove_skill

        async def _spy_remove(intent_name: str) -> None:
            pruned.append(intent_name)
            await _orig_remove(intent_name)

        store.remove_skill = _spy_remove  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await service.restore()

        assert "broken_skill" not in pruned
        assert (store.repo_path / "skills" / "broken_skill.py").is_file()
        assert (store.repo_path / "skills" / "broken_skill.json").is_file()
        assert "skill broken_skill restore failed" in caplog.text
