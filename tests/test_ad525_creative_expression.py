"""AD-525 Creative Expression v1 — Skills Inventory + Records Output."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import CreativeExpressionConfig, SystemConfig
from probos.creative.output_writer import CreativeOutputError, CreativeOutputWriter
from probos.creative.skills_registry import CreativeSkill, CreativeSkillsRegistry
from probos.crew_profile import PersonalityTraits
from probos.events import EventType
from probos.startup.finalize import _wire_creative_expression


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRecordsStore:
    """Minimal records-store stub capturing write_entry kwargs."""

    def __init__(self, repo_path=None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.repo_path = repo_path

    async def write_entry(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return kwargs["path"]


class _ExplodingRecordsStore:
    """Records-store stub whose write_entry always raises."""

    def __init__(self) -> None:
        self.repo_path = None

    async def write_entry(self, **kwargs: Any) -> str:
        raise RuntimeError("disk full")


class _CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


# ---------------------------------------------------------------------------
# Section 0 — EventTypes
# ---------------------------------------------------------------------------


def test_event_type_creative_work_published_exists() -> None:
    assert EventType.CREATIVE_WORK_PUBLISHED.value == "creative_work_published"


def test_event_type_creative_skill_affinity_queried_exists() -> None:
    assert EventType.CREATIVE_SKILL_AFFINITY_QUERIED.value == "creative_skill_affinity_queried"


# ---------------------------------------------------------------------------
# Section 5 — Pydantic config defaults
# ---------------------------------------------------------------------------


def test_creative_expression_config_defaults() -> None:
    cfg = CreativeExpressionConfig()
    assert cfg.enabled is True
    assert cfg.default_classification == "ship"

    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.creative_expression, CreativeExpressionConfig)
    assert sys_cfg.creative_expression.enabled is True


# ---------------------------------------------------------------------------
# Section 2 — CreativeSkill dataclass
# ---------------------------------------------------------------------------


def test_creative_skill_is_frozen_dataclass() -> None:
    skill = CreativeSkill(
        skill_id="x",
        name="X",
        medium=("a",),
        openness=0.9,
    )
    assert dataclasses.is_dataclass(skill)
    params = getattr(CreativeSkill, "__dataclass_params__", None)
    assert params is not None and params.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        skill.openness = 0.1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 3 — CreativeSkillsRegistry
# ---------------------------------------------------------------------------


def test_skills_registry_seeds_8_default_skills() -> None:
    registry = CreativeSkillsRegistry()
    skills = registry.list_skills()
    assert len(skills) == 8
    skill_ids = {s.skill_id for s in skills}
    assert skill_ids == {
        "creative_writing",
        "technical_writing",
        "code_as_art",
        "visual_design",
        "music_composition",
        "philosophy",
        "historiography",
        "comedy_satire",
    }


def test_skills_registry_get_skill_returns_skill_or_none() -> None:
    registry = CreativeSkillsRegistry()
    found = registry.get_skill("creative_writing")
    assert found is not None
    assert found.name == "Creative Writing"
    assert registry.get_skill("nonexistent") is None


def test_affinity_score_returns_zero_for_empty_traits() -> None:
    registry = CreativeSkillsRegistry()
    assert registry.affinity_score("creative_writing", {}) == 0.0


def test_affinity_score_returns_zero_for_unknown_skill() -> None:
    registry = CreativeSkillsRegistry()
    traits = {"openness": 0.9, "conscientiousness": 0.5,
              "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5}
    assert registry.affinity_score("not_a_skill", traits) == 0.0


def test_affinity_score_high_for_aligned_traits() -> None:
    registry = CreativeSkillsRegistry()
    aligned = {
        "openness": 0.85,
        "conscientiousness": 0.5,
        "extraversion": 0.5,
        "agreeableness": 0.5,
        "neuroticism": 0.5,
    }
    misaligned = {
        "openness": 0.05,
        "conscientiousness": 0.5,
        "extraversion": 0.5,
        "agreeableness": 0.5,
        "neuroticism": 0.5,
    }
    high = registry.affinity_score("creative_writing", aligned)
    low = registry.affinity_score("creative_writing", misaligned)
    assert 0.0 <= low < high <= 1.0
    assert high > 0.9


def test_affinity_score_emits_queried_event() -> None:
    registry = CreativeSkillsRegistry()
    emitter = _CollectingEmitter()
    registry._emit_event_fn = emitter
    traits = {"openness": 0.85, "conscientiousness": 0.5,
              "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5}
    registry.affinity_score("creative_writing", traits)
    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == EventType.CREATIVE_SKILL_AFFINITY_QUERIED
    assert data["skill_id"] == "creative_writing"
    assert data["agent_traits"] == traits
    assert 0.0 <= data["score"] <= 1.0


def test_top_skills_for_returns_descending_order() -> None:
    registry = CreativeSkillsRegistry()
    traits = {
        "openness": 0.95,
        "conscientiousness": 0.5,
        "extraversion": 0.5,
        "agreeableness": 0.5,
        "neuroticism": 0.5,
    }
    ranked = registry.top_skills_for(traits, k=3)
    assert len(ranked) == 3
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)


def test_top_skills_for_respects_k_limit() -> None:
    registry = CreativeSkillsRegistry()
    traits = {"openness": 0.5, "conscientiousness": 0.5,
              "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5}
    assert registry.top_skills_for(traits, k=2) and len(registry.top_skills_for(traits, k=2)) == 2
    assert registry.top_skills_for(traits, k=0) == []
    assert registry.top_skills_for({}, k=3) == []


def test_register_skill_overwrites_existing_id() -> None:
    registry = CreativeSkillsRegistry()
    custom = CreativeSkill(
        skill_id="creative_writing",
        name="Custom Override",
        medium=("custom",),
        openness=0.10,
    )
    registry.register_skill(custom)
    found = registry.get_skill("creative_writing")
    assert found is custom
    assert found.name == "Custom Override"


# ---------------------------------------------------------------------------
# Section 4 — CreativeOutputWriter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_writes_to_creative_path() -> None:
    store = _FakeRecordsStore()
    runtime = SimpleNamespace(records_store=store)
    writer = CreativeOutputWriter(runtime, CreativeExpressionConfig())
    rel = await writer.publish(
        author_callsign="poet",
        topic_slug="moonrise",
        content="A poem about moonrise.",
        medium="poetry",
        skill_id="creative_writing",
    )
    assert rel == "creative/poet/moonrise.md"
    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["path"] == "creative/poet/moonrise.md"
    assert call["author"] == "poet"
    assert call["status"] == "published"
    assert call["classification"] == "ship"
    assert call["topic"] == "moonrise"
    assert call["tags"] == ["creative", "poetry", "creative_writing"]
    assert call["metrics"] is None


@pytest.mark.asyncio
async def test_publish_emits_published_event() -> None:
    store = _FakeRecordsStore()
    runtime = SimpleNamespace(records_store=store)
    writer = CreativeOutputWriter(runtime, CreativeExpressionConfig())
    emitter = _CollectingEmitter()
    writer._emit_event_fn = emitter
    await writer.publish(
        author_callsign="poet",
        topic_slug="moonrise",
        content="...",
        medium="poetry",
        skill_id="creative_writing",
    )
    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == EventType.CREATIVE_WORK_PUBLISHED
    assert data == {
        "author": "poet",
        "skill_id": "creative_writing",
        "medium": "poetry",
        "path": "creative/poet/moonrise.md",
        "classification": "ship",
    }


@pytest.mark.asyncio
async def test_publish_uses_default_classification_ship() -> None:
    store = _FakeRecordsStore()
    runtime = SimpleNamespace(records_store=store)
    writer = CreativeOutputWriter(runtime, CreativeExpressionConfig())
    await writer.publish(
        author_callsign="a",
        topic_slug="t",
        content="c",
        medium="m",
        skill_id="s",
    )
    assert store.calls[0]["classification"] == "ship"

    private_cfg = CreativeExpressionConfig(default_classification="private")
    writer_priv = CreativeOutputWriter(runtime, private_cfg)
    await writer_priv.publish(
        author_callsign="a",
        topic_slug="t2",
        content="c",
        medium="m",
        skill_id="s",
    )
    assert store.calls[1]["classification"] == "private"


@pytest.mark.asyncio
async def test_publish_raises_when_records_store_unavailable() -> None:
    runtime = SimpleNamespace()  # no records_store attr
    writer = CreativeOutputWriter(runtime, CreativeExpressionConfig())
    with pytest.raises(CreativeOutputError):
        await writer.publish(
            author_callsign="a",
            topic_slug="t",
            content="c",
            medium="m",
            skill_id="s",
        )

    # Wrap underlying write_entry exception
    runtime2 = SimpleNamespace(records_store=_ExplodingRecordsStore())
    writer2 = CreativeOutputWriter(runtime2, CreativeExpressionConfig())
    with pytest.raises(CreativeOutputError):
        await writer2.publish(
            author_callsign="a",
            topic_slug="t",
            content="c",
            medium="m",
            skill_id="s",
        )


@pytest.mark.asyncio
async def test_list_works_by_author_returns_only_authors_works(tmp_path) -> None:
    creative_dir = tmp_path / "creative"
    (creative_dir / "alice").mkdir(parents=True)
    (creative_dir / "alice" / "haiku.md").write_text("---\n---\n", encoding="utf-8")
    (creative_dir / "alice" / "essay.md").write_text("---\n---\n", encoding="utf-8")
    (creative_dir / "bob").mkdir()
    (creative_dir / "bob" / "song.md").write_text("---\n---\n", encoding="utf-8")

    store = _FakeRecordsStore(repo_path=tmp_path)
    runtime = SimpleNamespace(records_store=store)
    writer = CreativeOutputWriter(runtime, CreativeExpressionConfig())

    alice_works = await writer.list_works_by_author("alice")
    assert sorted(alice_works) == [
        "creative/alice/essay.md",
        "creative/alice/haiku.md",
    ]
    assert await writer.list_works_by_author("bob") == ["creative/bob/song.md"]
    assert await writer.list_works_by_author("nobody") == []


# ---------------------------------------------------------------------------
# Section 6 — Runtime wiring
# ---------------------------------------------------------------------------


def test_runtime_attributes_set_when_enabled() -> None:
    runtime = MagicMock(spec=["emit_event", "creative_skills_registry", "creative_output_writer"])
    config = SimpleNamespace(creative_expression=CreativeExpressionConfig(enabled=True))
    wired = _wire_creative_expression(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.creative_skills_registry, CreativeSkillsRegistry)
    assert isinstance(runtime.creative_output_writer, CreativeOutputWriter)


def test_runtime_attributes_not_set_when_disabled() -> None:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    config = SimpleNamespace(creative_expression=CreativeExpressionConfig(enabled=False))
    wired = _wire_creative_expression(runtime=runtime, config=config)
    assert wired is False
    assert not hasattr(runtime, "creative_skills_registry")
    assert not hasattr(runtime, "creative_output_writer")


# ---------------------------------------------------------------------------
# R3 adapter contract — affinity_score accepts PersonalityTraits.to_dict()
# ---------------------------------------------------------------------------


def test_affinity_score_accepts_personality_traits_to_dict_shape() -> None:
    traits_obj = PersonalityTraits(
        openness=0.85,
        conscientiousness=0.5,
        extraversion=0.5,
        agreeableness=0.5,
        neuroticism=0.5,
    )
    traits_dict = traits_obj.to_dict()
    assert set(traits_dict.keys()) >= {
        "openness",
        "conscientiousness",
        "extraversion",
        "agreeableness",
        "neuroticism",
    }
    registry = CreativeSkillsRegistry()
    score = registry.affinity_score("creative_writing", traits_dict)
    assert 0.0 <= score <= 1.0
    assert score > 0.9
