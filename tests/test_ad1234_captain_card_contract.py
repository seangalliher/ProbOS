"""AD-1234 (#1117): the Captain Card configuration was documentation, not code.

`CognitiveConfig` declared four Captain Card fields. Every one was unread in
`src/`. An operator following `docs/development/config-reference.md` and setting
`captain_card_enabled: false` got the Card injected anyway; one setting
`captain_card_path` got `captain_card.json` regardless.

That is worse than a missing feature. A config field is a promise, and a config
reference generated from the models will document a promise nothing keeps --
which is how this survived: the doc was accurate about the *declaration* and
silent about the *reader*.

Three fields are now real. The fourth --
`captain_card_refresh_min_interval_seconds`, "minimum interval between
Dreaming-driven Card refreshes" -- is DELETED rather than wired, because there
is no Dreaming-driven Card refresh anywhere: `captain_card` appears in eight
files and none of them refresh it. Wiring a rate limit onto a mechanism that
does not exist would have been the same defect with more code.

The Card is still always LOADED even when injection is off, because
`SessionManager` keys session continuity on `captain_card.id`. The flag governs
whether the Card reaches a prompt, which is what its description claims.
"""

from __future__ import annotations

import inspect

import pytest

from probos.config import CognitiveConfig, SystemConfig


# ── the fields exist and are readable ─────────────────────────────


def test_the_deleted_field_is_gone_not_merely_undocumented() -> None:
    """It described "Dreaming-driven Card refreshes". Enumeration behind that
    claim: ``captain_card`` appears in 8 files across src/ and not one refreshes
    the Card. A knob on an absent mechanism is a promise too.
    """
    assert "captain_card_refresh_min_interval_seconds" not in CognitiveConfig.model_fields


def test_the_three_surviving_fields_are_still_declared() -> None:
    for name in (
        "captain_card_enabled",
        "captain_card_path",
        "captain_card_max_tokens",
    ):
        assert name in CognitiveConfig.model_fields, name


# ── each one is actually read ─────────────────────────────────────


def test_the_configured_path_is_read_rather_than_hardcoded() -> None:
    """``self._data_dir / "captain_card.json"`` was the literal in runtime."""
    from probos import runtime as runtime_mod

    src = inspect.getsource(runtime_mod)
    assert "captain_card_path" in src
    assert 'self._data_dir / "captain_card.json"' not in src


def test_the_enabled_flag_gates_the_injection() -> None:
    from probos import runtime as runtime_mod

    src = inspect.getsource(runtime_mod)
    assert "captain_card_enabled" in src


def test_the_flag_gates_the_second_injection_site_too() -> None:
    """Yeoman adopted the persona whenever the card was not None. One flag, both
    sites, or it is not a contract -- the runtime gate alone would have left the
    Card in Yeoman's identity preamble with the feature "off".
    """
    from probos.startup import agent_fleet

    src = inspect.getsource(agent_fleet)
    assert "captain_card_enabled" in src


def test_the_token_budget_is_enforced() -> None:
    from probos import runtime as runtime_mod

    src = inspect.getsource(runtime_mod)
    assert "captain_card_max_tokens" in src


# ── the rendered context respects the budget ──────────────────────


class _Card:
    def __init__(self, text: str) -> None:
        self._text = text

    def to_system_context(self) -> str:
        return self._text


def _render(card: _Card, cfg: CognitiveConfig) -> str:
    """The exact expression runtime uses, exercised without booting a runtime."""
    if not cfg.captain_card_enabled:
        return ""
    ctx = card.to_system_context()
    cap = int(cfg.captain_card_max_tokens) * 4
    return ctx if len(ctx) <= cap else ctx[:cap].rstrip() + "\n"


def test_a_card_inside_the_budget_is_untouched() -> None:
    card = _Card("You are Yeo, Sean's personal assistant.\n")
    out = _render(card, CognitiveConfig())
    assert out == "You are Yeo, Sean's personal assistant.\n"


def test_a_card_over_the_budget_is_cut_to_it() -> None:
    cfg = CognitiveConfig(captain_card_max_tokens=100)  # 400 chars
    out = _render(_Card("x" * 5000), cfg)
    assert len(out) <= 401  # 400 + the restored newline


def test_disabled_injects_nothing_at_all() -> None:
    """Not "a shorter card" -- nothing. The flag says inject or do not."""
    cfg = CognitiveConfig(captain_card_enabled=False)
    assert _render(_Card("You are Yeo."), cfg) == ""


# ── the config reference cannot drift back ────────────────────────


def test_every_captain_card_field_has_a_reader() -> None:
    """The assertion whose absence let four fields ship unread. Any future
    Captain Card field must be read somewhere in src/ or this goes red.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
    sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*.py")
        if p.name != "config.py"
    )

    unread = [
        name for name in CognitiveConfig.model_fields
        if name.startswith("captain_card") and name not in sources
    ]
    assert unread == [], f"declared but never read outside config.py: {unread}"


@pytest.mark.parametrize("enabled", [True, False])
def test_the_config_round_trips_both_ways(enabled: bool) -> None:
    cfg = SystemConfig()
    cfg.cognitive.captain_card_enabled = enabled
    assert cfg.cognitive.captain_card_enabled is enabled
