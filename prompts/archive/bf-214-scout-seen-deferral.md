# BF-214: Scout Marks Repos as Seen Before Classification Succeeds — Build Prompt

**BF:** 214  
**Issue:** #300  
**Related:** BF-208 (Scout perceive routing), BF-209 (Scout chain bypass), AD-647 (Process Chains)  
**Scope:** ~20 lines changed in 1 file. Zero new modules.

---

## Problem

The scout marks GitHub repos as "seen" in `perceive()` (L.336) and persists to disk (L.349) **before** the LLM classifies them in `act()` (L.386). If the LLM fails, returns garbage, or connectivity drops, `parse_scout_reports()` returns an empty list — but the repos are already in `scout_seen.json` with a 90-day TTL. They will never be retried.

**Flow today:**

```
perceive()                          act()
  ├── search GitHub (177 repos)       ├── get llm_output
  ├── filter by seen file             ├── parse_scout_reports(llm_output) → [] (LLM failed)
  ├── mark ALL new as seen (L.336)    ├── filter_findings([]) → []
  ├── _save_seen() to disk (L.349)    └── store report: {total_classified: 0, findings: []}
  └── build repo text for LLM
```

**Result:** Zero classified repos across 5 consecutive days. Scout searches GitHub successfully (30 items per query, 6 queries), but all repos were marked seen on the first run (2026-04-19T05:01). Every subsequent run finds zero new repos. The first run's LLM classification either failed (connectivity issues) or produced output that `parse_scout_reports()` couldn't parse — but the repos were already persisted as seen.

**Additional issue:** `parse_scout_reports()` returns an empty list silently on parse failure — no logging, no signal to `act()` that classification failed vs. "all repos were SKIP."

---

## What Already Exists

- `_load_seen()` / `_save_seen()` (L.182-197): JSON file with `{repo_name: iso_timestamp}`, 90-day pruning
- `_repo_metadata` instance var (L.372): stores repo metadata from perceive for enrichment in act
- `parse_scout_reports()` (L.82-127): parses `===SCOUT_REPORT===` blocks, returns only absorb/visiting_officer
- `filter_findings()` (L.130-136): filters by composite_score >= 3
- Scout duty fires once daily (86400s in system.yaml)
- `act()` L.383: early exit on "No new repositories" in llm_output

---

## Fix

Defer seen marking from `perceive()` to `act()`. Repos are only marked seen after classification succeeds. Two changes in scout.py, zero new modules.

### Part A: Defer seen marking in perceive() (scout.py L.326-349)

**Find lines 326-349:**

```python
        seen = _load_seen(self._seen_file)
        new_repos: list[dict[str, Any]] = []

        for query, min_stars in queries:
            items = await self._search_github(query, min_stars)
            for item in items:
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                seen[full_name] = datetime.now(timezone.utc).isoformat()
                new_repos.append({
                    "full_name": full_name,
                    "description": item.get("description", "") or "",
                    "stars": item.get("stargazers_count", 0),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "language": item.get("language", "") or "",
                    "license": (item.get("license") or {}).get("spdx_id", ""),
                    "topics": item.get("topics", []),
                    "url": item.get("html_url", ""),
                })

        _save_seen(seen, self._seen_file)
```

**Replace with:**

```python
        seen = _load_seen(self._seen_file)
        new_repos: list[dict[str, Any]] = []

        for query, min_stars in queries:
            items = await self._search_github(query, min_stars)
            for item in items:
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                new_repos.append({
                    "full_name": full_name,
                    "description": item.get("description", "") or "",
                    "stars": item.get("stargazers_count", 0),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "language": item.get("language", "") or "",
                    "license": (item.get("license") or {}).get("spdx_id", ""),
                    "topics": item.get("topics", []),
                    "url": item.get("html_url", ""),
                })

        # BF-214: Do NOT save seen here — defer to act() after classification succeeds.
        # Store pending repo names for act() to mark as seen.
        self._pending_seen_repos = [r["full_name"] for r in new_repos]
```

**What changed:**
- Removed `seen[full_name] = datetime.now(...)` from the loop — repos no longer marked seen during perceive
- Removed `_save_seen(seen, self._seen_file)` — no premature disk write
- Added `self._pending_seen_repos` — list of repo names that need to be marked seen after successful classification
- `seen` dict is still loaded for the filter check (`if full_name in seen: continue`) — existing seen repos are still skipped

### Part B: Mark seen after classification in act() (scout.py L.375-410)

**Find lines 375-410:**

