"""AD-723: Sensorium dispatch unification — Tests (Wave 144 v1, producer-side).

Covers the chain-path producer-side migration shipped in AD-723 v1:

* New ``SensoriumPath`` enum and ``SensoriumEntry`` dataclass
* Registry shape conversion (``tuple`` → ``SensoriumEntry``)
* Sync + async dispatcher core
* Path-coherence rules (avatar / intent-self-tag / situation / DM monitoring)
* Chain-side extraction byte-equality (golden snapshot)

The DM/WR consumer-side migration of ``_build_user_message`` is deferred to
AD-723a-1 (#617). Snapshot fixtures for DM/WR live in that AD's prompt.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    SensoriumEntry,
    SensoriumLayer,
    SensoriumPath,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sensorium_snapshots"


# ---------------------------------------------------------------------------
# Helpers — mirror tests/test_ad646_cognitive_baseline.py patterns
# ---------------------------------------------------------------------------

def _make_runtime(trust_score: float = 0.75) -> MagicMock:
    rt = MagicMock()
    rt.trust_network.get_score.return_value = trust_score
    rt.ontology.get_crew_context.return_value = {
        "identity": {"callsign": "Echo", "post": "Counselor"},
        "department": {"name": "Medical"},
        "reports_to": "Captain",
        "direct_reports": ["Nurse Chapel"],
        "peers": ["Bones"],
        "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
        "capabilities": [],
        "does_not_have": [],
    }
    rt.is_cold_start = False
    rt.config = MagicMock()
    rt.config.earned_agency.initiative_trust_thresholds = None
    rt.config.avatar_telemetry = MagicMock()
    rt.config.avatar_telemetry.inject_into_agent_context = False
    rt.config.avatar_telemetry.divergence_detection = False
    return rt


def _make_agent(runtime: MagicMock | None = None) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="ad723-agent", instructions="ad723 test")
    agent.callsign = "AD723Agent"
    agent.agent_type = "ad723_agent"
    agent._runtime = runtime if runtime is not None else _make_runtime()
    # Pin temporal so wall-clock drift cannot invalidate byte equality.
    agent._build_temporal_context = lambda: "Current time: 2026-05-10 12:00 UTC"
    return agent


# ---------------------------------------------------------------------------
# §1. Types — SensoriumPath / SensoriumEntry
# ---------------------------------------------------------------------------

class TestSensoriumTypes:

    def test_sensorium_path_values_are_strings(self):
        # StrEnum members are usable as plain strings for serialization.
        assert SensoriumPath.CHAIN_BASELINE == "chain_baseline"
        assert SensoriumPath.DM_ONESHOT == "dm_oneshot"

    def test_sensorium_entry_defaults(self):
        entry = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test",
        )
        assert entry.paths == ()
        assert entry.priority == 0
        assert entry.output_key is None

    def test_sensorium_entry_is_frozen(self):
        entry = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test",
        )
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            entry.priority = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# §2. Registry shape — every entry is a SensoriumEntry; every registered
# method name resolves on CognitiveAgent (phantom-API guard)
# ---------------------------------------------------------------------------

class TestRegistryShape:

    def test_all_entries_are_sensorium_entry(self):
        for name, entry in CognitiveAgent.SENSORIUM_REGISTRY.items():
            assert isinstance(entry, SensoriumEntry), name

    def test_all_registered_methods_exist(self):
        """Phantom-API guard: every registered method name must resolve on CognitiveAgent."""
        for method_name in CognitiveAgent.SENSORIUM_REGISTRY:
            assert hasattr(CognitiveAgent, method_name), (
                f"AD-723: {method_name} is registered but not defined on CognitiveAgent"
            )


# ---------------------------------------------------------------------------
# §3. Path coherence — encodes ruling Captain decisions from AD-722 (h),
# AD-722a, and the System-1 / System-2 path split.
# ---------------------------------------------------------------------------

class TestPathCoherence:

    def test_avatar_not_in_wr_paths(self):
        """AD-722 addendum (h): avatar block is NOT injected into WR (peer audience)."""
        entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_avatar_self_observation"]
        assert SensoriumPath.WR_ONESHOT not in entry.paths
        assert SensoriumPath.CHAIN_BASELINE in entry.paths
        assert SensoriumPath.DM_ONESHOT in entry.paths

    def test_intent_self_tag_not_in_wr_paths(self):
        """AD-722a: intent self-tag follows avatar block — also NOT in WR."""
        entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_intent_self_tag_instruction"]
        assert SensoriumPath.WR_ONESHOT not in entry.paths
        assert SensoriumPath.CHAIN_BASELINE in entry.paths
        assert SensoriumPath.DM_ONESHOT in entry.paths

    def test_dm_self_monitoring_not_in_dm_paths(self):
        """`_build_dm_self_monitoring` is for WR dm-* channel detection, not DM one-shot."""
        entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_dm_self_monitoring"]
        assert SensoriumPath.DM_ONESHOT not in entry.paths
        assert SensoriumPath.WR_ONESHOT in entry.paths

    def test_situation_entries_chain_only(self):
        """CHAIN_SITUATION entries never appear in DM/WR (situation is chain-only)."""
        for name, entry in CognitiveAgent.SENSORIUM_REGISTRY.items():
            if SensoriumPath.CHAIN_SITUATION in entry.paths:
                assert SensoriumPath.DM_ONESHOT not in entry.paths, name
                assert SensoriumPath.WR_ONESHOT not in entry.paths, name


# ---------------------------------------------------------------------------
# §4. Dispatcher core — sync, async, ordering, removal, error degradation
# ---------------------------------------------------------------------------

class TestDispatcherCore:

    def test_sync_dispatch_returns_dict(self):
        agent = _make_agent()
        result = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_BASELINE, {"recent_memories": []},
        )
        assert isinstance(result, dict)
        # No-memories flag fires when no memories.
        assert result.get("_no_episodic_memories")

    def test_sync_dispatch_empty_paths_returns_empty(self):
        """Entries with paths=() never appear in any dispatch."""
        agent = _make_agent()
        # CHAIN_BASELINE dispatch must not include the inventory-only
        # method `_build_cognitive_baseline` (which has paths=()).
        for method_name, entry in agent._sensorium_entries_for_path(SensoriumPath.CHAIN_BASELINE):
            assert entry.paths != ()

    def test_sync_dispatch_rejects_async_method(self, monkeypatch):
        """AD-723: sync dispatcher refuses to silently drop async methods."""
        async def _async_payload(self, observation: dict) -> str:
            return "async-result"

        agent = _make_agent()
        monkeypatch.setattr(
            CognitiveAgent, "_test_async_method", _async_payload, raising=False,
        )
        CognitiveAgent.SENSORIUM_REGISTRY["_test_async_method"] = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test only",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_test_key",
        )
        try:
            with pytest.raises(RuntimeError, match="async method .* on sync path"):
                agent._dispatch_sensorium_sync(SensoriumPath.CHAIN_BASELINE, {})
        finally:
            CognitiveAgent.SENSORIUM_REGISTRY.pop("_test_async_method", None)

    def test_async_dispatch_awaits_coroutine_methods(self, monkeypatch):
        """`_dispatch_sensorium_async` awaits async methods and merges results."""
        async def _async_payload(self, observation: dict) -> str:
            return "async-value"

        agent = _make_agent()
        monkeypatch.setattr(
            CognitiveAgent, "_test_async_dm", _async_payload, raising=False,
        )
        CognitiveAgent.SENSORIUM_REGISTRY["_test_async_dm"] = SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="async test entry",
            paths=(SensoriumPath.DM_ONESHOT,),
            output_key="_async_key",
        )
        try:
            result = asyncio.run(
                agent._dispatch_sensorium_async(SensoriumPath.DM_ONESHOT, {})
            )
            assert result.get("_async_key") == "async-value"
        finally:
            CognitiveAgent.SENSORIUM_REGISTRY.pop("_test_async_dm", None)

    def test_apply_result_none_signals_removal(self):
        """AD-646: ``None`` from a registered method pops the key from merged."""
        agent = _make_agent()
        entry = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_target_key",
        )
        merged = {"_target_key": "baseline-value", "_other": "kept"}
        agent._apply_sensorium_result(merged, entry, "_test", None)
        assert "_target_key" not in merged
        assert merged["_other"] == "kept"

    def test_apply_result_empty_string_skipped(self):
        """Returning ``""`` is no-contribution: dispatcher neither sets nor pops."""
        agent = _make_agent()
        entry = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_target_key",
        )
        merged = {"_target_key": "previous-value"}
        agent._apply_sensorium_result(merged, entry, "_test", "")
        assert merged == {"_target_key": "previous-value"}

    def test_apply_result_dict_multi_key(self):
        """A dict return contributes to multiple keys; None values inside dict pop."""
        agent = _make_agent()
        entry = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="test",
            paths=(SensoriumPath.CHAIN_BASELINE,),
        )
        merged = {"_will_be_popped": "old", "_kept": "k"}
        agent._apply_sensorium_result(
            merged, entry, "_test",
            {"_new": "n", "_will_be_popped": None, "_empty": ""},
        )
        assert merged == {"_kept": "k", "_new": "n"}

    def test_dispatch_method_raise_is_tier2_degrade(self, monkeypatch, caplog):
        """An exception from a registered method is logged and skipped (Tier-2)."""
        def _boom(self, observation: dict) -> str:
            raise RuntimeError("intentional test failure")

        agent = _make_agent()
        monkeypatch.setattr(CognitiveAgent, "_test_boom", _boom, raising=False)
        CognitiveAgent.SENSORIUM_REGISTRY["_test_boom"] = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="boom",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_boom_key",
        )
        try:
            with caplog.at_level(logging.DEBUG, logger="probos.cognitive.cognitive_agent"):
                result = agent._dispatch_sensorium_sync(
                    SensoriumPath.CHAIN_BASELINE, {"recent_memories": []},
                )
            # Other entries still produced output.
            assert "_no_episodic_memories" in result
            # Boom entry did not produce its key.
            assert "_boom_key" not in result
        finally:
            CognitiveAgent.SENSORIUM_REGISTRY.pop("_test_boom", None)

    def test_priority_ordering(self):
        """Higher-priority extension overrides lower-priority baseline by key."""
        agent = _make_agent()
        # baseline writes _source_attribution_text; extension overrides.
        baseline = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_BASELINE, {"recent_memories": []},
        )
        assert "Source quality: unknown" in baseline["_source_attribution_text"]

        framing = MagicMock()
        framing.authority = MagicMock()
        framing.authority.value = "authoritative"
        ext_obs = {"_context_parts": {
            "recent_memories": [{"x": 1}],
            "_source_framing": framing,
        }}
        ext = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_EXTENSIONS, ext_obs,
        )
        assert "Source quality: authoritative" in ext["_source_attribution_text"]


# ---------------------------------------------------------------------------
# §5. AD-646 None-for-removal regression — preserved through extensions
# ---------------------------------------------------------------------------

class TestNoneRemovalSemantics:

    def test_extensions_no_memories_removal(self):
        """When memories present in context_parts, baseline's no-memories flag is popped."""
        agent = _make_agent()
        context_parts = {
            "recent_memories": [{"x": 1}],
            "_source_framing": MagicMock(authority=None),
        }
        state = agent._build_cognitive_state(
            context_parts, observation={"recent_memories": []},
        )
        # Extension explicitly pops _no_episodic_memories via None return.
        assert "_no_episodic_memories" not in state

    def test_extensions_no_memories_set_when_framing_but_empty(self):
        """When framing present but no memories, the flag IS set."""
        agent = _make_agent()
        framing = MagicMock()
        framing.authority = None
        context_parts = {
            "recent_memories": [],
            "_source_framing": framing,
        }
        state = agent._build_cognitive_state(
            context_parts, observation={"recent_memories": [{"y": 1}]},
        )
        assert "_no_episodic_memories" in state


