# Test Coverage Improvement — Close All Gaps to 90%+

*Better coverage = faster iteration. Every untested path is a trap for the next AD.*

## Context

Current test suite: **2,066 passed, 11 skipped, 0 failed** across 82% overall coverage (13,905 statements, 2,464 uncovered). This prompt targets the 10 files below 82% coverage, prioritized by impact (uncovered statement count × criticality). The goal is **90%+ coverage on each file** through focused unit tests that exercise the uncovered code paths.

**Current coverage report (files below target):**

| File | Statements | Covered | Coverage | Gap |
|------|-----------|---------|----------|-----|
| `experience/shell.py` | 605 | 335 | 55% | 270 uncovered |
| `runtime.py` | 1,414 | 1,119 | 79% | 295 uncovered |
| `cognitive/builder.py` | 930 | 753 | 81% | 177 uncovered |
| `experience/renderer.py` | 299 | 209 | 70% | 90 uncovered |
| `cognitive/self_mod.py` | 256 | 187 | 73% | 69 uncovered |
| `knowledge/store.py` | 374 | 307 | 82% | 67 uncovered |
| `knowledge/semantic.py` | 137 | 107 | 78% | 30 uncovered |
| `cognitive/dependency_resolver.py` | 111 | 81 | 73% | 30 uncovered |
| `cognitive/behavioral_monitor.py` | 80 | 59 | 74% | 21 uncovered |
| `cognitive/codebase_skill.py` | 28 | 13 | 46% | 15 uncovered |

## Pre-Build Audit

Read these files BEFORE writing any tests. Understand the existing test patterns.

1. `tests/test_experience.py` — existing shell/renderer tests, fixtures, helper functions
2. `tests/test_runtime.py` — existing runtime tests (largest test file)
3. `tests/test_builder_agent.py` — existing builder tests
4. `tests/test_self_mod.py` — existing self-mod tests
5. `tests/test_knowledge_store.py` — existing knowledge store tests
6. `tests/test_semantic_knowledge.py` — existing semantic layer tests
7. `tests/test_dependency_resolver.py` — existing dependency resolver tests

Then read the SOURCE files to understand the uncovered code paths:

8. `src/probos/experience/shell.py` — slash command handlers, approval callbacks
9. `src/probos/experience/renderer.py` — self-mod UX flow, escalation events
10. `src/probos/cognitive/self_mod.py` — skill pipeline, agent removal
11. `src/probos/cognitive/behavioral_monitor.py` — execution recording, trust tracking
12. `src/probos/cognitive/codebase_skill.py` — handler actions
13. `src/probos/knowledge/semantic.py` — indexing methods, reindex
14. `src/probos/knowledge/store.py` — git ops, rollback, artifact history
15. `src/probos/cognitive/dependency_resolver.py` — install chain, approval
16. `src/probos/runtime.py` — correction pipeline, warm boot, federation startup
17. `src/probos/cognitive/builder.py` — execute_approved_build subprocess, localization

## What to Build

Work through these steps IN ORDER. After each step, run:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Ensure all existing tests still pass before moving to the next step. If a test fails, fix it immediately before continuing.

---

### Step 1: `tests/test_behavioral_monitor.py` (NEW FILE)

Create a new test file for `BehavioralMonitor`. This is the smallest gap and will build confidence.

**What to test (21 uncovered statements):**

