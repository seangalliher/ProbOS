"""AD-738c (Wave 158): duration-aware Preston Blair -> Oculus viseme mapping.

Four boundary tests pinning the new `B`-vowel routing while preserving
backward compat for non-`B` shapes and short-`B` frames.
"""

from __future__ import annotations

from probos.avatars.rhubarb_backend import (
    _B_LONG_DURATION_MS,
    _map_preston_blair_to_oculus,
    _parse_rhubarb_output,
)


def test_map_b_short_duration_routes_to_kk():
    """Short B frames stay as the consonant default `kk` (stop consonants)."""
    assert _map_preston_blair_to_oculus("B", duration_ms=50.0) == "kk"
    # Default kwarg (legacy callers) -> kk.
    assert _map_preston_blair_to_oculus("B") == "kk"
    assert _map_preston_blair_to_oculus("B", duration_ms=0.0) == "kk"
    # Boundary: equality is NOT a long frame (strict >).
    assert _map_preston_blair_to_oculus("B", duration_ms=_B_LONG_DURATION_MS) == "kk"
    assert _map_preston_blair_to_oculus("B", duration_ms=79.0) == "kk"


def test_map_b_long_duration_routes_to_ih():
    """Long B frames route to full vowel `ih`."""
    assert _map_preston_blair_to_oculus("B", duration_ms=100.0) == "ih"
    assert _map_preston_blair_to_oculus("B", duration_ms=81.0) == "ih"
    # Just above the boundary.
    assert _map_preston_blair_to_oculus("B", duration_ms=_B_LONG_DURATION_MS + 0.1) == "ih"


def test_map_non_b_ignores_duration():
    """Duration kwarg only affects `B`. All other shapes unchanged."""
    cases = {
        "A": "PP", "C": "E", "D": "aa", "E": "oh",
        "F": "ou", "G": "FF", "H": "RR", "X": "sil",
    }
    for pb, expected in cases.items():
        assert _map_preston_blair_to_oculus(pb, duration_ms=200.0) == expected
        assert _map_preston_blair_to_oculus(pb, duration_ms=0.0) == expected


def test_parse_rhubarb_output_emits_ih_for_long_b():
    """Integration: long-B frame from rhubarb JSON becomes `ih`."""
    long_b = {
        "metadata": {"soundFile": "test.wav", "duration": 0.1},
        "mouthCues": [
            {"start": 0.0, "end": 0.1, "value": "B"},  # 100 ms B -> ih
        ],
    }
    frames = _parse_rhubarb_output(long_b)
    assert len(frames) == 1
    assert frames[0].viseme == "ih"
    assert frames[0].duration == 0.1

    short_b = {
        "metadata": {"soundFile": "test.wav", "duration": 0.05},
        "mouthCues": [
            {"start": 0.0, "end": 0.05, "value": "B"},  # 50 ms B -> kk
        ],
    }
    frames = _parse_rhubarb_output(short_b)
    assert len(frames) == 1
    assert frames[0].viseme == "kk"
    assert frames[0].duration == 0.05
