"""AD-1356 (#1722) acceptance 1: the replay script on a synthetic copy of 2026-10-31's 28 requests.

The requests are filed by the real ``CapabilityRequestStore``: agent-work payloads from the gate's ``approval_payload``,
and repair payloads in the shape ``repair_action`` recognises; the live database is never opened. On the base this file fails at load (``scripts/replay_approval_tiers.py``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from probos.agent_work_runner import approval_payload
from probos.capability_request import CapabilityRequestStore

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_approval_tiers.py"
PLACEHOLDERS = ("grep_app_placeholder_skip", "grep-app_placeholder_skip", "grep_placeholder_skip")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ad1356_replay", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = _load()


def _repair(code: str) -> dict[str, Any]:
    return {
        "tool_id": "repair", "action": "dispatch",
        "params": {
            "fault_id": f"fault-{code}", "signature": hashlib.sha256(code.encode()).hexdigest(),
            "targets": ["src/probos/substrate/event_log.py"],
            "brief": f"event_log_query failed the same way twice: event_log_query_invalid:{code}",
        },
        "scope_key": "seangalliher/ProbOS", "session_id": None, "thread_id": "t-1",
    }


async def _the_31st(tmp_path: Path) -> Path:
    """28 requests in the 2026-10-31 shape (#1722): 7 codebase_query, 6 list_files, 3 find_mcp_tool, 2 read_file (one a
    recovery read), 1 codebase_read_source, 3 run_python, 3 nonexistent tools, 3 input-error repairs."""
    db = tmp_path / "copy" / "capability_requests.db"
    db.parent.mkdir()
    store = CapabilityRequestStore(db_path=str(db))
    await store.start()
    try:
        item = "wi-replay-1"
        calls: list[tuple[str, dict[str, Any]]] = [("codebase_query", {"concept": f"relay {n}"}) for n in range(7)]
        calls += [("list_files", {"pattern": f"*.{ext}"}) for ext in ("py", "md", "txt", "yaml", "json", "toml")]
        calls += [("find_mcp_tool", {"query": query}) for query in ("grep", "docs", "issues")]
        calls += [
            ("read_file", {"path": str(tmp_path / "project" / "notes.txt")}),
            ("read_file", {"path": str(tmp_path / "workspaces" / ".tool-results" / "r1.txt")}),
            ("codebase_read_source", {"file_path": "src/probos/relay.py"}),
        ]
        calls += [("run_python", {"code": f"print({n})"}) for n in range(3)]
        calls += [(name, {}) for name in PLACEHOLDERS]
        for tool_id, params in calls:
            payload = approval_payload(tool_id, params, item)
            assert await store.file_action_request("forge-1", payload, work_item_id=item) is not None, tool_id
        for code in ("window", "filter_required", "aggregate_filters"):
            assert await store.file_action_request("system", _repair(code)) is not None
    finally:
        await store.stop()
    return db


def _run(db: Path, receipt: Path, *extra: str) -> dict[str, Any]:
    argv = ["--db", str(db), "--since", "0", "--until", str(time.time() + 60), "--receipt", str(receipt), *extra]
    assert replay.main(argv) == 0
    return json.loads(receipt.read_text(encoding="utf-8"))


# R1
async def test_the_31st_replays_to_three_captain_decisions_and_the_copy_is_unchanged(tmp_path: Path) -> None:
    """With read_roots set, the default deciders and run_python registered: 9 routine reads run directly, the
    recovery read is admitted, 9 elevated calls go to AD-1213's route, the 3 nonexistent tools are refused, the 3
    input-error repairs are not filed, and the 3 run_python calls are the Captain's. The copy's bytes do not change."""
    db = await _the_31st(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    got = _run(db, tmp_path / "gates" / "ad-1356-replay.receipt.json", "--registered-ids", "run_python")
    assert got["counts"] == {
        "critical_captain": 3, "elevated_chief": 9, "input_error": 3, "recovery_read": 1, "routine_auto": 9,
        "unregistered": 3,
    }
    assert (got["requests"], got["captain_routed"], got["chain_decided"]) == (28, 3, 9)
    assert got["unregistered_tool_ids"] == sorted(PLACEHOLDERS) and got["unlisted_tool_ids"] == []
    assert got["registered_ids"] == ["run_python"]
    assert got["deciders"] == {"routine": "auto", "elevated": "chief", "critical": "captain"}
    assert got["reads_confined"] is True
    assert got["db_sha256"] == before == hashlib.sha256(db.read_bytes()).hexdigest()


# R2
async def test_with_reads_unconfined_the_two_path_reads_go_to_the_captain_and_a_missing_copy_is_refused(
    tmp_path: Path,
) -> None:
    """With read_roots unset and run_python registered, read_file and codebase_read_source are critical (5 for the
    Captain); the recovery read is still admitted. A missing copy exits 2 and writes no receipt."""
    db = await _the_31st(tmp_path)
    got = _run(db, tmp_path / "receipt.json", "--reads-unconfined", "--registered-ids", "run_python")
    assert (got["counts"]["critical_captain"], got["counts"]["recovery_read"], got["counts"]["routine_auto"]) == (5, 1, 7)
    assert got["captain_routed"] == 5 and got["reads_confined"] is False
    absent = tmp_path / "r2.json"
    assert replay.main(["--db", str(tmp_path / "absent.db"), "--since", "0", "--until", "1", "--receipt", str(absent)]) == 2
    assert not absent.exists()


# R3
async def test_without_registered_ids_run_python_and_the_nonexistent_tools_stay_unlisted(tmp_path: Path) -> None:
    """With no --registered-ids the script cannot tell run_python (registered, critical) from the 3 nonexistent tools
    (refused): all 6 are unlisted, and none is counted for the Captain."""
    db = await _the_31st(tmp_path)
    got = _run(db, tmp_path / "receipt.json")
    assert (got["counts"]["unlisted"], got["captain_routed"]) == (6, 0)
    assert "critical_captain" not in got["counts"] and "unregistered" not in got["counts"]
    assert got["unlisted_tool_ids"] == sorted((*PLACEHOLDERS, "run_python"))
    assert got["unregistered_tool_ids"] == [] and got["registered_ids"] is None
