"""AD-668: Salience filter tests."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.agent_working_memory import AgentWorkingMemory, WorkingMemoryEntry
from probos.cognitive.novelty_gate import NoveltyVerdict
from probos.cognitive.salience_filter import BackgroundStream, SalienceFilter, SalienceScore


class _FakeNoveltyGate:
    def __init__(self, verdict: NoveltyVerdict) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str]] = []

    def check(self, agent_id: str, text: str) -> NoveltyVerdict:
        self.calls.append((agent_id, text))
        return self.verdict


def _entry(
    content: str = "candidate",
    category: str = "event",
    metadata: dict[str, object] | None = None,
    timestamp: float | None = None,
) -> WorkingMemoryEntry:
    return WorkingMemoryEntry(
        content=content,
        category=category,
        source_pathway="system",
        timestamp=time.time() if timestamp is None else timestamp,
        metadata=metadata or {},
    )


class TestSalienceScore:
    def test_salience_score_fields(self) -> None:
        entry = _entry()
        score = SalienceScore(
            total=0.7,
            components={"relevance": 0.7},
            promoted=True,
            entry=entry,
        )

        assert score.total == 0.7
        assert score.components["relevance"] == 0.7
        assert score.promoted is True
        assert score.entry is entry

    def test_salience_score_promoted_true(self) -> None:
        score = SalienceScore(total=0.8, components={}, promoted=True, entry=_entry())

        assert score.promoted is True

    def test_salience_score_promoted_false(self) -> None:
        score = SalienceScore(total=0.2, components={}, promoted=False, entry=_entry())

        assert score.promoted is False


class TestSalienceFilterConstruction:
    def test_default_weights(self) -> None:
        salience_filter = SalienceFilter()

        assert salience_filter._weights == {
            "relevance": pytest.approx(0.30),
            "recency": pytest.approx(0.25),
            "novelty": pytest.approx(0.15),
            "urgency": pytest.approx(0.20),
            "social": pytest.approx(0.10),
        }

    def test_custom_weights_normalized(self) -> None:
        salience_filter = SalienceFilter(weights={"relevance": 2.0, "recency": 1.0})

        assert salience_filter._weights["relevance"] == pytest.approx(2.0 / 3.0)
        assert salience_filter._weights["recency"] == pytest.approx(1.0 / 3.0)
        assert sum(salience_filter._weights.values()) == pytest.approx(1.0)

    def test_from_config(self) -> None:
        from probos.config import SalienceConfig

        config = SalienceConfig(threshold=0.75, weights={"urgency": 1.0})

        salience_filter = SalienceFilter.from_config(config)

        assert salience_filter._threshold == 0.75
        assert salience_filter._weights == {"urgency": pytest.approx(1.0)}


class TestScoreRelevance:
    def test_relevance_department_match(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(metadata={"department": "engineering"})

        score = salience_filter._score_relevance(entry, {"department": "engineering"})

        assert score >= 0.8

    def test_relevance_duty_match(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(metadata={"duty": "repair"})

        score = salience_filter._score_relevance(entry, {"current_duty": "repair"})

        assert score >= 0.9

    def test_relevance_no_context(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_relevance(_entry(), {})

        assert score == 0.5

    def test_relevance_alert_category_floor(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_relevance(_entry(category="alert"), {})

        assert score >= 0.7


class TestScoreRecency:
    def test_recency_fresh_entry(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_recency(_entry(), {})

        assert score > 0.99

    def test_recency_old_entry(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(timestamp=time.time() - 600)

        score = salience_filter._score_recency(entry, {})

        assert score < 0.5

    def test_recency_very_old_entry(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(timestamp=time.time() - 3600)

        score = salience_filter._score_recency(entry, {})

        assert score < 0.01


class TestScoreNovelty:
    def test_novelty_no_gate(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_novelty(_entry(), {})

        assert score == 0.5

    def test_novelty_with_novel_verdict(self) -> None:
        gate = _FakeNoveltyGate(NoveltyVerdict(is_novel=True, similarity=0.2, reason="novel"))
        salience_filter = SalienceFilter(novelty_gate=gate)

        score = salience_filter._score_novelty(_entry("fresh topic"), {"agent_id": "agent-1"})

        assert score == pytest.approx(0.8)
        assert gate.calls == [("agent-1", "fresh topic")]

    def test_novelty_with_duplicate_verdict(self) -> None:
        gate = _FakeNoveltyGate(
            NoveltyVerdict(is_novel=False, similarity=0.9, reason="duplicate")
        )
        salience_filter = SalienceFilter(novelty_gate=gate)

        score = salience_filter._score_novelty(_entry(), {"agent_id": "agent-1"})

        assert score == pytest.approx(0.1)


class TestScoreUrgency:
    def test_urgency_critical_severity(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_urgency(_entry(metadata={"severity": "critical"}), {})

        assert score == 1.0

    def test_urgency_normal_baseline(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_urgency(_entry(), {"alert_level": "normal"})

        assert score == 0.3

    def test_urgency_red_alert_boost(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_urgency(_entry(), {"alert_level": "red"})

        assert score >= 0.5


class TestScoreSocial:
    def test_social_trusted_source(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(metadata={"from": "known_agent"})

        score = salience_filter._score_social(entry, {"trust_scores": {"known_agent": 0.9}})

        assert score == 0.9

    def test_social_unknown_source(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(metadata={"from": "stranger"})

        score = salience_filter._score_social(entry, {"trust_scores": {}})

        assert score == 0.4

    def test_social_no_source(self) -> None:
        salience_filter = SalienceFilter()

        score = salience_filter._score_social(_entry(), {})

        assert score == 0.5


class TestScoreAggregation:
    def test_score_total_is_weighted_sum(self) -> None:
        salience_filter = SalienceFilter()
        entry = _entry(metadata={"severity": "high", "from": "known_agent"})
        context = {"trust_scores": {"known_agent": 0.8}}

        score = salience_filter.score(entry, context)
        expected = round(
            sum(salience_filter._weights[key] * score.components[key] for key in salience_filter._weights),
            4,
        )

        assert score.total == expected

    def test_score_total_clamped(self) -> None:
        salience_filter = SalienceFilter(weights={"social": 1.0})
        high = salience_filter.score(_entry(metadata={"from": "agent"}), {"trust_scores": {"agent": 5.0}})
        low = salience_filter.score(_entry(metadata={"from": "agent"}), {"trust_scores": {"agent": -5.0}})

        assert high.total == 1.0
        assert low.total == 0.0

    def test_should_promote_convenience(self) -> None:
        salience_filter = SalienceFilter(threshold=0.9)
        entry = _entry(metadata={"severity": "critical"})

        assert salience_filter.should_promote(entry, {}) is salience_filter.score(entry, {}).promoted


class TestBackgroundStream:
    def test_add_and_peek(self) -> None:
        stream = BackgroundStream()
        score = SalienceScore(0.2, {}, False, _entry())

        stream.add(score)

        assert stream.peek() == [score]
        assert len(stream) == 1

    def test_drain_clears(self) -> None:
        stream = BackgroundStream()
        score = SalienceScore(0.2, {}, False, _entry())
        stream.add(score)

        drained = stream.drain()

        assert drained == [score]
        assert len(stream) == 0

    def test_max_entries_cap(self) -> None:
        stream = BackgroundStream(max_entries=2)
        scores = [SalienceScore(i / 10, {}, False, _entry(str(i))) for i in range(3)]

        for score in scores:
            stream.add(score)

        assert stream.peek() == scores[1:]

    def test_len(self) -> None:
        stream = BackgroundStream()
        stream.add(SalienceScore(0.2, {}, False, _entry()))
        stream.add(SalienceScore(0.1, {}, False, _entry()))

        assert len(stream) == 2


class TestWorkingMemoryIntegration:
    def test_record_without_filter_always_passes(self) -> None:
        wm = AgentWorkingMemory()

        wm.record_event("Routine event")

        assert "Routine event" in wm.render_context()

    def test_record_with_filter_promotes_high_salience(self) -> None:
        salience_filter = SalienceFilter(threshold=0.3)
        wm = AgentWorkingMemory(
            salience_filter=salience_filter,
            agent_context={
                "department": "engineering",
                "current_duty": "repair",
                "trust_scores": {"known_agent": 1.0},
                "alert_level": "red",
            },
        )

        wm.record_event(
            "Core breach",
            metadata={
                "severity": "critical",
                "department": "engineering",
                "duty": "repair",
                "from": "known_agent",
            },
        )

        assert "Core breach" in wm.render_context()
        assert wm.get_background_stream() is not None
        assert len(wm.get_background_stream() or []) == 0

    def test_record_with_filter_demotes_low_salience(self) -> None:
        salience_filter = SalienceFilter(threshold=0.99)
        wm = AgentWorkingMemory(salience_filter=salience_filter)

        wm.record_event("Routine ping")

        stream = wm.get_background_stream()
        assert wm.render_context() == ""
        assert stream is not None
        assert len(stream) == 1
        assert stream.peek()[0].entry.content == "Routine ping"

    def test_background_stream_accessible(self) -> None:
        wm = AgentWorkingMemory(salience_filter=SalienceFilter())

        assert isinstance(wm.get_background_stream(), BackgroundStream)

    def test_set_agent_context(self) -> None:
        wm = AgentWorkingMemory(salience_filter=SalienceFilter(threshold=0.6))
        wm.record_observation("Before context", source="proactive", metadata={"department": "engineering"})

        wm.set_agent_context({"department": "engineering"})
        wm.record_observation("After context", source="proactive", metadata={"department": "engineering"})

        context = wm.render_context()
        assert "Before context" not in context
        assert "After context" in context

    def test_all_record_methods_gated(self) -> None:
        wm = AgentWorkingMemory(salience_filter=SalienceFilter(threshold=0.99))

        wm.record_action("Action", source="dm")
        wm.record_observation("Observation", source="proactive")
        wm.record_conversation("Conversation", partner="Captain", source="dm")
        wm.record_event("Event")
        wm.record_reasoning("Reasoning", source="chain")

        stream = wm.get_background_stream()
        assert wm.render_context() == ""
        assert stream is not None
        assert len(stream) == 5
