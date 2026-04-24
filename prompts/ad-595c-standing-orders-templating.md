# AD-595c: Standing Orders Templating — Billet-Aware Instructions

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry must be built first)
**Files:** `src/probos/cognitive/standing_orders.py`, `tests/test_ad595c_billet_templating.py` (NEW)

## Problem

Standing orders reference billets by hardcoded title strings: "the Chief Engineer", "the Chief Science Officer", "the Operations Chief". When agents read these instructions, the titles are abstract — they don't know *who* currently holds that billet. The Data Analyst's orders say "Escalate anomalies to the Chief Science Officer" but the agent doesn't know if that's Meridian, Atlas, or someone else.

After AD-595a gives us `BilletRegistry.resolve()`, standing orders can resolve billet references to current callsigns at composition time, making instructions concrete: "Escalate anomalies to Meridian (Chief Science Officer)".

## Design

Add a **template substitution step** to `compose_instructions()` that processes `{Billet Title}` patterns in standing orders text:

- `{Chief Engineer}` → `LaForge (Chief Engineer)` (if billet filled)
- `{Chief Engineer}` → `Chief Engineer` (if billet vacant — graceful fallback)

The substitution happens **after** all tiers are loaded and concatenated, as a post-processing pass. This means:
- No changes to standing orders `.md` files are required (existing hardcoded references keep working)
- Authors can optionally wrap billet titles in `{}` for dynamic resolution
- New standing orders written by agents (tier 5) can also use templates

**Template syntax:**
- `{Title}` — matches a billet title (case-insensitive lookup)
- Only processes tokens inside `{}` that match a known billet title
- Non-matching `{tokens}` are left unchanged (safe for markdown, code blocks, etc.)

## What This Does NOT Change

- Standing orders `.md` file contents — no changes to existing files (the builder should NOT edit .md files in config/)
- `compose_instructions()` signature — unchanged (uses module-level `_billet_registry`, no new parameters)
- Standing orders tier hierarchy (1–7) — unchanged
- Personality block building — unchanged
- Directive store integration — unchanged
- Skill catalog integration — unchanged
- `_load_file()` caching — unchanged

---

## Section 1: Add billet template resolution function

**File:** `src/probos/cognitive/standing_orders.py`

Add a new function after `clear_cache()` (after line 205) and before `compose_instructions()`:

```python
# Module-level BilletRegistry reference, set at startup (AD-595c)
_billet_registry: Any = None


def set_billet_registry(registry: Any) -> None:
    """Wire the BilletRegistry for template substitution (AD-595c)."""
    global _billet_registry
    _billet_registry = registry


def _resolve_billet_templates(text: str, registry: Any) -> str:
    """Replace {Billet Title} patterns with resolved callsigns.

    - `{Chief Engineer}` → `LaForge (Chief Engineer)` if billet filled
    - `{Chief Engineer}` → `Chief Engineer` if billet vacant or unknown
    - Non-matching `{tokens}` are left unchanged

    Only processes tokens that are 2+ chars and don't contain code-like
    characters (=, (, ), <, >) to avoid mangling code blocks or markdown.
    """
    import re

    def _replace(match: re.Match) -> str:
        token = match.group(1)
        # Skip code-like tokens: contains =, (, ), <, >, |, backtick
        if any(c in token for c in '=()<>|`'):
            return match.group(0)
        # Skip single-char tokens
        if len(token.strip()) < 2:
            return match.group(0)
        holder = registry.resolve(token.strip())
        if holder is None:
            return match.group(0)  # Not a known billet — leave unchanged
        if holder.holder_callsign:
            return f"{holder.holder_callsign} ({holder.title})"
        return holder.title  # Vacant — just the title

    # Match {content} but NOT inside backtick-fenced code blocks
    # Simple approach: process line by line, skip lines inside ``` blocks
    lines = text.split('\n')
    in_code_block = False
    result_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            result_lines.append(line)
            continue
        if in_code_block:
            result_lines.append(line)
            continue
        # Process billet templates outside code blocks
        result_lines.append(re.sub(r'\{([^}]+)\}', _replace, line))
    return '\n'.join(result_lines)