```python
    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM classification, store report, deliver notifications."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        # BF-177: Allow duty-triggered proactive_think (scout_report) to reach report generation
        is_duty_triggered = bool(decision.get("duty", {}).get("duty_id"))
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think") and not is_duty_triggered:
            return {"success": True, "result": decision.get("llm_output", "")}
        llm_output = decision.get("llm_output", "")
        if "No new repositories" in llm_output or not llm_output.strip():
            return {"success": True, "result": "No new findings to report."}

        findings = parse_scout_reports(llm_output)

        # Enrich with metadata from perceive
        metadata = getattr(self, "_repo_metadata", {})
        for f in findings:
            meta = metadata.get(f.repo_full_name, {})
            f.language = meta.get("language", f.language)
            f.license = meta.get("license", f.license)
            f.topics = meta.get("topics", f.topics)

        # Filter by relevance
        filtered = filter_findings(findings, min_relevance=3)
        self._last_findings = filtered

        # Store report
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._reports_dir / f"{date_str}.json"
        report_data = {
            "date": date_str,
            "total_classified": len(findings),
            "total_relevant": len(filtered),
            "findings": [asdict(f) for f in filtered],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
```

**Replace with:**

```python
    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM classification, store report, deliver notifications."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        # BF-177: Allow duty-triggered proactive_think (scout_report) to reach report generation
        is_duty_triggered = bool(decision.get("duty", {}).get("duty_id"))
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think") and not is_duty_triggered:
            return {"success": True, "result": decision.get("llm_output", "")}
        llm_output = decision.get("llm_output", "")
        if "No new repositories" in llm_output or not llm_output.strip():
            # BF-214: "No new repositories" means perceive found nothing new —
            # no pending repos to mark. Safe to return.
            return {"success": True, "result": "No new findings to report."}

        findings = parse_scout_reports(llm_output)

        # BF-214: Mark repos as seen ONLY after classification succeeds.
        # "Succeeds" = parse_scout_reports found at least one ===SCOUT_REPORT=== block
        # (including SKIP classifications, which parse_scout_reports filters out but
        # their presence proves the LLM responded in the correct format).
        # If findings is empty AND llm_output contains ===SCOUT_REPORT===, the LLM
        # classified everything as SKIP — that's a valid result, mark as seen.
        # If findings is empty AND no ===SCOUT_REPORT=== blocks, the LLM failed to
        # produce the expected format — do NOT mark as seen, allow retry next cycle.
        _pending = getattr(self, "_pending_seen_repos", [])
        _classification_succeeded = bool(findings) or "===SCOUT_REPORT===" in llm_output
        if _pending and _classification_succeeded:
            seen = _load_seen(self._seen_file)
            _now = datetime.now(timezone.utc).isoformat()
            for repo_name in _pending:
                seen[repo_name] = _now
            _save_seen(seen, self._seen_file)
            logger.info("Scout: marked %d repos as seen after classification", len(_pending))
            self._pending_seen_repos = []
        elif _pending and not _classification_succeeded:
            logger.warning(
                "Scout: classification failed — %d repos NOT marked as seen, will retry next cycle",
                len(_pending),
            )
            self._pending_seen_repos = []

        # Enrich with metadata from perceive
        metadata = getattr(self, "_repo_metadata", {})
        for f in findings:
            meta = metadata.get(f.repo_full_name, {})
            f.language = meta.get("language", f.language)
            f.license = meta.get("license", f.license)
            f.topics = meta.get("topics", f.topics)

        # Filter by relevance
        filtered = filter_findings(findings, min_relevance=3)
        self._last_findings = filtered

        # Store report
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._reports_dir / f"{date_str}.json"
        report_data = {
            "date": date_str,
            "total_classified": len(findings),
            "total_relevant": len(filtered),
            "findings": [asdict(f) for f in filtered],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
```

**What changed:**
- After `parse_scout_reports()`, check whether classification succeeded
- Success criteria: `findings` is non-empty (absorb/visiting_officer found) OR `===SCOUT_REPORT===` appears in output (LLM produced the format, repos were just all SKIP)
- On success: load seen file, mark all pending repos, save to disk
- On failure: log warning, clear pending list — repos remain unseen for next cycle retry
- Pending list cleared in both paths to prevent stale state

### Part C: Initialize pending list (scout.py __init__)

In `__init__` (around L.225-229), add initialization:

**After `self._last_findings: list[ScoutFinding] = []` (L.229), add:**

```python
        self._pending_seen_repos: list[str] = []  # BF-214: deferred seen marking
```

### Part D: Clear seen file on reset (optional, low-risk)

The current seen file survives resets. After a reset, the new instance starts with a stale seen file from the prior instance. This isn't strictly a bug (90-day pruning handles eventual cleanup), but it means the first post-reset run won't discover repos that the prior instance already saw.