```python
"""Tests for BehavioralMonitor — execution recording, trust tracking, removal recommendations."""

from __future__ import annotations

import pytest
from probos.cognitive.behavioral_monitor import BehavioralMonitor


class TestRecordExecution:
    """Tests for record_execution() — lines 67-100."""

    def test_record_successful_execution(self):
        """Recording a successful execution updates tracking data."""
        bm = BehavioralMonitor()
        bm.record_execution("test_agent", "designed", success=True, duration_ms=100.0)
        status = bm.get_status()
        assert "test_agent" in status

    def test_record_failed_execution(self):
        """Recording a failed execution increments failure count."""
        bm = BehavioralMonitor()
        for _ in range(6):
            bm.record_execution("flaky_agent", "designed", success=False, duration_ms=50.0)
        alerts = bm.get_alerts()
        # After 5+ failures, should generate an alert
        assert len(alerts) > 0

    def test_untracked_agent_type_ignored(self):
        """Agent types not in the tracked set are silently ignored."""
        bm = BehavioralMonitor()
        bm.record_execution("builtin_agent", "some_unknown_type", success=True, duration_ms=100.0)
        status = bm.get_status()
        assert "builtin_agent" not in status

    def test_slow_execution_alert(self):
        """Consistently slow executions trigger an alert after threshold."""
        bm = BehavioralMonitor()
        for _ in range(4):
            bm.record_execution("slow_agent", "designed", success=True, duration_ms=30000.0)
        alerts = bm.get_alerts()
        assert any("slow" in str(a).lower() for a in alerts)


class TestTrustTrajectory:
    """Tests for check_trust_trajectory() — lines 104-121."""

    def test_stable_trust_no_alert(self):
        """Stable trust scores produce no decline alert."""
        bm = BehavioralMonitor()
        bm.record_execution("stable_agent", "designed", success=True, duration_ms=100.0)
        bm.check_trust_trajectory("stable_agent", 0.9)
        bm.check_trust_trajectory("stable_agent", 0.9)
        bm.check_trust_trajectory("stable_agent", 0.9)
        alerts = bm.get_alerts(agent_type="stable_agent")
        trust_alerts = [a for a in alerts if "trust" in str(a).lower() or "decline" in str(a).lower()]
        assert len(trust_alerts) == 0

    def test_declining_trust_triggers_alert(self):
        """Consistently declining trust triggers a decline alert."""
        bm = BehavioralMonitor()
        bm.record_execution("declining_agent", "designed", success=True, duration_ms=100.0)
        # Simulate steady decline
        for score in [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5]:
            bm.check_trust_trajectory("declining_agent", score)
        alerts = bm.get_alerts()
        assert len(alerts) > 0


class TestGetAlerts:
    """Tests for get_alerts() with agent_type filter — line 126."""

    def test_filter_by_agent_type(self):
        """get_alerts(agent_type=...) filters to matching agent only."""
        bm = BehavioralMonitor()
        for _ in range(6):
            bm.record_execution("agent_a", "designed", success=False, duration_ms=50.0)
        for _ in range(6):
            bm.record_execution("agent_b", "designed", success=False, duration_ms=50.0)
        a_alerts = bm.get_alerts(agent_type="agent_a")
        b_alerts = bm.get_alerts(agent_type="agent_b")
        # Each should only see their own alerts, not the other's
        assert len(a_alerts) > 0
        assert len(b_alerts) > 0


class TestGetStatus:
    """Tests for get_status() — lines 131-142."""

    def test_status_dict_structure(self):
        """get_status() returns dict with expected keys per agent."""
        bm = BehavioralMonitor()
        bm.record_execution("my_agent", "designed", success=True, duration_ms=200.0)
        status = bm.get_status()
        assert "my_agent" in status


class TestShouldRecommendRemoval:
    """Tests for should_recommend_removal() — lines 151-166."""

    def test_no_recommendation_for_healthy_agent(self):
        """Healthy agent is not recommended for removal."""
        bm = BehavioralMonitor()
        bm.record_execution("good_agent", "designed", success=True, duration_ms=100.0)
        assert bm.should_recommend_removal("good_agent") is False

    def test_recommendation_for_high_failure_rate(self):
        """Agent with >80% failure rate across 5+ executions is recommended for removal."""
        bm = BehavioralMonitor()
        for _ in range(10):
            bm.record_execution("bad_agent", "designed", success=False, duration_ms=50.0)
        assert bm.should_recommend_removal("bad_agent") is True

    def test_recommendation_for_trust_decline(self):
        """Agent with sustained trust decline is recommended for removal."""
        bm = BehavioralMonitor()
        bm.record_execution("untrusted_agent", "designed", success=True, duration_ms=100.0)
        for score in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]:
            bm.check_trust_trajectory("untrusted_agent", score)
        # May or may not recommend depending on window size — test the call doesn't crash
        result = bm.should_recommend_removal("untrusted_agent")
        assert isinstance(result, bool)

    def test_unknown_agent_not_recommended(self):
        """Unknown agent returns False (not crash)."""
        bm = BehavioralMonitor()
        assert bm.should_recommend_removal("nonexistent") is False
```

Adapt the above to match the actual constructor signature and method signatures in `behavioral_monitor.py`. The key is to exercise:
- `record_execution()` with untracked agent type (early return) and the failure/slow alerting paths
- `check_trust_trajectory()` with stable and declining trust
- `get_alerts()` with and without `agent_type` filter
- `get_status()` structure
- `should_recommend_removal()` for healthy, failing, declining, and unknown agents

---

### Step 2: `tests/test_codebase_skill.py` (NEW FILE)

Create a new test file for `CodebaseSkill`. Only 28 statements total — easy to hit 90%+.

**What to test (15 uncovered statements — all handler actions):**

