"""Tests for AD-595c: Standing orders billet template resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.standing_orders import (
    _resolve_billet_templates,
    set_billet_registry,
)


def _make_registry(billets: dict[str, tuple[str, str | None]]) -> MagicMock:
    """Create a mock BilletRegistry.

    billets: {title_or_id: (formal_title, callsign_or_None)}
    """
    from probos.ontology.billet_registry import BilletHolder

    registry = MagicMock()

    def _resolve(title_or_id: str) -> BilletHolder | None:
        key = title_or_id.strip().lower()
        for k, (title, callsign) in billets.items():
            if k.lower() == key:
                return BilletHolder(
                    billet_id=k.lower().replace(" ", "_"),
                    title=title,
                    department="test",
                    holder_agent_type="test_agent",
                    holder_callsign=callsign,
                    holder_agent_id="agent-001" if callsign else None,
                )
        return None

    registry.resolve = MagicMock(side_effect=_resolve)
    return registry


# --- Template resolution ---

class TestBilletTemplateResolution:

    def test_resolve_filled_billet(self):
        """Filled billet resolves to 'Callsign (Title)'."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to the {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Report to the LaForge (Chief Engineer)."

    def test_resolve_vacant_billet(self):
        """Vacant billet resolves to 'Title (vacant)'."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", None)})
        text = "Report to the {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Report to the Chief Engineer (vacant)."

    def test_unknown_token_unchanged(self):
        """Non-billet tokens in {} are left unchanged."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Use {unknown_setting} for config."
        result = _resolve_billet_templates(text, reg)
        assert result == "Use {unknown_setting} for config."

    def test_code_like_tokens_unchanged(self):
        """Tokens with code characters are skipped."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Format: {key=value} and {func()}"
        result = _resolve_billet_templates(text, reg)
        assert result == "Format: {key=value} and {func()}"

    def test_multiple_billets_in_one_line(self):
        """Multiple billet references on one line all resolve."""
        reg = _make_registry({
            "Chief Engineer": ("Chief Engineer", "LaForge"),
            "Chief Science Officer": ("Chief Science Officer", "Meridian"),
        })
        text = "Coordinate between {Chief Engineer} and {Chief Science Officer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Coordinate between LaForge (Chief Engineer) and Meridian (Chief Science Officer)."

    def test_case_insensitive_resolution(self):
        """Billet resolution is case-insensitive."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Ask {chief engineer} for help."
        result = _resolve_billet_templates(text, reg)
        assert result == "Ask LaForge (Chief Engineer) for help."

    def test_code_block_backtick_not_processed(self):
        """Content inside ``` code blocks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to {Chief Engineer}.\n```\n{Chief Engineer}\n```\nEnd."
        result = _resolve_billet_templates(text, reg)
        lines = result.split('\n')
        assert lines[0] == "Report to LaForge (Chief Engineer)."
        assert lines[2] == "{Chief Engineer}"  # Inside code block — unchanged
        assert lines[4] == "End."

    def test_code_block_tilde_not_processed(self):
        """Content inside ~~~ code blocks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to {Chief Engineer}.\n~~~\n{Chief Engineer}\n~~~\nEnd."
        result = _resolve_billet_templates(text, reg)
        lines = result.split('\n')
        assert lines[0] == "Report to LaForge (Chief Engineer)."
        assert lines[2] == "{Chief Engineer}"  # Inside tilde block — unchanged

    def test_inline_backtick_not_processed(self):
        """Content inside inline backticks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Use `{Chief Engineer}` for the reference."
        result = _resolve_billet_templates(text, reg)
        assert result == "Use `{Chief Engineer}` for the reference."

    def test_empty_text(self):
        """Empty text returns empty."""
        reg = _make_registry({})
        assert _resolve_billet_templates("", reg) == ""

    def test_no_templates(self):
        """Text without {} templates passes through unchanged."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "No templates here."
        assert _resolve_billet_templates(text, reg) == text

    def test_single_char_token_skipped(self):
        """Single-char tokens are skipped."""
        reg = _make_registry({})
        text = "Format {x} value."
        assert _resolve_billet_templates(text, reg) == "Format {x} value."

    def test_empty_braces_unchanged(self):
        """Empty braces {} pass through unchanged (regex requires 1+ char)."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Empty {} braces and {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert "{}" in result
        assert "LaForge (Chief Engineer)" in result

    def test_nested_braces_outer_preserved(self):
        """Nested braces {{something}} — inner match occurs, outer brace preserved."""
        reg = _make_registry({})
        text = "Template {{variable}} here."
        result = _resolve_billet_templates(text, reg)
        assert result == "Template {{variable}} here."


# --- set_billet_registry ---

class TestSetBilletRegistry:

    def test_set_billet_registry_stores_reference(self):
        """set_billet_registry stores the registry in module state."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            mock_reg = MagicMock()
            set_billet_registry(mock_reg)
            assert standing_orders._billet_registry is mock_reg
        finally:
            standing_orders._billet_registry = old_reg


    def test_set_billet_registry_none_clears(self):
        """set_billet_registry(None) clears the module state."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            set_billet_registry(MagicMock())
            set_billet_registry(None)
            assert standing_orders._billet_registry is None
        finally:
            standing_orders._billet_registry = old_reg


# --- Integration with compose_instructions ---

class TestComposeIntegration:

    def test_compose_with_billet_registry(self):
        """compose_instructions resolves billets when registry is wired."""
        from probos.cognitive import standing_orders

        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})

        old_reg = standing_orders._billet_registry
        try:
            standing_orders._billet_registry = reg
            result = standing_orders.compose_instructions(
                agent_type="test_agent",
                hardcoded_instructions="Report to {Chief Engineer}.",
            )
            assert "LaForge (Chief Engineer)" in result
        finally:
            standing_orders._billet_registry = old_reg

    def test_compose_without_billet_registry(self):
        """compose_instructions leaves templates when no registry."""
        from probos.cognitive import standing_orders

        old_reg = standing_orders._billet_registry
        try:
            standing_orders._billet_registry = None
            result = standing_orders.compose_instructions(
                agent_type="test_agent",
                hardcoded_instructions="Report to {Chief Engineer}.",
            )
            assert "{Chief Engineer}" in result
        finally:
            standing_orders._billet_registry = old_reg