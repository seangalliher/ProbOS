"""AD-721g: per-rank baseline VRM resolver — boundary tests.

License-clean by construction: ProbOS OSS never ships avatar bytes. Tests
synthesise VRM files under ``tmp_path`` and verify resolver + read-path
fallback. Real ``AvatarsConfig`` + real ``BaselineVRMManifest`` per BF-287.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.baseline_resolver import (
    _BASELINES_SUBDIR,
    resolve_baseline_vrm_filename,
    resolve_baseline_vrm_path,
)
from probos.config import BaselineVRMManifest
from probos.crew_profile import Rank


def _write_vrm(target: Path, content: bytes = b"VRM-FAKE") -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


# ── Pure-mapping resolver tests ─────────────────────────────────


def test_resolve_filename_empty_manifest_returns_blank_for_all_ranks():
    manifest = BaselineVRMManifest()
    for rank in (Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR):
        assert resolve_baseline_vrm_filename(rank, manifest) == ""


def test_resolve_path_populated_manifest_existing_file_returns_path(tmp_path):
    manifest = BaselineVRMManifest(ensign="ensign.vrm")
    avatars_dir = tmp_path / "avatars"
    target = avatars_dir / _BASELINES_SUBDIR / "ensign.vrm"
    _write_vrm(target)
    result = resolve_baseline_vrm_path(Rank.ENSIGN, manifest, avatars_dir)
    assert result is not None
    assert result == target.resolve()


def test_resolve_path_populated_manifest_missing_file_returns_none(tmp_path):
    manifest = BaselineVRMManifest(ensign="missing.vrm")
    result = resolve_baseline_vrm_path(Rank.ENSIGN, manifest, tmp_path / "avatars")
    assert result is None


def test_resolve_path_filename_with_slash_is_rejected(tmp_path, caplog):
    manifest = BaselineVRMManifest(ensign="sub/escape.vrm")
    avatars_dir = tmp_path / "avatars"
    _write_vrm(avatars_dir / _BASELINES_SUBDIR / "sub" / "escape.vrm")
    with caplog.at_level("WARNING"):
        result = resolve_baseline_vrm_path(Rank.ENSIGN, manifest, avatars_dir)
    assert result is None
    assert any("path separators" in rec.message for rec in caplog.records)


def test_resolve_path_filename_with_parent_dir_is_rejected(tmp_path):
    manifest = BaselineVRMManifest(ensign="../escape.vrm")
    result = resolve_baseline_vrm_path(Rank.ENSIGN, manifest, tmp_path / "avatars")
    assert result is None


def test_resolve_path_filename_with_backslash_is_rejected(tmp_path):
    # Pure-mapping rejection — does not require the file to exist.
    manifest = BaselineVRMManifest(ensign=r"sub\escape.vrm")
    result = resolve_baseline_vrm_path(Rank.ENSIGN, manifest, tmp_path / "avatars")
    assert result is None


def test_resolve_filename_maps_ensign_trust_to_ensign_entry():
    manifest = BaselineVRMManifest(ensign="ens.vrm")
    rank = Rank.from_trust(0.45)
    assert rank == Rank.ENSIGN
    assert resolve_baseline_vrm_filename(rank, manifest) == "ens.vrm"


def test_resolve_filename_maps_senior_trust_to_senior_entry():
    manifest = BaselineVRMManifest(senior="senior.vrm")
    rank = Rank.from_trust(0.92)
    assert rank == Rank.SENIOR
    assert resolve_baseline_vrm_filename(rank, manifest) == "senior.vrm"


# ── Read-path integration ───────────────────────────────────────


def _make_runtime(tmp_path: Path, manifest: BaselineVRMManifest) -> MagicMock:
    """Minimal runtime for the /agent/{id}/profile read path."""
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "ad721g_test_agent"
    agent.confidence = 0.85
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.tier = "domain"
    agent.pool = "counselor"
    agent.is_alive = True
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi",
        "agent_type": "counselor",
        "agent_id": "agent-007",
        "display_name": "Counselor",
        "department": "bridge",
    }
    runtime.trust_network = MagicMock()
    # Force senior tier so SENIOR baseline is picked up.
    runtime.trust_network.get_score.return_value = 0.95
    runtime.trust_network.get_history.return_value = []
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.profile_store = None
    runtime.emit_event = MagicMock()

    # BF-287: real Pydantic AvatarsConfig with the real BaselineVRMManifest.
    from probos.config import AvatarsConfig

    avatars_cfg = AvatarsConfig(
        enabled=True,
        avatars_dir=str(tmp_path / "avatars"),
        baseline_vrms=manifest,
    )
    cfg = MagicMock()
    cfg.avatars = avatars_cfg
    runtime.config = cfg
    return runtime


def test_profile_returns_baseline_url_when_seed_empty_and_baseline_present(tmp_path):
    manifest = BaselineVRMManifest(senior="senior.vrm")
    avatars_dir = tmp_path / "avatars"
    _write_vrm(avatars_dir / _BASELINES_SUBDIR / "senior.vrm")
    runtime = _make_runtime(tmp_path, manifest)

    from probos.api import create_app
    client = TestClient(create_app(runtime))

    resp = client.get("/api/agent/agent-007/profile")
    assert resp.status_code == 200, resp.text
    appearance = resp.json().get("appearance") or {}
    assert appearance.get("vrm_url") == f"{_BASELINES_SUBDIR}/senior.vrm"