# ---------------------------------------------------------------------------
# §6. Chain-baseline snapshot byte-equality — the acceptance gate
# ---------------------------------------------------------------------------

class TestChainBaselineSnapshot:

    def test_chain_baseline_byte_equality(self):
        """AD-723: refactored CHAIN_BASELINE dispatch is byte-identical to pre-refactor.

        Fixture captured pre-refactor by
        ``tests/fixtures/sensorium_snapshots/_capture_chain_baseline.py``
        with default avatar/divergence flags OFF. Re-running the dispatcher
        with the same canned observation MUST produce the same dict shape
        and the same per-key text — byte for byte.
        """
        agent = _make_agent()
        observation = {
            "recent_memories": [
                {"content": "Observed latency spike at 14:00", "timestamp": 1713500000},
                {"content": "Reviewed comm logs with Bones", "timestamp": 1713600000},
            ],
            "context": "Captain, please review.",
        }
        state = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_BASELINE, observation,
        )
        rendered = "".join(f"{k}\n{v}\n---\n" for k, v in state.items())
        fixture = (FIXTURES_DIR / "chain_baseline.txt").read_text(encoding="utf-8")
        assert rendered == fixture, (
            "AD-723 chain-baseline byte-equality regression. "
            "If the change is intentional, re-run "
            "tests/fixtures/sensorium_snapshots/_capture_chain_baseline.py "
            "to regenerate the fixture."
        )

    def test_chain_baseline_via_shim_matches_dispatcher(self):
        """The legacy shim ``_build_cognitive_baseline`` delegates to the dispatcher."""
        agent = _make_agent()
        observation = {"recent_memories": [{"y": 2}], "context": ""}
        via_shim = agent._build_cognitive_baseline(observation)
        via_dispatcher = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_BASELINE, observation,
        )
        assert via_shim == via_dispatcher