```python
"""Tests for CodebaseSkill handler actions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from probos.cognitive.codebase_skill import CodebaseSkillHandler


class TestCodebaseSkillHandler:
    """Tests for all handler actions — lines 37-68."""

    @pytest.fixture
    def handler(self):
        """Create a CodebaseSkillHandler with mocked CodebaseIndex."""
        # Check the actual constructor signature and adapt
        h = CodebaseSkillHandler.__new__(CodebaseSkillHandler)
        # Set up whatever internal state the handler needs
        return h

    @pytest.mark.asyncio
    async def test_read_source_action(self, handler):
        """'read_source' action returns file content."""
        # Construct an IntentMessage with action='read_source' and call handler
        pass  # Fill in based on actual handler interface

    @pytest.mark.asyncio
    async def test_get_agent_map_action(self, handler):
        """'get_agent_map' action returns the agent type map."""
        pass

    @pytest.mark.asyncio
    async def test_get_layer_map_action(self, handler):
        """'get_layer_map' action returns the architecture layer map."""
        pass

    @pytest.mark.asyncio
    async def test_get_config_schema_action(self, handler):
        """'get_config_schema' action returns config schema info."""
        pass

    @pytest.mark.asyncio
    async def test_get_api_surface_action(self, handler):
        """'get_api_surface' action returns API surface data."""
        pass

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, handler):
        """Unknown action returns an error IntentResult."""
        pass

    @pytest.mark.asyncio
    async def test_exception_handling(self, handler):
        """Exception during handling returns error IntentResult (lines 67-68)."""
        pass
```

Read `src/probos/cognitive/codebase_skill.py` to understand the exact handler interface (how it receives intents, what CodebaseIndex methods it calls, what it returns). Then fill in each test with proper mocking of `CodebaseIndex`. Each test should verify the `IntentResult` has `success=True` (or `False` for error cases) and contains expected data.

---

### Step 3: Add to `tests/test_semantic_knowledge.py` — Semantic Layer Gaps

**What to test (30 uncovered statements):**

Add a new test class to the EXISTING `tests/test_semantic_knowledge.py` file:

```python
class TestSemanticIndexing:
    """Tests for index_*() methods and reindex_from_store() — cover lines 89-374."""

    @pytest.fixture
    def semantic_layer(self, tmp_path):
        """Create a SemanticKnowledgeLayer with test ChromaDB path."""
        return SemanticKnowledgeLayer(persist_dir=str(tmp_path / "chroma"))

    def test_index_agent_none_collection(self, semantic_layer):
        """index_agent() returns early when collection is None."""
        # Mock _collection to be None, verify no exception
        pass

    def test_index_skill_success(self, semantic_layer):
        """index_skill() indexes a skill into the collection."""
        pass

    def test_index_workflow_success(self, semantic_layer):
        """index_workflow() indexes a workflow entry."""
        pass

    def test_index_qa_report_success(self, semantic_layer):
        """index_qa_report() indexes a QA report."""
        pass

    def test_index_event_success(self, semantic_layer):
        """index_event() indexes an event."""
        pass

    def test_search_exception_handling(self, semantic_layer):
        """search() catches ChromaDB exceptions gracefully (lines 259-260)."""
        # Mock _collection.query to raise an exception
        pass

    def test_stats_exception_handling(self, semantic_layer):
        """stats() catches exception when getting collection count (lines 297-298)."""
        pass

    @pytest.mark.asyncio
    async def test_reindex_from_store(self, semantic_layer):
        """reindex_from_store() loads and re-indexes all artifact types (lines 321-374)."""
        # Create a mock KnowledgeStore with agents, skills, workflows, QA reports
        # Call reindex and verify items were indexed
        pass
```

Read `src/probos/knowledge/semantic.py` to get exact method signatures and ChromaDB interaction patterns. Mock the ChromaDB collection where needed. The `_collection is None` early returns are the easiest wins.

---

### Step 4: Add to `tests/test_dependency_resolver.py` — Install Chain & Approval

**What to test (30 uncovered statements):**

Add test classes to the EXISTING `tests/test_dependency_resolver.py`:

```python
class TestResolveApprovalFlow:
    """Tests for resolve() user approval — lines 132-133."""

    @pytest.mark.asyncio
    async def test_approval_fn_exception_propagates(self):
        """When approval_fn raises, resolve() propagates the exception."""
        async def bad_approval(pkgs):
            raise RuntimeError("User cancelled")
        r = _resolver(allowed=[], approval_fn=bad_approval)
        result = await r.resolve("import unknown_pkg\n")
        # Should handle gracefully — check actual behavior
        assert isinstance(result, DependencyResult)

    @pytest.mark.asyncio
    async def test_approval_fn_denies_install(self):
        """When approval_fn returns denial, package is not installed."""
        async def deny_approval(pkgs):
            return False
        r = _resolver(allowed=[], approval_fn=deny_approval)
        source = "import some_random_package\n"
        result = await r.resolve(source)
        assert not result.installed


class TestInstallPackage:
    """Tests for _install_package() — lines 151-226."""

    @pytest.mark.asyncio
    async def test_install_success_but_not_found(self):
        """pip install succeeds but find_spec still returns None (lines 151-152)."""
        r = _resolver()
        with patch("subprocess.run") as mock_run, \
             patch("importlib.util.find_spec", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            result = await r._install_package("nonexistent_pkg")
            assert result is False  # Installed but not importable

    @pytest.mark.asyncio
    async def test_pip_fallback_to_uv(self):
        """When pip install fails, falls back to uv pip install (lines 179-226)."""
        r = _resolver()
        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # pip fails
                return MagicMock(returncode=1, stderr="pip error")
            # uv succeeds
            return MagicMock(returncode=0)
        with patch("subprocess.run", side_effect=mock_run), \
             patch("importlib.util.find_spec", return_value=MagicMock()):
            result = await r._install_package("some_pkg")


class TestDetectMissingEdgeCases:
    """Tests for detect_missing() edge cases — lines 100-105."""

    def test_find_spec_raises_module_not_found(self):
        """ModuleNotFoundError from find_spec is caught (line 100-101)."""
        r = _resolver(allowed=["collections"])
        with patch("importlib.util.find_spec", side_effect=ModuleNotFoundError):
            missing = r.detect_missing("import collections\n")
            # Should treat as missing or handle gracefully
            assert isinstance(missing, list)

    def test_find_spec_raises_value_error(self):
        """ValueError from find_spec is caught (line 101)."""
        r = _resolver(allowed=["weird_mod"])
        with patch("importlib.util.find_spec", side_effect=ValueError):
            missing = r.detect_missing("import weird_mod\n")
            assert isinstance(missing, list)

    def test_probos_import_skipped(self):
        """Imports starting with 'probos' are skipped (line 105)."""
        r = _resolver(allowed=[])
        missing = r.detect_missing("from probos.types import IntentMessage\n")
        # probos imports should never be in missing list
        assert not any("probos" in m for m in missing)
```

Read `src/probos/cognitive/dependency_resolver.py` to verify the actual method signatures, the `_install_package()` fallback chain structure, and how `detect_missing()` handles exceptions. Adapt mocking accordingly.

---

### Step 5: Add to `tests/test_knowledge_store.py` — Git Ops & Rollback

**What to test (67 uncovered statements):**

Add test classes to the EXISTING `tests/test_knowledge_store.py`:

```python
class TestKnowledgeStoreErrorPaths:
    """Tests for error handling in load_*() methods."""

    @pytest.mark.asyncio
    async def test_load_episodes_corrupt_file(self, tmp_path):
        """Individual corrupt episode file doesn't crash load_episodes() (lines 114-115)."""
        # Create a KnowledgeStore with a valid repo path
        # Write a corrupt JSON file in the episodes directory
        # Call load_episodes() — should log warning, not crash

    @pytest.mark.asyncio
    async def test_load_agents_corrupt_file(self, tmp_path):
        """Corrupt agent file doesn't crash load_agents() (lines 163-176)."""
        pass

    @pytest.mark.asyncio
    async def test_load_skills_corrupt_file(self, tmp_path):
        """Corrupt skill file doesn't crash load_skills() (lines 203-216)."""
        pass

    @pytest.mark.asyncio
    async def test_load_trust_snapshot_missing(self, tmp_path):
        """Missing trust snapshot file returns empty dict (lines 239-241)."""
        pass

    @pytest.mark.asyncio
    async def test_load_routing_weights_missing(self, tmp_path):
        """Missing routing weights file returns empty dict (lines 260-262)."""
        pass

    @pytest.mark.asyncio
    async def test_load_workflows_corrupt(self, tmp_path):
        """Corrupt workflows file handled gracefully (lines 286-288)."""
        pass

    @pytest.mark.asyncio
    async def test_load_qa_reports_corrupt(self, tmp_path):
        """Corrupt QA reports file handled gracefully (lines 304-312)."""
        pass

    @pytest.mark.asyncio
    async def test_load_manifest_corrupt(self, tmp_path):
        """Corrupt manifest file handled gracefully (lines 333-335)."""
        pass


class TestKnowledgeStoreGitOps:
    """Tests for git operations — _ensure_repo, _git_commit, rollback, history."""

    @pytest.mark.asyncio
    async def test_ensure_repo_initializes_git(self, tmp_path):
        """_ensure_repo() runs git init when no .git exists (lines 379-395)."""
        pass

    @pytest.mark.asyncio
    async def test_git_commit_failure_warns(self, tmp_path):
        """Failed git commit logs warning, doesn't crash (line 450)."""
        pass

    @pytest.mark.asyncio
    async def test_rollback_artifact(self, tmp_path):
        """rollback_artifact() restores a previous version (lines 497-531)."""
        pass

    @pytest.mark.asyncio
    async def test_artifact_history(self, tmp_path):
        """artifact_history() returns commit log for an artifact (lines 541-569)."""
        pass

    @pytest.mark.asyncio
    async def test_artifact_path_mapping(self, tmp_path):
        """_artifact_path() correctly maps all artifact types (lines 576-587)."""
        pass

    @pytest.mark.asyncio
    async def test_recent_commits(self, tmp_path):
        """recent_commits() returns repo-wide commit log (lines 602-626)."""
        pass

    @pytest.mark.asyncio
    async def test_meta_info(self, tmp_path):
        """meta_info() reads schema version from meta.json (lines 625-632)."""
        pass


class TestKnowledgeStoreScheduling:
    """Tests for debounce and flush — lines 408-430."""

    @pytest.mark.asyncio
    async def test_schedule_commit_runtime_error(self, tmp_path):
        """_schedule_commit() handles RuntimeError for missing event loop (lines 421-423)."""
        pass

    @pytest.mark.asyncio
    async def test_flush_pending_empty(self, tmp_path):
        """_flush_pending() is a no-op when no pending messages (line 430)."""
        pass

    @pytest.mark.asyncio
    async def test_default_repo_path(self, tmp_path):
        """When config.repo_path is empty, defaults to ~/.probos/knowledge/ (line 42)."""
        pass
```