```

---

## Section 2: Integrate into `compose_instructions()`

**File:** `src/probos/cognitive/standing_orders.py`

At the end of `compose_instructions()`, just before the `return` statement (line 303), add template resolution:

Current (line 303):
```python
    return "\n\n---\n\n".join(parts)
```

Change to:
```python
    composed = "\n\n---\n\n".join(parts)

    # AD-595c: Resolve billet templates
    if _billet_registry is not None:
        composed = _resolve_billet_templates(composed, _billet_registry)

    return composed
```

---

## Section 3: Wire BilletRegistry at startup

**File:** `src/probos/startup/finalize.py`

In the finalize phase, immediately after the AD-595a BilletRegistry wiring block (around line 93 after AD-595a is built), add:

```python
    # AD-595c: Wire BilletRegistry into standing orders for template resolution
    if runtime._billet_registry:
        from probos.cognitive.standing_orders import set_billet_registry
        set_billet_registry(runtime._billet_registry)
        logger.info("AD-595c: Standing orders billet templating wired")
```

---

## Section 4: Add cache clearing for billet changes

**File:** `src/probos/cognitive/standing_orders.py`

Update `clear_cache()` to note that billet resolution is not cached.

Current (lines 202–205):
```python
def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated)."""
    _load_file.cache_clear()
    _build_personality_block.cache_clear()
```

Change to:
```python
def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated).

    Note: Billet template resolution (AD-595c) is not cached — it runs
    live on each compose_instructions() call. No cache invalidation needed
    when billets change.
    """
    _load_file.cache_clear()
    _build_personality_block.cache_clear()
```

---

## Section 5: Tests

**File:** `tests/test_ad595c_billet_templating.py` (NEW)

```python
"""Tests for AD-595c: Standing orders billet template resolution."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.cognitive.standing_orders import _resolve_billet_templates


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
        """Vacant billet resolves to just the title."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", None)})
        text = "Report to the {Chief Engineer}."
        result = _resolve_billet_templates(text, reg)
        assert result == "Report to the Chief Engineer."

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

    def test_code_block_not_processed(self):
        """Content inside ``` code blocks is not processed."""
        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})
        text = "Report to {Chief Engineer}.\n```\n{Chief Engineer}\n```\nEnd."
        result = _resolve_billet_templates(text, reg)
        lines = result.split('\n')
        assert lines[0] == "Report to LaForge (Chief Engineer)."
        assert lines[2] == "{Chief Engineer}"  # Inside code block — unchanged
        assert lines[4] == "End."

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
        """Nested braces {{something}} — inner match occurs, outer brace preserved.

        Known limitation: regex matches inner {something}, leaving stray outer braces.
        This is acceptable since standing orders don't use Jinja-style {{}} syntax.
        """
        reg = _make_registry({})
        text = "Template {{variable}} here."
        result = _resolve_billet_templates(text, reg)
        # {variable} is not a known billet, so the inner match is left unchanged
        assert "{{variable}}" in result


# --- Integration with compose_instructions ---

class TestComposeIntegration:

    def test_compose_with_billet_registry(self):
        """compose_instructions resolves billets when registry is wired."""
        from probos.cognitive import standing_orders

        reg = _make_registry({"Chief Engineer": ("Chief Engineer", "LaForge")})

        # Wire registry
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
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad595c_billet_templating.py -v

# Existing standing orders tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "standing_order" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
AD-595c CLOSED. Standing orders billet templating. compose_instructions() now resolves {Billet Title} patterns to current callsigns via BilletRegistry: {Chief Engineer} → LaForge (Chief Engineer). Graceful fallback for vacant billets and unknown tokens. Code blocks excluded from processing. 13 new tests. Depends on AD-595a.
```

### DECISIONS.md
Add entry:
```
**AD-595c: Post-processing template substitution for billet references.** Standing orders `.md` files can use `{Billet Title}` syntax to reference billets dynamically. Resolution happens as a post-processing pass in `compose_instructions()`, after all tiers are concatenated. This means existing hardcoded references ("the Chief Engineer") still work, and the template syntax is opt-in. Code blocks are excluded from processing. No changes to existing standing orders files — this just enables future use. The substitution is not cached (runs live each call) since instructions are composed per-agent per-cycle.
```

### docs/development/roadmap.md
Update AD-595c status from `planned` to `complete` in the sub-AD list.
