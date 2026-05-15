"""AD-723a-3: SensoriumEntry gains injection_zone + wrapper metadata.

Boundary tests:
1. Backward-compatible default construction.
2. injection_zone alone.
3. wrapper alone.
4. Frozen-instance immutability.
5. Dispatcher applies wrapper on string output.
6. Dispatcher skips wrapper on dict-return contract.
7. Wrapper exception falls back to raw output.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import SensoriumEntry, SensoriumLayer


# --------------------------------------------------------------------------- #
# 1-4 — dataclass surface                                                     #
# --------------------------------------------------------------------------- #


def test_sensorium_entry_constructs_without_new_fields() -> None:
    e = SensoriumEntry(layer=SensoriumLayer.PROPRIOCEPTION, description="x")
    assert e.injection_zone is None
    assert e.wrapper is None


def test_sensorium_entry_with_zone_only() -> None:
    e = SensoriumEntry(
        layer=SensoriumLayer.PROPRIOCEPTION, description="x",
        injection_zone="temporal_header",
    )
    assert e.injection_zone == "temporal_header"
    assert e.wrapper is None


def test_sensorium_entry_with_wrapper_only() -> None:
    def wrap(s: str) -> str:
        return f"[{s}]"
    e = SensoriumEntry(
        layer=SensoriumLayer.PROPRIOCEPTION, description="x", wrapper=wrap,
    )
    assert e.wrapper is wrap
    assert callable(e.wrapper)


def test_sensorium_entry_frozen_immutable() -> None:
    e = SensoriumEntry(layer=SensoriumLayer.PROPRIOCEPTION, description="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.injection_zone = "y"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 5-7 — dispatcher integration via _apply_sensorium_result                    #
# --------------------------------------------------------------------------- #


class _BareDispatcher:
    """Minimal carrier for ``_apply_sensorium_result`` — avoids constructing
    a full CognitiveAgent (heavy boot path)."""


def _apply(
    merged: dict[str, str], entry: SensoriumEntry, method_name: str, result: Any,
) -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent
    CognitiveAgent._apply_sensorium_result(
        _BareDispatcher(), merged, entry, method_name, result,  # type: ignore[arg-type]
    )


def test_dispatcher_applies_wrapper_to_string_output() -> None:
    entry = SensoriumEntry(
        layer=SensoriumLayer.PROPRIOCEPTION,
        description="x",
        output_key="k",
        wrapper=lambda s: f"--- A ---\n{s}",
    )
    merged: dict[str, str] = {}
    _apply(merged, entry, "stub_method", "foo")
    assert merged == {"k": "--- A ---\nfoo"}


def test_dispatcher_skips_wrapper_for_dict_output() -> None:
    seen: list[str] = []

    def wrap(s: str) -> str:
        seen.append(s)
        return f"WRAPPED:{s}"

    entry = SensoriumEntry(
        layer=SensoriumLayer.PROPRIOCEPTION,
        description="x",
        wrapper=wrap,  # output_key intentionally None — dict-return contract
    )
    merged: dict[str, str] = {}
    _apply(merged, entry, "stub_method", {"k": "v"})
    assert merged == {"k": "v"}
    assert seen == []  # wrapper never called


def test_dispatcher_wrapper_exception_falls_back_to_raw() -> None:
    def boom(_s: str) -> str:
        raise RuntimeError("wrapper raised")

    entry = SensoriumEntry(
        layer=SensoriumLayer.PROPRIOCEPTION,
        description="x",
        output_key="k",
        wrapper=boom,
    )
    merged: dict[str, str] = {}
    _apply(merged, entry, "stub_method", "raw-value")
    assert merged == {"k": "raw-value"}