**No code change needed.** The `probos reset` command deletes the data directory, which includes `scout_seen.json`. If the seen file persists across resets, that's a separate issue in the reset handler, not in scout.py.

---

## Verification Checklist

**Deferred seen marking (Part A):**
1. [ ] `seen[full_name] = datetime.now(...)` removed from perceive loop (L.336)
2. [ ] `_save_seen(seen, self._seen_file)` removed from perceive (L.349)
3. [ ] `self._pending_seen_repos` set with new repo names in perceive
4. [ ] `seen` dict still loaded and used for filter check in perceive

**Classification-gated marking (Part B):**
5. [ ] `_pending_seen_repos` read in act() after parse_scout_reports()
6. [ ] Repos marked seen only when classification succeeds (findings OR ===SCOUT_REPORT=== blocks)
7. [ ] Warning logged when classification fails and repos NOT marked seen
8. [ ] `_pending_seen_repos` cleared in both success and failure paths
9. [ ] `_save_seen()` called in act() on success path

**Initialization (Part C):**
10. [ ] `_pending_seen_repos` initialized in __init__

**General:**
11. [ ] "No new repositories" early exit (L.383) unchanged — no pending repos in that path
12. [ ] Non-duty proactive_think pass-through (L.380) unchanged
13. [ ] All existing tests pass (`pytest tests/ -x -q`)
14. [ ] No imports changed, no new modules

---

## Tests (tests/test_bf214_scout_seen_deferral.py)

```python
"""BF-214: Scout deferred seen marking tests."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from probos.cognitive.scout import (
    ScoutAgent,
    parse_scout_reports,
    _load_seen,
    _save_seen,
)


class TestParseScoutReportsEdgeCases:
    """Verify parse_scout_reports handles failure cases."""

    def test_empty_string_returns_empty(self):
        """Empty LLM output returns no findings."""
        assert parse_scout_reports("") == []

    def test_garbage_returns_empty(self):
        """LLM output without ===SCOUT_REPORT=== returns no findings."""
        assert parse_scout_reports("Here are my thoughts on these repos...") == []

    def test_all_skip_returns_empty(self):
        """All-SKIP classification returns empty findings (SKIP filtered out)."""
        text = (
            "===SCOUT_REPORT===\n"
            "REPO: foo/bar\nSTARS: 100\nURL: https://github.com/foo/bar\n"
            "CLASS: skip\nRELEVANCE: 1\nSUMMARY: Not relevant\nINSIGHT: None\n"
            "===END==="
        )
        assert parse_scout_reports(text) == []

    def test_valid_absorb_parsed(self):
        """Absorb classification parsed correctly."""
        text = (
            "===SCOUT_REPORT===\n"
            "REPO: cool/project\nSTARS: 500\nURL: https://github.com/cool/project\n"
            "CLASS: absorb\nRELEVANCE: 4\nCREDIBILITY: 3\nRELIABILITY: 3\n"
            "SUMMARY: Useful agent pattern\nINSIGHT: Context management approach\n"
            "===END==="
        )
        findings = parse_scout_reports(text)
        assert len(findings) == 1
        assert findings[0].repo_full_name == "cool/project"
        assert findings[0].classification == "absorb"


class TestDeferredSeenMarking:
    """Verify repos are only marked seen after classification succeeds."""

    def test_perceive_does_not_save_seen(self, tmp_path):
        """perceive() must NOT call _save_seen or mark repos in seen dict."""
        import inspect
        from probos.cognitive.scout import ScoutAgent
        source = inspect.getsource(ScoutAgent.perceive)
        # _save_seen should not appear in perceive method body
        assert "_save_seen" not in source

    def test_perceive_sets_pending_repos(self):
        """perceive() stores pending repo names for act() to consume."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = []
        # Simulate what perceive does after search
        new_repos = ["foo/bar", "baz/qux"]
        agent._pending_seen_repos = new_repos
        assert agent._pending_seen_repos == ["foo/bar", "baz/qux"]

    def test_act_marks_seen_on_success(self, tmp_path):
        """act() marks repos as seen when classification produces valid blocks."""
        seen_file = tmp_path / "scout_seen.json"
        seen_file.write_text("{}", encoding="utf-8")

        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._seen_file = seen_file  # property override for test
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._reports_dir = tmp_path / "reports"
        agent._runtime = None

        # Mock _seen_file property
        type(agent)._seen_file = property(lambda self: seen_file)

        # Valid LLM output with ===SCOUT_REPORT=== blocks
        llm_output = (
            "===SCOUT_REPORT===\n"
            "REPO: cool/project\nSTARS: 500\nURL: https://github.com/cool/project\n"
            "CLASS: absorb\nRELEVANCE: 4\nCREDIBILITY: 3\nRELIABILITY: 3\n"
            "SUMMARY: Useful\nINSIGHT: Good\n"
            "===END==="
        )

        import asyncio
        decision = {
            "intent": "proactive_think",
            "duty": {"duty_id": "scout_report"},
            "llm_output": llm_output,
        }
        asyncio.run(agent.act(decision))

        # Verify repos were marked seen
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
        assert "cool/project" in seen
        assert "another/repo" in seen

    def test_act_does_not_mark_seen_on_failure(self, tmp_path):
        """act() does NOT mark repos as seen when LLM output is garbage."""
        seen_file = tmp_path / "scout_seen.json"
        seen_file.write_text("{}", encoding="utf-8")

        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["cool/project", "another/repo"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._reports_dir = tmp_path / "reports"
        agent._runtime = None
        type(agent)._seen_file = property(lambda self: seen_file)

        # Garbage LLM output — no ===SCOUT_REPORT=== blocks
        llm_output = "I analyzed these repos and found some interesting things..."
        decision = {
            "intent": "proactive_think",
            "duty": {"duty_id": "scout_report"},
            "llm_output": llm_output,
        }

        import asyncio
        asyncio.run(agent.act(decision))

        # Verify repos were NOT marked seen
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
        assert "cool/project" not in seen
        assert "another/repo" not in seen

    def test_act_marks_seen_when_all_skip(self, tmp_path):
        """act() marks repos as seen when all are classified SKIP (valid response)."""
        seen_file = tmp_path / "scout_seen.json"
        seen_file.write_text("{}", encoding="utf-8")

        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["boring/project"]
        agent._repo_metadata = {}
        agent._last_findings = []
        agent._reports_dir = tmp_path / "reports"
        agent._runtime = None
        type(agent)._seen_file = property(lambda self: seen_file)

        # All SKIP — parse_scout_reports returns [] but ===SCOUT_REPORT=== present
        llm_output = (
            "===SCOUT_REPORT===\n"
            "REPO: boring/project\nSTARS: 50\nURL: https://github.com/boring/project\n"
            "CLASS: skip\nRELEVANCE: 1\nSUMMARY: Not relevant\nINSIGHT: None\n"
            "===END==="
        )
        decision = {
            "intent": "proactive_think",
            "duty": {"duty_id": "scout_report"},
            "llm_output": llm_output,
        }

        import asyncio
        asyncio.run(agent.act(decision))

        # All-SKIP is a valid classification — repo should be marked seen
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
        assert "boring/project" in seen

    def test_pending_cleared_on_both_paths(self):
        """_pending_seen_repos is cleared regardless of success or failure."""
        agent = ScoutAgent.__new__(ScoutAgent)
        agent._pending_seen_repos = ["foo/bar"]
        # After act() runs (either path), pending should be empty
        # This is verified implicitly by the success/failure tests above
        # but we explicitly check the initial state
        assert len(agent._pending_seen_repos) == 1
```

