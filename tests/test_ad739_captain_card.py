"""AD-739: Captain Card data model + render pipeline tests."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from probos import captain_card as cc_pkg
from probos.captain_card import card as cc
from probos.captain_card.card import (
    CaptainCard,
    CorrectionRef,
    default_captain_card,
    load_card,
    render_card_for_prompt,
    save_card,
)
from probos.config import SystemConfig


# 1. Default-bootstrap Card created when no file exists.
def test_default_bootstrap_card(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    card = load_card(target)
    assert isinstance(card, CaptainCard)
    assert card.name == "Captain"
    assert card.role == "Operator"
    assert card.version == 1


# 2. Card roundtrips through save_card / load_card.
def test_card_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "card.json"
    original = CaptainCard(
        name="Sean", callsign="Captain",
        preferences=["concise replies", "no emoji"],
    )
    assert save_card(original, target) is True
    restored = load_card(target)
    assert restored.name == "Sean"
    assert restored.callsign == "Captain"
    assert restored.preferences == ["concise replies", "no emoji"]


# 3. Render produces output within token budget for populated Card.
def test_render_within_token_budget() -> None:
    card = CaptainCard(
        name="Captain",
        role="Operator",
        preferences=["bullet form", "short answers"],
    )
    rendered = render_card_for_prompt(card, max_tokens=500)
    # 500 tokens approximated as 2000 chars.
    assert len(rendered) <= 2000
    assert "Captain" in rendered


# 4. Truncation: oversized Card → tail-truncated; identity preserved.
def test_truncation_preserves_identity() -> None:
    huge_prefs = [f"preference number {i} which is quite long and verbose" for i in range(10)]
    huge_corrections = [
        CorrectionRef(
            episode_id=f"ep-{i}",
            summary=f"correction summary {i} that is also long",
            timestamp=float(i),
        )
        for i in range(3)
    ]
    card = CaptainCard(
        name="Captain",
        role="Operator",
        preferences=huge_prefs,
        recent_corrections=huge_corrections,
    )
    rendered = render_card_for_prompt(card, max_tokens=50)  # 200 chars budget
    # Identity preserved.
    assert "Captain" in rendered
    assert "Operator" in rendered
    # Tail-truncated — most preferences/corrections dropped.
    assert len(rendered) <= 200


# 5. _CAPABILITY_GAP_RE validation: gap-phrase lines stripped.
def test_capability_gap_line_stripped() -> None:
    # Inject a preference that contains a gap phrase ("can't", "don't have").
    card = CaptainCard(
        name="Captain",
        role="Operator",
        preferences=[
            "concise replies",
            "I don't have any other preferences right now",
        ],
    )
    rendered = render_card_for_prompt(card, max_tokens=500)
    # Gap-phrase line dropped.
    assert "don't have" not in rendered.lower()
    # Other content preserved.
    assert "concise replies" in rendered


# 6. AD-731 invariant: avatar_ref must be SHA-256 hex.
def test_avatar_ref_validates_sha256() -> None:
    valid = "a" * 64
    card = CaptainCard(name="Captain", role="Operator", avatar_ref=valid)
    assert card.avatar_ref == valid
    # Invalid value raises.
    with pytest.raises(ValueError):
        CaptainCard(name="Captain", role="Operator", avatar_ref="not-a-hash")


# 7. avatar_ref None is allowed (default).
def test_avatar_ref_none_allowed() -> None:
    card = CaptainCard(name="Captain", role="Operator")
    assert card.avatar_ref is None


# 8. AD-731 source-scan: no inline image bytes in the module.
def test_ad731_source_scan_no_inline_bytes() -> None:
    source = inspect.getsource(cc)
    assert "b64encode" not in source
    assert "base64.b64" not in source


# 9. CognitiveConfig fields defaults.
def test_cognitive_config_defaults() -> None:
    cfg = SystemConfig()
    assert cfg.cognitive.captain_card_enabled is True
    assert cfg.cognitive.captain_card_path == "captain_card.json"
    assert cfg.cognitive.captain_card_max_tokens == 500
    # AD-1234 (#1117): ``captain_card_refresh_min_interval_seconds`` was
    # DELETED, not renamed. It described "Dreaming-driven Card refreshes" and
    # nothing in src/ ever refreshed the Card, so it rate-limited a mechanism
    # that does not exist. This assertion is kept and inverted rather than
    # dropped: if the field returns, it must arrive with the refresh it bounds.
    assert not hasattr(cfg.cognitive, "captain_card_refresh_min_interval_seconds")


# 10. Public surface — package exposes the canonical names.
def test_package_public_surface() -> None:
    assert hasattr(cc_pkg, "CaptainCard")
    assert hasattr(cc_pkg, "render_card_for_prompt")
    assert hasattr(cc_pkg, "load_card")
    assert hasattr(cc_pkg, "save_card")
    assert hasattr(cc_pkg, "default_captain_card")
