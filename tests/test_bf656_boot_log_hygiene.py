"""BF-656/BF-661: boot-log hygiene and safe skill recovery.

Part A — the AD-423a ontology seed no longer registers a no-op ``codebase_query``
placeholder that the real AD-544 native ``CodebaseQueryTool`` then legitimately
replaced (one ``Replacing existing tool registration: codebase_query`` per boot).
Part B — warm boot prunes only provably inert stubs. Invalid or mismatched
non-stub source is preserved behind a hash-keyed quarantine marker until its
source changes and validates.
"""

from __future__ import annotations

import hashlib
import inspect
import json
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
from probos.substrate.skill_agent import SkillBasedAgent
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.protocol import ToolType
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage, IntentResult, Skill
from probos.warm_boot import WarmBootService, _is_inert_skill_stub

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
# Part B — warm boot quarantines recoverable skills and prunes inert stubs
# ==================================================================


class TestWarmBootSkillRecoverySafety:
    @pytest.mark.parametrize(
        ("source_code", "expected"),
        [
            ("", True),
            ("  # comment only\n", True),
            ('"""module docstring"""\npass\n', True),
            ('pass\n"not a module docstring"\n', False),
            ("import json\n", False),
            ("value = 1\n", False),
            ("async def handle_other(intent, llm_client=None):\n    pass\n", False),
            ("if True print('broken')\n", False),
        ],
    )
    def test_inert_skill_stub_classification(
        self, source_code: str, expected: bool,
    ) -> None:
        assert _is_inert_skill_stub(source_code) is expected

    @pytest.mark.asyncio
    async def test_comment_only_stub_is_pruned_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill("nohandler", "# no handler\n", {"name": "nohandler"})

        with caplog.at_level(logging.INFO, logger="probos.warm_boot"):
            await service.restore()
            await service.restore()

        assert not (store.repo_path / "skills" / "nohandler.py").exists()
        assert not (store.repo_path / "skills" / "nohandler.json").exists()
        assert await store.load_skill_quarantine("nohandler") is None
        assert caplog.text.count("provably inert stable stub") == 1
        assert not any(
            record.levelno == logging.WARNING and "nohandler" in record.getMessage()
            for record in caplog.records
        )
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_mismatched_handler_is_preserved_and_quarantined(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = "async def handle_other(intent, llm_client=None):\n    return None\n"
        descriptor = '{"name":"wanted","description":"preserve exactly"}'
        skills_dir = store.repo_path / "skills"
        (skills_dir / "wanted.py").write_text(source, encoding="utf-8")
        (skills_dir / "wanted.json").write_text(descriptor, encoding="utf-8")
        source_bytes = (skills_dir / "wanted.py").read_bytes()
        descriptor_bytes = (skills_dir / "wanted.json").read_bytes()

        await service.restore()

        assert (skills_dir / "wanted.py").read_bytes() == source_bytes
        assert (skills_dir / "wanted.json").read_bytes() == descriptor_bytes
        marker = await store.load_skill_quarantine("wanted")
        assert marker is not None
        assert marker["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
        assert marker["reason"] == "skill_validation_failed"
        assert any("handle_wanted" in error for error in marker["errors"])
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matching_quarantine_skips_retry_without_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = "async def handle_other(intent, llm_client=None):\n    return None\n"
        await store.store_skill("wanted", source, {"name": "wanted"})
        await service.restore()

        from probos.cognitive.skill_validator import SkillValidator

        def _unexpected_validate(*args: object, **kwargs: object) -> list[str]:
            raise AssertionError("matching quarantine must skip validation")

        monkeypatch.setattr(SkillValidator, "validate", _unexpected_validate)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="probos.warm_boot"):
            await service.restore()

        assert "remains quarantined for the same stable source hash" in caplog.text
        assert not any(record.levelno >= logging.WARNING for record in caplog.records)
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_changed_source_revalidates_and_clears_quarantine_on_success(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "wanted",
            "async def handle_other(intent, llm_client=None):\n    return None\n",
            {"name": "wanted"},
        )
        await service.restore()
        assert await store.load_skill_quarantine("wanted") is not None

        exact_source = (
            "async def handle_wanted(intent, llm_client=None):\n"
            "    return None\n"
        )
        (store.repo_path / "skills" / "wanted.py").write_text(
            exact_source, encoding="utf-8",
        )
        await service.restore()

        add_skill_fn.assert_awaited_once()
        skill_obj = add_skill_fn.await_args.args[0]
        assert isinstance(skill_obj, Skill)
        assert skill_obj.name == "wanted"
        assert await store.load_skill_quarantine("wanted") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source",
        [
            "async def handle_broken_skill(:\n    return None\n",
            (
                "import definitely_not_a_real_module_bf661\n\n"
                "async def handle_broken_skill(intent, llm_client=None):\n"
                "    return None\n"
            ),
            (
                "async def handle_broken_skill(intent, llm_client=None):\n"
                "    return eval('1 + 1')\n"
            ),
        ],
    )
    async def test_syntax_or_import_failure_is_preserved_and_quarantined(
        self, tmp_path: Path, source: str,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        descriptor = {"name": "broken_skill", "params": {"value": "test"}}
        await store.store_skill("broken_skill", source, descriptor)

        await service.restore()

        skills_dir = store.repo_path / "skills"
        assert (skills_dir / "broken_skill.py").read_text(encoding="utf-8") == source
        assert json.loads(
            (skills_dir / "broken_skill.json").read_text(encoding="utf-8")
        ) == descriptor
        marker = await store.load_skill_quarantine("broken_skill")
        assert marker is not None
        assert marker["reason"] == "skill_validation_failed"
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_validation_failure_source_is_never_executed(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        sentinel = tmp_path / "must-not-exist"
        source = (
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed')\n\n"
            "async def handle_other(intent, llm_client=None):\n"
            "    return None\n"
        )
        await store.store_skill("wanted", source, {"name": "wanted"})

        await service.restore()

        assert not sentinel.exists()
        assert await store.load_skill_quarantine("wanted") is not None
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exact_async_valid_skill_still_restores(self, tmp_path: Path) -> None:
        previous_intents = set(SkillBasedAgent._handled_intents)
        previous_descriptors = list(SkillBasedAgent.intent_descriptors)
        llm_client = object()
        agent = SkillBasedAgent(pool="test", llm_client=llm_client)

        async def _attach(skill: Skill, *, persist: bool = True) -> None:
            assert persist is False
            agent.add_skill(skill)

        add_skill_fn = AsyncMock(side_effect=_attach)
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "valid_skill",
            (
                "async def handle_valid_skill(intent, llm_client=None):\n"
                "    from probos.types import IntentResult\n"
                "    return IntentResult(\n"
                "        intent_id=intent.id,\n"
                "        agent_id='restored-skill',\n"
                "        success=llm_client is not None,\n"
                "        result={'client_id': id(llm_client)},\n"
                "    )\n"
            ),
            {"name": "valid_skill"},
        )

        try:
            await service.restore()

            add_skill_fn.assert_awaited_once()
            skill_obj = add_skill_fn.await_args.args[0]
            assert isinstance(skill_obj, Skill)
            assert skill_obj.name == "valid_skill"
            assert skill_obj.handler is not None
            assert inspect.iscoroutinefunction(skill_obj.handler)
            intent = IntentMessage(intent="valid_skill", params={})
            result = await agent.handle_intent(intent)
            assert isinstance(result, IntentResult)
            assert result.success is True
            assert result.intent_id == intent.id
            assert result.result == {"client_id": id(llm_client)}
            assert add_skill_fn.await_args.kwargs == {"persist": False}
            assert (store.repo_path / "skills" / "valid_skill.py").is_file()
            assert (store.repo_path / "skills" / "valid_skill.json").is_file()
            assert await store.load_skill_quarantine("valid_skill") is None
        finally:
            SkillBasedAgent._handled_intents.clear()
            SkillBasedAgent._handled_intents.update(previous_intents)
            SkillBasedAgent.intent_descriptors[:] = previous_descriptors

    @pytest.mark.asyncio
    async def test_positional_only_llm_client_with_kwargs_is_quarantined(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = (
            "async def handle_wanted(intent, llm_client=None, /, **kwargs):\n"
            "    return None\n"
        )
        await store.store_skill("wanted", source, {"name": "wanted"})

        await service.restore()

        marker = await store.load_skill_quarantine("wanted")
        assert marker is not None
        assert marker["reason"] == "skill_validation_failed"
        assert any("positional-only llm_client" in error for error in marker["errors"])
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_restore_uses_source_then_atomic_final_reread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "wanted",
            "async def handle_wanted(intent, llm_client=None):\n    return None\n",
            {"name": "wanted"},
        )
        source_loader = AsyncMock(wraps=store.load_skill_source)
        state_loader = AsyncMock(wraps=store.load_skill_source_and_quarantine)
        monkeypatch.setattr(store, "load_skill_source", source_loader)
        monkeypatch.setattr(
            store, "load_skill_source_and_quarantine", state_loader,
        )

        await service.restore()

        assert source_loader.await_count == 1
        assert state_loader.await_count == 1
        add_skill_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stale_marker_restore_uses_source_then_atomic_final_reread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = (
            "async def handle_wanted(intent, llm_client=None):\n"
            "    return None\n"
        )
        await store.store_skill("wanted", source, {"name": "wanted"})
        old_source = "async def handle_other(intent, llm_client=None):\n    return None\n"
        old_hash = hashlib.sha256(old_source.encode()).hexdigest()
        marker_path = store.repo_path / "skill_quarantine" / "wanted.json"
        marker_path.write_text(
            json.dumps(
                {
                    "intent_name": "wanted",
                    "source_sha256": old_hash,
                    "reason": "skill_validation_failed",
                    "errors": ["old error"],
                    "timestamp": "2026-07-10T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        source_loader = AsyncMock(wraps=store.load_skill_source)
        state_loader = AsyncMock(wraps=store.load_skill_source_and_quarantine)
        monkeypatch.setattr(store, "load_skill_source", source_loader)
        monkeypatch.setattr(
            store, "load_skill_source_and_quarantine", state_loader,
        )

        await service.restore()

        assert source_loader.await_count == 1
        assert state_loader.await_count == 1
        add_skill_fn.assert_awaited_once()
        assert add_skill_fn.await_args.kwargs == {"persist": False}
        assert await store.load_skill_quarantine("wanted") is None

    @pytest.mark.asyncio
    async def test_matching_marker_published_during_final_state_read_blocks_attach(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = (
            "async def handle_wanted(intent, llm_client=None):\n"
            "    return None\n"
        )
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        await store.store_skill("wanted", source, {"name": "wanted"})
        marker_path = store.repo_path / "skill_quarantine" / "wanted.json"
        real_locked_source_load = store._load_skill_source_locked
        locked_source_reads = 0

        def _publish_marker_during_final_read(intent_name: str) -> str | None:
            nonlocal locked_source_reads
            loaded = real_locked_source_load(intent_name)
            locked_source_reads += 1
            if locked_source_reads == 2:
                marker_path.write_text(
                    json.dumps(
                        {
                            "intent_name": "wanted",
                            "source_sha256": source_hash,
                            "reason": "published_during_final_state_read",
                            "errors": [],
                            "timestamp": "2026-07-11T00:00:00+00:00",
                        }
                    ),
                    encoding="utf-8",
                )
            return loaded

        monkeypatch.setattr(
            store, "_load_skill_source_locked", _publish_marker_during_final_read,
        )

        await service.restore()

        assert locked_source_reads == 2
        add_skill_fn.assert_not_awaited()
        marker = await store.load_skill_quarantine("wanted")
        assert marker is not None
        assert marker["source_sha256"] == source_hash
        assert marker["reason"] == "published_during_final_state_read"

    @pytest.mark.asyncio
    async def test_allowed_import_execution_failure_is_preserved_and_quarantined(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = (
            "import json.missing_bf661\n\n"
            "async def handle_broken_skill(intent, llm_client=None):\n"
            "    return None\n"
        )
        descriptor = {"name": "broken_skill"}
        await store.store_skill("broken_skill", source, descriptor)

        await service.restore()

        assert (
            store.repo_path / "skills" / "broken_skill.py"
        ).read_text(encoding="utf-8") == source
        assert json.loads(
            (store.repo_path / "skills" / "broken_skill.json").read_text()
        ) == descriptor
        marker = await store.load_skill_quarantine("broken_skill")
        assert marker is not None
        assert marker["reason"] == "skill_source_load_failed"
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_quarantine_lookup_failure_preserves_without_attachment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "wanted",
            "async def handle_wanted(intent, llm_client=None):\n    return None\n",
            {"name": "wanted"},
        )

        async def _broken_quarantine_load(intent_name: str) -> dict:
            raise OSError(f"sidecar read failed for {intent_name}")

        monkeypatch.setattr(
            store, "load_skill_quarantine", _broken_quarantine_load,
        )
        await service.restore()

        assert await store.load_skill_source("wanted") is not None
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_descriptor_is_preserved_without_hash_quarantine(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source = (
            "async def handle_wanted(intent, llm_client=None):\n"
            "    return None\n"
        )
        descriptor = ["invalid-descriptor-shape"]
        await store.store_skill("wanted", source, descriptor)

        await service.restore()

        assert (
            store.repo_path / "skills" / "wanted.py"
        ).read_text(encoding="utf-8") == source
        assert json.loads(
            (store.repo_path / "skills" / "wanted.json").read_text()
        ) == descriptor
        assert await store.load_skill_quarantine("wanted") is None
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attachment_failure_is_retryable_without_source_change(
        self, tmp_path: Path,
    ) -> None:
        add_skill_fn = AsyncMock(side_effect=[RuntimeError("temporary"), None])
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill(
            "wanted",
            "async def handle_wanted(intent, llm_client=None):\n    return None\n",
            {"name": "wanted"},
        )

        await service.restore()
        assert await store.load_skill_quarantine("wanted") is None
        await service.restore()

        assert add_skill_fn.await_count == 2
        assert await store.load_skill_quarantine("wanted") is None

    @pytest.mark.asyncio
    async def test_source_change_before_matching_marker_skip_revalidates_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        invalid = "async def handle_other(intent, llm_client=None):\n    return None\n"
        repaired = "async def handle_wanted(intent, llm_client=None):\n    return None\n"
        await store.store_skill("wanted", invalid, {"name": "wanted"})
        invalid_hash = hashlib.sha256(invalid.encode()).hexdigest()
        await store.quarantine_skill(
            "wanted", source_code=invalid, expected_source_sha256=invalid_hash,
            reason="invalid", errors=[],
        )
        real_marker_load = store.load_skill_quarantine
        changed = False

        async def _marker_then_repair(intent_name: str) -> dict | None:
            nonlocal changed
            marker = await real_marker_load(intent_name)
            if not changed:
                changed = True
                await store.store_skill("wanted", repaired, {"name": "wanted"})
            return marker

        monkeypatch.setattr(store, "load_skill_quarantine", _marker_then_repair)

        await service.restore()

        add_skill_fn.assert_awaited_once()
        assert add_skill_fn.await_args.args[0].source_code == repaired

    @pytest.mark.asyncio
    async def test_source_change_before_quarantine_prevents_old_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        invalid_a = "async def handle_other(intent, llm_client=None):\n    return 'a'\n"
        invalid_b = "async def handle_other(intent, llm_client=None):\n    return 'b'\n"
        await store.store_skill("wanted", invalid_a, {"name": "wanted"})
        real_source_load = store.load_skill_source
        reads = 0

        async def _change_on_pre_quarantine(intent_name: str) -> str | None:
            nonlocal reads
            reads += 1
            if reads == 1:
                await store.store_skill("wanted", invalid_b, {"name": "wanted"})
            return await real_source_load(intent_name)

        monkeypatch.setattr(store, "load_skill_source", _change_on_pre_quarantine)

        await service.restore()

        marker = await store.load_skill_quarantine("wanted")
        assert marker is not None
        assert marker["source_sha256"] == hashlib.sha256(invalid_b.encode()).hexdigest()
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_source_change_before_inert_prune_does_not_delete_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        inert = "# inert\n"
        repaired = "async def handle_wanted(intent, llm_client=None):\n    return None\n"
        await store.store_skill("wanted", inert, {"name": "wanted"})
        real_source_load = store.load_skill_source
        changed = False

        async def _change_before_prune(intent_name: str) -> str | None:
            nonlocal changed
            if not changed:
                changed = True
                await store.store_skill("wanted", repaired, {"name": "wanted"})
            return await real_source_load(intent_name)

        monkeypatch.setattr(store, "load_skill_source", _change_before_prune)

        await service.restore()

        assert await store.load_skill_source("wanted") == repaired
        add_skill_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_source_change_after_import_prevents_old_handler_attachment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        source_a = "async def handle_wanted(intent, llm_client=None):\n    return 'a'\n"
        source_b = "async def handle_wanted(intent, llm_client=None):\n    return 'b'\n"
        await store.store_skill("wanted", source_a, {"name": "wanted"})
        real_loader = service._load_skill_handler
        loaded = False

        def _load_then_change(intent_name: str, source_code: str):
            nonlocal loaded
            handler = real_loader(intent_name, source_code)
            if not loaded:
                loaded = True
                source_path = store.repo_path / "skills" / "wanted.py"
                source_path.write_text(source_b, encoding="utf-8")
            return handler

        monkeypatch.setattr(service, "_load_skill_handler", _load_then_change)

        await service.restore()

        add_skill_fn.assert_not_awaited()
        assert (store.repo_path / "skills" / "wanted.py").read_text(
            encoding="utf-8",
        ) == source_b

    @pytest.mark.asyncio
    async def test_three_unstable_snapshots_exhaust_without_action(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        sources = [
            f"async def handle_other(intent, llm_client=None):\n    return {index}\n"
            for index in range(20)
        ]
        await store.store_skill("wanted", sources[0], {"name": "wanted"})
        real_source_load = store.load_skill_source
        reads = 0

        async def _always_change(_intent_name: str) -> str:
            nonlocal reads
            reads += 1
            next_source = sources[reads]
            (store.repo_path / "skills" / "wanted.py").write_text(
                next_source, encoding="utf-8",
            )
            loaded = await real_source_load("wanted")
            assert loaded is not None
            return loaded

        source_loader = AsyncMock(side_effect=_always_change)
        monkeypatch.setattr(store, "load_skill_source", source_loader)

        with caplog.at_level(logging.WARNING, logger="probos.warm_boot"):
            await service.restore()

        assert source_loader.await_count == 2
        assert "initial candidate plus two public source rereads" in caplog.text
        assert await store.load_skill_quarantine("wanted") is None
        assert (store.repo_path / "skills" / "wanted.py").exists()
        add_skill_fn.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "source",
        [
            (
                "def sync_decorator(func):\n"
                "    def wrapper(intent, llm_client=None):\n"
                "        return None\n"
                "    return wrapper\n\n"
                "@sync_decorator\n"
                "async def handle_wanted(intent, llm_client=None):\n"
                "    return None\n"
            ),
            (
                "async def handle_wanted(intent, llm_client=None):\n"
                "    return None\n\n"
                "async def replacement(*, intent, llm_client=None):\n"
                "    return None\n\n"
                "handle_wanted = replacement\n"
            ),
        ],
    )
    async def test_loaded_sync_or_bind_incompatible_handler_quarantined(
        self, tmp_path: Path, source: str,
    ) -> None:
        add_skill_fn = AsyncMock()
        service, store = _make_warm_boot(tmp_path, add_skill_fn)
        await store.initialize()
        await store.store_skill("wanted", source, {"name": "wanted"})

        await service.restore()

        marker = await store.load_skill_quarantine("wanted")
        assert marker is not None
        assert marker["reason"] == "skill_handler_runtime_contract_failed"
        add_skill_fn.assert_not_awaited()
