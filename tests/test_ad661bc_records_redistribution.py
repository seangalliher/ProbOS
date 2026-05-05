"""AD-661b + AD-661c — Ship's Records consumption + budget remainder redistribution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.diagnostic_context import (
    _MAX_RECORDS_CANDIDATES,
    _RECORDS_CONTENT_EXCERPT_CHARS,
    _RECORDS_READER_ID,
    DiagnosticBundle,
    DiagnosticContextService,
)
from probos.config import DiagnosticContextConfig


def _make_runtime(
    *,
    records_store=None,
    cognitive_journal=None,
    procedure_store=None,
    episodic_memory=None,
):
    return SimpleNamespace(
        cognitive_journal=cognitive_journal,
        procedure_store=procedure_store,
        episodic_memory=episodic_memory,
        records_store=records_store,
    )


def _stub_records_store(entries, content_by_path=None):
    """Build a minimal records_store stub with list_entries + read_entry."""
    content_by_path = content_by_path or {}
    store = MagicMock()
    store.list_entries = AsyncMock(return_value=entries)

    async def _read(path, *, reader_id, reader_department):
        # Assert system reader identity is propagated.
        assert reader_id == _RECORDS_READER_ID
        assert reader_department == ""
        if path in content_by_path:
            return {"path": path, "content": content_by_path[path], "frontmatter": {}}
        return None

    store.read_entry = AsyncMock(side_effect=_read)
    return store


# --- Test 1: config 4-ratio validation + redistribute default ----------------
def test_config_4_ratios_validate_and_default() -> None:
    cfg = DiagnosticContextConfig()
    total = (
        cfg.chain_trace_ratio
        + cfg.procedure_ratio
        + cfg.episode_ratio
        + cfg.records_ratio
    )
    assert abs(total - 1.0) < 0.01
    assert cfg.redistribute_remainder is True
    # explicit bad sum raises
    with pytest.raises(Exception):
        DiagnosticContextConfig(records_ratio=0.5)


# --- Test 2: bundle includes records field ----------------------------------
def test_bundle_includes_records_field() -> None:
    b = DiagnosticBundle(query="x", records=[{"path": "r1", "title": "Report 1"}])
    d = b.to_dict()
    assert "records" in d
    assert d["records"][0]["path"] == "r1"
    # to_dict returns a copy
    d["records"].append({"path": "r2"})
    assert len(b.records) == 1


# --- Test 3: records gathered when store has matches ------------------------
@pytest.mark.asyncio
async def test_records_gathered_when_store_has_matches() -> None:
    entries = [
        {"path": "r1", "frontmatter": {"title": "CPU spike incident", "classification": "ship", "author": "lt-data"}},
        {"path": "r2", "frontmatter": {"title": "Coffee break log", "classification": "ship"}},
        {"path": "r3", "frontmatter": {"title": "Memory usage notes", "classification": "ship"}},
    ]
    contents = {
        "r1": "Detailed CPU spike investigation results",
        "r2": "Casual coffee break notes",
        "r3": "CPU memory bus correlation",  # title miss, content hit
    }
    runtime = _make_runtime(records_store=_stub_records_store(entries, contents))
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu", budget_tokens=8000)
    paths = sorted(r["path"] for r in bundle.records)
    assert paths == ["r1", "r3"]
    r1 = next(r for r in bundle.records if r["path"] == "r1")
    assert r1["title"] == "CPU spike incident"
    assert r1["classification"] == "ship"
    assert r1["author"] == "lt-data"
    assert "summary_excerpt" in r1


# --- Test 4: records empty when no records_store ----------------------------
@pytest.mark.asyncio
async def test_records_empty_when_no_records_store() -> None:
    runtime = _make_runtime(records_store=None)
    svc = DiagnosticContextService(runtime)
    bundle = await svc.assemble(query="cpu")
    assert bundle.records == []


# --- Test 5: records empty when keyword has no matches ----------------------
@pytest.mark.asyncio
async def test_records_empty_when_keyword_no_match() -> None:
    entries = [
        {"path": "r1", "frontmatter": {"title": "Coffee log", "classification": "ship"}},
        {"path": "r2", "frontmatter": {"title": "Lunch menu", "classification": "ship"}},
    ]
    contents = {"r1": "morning coffee", "r2": "tuesday lunch"}
    runtime = _make_runtime(records_store=_stub_records_store(entries, contents))
    svc = DiagnosticContextService(runtime)
    bundle = await svc.assemble(query="quantum")
    assert bundle.records == []


# --- Test 6: records excerpt truncated to cap -------------------------------
@pytest.mark.asyncio
async def test_records_excerpt_truncated() -> None:
    entries = [{"path": "r1", "frontmatter": {"title": "CPU log", "classification": "ship"}}]
    big_content = "cpu " + ("y" * 5000)
    runtime = _make_runtime(records_store=_stub_records_store(entries, {"r1": big_content}))
    svc = DiagnosticContextService(runtime, default_budget_tokens=64000)
    bundle = await svc.assemble(query="cpu", budget_tokens=64000)
    assert len(bundle.records) == 1
    excerpt = bundle.records[0]["summary_excerpt"]
    assert len(excerpt) == _RECORDS_CONTENT_EXCERPT_CHARS


# --- Test 7: records contribute to total_estimated_tokens -------------------
@pytest.mark.asyncio
async def test_records_contribute_to_total_estimated_tokens() -> None:
    entries = [
        {"path": "r1", "frontmatter": {"title": "CPU spike", "classification": "ship"}},
        {"path": "r2", "frontmatter": {"title": "CPU drift", "classification": "ship"}},
    ]
    contents = {"r1": "CPU detailed " * 50, "r2": "CPU detailed " * 50}

    runtime_with = _make_runtime(records_store=_stub_records_store(entries, contents))
    svc_with = DiagnosticContextService(runtime_with, default_budget_tokens=8000)
    bundle_with = await svc_with.assemble(query="cpu", budget_tokens=8000)

    runtime_without = _make_runtime(records_store=None)
    svc_without = DiagnosticContextService(runtime_without, default_budget_tokens=8000)
    bundle_without = await svc_without.assemble(query="cpu", budget_tokens=8000)

    assert bundle_with.total_estimated_tokens > bundle_without.total_estimated_tokens
    assert len(bundle_with.records) == 2


# --- Test 8: redistribute under-fill flows to other tiers -------------------
@pytest.mark.asyncio
async def test_redistribute_under_fill_in_tier_flows_to_others() -> None:
    # 50 medium chain_trace candidates that match "cpu" (each ~30 tokens so
    # 50 rows easily exceed the 600-token chain slice but fit in 2000 total).
    small_rows = [
        {"chain_id": f"c{i}", "step_index": 0, "step_name": "evaluate",
         "sub_task_type": "cpu_step", "intent": "diagnose",
         "error_truncated": "padding " * 12, "communication_context": "ctx"}
        for i in range(50)
    ]
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=small_rows)

    runtime = _make_runtime(cognitive_journal=journal, records_store=None)

    # WITH redistribute=True: chain_traces should consume well beyond its
    # 30%-of-2000=600-token slice because procedures/episodes/records are 0.
    svc_redist = DiagnosticContextService(
        runtime, default_budget_tokens=2000, redistribute_remainder=True,
    )
    bundle_redist = await svc_redist.assemble(query="cpu", budget_tokens=2000)

    # WITHOUT redistribute: chain_traces capped at ~600 tokens.
    svc_capped = DiagnosticContextService(
        runtime, default_budget_tokens=2000, redistribute_remainder=False,
    )
    bundle_capped = await svc_capped.assemble(query="cpu", budget_tokens=2000)

    assert len(bundle_redist.chain_traces) > len(bundle_capped.chain_traces)


# --- Test 9: truncated False when all candidates fit ------------------------
@pytest.mark.asyncio
async def test_truncated_false_when_all_candidates_fit() -> None:
    entries = [{"path": "r1", "frontmatter": {"title": "CPU info", "classification": "ship"}}]
    contents = {"r1": "small cpu note"}
    runtime = _make_runtime(records_store=_stub_records_store(entries, contents))
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu", budget_tokens=8000)
    assert bundle.truncated is False


# --- Test 10: truncated True when budget exhausted with leftover candidates -
@pytest.mark.asyncio
async def test_truncated_true_when_budget_exhausted_with_candidates_left() -> None:
    huge_rows = [
        {"chain_id": f"c{i}", "step_index": 0, "step_name": "evaluate",
         "sub_task_type": "cpu_step", "intent": "diagnose",
         "error_truncated": "x" * 4000, "communication_context": ""}
        for i in range(20)
    ]
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=huge_rows)
    runtime = _make_runtime(cognitive_journal=journal, records_store=None)
    svc = DiagnosticContextService(runtime, default_budget_tokens=200)
    bundle = await svc.assemble(query="cpu", budget_tokens=200)
    assert bundle.truncated is True


# --- Test 11: redistribution priority chain_traces fills before records -----
@pytest.mark.asyncio
async def test_redistribution_priority_order_chain_first() -> None:
    # Both tiers want extras. Chain traces should consume the redistribution
    # remainder before records, per _TIER_PRIORITY ordering.
    chain_rows = [
        {"chain_id": f"c{i}", "step_index": 0, "step_name": "evaluate",
         "sub_task_type": "cpu_step", "intent": "diagnose",
         "error_truncated": "", "communication_context": ""}
        for i in range(40)
    ]
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=chain_rows)

    record_entries = [
        {"path": f"r{i}", "frontmatter": {"title": "cpu doc", "classification": "ship"}}
        for i in range(40)
    ]
    record_contents = {f"r{i}": "cpu detail" for i in range(40)}
    store = _stub_records_store(record_entries, record_contents)

    runtime = _make_runtime(cognitive_journal=journal, records_store=store)
    svc = DiagnosticContextService(
        runtime, default_budget_tokens=2000, redistribute_remainder=True,
    )
    bundle = await svc.assemble(query="cpu", budget_tokens=2000)

    # In a tied-priority world both would have similar counts; here chain_traces
    # claims the remainder first so its post-pass-2 count exceeds records'.
    assert len(bundle.chain_traces) > len(bundle.records)


# --- Test 12: v1 backcompat — records=None + redistribute=False round-trip --
@pytest.mark.asyncio
async def test_v1_backcompat_chain_procedures_episodes_unchanged() -> None:
    # Mirror v1 test_procedure_exemplar_resolution shape but with new defaults
    # disabled — assert that procedure exemplar resolution still produces the
    # same bundle content (no records, no redistribution leakage).
    proc = SimpleNamespace(
        id="p1", name="diagnose cpu",
        description="Investigate cpu spikes via memory check",
        intent_types=["diagnose"], compilation_level=2,
        trace_exemplars=["ep_a"],
    )
    store = MagicMock()
    store.list_active = AsyncMock(return_value=[
        {"id": "p1", "name": "diagnose cpu",
         "description": "Investigate cpu spikes via memory check",
         "intent_types": ["diagnose"], "compilation_level": 2},
    ])
    store.get = AsyncMock(return_value=proc)

    ep_a = SimpleNamespace(
        id="ep_a", text="cpu spike narrative", agent_id="a1",
        agent_type="diagnostician", timestamp=1.0, importance=0.8,
        intent_type="diagnose",
    )
    episodic = MagicMock()
    episodic.get_by_ids = AsyncMock(return_value=[ep_a])

    runtime = _make_runtime(
        procedure_store=store, episodic_memory=episodic, records_store=None,
    )
    svc = DiagnosticContextService(
        runtime, default_budget_tokens=4000, redistribute_remainder=False,
    )
    bundle = await svc.assemble(query="cpu", budget_tokens=4000)

    assert bundle.records == []
    assert len(bundle.procedures) == 1
    assert bundle.procedures[0]["id"] == "p1"
    assert len(bundle.procedures[0]["exemplar_episodes"]) == 1
    assert len(bundle.episodes) == 1
    assert bundle.episodes[0]["id"] == "ep_a"
    assert bundle.truncated is False


# --- Sanity: module-level constants exposed for diagnostics -----------------
def test_module_level_caps_are_sane() -> None:
    assert _MAX_RECORDS_CANDIDATES > 0
    assert _RECORDS_CONTENT_EXCERPT_CHARS > 0
    assert _RECORDS_READER_ID == "_diagnostic_context_system"