Read `src/probos/knowledge/store.py` to understand the actual class constructor, how git operations work, and what each method expects. For git operation tests, use `tmp_path` fixtures to create isolated test directories. Mock `subprocess.run` for git commands where appropriate.

---

### Step 6: Add to `tests/test_experience.py` — Shell Command Handlers

This is the **highest impact** step. The `shell.py` file is at 55% coverage — nearly all slash command handlers are untested.

**What to test (270 uncovered statements):**

Add new test classes to the EXISTING `tests/test_experience.py`:

```python
# -----------------------------------------------------------------------
# Shell command handler tests
# -----------------------------------------------------------------------


class TestShellHistoryCommand:
    """Tests for _cmd_history() — lines 261-262."""

    @pytest.mark.asyncio
    async def test_history_with_episodic_memory(self, shell, console):
        """The /history command displays episodic memory entries."""
        # Mock runtime's episodic memory to return some episodes
        # Call shell._cmd_history([])
        # Verify console output contains episode info
        pass

    @pytest.mark.asyncio
    async def test_history_empty(self, shell, console):
        """The /history command handles no episodes gracefully."""
        pass


class TestShellRecallCommand:
    """Tests for _cmd_recall() — lines 284-289."""

    @pytest.mark.asyncio
    async def test_recall_with_query(self, shell, console):
        """The /recall command performs semantic search on episodic memory."""
        pass

    @pytest.mark.asyncio
    async def test_recall_no_results(self, shell, console):
        """The /recall command handles no results gracefully."""
        pass


class TestShellDreamCommand:
    """Tests for _cmd_dream() — lines 326-327."""

    @pytest.mark.asyncio
    async def test_dream_displays_report(self, shell, console):
        """The /dream command displays dream report."""
        pass


class TestShellFederationCommand:
    """Tests for _cmd_federation() and _cmd_peers() — lines 335-343."""

    @pytest.mark.asyncio
    async def test_federation_status(self, shell, console):
        """The /federation command shows federation status."""
        pass

    @pytest.mark.asyncio
    async def test_peers_display(self, shell, console):
        """The /peers command shows peer node models."""
        pass


class TestShellDesignedCommand:
    """Tests for _cmd_designed() — lines 347-351."""

    @pytest.mark.asyncio
    async def test_designed_empty(self, shell, console):
        """The /designed command with no designed agents shows empty message."""
        pass

    @pytest.mark.asyncio
    async def test_designed_with_behavioral_monitor(self, shell, console):
        """The /designed command includes behavioral monitor data when present."""
        pass


class TestShellKnowledgeCommand:
    """Tests for _cmd_knowledge() — lines 377-378."""

    @pytest.mark.asyncio
    async def test_knowledge_status(self, shell, console):
        """The /knowledge command shows knowledge store status."""
        pass


class TestShellQACommand:
    """Tests for _cmd_qa() — lines 360-367."""

    @pytest.mark.asyncio
    async def test_qa_with_reports(self, shell, console):
        """The /qa command displays QA report details."""
        pass


class TestShellPlanCommand:
    """Tests for _cmd_plan() — lines 449-486."""

    @pytest.mark.asyncio
    async def test_plan_with_capability_gap(self, shell, console):
        """The /plan command shows self-mod proposal for capability gap."""
        pass


class TestShellSearchCommand:
    """Tests for _cmd_search() — lines 720-737."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, shell, console):
        """The /search command returns semantic search results."""
        pass

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, shell, console):
        """The /search command supports type filtering."""
        pass


class TestShellImportsCommand:
    """Tests for _cmd_imports() — lines 838-867."""

    @pytest.mark.asyncio
    async def test_imports_list(self, shell, console):
        """The /imports command lists allowed imports."""
        pass

    @pytest.mark.asyncio
    async def test_imports_add(self, shell, console):
        """The /imports add <module> adds to whitelist."""
        pass

    @pytest.mark.asyncio
    async def test_imports_remove(self, shell, console):
        """The /imports remove <module> removes from whitelist."""
        pass


class TestShellApprovalCallbacks:
    """Tests for user approval callback methods — lines 939-1053."""

    @pytest.mark.asyncio
    async def test_user_escalation_callback(self, shell, console):
        """_user_escalation_callback() presents escalation choices (lines 939-979)."""
        # Mock input to provide a choice
        pass

    @pytest.mark.asyncio
    async def test_user_self_mod_approval(self, shell, console):
        """_user_self_mod_approval() prompts for self-mod approval (lines 987-1001)."""
        pass

    @pytest.mark.asyncio
    async def test_user_import_approval(self, shell, console):
        """_user_import_approval() prompts for import approval (lines 1009-1028)."""
        pass

    @pytest.mark.asyncio
    async def test_user_dep_install_approval(self, shell, console):
        """_user_dep_install_approval() prompts for dep install (lines 1036-1053)."""
        pass
```