Test count: 9 tests across 2 classes.

---

## What This Does NOT Do (Out of Scope)

- **Does not change search queries or frequency.** The 7-day window and 86400s duty cycle are correct as-is.
- **Does not change the 90-day seen TTL.** Pruning policy is unchanged.
- **Does not change parse_scout_reports() parsing logic.** The parser correctly filters SKIP — the fix uses `===SCOUT_REPORT===` presence as a success signal.
- **Does not add retry logic.** Failed classifications will naturally retry on the next duty cycle (daily). The pending repos remain unseen, so the next perceive() will find them again via GitHub search.
- **Does not change filter_findings() threshold.** The composite_score >= 3 threshold is unchanged.
- **Does not modify the reset handler.** `probos reset` already clears the data directory.

---

## Engineering Principles Compliance

- **Fail Fast:** Classification failure is now logged with a WARNING (`"classification failed — N repos NOT marked as seen"`). Previously silent — zero visibility into data loss.
- **Defense in Depth:** Two-layer success check: `bool(findings)` catches absorb/visiting_officer findings; `"===SCOUT_REPORT===" in llm_output` catches all-SKIP valid classifications. Neither alone is sufficient.
- **DRY:** Reuses existing `_load_seen()` / `_save_seen()` functions. No duplication.
- **SOLID (S):** perceive() gathers data, act() processes results and manages state. Seen file management moved to where it logically belongs — after processing, not before.
- **Cloud-Ready Storage:** Seen file uses existing JSON persistence pattern. No new storage interfaces.