# ---------------------------------------------------------------------------
# §7. Chain-side extraction coverage — every baseline/extension/situation
# extraction method is exercised at least once.
# ---------------------------------------------------------------------------

class TestChainExtractionCoverage:

    def test_baseline_extracted_methods_all_invocable(self):
        """Each baseline ``_sensorium_*`` extraction returns str when data present."""
        agent = _make_agent()
        observation = {
            "recent_memories": [{"x": 1}],
            "context": "Captain, please review.",
        }
        # Methods registered for CHAIN_BASELINE that are extracted helpers
        # (not the avatar / intent-self-tag direct entries).
        names = [
            "_sensorium_agent_metrics",
            "_sensorium_ontology_baseline",
            "_sensorium_source_attribution_baseline",
            "_sensorium_confab_guard_baseline",
        ]
        for name in names:
            method = getattr(agent, name)
            result = method(observation)
            assert isinstance(result, str), name
            assert result, f"{name} returned empty string with full observation"

    def test_situation_dispatch_returns_only_situation_keys(self):
        """CHAIN_SITUATION dispatch only contains situation keys, never baseline keys."""
        agent = _make_agent()
        context_parts = {
            "recent_alerts": [{"severity": "yellow", "title": "test", "source": "bridge"}],
            "active_game": None,
        }
        state = agent._build_situation_awareness(context_parts)
        # Situation key produced
        assert "_recent_alerts" in state
        # No baseline keys
        assert "_temporal_context" not in state
        assert "_agent_metrics" not in state


# ---------------------------------------------------------------------------
# §8. AD-722 / AD-722a default-OFF byte-identity guard
# ---------------------------------------------------------------------------

class TestAvatarDefaultOff:

    def test_avatar_default_off_no_key_in_baseline(self):
        """avatar_telemetry.inject_into_agent_context default=False → no key in state."""
        agent = _make_agent()
        state = agent._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_BASELINE, {"recent_memories": []},
        )
        assert "_avatar_self_observation" not in state
        assert "_intent_self_tag" not in state
