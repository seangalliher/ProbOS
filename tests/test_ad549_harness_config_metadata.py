"""AD-549: Tests for NativeSWEHarnessConfig + BuildResult.metadata."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from probos.config import NativeSWEHarnessConfig, SystemConfig


def test_native_swe_harness_config_defaults() -> None:
    cfg = NativeSWEHarnessConfig()
    assert cfg.enabled is False
    assert cfg.eligibility_modify_only is True
    assert cfg.max_iterations == 25
    assert cfg.max_fix_iterations == 5
    assert cfg.token_budget is None
    assert cfg.compaction_threshold_pct == 0.8
    assert cfg.blocked_paths == [
        "src/probos/security/",
        ".env",
        "config/sealed_modules.yaml",
    ]


def test_native_swe_harness_config_max_iterations_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        NativeSWEHarnessConfig(max_iterations=0)


def test_native_swe_harness_config_compaction_threshold_upper_bound() -> None:
    with pytest.raises(ValidationError):
        NativeSWEHarnessConfig(compaction_threshold_pct=1.0)


def test_system_config_native_swe_harness_field_present() -> None:
    cfg = SystemConfig()
    assert isinstance(cfg.native_swe_harness, NativeSWEHarnessConfig)


def test_build_result_accepts_metadata_dict() -> None:
    from probos.cognitive.builder import BuildResult, BuildSpec

    spec = BuildSpec(title="t", description="d")
    md = {"builder_type": "native_harness", "iterations": 3}
    br = BuildResult(success=True, spec=spec, metadata=md)
    assert br.metadata == md
    # Default metadata is empty dict
    br2 = BuildResult(success=True, spec=spec)
    assert br2.metadata == {}