**IMPORTANT**: The shell command handlers call `self.runtime.*` methods internally. Mock these runtime methods appropriately — do NOT try to run a full runtime for shell tests. Use the existing `shell` fixture from test_experience.py and mock runtime attributes as needed. For approval callbacks, mock `input()` or `console.input()` to provide simulated user responses.

---

### Step 7: Add to `tests/test_experience.py` — Renderer Gaps

**What to test (90 uncovered statements):**

Add test classes for renderer gaps:

```python
# -----------------------------------------------------------------------
# Renderer tests
# -----------------------------------------------------------------------


class TestRendererSelfModFlow:
    """Tests for self-mod strategy display — lines 150-311."""

    @pytest.fixture
    def renderer(self, runtime, console):
        """Create an ExecutionRenderer."""
        return ExecutionRenderer(runtime, console=console)

    @pytest.mark.asyncio
    async def test_self_mod_strategy_display(self, renderer, console):
        """Renderer displays self-mod strategy options when capability gap detected."""
        # Mock the runtime to have a pending self-mod proposal
        # Call the appropriate renderer method
        # Verify console output contains strategy options
        pass


class TestRendererEscalationEvents:
    """Tests for escalation event handling — lines 376-466."""

    @pytest.fixture
    def renderer(self, runtime, console):
        return ExecutionRenderer(runtime, console=console)

    @pytest.mark.asyncio
    async def test_escalation_start_event(self, renderer, console):
        """Renderer handles escalation start event (lines 396-397)."""
        pass

    @pytest.mark.asyncio
    async def test_escalation_resolved_event(self, renderer, console):
        """Renderer handles escalation resolved event (lines 409-410)."""
        pass

    @pytest.mark.asyncio
    async def test_escalation_exhausted_event(self, renderer, console):
        """Renderer handles escalation exhausted event."""
        pass


class TestRendererProgressTable:
    """Tests for _build_progress_table() — lines 485-497."""

    @pytest.fixture
    def renderer(self, runtime, console):
        return ExecutionRenderer(runtime, console=console)

    def test_progress_table_structure(self, renderer):
        """_build_progress_table() returns a Rich Table with expected columns."""
        pass

    def test_progress_table_with_results(self, renderer):
        """Progress table renders with actual execution results."""
        pass
```

Read `src/probos/experience/renderer.py` to understand the event handler registration pattern. Many of these handlers are called from `_on_*` callback methods registered during `render_execution()`. Test them by calling the callbacks directly with mock event data.

---

### Step 8: Add to `tests/test_self_mod.py` — Skill Pipeline & Agent Removal

**What to test (69 uncovered statements):**

Add test classes to the EXISTING `tests/test_self_mod.py`:

```python
class TestHandleAddSkill:
    """Tests for handle_add_skill() pipeline — lines 392-482."""

    @pytest.mark.asyncio
    async def test_add_skill_max_limit(self):
        """handle_add_skill() rejects when max skill limit reached."""
        pass

    @pytest.mark.asyncio
    async def test_add_skill_design_and_validate(self):
        """handle_add_skill() designs, validates, and compiles a skill."""
        pass

    @pytest.mark.asyncio
    async def test_add_skill_compilation_failure(self):
        """handle_add_skill() handles compilation failure gracefully."""
        pass


class TestDesignedAgentStatus:
    """Tests for designed_agent_status() — lines 513-522."""

    @pytest.mark.asyncio
    async def test_status_with_agents(self):
        """designed_agent_status() returns summary of designed agents."""
        pass

    @pytest.mark.asyncio
    async def test_status_empty(self):
        """designed_agent_status() returns empty list when no agents exist."""
        pass


class TestRemoveDesignedAgent:
    """Tests for remove_designed_agent() — lines 543-571."""

    @pytest.mark.asyncio
    async def test_remove_existing_agent(self):
        """remove_designed_agent() cleans up all references."""
        # Verify: unsubscribe from intent bus, unregister from capability registry,
        # stop pool, remove from knowledge store
        pass

    @pytest.mark.asyncio
    async def test_remove_nonexistent_agent(self):
        """remove_designed_agent() handles missing agent gracefully."""
        pass


class TestSelfModErrorPaths:
    """Tests for error handling paths — lines 135-216."""

    @pytest.mark.asyncio
    async def test_user_approval_rejection(self):
        """When _user_approval_fn raises, pipeline handles gracefully (lines 135-136)."""
        pass

    @pytest.mark.asyncio
    async def test_research_failure(self):
        """Research phase exception is handled (lines 157-158)."""
        pass

    @pytest.mark.asyncio
    async def test_design_failure_creates_record(self):
        """Design failure creates a failed_design record (lines 175-187)."""
        pass

    @pytest.mark.asyncio
    async def test_import_approval_flow(self):
        """When validation fails only on imports, approval flow is triggered (lines 196-216)."""
        pass

    @pytest.mark.asyncio
    async def test_registration_failure(self):
        """Registration failure is handled (lines 311-312)."""
        pass

    @pytest.mark.asyncio
    async def test_pool_creation_failure(self):
        """Pool creation failure is handled (lines 316-348)."""
        pass
```

Read `src/probos/cognitive/self_mod.py` to understand the `SelfModPipeline` constructor, how `handle_add_skill()` works, and what `DesignedAgentRecord` looks like. Mock the LLM client, agent designer, code validator, and knowledge store.

---

### Step 9: Add to `tests/test_runtime.py` — Correction Pipeline & Warm Boot

**What to test (selected high-value paths from 295 uncovered):**

Target the most critical uncovered paths in runtime. Do NOT try to cover everything — focus on:

Add test classes to the EXISTING `tests/test_runtime.py`:

```python
class TestApplyCorrection:
    """Tests for apply_correction() pipeline — lines 1942-2028."""

    @pytest.mark.asyncio
    async def test_apply_skill_correction(self, runtime):
        """apply_correction() for a skill updates the skill handler."""
        pass

    @pytest.mark.asyncio
    async def test_apply_agent_correction(self, runtime):
        """apply_correction() for an agent hot-swaps the agent class."""
        pass

    @pytest.mark.asyncio
    async def test_apply_correction_auto_retry(self, runtime):
        """apply_correction() auto-retries the original request on success."""
        pass


class TestSelfModelVerification:
    """Tests for _verify_response() edge cases — lines 1268-1301."""

    @pytest.mark.asyncio
    async def test_fabricated_department_detection(self, runtime):
        """_verify_response() catches fabricated department claims (lines 1268-1269)."""
        pass

    @pytest.mark.asyncio
    async def test_system_mode_contradiction(self, runtime):
        """_verify_response() catches dreaming state contradictions (lines 1283-1284)."""
        pass


class TestConversationHistoryEnrichment:
    """Tests for conversation context enrichment — lines 1508-1515."""

    @pytest.mark.asyncio
    async def test_conversation_history_with_dag(self, runtime):
        """When conversation_history has a DAG, context is enriched with prior intent summary."""
        pass


class TestCorrectionDetection:
    """Tests for correction detection in NL pipeline — lines 1459-1504."""

    @pytest.mark.asyncio
    async def test_correction_detected_and_applied(self, runtime):
        """When correction detector finds a correction, patch is applied."""
        pass
```

Read `src/probos/runtime.py` around the listed line ranges. For `apply_correction()`, you'll need a mock `CorrectionRecord`. For `_verify_response()`, construct response dicts that trigger the fabrication/contradiction checks. Use the existing runtime fixture from `test_runtime.py`.

---

### Step 10: Add to `tests/test_builder_agent.py` — Builder Edge Cases

**What to test (selected high-value paths from 177 uncovered):**

Add test classes to the EXISTING `tests/test_builder_agent.py`:

```python
class TestFindUnresolvedNamesEdgeCases:
    """Tests for _find_unresolved_names() AST node handling — lines 1101-1144."""

    def test_vararg_in_function(self):
        """*args parameter is recognized as defined name."""
        source = "def foo(*args): pass"
        defined, used = _find_unresolved_names(source)
        assert "args" in defined

    def test_kwarg_in_function(self):
        """**kwargs parameter is recognized as defined name."""
        source = "def foo(**kwargs): pass"
        defined, used = _find_unresolved_names(source)
        assert "kwargs" in defined

    def test_kwonlyargs(self):
        """Keyword-only args after * are recognized."""
        source = "def foo(*, key): pass"
        defined, used = _find_unresolved_names(source)
        assert "key" in defined

    def test_tuple_assignment(self):
        """Tuple unpacking targets are recognized."""
        source = "a, b = 1, 2"
        defined, used = _find_unresolved_names(source)
        assert "a" in defined
        assert "b" in defined

    def test_annotated_assignment(self):
        """Annotated assignments (x: int = 1) are recognized."""
        source = "x: int = 1"
        defined, used = _find_unresolved_names(source)
        assert "x" in defined

    def test_for_loop_variable(self):
        """For loop variable is recognized as defined."""
        source = "for i in range(10): pass"
        defined, used = _find_unresolved_names(source)
        assert "i" in defined

    def test_with_statement_variable(self):
        """With statement 'as' variable is recognized."""
        source = "with open('f') as fp: pass"
        defined, used = _find_unresolved_names(source)
        assert "fp" in defined

    def test_except_handler_variable(self):
        """Exception handler 'as' variable is recognized."""
        source = "try:\n    pass\nexcept Exception as e:\n    pass"
        defined, used = _find_unresolved_names(source)
        assert "e" in defined

    def test_comprehension_variable(self):
        """Comprehension target variable is recognized."""
        source = "result = [x for x in range(10)]"
        defined, used = _find_unresolved_names(source)
        assert "x" in defined


class TestValidateAssemblyChecks:
    """Tests for validate_assembly() detailed checks — lines 1215-1279."""

    def test_duplicate_definition_detected(self):
        """validate_assembly() detects duplicate function definitions across chunks."""
        pass

    def test_modify_block_invalid_search_string(self):
        """validate_assembly() flags MODIFY blocks with search strings not found in target."""
        pass

    def test_interface_contract_violation(self):
        """validate_assembly() checks interface contracts between chunks."""
        pass


class TestLocalizeContext:
    """Tests for _localize_context() — lines 1492-1609."""

    @pytest.mark.asyncio
    async def test_localize_sends_outline_prompt(self):
        """_localize_context() sends AST outline to fast-tier LLM."""
        pass

    @pytest.mark.asyncio
    async def test_localize_fallback_truncation(self):
        """_localize_context() falls back to head/tail truncation on LLM failure."""
        pass


class TestFallbackTruncate:
    """Tests for _fallback_truncate() — lines 1614-1627."""

    def test_short_content_unchanged(self):
        """Content under 15K chars is returned as-is."""
        result = _fallback_truncate("short content")
        assert result == "short content"

    def test_long_content_truncated(self):
        """Content over 15K chars is truncated to head + tail."""
        long_content = "x\n" * 20000
        result = _fallback_truncate(long_content)
        assert len(result) < len(long_content)
        assert "..." in result or "truncated" in result.lower()


class TestTransporterBuildEdgeCases:
    """Tests for transporter_build() edge cases — lines 1034-1035."""

    @pytest.mark.asyncio
    async def test_empty_decomposition_returns_empty(self):
        """transporter_build() returns empty list when decomposition produces no chunks."""
        pass
```

Read `src/probos/cognitive/builder.py` to get exact signatures for `_find_unresolved_names`, `_fallback_truncate`, `validate_assembly`, and `_localize_context`. For `_find_unresolved_names`, the tests are pure unit tests (AST parsing, no mocking needed). For `_localize_context`, mock the LLM client.

---

## Implementation Constraints

1. **No new dependencies.** All tests use `pytest`, `pytest-asyncio`, `unittest.mock`, and existing test utilities.
2. **Backward compatible.** No modifications to any source file in `src/probos/`. Only add or modify test files.
3. **Each step must leave all tests passing.** Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after every step. Fix any failures before proceeding.
4. **Match existing patterns.** Follow the code style, fixture patterns, and mock patterns already used in the test files you read in the pre-build audit.
5. **Use `tmp_path` for filesystem tests.** Never write to real directories.
6. **Mock LLM calls.** Use `MockLLMClient` or `AsyncMock` — never make real LLM calls.
7. **Mock subprocess calls.** Use `unittest.mock.patch("subprocess.run")` for git/pip commands.
8. **Test names must be descriptive.** Follow the `test_<what>_<expected>` pattern used throughout the codebase.
9. **Async tests use `@pytest.mark.asyncio`.** Match the existing async test patterns.
10. **Do NOT modify dashboard.html, PROGRESS.md, or DECISIONS.md.** This is a test-only change.

## Test Execution

After all steps are complete, run the full suite with coverage:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ --cov=src/probos --cov-report=term-missing -q
```

Verify:
- All tests pass (0 failures)
- Each target file is now at 85%+ coverage (ideally 90%+)
- No existing tests were broken

## Do NOT Build

- Do NOT modify any source code in `src/probos/` — this prompt is test-only
- Do NOT add integration tests that require a running server, network, or real LLM
- Do NOT add tests for `federation/transport.py` (requires real ZeroMQ, covered separately)
- Do NOT add slow tests (each test should complete in < 2 seconds)
- Do NOT update PROGRESS.md, DECISIONS.md, or dashboard.html
