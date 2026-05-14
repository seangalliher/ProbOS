"""AD-722c: boundary tests for telemetry history writer + query."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from probos.avatars.telemetry import AgentSignalsSnapshot, AvatarTelemetrySnapshot
from probos.avatars.telemetry_history import TelemetryHistoryWriter


def _make_snap(agent_id: str = "ezri") -> AvatarTelemetrySnapshot:
    return AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting=None,
        current_signals=AgentSignalsSnapshot(
            trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
        ),
        mouth_active=False,
        applied_modulation=None,
        dsl_summary=None,
        last_observed_at=0.0,
        degraded_reasons=(),
        sampling_rate_ms=2000,
        sampling_tier="normal",
    )


@pytest.mark.asyncio
async def test_writer_appends_and_queries_roundtrip(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    for _ in range(3):
        await writer.append(_make_snap())
    rows = await writer.query("ezri", limit=10)
    assert len(rows) == 3
    timestamps = [r["ts"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    for r in rows:
        assert r["snap"]["agent_id"] == "ezri"


@pytest.mark.asyncio
async def test_writer_rejects_malicious_agent_id(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    for bad in ("../evil", "", "with/slash", "spaces here"):
        await writer.append(_make_snap(agent_id=bad))
    # Nothing should have been created (the only valid op above would have
    # been the empty-string short-circuit; none of the candidates pass).
    assert list(tmp_path.iterdir()) == []
    rows = await writer.query("../evil", limit=10)
    assert rows == []


@pytest.mark.asyncio
async def test_query_respects_since(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    path = tmp_path / "ezri.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with path.open("w", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(json.dumps({
                "ts": now - (i * 10),
                "snap": _make_snap().to_dict(),
            }) + "\n")
    # since = now - 25 should keep rows at offsets 0, 10, 20.
    rows = await writer.query("ezri", limit=10, since=now - 25)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_query_respects_retention_window(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    path = tmp_path / "ezri.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with path.open("w", encoding="utf-8") as fh:
        # Two recent rows + one ancient.
        fh.write(json.dumps({"ts": now, "snap": _make_snap().to_dict()}) + "\n")
        fh.write(json.dumps({"ts": now - 100, "snap": _make_snap().to_dict()}) + "\n")
        fh.write(json.dumps({"ts": now - (60 * 86400), "snap": _make_snap().to_dict()}) + "\n")
    rows = await writer.query("ezri", limit=10, retention_days=30)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_writer_tolerates_disk_failure(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    with patch.object(Path, "open", side_effect=OSError("disk full")):
        # Must not raise.
        await writer.append(_make_snap())


@pytest.mark.asyncio
async def test_query_skips_malformed_lines(tmp_path: Path) -> None:
    writer = TelemetryHistoryWriter(str(tmp_path))
    path = tmp_path / "ezri.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now, "snap": _make_snap().to_dict()}) + "\n")
        fh.write("not-json-at-all\n")
        fh.write('{"ts": "not-a-float", "snap": {}}\n')
    rows = await writer.query("ezri", limit=10)
    assert len(rows) == 1
    assert rows[0]["snap"]["agent_id"] == "ezri"
