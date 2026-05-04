"""AD-507 Crew Development Framework v1 — Core Knowledge Curriculum Registry."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import CrewDevelopmentConfig, SystemConfig
from probos.crew_development import (
    CoreKnowledgeCurriculumRegistry,
    CurriculumModule,
)
from probos.events import EventType
from probos.startup.finalize import _wire_curriculum_registry


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


# ---------------------------------------------------------------------------
# Section 0 — EventType
# ---------------------------------------------------------------------------


def test_event_type_curriculum_module_queried_exists() -> None:
    assert EventType.CURRICULUM_MODULE_QUERIED.value == "curriculum_module_queried"


# ---------------------------------------------------------------------------
# Section 4 — Pydantic config defaults
# ---------------------------------------------------------------------------


def test_crew_development_config_defaults() -> None:
    cfg = CrewDevelopmentConfig()
    assert cfg.enabled is True

    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.crew_development, CrewDevelopmentConfig)
    assert sys_cfg.crew_development.enabled is True


# ---------------------------------------------------------------------------
# Section 2 — CurriculumModule dataclass
# ---------------------------------------------------------------------------


def test_curriculum_module_is_frozen_dataclass() -> None:
    module = CurriculumModule(
        module_id="x",
        title="X",
        category="identity",
        summary="s",
        learning_objectives=("a",),
        delivery_phase="orientation",
    )
    assert dataclasses.is_dataclass(module)
    params = getattr(CurriculumModule, "__dataclass_params__", None)
    assert params is not None and params.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        module.title = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 3 — Registry behavior
# ---------------------------------------------------------------------------


def test_registry_seeds_9_default_modules() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    modules = registry.list_modules()
    assert len(modules) == 9
    ids = {m.module_id for m in modules}
    assert ids == {
        "identity_grounding",
        "chain_of_command",
        "ward_room_protocol",
        "dm_etiquette",
        "notebook_discipline",
        "episodic_vs_llm",
        "trust_mechanics",
        "ethics_boundaries",
        "self_regulation",
    }
    categories = {m.category for m in modules}
    assert categories == {
        "identity",
        "communication",
        "memory",
        "trust",
        "ethics",
        "self_regulation",
    }


def test_get_module_returns_module_or_none() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    hit = registry.get_module("identity_grounding")
    assert hit is not None
    assert hit.title == "Identity & DID"
    assert registry.get_module("does_not_exist") is None


def test_get_module_emits_event_on_hit() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    emitter = _CollectingEmitter()
    registry.emit_event = emitter

    registry.get_module("identity_grounding")
    registry.get_module("does_not_exist")

    assert len(emitter.events) == 1
    event_type, payload = emitter.events[0]
    assert event_type is EventType.CURRICULUM_MODULE_QUERIED
    assert payload == {"module_id": "identity_grounding", "query_type": "by_id"}


def test_list_by_category_filters() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    emitter = _CollectingEmitter()
    registry.emit_event = emitter

    identity_modules = registry.list_by_category("identity")
    assert {m.module_id for m in identity_modules} == {
        "identity_grounding",
        "chain_of_command",
    }

    empty = registry.list_by_category("nonexistent")
    assert empty == ()

    assert len(emitter.events) == 1
    _, payload = emitter.events[0]
    assert payload["query_type"] == "by_category:identity"


def test_list_by_phase_filters() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    emitter = _CollectingEmitter()
    registry.emit_event = emitter

    orientation = registry.list_by_phase("orientation")
    assert {m.module_id for m in orientation} == {
        "identity_grounding",
        "chain_of_command",
        "ethics_boundaries",
    }
    empty = registry.list_by_phase("nonexistent")
    assert empty == ()

    assert len(emitter.events) == 1
    _, payload = emitter.events[0]
    assert payload["query_type"] == "by_phase:orientation"


def test_register_module_overwrites_existing_id() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    replacement = CurriculumModule(
        module_id="identity_grounding",
        title="Replaced",
        category="identity",
        summary="overwritten",
        learning_objectives=("z",),
        delivery_phase="orientation",
    )
    registry.register_module(replacement)
    hit = registry.get_module("identity_grounding")
    assert hit is not None
    assert hit.title == "Replaced"
    # Total module count unchanged (overwrite, not append)
    assert len(registry.list_modules()) == 9


# ---------------------------------------------------------------------------
# Section 5 — Runtime wiring
# ---------------------------------------------------------------------------


def test_runtime_attribute_set_when_enabled() -> None:
    runtime = MagicMock(spec=["emit_event", "curriculum_registry"])
    config = SimpleNamespace(crew_development=CrewDevelopmentConfig(enabled=True))
    wired = _wire_curriculum_registry(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.curriculum_registry, CoreKnowledgeCurriculumRegistry)
    assert len(runtime.curriculum_registry.list_modules()) == 9


def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(crew_development=CrewDevelopmentConfig(enabled=False))
    wired = _wire_curriculum_registry(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "curriculum_registry")
